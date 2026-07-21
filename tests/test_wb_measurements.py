from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx

from wb_unit_economics.wb_measurements import (
    MEASUREMENT_PENALTIES_ENDPOINT,
    WAREHOUSE_MEASUREMENTS_ENDPOINT,
    WbMeasurementsClient,
    export_wb_measurement_penalties,
    flatten_measurement_penalties,
    flatten_warehouse_measurements,
)


def _penalty_row(dim_id: int) -> dict:
    return {
        "nmId": 100 + dim_id,
        "subjectName": "RAW SUBJECT",
        "dimId": dim_id,
        "prcOver": 125.0,
        "volume": 2.5,
        "width": 10,
        "length": 25,
        "height": 10,
        "volumeSup": 2.0,
        "widthSup": 10,
        "lengthSup": 20,
        "heightSup": 10,
        "photoUrls": ["RAW PHOTO URL"],
        "dtBonus": "2026-07-01T00:00:00Z",
        "isValid": True,
        "isValidDt": "2026-07-01T01:00:00Z",
        "penaltyAmount": 10,
        "reversalAmount": 0,
    }


def test_measurement_penalties_pagination_reconciles_provider_total() -> None:
    offsets: list[str] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(MEASUREMENT_PENALTIES_ENDPOINT)
        assert request.method == "GET"
        params = request.url.params
        offsets.append(params["offset"])
        assert params["limit"] == "2"
        if params["offset"] == "0":
            rows = [_penalty_row(1), _penalty_row(2)]
        else:
            rows = [_penalty_row(3)]
        return httpx.Response(200, json={"data": {"reports": rows, "total": 3}})

    client = WbMeasurementsClient(
        "token",
        page_limit=2,
        page_delay_seconds=0.25,
        _transport=httpx.MockTransport(handler),
        _sleep=sleeps.append,
    )
    payload = client.fetch_measurement_penalties(
        date_from=datetime(2026, 7, 1, tzinfo=UTC),
        date_to=datetime(2026, 7, 21, tzinfo=UTC),
    )

    assert payload.provider_total == 3
    assert [row["dimId"] for row in payload.rows] == [1, 2, 3]
    assert offsets == ["0", "2"]
    assert sleeps == [0.25]


def test_warehouse_measurements_uses_separate_read_only_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith(WAREHOUSE_MEASUREMENTS_ENDPOINT)
        assert request.method == "GET"
        return httpx.Response(200, json={"data": {"reports": [], "total": 0}})

    payload = WbMeasurementsClient(
        "token", _transport=httpx.MockTransport(handler)
    ).fetch_warehouse_measurements(
        date_from=datetime(2026, 7, 1, tzinfo=UTC),
        date_to=datetime(2026, 7, 21, tzinfo=UTC),
    )

    assert payload.rows == []
    assert payload.provider_total == 0


def test_flat_measurement_rows_omit_photos_and_subject_values() -> None:
    penalty = flatten_measurement_penalties([_penalty_row(7)])[0]
    warehouse = flatten_warehouse_measurements(
        [
            {
                "nmId": 10,
                "subjectName": "RAW SUBJECT",
                "dimId": 11,
                "volume": 1,
                "width": 10,
                "length": 10,
                "height": 10,
                "photoUrls": ["RAW PHOTO URL"],
                "dt": "2026-07-02T00:00:00Z",
            }
        ]
    )[0]

    rendered = json.dumps([penalty, warehouse], ensure_ascii=False)
    assert "photo" not in rendered.lower()
    assert "subject" not in rendered.lower()
    assert "RAW" not in rendered
    assert penalty["penalty_amount"] == 10
    assert warehouse["dt"] == "2026-07-02T00:00:00Z"


def test_measurement_export_keeps_raw_evidence_but_safe_flat(tmp_path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"data": {"reports": [_penalty_row(9)], "total": 1}},
        )

    result = export_wb_measurement_penalties(
        WbMeasurementsClient("token", _transport=httpx.MockTransport(handler)),
        tmp_path,
        date_from=datetime(2026, 7, 1, tzinfo=UTC),
        date_to=datetime(2026, 7, 21, tzinfo=UTC),
        seller_account_id="account",
        file_prefix="safe",
    )

    assert result.ok is True
    assert result.row_count == result.provider_total == 1
    assert result.raw_output_path is not None
    assert result.flat_output_path is not None
    raw_text = result.raw_output_path.read_text(encoding="utf-8")
    flat_text = result.flat_output_path.read_text(encoding="utf-8")
    assert "RAW PHOTO URL" in raw_text
    assert "RAW SUBJECT" in raw_text
    assert "RAW" not in flat_text
    assert result.raw_payload_hash
    assert result.flat_payload_hash


def test_incomplete_measurement_page_fails_closed() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"reports": [], "total": 2}})

    result = export_wb_measurement_penalties(
        WbMeasurementsClient("token", _transport=httpx.MockTransport(handler)),
        Path("unused"),
        date_from=datetime(2026, 7, 1, tzinfo=UTC),
        date_to=datetime(2026, 7, 21, tzinfo=UTC),
    )

    assert result.ok is False
    assert result.error == "ValueError"
