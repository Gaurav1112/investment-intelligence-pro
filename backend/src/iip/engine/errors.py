"""Typed engine errors. The engine never returns a silently-degraded number: it raises one of these."""

from __future__ import annotations


class EngineError(Exception):
    """Base class for all deterministic-engine errors."""

    code = "ENGINE_ERROR"


class InvalidInput(EngineError):
    code = "INVALID_INPUT"


class NumericalError(EngineError):
    """A solver failed verification, or NaN/Inf crossed the float→Decimal boundary."""

    code = "NUMERICAL_ERROR"


class StaleData(EngineError):
    code = "STALE_DATA"


class MissingData(EngineError):
    code = "MISSING_DATA"


class MissingDistributionData(MissingData):
    code = "MISSING_DISTRIBUTION_DATA"


class RuleNotFound(EngineError):
    """No versioned rule (tax, exit load, category) applies on the requested date."""

    code = "RULE_NOT_FOUND"


class AmbiguousRule(EngineError):
    code = "AMBIGUOUS_RULE"


class InsufficientHistory(EngineError):
    """Not enough clean observations to compute a metric honestly."""

    code = "INSUFFICIENT_HISTORY"


class DataGapsExceedGate(InsufficientHistory, InvalidInput):
    """validation-methodology §8 / risk-methodology §1 / feasibility §4.4.1: too many gaps (> 7 calendar days, or
    suspect month-end grid points) — more than 2 % — so the series is rejected. It is both "not enough clean history"
    (callers that refuse on InsufficientHistory refuse) and an invalid series (callers that reject InvalidInput do)."""

    code = "DATA_GAPS_EXCEED_GATE"
