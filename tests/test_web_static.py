from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "wb_unit_economics" / "web" / "static"


def _css_hex_variable(styles: str, name: str) -> str:
    match = re.search(rf"{re.escape(name)}:\s*(#[0-9a-fA-F]{{6}});", styles)
    assert match is not None
    return match.group(1)


def _relative_luminance(color: str) -> float:
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92
        if channel <= 0.03928
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(foreground: str, background: str) -> float:
    first = _relative_luminance(foreground)
    second = _relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


def test_margin_calculator_dialog_has_accessible_fact_scenario_structure() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")

    assert 'id="margin-calculator-overlay"' in html
    assert 'aria-modal="true"' in html
    assert 'role="dialog"' in html
    assert 'id="margin-calculator-fact-grid"' in html
    assert 'id="margin-calculator-scenario-grid"' in html
    assert 'id="margin-calculator-form"' in html
    assert html.count(" required") >= 11
    assert html.count("Оценка") >= 2
    assert "Фактические значения уже подставлены." in html
    assert "Себестоимость, ₽/шт." in html
    assert "Себестоимость на единицу, ₽" not in html
    assert "Сохранить сценарий" not in html


def test_margin_calculator_action_and_focus_lifecycle_are_wired() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")

    assert 'calculatorButton.textContent = "Рассчитать маржу"' in script
    assert "openMarginCalculator(item)" in script
    assert "closeMarginCalculator({ restoreFocus: false })" in script
    assert "openWidgetOverlay(els.marginCalculatorOverlay)" in script
    assert "closeWidgetOverlay(els.marginCalculatorOverlay, options)" in script
    assert "scheme: marginCalculatorRequestScheme(requestedScheme)" in script
    assert 'return ["FBO", "FBS"].includes(scheme) ? scheme : "";' in script
    assert "populateMarginCalculatorInputs(payload.fact || {})" in script
    assert "state.marginCalculatorBaseline = baseline" in script
    assert 'classList.toggle("is-target-mode", targetMode)' in script
    assert "renderMarginCalculatorEmptyState(" in script
    assert '"Цена, себестоимость и расходы подставятся автоматически."' in script
    assert "changedInputs" not in script or "is-changed" in script
    assert "НДС к уплате" in script
    assert "Налог с выручки" in script
    assert "Прибыль после учтённых налогов" in script


def test_margin_calculator_layout_is_responsive_and_marks_changed_inputs() -> None:
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert ".margin-calculator-body" in styles
    assert "align-items: start;" in styles
    assert 'grid-template-areas:\n      "fact parameters"' in styles
    assert (
        'grid-template-areas:\n      "fact"\n      "parameters"\n      "scenario";'
        in styles
    )
    assert "grid-template-columns: 1fr;" in styles
    assert ".margin-field-label" in styles
    assert ".margin-empty-state" in styles
    assert "min-height: 44px;" in styles
    assert ".margin-input-grid input.is-changed" in styles
    assert ".report-rows-table td:first-child" in styles


def test_widget_modal_accessibility_lifecycle_is_wired() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert "const widgetOpen = Boolean(currentOpenWidgetOverlay());" in script
    assert "els.cabinetView.inert = widgetOpen;" in script
    assert "state.widgetReturnFocus = widgetReturnFocusTarget();" in script
    assert "function widgetReturnFocusTarget()" in script
    assert 'active.closest("details")?.querySelector("summary")' in script
    assert 'document.body.classList.toggle("widget-open", widgetOpen);' in script
    assert "target.focus({ preventScroll: true });" in script
    assert "window.setTimeout(() => target.focus(), 0);" not in script
    widget_overlay = styles.split(".widget-overlay {", 1)[1].split("}", 1)[0]
    assert "z-index: 1100;" in widget_overlay


def test_role_chart_contrast_and_touch_accessibility_contracts() -> None:
    script = (STATIC / "app.js").read_text(encoding="utf-8")
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")

    report_button = script.split("function updateReportBuildButton", 1)[1].split(
        "\nfunction ", 1
    )[0]
    client_branch = report_button.split('if (!isStaff) {', 1)[1].split(
        "return;", 1
    )[0]
    assert 'removeAttribute("aria-haspopup")' in client_branch
    assert 'removeAttribute("aria-controls")' in client_branch
    assert 'setAttribute("aria-haspopup", "dialog")' in report_button
    assert 'svg.setAttribute("role", "group")' in script
    assert 'svg.setAttribute("role", "img")' not in script
    assert _contrast_ratio(
        _css_hex_variable(styles, "--muted"),
        _css_hex_variable(styles, "--surface-muted"),
    ) >= 4.5
    assert _contrast_ratio(
        _css_hex_variable(styles, "--review"),
        _css_hex_variable(styles, "--review-bg"),
    ) >= 4.5
    upload_summary = styles.split(".upload-help summary {", 1)[1].split("}", 1)[0]
    assert "min-height: 32px;" in upload_summary
