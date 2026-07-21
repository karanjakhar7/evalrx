from __future__ import annotations

import pytest
from pydantic import ValidationError

from confido_eval.config import load_config
from confido_eval.models import (
    AgentPerformanceResult,
    Evidence,
    MetricResult,
    ScoreStatus,
)
from confido_eval.normalize import prepare_dataset
from confido_eval.runner import apply_review_rules, validate_evidence


def metric(score: int = 3, quote: str = "Hello") -> MetricResult:
    return MetricResult(
        status=ScoreStatus.SCORED,
        score=score,
        evidence=[Evidence(turn_id=1, quote=quote)],
        reasoning_summary="Observable evidence supports the score.",
    )


def test_metric_requires_null_for_non_scored_status() -> None:
    with pytest.raises(ValidationError):
        MetricResult(
            status=ScoreStatus.UNCERTAIN,
            score=1,
            reasoning_summary="Uncertain.",
        )


def test_evidence_and_automation_validation() -> None:
    config = load_config()
    call = prepare_dataset(config)[0]
    first_quote = call.turns[0].text
    result = AgentPerformanceResult(
        call_id=call.call_id,
        identity_and_authorization=metric(3, first_quote),
        intent_and_routing=metric(3, first_quote),
        information_capture_and_groundedness=metric(3, first_quote),
        workflow_execution=metric(3, first_quote),
        resolution_and_automation=metric(3, first_quote),
        recovery_and_escalation=metric(3, first_quote),
        automation_level_achieved=3,
        best_possible_automation_level=2,
        primary_root_cause="insufficient_evidence",
        confidence=0.9,
        requires_human_review=False,
    )
    errors = validate_evidence(call, result)
    assert "best_possible_automation_level is below achieved level" in errors

    unsupported = result.model_copy(
        update={"identity_and_authorization": metric(3, "quote absent from source")}
    )
    errors = validate_evidence(call, unsupported)
    assert any("quote is not present" in error for error in errors)


def test_poor_source_forces_review() -> None:
    config = load_config()
    call = prepare_dataset(config)[50]
    call = call.model_copy(
        update={
            "data_quality": call.data_quality.model_copy(
                update={"transcript_quality": "poor"}
            )
        }
    )
    result = AgentPerformanceResult(
        call_id=call.call_id,
        identity_and_authorization=metric(),
        intent_and_routing=metric(),
        information_capture_and_groundedness=metric(),
        workflow_execution=metric(),
        resolution_and_automation=metric(),
        recovery_and_escalation=metric(),
        automation_level_achieved=2,
        best_possible_automation_level=2,
        primary_root_cause="insufficient_evidence",
        confidence=0.95,
        requires_human_review=False,
    )
    reviewed = apply_review_rules(config, call, result)
    assert reviewed.requires_human_review is True
