"""Stateless single-call evaluation for interactive callers (e.g. an HTTP API).

Unlike the CLI batch commands, nothing here reads or writes the run filesystem.
A raw labeled transcript is normalized into a :class:`CallRecord` in memory and
evaluated through the same canonical stage path used by the pipeline
(:func:`confido_eval.runner.evaluate_stage_call`), so results match a batch run
of the same call.
"""

from __future__ import annotations

import asyncio
from typing import Any

from .config import EvalConfig
from .models import (
    CallRecord,
    ClassificationResult,
    DataQuality,
    SourceType,
    StageRecord,
)
from .normalize import parse_labeled_transcript, sha256_bytes, transcript_quality
from .runner import evaluate_stage_call

JUDGE_STAGES = ("agent_performance", "patient_experience", "safety_compliance")

_ANONYMIZATION_NOTE = (
    "Source may contain intentional anonymization cuts; never score them as agent failures."
)


class TranscriptError(ValueError):
    """Raised when a submitted transcript cannot be normalized into a call."""


def build_transcript_call_record(
    transcript: str,
    call_id: str = "api_request",
) -> CallRecord:
    """Normalize a labeled ``Agent:``/``User:`` transcript into a ``CallRecord``.

    Mirrors :func:`confido_eval.normalize.normalize_workbook` for a single
    transcript so an ad-hoc call is represented exactly like a corpus call.
    """
    text = (transcript or "").strip()
    if not text:
        raise TranscriptError("transcript is empty")
    turns = parse_labeled_transcript(text)
    if not turns:
        raise TranscriptError("no turns parsed from transcript")

    notes = [_ANONYMIZATION_NOTE]
    if len(text) < 500:
        notes.append("Short source transcript; review for intentional cut or limited interaction.")

    return CallRecord(
        call_id=call_id,
        source_call_id=call_id,
        source_type=SourceType.TRANSCRIPT,
        source_path="api://transcript",
        source_sha256=sha256_bytes(text.encode("utf-8")),
        transcript=text,
        turns=turns,
        data_quality=DataQuality(
            transcript_quality=transcript_quality(text),
            redaction_present=True,
            truncated=True,
            missing_operational_context=True,
            notes=notes,
        ),
        role_mapping={"Agent": "agent", "User": "counterparty"},
        role_mapping_confidence=1.0,
    )


def _stage_view(record: StageRecord) -> dict[str, Any]:
    return {
        "validation_status": record.metadata.validation_status,
        "requires_human_review": record.requires_human_review,
        "review_reasons": record.review_reasons,
        "validation_errors": record.metadata.validation_errors,
        "model": record.metadata.model,
        "result": record.result,
    }


async def evaluate_transcript(
    config: EvalConfig,
    transcript: str,
    call_id: str = "api_request",
) -> dict[str, Any]:
    """Run classification then the three judges on one transcript, in memory.

    Classification runs first because the judges consume it as context; the three
    judges then run concurrently under the configured concurrency limit.
    """
    call = build_transcript_call_record(transcript, call_id=call_id)

    classification = await evaluate_stage_call(config, "classification", call, None)
    parsed_classification: ClassificationResult | None = None
    if classification.result is not None:
        parsed_classification = ClassificationResult.model_validate(classification.result)

    semaphore = asyncio.Semaphore(config.concurrency)

    async def bounded(stage: str) -> StageRecord:
        async with semaphore:
            return await evaluate_stage_call(config, stage, call, parsed_classification)

    judge_records = await asyncio.gather(*(bounded(stage) for stage in JUDGE_STAGES))

    stages = {"classification": _stage_view(classification)}
    for stage, record in zip(JUDGE_STAGES, judge_records, strict=True):
        stages[stage] = _stage_view(record)

    return {
        "call": {
            "call_id": call.call_id,
            "source_type": call.source_type.value,
            "source_sha256": call.source_sha256,
            "data_quality": call.data_quality.model_dump(mode="json"),
        },
        "stages": stages,
        "run": {
            "models": config.model_by_stage,
            "prompt_version": config.prompt_version,
        },
    }
