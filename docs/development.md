# Development

## Local setup

```bash
uv sync --extra dev
uv run evalrx --help
```

The evaluation runtime does not depend on a transcription SDK. Install the
optional extra only when generating new Deepgram responses:

```bash
uv sync --extra transcription
uv run python transcribe.py
```

The package uses a `src/` layout and exposes `evalrx` through the project
entry point. Runtime configuration lives in `config/eval.toml`; packaged defaults
are included automatically in wheel installs from their canonical files.

## Repository layout

```text
config/                  Runtime models, thresholds, retries, and audit policy
docs/                    Production documentation
prompts/<version>/       Canonical plain-text prompt templates
src/evalrx/              Package code and runtime assets
tests/                   Unit, contract, and opt-in live tests
data/                    Ignored private sources, ASR responses, and normalized data
```

## Verification

Run the full local gate before committing:

```bash
uv run --extra dev pytest
uv run --extra dev ruff check .
uv build
git diff --check
```

The default test suite creates synthetic workbooks, WAV files, and ASR responses
in temporary directories and uses mocked provider responses. No private dataset
or credentials are needed. The opt-in live smoke test sends one synthetic call
through the configured provider:

```bash
EVALRX_LIVE_SMOKE=1 uv run --extra dev pytest -m live
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

Workbook generation uses the declared `openpyxl` dependency. It needs no desktop
runtime or JavaScript installation. Tests verify all seven sheets, dynamic row
ranges, reviewer fields, and calibration import. JSONL remains canonical;
workbook edits are imported through the review interface.

## Definition of done

A production change is complete when:

- Tests and lint pass.
- Package build includes prompts, config defaults, and the frontend.
- New failures remain explicit and reviewable.
- Security and redaction rules are preserved.
- Operator and architecture docs reflect changed behavior.
- No generated data, local plans, source datasets, or secrets are staged.
