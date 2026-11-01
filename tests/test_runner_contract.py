from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from evalrx.models import ClassificationResult
from evalrx.normalize import prepare_dataset
from evalrx.runner import _messages, run_stage_call


def _classification(call_id: str) -> ClassificationResult:
    return ClassificationResult(
        call_id=call_id,
        direction="inbound",
        workflow="medical_records",
        interaction_type="live_conversation",
        counterparty_type="patient",
        primary_intent="request_medical_records",
        final_disposition="information_collected",
        transcript_quality="good",
        confidence=0.92,
        requires_human_review=False,
        reasoning_summary="The caller requests medical records.",
    )


def _response(result: ClassificationResult):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=result.model_dump_json()))],
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        _hidden_params={"response_cost": 0.001},
    )


@pytest.mark.asyncio
async def test_structured_classification_contract(monkeypatch, dataset_config) -> None:
    config = dataset_config
    call = prepare_dataset(config)[0]
    result = _classification(call.call_id)

    async def fake_completion(**kwargs):
        assert kwargs["model"] == "gemini/gemini-3.1-flash-lite"
        assert kwargs["response_format"]["type"] == "json_schema"
        assert kwargs["response_format"]["json_schema"]["strict"] is True
        return _response(result)

    monkeypatch.setattr("evalrx.runner._acompletion", fake_completion)
    record = await run_stage_call(
        config,
        "contract",
        "classification",
        call,
        None,
        resume=False,
    )
    assert record.metadata.validation_status == "valid"
    assert record.metadata.total_tokens == 30
    assert record.metadata.litellm_version != ""


@pytest.mark.asyncio
async def test_invalid_json_and_rate_limit_retry(monkeypatch, dataset_config) -> None:
    config = dataset_config
    call = prepare_dataset(config)[0]
    result = _classification(call.call_id)
    attempts = 0

    class RateLimitError(Exception):
        pass

    async def fake_completion(**_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RateLimitError("try later")
        if attempts == 2:
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="not-json"))],
                usage=None,
                _hidden_params={},
            )
        return _response(result)

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr("evalrx.runner._acompletion", fake_completion)
    monkeypatch.setattr("evalrx.runner.asyncio.sleep", no_sleep)
    record = await run_stage_call(config, "retry", "classification", call, None, resume=False)
    assert attempts == 3
    assert record.metadata.validation_status == "valid"
    assert record.metadata.attempts == 3


@pytest.mark.asyncio
async def test_auth_error_is_retained_without_retry(monkeypatch, dataset_config) -> None:
    config = dataset_config
    call = prepare_dataset(config)[0]
    attempts = 0

    class AuthenticationError(Exception):
        pass

    async def fake_completion(**_kwargs):
        nonlocal attempts
        attempts += 1
        raise AuthenticationError("invalid credential")

    monkeypatch.setattr("evalrx.runner._acompletion", fake_completion)
    record = await run_stage_call(config, "auth", "classification", call, None, resume=False)
    assert attempts == 1
    assert record.metadata.validation_status == "failed"
    assert record.requires_human_review is True
    assert "AuthenticationError" in record.metadata.validation_errors[0]


@pytest.mark.asyncio
async def test_valid_result_is_resumable(monkeypatch, dataset_config) -> None:
    config = dataset_config
    call = prepare_dataset(config)[0]
    result = _classification(call.call_id)

    async def fake_completion(**_kwargs):
        return _response(result)

    monkeypatch.setattr("evalrx.runner._acompletion", fake_completion)
    first = await run_stage_call(config, "resume", "classification", call, None, resume=False)

    async def should_not_run(**_kwargs):
        raise AssertionError("provider called despite reusable matching result")

    monkeypatch.setattr("evalrx.runner._acompletion", should_not_run)
    second = await run_stage_call(config, "resume", "classification", call, None, resume=True)
    assert second == first


def test_audio_judge_payload_contains_wav_and_timestamped_transcript(dataset_config) -> None:
    config = dataset_config
    audio_call = next(call for call in prepare_dataset(config) if call.source_type.value == "audio")
    messages = _messages(config, "agent_performance", audio_call, None)
    content = messages[1]["content"]
    assert isinstance(content, list)
    assert content[1]["type"] == "input_audio"
    assert content[1]["input_audio"]["format"] == "wav"
    assert content[1]["input_audio"]["data"]
    assert "start_seconds" in content[0]["text"]


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_redacted_classification_smoke(dataset_config) -> None:
    if os.environ.get("EVALRX_LIVE_SMOKE") != "1" or not os.environ.get("GEMINI_API_KEY"):
        pytest.skip("set EVALRX_LIVE_SMOKE=1 and GEMINI_API_KEY to run")
    config = dataset_config
    call = prepare_dataset(config)[0]
    record = await run_stage_call(config, "live-smoke", "classification", call, None, resume=False)
    assert record.metadata.validation_status == "valid"


def test_classify_selects_calibration_for_any_dataset_size(monkeypatch, dataset_config):
    import json
    from typer.testing import CliRunner
    from evalrx.cli import app

    prepare_dataset(dataset_config)
    monkeypatch.setattr("evalrx.cli._config", lambda: dataset_config)
    monkeypatch.setattr("evalrx.cli._require_gemini_key", lambda _config: None)

    async def fake_completion(**kwargs):
        payload = json.loads(kwargs["messages"][1]["content"].split("\n\n", 1)[1])
        return _response(_classification(payload["call"]["call_id"]))

    monkeypatch.setattr("evalrx.runner._acompletion", fake_completion)
    result = CliRunner().invoke(app, ["classify", "--run-id", "small"])
    assert result.exit_code == 0, result.output
    manifest = json.loads(
        (dataset_config.path("runs") / "small" / "calibration_manifest.json").read_text()
    )
    assert len(manifest["transcript_development"]) == 2
    assert len(manifest["audio_development"]) == 2
