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


def _goods_return_row() -> dict:
    return {
        "reason": "RAW_REASON",
        "status": "RAW_STATUS",
        "returnType": "RAW_RETURN_TYPE",
        "srid": "RAW_SRID",
        "nmId": 100,
    }


def _claim_row() -> dict:
    return {
        "id": "RAW_CLAIM_ID",
        "nm_id": 100,
        "user_comment": "RAW_USER_COMMENT",
        "srid": "RAW_SRID",
        "dt": "2026-07-22T00:00:00",
        "origin_id_info": "RAW_DEVICE_DATA",
        "photos": ["RAW_PHOTO_URL"],
    }


def test_r0_endpoints_are_minimal_read_only_and_claim_archive_is_boolean() -> None:
    endpoints = probe.r0_endpoints(date(2026, 7, 22), days=7)

    assert [item[0] for item in endpoints] == [
        "goods_return",
        "claims_active",
        "claims_archive",
    ]
    goods = endpoints[0]
    assert goods[2] == {"dateFrom": "2026-07-16", "dateTo": "2026-07-22"}
    assert goods[1].startswith("https://seller-analytics-api.wildberries.ru/")
    active = endpoints[1]
    archive = endpoints[2]
    assert active[1] == archive[1]
    assert active[2] == {"is_archive": False, "limit": 1, "offset": 0}
    assert archive[2] == {"is_archive": True, "limit": 1, "offset": 0}

    with pytest.raises(ValueError, match="between 1 and 31"):
        probe.r0_endpoints(date(2026, 7, 22), days=32)


def test_r0_response_classifier_checks_goods_and_claims_contracts() -> None:
    assert (
        probe.classify_r0_response("goods_return", _Response(200, {"report": []}))
        == "confirmed_empty"
    )
    assert (
        probe.classify_r0_response(
            "goods_return", _Response(200, {"report": [_goods_return_row()]})
        )
        == "confirmed_nonempty"
    )
    assert (
        probe.classify_r0_response(
            "claims_active", _Response(200, {"claims": [], "total": 0})
        )
        == "confirmed_empty"
    )
    assert (
        probe.classify_r0_response(
            "claims_archive",
            _Response(200, {"claims": [_claim_row()], "total": 1}),
        )
        == "confirmed_nonempty"
    )
    assert (
        probe.classify_r0_response(
            "claims_active", _Response(200, {"claims": [], "total": 1})
        )
        == "schema_mismatch"
    )
    assert (
        probe.classify_r0_response(
            "goods_return", _Response(200, {"report": [{"reason": "x"}]})
        )
        == "schema_mismatch"
    )
    assert probe.classify_r0_response("goods_return", _Response(401)) == (
        "access_denied"
    )
    assert probe.classify_r0_response("goods_return", _Response(402)) == (
        "paid_scope_required"
    )
    assert probe.classify_r0_response("goods_return", _Response(429)) == (
        "unavailable"
    )
    assert probe.classify_r0_response(
        "goods_return", _Response(200, broken_json=True)
    ) == "schema_mismatch"


def test_r0_status_aggregation_is_boolean_only_and_allows_partial_source() -> None:
    report = probe.aggregate_r0_statuses(
        {
            "goods_return": ["confirmed_nonempty", "access_denied"],
            "claims_active": ["access_denied"],
            "claims_archive": ["paid_scope_required"],
        }
    )

    assert report["goodsReturnGate"] is True
    assert report["claimsGate"] is False
    assert report["completeSourceGate"] is False
    assert report["implementationGate"] is True
    assert report["endpoints"]["goods_return"]["confirmedNonemptyPresent"] is True
    assert report["endpoints"]["claims_archive"][
        "paidScopeRequiredPresent"
    ] is True
    rendered = str(report)
    for forbidden in (
        "RAW_REASON",
        "RAW_USER_COMMENT",
        "RAW_DEVICE_DATA",
        "RAW_PHOTO_URL",
        "user_comment",
        "srid",
        "nm_id",
        "provider",
        "total",
        "rowCount",
        "cabinetCount",
    ):
        assert forbidden not in rendered


def test_r0_join_keys_are_exact_scoped_hashes_without_raw_identifiers() -> None:
    first_account = probe.R0ProbeAccount(
        api_key="test-key",
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id="cabinet-a",
    )
    second_account = first_account._replace(wb_cabinet_id="cabinet-b")
    payload = {"report": [_goods_return_row(), {"srid": "missing-nm"}]}

    first_keys, first_invalid = probe.r0_join_keys(
        "goods_return", payload, first_account
    )
    second_keys, second_invalid = probe.r0_join_keys(
        "goods_return", payload, second_account
    )

    assert first_invalid is True
    assert second_invalid is True
    assert len(first_keys) == 1
    assert len(second_keys) == 1
    assert first_keys != second_keys
    rendered = str(first_keys | second_keys)
    assert "RAW_SRID" not in rendered
    assert "tenant-a" not in rendered
    assert "cabinet-a" not in rendered


def test_r0_schema_mismatch_blocks_only_affected_source_gate() -> None:
    report = probe.aggregate_r0_statuses(
        {
            "goods_return": ["confirmed_empty", "schema_mismatch"],
            "claims_active": ["confirmed_empty"],
            "claims_archive": ["confirmed_nonempty"],
        }
    )

    assert report["goodsReturnGate"] is False
    assert report["claimsGate"] is True
    assert report["completeSourceGate"] is False
    assert report["implementationGate"] is True


def test_r0_join_gate_requires_evaluated_exact_match() -> None:
    assert probe.r0_join_gate(join_evaluated=True, matched_present=True) is True
    assert probe.r0_join_gate(join_evaluated=True, matched_present=False) is False
    assert probe.r0_join_gate(join_evaluated=False, matched_present=True) is False


def test_run_r0_probe_aligns_window_and_returns_only_safe_booleans(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = probe.R0ProbeAccount(
        api_key="test-key",
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id="cabinet-a",
        report_window_end=date(2026, 7, 20),
    )
    requested_params: list[dict] = []

    class _Client:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def get(self, url: str, *, params: dict):
            requested_params.append(params)
            if "goods-return" in url:
                return _Response(200, {"report": [_goods_return_row()]})
            return _Response(200, {"claims": [], "total": 0})

    captured_source_keys: dict[tuple[str, str, str], set[str]] = {}

    def _evaluate(_settings, source_keys_by_scope, **_kwargs):
        captured_source_keys.update(source_keys_by_scope)
        return {
            "joinEvaluated": True,
            "sourceKeyPresent": True,
            "financeReturnKeyPresent": True,
            "matchedPresent": False,
            "sourceUnmatchedPresent": True,
            "financeUnmatchedPresent": True,
            "invalidSourceKeyPresent": False,
            "joinGate": False,
        }

    monkeypatch.setattr(probe.httpx, "Client", _Client)
    monkeypatch.setattr(probe, "evaluate_r0_join", _evaluate)

    report = probe.run_r0_probe(
        [account], object(), date(2026, 7, 22), days=7
    )

    assert requested_params[0] == {
        "dateFrom": "2026-07-14",
        "dateTo": "2026-07-20",
    }
    assert report["reportWindowAligned"] is True
    assert report["sourceImplementationGate"] is True
    assert report["implementationGate"] is False
    assert captured_source_keys[account.scope]
    rendered = str(report) + str(set().union(*captured_source_keys.values()))
    for forbidden in (
        "RAW_REASON",
        "RAW_STATUS",
        "RAW_RETURN_TYPE",
        "RAW_SRID",
        "tenant-a",
        "client-a",
        "cabinet-a",
        "test-key",
    ):
        assert forbidden not in rendered
