"""Investor profile: the minimum suitability inputs (requirements.md §3.2) and the mode rule.

Personalised mode requires ALL critical inputs 1–5. Anything missing → EXPLORATION (no personalised ranking).
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from iip.engine.ranking import CREDIT_SCALE, Objective
from iip.store.db import write_tx

PROFILE_ID = "default"
SURCHARGE_BANDS = frozenset({Decimal("0"), Decimal("0.10"), Decimal("0.15"), Decimal("0.25")})
ILLUSTRATIVE_AMOUNT = Decimal("100000")
ILLUSTRATIVE_HORIZON_DAYS = 182


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: Decimal | None = Field(default=None, gt=0, le=Decimal("1000000000000"))  # ≤ ₹1 lakh crore
    withdrawal_date: date | None = None
    objective: Objective | None = None
    loss_acceptable: bool | None = None
    max_loss_fraction: Decimal | None = Field(default=None, ge=0, le=1)
    early_need: Literal["unlikely", "possible", "likely"] | None = None
    max_days_to_cash: int | None = Field(default=None, ge=0, le=3650)
    credit_floor: str | None = None
    excluded_kinds: list[Literal["mf_scheme", "tbill", "gsec", "sdl", "corp_bond", "fd", "small_savings"]] = []
    exclude_nbfc_deposits: bool = True
    tax_regime: Literal["new", "old"] | None = None
    slab_rate: Decimal | None = Field(default=None, ge=0, le=Decimal("0.5"))
    # New-regime surcharge band on total income (0 below ₹50 lakh; 10 % / 15 % / 25 % above ₹50 L / ₹1 Cr / ₹2 Cr).
    surcharge_rate: Decimal | None = None
    return_aspiration: Decimal | None = Field(default=None, ge=0, le=5)  # stated aspiration, never an optimiser target

    @field_validator("credit_floor")
    @classmethod
    def _floor(cls, v: str | None) -> str | None:
        if v is not None and v not in CREDIT_SCALE:
            raise ValueError(f"unknown credit floor; use one of {CREDIT_SCALE}")
        return v

    @field_validator("surcharge_rate")
    @classmethod
    def _surcharge_band(cls, v: Decimal | None) -> Decimal | None:
        if v is not None and v not in SURCHARGE_BANDS:
            raise ValueError("surcharge_rate must be one of the new-regime bands 0, 0.10, 0.15 or 0.25")
        return v

    @field_validator("amount", "max_loss_fraction", "slab_rate", "return_aspiration", "surcharge_rate", mode="before")
    @classmethod
    def _no_floats(cls, v: object) -> object:
        if isinstance(v, float):
            raise ValueError("send decimals as strings, not floats")
        return v

    @model_validator(mode="after")
    def _consistency(self) -> Profile:
        if self.loss_acceptable is False and self.max_loss_fraction not in (None, Decimal(0)):
            raise ValueError("max_loss_fraction must be 0 or empty when principal loss is not acceptable")
        if self.objective in (Objective.GROWTH, Objective.AGGRESSIVE_GROWTH) and self.loss_acceptable is False:
            raise ValueError("growth objectives require accepting some loss; choose objective A, B or C instead")
        return self


class ProfileStatus(BaseModel):
    profile: Profile
    mode: Literal["PERSONALISED", "EXPLORATION"]
    missing: list[str]
    horizon_days: int | None
    conflicts: list[str]


CRITICAL = (
    ("amount", "Investable amount"),
    ("withdrawal_date", "Required withdrawal date"),
    ("objective", "Objective (A–E)"),
    ("loss_acceptable", "Whether a principal loss is acceptable"),
    ("early_need", "Whether the money may be needed early"),
)

_CONFLICT_PRESERVING = (
    "CONSTRAINT_CONFLICT: a high return aspiration is incompatible with a capital-preservation or liquidity objective. "
    "Instruments that historically preserved capital over short horizons have not delivered returns of that size. "
    "See Return-Target Feasibility."
)
_CONFLICT_SHORT = (
    "CONSTRAINT_CONFLICT: aiming for a high annual return over less than 12 months requires market-linked risk with a "
    "material historical frequency of loss at this horizon."
)


def evaluate(profile: Profile, as_of: date) -> ProfileStatus:
    missing = [label for field, label in CRITICAL if getattr(profile, field) is None]
    conflicts: list[str] = []
    horizon: int | None = None
    if profile.withdrawal_date is not None:
        horizon = (profile.withdrawal_date - as_of).days
        if horizon <= 0:
            missing.append("Withdrawal date must be in the future")
            horizon = None
    if profile.loss_acceptable and profile.max_loss_fraction is None:
        missing.append("Maximum acceptable loss (needed when loss is acceptable)")
    if profile.objective in (Objective.GROWTH, Objective.AGGRESSIVE_GROWTH) and profile.max_loss_fraction is None:
        missing.append("Explicit loss budget (required for growth objectives)")
    if profile.return_aspiration is not None and horizon is not None:
        preserving = profile.objective in (Objective.CAPITAL_PRESERVATION, Objective.LIQUIDITY)
        if preserving and profile.return_aspiration > Decimal("0.10"):
            conflicts.append(_CONFLICT_PRESERVING)
        if horizon < 365 and profile.return_aspiration >= Decimal("0.15"):
            conflicts.append(_CONFLICT_SHORT)
    mode: Literal["PERSONALISED", "EXPLORATION"] = "EXPLORATION" if missing else "PERSONALISED"
    return ProfileStatus(profile=profile, mode=mode, missing=missing, horizon_days=horizon, conflicts=conflicts)


def load(conn: sqlite3.Connection) -> Profile:
    row = conn.execute("SELECT data_json FROM profiles WHERE profile_id = ?", (PROFILE_ID,)).fetchone()
    return Profile.model_validate_json(row["data_json"]) if row else Profile()


def save(conn: sqlite3.Connection, profile: Profile, at: str) -> None:
    data = profile.model_dump_json()
    with write_tx(conn):
        conn.execute(
            "INSERT INTO profiles(profile_id, data_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(profile_id) DO UPDATE SET data_json = excluded.data_json, updated_at = excluded.updated_at",
            (PROFILE_ID, data, at),
        )
        conn.execute(
            "INSERT INTO audit_events(at, action, subject, detail) VALUES (?, 'profile.update', 'profile', ?)",
            (at, json.dumps(sorted(k for k, v in profile.model_dump().items() if v not in (None, [])))),
        )
