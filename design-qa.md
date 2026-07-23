# Design QA: WB-логистика R-4 «Причины возвратов»

## Comparison target

- Source visual truth:
  `/root/.codex/generated_images/019f89c8-fbc3-7b20-a429-86d4620d130f/call_B1YzSruMnBSo67bryvDQwKVI.png`.
- Responsive target:
  `docs/design/wb-logistics-v4-analytics-target.html`.
- Browser-rendered implementation:
  `http://127.0.0.1:18766/cabinet?client_id=shumeyko&report_id=report-1#tables/logistics`
  on a local synthetic read-only fixture.
- Desktop implementation evidence:
  `/tmp/wb-r4-runtime-SRaPQ4/runtime-return-reasons-desktop.png`.
- Mobile implementation evidence:
  `/tmp/wb-r4-runtime-SRaPQ4/runtime-return-reasons-mobile.png`.
- Desktop combined comparison:
  `/tmp/wb-r4-runtime-SRaPQ4/comparison-selected-reference-vs-runtime-desktop.png`.
- Mobile combined comparison:
  `/tmp/wb-r4-runtime-SRaPQ4/comparison-target-vs-runtime-mobile.png`.

The selected reference is 1487 × 1058 px. The browser implementation was
captured at 1440 × 900 CSS px and 390 × 844 CSS px with
`deviceScaleFactor: 1`; both screenshots therefore have matching pixel and CSS
dimensions. The focused desktop implementation section is 1112 × 404 px. The
desktop comparison uses a crop of the selected reference around the R-4 block
and scales both focused regions to the same 1120 px display width. The mobile
comparison uses the responsive target and implementation at the same 390 px
width without density conversion.

State: staff-only synthetic draft, `sliceStatus=partial`, a confirmed
goods-return reason, claims `access_denied`, and one safe mart row. The
different synthetic counts between source and implementation are dynamic
content, not a visual mismatch.

## Full-view comparison

- The selected coverage-first hierarchy is preserved: disclosure title,
  three coverage states, two source rows, return details, and a recommendation
  derived only from a confirmed reason.
- The runtime section is placed after the enabled factor blocks and before the
  product rating, with no new sidebar item or scenario tab.
- The runtime keeps the existing cabinet typography, borders, radii, badges,
  table system and semantic colors. Its additional status pill is intentional:
  it exposes the accepted `ready`/`partial`/`empty`/`needs_rebuild`/`blocked`
  state matrix.
- On 390 × 844 the coverage strip stacks, source rows remain readable, and the
  desktop table becomes labelled cards. The persistent product navigation is
  expected existing application chrome.

## Focused comparison and iteration history

### Iteration 1

- [P2] Recommendation order and emphasis drifted from the selected reference.
  The first runtime capture placed a large amber recommendation card before
  the return table. Fix: moved the recommendation after the table and restyled
  it as a compact green-labelled evidence line.
- [P2] Two pieces of copy were more technical than the selected reference.
  Fix: aligned them to `Причина подтверждается только exact-связью` and
  `Покрытие неизвестно`, while keeping the claims source row explicit.

Post-fix evidence is the desktop and mobile combined comparison listed above.
No additional focused crop is required: the complete R-4 component and all
table text are legible in the combined desktop comparison.

## Required fidelity surfaces

- Fonts and typography: the implementation uses the cabinet system UI stack
  at the same hierarchy as adjacent logistics factors. Headings, coverage
  values, source labels, badges and mobile field labels remain readable and do
  not truncate.
- Spacing and layout rhythm: the three-part coverage strip, source grid, table
  and recommendation follow the selected order. The runtime uses existing
  10–12 px radii and cabinet spacing; there is no document, section or table
  overflow on either viewport.
- Colors and tokens: confirmed coverage uses the existing green fact palette,
  unavailable coverage uses neutral blue-gray, and unknown coverage uses the
  existing amber review palette. Meaning is repeated in text, not conveyed by
  color alone.
- Image quality and asset fidelity: the R-4 component contains no raster
  imagery, logos or custom illustrations. The implementation uses the native
  disclosure marker and existing product UI primitives; no placeholder image,
  CSS art, emoji or handcrafted SVG was introduced.
- Copy and content: Finance is not presented as a reason source, unavailable
  claims explicitly say that logistics calculation continues, raw comments
  and identifiers are absent, and only `evidenceType=fact` recommendations are
  rendered.
- States and interactions: disclosure collapse/reopen and remote table sorting
  were exercised. Both desktop and mobile started open, collapsed, reopened
  and retained the loaded data.
- Accessibility and resilience: semantic `details/summary`, status role,
  table headers, mobile field labels and existing sortable-table keyboard
  behavior are preserved. At 1440 × 900 and 390 × 844 there were no console
  errors, failed requests or horizontal overflow.

No actionable P0/P1/P2 findings remain.

final result: passed
