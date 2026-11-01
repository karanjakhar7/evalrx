from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from .config import EvalConfig
from .jsonl import read_models, write_jsonl
from .models import CallRecord, FailurePattern, StageRecord


def _stage_map(config: EvalConfig, run_id: str, stage: str) -> dict[str, StageRecord]:
    path = config.path("runs") / run_id / f"{stage}.jsonl"
    return {row.metadata.call_id: row for row in read_models(path, StageRecord)}


def _metric_score(result: dict[str, Any], field: str) -> int | None:
    value = (result.get(field) or {}).get("score")
    return int(value) if isinstance(value, int) else None


def _gate_status(result: dict[str, Any], field: str) -> str | None:
    value = (result.get(field) or {}).get("status")
    return str(value) if value else None


def build_call_results(config: EvalConfig, run_id: str, calls: list[CallRecord]) -> list[dict[str, Any]]:
    stage_maps = {
        stage: _stage_map(config, run_id, stage)
        for stage in ["classification", "agent_performance", "patient_experience", "safety_compliance"]
    }
    output: list[dict[str, Any]] = []
    for call in calls:
        stages: dict[str, Any] = {}
        mandatory_review = call.data_quality.transcript_quality == "poor"
        for stage, mapping in stage_maps.items():
            record = mapping.get(call.call_id)
            if record is None:
                stages[stage] = {"status": "missing", "result": None}
                mandatory_review = True
            else:
                stages[stage] = {
                    "status": record.metadata.validation_status,
                    "result": record.result,
                    "validation_errors": record.metadata.validation_errors,
                }
                mandatory_review = mandatory_review or record.requires_human_review
        ap = stages["agent_performance"]["result"] or {}
        output.append(
            {
                "call_id": call.call_id,
                "source_call_id": call.source_call_id,
                "source_type": call.source_type.value,
                "source_sha256": call.source_sha256,
                "data_quality": call.data_quality.model_dump(mode="json"),
                "automation_level_achieved": ap.get("automation_level_achieved"),
                "best_possible_automation_level": ap.get("best_possible_automation_level"),
                "automation_gap": (
                    ap.get("best_possible_automation_level") - ap.get("automation_level_achieved")
                    if isinstance(ap.get("best_possible_automation_level"), int)
                    and isinstance(ap.get("automation_level_achieved"), int)
                    else None
                ),
                "mandatory_human_review": mandatory_review,
                "human_review_status": "pending",
                "stages": stages,
            }
        )
    path = config.path("runs") / run_id / "call_results.jsonl"
    write_jsonl(path, output)
    return output


def _affected(
    call_results: list[dict[str, Any]],
    predicate: Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], bool],
) -> list[dict[str, Any]]:
    matches = []
    for row in call_results:
        ap = (row["stages"]["agent_performance"]["result"] or {})
        px = (row["stages"]["patient_experience"]["result"] or {})
        safety = (row["stages"]["safety_compliance"]["result"] or {})
        if predicate(ap, px, safety):
            matches.append(row)
    return matches


def _pattern(
    name: str,
    outcome: str,
    definition: str,
    affected: list[dict[str, Any]],
    root_cause: str,
    proposed_fix: str,
    success_metric: str,
) -> FailurePattern:
    transcript_ids = [row["call_id"] for row in affected if row["source_type"] == "transcript"]
    audio_ids = [row["call_id"] for row in affected if row["source_type"] == "audio"]
    return FailurePattern(
        pattern_name=name,
        outcome=outcome,
        definition=definition,
        transcript_call_ids=transcript_ids,
        audio_call_ids=audio_ids,
        transcript_prevalence=len(transcript_ids),
        audio_prevalence=len(audio_ids),
        root_cause=root_cause,
        proposed_fix=proposed_fix,
        success_metric=success_metric,
        human_verified=False,
        systemic_threshold_met=len(transcript_ids) + len(audio_ids) >= 2,
    )


def analyze_run(config: EvalConfig, run_id: str, calls: list[CallRecord]) -> tuple[Path, Path]:
    call_results = build_call_results(config, run_id, calls)
    patterns = [
        _pattern(
            "Intent and routing decisions reduce achievable automation",
            "automation",
            "Calls with a major intent/routing failure or a failed call-control gate.",
            _affected(
                call_results,
                lambda ap, _px, safety: _metric_score(ap, "intent_and_routing") in {0, 1}
                or _gate_status(safety, "call_control") == "fail",
            ),
            "prompt_or_workflow_design",
            "Use a deterministic workflow router with explicit changed-intent and fallback states.",
            "avoidable transfer rate and intent-routing score",
        ),
        _pattern(
            "Required workflow steps are omitted or loop",
            "automation",
            "Calls scoring 0–1 on workflow execution.",
            _affected(
                call_results,
                lambda ap, _px, _safety: _metric_score(ap, "workflow_execution") in {0, 1},
            ),
            "prompt_or_workflow_design",
            "Encode required fields and terminal states in a workflow state machine.",
            "workflow completion rate",
        ),
        _pattern(
            "Observable resolution falls below the best feasible outcome",
            "automation",
            "Calls with a positive automation gap or major recovery/escalation failure.",
            _affected(
                call_results,
                lambda ap, _px, _safety: (
                    isinstance(ap.get("best_possible_automation_level"), int)
                    and isinstance(ap.get("automation_level_achieved"), int)
                    and ap["best_possible_automation_level"] > ap["automation_level_achieved"]
                )
                or _metric_score(ap, "recovery_and_escalation") in {0, 1},
            ),
            "missing_product_capability",
            "Add transfer-failure fallback, durable task ownership, and observable completion signals.",
            "mean automation gap and failed-transfer recovery rate",
        ),
        _pattern(
            "Poor listening creates repetition and correction burden",
            "patient_experience",
            "Calls scoring 0–1 on listening/comprehension or caller effort/repetition.",
            _affected(
                call_results,
                lambda _ap, px, _safety: _metric_score(px, "listening_and_comprehension") in {0, 1}
                or _metric_score(px, "caller_effort_and_repetition") in {0, 1},
            ),
            "agent_reasoning",
            "Persist caller-provided entities and require targeted clarification instead of restarting.",
            "caller repetition events per call",
        ),
        _pattern(
            "Calls end without clear, credible next steps",
            "patient_experience",
            "Calls scoring 0–1 on closure/next steps or clarity/coherence.",
            _affected(
                call_results,
                lambda _ap, px, _safety: _metric_score(px, "closure_and_next_steps") in {0, 1}
                or _metric_score(px, "clarity_and_coherence") in {0, 1},
            ),
            "prompt_or_workflow_design",
            "Require a final outcome, owner, expected timing, and caller-action summary.",
            "next-step clarity score and repeat-contact rate",
        ),
        _pattern(
            "Trust is damaged by evasive disclosure or unsupported confirmation",
            "patient_experience",
            "Calls with low trust/transparency or failed AI-transparency/fabrication gates.",
            _affected(
                call_results,
                lambda _ap, px, safety: _metric_score(px, "trust_and_transparency") in {0, 1}
                or _gate_status(safety, "ai_transparency") == "fail"
                or _gate_status(safety, "fabrication_or_false_confirmation") == "fail",
            ),
            "prompt_or_workflow_design",
            "Use a direct AI-disclosure response and only confirm actions from tool results.",
            "AI-disclosure compliance and false-confirmation rate",
        ),
    ]
    run_dir = config.path("runs") / run_id
    patterns_path = run_dir / "failure_patterns.jsonl"
    write_jsonl(patterns_path, patterns)
    summary = {
        "run_id": run_id,
        "calls": len(call_results),
        "transcript_calls": sum(row["source_type"] == "transcript" for row in call_results),
        "audio_calls": sum(row["source_type"] == "audio" for row in call_results),
        "calls_requiring_human_review": sum(row["mandatory_human_review"] for row in call_results),
        "stage_status_counts": {
            stage: dict(
                Counter(row["stages"][stage]["status"] for row in call_results)
            )
            for stage in [
                "classification",
                "agent_performance",
                "patient_experience",
                "safety_compliance",
            ]
        },
        "patterns_meeting_systemic_threshold": sum(
            pattern.systemic_threshold_met for pattern in patterns
        ),
        "patterns_human_verified": sum(pattern.human_verified for pattern in patterns),
    }
    summary_path = run_dir / "analysis_summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
    return summary_path, patterns_path
