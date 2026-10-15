# Implementation Rules (binding for every contributor and agent)

1. **Spec first.** Implement exactly what the methodology documents specify (`docs/finance/*`, `docs/forecasting/*`,
   `docs/research/*`). If the spec is ambiguous or wrong, do not guess. Record it under "Spec issues" in your report, and choose the
   conservative behaviour (raise or abstain).
2. **TDD.** Write the fixture tests from the spec's worked examples first, see them fail, then implement.
   Tests must never be weakened to pass.
3. **Independent cross-check.** Every critical formula gets an oracle test in `backend/tests/oracle/` (marked
   `@pytest.mark.oracle`) against QuantLib, pyxirr, scipy, numpy or scoringrules. Never test a function only against itself.
4. **Purity.** `backend/src/iip/engine/**` must contain no I/O, no clock (`date.today()`, `datetime.now()`), no network, no
   `random`, and no `os`. Randomness only comes from `numpy.random.default_rng(seed)` with an explicit seed parameter. Dates are passed in.
   `tests/unit/test_engine_purity.py` enforces this.
5. **Money.** Use `iip.engine.money` (`D`, `engine_context`, `money`, `rate_display`, `from_float`). Run Decimal arithmetic inside
   `with engine_context():`. Never use `Decimal(float)`. Floats are allowed only in `engine/stats/**`, `engine/forecasting/**` and
   inside root solvers; convert back through `from_float`.
6. **Errors.** Raise the typed errors in `iip.engine.errors`. Never return a silently degraded number such as 0, NaN, or a forward-filled value.
7. **Results are explainable.** Public engine functions return frozen dataclasses that carry, where relevant: the value,
   the inputs used, the convention or day count, the formula id (e.g. `"CAGR@1"`), warnings (e.g. `ANNUALISED_FROM_SHORT_PERIOD`), and
   flags. Formula ids are versioned strings.
8. **Types and style.** Code must pass `mypy --strict` and ruff (config in `backend/pyproject.toml`). Use Python 3.12 syntax.
   Match the existing style in `engine/money.py` and `engine/dates.py`.
9. **Ownership.** Edit only the files assigned to you. Do **not** edit `pyproject.toml`, `uv.lock`, or other agents'
   files. If you need a dependency, report it instead of adding it. Do **not** run `git commit`.
10. **Commands** (run from `backend/`): `.venv/bin/pytest -q tests/<yours>`, `.venv/bin/ruff check src tests`,
    `.venv/bin/ruff format src/<yours> tests/<yours>`, `.venv/bin/mypy`.
11. **No fabricated data.** Test fixtures are hand-computed from the spec, or synthetic files that copy the layout recorded in `docs/data/probes/README.md` (no real third-party data is committed). Never invent
    market values and present them as real.
12. **Report.** Finish with: files created, test counts (pass/fail, from an actual run), oracle agreement tolerances, spec issues
    found, and anything left unimplemented, labelled `IMPLEMENTED, NOT VERIFIED` or `BLOCKED`.
