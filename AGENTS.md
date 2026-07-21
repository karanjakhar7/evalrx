# Confido Evaluation System

Production-oriented evaluation pipeline for healthcare voice-agent calls. The
system normalizes redacted sources, runs four structured evaluation stages,
supports human calibration, and produces auditable JSONL-first results.

## Repository map

- `README.md` — concise operator entry point.
- `docs/architecture.md` — boundaries, data flow, validation, and persistence.
- `docs/operations.md` — run lifecycle, review, recovery, and retention.
- `docs/development.md` — development and verification workflow.
- `docs/roadmap.md` — production engineering backlog.
- `config/eval.toml` — stage models, concurrency, retries, and audit policy.
- `prompts/` — canonical plain-text, versioned judge prompts.
- `src/confido_eval/` — installable package and runtime code.
- `tests/` — unit, contract, and opt-in live tests.
- `local/` — ignored local planning and submission material.

## Data handling

- Source workbooks, WAV files, and ASR responses are read-only.
- Samples may contain redactions and intentional anonymization cuts. These must
  never reduce agent scores.
- Numeric diarization labels remain unchanged until reviewed role evidence exists.
- Raw audio must not be duplicated into normalized data or model-run artifacts.
- Generated data, runs, review drafts, outputs, local plans, and secrets stay out
  of Git.

## Setup and verification

Python 3.12 or newer and `uv` are required.

```bash
uv sync --extra dev
uv run --extra dev pytest
uv run --extra dev ruff check .
uv build
```

`.env` may contain provider credentials. Never read, print, log, or commit their
values. The application loads them only during runtime authentication.

## Engineering rules

- JSONL is canonical; reports and workbooks are derived artifacts.
- Invalid or failed judge output remains explicit and review-required.
- Prompt, model, schema, and source changes must invalidate resumable stage keys.
- Prompt templates have one canonical source; the package build includes them in
  the wheel automatically.
- Preserve unrelated user changes in a dirty worktree.
