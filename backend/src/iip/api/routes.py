"""Router registry. Feature routers are added here as stages land."""

from __future__ import annotations

from fastapi import APIRouter


def all_routers() -> list[APIRouter]:
    return []
