"""Survivorship support (PLAN A09): closed/merged-scheme rows, scheme status, earliest NAV date per role, the
pre-2013 Regular-plan label, and the probe script's pure logic.

Every scheme code, name and NAV below is SYNTHETIC (fictional fund house "Halcyon"); no AMFI data is used.
"""

from __future__ import annotations

import importlib.util
import itertools
import sys
from datetime import date
from pathlib import Path
from types import ModuleType

import pytest

from iip.data.models import QualityStatus, RawPayload
from iip.data.parsers.amfi_navall import NAVALL_HEADER, parse_navall
from iip.data.parsers.amfi_navhistory import (
    DIRECT_PLANS_START,
    FLAG_CEASED,
    FLAG_STARTED,
    LABEL_REGULAR_PRE_2013,
    NAVHISTORY_HEADER,
    EarliestStatus,
    earliest_nav_date_per_role,
    history_spans,
    parse_navhistory,
    window_flags,
)
from iip.data.parsers.amfi_scheme_master import (
    SCHEME_MASTER_HEADER,
    SchemeStatus,
    classify_scheme_status,
    history_tp,
    latest_nav_dates,
    parse_scheme_master,
)
from iip.data.registry import MAX_HISTORY_WINDOW_DAYS, SourceRequest, navhistory_request
from tests.data.conftest import (
    NAVALL_RETRIEVED,
    NAVALL_URL,
    NAVHISTORY_RETRIEVED,
    NAVHISTORY_URL,
    SCHEMEDATA_RETRIEVED,
    SCHEMEDATA_URL,
    make_payload,
)

FQ = QualityStatus.FIXTURE


def _hist_row(code: int, name: str, plan: str, nav: str, d: str) -> bytes:
    return f"{code};{name};{plan};Growth Option;;;{nav};{d}".encode()


def _history(section: str, *rows: bytes, amc: str = "Halcyon Mutual Fund") -> bytes:
    lines = [NAVHISTORY_HEADER.encode(), b"", section.encode(), b"", b"", amc.encode(), *rows]
    return b"\r\n".join(lines) + b"\r\n"


def _parse_hist(content: bytes):
    return parse_navhistory(make_payload("amfi.navhistory", content, NAVHISTORY_URL, NAVHISTORY_RETRIEVED), quality=FQ)


def _navall(*rows: bytes) -> bytes:
    lines = [NAVALL_HEADER.encode(), b" ", b"Open Ended Schemes(Index Funds)", b" ", b"Halcyon Mutual Fund", *rows]
    return b"\r\n".join(lines) + b"\r\n"


def _navall_row(code: int, nav: str, d: str) -> bytes:
    return f"{code};-;-;Halcyon Synthetic Fund {code};Direct Plan;Growth Option;{nav};{d}".encode()


def _parse_navall(content: bytes):
    return parse_navall(make_payload("amfi.navall", content, NAVALL_URL, NAVALL_RETRIEVED), quality=FQ)


# A synthetic close-ended (tp=2) window: one scheme matures mid-window, one publishes "N.A." after closure, one runs on.
CLOSED_WINDOW = _history(
    "Close Ended Schemes ( Income )",
    _hist_row(900001, "Halcyon Fixed Term Plan Series 1 - Growth", "Regular Plan", "10.5000", "02-Jan-2015"),
    _hist_row(900001, "Halcyon Fixed Term Plan Series 1 - Growth", "Regular Plan", "10.5100", "05-Jan-2015"),
    _hist_row(900001, "Halcyon Fixed Term Plan Series 1 - Growth", "Regular Plan", "10.5200", "15-Jan-2015"),
    _hist_row(900002, "Halcyon Fixed Term Plan Series 2 - Growth", "", "11.0000", "02-Jan-2015"),
    _hist_row(900002, "Halcyon Fixed Term Plan Series 2 - Growth", "", "N.A.", "30-Mar-2015"),
    _hist_row(900003, "Halcyon Fixed Term Plan Series 3 - Growth", "Regular Plan", "12.0000", "02-Jan-2015"),
    _hist_row(900003, "Halcyon Fixed Term Plan Series 3 - Growth", "Regular Plan", "12.0100", "31-Mar-2015"),
)
W_START, W_END = date(2015, 1, 1), date(2015, 3, 31)


# --- parser: closed / merged / interval sections ---------------------------------------------------------------------


def test_close_ended_section_rows_parse_with_their_type() -> None:
    res = _parse_hist(CLOSED_WINDOW)
    assert res.report.rows_ok == 6
    assert {r.scheme_type for r in res.records} == {"Close Ended Schemes"}
    assert {r.category for r in res.records} == {"Income"}


def test_na_nav_after_closure_is_rejected_per_row_not_file() -> None:
    res = _parse_hist(CLOSED_WINDOW)
    assert res.report.rows_rejected == 1
    assert res.report.rejections[0].reason == "NAV_NOT_AVAILABLE"


def test_interval_and_legacy_amc_sections_parse() -> None:
    content = _history(
        "Interval Fund Schemes ( Income )",
        _hist_row(900010, "Halcyon Interval Fund - Growth", "Regular Plan", "15.1", "02-Jan-2015"),
        amc="Halcyon Trustee Company (merged)",
    )
    res = _parse_hist(content)
    assert res.report.rows_ok == 1
    assert res.records[0].scheme_type == "Interval Fund Schemes"
    assert any("AMC_NAME_UNUSUAL" in w for w in res.report.warnings)


def test_spans_keep_dates_and_counts_but_no_nav_values() -> None:
    spans = history_spans([_parse_hist(CLOSED_WINDOW)])
    assert sorted(spans) == [900001, 900002, 900003]
    s1 = spans[900001]
    assert (s1.first_date, s1.last_date, s1.n_observations) == (date(2015, 1, 2), date(2015, 1, 15), 3)
    assert s1.scheme_type == "Close Ended Schemes" and s1.plan == "Regular Plan"
    assert spans[900002].n_observations == 1  # the N.A. row was rejected, so it does not extend the span
    assert not hasattr(s1, "value") and not hasattr(s1, "nav")


def test_spans_merge_windows_and_take_latest_context() -> None:
    early = _history("Open Ended Schemes ( Index Funds )", _hist_row(900020, "Old Name", "", "10", "02-Jan-2012"))
    late = _history(
        "Open Ended Schemes ( Index Funds )", _hist_row(900020, "New Name", "Regular Plan", "20", "02-Jan-2014")
    )
    spans = history_spans([_parse_hist(late), _parse_hist(early)])
    s = spans[900020]
    assert (s.first_date, s.last_date, s.n_observations, s.n_pre_direct) == (date(2012, 1, 2), date(2014, 1, 2), 2, 1)
    assert s.plan == "Regular Plan"
    assert s.labels == (LABEL_REGULAR_PRE_2013,)


def test_ceased_and_started_flags() -> None:
    spans = history_spans([_parse_hist(CLOSED_WINDOW)])
    assert window_flags(spans[900001], window_start=W_START, window_end=W_END) == (FLAG_CEASED,)
    assert window_flags(spans[900002], window_start=W_START, window_end=W_END) == (FLAG_CEASED,)
    assert window_flags(spans[900003], window_start=W_START, window_end=W_END) == ()
    assert window_flags(spans[900003], window_start=date(2014, 12, 1), window_end=W_END) == (FLAG_STARTED,)
    with pytest.raises(ValueError, match="window_start"):
        window_flags(spans[900003], window_start=W_END, window_end=W_START)


# --- earliest NAV date per role --------------------------------------------------------------------------------------


def _spans_for_role():
    reg = _history(
        "Open Ended Schemes ( Other Scheme - Index Funds )",
        _hist_row(900031, "Halcyon Index Fund - Growth", "", "10.0", "03-Apr-2006"),
        _hist_row(900031, "Halcyon Index Fund - Growth", "Regular Plan", "40.0", "02-Jan-2013"),
    )
    direct = _history(
        "Open Ended Schemes ( Other Scheme - Index Funds )",
        _hist_row(900032, "Halcyon Index Fund - Direct Plan - Growth", "Direct Plan", "41.0", "02-Jan-2013"),
        _hist_row(900033, "Halcyon Momentum Index Fund - Direct Plan - Growth", "Direct Plan", "10", "01-Mar-2021"),
    )
    return history_spans([_parse_hist(reg), _parse_hist(direct)])


def test_earliest_per_role_uses_regular_twin_and_labels_pre_2013() -> None:
    spans = _spans_for_role()
    bindings = {"index_fund.nifty50": [900032, 900031], "index_fund.momentum": [900033], "gilt": [900099]}
    out = earliest_nav_date_per_role(spans, bindings, searched_from=date(2006, 1, 1))
    n50 = out["index_fund.nifty50"]
    assert (n50.scheme_code, n50.earliest_date, n50.status) == (900031, date(2006, 4, 3), EarliestStatus.VERIFIED)
    assert n50.labels == (LABEL_REGULAR_PRE_2013,)
    mom = out["index_fund.momentum"]
    assert mom.earliest_date == date(2021, 3, 1) and mom.labels == ()
    assert out["gilt"].status is EarliestStatus.NO_DATA and out["gilt"].earliest_date is None
    assert list(out) == sorted(bindings)


def test_earliest_is_not_verified_without_an_earlier_search() -> None:
    spans = _spans_for_role()
    for searched_from in (None, date(2006, 4, 3), date(2007, 1, 1)):
        out = earliest_nav_date_per_role(spans, {"r": [900031]}, searched_from=searched_from)
        assert out["r"].status is EarliestStatus.NOT_VERIFIED


def test_direct_plans_start_constant() -> None:
    assert DIRECT_PLANS_START == date(2013, 1, 1)


# --- scheme master: type → tp, status from NAVAll ---------------------------------------------------------------------


def _master_row(code: int, stype: str, launch: str, closure: str) -> bytes:
    return (
        f"Halcyon AMC Limited,{code},Halcyon Synthetic Scheme {code},{stype},Income,"
        f"Halcyon Synthetic Scheme {code} - Growth,5000,{launch},{closure},"
    ).encode()


def _parse_master(*rows: bytes):
    content = b"\r\n".join([SCHEME_MASTER_HEADER.encode(), *rows]) + b"\r\n"
    payload = make_payload("amfi.schememaster", content, SCHEMEDATA_URL, SCHEMEDATA_RETRIEVED, content_type="text/csv")
    return parse_scheme_master(payload)


def test_history_tp_from_scheme_type() -> None:
    res = _parse_master(
        _master_row(900041, "Open Ended", "01-Jan-2010", "01-Jan-2010"),
        _master_row(900042, "Close Ended", "01-Jan-2014", "15-Jan-2014"),
        _master_row(900043, "Interval Fund", "01-Jan-2014", "15-Jan-2014"),
        _master_row(900044, "Something New", "01-Jan-2014", "15-Jan-2014"),
        _master_row(900045, "", "01-Jan-2014", ""),
    )
    assert [history_tp(r) for r in res.records] == [1, 2, 3, None, None]


def test_closure_date_is_not_a_wind_up_signal() -> None:
    # Open-ended scheme whose "Closure Date" equals its launch date (the NFO close): still LIVE by NAVAll.
    res = _parse_master(_master_row(900041, "Open Ended", "01-Jan-2010", "01-Jan-2010"))
    navall = _parse_navall(_navall(_navall_row(900041, "12.5", "14-Oct-2026")))
    assert res.records[0].closure_date == date(2010, 1, 1)
    status = classify_scheme_status([r.scheme_code for r in res.records], latest_nav_dates(navall))
    assert status == {900041: SchemeStatus.LIVE}


def test_classify_status_live_dormant_not_published() -> None:
    navall = _parse_navall(
        _navall(
            _navall_row(900051, "10.0", "14-Oct-2026"),
            _navall_row(900052, "10.0", "13-Sep-2026"),  # 31 days stale
            _navall_row(900053, "10.0", "14-Sep-2026"),  # exactly 30 days: still live
            _navall_row(900054, "10.0", "15-Sep-2017"),
        )
    )
    dates = latest_nav_dates(navall)
    out = classify_scheme_status([900054, 900051, 900052, 900053, 900055, 900051], dates)
    assert out == {
        900051: SchemeStatus.LIVE,
        900052: SchemeStatus.DORMANT,
        900053: SchemeStatus.LIVE,
        900054: SchemeStatus.DORMANT,
        900055: SchemeStatus.NOT_PUBLISHED,
    }
    assert list(out) == sorted(out)


def test_classify_status_refuses_without_navall() -> None:
    with pytest.raises(ValueError, match="NAVAll"):
        classify_scheme_status([900051], {})
    with pytest.raises(ValueError, match="stale_after_days"):
        classify_scheme_status([900051], {900051: date(2026, 10, 14)}, stale_after_days=-1)


# --- probe script (pure logic + offline end-to-end with synthetic payloads) -------------------------------------------


def _load_probe() -> ModuleType:
    path = Path(__file__).resolve().parents[2] / "scripts" / "probe_amfi_closed.py"
    spec = importlib.util.spec_from_file_location("probe_amfi_closed", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


probe = _load_probe()


def test_plan_windows_are_contiguous_and_accepted_by_the_request_builder() -> None:
    wins = probe.plan_windows(date(2006, 4, 1), date(2007, 4, 1))
    assert wins[0][0] == date(2006, 4, 1) and wins[-1][1] == date(2007, 4, 1)
    for (_, e1), (s2, _) in itertools.pairwise(wins):
        assert (s2 - e1).days == 1
    for s, e in wins:
        assert 0 <= (e - s).days <= MAX_HISTORY_WINDOW_DAYS
        navhistory_request(mf_id=1, tp=1, from_date=s, to_date=e)  # must not raise
    assert probe.plan_windows(date(2020, 1, 1), date(2020, 1, 1)) == [(date(2020, 1, 1), date(2020, 1, 1))]
    with pytest.raises(ValueError):
        probe.plan_windows(date(2020, 1, 2), date(2020, 1, 1))


@pytest.mark.parametrize("first", [0, 1, 5, 12, 29])
def test_find_first_window_binary_search(first: int) -> None:
    calls: list[int] = []

    def has_rows(k: int) -> bool:
        calls.append(k)
        return k >= first

    assert probe.find_first_window(30, has_rows) == first
    assert len(calls) <= 7
    if first > 0:
        assert first - 1 in calls  # the window before the answer was searched and was empty


def test_find_first_window_none_when_absent() -> None:
    assert probe.find_first_window(10, lambda _k: False) is None
    assert probe.find_first_window(0, lambda _k: True) is None


def _navall_today():
    return _parse_navall(_navall(_navall_row(900003, "12.5", "14-Oct-2026"), _navall_row(900002, "9.0", "15-Sep-2017")))


def test_survivorship_summary_verified_when_gone_schemes_appear() -> None:
    hist = {2: [_parse_hist(CLOSED_WINDOW)]}
    s = probe.survivorship_summary(hist, _navall_today(), None, window_start=W_START, window_end=W_END)
    assert s.answer == "VERIFIED"
    assert s.counts["history_codes"] == 3
    assert s.counts["history_codes_tp2"] == 3 and s.counts["history_codes_tp1"] == 0
    assert s.counts["history_codes_gone_today_tp2"] == 2 and s.counts["history_codes_gone_today_tp1"] == 0
    assert s.counts["history_codes_live_today"] == 1
    assert s.counts["history_codes_dormant_today"] == 1
    assert s.counts["history_codes_absent_from_navall"] == 1
    assert s.counts["history_codes_ceased_in_window"] == 2
    assert s.counts["history_rows_rejected"] == 1
    assert "master_codes" not in s.counts


def test_survivorship_summary_not_verified_when_all_live_or_empty() -> None:
    live_only = _history(
        "Close Ended Schemes ( Income )", _hist_row(900003, "Halcyon FTP 3 - Growth", "", "12.0", "02-Jan-2015")
    )
    s = probe.survivorship_summary(
        {2: [_parse_hist(live_only)]}, _navall_today(), None, window_start=W_START, window_end=W_END
    )
    assert s.answer == "NOT VERIFIED"
    empty = probe.survivorship_summary({}, _navall_today(), None, window_start=W_START, window_end=W_END)
    assert empty.answer == "NOT VERIFIED" and empty.counts["history_codes"] == 0


def test_render_counts_holds_no_scheme_codes_or_navs() -> None:
    hist = {2: [_parse_hist(CLOSED_WINDOW)]}
    s = probe.survivorship_summary(hist, _navall_today(), None, window_start=W_START, window_end=W_END)
    text = probe.render_counts(s, window_start=W_START, window_end=W_END, mf=1)
    assert "VERIFIED" in text
    for forbidden in ("900001", "900002", "900003", "10.5", "12.0", "Halcyon"):
        assert forbidden not in text


def _fake_fetch(responses: dict[str, bytes | None], seen: list[str]):
    def fetch(req: SourceRequest) -> RawPayload | None:
        seen.append(req.url)
        for key, body in responses.items():
            if key in req.url:
                if body is None:
                    return None
                ctype = "text/csv" if "SchemeData" in req.url else "text/plain"
                return RawPayload.from_bytes(
                    source_id=req.source.id,
                    final_url=req.url.replace("www.amfiindia.com/spages", "portal.amfiindia.com/spages"),
                    retrieved_at=NAVHISTORY_RETRIEVED,
                    content=body,
                    content_type=ctype,
                )
        raise AssertionError(f"unexpected request {req.url}")

    return fetch


def test_run_survivorship_offline_end_to_end() -> None:
    master = b"\r\n".join([SCHEME_MASTER_HEADER.encode(), _master_row(900003, "Close Ended", "01-Jan-2014", "")])
    seen: list[str] = []
    fetch = _fake_fetch(
        {
            "NAVAll": _navall(_navall_row(900003, "12.5", "14-Oct-2026")),
            "SchemeData": master + b"\r\n",
            "tp=1": None,
            "tp=2": CLOSED_WINDOW,
            "tp=3": None,
        },
        seen,
    )
    s = probe.run_survivorship(fetch, mf=1, window_start=W_START, window_end=W_END)
    assert s.answer == "VERIFIED"
    assert s.counts["master_codes"] == 1
    assert s.counts["history_codes_absent_from_master"] == 2
    assert s.counts["history_codes_absent_from_navall"] == 2
    assert sum("DownloadNAVHistoryReport" in u for u in seen) == 3


def test_run_earliest_offline_binary_search() -> None:
    # Synthetic role scheme 900031 publishes from 2006-04-03 on; windows before that hold only another scheme.
    first = date(2006, 4, 3)

    def fetch(req: SourceRequest) -> RawPayload | None:
        q = dict(part.split("=") for part in req.url.split("?")[1].split("&"))
        start = _amfi(q["frmdt"])
        end = _amfi(q["todt"])
        row_day = max(start, first)
        rows = [_hist_row(900099, "Other Fund - Growth", "", "10", _fmt(start))]
        if row_day <= end:
            rows.append(_hist_row(900031, "Halcyon Index Fund - Growth", "", "10", _fmt(row_day)))
        body = _history("Open Ended Schemes ( Index Funds )", *rows)
        return RawPayload.from_bytes(
            source_id=req.source.id,
            final_url=req.url,
            retrieved_at=NAVHISTORY_RETRIEVED,
            content=body,
            content_type="text/plain",
        )

    roles = {"index_fund.nifty50": probe.RoleBinding(mf=1, tp=1, codes=(900031,))}
    out = probe.run_earliest(fetch, roles, since=date(2005, 1, 1), until=date(2010, 1, 1))
    assert len(out) == 1
    assert out[0].earliest_date == first
    assert out[0].status is EarliestStatus.VERIFIED
    assert out[0].labels == (LABEL_REGULAR_PRE_2013,)
    missing = probe.run_earliest(
        fetch, {"r": probe.RoleBinding(mf=1, tp=1, codes=(900077,))}, since=date(2005, 1, 1), until=date(2006, 1, 1)
    )
    assert missing[0].status is EarliestStatus.NO_DATA


def test_load_roles_validates(tmp_path: Path) -> None:
    good = tmp_path / "roles.json"
    good.write_text('{"r": {"mf": 1, "tp": 1, "codes": [900031, 900032]}}', encoding="utf-8")
    assert probe.load_roles(good) == {"r": probe.RoleBinding(1, 1, (900031, 900032))}
    for bad in ("{}", '{"r": {"mf": 1, "tp": 1, "codes": []}}', '{"r": {"mf": "x", "tp": 1, "codes": [1]}}'):
        good.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError):
            probe.load_roles(good)


_MON = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _fmt(d: date) -> str:
    return f"{d.day:02d}-{_MON[d.month - 1]}-{d.year}"


def _amfi(text: str) -> date:
    day, mon, year = text.split("-")
    return date(int(year), _MON.index(mon) + 1, int(day))
