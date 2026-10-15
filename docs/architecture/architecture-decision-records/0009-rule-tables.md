# ADR-0009: Versioned tax and regulatory rule tables

## Decision
- Tax rules are data, not code: `rules/tax/*.yaml`. Each rule has:
  - `rule_id`, `act` (ITA1961 | ITA2025) and section numbers (old and new);
  - `instrument_class`, conditions, holding-period threshold, rate, exemption;
  - `effective_from`, `effective_to`;
  - `source_url`, `verification_status` (P | S | NV).
- The engine selects rules by the **transaction date**. If more than one rule matches, or none does, the engine abstains.
- Results computed under an `NV` rule are labelled "unverified tax assumption".
- MF category rename mapping (SEBI, 26-Feb-2026) and expense regime (TER → Base Expense Ratio from 1-Apr-2026) are rule tables too.
- The Compliance Guard phrase list is a versioned rule table.

## Evidence
indian-instruments-and-tax.md (tax rule table; 13 CA questions); regulatory-readiness.md (banned phrases).
