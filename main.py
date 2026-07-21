"""Project entrypoints.

``main:app`` is the FastAPI ASGI application — the entrypoint used by ASGI
servers and by Vercel's FastAPI framework preset. Running this file directly
(``python main.py ...``) still invokes the Typer CLI. The web app is imported
lazily via :pep:`562` so CLI-only installs (without the ``api`` extra) keep
working and never import FastAPI.
"""

from __future__ import annotations

from typing import Any


def __getattr__(name: str) -> Any:
    # Lazily expose the ASGI app as ``main:app`` without importing FastAPI at
    # module load, so the CLI path below stays dependency-light.
    if name == "app":
        from confido_eval.webapp import app

        return app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


if __name__ == "__main__":
    from confido_eval.cli import app as cli

    cli()
