"""Router registry. Feature routers are added here as stages land."""

from __future__ import annotations

from fastapi import APIRouter

from iip.api import routes_analysis, routes_cas, routes_core, routes_llm, routes_portfolio, routes_profile


def all_routers() -> list[APIRouter]:
    return [
        routes_profile.router(),
        routes_core.router(),
        routes_analysis.router(),
        routes_portfolio.router(),
        routes_llm.router(),
        routes_cas.router(),
    ]
