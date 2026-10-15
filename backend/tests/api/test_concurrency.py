"""Regression (live browser pass 2026-10-15): parallel API requests shared one SQLite connection across worker threads
and failed with sqlite3.InterfaceError (HTTP 500)."""

from concurrent.futures import ThreadPoolExecutor

from starlette.testclient import TestClient

from tests.api.test_analysis_api import FD, LIQUID, TBILL, api  # noqa: F401 - fixture re-export


def test_parallel_requests_do_not_corrupt_the_connection(api: tuple[TestClient, dict[str, str]]) -> None:  # noqa: F811
    c, _ = api
    paths = [f"/api/instruments/{i}" for i in (TBILL, FD, LIQUID)] * 20 + ["/api/instruments?kind=mf_scheme"] * 20
    with ThreadPoolExecutor(max_workers=16) as pool:
        codes = list(pool.map(lambda p: c.get(p).status_code, paths))
    assert codes.count(200) == len(paths), sorted(set(codes))
