from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import httpx

from wb_unit_economics.wb_return_claims import (
    RETURN_CLAIMS_ENDPOINT,
    WbReturnClaimsClient,
    build_return_claim_links,
    claims_source_state_message,
    export_wb_return_claims,
    flatten_return_claims,
    normalize_claim_source_row,
)


def _claim(
    *,
    claim_id: str = "claim-safe-1",
    srid: str = "srid-safe-1",
    nm_id: int = 101,
    comment: str = "synthetic buyer comment",
) -> dict:
    return {
        "id": claim_id,
        "srid": srid,
        "nm_id": nm_id,
        "user_comment": comment,
        "wb_comment": "synthetic provider comment",
        "origin_id_info": {"synthetic": True},
        "photos": ["synthetic-photo"],
        "actions": ["synthetic-action"],
    }


def _source_row(
    *,
    srid: object = "srid-safe-1",
    nm_id: object = 101,
    cabinet_id: str = "cabinet-a",
    has_comment: object = True,
):
    return normalize_claim_source_row(
        {
            "srid": srid,
            "nm_id": nm_id,
            "is_archive": False,
            "has_user_comment": has_comment,
        },
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id=cabinet_id,
    )


def _finance_row(
    *,
    chain_key: str = "chain-a",
    finance_srid: str = "srid-safe-1",
    nm_id: str = "101",
    cabinet_id: str = "cabinet-a",
):
    return SimpleNamespace(
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id=cabinet_id,
        nm_id=nm_id,
        finance_srid=finance_srid,
        chain_key=chain_key,
    )


def _return_chain(
    *,
    chain_key: str = "chain-a",
    financial_date: date = date(2026, 7, 20),
):
    return SimpleNamespace(
        chain_key=chain_key,
        financial_date=financial_date,
        return_quantity=1,
        logistics_reverse=0,
    )


def test_client_uses_only_get_boolean_slices_and_reconciles_all_pages() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.method == "GET"
        assert str(request.url).startswith(RETURN_CLAIMS_ENDPOINT)
        is_archive = request.url.params["is_archive"] == "true"
        offset = int(request.url.params["offset"])
        if is_archive:
            return httpx.Response(200, json={"claims": [], "total": 0})
        rows = [
            _claim(claim_id="claim-safe-1"),
            _claim(claim_id="claim-safe-2", srid="srid-safe-2"),
        ]
        return httpx.Response(
            200,
            json={"claims": rows[offset : offset + 1], "total": 2},
        )

    client = WbReturnClaimsClient(
        api_key="test-key",
        page_limit=1,
        request_interval_seconds=0,
        _transport=httpx.MockTransport(handler),
    )
    active = client.fetch_claims(is_archive=False)
    archive = client.fetch_claims(is_archive=True)

    assert len(active["claims"]) == 2
    assert archive == {"claims": [], "total": 0}
    assert [request.url.params["offset"] for request in seen] == ["0", "1", "0"]
    assert {request.url.params["is_archive"] for request in seen} == {
        "false",
        "true",
    }
    assert all(request.headers["Authorization"] == "test-key" for request in seen)


def test_flat_projection_contains_no_comments_claim_ids_or_media() -> None:
    flat = flatten_return_claims(
        {"claims": [_claim()]},
        is_archive=False,
    )

    assert flat == [
        {
            "srid": "srid-safe-1",
            "nm_id": 101,
            "is_archive": False,
            "has_user_comment": True,
        }
    ]
    serialized = json.dumps(flat)
    for forbidden in (
        "claim-safe-1",
        "synthetic buyer comment",
        "synthetic provider comment",
        "synthetic-photo",
        "origin_id_info",
        "actions",
    ):
        assert forbidden not in serialized


def test_export_marks_confirmed_empty_without_blocking(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"claims": [], "total": 0})

    result = export_wb_return_claims(
        WbReturnClaimsClient(
            api_key="test-key",
            request_interval_seconds=0,
            _transport=httpx.MockTransport(handler),
        ),
        tmp_path,
        as_of=date(2026, 7, 23),
    )

    assert result.ok is True
    assert result.source_state == "confirmed_empty"
    assert result.row_count == 0
    assert claims_source_state_message(result.source_state) == (
        "Заявок за доступное окно нет"
    )
    assert result.flat_output_path is not None
    assert json.loads(result.flat_output_path.read_text(encoding="utf-8")) == []


def test_export_marks_access_denied_without_creating_snapshot_files(tmp_path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    result = export_wb_return_claims(
        WbReturnClaimsClient(
            api_key="test-key",
            request_interval_seconds=0,
            _transport=httpx.MockTransport(handler),
        ),
        tmp_path,
        as_of=date(2026, 7, 23),
    )

    assert result.ok is False
    assert result.source_state == "access_denied"
    assert result.raw_output_path is None
    assert result.flat_output_path is None
    assert claims_source_state_message(result.source_state) == (
        "Источник заявок недоступен"
    )
    assert list(tmp_path.iterdir()) == []


def test_exact_match_activates_claim_flags_and_empty_rows_do_not() -> None:
    empty = build_return_claim_links(
        [_finance_row()],
        [_return_chain()],
        [],
        source_coverage_start=date(2026, 7, 10),
        source_coverage_end=date(2026, 7, 23),
    )
    matched = build_return_claim_links(
        [_finance_row()],
        [_return_chain()],
        [_source_row()],
        source_coverage_start=date(2026, 7, 10),
        source_coverage_end=date(2026, 7, 23),
    )

    assert empty.rows == ()
    assert empty.matched_chain_count == 0
    assert empty.finance_unmatched_count == 1
    assert matched.matched_chain_count == 1
    assert matched.finance_unmatched_count == 0
    assert matched.rows[0].coverage_status == "ready"
    assert matched.rows[0].claim_available is True
    assert matched.rows[0].has_user_comment is True
    assert matched.rows[0].evidence_type == "fact"


def test_unmatched_cross_scope_and_ambiguous_finance_never_become_fact() -> None:
    unmatched = build_return_claim_links(
        [_finance_row(cabinet_id="cabinet-b")],
        [_return_chain()],
        [_source_row(cabinet_id="cabinet-a")],
        source_coverage_start=date(2026, 7, 10),
        source_coverage_end=date(2026, 7, 23),
    )
    ambiguous = build_return_claim_links(
        [
            _finance_row(chain_key="chain-a"),
            _finance_row(chain_key="chain-b"),
        ],
        [_return_chain(chain_key="chain-a"), _return_chain(chain_key="chain-b")],
        [_source_row()],
        source_coverage_start=date(2026, 7, 10),
        source_coverage_end=date(2026, 7, 23),
    )

    assert unmatched.rows[0].coverage_status == "unmatched_finance"
    assert unmatched.rows[0].claim_available is False
    assert unmatched.rows[0].has_user_comment is False
    assert unmatched.rows[0].evidence_type == "data_unavailable"
    assert ambiguous.rows[0].coverage_status == "conflicting_finance"
    assert ambiguous.rows[0].claim_available is False


def test_normalizer_rejects_raw_comment_and_claim_id_in_flat_input() -> None:
    row = normalize_claim_source_row(
        {
            "id": "claim-safe-1",
            "srid": "srid-safe-1",
            "nm_id": 101,
            "is_archive": False,
            "has_user_comment": True,
            "user_comment": "synthetic",
        },
        tenant_id="tenant-a",
        client_id="client-a",
        wb_cabinet_id="cabinet-a",
    )

    assert row.identity_key is None
    assert row.validation_errors == ("id_forbidden", "user_comment_forbidden")
