# ADR-0006: Frontend components and charting

## Decision
- **Components:** Radix primitives, with shadcn/ui patterns copied into the repository (MIT).
- **Tables:** TanStack Table.
- **Charts:**
  - Recharts for standard time series and bars.
  - Hand-built SVG React components using `d3-scale` for the quantile dot plot (20 dots), the fan chart and the drawdown chart.
  - ECharts is deferred; lightweight-charts is excluded.
- **Fonts:** self-hosted Inter with tabular numerals (verify the ₹ glyph; the fallback is the system font). No external CDNs, because of the CSP.
- **Number formatting:** Indian grouping (lakh/crore) using `Intl.NumberFormat('en-IN')`, with tests at the 99,999 / 1,00,000 / 99,99,999 / 1,00,00,000 boundaries.

## Evidence
ux-design.md §7; reference-selection.md §6.1 (conflict resolution); hidden-gems.md (bharatutils lakh/crore boundary bug).
