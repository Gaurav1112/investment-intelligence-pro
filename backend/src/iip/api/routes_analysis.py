"""Feature routes (analysis). Owned by a Stage D agent; registered in routes.py."""

from __future__ import annotations

from fastapi import APIRouter


def router() -> APIRouter:
    return APIRouter(prefix="/api")
