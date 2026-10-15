"""ECC F1/DB-2: two concurrent applies of the same import batch must store its rows exactly once.

Every pre-transaction check used to run outside BEGIN IMMEDIATE. Both requests passed them while the pre-import
backup ran, and the later transaction re-inserted every row. The barrier below stands in for that slow backup and
forces both threads past the checks before either one writes."""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from iip.services import cas
from iip.services import portfolio as pf
from iip.store.db import connect, migrate
from tests.services import cas_synthetic as syn
from tests.services.test_cas import seed_isins
from tests.services.test_portfolio import CSV_OK, NOW, make_pf, seed_market


def _race(db: Path, apply: Callable[[Any, Callable[[], object]], dict[str, Any]]) -> list[object]:
    barrier = threading.Barrier(2)
    results: list[object] = []

    def run() -> None:
        c = connect(db)
        try:
            results.append(apply(c, lambda: barrier.wait(5))["transactions_created"])
        except pf.PortfolioError as exc:
            results.append(exc.code)
        finally:
            c.close()

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def _setup(tmp_path: Path) -> tuple[Path, Any]:
    db = tmp_path / "x.db"
    c = connect(db)
    migrate(c, NOW.isoformat())
    seed_market(c)
    seed_isins(c)
    return db, c


def test_concurrent_csv_apply_stores_rows_once(tmp_path: Path) -> None:
    db, c = _setup(tmp_path)
    pid = make_pf(c)
    p = pf.preview_holdings_import(c, pid, CSV_OK, "h.csv", None, NOW)
    n = len(p["will_store"])
    assert n > 0

    def apply(conn: Any, pre: Callable[[], object]) -> dict[str, Any]:
        return pf.apply_holdings_import(conn, p["batch_id"], p["file_sha256"], NOW, pre_change=pre)

    results = _race(db, apply)
    assert sorted(results, key=str) == sorted([n, "ALREADY_APPLIED"], key=str)
    assert c.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == n


def test_concurrent_cas_apply_stores_rows_once(tmp_path: Path) -> None:
    db, c = _setup(tmp_path)
    pid = make_pf(c)
    p = cas.preview_cas_import(c, pid, syn.build_pdf(None), syn.PASSWORD, NOW)
    body = cas.CasApplyIn(sha256=str(p["file_sha256"]))
    n = len(p["will_store"])  # type: ignore[arg-type]
    assert n > 0

    def apply(conn: Any, pre: Callable[[], object]) -> dict[str, Any]:
        return cas.apply_cas_import(conn, str(p["batch_id"]), body, NOW, pre_change=pre)

    results = _race(db, apply)
    assert sorted(results, key=str) == sorted([n, "ALREADY_APPLIED"], key=str)
    assert c.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == n
