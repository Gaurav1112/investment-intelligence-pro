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
