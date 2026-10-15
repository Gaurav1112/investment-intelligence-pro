# ADR-0011: Independent test oracles

## Decision
- A dev-only dependency group `oracle`: QuantLib 1.44, pyxirr, scipy, scoringrules, and (optionally) nci/scores. Runtime code never imports them; this is enforced by a test that scans imports.
- Every critical formula has (a) hand-computed fixtures from the methodology documents and (b) a cross-check against an oracle.
- GPL tools (bond_pricing) are used only out-of-tree for manual cross-checks.

## Evidence
reference-selection.md §4; hidden-gems.md.
