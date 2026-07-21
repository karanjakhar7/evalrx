from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .config import EvalConfig


def _artifact_module() -> Path:
    configured = os.environ.get("CONFIDO_ARTIFACT_TOOL_MODULE")
    if configured:
        return Path(configured).expanduser().resolve()
    return (
        Path.home()
        / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules"
        / "@oai/artifact-tool/dist/artifact_tool.mjs"
    )


def _node_binary() -> str:
    discovered = shutil.which("node")
    if discovered:
        return discovered
    bundled = (
        Path.home()
        / ".cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node"
    )
    if bundled.exists():
        return str(bundled)
    raise RuntimeError("Node.js is required to generate the review workbook")


def build_review_workbook(config: EvalConfig, run_id: str) -> Path:
    """Generate and visually render the seven-sheet workbook with artifact-tool."""
    module = _artifact_module()
    if not module.exists():
        raise RuntimeError(
            "@oai/artifact-tool was not found; set CONFIDO_ARTIFACT_TOOL_MODULE "
            "to its artifact_tool.mjs path"
        )
    script = Path(__file__).with_name("build_workbook.mjs")
    environment = {
        key: value
        for key, value in os.environ.items()
        if key in {"HOME", "PATH", "TMPDIR", "LANG", "LC_ALL"}
    }
    environment["CONFIDO_ARTIFACT_TOOL_MODULE"] = str(module)
    result = subprocess.run(
        [_node_binary(), str(script), str(config.project_root), run_id],
        cwd=config.project_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()[-1:]
        raise RuntimeError(f"Workbook generation failed: {detail[0] if detail else 'unknown error'}")
    workbook = config.path("outputs") / run_id / "confido_evaluation_review.xlsx"
    if not workbook.exists():
        raise RuntimeError("Workbook generator completed without producing the expected file")
    return workbook
