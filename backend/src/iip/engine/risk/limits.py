"""L4 concentration and default limits — ``risk.limits@1`` (design-risk-first.md §5.5).

| Limit                     | Formula                                   | Default                                   |
|---------------------------|-------------------------------------------|-------------------------------------------|
| Single scheme             | MV_scheme / V_total ≤ c_scheme            | PARAMETER, user-set                       |
| Single AMC                | Σ MV_amc / V_total ≤ c_amc                | PARAMETER                                 |
| Sector or thematic        | Σ MV_sector / V_total ≤ c_theme           | PARAMETER                                 |
| Factor sleeve (U3)        | Σ MV_factor / V_equity ≤ c_factor         | PARAMETER                                 |
| Bank deposits             | Σ deposit per bank > ₹5,00,000            | statutory DICGC cover (deposits engine)   |
| Uninsured single issuer   | exposure_issuer / V_total ≤ c_issuer      | PARAMETER; exposure only, no loss number  |

A breach is an ``ACTION`` (it does not suppress lower layers).  A limit whose parameter is not set abstains with
REQUIRES CONFIGURATION; the engine never invents a default cap.  Nothing here proposes a sale.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from iip.engine.deposits import ABOVE_LIMIT, DICGC_LIMIT, DepositHolding, dicgc_coverage
from iip.engine.errors import InvalidInput
from iip.engine.money import ONE, ZERO, engine_context
from iip.engine.risk import EQUITY_CLASSES, Abstention, Outcome, RiskClass, Status, combine_outcomes

RULE_ID = "risk.limits@1"


class LimitKind(StrEnum):
    SCHEME = "SCHEME"
    AMC = "AMC"
    THEME = "THEME"
    FACTOR = "FACTOR"
    ISSUER = "ISSUER"
    BANK_DEPOSIT = "BANK_DEPOSIT"


@dataclass(frozen=True)
class LimitHolding:
    holding_id: str
    risk_class: RiskClass
    market_value: Decimal
    scheme_id: str | None = None
    amc: str | None = None
    theme: str | None = None  # sector or thematic label
    is_factor: bool = False
    uninsured_issuer: str | None = None  # NBFC/corporate FD or bond issuer; None when not applicable


@dataclass(frozen=True)
class LimitParams:
    """User-set caps (fractions).  None = not configured → that limit abstains."""

    c_scheme: Decimal | None = None
    c_amc: Decimal | None = None
    c_theme: Decimal | None = None
    c_factor: Decimal | None = None
    c_issuer: Decimal | None = None


@dataclass(frozen=True)
class LimitFinding:
    kind: LimitKind
    key: str  # scheme id, AMC, theme, issuer, bank id or "factor"
    exposure: Decimal  # ₹
    share: Decimal | None  # exposure / base; None for the ₹ deposit rule
    cap: Decimal  # fraction, or ₹ for BANK_DEPOSIT
    outcome: Outcome  # ACTION


@dataclass(frozen=True)
class LimitsResult:
    outcome: Outcome  # ACTION > ABSTAIN > PASS
    total_value: Decimal
    equity_value: Decimal
    findings: tuple[LimitFinding, ...]
    abstentions: tuple[Abstention, ...]
    status: Status
    rule_id: str = RULE_ID


def _check_cap(name: str, cap: Decimal | None) -> None:
    if cap is not None and not (ZERO < cap <= ONE):
        raise InvalidInput(f"{name} must be a fraction in (0, 1]")


def _group(holdings: Sequence[LimitHolding], key_of: str) -> dict[str, Decimal]:
    out: dict[str, Decimal] = {}
    with engine_context():
        for h in holdings:
            key = getattr(h, key_of)
            if key is not None:
                out[key] = out.get(key, ZERO) + h.market_value
    return out


def check_limits(
    holdings: Sequence[LimitHolding],
    params: LimitParams,
    *,
    deposits: Sequence[DepositHolding] = (),
    as_of: date | None = None,
) -> LimitsResult:
    for name in ("c_scheme", "c_amc", "c_theme", "c_factor", "c_issuer"):
        _check_cap(name, getattr(params, name))
    for h in holdings:
        if h.market_value < 0:
            raise InvalidInput(f"holding {h.holding_id!r}: market value must be ≥ 0")
    with engine_context():
        total = sum((h.market_value for h in holdings), ZERO)
        equity = sum((h.market_value for h in holdings if h.risk_class in EQUITY_CLASSES), ZERO)

    findings: list[LimitFinding] = []
    abstentions: list[Abstention] = []

    def share_limit(kind: LimitKind, cap: Decimal | None, groups: dict[str, Decimal], base: Decimal) -> None:
        if not groups or base == 0:
            return
        if cap is None:
            abstentions.append(
                Abstention(
                    code="limit_not_configured",
                    missing_input=f"{kind.value.lower()} limit",
                    how_to_fix=f"set your maximum share for a single {kind.value.lower()} in Settings",
                )
            )
            return
        with engine_context():
            for key, exposure in sorted(groups.items()):
                share = exposure / base
                if share > cap:
                    findings.append(LimitFinding(kind, key, exposure, share, cap, Outcome.ACTION))

    share_limit(LimitKind.SCHEME, params.c_scheme, _group(holdings, "scheme_id"), total)
    share_limit(LimitKind.AMC, params.c_amc, _group(holdings, "amc"), total)
    share_limit(LimitKind.THEME, params.c_theme, _group(holdings, "theme"), total)
    with engine_context():
        factor = sum((h.market_value for h in holdings if h.is_factor and h.risk_class in EQUITY_CLASSES), ZERO)
    share_limit(LimitKind.FACTOR, params.c_factor, {"factor": factor} if factor > 0 else {}, equity)
    share_limit(LimitKind.ISSUER, params.c_issuer, _group(holdings, "uninsured_issuer"), total)

    if deposits:
        if as_of is None:
            raise InvalidInput("as_of is required to check deposit insurance cover")
        cover = dicgc_coverage(deposits, as_of=as_of)
        for g in cover.groups:
            if ABOVE_LIMIT in g.flags:
                findings.append(
                    LimitFinding(LimitKind.BANK_DEPOSIT, g.institution_id, g.total, None, DICGC_LIMIT, Outcome.ACTION)
                )

    outcome = combine_outcomes(
        [f.outcome for f in findings] + [Outcome.ABSTAIN] * bool(abstentions),
        precedence=(Outcome.ACTION, Outcome.ABSTAIN),
    )
    return LimitsResult(
        outcome=outcome,
        total_value=total,
        equity_value=equity,
        findings=tuple(findings),
        abstentions=tuple(abstentions),
        status=Status.REQUIRES_CONFIGURATION if abstentions else Status.VERIFIED,
    )
