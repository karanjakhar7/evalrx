"""Vercel entrypoint. The real app lives in the installed package so it can be
imported from any working directory; this shim exists for Vercel's ``api/``
convention. See ``confido_eval.webapp``."""

from confido_eval.webapp import app

__all__ = ["app"]
