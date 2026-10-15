# ADR-0002: Money, precision and rounding

## Decision
- Decimal context: precision **34**, traps on `InvalidOperation` and `DivisionByZero`. Intermediate values are never rounded.
- **INR amounts** (display and ledger): quantise to 0.01 using `ROUND_HALF_UP`, which matches bank and AMC statements.
- **Rates, ratios and statistics**: `ROUND_HALF_EVEN` at the display boundary only.
- **Counterparty-replicating calculations** (stamp duty, allotted units, FD maturity): round at the same step and in the same mode as the counterparty documents.
- Floats are allowed only in `engine/stats/*` and inside root solvers (YTM, XIRR). Every float root is re-verified in Decimal: NPV at the root must be within a tolerance; if not, the result is "no solution".
- NAVs are parsed from source strings directly into Decimal. Floats are never an intermediate step.
- Every calculation function is pure: no clock, no randomness and no I/O. Dates are passed in explicitly. Bootstrap randomness uses an explicit seed recorded in the run.

## Evidence
calculation-methodology.md §1. Probes show NAVs with 0–8 decimal places and mfapi.in padding to 5 decimals (source-registry.md).
