from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Annotated

import typer

from .analysis import analyze_run
from .calibration import (
    calibration_call_ids,
    export_calibration,
    import_calibration,
    select_calibration,
    select_calibration_offline,
)
from .compare import compare_run
from .config import EvalConfig, load_config
from .models import CallRecord
from .normalize import prepare_dataset
from .runner import (
    load_dotenv_for_runtime,
    load_normalized_calls,
    run_judges,
    run_stage,
)
from .submission import build_submission
from .workbook import build_review_workbook


app = typer.Typer(
    name="confido-eval",
    help="Evaluate anonymized Confido healthcare voice-agent calls.",
    no_args_is_help=True,
)
calibration_app = typer.Typer(help="Export or import human calibration labels.")
app.add_typer(calibration_app, name="calibration")


def _config() -> EvalConfig:
    return load_config()


def _require_calls(config: EvalConfig) -> list[CallRecord]:
    if not config.path("normalized").exists():
        raise typer.BadParameter("Normalized data missing. Run `confido-eval prepare` first.")
    return load_normalized_calls(config)


def _filter_calls(calls: list[CallRecord], call_ids: str | None) -> list[CallRecord]:
    if not call_ids:
        return calls
    requested = {item.strip() for item in call_ids.split(",") if item.strip()}
    selected = [call for call in calls if call.call_id in requested]
    missing = requested - {call.call_id for call in selected}
    if missing:
        raise typer.BadParameter(f"Unknown call IDs: {', '.join(sorted(missing))}")
    return selected


def _require_gemini_key(config: EvalConfig) -> None:
    load_dotenv_for_runtime(config)
    if not os.environ.get("GEMINI_API_KEY"):
        raise typer.BadParameter("GEMINI_API_KEY is not set in .env or the environment")


def _write_manifest(config: EvalConfig, run_id: str) -> None:
    run_dir = config.path("runs") / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "models": config.model_by_stage,
        "prompt_version": config.prompt_version,
        "temperature": config.temperature,
        "concurrency": config.concurrency,
        "max_retries": config.max_retries,
    }
    (run_dir / "run_manifest.json").write_text(json.dumps(payload, indent=2, sort_keys=True))


@app.command()
def prepare() -> None:
    """Normalize and validate all transcript and audio sources."""
    config = _config()
    records = prepare_dataset(config)
    transcript_count = sum(record.source_type.value == "transcript" for record in records)
    audio_count = sum(record.source_type.value == "audio" for record in records)
    typer.echo(
        f"Prepared {len(records)} calls ({transcript_count} transcripts, {audio_count} audio) "
        f"at {config.path('normalized')}"
    )


@app.command()
def classify(
    run_id: Annotated[str, typer.Option(help="Stable identifier for this evaluation run.")],
    resume: Annotated[bool, typer.Option(help="Reuse valid matching stage outputs.")] = False,
    call_ids: Annotated[
        str | None, typer.Option(help="Comma-separated call IDs for a targeted run.")
    ] = None,
    model: Annotated[str | None, typer.Option(help="Override the configured classifier model.")] = None,
) -> None:
    """Classify calls, then select the diverse calibration set."""
    config = _config()
    _require_gemini_key(config)
    calls = _filter_calls(_require_calls(config), call_ids)
    _write_manifest(config, run_id)
    records = asyncio.run(
        run_stage(
            config,
            run_id,
            "classification",
            calls,
            resume=resume,
            model_override=model,
        )
    )
    valid = sum(record.metadata.validation_status == "valid" for record in records)
    typer.echo(f"Classification complete: {valid}/{len(records)} valid")
    if call_ids is None and len(calls) == 60:
        manifest = select_calibration(config, run_id, calls)
        typer.echo(
            "Calibration selected: "
            f"{len(manifest['transcript_development'])} development transcripts, "
            f"{len(manifest['transcript_holdout'])} holdout transcripts, "
            f"{len(manifest['audio_development'])} development audio, "
            f"{len(manifest['audio_validation'])} validation audio"
        )


@app.command()
def judge(
    run_id: Annotated[str, typer.Option(help="Existing classified run identifier.")],
    dataset: Annotated[str, typer.Option(help="`calibration` or `all`.")] = "calibration",
    resume: Annotated[bool, typer.Option(help="Reuse valid matching stage outputs.")] = False,
    call_ids: Annotated[
        str | None, typer.Option(help="Comma-separated call IDs for a targeted run.")
    ] = None,
    stage: Annotated[
        str | None,
        typer.Option(help="Optional single judge stage: agent_performance, patient_experience, safety_compliance."),
    ] = None,
    model: Annotated[str | None, typer.Option(help="Override the configured judge model.")] = None,
) -> None:
    """Run the three structured evaluation judges."""
    config = _config()
    _require_gemini_key(config)
    calls = _require_calls(config)
    if dataset not in {"calibration", "all"}:
        raise typer.BadParameter("dataset must be `calibration` or `all`")
    if dataset == "calibration":
        path = config.path("runs") / run_id / "calibration_manifest.json"
        if not path.exists():
            raise typer.BadParameter("Calibration manifest missing. Run classify on all calls first.")
        manifest = json.loads(path.read_text())
        selected = set(calibration_call_ids(manifest))
        calls = [call for call in calls if call.call_id in selected]
    calls = _filter_calls(calls, call_ids)
    outputs = asyncio.run(
        run_judges(
            config,
            run_id,
            calls,
            resume=resume,
            stage_filter=stage,
            model_override=model,
        )
    )
    for stage_name, records in outputs.items():
        valid = sum(record.metadata.validation_status == "valid" for record in records)
        typer.echo(f"{stage_name}: {valid}/{len(records)} valid")


@calibration_app.command("export")
def calibration_export(
    run_id: Annotated[str, typer.Option(help="Run containing calibration selections and drafts.")],
) -> None:
    """Export editable human-review rows and pending canonical labels."""
    config = _config()
    csv_path, labels_path = export_calibration(config, run_id, _require_calls(config))
    typer.echo(f"Review CSV: {csv_path}")
    typer.echo(f"Pending labels: {labels_path}")


@calibration_app.command("bootstrap")
def calibration_bootstrap(
    run_id: Annotated[str, typer.Option(help="Run to receive a provisional calibration set.")],
) -> None:
    """Select a provisional diverse set without claiming live classification."""
    config = _config()
    manifest = select_calibration_offline(config, run_id, _require_calls(config))
    typer.echo(
        "Provisional calibration selected: "
        f"{len(manifest['transcript_development'])} development transcripts, "
        f"{len(manifest['transcript_holdout'])} holdout transcripts, "
        f"{len(manifest['audio_development'])} development audio, "
        f"{len(manifest['audio_validation'])} validation audio"
    )


@calibration_app.command("import")
def calibration_import(
    run_id: Annotated[str, typer.Option(help="Run to receive reviewed labels.")],
    source: Annotated[Path, typer.Option(exists=True, readable=True, help="Reviewed CSV or XLSX.")],
) -> None:
    """Import user-reviewed labels as canonical human ground truth."""
    config = _config()
    output = import_calibration(config, run_id, source)
    typer.echo(f"Imported human labels: {output}")


@app.command()
def compare(
    run_id: Annotated[str, typer.Option(help="Run with judge outputs and human labels.")],
) -> None:
    """Calculate judge–human agreement and disagreement records."""
    summary, disagreements = compare_run(_config(), run_id)
    typer.echo(f"Comparison: {summary}")
    typer.echo(f"Disagreements: {disagreements}")


@app.command()
def analyze(
    run_id: Annotated[str, typer.Option(help="Run with all four stage outputs.")],
) -> None:
    """Aggregate call results and six candidate failure patterns."""
    config = _config()
    summary, patterns = analyze_run(config, run_id, _require_calls(config))
    typer.echo(f"Analysis: {summary}")
    typer.echo(f"Failure patterns: {patterns}")


@app.command("build-submission")
def build_submission_command(
    run_id: Annotated[str, typer.Option(help="Run to package for review/submission.")],
) -> None:
    """Generate report, JSONL bundle, workbook, rendered previews, and video outline."""
    config = _config()
    run_dir = config.path("runs") / run_id
    if not (run_dir / "analysis_summary.json").exists():
        analyze_run(config, run_id, _require_calls(config))
    if not (run_dir / "comparison.json").exists():
        compare_run(config, run_id)
    review_csv = config.path("review") / run_id / "calibration_review.csv"
    if not review_csv.exists():
        export_calibration(config, run_id, _require_calls(config))
    report, schemas, video = build_submission(config, run_id)
    workbook = build_review_workbook(config, run_id)
    typer.echo(f"Report: {report}")
    typer.echo(f"Schemas: {schemas}")
    typer.echo(f"Video outline: {video}")
    typer.echo(f"Review workbook: {workbook}")


if __name__ == "__main__":
    app()
