from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

CENT = Decimal("0.01")
SCENARIO_KEY_FIELDS = ("week", "nmId", "articleWb", "scheme")
STATUS_KEY_FIELDS = ("week", "nmId", "articleWb", "barcode", "scheme")
COMPLETENESS_PRIORITY = {
    "confirmed": 0,
    "management_assumption": 10,
    "partial": 20,
    "missing": 30,
    "mismatch": 40,
}


def overlay_management_input_vat_rows(
    source_rows: Sequence[MutableMapping[str, Any]],
    scenario_rows: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Apply a VAT-only management scenario without changing source-report P&L.

    The scenario may use a coarser row grain than the published source report.
    Amounts are therefore reconciled by week/product/scheme and allocated back to
    the original rows deterministically to the kopeck.
    """

    source_groups = _group_rows(source_rows)
    scenario_groups = _group_rows(scenario_rows)
    scenario_status_groups = _group_rows(scenario_rows, fields=STATUS_KEY_FIELDS)
    missing_source_keys = sorted(
        set(scenario_groups) - set(source_groups), key=_sortable_key
    )
    missing_scenario_keys = sorted(
        set(source_groups) - set(scenario_groups), key=_sortable_key
    )
    if missing_source_keys or missing_scenario_keys:
        raise ValueError(
            "input VAT overlay grain mismatch: "
            f"scenario_without_source={len(missing_source_keys)}, "
            f"source_without_scenario={len(missing_scenario_keys)}"
        )

    target_totals = defaultdict(lambda: Decimal("0"))
    applied_totals = defaultdict(lambda: Decimal("0"))
    completeness_counts: dict[str, int] = defaultdict(int)

    for key in sorted(scenario_groups, key=_sortable_key):
        targets = _scenario_targets(scenario_groups[key])
        rows = source_groups[key]
        import_values = _allocate_money(
            targets["vatInputFromImportScenario"],
            rows,
            weight=lambda row: _decimal(row.get("cost")),
        )
        wb_values = _allocate_money(
            targets["vatInputFromWbScenario"],
            rows,
            weight=_wb_service_weight,
        )
        scenario_weights = [
            import_value + wb_value
            for import_value, wb_value in zip(import_values, wb_values, strict=True)
        ]
        vat_input_values = _allocate_money_from_weights(
            targets["vatInput"], rows, scenario_weights
        )
        from_wb_values = _allocate_money(
            targets["vatInputFromWb"], rows, weight=_wb_service_weight
        )
        from_1c_values = _allocate_money(
            targets["vatInputFrom1c"],
            rows,
            weight=lambda row: _decimal(row.get("cost")),
        )
        fallback_completeness = str(targets["vatInputCompleteness"])
        fallback_input_vat_mode = str(targets["inputVatMode"])

        for index, row in enumerate(rows):
            status_rows = scenario_status_groups.get(
                _scenario_key(row, fields=STATUS_KEY_FIELDS)
            )
            status_targets = (
                _scenario_targets(status_rows) if status_rows else targets
            )
            completeness = str(
                status_targets.get("vatInputCompleteness")
                or fallback_completeness
            )
            input_vat_mode = str(
                status_targets.get("inputVatMode") or fallback_input_vat_mode
            )
            row["vatInputFromImportScenario"] = import_values[index]
            row["vatInputFromWbScenario"] = wb_values[index]
            row["vatInput"] = vat_input_values[index]
            row["vatInputFromWb"] = from_wb_values[index]
            row["vatInputFrom1c"] = from_1c_values[index]
            row["vatInputDifference"] = (
                from_1c_values[index] - from_wb_values[index]
            ).quantize(CENT, rounding=ROUND_HALF_UP)
            row["vatInputCompleteness"] = completeness
            row["inputVatMode"] = input_vat_mode
            row["vatInputConfirmed"] = False
            vat_payable = (
                _decimal(row.get("vatOutput")) - vat_input_values[index]
            ).quantize(CENT, rounding=ROUND_HALF_UP)
            row["vatPayable"] = vat_payable
            row["vat"] = vat_payable
            completeness_counts[completeness] += 1

        for field in (
            "vatInputFromImportScenario",
            "vatInputFromWbScenario",
            "vatInput",
            "vatInputFromWb",
            "vatInputFrom1c",
        ):
            target_totals[field] += _decimal(targets[field])
            applied_totals[field] += sum(
                (_decimal(row.get(field)) for row in rows), Decimal("0")
            )

    for field, target in target_totals.items():
        applied = applied_totals[field]
        if applied != target:
            raise ValueError(
                f"input VAT overlay total mismatch for {field}: "
                f"target={target}, applied={applied}"
            )

    return {
        "sourceRowCount": len(source_rows),
        "scenarioRowCount": len(scenario_rows),
        "grainCount": len(source_groups),
        "totals": {key: value for key, value in sorted(applied_totals.items())},
        "completenessCounts": dict(sorted(completeness_counts.items())),
    }


def _group_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    fields: tuple[str, ...] = SCENARIO_KEY_FIELDS,
) -> dict[tuple[str, ...], list[Mapping[str, Any]]]:
    grouped: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[_scenario_key(row, fields=fields)].append(row)
    return grouped


def _scenario_key(
    row: Mapping[str, Any],
    *,
    fields: tuple[str, ...] = SCENARIO_KEY_FIELDS,
) -> tuple[str, ...]:
    return tuple(str(row.get(field) or "").strip() for field in fields)


def _scenario_targets(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    totals = {
        field: sum((_decimal(row.get(field)) for row in rows), Decimal("0"))
        for field in (
            "vatInputFromImportScenario",
            "vatInputFromWbScenario",
            "vatInput",
            "vatInputFromWb",
            "vatInputFrom1c",
        )
    }
    completeness = max(
        (str(row.get("vatInputCompleteness") or "missing") for row in rows),
        key=lambda value: COMPLETENESS_PRIORITY.get(value, 100),
    )
    mode = (
        "management_assumption"
        if any(
            str(row.get("inputVatMode") or "") == "management_assumption"
            for row in rows
        )
        else "accounting_fact"
    )
    return {
        **totals,
        "vatInputCompleteness": completeness,
        "inputVatMode": mode,
    }


def _allocate_money(
    total: Decimal,
    rows: Sequence[Mapping[str, Any]],
    *,
    weight: Callable[[Mapping[str, Any]], Decimal],
) -> list[Decimal]:
    weights = [weight(row) for row in rows]
    return _allocate_money_from_weights(total, rows, weights)


def _allocate_money_from_weights(
    total: Decimal,
    rows: Sequence[Mapping[str, Any]],
    weights: Sequence[Decimal],
) -> list[Decimal]:
    if not rows:
        raise ValueError("cannot allocate input VAT to an empty source grain")
    total = total.quantize(CENT, rounding=ROUND_HALF_UP)
    weight_total = sum(weights, Decimal("0"))
    if weight_total == 0:
        fallback = [abs(_decimal(row.get("revenue"))) for row in rows]
        weight_total = sum(fallback, Decimal("0"))
        weights = fallback
    if weight_total == 0:
        weights = [Decimal("1") for _ in rows]
        weight_total = Decimal(len(rows))

    raw = [total * value / weight_total for value in weights]
    rounded = [value.quantize(CENT, rounding=ROUND_HALF_UP) for value in raw]
    difference = total - sum(rounded, Decimal("0"))
    steps = int(abs(difference) / CENT)
    if steps:
        reverse = difference > 0
        candidates = sorted(
            range(len(rows)),
            key=lambda index: (raw[index] - rounded[index], -index),
            reverse=reverse,
        )
        step = CENT if difference > 0 else -CENT
        for index in range(steps):
            target_index = candidates[index % len(candidates)]
            rounded[target_index] += step
    if sum(rounded, Decimal("0")) != total:
        raise ValueError("input VAT cent allocation failed")
    return rounded


def _wb_service_weight(row: Mapping[str, Any]) -> Decimal:
    return sum(
        (
            _decimal(row.get(field))
            for field in (
                "commission",
                "logistics",
                "storage",
                "acceptance",
                "promotion",
                "acquiring",
            )
        ),
        Decimal("0"),
    )


def _decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    return Decimal(str(value))


def _sortable_key(value: tuple[str, ...]) -> tuple[str, ...]:
    return value
