"""FastAPI application for live single-call analysis.

The ASGI ``app`` lives inside the installed package so it is importable from any
working directory (``uvicorn confido_eval.webapp:app``). Config and prompts are
resolved from the package location, not the current directory, so the server
behaves identically regardless of where it is launched.

Thin re-export shims exist for specific runtimes: ``api/index.py`` for Vercel's
zero-config ``api/`` convention and ``app/main.py`` for an ``app.main:app`` target.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .config import load_config
from .runner import load_dotenv_for_runtime
from .service import TranscriptError, evaluate_transcript

config = load_config()
# Bundled frontend, read from the package location so it resolves from any
# working directory and from the installed wheel (e.g. on Vercel).
INDEX_HTML = (Path(__file__).with_name("static") / "index.html").read_text(encoding="utf-8")
# Load provider credentials from the same .env the CLI uses (resolved from the
# package location, so it works from any working directory). On hosts without a
# .env file (e.g. Vercel) this is a no-op and real environment variables win.
load_dotenv_for_runtime(config)

app = FastAPI(
    title="Confido Analysis API",
    version="0.1.0",
    description="Live single-call evaluation for anonymized healthcare voice-agent transcripts.",
)


class AnalysisRequest(BaseModel):
    transcript: str = Field(
        min_length=1,
        description="Labeled transcript, one turn per line as 'Agent: ...' / 'User: ...'.",
    )
    call_id: str | None = Field(
        default=None,
        description="Optional identifier echoed back on the result.",
    )


def _gemini_key_present() -> bool:
    return bool(os.environ.get("GEMINI_API_KEY"))


@app.get("/", response_class=HTMLResponse)
def root() -> HTMLResponse:
    return HTMLResponse(INDEX_HTML)


@app.get("/health")
def health() -> dict[str, object]:
    return {
        "status": "ok",
        "gemini_key_present": _gemini_key_present(),
        "models": config.model_by_stage,
        "prompt_version": config.prompt_version,
    }


@app.post("/analysis")
async def analysis(request: AnalysisRequest) -> dict[str, object]:
    if not _gemini_key_present():
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY is not configured on the server.",
        )
    try:
        return await evaluate_transcript(
            config,
            request.transcript,
            call_id=request.call_id or "api_request",
        )
    except TranscriptError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # provider / unexpected runtime failure
        raise HTTPException(status_code=502, detail=f"Evaluation failed: {exc}") from exc
