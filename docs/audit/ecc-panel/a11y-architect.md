# a11y-architect review: frontend/src (WCAG 2.2 AA)

Scope: `frontend/src` pages, components, charts and styles. This was a read-only, static review. No browser or assistive-technology run was done.
`docs/operations/known-limitations.md` and `docs/audit/final-red-team-report.md` list no accessibility items, so nothing below repeats a known issue.

## What already works well

- There is a skip link, `main` has `tabIndex=-1`, and the nav groups are labelled.
- Focus is visible everywhere through the global `:focus-visible` outline in the accent colour. Reduced motion is respected.
- Freshness badges and certainty tiers use a glyph and a word, so meaning never rests on colour alone. Gains use ▲ and ▼ arrows as well as colour.
- The ExplainDrawer is a native modal `<dialog>`, and its heading takes focus when it opens.
- Almost every form control has a programmatic label. Field errors use `role="alert"`, and several flows (Alerts, Settings, CAS import, Watchlist) move focus to the result after an action.
- Design-token text pairs reach at least 4.5:1 in both themes (checked: subtle text on white is 5.76:1, on surface-2 5.14:1; dark subtle is 6.51:1).

## Findings (most severe first)

### A11Y-1 (high): Onboarding disables Save without saying why (WCAG 3.3.1, 3.3.3, 4.1.2)
- `pages/Onboarding.tsx:52`: `invalid` is true when the amount, loss % (`lossFr`), tax slab (`slabFr`) or return aspiration (`aspFr`) is invalid.
- `pages/Onboarding.tsx:266`: the Save button is then `disabled={save.pending || invalid}`.
- `pages/Onboarding.tsx:147`: the loss-% input sets `aria-invalid` but shows no error text, and its hint is not linked with `aria-describedby`.
- `pages/Onboarding.tsx:186` and `:207`: the slab and aspiration inputs set neither `aria-invalid` nor an error message.
- The review step (`:216-231`) does not show slab or aspiration at all.

**Scenario:** on step 4 a user types `30%` in the slab field. On step 5 (Review), Save is greyed out. Nothing on screen or in the accessibility tree says which field is wrong or that it sits on another step. A screen-reader user hears only "Save, dimmed". These are the risk-tolerance and tax inputs that personalise every ranking, so a user may give up and stay in exploration mode, or misread their saved state.

**Fix:**
- Keep Save enabled and validate on submit.
- List the errors in a `role="alert"` summary, with links that jump to the right step and field.
- Give each of these inputs `aria-invalid` and `aria-describedby` pointing at a visible message.

### A11Y-2 (medium): focus is lost when the focused control is removed (WCAG 2.4.3)
- `pages/Compare.tsx:237-241`: the "Select <name>" button calls `onPick` and then `setResults(null)`. The list and the focused button unmount, so focus falls to `<body>`.
- `pages/Compare.tsx:275`: `SinglePicker`'s "Change instrument" calls `onChange(null)` with no refocus. This is used on Risk (`pages/Risk.tsx:67`) and Scenarios (`pages/Scenarios.tsx:207`, `:474`). By contrast, Watchlist's own picker does refocus, at `pages/Watchlist.tsx:88`.
- `pages/Simulator.tsx:162`: "Remove <name>" deletes its own row and moves focus nowhere.
- `pages/MfExplorer.tsx:151` and `:165`: after a backfill or NAV fetch, `list.reload()` runs. `lib/useApi.ts` calls `setData(null)` on every reload, so the 500-row table becomes `<Loading>`, and the focused "Backfill history" button plus the scroll position are lost.

**Scenario:** a keyboard user picks a fund on Risk and presses Tab. They restart from the top of the document instead of reaching the horizon field. On Mutual funds, after backfilling row 200 they have to tab back through the whole table.

**Fix:**
- After each of these actions, move focus deliberately: to the new "Selected" region, the search input, the next row's Remove button, or the activity log.
- Alternatively, make `useApi.reload` keep the previous data while it refetches.

### A11Y-3 (medium): route changes are silent and every page has the same title (WCAG 2.4.2, 4.1.3)
- `index.html:7` hard-codes `<title>Investment Intelligence Pro</title>`, and nothing in `frontend/src` sets `document.title` (grep found 0 hits).
- `App.tsx:176-205` (`Shell`) only closes the mobile menu on a path change. Focus stays on the nav link, and nothing announces the new page.

**Scenario:** a screen-reader user activates "Risk" in the nav. They hear nothing new, and the browser tab or history entry for Risk, Compare and Discovery all read the same, which makes it easy to act on the wrong page.

**Fix:** on each `pathname` change:
- set `document.title` to `"<Page> · Investment Intelligence Pro"`;
- move focus to the page `<h1>` (or to `#main`).

### A11Y-4 (medium): DotPlot puts 20 focusable circles inside a `role="img"` SVG (WCAG 4.1.2, 2.4.3)
- `charts/DotPlot.tsx:41-45`: the `<svg role="img" aria-label=…>` element.
- `charts/DotPlot.tsx:77-89`: every `<circle>` has `tabIndex={0}` and its own `aria-label`.

Children of `role="img"` are presentational, so their labels are not exposed. A keyboard user gets one Tab stop per quantile (20 by default) per chart, and each is announced as nothing or as the whole image again. The figcaption's "Focused: …" text is not a live region.

**Fix:** make the SVG `aria-hidden` and non-focusable. The existing "View as table" `<details>` is already the accessible equivalent. If dot-by-dot exploration is wanted, use a single focusable group that moves between dots with arrow keys, plus a live region.

### A11Y-5 (medium): stale numbers are struck through visually but announced as current (WCAG 1.3.1)
- `components/ExplainDrawer.tsx:105-111`: `ExplainedNumber` adds class `is-stale` (strikethrough and muted colour, `styles/app.css:198`) when `item.freshness === "STALE"`. Its `aria-label` is `` `${item.label}: ${item.display}. Press to explain.` `` with no freshness, and that label replaces the visible content.

**Scenario:** in the Discovery results table, a sighted user sees a crossed-out return band and knows not to trust it. A screen-reader user hears "Median: 6.1%. Press to explain." exactly as for fresh data. That is a decision-relevant difference for real money, across 22 `ExplainedNumber` call sites.

**Fix:** when the value is not current, include the freshness word in the label, for example `"…: 6.1% (STALE). Press to explain."`.

### A11Y-6 (low): the exit-load form opens far from the button that opens it (WCAG 2.4.3)
- `pages/MfExplorer.tsx:226` and `:306-317`: "Enter exit load for <name>" is in a table row that can be row 400 of the tall table. `ExitLoadForm` renders above the table and focus does not move into it.
- On save or cancel the form unmounts, so focus is lost again. This combines with the reload issue in A11Y-2.

**Scenario:** a keyboard or screen-reader user presses the button and nothing seems to happen. The form is off-screen above them.

**Fix:**
- Focus the form's `<h3 id="el-title">` (with `tabIndex=-1`) when it mounts.
- Return focus to the row's button, or to the activity log, when it closes.

### A11Y-7 (low): acknowledged alerts drop below text contrast (WCAG 1.4.3)
- `styles/app.css:328` sets `.alert.is-acked { opacity: 0.75; }`. `pages/Alerts.tsx:345-356` applies it to the whole card, including 12px `small subtle` text: kind, "raised …" and "Acknowledged …".
- Computed against the light theme: `#5f6675` at 75% on `#ffffff` is about `#878c98`, which is 3.37:1. The warning severity colour `#7a5300` at 75% is 3.85:1. Both are below 4.5:1. In dark mode, subtle text at 75% is 4.23:1, also a failure.

**Fix:** drop the opacity. Show the acknowledged state with the existing "Acknowledged <time>" text, a border style or a glyph instead.

## Not reported (checked; no failure found)
- **Tabs** (`Scenarios.tsx:59`, `FixedIncome.tsx:1325`): there is no arrow-key roving, but every tab can be reached and activated by keyboard. This departs from the ARIA Authoring Practices pattern but is not a WCAG failure.
- **`DataTable` `onRowOpen` row focus**: no caller passes `onRowOpen`, so this code never runs.
- **Target size (2.5.8)**: buttons are at least 28px tall, the sort buttons 24px, and checkboxes and radios sit inside clickable labels.
