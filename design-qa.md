# Design QA: overview sales pattern v2.33

## Comparison target

- Source visual truth: `/root/.codex/attachments/bb06fefa-3e50-4560-af55-5bb1f8772e09/codex-clipboard-6fb1c69c-f422-47e7-b397-f58cedfd1080.png`
- Source pattern: management Sales view with compact semantic KPI cards and a
  full-width multi-series sales chart.
- Implementation: local authenticated cabinet at `#overview`.
- Desktop KPI evidence: `/root/.codex/visualizations/2026/07/13/019f5ac5-60cd-7941-83d4-76dbefbb3202/overview-sales-v1/02-kpis-desktop.png`
- Desktop chart evidence: `/root/.codex/visualizations/2026/07/13/019f5ac5-60cd-7941-83d4-76dbefbb3202/overview-sales-v1/03-chart-desktop.png`
- Mobile evidence: `/root/.codex/visualizations/2026/07/13/019f5ac5-60cd-7941-83d4-76dbefbb3202/overview-sales-v1/07-kpis-mobile.png`
- Viewports: 1488 x 1058 and 390 x 844.

The supplied source and the implementation KPI/chart captures were opened
together in one visual comparison input. The source has plan, forecast and
comparison series that do not exist in the accepted Shumeyko data contract;
those series were deliberately not invented.

## Full-view comparison

- The source pattern is preserved: five primary cards in the first row, two in
  the second row, semantic top borders, a restrained white surface and one
  large chart below the decision metrics.
- The first level now contains seven decision KPIs instead of nineteen equal
  cards. Secondary and tax facts remain available in one disclosure, so the
  redesign does not hide or zero unavailable values.
- The chart follows the source visual grammar: neutral sales bars, blue revenue,
  green marginal income and purple margin on a separate percent axis.
- The existing product typography and teal/navy token family were retained, so
  the borrowed pattern still belongs to the current cabinet design system.

## Focused comparison and iteration history

### Iteration 1

- [P1] Six unavailable tax values created six visually identical
  `Не рассчитано` cards. Fix: replaced them with one explicit tax-status card
  while keeping all six values when a tax profile is calculated.
- [P1] The old grouped money columns were too small to support month-to-month
  reading. Fix: replaced them with a full-width dual-axis chart and exact
  keyboard-accessible month tooltip.
- [P2] The chart initially kept the older title `Динамика денег`. Fix: aligned
  the runtime title and subtitle with the implemented `Динамика продаж` scope.
- [P2] A single filtered month could start outside the visible mobile chart
  viewport. Fix: the chart centers a one-month state after rendering while
  preserving local chart scrolling and preventing page overflow.
- [P2] The desktop tooltip wrapped the currency onto a separate line. Fix:
  increased the tooltip width without affecting the plot area.

### Post-fix checks

- Seven primary KPI cards and seven secondary cards in the synthetic state.
- Month selection works with keyboard Enter and applies the existing month
  detail filter.
- No duplicate DOM ids and no horizontal page overflow on desktop or mobile.
- Long charts keep overflow inside the chart viewport rather than widening the
  page.
- The only console entry was the expected unauthenticated `/api/me` 401 before
  login; no authenticated application error was observed.

## Required fidelity surfaces

- Typography: existing system UI stack; primary KPI values remain readable and
  unavailable values wrap cleanly at 390 px.
- Spacing: card heights and gaps match the compact source rhythm; `Контроль 1С`
  stays a separate accounting block and does not compete with primary KPIs.
- Colors: meaning is carried by both labels and semantic top borders; chart
  series have legend labels and do not rely on color alone.
- Interaction: every month has a focusable hit area, exact accessible label,
  tooltip, crosshair and existing read-only drilldown action.
- Data integrity: no forecast or prior-period comparison was shown because the
  current payload does not provide those facts.

No actionable P0/P1/P2 visual findings remain.

## Known scope limitation

This comparison covers the WB consultant/admin scenario only. For Ozon-context
clients, `#checks/cost` is not reachable: `selectWorkspace()` and
`renderCostReview()` (`app.js`) both downgrade `checkView` back to `summary`
when `shouldUseOzonWorkingView()` is true, and the "Разобрать себестоимость"
next-action opens the legacy `missingCost` drilldown overlay instead of
routing to the new cost-review page. This is intentional (the cost-review
workflow assumes WB's weekly missing-cost model) but was not part of this
visual QA pass and should be tracked as a separate scoping decision before
claiming full parity across marketplaces.

final result: passed (WB scenario only — see scope limitation above)
