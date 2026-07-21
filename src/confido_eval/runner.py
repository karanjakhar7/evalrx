from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.metadata
import json
import time
from datetime import UTC, datetime
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from .config import EvalConfig
from .jsonl import read_models, write_jsonl
from .models import (
    AgentPerformanceResult,
    CallRecord,
    ClassificationResult,
    GateStatus,
    PatientExperienceResult,
    SafetyComplianceResult,
    SourceType,
    StageMetadata,
    StageRecord,
)
from .prompts import load_prompt, prompt_hash, render_user_payload, structured_output_format


STAGE_MODELS: dict[str, type[BaseModel]] = {
    "classification": ClassificationResult,
    "agent_performance": AgentPerformanceResult,
    "patient_experience": PatientExperienceResult,
    "safety_compliance": SafetyComplianceResult,
}


def _litellm_version() -> str:
    try:
        return importlib.metadata.version("litellm")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _is_transient_provider_error(exc: Exception) -> bool:
    name = type(exc).__name__.casefold()
    return any(
        marker in name
        for marker in (
            "ratelimit",
            "timeout",
            "serviceunavailable",
            "internalserver",
            "apiconnection",
        )
    )


def _selected_for_noncritical_audit(config: EvalConfig, call: CallRecord, stage: str) -> bool:
    if stage == "classification":
        return False
    fraction = float(config.raw["audit"].get("noncritical_pass_sample", 0.0))
    digest = hashlib.sha256(
        f"{call.call_id}:{stage}:{config.prompt_version}".encode("utf-8")
    ).digest()
    draw = int.from_bytes(digest[:8], "big") / 2**64
    return draw < fraction


async def _acompletion(**kwargs: Any) -> Any:
    # Lazy import keeps offline commands such as prepare/help from triggering provider lookups.
    import litellm

    return await litellm.acompletion(**kwargs)


def _usage_value(usage: Any, key: str) -> int | None:
    if usage is None:
        return None
    value = getattr(usage, key, None)
    if value is None and isinstance(usage, dict):
        value = usage.get(key)
    return int(value) if isinstance(value, (int, float)) else None


def _normalized_text(value: str) -> str:
    return " ".join(value.split()).casefold()


def validate_evidence(call: CallRecord, result: BaseModel) -> list[str]:
    errors: list[str] = []
    transcript = _normalized_text(call.transcript)
    turn_ids = {turn.turn_id for turn in call.turns}
    duration = call.audio.duration_seconds if call.audio else None

    for field_name in type(result).model_fields:
        value = getattr(result, field_name)
        evidence_items = getattr(value, "evidence", None)
        if evidence_items is None:
            continue
        for evidence in evidence_items:
            if _normalized_text(evidence.quote) not in transcript:
                errors.append(f"{field_name}: quote is not present in normalized transcript")
            if evidence.turn_id is not None and evidence.turn_id not in turn_ids:
                errors.append(f"{field_name}: unknown turn_id {evidence.turn_id}")
            if duration is not None:
                for label, timestamp in (
                    ("start_seconds", evidence.start_seconds),
                    ("end_seconds", evidence.end_seconds),
                ):
                    if timestamp is not None and timestamp > duration + 0.25:
                        errors.append(f"{field_name}: {label} exceeds audio duration")
                if (
                    evidence.start_seconds is not None
                    and evidence.end_seconds is not None
                    and evidence.end_seconds < evidence.start_seconds
                ):
                    errors.append(f"{field_name}: end_seconds precedes start_seconds")
            elif evidence.start_seconds is not None or evidence.end_seconds is not None:
                errors.append(f"{field_name}: timestamps supplied for transcript-only call")

    if isinstance(result, AgentPerformanceResult):
        if result.best_possible_automation_level < result.automation_level_achieved:
            errors.append("best_possible_automation_level is below achieved level")
    if result.call_id != call.call_id:
        errors.append(f"result call_id {result.call_id!r} does not match {call.call_id!r}")
    return errors


def apply_review_rules(
    config: EvalConfig,
    call: CallRecord,
    result: BaseModel,
) -> BaseModel:
    poor_source = call.data_quality.transcript_quality == "poor"
    if isinstance(result, ClassificationResult):
        review = (
            result.requires_human_review
            or result.confidence < config.classification_review_below
            or result.workflow == "unknown"
            or result.counterparty_type == "unknown"
            or result.interaction_type == "unclear"
            or poor_source
        )
        return result.model_copy(update={"requires_human_review": review})
    if isinstance(result, (AgentPerformanceResult, PatientExperienceResult)):
        review = (
            result.requires_human_review
            or result.confidence < config.mandatory_confidence_below
            or poor_source
        )
        return result.model_copy(update={"requires_human_review": review})
    if isinstance(result, SafetyComplianceResult):
        gates = [
            result.privacy_and_identity,
            result.clinical_safety,
            result.fabrication_or_false_confirmation,
            result.financial_safety,
            result.ai_transparency,
            result.call_control,
        ]
        blocked = any(gate.status in {GateStatus.FAIL, GateStatus.UNCERTAIN} for gate in gates)
        return result.model_copy(
            update={
                "requires_human_review": result.requires_human_review or blocked or poor_source,
                "production_pass": result.production_pass and not blocked,
            }
        )
    return result


def _messages(
    config: EvalConfig,
    stage: str,
    call: CallRecord,
    classification: ClassificationResult | None,
) -> list[dict[str, Any]]:
    prompt = load_prompt(config, stage)
    user_text = render_user_payload(call, classification)
    content: str | list[dict[str, Any]] = user_text
    if call.source_type == SourceType.AUDIO and stage != "classification":
        if call.audio is None:
            raise ValueError(f"Audio metadata missing for {call.call_id}")
        wav_path = config.project_root / call.audio.wav_path
        encoded = base64.b64encode(wav_path.read_bytes()).decode("ascii")
        content = [
            {"type": "text", "text": user_text},
            {"type": "input_audio", "input_audio": {"data": encoded, "format": "wav"}},
        ]
    return [
        {"role": "system", "content": prompt},
        {"role": "user", "content": content},
    ]


async def evaluate_stage_call(
    config: EvalConfig,
    stage: str,
    call: CallRecord,
    classification: ClassificationResult | None,
    *,
    model_override: str | None = None,
) -> StageRecord:
    """Evaluate a single call for one stage with no filesystem side effects.

    This is the canonical evaluation path: build messages, call the provider with
    the strict schema, validate locally, and assemble a ``StageRecord``. It does
    not read cached records or persist anything, so it is safe to use from
    stateless contexts such as the HTTP service. Callers that need resume and
    persistence should use :func:`run_stage_call`, which wraps this function.
    """
    prompt = load_prompt(config, stage)
    prompt_sha = prompt_hash(prompt)
    model_name = model_override or config.model_by_stage[stage]

    response_model = STAGE_MODELS[stage]
    attempts = 0
    started_iso = datetime.now(UTC).isoformat()
    started = time.perf_counter()
    raw_content: str | None = None
    last_errors: list[str] = []
    response: Any = None

    for attempt in range(config.max_retries + 1):
        attempts = attempt + 1
        retryable = True
        try:
            response = await _acompletion(
                model=model_name,
                messages=_messages(config, stage, call, classification),
                response_format=structured_output_format(
                    response_model, stage, config.prompt_version
                ),
                temperature=config.temperature,
                max_tokens=config.max_tokens(stage),
                timeout=180,
            )
            raw_content = response.choices[0].message.content
            if not isinstance(raw_content, str):
                raise ValueError("Model response did not contain string content")
            parsed = response_model.model_validate_json(raw_content)
            parsed = apply_review_rules(config, call, parsed)
            evidence_errors = validate_evidence(call, parsed)
            review_reasons: list[str] = []
            if bool(getattr(parsed, "requires_human_review", False)):
                review_reasons.append("judge_or_mandatory_rule")
            if evidence_errors:
                review_reasons.append("local_validation_error")
            audit_sampled = not review_reasons and _selected_for_noncritical_audit(
                config, call, stage
            )
            if audit_sampled:
                review_reasons.append("deterministic_noncritical_audit_sample")
            record = StageRecord(
                metadata=StageMetadata(
                    call_id=call.call_id,
                    stage=stage,
                    model=model_name,
                    litellm_version=_litellm_version(),
                    prompt_version=config.prompt_version,
                    prompt_sha256=prompt_sha,
                    source_sha256=call.source_sha256,
                    started_at=started_iso,
                    latency_seconds=round(time.perf_counter() - started, 3),
                    prompt_tokens=_usage_value(getattr(response, "usage", None), "prompt_tokens"),
                    completion_tokens=_usage_value(
                        getattr(response, "usage", None), "completion_tokens"
                    ),
                    total_tokens=_usage_value(getattr(response, "usage", None), "total_tokens"),
                    response_cost=getattr(response, "_hidden_params", {}).get("response_cost"),
                    attempts=attempts,
                    validation_status="invalid" if evidence_errors else "valid",
                    validation_errors=evidence_errors,
                ),
                result=parsed.model_dump(mode="json"),
                raw_response=raw_content,
                requires_human_review=(
                    bool(getattr(parsed, "requires_human_review", False))
                    or bool(evidence_errors)
                    or audit_sampled
                ),
                review_reasons=review_reasons,
            )
            return record
        except (ValidationError, ValueError, json.JSONDecodeError) as exc:
            last_errors = [f"{type(exc).__name__}: {exc}"]
        except Exception as exc:  # LiteLLM maps provider errors to shared exception types.
            last_errors = [f"{type(exc).__name__}: {exc}"]
            retryable = _is_transient_provider_error(exc)
        if retryable and attempt < config.max_retries:
            await asyncio.sleep(2**attempt)
        else:
            break

    record = StageRecord(
        metadata=StageMetadata(
            call_id=call.call_id,
            stage=stage,
            model=model_name,
            litellm_version=_litellm_version(),
            prompt_version=config.prompt_version,
            prompt_sha256=prompt_sha,
            source_sha256=call.source_sha256,
            started_at=started_iso,
            latency_seconds=round(time.perf_counter() - started, 3),
            attempts=attempts,
            validation_status="failed",
            validation_errors=last_errors,
        ),
        result=None,
        raw_response=raw_content,
        requires_human_review=True,
        review_reasons=["stage_failed"],
    )
    return record


async def run_stage_call(
    config: EvalConfig,
    run_id: str,
    stage: str,
    call: CallRecord,
    classification: ClassificationResult | None,
    *,
    resume: bool,
    model_override: str | None = None,
) -> StageRecord:
    """Evaluate a stage and persist the record under ``runs/<run_id>/stages``.

    Reuses a valid matching cached record when ``resume`` is set, otherwise
    delegates to :func:`evaluate_stage_call` and writes the result to disk.
    """
    stage_dir = config.path("runs") / run_id / "stages" / stage
    stage_dir.mkdir(parents=True, exist_ok=True)
    record_path = stage_dir / f"{call.call_id}.json"
    model_name = model_override or config.model_by_stage[stage]

    if resume and record_path.exists():
        existing = StageRecord.model_validate_json(record_path.read_text())
        meta = existing.metadata
        if (
            meta.model == model_name
            and meta.prompt_sha256 == prompt_hash(load_prompt(config, stage))
            and meta.source_sha256 == call.source_sha256
            and meta.validation_status == "valid"
        ):
            return existing

    record = await evaluate_stage_call(
        config,
        stage,
        call,
        classification,
        model_override=model_override,
    )
    record_path.write_text(record.model_dump_json(indent=2))
    return record


def _load_classifications(config: EvalConfig, run_id: str) -> dict[str, ClassificationResult]:
    path = config.path("runs") / run_id / "classification.jsonl"
    results: dict[str, ClassificationResult] = {}
    for record in read_models(path, StageRecord):
        if record.result:
            parsed = ClassificationResult.model_validate(record.result)
            results[parsed.call_id] = parsed
    return results


async def run_stage(
    config: EvalConfig,
    run_id: str,
    stage: str,
    calls: list[CallRecord],
    *,
    resume: bool = False,
    model_override: str | None = None,
) -> list[StageRecord]:
    if stage not in STAGE_MODELS:
        raise ValueError(f"Unknown stage: {stage}")
    classifications = {} if stage == "classification" else _load_classifications(config, run_id)
    if stage != "classification":
        missing = [call.call_id for call in calls if call.call_id not in classifications]
        if missing:
            raise ValueError(f"Missing classifications for {len(missing)} calls: {missing[:5]}")

    semaphore = asyncio.Semaphore(config.concurrency)

    async def bounded(call: CallRecord) -> StageRecord:
        async with semaphore:
            return await run_stage_call(
                config,
                run_id,
                stage,
                call,
                classifications.get(call.call_id),
                resume=resume,
                model_override=model_override,
            )

    records = await asyncio.gather(*(bounded(call) for call in calls))
    output = config.path("runs") / run_id / f"{stage}.jsonl"
    write_jsonl(output, records)
    return list(records)


async def run_judges(
    config: EvalConfig,
    run_id: str,
    calls: list[CallRecord],
    *,
    resume: bool = False,
    stage_filter: str | None = None,
    model_override: str | None = None,
) -> dict[str, list[StageRecord]]:
    stages = ["agent_performance", "patient_experience", "safety_compliance"]
    if stage_filter:
        if stage_filter not in stages:
            raise ValueError(f"Judge stage must be one of {stages}")
        stages = [stage_filter]
    classifications = _load_classifications(config, run_id)
    missing = [call.call_id for call in calls if call.call_id not in classifications]
    if missing:
        raise ValueError(f"Missing classifications for {len(missing)} calls: {missing[:5]}")

    semaphore = asyncio.Semaphore(config.concurrency)

    async def bounded(stage: str, call: CallRecord) -> StageRecord:
        async with semaphore:
            return await run_stage_call(
                config,
                run_id,
                stage,
                call,
                classifications[call.call_id],
                resume=resume,
                model_override=model_override,
            )

    work = [(stage, call) for stage in stages for call in calls]
    records = await asyncio.gather(*(bounded(stage, call) for stage, call in work))
    outputs: dict[str, list[StageRecord]] = {stage: [] for stage in stages}
    for (stage, _call), record in zip(work, records, strict=True):
        outputs[stage].append(record)
    for stage, stage_records in outputs.items():
        write_jsonl(config.path("runs") / run_id / f"{stage}.jsonl", stage_records)
    return outputs


def load_normalized_calls(config: EvalConfig) -> list[CallRecord]:
    return read_models(config.path("normalized"), CallRecord)


def load_dotenv_for_runtime(config: EvalConfig) -> None:
    load_dotenv(config.project_root / ".env")
