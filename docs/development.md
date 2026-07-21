# Development

## Local setup

```bash
uv sync --extra dev
uv run confido-eval --help
```

The evaluation runtime does not depend on a transcription SDK. Install the
optional extra only when generating new Deepgram responses:

```bash
uv sync --extra transcription
uv run python transcribe.py
```

The package uses a `src/` layout and exposes `confido-eval` through the project
entry point. Runtime configuration lives in `config/eval.toml`; packaged defaults
under `src/confido_eval/assets/` must remain synchronized for wheel installs.

## Repository layout

```text
config/                  Runtime models, thresholds, retries, and audit policy
docs/                    Production documentation
prompts/<version>/       Canonical plain-text prompt templates
src/confido_eval/        Package code and runtime assets
tests/                   Unit, contract, and opt-in live tests
transcripts/             Existing ASR responses used as read-only sources
local/                   Ignored local planning and submission workspace
```

## Verification

Run the full local gate before committing:

```bash
uv run --extra dev pytest
uv run --extra dev ruff check .
uv build
git diff --check
```

The default test suite uses mocked provider responses. The opt-in live smoke test
sends one redacted call through the configured provider:

```bash
CONFIDO_LIVE_SMOKE=1 uv run --extra dev pytest -m live
```

## Prompt changes

Do not overwrite a prompt version after it has produced reviewed results. Create
a new version directory, update the configured stage version, and retain the old
prompt for regression comparison. Every prompt must include metric definitions,
anchors, applicability, redaction exclusions, evidence rules, uncertainty, and
human-review triggers.

Prompt templates use `.txt` files because they are provider instructions, not
rendered documentation. They have one canonical copy under `prompts/`; Hatch
includes that copy in the wheel at build time.

## Schema changes

Pydantic models are strict (`extra="forbid"`). Add fields deliberately, bump the
schema version, update prompt output contracts, and add compatibility tests for
saved stage records. Never silently coerce invalid evidence or automation levels.

## Provider and retry changes

Provider calls belong in `runner.py`. Preserve the distinction between transient
failures, which may be retried with bounded backoff, and non-transient failures,
which should be retained immediately. Tests must cover invalid JSON, rate limits,
authentication failures, resumption, and multimodal audio payloads.

## Workbook changes

Workbook generation uses the packaged artifact-tool JavaScript module. Every
sheet must be rendered after changes, inspected visually, and scanned for formula
errors. JSONL remains canonical; workbook edits are imported through the review
interface rather than treated as a second source of truth.

## Definition of done

A production change is complete when:

- Tests and lint pass.
- Package build includes prompts, config defaults, and workbook runtime assets.
- New failures remain explicit and reviewable.
- Security and redaction rules are preserved.
- Operator and architecture docs reflect changed behavior.
- No generated data, local plans, source datasets, or secrets are staged.
