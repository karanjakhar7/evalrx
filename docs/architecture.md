# Architecture

## Purpose

Confido Evaluation System evaluates healthcare voice-agent interactions without
collapsing operational quality, caller experience, and safety into a single
score. The design favors auditable records, explicit uncertainty, human review,
and reproducible reruns.

## System boundaries

The pipeline accepts redacted transcript and audio sources. It does not modify
source files, infer backend actions that are not observable, or treat model output
as human ground truth. External model and transcription providers are adapters;
canonical records remain provider-neutral Pydantic models serialized as JSONL.

## Processing flow

```text
Read-only sources
      │
      ▼
Normalization and source-quality inventory
      │
      ▼
Classification
      │
      ├──────────────┬──────────────────┐
      ▼              ▼                  ▼
Agent judge    Experience judge    Safety judge
      └──────────────┴──────────────────┘
                     │
                     ▼
Validation and human-review routing
                     │
                     ▼
Comparison, analysis, and derived artifacts
```

Classification runs first because expected behavior depends on workflow,
interaction type, counterparty, and disposition. The three judges then run in
parallel behind one shared concurrency limit.

## Components

| Component | Responsibility |
|---|---|
| `normalize.py` | Read source data, assign stable IDs, construct deterministic turns, calculate hashes, and flag source limitations. |
| `models.py` | Define strict contracts for calls, evidence, stage outputs, human labels, disagreements, and failure patterns. |
| `prompts.py` | Load canonical plain-text prompts, hash content, and build strict JSON Schema contracts from Pydantic result models. |
| `runner.py` | Execute LiteLLM calls, enforce concurrency/retries, validate evidence, resume matching work, and route review. |
| `calibration.py` | Select coverage-oriented calibration samples and round-trip reviewer labels. |
| `compare.py` | Calculate agreement, weighted kappa, gate precision/recall, evidence validity, and Wilson intervals. |
| `analysis.py` | Produce call-level aggregates and candidate recurring patterns while preserving sample denominators. |
| `submission.py` | Package canonical and derived machine-readable/report artifacts. |
| `workbook.py` | Generate and render the editable review workbook through the artifact runtime. |
| `cli.py` | Expose the supported operator interface. |

## Canonical records and derived artifacts

JSONL is the source of truth. Workbooks and Markdown reports are derived views.
Every call has a stable `call_id`, source hash, original text, normalized turns,
role mapping, and source-quality record. Every model result stores its model,
LiteLLM version, prompt and schema versions, prompt/source hashes, token usage,
latency, raw structured response, validation status, and review decision.

The source hash covers the immutable input representation. A stage result is
reusable only when call ID, stage, model, prompt hash, and source hash still
match. This makes `--resume` idempotent without masking prompt or data changes.

## Validation and trust boundaries

Every stage sends a strict Pydantic-derived JSON Schema through LiteLLM. Provider
structured output is still untrusted until local validation succeeds. The
pipeline verifies:

- Pydantic schema conformance and call-ID consistency.
- Quoted evidence exists in the normalized transcript.
- Turn IDs exist and audio timestamps are ordered and within duration.
- Best-possible automation is not below achieved automation.
- Critical or uncertain safety gates force human review.
- Poor source quality, unknown classifications, low confidence, stage failures,
  and deterministic audit samples are routed to review.

Validation failures are retained as explicit records; the system does not
silently repair judge output.

## Execution and failure handling

Classification uses the configured concurrency limit. Downstream judge work is
scheduled concurrently across stages and calls while sharing the same global
limit. Schema failures and transient provider failures receive bounded
exponential-backoff retries. Authentication and other non-transient failures are
recorded immediately and require review.

Per-call stage files make partial progress durable. Run-level JSONL files are
canonical indexes over those records. A failed call does not make the rest of a
run disappear.

## Security and privacy

- Secrets are loaded from `.env` at runtime and are excluded from logs and
  artifacts.
- Raw audio is referenced by path and is never embedded in normalized output.
- Source inputs, normalized data, runs, review drafts, and outputs are ignored by
  Git.
- Request headers are never persisted.
- Redaction and intentional anonymization cuts are hard exclusions from scoring.

## Extension points

Stage-specific models can be changed in `config/eval.toml` without code changes.
New prompt versions live beside existing versions and change resume keys through
their content hash. New schemas should be introduced with an explicit schema
version and migration/compatibility tests. Provider changes belong behind the
LiteLLM adapter; artifact consumers should continue reading the canonical models.
