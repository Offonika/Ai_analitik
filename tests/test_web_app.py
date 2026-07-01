from __future__ import annotations

from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from openpyxl import Workbook

from wb_unit_economics.web import integrations, repository
from wb_unit_economics.web.ai import AiAnalyst
from wb_unit_economics.web.app import create_app
from wb_unit_economics.web.dashboard_payload import (
    analysis_period_text,
    document_reconciliation_rows,
    period_boundaries_from_label,
    period_label_from_value,
)
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import TenantIntegration
from wb_unit_economics.web.refresh import AutoRefreshBusyError, OnecAutoRefreshService
from wb_unit_economics.web.repository import import_dashboard_payload, upsert_user
from wb_unit_economics.web.settings import WebSettings


def sample_payload() -> dict:
    return {
        "meta": {
            "title": "Кабинет юнит-экономики WB",
            "client": "Шумейко и Партнеры",
            "period": "01.03.2026 - 17.06.2026",
            "reportPeriod": "01.03.2026 - 17.06.2026",
            "periodText": "март, апрель, май, июнь; июнь неполный, по 17.06.2026",
            "periodStatus": "предварительный: июнь неполный",
            "sourceCoverage": "01.03.2026 - 17.06.2026",
            "sourceCoverageStart": "2026-03-01",
            "sourceCoverageEnd": "2026-06-17",
            "methodologyVersion": "Excel MVP / test",
            "generatedAt": "20.06.2026 12:00",
            "sourceWorkbook": "shumeyko_wb_excel_mvp.xlsx",
            "returnReasonLimitation": (
                "Причина возврата не передается текущими источниками"
            ),
        },
        "options": {},
        "monthly": [],
        "expenses": [],
        "unitRows": [
            {
                "id": "unit-1",
                "week": "2026-04-06",
                "month": "Апрель 2026",
                "documentReport": (
                    "Отчет комиссионера · 06.04.2026-12.04.2026 · закрытие 12.04.2026"
                ),
                "wbReportId": "726807272",
                "wbReportDate": "2026-04-13",
                "organization": "Организация A",
                "cabinet": "Кабинет A",
                "product": "Убыточный товар",
                "nmId": "1001",
                "articleWb": "WB-LOSS",
                "article1c": "A-LOSS",
                "barcode": "BAR-LOSS",
                "scheme": "FBO",
                "sales": 20,
                "returns": 8,
                "netQty": 12,
                "returnRate": 0.4,
                "revenueBeforeSpp": 100000,
                "spp": 1000,
                "revenue": 99000,
                "vat": 4714,
                "revenueWithoutVat": 94286,
                "cost": 65000,
                "commission": 10000,
                "logistics": 27000,
                "storage": 3000,
                "acceptance": 0,
                "promotion": 4000,
                "penalties": 0,
                "acquiring": 1200,
                "usn": 990,
                "profitBeforeTax": -9000,
                "profit": -14704,
                "margin": -0.1485,
                "unitProfit": -1225.3,
                "status": "ОК",
                "statusReason": "Данные достаточны для расчета",
                "sppStatus": "ОК",
                "lossClass": "Возвраты + логистика",
                "lossDriver": "Возвраты + логистика",
            },
            {
                "id": "unit-2",
                "week": "2026-06-02",
                "month": "Июнь 2026 (неполный месяц)",
                "documentReport": (
                    "Отчет комиссионера · 01.06.2026-07.06.2026 · закрытие 07.06.2026"
                ),
                "organization": "Организация B",
                "cabinet": "Кабинет B",
                "product": "Товар без себестоимости",
                "nmId": "1003",
                "articleWb": "WB-NOCOST",
                "article1c": "A-NOCOST",
                "barcode": "BAR-NOCOST",
                "scheme": "FBO",
                "sales": 5,
                "returns": 0,
                "netQty": 5,
                "returnRate": 0,
                "revenueBeforeSpp": 20000,
                "spp": 0,
                "revenue": 20000,
                "vat": 952,
                "revenueWithoutVat": 19048,
                "cost": 0,
                "commission": 2000,
                "logistics": 1500,
                "storage": 500,
                "acceptance": 0,
                "promotion": 0,
                "penalties": 0,
                "acquiring": 200,
                "usn": 200,
                "profitBeforeTax": 16000,
                "profit": 14648,
                "margin": 0.7324,
                "unitProfit": 2929.6,
                "status": "Нет себестоимости 1С",
                "statusReason": "Нет действующей себестоимости 1С",
                "sppStatus": "ОК",
                "lossClass": "Нужна проверка данных",
                "lossDriver": "Нет себестоимости 1С",
            },
        ],
        "returns": [],
        "lostSales": [
            {
                "id": "lost-1",
                "cabinet": "Кабинет A",
                "product": "Убыточный товар",
                "article1c": "A-LOSS",
                "barcode": "BAR-LOSS",
                "zeroStockDays": 10,
                "onecStock": 12,
                "onecWarehouses": "Собственный склад: 12",
                "sales": 20,
                "lostUnits": 5,
                "lostRevenue": 25000,
                "lostProfit": 3000,
                "note": "Сверить с 1С",
            }
        ],
        "reconciliation": [],
        "reconciliationMonthly": [
            {
                "month": "Апрель 2026",
                "wb_quantity": 90,
                "onec_quantity": 91,
                "quantity_delta": -1,
                "wb_cogs": 90000,
                "onec_cogs": 91000,
                "cogs_delta": -1000,
                "wb_mp_expenses": 55000,
                "onec_mp_expenses": 53000,
                "mp_expenses_delta": 2000,
                "comment": "Тестовая сверка",
            }
        ],
        "documentReconciliation": [
            {
                "id": "doc-recon-1",
                "status": "OK",
                "payoutStatus": "Нужен источник выплаты 1С",
                "periodStatus": "полный период",
                "documentReport": (
                    "Отчет комиссионера · 06.04.2026-12.04.2026 · закрытие 12.04.2026"
                ),
                "salesPeriod": "2026-04-06 - 2026-04-12",
                "salesPeriodStart": "2026-04-06",
                "salesPeriodEnd": "2026-04-12",
                "expectedDocumentDate": "2026-04-12",
                "documentType": "Отчет комиссионера",
                "cabinet": "Кабинет A",
                "organization": "Организация A",
                "summaryReportId": "SUMMARY-1",
                "weeklySalesReportId": "SUMMARY-1",
                "weeklyBuyoutReportId": "BUYOUT-1",
                "wbReportIds": "726807272",
                "onecDocuments": "DOC-COMMISSIONER-1",
                "onecDocumentTypes": "ОтчетКомиссионера",
                "onecDocumentDates": "2026-04-12",
                "wbSalesQuantity": 22,
                "wbReturnQuantity": 2,
                "wbNetQuantity": 20,
                "onecSalesQuantity": 22,
                "onecReturnQuantity": 2,
                "onecNetQuantity": 20,
                "salesQuantityDelta": 0,
                "returnQuantityDelta": 0,
                "netQuantityDelta": 0,
                "wbQuantity": 20,
                "onecQuantity": 20,
                "quantityDelta": 0,
                "wbAmount": 99000,
                "onecAmount": 99000,
                "amountDelta": 0,
                "buyoutRetailAmountSum": None,
                "buyoutForPaySum": None,
                "buyoutBankPaymentSum": None,
                "onecExpenseInvoiceAmount": None,
                "buyoutRetailDelta": None,
                "buyoutForPayDelta": None,
                "buyoutBankDelta": None,
                "pdfBankPayment": 85000,
                "wbForPaySum": 85000,
                "onecSettlementTotal": 85000,
                "settlementDelta": 0,
                "onecSourceRows": 10,
                "comment": "Документ совпал",
            }
        ],
    }


def ready_payload() -> dict:
    payload = deepcopy(sample_payload())
    payload["meta"] = {
        **payload["meta"],
        "period": "01.04.2026 - 30.04.2026",
        "periodText": "апрель 2026",
        "periodStatus": "",
        "sourceWorkbook": "ready-report.xlsx",
    }
    clean_rows = []
    for row in payload["unitRows"]:
        clean_rows.append(
            {
                **row,
                "month": "Апрель 2026",
                "status": "ОК",
                "statusReason": "Данные достаточны для расчета",
                "lossClass": "Без критичных проблем",
                "lossDriver": "Без критичных проблем",
            }
        )
    clean_rows[1] = {
        **clean_rows[1],
        "cost": 9000,
        "profit": 5648,
        "unitProfit": 1129.6,
    }
    payload["unitRows"] = clean_rows
    return payload


def client_ready_draft_text() -> str:
    return (
        "Ключевой вывод\n"
        "Отчет можно отправлять клиенту после стандартной проверки консультанта.\n\n"
        "Факты\n"
        "- Строки отчета имеют статус ОК.\n\n"
        "Что требует проверки\n"
        "- Дополнительных блокеров по данным нет.\n\n"
        "Ограничения\n"
        "- AI не меняет данные WB/1C и не выполняет отправку клиенту.\n\n"
        "Следующий шаг\n"
        "Передать отчет клиенту."
    )


class FakeAutoRefreshService:
    def __init__(self, workbook_path: Path) -> None:
        self.workbook_path = workbook_path

    def run(self, db, *, user, report, reason, thread_id=None):
        try:
            refresh_run = repository.create_source_refresh_run(
                db,
                tenant_id=report.tenant_id,
                mode="onec-only",
                credential_source="tenant",
                dry_run=False,
                snapshot_set_id="onec-only-test",
                period_start=date(2026, 3, 1),
                period_end=date(2026, 6, 17),
                user=user,
                source_report=report,
                reason=reason,
            )
        except ValueError as exc:
            raise AutoRefreshBusyError(str(exc)) from exc
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="running",
            started_at=repository.security.utcnow(),
            root_dir="data/source_refresh/onec-only-test",
        )
        repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="onec_sales_register",
            source_label="AccumulationRegister_Продажи",
            required=True,
            status="loaded",
            snapshot_hash="hash",
            row_count=7,
            raw_path="data/source_refresh/onec-only-test/onec/sales_register.json",
        )
        repository.update_source_refresh_run(db, refresh_run, status="rebuilding")
        payload = sample_payload()
        payload["meta"] = {
            **payload["meta"],
            "sourceWorkbook": "auto-refresh.xlsx",
            "generatedAt": "20.06.2026 13:00",
        }
        payload["unitRows"][1] = {
            **payload["unitRows"][1],
            "status": "ОК",
            "statusReason": "Себестоимость обновлена из read-only 1С job",
            "cost": 9000,
            "profit": 5648,
        }
        report_id = f"{report.id}-refresh"
        self.workbook_path.parent.mkdir(parents=True, exist_ok=True)
        self.workbook_path.write_bytes(b"auto-xlsx")
        new_report = repository.import_dashboard_payload(
            db,
            payload,
            tenant_id=report.tenant_id,
            tenant_name=report.client_name,
            report_id=report_id,
            source_workbook_path=str(self.workbook_path),
        )
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="report_created",
            workbook_path=str(self.workbook_path),
            new_report_run_id=new_report.id,
            finished_at=repository.security.utcnow(),
        )
        repository.audit(
            db,
            action="source_refresh_report_created",
            user=user,
            tenant_id=report.tenant_id,
            entity_type="source_refresh_run",
            entity_id=refresh_run.id,
            payload={
                "source_report_run_id": report.id,
                "new_report_run_id": new_report.id,
                "status": "report_created",
            },
        )
        result = repository.source_refresh_run_payload(refresh_run)
        result["jobType"] = "source_refresh"
        result["sourceRefreshRunId"] = result["id"]
        if thread_id:
            result["threadId"] = thread_id
        return result


def make_client(
    tmp_path: Path,
    *,
    payload: dict | None = None,
    settings_overrides: dict | None = None,
    auto_refresh_service=None,
) -> TestClient:
    export = tmp_path / "reports" / "shumeyko_wb_excel_mvp.xlsx"
    export.parent.mkdir()
    export.write_bytes(b"xlsx")
    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        import_dashboard_payload(
            db,
            payload or sample_payload(),
            tenant_id="shumeyko",
            tenant_name="Шумейко и Партнеры",
            report_id="report-1",
            source_workbook_path=str(export),
        )
        upsert_user(
            db,
            email="admin@example.com",
            password="secret",
            tenant_id="shumeyko",
            role="admin",
        )
        import_dashboard_payload(
            db,
            sample_payload(),
            tenant_id="other",
            tenant_name="Другой клиент",
            report_id="other-report",
            source_workbook_path=str(export),
        )
        db.commit()
    settings_values = {
        "database_url": f"sqlite:///{tmp_path / 'web.sqlite3'}",
        "cookie_secure": False,
        "allowed_export_root": str(export.parent),
        "openai_api_key": "",
    }
    settings_values.update(settings_overrides or {})
    settings = WebSettings(**settings_values)
    app = create_app(
        settings=settings,
        session_factory=session_factory,
        auto_refresh_service=auto_refresh_service,
    )
    return TestClient(app)


def login(client: TestClient) -> None:
    login_as(client, "admin@example.com", "secret")


def login_as(client: TestClient, email: str, password: str) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert response.status_code == 200


def test_import_dashboard_payload_replaces_existing_report_rows(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        import_dashboard_payload(
            db,
            sample_payload(),
            tenant_id="shumeyko",
            tenant_name="Шумейко и Партнеры",
            report_id="report-1",
        )
        db.commit()
        replacement = deepcopy(sample_payload())
        replacement["unitRows"] = [replacement["unitRows"][0]]
        replacement["lostSales"] = []
        replacement["documentReconciliation"] = []
        import_dashboard_payload(
            db,
            replacement,
            tenant_id="shumeyko",
            tenant_name="Шумейко и Партнеры",
            report_id="report-1",
        )
        db.commit()
        report = db.get(repository.ReportRun, "report-1")
        assert report is not None
        summary = repository.report_full_payload(db, report)

    assert len(summary["unitRows"]) == 1
    assert (
        summary["unitRows"][0]["documentReport"]
        == "Отчет комиссионера · 06.04.2026-12.04.2026 · закрытие 12.04.2026"
    )
    assert summary["unitRows"][0]["wbReportId"] == "726807272"
    assert summary["unitRows"][0]["wbReportDate"] == "2026-04-13"
    assert summary["meta"]["sourceCoverage"] == "01.03.2026 - 17.06.2026"
    assert summary["meta"]["sourceCoverageStart"] == "2026-03-01"
    assert summary["meta"]["sourceCoverageEnd"] == "2026-06-17"
    assert len(summary["liquidityRows"]) == 1
    assert summary["lostSales"] == []
    assert summary["reconciliationMonthly"][0]["wb_quantity"] == 90.0
    assert summary["reconciliationMonthly"][0]["onec_quantity"] == 91.0
    assert summary["reconciliationMonthly"][0]["quantity_delta"] == -1.0
    assert summary["documentReconciliation"] == []


def test_multi_client_backfill_is_idempotent(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        import_dashboard_payload(
            db,
            sample_payload(),
            tenant_id="shumeyko",
            tenant_name="Шумейко и Партнеры",
            report_id="report-1",
        )
        client = db.query(repository.Client).filter_by(tenant_id="shumeyko").one()
        client.name = "Реальный клиент"
        db.commit()

    init_db(engine)
    init_db(engine)

    with session_factory() as db:
        client = db.query(repository.Client).filter_by(tenant_id="shumeyko").one()
        report = db.get(repository.ReportRun, "report-1")
        unit_rows = db.query(repository.ReportUnitRow).all()
        lost_rows = db.query(repository.ReportLostSalesRow).all()
        document_rows = db.query(repository.ReportDocumentReconciliationRow).all()

        assert client.name == "Реальный клиент"
        assert db.query(repository.Client).filter_by(tenant_id="shumeyko").count() == 1
        company_count = (
            db.query(repository.ClientCompany).filter_by(client_id="shumeyko").count()
        )
        cabinet_count = (
            db.query(repository.WbCabinet).filter_by(client_id="shumeyko").count()
        )
        assert company_count == 2
        assert cabinet_count == 2

    assert report is not None
    assert report.client_id == "shumeyko"
    assert {row.client_id for row in unit_rows} == {"shumeyko"}
    assert all(row.client_company_id for row in unit_rows)
    assert all(row.wb_cabinet_id for row in unit_rows)
    assert {row.client_id for row in lost_rows} == {"shumeyko"}
    assert all(row.wb_cabinet_id for row in lost_rows)
    assert {row.client_id for row in document_rows} == {"shumeyko"}
    assert all(row.client_company_id for row in document_rows)
    assert all(row.wb_cabinet_id for row in document_rows)


def test_import_uses_existing_client_name_over_legacy_meta(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        import_dashboard_payload(
            db,
            sample_payload(),
            tenant_id="shumeyko",
            tenant_name="Шумейко и Партнеры",
            report_id="report-1",
        )
        client = db.query(repository.Client).filter_by(tenant_id="shumeyko").one()
        client.name = "Реальный клиент"
        db.commit()

        import_dashboard_payload(
            db,
            sample_payload(),
            tenant_id="shumeyko",
            tenant_name="Шумейко и Партнеры",
            report_id="report-2",
        )
        db.commit()
        report = db.get(repository.ReportRun, "report-2")
        client = db.query(repository.Client).filter_by(tenant_id="shumeyko").one()

    assert report is not None
    assert report.client_name == "Реальный клиент"
    assert client.name == "Реальный клиент"


def test_report_summary_preserves_lost_sales_onec_stock(tmp_path: Path) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        import_dashboard_payload(
            db,
            sample_payload(),
            tenant_id="shumeyko",
            tenant_name="Шумейко и Партнеры",
            report_id="report-1",
        )
        db.commit()
        report = db.get(repository.ReportRun, "report-1")
        assert report is not None
        summary = repository.report_summary_payload(db, report)

    assert summary["lostSales"][0]["onecStock"] == 12.0
    assert summary["lostSales"][0]["onecWarehouses"] == "Собственный склад: 12"


def test_report_summary_includes_document_reconciliation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    login(client)

    response = client.get("/api/reports/report-1/summary")

    assert response.status_code == 200
    summary = response.json()
    assert summary["documentReconciliation"][0]["status"] == "OK"
    assert (
        summary["documentReconciliation"][0]["payoutStatus"]
        == "Нужен источник выплаты 1С"
    )
    assert (
        summary["documentReconciliation"][0]["documentReport"]
        == "Отчет комиссионера · 06.04.2026-12.04.2026 · закрытие 12.04.2026"
    )
    assert summary["documentReconciliation"][0]["wbSalesQuantity"] == 22
    assert summary["documentReconciliation"][0]["onecReturnQuantity"] == 2
    assert summary["documentReconciliation"][0]["netQuantityDelta"] == 0
    assert summary["documentReconciliation"][0]["wbForPaySum"] == 85000
    assert summary["documentReconciliation"][0]["weeklySalesReportId"] == "SUMMARY-1"
    assert summary["documentReconciliation"][0]["weeklyBuyoutReportId"] == "BUYOUT-1"
    assert summary["documentReconciliation"][0]["onecSettlementTotal"] == 85000
    assert summary["documentReconciliation"][0]["settlementDelta"] == 0
    assert (
        "Отчет комиссионера · 06.04.2026-12.04.2026 · закрытие 12.04.2026"
        in summary["options"]["documentReports"]
    )


def test_dashboard_payload_period_helpers_separate_report_period_and_coverage() -> None:
    report_period = period_label_from_value(
        "2026-03-01 - 2026-06-17",
        "01.04.2026 - 17.06.2026",
    )
    coverage = period_label_from_value(
        "2026-04-01 - 2026-06-17",
        "",
    )

    assert report_period == "01.03.2026 - 17.06.2026"
    assert coverage == "01.04.2026 - 17.06.2026"
    assert period_boundaries_from_label(coverage) == ("2026-04-01", "2026-06-17")
    assert (
        analysis_period_text(
            "Период анализа: март, апрель, май, июнь; июнь неполный",
            "fallback",
        )
        == "март, апрель, май, июнь; июнь неполный"
    )


def test_document_reconciliation_parser_reads_excel_control_columns() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Сверка документов 1С"
    sheet.append(
        [
            "Статус сверки",
            "Статус выплаты",
            "Статус периода",
            "Период продаж",
            "Ожидаемая дата документа",
            "Тип документа WB/1С",
            "Кабинет WB",
            "Организация 1С",
            "Номер отчета WB (сводный)",
            "WB отчет продаж",
            "WB отчет выкупов",
            "WB reportId в пакете",
            "Документы 1С",
            "Типы документов 1С",
            "Даты документов 1С",
            "WB продажи",
            "WB возвраты",
            "WB чистое",
            "1С продажи",
            "1С возвраты",
            "1С чистое",
            "Дельта продажи",
            "Дельта возвраты",
            "Дельта чистое",
            "WB количество для 1С",
            "1С количество",
            "Дельта количество",
            "WB сумма документа",
            "1С сумма документа",
            "Дельта сумма",
            "WB выкуп: retailAmountSum",
            "WB выкуп: forPaySum",
            "WB выкуп: bankPaymentSum",
            "1С расходная накладная",
            "Δ выкуп retail",
            "Δ выкуп к перечислению",
            "Δ выкуп банк",
            "PDF 8. К перечислению",
            "WB к перечислению (forPaySum)",
            "1С оборот взаиморасчетов",
            "Дельта к обороту 1С",
            "Строк регистра 1С",
            "Комментарий",
        ]
    )
    sheet.append(
        [
            "OK",
            "Нужен источник выплаты 1С",
            "неполный период",
            "2026-04-06 - 2026-04-12",
            "2026-04-12",
            "Уведомление о выкупе",
            "Кабинет A",
            "Организация A",
            "SUMMARY-1",
            "SUMMARY-SALES-1",
            "SUMMARY-BUYOUT-1",
            "7268072721",
            "DOC-BUYOUT-1",
            "РасходнаяНакладная",
            "2026-04-12",
            42,
            0,
            42,
            42,
            0,
            42,
            0,
            0,
            0,
            42,
            42,
            0,
            66003.74,
            66003.74,
            0,
            66003.74,
            53420.94,
            24541.31,
            39464.41,
            26539.33,
            13956.53,
            -14923.1,
            64000,
            64000,
            None,
            None,
            5,
            "Нужен источник выплаты 1С",
        ]
    )

    rows = document_reconciliation_rows(workbook)

    assert rows == [
        {
            "id": "document-reconciliation-1",
            "status": "OK",
            "payoutStatus": "Нужен источник выплаты 1С",
            "periodStatus": "неполный период",
            "documentReport": (
                "Уведомление о выкупе · 06.04.2026-12.04.2026 · закрытие 12.04.2026"
            ),
            "salesPeriod": "2026-04-06 - 2026-04-12",
            "salesPeriodStart": "2026-04-06",
            "salesPeriodEnd": "2026-04-12",
            "expectedDocumentDate": "2026-04-12",
            "documentType": "Уведомление о выкупе",
            "cabinet": "Кабинет A",
            "organization": "Организация A",
            "summaryReportId": "SUMMARY-1",
            "weeklySalesReportId": "SUMMARY-SALES-1",
            "weeklyBuyoutReportId": "SUMMARY-BUYOUT-1",
            "wbReportIds": "7268072721",
            "onecDocuments": "DOC-BUYOUT-1",
            "onecDocumentTypes": "РасходнаяНакладная",
            "onecDocumentDates": "2026-04-12",
            "wbSalesQuantity": 42,
            "wbReturnQuantity": 0,
            "wbNetQuantity": 42,
            "onecSalesQuantity": 42,
            "onecReturnQuantity": 0,
            "onecNetQuantity": 42,
            "salesQuantityDelta": 0,
            "returnQuantityDelta": 0,
            "netQuantityDelta": 0,
            "wbQuantity": 42,
            "onecQuantity": 42,
            "quantityDelta": 0,
            "wbAmount": 66003.74,
            "onecAmount": 66003.74,
            "amountDelta": 0,
            "buyoutRetailAmountSum": 66003.74,
            "buyoutForPaySum": 53420.94,
            "buyoutBankPaymentSum": 24541.31,
            "onecExpenseInvoiceAmount": 39464.41,
            "buyoutRetailDelta": 26539.33,
            "buyoutForPayDelta": 13956.53,
            "buyoutBankDelta": -14923.1,
            "pdfBankPayment": 64000,
            "wbForPaySum": 64000,
            "onecSettlementTotal": None,
            "settlementDelta": None,
            "onecSourceRows": 5,
            "comment": "Нужен источник выплаты 1С",
        }
    ]


def test_report_requires_auth(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    assert client.get("/api/reports/report-1/summary").status_code == 401


def test_login_remember_me_extends_session_cookie(tmp_path: Path) -> None:
    client = make_client(
        tmp_path,
        settings_overrides={
            "session_ttl_hours": 1,
            "remember_me_session_ttl_hours": 48,
        },
    )

    response = client.post(
        "/api/auth/login",
        json={
            "email": "admin@example.com",
            "password": "secret",
            "remember_me": True,
        },
    )

    assert response.status_code == 200
    assert "Max-Age=172800" in response.headers["set-cookie"]


def test_cabinet_shell_serves_login_without_report_data(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    page = client.get("/")
    assert page.status_code == 200
    assert "Кабинет отчета" in page.text
    assert "Убыточный товар" not in page.text
    assert "Нет себестоимости 1С" not in page.text

    cabinet = client.get("/cabinet")
    assert cabinet.status_code == 200
    assert "/static/app.js" in cabinet.text
    assert 'id="rows-filter-form"' in cabinet.text
    assert "filter-document-report" in cabinet.text
    assert 'class="products-table"' in cabinet.text
    assert 'id="ai-panel"' in cabinet.text
    assert 'id="integrations-panel"' in cabinet.text
    assert 'id="source-refresh-panel"' in cabinet.text
    assert client.get("/api/reports").status_code == 401


def test_cabinet_static_assets_use_readiness_api_and_safe_rendering(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)

    app_js = client.get("/static/app.js")
    assert app_js.status_code == 200
    assert "/api/reports" in app_js.text
    assert "/summary" in app_js.text
    assert "/freshness" in app_js.text
    assert "/client-draft" in app_js.text
    assert "/messages/stream" in app_js.text
    assert "answerSource" in app_js.text
    assert "latestSourceRefresh" in app_js.text
    assert "sourceRefreshNewReport" in app_js.text
    assert "/api/integrations" in app_js.text
    assert "storageMode" in app_js.text
    assert "lastCheck.message" in app_js.text
    assert "status_filter" in app_js.text
    assert "loss_class" in app_js.text
    assert "document_report" in app_js.text
    assert "liquidityRows" in app_js.text
    assert "liquidity-rows" in app_js.text
    assert "function asArray" in app_js.text
    assert "sourceLoads = asArray" in app_js.text
    assert "summary.unitRows" not in app_js.text
    assert "URLSearchParams" in app_js.text
    assert "readiness" in app_js.text
    assert "innerHTML" not in app_js.text

    css = client.get("/static/styles.css")
    assert css.status_code == 200
    assert "@media (max-width: 560px)" in css.text
    assert ".filters-bar" in css.text
    assert "-webkit-overflow-scrolling: touch" in css.text
    assert "width: max-content" in css.text
    assert ".ai-workspace" in css.text
    assert ".integration-card" in css.text
    assert ".integration-details" in css.text
    assert ".source-refresh-collection" in css.text
    assert "overflow-wrap: anywhere" in css.text


def test_login_report_filters_and_export(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    login(client)

    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["tenants"][0]["id"] == "shumeyko"

    reports = client.get("/api/reports").json()["items"]
    assert [item["id"] for item in reports] == ["report-1"]

    summary = client.get("/api/reports/report-1/summary").json()
    assert summary["meta"]["periodStatus"] == "предварительный: июнь неполный"
    assert "unitRows" not in summary
    assert summary["kpis"]["rowCount"] == 2
    assert summary["kpis"]["revenue"] == 119000
    assert summary["kpis"]["profit"] == -56
    assert summary["kpis"]["lossRows"] == 1
    assert summary["quality"]["okRows"] == 1
    assert summary["quality"]["missingCostRows"] == 1
    assert summary["readiness"]["status"] == "partial_period"
    assert summary["readiness"]["label"] == "Неполный период"
    assert summary["readiness"]["score"] == 70
    assert summary["options"]["periodStart"] == "2026-04-06"
    assert summary["options"]["periodEnd"] == "2026-06-02"
    assert len(summary["liquidityRows"]) == 2
    assert {
        row["liquidityStatus"] for row in summary["liquidityRows"]
    } == {
        "Убыточный: логистика и приемка WB",
        "Нужна проверка данных",
    }
    assert summary["options"]["liquidityStatuses"] == [
        "Нужна проверка данных",
        "Убыточный: логистика и приемка WB",
    ]
    assert {reason["code"] for reason in summary["readiness"]["reviewReasons"]} == {
        "partial_period",
        "missing_cost",
        "client_draft_missing",
    }

    rows = client.get(
        "/api/reports/report-1/rows",
        params={"preset": "losses", "query": "BAR-LOSS"},
    ).json()
    assert rows["total"] == 1
    assert rows["items"][0]["product"] == "Убыточный товар"

    filtered_rows = client.get(
        "/api/reports/report-1/rows",
        params={"status_filter": "Нет себестоимости 1С", "limit": 50},
    ).json()
    assert filtered_rows["total"] == 1
    assert filtered_rows["items"][0]["barcode"] == "BAR-NOCOST"

    document_rows = client.get(
        "/api/reports/report-1/rows",
        params={
            "document_report": (
                "Отчет комиссионера · 06.04.2026-12.04.2026 · закрытие 12.04.2026"
            ),
            "limit": 50,
        },
    ).json()
    assert document_rows["total"] == 1
    assert document_rows["items"][0]["barcode"] == "BAR-LOSS"

    period_rows = client.get(
        "/api/reports/report-1/rows",
        params={"period_start": "2026-06-01", "period_end": "2026-06-30"},
    ).json()
    assert period_rows["total"] == 1
    assert period_rows["items"][0]["barcode"] == "BAR-NOCOST"

    sku = client.get("/api/reports/report-1/sku/BAR-NOCOST").json()
    assert sku["status"] == "Нет себестоимости 1С"

    export = client.get("/api/reports/report-1/export.xlsx")
    assert export.status_code == 200
    assert export.content == b"xlsx"

    freshness = client.get("/api/reports/report-1/freshness")
    assert freshness.status_code == 200
    assert freshness.json()["rowCount"] == 2
    assert freshness.json()["sourceLoads"][0]["status"] == "loaded"
    assert freshness.json()["readiness"]["status"] == "partial_period"

    management = client.get("/api/reports/report-1/management-report")
    assert management.status_code == 200
    assert "Убыточных строк" in management.json()["markdown"]


def test_report_summary_is_lightweight_for_large_reports(tmp_path: Path) -> None:
    payload = deepcopy(sample_payload())
    rows = []
    for index in range(1200):
        base = payload["unitRows"][index % 2]
        rows.append(
            {
                **base,
                "id": f"unit-large-{index}",
                "product": f"{base['product']} {index}",
                "nmId": f"{base['nmId']}-{index}",
                "barcode": f"{base['barcode']}-{index}",
            }
        )
    payload["unitRows"] = rows
    client = make_client(tmp_path, payload=payload)
    login(client)

    response = client.get("/api/reports/report-1/summary")
    assert response.status_code == 200
    summary = response.json()
    assert "unitRows" not in summary
    assert summary["kpis"]["rowCount"] == 1200
    assert summary["quality"]["missingCostRows"] == 600
    assert len(summary["liquidityRows"]) <= 100
    assert len(response.content) < 250_000

    rows_response = client.get(
        "/api/reports/report-1/rows",
        params={"limit": 250},
    )
    assert rows_response.status_code == 200
    rows_payload = rows_response.json()
    assert rows_payload["total"] == 1200
    assert len(rows_payload["items"]) == 250


def test_multi_client_report_access_requires_explicit_client(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    with client.app.state.session_factory() as db:
        db.get(repository.Client, "shumeyko").name = "Реальный клиент"
        upsert_user(
            db,
            email="admin@example.com",
            password="secret",
            tenant_id="other",
            role="admin",
        )
        db.commit()

    login(client)

    me = client.get("/api/me")
    assert me.status_code == 200
    me_clients = me.json()["clients"]
    assert next(
        item for item in me_clients if item["clientId"] == "shumeyko"
    )["name"] == "Реальный клиент"

    clients = client.get("/api/clients")
    assert clients.status_code == 200
    assert {item["clientId"] for item in clients.json()["items"]} == {
        "shumeyko",
        "other",
    }

    latest_without_client = client.get("/api/reports/latest/summary")
    assert latest_without_client.status_code == 400

    latest_shumeyko = client.get(
        "/api/reports/latest/summary",
        params={"client_id": "shumeyko"},
    )
    assert latest_shumeyko.status_code == 200
    summary = latest_shumeyko.json()
    assert summary["meta"]["clientId"] == "shumeyko"
    assert "unitRows" not in summary
    assert summary["options"]["cabinets"][0]["id"]
    assert summary["options"]["organizations"][0]["id"]

    latest_other = client.get(
        "/api/reports/latest/summary",
        params={"client_id": "other"},
    )
    assert latest_other.status_code == 200
    assert latest_other.json()["meta"]["clientId"] == "other"

    shumeyko_reports = client.get("/api/clients/shumeyko/reports")
    other_reports = client.get("/api/clients/other/reports")
    assert [item["id"] for item in shumeyko_reports.json()["items"]] == ["report-1"]
    assert [item["id"] for item in other_reports.json()["items"]] == ["other-report"]
    assert client.get("/api/clients/missing/reports").status_code == 404

    cabinet_a = next(
        item for item in summary["options"]["cabinets"] if item["label"] == "Кабинет A"
    )
    company_a = next(
        item
        for item in summary["options"]["organizations"]
        if item["label"] == "Организация A"
    )
    rows = client.get(
        "/api/reports/report-1/rows",
        params={
            "wb_cabinet_id": cabinet_a["id"],
            "client_company_id": company_a["id"],
        },
    )
    assert rows.status_code == 200
    assert rows.json()["total"] == 1
    assert rows.json()["items"][0]["barcode"] == "BAR-LOSS"

    legacy_rows = client.get(
        "/api/reports/report-1/rows",
        params={"wb_cabinet_id": "Кабинет A"},
    )
    assert legacy_rows.status_code == 200
    assert legacy_rows.json()["total"] == 1


def test_report_readiness_ready_after_clean_data_and_final_draft(
    tmp_path: Path,
) -> None:
    payload = ready_payload()
    client = make_client(tmp_path, payload=payload)
    login(client)

    saved = client.put(
        "/api/reports/report-1/client-draft",
        json={
            "content": client_ready_draft_text(),
            "instruction": "Готовый клиентский текст",
        },
    )
    assert saved.status_code == 200
    finalized = client.post(
        "/api/reports/report-1/client-draft/finalize",
        json={"revision": 1},
    )
    assert finalized.status_code == 200

    summary = client.get("/api/reports/report-1/summary").json()
    assert summary["readiness"] == {
        "status": "ready",
        "score": 100,
        "label": "Готов к отправке",
        "blockingReasons": [],
        "reviewReasons": [],
        "nextAction": "Можно отправлять клиенту.",
        "checkedBy": "system",
    }


def test_report_readiness_blocks_empty_report(tmp_path: Path) -> None:
    payload = ready_payload()
    payload["unitRows"] = []
    client = make_client(tmp_path, payload=payload)
    login(client)

    summary = client.get("/api/reports/report-1/summary").json()
    assert summary["readiness"]["status"] == "failed"
    assert summary["readiness"]["score"] == 0
    assert summary["readiness"]["blockingReasons"][0]["code"] == "no_rows"


def test_report_readiness_hides_staff_draft_state_from_client_role(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path, payload=ready_payload())
    login(client)
    created = client.post(
        "/api/admin/users",
        json={"email": "readiness-client@example.com", "role": "client"},
    ).json()

    client.post("/api/auth/logout")
    login_as(client, "readiness-client@example.com", created["temporaryPassword"])

    summary = client.get("/api/reports/report-1/summary").json()
    reason_codes = {reason["code"] for reason in summary["readiness"]["reviewReasons"]}
    assert "client_draft_missing" not in reason_codes
    assert summary["readiness"]["status"] == "ready"


def test_report_summary_includes_latest_source_refresh_safely(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    login(client)
    with client.app.state.session_factory() as db:
        user = db.query(repository.User).filter_by(email="admin@example.com").one()
        report = db.get(repository.ReportRun, "report-1")
        assert report is not None
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            mode="full",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="full-test",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 17),
            user=user,
            source_report=report,
            reason="test refresh",
        )
        repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="wb_finance_detail",
            source_label="WB Finance sales report details",
            required=True,
            status="failed",
            row_count=0,
            raw_path="data/source_refresh/full-test/wb_finance",
            error_message="HTTP 401 token expired",
        )
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="failed",
            error_message="HTTP 401 token expired",
            finished_at=repository.security.utcnow(),
        )
        db.commit()

    staff_summary = client.get("/api/reports/report-1/summary").json()
    staff_refresh = staff_summary["latestSourceRefresh"]
    assert staff_refresh["status"] == "failed"
    assert staff_refresh["errorMessage"] == "HTTP 401 token expired"
    assert staff_refresh["collections"][0]["rawPath"].endswith("wb_finance")

    created = client.post(
        "/api/admin/users",
        json={"email": "refresh-view-client@example.com", "role": "client"},
    ).json()
    client.post("/api/auth/logout")
    login_as(client, "refresh-view-client@example.com", created["temporaryPassword"])

    client_summary = client.get("/api/reports/report-1/summary").json()
    client_refresh = client_summary["latestSourceRefresh"]
    assert client_refresh["status"] == "failed"
    assert client_refresh["errorMessage"].startswith("Последний refresh")
    assert client_refresh["collections"][0]["rawPath"] == ""
    assert client_refresh["collections"][0]["payload"] == {}
    assert "HTTP 401" not in str(client_refresh)


def test_analytical_report_artifact_requires_auth_and_downloads(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = make_client(tmp_path)

    assert client.post("/api/reports/report-1/analytical-report").status_code == 401
    login(client)

    def fake_build_client_analytical_report(**kwargs):
        output_dir = kwargs["output_dir"]
        output_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = output_dir / "report.md"
        docx_path = output_dir / "report.docx"
        markdown_path.write_text("# Отчет", encoding="utf-8")
        docx_path.write_bytes(b"docx")
        return SimpleNamespace(
            markdown_path=markdown_path,
            docx_path=docx_path,
            pdf_path=None,
            pdf_status="unavailable",
            pdf_message="PDF converter is unavailable.",
        )

    monkeypatch.setattr(
        "wb_unit_economics.web.app.build_client_analytical_report",
        fake_build_client_analytical_report,
    )

    generated = client.post(
        "/api/reports/report-1/analytical-report",
        json={"branded": True},
    )
    assert generated.status_code == 200
    payload = generated.json()
    assert payload["files"]["docx"]["url"].endswith("/analytical-report.docx")
    assert payload["files"]["pdf"]["status"] == "unavailable"

    docx = client.get("/api/reports/report-1/analytical-report.docx")
    assert docx.status_code == 200
    assert docx.content == b"docx"

    pdf = client.get("/api/reports/report-1/analytical-report.pdf")
    assert pdf.status_code == 404


def test_tenant_isolation(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    login(client)

    assert client.get("/api/reports/other-report/summary").status_code == 404
    assert client.get("/api/reports/other-report/client-draft").status_code == 404


def test_client_draft_is_staff_only(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    login(client)

    created = client.post(
        "/api/admin/users",
        json={"email": "draft-client@example.com", "role": "client"},
    ).json()
    staff_view = client.get("/api/reports/report-1/client-draft")
    assert staff_view.status_code == 200
    assert staff_view.json()["latest"] is None

    client.post("/api/auth/logout")
    login_as(
        client,
        "draft-client@example.com",
        created["temporaryPassword"],
    )

    assert client.get("/api/reports/report-1/client-draft").status_code == 403


def test_client_draft_revisions_finalize_and_audit(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    client = make_client(tmp_path)
    login(client)

    first = client.post(
        "/api/reports/report-1/client-draft/refine",
        json={"action": "assemble", "instruction": "Собери клиентский текст"},
    )
    assert first.status_code == 200
    first_payload = first.json()
    assert first_payload["changed"] is True
    assert first_payload["latest"]["revision"] == 1
    assert first_payload["latest"]["source"] == "deterministic_base"
    assert "Ключевой вывод" in first_payload["latest"]["content"]
    assert "Ограничения" in first_payload["latest"]["content"]
    assert "draft_management_report" not in first_payload["latest"]["content"]
    assert "tool_completed" not in first_payload["latest"]["content"]

    unavailable = client.post(
        "/api/reports/report-1/client-draft/refine",
        json={"action": "shorten", "instruction": "Сократи"},
    )
    assert unavailable.status_code == 200
    unavailable_payload = unavailable.json()
    assert unavailable_payload["changed"] is False
    assert unavailable_payload["aiAvailable"] is False
    assert "не изменен" in unavailable_payload["message"]
    assert len(unavailable_payload["revisions"]) == 1

    manual_text = (
        "Ключевой вывод\n"
        "Клиенту нужно проверить убыточность и себестоимость.\n\n"
        "Факты\n"
        "- В отчете есть убыточная строка.\n\n"
        "Что требует проверки\n"
        "- Себестоимость 1С по товару без себестоимости.\n\n"
        "Ограничения\n"
        "- Причины возврата не передаются текущими источниками.\n\n"
        "Следующий шаг\n"
        "Согласовать проверку с аналитиком."
    )
    saved = client.put(
        "/api/reports/report-1/client-draft",
        json={"content": manual_text, "instruction": "Ручная правка"},
    )
    assert saved.status_code == 200
    saved_payload = saved.json()
    assert saved_payload["latest"]["revision"] == 2
    assert saved_payload["latest"]["source"] == "manual"

    finalized = client.post(
        "/api/reports/report-1/client-draft/finalize",
        json={"revision": 2},
    )
    assert finalized.status_code == 200
    assert finalized.json()["latest"]["status"] == "ready"

    audit = client.get("/api/admin/audit")
    actions = {item["action"] for item in audit.json()["items"]}
    assert "ai_client_draft_created" in actions
    assert "ai_client_draft_saved" in actions
    assert "ai_client_draft_finalized" in actions


def test_client_draft_rejects_internal_labels(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    login(client)

    response = client.put(
        "/api/reports/report-1/client-draft",
        json={
            "content": "Ключевой вывод\nСработал draft_management_report.",
            "instruction": "Ручная правка",
        },
    )
    assert response.status_code == 400


def test_admin_user_management_and_audit(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    login(client)

    created = client.post(
        "/api/admin/users",
        json={
            "email": "client@example.com",
            "name": "Client",
            "role": "client",
        },
    )
    assert created.status_code == 200
    client_user = created.json()["user"]
    assert client_user["tenants"][0]["role"] == "client"
    assert created.json()["temporaryPassword"]

    users = client.get("/api/admin/users")
    assert users.status_code == 200
    assert {item["email"] for item in users.json()["items"]} == {
        "admin@example.com",
        "client@example.com",
    }

    reset = client.post(f"/api/admin/users/{client_user['id']}/reset-password", json={})
    assert reset.status_code == 200
    assert reset.json()["temporaryPassword"]

    disabled = client.patch(
        f"/api/admin/users/{client_user['id']}",
        json={"is_active": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["user"]["isActive"] is False

    audit = client.get("/api/admin/audit")
    assert audit.status_code == 200
    assert any(
        item["action"] == "user_password_reset" for item in audit.json()["items"]
    )


def test_client_role_cannot_manage_users(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    login(client)
    created = client.post(
        "/api/admin/users",
        json={"email": "client@example.com", "role": "client"},
    ).json()
    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={
            "email": "client@example.com",
            "password": created["temporaryPassword"],
        },
    )

    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/api/admin/audit").status_code == 403


def test_tenant_integrations_are_staff_only_and_mask_secrets(
    tmp_path: Path, monkeypatch
) -> None:
    integration_key = Fernet.generate_key().decode("ascii")
    checked_secrets: list[tuple[str, str]] = []

    def fake_check(
        _settings: WebSettings, *, provider: str, secret: str
    ) -> integrations.IntegrationCheckResult:
        checked_secrets.append((provider, secret))
        return integrations.IntegrationCheckResult(
            status="check_ok",
            message=f"{provider} проверен read-only",
            payload={
                "provider": provider,
                "checkedAt": "2026-06-21T09:00:00+03:00",
                "checkMode": "live_read_only",
                "endpointCategory": "test_ping",
                "httpStatus": 200,
            },
        )

    monkeypatch.setattr(integrations, "run_provider_check", fake_check)
    client = make_client(
        tmp_path,
        settings_overrides={"integration_secret_key": integration_key},
    )
    login(client)

    empty = client.get("/api/integrations")
    assert empty.status_code == 200
    empty_payload = empty.json()
    assert {item["provider"] for item in empty_payload["items"]} == {
        "wb_api",
        "onec_readonly",
    }
    assert {
        item["providerBase"]: item for item in empty_payload["providers"]
    }["wb_api"] == {
        "providerBase": "wb_api",
        "label": "Wildberries API",
        "readOnly": True,
        "supportsMultiple": True,
        "primaryProviderId": "wb_api",
        "roles": [
            {
                "id": "finance_reports",
                "label": "Финансовые отчеты",
                "default": True,
            },
            {
                "id": "analytics_stocks",
                "label": "Аналитика и остатки",
                "default": False,
            },
            {
                "id": "content_cards",
                "label": "Карточки товаров",
                "default": False,
            },
            {
                "id": "full_readonly",
                "label": "Полный read-only доступ",
                "default": False,
            },
        ],
    }

    saved = client.put(
        "/api/integrations/wb_api",
        json={"label": "WB кабинет", "secret": "wb-token-secret-123456"},
    )
    assert saved.status_code == 200
    payload = saved.json()
    assert payload["status"] == "configured"
    assert payload["configured"] is True
    assert payload["providerBase"] == "wb_api"
    assert payload["connectionKey"] == "primary"
    assert payload["connectionRole"] == "finance_reports"
    assert payload["isPrimary"] is True
    assert payload["secretHint"] == "***3456"
    assert payload["storageMode"] == "encrypted"
    assert "wb-token-secret" not in str(payload)

    checked = client.post("/api/integrations/wb_api/check", json={})
    assert checked.status_code == 200
    assert checked.json()["status"] == "check_ok"
    assert checked.json()["lastCheck"]["message"] == "wb_api проверен read-only"
    assert checked.json()["lastCheck"]["httpStatus"] == 200
    assert checked_secrets == [("wb_api", "wb-token-secret-123456")]

    extra = client.post(
        "/api/integrations",
        json={
            "provider": "wb_api",
            "label": "WB кабинет маркетплейс 2",
            "connection_role": "analytics_stocks",
            "cabinet_name": "Кабинет 2",
            "organization_name": "ООО Тест",
            "secret": "wb-extra-token-654321",
        },
    )
    assert extra.status_code == 200
    extra_payload = extra.json()
    assert extra_payload["provider"].startswith("wb_api:")
    assert extra_payload["providerBase"] == "wb_api"
    assert extra_payload["connectionKey"] != "primary"
    assert extra_payload["connectionRole"] == "analytics_stocks"
    assert extra_payload["cabinetName"] == "Кабинет 2"
    assert extra_payload["organizationName"] == "ООО Тест"
    assert extra_payload["isPrimary"] is False
    assert extra_payload["secretHint"] == "***4321"
    assert "wb-extra-token" not in str(extra_payload)

    listed = client.get("/api/integrations").json()["items"]
    assert {"wb_api", "onec_readonly", extra_payload["provider"]} <= {
        item["provider"] for item in listed
    }

    checked_extra = client.post(
        f"/api/integrations/{quote(extra_payload['provider'], safe='')}/check",
        json={},
    )
    assert checked_extra.status_code == 200
    assert checked_extra.json()["status"] == "check_ok"
    assert checked_secrets[-1] == ("wb_api", "wb-extra-token-654321")

    saved_onec = client.put(
        "/api/integrations/onec_readonly",
        json={
            "label": "1С тест",
            "secret": (
                "baseUrl=https://onec.example.test/odata/standard.odata;"
                "username=reader;password=onec-secret;verifySsl=true"
            ),
        },
    )
    assert saved_onec.status_code == 200
    assert saved_onec.json()["storageMode"] == "encrypted"
    checked_onec = client.post("/api/integrations/onec_readonly/check", json={})
    assert checked_onec.status_code == 200
    assert checked_onec.json()["status"] == "check_ok"
    assert checked_secrets[-1] == (
        "onec_readonly",
        "baseUrl=https://onec.example.test/odata/standard.odata;"
        "username=reader;password=onec-secret;verifySsl=true",
    )

    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        integration = (
            db.query(TenantIntegration)
            .filter_by(tenant_id="shumeyko", provider="wb_api")
            .one()
        )
        assert integration.config_payload["storage"] == "encrypted"
        assert "secretCiphertext" in integration.config_payload
        assert "wb-token-secret" not in str(integration.config_payload)

    disabled = client.post("/api/integrations/wb_api/disable", json={})
    assert disabled.status_code == 200
    assert disabled.json()["status"] == "disabled"
    assert "wb-token-secret" not in str(disabled.json())

    audit = client.get("/api/admin/audit").json()["items"]
    audit_text = str(audit)
    assert "tenant_integration_saved" in {item["action"] for item in audit}
    assert "tenant_integration_checked" in {item["action"] for item in audit}
    assert "tenant_integration_disabled" in {item["action"] for item in audit}
    assert "wb-token-secret" not in audit_text

    created = client.post(
        "/api/admin/users",
        json={"email": "integrations-client@example.com", "role": "client"},
    ).json()
    client.post("/api/auth/logout")
    login_as(client, "integrations-client@example.com", created["temporaryPassword"])

    assert client.get("/api/integrations").status_code == 403
    assert (
        client.put(
            "/api/integrations/wb_api",
            json={"secret": "another-secret"},
        ).status_code
        == 403
    )
    assert (
        client.post(
            "/api/integrations",
            json={"provider": "wb_api", "secret": "another-secret"},
        ).status_code
        == 403
    )


def test_tenant_integration_hash_only_storage_cannot_live_check(
    tmp_path: Path,
) -> None:
    client = make_client(tmp_path)
    login(client)

    saved = client.put(
        "/api/integrations/wb_api",
        json={"label": "WB без ключа шифрования", "secret": "legacy-token-123"},
    )
    assert saved.status_code == 200
    assert saved.json()["status"] == "configured"
    assert saved.json()["storageMode"] == "hash_only"

    checked = client.post("/api/integrations/wb_api/check", json={})
    assert checked.status_code == 200
    payload = checked.json()
    assert payload["status"] == "check_failed"
    assert payload["lastCheck"]["checkMode"] == "configuration"
    assert "SHUMEYKO_INTEGRATION_SECRET_KEY" in payload["lastCheck"]["message"]
    assert "legacy-token" not in str(payload)


def test_live_checks_are_read_only_and_disabled_by_default(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    login(client)

    response = client.post(
        "/api/reports/report-1/live-checks/onec-cost",
        json={"lookup": "BAR-NOCOST"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "disabled"
    assert payload["reviewStatus"] == "needs_review"
    assert "не опрашивались" in payload["message"]


def test_onec_auto_refresh_is_staff_only_flagged_and_creates_new_report(
    tmp_path: Path,
) -> None:
    fake_service = FakeAutoRefreshService(tmp_path / "reports" / "auto-refresh.xlsx")
    client = make_client(
        tmp_path,
        settings_overrides={"source_refresh_enabled": True},
        auto_refresh_service=fake_service,
    )
    login(client)

    response = client.post(
        "/api/reports/report-1/refresh/onec-auto",
        json={"reason": "Нужно дозагрузить себестоимость 1С"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "report_created"
    assert payload["jobType"] == "source_refresh"
    assert payload["sourceReportRunId"] == "report-1"
    assert payload["newReportRunId"] == "report-1-refresh"
    assert "row_payload" not in str(payload).lower()

    old_summary = client.get("/api/reports/report-1/summary").json()
    new_summary = client.get("/api/reports/report-1-refresh/summary").json()
    assert old_summary["quality"]["missingCostRows"] == 1
    assert new_summary["quality"]["missingCostRows"] == 0
    new_rows = client.get(
        "/api/reports/report-1-refresh/rows",
        params={"status_filter": "ОК", "limit": 10},
    ).json()
    assert new_rows["total"] == 2
    assert [item["id"] for item in client.get("/api/reports").json()["items"]][0] == (
        "report-1-refresh"
    )

    job = client.get(f"/api/reports/report-1/refresh-jobs/{payload['id']}")
    assert job.status_code == 200
    assert job.json()["newReportRunId"] == "report-1-refresh"
    assert job.json()["mode"] == "onec-only"

    audit = client.get("/api/admin/audit")
    actions = {item["action"] for item in audit.json()["items"]}
    assert "source_refresh_requested" in actions
    assert "source_refresh_report_created" in actions
    assert "onec_auto_refresh_started" not in actions


def test_onec_auto_refresh_wrapper_calls_source_refresh_onec_only(
    tmp_path: Path,
) -> None:
    class FakeSourceRefreshService:
        def __init__(self) -> None:
            self.kwargs = {}

        def run(self, db, **kwargs):
            self.kwargs = kwargs
            return {
                "id": "source_refresh_1",
                "tenantId": kwargs["tenant_id"],
                "sourceReportRunId": kwargs["source_report"].id,
                "newReportRunId": "report-1-source-refresh",
                "mode": kwargs["mode"],
                "status": "report_created",
                "collections": [],
            }

    client = make_client(tmp_path)
    fake_source_refresh = FakeSourceRefreshService()
    service = OnecAutoRefreshService(
        WebSettings(
            database_url=f"sqlite:///{tmp_path / 'web.sqlite3'}",
            cookie_secure=False,
            allowed_export_root=str(tmp_path / "reports"),
            source_refresh_enabled=True,
        ),
        source_refresh_service=fake_source_refresh,
    )
    with client.app.state.session_factory() as db:
        user = db.query(repository.User).filter_by(email="admin@example.com").one()
        report = db.get(repository.ReportRun, "report-1")
        assert report is not None
        payload = service.run(db, user=user, report=report, reason="refresh 1c")

    assert fake_source_refresh.kwargs["tenant_id"] == "shumeyko"
    assert fake_source_refresh.kwargs["mode"] == "onec-only"
    assert fake_source_refresh.kwargs["credential_source"] == "tenant"
    assert fake_source_refresh.kwargs["dry_run"] is False
    assert fake_source_refresh.kwargs["source_report"].id == "report-1"
    assert payload["jobType"] == "source_refresh"
    assert payload["sourceRefreshRunId"] == "source_refresh_1"


def test_onec_auto_refresh_disabled_and_client_forbidden(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    login(client)

    disabled = client.post(
        "/api/reports/report-1/refresh/onec-auto",
        json={"reason": "Дозагрузить 1С"},
    )
    assert disabled.status_code == 409
    assert "SOURCE_REFRESH" in disabled.json()["detail"]

    created = client.post(
        "/api/admin/users",
        json={"email": "refresh-client@example.com", "role": "client"},
    ).json()
    client.post("/api/auth/logout")
    login_as(client, "refresh-client@example.com", created["temporaryPassword"])
    forbidden = client.post(
        "/api/reports/report-1/refresh/onec-auto",
        json={"reason": "Дозагрузить 1С"},
    )
    assert forbidden.status_code == 403


def test_onec_auto_refresh_rejects_active_job(tmp_path: Path) -> None:
    fake_service = FakeAutoRefreshService(tmp_path / "reports" / "auto-refresh.xlsx")
    client = make_client(
        tmp_path,
        settings_overrides={"source_refresh_enabled": True},
        auto_refresh_service=fake_service,
    )
    login(client)
    with client.app.state.session_factory() as db:
        user = db.query(repository.User).filter_by(email="admin@example.com").one()
        report = db.get(repository.ReportRun, "report-1")
        assert report is not None
        repository.create_source_refresh_run(
            db,
            tenant_id=report.tenant_id,
            mode="onec-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="onec-only-active",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 17),
            user=user,
            source_report=report,
            reason="already running",
        )
        db.commit()

    response = client.post(
        "/api/reports/report-1/refresh/onec-auto",
        json={"reason": "Дозагрузить 1С"},
    )
    assert response.status_code == 409


def test_ai_fallback_uses_report_facts(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    login(client)

    thread = client.post("/api/ai/threads", json={"report_id": "report-1"}).json()
    answer = client.post(
        f"/api/ai/threads/{thread['id']}/messages",
        json={"content": "Что самое важное по убыточности?"},
    ).json()
    assistant_messages = [
        item["content"] for item in answer["messages"] if item["role"] == "assistant"
    ]
    assert assistant_messages
    assert "Убыточных строк" in assistant_messages[-1]
    assert "не меняю данные" in assistant_messages[-1]
    assert any(item["type"] == "tool_completed" for item in answer["events"])
    done_events = [
        item for item in answer["events"] if item["type"] == "assistant_done"
    ]
    assert done_events[-1]["payload"]["answerSource"] == "fallback"
    assert done_events[-1]["payload"]["fallbackReason"] == "no_openai_key"


def test_ai_openai_source_is_visible_when_model_answers(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_openai_answer(self, db, user, thread, report, question):
        return "OpenAI: главный риск — себестоимость и убыточные SKU.", ""

    monkeypatch.setattr(AiAnalyst, "_openai_answer", fake_openai_answer)
    client = make_client(tmp_path, settings_overrides={"openai_api_key": "test-key"})
    login(client)

    thread = client.post("/api/ai/threads", json={"report_id": "report-1"}).json()
    answer = client.post(
        f"/api/ai/threads/{thread['id']}/messages",
        json={"content": "Что главное?"},
    ).json()

    assistant_messages = [
        item["content"] for item in answer["messages"] if item["role"] == "assistant"
    ]
    assert assistant_messages[-1].startswith("OpenAI:")
    done_events = [
        item for item in answer["events"] if item["type"] == "assistant_done"
    ]
    assert done_events[-1]["payload"]["answerSource"] == "openai"
    assert done_events[-1]["payload"]["model"]
    assert any(item["type"] == "answer_source" for item in answer["events"])


def test_ai_fallback_reason_is_hidden_from_client_role(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_openai_answer(self, db, user, thread, report, question):
        return None, "BadRequestError"

    monkeypatch.setattr(AiAnalyst, "_openai_answer", fake_openai_answer)
    client = make_client(tmp_path, settings_overrides={"openai_api_key": "test-key"})
    login(client)
    created = client.post(
        "/api/admin/users",
        json={"email": "ai-client@example.com", "role": "client"},
    ).json()
    client.post("/api/auth/logout")
    login_as(client, "ai-client@example.com", created["temporaryPassword"])

    thread = client.post("/api/ai/threads", json={"report_id": "report-1"}).json()
    answer = client.post(
        f"/api/ai/threads/{thread['id']}/messages",
        json={"content": "Что главное?"},
    ).json()

    done_events = [
        item for item in answer["events"] if item["type"] == "assistant_done"
    ]
    assert done_events[-1]["payload"]["answerSource"] == "fallback"
    assert "fallbackReason" not in done_events[-1]["payload"]
    assert "BadRequestError" not in str(answer)


def test_ai_explicit_onec_refresh_creates_new_report(tmp_path: Path) -> None:
    fake_service = FakeAutoRefreshService(tmp_path / "reports" / "auto-refresh.xlsx")
    client = make_client(
        tmp_path,
        settings_overrides={"source_refresh_enabled": True},
        auto_refresh_service=fake_service,
    )
    login(client)

    thread = client.post("/api/ai/threads", json={"report_id": "report-1"}).json()
    answer = client.post(
        f"/api/ai/threads/{thread['id']}/messages",
        json={"content": "Дозагрузи 1С себестоимость и пересобери отчет"},
    ).json()

    assistant_messages = [
        item["content"] for item in answer["messages"] if item["role"] == "assistant"
    ]
    assert "report-1-refresh" in assistant_messages[-1]
    assert client.get("/api/reports/report-1-refresh/summary").status_code == 200
    titles = {item["title"] for item in answer["events"]}
    assert "Нашел нехватку 1С-данных" in titles
    assert "Дозагружаю 1С read-only" in titles
    assert "Пересчитываю отчет" in titles
    assert "Создан новый отчет" in titles

    audit = client.get("/api/admin/audit").json()["items"]
    assert any(item["action"] == "ai_onec_auto_refresh_completed" for item in audit)


def test_ai_does_not_refresh_for_general_question(tmp_path: Path) -> None:
    fake_service = FakeAutoRefreshService(tmp_path / "reports" / "auto-refresh.xlsx")
    client = make_client(
        tmp_path,
        settings_overrides={"source_refresh_enabled": True},
        auto_refresh_service=fake_service,
    )
    login(client)

    thread = client.post("/api/ai/threads", json={"report_id": "report-1"}).json()
    client.post(
        f"/api/ai/threads/{thread['id']}/messages",
        json={"content": "Что главное по отчету?"},
    )

    assert client.get("/api/reports/report-1-refresh/summary").status_code == 404


def test_ai_client_role_cannot_trigger_onec_refresh(tmp_path: Path) -> None:
    fake_service = FakeAutoRefreshService(tmp_path / "reports" / "auto-refresh.xlsx")
    client = make_client(
        tmp_path,
        settings_overrides={"source_refresh_enabled": True},
        auto_refresh_service=fake_service,
    )
    login(client)
    created = client.post(
        "/api/admin/users",
        json={"email": "ai-refresh-client@example.com", "role": "client"},
    ).json()
    client.post("/api/auth/logout")
    login_as(client, "ai-refresh-client@example.com", created["temporaryPassword"])

    thread = client.post("/api/ai/threads", json={"report_id": "report-1"}).json()
    answer = client.post(
        f"/api/ai/threads/{thread['id']}/messages",
        json={"content": "Дозагрузи 1С себестоимость и пересобери отчет"},
    ).json()

    assistant_messages = [
        item["content"] for item in answer["messages"] if item["role"] == "assistant"
    ]
    assert "нужна проверка консультанта" in assistant_messages[-1].lower()
    assert client.get("/api/reports/report-1-refresh/summary").status_code == 404


def test_ai_stream_returns_safe_events_and_final_answer(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    login(client)

    thread = client.post("/api/ai/threads", json={"report_id": "report-1"}).json()
    with client.stream(
        "POST",
        f"/api/ai/threads/{thread['id']}/messages/stream",
        json={"content": "Покажи убыточные SKU"},
    ) as response:
        assert response.status_code == 200
        body = "".join(response.iter_text())

    assert "event: status" in body
    assert "event: tool_completed" in body
    assert "event: answer_source" in body
    assert "event: final" in body
    assert "answerSource" in body
    assert "Убыточных строк" in body

    events = client.get(f"/api/ai/threads/{thread['id']}/events").json()["items"]
    assert any(item["title"] == "Разбираю убыточность" for item in events)
    assert not any("input_payload" in item.get("payload", {}) for item in events)
