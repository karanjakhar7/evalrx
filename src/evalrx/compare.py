from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

from .calibration import AP_FIELDS, PX_FIELDS, SAFETY_FIELDS
from .config import EvalConfig
from .jsonl import read_models, write_jsonl
from .models import Disagreement, HumanLabel, StageRecord


def wilson_interval(successes: int, total: int, z: float = 1.96) -> tuple[float, float] | None:
    if total == 0:
        return None
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt((p * (1 - p) + z * z / (4 * total)) / total) / denominator
    return round(max(0.0, centre - margin), 4), round(min(1.0, centre + margin), 4)


def weighted_kappa(pairs: list[tuple[int, int]], categories: int = 4) -> float | None:
    if not pairs:
        return None
    total = len(pairs)
    observed = 0.0
    human_counts = Counter(human for _, human in pairs)
    judge_counts = Counter(judge for judge, _ in pairs)
    for judge, human in pairs:
        observed += ((judge - human) / (categories - 1)) ** 2
    observed /= total
    expected = 0.0
    for judge in range(categories):
        for human in range(categories):
            weight = ((judge - human) / (categories - 1)) ** 2
            expected += weight * judge_counts[judge] * human_counts[human] / (total * total)
    if expected == 0:
        return 1.0 if observed == 0 else None
    return round(1 - observed / expected, 4)


def _stage_map(config: EvalConfig, run_id: str, stage: str) -> dict[str, dict[str, Any]]:
    path = config.path("runs") / run_id / f"{stage}.jsonl"
    return {
        record.metadata.call_id: record.result
        for record in read_models(path, StageRecord)
        if record.result
    }


def compare_run(config: EvalConfig, run_id: str) -> tuple[Path, Path]:
    labels_path = config.path("runs") / run_id / "human_labels.jsonl"
    labels = read_models(labels_path, HumanLabel)
    complete = [label for label in labels if label.review_status == "complete"]
    stages = {
        stage: _stage_map(config, run_id, stage)
        for stage in ["classification", "agent_performance", "patient_experience", "safety_compliance"]
    }
    disagreements: list[Disagreement] = []
    score_pairs: list[tuple[int, int]] = []
    exact = 0
    within_one = 0
    automation_pairs: list[tuple[int, int]] = []
    automation_exact = 0

    for label in complete:
        call_id = label.call_id
        for stage, fields, human_scores in [
            ("agent_performance", AP_FIELDS, label.agent_performance_scores),
            ("patient_experience", PX_FIELDS, label.patient_experience_scores),
        ]:
            result = stages[stage].get(call_id) or {}
            for field in fields:
                human = human_scores.get(field)
                judge = (result.get(field) or {}).get("score")
                if human is None or judge is None:
                    continue
                pair = int(judge), int(human)
                score_pairs.append(pair)
                exact += int(pair[0] == pair[1])
                within_one += int(abs(pair[0] - pair[1]) <= 1)
                if pair[0] != pair[1]:
                    disagreements.append(
                        Disagreement(
                            call_id=call_id,
                            field=f"{stage}.{field}",
                            judge_value=pair[0],
                            human_value=pair[1],
                        )
                    )

        agent_result = stages["agent_performance"].get(call_id) or {}
        for field, human in [
            ("automation_level_achieved", label.automation_level_achieved),
            ("best_possible_automation_level", label.best_possible_automation_level),
        ]:
            judge = agent_result.get(field)
            if human is None or judge is None:
                continue
            pair = int(judge), int(human)
            automation_pairs.append(pair)
            automation_exact += int(pair[0] == pair[1])
            if pair[0] != pair[1]:
                disagreements.append(
                    Disagreement(
                        call_id=call_id,
                        field=f"agent_performance.{field}",
                        judge_value=pair[0],
                        human_value=pair[1],
                    )
                )

    critical_tp = critical_fp = critical_fn = 0
    for label in complete:
        result = stages["safety_compliance"].get(label.call_id) or {}
        for field in SAFETY_FIELDS:
            human = label.safety_gate_statuses.get(field)
            judge = (result.get(field) or {}).get("status")
            if not human or not judge:
                continue
            human_positive = human in {"fail", "uncertain"}
            judge_positive = judge in {"fail", "uncertain"}
            critical_tp += int(human_positive and judge_positive)
            critical_fp += int(not human_positive and judge_positive)
            critical_fn += int(human_positive and not judge_positive)
            if human != judge:
                disagreements.append(
                    Disagreement(
                        call_id=label.call_id,
                        field=f"safety_compliance.{field}",
                        judge_value=judge,
                        human_value=human,
                    )
                )

    total = len(score_pairs)
    automation_total = len(automation_pairs)
    precision_denominator = critical_tp + critical_fp
    recall_denominator = critical_tp + critical_fn
    judge_records = [
        record
        for stage in ["agent_performance", "patient_experience", "safety_compliance"]
        for record in read_models(config.path("runs") / run_id / f"{stage}.jsonl", StageRecord)
        if record.result is not None
    ]
    evidence_valid = sum(
        record.metadata.validation_status == "valid" for record in judge_records
    )
    evidence_total = len(judge_records)
    all_human_complete = bool(labels) and len(complete) == len(labels)
    summary = {
        "run_id": run_id,
        "status": "complete" if all_human_complete else "pending_human_review",
        "human_labels_total": len(labels),
        "human_labels_complete": len(complete),
        "score_pairs": total,
        "exact_agreement": round(exact / total, 4) if total else None,
        "exact_agreement_wilson_95": wilson_interval(exact, total),
        "within_one_agreement": round(within_one / total, 4) if total else None,
        "within_one_wilson_95": wilson_interval(within_one, total),
        "quadratic_weighted_kappa": weighted_kappa(score_pairs),
        "automation_level_pairs": automation_total,
        "automation_level_agreement": (
            round(automation_exact / automation_total, 4) if automation_total else None
        ),
        "automation_level_agreement_wilson_95": wilson_interval(
            automation_exact, automation_total
        ),
        "critical_gate_precision": (
            round(critical_tp / precision_denominator, 4) if precision_denominator else None
        ),
        "critical_gate_precision_wilson_95": wilson_interval(
            critical_tp, precision_denominator
        ),
        "critical_gate_recall": (
            round(critical_tp / recall_denominator, 4) if recall_denominator else None
        ),
        "critical_gate_recall_wilson_95": wilson_interval(critical_tp, recall_denominator),
        "evidence_validity": (
            round(evidence_valid / evidence_total, 4) if evidence_total else None
        ),
        "evidence_validity_wilson_95": wilson_interval(evidence_valid, evidence_total),
        "evidence_records": evidence_total,
        "disagreement_count": len(disagreements),
        "limitation": "Metrics remain pending until user-reviewed labels are imported."
        if not all_human_complete
        else "Small calibration samples produce wide confidence intervals.",
    }
    run_dir = config.path("runs") / run_id
    summary_path = run_dir / "comparison.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
    disagreements_path = run_dir / "disagreements.jsonl"
    write_jsonl(disagreements_path, disagreements)
    return summary_path, disagreements_path
