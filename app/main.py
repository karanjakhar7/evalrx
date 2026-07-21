"""Local/general entrypoint: ``uvicorn app.main:app`` (run from the repo root).

The real app lives in the installed package, so ``uvicorn confido_eval.webapp:app``
works from any directory. This shim provides the conventional ``app.main:app``
target for local development."""

from confido_eval.webapp import app

__all__ = ["app"]
