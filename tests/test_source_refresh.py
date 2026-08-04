from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from cryptography.fernet import Fernet
from openpyxl import Workbook
from sqlalchemy.exc import OperationalError

from wb_unit_economics.contracts import (
    MarketplaceFinanceDailyFact,
    TaxProfile,
    VatDeductionMode,
    VatMode,
)
from wb_unit_economics.onec_odata import (
    OnecODataMetadataCheckResult,
    OnecSampleExportResult,
)
from wb_unit_economics.ozon import OzonPageResult
from wb_unit_economics.wb_content import WbProductCardsPageResult
from wb_unit_economics.wb_documents import WbDocumentExportResult
from wb_unit_economics.wb_finance import (
    WbFinancePageResult,
    WbFinanceSellerAccount,
    WbFinanceSettings,
    WbSalesReportListPageResult,
)
from wb_unit_economics.wb_goods_return import WbGoodsReturnExportResult
from wb_unit_economics.wb_return_claims import WbReturnClaimsExportResult
from wb_unit_economics.wb_stocks import WbStockExportResult
from wb_unit_economics.web import integrations, repository, source_refresh
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import (
    MarketplaceOperationFact,
    OrganizationTaxProfile,
    OrganizationTaxProfileOverride,
    ReportArtifact,
    ReportLogisticsAnalysisContext,
    ReportLogisticsOrderRow,
    ReportLogisticsSkuRow,
    ReportRun,
    SourceLoad,
    SourceRefreshCollection,
    SourceRefreshRun,
    SourceRefreshTask,
    SourceSnapshotRow,
    TenantIntegration,
    WbCabinet,
)
from wb_unit_economics.web.repository import import_dashboard_payload, upsert_user
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import (
    ONEC_DATABASE_ROW_PERSIST_MAX_BYTES,
    ONEC_REFRESH_COLLECTIONS,
    CollectorContext,
    SourceCredentials,
    SourceRefreshService,
    _collect_wb_stock_history,
    _is_ozon_report_control_result,
    _onec_financial_table_quality,
    _ozon_collection_status,
    _page_limit_exhausted,
    _persist_onec_rows,
    _read_ozon_rows,
    _safe_error,
    default_period_for_mode,
)


@pytest.fixture(autouse=True)
def _prevent_live_return_claims_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """Source-refresh tests must never call the external claims endpoint."""

    def fake_export(
        _client,
        _output_dir,
        *,
        as_of,
        seller_account_id="",
        account_name="",
        file_prefix="",
    ):
        del file_prefix
        return WbReturnClaimsExportResult(
            ok=False,
            source_state="access_denied",
            active_state="access_denied",
            archive_state="access_denied",
            seller_account_id=seller_account_id,
            account_name=account_name,
            coverage_start=as_of - timedelta(days=13),
            coverage_end=as_of,
            status_code=403,
            error="HTTPStatusError",
        )

    monkeypatch.setattr(source_refresh, "export_wb_return_claims", fake_export)


def test_default_source_refresh_periods_are_explicit_and_mode_specific() -> None:
    settings = WebSettings(
        _env_file=None,
        source_refresh_period_start="2026-03-01",
        source_refresh_period_end="2026-07-22",
        source_refresh_rolling_window_days=28,
    )

    assert default_period_for_mode(settings, "full") == (
        date(2026, 3, 1),
        date(2026, 7, 22),
    )
    assert default_period_for_mode(settings, "daily") == (
        date(2026, 6, 25),
        date(2026, 7, 22),
    )


def test_onec_commissioner_headers_without_financial_tables_are_partial(
    tmp_path: Path,
) -> None:
    output_path = tmp_path / "commissioner_reports.raw.json"
    output_path.write_text(
        json.dumps({"value": [{"Ref_Key": "report-1", "Number": "1"}]}),
        encoding="utf-8",
    )
    quality = _onec_financial_table_quality(
        OnecSampleExportResult(
            sample_id="commissioner_reports",
            collection_name="Document_ОтчетКомиссионера",
            ok=True,
            row_count=1,
            output_path=output_path,
            detail_mode="financial_tables",
        )
    )

    assert quality == {
        "status": "partial_source",
        "code": "commissioner_financial_tables_missing",
        "headerRows": 1,
        "rowsWithTables": 0,
        "financialLineCount": 0,
    }


def test_onec_commissioner_financial_tables_are_loaded(tmp_path: Path) -> None:
    output_path = tmp_path / "commissioner_reports.raw.json"
    output_path.write_text(
        json.dumps(
            {
                "value": [
                    {
                        "Ref_Key": "report-1",
                        "Организация_Key": "organization-1",
                        "Запасы": [{"Номенклатура_Key": "item-1", "Всего": 100}],
                        "ЗапасыВозвраты": [],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    quality = _onec_financial_table_quality(
        OnecSampleExportResult(
            sample_id="commissioner_reports",
            collection_name="Document_ОтчетКомиссионера",
            ok=True,
            row_count=1,
            output_path=output_path,
            detail_mode="financial_tables",
        )
    )

    assert quality["status"] == "loaded"
    assert quality["financialLineCount"] == 1


def test_onec_commissioner_without_organization_is_partial(tmp_path: Path) -> None:
    output_path = tmp_path / "commissioner_reports.raw.json"
    output_path.write_text(
        json.dumps(
            {
                "value": [
                    {
                        "Ref_Key": "report-1",
                        "Запасы": [{"Номенклатура_Key": "item-1", "Всего": 100}],
                        "ЗапасыВозвраты": [],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    quality = _onec_financial_table_quality(
        OnecSampleExportResult(
            sample_id="commissioner_reports",
            collection_name="Document_ОтчетКомиссионера",
            ok=True,
            row_count=1,
            output_path=output_path,
            detail_mode="financial_tables",
        )
    )

    assert quality["status"] == "partial_source"
    assert quality["code"] == "commissioner_organization_missing"


def test_incomplete_commissioner_tables_cannot_create_ozon_draft(
    tmp_path: Path,
) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="ozon-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="incomplete-commissioner",
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            user=user,
            source_report=report,
        )
        repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="onec_commissioner_reports",
            source_label="Document_ОтчетКомиссионера",
            required=False,
            publication_required=True,
            status="partial_source",
            row_count=3,
            payload={
                "dataQuality": {
                    "status": "partial_source",
                    "code": "commissioner_financial_tables_missing",
                }
            },
        )
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="needs_review",
            finished_at=datetime.now(),
        )

        with pytest.raises(ValueError, match="complete 1C commissioner"):
            repository.materialize_ozon_draft_report(db, refresh_run, user=user)

        assert refresh_run.new_report_run_id is None


def test_redeem_notifications_collection_persists_primary_amount(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    output_dir = settings.source_refresh_root_path / "full-redeem-notifications-test"
    output_dir = output_dir / "wb_redeem_notifications"
    account_dir = output_dir / "WB_ACCOUNT_1"
    account_dir.mkdir(parents=True)
    manifest_path = account_dir / "documents_manifest.json"
    manifest_path.write_text(
        json.dumps(
            [
                {
                    "serviceName": "redeem-notification-685214500",
                    "name": "Уведомление о выкупе №685214500",
                    "category": "Уведомление о выкупе",
                    "creationTime": "2026-04-13T15:52:40Z",
                    "download": {
                        "sha256": "document-hash",
                        "summary": {
                            "reportId": "685214500",
                            "status": "parsed",
                            "quantity": "62",
                            "purchaseAmount": "51532.81",
                            "vatAmount": "9292.80",
                        },
                    },
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (output_dir / "manifest.json").write_text(
        json.dumps({"results": []}), encoding="utf-8"
    )

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="full-redeem-notifications-test",
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            user=user,
            source_report=report,
            reason="test",
        )
        service = SourceRefreshService(settings)
        collection = service._record_wb_redeem_notifications(
            db,
            refresh_run,
            output_dir,
            [
                WbDocumentExportResult(
                    seller_account_id="WB_ACCOUNT_1",
                    account_name="Кабинет 1",
                    ok=True,
                    status="ok",
                    row_count=1,
                    downloaded_count=1,
                    output_file="WB_ACCOUNT_1/documents_manifest.json",
                    status_code=200,
                )
            ],
            wb_cabinet_ids={"WB_ACCOUNT_1": "cabinet-1"},
        )
        source_row = (
            db.query(SourceSnapshotRow).filter_by(collection_id=collection.id).one()
        )

    assert collection.status == "loaded"
    assert collection.row_count == 1
    assert collection.payload["parsedDocuments"] == 1
    assert collection.payload["rawIntegrity"]["status"] == "verified"
    assert source_row.source_row_id == "685214500"
    assert source_row.wb_cabinet_id == "cabinet-1"
    assert source_row.row_payload["purchaseAmount"] == "51532.81"
    assert source_row.row_payload["quantity"] == "62"


def test_stock_history_collection_records_two_cabinets_and_missing_scope(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    output_dir = tmp_path / "stock_history"
    output_dir.mkdir()
    zip_path = output_dir / "account-1.zip"
    period_start = date(2026, 3, 1)
    period_end = date(2026, 3, 3)
    with ZipFile(zip_path, "w") as archive:
        archive.writestr(
            "stock.csv",
            ("NmID,VendorCode,01.03.2026,02.03.2026,03.03.2026\n101,A-1,3,0,2\n"),
        )

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="full-stock-history-test",
            period_start=period_start,
            period_end=period_end,
            user=user,
            source_report=report,
            reason="test",
        )
        service = SourceRefreshService(settings)
        collection = service._record_wb_stock_history(
            db,
            refresh_run,
            output_dir,
            [
                WbStockExportResult(
                    seller_account_id="WB_ACCOUNT_1",
                    account_name="Кабинет 1",
                    source="wb_stock_history_daily_csv",
                    ok=True,
                    status="ok",
                    row_count=0,
                    output_path=zip_path,
                ),
                WbStockExportResult(
                    seller_account_id="WB_ACCOUNT_2",
                    account_name="Кабинет 2",
                    source="wb_stock_history_daily_csv",
                    ok=False,
                    status="access_error",
                    row_count=0,
                    status_code=403,
                    error="HTTP 403",
                ),
            ],
            wb_cabinet_ids={
                "WB_ACCOUNT_1": "cabinet-1",
                "WB_ACCOUNT_2": "cabinet-2",
            },
            period_start=period_start,
            period_end=period_end,
        )

    assert collection.status == "needs_review"
    assert collection.payload["periodStart"] == "2026-03-01"
    assert collection.payload["periodEnd"] == "2026-03-03"
    assert collection.payload["stockType"] == "wb"
    assert collection.payload["accounts"][0]["calculated"] is True
    assert collection.payload["accounts"][0]["coveredDays"] == 3
    assert collection.payload["accounts"][1]["status"] == "missing_scope"
    assert collection.payload["accounts"][1]["calculated"] is False


def test_stock_history_collector_keeps_report_period_and_provider_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    seen: dict[str, date] = {}
    monkeypatch.setattr(
        source_refresh,
        "_moscow_today",
        lambda: date(2026, 7, 11),
    )

    def fake_exporter(_settings, output_dir: Path, **kwargs):
        seen["period_start"] = kwargs["period_start"]
        seen["period_end"] = kwargs["period_end"]
        output_dir.mkdir(parents=True, exist_ok=True)
        zip_path = output_dir / "account-1.zip"
        dates = []
        current = kwargs["period_start"]
        while current <= kwargs["period_end"]:
            dates.append(current)
            current += timedelta(days=1)
        with ZipFile(zip_path, "w") as archive:
            archive.writestr(
                "stock.csv",
                "NmID,VendorCode,"
                + ",".join(item.strftime("%d.%m.%Y") for item in dates)
                + "\n101,A-1,"
                + ",".join("1" for _item in dates)
                + "\n",
            )
        return [
            WbStockExportResult(
                seller_account_id="WB_ACCOUNT_1",
                account_name="Кабинет 1",
                source="wb_stock_history_daily_csv",
                ok=True,
                status="ok",
                row_count=0,
                output_path=zip_path,
            )
        ]

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="full-stock-provider-window-test",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 7, 10),
            user=user,
            source_report=report,
            reason="test",
        )
        service = SourceRefreshService(
            settings,
            wb_stock_history_exporter=fake_exporter,
        )
        result = _collect_wb_stock_history(
            service,
            CollectorContext(
                db=db,
                refresh_run=refresh_run,
                credentials=SourceCredentials(
                    wb_settings=WbFinanceSettings(
                        accounts=(
                            WbFinanceSellerAccount(
                                seller_account_id="WB_ACCOUNT_1",
                                account_name="Кабинет 1",
                                api_key="test-key",
                            ),
                        )
                    ),
                    onec_settings=None,
                    ozon_settings=None,
                    wb_cabinet_ids={"WB_ACCOUNT_1": "cabinet-1"},
                    ozon_cabinet_ids={},
                    issues=(),
                ),
                root_dir=tmp_path / "snapshot",
                period_start=date(2026, 3, 1),
                period_end=date(2026, 7, 10),
                mode="full",
            ),
        )

    assert seen == {
        "period_start": date(2026, 4, 11),
        "period_end": date(2026, 7, 10),
    }
    assert result.collection is not None
    assert result.collection.payload["periodStart"] == "2026-03-01"
    assert result.collection.payload["actualPeriodStart"] == "2026-04-11"
    assert result.collection.payload["accounts"][0]["coveredDays"] == 91
    assert result.collection.payload["accounts"][0]["totalDays"] == 132
    assert result.collection.payload["accounts"][0]["status"] == (
        "partial_provider_window"
    )
    assert result.collection.status == "loaded"
    assert result.collection.payload["calculated"] is True
    assert result.collection.payload["providerWindowCalculated"] is True
    assert result.collection.payload["fullCoverage"] is False
    assert result.collection.payload["accounts"][0]["calculated"] is True
    assert result.collection.payload["accounts"][0]["providerWindowCalculated"] is True
    assert result.collection.payload["accounts"][0]["fullCoverage"] is False
    assert result.collection.payload["calculationPeriodStart"] == "2026-04-11"
    assert result.collection.payload["calculationPeriodEnd"] == "2026-07-10"
    assert (
        result.collection.payload["calculationContextVersion"] == "lost-sales-filter-v1"
    )
    assert result.collection.payload["extrapolated"] is False


def test_stock_history_collector_marks_three_month_period_complete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    seen: dict[str, date] = {}
    monkeypatch.setattr(
        source_refresh,
        "_moscow_today",
        lambda: date(2026, 7, 10),
    )

    def fake_exporter(_settings, output_dir: Path, **kwargs):
        seen["period_start"] = kwargs["period_start"]
        seen["period_end"] = kwargs["period_end"]
        output_dir.mkdir(parents=True, exist_ok=True)
        zip_path = output_dir / "account-1.zip"
        dates = []
        current = kwargs["period_start"]
        while current <= kwargs["period_end"]:
            dates.append(current)
            current += timedelta(days=1)
        with ZipFile(zip_path, "w") as archive:
            archive.writestr(
                "stock.csv",
                "NmID,VendorCode,"
                + ",".join(item.strftime("%d.%m.%Y") for item in dates)
                + "\n101,A-1,"
                + ",".join("1" for _item in dates)
                + "\n",
            )
        return [
            WbStockExportResult(
                seller_account_id="WB_ACCOUNT_1",
                account_name="Кабинет 1",
                source="wb_stock_history_daily_csv",
                ok=True,
                status="ok",
                row_count=0,
                output_path=zip_path,
            )
        ]

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="short-stock-provider-window-test",
            period_start=date(2026, 4, 10),
            period_end=date(2026, 7, 10),
            user=user,
            source_report=report,
            reason="test",
        )
        service = SourceRefreshService(
            settings,
            wb_stock_history_exporter=fake_exporter,
        )
        result = _collect_wb_stock_history(
            service,
            CollectorContext(
                db=db,
                refresh_run=refresh_run,
                credentials=SourceCredentials(
                    wb_settings=WbFinanceSettings(
                        accounts=(
                            WbFinanceSellerAccount(
                                seller_account_id="WB_ACCOUNT_1",
                                account_name="Кабинет 1",
                                api_key="test-key",
                            ),
                        )
                    ),
                    onec_settings=None,
                    ozon_settings=None,
                    wb_cabinet_ids={"WB_ACCOUNT_1": "cabinet-1"},
                    ozon_cabinet_ids={},
                    issues=(),
                ),
                root_dir=tmp_path / "short-snapshot",
                period_start=date(2026, 4, 10),
                period_end=date(2026, 7, 10),
                mode="full",
            ),
        )

    assert seen == {
        "period_start": date(2026, 4, 10),
        "period_end": date(2026, 7, 10),
    }
    assert result.collection is not None
    assert result.collection.status == "loaded"
    assert result.collection.payload["accounts"][0]["coveredDays"] == 92
    assert result.collection.payload["accounts"][0]["totalDays"] == 92
    assert result.collection.payload["accounts"][0]["calculated"] is True
    assert result.collection.payload["accounts"][0]["fullCoverage"] is True
    assert result.collection.payload["fullCoverage"] is True


def test_stock_history_collector_skips_period_outside_current_provider_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    monkeypatch.setattr(
        source_refresh,
        "_moscow_today",
        lambda: date(2026, 7, 11),
    )

    def unexpected_exporter(*_args, **_kwargs):
        raise AssertionError("WB exporter must not receive an out-of-window period")

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="old-stock-provider-window-test",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 3, 31),
            user=user,
            source_report=report,
            reason="test",
        )
        service = SourceRefreshService(
            settings,
            wb_stock_history_exporter=unexpected_exporter,
        )
        result = _collect_wb_stock_history(
            service,
            CollectorContext(
                db=db,
                refresh_run=refresh_run,
                credentials=SourceCredentials(
                    wb_settings=WbFinanceSettings(
                        accounts=(
                            WbFinanceSellerAccount(
                                seller_account_id="WB_ACCOUNT_1",
                                account_name="Кабинет 1",
                                api_key="test-key",
                            ),
                        )
                    ),
                    onec_settings=None,
                    ozon_settings=None,
                    wb_cabinet_ids={"WB_ACCOUNT_1": "cabinet-1"},
                    ozon_cabinet_ids={},
                    issues=(),
                ),
                root_dir=tmp_path / "old-snapshot",
                period_start=date(2026, 3, 1),
                period_end=date(2026, 3, 31),
                mode="full",
            ),
        )

    assert result.collection is not None
    assert result.collection.status == "needs_review"
    assert result.collection.payload["actualPeriodStart"] is None
    assert result.collection.payload["actualPeriodEnd"] is None
    assert result.collection.payload["accounts"][0]["status"] == (
        "outside_provider_window"
    )
    assert result.collection.payload["accounts"][0]["coveredDays"] == 0
    assert result.collection.payload["accounts"][0]["calculated"] is False


def minimal_payload() -> dict:
    return {
        "meta": {
            "title": "Кабинет юнит-экономики WB",
            "client": "Шумейко и Партнеры",
            "period": "01.03.2026 - 17.06.2026",
            "periodText": "март-июнь 2026",
            "periodStatus": "",
            "methodologyVersion": "Excel MVP / test",
            "generatedAt": "20.06.2026 12:00",
            "sourceWorkbook": "source-refresh.xlsx",
            "returnReasonLimitation": "",
        },
        "options": {},
        "monthly": [],
        "expenses": [],
        "unitRows": [
            {
                "id": "unit-1",
                "week": "2026-04-06",
                "month": "Апрель 2026",
                "documentReport": "Отчет комиссионера · 06.04.2026-12.04.2026",
                "organization": "Организация A",
                "cabinet": "Кабинет A",
                "product": "Товар",
                "nmId": "1001",
                "articleWb": "WB-1",
                "article1c": "A-1",
                "barcode": "BAR-1",
                "scheme": "FBO",
                "sales": 1,
                "returns": 0,
                "netQty": 1,
                "returnRate": 0,
                "revenueBeforeSpp": 1000,
                "spp": 0,
                "revenue": 1000,
                "vat": 48,
                "revenueWithoutVat": 952,
                "cost": 300,
                "commission": 100,
                "logistics": 50,
                "storage": 0,
                "acceptance": 0,
                "promotion": 0,
                "penalties": 0,
                "acquiring": 10,
                "usn": 10,
                "profitBeforeTax": 540,
                "profit": 482,
                "margin": 0.482,
                "unitProfit": 482,
                "status": "ОК",
                "statusReason": "Данные достаточны для расчета",
                "sppStatus": "ОК",
                "lossClass": "Без критичных проблем",
                "lossDriver": "Без критичных проблем",
            }
        ],
        "returns": [],
        "lostSales": [],
        "reconciliation": [],
        "reconciliationMonthly": [],
        "documentReconciliation": [],
    }


def test_logistics_analysis_is_built_from_persisted_read_only_snapshot(
    tmp_path: Path,
) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        unit_row = (
            db.query(repository.ReportUnitRow).filter_by(report_run_id=report.id).one()
        )
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="logistics-gate-test",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            source_report=report,
            reason="logistics gate test",
        )
        collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="wb_finance_detail",
            source_label="WB finance",
            required=True,
            status="loaded",
            row_count=1,
        )
        logistics_payload = {
            "rrDate": "2026-04-06",
            "orderDt": "2026-04-05",
            "orderUid": "order-1",
            "nmId": "1001",
            "sku": "BAR-1",
            "vendorCode": "WB-1",
            "title": "Товар",
            "deliveryMethod": "FBO",
            "docTypeName": "Логистика",
            "sellerOperName": "Логистика",
            "deliveryService": "50",
            "deliveryAmount": "1",
            "returnAmount": "0",
        }
        repository.add_source_snapshot_row(
            db,
            collection,
            row_number=1,
            raw_payload_hash=source_refresh._hash_payload(logistics_payload),
            source_row_id="rrd-1",
            wb_cabinet_id=unit_row.wb_cabinet_id,
            row_payload=logistics_payload,
        )

        source_refresh._build_and_persist_logistics_analysis(
            db,
            report,
            refresh_runs=[refresh_run],
        )
        db.commit()

        context = db.get(ReportLogisticsAnalysisContext, report.id)
        order_rows = db.query(ReportLogisticsOrderRow).all()
        sku_rows = db.query(ReportLogisticsSkuRow).all()

    assert context is not None
    assert context.data_status == "ready"
    assert context.key_coverage_pct == Decimal("100")
    assert context.order_delta == 0
    assert context.sku_delta == 0
    assert len(order_rows) == 1
    assert len(sku_rows) == 1
    assert sku_rows[0].logistics_total == Decimal("50")


def test_return_reason_context_builds_from_lineage_and_denied_claims_is_partial(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    service = SourceRefreshService(settings)
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        report.publication_status = "draft"
        report.is_current = False
        unit_row = db.query(repository.ReportUnitRow).one()
        cabinet_id = unit_row.wb_cabinet_id
        finance_run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="return-reason-finance",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            source_report=report,
            reason="return reason finance test",
            enforce_active_check=False,
        )
        finance_collection = repository.add_source_refresh_collection(
            db,
            finance_run,
            source_type="wb_finance_detail",
            source_label="WB finance",
            required=True,
            status="loaded",
            row_count=1,
        )
        finance_payload = {
            "rrdId": "return-finance-1",
            "rrDate": "2026-04-06",
            "orderDt": "2026-04-05",
            "orderUid": "return-order-internal",
            "srid": "return-srid-1",
            "nmId": "1001",
            "sku": "BAR-1",
            "vendorCode": "WB-1",
            "title": "Товар",
            "deliveryMethod": "FBO",
            "docTypeName": "Возврат",
            "sellerOperName": "Возврат",
            "quantity": "-1",
            "retailAmount": "-1000",
            "deliveryService": "50",
            "deliveryAmount": "0",
            "returnAmount": "0",
        }
        repository.add_source_snapshot_row(
            db,
            finance_collection,
            row_number=1,
            raw_payload_hash=source_refresh._hash_payload(finance_payload),
            source_row_id="return-finance-1",
            wb_cabinet_id=cabinet_id,
            row_payload=finance_payload,
        )
        goods_run, _, _ = _add_goods_return_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="return-reason-goods",
            cabinet_id=cabinet_id,
            rows=[_goods_return_source_row(srid="return-srid-1")],
            file_authoritative=False,
        )
        claims_run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="return-reason-claims-denied",
            period_start=report.period_start,
            period_end=report.period_end,
            reason="return reason claims denied test",
            enforce_active_check=False,
        )
        claims_root = settings.source_refresh_root_path / claims_run.snapshot_set_id
        claims_dir = claims_root / "wb_return_claims"
        claims_dir.mkdir(parents=True)
        claims_run.root_dir = str(claims_root)
        denied = WbReturnClaimsExportResult(
            ok=False,
            source_state="access_denied",
            active_state="access_denied",
            archive_state="access_denied",
            seller_account_id="WB_ACCOUNT_SAFE",
            account_name="Кабинет",
            coverage_start=report.period_end - timedelta(days=13),
            coverage_end=report.period_end,
            status_code=403,
            error="HTTPStatusError",
        )
        (claims_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "coverageStart": denied.coverage_start.isoformat(),
                    "coverageEnd": denied.coverage_end.isoformat(),
                    "results": [
                        source_refresh._wb_return_claims_result_payload(denied)
                    ],
                }
            ),
            encoding="utf-8",
        )
        service._record_wb_return_claims(
            db,
            claims_run,
            claims_dir,
            [denied],
            wb_cabinet_ids={"WB_ACCOUNT_SAFE": cabinet_id},
        )

        logistics_result = source_refresh._build_and_persist_logistics_analysis(
            db,
            report,
            primary_refresh_run=finance_run,
        )
        source_refresh._build_and_persist_logistics_return_reasons(
            db,
            report,
            logistics_result=logistics_result,
            primary_refresh_run=finance_run,
            contributing_runs=[goods_run, claims_run],
        )
        db.flush()
        context = db.get(
            repository.ReportLogisticsReturnReasonContext,
            report.id,
        )
        rows = db.query(repository.ReportLogisticsReturnReasonRow).all()

    assert context is not None
    assert report.logistics_return_reasons_required is True
    assert context.data_status == "partial", context.blocking_reasons
    assert context.claims_source_status == "access_denied"
    assert context.blocking_reasons == []
    assert context.return_reason_row_count == 1
    assert len(rows) == 1
    assert rows[0].reason_category == "Не подошёл размер"
    assert rows[0].evidence_type == "fact"
    assert rows[0].claim_available is None
    assert rows[0].has_user_comment is None


@pytest.mark.parametrize(
    ("tamper_after_verify", "add_database_row", "expected_blocker"),
    [
        (False, False, None),
        (True, False, "file_authoritative_snapshot_invalid"),
        (False, True, "source_storage_ambiguity"),
    ],
)
def test_logistics_analysis_reads_verified_file_authoritative_snapshot(
    tmp_path: Path,
    tamper_after_verify: bool,
    add_database_row: bool,
    expected_blocker: str | None,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        unit_row = (
            db.query(repository.ReportUnitRow).filter_by(report_run_id=report.id).one()
        )
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="file-authoritative-logistics-gate",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            source_report=report,
            reason="file-authoritative logistics gate test",
        )
        run_root = settings.source_refresh_root_path / refresh_run.id
        raw_dir = run_root / "wb_finance_detail"
        raw_dir.mkdir(parents=True)
        refresh_run.root_dir = str(run_root)
        logistics_payload = {
            "rrdId": "rrd-file-1",
            "rrDate": "2026-04-06",
            "orderDt": "2026-04-05",
            "orderUid": "order-1",
            "nmId": "1001",
            "sku": "BAR-1",
            "vendorCode": "WB-1",
            "title": "Товар",
            "deliveryMethod": "FBO",
            "docTypeName": "Логистика",
            "sellerOperName": "Логистика",
            "deliveryService": "50",
            "deliveryAmount": "1",
            "returnAmount": "0",
        }
        page_payload = [logistics_payload]
        output_path = raw_dir / "page-1.json"
        output_path.write_text(
            json.dumps(page_payload, ensure_ascii=False),
            encoding="utf-8",
        )
        result_item = {
            "sellerAccountId": "WB_ACCOUNT_1",
            "accountName": "Кабинет 1",
            "wbCabinetId": unit_row.wb_cabinet_id,
            "pageIndex": 1,
            "status": "loaded",
            "sourceStatus": "ok",
            "ok": True,
            "rowCount": 1,
            "rrdIdStart": 0,
            "rrdIdNext": None,
            "statusCode": 200,
            "rawPayloadHash": source_refresh._hash_payload(page_payload),
            "outputFile": output_path.name,
            "error": "",
        }
        (raw_dir / "manifest.json").write_text(
            json.dumps({"results": [result_item]}, ensure_ascii=False),
            encoding="utf-8",
        )
        collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="wb_finance_detail",
            source_label="WB finance",
            required=True,
            status="loaded",
            snapshot_hash=source_refresh._hash_payload([result_item]),
            row_count=1,
            raw_path=str(raw_dir),
            payload={
                "results": [result_item],
                "rowPersistence": {
                    "status": "skipped_large_snapshot",
                    "limit": 0,
                    "rawFilesAuthoritative": True,
                },
            },
        )
        source_refresh._attach_collection_raw_integrity(
            collection,
            source_root=settings.source_refresh_root_path,
        )
        assert collection.payload["rawIntegrity"]["status"] == "verified"
        assert (
            db.query(SourceSnapshotRow).filter_by(collection_id=collection.id).count()
            == 0
        )
        if tamper_after_verify:
            output_path.write_text(
                json.dumps([{**logistics_payload, "deliveryService": "51"}]),
                encoding="utf-8",
            )
        if add_database_row:
            repository.add_source_snapshot_row(
                db,
                collection,
                row_number=1,
                raw_payload_hash=source_refresh._hash_payload(logistics_payload),
                source_row_id="rrd-file-1",
                wb_cabinet_id=unit_row.wb_cabinet_id,
                row_payload=logistics_payload,
            )

        source_refresh._build_and_persist_logistics_analysis(
            db,
            report,
            primary_refresh_run=refresh_run,
        )
        db.commit()

        context = db.get(ReportLogisticsAnalysisContext, report.id)
        order_rows = db.query(ReportLogisticsOrderRow).all()
        sku_rows = db.query(ReportLogisticsSkuRow).all()

    assert context is not None
    if expected_blocker is not None:
        assert context.data_status == "blocked"
        assert expected_blocker in context.blocking_reasons
        assert order_rows == []
        assert sku_rows == []
        return
    assert context.data_status == "ready"
    assert context.key_coverage_pct == Decimal("100")
    assert context.order_delta == 0
    assert context.sku_delta == 0
    assert len(order_rows) == 1
    assert len(sku_rows) == 1
    assert sku_rows[0].logistics_total == Decimal("50")


def test_dimension_snapshot_db_and_file_authoritative_are_equivalent(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        cards = [_dimension_card("1001")]
        db_run, _db_collection = _add_dimension_database_snapshot(
            db,
            report,
            snapshot_set_id="dimensions-db",
            cabinet_id=cabinet_id,
            cards=cards,
        )
        file_run, _file_collection, _flat_path = _add_dimension_file_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="dimensions-file",
            cabinet_id=cabinet_id,
            cards=cards,
        )

        db_selection = source_refresh._select_dimension_snapshot(
            db, report, roles=[(0, db_run)]
        )
        file_selection = source_refresh._select_dimension_snapshot(
            db, report, roles=[(0, file_run)]
        )

    assert db_selection.blocking_reasons == ()
    assert file_selection.blocking_reasons == ()
    assert db_selection.card_rows == file_selection.card_rows
    assert db_selection.source_row_count == file_selection.source_row_count == 1


def test_goods_return_snapshot_db_and_file_authoritative_are_equivalent(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        rows = [_goods_return_source_row()]
        db_run, _, _ = _add_goods_return_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="goods-return-db",
            cabinet_id=cabinet_id,
            rows=rows,
            file_authoritative=False,
        )
        file_run, _, _ = _add_goods_return_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="goods-return-file",
            cabinet_id=cabinet_id,
            rows=rows,
            file_authoritative=True,
        )

        db_selection = source_refresh._select_goods_return_snapshot(
            db, report, roles=[(0, db_run)]
        )
        file_selection = source_refresh._select_goods_return_snapshot(
            db, report, roles=[(0, file_run)]
        )

    assert db_selection.blocking_reasons == ()
    assert file_selection.blocking_reasons == ()
    assert db_selection.source_rows == file_selection.source_rows
    assert db_selection.source_row_count == file_selection.source_row_count == 1


def test_goods_return_record_registers_verified_collection_and_rows(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    service = SourceRefreshService(settings)
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="goods-return-record",
            period_start=report.period_start,
            period_end=report.period_end,
            reason="goods-return record test",
            enforce_active_check=False,
        )
        run_root = settings.source_refresh_root_path / "goods-return-record"
        output_dir = run_root / "wb_goods_return"
        output_dir.mkdir(parents=True)
        run.root_dir = str(run_root)
        raw_payload = {"report": []}
        flat_rows = [_goods_return_source_row()]
        raw_path = output_dir / "goods-return.raw.json"
        flat_path = output_dir / "goods-return.flat.json"
        raw_path.write_text(json.dumps(raw_payload), encoding="utf-8")
        flat_path.write_text(json.dumps(flat_rows), encoding="utf-8")
        result = WbGoodsReturnExportResult(
            ok=True,
            seller_account_id="WB_ACCOUNT_SAFE",
            account_name="Кабинет",
            row_count=1,
            raw_output_path=raw_path,
            flat_output_path=flat_path,
            raw_payload_hash=source_refresh._hash_payload(raw_payload),
            flat_payload_hash=source_refresh._hash_payload(flat_rows),
            coverage_start=report.period_start,
            coverage_end=report.period_end,
            status_code=200,
        )
        (output_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "coverageStart": report.period_start.isoformat(),
                    "coverageEnd": report.period_end.isoformat(),
                    "results": [source_refresh._wb_goods_return_result_payload(result)],
                }
            ),
            encoding="utf-8",
        )

        collection = service._record_wb_goods_return(
            db,
            run,
            output_dir,
            [result],
            wb_cabinet_ids={"WB_ACCOUNT_SAFE": cabinet_id},
            period_start=report.period_start,
            period_end=report.period_end,
        )
        db.flush()

        snapshots = (
            db.query(SourceSnapshotRow).filter_by(collection_id=collection.id).all()
        )

    assert collection.status == "loaded"
    assert collection.row_count == 1
    assert collection.payload["rawIntegrity"]["status"] == "verified"
    assert collection.payload["coverageStart"] == report.period_start.isoformat()
    assert len(snapshots) == 1
    assert snapshots[0].wb_cabinet_id == cabinet_id


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ("snapshot_hash", "goods_return_source_snapshot_hash_mismatch"),
        ("tenant_scope", "goods_return_source_scope_mismatch"),
        ("storage_ambiguity", "goods_return_source_storage_ambiguity"),
        ("file_tamper", "goods_return_file_snapshot_invalid"),
    ],
)
def test_goods_return_snapshot_integrity_failures_are_blocking(
    tmp_path: Path,
    failure: str,
    expected_code: str,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        file_authoritative = failure in {"storage_ambiguity", "file_tamper"}
        run, collection, flat_path = _add_goods_return_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id=f"goods-return-{failure}",
            cabinet_id=cabinet_id,
            rows=[_goods_return_source_row()],
            file_authoritative=file_authoritative,
        )
        if failure == "snapshot_hash":
            collection.snapshot_hash = "changed"
        elif failure == "tenant_scope":
            collection.tenant_id = "other"
        elif failure == "storage_ambiguity":
            row_payload = _goods_return_source_row()
            repository.add_source_snapshot_row(
                db,
                collection,
                row_number=1,
                raw_payload_hash=source_refresh._hash_payload(row_payload),
                source_row_id="safe-hash",
                wb_cabinet_id=cabinet_id,
                row_payload=row_payload,
            )
        elif failure == "file_tamper":
            flat_path.write_text(
                json.dumps([{**_goods_return_source_row(), "reason": "changed"}]),
                encoding="utf-8",
            )

        selection = source_refresh._select_goods_return_snapshot(
            db, report, roles=[(0, run)]
        )

    assert selection.source_rows == ()
    assert expected_code in selection.blocking_reasons


def test_return_claims_record_and_selector_keep_only_safe_flat_fields(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    service = SourceRefreshService(settings)
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="return-claims-record",
            period_start=report.period_start,
            period_end=report.period_end,
            reason="return claims record test",
            enforce_active_check=False,
        )
        run_root = settings.source_refresh_root_path / "return-claims-record"
        output_dir = run_root / "wb_return_claims"
        output_dir.mkdir(parents=True)
        run.root_dir = str(run_root)
        raw_payload = {
            "active": {
                "claims": [
                    {
                        "id": "synthetic-claim-id",
                        "srid": "synthetic-srid",
                        "nm_id": 1001,
                        "user_comment": "synthetic comment",
                        "photos": ["synthetic-photo"],
                    }
                ],
                "total": 1,
            },
            "archive": {"claims": [], "total": 0},
        }
        flat_rows = [
            {
                "srid": "synthetic-srid",
                "nm_id": 1001,
                "is_archive": False,
                "has_user_comment": True,
            }
        ]
        raw_path = output_dir / "return-claims.raw.json"
        flat_path = output_dir / "return-claims.flat.json"
        raw_path.write_text(json.dumps(raw_payload), encoding="utf-8")
        flat_path.write_text(json.dumps(flat_rows), encoding="utf-8")
        result = WbReturnClaimsExportResult(
            ok=True,
            source_state="confirmed_nonempty",
            active_state="confirmed_nonempty",
            archive_state="confirmed_empty",
            seller_account_id="WB_ACCOUNT_SAFE",
            account_name="Кабинет",
            row_count=1,
            raw_output_path=raw_path,
            flat_output_path=flat_path,
            raw_payload_hash=source_refresh._hash_payload(raw_payload),
            flat_payload_hash=source_refresh._hash_payload(flat_rows),
            coverage_start=report.period_end - timedelta(days=13),
            coverage_end=report.period_end,
            status_code=200,
        )
        (output_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "coverageStart": result.coverage_start.isoformat(),
                    "coverageEnd": result.coverage_end.isoformat(),
                    "results": [
                        source_refresh._wb_return_claims_result_payload(result)
                    ],
                }
            ),
            encoding="utf-8",
        )

        collection = service._record_wb_return_claims(
            db,
            run,
            output_dir,
            [result],
            wb_cabinet_ids={"WB_ACCOUNT_SAFE": cabinet_id},
        )
        db.flush()
        selection = source_refresh._select_return_claims_snapshot(
            db, report, roles=[(0, run)]
        )
        snapshot = (
            db.query(SourceSnapshotRow).filter_by(collection_id=collection.id).one()
        )
        public_collection = repository.source_refresh_collection_payload(
            collection,
            include_sensitive=False,
        )

    assert collection.status == "loaded"
    assert selection.blocking_reasons == ()
    assert selection.source_state == "confirmed_nonempty"
    assert selection.cabinet_states == ((cabinet_id, "confirmed_nonempty"),)
    assert selection.source_rows[0].identity_key is not None
    assert selection.source_rows[0].has_user_comment is True
    assert public_collection["sourceState"] == "confirmed_nonempty"
    assert public_collection["sourceMessage"] == ("Заявки за доступное окно получены")
    assert public_collection["payload"] == {}
    assert "user_comment" not in snapshot.row_payload
    assert "photos" not in snapshot.row_payload
    serialized = json.dumps(snapshot.row_payload)
    for forbidden in (
        "synthetic-claim-id",
        "synthetic comment",
        "synthetic-photo",
    ):
        assert forbidden not in serialized


def test_return_claims_access_denied_is_review_state_not_blocker(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    service = SourceRefreshService(settings)
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="return-claims-denied",
            period_start=report.period_start,
            period_end=report.period_end,
            reason="return claims denied test",
            enforce_active_check=False,
        )
        run_root = settings.source_refresh_root_path / "return-claims-denied"
        output_dir = run_root / "wb_return_claims"
        output_dir.mkdir(parents=True)
        run.root_dir = str(run_root)
        result = WbReturnClaimsExportResult(
            ok=False,
            source_state="access_denied",
            active_state="access_denied",
            archive_state="access_denied",
            seller_account_id="WB_ACCOUNT_SAFE",
            account_name="Кабинет",
            coverage_start=report.period_end - timedelta(days=13),
            coverage_end=report.period_end,
            status_code=403,
            error="HTTPStatusError",
        )
        (output_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "coverageStart": result.coverage_start.isoformat(),
                    "coverageEnd": result.coverage_end.isoformat(),
                    "results": [
                        source_refresh._wb_return_claims_result_payload(result)
                    ],
                }
            ),
            encoding="utf-8",
        )

        collection = service._record_wb_return_claims(
            db,
            run,
            output_dir,
            [result],
            wb_cabinet_ids={"WB_ACCOUNT_SAFE": cabinet_id},
        )
        db.flush()
        selection = source_refresh._select_return_claims_snapshot(
            db, report, roles=[(0, run)]
        )
        public_collection = repository.source_refresh_collection_payload(
            collection,
            include_sensitive=False,
        )

    assert collection.status == "needs_review"
    assert selection.source_rows == ()
    assert selection.source_state == "access_denied"
    assert selection.blocking_reasons == ()
    assert "return_claims_source_access_denied" in selection.review_reasons
    assert public_collection["sourceState"] == "access_denied"
    assert public_collection["sourceMessage"] == "Источник заявок недоступен"
    assert public_collection["payload"] == {}


def test_return_claims_empty_collection_has_reader_facing_marker() -> None:
    state, message = repository._safe_collection_source_state(
        SimpleNamespace(
            source_type="wb_return_claims",
            payload={"results": [{"status": "confirmed_empty"}]},
        )
    )

    assert state == "confirmed_empty"
    assert message == "Заявок за доступное окно нет"


def test_tariff_snapshot_db_and_file_authoritative_are_equivalent(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        rows = [_tariff_row()]
        db_run, _ = _add_tariff_database_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="tariffs-db",
            cabinet_id=cabinet_id,
            rows=rows,
        )
        file_run, _, _ = _add_tariff_file_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="tariffs-file",
            cabinet_id=cabinet_id,
            rows=rows,
        )

        db_selection = source_refresh._select_tariff_snapshot(
            db, report, roles=[(0, db_run)]
        )
        file_selection = source_refresh._select_tariff_snapshot(
            db, report, roles=[(0, file_run)]
        )

    assert db_selection.blocking_reasons == ()
    assert file_selection.blocking_reasons == ()
    assert db_selection.tariff_rows == file_selection.tariff_rows
    assert db_selection.factor_snapshot_date == date(2026, 7, 21)
    assert db_selection.source_row_count == file_selection.source_row_count == 1


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ("database_hash", "tariff_source_payload_hash_mismatch"),
        ("database_row_count", "tariff_database_row_count_mismatch"),
        ("snapshot_hash", "tariff_source_snapshot_hash_mismatch"),
        ("tenant_scope", "tariff_source_scope_mismatch"),
        ("unverified_manifest", "tariff_raw_snapshot_invalid"),
        ("storage_ambiguity", "tariff_source_storage_ambiguity"),
        ("file_tamper", "tariff_file_snapshot_invalid"),
        ("path_traversal", "tariff_file_snapshot_invalid"),
    ],
)
def test_tariff_snapshot_integrity_failures_are_blocking(
    tmp_path: Path,
    failure: str,
    expected_code: str,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        rows = [_tariff_row()]
        if failure in {"storage_ambiguity", "file_tamper", "path_traversal"}:
            run, collection, flat_path = _add_tariff_file_snapshot(
                db,
                report,
                settings=settings,
                snapshot_set_id=f"tariffs-{failure}",
                cabinet_id=cabinet_id,
                rows=rows,
            )
            if failure == "storage_ambiguity":
                row_payload = rows[0]
                repository.add_source_snapshot_row(
                    db,
                    collection,
                    row_number=1,
                    raw_payload_hash=source_refresh._hash_payload(row_payload),
                    source_row_id="tariff-1",
                    wb_cabinet_id=cabinet_id,
                    row_payload=row_payload,
                )
            elif failure == "file_tamper":
                flat_path.write_text(
                    json.dumps(
                        {
                            "box": [{**rows[0], "box_delivery_coef_expr": "999"}],
                            "pallet": [],
                        }
                    ),
                    encoding="utf-8",
                )
            else:
                results = list(collection.payload["results"])
                results[0] = {
                    **results[0],
                    "flatOutputFile": "../tariffs.flat.json",
                }
                collection.snapshot_hash = source_refresh._hash_payload(results)
                collection.payload = {**collection.payload, "results": results}
        else:
            run, collection = _add_tariff_database_snapshot(
                db,
                report,
                settings=settings,
                snapshot_set_id=f"tariffs-{failure}",
                cabinet_id=cabinet_id,
                rows=rows,
            )
            if failure == "database_hash":
                db.query(SourceSnapshotRow).filter_by(
                    collection_id=collection.id
                ).one().raw_payload_hash = "changed"
            elif failure == "database_row_count":
                results = [{**collection.payload["results"][0], "rowCount": 2}]
                collection.row_count = 2
                collection.snapshot_hash = source_refresh._hash_payload(results)
                collection.payload = {**collection.payload, "results": results}
            elif failure == "snapshot_hash":
                collection.snapshot_hash = "changed"
            elif failure == "tenant_scope":
                collection.tenant_id = "other"
            elif failure == "unverified_manifest":
                collection.payload = {
                    **collection.payload,
                    "rawIntegrity": {"status": "failed"},
                }

        selection = source_refresh._select_tariff_snapshot(db, report, roles=[(0, run)])

    assert selection.tariff_rows == ()
    assert expected_code in selection.blocking_reasons


def test_tariff_snapshot_uses_primary_before_base_and_blocks_peer_conflict(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        primary, _ = _add_tariff_database_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="tariffs-primary",
            cabinet_id=cabinet_id,
            rows=[_tariff_row()],
        )
        base, _ = _add_tariff_database_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="tariffs-base",
            cabinet_id=cabinet_id,
            rows=[{**_tariff_row(), "box_delivery_coef_expr": "999"}],
        )
        peer, _ = _add_tariff_database_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="tariffs-peer",
            cabinet_id=cabinet_id,
            rows=[{**_tariff_row(), "box_delivery_coef_expr": "135"}],
        )

        selected = source_refresh._select_tariff_snapshot(
            db, report, roles=[(0, primary), (1, base)]
        )
        conflicted = source_refresh._select_tariff_snapshot(
            db, report, roles=[(0, primary), (0, peer)]
        )

    assert selected.blocking_reasons == ()
    assert selected.tariff_rows[0]["box_delivery_coef_expr"] == "125"
    assert conflicted.tariff_rows == ()
    assert conflicted.blocking_reasons == ("tariff_source_revision_conflict",)


def test_tariff_snapshot_partial_collection_is_reviewable(tmp_path: Path) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        run, collection = _add_tariff_database_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="tariffs-partial",
            cabinet_id=cabinet_id,
            rows=[_tariff_row()],
        )
        collection.status = "partial_source"

        selection = source_refresh._select_tariff_snapshot(db, report, roles=[(0, run)])

    assert selection.blocking_reasons == ()
    assert selection.review_reasons == ("tariff_source_partial",)
    assert len(selection.tariff_rows) == 1


def test_route_snapshot_db_and_file_authoritative_are_equivalent(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        rows = [_route_source_row()]
        db_run, _, _ = _add_route_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="routes-db",
            cabinet_id=cabinet_id,
            rows=rows,
            file_authoritative=False,
        )
        file_run, _, _ = _add_route_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="routes-file",
            cabinet_id=cabinet_id,
            rows=rows,
            file_authoritative=True,
        )

        db_selection = source_refresh._select_route_snapshot(
            db, report, roles=[(0, db_run)]
        )
        file_selection = source_refresh._select_route_snapshot(
            db, report, roles=[(0, file_run)]
        )

    assert db_selection.blocking_reasons == ()
    assert file_selection.blocking_reasons == ()
    assert db_selection.route_rows == file_selection.route_rows
    assert db_selection.source_row_count == file_selection.source_row_count == 1
    assert db_selection.source_coverage_start == report.period_start
    assert db_selection.source_coverage_end == report.period_end


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ("database_hash", "route_source_payload_hash_mismatch"),
        ("database_row_count", "route_database_row_count_mismatch"),
        ("snapshot_hash", "route_source_snapshot_hash_mismatch"),
        ("tenant_scope", "route_source_scope_mismatch"),
        ("unverified_manifest", "route_raw_snapshot_invalid"),
        ("storage_ambiguity", "route_source_storage_ambiguity"),
        ("file_tamper", "route_file_snapshot_invalid"),
        ("path_traversal", "route_file_snapshot_invalid"),
    ],
)
def test_route_snapshot_integrity_failures_are_blocking(
    tmp_path: Path,
    failure: str,
    expected_code: str,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        file_authoritative = failure in {
            "storage_ambiguity",
            "file_tamper",
            "path_traversal",
        }
        run, collection, flat_path = _add_route_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id=f"routes-{failure}",
            cabinet_id=cabinet_id,
            rows=[_route_source_row()],
            file_authoritative=file_authoritative,
        )
        if failure == "database_hash":
            db.query(SourceSnapshotRow).filter_by(
                collection_id=collection.id
            ).one().raw_payload_hash = "changed"
        elif failure == "database_row_count":
            collection.row_count = 2
            results = [{**collection.payload["results"][0], "rowCount": 2}]
            collection.snapshot_hash = source_refresh._hash_payload(results)
            collection.payload = {**collection.payload, "results": results}
        elif failure == "snapshot_hash":
            collection.snapshot_hash = "changed"
        elif failure == "tenant_scope":
            collection.tenant_id = "other"
        elif failure == "unverified_manifest":
            collection.payload = {
                **collection.payload,
                "rawIntegrity": {"status": "failed"},
            }
        elif failure == "storage_ambiguity":
            row = _route_source_row()
            repository.add_source_snapshot_row(
                db,
                collection,
                row_number=1,
                raw_payload_hash=source_refresh._hash_payload(row),
                source_row_id="route-1",
                wb_cabinet_id=cabinet_id,
                row_payload=row,
            )
        elif failure == "file_tamper":
            flat_path.write_text(
                json.dumps([_route_source_row(warehouse="Склад X")]),
                encoding="utf-8",
            )
        elif failure == "path_traversal":
            results = list(collection.payload["results"])
            results[0] = {
                **results[0],
                "flatOutputFile": "../supplier-sales.flat.json",
            }
            collection.snapshot_hash = source_refresh._hash_payload(results)
            collection.payload = {**collection.payload, "results": results}

        selection = source_refresh._select_route_snapshot(db, report, roles=[(0, run)])

    assert selection.route_rows == ()
    assert expected_code in selection.blocking_reasons


def test_route_snapshot_uses_primary_before_base_and_blocks_peer_conflict(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        primary, _, _ = _add_route_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="routes-primary",
            cabinet_id=cabinet_id,
            rows=[_route_source_row()],
            file_authoritative=False,
        )
        base, _, _ = _add_route_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="routes-base",
            cabinet_id=cabinet_id,
            rows=[_route_source_row(warehouse="Склад B")],
            file_authoritative=False,
        )
        peer, _, _ = _add_route_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="routes-peer",
            cabinet_id=cabinet_id,
            rows=[_route_source_row(warehouse="Склад C")],
            file_authoritative=False,
        )

        selected = source_refresh._select_route_snapshot(
            db, report, roles=[(0, primary), (1, base)]
        )
        conflicted = source_refresh._select_route_snapshot(
            db, report, roles=[(0, primary), (0, peer)]
        )

    assert selected.blocking_reasons == ()
    assert selected.route_rows[0]["warehouse_name"] == "Склад A"
    assert conflicted.route_rows == ()
    assert conflicted.blocking_reasons == ("route_source_revision_conflict",)


def test_route_snapshot_partial_collection_is_reviewable(tmp_path: Path) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        run, collection, _ = _add_route_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="routes-partial",
            cabinet_id=cabinet_id,
            rows=[_route_source_row()],
            file_authoritative=False,
        )
        collection.status = "partial_source"
        selection = source_refresh._select_route_snapshot(db, report, roles=[(0, run)])

    assert selection.blocking_reasons == ()
    assert selection.review_reasons == ("route_source_partial",)
    assert len(selection.route_rows) == 1


@pytest.mark.parametrize(
    "source_type",
    ["wb_measurement_penalties", "wb_warehouse_measurements"],
)
def test_measurement_snapshot_db_and_file_authoritative_are_equivalent(
    tmp_path: Path,
    source_type: str,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        rows = [_measurement_source_row(source_type)]
        db_run, _, _ = _add_measurement_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id=f"{source_type}-db",
            cabinet_id=cabinet_id,
            source_type=source_type,
            rows=rows,
            file_authoritative=False,
        )
        file_run, _, _ = _add_measurement_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id=f"{source_type}-file",
            cabinet_id=cabinet_id,
            source_type=source_type,
            rows=rows,
            file_authoritative=True,
        )

        db_selection = source_refresh._select_measurement_snapshot(
            db, report, roles=[(0, db_run)], source_type=source_type
        )
        file_selection = source_refresh._select_measurement_snapshot(
            db, report, roles=[(0, file_run)], source_type=source_type
        )

    assert db_selection.blocking_reasons == ()
    assert file_selection.blocking_reasons == ()
    assert db_selection.measurement_rows == file_selection.measurement_rows
    assert db_selection.source_row_count == file_selection.source_row_count == 1
    assert db_selection.provider_event_count == 1
    assert db_selection.complete is True


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ("database_hash", "measurement_penalties_source_payload_hash_mismatch"),
        ("database_row_count", "measurement_penalties_database_row_count_mismatch"),
        ("snapshot_hash", "measurement_penalties_source_snapshot_hash_mismatch"),
        ("provider_total", "measurement_penalties_source_provider_total_mismatch"),
        ("tenant_scope", "measurement_penalties_source_scope_mismatch"),
        ("window", "measurement_penalties_source_window_mismatch"),
        ("unverified_manifest", "measurement_penalties_raw_snapshot_invalid"),
        ("storage_ambiguity", "measurement_penalties_source_storage_ambiguity"),
        ("file_tamper", "measurement_penalties_file_snapshot_invalid"),
        ("path_traversal", "measurement_penalties_file_snapshot_invalid"),
    ],
)
def test_measurement_snapshot_integrity_failures_are_blocking(
    tmp_path: Path,
    failure: str,
    expected_code: str,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    source_type = "wb_measurement_penalties"
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        file_authoritative = failure in {
            "storage_ambiguity",
            "file_tamper",
            "path_traversal",
        }
        run, collection, flat_path = _add_measurement_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id=f"measurement-{failure}",
            cabinet_id=cabinet_id,
            source_type=source_type,
            rows=[_measurement_source_row(source_type)],
            file_authoritative=file_authoritative,
        )
        if failure == "database_hash":
            db.query(SourceSnapshotRow).filter_by(
                collection_id=collection.id
            ).one().raw_payload_hash = "changed"
        elif failure == "database_row_count":
            db.query(SourceSnapshotRow).filter_by(collection_id=collection.id).delete()
        elif failure == "snapshot_hash":
            collection.snapshot_hash = "changed"
        elif failure == "provider_total":
            results = [{**collection.payload["results"][0], "providerTotal": 2}]
            collection.snapshot_hash = source_refresh._hash_payload(results)
            collection.payload = {**collection.payload, "results": results}
        elif failure == "tenant_scope":
            collection.tenant_id = "other"
        elif failure == "window":
            collection.payload = {
                **collection.payload,
                "coverageStart": "2026-04-02",
            }
        elif failure == "unverified_manifest":
            collection.payload = {
                **collection.payload,
                "rawIntegrity": {"status": "failed"},
            }
        elif failure == "storage_ambiguity":
            row = {
                **_measurement_source_row(source_type),
                "measurement_source_type": source_type,
            }
            repository.add_source_snapshot_row(
                db,
                collection,
                row_number=1,
                raw_payload_hash=source_refresh._hash_payload(row),
                source_row_id="measurement-1",
                wb_cabinet_id=cabinet_id,
                row_payload=row,
            )
        elif failure == "file_tamper":
            flat_path.write_text(json.dumps([]), encoding="utf-8")
        elif failure == "path_traversal":
            results = list(collection.payload["results"])
            results[0] = {
                **results[0],
                "flatOutputFile": "../measurements.flat.json",
            }
            collection.snapshot_hash = source_refresh._hash_payload(results)
            collection.payload = {**collection.payload, "results": results}

        selection = source_refresh._select_measurement_snapshot(
            db,
            report,
            roles=[(0, run)],
            source_type=source_type,
        )

    assert selection.measurement_rows == ()
    assert expected_code in selection.blocking_reasons


def test_measurement_snapshot_precedence_partial_and_context_build(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        report.publication_status = "draft"
        report.is_current = False
        unit_row = db.query(repository.ReportUnitRow).one()
        cabinet_id = unit_row.wb_cabinet_id
        primary, primary_collection, _ = _add_measurement_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="measurement-primary",
            cabinet_id=cabinet_id,
            source_type="wb_measurement_penalties",
            rows=[_measurement_source_row("wb_measurement_penalties")],
            file_authoritative=False,
        )
        base, _, _ = _add_measurement_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="measurement-base",
            cabinet_id=cabinet_id,
            source_type="wb_measurement_penalties",
            rows=[
                {
                    **_measurement_source_row("wb_measurement_penalties"),
                    "penalty_amount": "20",
                }
            ],
            file_authoritative=False,
        )
        peer, _, _ = _add_measurement_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="measurement-peer",
            cabinet_id=cabinet_id,
            source_type="wb_measurement_penalties",
            rows=[
                {
                    **_measurement_source_row("wb_measurement_penalties"),
                    "penalty_amount": "30",
                }
            ],
            file_authoritative=False,
        )
        warehouse_run, _, _ = _add_measurement_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="measurement-warehouse",
            cabinet_id=cabinet_id,
            source_type="wb_warehouse_measurements",
            rows=[_measurement_source_row("wb_warehouse_measurements")],
            file_authoritative=False,
        )

        selected = source_refresh._select_measurement_snapshot(
            db,
            report,
            roles=[(0, primary), (1, base)],
            source_type="wb_measurement_penalties",
        )
        conflicted = source_refresh._select_measurement_snapshot(
            db,
            report,
            roles=[(0, primary), (0, peer)],
            source_type="wb_measurement_penalties",
        )
        assert selected.measurement_rows[0]["penalty_amount"] == "10"
        assert conflicted.blocking_reasons == (
            "measurement_penalties_source_revision_conflict",
        )

        logistics_result = SimpleNamespace(
            context=SimpleNamespace(data_status="ready"),
            sku_rows=[
                SimpleNamespace(
                    tenant_id=report.tenant_id,
                    client_id=report.client_id,
                    wb_cabinet_id=cabinet_id,
                    client_company_id=unit_row.client_company_id,
                    scheme="fbo",
                    product_ref="product-safe",
                    product="Товар",
                    nm_id="1001",
                    source_hash_digest="sku-source-hash",
                )
            ],
        )
        source_refresh._build_and_persist_logistics_measurements(
            db,
            report,
            logistics_result=logistics_result,
            contributing_runs=[primary, warehouse_run],
        )
        db.flush()
        context = db.get(repository.ReportLogisticsMeasurementContext, report.id)
        events = db.query(repository.ReportLogisticsMeasurementRow).all()

        assert report.logistics_measurements_required is True
        assert context is not None
        assert context.data_status == "ready"
        assert context.complete_endpoint_count == 2
        assert context.source_event_count == 2
        assert context.provider_event_count == 2
        assert context.measurement_row_count == 1
        assert len(events) == 1
        assert events[0].event_kind == "merged"
        assert events[0].included_in_financial_kpi is False

        primary_collection.status = "partial_source"
        partial = source_refresh._select_measurement_snapshot(
            db,
            report,
            roles=[(0, primary)],
            source_type="wb_measurement_penalties",
        )
        assert partial.blocking_reasons == ()
        assert "measurement_penalties_source_partial" in partial.review_reasons
        assert partial.complete is False


def test_dimension_snapshot_uses_primary_before_base_and_blocks_peer_conflict(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        primary, _ = _add_dimension_database_snapshot(
            db,
            report,
            snapshot_set_id="dimensions-primary",
            cabinet_id=cabinet_id,
            cards=[_dimension_card("1001", length=30)],
        )
        base, _ = _add_dimension_database_snapshot(
            db,
            report,
            snapshot_set_id="dimensions-base",
            cabinet_id=cabinet_id,
            cards=[_dimension_card("1001", length=99)],
        )
        peer, _ = _add_dimension_database_snapshot(
            db,
            report,
            snapshot_set_id="dimensions-peer",
            cabinet_id=cabinet_id,
            cards=[_dimension_card("1001", length=41)],
        )

        selected = source_refresh._select_dimension_snapshot(
            db, report, roles=[(0, primary), (1, base)]
        )
        conflicted = source_refresh._select_dimension_snapshot(
            db, report, roles=[(0, primary), (0, peer)]
        )

    assert selected.blocking_reasons == ()
    assert selected.card_rows[0]["length_cm"] == 30
    assert conflicted.card_rows == ()
    assert conflicted.blocking_reasons == ("dimension_source_revision_conflict",)


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    [
        ("database_hash", "dimension_source_payload_hash_mismatch"),
        ("database_row_count", "dimension_database_row_count_mismatch"),
        ("snapshot_hash", "dimension_source_snapshot_hash_mismatch"),
        ("tenant_scope", "dimension_source_scope_mismatch"),
        ("storage_ambiguity", "dimension_source_storage_ambiguity"),
        ("file_tamper", "dimension_file_snapshot_invalid"),
        ("path_traversal", "dimension_file_snapshot_invalid"),
    ],
)
def test_dimension_snapshot_integrity_failures_are_blocking(
    tmp_path: Path,
    failure: str,
    expected_code: str,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        cards = [_dimension_card("1001")]
        if failure in {"storage_ambiguity", "file_tamper", "path_traversal"}:
            run, collection, flat_path = _add_dimension_file_snapshot(
                db,
                report,
                settings=settings,
                snapshot_set_id=f"dimensions-{failure}",
                cabinet_id=cabinet_id,
                cards=cards,
            )
            if failure == "storage_ambiguity":
                repository.add_source_snapshot_row(
                    db,
                    collection,
                    row_number=1,
                    raw_payload_hash=source_refresh._hash_payload(cards[0]),
                    source_row_id="1001",
                    wb_cabinet_id=cabinet_id,
                    row_payload=cards[0],
                )
            elif failure == "file_tamper":
                flat_path.write_text(
                    json.dumps([_dimension_card("1001", length=77)]),
                    encoding="utf-8",
                )
            else:
                results = list(collection.payload["results"])
                results[0] = {**results[0], "flatOutputFile": "../cards.flat.json"}
                collection.snapshot_hash = source_refresh._hash_payload(results)
                collection.payload = {**collection.payload, "results": results}
        else:
            run, collection = _add_dimension_database_snapshot(
                db,
                report,
                snapshot_set_id=f"dimensions-{failure}",
                cabinet_id=cabinet_id,
                cards=cards,
            )
            if failure == "database_hash":
                snapshot_row = (
                    db.query(SourceSnapshotRow)
                    .filter_by(collection_id=collection.id)
                    .one()
                )
                snapshot_row.raw_payload_hash = "changed"
            elif failure == "database_row_count":
                collection.row_count = 2
                results = [{**collection.payload["results"][0], "rowCount": 2}]
                collection.snapshot_hash = source_refresh._hash_payload(results)
                collection.payload = {**collection.payload, "results": results}
            elif failure == "snapshot_hash":
                collection.snapshot_hash = "changed"
            elif failure == "tenant_scope":
                collection.tenant_id = "other"

        selection = source_refresh._select_dimension_snapshot(
            db, report, roles=[(0, run)]
        )

    assert selection.card_rows == ()
    assert expected_code in selection.blocking_reasons


def test_dimension_snapshot_partial_collection_is_reviewable(tmp_path: Path) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        cabinet_id = db.query(repository.ReportUnitRow).one().wb_cabinet_id
        run, collection = _add_dimension_database_snapshot(
            db,
            report,
            snapshot_set_id="dimensions-partial",
            cabinet_id=cabinet_id,
            cards=[_dimension_card("1001")],
        )
        collection.status = "partial_source"

        selection = source_refresh._select_dimension_snapshot(
            db, report, roles=[(0, run)]
        )

    assert selection.blocking_reasons == ()
    assert selection.review_reasons == ("dimension_source_partial",)
    assert len(selection.card_rows) == 1


def test_dimension_context_and_rows_are_built_for_new_draft(tmp_path: Path) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        report.publication_status = "draft"
        report.is_current = False
        unit_row = db.query(repository.ReportUnitRow).one()
        finance_run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="dimensions-end-to-end-finance",
            period_start=report.period_start,
            period_end=report.period_end,
            reason="dimension end-to-end test",
            enforce_active_check=False,
        )
        finance_collection = repository.add_source_refresh_collection(
            db,
            finance_run,
            source_type="wb_finance_detail",
            source_label="WB finance",
            required=True,
            status="loaded",
            row_count=1,
        )
        finance_payload = {
            "rrdId": "dimension-finance-1",
            "rrDate": "2026-04-06",
            "orderDt": "2026-04-05",
            "orderUid": "dimension-order-1",
            "nmId": "1001",
            "sku": "BAR-1",
            "vendorCode": "WB-1",
            "title": "Товар",
            "deliveryMethod": "FBO",
            "docTypeName": "Логистика",
            "sellerOperName": "Логистика",
            "deliveryService": "50",
            "deliveryAmount": "1",
            "returnAmount": "0",
        }
        repository.add_source_snapshot_row(
            db,
            finance_collection,
            row_number=1,
            raw_payload_hash=source_refresh._hash_payload(finance_payload),
            source_row_id="dimension-finance-1",
            wb_cabinet_id=unit_row.wb_cabinet_id,
            row_payload=finance_payload,
        )
        cards_run, _collection = _add_dimension_database_snapshot(
            db,
            report,
            snapshot_set_id="dimensions-end-to-end-cards",
            cabinet_id=unit_row.wb_cabinet_id,
            cards=[_dimension_card("1001")],
        )

        logistics_result = source_refresh._build_and_persist_logistics_analysis(
            db,
            report,
            primary_refresh_run=finance_run,
        )
        source_refresh._build_and_persist_logistics_dimensions(
            db,
            report,
            logistics_result=logistics_result,
            primary_refresh_run=finance_run,
            contributing_runs=[cards_run],
        )
        db.commit()

        context = db.get(repository.ReportLogisticsDimensionContext, report.id)
        rows = repository.report_logistics_dimension_rows(db, report.id)

    assert report.logistics_dimensions_required is True
    assert context is not None
    assert context.data_status == "ready"
    assert context.dimension_row_count == 1
    assert len(rows) == 1
    assert rows[0].volume_l == Decimal("6")


def test_tariff_context_and_rows_are_built_for_new_draft(tmp_path: Path) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        report.publication_status = "draft"
        report.is_current = False
        unit_row = db.query(repository.ReportUnitRow).one()
        finance_run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="tariffs-end-to-end-finance",
            period_start=report.period_start,
            period_end=report.period_end,
            reason="tariff end-to-end test",
            enforce_active_check=False,
        )
        finance_collection = repository.add_source_refresh_collection(
            db,
            finance_run,
            source_type="wb_finance_detail",
            source_label="WB finance",
            required=True,
            status="loaded",
            row_count=1,
        )
        finance_payload = {
            "rrdId": "tariff-finance-1",
            "rrDate": "2026-04-06",
            "orderDt": "2026-04-05",
            "orderUid": "tariff-order-1",
            "nmId": "1001",
            "sku": "BAR-1",
            "vendorCode": "WB-1",
            "title": "Товар",
            "deliveryMethod": "FBO",
            "docTypeName": "Логистика",
            "sellerOperName": "Логистика",
            "deliveryService": "50",
            "deliveryAmount": "1",
            "returnAmount": "0",
        }
        repository.add_source_snapshot_row(
            db,
            finance_collection,
            row_number=1,
            raw_payload_hash=source_refresh._hash_payload(finance_payload),
            source_row_id="tariff-finance-1",
            wb_cabinet_id=unit_row.wb_cabinet_id,
            row_payload=finance_payload,
        )
        tariff_run, _collection = _add_tariff_database_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="tariffs-end-to-end-source",
            cabinet_id=unit_row.wb_cabinet_id,
            rows=[_tariff_row()],
        )

        logistics_result = source_refresh._build_and_persist_logistics_analysis(
            db,
            report,
            primary_refresh_run=finance_run,
        )
        source_refresh._build_and_persist_logistics_tariffs(
            db,
            report,
            logistics_result=logistics_result,
            primary_refresh_run=finance_run,
            contributing_runs=[tariff_run],
        )
        db.commit()

        context = db.get(repository.ReportLogisticsTariffContext, report.id)
        rows = db.query(repository.ReportLogisticsTariffRow).all()

    assert report.logistics_tariffs_required is True
    assert context is not None
    assert context.data_status == "partial"
    assert context.expected_point_count == 2
    assert context.factual_point_count == 1
    assert context.unavailable_point_count == 1
    assert len(rows) == 2
    assert {row.tariff_type for row in rows} == {"box", "pallet"}


def test_route_context_and_rows_are_built_for_new_draft(tmp_path: Path) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        report.publication_status = "draft"
        report.is_current = False
        unit_row = db.query(repository.ReportUnitRow).one()
        finance_run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="routes-end-to-end-finance",
            period_start=report.period_start,
            period_end=report.period_end,
            reason="route end-to-end test",
            enforce_active_check=False,
        )
        finance_collection = repository.add_source_refresh_collection(
            db,
            finance_run,
            source_type="wb_finance_detail",
            source_label="WB finance",
            required=True,
            status="loaded",
            row_count=1,
        )
        finance_payload = {
            "rrdId": "route-finance-1",
            "rrDate": "2026-04-06",
            "orderDt": "2026-04-05",
            "orderUid": "route-order-1",
            "nmId": "1001",
            "sku": "BAR-1",
            "vendorCode": "WB-1",
            "title": "Товар",
            "deliveryMethod": "FBO",
            "docTypeName": "Логистика",
            "sellerOperName": "Логистика",
            "deliveryService": "50",
            "deliveryAmount": "1",
            "returnAmount": "0",
        }
        repository.add_source_snapshot_row(
            db,
            finance_collection,
            row_number=1,
            raw_payload_hash=source_refresh._hash_payload(finance_payload),
            source_row_id="route-finance-1",
            wb_cabinet_id=unit_row.wb_cabinet_id,
            row_payload=finance_payload,
        )
        route_run, _collection, _flat_path = _add_route_snapshot(
            db,
            report,
            settings=settings,
            snapshot_set_id="routes-end-to-end-source",
            cabinet_id=unit_row.wb_cabinet_id,
            rows=[_route_source_row()],
            file_authoritative=False,
        )

        logistics_result = source_refresh._build_and_persist_logistics_analysis(
            db,
            report,
            primary_refresh_run=finance_run,
        )
        source_refresh._build_and_persist_logistics_routes(
            db,
            report,
            logistics_result=logistics_result,
            primary_refresh_run=finance_run,
            contributing_runs=[route_run],
        )
        db.commit()

        context = db.get(repository.ReportLogisticsRouteContext, report.id)
        rows = db.query(repository.ReportLogisticsRouteRow).all()

    assert report.logistics_routes_required is True
    assert context is not None
    assert context.data_status == "ready"
    assert context.total_chain_count == 1
    assert context.matched_chain_count == 1
    assert context.missing_chain_count == 0
    assert context.total_logistics == Decimal("50")
    assert context.linked_logistics == Decimal("50")
    assert len(rows) == 1
    assert rows[0].warehouse == "Склад A"
    assert rows[0].destination == "Страна · Округ · Регион A"
    assert rows[0].coverage_status == "ready"


def test_logistics_analysis_blocks_undated_report_row_without_losing_total(
    tmp_path: Path,
) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        _user, report = _session_user_report(db, user, report)
        unit_row = (
            db.query(repository.ReportUnitRow).filter_by(report_run_id=report.id).one()
        )
        unit_row.week = None
        unit_row.accounting_period_date = None
        unit_row.logistics = Decimal("50")

        source_refresh._build_and_persist_logistics_analysis(
            db,
            report,
            refresh_runs=[],
        )
        db.commit()

        context = db.get(ReportLogisticsAnalysisContext, report.id)
        order_count = db.query(ReportLogisticsOrderRow).count()
        sku_count = db.query(ReportLogisticsSkuRow).count()

    assert context is not None
    assert context.data_status == "blocked"
    assert context.report_logistics_total == Decimal("50")
    assert context.invalid_report_row_count == 1
    assert context.report_required_field_error_count == 1
    assert "invalid_required_report_fields" in context.blocking_reasons
    assert order_count == 0
    assert sku_count == 0


def test_logistics_analysis_blocks_non_object_snapshot_payload(
    tmp_path: Path,
) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        unit_row = (
            db.query(repository.ReportUnitRow).filter_by(report_run_id=report.id).one()
        )
        unit_row.logistics = Decimal("0")
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="invalid-logistics-payload",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            source_report=report,
            reason="invalid logistics payload",
        )
        collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="wb_finance_detail",
            source_label="WB finance",
            required=True,
            status="loaded",
            row_count=1,
        )
        invalid_payload = ["not", "an", "object"]
        repository.add_source_snapshot_row(
            db,
            collection,
            row_number=1,
            raw_payload_hash=source_refresh._hash_payload(invalid_payload),
            source_row_id="rrd-invalid",
            wb_cabinet_id=unit_row.wb_cabinet_id,
            row_payload=invalid_payload,
        )

        source_refresh._build_and_persist_logistics_analysis(
            db,
            report,
            primary_refresh_run=refresh_run,
        )
        db.commit()
        context = db.get(ReportLogisticsAnalysisContext, report.id)

    assert context is not None
    assert context.data_status == "blocked"
    assert context.source_row_count == 1
    assert context.invalid_source_payload_shape_count == 1
    assert context.invalid_source_row_count == 1
    assert "invalid_source_payload_shape" in context.blocking_reasons


def test_logistics_snapshot_owner_replaces_base_revision(
    tmp_path: Path,
) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        unit_row = (
            db.query(repository.ReportUnitRow).filter_by(report_run_id=report.id).one()
        )
        base = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="logistics-base",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            source_report=report,
            reason="base",
            enforce_active_check=False,
        )
        current = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="incremental",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="logistics-current",
            period_start=report.period_start,
            period_end=report.period_end,
            source_window_start=date(2026, 4, 6),
            source_window_end=date(2026, 4, 6),
            user=user,
            source_report=report,
            base_source_refresh_run=base,
            reason="current",
            enforce_active_check=False,
        )
        for run, amount in ((base, "40"), (current, "50")):
            collection = repository.add_source_refresh_collection(
                db,
                run,
                source_type="wb_finance_detail",
                source_label="WB finance",
                required=True,
                status="loaded",
                row_count=1,
            )
            payload = {
                "rrdId": 1,
                "rrDate": "2026-04-06",
                "orderUid": "order-1",
                "nmId": "1001",
                "sku": "BAR-1",
                "deliveryMethod": "FBO",
                "deliveryService": amount,
                "deliveryAmount": "1",
                "returnAmount": "0",
            }
            repository.add_source_snapshot_row(
                db,
                collection,
                row_number=1,
                raw_payload_hash=source_refresh._hash_payload(payload),
                source_row_id="1",
                wb_cabinet_id=unit_row.wb_cabinet_id,
                row_payload=payload,
            )

        source_refresh._build_and_persist_logistics_analysis(
            db,
            report,
            primary_refresh_run=current,
            base_refresh_run=base,
        )
        db.commit()
        context = db.get(ReportLogisticsAnalysisContext, report.id)

    assert context is not None
    assert context.data_status == "ready"
    assert context.raw_logistics_total == Decimal("50")
    assert context.source_revision_discarded_count == 1
    assert context.source_revision_conflict_count == 0


def test_logistics_provider_identity_mismatch_blocks_gate(tmp_path: Path) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        unit_row = (
            db.query(repository.ReportUnitRow).filter_by(report_run_id=report.id).one()
        )
        base = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="identity-base",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            source_report=report,
            reason="identity base",
            enforce_active_check=False,
        )
        current = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="incremental",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="identity-current",
            period_start=report.period_start,
            period_end=report.period_end,
            source_window_start=date(2026, 4, 6),
            source_window_end=date(2026, 4, 6),
            user=user,
            source_report=report,
            base_source_refresh_run=base,
            reason="identity current",
            enforce_active_check=False,
        )
        for run, amount, snapshot_row_id in (
            (base, "40", "alias-a"),
            (current, "60", "alias-b"),
        ):
            collection = repository.add_source_refresh_collection(
                db,
                run,
                source_type="wb_finance_detail",
                source_label="WB finance",
                required=True,
                status="loaded",
                row_count=1,
            )
            payload = {
                "rrdId": 1,
                "rrDate": "2026-04-06",
                "orderUid": "order-1",
                "nmId": "1001",
                "sku": "BAR-1",
                "deliveryMethod": "FBO",
                "deliveryService": amount,
                "deliveryAmount": "1",
                "returnAmount": "0",
            }
            repository.add_source_snapshot_row(
                db,
                collection,
                row_number=1,
                raw_payload_hash=source_refresh._hash_payload(payload),
                source_row_id=snapshot_row_id,
                wb_cabinet_id=unit_row.wb_cabinet_id,
                row_payload=payload,
            )

        source_refresh._build_and_persist_logistics_analysis(
            db,
            report,
            primary_refresh_run=current,
            base_refresh_run=base,
        )
        db.commit()
        context = db.get(ReportLogisticsAnalysisContext, report.id)
        order_count = db.query(ReportLogisticsOrderRow).count()
        sku_count = db.query(ReportLogisticsSkuRow).count()

    assert context is not None
    assert context.data_status == "blocked"
    assert context.source_identity_error_count == 2
    assert "source_identity_mismatch" in context.blocking_reasons
    assert order_count == 0
    assert sku_count == 0


def test_logistics_conflicting_revisions_in_owner_layer_block_gate(
    tmp_path: Path,
) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        unit_row = (
            db.query(repository.ReportUnitRow).filter_by(report_run_id=report.id).one()
        )
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="conflicting-logistics-revisions",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            source_report=report,
            reason="conflicting revisions",
        )
        collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="wb_finance_detail",
            source_label="WB finance",
            required=True,
            status="loaded",
            row_count=2,
        )
        payloads = [
            {
                "rrdId": 1,
                "rrDate": "2026-04-06",
                "orderUid": "order-1",
                "nmId": "1001",
                "sku": "BAR-1",
                "deliveryMethod": "FBO",
                "deliveryService": amount,
                "deliveryAmount": "1",
                "returnAmount": "0",
            }
            for amount in ("40", "50")
        ]
        stale_hash = source_refresh._hash_payload(payloads[0])
        for row_number, payload in enumerate(payloads, 1):
            repository.add_source_snapshot_row(
                db,
                collection,
                row_number=row_number,
                raw_payload_hash=stale_hash,
                source_row_id="1",
                wb_cabinet_id=unit_row.wb_cabinet_id,
                row_payload=payload,
            )

        source_refresh._build_and_persist_logistics_analysis(
            db,
            report,
            primary_refresh_run=refresh_run,
        )
        db.commit()
        context = db.get(ReportLogisticsAnalysisContext, report.id)

    assert context is not None
    assert context.data_status == "blocked"
    assert context.source_revision_conflict_count == 1
    assert context.source_revision_discarded_count == 1
    assert "source_revision_conflict" in context.blocking_reasons
    assert "source_payload_hash_mismatch" in context.blocking_reasons


def test_page_limit_exhaustion_detects_full_last_page_per_source_group() -> None:
    assert _page_limit_exhausted(
        [
            WbProductCardsPageResult(
                seller_account_id="WB_ACCOUNT_1",
                account_name="Cabinet",
                cards_source="active",
                page_index=50,
                ok=True,
                card_count=100,
            )
        ],
        max_pages=50,
        page_limit=100,
        row_count_attribute="card_count",
        group_attributes=("seller_account_id", "cards_source"),
    )
    assert not _page_limit_exhausted(
        [
            WbProductCardsPageResult(
                seller_account_id="WB_ACCOUNT_1",
                account_name="Cabinet",
                cards_source="active",
                page_index=50,
                ok=True,
                card_count=99,
            )
        ],
        max_pages=50,
        page_limit=100,
        row_count_attribute="card_count",
        group_attributes=("seller_account_id", "cards_source"),
    )


def test_source_refresh_enqueue_accepts_explicit_business_period(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        payload = SourceRefreshService(settings).enqueue(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            user=user,
            source_report=report,
            reason="April financial acceptance",
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
        )
        db.commit()

    assert payload["periodStart"] == "2026-04-01"
    assert payload["periodEnd"] == "2026-04-30"


@pytest.mark.parametrize("resume_mode", ["onec-only", "ozon-only"])
def test_source_refresh_auto_resume_creates_new_immutable_lineage(
    tmp_path: Path,
    resume_mode: str,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    period_start = date(2026, 4, 1)
    period_end = date(2026, 4, 30)

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        previous = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="full-partial-april",
            period_start=period_start,
            period_end=period_end,
            user=user,
            source_report=report,
            reason="partial 1C",
        )
        previous_root = settings.source_refresh_root_path / previous.snapshot_set_id
        checkpoint_dir = previous_root / "onec" / "commissioner_reports"
        checkpoint_dir.mkdir(parents=True)
        (checkpoint_dir / "manifest.json").write_text("{}", encoding="utf-8")
        repository.add_source_refresh_collection(
            db,
            previous,
            source_type="onec_commissioner_reports",
            source_label="Document_ОтчетКомиссионера",
            required=False,
            publication_required=True,
            status="partial_source",
            row_count=500,
            raw_path=str(previous_root / "onec"),
            payload={"retryable": True},
        )
        repository.update_source_refresh_run(
            db,
            previous,
            status="needs_review",
            root_dir=str(previous_root),
            started_at=datetime(2026, 7, 10, 10, 0),
            finished_at=datetime(2026, 7, 10, 10, 5),
        )
        db.commit()

        payload = SourceRefreshService(settings).enqueue(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode=resume_mode,
            user=user,
            source_report=report,
            period_start=period_start,
            period_end=period_end,
        )
        current = db.get(source_refresh.SourceRefreshRun, payload["id"])

    assert payload["id"] != previous.id
    assert payload["snapshotSetId"] != previous.snapshot_set_id
    assert payload["resumedFromRunId"] == previous.id
    assert current is not None
    assert current.resumed_from_run_id == previous.id
    assert (previous_root / "onec").is_dir()


@pytest.mark.parametrize(
    ("requested_mode", "should_resume"),
    [("full", True), ("ozon-only", False)],
)
def test_source_refresh_auto_resume_uses_wb_checkpoint_only_outside_ozon_mode(
    tmp_path: Path,
    requested_mode: str,
    should_resume: bool,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    period_start = date(2026, 4, 1)
    period_end = date(2026, 4, 30)

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        previous = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="full-partial-wb-april",
            period_start=period_start,
            period_end=period_end,
            user=user,
            source_report=report,
            reason="partial WB",
        )
        previous_root = settings.source_refresh_root_path / previous.snapshot_set_id
        checkpoint_dir = previous_root / "wb_finance"
        checkpoint_dir.mkdir(parents=True)
        (checkpoint_dir / "manifest.json").write_text("{}", encoding="utf-8")
        repository.add_source_refresh_collection(
            db,
            previous,
            source_type="wb_finance_detail",
            source_label="WB finance detail",
            required=True,
            status="partial_source",
            row_count=800_000,
            raw_path=str(checkpoint_dir),
            payload={"retryable": True},
        )
        repository.update_source_refresh_run(
            db,
            previous,
            status="failed",
            root_dir=str(previous_root),
            started_at=datetime(2026, 7, 10, 10, 0),
            finished_at=datetime(2026, 7, 10, 10, 5),
        )
        db.commit()

        payload = SourceRefreshService(settings).enqueue(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode=requested_mode,
            user=user,
            source_report=report,
            period_start=period_start,
            period_end=period_end,
        )
        current = db.get(source_refresh.SourceRefreshRun, payload["id"])

    assert payload["id"] != previous.id
    assert payload["resumedFromRunId"] == (previous.id if should_resume else None)
    assert current is not None
    assert current.resumed_from_run_id == (previous.id if should_resume else None)
    assert (previous_root / "wb_finance" / "manifest.json").is_file()


def test_ozon_only_explicit_resume_rejects_empty_onec_directory(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    period_start = date(2026, 4, 1)
    period_end = date(2026, 4, 30)

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        previous = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="full-empty-onec-april",
            period_start=period_start,
            period_end=period_end,
            user=user,
            source_report=report,
        )
        previous_root = settings.source_refresh_root_path / previous.snapshot_set_id
        (previous_root / "onec").mkdir(parents=True)
        repository.update_source_refresh_run(
            db,
            previous,
            status="failed",
            root_dir=str(previous_root),
            finished_at=datetime(2026, 7, 10, 10, 5),
        )
        db.commit()

        with pytest.raises(
            source_refresh.SourceRefreshConfigError,
            match="incompatible or has no safe checkpoint",
        ):
            SourceRefreshService(settings).enqueue(
                db,
                tenant_id="shumeyko",
                client_id=report.client_id,
                mode="ozon-only",
                user=user,
                source_report=report,
                period_start=period_start,
                period_end=period_end,
                resume_from_run_id=previous.id,
            )


def test_copy_resume_directory_preserves_nested_document_tree(tmp_path: Path) -> None:
    source = tmp_path / "source"
    nested = source / "WB_ACCOUNT_1" / "documents"
    nested.mkdir(parents=True)
    (source / "manifest.json").write_text("{}", encoding="utf-8")
    (nested / "notice.zip").write_bytes(b"primary-document")

    destination = tmp_path / "destination"
    source_refresh._copy_resume_directory(source, destination)

    assert (destination / "manifest.json").read_text(encoding="utf-8") == "{}"
    copied_document = destination / "WB_ACCOUNT_1" / "documents" / "notice.zip"
    assert copied_document.read_bytes() == b"primary-document"


def test_daily_fact_parity_requires_exact_reconciled_cogs() -> None:
    money_fields = {
        "quantity": Decimal("1"),
        "net_revenue": Decimal("100"),
        "wb_commission": Decimal("10"),
        "logistics": Decimal("5"),
        "storage": Decimal("1"),
        "acceptance": Decimal("1"),
        "marketplace_promotion": Decimal("1"),
        "penalties_and_holdbacks": Decimal("1"),
        "acquiring": Decimal("1"),
        "vat_input_from_marketplace": Decimal("1"),
        "vat_input_from_1c": Decimal("1"),
    }
    daily = SimpleNamespace(
        **money_fields,
        cogs=Decimal("50.00"),
        source_row_count=1,
    )
    report_row = SimpleNamespace(
        **money_fields,
        wb_promotion=money_fields["marketplace_promotion"],
        vat_input_from_wb=money_fields["vat_input_from_marketplace"],
        cogs_from_1c_with_extra_costs=Decimal("50.00"),
    )
    build = {"report": SimpleNamespace(rows=[report_row]), "wb_rows": 1}

    parity = source_refresh._wb_daily_fact_parity(build, [daily])

    assert parity["differences"] == {}
    assert parity["roundingTolerance"] == {"cogs": "0.00"}

    daily.cogs = Decimal("50.01")
    with pytest.raises(
        source_refresh.SourceRefreshConfigError,
        match="daily facts parity mismatch: cogs",
    ):
        source_refresh._wb_daily_fact_parity(build, [daily])


def test_snapshot_batch_is_1000_rows_and_unknown_transaction_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert source_refresh.SOURCE_SNAPSHOT_ROW_CHUNK_SIZE == 1000
    commits: list[bool] = []
    inserted: list[list[dict[str, object]]] = []
    db = SimpleNamespace(commit=lambda: commits.append(True))
    collection = SimpleNamespace(id="collection-1")
    batch = [{"row_number": index} for index in range(1, 1001)]

    monkeypatch.setattr(
        repository,
        "add_source_snapshot_rows",
        lambda _db, _collection, rows: inserted.append(list(rows)),
    )
    source_refresh._flush_snapshot_batch(db, collection, batch)

    assert len(inserted) == 1
    assert len(inserted[0]) == 1000
    assert commits == [True]
    assert batch == []

    unknown_batch = [{"row_number": index} for index in range(1001, 2001)]

    def fail_insert(_db, _collection, _rows):
        raise OperationalError("INSERT source snapshot", {}, ConnectionError())

    monkeypatch.setattr(repository, "add_source_snapshot_rows", fail_insert)
    with pytest.raises(OperationalError):
        source_refresh._flush_snapshot_batch(db, collection, unknown_batch)

    assert len(unknown_batch) == 1000
    assert commits == [True]

    commit_failure_inserts: list[list[dict[str, object]]] = []
    commit_failure_batch = [{"row_number": index} for index in range(2001, 3001)]

    def fail_commit():
        raise OperationalError("COMMIT", {}, ConnectionError())

    monkeypatch.setattr(
        repository,
        "add_source_snapshot_rows",
        lambda _db, _collection, rows: commit_failure_inserts.append(list(rows)),
    )
    with pytest.raises(OperationalError):
        source_refresh._flush_snapshot_batch(
            SimpleNamespace(commit=fail_commit),
            collection,
            commit_failure_batch,
        )

    assert len(commit_failure_inserts) == 1
    assert commit_failure_batch == []


def test_operational_error_fails_immutable_run_and_next_run_uses_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    service = SourceRefreshService(settings)
    credentials = SourceCredentials(
        wb_settings=None,
        onec_settings=None,
        ozon_settings=None,
        wb_cabinet_ids={},
        ozon_cabinet_ids={},
        issues=(),
    )
    monkeypatch.setattr(service, "_credentials", lambda *_args, **_kwargs: credentials)

    def fail_after_checkpoint(context, *, include_external):
        checkpoint = context.root_dir / "onec" / "sales_register"
        checkpoint.mkdir(parents=True, exist_ok=True)
        (checkpoint / "manifest.json").write_text("{}", encoding="utf-8")
        raise OperationalError("INSERT source snapshot", {}, ConnectionError())

    monkeypatch.setattr(service, "_run_collectors", fail_after_checkpoint)
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        failed = service.run(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode="onec-only",
            user=user,
            source_report=report,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
        )
        assert failed["status"] == "failed"
        failed_run = db.get(source_refresh.SourceRefreshRun, failed["id"])
        assert failed_run is not None
        assert failed_run.finished_at is not None

        resumed = service.enqueue(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode="onec-only",
            user=user,
            source_report=report,
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
        )

    assert resumed["id"] != failed["id"]
    assert resumed["resumedFromRunId"] == failed["id"]


@pytest.fixture(autouse=True)
def successful_onec_metadata_check(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        source_refresh,
        "check_onec_odata_metadata_with_retry",
        lambda _settings: OnecODataMetadataCheckResult(
            ok=True,
            status_code=200,
            content_type="application/xml",
            attempt_count=1,
            timeout_seconds=60,
        ),
    )


def test_source_refresh_blocks_hash_only_tenant_credentials(tmp_path: Path) -> None:
    settings, session_factory, user, _report, mapping_dir = _source_refresh_context(
        tmp_path,
        integration_key="",
    )
    with session_factory() as db:
        user, _report = _session_user_report(db, user, _report)
        repository.save_tenant_integration(
            db,
            user=user,
            tenant_id="shumeyko",
            provider="wb_api",
            secret="wb-token-secret",
        )
        repository.save_tenant_integration(
            db,
            user=user,
            tenant_id="shumeyko",
            provider="onec_readonly",
            secret=_onec_secret(),
        )
        db.commit()
        service = SourceRefreshService(settings)
        payload = service.run(db, tenant_id="shumeyko", mode="full")

    assert payload["status"] == "needs_configuration"
    assert {item["sourceType"] for item in payload["collections"]} >= {
        "wb_api",
        "onec_readonly",
        "sku_mapping",
    }
    assert mapping_dir.exists()


def test_source_refresh_blocks_check_failed_tenant_integration_before_external_reads(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )

    def exporter_should_not_run(*_args: object, **_kwargs: object) -> list[object]:
        raise AssertionError("external exporter should not run")

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        onec_integration = (
            db.query(TenantIntegration)
            .filter_by(tenant_id="shumeyko", provider="onec_readonly")
            .one()
        )
        onec_integration.status = "check_failed"
        onec_integration.last_checked_at = datetime(2026, 7, 5, 14, 20)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=exporter_should_not_run,
            onec_exporter=exporter_should_not_run,
            workbook_builder=_builder_should_not_run,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="daily",
            user=user,
            source_report=report,
        )
        onec_collection = (
            db.query(SourceRefreshCollection)
            .filter_by(source_type="onec_readonly")
            .one()
        )

    assert payload["status"] == "needs_configuration"
    assert onec_collection.status == "needs_configuration"
    assert onec_collection.error_message == "integration_not_runtime_ready"
    assert onec_collection.payload["status"] == "check_failed"


def test_source_refresh_fails_fast_on_onec_metadata_before_marketplace_reads(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    external_calls: list[str] = []

    def exporter_should_not_run(*_args: object, **_kwargs: object) -> list[object]:
        external_calls.append("called")
        raise AssertionError("heavy external exporter should not run")

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=exporter_should_not_run,
            wb_product_cards_exporter=exporter_should_not_run,
            onec_exporter=exporter_should_not_run,
            onec_metadata_checker=lambda _settings: OnecODataMetadataCheckResult(
                ok=False,
                status_code=404,
                error="HTTP 404",
                content_type="application/json",
            ),
            workbook_builder=_builder_should_not_run,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )

        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="daily",
            user=user,
            source_report=report,
        )
        metadata_collection = (
            db.query(SourceRefreshCollection)
            .filter_by(source_type="onec_odata_metadata")
            .one()
        )
        integration = (
            db.query(TenantIntegration)
            .filter_by(tenant_id="shumeyko", provider="onec_readonly")
            .one()
        )
        integration_payload = repository.tenant_integration_payload(
            integration,
            "shumeyko",
            "onec_readonly",
        )

    assert payload["status"] == "failed"
    assert payload["errorMessage"] == "onec_odata_metadata_unavailable: HTTP 404"
    assert external_calls == []
    assert metadata_collection.required is True
    assert metadata_collection.status == "failed"
    assert metadata_collection.payload["metadataValid"] is False
    assert metadata_collection.payload["attemptCount"] == 1
    assert integration.status == "configured"
    assert integration_payload["runtimeStatus"] == "check_failed"
    assert integration_payload["lastRuntimeCheck"]["httpStatus"] == 404


def test_split_collector_retries_transient_metadata_failure_then_stops(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.source_refresh_task_queue_enabled = True
    external_calls: list[str] = []

    def exporter_should_not_run(*_args: object, **_kwargs: object) -> list[object]:
        external_calls.append("called")
        raise AssertionError("heavy external exporter should not run")

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=exporter_should_not_run,
            wb_product_cards_exporter=exporter_should_not_run,
            onec_exporter=exporter_should_not_run,
            onec_metadata_checker=lambda _settings: OnecODataMetadataCheckResult(
                ok=False,
                status_code=503,
                error="ServiceUnavailable",
                content_type="application/json",
            ),
            workbook_builder=_builder_should_not_run,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        queued = service.enqueue(
            db,
            tenant_id="shumeyko",
            mode="daily",
            user=user,
            source_report=report,
        )
        run = db.get(SourceRefreshRun, queued["id"])
        assert run is not None
        tasks = repository.ensure_source_refresh_task_chain(db, run)
        db.commit()

        for attempt in (1, 2):
            collector = repository.claim_next_source_refresh_task(
                db,
                worker_id=f"collector:{attempt}",
                allowed_task_types={"collect_sources"},
                now=tasks[0].not_before,
            )
            assert collector is tasks[0]
            db.commit()
            db.info["source_refresh_split_pipeline"] = True
            try:
                payload = service.run_existing(
                    db,
                    run.id,
                    worker_id=f"collector:{attempt}",
                    stop_after_sources=True,
                )
            finally:
                db.info.pop("source_refresh_split_pipeline", None)
            db.refresh(run)
            db.refresh(collector)
            if attempt == 1:
                assert payload["status"] == "queued"
                assert collector.status == "queued"
                assert run.finished_at is None

        assert payload["status"] == "failed"
        assert collector.status == "failed"
        assert collector.attempt == 2
        assert run.finished_at is not None
        assert [item.status for item in tasks[1:]] == [
            "cancelled",
            "cancelled",
            "cancelled",
        ]
        assert external_calls == []


def test_failed_snapshot_cleanup_keeps_latest_and_published_snapshot(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.source_refresh_failed_snapshot_keep = 2
    snapshot_ids = [f"daily-failed-{index}" for index in range(1, 5)]

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        report.source_snapshot_set_id = snapshot_ids[0]
        runs = []
        for index, snapshot_set_id in enumerate(snapshot_ids, start=1):
            run = repository.create_source_refresh_run(
                db,
                tenant_id="shumeyko",
                mode="daily",
                credential_source="tenant",
                dry_run=False,
                snapshot_set_id=snapshot_set_id,
                period_start=date(2026, 7, 1),
                period_end=date(2026, 7, 9),
                user=user,
                source_report=None,
                reason="failed cleanup test",
            )
            run.created_at = datetime(2026, 7, 10, index, 0)
            repository.update_source_refresh_run(
                db,
                run,
                status="failed",
                finished_at=datetime(2026, 7, 10, index, 1),
            )
            snapshot_dir = settings.source_refresh_root_path / snapshot_set_id
            snapshot_dir.mkdir(parents=True)
            (snapshot_dir / "manifest.json").write_text("{}", encoding="utf-8")
            runs.append(run)
        db.flush()
        service = SourceRefreshService(settings)

        removed = service._prune_failed_snapshot_directories(db, runs[-1])

    assert {path.name for path in removed} == {snapshot_ids[1]}
    assert (settings.source_refresh_root_path / snapshot_ids[0]).exists()
    assert not (settings.source_refresh_root_path / snapshot_ids[1]).exists()
    assert (settings.source_refresh_root_path / snapshot_ids[2]).exists()
    assert (settings.source_refresh_root_path / snapshot_ids[3]).exists()


def test_source_refresh_uses_encrypted_tenant_credentials_and_creates_report(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_report_list_exporter=_fake_report_list_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_fake_workbook_builder,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="full",
            user=user,
            source_report=report,
        )
        db.commit()
        new_report = db.get(ReportRun, payload["newReportRunId"])
        source_loads = db.query(SourceLoad).filter_by(report_run_id=new_report.id).all()
        refresh_collections = (
            db.query(SourceRefreshCollection)
            .filter_by(refresh_run_id=payload["id"])
            .all()
        )
        snapshot_rows = db.query(SourceSnapshotRow).all()

    assert payload["status"] == "needs_review"
    assert seen["wb_api_key"] == "wb-token-secret"
    assert seen["wb_finance_period_start"] == date(2026, 2, 23)
    assert seen["wb_finance_period_end"] == date(2026, 6, 17)
    assert seen["onec_username"] == "readonly"
    assert seen["onec_password"] == "onec-secret"
    assert seen["onec_period_start"] == date(2026, 3, 1)
    assert seen["onec_period_end"] == date(2026, 6, 17)
    assert seen["wb_content_request_delay_seconds"] == 0.65
    assert new_report is not None
    assert {item.source_type for item in source_loads} >= {
        "wb_finance_detail",
        "wb_sales_report_list",
        "wb_product_cards",
        "sku_mapping",
        "onec_sales_register",
    }
    assert {item.source_type for item in snapshot_rows} >= {
        "wb_finance_detail",
        "wb_sales_report_list",
        "wb_product_cards",
        "sku_mapping",
        "onec_sales_register",
    }
    assert any(
        item.source_type == "wb_finance_detail" and item.source_row_id == "987"
        for item in snapshot_rows
    )
    assert any(
        item.source_type == "wb_sales_report_list" and item.source_row_id == "713660329"
        for item in snapshot_rows
    )
    assert any(
        item.source_type == "onec_sales_register"
        and item.source_row_id == "sales_register-ref"
        for item in snapshot_rows
    )
    assert any(
        item.source_type == "onec_commissioner_reports"
        and item.publication_required
        and not item.required
        for item in source_loads
    )
    assert any(
        item.source_type == "onec_commissioner_reports"
        and item.payload.get("detailMode") == "financial_tables"
        for item in refresh_collections
    )


def test_source_refresh_keeps_large_wb_raw_files_without_database_duplication(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.source_refresh_wb_persist_row_limit = 0
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_report_list_exporter=_fake_report_list_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_fake_workbook_builder,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="full",
            user=user,
            source_report=report,
        )
        db.commit()
        collection = (
            db.query(SourceRefreshCollection)
            .filter_by(
                refresh_run_id=payload["id"],
                source_type="wb_finance_detail",
            )
            .one()
        )
        persisted_count = (
            db.query(SourceSnapshotRow)
            .filter_by(
                refresh_run_id=payload["id"],
                source_type="wb_finance_detail",
            )
            .count()
        )

    assert collection.row_count == 1
    assert collection.status == "loaded"
    assert collection.payload["rowPersistence"] == {
        "status": "skipped_large_snapshot",
        "limit": 0,
        "rawFilesAuthoritative": True,
    }
    assert persisted_count == 0


def test_source_refresh_files_only_skips_all_wb_raw_rows(tmp_path: Path) -> None:
    seen: dict[str, object] = {}
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.source_refresh_raw_db_mode = "files_only"
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_report_list_exporter=_fake_report_list_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_fake_workbook_builder,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="full",
            user=user,
            source_report=report,
        )
        db.commit()
        collections = (
            db.query(SourceRefreshCollection)
            .filter_by(refresh_run_id=payload["id"])
            .all()
        )
        wb_rows = (
            db.query(SourceSnapshotRow)
            .filter(
                SourceSnapshotRow.refresh_run_id == payload["id"],
                SourceSnapshotRow.source_type.in_(
                    {
                        "wb_finance_detail",
                        "wb_sales_report_list",
                        "wb_product_cards",
                    }
                ),
            )
            .count()
        )

    assert wb_rows == 0
    wb_collections = [
        item
        for item in collections
        if item.source_type
        in {"wb_finance_detail", "wb_sales_report_list", "wb_product_cards"}
    ]
    assert wb_collections
    assert all(
        item.payload["rowPersistence"]["status"] == "file_authoritative"
        for item in wb_collections
    )


def test_daily_refresh_materializes_daily_facts_when_enabled(
    tmp_path: Path,
    monkeypatch,
) -> None:
    seen: dict[str, object] = {}
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.marketplace_daily_facts_enabled = True
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_builder_should_not_run,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )

        def materialize(_db, refresh_run, **paths):
            seen["daily_facts_run_id"] = refresh_run.id
            seen["daily_facts_wb_dir"] = paths["wb_finance_dir"]

        monkeypatch.setattr(service, "_materialize_wb_daily_facts", materialize)
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="daily",
            user=user,
            source_report=report,
        )

    assert payload["status"] == "needs_review"
    assert seen["daily_facts_run_id"] == payload["id"]
    assert Path(seen["daily_facts_wb_dir"]).name == "wb_finance"


def test_incremental_refresh_uses_28_day_window_and_requires_full_base(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.source_refresh_incremental_enabled = True
    settings.marketplace_daily_facts_enabled = True
    settings.db_first_reports_enabled = True
    monkeypatch.setattr(
        source_refresh,
        "_incremental_yesterday",
        lambda: date(2026, 6, 17),
    )
    service = SourceRefreshService(settings)
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        refresh_run = service._create_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="incremental",
            credential_source="tenant",
            dry_run=False,
            user=user,
            source_report=report,
            reason="incremental test",
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 2),
            resume_mode="never",
            resume_from_run_id=None,
        )
        assert isinstance(refresh_run, SourceRefreshRun)
        assert refresh_run.source_window_start == date(2026, 5, 21)
        assert refresh_run.source_window_end == date(2026, 6, 17)
        assert refresh_run.period_start == report.period_start
        assert refresh_run.period_end == date(2026, 6, 17)

        payload = service._execute_run(db, refresh_run, user=user)

    assert payload["status"] == "needs_full_refresh"
    assert payload["failureCode"] == "incremental_base_unavailable"


def test_incremental_refresh_requires_db_first_reports(tmp_path: Path) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.source_refresh_incremental_enabled = True
    settings.marketplace_daily_facts_enabled = True
    settings.db_first_reports_enabled = False
    service = SourceRefreshService(settings)
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        with pytest.raises(
            source_refresh.SourceRefreshConfigError,
            match="DB_FIRST_REPORTS_ENABLED",
        ):
            service._create_refresh_run(
                db,
                tenant_id=report.tenant_id,
                client_id=report.client_id,
                mode="incremental",
                credential_source="tenant",
                dry_run=False,
                user=user,
                source_report=report,
                reason="incremental test",
                period_start=report.period_start,
                period_end=date(2026, 6, 17),
                resume_mode="never",
                resume_from_run_id=None,
            )


def test_logistics_master_flag_requires_db_first_before_refresh(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.logistics_analysis_enabled = True
    settings.db_first_reports_enabled = False
    service = SourceRefreshService(settings)

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        payload = service.run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            user=user,
            source_report=report,
            reason="logistics config gate",
            period_start=report.period_start,
            period_end=report.period_end,
            resume_mode="never",
            resume_from_run_id=None,
        )

    assert payload["status"] == "needs_configuration"
    assert payload["failureCode"] == "logistics_requires_db_first"
    assert payload["collections"] == []


def test_incremental_refresh_reuses_valid_full_daily_facts_base(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.source_refresh_incremental_enabled = True
    settings.marketplace_daily_facts_enabled = True
    settings.db_first_reports_enabled = True
    monkeypatch.setattr(
        source_refresh,
        "_incremental_yesterday",
        lambda: date(2026, 6, 17),
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        base_root = settings.source_refresh_root_path / "full-incremental-base"
        finance_dir = base_root / "wb_finance"
        finance_dir.mkdir(parents=True)
        (finance_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "results": [
                        {
                            "seller_account_id": "WB_ACCOUNT_9",
                            "status": "no_data",
                            "page_index": 1,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        base = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="full-incremental-base",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            source_report=report,
            reason="full base",
        )
        repository.update_source_refresh_run(
            db,
            base,
            status="report_created",
            root_dir=str(base_root),
            finished_at=datetime.now().astimezone(),
        )
        finance_collection = repository.add_source_refresh_collection(
            db,
            base,
            source_type="wb_finance_detail",
            source_label="WB finance",
            required=True,
            status="loaded",
            snapshot_hash="wb-base-hash",
            raw_path=str(finance_dir),
            payload={
                "sourceCoverageStart": report.period_start.isoformat(),
                "sourceCoverageEnd": report.period_end.isoformat(),
                "dailyFacts": {
                    "status": "materialized",
                    "parity": {"status": "aggregate_only"},
                    "persistedParity": {"status": "matched"},
                },
            },
        )
        repository.add_source_refresh_collection(
            db,
            base,
            source_type="wb_product_cards",
            source_label="WB cards",
            required=True,
            status="loaded",
            snapshot_hash="cards-base-hash",
        )
        repository.replace_marketplace_finance_daily_facts(
            db,
            base,
            [
                MarketplaceFinanceDailyFact(
                    client_id=report.client_id,
                    seller_account_id="WB_ACCOUNT_9",
                    organization_id="1C_ORG_1",
                    fact_date=report.period_start,
                    marketplace_report_id="WB-BASE",
                    document_kind="commissioner_report",
                    source_row_count=1,
                    source_hash_digest="base-fact-hash",
                    methodology_version=source_refresh.METHODOLOGY_VERSION,
                )
            ],
            marketplace="wb",
        )
        db.commit()

        service = SourceRefreshService(settings)
        refresh_run = service._create_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="incremental",
            credential_source="tenant",
            dry_run=False,
            user=user,
            source_report=report,
            reason="incremental",
            period_start=None,
            period_end=None,
            resume_mode="never",
            resume_from_run_id=None,
        )
        finance_collection.payload = {
            **finance_collection.payload,
            "sourceCoverageStart": (
                report.period_start + timedelta(days=1)
            ).isoformat(),
        }
        coverage_issue = service._daily_facts_coverage_issue(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            period_start=report.period_start,
            period_end=report.period_start,
        )

    assert isinstance(refresh_run, SourceRefreshRun)
    assert refresh_run.mode == "incremental"
    assert refresh_run.base_source_refresh_run_id == base.id
    assert coverage_issue == (
        f"daily_facts_coverage_gap:{report.period_start.isoformat()}"
    )


def test_incremental_materialization_uses_exact_window_and_report_boundaries(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    captured: dict[str, object] = {}
    import scripts.rebuild_report_from_sources as rebuild

    monkeypatch.setattr(
        source_refresh,
        "_reverify_collection_raw_integrity",
        lambda *_args, **_kwargs: None,
    )

    def fake_build(args, **_kwargs):
        captured["args"] = args
        return {"daily_facts": []}

    monkeypatch.setattr(rebuild, "build_db_first_payload", fake_build)

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        base = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="full-materialization-context",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            source_report=report,
            reason="base",
        )
        repository.update_source_refresh_run(
            db,
            base,
            status="report_created",
            finished_at=datetime.now().astimezone(),
        )
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="incremental",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="incremental-materialization-context",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            source_report=report,
            reason="incremental",
        )
        refresh_run.base_source_refresh_run_id = base.id
        refresh_run.source_window_start = date(2026, 5, 21)
        refresh_run.source_window_end = date(2026, 6, 17)
        expected_period_start = date(2026, 5, 18)
        expected_period_end = date(2026, 6, 21)
        current_summary = SimpleNamespace(
            seller_account_id="seller",
            report_id="current-summary",
            date_from=date(2026, 6, 12),
            date_to=date(2026, 6, 17),
            create_date=date(2026, 6, 18),
        )
        service = SourceRefreshService(settings)
        monkeypatch.setattr(
            service,
            "_incremental_wb_summary_rows",
            lambda *_args, **_kwargs: [current_summary],
        )
        monkeypatch.setattr(
            service,
            "_calculation_sku_mappings",
            lambda *_args, **_kwargs: [],
        )

        def fake_save(*_args, **kwargs):
            captured["save_kwargs"] = kwargs

        monkeypatch.setattr(service, "_save_wb_daily_facts", fake_save)
        service._materialize_wb_daily_facts(
            db,
            refresh_run,
            wb_finance_dir=tmp_path,
            onec_dir=tmp_path,
            wb_report_list_dir=tmp_path,
            wb_cards_dir=tmp_path,
            wb_stock_history_dir=tmp_path,
        )

    args = captured["args"]
    assert args.report_period_start == expected_period_start
    assert args.report_period_end == expected_period_end
    assert args.wb_sales_report_summary_rows == [current_summary]
    assert captured["save_kwargs"]["replacement_summary_rows"] == [current_summary]


def test_daily_facts_report_selection_includes_opening_partial_week(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="incremental",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="opening-partial-week",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 17),
            user=user,
            source_report=report,
            reason="opening partial week",
        )
        facts = [
            MarketplaceFinanceDailyFact(
                client_id=report.client_id,
                seller_account_id="seller",
                organization_id="org",
                fact_date=fact_date,
                marketplace_report_id=f"report-{fact_date.isoformat()}",
                document_kind="commissioner_report",
                source_row_count=1,
                source_hash_digest=str(index) * 64,
                methodology_version="test-v1",
            )
            for index, fact_date in enumerate(
                (date(2026, 2, 22), date(2026, 2, 23), date(2026, 3, 1)),
                start=1,
            )
        ]
        repository.replace_marketplace_finance_daily_facts(
            db,
            refresh_run,
            facts,
            marketplace="wb",
            coverage_start=date(2026, 2, 22),
            coverage_end=date(2026, 6, 17),
        )
        selected = SourceRefreshService(settings)._daily_facts_for_report(
            db,
            refresh_run,
        )

    assert [item.fact_date for item in selected] == [
        date(2026, 2, 23),
        date(2026, 3, 1),
    ]


def test_large_onec_snapshot_stays_file_authoritative(tmp_path: Path) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    output_path = tmp_path / "large-onec.raw.json"
    with output_path.open("wb") as handle:
        handle.seek(ONEC_DATABASE_ROW_PERSIST_MAX_BYTES)
        handle.write(b"\n")

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="onec-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="large-onec-test",
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            user=user,
            source_report=report,
        )
        collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="onec_sales_register",
            source_label="AccumulationRegister_Продажи",
            required=True,
            status="loaded",
            row_count=87,
            raw_path=str(output_path),
        )
        result = OnecSampleExportResult(
            sample_id="sales_register",
            collection_name="AccumulationRegister_Продажи",
            ok=True,
            row_count=87,
            output_path=output_path,
        )

        _persist_onec_rows(db, collection, result)
        persisted_count = (
            db.query(SourceSnapshotRow).filter_by(collection_id=collection.id).count()
        )

    assert persisted_count == 0
    assert collection.payload["rowPersistence"] == {
        "status": "skipped_large_snapshot",
        "limitBytes": ONEC_DATABASE_ROW_PERSIST_MAX_BYTES,
        "byteSize": ONEC_DATABASE_ROW_PERSIST_MAX_BYTES + 1,
        "rawFilesAuthoritative": True,
    }


def test_large_commissioner_snapshot_persists_compact_financial_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    output_path = tmp_path / "commissioner-reports.raw.json"
    output_path.write_text(
        json.dumps(
            {
                "value": [
                    {
                        "Ref_Key": "report-1",
                        "Date": "2026-04-30T12:00:00",
                        "Number": "НФНФ-000011",
                        "Комментарий": "Ozon, отчет 123",
                        "Организация_Key": "organization-1",
                        "Контрагент_Key": "ozon-counterparty",
                        "Запасы": [
                            {
                                "Номенклатура_Key": "item-1",
                                "Количество": 2,
                                "Всего": 300,
                                "СуммаНДС": 50,
                                "НенужноеПоле": "не сохранять",
                            }
                        ],
                        "ЗапасыВозвраты": [],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(source_refresh, "ONEC_DATABASE_ROW_PERSIST_MAX_BYTES", 1)

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="ozon-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="large-commissioner-test",
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            user=user,
            source_report=report,
        )
        collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="onec_commissioner_reports",
            source_label="Document_ОтчетКомиссионера",
            required=False,
            publication_required=True,
            status="loaded",
            row_count=1,
            raw_path=str(output_path),
        )
        result = OnecSampleExportResult(
            sample_id="commissioner_reports",
            collection_name="Document_ОтчетКомиссионера",
            ok=True,
            row_count=1,
            output_path=output_path,
        )

        _persist_onec_rows(db, collection, result)
        persisted = (
            db.query(SourceSnapshotRow).filter_by(collection_id=collection.id).one()
        )

    assert collection.payload["rowPersistence"]["status"] == (
        "compacted_large_snapshot"
    )
    assert collection.payload["rowPersistence"]["persistedDocumentRows"] == 1
    assert persisted.row_payload["Запасы"][0] == {
        "Номенклатура_Key": "item-1",
        "Количество": 2,
        "Всего": 300,
        "СуммаНДС": 50,
    }
    assert "НенужноеПоле" not in persisted.row_payload["Запасы"][0]


def test_source_refresh_collects_optional_ozon_finance_without_blocking_wb(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.source_refresh_ozon_request_delay_seconds = 0
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        ozon_secret = (
            '{"clientId":"ozon-client","apiKey":"ozon-key",'
            '"sellerAccountId":"OZON_ACCOUNT_1","accountName":"Ozon кабинет"}'
        )
        repository.save_tenant_integration(
            db,
            user=user,
            tenant_id="shumeyko",
            provider="ozon_api",
            secret=ozon_secret,
            secret_storage=integrations.secret_storage_payload(
                settings,
                ozon_secret,
            ).payload,
        )
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            ozon_cash_flow_exporter=_fake_ozon_cash_flow_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_builder_should_not_run,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="daily",
            user=user,
            source_report=report,
        )
        ozon_collection = (
            db.query(SourceRefreshCollection)
            .filter_by(source_type="ozon_finance_cash_flow")
            .one()
        )
        ozon_rows = (
            db.query(SourceSnapshotRow)
            .filter_by(source_type="ozon_finance_cash_flow")
            .all()
        )

    assert payload["status"] == "needs_review"
    assert seen["ozon_client_id"] == "ozon-client"
    assert seen["ozon_api_key"] == "ozon-key"
    assert ozon_collection.required is False
    assert ozon_collection.status == "loaded"
    assert ozon_collection.payload["marketplace"] == "ozon"
    assert ozon_collection.payload["results"][0]["sourceEndpoint"] == (
        "/v1/finance/cash-flow-statement/list"
    )
    assert len(ozon_rows) == 1
    assert ozon_rows[0].source_row_id == "op-ozon-1"
    assert ozon_rows[0].row_payload["marketplace"] == "ozon"
    assert ozon_rows[0].row_payload["offer_id"] == "A-1"


def test_ozon_realization_defers_and_atomically_promotes_typed_operation_facts(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.source_refresh_raw_db_mode = "legacy"
    settings.marketplace_daily_facts_enabled = True
    settings.source_refresh_ozon_typed_facts_enabled = True
    output_dir = Path(settings.source_refresh_root) / "run" / "ozon_realization"
    output_dir.mkdir(parents=True)
    output_path = output_dir / "realization.raw.json"
    output_path.write_text(
        json.dumps(
            {
                "rows": [
                    {
                        "operation_id": "operation-1",
                        "date": "2026-07-05",
                        "items": [
                            {
                                "product_id": "product-1",
                                "offer_id": "offer-1",
                                "sku": "sku-1",
                                "quantity": 2,
                                "sale_amount": 500,
                                "commission": 50,
                                "logistics": 20,
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    raw_payload = json.loads(output_path.read_text(encoding="utf-8"))
    raw_hash = hashlib.sha256(
        json.dumps(
            raw_payload,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "sourceType": "ozon_realization",
                        "sellerAccountId": "OZON_ACCOUNT_1",
                        "accountName": "Ozon",
                        "pageIndex": 1,
                        "status": "ok",
                        "ok": True,
                        "rowCount": 1,
                        "statusCode": 200,
                        "sourceEndpoint": "/v1/finance/realization",
                        "rawPayloadHash": raw_hash,
                        "outputFile": output_path.name,
                        "reportCode": "",
                        "error": "",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode="ozon-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="ozon-files-only",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            user=user,
            source_report=report,
            reason="test",
        )
        service = SourceRefreshService(settings)
        service._record_ozon_results(
            db,
            refresh_run,
            output_dir,
            [
                OzonPageResult(
                    source_type="ozon_realization",
                    seller_account_id="OZON_ACCOUNT_1",
                    account_name="Ozon",
                    page_index=1,
                    ok=True,
                    status="ok",
                    row_count=1,
                    raw_payload_hash=raw_hash,
                    output_path=output_path,
                    status_code=200,
                    source_endpoint="/v1/finance/realization",
                )
            ],
            source_type="ozon_realization",
            source_label="Ozon realization",
            ozon_cabinet_ids={"OZON_ACCOUNT_1": "ozon-cabinet"},
        )
        assert (
            db.query(MarketplaceOperationFact)
            .filter_by(source_refresh_run_id=refresh_run.id)
            .count()
            == 0
        )
        assert service._promote_ozon_typed_facts(
            db,
            refresh_run,
            ozon_cabinet_ids={"OZON_ACCOUNT_1": "ozon-cabinet"},
        )
        db.commit()
        collection = (
            db.query(SourceRefreshCollection)
            .filter_by(
                refresh_run_id=refresh_run.id,
                source_type="ozon_realization",
            )
            .one()
        )
        raw_count = (
            db.query(SourceSnapshotRow).filter_by(collection_id=collection.id).count()
        )
        facts = (
            db.query(MarketplaceOperationFact)
            .filter_by(source_refresh_run_id=refresh_run.id)
            .all()
        )
        adapted = repository._ozon_realization_source_rows(
            db,
            tenant_id=refresh_run.tenant_id,
            refresh_run=refresh_run,
            limit=50,
            prefer_typed=True,
        )

    assert collection.payload["typedParity"]["status"] == "pending_diagnostics"
    assert raw_count == 1
    assert len(facts) == 3
    assert {item.service_key for item in facts} == {
        "product",
        "commission",
        "logistics",
    }
    product_fact = next(item for item in facts if item.service_key == "product")
    assert product_fact.amount == Decimal("500.00")
    assert adapted[0].row_payload["commission"] == Decimal("50.00")
    assert adapted[0].row_payload["logistics"] == Decimal("20.00")
    assert adapted[0].row_payload["offer_id"] == "offer-1"


def test_ozon_files_only_is_blocked_without_full_legacy_qualification(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.source_refresh_raw_db_mode = "files_only"
    settings.marketplace_daily_facts_enabled = True
    settings.source_refresh_ozon_typed_facts_enabled = True
    settings.source_refresh_ozon_files_only_enabled = True
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode="ozon-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="unqualified-files-only",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            user=user,
            source_report=report,
            reason="test",
        )

        with pytest.raises(
            source_refresh.SourceRefreshConfigError,
            match="full legacy qualification",
        ):
            SourceRefreshService(settings)._record_ozon_results(
                db,
                refresh_run,
                tmp_path,
                [],
                source_type="ozon_realization",
                source_label="Ozon realization",
                ozon_cabinet_ids={},
            )


def test_ozon_qualification_requires_promotable_run_and_same_sellers(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        previous = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode="ozon-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="qualified-legacy",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            user=user,
            source_report=report,
            reason="qualification",
        )
        collection = repository.add_source_refresh_collection(
            db,
            previous,
            source_type="ozon_realization",
            source_label="Ozon realization",
            required=False,
            status="loaded",
            row_count=1,
            payload={
                "results": [{"sellerAccountId": "seller-1"}],
                "rawIntegrity": {"status": "verified"},
                "typedParity": {
                    "status": "matched",
                    "diagnosticsParity": {"status": "matched"},
                    "persistenceParity": {"status": "matched"},
                    "legacyFileParity": {"status": "matched"},
                    "sourceCoverage": {"status": "matched"},
                },
            },
        )
        repository.update_source_refresh_run(
            db,
            previous,
            status="needs_review",
            finished_at=datetime(2026, 7, 20, 12, 0),
        )
        current = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode="ozon-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="files-only-current",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 7, 31),
            user=user,
            source_report=report,
            reason="files only",
        )
        service = SourceRefreshService(settings)

        matched = service._ozon_qualification_run_id(
            db,
            current,
            source_type="ozon_realization",
            seller_account_ids={"seller-1"},
        )
        changed_seller = service._ozon_qualification_run_id(
            db,
            current,
            source_type="ozon_realization",
            seller_account_ids={"seller-2"},
        )
        collection.status = "partial_source"
        partial = service._ozon_qualification_run_id(
            db,
            current,
            source_type="ozon_realization",
            seller_account_ids={"seller-1"},
        )

    assert matched == previous.id
    assert changed_seller == ""
    assert partial == ""


def test_ozon_typed_keys_do_not_depend_on_source_row_order(tmp_path: Path) -> None:
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    first_rows = [
        {"operation_id": "op-1", "product_id": "p-1", "amount": 10},
        {"operation_id": "op-2", "product_id": "p-2", "amount": 20},
    ]
    first_path.write_text(json.dumps(first_rows), encoding="utf-8")
    second_path.write_text(json.dumps(list(reversed(first_rows))), encoding="utf-8")

    def result(path: Path) -> OzonPageResult:
        return OzonPageResult(
            source_type="ozon_finance_cash_flow",
            seller_account_id="seller",
            account_name="Ozon",
            page_index=1,
            ok=True,
            status="ok",
            row_count=2,
            raw_payload_hash="hash",
            output_path=path,
            source_endpoint="/finance",
        )

    first_keys = {
        item["source_key"]
        for item in source_refresh._iter_ozon_operation_facts(
            [result(first_path)],
            ozon_cabinet_ids={"seller": "cabinet"},
        )
    }
    second_keys = {
        item["source_key"]
        for item in source_refresh._iter_ozon_operation_facts(
            [result(second_path)],
            ozon_cabinet_ids={"seller": "cabinet"},
        )
    }

    assert first_keys == second_keys


def test_ozon_typed_fallback_keys_use_payload_not_row_position(
    tmp_path: Path,
) -> None:
    first_path = tmp_path / "first-anonymous.json"
    second_path = tmp_path / "second-anonymous.json"
    rows = [
        {"operation_type": "service-a", "amount": 10},
        {"operation_type": "service-b", "amount": 20},
    ]
    first_path.write_text(json.dumps(rows), encoding="utf-8")
    second_path.write_text(json.dumps(list(reversed(rows))), encoding="utf-8")

    def result(path: Path) -> OzonPageResult:
        return OzonPageResult(
            source_type="ozon_mutual_settlement_file",
            seller_account_id="seller",
            account_name="Ozon",
            page_index=1,
            ok=True,
            status="ok",
            row_count=2,
            raw_payload_hash="hash",
            output_path=path,
            source_endpoint="report_file",
        )

    first_keys = {
        item["source_key"]
        for item in source_refresh._iter_ozon_operation_facts(
            [result(first_path)],
            ozon_cabinet_ids={"seller": "cabinet"},
        )
    }
    second_keys = {
        item["source_key"]
        for item in source_refresh._iter_ozon_operation_facts(
            [result(second_path)],
            ozon_cabinet_ids={"seller": "cabinet"},
        )
    }

    assert first_keys == second_keys


def test_ozon_typed_fallback_preserves_dates_duplicates_and_client_scope(
    tmp_path: Path,
) -> None:
    path = tmp_path / "anonymous-operations.json"
    path.write_text(
        json.dumps(
            [
                {"operation_type": "service", "date": "2026-06-01", "amount": 10},
                {"operation_type": "service", "date": "2026-06-02", "amount": 10},
                {"operation_type": "service", "date": "2026-06-02", "amount": 10},
            ]
        ),
        encoding="utf-8",
    )
    result = OzonPageResult(
        source_type="ozon_b2b_sales_json",
        seller_account_id="seller",
        account_name="Ozon",
        page_index=1,
        ok=True,
        status="ok",
        row_count=3,
        output_path=path,
        source_endpoint="/v1/finance/document-b2b-sales/json",
    )
    first_client = source_refresh._merge_ozon_operation_facts(
        list(
            source_refresh._iter_ozon_operation_facts(
                [result],
                ozon_cabinet_ids={"seller": "cabinet"},
                client_id="client-1",
            )
        )
    )
    second_client = source_refresh._merge_ozon_operation_facts(
        list(
            source_refresh._iter_ozon_operation_facts(
                [result],
                ozon_cabinet_ids={"seller": "cabinet"},
                client_id="client-2",
            )
        )
    )

    assert len(first_client) == 3
    assert len({item["source_key"] for item in first_client}) == 3
    assert {item["operation_date"] for item in first_client} == {
        date(2026, 6, 1),
        date(2026, 6, 2),
    }
    assert {item["source_key"] for item in first_client}.isdisjoint(
        item["source_key"] for item in second_client
    )


def test_ozon_typed_cash_flow_flattens_period_rows(tmp_path: Path) -> None:
    path = tmp_path / "cash-flow.json"
    path.write_text(
        json.dumps(
            {
                "result": {
                    "cash_flows": [
                        {
                            "period": "2026-06-01",
                            "orders_amount": 100,
                            "returns_amount": 10,
                            "commission_amount": 5,
                        },
                        {
                            "period": "2026-07-01",
                            "orders_amount": 200,
                            "returns_amount": 20,
                            "commission_amount": 10,
                        },
                    ],
                    "details": [],
                }
            }
        ),
        encoding="utf-8",
    )
    result = OzonPageResult(
        source_type="ozon_finance_cash_flow",
        seller_account_id="seller",
        account_name="Ozon",
        page_index=1,
        ok=True,
        status="ok",
        row_count=2,
        raw_payload_hash="hash",
        output_path=path,
        source_endpoint="/v1/finance/cash-flow-statement/list",
    )

    assert len(_read_ozon_rows(path)) == 2

    facts = list(
        source_refresh._iter_ozon_operation_facts(
            [result],
            ozon_cabinet_ids={"seller": "cabinet"},
        )
    )

    assert len(facts) == 2
    assert len({item["source_key"] for item in facts}) == 2
    assert sum((item["amount"] for item in facts), Decimal("0")) == Decimal("270")


def test_ozon_typed_realization_reads_nested_sale_amount(tmp_path: Path) -> None:
    path = tmp_path / "realization-nested.json"
    path.write_text(
        json.dumps(
            {
                "result": {
                    "rows": [
                        {
                            "item": {"offer_id": "offer-1", "sku": "sku-1"},
                            "delivery_commission": {"quantity": 2, "amount": 1000},
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    result = OzonPageResult(
        source_type="ozon_realization",
        seller_account_id="seller",
        account_name="Ozon",
        page_index=1,
        ok=True,
        status="ok",
        row_count=1,
        raw_payload_hash="hash",
        output_path=path,
        source_endpoint="/v2/finance/realization",
    )

    facts = list(
        source_refresh._iter_ozon_operation_facts(
            [result],
            ozon_cabinet_ids={"seller": "cabinet"},
        )
    )

    assert len(facts) == 1
    assert facts[0]["quantity"] == Decimal("2")
    assert facts[0]["amount"] == Decimal("1000")


def test_source_refresh_ozon_only_skips_wb_and_creates_staff_draft(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.source_refresh_ozon_request_delay_seconds = 0
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        onec_secret = _onec_secret()
        repository.save_tenant_integration(
            db,
            user=user,
            tenant_id="shumeyko",
            provider="onec_readonly",
            secret=onec_secret,
            secret_storage=integrations.secret_storage_payload(
                settings,
                onec_secret,
            ).payload,
        )
        ozon_secret = (
            '{"clientId":"ozon-client","apiKey":"ozon-key",'
            '"sellerAccountId":"OZON_ACCOUNT_1","accountName":"Ozon кабинет"}'
        )
        repository.save_tenant_integration(
            db,
            user=user,
            tenant_id="shumeyko",
            provider="ozon_api",
            secret=ozon_secret,
            secret_storage=integrations.secret_storage_payload(
                settings,
                ozon_secret,
            ).payload,
        )
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_builder_should_not_run,
            ozon_cash_flow_exporter=_fake_ozon_cash_flow_exporter(seen),
            ozon_realization_exporter=_fake_ozon_realization_exporter(seen),
            ozon_realization_posting_exporter=_fake_ozon_extra_exporter(
                seen,
                source_type="ozon_realization_posting",
                seen_key="ozon_realization_posting_client_id",
                endpoint="/v1/finance/realization/posting",
            ),
            ozon_products_buyout_exporter=_fake_ozon_extra_exporter(
                seen,
                source_type="ozon_products_buyout",
                seen_key="ozon_products_buyout_client_id",
                endpoint="/v1/finance/products/buyout",
            ),
            ozon_b2b_sales_exporter=_fake_ozon_extra_exporter(
                seen,
                source_type="ozon_b2b_sales_json",
                seen_key="ozon_b2b_sales_client_id",
                endpoint="/v1/finance/document-b2b-sales/json",
            ),
            ozon_mutual_settlement_exporter=_fake_ozon_extra_exporter(
                seen,
                source_type="ozon_mutual_settlement",
                seen_key="ozon_mutual_settlement_client_id",
                endpoint="/v1/finance/mutual-settlement",
            ),
            ozon_products_exporter=_fake_ozon_products_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_builder_should_not_run,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="ozon-only",
            user=user,
            source_report=report,
        )
        refresh_run = db.get(SourceRefreshRun, payload["id"])
        assert refresh_run is not None
        repeated_draft = repository.materialize_ozon_draft_report(
            db,
            refresh_run,
            user=user,
        )
        reports = db.query(ReportRun).filter_by(tenant_id="shumeyko").all()
        ozon_collection = (
            db.query(SourceRefreshCollection)
            .filter_by(source_type="ozon_finance_cash_flow")
            .one()
        )
        ozon_products = (
            db.query(SourceRefreshCollection)
            .filter_by(source_type="ozon_products_report")
            .one()
        )
        ozon_realization = (
            db.query(SourceRefreshCollection)
            .filter_by(source_type="ozon_realization")
            .one()
        )
        ozon_realization_row = (
            db.query(SourceSnapshotRow)
            .filter_by(collection_id=ozon_realization.id)
            .one()
        )
        ozon_extra = {
            item.source_type: item
            for item in db.query(SourceRefreshCollection)
            .filter(SourceRefreshCollection.source_type.like("ozon_%"))
            .all()
        }

    assert payload["status"] == "needs_review"
    assert payload["newReportRunId"].startswith("ozon_draft_")
    draft = next(item for item in reports if item.id == payload["newReportRunId"])
    assert draft.publication_status == "draft"
    assert draft.is_current is False
    assert draft.lineage_type == repository.OZON_DRAFT_LINEAGE_TYPE
    assert repeated_draft.id == draft.id
    assert {item.id for item in reports} == {"report-1", draft.id}
    assert seen["ozon_client_id"] == "ozon-client"
    assert "wb_api_key" not in seen
    assert ozon_collection.required is True
    assert ozon_collection.status == "loaded"
    assert seen["ozon_realization_client_id"] == "ozon-client"
    assert ozon_realization.required is False
    assert ozon_realization.status == "loaded"
    assert ozon_realization_row.row_payload["seller_account_id"] == "OZON_ACCOUNT_1"
    assert ozon_realization_row.row_payload["source_page_index"] == 1
    assert seen["ozon_realization_posting_client_id"] == "ozon-client"
    assert seen["ozon_products_buyout_client_id"] == "ozon-client"
    assert seen["ozon_b2b_sales_client_id"] == "ozon-client"
    assert seen["ozon_mutual_settlement_client_id"] == "ozon-client"
    assert ozon_extra["ozon_realization_posting"].status == "loaded"
    assert ozon_extra["ozon_products_buyout"].status == "loaded"
    assert ozon_extra["ozon_b2b_sales_json"].status == "loaded"
    assert ozon_extra["ozon_mutual_settlement"].status == "loaded"
    assert ozon_products.required is False
    assert ozon_products.status == "loaded"
    assert "wb_api" not in {item["sourceType"] for item in payload["collections"]}


def test_read_ozon_rows_handles_xlsx_report_with_csv_suffix(tmp_path: Path) -> None:
    path = tmp_path / "ozon-mutual-file.raw.csv"
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["operation_type", "amount"])
    sheet.append(["MarketplaceServiceCostPerClick", -100])
    workbook.save(path)
    workbook.close()

    rows = _read_ozon_rows(path)

    assert rows == [
        {
            "operation_type": "MarketplaceServiceCostPerClick",
            "amount": "-100",
        }
    ]


def test_ozon_report_control_results_are_not_product_rows() -> None:
    base = {
        "seller_account_id": "OZON_ACCOUNT_1",
        "account_name": "Ozon",
        "page_index": 1,
        "ok": True,
        "status": "ok",
        "row_count": 1,
        "status_code": 200,
    }

    assert _is_ozon_report_control_result(
        OzonPageResult(
            source_type="ozon_products_report",
            source_endpoint="/v1/report/products/create",
            **base,
        )
    )
    assert _is_ozon_report_control_result(
        OzonPageResult(
            source_type="ozon_products_report_info",
            source_endpoint="/v1/report/info",
            **base,
        )
    )
    assert not _is_ozon_report_control_result(
        OzonPageResult(
            source_type="ozon_products_report_file",
            source_endpoint="report_file",
            **base,
        )
    )
    assert _is_ozon_report_control_result(
        OzonPageResult(
            source_type="ozon_mutual_settlement",
            source_endpoint="/v1/finance/mutual-settlement",
            **base,
        )
    )


def test_ozon_report_without_file_needs_review() -> None:
    base = {
        "seller_account_id": "OZON_ACCOUNT_1",
        "account_name": "Ozon",
        "page_index": 1,
        "ok": True,
        "status": "ok",
        "row_count": 1,
        "status_code": 200,
    }
    results = [
        OzonPageResult(
            source_type="ozon_products_report",
            source_endpoint="/v1/report/products/create",
            **base,
        ),
        OzonPageResult(
            source_type="ozon_products_report_info",
            source_endpoint="/v1/report/info",
            **base,
        ),
    ]
    payload_items = [{"status": "loaded"}, {"status": "loaded"}]

    status = _ozon_collection_status(
        results,
        payload_items,
        row_count=0,
        required=False,
    )

    assert status == "needs_review"


def test_ozon_report_collection_marks_one_lost_month_partial() -> None:
    base = {
        "seller_account_id": "OZON_ACCOUNT_1",
        "account_name": "Ozon",
        "page_index": 1,
        "status_code": 200,
    }
    results = [
        OzonPageResult(
            source_type="ozon_mutual_settlement_info",
            source_endpoint="/v1/report/info",
            ok=True,
            status="ok",
            row_count=0,
            **base,
        ),
        OzonPageResult(
            source_type="ozon_mutual_settlement_file",
            source_endpoint="report_file",
            ok=True,
            status="ok",
            row_count=10,
            **base,
        ),
        OzonPageResult(
            source_type="ozon_mutual_settlement_info",
            source_endpoint="/v1/report/info",
            ok=False,
            status="report_timeout",
            row_count=0,
            **base,
        ),
    ]
    payload_items = [
        {"status": "empty_expected"},
        {"status": "loaded"},
        {"status": "partial_source"},
    ]

    optional_status = _ozon_collection_status(
        results,
        payload_items,
        row_count=10,
        required=False,
    )
    required_status = _ozon_collection_status(
        results,
        payload_items,
        row_count=10,
        required=True,
    )

    assert optional_status == "needs_review"
    assert required_status == "partial_source"


def test_source_refresh_uses_all_finance_role_wb_integrations(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )

    def save_wb(provider: str, secret: str, *, role: str, cabinet_name: str) -> None:
        repository.save_tenant_integration(
            db,
            user=user,
            tenant_id="shumeyko",
            provider=provider,
            secret=secret,
            label=cabinet_name,
            connection_role=role,
            cabinet_name=cabinet_name,
            secret_storage=integrations.secret_storage_payload(
                settings,
                secret,
            ).payload,
        )

    def fake_wb_finance_exporter(settings, output_dir: Path, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        seen["finance_accounts"] = [
            (item.seller_account_id, item.account_name) for item in settings.accounts
        ]
        results = []
        for index, account in enumerate(settings.accounts, start=1):
            output_path = output_dir / f"account_{index}.raw.json"
            output_path.write_text(
                json.dumps(
                    [{"rrdId": index, "srid": f"srid-{index}"}],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            results.append(
                WbFinancePageResult(
                    seller_account_id=account.seller_account_id,
                    account_name=account.account_name,
                    page_index=1,
                    ok=True,
                    status="ok",
                    row_count=1,
                    rrd_id_start=0,
                    rrd_id_next=0,
                    raw_payload_hash=f"wb-hash-{index}",
                    output_path=output_path,
                    status_code=200,
                )
            )
        return results

    def fake_report_list_exporter(settings, output_dir: Path, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        seen["report_list_accounts"] = [
            (item.seller_account_id, item.account_name) for item in settings.accounts
        ]
        results = []
        for index, account in enumerate(settings.accounts, start=1):
            output_path = output_dir / f"report_list_{index}.raw.json"
            output_path.write_text(
                json.dumps(
                    [{"reportId": index, "realizationreport_id": index}],
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            results.append(
                WbSalesReportListPageResult(
                    seller_account_id=account.seller_account_id,
                    account_name=account.account_name,
                    page_index=1,
                    ok=True,
                    status="ok",
                    row_count=1,
                    offset=0,
                    raw_payload_hash=f"report-list-hash-{index}",
                    output_path=output_path,
                    status_code=200,
                )
            )
        return results

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        save_wb(
            "wb_api",
            "primary-token",
            role="finance_reports",
            cabinet_name="Основной кабинет",
        )
        save_wb(
            "wb_api:second",
            "second-token",
            role="finance_reports",
            cabinet_name="Второй кабинет",
        )
        save_wb(
            "wb_api:stock",
            "stock-token",
            role="analytics_stocks",
            cabinet_name="Остатки",
        )
        onec_secret = _onec_secret()
        repository.save_tenant_integration(
            db,
            user=user,
            tenant_id="shumeyko",
            provider="onec_readonly",
            secret=onec_secret,
            secret_storage=integrations.secret_storage_payload(
                settings,
                onec_secret,
            ).payload,
        )
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=fake_wb_finance_exporter,
            wb_report_list_exporter=fake_report_list_exporter,
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_fake_workbook_builder,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="full",
            user=user,
            source_report=report,
        )
        finance_collections = (
            db.query(SourceRefreshCollection)
            .filter_by(source_type="wb_finance_detail")
            .order_by(SourceRefreshCollection.id)
            .all()
        )
        report_list_collections = (
            db.query(SourceRefreshCollection)
            .filter_by(source_type="wb_sales_report_list")
            .order_by(SourceRefreshCollection.id)
            .all()
        )
        finance_rows = (
            db.query(SourceSnapshotRow)
            .filter_by(source_type="wb_finance_detail")
            .order_by(SourceSnapshotRow.id)
            .all()
        )
        cabinet_names = {
            item.display_name
            for item in db.query(WbCabinet).filter_by(client_id="shumeyko")
        }

    assert payload["status"] == "needs_review"
    assert seen["finance_accounts"] == [
        ("WB_ACCOUNT_1", "Основной кабинет"),
        ("WB_ACCOUNT_2", "Второй кабинет"),
    ]
    assert seen["report_list_accounts"] == seen["finance_accounts"]
    assert cabinet_names >= {"Основной кабинет", "Второй кабинет", "Остатки"}
    finance_cabinet_ids = {
        result["wbCabinetId"]
        for item in finance_collections
        for result in item.payload["results"]
    }
    report_list_cabinet_ids = {
        result["wbCabinetId"]
        for item in report_list_collections
        for result in item.payload["results"]
    }
    assert finance_cabinet_ids == report_list_cabinet_ids
    assert len(finance_cabinet_ids) == 2
    assert all(item.client_id == "shumeyko" for item in finance_collections)
    assert {item.client_id for item in finance_rows} == {"shumeyko"}
    assert {item.wb_cabinet_id for item in finance_rows} == finance_cabinet_ids


def test_wb_integration_reuses_existing_report_cabinet_by_name(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        existing = db.query(WbCabinet).filter_by(display_name="Кабинет A").one()
        repository.save_tenant_integration(
            db,
            user=user,
            tenant_id="shumeyko",
            provider="wb_api:second",
            secret="wb-token-secret",
            label="Кабинет A",
            connection_role="finance_reports",
            cabinet_name="Кабинет A",
            organization_name="Организация-дубль",
            secret_storage=integrations.secret_storage_payload(
                settings,
                "wb-token-secret",
            ).payload,
        )
        db.commit()
        integration = (
            db.query(repository.TenantIntegration)
            .filter_by(provider="wb_api:second")
            .one()
        )
        cabinets = db.query(WbCabinet).filter_by(display_name="Кабинет A").all()

    assert integration.config_payload["wbCabinetId"] == existing.id
    assert integration.config_payload["clientCompanyId"] == existing.client_company_id
    assert len(cabinets) == 1


def test_source_refresh_db_first_branch_keeps_staff_draft_and_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.rebuild_report_from_sources as rebuild_script

    seen: dict[str, object] = {}
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.db_first_reports_enabled = True

    def fake_build_db_first_payload(
        args,
        *,
        tax_profiles=None,
        input_vat_policies=None,
    ):
        seen["builder_used"] = True
        assert args.wb_finance_dir is not None
        assert args.onec_dir is not None
        assert args.wb_finance_source == "files-stream"
        assert args.keep_stream_cache is False
        assert args.sku_mappings is not None
        assert tax_profiles is not None
        assert len(tax_profiles) == 1
        assert tax_profiles[0].source == "manual_override"
        assert input_vat_policies == []
        seen["tax_profile_source"] = tax_profiles[0].source
        return {"payload": minimal_payload()}

    monkeypatch.setattr(
        rebuild_script,
        "build_db_first_payload",
        fake_build_db_first_payload,
    )
    monkeypatch.setattr(rebuild_script, "_validate_marts", lambda _payload: None)

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        company = (
            db.query(repository.ClientCompany)
            .filter_by(client_id="shumeyko", status="active")
            .order_by(repository.ClientCompany.id)
            .first()
        )
        assert company is not None
        company.onec_organization_id = "organizations-ref"
        repository.create_tax_profile_override(
            db,
            user=user,
            client_id="shumeyko",
            company_id=company.id,
            tax_system="ОСНО",
            vat_rate=Decimal("22"),
            vat_mode="included",
            vat_deduction_mode="allowed",
            revenue_tax_rate=Decimal("0"),
            income_tax_kind="ip_ndfl_progressive",
            valid_from=date(2026, 1, 1),
            valid_to=date(2026, 12, 31),
            reason="Подтверждено бухгалтером для теста",
        )
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_report_list_exporter=_fake_report_list_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_builder_should_not_run,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="full",
            user=user,
            source_report=report,
        )
        db.commit()
        new_report = db.get(ReportRun, payload["newReportRunId"])
        old_report = db.get(ReportRun, report.id)
        artifacts = (
            db.query(ReportArtifact)
            .filter_by(report_run_id=payload["newReportRunId"])
            .all()
        )
        source_loads = (
            db.query(SourceLoad)
            .filter_by(report_run_id=payload["newReportRunId"])
            .all()
        )
        tax_collection = (
            db.query(SourceRefreshCollection)
            .filter_by(
                refresh_run_id=payload["id"],
                source_type="onec_tax_profiles",
            )
            .one()
        )

    assert payload["status"] == "needs_review"
    assert seen["builder_used"] is True
    assert seen["tax_profile_source"] == "manual_override"
    assert tax_collection.status == "loaded"
    assert tax_collection.payload["profileCount"] == 1
    assert tax_collection.payload["sourceProfileCount"] == 0
    assert tax_collection.payload["manualOverrideCount"] == 1
    assert new_report is not None
    assert new_report.lineage_type == "db_first_report_marts"
    assert new_report.publication_status == "draft"
    assert new_report.is_current is False
    assert old_report is not None
    assert old_report.is_current is True
    assert source_loads
    assert all(item.source_refresh_run_id == payload["id"] for item in source_loads)
    assert "db_first_report_marts" not in {item.source_type for item in source_loads}
    artifact_types = {item.artifact_type for item in artifacts}
    assert artifact_types == {"excel"}
    assert all(Path(item.path).exists() for item in artifacts)
    assert all(item.sha256 for item in artifacts)


def test_split_pipeline_resumes_from_raw_to_marts_without_recollecting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.rebuild_report_from_sources as rebuild_script
    import scripts.run_source_refresh_export_task as export_task_script

    seen: dict[str, object] = {}
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.db_first_reports_enabled = True
    settings.source_refresh_task_queue_enabled = True
    settings.marketplace_daily_facts_enabled = False

    def fake_build_db_first_payload(
        args,
        *,
        tax_profiles=None,
        input_vat_policies=None,
    ):
        seen["build_calls"] = int(seen.get("build_calls") or 0) + 1
        assert args.wb_finance_source == "files-stream"
        assert tax_profiles is not None
        assert input_vat_policies == []
        return {"payload": minimal_payload()}

    monkeypatch.setattr(
        rebuild_script,
        "build_db_first_payload",
        fake_build_db_first_payload,
    )
    monkeypatch.setattr(rebuild_script, "_validate_marts", lambda _payload: None)

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_report_list_exporter=_fake_report_list_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_builder_should_not_run,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        queued = service.enqueue(
            db,
            tenant_id="shumeyko",
            mode="full",
            user=user,
            source_report=report,
        )
        refresh_run = db.get(SourceRefreshRun, queued["id"])
        assert refresh_run is not None
        repository.ensure_source_refresh_task_chain(db, refresh_run)
        db.commit()

        collector = repository.claim_next_source_refresh_task(
            db,
            worker_id="collector:test",
            allowed_task_types={"collect_sources"},
        )
        assert collector is not None
        db.commit()
        db.info["source_refresh_split_pipeline"] = True
        try:
            service.run_existing(
                db,
                refresh_run.id,
                worker_id="collector:test",
                stop_after_sources=True,
            )
        finally:
            db.info.pop("source_refresh_split_pipeline", None)

        db.refresh(refresh_run)
        db.refresh(collector)
        assert refresh_run.status == "source_loaded"
        assert collector.status == "succeeded"
        assert refresh_run.new_report_run_id is None

        materialize = repository.claim_next_source_refresh_task(
            db,
            worker_id="heavy:materialize",
            allowed_task_types={"materialize_facts"},
        )
        assert materialize is not None
        db.commit()
        service.run_split_materialize_task(
            db,
            materialize,
            worker_id="heavy:materialize",
        )

        build = repository.claim_next_source_refresh_task(
            db,
            worker_id="heavy:build",
            allowed_task_types={"build_report"},
        )
        assert build is not None
        db.commit()
        build_payload = service.run_split_build_report_task(
            db,
            build,
            worker_id="heavy:build",
        )
        assert build_payload["status"] == "rebuilding", (
            build_payload["failureCode"],
            build_payload["errorMessage"],
        )

        db.refresh(refresh_run)
        tasks = list(
            db.query(SourceRefreshTask)
            .filter_by(refresh_run_id=refresh_run.id)
            .order_by(SourceRefreshTask.created_at, SourceRefreshTask.id)
        )
        draft = db.get(ReportRun, refresh_run.new_report_run_id)
        artifacts = (
            db.query(ReportArtifact)
            .filter_by(report_run_id=refresh_run.new_report_run_id)
            .all()
        )
        assert artifacts == []
        monkeypatch.setattr(
            export_task_script,
            "_start_heartbeat_process",
            lambda *_args, **_kwargs: None,
        )
        monkeypatch.setattr(
            export_task_script,
            "_stop_heartbeat_process",
            lambda _process: None,
        )
        assert export_task_script.execute_one(db, settings) is True
        db.refresh(refresh_run)
        tasks = list(
            db.query(SourceRefreshTask)
            .filter_by(refresh_run_id=refresh_run.id)
            .order_by(SourceRefreshTask.created_at, SourceRefreshTask.id)
        )
        artifacts = (
            db.query(ReportArtifact)
            .filter_by(report_run_id=refresh_run.new_report_run_id)
            .all()
        )

    assert seen["build_calls"] == 1
    assert [item.status for item in tasks] == [
        "succeeded",
        "succeeded",
        "succeeded",
        "succeeded",
    ]
    assert draft is not None
    assert draft.publication_status == "draft"
    assert draft.is_current is False
    assert refresh_run.status == "needs_review"
    assert len(artifacts) == 1
    assert artifacts[0].artifact_type == "excel"
    assert Path(artifacts[0].path).is_file()


def test_source_refresh_db_first_post_build_failure_does_not_publish_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.rebuild_report_from_sources as rebuild_script

    seen: dict[str, object] = {}
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.db_first_reports_enabled = True

    def fake_build_db_first_payload(
        _args,
        *,
        tax_profiles=None,
        input_vat_policies=None,
    ):
        assert tax_profiles is not None
        assert input_vat_policies == []
        return {"payload": minimal_payload()}

    monkeypatch.setattr(
        rebuild_script,
        "build_db_first_payload",
        fake_build_db_first_payload,
    )
    monkeypatch.setattr(rebuild_script, "_validate_marts", lambda _payload: None)

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_report_list_exporter=_fake_report_list_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_builder_should_not_run,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )

        def fail_after_report_build(*_args, **_kwargs):
            raise RuntimeError("post build attach failed")

        monkeypatch.setattr(service, "_attach_source_loads", fail_after_report_build)
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="full",
            user=user,
            source_report=report,
        )
        db.commit()
        old_report = db.get(ReportRun, report.id)
        draft_reports = db.query(ReportRun).filter(ReportRun.id != report.id).all()

    assert payload["status"] == "failed"
    assert payload["newReportRunId"] is None
    assert payload["errorMessage"] == "RuntimeError: post build attach failed"
    assert old_report is not None
    assert old_report.is_current is True
    assert draft_reports
    assert all(item.publication_status == "draft" for item in draft_reports)
    assert all(item.is_current is False for item in draft_reports)


def test_source_refresh_tax_profiles_do_not_inherit_previous_run(
    tmp_path: Path,
) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        company = (
            db.query(repository.ClientCompany)
            .filter_by(client_id="shumeyko", status="active")
            .order_by(repository.ClientCompany.id)
            .first()
        )
        assert company is not None
        company.onec_organization_id = "ORG-1"
        previous = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="tax-profile-previous",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 30),
            user=user,
            source_report=report,
            reason="previous tax profile",
            enforce_active_check=False,
        )
        current = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="tax-profile-current",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 30),
            user=user,
            source_report=report,
            reason="current tax profile",
            enforce_active_check=False,
        )
        db.add(
            OrganizationTaxProfile(
                id="tax-profile-previous",
                tenant_id="shumeyko",
                client_id="shumeyko",
                client_company_id=company.id,
                organization_id="ORG-1",
                tax_system="ОСНО",
                vat_rate=Decimal("22"),
                vat_mode="included",
                vat_deduction_mode="allowed",
                revenue_tax_rate=Decimal("0"),
                income_tax_kind="ip_ndfl_progressive",
                valid_from=date(2026, 1, 1),
                valid_to=date(2026, 12, 31),
                source="Catalog_Организации",
                source_refresh_run_id=previous.id,
                source_snapshot_hash="previous-tax-profile-hash",
                methodology_version="ozon-tax-profile-v2",
                status="active",
                created_at=datetime.now().astimezone(),
            )
        )
        db.flush()

        profiles = repository.tax_profiles_for_source_refresh(db, current)

    assert profiles == []


def test_source_refresh_derives_osno_for_exact_company_name_match(
    tmp_path: Path,
) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        company = (
            db.query(repository.ClientCompany)
            .filter_by(client_id="shumeyko", status="active")
            .first()
        )
        assert company is not None
        company.onec_organization_id = ""
        company.display_name = "Организация из 1С"
        run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            mode="onec-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="derived-osno-test",
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            user=user,
            source_report=report,
            reason="derived OSNO test",
        )
        organization_collection = repository.add_source_refresh_collection(
            db,
            run,
            source_type="onec_organizations",
            source_label="Catalog_Организации",
            required=True,
            status="loaded",
            row_count=1,
        )
        repository.add_source_snapshot_row(
            db,
            organization_collection,
            row_number=1,
            raw_payload_hash="organization-hash",
            row_payload={
                "Ref_Key": "ORG-OSNO",
                "Description": "Организация из 1С",
                "ВидСтавкиНДСПоУмолчанию": "Общая",
                "НДСВключатьВСтоимость": False,
                "ЮридическоеФизическоеЛицо": "ФизическоеЛицо",
                "СчетУчетаЛичныхСредствПредпринимателя_Key": "account-guid",
            },
            source_row_id="ORG-OSNO",
        )
        repository.add_source_refresh_collection(
            db,
            run,
            source_type="onec_tax_special_regime_notifications",
            source_label="Document_УведомлениеОСпецрежимахНалогообложения",
            required=False,
            status="empty_expected",
            row_count=0,
        )

        tax_collection = repository.sync_organization_tax_profiles(db, run, user=user)
        profile = db.query(OrganizationTaxProfile).one()

    assert company.onec_organization_id == "ORG-OSNO"
    assert tax_collection.status == "loaded"
    assert tax_collection.payload["profileCount"] == 1
    assert tax_collection.payload["missingProfileCount"] == 0
    assert tax_collection.payload["specialTaxSourceComplete"] is True
    assert profile.tax_system == "ОСНО"
    assert profile.vat_rate == Decimal("22")
    assert profile.vat_deduction_mode == "allowed"
    assert profile.revenue_tax_rate == 0
    assert profile.source == "Catalog_Организации:derived_osno_2026"


def test_source_refresh_does_not_link_single_organization_with_different_name(
    tmp_path: Path,
) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        company = (
            db.query(repository.ClientCompany)
            .filter_by(client_id="shumeyko", status="active")
            .first()
        )
        assert company is not None
        company.onec_organization_id = ""
        company.display_name = "Организация заказчика"
        run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            mode="onec-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="mismatched-single-organization",
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            user=user,
            source_report=report,
            reason="single organization must not be guessed",
        )
        organization_collection = repository.add_source_refresh_collection(
            db,
            run,
            source_type="onec_organizations",
            source_label="Catalog_Организации",
            required=True,
            status="loaded",
            row_count=1,
        )
        repository.add_source_snapshot_row(
            db,
            organization_collection,
            row_number=1,
            raw_payload_hash="mismatched-organization-hash",
            row_payload={
                "Ref_Key": "ORG-OTHER",
                "Description": "Другая организация из 1С",
            },
            source_row_id="ORG-OTHER",
        )

        tax_collection = repository.sync_organization_tax_profiles(db, run, user=user)
        profile_count = db.query(OrganizationTaxProfile).count()

    assert company.onec_organization_id == ""
    assert profile_count == 0
    assert tax_collection.payload["autoLinkedCompanyCount"] == 0


def test_source_refresh_builds_usn_profile_from_accounting_evidence(
    tmp_path: Path,
) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        company = (
            db.query(repository.ClientCompany)
            .filter_by(client_id="shumeyko", status="active")
            .first()
        )
        assert company is not None
        company.onec_organization_id = "ORG-USN"
        run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            mode="onec-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="usn-accounting-evidence",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 30),
            user=user,
            source_report=report,
            reason="USN accounting evidence test",
        )

        def add_rows(source_type: str, rows: list[dict[str, object]]) -> None:
            collection = repository.add_source_refresh_collection(
                db,
                run,
                source_type=source_type,
                source_label=source_type,
                required=False,
                status="loaded" if rows else "empty_expected",
                row_count=len(rows),
            )
            for index, payload in enumerate(rows, 1):
                repository.add_source_snapshot_row(
                    db,
                    collection,
                    row_number=index,
                    raw_payload_hash=f"{source_type}-{index}",
                    row_payload=payload,
                )

        add_rows(
            "onec_organizations",
            [{"Ref_Key": "ORG-USN", "НДСВключатьВСтоимость": True}],
        )
        add_rows("onec_tax_special_regime_notifications", [])
        add_rows(
            "onec_tax_kinds",
            [
                {
                    "Ref_Key": "TAX-USN",
                    "Description": "Налог при УСН (доходы)",
                    "DeletionMark": False,
                }
            ],
        )
        add_rows(
            "onec_tax_accruals",
            [
                {
                    "Ref_Key": "ACCRUAL-1",
                    "Date": "2026-03-31T00:00:00",
                    "Posted": True,
                    "DeletionMark": False,
                    "Организация_Key": "ORG-USN",
                }
            ],
        )
        add_rows(
            "onec_tax_accrual_lines",
            [{"Ref_Key": "ACCRUAL-1", "ВидНалога_Key": "TAX-USN"}],
        )
        add_rows(
            "onec_vat_sales_book",
            [
                {
                    "Period": "2026-03-31T00:00:00",
                    "Active": True,
                    "Организация_Key": "ORG-USN",
                    "СтавкаНДС": "НДС5",
                    "НДС": "100",
                }
            ],
        )
        now = repository.security.utcnow()
        db.add(
            OrganizationTaxProfileOverride(
                id="rate-anchor-usn",
                tenant_id="shumeyko",
                client_id="shumeyko",
                client_company_id=company.id,
                organization_id="ORG-USN",
                tax_system="УСН Доходы",
                vat_rate=Decimal("5"),
                vat_mode="included",
                vat_deduction_mode="not_allowed",
                revenue_tax_rate=Decimal("0.01"),
                income_tax_kind="",
                valid_from=date(2026, 1, 1),
                valid_to=None,
                status="active",
                reason=(
                    "[rate_anchor_only] Подтвержденная ставка, не опубликованная OData"
                ),
                rate_basis_kind="regional_preference",
                basis_document="Региональный закон о льготной ставке УСН",
                confirmed_by="Бухгалтер",
                source_object_ids='["ACCRUAL-1"]',
                created_by_user_id=user.id,
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()

        fallback_profile, fallback_status = repository.resolve_company_tax_profile(
            db,
            company=company,
            calculation_date=run.period_end,
            refresh_run=run,
        )
        assert fallback_profile is None
        assert fallback_status["status"] == "missing"

        tax_collection = repository.sync_organization_tax_profiles(db, run, user=user)
        source_profile = (
            db.query(OrganizationTaxProfile)
            .filter_by(source_refresh_run_id=run.id)
            .one()
        )

    assert tax_collection.status == "loaded"
    assert tax_collection.payload["profileCount"] == 1
    assert tax_collection.payload["missingProfileCount"] == 0
    assert tax_collection.payload["manualOverrideCount"] == 0
    assert tax_collection.payload["methodologyVersion"] == (
        "marketplace-tax-profile-v4"
    )
    diagnostic = tax_collection.payload["companyDiagnostics"][0]
    assert diagnostic["accountingEvidence"]["rateAnchorMatched"] is True
    assert source_profile.tax_system == "УСН Доходы"
    assert source_profile.vat_rate == Decimal("5")
    assert source_profile.vat_deduction_mode == "not_allowed"
    assert source_profile.revenue_tax_rate == Decimal("0.01")
    assert source_profile.source == "1C:tax_accruals+vat_sales+audited_rate"
    assert source_profile.rate_basis_kind == "regional_preference"
    assert source_profile.basis_document == "Региональный закон о льготной ставке УСН"
    assert source_profile.confirmed_by == "Бухгалтер"


def test_source_refresh_deduplicates_tax_profiles_by_storage_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        company = (
            db.query(repository.ClientCompany)
            .filter_by(client_id="shumeyko", status="active")
            .first()
        )
        assert company is not None
        company.onec_organization_id = "ORG-USN"
        run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            mode="onec-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="tax-profile-storage-identity",
            period_start=date(2026, 7, 27),
            period_end=date(2026, 8, 2),
            user=user,
            source_report=report,
            reason="tax profile storage identity regression",
        )
        organization_collection = repository.add_source_refresh_collection(
            db,
            run,
            source_type="onec_organizations",
            source_label="Catalog_Организации",
            required=True,
            status="loaded",
            row_count=1,
        )
        repository.add_source_snapshot_row(
            db,
            organization_collection,
            row_number=1,
            raw_payload_hash="organization-hash",
            row_payload={"Ref_Key": "ORG-USN"},
            source_row_id="ORG-USN",
        )
        repository.add_source_refresh_collection(
            db,
            run,
            source_type="onec_tax_special_regime_notifications",
            source_label="Document_УведомлениеОСпецрежимахНалогообложения",
            required=False,
            status="empty_expected",
            row_count=0,
        )

        def profiles_for_date(
            *_args: object,
            calculation_date=None,
            **_kwargs: object,
        ):
            assert calculation_date is not None
            return [
                TaxProfile(
                    client_id="shumeyko",
                    organization_id="ORG-USN",
                    tax_system="УСН Доходы",
                    vat_rate=Decimal("5"),
                    vat_mode=VatMode.INCLUDED,
                    vat_deduction_mode=VatDeductionMode.NOT_ALLOWED,
                    revenue_tax_rate=Decimal("0.01"),
                    valid_from=date(2026, 1, 1),
                    source="1C:tax_accruals+vat_sales+audited_rate",
                    basis_document=calculation_date.isoformat(),
                )
            ]

        monkeypatch.setattr(
            repository,
            "tax_profiles_from_account_org_mapping",
            profiles_for_date,
        )

        tax_collection = repository.sync_organization_tax_profiles(db, run, user=user)
        profiles = (
            db.query(OrganizationTaxProfile)
            .filter_by(source_refresh_run_id=run.id)
            .all()
        )

    assert tax_collection.payload["profileCount"] == 1
    assert len(profiles) == 1
    assert profiles[0].basis_document == "2026-08-02"


def test_accounting_evidence_snapshot_query_uses_run_collection_index(
    tmp_path: Path,
) -> None:
    collection = SimpleNamespace(
        id=17,
        source_type="onec_kudir",
        status="loaded",
        snapshot_hash="kudir-sha",
        raw_path="",
    )
    row = SimpleNamespace(row_payload={"Ref_Key": "row-1"})

    class RecordingSession:
        def __init__(self) -> None:
            self.statements: list[object] = []

        def scalars(self, statement: object) -> list[object]:
            self.statements.append(statement)
            return [collection] if len(self.statements) == 1 else [row]

    db = RecordingSession()
    service = SourceRefreshService(
        WebSettings(source_refresh_root=str(tmp_path / "source-refresh"))
    )

    sources = service._accounting_evidence_sources(
        db,
        SimpleNamespace(id="generation-1"),
        tmp_path,
    )

    assert sources["onec_kudir"].rows == ({"Ref_Key": "row-1"},)
    snapshot_where = str(db.statements[1]).partition("WHERE")[2]
    assert "source_snapshot_rows.refresh_run_id" in snapshot_where
    assert "source_snapshot_rows.collection_id" in snapshot_where


def test_source_refresh_builds_configured_usn_expense_profile_from_settings(
    tmp_path: Path,
) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        company = (
            db.query(repository.ClientCompany)
            .filter_by(client_id="shumeyko", status="active")
            .first()
        )
        assert company is not None
        company.onec_organization_id = "ORG-USN-DR"
        run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            mode="onec-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="usn-periodic-settings",
            period_start=date(2026, 4, 1),
            period_end=date(2026, 4, 30),
            user=user,
            source_report=report,
            reason="periodic tax settings test",
        )

        def add_rows(source_type: str, rows: list[dict[str, object]]) -> None:
            collection = repository.add_source_refresh_collection(
                db,
                run,
                source_type=source_type,
                source_label=source_type,
                required=False,
                status="loaded" if rows else "empty_expected",
                row_count=len(rows),
            )
            for index, payload in enumerate(rows, 1):
                repository.add_source_snapshot_row(
                    db,
                    collection,
                    row_number=index,
                    raw_payload_hash=f"{source_type}-{index}",
                    row_payload=payload,
                )

        add_rows("onec_organizations", [{"Ref_Key": "ORG-USN-DR"}])
        add_rows(
            "onec_tax_system_settings",
            [
                {
                    "Period": "2026-01-01T00:00:00",
                    "Организация_Key": "ORG-USN-DR",
                    "СистемаНалогообложения": "Упрощенная",
                    "ПлательщикУСН": True,
                    "ОбъектНалогообложения": "ДоходыМинусРасходы",
                    "СтавкаНалога": "15",
                    "ПовышеннаяСтавкаНалога": "20",
                    "ПлательщикНДСПрименяющийУСН": True,
                }
            ],
        )
        add_rows(
            "onec_vat_settings",
            [
                {
                    "Period": "2026-01-01T00:00:00",
                    "Организация_Key": "ORG-USN-DR",
                    "ПрименяетсяОсвобождениеОтУплатыНДС": False,
                    "СтавкаНалогообложенияПриУСН": "Общая",
                }
            ],
        )

        tax_collection = repository.sync_organization_tax_profiles(db, run, user=user)
        source_profile = (
            db.query(OrganizationTaxProfile)
            .filter_by(source_refresh_run_id=run.id)
            .one()
        )
        resolved_profile, resolved_status = repository.resolve_company_tax_profile(
            db,
            company=company,
            calculation_date=run.period_end,
            refresh_run=run,
        )

    assert tax_collection.status == "loaded"
    assert tax_collection.payload["configuredCompanyCount"] == 1
    assert tax_collection.payload["profileCount"] == 1
    assert tax_collection.payload["unconfirmedProfileCount"] == 0
    assert source_profile.tax_system == "УСН Доходы минус расходы"
    assert source_profile.tax_object == "income_minus_expenses"
    assert source_profile.tax_rate == Decimal("15")
    assert source_profile.elevated_tax_rate == Decimal("20")
    assert source_profile.vat_rate == Decimal("22")
    assert source_profile.vat_deduction_mode == "allowed"
    assert source_profile.revenue_tax_rate == Decimal("0")
    assert source_profile.source == "1C:tax_system_settings+vat_settings"
    assert resolved_profile is not None
    assert resolved_status["status"] == "ready"


def test_source_refresh_blocks_conflicting_active_run_with_status(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="active-run",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 17),
            user=user,
            source_report=report,
        )
        db.commit()
        service = SourceRefreshService(settings)
        payload = service.run(db, tenant_id="shumeyko", mode="full", user=user)

    assert payload["status"] == "blocked_active_refresh"
    assert payload["errorMessage"].startswith("Conflicting source refresh is active")


def test_source_refresh_daily_blocks_when_full_is_active(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="active-full-run",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 17),
            user=user,
            source_report=report,
        )
        db.commit()
        service = SourceRefreshService(settings)
        payload = service.run(db, tenant_id="shumeyko", mode="daily", user=user)

    assert payload["status"] == "blocked_active_refresh"


def test_source_refresh_incremental_blocks_when_daily_is_active(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.source_refresh_incremental_enabled = True
    settings.marketplace_daily_facts_enabled = True
    settings.db_first_reports_enabled = True
    monkeypatch.setattr(
        source_refresh,
        "_incremental_yesterday",
        lambda: date(2026, 6, 17),
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        active = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode="daily",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="active-daily-run",
            period_start=date(2026, 6, 4),
            period_end=date(2026, 6, 17),
            user=user,
            source_report=report,
        )
        db.commit()
        service = SourceRefreshService(settings)
        payload = service.run(
            db,
            tenant_id="shumeyko",
            client_id=report.client_id,
            mode="incremental",
            user=user,
            source_report=report,
        )

    assert payload["status"] == "blocked_active_refresh"
    assert payload["blockedByRunId"] == active.id


def test_source_refresh_low_disk_guard_skips_external_reads(tmp_path: Path) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.source_refresh_min_free_gb = 1_000_000
    seen: dict[str, object] = {}
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_builder_should_not_run,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="full",
            user=user,
            source_report=report,
        )

    assert payload["status"] == "blocked_low_disk"
    assert payload["collections"] == []
    assert seen == {}


def test_source_refresh_finished_source_loaded_run_does_not_block_next_run(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        previous = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            mode="daily",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="finished-daily",
            period_start=date(2026, 6, 9),
            period_end=date(2026, 6, 17),
            user=user,
            source_report=report,
        )
        repository.update_source_refresh_run(
            db,
            previous,
            status="source_loaded",
            finished_at=repository.security.utcnow(),
        )
        db.commit()

        service = SourceRefreshService(settings)
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="daily",
            dry_run=True,
            user=user,
            source_report=report,
        )

    assert payload["id"] != previous.id
    assert payload["status"] == "needs_configuration"


def test_source_refresh_mandatory_wb_failure_keeps_previous_report(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    seen: dict[str, object] = {}
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_failure_exporter,
            wb_report_list_exporter=_fake_report_list_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_builder_should_not_run,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="full",
            user=user,
            source_report=report,
        )
        reports = db.query(ReportRun).filter_by(tenant_id="shumeyko").all()

    assert payload["status"] == "failed"
    assert payload["newReportRunId"] is None
    assert [item.id for item in reports] == ["report-1"]


def test_source_refresh_empty_wb_first_page_blocks_report(tmp_path: Path) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    seen: dict[str, object] = {}
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_empty_first_page_exporter,
            wb_report_list_exporter=_fake_report_list_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_builder_should_not_run,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="full",
            user=user,
            source_report=report,
        )

    finance = [
        item
        for item in payload["collections"]
        if item["sourceType"] == "wb_finance_detail"
    ][0]
    assert payload["status"] == "failed"
    assert finance["status"] == "empty_unexpected"


def test_source_refresh_wb_max_pages_with_next_rrd_blocks_report(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.source_refresh_wb_max_pages = 1
    seen: dict[str, object] = {}

    def wb_exporter(settings, output_dir: Path, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        assert kwargs["max_pages"] == 1
        output_path = output_dir / "wb.raw.json"
        output_path.write_text(
            json.dumps([{"rrdId": 987, "nmId": 1001}], ensure_ascii=False),
            encoding="utf-8",
        )
        return [
            WbFinancePageResult(
                seller_account_id=settings.accounts[0].seller_account_id,
                account_name=settings.accounts[0].account_name,
                page_index=1,
                ok=True,
                status="ok",
                row_count=100000,
                rrd_id_start=0,
                rrd_id_next=987,
                raw_payload_hash="wb-hash",
                output_path=output_path,
                status_code=200,
            )
        ]

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=wb_exporter,
            wb_report_list_exporter=_fake_report_list_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_builder_should_not_run,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="full",
            user=user,
            source_report=report,
        )
        finance_rows = (
            db.query(SourceSnapshotRow)
            .filter_by(source_type="wb_finance_detail")
            .count()
        )
        reports = db.query(ReportRun).filter_by(tenant_id="shumeyko").all()

    finance = [
        item
        for item in payload["collections"]
        if item["sourceType"] == "wb_finance_detail"
    ][0]
    assert payload["status"] == "failed"
    assert payload["newReportRunId"] is None
    assert finance["status"] == "partial_source"
    assert finance["rowCount"] == 100000
    assert finance["payload"]["completenessIssue"] == (
        "max_pages_reached_with_next_rrd_id"
    )
    assert finance["payload"]["results"][0]["maxPagesReached"] is True
    assert finance["payload"]["results"][0]["rrdIdNext"] == 987
    assert finance_rows == 0
    assert [item.id for item in reports] == ["report-1"]


def test_source_refresh_optional_failure_creates_needs_review_report(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_report_list_exporter=_fake_report_list_failure_exporter,
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_fake_workbook_builder,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="full",
            user=user,
            source_report=report,
        )
        loads = db.query(SourceLoad).filter_by(report_run_id=payload["newReportRunId"])
        report_list_load = loads.filter_by(source_type="wb_sales_report_list").one()

    assert payload["status"] == "needs_review"
    assert report_list_load.status == "needs_review"


def test_source_refresh_optional_onec_404_does_not_force_review(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )

    def onec_exporter(
        settings,
        collections,
        output_dir: Path,
        *,
        top: int,
        max_pages: int,
        **kwargs,
    ):
        loaded = _fake_onec_exporter(seen)(
            settings,
            [
                item
                for item in collections
                if item.sample_id
                not in {"supplier_receipts", "supplier_receipt_expenses"}
            ],
            output_dir,
            top=top,
            max_pages=max_pages,
            **kwargs,
        )
        missing_optional = [
            OnecSampleExportResult(
                sample_id=item.sample_id,
                collection_name=item.collection_name,
                ok=False,
                row_count=0,
                page_count=0,
                status_code=404,
                error="HTTP 404",
            )
            for item in collections
            if item.sample_id in {"supplier_receipts", "supplier_receipt_expenses"}
        ]
        return [*loaded, *missing_optional]

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_report_list_exporter=_fake_report_list_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=onec_exporter,
            workbook_builder=_fake_workbook_builder,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="full",
            user=user,
            source_report=report,
        )
        loads = db.query(SourceLoad).filter_by(report_run_id=payload["newReportRunId"])
        supplier_receipts_load = loads.filter_by(
            source_type="onec_supplier_receipts"
        ).one()

    optional_statuses = {
        item["sourceType"]: item["status"]
        for item in payload["collections"]
        if item["sourceType"].startswith("onec_supplier_receipt")
    }
    assert payload["status"] == "needs_review"
    assert optional_statuses == {
        "onec_supplier_receipt_expenses": "empty_expected",
        "onec_supplier_receipts": "empty_expected",
    }
    assert supplier_receipts_load.status == "empty_expected"


def test_source_refresh_mandatory_raw_row_failure_blocks_report(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    seen: dict[str, object] = {}

    def wb_exporter(settings, output_dir: Path, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        return [
            WbFinancePageResult(
                seller_account_id=settings.accounts[0].seller_account_id,
                account_name=settings.accounts[0].account_name,
                page_index=1,
                ok=True,
                status="ok",
                row_count=1,
                rrd_id_start=0,
                raw_payload_hash="wb-hash",
                output_path=output_dir / "missing.raw.json",
                status_code=200,
            )
        ]

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=wb_exporter,
            wb_report_list_exporter=_fake_report_list_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_builder_should_not_run,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="full",
            user=user,
            source_report=report,
        )

    finance = [
        item
        for item in payload["collections"]
        if item["sourceType"] == "wb_finance_detail"
    ][0]
    assert payload["status"] == "failed"
    assert payload["newReportRunId"] is None
    assert finance["status"] == "failed"
    assert finance["errorMessage"].startswith("raw_row_persistence_failed")


def test_source_refresh_optional_raw_row_failure_marks_needs_review(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    seen: dict[str, object] = {}

    def report_list_exporter(settings, output_dir: Path, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        return [
            WbSalesReportListPageResult(
                seller_account_id=settings.accounts[0].seller_account_id,
                account_name=settings.accounts[0].account_name,
                page_index=1,
                ok=True,
                status="ok",
                row_count=1,
                offset=0,
                raw_payload_hash="report-list-hash",
                output_path=output_dir / "missing.raw.json",
                status_code=200,
            )
        ]

    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_report_list_exporter=report_list_exporter,
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_fake_workbook_builder,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="full",
            user=user,
            source_report=report,
        )

    report_list = [
        item
        for item in payload["collections"]
        if item["sourceType"] == "wb_sales_report_list"
    ][0]
    assert payload["status"] == "needs_review"
    assert payload["newReportRunId"]
    assert report_list["status"] == "needs_review"
    assert report_list["errorMessage"].startswith("raw_row_persistence_failed")


def test_source_refresh_dry_run_fails_when_mapping_is_missing(tmp_path: Path) -> None:
    settings, session_factory, user, _report, mapping_dir = _source_refresh_context(
        tmp_path
    )
    (mapping_dir / "mapping.csv").unlink()
    mapping_dir.rmdir()
    with session_factory() as db:
        user, _report = _session_user_report(db, user, _report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(settings)
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="full",
            dry_run=True,
            user=user,
            source_report=_report,
        )

    mapping = [
        item for item in payload["collections"] if item["sourceType"] == "sku_mapping"
    ][0]
    assert payload["status"] == "needs_review"
    assert mapping["status"] == "needs_review"
    assert mapping["errorMessage"] == "mapping_service_empty"
    assert mapping["payload"]["legacyFileSource"]["errorMessage"] == (
        "mapping_source_missing"
    )


def test_source_refresh_stale_mapping_marks_report_needs_review(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}
    settings, session_factory, user, report, mapping_dir = _source_refresh_context(
        tmp_path,
        mapping_stale_days=1,
    )
    old_timestamp = datetime.now().timestamp() - timedelta(days=10).total_seconds()
    mapping_file = mapping_dir / "mapping.csv"
    os.utime(mapping_file, (old_timestamp, old_timestamp))
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_report_list_exporter=_fake_report_list_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_fake_workbook_builder,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="full",
            user=user,
            source_report=report,
        )

    mapping = [
        item for item in payload["collections"] if item["sourceType"] == "sku_mapping"
    ][0]
    assert payload["status"] == "needs_review"
    assert mapping["status"] == "needs_review"
    assert mapping["payload"]["legacyFileSource"]["status"] == "stale"


def test_source_refresh_daily_stale_mapping_returns_needs_review(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}
    settings, session_factory, user, report, mapping_dir = _source_refresh_context(
        tmp_path,
        mapping_stale_days=1,
    )
    old_timestamp = datetime.now().timestamp() - timedelta(days=10).total_seconds()
    mapping_file = mapping_dir / "mapping.csv"
    os.utime(mapping_file, (old_timestamp, old_timestamp))
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_report_list_exporter=_fake_report_list_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_builder_should_not_run,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="daily",
            user=user,
            source_report=report,
        )

    assert payload["status"] == "needs_review"
    assert payload["newReportRunId"] is None


def test_source_refresh_standalone_onec_only_does_not_create_report(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_report_list_exporter=_fake_report_list_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_builder_should_not_run,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="onec-only",
            user=user,
        )
        reports = db.query(ReportRun).filter_by(tenant_id="shumeyko").all()

    assert payload["status"] == "needs_review"
    assert payload["newReportRunId"] is None
    assert [item.id for item in reports] == ["report-1"]


def test_onec_only_with_report_falls_back_to_full_without_reusable_wb_snapshot(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        refresh_run = SourceRefreshService(settings)._create_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="onec-only",
            credential_source="tenant",
            dry_run=False,
            user=user,
            source_report=report,
            reason="tax profile changed",
            period_start=None,
            period_end=None,
            resume_mode="never",
            resume_from_run_id=None,
        )

    assert isinstance(refresh_run, SourceRefreshRun)
    assert refresh_run.mode == "full"
    assert refresh_run.period_start == report.period_start
    assert refresh_run.period_end == report.period_end
    assert refresh_run.base_source_refresh_run_id is None


def test_onec_only_with_report_reuses_complete_full_wb_snapshot(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        root_dir = settings.source_refresh_root_path / "full-reusable"
        finance_dir = root_dir / "wb_finance"
        cards_dir = root_dir / "wb_product_cards"
        finance_dir.mkdir(parents=True)
        cards_dir.mkdir()
        (finance_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "results": [
                        {
                            "seller_account_id": "WB_ACCOUNT",
                            "status": "no_data",
                            "page_index": 1,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (cards_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "results": [
                        {
                            "seller_account_id": "WB_ACCOUNT",
                            "ok": True,
                            "page_index": 1,
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        now = datetime.now().astimezone()
        db.add(
            WbCabinet(
                id="cabinet-active",
                tenant_id=report.tenant_id,
                client_id=report.client_id,
                display_name="Активный кабинет",
                cabinet_key="active",
                provider="wb_api",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        base = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="full-reusable",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            source_report=report,
            reason="base",
        )
        repository.update_source_refresh_run(
            db,
            base,
            status="report_created",
            root_dir=str(root_dir),
            finished_at=datetime.now().astimezone(),
        )
        repository.add_source_refresh_collection(
            db,
            base,
            source_type="wb_finance_detail",
            source_label="WB finance",
            required=True,
            status="loaded",
            raw_path=str(finance_dir),
            payload={
                "sourceCoverageStart": report.period_start.isoformat(),
                "sourceCoverageEnd": report.period_end.isoformat(),
                "results": [
                    {"wbCabinetId": "cabinet-active"},
                    {"wbCabinetId": "cabinet-historical"},
                ],
            },
        )
        repository.add_source_refresh_collection(
            db,
            base,
            source_type="wb_product_cards",
            source_label="WB cards",
            required=True,
            status="loaded",
            raw_path=str(cards_dir),
        )
        refresh_run = SourceRefreshService(settings)._create_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="onec-only",
            credential_source="tenant",
            dry_run=False,
            user=user,
            source_report=report,
            reason="tax profile changed",
            period_start=None,
            period_end=None,
            resume_mode="never",
            resume_from_run_id=None,
        )

    assert isinstance(refresh_run, SourceRefreshRun)
    assert refresh_run.mode == "onec-only"
    assert refresh_run.base_source_refresh_run_id == base.id


def test_tax_profile_sync_distinguishes_live_profile_from_report_application(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="onec-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="onec-tax-ready",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            source_report=None,
            reason="tax profile",
        )
        company_ids = {
            item.client_company_id
            for item in db.query(repository.ReportUnitRow)
            .filter(repository.ReportUnitRow.report_run_id == report.id)
            .all()
            if item.client_company_id
        }
        for index, company_id in enumerate(sorted(company_ids), start=1):
            company = db.get(repository.ClientCompany, company_id)
            assert company is not None
            company.onec_organization_id = f"ORG-TAX-SYNC-{index}"
            db.add(
                OrganizationTaxProfile(
                    id=f"tax-sync-profile-{index}",
                    tenant_id=report.tenant_id,
                    client_id=report.client_id,
                    client_company_id=company.id,
                    organization_id=company.onec_organization_id,
                    tax_system="ОСНО",
                    vat_rate=Decimal("22"),
                    vat_mode="included",
                    vat_deduction_mode="allowed",
                    revenue_tax_rate=Decimal("0"),
                    income_tax_kind="ip_ndfl_progressive",
                    valid_from=date(2026, 1, 1),
                    valid_to=None,
                    source="1C:test",
                    source_refresh_run_id=refresh_run.id,
                    source_snapshot_hash="tax-profile-hash",
                    methodology_version="marketplace-tax-profile-v3",
                    status="active",
                    created_at=repository.security.utcnow(),
                )
            )
        collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="onec_tax_profiles",
            source_label="Tax profiles",
            required=False,
            status="loaded",
            snapshot_hash="tax-profile-hash",
            row_count=len(company_ids),
            payload={
                "profileCount": len(company_ids),
                "missingProfileCount": 0,
                "unconfirmedProfileCount": 0,
            },
        )
        not_applied = repository.tax_profile_sync_payload(
            db,
            report,
            tax_context={"calculated": False},
            include_staff_details=True,
        )
        db.add(
            SourceLoad(
                tenant_id=report.tenant_id,
                client_id=report.client_id,
                wb_cabinet_id="",
                report_run_id=report.id,
                source_refresh_run_id=refresh_run.id,
                required=False,
                publication_required=False,
                source_type="onec_tax_profiles",
                source_label="Tax profiles",
                status="loaded",
                snapshot_hash=collection.snapshot_hash,
                row_count=len(company_ids),
                loaded_at=datetime.now().astimezone(),
            )
        )
        db.flush()
        applied = repository.tax_profile_sync_payload(
            db,
            report,
            tax_context={"calculated": True},
            include_staff_details=True,
        )
        client_payload = repository.tax_profile_sync_payload(
            db,
            report,
            tax_context={"calculated": True},
            include_staff_details=False,
        )

    assert not_applied["liveStatus"] == "ready"
    assert not_applied["reportStatus"] == "confirmed_not_applied"
    assert not_applied["needsRebuild"] is True
    assert "ещё не применён" in not_applied["message"]
    assert applied["reportStatus"] == "applied"
    assert applied["needsRebuild"] is False
    assert client_payload == {
        "reportStatus": "applied",
        "needsRebuild": False,
        "message": "Налоговый профиль применён в текущем отчёте.",
    }


def test_retention_protects_report_refresh_and_composite_base(
    tmp_path: Path,
) -> None:
    from scripts.prune_source_refresh import _protected_from_database

    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        base_root = settings.source_refresh_root_path / "full-lineage-base"
        current_root = settings.source_refresh_root_path / "onec-lineage-current"
        base_root.mkdir(parents=True)
        current_root.mkdir()
        base = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id=base_root.name,
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            source_report=report,
            reason="base",
        )
        repository.update_source_refresh_run(
            db,
            base,
            status="report_created",
            root_dir=str(base_root),
            finished_at=datetime.now().astimezone(),
        )
        composite = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="onec-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id=current_root.name,
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            source_report=report,
            base_source_refresh_run=base,
            reason="composite",
        )
        repository.update_source_refresh_run(
            db,
            composite,
            status="report_created",
            root_dir=str(current_root),
            finished_at=datetime.now().astimezone(),
        )
        db.add(
            SourceLoad(
                tenant_id=report.tenant_id,
                client_id=report.client_id,
                wb_cabinet_id="",
                report_run_id=report.id,
                source_refresh_run_id=composite.id,
                required=True,
                publication_required=False,
                source_type="onec_odata",
                source_label="1C",
                status="loaded",
                snapshot_hash="onec-hash",
                row_count=1,
                loaded_at=datetime.now().astimezone(),
            )
        )
        db.commit()

    protected = _protected_from_database(settings.database_url)
    assert base_root.name in protected
    assert current_root.name in protected


def test_retention_protects_newest_successful_full_per_client(
    tmp_path: Path,
) -> None:
    from scripts.prune_source_refresh import _protected_from_database

    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        runs: list[SourceRefreshRun] = []
        for index in (1, 2):
            root = settings.source_refresh_root_path / f"full-client-{index}"
            root.mkdir(parents=True)
            run = repository.create_source_refresh_run(
                db,
                tenant_id=report.tenant_id,
                client_id=report.client_id,
                mode="full",
                credential_source="tenant",
                dry_run=False,
                snapshot_set_id=root.name,
                period_start=report.period_start,
                period_end=report.period_end,
                user=user,
                reason=f"full {index}",
            )
            repository.update_source_refresh_run(
                db,
                run,
                status="report_created",
                root_dir=str(root),
                finished_at=datetime.now().astimezone(),
            )
            runs.append(run)
        db.commit()

    protected = _protected_from_database(settings.database_url)

    assert runs[-1].snapshot_set_id in protected


def test_composite_report_source_loads_keep_wb_base_and_current_onec_lineage(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        base = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="full-base-loads",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            source_report=report,
            reason="base",
        )
        current = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="onec-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="onec-current-loads",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            source_report=report,
            base_source_refresh_run=base,
            reason="current",
            enforce_active_check=False,
        )
        repository.add_source_refresh_collection(
            db,
            base,
            source_type="wb_finance_detail",
            source_label="WB",
            required=True,
            status="loaded",
            snapshot_hash="wb-hash",
            row_count=10,
        )
        repository.add_source_refresh_collection(
            db,
            current,
            source_type="onec_tax_profiles",
            source_label="Tax",
            required=False,
            status="loaded",
            snapshot_hash="tax-hash",
            row_count=2,
        )
        repository.replace_source_loads_from_refresh(
            db,
            report,
            current,
            base_refresh_run=base,
        )
        loads = {
            item.source_type: item
            for item in db.query(SourceLoad).filter_by(report_run_id=report.id)
        }

    assert loads["wb_finance_detail"].source_refresh_run_id == base.id
    assert loads["onec_tax_profiles"].source_refresh_run_id == current.id
    assert loads["wb_finance_detail"].lineage_role == "base"
    assert loads["wb_finance_detail"].coverage_start == report.period_start
    assert loads["wb_finance_detail"].coverage_end == report.period_end
    assert loads["onec_tax_profiles"].lineage_role == "current"
    assert loads["onec_tax_profiles"].coverage_start == report.period_start
    assert loads["onec_tax_profiles"].coverage_end == report.period_end


def test_incremental_snapshot_set_hash_includes_source_snapshots(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    service = SourceRefreshService(settings)
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        base = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="base-run",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            reason="base",
        )
        current = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="incremental",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="current-run",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            base_source_refresh_run=base,
            reason="current",
            enforce_active_check=False,
        )
        overlay = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="incremental",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="overlay-run",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            reason="overlay",
            enforce_active_check=False,
        )
        repository.add_source_refresh_collection(
            db,
            base,
            source_type="wb_finance_detail",
            source_label="WB",
            required=True,
            status="loaded",
            snapshot_hash="wb-hash",
            row_count=1,
        )
        onec = repository.add_source_refresh_collection(
            db,
            current,
            source_type="onec_odata",
            source_label="1C",
            required=True,
            status="loaded",
            snapshot_hash="onec-hash-v1",
            row_count=1,
        )
        repository.add_source_refresh_collection(
            db,
            overlay,
            source_type="wb_finance_detail",
            source_label="WB overlay",
            required=True,
            status="loaded",
            snapshot_hash="overlay-hash",
            row_count=1,
        )
        first = service._report_snapshot_set_id(
            current,
            base_refresh_run=base,
            contributing_runs=[base, overlay, current],
        )
        onec.snapshot_hash = "onec-hash-v2"
        second = service._report_snapshot_set_id(
            current,
            base_refresh_run=base,
            contributing_runs=[base, overlay, current],
        )

    assert first.startswith("composite-")
    assert second.startswith("composite-")
    assert first != second


def test_incremental_source_loads_keep_only_composed_base_and_overlay_sources(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        base = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="full-incremental-lineage",
            period_start=report.period_start,
            period_end=report.period_end,
            source_window_start=report.period_start,
            source_window_end=report.period_end,
            user=user,
            reason="base",
        )
        overlay = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="incremental",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="previous-incremental-lineage",
            period_start=report.period_start,
            period_end=report.period_end,
            source_window_start=date(2026, 5, 1),
            source_window_end=report.period_end,
            user=user,
            reason="overlay",
            enforce_active_check=False,
        )
        current = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="incremental",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="current-incremental-lineage",
            period_start=report.period_start,
            period_end=report.period_end,
            source_window_start=date(2026, 5, 21),
            source_window_end=report.period_end,
            user=user,
            base_source_refresh_run=base,
            reason="current",
            enforce_active_check=False,
        )
        for run in (base, overlay, current):
            for source_type in ("wb_finance_detail", "wb_stock_history_daily"):
                repository.add_source_refresh_collection(
                    db,
                    run,
                    source_type=source_type,
                    source_label=source_type,
                    required=source_type == "wb_finance_detail",
                    status="loaded",
                    snapshot_hash=f"{run.id}-{source_type}",
                    row_count=1,
                )
        repository.add_source_refresh_collection(
            db,
            current,
            source_type="onec_odata",
            source_label="1C",
            required=True,
            status="loaded",
            snapshot_hash="onec-current",
            row_count=1,
        )

        repository.replace_source_loads_from_refresh(
            db,
            report,
            current,
            base_refresh_run=base,
            contributing_runs=[base, overlay, current],
        )
        loads = list(
            db.query(SourceLoad)
            .filter_by(report_run_id=report.id)
            .order_by(SourceLoad.id)
        )

    assert len(loads) == 5
    assert {(item.source_type, item.lineage_role) for item in loads} == {
        ("wb_finance_detail", "base"),
        ("wb_finance_detail", "overlay"),
        ("wb_finance_detail", "current"),
        ("wb_stock_history_daily", "current"),
        ("onec_odata", "current"),
    }
    finance_coverage = {
        item.lineage_role: (item.coverage_start, item.coverage_end)
        for item in loads
        if item.source_type == "wb_finance_detail"
    }
    assert finance_coverage == {
        "base": (report.period_start, report.period_end),
        "overlay": (date(2026, 5, 1), report.period_end),
        "current": (date(2026, 5, 21), report.period_end),
    }


def test_replace_report_source_load_uses_exact_registered_stock_collection(
    tmp_path: Path,
) -> None:
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        stock_run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            client_id=report.client_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="registered-stock-source",
            period_start=report.period_start,
            period_end=report.period_end,
            user=user,
            source_report=report,
            reason="registered stock source",
        )
        repository.add_source_refresh_collection(
            db,
            stock_run,
            source_type="wb_stock_history_daily",
            source_label="WB stock history",
            required=False,
            status="loaded",
            snapshot_hash="stock-hash",
            row_count=2,
            raw_path=str(tmp_path / "stock"),
        )
        repository.replace_report_source_load_from_refresh(
            db,
            report,
            stock_run,
            source_type="wb_stock_history_daily",
        )
        loads = list(
            db.query(SourceLoad).filter_by(
                report_run_id=report.id,
                source_type="wb_stock_history_daily",
            )
        )

    assert len(loads) == 1
    assert loads[0].source_refresh_run_id == stock_run.id
    assert loads[0].snapshot_hash == "stock-hash"


def test_source_refresh_fails_if_workbook_builder_does_not_create_file(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_report_list_exporter=_fake_report_list_exporter(seen),
            wb_product_cards_exporter=_fake_wb_product_cards_exporter(seen),
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=lambda _args: 1,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="full",
            user=user,
            source_report=report,
        )

    assert payload["status"] == "failed"
    assert payload["newReportRunId"] is None
    assert payload["errorMessage"] == (
        "ValueError: source refresh workbook was not created"
    )


def test_source_refresh_safe_error_keeps_context_and_redacts_secrets() -> None:
    error = RuntimeError(
        "failed with token=abc12345678901234567890123456789012345 "
        "and password=plain-secret"
    )

    message = _safe_error(error)

    assert message.startswith("RuntimeError: failed with token=<redacted>")
    assert "password=<redacted>" in message
    assert "plain-secret" not in message
    assert "abc12345678901234567890123456789012345" not in message


def test_source_snapshot_duplicate_position_is_blocked(tmp_path: Path) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="snapshot-1",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 17),
            user=user,
            source_report=report,
        )
        collection = repository.add_source_refresh_collection(
            db,
            run,
            source_type="wb_finance_detail",
            source_label="WB Finance",
            required=True,
            status="loaded",
        )
        first = repository.add_source_snapshot_row(
            db,
            collection,
            row_number=1,
            raw_payload_hash="hash-1",
            row_payload={"rrdId": 1},
            source_row_id="1",
        )
        with pytest.raises(ValueError, match="duplicate source row position"):
            repository.add_source_snapshot_row(
                db,
                collection,
                row_number=1,
                raw_payload_hash="hash-1",
                row_payload={"rrdId": 1},
                source_row_id="1",
            )
        count = db.query(SourceSnapshotRow).count()

    assert first.id is not None
    assert count == 1
    assert collection.status == "needs_review"


def test_source_snapshot_bulk_insert_returns_exact_inserted_count(
    tmp_path: Path,
) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="snapshot-bulk-insert",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 17),
            user=user,
            source_report=report,
        )
        collection = repository.add_source_refresh_collection(
            db,
            run,
            source_type="wb_finance_detail",
            source_label="WB Finance",
            required=True,
            status="loaded",
        )
        inserted_count = repository.add_source_snapshot_rows(
            db,
            collection,
            [
                {
                    "row_number": row_number,
                    "raw_payload_hash": f"hash-{row_number}",
                    "row_payload": {"rrdId": row_number},
                    "source_row_id": str(row_number),
                }
                for row_number in (1, 2)
            ],
        )
        persisted_count = db.query(SourceSnapshotRow).count()

    assert inserted_count == 2
    assert persisted_count == 2
    assert collection.status == "loaded"
    assert collection.error_message == ""


def test_source_snapshot_keeps_distinct_rows_with_same_technical_id(
    tmp_path: Path,
) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="snapshot-technical-id",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 17),
            user=user,
            source_report=report,
        )
        collection = repository.add_source_refresh_collection(
            db,
            run,
            source_type="wb_finance_detail",
            source_label="WB Finance",
            required=True,
            status="loaded",
        )
        for row_number, payload_hash in ((1, "hash-1"), (2, "hash-2")):
            repository.add_source_snapshot_row(
                db,
                collection,
                row_number=row_number,
                raw_payload_hash=payload_hash,
                row_payload={"rrdId": 1, "line": row_number},
                source_row_id="same-technical-id",
            )
        control = repository.validate_source_snapshot_duplicates(db, run)
        count = db.query(SourceSnapshotRow).count()

    assert count == 2
    assert control.status == "loaded"
    assert control.row_count == 0


def test_source_snapshot_repeated_payload_hash_blocks_profit(tmp_path: Path) -> None:
    _settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="snapshot-payload-duplicate",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 17),
            user=user,
            source_report=report,
        )
        collection = repository.add_source_refresh_collection(
            db,
            run,
            source_type="wb_finance_detail",
            source_label="WB Finance",
            required=True,
            status="loaded",
        )
        for row_number in (1, 2):
            repository.add_source_snapshot_row(
                db,
                collection,
                row_number=row_number,
                raw_payload_hash="same-payload-hash",
                row_payload={"rrdId": row_number},
                source_row_id=str(row_number),
            )
        control = repository.validate_source_snapshot_duplicates(db, run)

    assert control.status == "needs_review"
    assert control.row_count == 1
    assert control.payload["blocksProfit"] is True


def _source_refresh_context(
    tmp_path: Path,
    *,
    integration_key: str | None = None,
    mapping_stale_days: int = 7,
):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    workbook = reports_dir / "initial.xlsx"
    workbook.write_bytes(b"xlsx")
    mapping_dir = tmp_path / "mapping"
    mapping_dir.mkdir()
    (mapping_dir / "mapping.csv").write_text(
        "barcode,article\n1,A-1\n",
        encoding="utf-8",
    )
    if integration_key is None:
        integration_key = Fernet.generate_key().decode("ascii")
    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        import_dashboard_payload(
            db,
            minimal_payload(),
            tenant_id="shumeyko",
            tenant_name="Шумейко и Партнеры",
            report_id="report-1",
            source_workbook_path=str(workbook),
        )
        user = upsert_user(
            db,
            email="admin@example.com",
            password="secret",
            tenant_id="shumeyko",
            role="admin",
        )
        report = db.get(ReportRun, "report-1")
        db.commit()
    settings = WebSettings(
        database_url=f"sqlite:///{tmp_path / 'web.sqlite3'}",
        cookie_secure=False,
        allowed_export_root=str(reports_dir),
        integration_secret_key=integration_key,
        source_refresh_enabled=True,
        source_refresh_root=str(tmp_path / "source_refresh"),
        source_refresh_period_start="2026-03-01",
        source_refresh_period_end="2026-06-17",
        source_refresh_mapping_dir=str(mapping_dir),
        source_refresh_mapping_stale_days=mapping_stale_days,
        source_refresh_wb_request_delay_seconds=0,
        source_refresh_min_free_gb=0,
    )
    return settings, session_factory, user, report, mapping_dir


def _session_user_report(db, user, report):
    return db.get(repository.User, user.id), db.get(ReportRun, report.id)


def _dimension_card(nm_id: str, *, length: int = 30) -> dict[str, object]:
    return {
        "nm_id": nm_id,
        "length_cm": length,
        "width_cm": 20,
        "height_cm": 10,
        "weight_brutto_kg": 2,
        "dimensions_valid": True,
    }


def _add_dimension_database_snapshot(
    db,
    report,
    *,
    snapshot_set_id: str,
    cabinet_id: str,
    cards: list[dict[str, object]],
):
    run = repository.create_source_refresh_run(
        db,
        tenant_id=report.tenant_id,
        client_id=report.client_id,
        mode="full",
        credential_source="tenant",
        dry_run=False,
        snapshot_set_id=snapshot_set_id,
        period_start=report.period_start,
        period_end=report.period_end,
        reason="dimension source test",
        enforce_active_check=False,
    )
    results = [
        {
            "wbCabinetId": cabinet_id,
            "pageIndex": 1,
            "status": "loaded",
            "ok": True,
            "rowCount": len(cards),
            "flatPayloadHash": source_refresh._hash_payload(cards),
        }
    ]
    collection = repository.add_source_refresh_collection(
        db,
        run,
        source_type="wb_product_cards",
        source_label="WB cards",
        required=True,
        status="loaded",
        snapshot_hash=source_refresh._hash_payload(results),
        row_count=len(cards),
        payload={"results": results},
    )
    for row_number, card in enumerate(cards, start=1):
        repository.add_source_snapshot_row(
            db,
            collection,
            row_number=row_number,
            raw_payload_hash=source_refresh._hash_payload(card),
            source_row_id=str(card["nm_id"]),
            wb_cabinet_id=cabinet_id,
            row_payload=card,
        )
    return run, collection


def _add_dimension_file_snapshot(
    db,
    report,
    *,
    settings: WebSettings,
    snapshot_set_id: str,
    cabinet_id: str,
    cards: list[dict[str, object]],
):
    run = repository.create_source_refresh_run(
        db,
        tenant_id=report.tenant_id,
        client_id=report.client_id,
        mode="full",
        credential_source="tenant",
        dry_run=False,
        snapshot_set_id=snapshot_set_id,
        period_start=report.period_start,
        period_end=report.period_end,
        reason="file dimension source test",
        enforce_active_check=False,
    )
    run_root = settings.source_refresh_root_path / snapshot_set_id
    raw_dir = run_root / "wb_product_cards"
    raw_dir.mkdir(parents=True)
    run.root_dir = str(run_root)
    raw_payload = {"cards": []}
    raw_path = raw_dir / "cards.raw.json"
    flat_path = raw_dir / "cards.flat.json"
    raw_path.write_text(json.dumps(raw_payload), encoding="utf-8")
    flat_path.write_text(json.dumps(cards), encoding="utf-8")
    results = [
        {
            "wbCabinetId": cabinet_id,
            "pageIndex": 1,
            "status": "loaded",
            "ok": True,
            "rowCount": len(cards),
            "rawPayloadHash": source_refresh._hash_payload(raw_payload),
            "flatPayloadHash": source_refresh._hash_payload(cards),
            "outputFile": raw_path.name,
            "flatOutputFile": flat_path.name,
        }
    ]
    (raw_dir / "manifest.json").write_text(
        json.dumps({"results": results}),
        encoding="utf-8",
    )
    collection = repository.add_source_refresh_collection(
        db,
        run,
        source_type="wb_product_cards",
        source_label="WB cards",
        required=True,
        status="loaded",
        snapshot_hash=source_refresh._hash_payload(results),
        row_count=len(cards),
        raw_path=str(raw_dir),
        payload={
            "results": results,
            "rowPersistence": {
                "status": "file_authoritative",
                "rawFilesAuthoritative": True,
            },
        },
    )
    source_refresh._attach_collection_raw_integrity(
        collection,
        source_root=settings.source_refresh_root_path,
    )
    assert collection.payload["rawIntegrity"]["status"] == "verified"
    return run, collection, flat_path


def _tariff_row() -> dict[str, object]:
    return {
        "requested_date": "2026-04-06",
        "tariff_type": "box",
        "warehouse_name": "Склад A",
        "geo_name": "Округ A",
        "dt_next_box": "2026-04-13",
        "dt_till_max": "2026-04-30",
        "box_delivery_base": "48",
        "box_delivery_liter": "11,2",
        "box_delivery_coef_expr": "125",
        "box_storage_base": "0,14",
        "box_storage_liter": "0,07",
        "box_storage_coef_expr": "115",
    }


def _add_tariff_database_snapshot(
    db,
    report,
    *,
    settings: WebSettings,
    snapshot_set_id: str,
    cabinet_id: str,
    rows: list[dict[str, object]],
):
    run = repository.create_source_refresh_run(
        db,
        tenant_id=report.tenant_id,
        client_id=report.client_id,
        mode="full",
        credential_source="tenant",
        dry_run=False,
        snapshot_set_id=snapshot_set_id,
        period_start=report.period_start,
        period_end=report.period_end,
        reason="tariff source test",
        enforce_active_check=False,
    )
    run_root = settings.source_refresh_root_path / snapshot_set_id
    raw_dir = run_root / "wb_tariffs"
    raw_dir.mkdir(parents=True)
    run.root_dir = str(run_root)
    raw_payload = {"box": {}, "pallet": {}}
    flat_payload = {"box": rows, "pallet": []}
    raw_path = raw_dir / "tariffs.raw.json"
    flat_path = raw_dir / "tariffs.flat.json"
    raw_path.write_text(json.dumps(raw_payload), encoding="utf-8")
    flat_path.write_text(json.dumps(flat_payload), encoding="utf-8")
    results = [
        {
            "wbCabinetId": cabinet_id,
            "pageIndex": 20260406,
            "targetDate": "2026-04-06",
            "status": "loaded",
            "ok": True,
            "rowCount": len(rows),
            "rawPayloadHash": source_refresh._hash_payload(raw_payload),
            "flatPayloadHash": source_refresh._hash_payload(flat_payload),
            "outputFile": raw_path.name,
            "flatOutputFile": flat_path.name,
        }
    ]
    (raw_dir / "manifest.json").write_text(
        json.dumps({"results": results}),
        encoding="utf-8",
    )
    collection = repository.add_source_refresh_collection(
        db,
        run,
        source_type="wb_tariffs",
        source_label="WB tariffs",
        required=False,
        status="loaded",
        snapshot_hash=source_refresh._hash_payload(results),
        row_count=len(rows),
        raw_path=str(raw_dir),
        payload={
            "results": results,
            "factorSnapshotDate": "2026-07-21",
        },
    )
    source_refresh._attach_collection_raw_integrity(
        collection,
        source_root=settings.source_refresh_root_path,
    )
    assert collection.payload["rawIntegrity"]["status"] == "verified"
    for row_number, row in enumerate(rows, start=1):
        repository.add_source_snapshot_row(
            db,
            collection,
            row_number=row_number,
            raw_payload_hash=source_refresh._hash_payload(row),
            source_row_id=f"tariff-{row_number}",
            wb_cabinet_id=cabinet_id,
            row_payload=row,
        )
    return run, collection


def _add_tariff_file_snapshot(
    db,
    report,
    *,
    settings: WebSettings,
    snapshot_set_id: str,
    cabinet_id: str,
    rows: list[dict[str, object]],
):
    run = repository.create_source_refresh_run(
        db,
        tenant_id=report.tenant_id,
        client_id=report.client_id,
        mode="full",
        credential_source="tenant",
        dry_run=False,
        snapshot_set_id=snapshot_set_id,
        period_start=report.period_start,
        period_end=report.period_end,
        reason="file tariff source test",
        enforce_active_check=False,
    )
    run_root = settings.source_refresh_root_path / snapshot_set_id
    raw_dir = run_root / "wb_tariffs"
    raw_dir.mkdir(parents=True)
    run.root_dir = str(run_root)
    raw_payload = {"box": {}, "pallet": {}}
    flat_payload = {"box": rows, "pallet": []}
    raw_path = raw_dir / "tariffs.raw.json"
    flat_path = raw_dir / "tariffs.flat.json"
    raw_path.write_text(json.dumps(raw_payload), encoding="utf-8")
    flat_path.write_text(json.dumps(flat_payload), encoding="utf-8")
    results = [
        {
            "wbCabinetId": cabinet_id,
            "pageIndex": 20260406,
            "targetDate": "2026-04-06",
            "status": "loaded",
            "ok": True,
            "rowCount": len(rows),
            "rawPayloadHash": source_refresh._hash_payload(raw_payload),
            "flatPayloadHash": source_refresh._hash_payload(flat_payload),
            "outputFile": raw_path.name,
            "flatOutputFile": flat_path.name,
        }
    ]
    (raw_dir / "manifest.json").write_text(
        json.dumps({"results": results}),
        encoding="utf-8",
    )
    collection = repository.add_source_refresh_collection(
        db,
        run,
        source_type="wb_tariffs",
        source_label="WB tariffs",
        required=False,
        status="loaded",
        snapshot_hash=source_refresh._hash_payload(results),
        row_count=len(rows),
        raw_path=str(raw_dir),
        payload={
            "results": results,
            "factorSnapshotDate": "2026-07-21",
            "rowPersistence": {
                "status": "file_authoritative",
                "rawFilesAuthoritative": True,
            },
        },
    )
    source_refresh._attach_collection_raw_integrity(
        collection,
        source_root=settings.source_refresh_root_path,
    )
    assert collection.payload["rawIntegrity"]["status"] == "verified"
    return run, collection, flat_path


def _route_source_row(
    *,
    srid: str = "route-order-1",
    nm_id: str = "1001",
    warehouse: str = "Склад A",
    region: str = "Регион A",
) -> dict[str, object]:
    return {
        "srid": srid,
        "g_number": "safe-order-group",
        "sale_id": "safe-sale",
        "nm_id": nm_id,
        "barcode": "BAR-1",
        "sale_date": "2026-04-06T10:00:00",
        "last_change_date": "2026-04-06T11:00:00",
        "warehouse_name": warehouse,
        "country_name": "Страна",
        "oblast_okrug_name": "Округ",
        "region_name": region,
    }


def _goods_return_source_row(
    *,
    srid: str = "return-srid-1",
    nm_id: str = "1001",
    reason: str | None = "Не подошёл размер",
) -> dict[str, object]:
    return {
        "srid": srid,
        "order_id": "assembly-safe-1",
        "nm_id": nm_id,
        "barcode": "BAR-1",
        "reason": reason,
        "status": "returned",
        "return_type": "seller_return",
    }


def _add_goods_return_snapshot(
    db,
    report,
    *,
    settings: WebSettings,
    snapshot_set_id: str,
    cabinet_id: str,
    rows: list[dict[str, object]],
    file_authoritative: bool,
):
    run = repository.create_source_refresh_run(
        db,
        tenant_id=report.tenant_id,
        client_id=report.client_id,
        mode="full",
        credential_source="tenant",
        dry_run=False,
        snapshot_set_id=snapshot_set_id,
        period_start=report.period_start,
        period_end=report.period_end,
        reason="goods-return source test",
        enforce_active_check=False,
    )
    run_root = settings.source_refresh_root_path / snapshot_set_id
    raw_dir = run_root / "wb_goods_return"
    raw_dir.mkdir(parents=True)
    run.root_dir = str(run_root)
    raw_payload = {
        "report": [
            {
                "srid": row["srid"],
                "orderId": row["order_id"],
                "nmId": int(str(row["nm_id"])),
                "barcode": row["barcode"],
                "reason": row["reason"],
                "status": row["status"],
                "returnType": row["return_type"],
            }
            for row in rows
        ]
    }
    raw_path = raw_dir / "goods-return.raw.json"
    flat_path = raw_dir / "goods-return.flat.json"
    raw_path.write_text(json.dumps(raw_payload), encoding="utf-8")
    flat_path.write_text(json.dumps(rows), encoding="utf-8")
    results = [
        {
            "sellerAccountId": "WB_ACCOUNT_SAFE",
            "accountName": "Кабинет",
            "wbCabinetId": cabinet_id,
            "pageIndex": 1,
            "status": "loaded",
            "ok": True,
            "rowCount": len(rows),
            "statusCode": 200,
            "coverageStart": report.period_start.isoformat(),
            "coverageEnd": report.period_end.isoformat(),
            "rawPayloadHash": source_refresh._hash_payload(raw_payload),
            "flatPayloadHash": source_refresh._hash_payload(rows),
            "outputFile": raw_path.name,
            "flatOutputFile": flat_path.name,
            "error": "",
        }
    ]
    (raw_dir / "manifest.json").write_text(
        json.dumps({"results": results}),
        encoding="utf-8",
    )
    payload: dict[str, object] = {
        "results": results,
        "coverageStart": report.period_start.isoformat(),
        "coverageEnd": report.period_end.isoformat(),
    }
    if file_authoritative:
        payload["rowPersistence"] = {
            "status": "file_authoritative",
            "rawFilesAuthoritative": True,
        }
    collection = repository.add_source_refresh_collection(
        db,
        run,
        source_type="wb_goods_return",
        source_label="WB goods return reasons",
        required=False,
        status="loaded",
        snapshot_hash=source_refresh._hash_payload(results),
        row_count=len(rows),
        raw_path=str(raw_dir),
        payload=payload,
    )
    source_refresh._attach_collection_raw_integrity(
        collection,
        source_root=settings.source_refresh_root_path,
    )
    assert collection.payload["rawIntegrity"]["status"] == "verified"
    if not file_authoritative:
        for row_number, row in enumerate(rows, 1):
            repository.add_source_snapshot_row(
                db,
                collection,
                row_number=row_number,
                raw_payload_hash=source_refresh._hash_payload(row),
                source_row_id=f"goods-return-{row_number}",
                wb_cabinet_id=cabinet_id,
                row_payload=row,
            )
    return run, collection, flat_path


def _add_route_snapshot(
    db,
    report,
    *,
    settings: WebSettings,
    snapshot_set_id: str,
    cabinet_id: str,
    rows: list[dict[str, object]],
    file_authoritative: bool,
):
    run = repository.create_source_refresh_run(
        db,
        tenant_id=report.tenant_id,
        client_id=report.client_id,
        mode="full",
        credential_source="tenant",
        dry_run=False,
        snapshot_set_id=snapshot_set_id,
        period_start=report.period_start,
        period_end=report.period_end,
        reason="route source test",
        enforce_active_check=False,
    )
    run_root = settings.source_refresh_root_path / snapshot_set_id
    raw_dir = run_root / "wb_supplier_sales"
    raw_dir.mkdir(parents=True)
    run.root_dir = str(run_root)
    raw_payload = [
        {
            "srid": row["srid"],
            "nmId": int(str(row["nm_id"])),
            "warehouseName": row["warehouse_name"],
            "countryName": row["country_name"],
            "oblastOkrugName": row["oblast_okrug_name"],
            "regionName": row["region_name"],
        }
        for row in rows
    ]
    raw_path = raw_dir / "supplier-sales.raw.json"
    flat_path = raw_dir / "supplier-sales.flat.json"
    raw_path.write_text(json.dumps(raw_payload), encoding="utf-8")
    flat_path.write_text(json.dumps(rows), encoding="utf-8")
    results = [
        {
            "sellerAccountId": "WB_ACCOUNT_SAFE",
            "accountName": "Кабинет",
            "wbCabinetId": cabinet_id,
            "pageIndex": 1,
            "status": "loaded",
            "ok": True,
            "rowCount": len(rows),
            "statusCode": 200,
            "rawPayloadHash": source_refresh._hash_payload(raw_payload),
            "flatPayloadHash": source_refresh._hash_payload(rows),
            "outputFile": raw_path.name,
            "flatOutputFile": flat_path.name,
            "error": "",
        }
    ]
    (raw_dir / "manifest.json").write_text(
        json.dumps({"results": results}),
        encoding="utf-8",
    )
    payload: dict[str, object] = {
        "results": results,
        "coverageStart": report.period_start.isoformat(),
        "coverageEnd": report.period_end.isoformat(),
        "factorSnapshotDate": "2026-07-21",
    }
    if file_authoritative:
        payload["rowPersistence"] = {
            "status": "file_authoritative",
            "rawFilesAuthoritative": True,
        }
    collection = repository.add_source_refresh_collection(
        db,
        run,
        source_type="wb_supplier_sales",
        source_label="WB supplier sales routes",
        required=False,
        status="loaded",
        snapshot_hash=source_refresh._hash_payload(results),
        row_count=len(rows),
        raw_path=str(raw_dir),
        payload=payload,
    )
    source_refresh._attach_collection_raw_integrity(
        collection,
        source_root=settings.source_refresh_root_path,
    )
    assert collection.payload["rawIntegrity"]["status"] == "verified"
    if not file_authoritative:
        for row_number, row in enumerate(rows, 1):
            repository.add_source_snapshot_row(
                db,
                collection,
                row_number=row_number,
                raw_payload_hash=source_refresh._hash_payload(row),
                source_row_id=f"route-{row_number}",
                wb_cabinet_id=cabinet_id,
                row_payload=row,
            )
    return run, collection, flat_path


def _measurement_source_row(source_type: str) -> dict[str, object]:
    common: dict[str, object] = {
        "nm_id": "1001",
        "dim_id": "dimension-event-safe",
        "volume": "2.5",
        "width": "10",
        "length": "25",
        "height": "10",
    }
    if source_type == "wb_measurement_penalties":
        return {
            **common,
            "volume_sup": "2",
            "width_sup": "10",
            "length_sup": "20",
            "height_sup": "10",
            "prc_over": "125",
            "dt_bonus": "2026-04-07T10:00:00Z",
            "is_valid": True,
            "is_valid_dt": "2026-04-07T11:00:00Z",
            "penalty_amount": "10",
            "reversal_amount": "0",
        }
    return {**common, "dt": "2026-04-07T09:00:00Z"}


def _add_measurement_snapshot(
    db,
    report,
    *,
    settings: WebSettings,
    snapshot_set_id: str,
    cabinet_id: str,
    source_type: str,
    rows: list[dict[str, object]],
    file_authoritative: bool,
):
    run = repository.create_source_refresh_run(
        db,
        tenant_id=report.tenant_id,
        client_id=report.client_id,
        mode="full",
        credential_source="tenant",
        dry_run=False,
        snapshot_set_id=snapshot_set_id,
        period_start=report.period_start,
        period_end=report.period_end,
        reason="measurement source test",
        enforce_active_check=False,
    )
    run_root = settings.source_refresh_root_path / snapshot_set_id
    raw_dir = run_root / source_type
    raw_dir.mkdir(parents=True)
    run.root_dir = str(run_root)
    raw_payload = {
        "dateFrom": f"{report.period_start.isoformat()}T00:00:00Z",
        "dateTo": f"{report.period_end.isoformat()}T23:59:59Z",
        "reports": rows,
        "total": len(rows),
    }
    raw_path = raw_dir / "measurements.raw.json"
    flat_path = raw_dir / "measurements.flat.json"
    raw_path.write_text(json.dumps(raw_payload), encoding="utf-8")
    flat_path.write_text(json.dumps(rows), encoding="utf-8")
    results = [
        {
            "sellerAccountId": "WB_ACCOUNT_SAFE",
            "accountName": "Кабинет",
            "wbCabinetId": cabinet_id,
            "pageIndex": 1,
            "status": "loaded" if rows else "empty_expected",
            "ok": True,
            "rowCount": len(rows),
            "providerTotal": len(rows),
            "statusCode": 200,
            "rawPayloadHash": source_refresh._hash_payload(raw_payload),
            "flatPayloadHash": source_refresh._hash_payload(rows),
            "outputFile": raw_path.name,
            "flatOutputFile": flat_path.name,
            "error": "",
        }
    ]
    factor_snapshot_at = "2026-07-21T12:00:00+00:00"
    metadata = {
        "source": source_type,
        "periodStart": report.period_start.isoformat(),
        "periodEnd": report.period_end.isoformat(),
        "coverageStart": report.period_start.isoformat(),
        "coverageEnd": report.period_end.isoformat(),
        "factorSnapshotAt": factor_snapshot_at,
    }
    (raw_dir / "manifest.json").write_text(
        json.dumps({**metadata, "results": results}),
        encoding="utf-8",
    )
    payload: dict[str, object] = {
        "results": results,
        **{key: value for key, value in metadata.items() if key != "source"},
    }
    if file_authoritative:
        payload["rowPersistence"] = {
            "status": "file_authoritative",
            "rawFilesAuthoritative": True,
        }
    collection = repository.add_source_refresh_collection(
        db,
        run,
        source_type=source_type,
        source_label="WB measurements",
        required=False,
        status="loaded",
        snapshot_hash=source_refresh._hash_payload(results),
        row_count=len(rows),
        raw_path=str(raw_dir),
        payload=payload,
    )
    source_refresh._attach_collection_raw_integrity(
        collection,
        source_root=settings.source_refresh_root_path,
    )
    assert collection.payload["rawIntegrity"]["status"] == "verified"
    if not file_authoritative:
        for row_number, row in enumerate(rows, 1):
            persisted = {
                **row,
                "marketplace": "wb",
                "measurement_source_type": source_type,
                "source_output_file": flat_path.name,
            }
            repository.add_source_snapshot_row(
                db,
                collection,
                row_number=row_number,
                raw_payload_hash=source_refresh._hash_payload(persisted),
                source_row_id=f"measurement-{row_number}",
                wb_cabinet_id=cabinet_id,
                row_payload=persisted,
            )
    return run, collection, flat_path


def _save_encrypted_integrations(db, *, settings: WebSettings, user) -> None:
    wb_secret = (
        '{"accounts":[{"sellerAccountId":"WB_ACCOUNT_9",'
        '"accountName":"Кабинет","apiKey":"wb-token-secret"}]}'
    )
    repository.save_tenant_integration(
        db,
        user=user,
        tenant_id="shumeyko",
        provider="wb_api",
        secret=wb_secret,
        secret_storage=integrations.secret_storage_payload(settings, wb_secret).payload,
    )
    onec_secret = _onec_secret()
    repository.save_tenant_integration(
        db,
        user=user,
        tenant_id="shumeyko",
        provider="onec_readonly",
        secret=onec_secret,
        secret_storage=integrations.secret_storage_payload(
            settings,
            onec_secret,
        ).payload,
    )
    db.commit()


def _onec_secret() -> str:
    return (
        '{"baseUrl":"https://onec.example/odata/standard.odata",'
        '"username":"readonly","password":"onec-secret","verifySsl":false}'
    )


def _fake_wb_finance_exporter(seen: dict[str, object]):
    def fake(settings, output_dir: Path, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        seen["wb_api_key"] = settings.accounts[0].api_key
        seen["wb_finance_period_start"] = _kwargs.get("period_start")
        seen["wb_finance_period_end"] = _kwargs.get("period_end")
        output_path = output_dir / "wb.raw.json"
        output_path.write_text(
            json.dumps(
                [
                    {
                        "rrdId": 987,
                        "srid": "srid-1",
                        "orderUid": "order-1",
                        "nmId": 1001,
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return [
            WbFinancePageResult(
                seller_account_id=settings.accounts[0].seller_account_id,
                account_name=settings.accounts[0].account_name,
                page_index=1,
                ok=True,
                status="ok",
                row_count=1,
                rrd_id_start=0,
                rrd_id_next=100,
                raw_payload_hash="wb-hash",
                output_path=output_path,
                status_code=200,
            ),
            WbFinancePageResult(
                seller_account_id=settings.accounts[0].seller_account_id,
                account_name=settings.accounts[0].account_name,
                page_index=2,
                ok=True,
                status="no_data",
                row_count=0,
                rrd_id_start=100,
                status_code=204,
            ),
        ]

    return fake


def _fake_wb_product_cards_exporter(seen: dict[str, object]):
    def fake(settings, output_dir: Path, **kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        account = settings.accounts[0]
        seen["wb_content_account"] = account.seller_account_id
        seen["wb_content_request_delay_seconds"] = kwargs["request_delay_seconds"]
        raw_path = output_dir / "wb-cards.raw.json"
        flat_path = output_dir / "wb-cards.flat.json"
        raw_path.write_text(
            json.dumps({"cards": [{"nmID": 1001, "vendorCode": "A-1"}]}),
            encoding="utf-8",
        )
        flat_path.write_text(
            json.dumps(
                [
                    {
                        "seller_account_id": account.seller_account_id,
                        "account_name": account.account_name,
                        "cards_source": "active",
                        "nm_id": 1001,
                        "vendor_code": "A-1",
                        "barcode": "111",
                        "title": "Товар",
                    }
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return [
            WbProductCardsPageResult(
                seller_account_id=account.seller_account_id,
                account_name=account.account_name,
                cards_source="active",
                page_index=1,
                ok=True,
                card_count=1,
                flat_row_count=1,
                raw_payload_hash="wb-cards-hash",
                output_path=raw_path,
                flat_output_path=flat_path,
                status_code=200,
            )
        ]

    return fake


def _fake_wb_failure_exporter(_settings, _output_dir: Path, **_kwargs):
    return [
        WbFinancePageResult(
            seller_account_id="WB_ACCOUNT_9",
            account_name="Кабинет",
            page_index=1,
            ok=False,
            status="rate_limited",
            row_count=0,
            rrd_id_start=0,
            status_code=429,
            error="HTTP 429",
        )
    ]


def _fake_wb_empty_first_page_exporter(_settings, _output_dir: Path, **_kwargs):
    return [
        WbFinancePageResult(
            seller_account_id="WB_ACCOUNT_9",
            account_name="Кабинет",
            page_index=1,
            ok=True,
            status="ok",
            row_count=0,
            rrd_id_start=0,
            status_code=200,
        )
    ]


def _fake_ozon_cash_flow_exporter(seen: dict[str, object]):
    def fake(settings, output_dir: Path, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        account = settings.accounts[0]
        seen["ozon_client_id"] = account.client_id
        seen["ozon_api_key"] = account.api_key
        output_path = output_dir / "ozon.raw.json"
        output_path.write_text(
            json.dumps(
                {
                    "result": {
                        "items": [
                            {
                                "operation_id": "op-ozon-1",
                                "offer_id": "A-1",
                                "price": "1000",
                            }
                        ]
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return [
            OzonPageResult(
                source_type="ozon_finance_cash_flow",
                seller_account_id=account.seller_account_id,
                account_name=account.account_name,
                page_index=1,
                ok=True,
                status="ok",
                row_count=1,
                raw_payload_hash="ozon-hash",
                output_path=output_path,
                status_code=200,
                source_endpoint="/v1/finance/cash-flow-statement/list",
            )
        ]

    return fake


def _fake_ozon_products_exporter(seen: dict[str, object]):
    def fake(settings, output_dir: Path, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        account = settings.accounts[0]
        seen["ozon_products_client_id"] = account.client_id
        output_path = output_dir / "ozon-products.raw.json"
        output_path.write_text(
            json.dumps(
                {
                    "result": {
                        "items": [
                            {
                                "offer_id": "A-1",
                                "product_id": "product-1",
                                "sku": "12345",
                            }
                        ]
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return [
            OzonPageResult(
                source_type="ozon_products_report",
                seller_account_id=account.seller_account_id,
                account_name=account.account_name,
                page_index=1,
                ok=True,
                status="ok",
                row_count=1,
                raw_payload_hash="ozon-products-hash",
                output_path=output_path,
                status_code=200,
                source_endpoint="report_file",
            )
        ]

    return fake


def _fake_ozon_realization_exporter(seen: dict[str, object]):
    def fake(settings, output_dir: Path, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        account = settings.accounts[0]
        seen["ozon_realization_client_id"] = account.client_id
        output_path = output_dir / "ozon-realization.raw.json"
        output_path.write_text(
            json.dumps(
                {
                    "result": {
                        "rows": [
                            {
                                "offer_id": "A-1",
                                "seller_account_id": "raw-should-not-win",
                                "source_page_index": 99,
                                "sale_qty": "2",
                                "sale_amount": "1000",
                            }
                        ]
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return [
            OzonPageResult(
                source_type="ozon_realization",
                seller_account_id=account.seller_account_id,
                account_name=account.account_name,
                page_index=1,
                ok=True,
                status="ok",
                row_count=1,
                raw_payload_hash="ozon-realization-hash",
                output_path=output_path,
                status_code=200,
                source_endpoint="/v2/finance/realization",
            )
        ]

    return fake


def _fake_ozon_extra_exporter(
    seen: dict[str, object],
    *,
    source_type: str,
    seen_key: str,
    endpoint: str,
):
    def fake(settings, output_dir: Path, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        account = settings.accounts[0]
        seen[seen_key] = account.client_id
        output_path = output_dir / f"{source_type}.raw.json"
        output_path.write_text(
            json.dumps(
                {
                    "result": {
                        "items": [
                            {
                                "id": f"{source_type}-1",
                                "amount": "100",
                            }
                        ]
                    }
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return [
            OzonPageResult(
                source_type=source_type,
                seller_account_id=account.seller_account_id,
                account_name=account.account_name,
                page_index=1,
                ok=True,
                status="ok",
                row_count=1,
                raw_payload_hash=f"{source_type}-hash",
                output_path=output_path,
                status_code=200,
                source_endpoint=endpoint,
            )
        ]

    return fake


def _fake_report_list_exporter(seen: dict[str, object]):
    def fake(settings, output_dir: Path, **_kwargs):
        output_dir.mkdir(parents=True, exist_ok=True)
        seen["report_list_account"] = settings.accounts[0].seller_account_id
        output_path = output_dir / "report-list.raw.json"
        output_path.write_text(
            json.dumps([{"reportId": 713660329, "currency": "RUB"}]),
            encoding="utf-8",
        )
        return [
            WbSalesReportListPageResult(
                seller_account_id=settings.accounts[0].seller_account_id,
                account_name=settings.accounts[0].account_name,
                page_index=1,
                ok=True,
                status="ok",
                row_count=1,
                offset=0,
                raw_payload_hash="report-list-hash",
                output_path=output_path,
                status_code=200,
            )
        ]

    return fake


def _fake_report_list_failure_exporter(_settings, _output_dir: Path, **_kwargs):
    return [
        WbSalesReportListPageResult(
            seller_account_id="WB_ACCOUNT_9",
            account_name="Кабинет",
            page_index=1,
            ok=False,
            status="rate_limited",
            row_count=0,
            offset=0,
            status_code=429,
            error="HTTP 429",
        )
    ]


def _fake_onec_exporter(seen: dict[str, object]):
    def fake(
        settings,
        collections,
        output_dir: Path,
        *,
        top: int,
        max_pages: int,
        **kwargs,
    ):
        output_dir.mkdir(parents=True, exist_ok=True)
        seen["onec_username"] = settings.username
        seen["onec_password"] = settings.password
        seen["onec_top"] = top
        seen["onec_max_pages"] = max_pages
        seen["onec_period_start"] = kwargs.get("period_start")
        seen["onec_period_end"] = kwargs.get("period_end")
        seen["onec_resume_from_dir"] = kwargs.get("resume_from_dir")
        results = []
        for item in collections:
            output_path = output_dir / f"{item.sample_id}.raw.json"
            row = {
                "Ref_Key": f"{item.sample_id}-ref",
                "LineNumber": 1,
                "Name": item.collection_name,
            }
            if item.sample_id == "commissioner_reports":
                row.update(
                    {
                        "Организация_Key": "organization-1",
                        "Запасы": [
                            {
                                "Номенклатура_Key": "item-1",
                                "Количество": 1,
                                "Всего": 100,
                            }
                        ],
                        "ЗапасыВозвраты": [],
                    }
                )
            output_path.write_text(
                json.dumps(
                    {
                        "value": [row],
                        "_source_pages": [
                            {
                                "page_index": 1,
                                "skip": 0,
                                "row_count": 1,
                                "status_code": 200,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            results.append(
                OnecSampleExportResult(
                    sample_id=item.sample_id,
                    collection_name=item.collection_name,
                    ok=True,
                    row_count=1,
                    page_count=1,
                    raw_payload_hash=f"{item.sample_id}-hash",
                    output_path=output_path,
                    status_code=200,
                    detail_mode=item.detail_mode,
                )
            )
        return results

    return fake


def _fake_workbook_builder(args) -> SimpleNamespace:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(b"xlsx")
    assert args.wb_finance_dir is not None
    assert args.onec_dir is not None
    assert args.onec_opiu_config is None
    assert args.tax_profiles is not None
    assert args.sku_mappings is not None
    return SimpleNamespace(output_path=args.output)


def _builder_should_not_run(_args) -> None:
    raise AssertionError("workbook builder should not run")


assert ONEC_REFRESH_COLLECTIONS
