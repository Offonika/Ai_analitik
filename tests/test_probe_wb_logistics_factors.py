from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

import pytest

from wb_unit_economics.logistics_analysis import source_row_from_payload

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
        "data": [{"reason": "RAWVALUE", "status": "RAWSTATUS", "srid": "z", "nmId": 1}]
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
        "orderId": 9001,
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
    assert active[2] == {"is_archive": False, "limit": 200, "offset": 0}
    assert archive[2] == {"is_archive": True, "limit": 200, "offset": 0}

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
    assert probe.classify_r0_response("goods_return", _Response(429)) == ("unavailable")
    assert (
        probe.classify_r0_response("goods_return", _Response(200, broken_json=True))
        == "schema_mismatch"
    )


def test_claims_fetch_reconciles_all_pages_without_exposing_raw_values() -> None:
    requested_params: list[dict] = []
    first = {**_claim_row(), "id": "RAW_CLAIM_FIRST", "srid": "RAW_SRID_FIRST"}
    second = {
        **_claim_row(),
        "id": "RAW_CLAIM_SECOND",
        "srid": "RAW_SRID_SECOND",
    }

    class _Client:
        def get(self, _url: str, *, params: dict):
            requested_params.append(dict(params))
            row = first if params["offset"] == 0 else second
            return _Response(200, {"claims": [row], "total": 2})

    status, payload = probe.fetch_r0_source_payload(
        _Client(),
        "claims_active",
        "https://returns-api.wildberries.ru/api/v1/claims",
        {"is_archive": False, "limit": 1, "offset": 0},
        claims_request_interval_seconds=0,
    )

    assert status == "confirmed_nonempty"
    assert payload is not None and len(payload["claims"]) == 2
    assert requested_params == [
        {"is_archive": False, "limit": 1, "offset": 0},
        {"is_archive": False, "limit": 1, "offset": 1},
    ]
    account = probe.R0ProbeAccount(
        api_key="",
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id="cabinet-a",
    )
    keys, ambiguity, invalid = probe.r0_identity_source_keys(
        "claims_active",
        payload,
        account,
    )
    rendered = str(keys) + str(ambiguity) + str(invalid)
    for forbidden in (
        "RAW_CLAIM_FIRST",
        "RAW_CLAIM_SECOND",
        "RAW_SRID_FIRST",
        "RAW_SRID_SECOND",
        "RAW_USER_COMMENT",
    ):
        assert forbidden not in rendered


@pytest.mark.parametrize("failure", ["duplicate", "changing_total", "empty_page"])
def test_claims_fetch_fails_closed_on_pagination_mismatch(failure: str) -> None:
    first = {**_claim_row(), "id": "claim-first"}

    class _Client:
        def get(self, _url: str, *, params: dict):
            if params["offset"] == 0:
                return _Response(200, {"claims": [first], "total": 2})
            if failure == "duplicate":
                return _Response(200, {"claims": [first], "total": 2})
            if failure == "changing_total":
                return _Response(
                    200,
                    {"claims": [{**_claim_row(), "id": "claim-second"}], "total": 3},
                )
            return _Response(200, {"claims": [], "total": 2})

    status, payload = probe.fetch_r0_source_payload(
        _Client(),
        "claims_archive",
        "https://returns-api.wildberries.ru/api/v1/claims",
        {"is_archive": True, "limit": 1, "offset": 0},
        claims_request_interval_seconds=0,
    )

    assert status == "pagination_mismatch"
    assert payload is None


def test_claims_fetch_caps_provider_total_before_partial_evidence() -> None:
    class _Client:
        def get(self, _url: str, *, params: dict):
            return _Response(200, {"claims": [_claim_row()], "total": 3})

    status, payload = probe.fetch_r0_source_payload(
        _Client(),
        "claims_active",
        "https://returns-api.wildberries.ru/api/v1/claims",
        {"is_archive": False, "limit": 1, "offset": 0},
        claims_max_pages=2,
        claims_request_interval_seconds=0,
    )

    assert status == "pagination_mismatch"
    assert payload is None


def test_claims_fetch_paces_first_page_and_active_archive_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps: list[float] = []

    class _Client:
        def get(self, _url: str, *, params: dict):
            return _Response(200, {"claims": [], "total": 0})

    monkeypatch.setattr(probe.time_module, "sleep", sleeps.append)
    for name, is_archive in (
        ("claims_active", False),
        ("claims_archive", True),
    ):
        status, payload = probe.fetch_r0_source_payload(
            _Client(),
            name,
            "https://returns-api.wildberries.ru/api/v1/claims",
            {"is_archive": is_archive, "limit": 200, "offset": 0},
            claims_request_interval_seconds=3.1,
        )
        assert status == "confirmed_empty"
        assert payload == {"claims": []}

    assert sleeps == [3.1, 3.1]


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
    assert report["endpoints"]["claims_archive"]["paidScopeRequiredPresent"] is True
    assert report["endpoints"]["claims_archive"]["paginationMismatchPresent"] is False
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


def test_r0_pagination_mismatch_blocks_claims_gate() -> None:
    report = probe.aggregate_r0_statuses(
        {
            "goods_return": ["confirmed_nonempty"],
            "claims_active": ["confirmed_nonempty", "pagination_mismatch"],
            "claims_archive": ["confirmed_empty"],
        }
    )

    assert report["goodsReturnGate"] is True
    assert report["claimsGate"] is False
    assert report["endpoints"]["claims_active"]["paginationMismatchPresent"] is True


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
    monkeypatch.setattr(probe, "CLAIMS_REQUEST_INTERVAL_SECONDS", 0)

    report = probe.run_r0_probe([account], object(), date(2026, 7, 22), days=7)

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


def test_r0_identity_source_keys_are_scoped_and_detect_order_ambiguity() -> None:
    account = probe.R0ProbeAccount(
        api_key="test-key",
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id="cabinet-a",
    )
    second = {**_goods_return_row(), "srid": "SECOND_RAW_SRID"}

    keys, ambiguous, invalid = probe.r0_identity_source_keys(
        "goods_return",
        {"report": [_goods_return_row(), second]},
        account,
    )

    assert len(keys["goodsReturnSrid"]) == 2
    assert len(keys["goodsReturnOrderId"]) == 1
    assert ambiguous["goodsReturnSrid"] is False
    assert ambiguous["goodsReturnOrderId"] is True
    assert invalid["goodsReturnSrid"] is False
    assert invalid["goodsReturnOrderId"] is False
    rendered = str(keys) + str(ambiguous) + str(invalid)
    for forbidden in (
        "RAW_SRID",
        "SECOND_RAW_SRID",
        "tenant-a",
        "client-a",
        "cabinet-a",
        "9001",
    ):
        assert forbidden not in rendered


def test_finance_identity_maps_resolve_same_name_fields_to_canonical_chain() -> None:
    row = source_row_from_payload(
        {
            "rrDate": "2026-07-20",
            "orderUid": "FINANCE_ORDER_UID",
            "srid": "SHARED_SRID",
            "orderId": 9001,
            "nmId": 100,
            "deliveryMethod": "FBO",
            "deliveryService": 10,
            "returnAmount": 1,
        },
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id="cabinet-a",
        client_company_id="company-a",
        fallback_date=date(2026, 7, 20),
    )
    account = probe.R0ProbeAccount(
        api_key="",
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id="cabinet-a",
    )

    maps = probe._finance_identity_maps(
        [row],
        tenant_id="tenant-a",
        client_id="client-a",
        cabinet_id="cabinet-a",
        return_keys={row.chain_key},
    )

    srid_key = probe._r0_identity_key(
        account,
        identifier="SHARED_SRID",
        nm_id="100",
    )
    order_id_key = probe._r0_identity_key(
        account,
        identifier="9001",
        nm_id="100",
    )
    assert maps["financeOrderUid"] == {row.chain_key: {row.chain_key}}
    assert maps["financeSrid"] == {srid_key: {row.chain_key}}
    assert maps["financeOrderId"] == {order_id_key: {row.chain_key}}


def test_r0_identity_same_name_match_opens_only_source_specific_gate() -> None:
    account = probe.R0ProbeAccount(
        api_key="",
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id="cabinet-a",
    )
    source, ambiguity, invalid = probe.r0_identity_source_keys(
        "goods_return",
        {"report": [_goods_return_row()]},
        account,
    )
    srid_key = next(iter(source["goodsReturnSrid"]))
    order_id_key = next(iter(source["goodsReturnOrderId"]))
    finance_maps = {
        account.scope: {
            "financeOrderUid": {},
            "financeSrid": {srid_key: {"canonical-chain"}},
            "financeOrderId": {order_id_key: {"canonical-chain"}},
        }
    }
    finance_state = {
        account.scope: {
            "joinEvaluated": True,
            "verifiedLineage": True,
            "lineageFailurePresent": False,
            "financeReturnKeyPresent": True,
        }
    }

    report = probe.evaluate_r0_identity(
        {account.scope: source},
        {account.scope: ambiguity},
        {account.scope: invalid},
        finance_maps,
        finance_state,
    )

    assert report["goodsReturnIdentityGate"] is True
    assert report["claimsIdentityGate"] is False
    assert report["completeIdentityGate"] is False
    assert report["goodsReturnImplementationGate"] is True
    assert report["claimsImplementationGate"] is False
    assert report["sameNameEvidencePresent"] is True
    assert report["baselineDirectMatchPresent"] is False
    assert report["contractChangeRequired"] is False


def test_r0_identity_canonical_ambiguity_blocks_candidate() -> None:
    account = probe.R0ProbeAccount(
        api_key="",
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id="cabinet-a",
    )
    source, ambiguity, invalid = probe.r0_identity_source_keys(
        "goods_return",
        {"report": [_goods_return_row()]},
        account,
    )
    srid_key = next(iter(source["goodsReturnSrid"]))
    empty_finance = {field: {} for field in probe.R0_IDENTITY_FINANCE_FIELDS}
    empty_finance["financeSrid"] = {
        srid_key: {"canonical-chain-a", "canonical-chain-b"}
    }

    report = probe.evaluate_r0_identity(
        {account.scope: source},
        {account.scope: ambiguity},
        {account.scope: invalid},
        {account.scope: empty_finance},
        {
            account.scope: {
                "joinEvaluated": True,
                "verifiedLineage": True,
                "lineageFailurePresent": False,
                "financeReturnKeyPresent": True,
            }
        },
    )

    candidate = report["candidates"]["goodsReturnSridToFinanceSrid"]
    assert candidate["matchedPresent"] is True
    assert candidate["financeAmbiguityPresent"] is True
    assert candidate["candidateGate"] is False
    assert report["goodsReturnIdentityGate"] is False


def test_r0_identity_database_file_ambiguity_blocks_verified_match() -> None:
    account = probe.R0ProbeAccount(
        api_key="",
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id="cabinet-a",
    )
    source, ambiguity, invalid = probe.r0_identity_source_keys(
        "goods_return",
        {"report": [_goods_return_row()]},
        account,
    )
    srid_key = next(iter(source["goodsReturnSrid"]))
    finance = {field: {} for field in probe.R0_IDENTITY_FINANCE_FIELDS}
    finance["financeSrid"] = {srid_key: {"canonical-chain"}}

    report = probe.evaluate_r0_identity(
        {account.scope: source},
        {account.scope: ambiguity},
        {account.scope: invalid},
        {account.scope: finance},
        {
            account.scope: {
                "joinEvaluated": True,
                "verifiedLineage": False,
                "lineageFailurePresent": True,
                "financeReturnKeyPresent": True,
                "sourceIntegrityFailurePresent": True,
                "storageIntegrityFailurePresent": True,
                "databaseFileAmbiguityPresent": True,
            }
        },
    )

    candidate = report["candidates"]["goodsReturnSridToFinanceSrid"]
    assert candidate["matchedPresent"] is True
    assert candidate["databaseFileAmbiguityPresent"] is True
    assert candidate["verifiedLineagePresent"] is False
    assert candidate["candidateGate"] is False
    assert report["goodsReturnIdentityGate"] is False


def test_latest_r0_report_reads_only_pre_factor_columns() -> None:
    class _Result:
        @staticmethod
        def first():
            return (
                "report-a",
                "tenant-a",
                "client-a",
                date(2026, 7, 1),
                date(2026, 7, 20),
            )

    class _Db:
        @staticmethod
        def execute(statement):
            assert tuple(column.key for column in statement.selected_columns) == (
                "id",
                "tenant_id",
                "client_id",
                "period_start",
                "period_end",
            )
            return _Result()

    report = probe._latest_r0_report(
        _Db(),
        tenant_id="tenant-a",
        client_id="client-a",
        cabinet_id="cabinet-a",
    )

    assert report == probe.R0ReportContext(
        "report-a",
        "tenant-a",
        "client-a",
        date(2026, 7, 1),
        date(2026, 7, 20),
    )


def test_r0_lineage_preflight_finds_existing_verified_file_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = probe.R0ProbeAccount(
        api_key="test-key",
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id="cabinet-a",
    )
    source_row = source_row_from_payload(
        {"orderUid": "RAW_ORDER", "nmId": 101},
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id="cabinet-a",
        client_company_id="company-a",
        source_row_id="source-a",
        source_hash="hash-a",
        fallback_date=None,
    )
    return_key = source_row.chain_key
    candidates = [
        probe.R0ReportContext(
            "report-new",
            "tenant-a",
            "client-a",
            date(2026, 7, 1),
            date(2026, 7, 20),
        ),
        probe.R0ReportContext(
            "report-old",
            "tenant-a",
            "client-a",
            date(2026, 6, 1),
            date(2026, 6, 20),
        ),
    ]

    class _Db:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        @staticmethod
        def scalars(_statement):
            return [return_key]

        @staticmethod
        def rollback() -> None:
            return None

    def _selected(_db, report):
        if report.id == "report-new":
            return (
                [],
                False,
                {
                    "sourceIntegrityFailurePresent": True,
                    "databaseFileAmbiguityPresent": True,
                    "databaseStoragePresent": True,
                    "fileStoragePresent": True,
                    "unambiguousStoragePresent": False,
                },
            )
        return (
            [source_row],
            True,
            {
                "databaseStoragePresent": False,
                "fileStoragePresent": True,
                "unambiguousStoragePresent": True,
            },
        )

    monkeypatch.setattr(probe, "make_engine", lambda _url: object())
    monkeypatch.setattr(probe, "make_session_factory", lambda _engine: lambda: _Db())
    monkeypatch.setattr(
        probe,
        "_r0_report_candidates",
        lambda *_args, **_kwargs: candidates,
    )
    monkeypatch.setattr(probe, "_selected_finance_identity_rows", _selected)

    class _Settings:
        database_url = "sqlite://"

    report = probe.run_r0_lineage_preflight([account], _Settings())

    assert report["candidateReportPresent"] is True
    assert report["databaseFileAmbiguityPresent"] is True
    assert report["verifiedUnambiguousReturnLineagePresent"] is True
    assert report["databaseOnlyVerifiedPresent"] is False
    assert report["fileOnlyVerifiedPresent"] is True
    assert report["newReportRequired"] is False
    assert report["acceptedReuseDecisionRequired"] is True
    assert report["implementationGate"] is False
    rendered = str(report)
    for forbidden in (
        "tenant-a",
        "client-a",
        "cabinet-a",
        "report-new",
        "report-old",
        "RAW_ORDER",
        "source-a",
        "company-a",
        "test-key",
    ):
        assert forbidden not in rendered


def test_r0_lineage_preflight_preserves_storage_evidence_across_scopes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    accounts = [
        probe.R0ProbeAccount(
            api_key="key-a",
            tenant_id="tenant-a",
            client_id="client-a",
            wb_cabinet_id="cabinet-a",
        ),
        probe.R0ProbeAccount(
            api_key="key-b",
            tenant_id="tenant-b",
            client_id="client-b",
            wb_cabinet_id="cabinet-b",
        ),
    ]
    source_rows = {
        "report-a": source_row_from_payload(
            {"orderUid": "order-a", "nmId": 101},
            tenant_id="tenant-a",
            client_id="client-a",
            wb_cabinet_id="cabinet-a",
            client_company_id="company-a",
            source_row_id="source-a",
            source_hash="hash-a",
            fallback_date=None,
        ),
        "report-b": source_row_from_payload(
            {"orderUid": "order-b", "nmId": 202},
            tenant_id="tenant-b",
            client_id="client-b",
            wb_cabinet_id="cabinet-b",
            client_company_id="company-b",
            source_row_id="source-b",
            source_hash="hash-b",
            fallback_date=None,
        ),
    }

    class _Db:
        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        @staticmethod
        def scalars(_statement):
            return [row.chain_key for row in source_rows.values()]

        @staticmethod
        def rollback() -> None:
            return None

    def _candidates(_db, **kwargs):
        suffix = kwargs["cabinet_id"][-1]
        return [
            probe.R0ReportContext(
                f"report-{suffix}",
                kwargs["tenant_id"],
                kwargs["client_id"],
                date(2026, 7, 1),
                date(2026, 7, 20),
            )
        ]

    def _selected(_db, report):
        database = report.id == "report-a"
        return (
            [source_rows[report.id]],
            True,
            {
                "databaseStoragePresent": database,
                "fileStoragePresent": not database,
                "unambiguousStoragePresent": True,
            },
        )

    monkeypatch.setattr(probe, "make_engine", lambda _url: object())
    monkeypatch.setattr(probe, "make_session_factory", lambda _engine: lambda: _Db())
    monkeypatch.setattr(probe, "_r0_report_candidates", _candidates)
    monkeypatch.setattr(probe, "_selected_finance_identity_rows", _selected)

    class _Settings:
        database_url = "sqlite://"

    report = probe.run_r0_lineage_preflight(accounts, _Settings())

    assert report["verifiedUnambiguousReturnLineagePresent"] is True
    assert report["databaseOnlyVerifiedPresent"] is True
    assert report["fileOnlyVerifiedPresent"] is True


def test_run_r0_identity_probe_is_boolean_only_and_never_implements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = probe.R0ProbeAccount(
        api_key="test-key",
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id="cabinet-a",
        report_window_end=date(2026, 7, 20),
    )

    class _Client:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def get(self, url: str, *, params: dict):
            if "goods-return" in url:
                return _Response(200, {"report": [_goods_return_row()]})
            return _Response(200, {"claims": [], "total": 0})

    source_keys, _ambiguity, _invalid = probe.r0_identity_source_keys(
        "goods_return",
        {"report": [_goods_return_row()]},
        account,
    )
    srid_key = next(iter(source_keys["goodsReturnSrid"]))

    def _load(_settings, scopes):
        assert scopes == {account.scope}
        return (
            {
                account.scope: {
                    "financeOrderUid": {},
                    "financeSrid": {srid_key: {"canonical-chain"}},
                    "financeOrderId": {},
                }
            },
            {
                account.scope: {
                    "joinEvaluated": True,
                    "verifiedLineage": True,
                    "lineageFailurePresent": False,
                    "financeReturnKeyPresent": True,
                }
            },
        )

    monkeypatch.setattr(probe.httpx, "Client", _Client)
    monkeypatch.setattr(probe, "load_r0_finance_identity", _load)
    monkeypatch.setattr(probe, "CLAIMS_REQUEST_INTERVAL_SECONDS", 0)

    report = probe.run_r0_identity_probe([account], object(), date(2026, 7, 22), days=7)

    assert report["identity"]["goodsReturnIdentityGate"] is True
    assert report["identity"]["completeIdentityGate"] is False
    assert report["goodsReturnImplementationGate"] is True
    assert report["claimsImplementationGate"] is False
    assert report["implementationGate"] is False
    rendered = str(report)
    for forbidden in (
        "RAW_REASON",
        "RAW_STATUS",
        "RAW_RETURN_TYPE",
        "RAW_SRID",
        "tenant-a",
        "client-a",
        "cabinet-a",
        "test-key",
        "9001",
        "canonical-chain",
    ):
        assert forbidden not in rendered


def test_run_r0_identity_probe_uses_all_claim_pages_and_keeps_r2_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = probe.R0ProbeAccount(
        api_key="test-key",
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id="cabinet-a",
        report_window_end=date(2026, 7, 20),
    )
    first_claim = {
        **_claim_row(),
        "id": "RAW_FIRST_CLAIM",
        "srid": "RAW_UNMATCHED_SRID",
    }
    matched_claim = {
        **_claim_row(),
        "id": "RAW_MATCHED_CLAIM",
        "srid": "RAW_MATCHED_SRID",
    }
    requested_active_offsets: list[int] = []

    class _Client:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def get(self, url: str, *, params: dict):
            if "goods-return" in url:
                return _Response(200, {"report": []})
            if params["is_archive"]:
                return _Response(200, {"claims": [], "total": 0})
            requested_active_offsets.append(params["offset"])
            row = first_claim if params["offset"] == 0 else matched_claim
            return _Response(200, {"claims": [row], "total": 2})

    source_keys, _ambiguity, _invalid = probe.r0_identity_source_keys(
        "claims_active",
        {"claims": [matched_claim]},
        account,
    )
    matching_key = next(iter(source_keys["claimsSrid"]))

    def _load(_settings, scopes):
        assert scopes == {account.scope}
        return (
            {
                account.scope: {
                    "financeOrderUid": {},
                    "financeSrid": {matching_key: {"canonical-chain"}},
                    "financeOrderId": {},
                }
            },
            {
                account.scope: {
                    "joinEvaluated": True,
                    "verifiedLineage": True,
                    "lineageFailurePresent": False,
                    "financeReturnKeyPresent": True,
                }
            },
        )

    monkeypatch.setattr(probe, "CLAIMS_PAGE_LIMIT", 1)
    monkeypatch.setattr(probe, "CLAIMS_REQUEST_INTERVAL_SECONDS", 0)
    monkeypatch.setattr(probe.httpx, "Client", _Client)
    monkeypatch.setattr(probe, "load_r0_finance_identity", _load)

    report = probe.run_r0_identity_probe(
        [account],
        object(),
        date(2026, 7, 22),
        days=7,
    )

    assert requested_active_offsets == [0, 1]
    assert report["identity"]["claimsIdentityGate"] is True
    assert report["identity"]["goodsReturnIdentityGate"] is False
    assert report["identity"]["completeIdentityGate"] is False
    assert report["identity"]["claimsImplementationGate"] is False
    assert report["claimsImplementationGate"] is False
    assert report["implementationGate"] is False
    rendered = str(report)
    for forbidden in (
        "RAW_FIRST_CLAIM",
        "RAW_MATCHED_CLAIM",
        "RAW_UNMATCHED_SRID",
        "RAW_MATCHED_SRID",
        "RAW_USER_COMMENT",
        "canonical-chain",
        "tenant-a",
        "client-a",
        "cabinet-a",
        "test-key",
    ):
        assert forbidden not in rendered
