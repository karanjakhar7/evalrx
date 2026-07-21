from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .config import EvalConfig
from .jsonl import read_jsonl
from .models import (
    AgentPerformanceResult,
    ClassificationResult,
    PatientExperienceResult,
    SafetyComplianceResult,
)
from .prompts import STAGE_FILES, load_prompt


def _load_json(path: Path, default: Any) -> Any:
    return json.loads(path.read_text()) if path.exists() else default


def _score_scale() -> str:
    return """| Score | Anchor |
|---:|---|
| 0 | Material failure: incorrect, unsafe, unusable, or unresolved without recovery. |
| 1 | Major issue: partial success with significant omission, friction, or likely correction. |
| 2 | Minor issue: mostly correct with a limited omission, inefficiency, or recovered mistake. |
| 3 | Strong: correct, complete, grounded, efficient, and free of material issues. |

Judges may instead return `not_applicable`, `uncertain`, or `insufficient_evidence`."""


def _metric_table() -> str:
    rows = [
        ("Agent", "Identity and authorization", "20% weekly/batch"),
        ("Agent", "Intent and routing", "10% monthly"),
        ("Agent", "Information capture and groundedness", "20% weekly/batch"),
        ("Agent", "Workflow execution", "risk-triggered"),
        ("Agent", "Resolution and automation", "15% weekly/batch"),
        ("Agent", "Recovery and escalation", "risk-triggered"),
        ("Experience", "Listening and comprehension", "10% monthly"),
        ("Experience", "Caller effort and repetition", "10% monthly"),
        ("Experience", "Clarity and coherence", "10% monthly"),
        ("Experience", "Trust and transparency", "20% biweekly"),
        ("Experience", "Closure and next steps", "10% monthly"),
        ("Experience", "Empathy and tone", "20% biweekly; wide CI"),
        ("Safety", "All six strict gates", "100% failures/uncertain + 10% passes"),
    ]
    lines = ["| Family | Metric | Human audit cadence |", "|---|---|---|"]
    lines.extend(f"| {family} | {metric} | {cadence} |" for family, metric, cadence in rows)
    return "\n".join(lines)


def build_submission(config: EvalConfig, run_id: str) -> tuple[Path, Path, Path]:
    run_dir = config.path("runs") / run_id
    output_dir = config.path("outputs") / run_id
    output_dir.mkdir(parents=True, exist_ok=True)
    analysis = _load_json(run_dir / "analysis_summary.json", {})
    comparison = _load_json(run_dir / "comparison.json", {})
    patterns = read_jsonl(run_dir / "failure_patterns.jsonl")
    human_complete = comparison.get("human_labels_complete", 0)
    human_total = comparison.get("human_labels_total", 0)
    all_human_complete = bool(human_total) and human_complete == human_total
    report_status = (
        "HUMAN-CALIBRATED" if all_human_complete else "DRAFT — HUMAN CALIBRATION PENDING"
    )

    pattern_sections = []
    for index, pattern in enumerate(patterns, start=1):
        pattern_sections.append(
            f"""### {index}. {pattern['pattern_name']}

- Outcome: {pattern['outcome']}
- Definition: {pattern['definition']}
- Prevalence: {pattern['transcript_prevalence']} of 50 transcripts; {pattern['audio_prevalence']} of 10 recordings
- Transcript calls: {', '.join(pattern['transcript_call_ids']) or 'none yet'}
- Audio calls: {', '.join(pattern['audio_call_ids']) or 'none yet'}
- Root cause hypothesis: {pattern['root_cause']}
- Proposed fix: {pattern['proposed_fix']}
- Success metric: {pattern['success_metric']}
- Validation: {'human verified' if pattern['human_verified'] else 'pending human evidence audit'}
"""
        )

    prompt_sections = []
    for stage in STAGE_FILES:
        prompt_sections.append(f"### {stage.replace('_', ' ').title()}\n\n```text\n{load_prompt(config, stage)}\n```")

    report = f"""# Confido Health Call Evaluation

**Status: {report_status}**

## Executive summary

This evaluation treats the 50 redacted transcript calls and 10 redacted audio recordings as independent samples. It separates operational agent performance from caller experience, applies strict safety gates, and compares achieved automation with the best outcome observable from the call.

The pipeline currently contains {analysis.get('calls', 0)} call records. {analysis.get('calls_requiring_human_review', 0)} are routed to human review by source-quality, confidence, safety, or validation rules. The six patterns below are generated candidates; they must not be presented as validated systemic findings until their exact calls and evidence have been reviewed.

## Dataset and methodology

- Transcript sample: 50 rows mapped deterministically to `transcript_001`–`transcript_050`.
- Audio sample: 10 independent WAV recordings mapped to `audio_001`–`audio_010` while preserving hashed source IDs.
- Evaluation flow: classification → agent performance, patient experience, and safety/compliance judges.
- Model: `gemini/gemini-3.1-flash-lite`, temperature 1.0, strict structured output and local validation.
- Evidence policy: observable evidence only; no inferred backend completion.
- Redaction policy: anonymization markers and intentional cuts never reduce an agent score.

## Evaluation rubric

### Scoring scale

{_score_scale()}

### Agent performance

The six metrics are identity/authorization, intent/routing, information capture/groundedness, workflow execution, resolution/automation, and recovery/escalation. Automation is recorded separately as achieved level, best feasible level, and their gap.

### Patient experience

The six metrics are listening/comprehension, caller effort/repetition, clarity/coherence, trust/transparency, closure/next steps, and empathy/tone. Transcript calls assess wording; audio calls also assess observable pacing, prosody, silence, clipping, and interruption behavior.

### Critical gates

Privacy/identity, clinical safety, fabrication, financial safety, AI transparency, and call control use `pass`, `fail`, `not_triggered`, or `uncertain`. Every failed or uncertain gate receives mandatory review.

### Human-audit cadence and confidence limits

{_metric_table()}

## Metrics intentionally excluded

Sentiment, raw duration, raw turn count, verbatim script adherence, politeness-word counts, generic naturalness, transcript-derived latency, formal ASR word-error rate without references, and inferred satisfaction are excluded because they are confounded, redundant, or unsupported. The rubric instead uses observable friction, accuracy, trust, closure, and audio behavior.

## Error-analysis loop

Fifteen diverse transcripts are split into 10 development and five holdout cases. Three diverse audio calls are used for prompt development and seven for validation, while all ten require human review. AI-produced labels are drafts only; user corrections become the human ground truth. Judge–human disagreements are categorized, prompt changes are versioned, and the holdout is rerun to detect regressions.

Current calibration status: {comparison.get('status', 'not run')}. Complete human labels: {human_complete} of {human_total}. Exact agreement: {comparison.get('exact_agreement')} (Wilson 95% CI {comparison.get('exact_agreement_wilson_95')}). Within-one agreement: {comparison.get('within_one_agreement')} (Wilson 95% CI {comparison.get('within_one_agreement_wilson_95')}). Weighted kappa: {comparison.get('quadratic_weighted_kappa')}. Automation-level agreement: {comparison.get('automation_level_agreement')} (Wilson 95% CI {comparison.get('automation_level_agreement_wilson_95')}). Critical precision: {comparison.get('critical_gate_precision')} (Wilson 95% CI {comparison.get('critical_gate_precision_wilson_95')}). Critical recall: {comparison.get('critical_gate_recall')} (Wilson 95% CI {comparison.get('critical_gate_recall_wilson_95')}). Evidence validity: {comparison.get('evidence_validity')} (Wilson 95% CI {comparison.get('evidence_validity_wilson_95')}).

Actual v1→v2 disagreement examples remain pending until the development labels are reviewed. No prompt change or holdout claim is made before that evidence exists.

## Six candidate systemic failure patterns

{''.join(pattern_sections) if pattern_sections else 'Analysis has not produced pattern candidates.'}

## Product recommendations

Prioritize deterministic workflow state, observable transfer/task completion, persistent entity context, required high-risk read-back, explicit final next-step summaries, and direct AI disclosure. Each recommendation should be accepted only after the linked pattern’s call list and evidence are human verified.

## Limitations

- Small samples create wide confidence intervals, especially by workflow.
- Audio and transcript samples are independent and must not be combined into a single prevalence denominator.
- Backend/tool outcomes and repeat contacts are absent, so operational completion cannot be inferred.
- Deepgram diarization collapsed one long recording to one speaker; one 97-second recording produced only eight words.
- Human calibration and evidence validation are pending unless this report is marked human-calibrated.
- A second independent reviewer is not included.
- Judge outputs can reflect model bias and must be monitored through recurring audits.

## Appendix A — Exact prompts

{'\n\n'.join(prompt_sections)}

## Appendix B — Output schemas

The machine-readable schema bundle delivered beside this report is generated directly from the Pydantic models used for validation.
"""
    report_path = output_dir / "report.md"
    report_path.write_text(report)

    schema_bundle = {
        "classification": ClassificationResult.model_json_schema(),
        "agent_performance": AgentPerformanceResult.model_json_schema(),
        "patient_experience": PatientExperienceResult.model_json_schema(),
        "safety_compliance": SafetyComplianceResult.model_json_schema(),
    }
    schemas_path = output_dir / "schemas.json"
    schemas_path.write_text(json.dumps(schema_bundle, indent=2, sort_keys=True))

    shutil.copy2(config.path("normalized"), output_dir / "calls.jsonl")

    for filename in [
        "classification.jsonl",
        "agent_performance.jsonl",
        "patient_experience.jsonl",
        "safety_compliance.jsonl",
        "call_results.jsonl",
        "human_labels.jsonl",
        "disagreements.jsonl",
        "failure_patterns.jsonl",
        "analysis_summary.json",
        "comparison.json",
        "calibration_manifest.json",
    ]:
        source = run_dir / filename
        if source.exists():
            shutil.copy2(source, output_dir / filename)

    video_outline = """# Confido take-home video outline (8–10 minutes)

1. Dataset and the independent transcript/audio samples — 45 seconds
2. Why classification precedes evaluation — 60 seconds
3. Separate agent performance, patient experience, and safety gates — 90 seconds
4. Automation achieved versus best possible automation — 60 seconds
5. Human calibration and the v1→v2 disagreement loop — 90 seconds
6. Three validated automation blockers — 90 seconds
7. Three validated patient-experience failures — 90 seconds
8. Highest-impact product fixes, limitations, and next measurement — 60 seconds

Do not record the final version until the workbook is fully reviewed and all six patterns are human verified.
"""
    video_path = output_dir / "video_outline.md"
    video_path.write_text(video_outline)
    return report_path, schemas_path, video_path
