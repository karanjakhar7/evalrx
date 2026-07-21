"""Deployment entrypoint: ``main:app`` is the FastAPI ASGI application (used by
Vercel's FastAPI preset and any ASGI server). Running this file directly
(``python main.py ...``) still invokes the Typer CLI."""

from confido_eval.webapp import app

__all__ = ["app"]


if __name__ == "__main__":
    from confido_eval.cli import app as cli

    cli()
