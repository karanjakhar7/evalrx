# EvalRX

Standalone, JSONL-first evaluation pipeline for healthcare voice agents.
It normalizes transcript and audio sources, classifies each interaction, runs
separate agent-performance, patient-experience, and safety judges, and routes
uncertain or high-risk results to human review.

## Documentation

- [Architecture](docs/architecture.md) — system boundaries, data flow, execution,
  persistence, and safety controls.
- [Operations](docs/operations.md) — run lifecycle, recovery, review, and artifact
  management.
- [Development](docs/development.md) — setup, testing, prompt/schema changes, and
  release checks.
- [Roadmap](docs/roadmap.md) — production engineering backlog only.

## Quick start

Python 3.12 or newer and `uv` are required.

```bash
cp .env.example .env
uv sync --extra dev
uv run evalrx --help
```

For batch evaluation, set source paths in `config/eval.toml`. Defaults are
`data/sources/transcripts.xlsx` (a `Transcripts` sheet with a
`transcript_redacted` column), `data/sources/audio/` (WAV recordings), and
`data/asr/` (matching Deepgram JSON responses). Create the audio directory even
for a transcript-only dataset. Private inputs are never included in Git. Tests
generate their own synthetic sources.

Run `uv run evalrx prepare` after adding your sources.

Set `GEMINI_API_KEY` in `.env` before running model-backed stages. The key is
loaded only at runtime and is never written to run records.

```bash
uv run evalrx classify --run-id baseline --resume
uv run evalrx judge --dataset calibration --run-id baseline --resume
uv run evalrx calibration export --run-id baseline
uv run evalrx calibration import --run-id baseline --source review/working/baseline/calibration_review.csv
uv run evalrx compare --run-id baseline
uv run evalrx judge --dataset all --run-id baseline --resume
uv run evalrx analyze --run-id baseline
uv run evalrx build-report --run-id baseline
```

Use `--call-ids` and `--stage` where available for targeted debugging. Stage
models, prompt versions, concurrency, retries, and review thresholds live in
`config/eval.toml`.

Judge instructions are plain-text files under `prompts/<version>/`. Every stage
requests a strict JSON Schema generated from its Pydantic result model; free-form
model text is never accepted as a successful stage result.

## HTTP API (preview)

A stateless FastAPI app exposes live single-call evaluation and a small served
frontend. It normalizes a labeled transcript in memory and runs classification
plus the three judges through the same canonical path as the batch pipeline — no
run filesystem is touched, so it deploys to serverless hosts (e.g. Vercel).

The ASGI app lives in the installed package (`evalrx.webapp:app`), so it
runs from any working directory once installed using packaged config and prompts
as defaults. An installed package uses the current working directory for `.env`,
local configuration, and batch data. `main:app` (root `main.py`) is
the deployment entrypoint (running `python main.py` still invokes the CLI).

Credentials load from the same `.env` as the CLI (set `GEMINI_API_KEY` there), or
from real environment variables. On Vercel there is no `.env`, so set the env var
in the dashboard.

```bash
uv sync --extra dev --extra api
# From the checkout, either entrypoint serves the same app:
uv run uvicorn main:app --reload            # deployment entrypoint
uv run uvicorn evalrx.webapp:app --reload

# Then open http://localhost:8000/ for the UI, or call the API directly:
curl -s -X POST localhost:8000/analysis \
  -H 'content-type: application/json' \
  -d '{"transcript":"Agent: How can I help?\nUser: I need to reschedule my appointment."}'
```

`GET /` serves the frontend; `GET /health` reports whether `GEMINI_API_KEY` is
present (never the value) and the configured models. For Vercel, `vercel.json`
selects the `fastapi` framework preset, which serves `main:app`; import the repo
in the dashboard, set `GEMINI_API_KEY`, and use Python 3.12. Audio calls and
auth/rate-limiting are out of scope for this preview. A hardened service API
remains a roadmap item (`docs/roadmap.md`, P2).

## Data contract

- Source workbooks, WAV files, and ASR responses are read-only inputs.
- `data/normalized/calls.jsonl` is the canonical normalized call manifest.
- `runs/<run-id>/` contains resumable stage records and run metadata.
- `review/working/<run-id>/` contains editable human-review exports.
- `outputs/<run-id>/` contains derived reports, JSONL bundles, workbooks, and
  schemas.
- AI-produced labels are drafts. Only imported reviewer corrections are human
  ground truth.
- Redactions, anonymization cuts, ASR/diarization defects, and absent backend
  metadata are source limitations, not agent failures.
- Transcript and audio samples retain separate prevalence denominators.

## Verification

```bash
uv run --extra dev pytest
uv run --extra dev ruff check .
uv build
```

The live provider smoke test is opt-in and requires both
`EVALRX_LIVE_SMOKE=1` and `GEMINI_API_KEY`.
