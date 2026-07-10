from __future__ import annotations

import json
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts import rebuild_report_from_sources
from wb_unit_economics.calculation import build_unit_economics_report
from wb_unit_economics.contracts import (
    AccountOrgMapping,
    MappingStatus,
    OnecUnfCostSnapshot,
    SkuMapping,
    WbSalesReportSummaryRow,
)
from wb_unit_economics.streaming_report import build_streamed_unit_economics_report
from wb_unit_economics.wb_finance import load_wb_finance_snapshots

TZ = ZoneInfo("Europe/Moscow")


def test_streamed_report_matches_list_builder_with_weekly_allocations(
    tmp_path: Path,
) -> None:
    wb_dir = _write_wb_export(
        tmp_path,
        rows=[
            {
                "rrdId": 1,
                "reportId": "777",
                "rrDate": "2026-06-10",
                "nmId": 101,
                "vendorCode": "A-1",
                "sku": "101-size",
                "docTypeName": "Продажа",
                "quantity": 2,
                "retailAmount": "1000",
                "ppvzSalesCommission": "100",
                "deliveryService": "30",
                "paidStorage": "10",
                "deduction": "5",
                "acquiringFee": "11",
            },
            {
                "rrdId": 2,
                "reportId": "777",
                "rrDate": "2026-06-11",
                "nmId": 102,
                "vendorCode": "B-2",
                "sku": "102-size",
                "docTypeName": "Продажа",
                "quantity": 1,
                "retailAmount": "500",
                "ppvzSalesCommission": "50",
                "deliveryService": "20",
                "paidStorage": "5",
                "deduction": "10",
                "acquiringFee": "7",
            },
            {
                "rrdId": 3,
                "reportId": "888",
                "rrDate": "2026-06-17",
                "nmId": 101,
                "vendorCode": "A-1",
                "sku": "101-size",
                "docTypeName": "Продажа",
                "quantity": 1,
                "retailAmount": "200",
                "ppvzSalesCommission": "20",
                "deliveryService": "5",
                "paidStorage": "2",
                "deduction": "1",
                "acquiringFee": "3",
            },
        ],
    )
    generated_at = datetime(2026, 7, 4, 12, 0, tzinfo=TZ)
    account_mapping = [
        AccountOrgMapping(
            client_id="client",
            seller_account_id="WB_ACCOUNT_1",
            organization_id="ORG-1",
            seller_account_name="Кабинет",
            organization_name="Организация",
        )
    ]
    costs = [
        _cost("ITEM-101", "A-1", Decimal("100")),
        _cost("ITEM-102", "B-2", Decimal("50")),
    ]
    mappings = [
        _mapping(101, "A-1", "101-size", "ITEM-101"),
        _mapping(102, "B-2", "102-size", "ITEM-102"),
    ]
    summary_rows = [
        _summary("777", date(2026, 6, 8), date(2026, 6, 14), 60, 30, 12),
        _summary("888", date(2026, 6, 15), date(2026, 6, 21), 2, 1, 0),
    ]

    wb_snapshots = load_wb_finance_snapshots(
        wb_dir,
        client_id="client",
        account_org_mapping=account_mapping,
    )
    expected = build_unit_economics_report(
        client_id="client",
        wb_snapshots=wb_snapshots,
        cost_snapshots=costs,
        sku_mappings=mappings,
        account_org_mapping=account_mapping,
        wb_sales_report_summary_rows=summary_rows,
        generated_at=generated_at,
        report_period_start=date(2026, 6, 10),
        report_period_end=date(2026, 6, 17),
    )

    streamed = build_streamed_unit_economics_report(
        client_id="client",
        wb_finance_dir=wb_dir,
        cost_snapshots=costs,
        sku_mappings=mappings,
        account_org_mapping=account_mapping,
        wb_sales_report_summary_rows=summary_rows,
        generated_at=generated_at,
        report_period_start=date(2026, 6, 10),
        report_period_end=date(2026, 6, 17),
        stream_cache_dir=tmp_path / "stream-cache",
    )

    assert streamed.wb_rows == 2
    assert streamed.bucket_count == 1
    assert streamed.report.model_dump(mode="json") == expected.model_dump(mode="json")


def test_rebuild_report_cli_accepts_files_stream(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rebuild_report_from_sources.py",
            "--report-id",
            "files-stream-cli-test",
            "--wb-finance-source",
            "files-stream",
            "--onec-services-dir",
            "data/onec_marketplace_service_samples/example",
            "--draft-only",
        ],
    )

    args = rebuild_report_from_sources.parse_args()

    assert args.wb_finance_source == "files-stream"
    assert args.onec_services_dir == Path(
        "data/onec_marketplace_service_samples/example"
    )
    assert args.stream_cache_dir == Path("data/.cache/wb_stream_rebuild")
    assert args.keep_stream_cache is False
    assert args.draft_only is True


def test_rebuild_report_cli_builds_audited_explicit_osno_profile(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "rebuild_report_from_sources.py",
            "--report-id",
            "explicit-osno-profile-test",
            "--tax-system",
            "ОСНО",
            "--vat-rate",
            "22",
            "--vat-deduction-mode",
            "allowed",
            "--tax-profile-source",
            "accepted-plan:galustov-osno-2026",
        ],
    )
    args = rebuild_report_from_sources.parse_args()
    mapping = [
        AccountOrgMapping(
            client_id="galustov",
            seller_account_id="wb-1",
            organization_id="onec-1",
            seller_account_name="ИП Галустов",
            organization_name="Галустов Рафаэль Рудольфович",
        )
    ]

    profiles = rebuild_report_from_sources._tax_profiles_for_rebuild(
        args,
        mapping,
        source_profiles=[],
    )

    assert len(profiles) == 1
    assert profiles[0].tax_system == "ОСНО"
    assert profiles[0].vat_rate == Decimal("22")
    assert profiles[0].vat_deduction_mode.value == "allowed"
    assert profiles[0].source == "accepted-plan:galustov-osno-2026"


def _write_wb_export(tmp_path: Path, *, rows: list[dict[str, object]]) -> Path:
    export_dir = tmp_path / "wb_finance"
    export_dir.mkdir()
    raw_file = export_dir / "wb_account_1_finance_page_1.raw.json"
    raw_file.write_text(
        json.dumps(rows, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    manifest = {
        "generated_at": "2026-07-04T12:00:00+03:00",
        "period_start": "2026-06-10",
        "period_end": "2026-06-17",
        "results": [
            {
                "seller_account_id": "WB_ACCOUNT_1",
                "account_name": "Кабинет",
                "status": "ok",
                "output_file": raw_file.name,
            },
            {
                "seller_account_id": "WB_ACCOUNT_1",
                "account_name": "Кабинет",
                "status": "no_data",
            },
        ],
    }
    (export_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return export_dir


def _mapping(
    nm_id: int,
    vendor_code: str,
    barcode: str,
    onec_item_id: str,
) -> SkuMapping:
    return SkuMapping(
        client_id="client",
        seller_account_id="WB_ACCOUNT_1",
        organization_id="ORG-1",
        nm_id=nm_id,
        vendor_code=vendor_code.lower(),
        barcode=barcode,
        onec_item_id=onec_item_id,
        onec_article=vendor_code,
        match_method="test",
        confidence=Decimal("1"),
        status=MappingStatus.MATCHED,
        updated_by="test",
        updated_at=datetime(2026, 7, 4, 12, 0, tzinfo=TZ),
    )


def _cost(onec_item_id: str, article: str, cost_value: Decimal) -> OnecUnfCostSnapshot:
    return OnecUnfCostSnapshot(
        client_id="client",
        organization_id="ORG-1",
        loaded_at=datetime(2026, 7, 4, 12, 0, tzinfo=TZ),
        onec_item_id=onec_item_id,
        article=article,
        barcode="",
        name=article,
        cost_value=cost_value,
        extra_costs_value=Decimal("0"),
        cost_currency="RUB",
        cost_method="test",
        effective_from=date(2026, 1, 1),
        source_document="test",
        raw_payload_hash=onec_item_id,
    )


def _summary(
    report_id: str,
    date_from: date,
    date_to: date,
    paid_storage_sum: int,
    deduction_sum: int,
    cashback_discount_sum: int,
) -> WbSalesReportSummaryRow:
    return WbSalesReportSummaryRow(
        client_id="client",
        seller_account_id="WB_ACCOUNT_1",
        account_name="Кабинет",
        report_id=report_id,
        date_from=date_from,
        date_to=date_to,
        create_date=date_to,
        paid_storage_sum=Decimal(paid_storage_sum),
        deduction_sum=Decimal(deduction_sum),
        cashback_discount_sum=Decimal(cashback_discount_sum),
        raw_payload_hash=report_id,
    )
