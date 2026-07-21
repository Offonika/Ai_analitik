from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "probe_wb_logistics_factors",
    Path(__file__).resolve().parents[1] / "scripts" / "probe_wb_logistics_factors.py",
)
probe = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(probe)


def test_collect_key_names_is_recursive_and_names_only() -> None:
    keys: set[str] = set()
    probe.collect_key_names(
        {"response": {"data": [{"reason": "цвет", "srid": "abc"}]}}, keys
    )
    assert "reason" in keys
    assert "srid" in keys
    # значения не попадают в множество имён
    assert "цвет" not in keys
    assert "abc" not in keys


def test_max_list_len_finds_deepest_list() -> None:
    assert probe.max_list_len({"a": {"b": [1, 2, 3]}}) == 3
    assert probe.max_list_len({"a": 1}) is None


def test_summarize_reports_field_presence_without_values() -> None:
    payload = {
        "data": [
            {"reason": "RAWVALUE", "status": "RAWSTATUS", "srid": "z", "nmId": 1}
        ]
    }
    summary = probe.summarize("goods_return", payload)
    present = summary["fields_present_anywhere"]
    assert present["reason"] is True
    assert present["srid"] is True
    assert present["returnType"] is False
    assert summary["max_list_len"] == 1
    # в сводке нет сырых значений
    assert "RAWVALUE" not in str(summary)
    assert "RAWSTATUS" not in str(summary)


def test_endpoints_are_read_only_wb_hosts() -> None:
    for _name, url, _params, _scope in probe.endpoints(date(2026, 7, 19)):
        assert url.startswith("https://")
        assert "wildberries.ru" in url


def test_f4_endpoints_are_read_only_minimal_and_cover_moscow_days() -> None:
    endpoints = probe.f4_endpoints(date(2026, 7, 21), days=31)

    assert [item[0] for item in endpoints] == [
        "measurement_penalties",
        "warehouse_measurements",
    ]
    for _name, url, params in endpoints:
        assert url.startswith(
            "https://seller-analytics-api.wildberries.ru/api/analytics/v1/"
        )
        assert params["limit"] == 1
        assert params["offset"] == 0
        assert params["dateFrom"].endswith("Z")
        assert params["dateTo"].endswith("Z")

    with pytest.raises(ValueError, match="between 1 and 366"):
        probe.f4_endpoints(date(2026, 7, 21), days=0)


class _Response:
    def __init__(self, status_code: int, payload=None, *, broken_json: bool = False):
        self.status_code = status_code
        self.payload = payload
        self.broken_json = broken_json

    def json(self):
        if self.broken_json:
            raise ValueError("not json")
        return self.payload


def _measurement_penalty_row() -> dict:
    return {
        "nmId": 100,
        "dimId": 200,
        "prcOver": 125.0,
        "volume": 2.5,
        "width": 10,
        "length": 25,
        "height": 10,
        "volumeSup": 2.0,
        "widthSup": 10,
        "lengthSup": 20,
        "heightSup": 10,
        "dtBonus": "2026-07-01T00:00:00Z",
        "isValid": True,
        "isValidDt": "2026-07-01T01:00:00Z",
        "penaltyAmount": 10,
        "reversalAmount": 0,
        "photoUrls": ["RAW_PHOTO_URL"],
    }


def test_f4_response_classifier_checks_envelope_and_required_names_only() -> None:
    assert (
        probe.classify_f4_response(
            "measurement_penalties",
            _Response(200, {"data": {"reports": [], "total": 0}}),
        )
        == "confirmed_empty"
    )
    assert (
        probe.classify_f4_response(
            "measurement_penalties",
            _Response(
                200,
                {"data": {"reports": [_measurement_penalty_row()], "total": 1}},
            ),
        )
        == "confirmed_nonempty"
    )
    assert (
        probe.classify_f4_response(
            "measurement_penalties",
            _Response(200, {"data": {"reports": [], "total": 1}}),
        )
        == "schema_mismatch"
    )
    assert (
        probe.classify_f4_response(
            "measurement_penalties", _Response(200, broken_json=True)
        )
        == "schema_mismatch"
    )
    assert (
        probe.classify_f4_response("measurement_penalties", _Response(403))
        == "access_denied"
    )
    assert (
        probe.classify_f4_response("measurement_penalties", _Response(429))
        == "unavailable"
    )


def test_f4_status_aggregation_has_no_values_ids_labels_or_counts() -> None:
    report = probe.aggregate_f4_statuses(
        {
            "measurement_penalties": ["confirmed_nonempty", "access_denied"],
            "warehouse_measurements": ["confirmed_empty", "unavailable"],
        }
    )

    assert report["implementationGate"] is True
    assert report["endpoints"]["measurement_penalties"] == {
        "schemaConfirmedAny": True,
        "confirmedEmptyPresent": False,
        "confirmedNonemptyPresent": True,
        "accessDeniedPresent": True,
        "unavailablePresent": False,
        "schemaMismatchPresent": False,
    }
    rendered = str(report)
    for forbidden in (
        "RAW_PHOTO_URL",
        "nmId",
        "dimId",
        "provider",
        "total",
        "rowCount",
        "cabinetCount",
    ):
        assert forbidden not in rendered


def test_f4_schema_mismatch_blocks_implementation_gate() -> None:
    report = probe.aggregate_f4_statuses(
        {
            "measurement_penalties": ["confirmed_nonempty", "schema_mismatch"],
            "warehouse_measurements": ["confirmed_empty"],
        }
    )

    assert report["implementationGate"] is False
