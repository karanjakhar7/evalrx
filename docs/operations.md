# Operations

## Prerequisites

- Python 3.12 or newer
- `uv`
- Read access to the configured source dataset
- `GEMINI_API_KEY` for model-backed stages
- `DEEPGRAM_API_KEY` only when generating fresh ASR responses
- Node.js and `@oai/artifact-tool` when generating the review workbook

Outside the bundled desktop runtime, set `CONFIDO_ARTIFACT_TOOL_MODULE` to the
absolute path of `@oai/artifact-tool/dist/artifact_tool.mjs`.

Copy `.env.example` to `.env` and set only the credentials required for the
operation. Never print, inspect, or commit `.env`.

Fresh transcription is an optional preprocessing operation:

```bash
uv sync --extra transcription
uv run python transcribe.py
```

## Run lifecycle

### 1. Prepare

```bash
uv run confido-eval prepare
```

Preparation validates the expected inventory, produces stable call and turn IDs,
records source hashes and quality flags, and writes the canonical normalized
manifest. Re-running preparation should produce the same IDs and hashes when
sources are unchanged.

### 2. Classify

```bash
uv run confido-eval classify --run-id <run-id> --resume
```

Classification creates the workflow context needed by every judge. A full run
also creates the deterministic calibration manifest.

If model access is temporarily unavailable, `calibration bootstrap` may create a
provisional coverage set. It is an operational convenience, not a substitute for
classification.

### 3. Calibrate and review

```bash
uv run confido-eval judge --dataset calibration --run-id <run-id> --resume
uv run confido-eval calibration export --run-id <run-id>
uv run confido-eval calibration import --run-id <run-id> --source <review-file>
uv run confido-eval compare --run-id <run-id>
```

Exports contain AI drafts and editable human fields. Review status becomes
complete only after all required rows for a call are completed. Comparison output
remains pending until reviewed labels exist.

### 4. Evaluate all calls and analyze

```bash
uv run confido-eval judge --dataset all --run-id <run-id> --resume
uv run confido-eval analyze --run-id <run-id>
```

Calls with missing or failed stages remain in call-level output with explicit
review-required state.

### 5. Package artifacts

```bash
uv run confido-eval build-submission --run-id <run-id>
```

This packages canonical JSONL, schemas, a Markdown report, a review workbook, and
rendered workbook previews. The command does not convert pending AI drafts into
validated findings.

## Resume and targeted recovery

Use `--resume` for interrupted or rate-limited runs. Valid matching per-call
results are reused; changed prompts, models, or sources are evaluated again. Use
call and stage filters to isolate failures before retrying the larger run.

Do not delete run directories to recover from ordinary failures. Failed-stage
records are useful audit evidence, and successful per-call records support safe
resumption.

## Human-review policy

Mandatory review includes critical failures, uncertain safety results, poor
source quality, unknown workflow/roles, low confidence, invalid evidence,
inconsistent automation levels, and failed stages. Non-critical passing results
are selected deterministically for audit according to `config/eval.toml`.

Human labels are authoritative only after import. Reviewer identity and notes
should be populated for completed records. A second reviewer or adjudication
process can be added without changing judge schemas.

## Data retention and access

Generated data is intentionally local:

- `data/normalized/`
- `runs/`
- `review/working/`
- `outputs/`
- `local/`

Apply the organization's retention policy to these directories. Do not publish
raw source material or model request payloads. Share only the minimum derived
artifact needed by its audience.

## Operational checks

Before treating a run as complete, verify:

- Expected call counts and unique IDs.
- No missing stage without an explicit failed/review-required record.
- Source hashes match the prepared manifest.
- Human-review requirements are resolved or clearly pending.
- Evidence quotes and timestamps validate.
- Transcript and audio denominators remain separate.
- Workbook previews render and the formula scan is clean.
- Output scans contain no secrets.
