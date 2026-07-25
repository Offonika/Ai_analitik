from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "src" / "wb_unit_economics" / "web" / "static"


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
    assert "changedInputs" not in script or "is-changed" in script
    assert "НДС к уплате" in script
    assert "Налог с выручки" in script
    assert "Прибыль после учтённых налогов" in script


def test_margin_calculator_layout_is_responsive_and_marks_changed_inputs() -> None:
    styles = (STATIC / "styles.css").read_text(encoding="utf-8")

    assert ".margin-calculator-body" in styles
    assert "grid-template-columns: 1fr;" in styles
    assert ".margin-input-grid input.is-changed" in styles
    assert ".report-rows-table td:first-child" in styles
