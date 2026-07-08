from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from openpyxl import Workbook

from wb_unit_economics.onec_odata import OnecSampleExportResult
from wb_unit_economics.ozon import OzonPageResult
from wb_unit_economics.wb_finance import (
    WbFinancePageResult,
    WbSalesReportListPageResult,
)
from wb_unit_economics.web import integrations, repository
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import (
    ReportArtifact,
    ReportRun,
    SourceLoad,
    SourceRefreshCollection,
    SourceSnapshotRow,
    TenantIntegration,
    WbCabinet,
)
from wb_unit_economics.web.repository import import_dashboard_payload, upsert_user
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import (
    ONEC_REFRESH_COLLECTIONS,
    SourceRefreshService,
    _read_ozon_rows,
    _safe_error,
)


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
        snapshot_rows = db.query(SourceSnapshotRow).all()

    assert payload["status"] == "report_created"
    assert seen["wb_api_key"] == "wb-token-secret"
    assert seen["onec_username"] == "readonly"
    assert seen["onec_password"] == "onec-secret"
    assert new_report is not None
    assert {item.source_type for item in source_loads} >= {
        "wb_finance_detail",
        "wb_sales_report_list",
        "sku_mapping",
        "onec_sales_register",
    }
    assert {item.source_type for item in snapshot_rows} >= {
        "wb_finance_detail",
        "wb_sales_report_list",
        "sku_mapping",
        "onec_sales_register",
    }
    assert any(
        item.source_type == "wb_finance_detail" and item.source_row_id == "987"
        for item in snapshot_rows
    )
    assert any(
        item.source_type == "wb_sales_report_list"
        and item.source_row_id == "713660329"
        for item in snapshot_rows
    )
    assert any(
        item.source_type == "onec_sales_register"
        and item.source_row_id == "sales_register-ref"
        for item in snapshot_rows
    )


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

    assert payload["status"] == "source_loaded"
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


def test_source_refresh_ozon_only_skips_wb_and_does_not_publish_report(
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

    assert payload["status"] == "source_loaded"
    assert payload["newReportRunId"] is None
    assert [item.id for item in reports] == ["report-1"]
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

    assert payload["status"] == "report_created"
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


def test_source_refresh_db_first_branch_publishes_report_and_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import scripts.rebuild_report_from_sources as rebuild_script

    seen: dict[str, object] = {}
    settings, session_factory, user, report, _mapping_dir = _source_refresh_context(
        tmp_path
    )
    settings.db_first_reports_enabled = True

    def fake_build_db_first_payload(args):
        seen["builder_used"] = True
        assert args.wb_finance_dir is not None
        assert args.onec_dir is not None
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

    assert payload["status"] == "report_created"
    assert seen["builder_used"] is True
    assert new_report is not None
    assert new_report.lineage_type == "db_first_report_marts"
    assert new_report.publication_status == "published"
    assert new_report.is_current is True
    assert old_report is not None
    assert old_report.is_current is False
    artifact_types = {item.artifact_type for item in artifacts}
    assert {"excel", "csv", "html", "docx"} <= artifact_types
    assert all(Path(item.path).exists() for item in artifacts)
    assert all(item.sha256 for item in artifacts)


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

    def fake_build_db_first_payload(_args):
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
        draft_reports = (
            db.query(ReportRun).filter(ReportRun.id != report.id).all()
        )

    assert payload["status"] == "failed"
    assert payload["newReportRunId"] is None
    assert payload["errorMessage"] == "RuntimeError: post build attach failed"
    assert old_report is not None
    assert old_report.is_current is True
    assert draft_reports
    assert all(item.publication_status == "draft" for item in draft_reports)
    assert all(item.is_current is False for item in draft_reports)


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
    assert payload["status"] == "report_created"
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
    assert payload["status"] == "failed"
    assert mapping["status"] == "failed"
    assert mapping["errorMessage"] == "mapping_source_missing"


def test_source_refresh_stale_mapping_marks_report_needs_review(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}
    settings, session_factory, user, report, mapping_dir = _source_refresh_context(
        tmp_path,
        mapping_stale_days=1,
    )
    old_timestamp = (
        datetime.now().timestamp() - timedelta(days=10).total_seconds()
    )
    mapping_file = mapping_dir / "mapping.csv"
    os.utime(mapping_file, (old_timestamp, old_timestamp))
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_report_list_exporter=_fake_report_list_exporter(seen),
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
    assert mapping["status"] == "stale"


def test_source_refresh_daily_stale_mapping_returns_needs_review(
    tmp_path: Path,
) -> None:
    seen: dict[str, object] = {}
    settings, session_factory, user, report, mapping_dir = _source_refresh_context(
        tmp_path,
        mapping_stale_days=1,
    )
    old_timestamp = (
        datetime.now().timestamp() - timedelta(days=10).total_seconds()
    )
    mapping_file = mapping_dir / "mapping.csv"
    os.utime(mapping_file, (old_timestamp, old_timestamp))
    with session_factory() as db:
        user, report = _session_user_report(db, user, report)
        _save_encrypted_integrations(db, settings=settings, user=user)
        service = SourceRefreshService(
            settings,
            wb_finance_exporter=_fake_wb_finance_exporter(seen),
            wb_report_list_exporter=_fake_report_list_exporter(seen),
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


def test_source_refresh_onec_only_does_not_publish_report(
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
            onec_exporter=_fake_onec_exporter(seen),
            workbook_builder=_builder_should_not_run,
            dashboard_payload_builder=lambda _path: minimal_payload(),
        )
        payload = service.run(
            db,
            tenant_id="shumeyko",
            mode="onec-only",
            user=user,
            source_report=report,
        )
        reports = db.query(ReportRun).filter_by(tenant_id="shumeyko").all()

    assert payload["status"] == "source_loaded"
    assert payload["newReportRunId"] is None
    assert [item.id for item in reports] == ["report-1"]


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


def test_source_snapshot_rows_are_idempotent(tmp_path: Path) -> None:
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
        second = repository.add_source_snapshot_row(
            db,
            collection,
            row_number=1,
            raw_payload_hash="hash-1",
            row_payload={"rrdId": 1},
            source_row_id="1",
        )
        count = db.query(SourceSnapshotRow).count()

    assert first.id == second.id
    assert count == 1


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
                source_endpoint="/v1/report/products/info",
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
    def fake(settings, collections, output_dir: Path, *, top: int, max_pages: int):
        output_dir.mkdir(parents=True, exist_ok=True)
        seen["onec_username"] = settings.username
        seen["onec_password"] = settings.password
        seen["onec_top"] = top
        seen["onec_max_pages"] = max_pages
        results = []
        for item in collections:
            output_path = output_dir / f"{item.sample_id}.raw.json"
            output_path.write_text(
                json.dumps(
                    {
                        "value": [
                            {
                                "Ref_Key": f"{item.sample_id}-ref",
                                "LineNumber": 1,
                                "Name": item.collection_name,
                            }
                        ],
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
    return SimpleNamespace(output_path=args.output)


def _builder_should_not_run(_args) -> None:
    raise AssertionError("workbook builder should not run")


assert ONEC_REFRESH_COLLECTIONS
