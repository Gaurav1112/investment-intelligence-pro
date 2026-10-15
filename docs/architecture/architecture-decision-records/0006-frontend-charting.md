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

## Amendment (2026-10-15, during Stage G)
- **Radix replaced by native elements.**
  - Radix Dialog's scroll-lock dependency (`react-remove-scroll`/`react-style-singleton`) injects a runtime `<style>` element. Our CSP
    (`style-src 'self'`, threat-model C-05) blocks that, so it would cause CSP violations.
  - The Explain drawer and other dialogs therefore use the native HTML `<dialog>` element. It provides focus trapping, `Esc` and an inert
    background, with no dependency.
  - Tabs, disclosure and menus are small in-house components following WAI-ARIA Authoring Practices.
  - React's `style={{…}}` is applied through CSSOM (`element.style.*`), which CSP permits. Stylesheets come only from the Vite bundle.
- **Fonts.** `@fontsource-variable/inter` (OFL-1.1) is bundled. No CDN.
- **TanStack Table removed.**
  - On re-audit, v8 pins were superseded and v9.3.1 introduced a new feature-registration API.
  - Our tables are small: hundreds of rows, sorting, keyboard row navigation, `aria-sort`. A ~150-line in-house `DataTable` is easier
    to audit and test than a large headless dependency, and it reduces supply-chain surface.
- **Dependency versions.** The initial pins (from memory) had 24 known advisories (3 critical: vitest/tinypool; high: vite,
  react-router). All were upgraded to current releases on 2026-10-15, and `pnpm audit` now reports 0 known vulnerabilities. `pnpm audit` is part of `make check`.
