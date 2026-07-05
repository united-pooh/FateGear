"""KTSL web backend package.

Provides the :mod:`scenario.web.ktsl_router` module that registers the
KTSL REST endpoints onto an existing aiohttp application via
:func:`register_ktsl_routes`.
"""

from __future__ import annotations

from .ktsl_router import register_ktsl_routes

__all__ = ["register_ktsl_routes"]
