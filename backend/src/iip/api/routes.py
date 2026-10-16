"""Router registry by autodiscovery (A05): every ``iip/api/routes_<feature>.py`` module is a feature router.

A new feature adds its own ``routes_<feature>.py`` exposing ``router() -> APIRouter``; nobody edits this file, so
parallel packages never collide on it. Routers are registered in module-name order (deterministic);
``tests/api/test_router_autodiscovery.py`` proves no route captures another's URL in that order and that every route
registered before the switch is still registered. A ``routes_*.py`` module without a usable ``router()`` fails
startup loudly: silently skipping it would drop its routes."""

from __future__ import annotations

import importlib
import pkgutil
from types import ModuleType

from fastapi import APIRouter

PREFIX = "routes_"


def _module_names(package: ModuleType) -> list[str]:
    return sorted(m.name for m in pkgutil.iter_modules(package.__path__) if m.name.startswith(PREFIX))


def discover_routers(package: ModuleType) -> list[APIRouter]:
    """Import every ``routes_*`` module of ``package`` (sorted by name) and build its router."""
    found: list[APIRouter] = []
    for name in _module_names(package):
        module = importlib.import_module(f"{package.__name__}.{name}")
        factory = getattr(module, "router", None)
        if not callable(factory):
            raise TypeError(f"{module.__name__} must define router() -> APIRouter")
        built = factory()
        if not isinstance(built, APIRouter):
            raise TypeError(f"{module.__name__}.router() returned {type(built).__name__}, not APIRouter")
        found.append(built)
    return found


def _api_package() -> ModuleType:
    return importlib.import_module("iip.api")


def router_module_names() -> list[str]:
    """The feature router modules that :func:`all_routers` registers, in registration order."""
    return _module_names(_api_package())


def all_routers() -> list[APIRouter]:
    return discover_routers(_api_package())
