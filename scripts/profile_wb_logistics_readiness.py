#!/usr/bin/env python3
"""Profile WB finance snapshots for logistics analysis without exposing raw rows."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from wb_unit_economics.wb_finance import _iter_json_list_objects

PROFILE_FIELDS = (
    "orderUid",
    "srid",
    "orderId",
    "shkId",
    "stickerId",
    "rrdId",
    "nmId",
    "sku",
    "docTypeName",
    "sellerOperName",
    "officeName",
    "country",
    "deliveryMethod",
    "deliveryAmount",
    "returnAmount",
    "deliveryService",
    "rebillLogisticCost",
    "dlvPrc",
    "fixTariffDateFrom",
    "fixTariffDateTo",
    "giBoxTypeName",
)
CANDIDATE_CHAIN_KEY_FIELDS = (
    "orderUid",
    "srid",
    "orderId",
    "shkId",
    "stickerId",
)


def discover_finance_files(snapshot_dir: Path) -> list[Path]:
    """Return finance raw pages below a source-refresh snapshot directory."""

    root = snapshot_dir.resolve()
    finance_dir = root / "wb_finance"
    search_root = finance_dir if finance_dir.is_dir() else root
    return sorted(search_root.glob("*_finance_page_*.raw.json"))


def profile_finance_files(paths: Sequence[Path]) -> dict[str, Any]:
    """Build a safe aggregate profile without returning row values or identifiers."""

    field_present: Counter[str] = Counter()
    field_non_empty: Counter[str] = Counter()
    logistics_field_present: Counter[str] = Counter()
    logistics_field_non_empty: Counter[str] = Counter()
    numeric_states: dict[str, Counter[str]] = {
        field: Counter()
        for field in ("deliveryService", "deliveryAmount", "returnAmount")
    }
    chain_rows: Counter[tuple[str, str, str]] = Counter()
    chain_products: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    key_rows: Counter[str] = Counter()
    logistics_key_rows: Counter[str] = Counter()
    field_chain_rows: Counter[tuple[str, str, str]] = Counter()
    field_chain_products: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    row_count = 0
    logistics_row_count = 0
    chain_key_rows = 0
    logistics_chain_key_rows = 0
    logistics_direction_signals: Counter[str] = Counter()

    for path in paths:
        source_scope = _source_scope(path)
        for row in _iter_json_list_objects(path):
            row_count += 1
            for field in PROFILE_FIELDS:
                if field in row:
                    field_present[field] += 1
                if _has_value(row.get(field)):
                    field_non_empty[field] += 1

            numeric = {
                field: _numeric_state(row.get(field)) for field in numeric_states
            }
            for field, state in numeric.items():
                numeric_states[field][state] += 1

            is_logistics = numeric["deliveryService"] == "nonzero"
            if is_logistics:
                logistics_row_count += 1
                for field in PROFILE_FIELDS:
                    if field in row:
                        logistics_field_present[field] += 1
                    if _has_value(row.get(field)):
                        logistics_field_non_empty[field] += 1

            chain_key = _chain_key(row)
            product_key = _text(row.get("nmId")) or _text(row.get("sku"))
            for field in CANDIDATE_CHAIN_KEY_FIELDS:
                value = _text(row.get(field))
                if not value:
                    continue
                key_rows[field] += 1
                if is_logistics:
                    logistics_key_rows[field] += 1
                field_key = (source_scope, field, value)
                field_chain_rows[field_key] += 1
                if product_key:
                    field_chain_products[field_key].add(product_key)
            if chain_key is not None:
                chain_key_rows += 1
                key = (source_scope, chain_key[0], chain_key[1])
                chain_rows[key] += 1
                if product_key:
                    chain_products[key].add(product_key)
                if is_logistics:
                    logistics_chain_key_rows += 1

            if is_logistics:
                forward_signal = numeric["deliveryAmount"] == "nonzero"
                reverse_signal = numeric["returnAmount"] == "nonzero"
                if forward_signal and reverse_signal:
                    signal = "both"
                elif forward_signal:
                    signal = "forward_only"
                elif reverse_signal:
                    signal = "reverse_only"
                else:
                    signal = "none"
                logistics_direction_signals[signal] += 1

    distinct_chain_count = len(chain_rows)
    multirow_chain_count = sum(count > 1 for count in chain_rows.values())
    conflicting_product_chain_count = sum(
        len(products) > 1 for products in chain_products.values()
    )

    return {
        "profileVersion": 1,
        "sourceFileCount": len(paths),
        "rowCount": row_count,
        "logisticsRowCount": logistics_row_count,
        "orderChain": {
            "candidateFallbackOrder": list(CANDIDATE_CHAIN_KEY_FIELDS),
            "rowCoveragePct": _percent(chain_key_rows, row_count),
            "logisticsRowCoveragePct": _percent(
                logistics_chain_key_rows, logistics_row_count
            ),
            "distinctChainCount": distinct_chain_count,
            "multirowChainCount": multirow_chain_count,
            "multirowChainPct": _percent(
                multirow_chain_count, distinct_chain_count
            ),
            "conflictingProductChainCount": conflicting_product_chain_count,
            "keyProfiles": {
                field: _key_profile(
                    field=field,
                    row_count=row_count,
                    logistics_row_count=logistics_row_count,
                    key_rows=key_rows,
                    logistics_key_rows=logistics_key_rows,
                    field_chain_rows=field_chain_rows,
                    field_chain_products=field_chain_products,
                )
                for field in CANDIDATE_CHAIN_KEY_FIELDS
            },
        },
        "directionSignalsOnLogisticsRows": {
            key: {
                "count": logistics_direction_signals[key],
                "pct": _percent(
                    logistics_direction_signals[key], logistics_row_count
                ),
            }
            for key in ("forward_only", "reverse_only", "both", "none")
        },
        "fieldCoverage": {
            field: {
                "presentPct": _percent(field_present[field], row_count),
                "nonEmptyPct": _percent(field_non_empty[field], row_count),
                "presentOnLogisticsRowsPct": _percent(
                    logistics_field_present[field], logistics_row_count
                ),
                "nonEmptyOnLogisticsRowsPct": _percent(
                    logistics_field_non_empty[field], logistics_row_count
                ),
            }
            for field in PROFILE_FIELDS
        },
        "numericValidity": {
            field: {
                "invalidCount": states["invalid"],
                "invalidPct": _percent(states["invalid"], row_count),
            }
            for field, states in numeric_states.items()
        },
    }


def _chain_key(row: Mapping[str, Any]) -> tuple[str, str] | None:
    for field in CANDIDATE_CHAIN_KEY_FIELDS:
        value = _text(row.get(field))
        if value:
            return field, value
    return None


def _source_scope(path: Path) -> str:
    """Group pages of one seller account without exposing that scope in output."""

    account_prefix = path.name.rsplit("_finance_page_", maxsplit=1)[0]
    return f"{path.parent.resolve()}::{account_prefix}"


def _key_profile(
    *,
    field: str,
    row_count: int,
    logistics_row_count: int,
    key_rows: Counter[str],
    logistics_key_rows: Counter[str],
    field_chain_rows: Counter[tuple[str, str, str]],
    field_chain_products: Mapping[tuple[str, str, str], set[str]],
) -> dict[str, int | float | None]:
    matching_keys = [key for key in field_chain_rows if key[1] == field]
    distinct_count = len(matching_keys)
    multirow_count = sum(field_chain_rows[key] > 1 for key in matching_keys)
    conflict_count = sum(
        len(field_chain_products.get(key, set())) > 1 for key in matching_keys
    )
    return {
        "rowCoveragePct": _percent(key_rows[field], row_count),
        "logisticsRowCoveragePct": _percent(
            logistics_key_rows[field], logistics_row_count
        ),
        "distinctChainCount": distinct_count,
        "multirowChainCount": multirow_count,
        "multirowChainPct": _percent(multirow_count, distinct_count),
        "conflictingProductChainCount": conflict_count,
    }


def _numeric_state(value: object) -> str:
    if not _has_value(value):
        return "missing"
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return "invalid"
    return "zero" if number == 0 else "nonzero"


def _has_value(value: object) -> bool:
    return value is not None and _text(value) != ""


def _text(value: object) -> str:
    return str(value).strip() if value is not None else ""


def _percent(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator * 100 / denominator, 2)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Profile WB finance logistics fields without printing raw rows, "
            "identifiers, articles, titles or monetary totals."
        )
    )
    parser.add_argument(
        "snapshot_dir",
        type=Path,
        help="Source-refresh snapshot directory or its wb_finance directory.",
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(list(argv) if argv is not None else None)
    paths = discover_finance_files(args.snapshot_dir)
    if not paths:
        print(json.dumps({"error": "wb_finance_files_not_found"}))
        return 2
    profile = profile_finance_files(paths)
    print(json.dumps(profile, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if profile["rowCount"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
