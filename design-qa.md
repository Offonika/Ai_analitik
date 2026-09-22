# Design QA: минималистичный chat-first AI-аналитик

## Comparison target

- Source visual truth:
  `/root/.codex/attachments/ae8c807a-9ca2-4e28-a300-91c4784b1ded/codex-clipboard-b5bbeb33-e67d-44e4-b423-621dfeb175b2.png`.
- Source dimensions: 2250 × 1128 px. Это исходный перегруженный экран, а не
  pixel-perfect макет: целевое изменение задано как минималистичный chat-first
  интерфейс без KPI-карточек, progress bars и постоянной правой timeline.
- Browser-rendered implementation: локальный FastAPI-стенд на синтетической
  read-only витрине, открытый Playwright Chromium.
- Desktop start:
  `/root/.codex/visualizations/2026/08/02/019fc174-7104-7e10-9a9a-efe1f28227a7/ai-chat-design-qa/desktop-start-1440x900.png`.
- Desktop widget-only:
  `/root/.codex/visualizations/2026/08/02/019fc174-7104-7e10-9a9a-efe1f28227a7/ai-chat-design-qa/desktop-start-1440x900-widget.png`.
- Tablet start:
  `/root/.codex/visualizations/2026/08/02/019fc174-7104-7e10-9a9a-efe1f28227a7/ai-chat-design-qa/tablet-start-760x900.png`.
- Mobile start:
  `/root/.codex/visualizations/2026/08/02/019fc174-7104-7e10-9a9a-efe1f28227a7/ai-chat-design-qa/mobile-start-390x844.png`.
- Desktop answer:
  `/root/.codex/visualizations/2026/08/02/019fc174-7104-7e10-9a9a-efe1f28227a7/ai-chat-design-qa/desktop-answer-1440x900.png`.
- Mobile answer:
  `/root/.codex/visualizations/2026/08/02/019fc174-7104-7e10-9a9a-efe1f28227a7/ai-chat-design-qa/mobile-answer-390x844.png`.
- Desktop citations and trace open:
  `/root/.codex/visualizations/2026/08/02/019fc174-7104-7e10-9a9a-efe1f28227a7/ai-chat-design-qa/desktop-evidence-open-1440x900.png`.
- Mobile citations and trace open:
  `/root/.codex/visualizations/2026/08/02/019fc174-7104-7e10-9a9a-efe1f28227a7/ai-chat-design-qa/mobile-evidence-open-390x844.png`.
- Combined full-view comparison:
  `/root/.codex/visualizations/2026/08/02/019fc174-7104-7e10-9a9a-efe1f28227a7/ai-chat-design-qa/comparison-source-vs-desktop-start.png`.

The implementation was captured at 1440 × 900, 760 × 900 and 390 × 844 CSS
px with `deviceScaleFactor: 1`; screenshot pixels equal CSS dimensions. The
desktop widget is 780 × 760 px, the tablet widget is 712 × 760 px and the
mobile widget is 370 × 824 px. The source is shown next to the 780 × 760
widget with `object-fit: contain`; no claim of pixel-level normalization is
made because the source is a before-state and the accepted target deliberately
changes its layout and density.

State: authenticated administrator, one published synthetic WB report,
readiness `Неполный период` with score 70/100, one missing-cost row, local
fallback answer, citations and safe trace. External systems and production data
were not used.

## Full-view comparison evidence

- The permanent KPI/context dashboard, three progress bars, fourth prompt and
  right-side timeline from the source are removed.
- The implementation has one visual column: compact report context, local
  greeting, at most three role-aware prompts, scrollable messages and composer.
- The answer uses the intended `Вывод → Факты → Следующий шаг` hierarchy.
- Citations and safe execution trace stay collapsed until requested. When both
  are open, chat and trace keep separate scroll regions.
- At 760 and 390 px the widget stays inside the viewport. Widget and message
  `scrollWidth` equal their `clientWidth`; form, message region and close button
  do not clip or overlap.

The combined comparison is sufficient as the focused desktop comparison: both
the source controls and the complete new widget are readable. Separate mobile
captures cover responsive behavior because the source does not define a mobile
layout.

## Findings and comparison history

### Iteration 1

- [P2] Readiness reason rendered as `[object Object]` in the local greeting.
  Location: `aiStartMessage` in `static/app.js`.
  Evidence: the first 390 px capture exposed the raw object conversion.
  Impact: the main limitation was incomprehensible at the moment the user opens
  the assistant.
  Fix: normalize readiness reasons through their safe `message`, `label` or
  `title` fields before composing the greeting.
- [P2] Expanding the nine-item trace could shrink the message region to 44 px
  and visually press the composer into it.
  Location: `.ai-trace` in `static/styles.css`.
  Evidence: the first desktop expanded-state measurement showed messages ending
  at 210 px while the form started at 186 px.
  Impact: the answer became hard to inspect while evidence was open.
  Fix: cap the open trace at `min(280px, 38vh)` and retain its internal scroll.

### Iteration 2

- Post-fix desktop expanded state: messages end at 383 px and the form starts at
  403 px.
- Post-fix mobile expanded state: messages end at 343 px and the form starts at
  363 px.
- The local greeting now shows the human-readable period limitation; no raw
  object text remains.
- No actionable P0/P1/P2 findings remain.

## Required fidelity surfaces

- Fonts and typography: the existing cabinet system stack and weights are
  preserved. The title, context, message copy, prompts and 12 px evidence text
  maintain hierarchy and readable line-height without truncating meaningful
  content. The composer placeholder ellipsizes only at the 390 px breakpoint.
- Spacing and layout rhythm: the 780 px desktop width, 20 px content padding,
  10–12 px radii and single-column rhythm remove the source's dashboard density.
  Desktop, tablet and mobile keep consistent gaps; opened evidence has bounded
  height and independent scrolling.
- Colors and visual tokens: the existing dark teal brand, pale teal local
  greeting, neutral assistant bubble, white surfaces and muted metadata are
  reused. Focus rings and borders retain visible contrast; state is not conveyed
  by color alone.
- Image quality and asset fidelity: the modal contains no raster illustrations,
  logos or custom decorative assets. No placeholders, handcrafted SVGs, emoji,
  CSS art or generated imagery were introduced.
- Copy and content: the greeting is derived from current report readiness,
  prompts are role-aware, and fallback answers show computed facts without
  coercing missing profit to zero. Technical fallback reasons remain hidden from
  the client role.
- Icons: the modal itself uses text controls and the browser-native disclosure
  marker; no mismatched icon family was introduced.
- States and interactions: local start without thread creation, prompt/input
  submit, simulated transport failure, retry, local answer, citations, trace,
  close/reopen and history restoration were exercised. Retry kept one user
  bubble; restored history had zero duplicated local greetings.
- Accessibility: focus enters the composer, semantic `role=log` and live status
  regions remain, disclosure controls are keyboard-native, and the close button
  stays visible at all tested widths. No horizontal overflow occurred in the
  widget or message region.
- Console and network: after the expected unauthenticated bootstrap 401 and the
  deliberately aborted request used to exercise retry, there were no unexpected
  console errors, page errors or failed requests.

## Implementation checklist

- [x] Replace dashboard-heavy AI modal with one-column chat-first layout.
- [x] Render safe local greeting and at most three role-aware prompts.
- [x] Keep citations and execution trace collapsed and scroll-safe.
- [x] Verify retry, history restoration, focus and read-only navigation.
- [x] Verify 1440, 760 and 390 px layouts in Chromium.
- [x] Re-run visual comparison after both P2 fixes.

## Follow-up polish

No blocking polish remains. A future optional P3 iteration could replace the
long mobile input placeholder with a shorter breakpoint-specific phrase, but
the current ellipsis is conventional and does not hide user-entered content.

final result: passed
