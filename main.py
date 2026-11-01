"""Deployment entrypoint: ``main:app`` is the FastAPI ASGI application (used by
Vercel's FastAPI preset and any ASGI server). Running this file directly
(``python main.py ...``) still invokes the Typer CLI."""

from evalrx.webapp import app

__all__ = ["app"]


if __name__ == "__main__":
    from evalrx.cli import app as cli

    cli()
