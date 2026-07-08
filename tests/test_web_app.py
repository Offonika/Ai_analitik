from __future__ import annotations

from copy import deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook

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
from wb_unit_economics.web.models import SourceRefreshRun, TenantIntegration, WbCabinet
from wb_unit_economics.web.refresh import AutoRefreshBusyError, OnecAutoRefreshService
from wb_unit_economics.web.repository import import_dashboard_payload, upsert_user
from wb_unit_economics.web.settings import WebSettings


def test_ozon_expense_reconciliation_uses_api_expenses_and_onec_control() -> None:
    ozon = repository._ozon_cash_flow_expenses_payload(
        [
            SimpleNamespace(
                row_payload={
                    "details": [
                        {
                            "period": {
                                "begin": "2026-04-01T00:00:00Z",
                                "end": "2026-04-30T00:00:00Z",
                            },
                            "delivery": {"total": "1000"},
                            "services": {"total": "-100"},
                            "others": {"total": "10"},
                        }
                    ]
                }
            )
        ],
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )
    onec = repository._onec_incoming_invoice_expense_payload(
        [
            SimpleNamespace(
                row_payload={
                    "Date": "2026-04-30T00:00:00",
                    "Контрагент_Key": "OZON-CP",
                    "ВидОперации": "ПоступлениеОтПоставщика",
                    "СуммаДокумента": "95",
                }
            )
        ],
        counterparty_ids=["OZON-CP"],
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )
    reconciliation = repository._ozon_expense_reconciliation_payload(ozon, onec)

    assert ozon["summary"]["expenseAmount"] == 90.0
    assert ozon["summary"]["deliveryAmount"] == 1000.0
    assert ozon["summary"]["positiveAdjustmentAmount"] == 10.0
    assert {
        "category": "delivery",
        "label": "Ozon доставка / денежный блок",
        "signedAmount": 1000.0,
        "expenseEffectAmount": None,
        "includedInExpense": False,
        "note": "Не входит в расходы V1: это отдельный денежный блок.",
    } in ozon["categoryRows"]
    assert onec["amount"] == 95.0
    assert onec["operationRows"] == [
        {
            "operation": "ПоступлениеОтПоставщика",
            "amount": 95.0,
            "rowCount": 1,
            "includedInControl": True,
            "note": "Входит в 1C контроль расходов.",
        }
    ]
    assert reconciliation["status"] == "review"
    assert reconciliation["deltaAmount"] == 5.0
    assert reconciliation["detailRows"][-1] == {
        "kind": "total",
        "label": "Итого к расчету",
        "ozonAmount": 90.0,
        "ozonSignedAmount": None,
        "onecAmount": 95.0,
        "deltaAmount": 5.0,
        "includedInExpense": True,
        "note": "Дельта = 1C контроль минус Ozon API.",
    }


def test_ozon_expense_reconciliation_keeps_onec_control_without_ozon_expenses() -> None:
    ozon = {
        "status": "missing",
        "summary": {},
        "categoryRows": [],
        "topItems": [],
    }
    onec = repository._onec_incoming_invoice_expense_payload(
        [
            SimpleNamespace(
                row_payload={
                    "Date": "2026-04-30T00:00:00",
                    "Контрагент_Key": "OZON-CP",
                    "ВидОперации": "ПоступлениеОтПоставщика",
                    "СуммаДокумента": "550",
                }
            )
        ],
        counterparty_ids=["OZON-CP"],
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )

    reconciliation = repository._ozon_expense_reconciliation_payload(ozon, onec)

    assert reconciliation["status"] == "missing"
    assert reconciliation["ozonExpenseAmount"] is None
    assert reconciliation["onecExpenseAmount"] == 550.0
    assert any(
        item["kind"] == "onec_operation" for item in reconciliation["detailRows"]
    )


def test_ozon_mutual_settlement_expenses_use_document_rows() -> None:
    mutual = repository._ozon_mutual_settlement_expenses_payload(
        [
            SimpleNamespace(
                row_payload={
                    "Наименование": "Акт выполненных работ",
                    "Сумма дебиторской задолженности, RUR": "4898080.79",
                    "Сумма кредиторской задолженности, RUR": "",
                }
            ),
            SimpleNamespace(
                row_payload={
                    "Наименование": "Отчет о перевыставлении услуг",
                    "Сумма дебиторской задолженности, RUR": "535869.81",
                    "Сумма кредиторской задолженности, RUR": "",
                }
            ),
            SimpleNamespace(
                row_payload={
                    "Наименование": "Отчет о реализации",
                    "Сумма дебиторской задолженности, RUR": "151715.49",
                    "Сумма кредиторской задолженности, RUR": "26149512.63",
                }
            ),
            SimpleNamespace(
                row_payload={
                    "Наименование": "Фактическая оплата селлеров",
                    "Сумма дебиторской задолженности, RUR": "17286376.74",
                    "Сумма кредиторской задолженности, RUR": "",
                }
            ),
        ]
    )

    assert mutual["status"] == "loaded"
    assert mutual["basis"] == "ozon_mutual_settlement_expense_documents"
    assert mutual["summary"]["expenseAmount"] == 5585666.09
    assert any(
        item["label"] == "Фактическая оплата селлеров"
        and item["includedInExpense"] is False
        for item in mutual["categoryRows"]
    )


def test_ozon_expense_reconciliation_shows_unmatched_onec_article() -> None:
    ozon = repository._ozon_mutual_settlement_expenses_payload(
        [
            SimpleNamespace(
                row_payload={
                    "Наименование": "Акт выполненных работ",
                    "Сумма дебиторской задолженности, RUR": "4898080.79",
                    "Сумма кредиторской задолженности, RUR": "",
                }
            ),
            SimpleNamespace(
                row_payload={
                    "Наименование": "Отчет о перевыставлении услуг",
                    "Сумма дебиторской задолженности, RUR": "535869.81",
                    "Сумма кредиторской задолженности, RUR": "",
                }
            ),
            SimpleNamespace(
                row_payload={
                    "Наименование": "Отчет о реализации",
                    "Сумма дебиторской задолженности, RUR": "151715.49",
                    "Сумма кредиторской задолженности, RUR": "",
                }
            ),
        ]
    )
    onec = repository._onec_incoming_invoice_expense_payload(
        [
            SimpleNamespace(
                row_payload={
                    "Date": "2026-04-30T00:00:00",
                    "Номер": "DOC-1",
                    "Контрагент_Key": "OZON-CP",
                    "ВидОперации": "ПоступлениеОтПоставщика",
                    "СуммаДокумента": "4898080.79",
                }
            ),
            SimpleNamespace(
                row_payload={
                    "Date": "2026-04-30T00:00:00",
                    "Номер": "DOC-2",
                    "Контрагент_Key": "OZON-CP",
                    "ВидОперации": "ПоступлениеОтПоставщика",
                    "СуммаДокумента": "535869.81",
                }
            ),
            SimpleNamespace(
                row_payload={
                    "Date": "2026-04-30T00:00:00",
                    "Номер": "DOC-3",
                    "Контрагент_Key": "OZON-CP",
                    "ВидОперации": "ПоступлениеОтПоставщика",
                    "СуммаДокумента": "151715.49",
                }
            ),
            SimpleNamespace(
                row_payload={
                    "Date": "2026-04-30T00:00:00",
                    "Номер": "DOC-4",
                    "Контрагент_Key": "OZON-CP",
                    "ВидОперации": "ПоступлениеОтПоставщика",
                    "СуммаДокумента": "550",
                }
            ),
        ],
        counterparty_ids=["OZON-CP"],
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )

    reconciliation = repository._ozon_expense_reconciliation_payload(ozon, onec)
    unmatched = [
        item
        for item in reconciliation["articleRows"]
        if item["kind"] == "onec_unmatched"
    ]

    assert reconciliation["deltaAmount"] == 550.0
    assert reconciliation["status"] == "review"
    assert "статьи без пары" in reconciliation["message"]
    assert len(unmatched) == 1
    assert unmatched[0]["ozonAmount"] == 0.0
    assert unmatched[0]["onecAmount"] == 550.0
    assert unmatched[0]["deltaAmount"] == 550.0
    assert "1C без пары в Ozon" in unmatched[0]["label"]
    assert "соседний месяц mutual settlement" in unmatched[0]["note"]


def test_ozon_period_from_output_file_accepts_mutual_settlement_xlsx() -> None:
    assert repository._ozon_period_from_output_file(
        "OZON_API_ozon_mutual_settlement_2026-04_file.raw.xlsx"
    ) == (date(2026, 4, 1), date(2026, 4, 30))


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
    payload["documentReconciliation"] = [
        {
            **row,
            "payoutStatus": "",
            "periodStatus": "полный период",
            "comment": "Документ совпал",
        }
        for row in payload["documentReconciliation"]
    ]
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
        self.last_reason = ""

    def run(self, db, *, user, report, reason, thread_id=None):
        self.last_reason = reason
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


class FakeSourceRefreshService:
    def __init__(self, workbook_path: Path) -> None:
        self.workbook_path = workbook_path
        self.calls = []

    def run(
        self,
        db,
        *,
        tenant_id,
        client_id=None,
        mode,
        credential_source,
        dry_run,
        user,
        reason,
        source_report=None,
    ):
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "client_id": client_id,
                "mode": mode,
                "credential_source": credential_source,
                "dry_run": dry_run,
                "reason": reason,
            }
        )
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id=tenant_id,
            mode=mode,
            credential_source=credential_source,
            dry_run=dry_run,
            snapshot_set_id=("dry-run-test" if dry_run else "full-test"),
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 17),
            client_id=client_id,
            user=user,
            source_report=source_report,
            reason=reason,
        )
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="running",
            started_at=repository.security.utcnow(),
            root_dir="data/source_refresh/full-test",
        )
        repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="sku_mapping",
            source_label="WB ↔ 1C mapping",
            required=True,
            status="loaded",
            snapshot_hash="hash",
            row_count=3,
            raw_path="data/source_refresh/full-test/mapping/manifest.json",
        )
        if dry_run:
            repository.update_source_refresh_run(
                db,
                refresh_run,
                status="dry_run_ready",
                finished_at=repository.security.utcnow(),
            )
            return repository.source_refresh_run_payload(refresh_run)

        self.workbook_path.parent.mkdir(parents=True, exist_ok=True)
        self.workbook_path.write_bytes(b"full-refresh-xlsx")
        new_report = repository.import_dashboard_payload(
            db,
            ready_payload(),
            tenant_id=tenant_id,
            tenant_name="Refresh tenant",
            report_id="client-full-refresh-report",
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
        return repository.source_refresh_run_payload(refresh_run)

    def enqueue(
        self,
        db,
        *,
        tenant_id,
        client_id=None,
        mode,
        credential_source,
        user,
        reason,
        source_report=None,
    ):
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "client_id": client_id,
                "mode": mode,
                "credential_source": credential_source,
                "dry_run": False,
                "reason": reason,
            }
        )
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id=tenant_id,
            mode=mode,
            credential_source=credential_source,
            dry_run=False,
            snapshot_set_id="full-test",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 17),
            client_id=client_id,
            user=user,
            source_report=source_report,
            reason=reason,
        )
        return repository.source_refresh_run_payload(refresh_run)

    def run_existing(self, db, refresh_run_id):
        refresh_run = db.get(SourceRefreshRun, refresh_run_id)
        assert refresh_run is not None
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="running",
            started_at=repository.security.utcnow(),
            root_dir="data/source_refresh/full-test",
        )
        repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="sku_mapping",
            source_label="WB ↔ 1C mapping",
            required=True,
            status="loaded",
            snapshot_hash="hash",
            row_count=3,
            raw_path="data/source_refresh/full-test/mapping/manifest.json",
        )
        self.workbook_path.parent.mkdir(parents=True, exist_ok=True)
        self.workbook_path.write_bytes(b"full-refresh-xlsx")
        new_report = repository.import_dashboard_payload(
            db,
            ready_payload(),
            tenant_id=refresh_run.tenant_id,
            tenant_name="Refresh tenant",
            report_id="client-full-refresh-report",
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
        return repository.source_refresh_run_payload(refresh_run)


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
    assert summary["quality"]["documentReconciliationRows"] == 1
    assert summary["quality"]["documentReconciliationIssues"] == 1
    assert summary["quality"]["documentReconciliationMissingOnec"] == 0
    assert "Отчет комиссионера" in summary["options"]["documentTypes"]
    assert "OK" in summary["options"]["documentReconciliationStatuses"]


def test_document_reconciliation_endpoint_filters_and_kpis(tmp_path: Path) -> None:
    payload = deepcopy(sample_payload())
    payload["documentReconciliation"][0] = {
        **payload["documentReconciliation"][0],
        "payoutStatus": "",
        "comment": "Чистая сверка",
    }
    payload["documentReconciliation"].append(
        {
            **payload["documentReconciliation"][0],
            "id": "doc-recon-2",
            "status": "Нужна проверка",
            "documentReport": (
                "Отчет комиссионера · 01.06.2026-07.06.2026 · закрытие 07.06.2026"
            ),
            "salesPeriod": "2026-06-01 - 2026-06-07",
            "salesPeriodStart": "2026-06-01",
            "salesPeriodEnd": "2026-06-07",
            "expectedDocumentDate": "2026-06-07",
            "cabinet": "Кабинет B",
            "wbCabinetId": "wb-b",
            "organization": "Организация B",
            "clientCompanyId": "company-b",
            "onecDocuments": "",
            "quantityDelta": 3,
            "amountDelta": 1200,
            "comment": "Нет документа 1С и есть дельта суммы",
        }
    )
    client = make_client(tmp_path, payload=payload)
    login(client)

    response = client.get(
        "/api/reports/report-1/document-reconciliation",
        params={"limit": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 2
    assert len(body["items"]) == 1
    assert body["kpis"]["documentCount"] == 2
    assert body["kpis"]["okRows"] == 1
    assert body["kpis"]["issueRows"] == 1
    assert body["kpis"]["missingOnecRows"] == 1
    assert body["kpis"]["amountDelta"] == 1200

    delta_rows = client.get(
        "/api/reports/report-1/document-reconciliation",
        params={"delta_only": "true"},
    ).json()
    assert delta_rows["total"] == 1
    assert delta_rows["items"][0]["id"] == "doc-recon-2"

    status_rows = client.get(
        "/api/reports/report-1/document-reconciliation",
        params={"status": "Нужна проверка", "period_start": "2026-06-01"},
    ).json()
    assert status_rows["total"] == 1
    assert status_rows["items"][0]["cabinet"] == "Кабинет B"


def test_document_reconciliation_endpoint_caps_limit(tmp_path: Path) -> None:
    payload = deepcopy(sample_payload())
    base_row = {
        **payload["documentReconciliation"][0],
        "payoutStatus": "",
        "comment": "Чистая сверка",
    }
    payload["documentReconciliation"] = [
        {
            **base_row,
            "id": f"doc-recon-{index}",
            "documentReport": f"Документ сверки {index}",
        }
        for index in range(1005)
    ]
    client = make_client(tmp_path, payload=payload)
    login(client)

    response = client.get(
        "/api/reports/report-1/document-reconciliation",
        params={"limit": 5000},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 1005
    assert body["kpis"]["documentCount"] == 1005
    assert len(body["items"]) == 1000


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
    assert (
        client.get("/api/reports/report-1/document-reconciliation").status_code
        == 401
    )


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
    integrations = client.get("/integrations")
    assert integrations.status_code == 200
    assert "/static/app.js" in integrations.text
    ai_page = client.get("/ai")
    assert ai_page.status_code == 200
    assert "/static/app.js" in ai_page.text
    assert 'id="ai-widget-overlay"' in ai_page.text
    assert 'id="ai-widget-close"' in ai_page.text
    assert 'id="client-output-widget-overlay"' in cabinet.text
    assert 'id="client-output-widget-close"' in cabinet.text
    assert 'id="integrations-widget-overlay"' in integrations.text
    assert 'id="integrations-widget-close"' in integrations.text
    assert 'id="drilldown-widget-overlay"' in cabinet.text
    assert 'id="drilldown-widget-close"' in cabinet.text
    assert 'id="drilldown-sources"' in cabinet.text
    assert 'id="drilldown-table-wrap"' in cabinet.text
    assert 'data-drilldown-preset="sources"' in cabinet.text
    assert 'data-drilldown-preset="missingCost"' in cabinet.text
    assert 'data-drilldown-preset="missingMapping"' in cabinet.text
    assert "Расшифровки проблем" in cabinet.text
    assert 'id="integrations-back-link"' not in integrations.text
    assert 'href="/ai"' not in cabinet.text
    assert 'href="/integrations"' not in cabinet.text
    assert 'aria-controls="client-output-widget-overlay"' in cabinet.text
    assert 'aria-controls="ai-widget-overlay"' in cabinet.text
    assert 'aria-controls="integrations-widget-overlay"' in cabinet.text
    assert 'id="rows-filter-form"' in cabinet.text
    assert "filter-document-report" not in cabinet.text
    assert 'id="apply-filters-button"' not in cabinet.text
    assert 'id="report-select"' not in cabinet.text
    assert 'class="report-switcher"' not in cabinet.text
    assert "Применить" not in cabinet.text
    assert 'id="topbar-cabinet-select"' in cabinet.text
    assert 'id="topbar-period-start"' in cabinet.text
    assert 'id="topbar-period-end"' in cabinet.text
    assert 'id="topbar-period-select"' not in cabinet.text
    assert 'id="new-client-button"' in cabinet.text
    assert 'id="new-client-widget-overlay"' in cabinet.text
    assert 'id="new-client-form"' in cabinet.text
    assert "Новый клиент" in cabinet.text
    assert "Кабинет МП" in cabinet.text
    assert 'aria-label="Фильтр по кабинету маркетплейса"' in cabinet.text
    assert "Дата начала" in cabinet.text
    assert "Дата конца" in cabinet.text
    assert "products-table" in cabinet.text
    assert 'class="products-table data-table report-rows-table"' in cabinet.text
    assert 'class="products-table data-table liquidity-table"' in cabinet.text
    assert 'class="products-table data-table lost-sales-table"' in cabinet.text
    assert 'id="analytics-panel"' in cabinet.text
    assert 'id="action-insights-panel"' in cabinet.text
    assert 'id="action-insights-list"' in cabinet.text
    assert "Аналитика" in cabinet.text
    assert 'id="money-trend-chart"' in cabinet.text
    assert 'id="unit-pl-table"' in cabinet.text
    assert "P&amp;L юнит-экономики" in cabinet.text
    assert 'id="loss-drivers-chart"' in cabinet.text
    assert 'id="returns-chart"' in cabinet.text
    assert (
        'class="panel full-width detail-workspace report-page-section"' in cabinet.text
    )
    assert 'data-detail-tab="liquidity"' in cabinet.text
    assert 'data-detail-tab="lostSales"' in cabinet.text
    assert 'data-detail-tab="onecReconciliation"' in cabinet.text
    assert 'data-detail-tab="products"' in cabinet.text
    assert 'id="integration-provider-tabs"' in cabinet.text
    assert 'data-integration-provider-filter="ozon_api"' in cabinet.text
    assert 'id="ozon-diagnostics-panel"' in cabinet.text
    assert 'id="ozon-excel-link"' in cabinet.text
    assert 'id="ozon-preview-rows"' in cabinet.text
    assert 'id="ozon-issue-list"' in cabinet.text
    assert 'id="ozon-vitrine-status"' in cabinet.text
    assert 'id="ozon-pnl-grid"' in cabinet.text
    assert 'id="ozon-buyout-rows"' in cabinet.text
    assert 'id="ozon-diagnostic-message"' in cabinet.text
    assert 'id="ozon-mapping-rows"' in cabinet.text
    assert "Диагностика источников" in cabinet.text
    assert "Ошибки Ozon" in cabinet.text
    assert "Что разобрать первым" in cabinet.text
    assert "Расчетная витрина" in cabinet.text
    assert "Ozon v1" in cabinet.text
    assert "Выкупы Ozon" in cabinet.text
    assert "Ozon + 1C" in cabinet.text
    assert "Excel Ozon" in cabinet.text
    assert "Источники Ozon + 1C" in cabinet.text
    assert "Сопоставление Ozon → 1C" in cabinet.text
    assert "Ozon finance" not in cabinet.text
    assert "cash-flow" not in cabinet.text
    assert "Ozon: детализация по товарам" in cabinet.text
    assert "Offer / SKU" in cabinet.text
    assert "Комиссии / услуги" in cabinet.text
    assert "Партнерские услуги" in cabinet.text
    assert "Прибыль до налогов / маржа" in cabinet.text
    assert "Причина / действие" in cabinet.text
    assert "Номенклатура 1С" in cabinet.text
    assert cabinet.text.index('id="kpi-grid"') < cabinet.text.index(
        'id="ozon-diagnostics-panel"'
    )
    assert cabinet.text.index('id="ozon-diagnostics-panel"') < cabinet.text.index(
        'id="analytics-panel"'
    )
    assert 'id="liquidity-summary"' in cabinet.text
    assert 'class="metric-grid liquidity-insight-grid"' in cabinet.text
    assert "МД1 наценка" in cabinet.text
    assert "МД6 до налогов" in cabinet.text
    assert "Маржа" in cabinet.text
    assert "Юнит-экономика" in cabinet.text
    assert "Расчетная таблица" in cabinet.text
    assert cabinet.text.index('data-detail-tab="products"') < cabinet.text.index(
        'data-detail-tab="liquidity"'
    )
    assert 'data-detail-panel="liquidity"' in cabinet.text
    assert 'data-detail-panel="lostSales"' in cabinet.text
    assert 'data-detail-panel="onecReconciliation"' in cabinet.text
    assert 'data-detail-panel="products"' in cabinet.text
    assert 'data-row-preset="returns"' in cabinet.text
    assert 'id="onec-reconciliation-filter-form"' in cabinet.text
    assert 'id="onec-filter-delta-only"' in cabinet.text
    assert 'id="ai-panel"' in cabinet.text
    assert 'id="integrations-panel"' in cabinet.text
    assert 'id="next-action-upload-form"' in cabinet.text
    assert 'id="next-action-upload-file"' in cabinet.text
    assert 'class="file-picker upload-file-button"' in cabinet.text
    assert "Вставить файл из 1С" in cabinet.text
    assert "Обновить сопоставление" in cabinet.text
    assert "data-tooltip" in cabinet.text
    assert 'id="source-refresh-panel"' in cabinet.text
    assert 'id="source-refresh-mapping-form"' in cabinet.text
    assert 'id="source-refresh-steps"' in cabinet.text
    assert 'id="source-refresh-full-run"' in cabinet.text
    assert 'id="source-refresh-ozon-run"' in cabinet.text
    assert cabinet.text.index('id="source-refresh-panel"') < cabinet.text.index(
        'id="integration-list"'
    )
    assert "Сопоставление и полное обновление" in cabinet.text
    assert "Вставить сопоставление" in cabinet.text
    assert "Проверить" in cabinet.text
    assert "Запустить" in cabinet.text
    assert 'id="mapping-upload-form"' not in cabinet.text
    assert 'id="mapping-upload-file"' not in cabinet.text
    assert 'id="client-structure-panel"' not in cabinet.text
    assert "Источники и свежесть" not in cabinet.text
    assert "Организации и WB-кабинеты" not in cabinet.text
    assert 'class="control-room report-page-section"' in cabinet.text
    assert 'class="decision-strip readiness-neutral"' in cabinet.text
    assert 'class="panel money-strip report-page-section"' in cabinet.text
    assert 'class="decision-support-grid report-page-section"' in cabinet.text
    assert 'class="panel preflight-panel report-page-section"' in cabinet.text
    assert "Готовность, деньги и следующий шаг по клиенту" not in cabinet.text
    assert "Финансовая картина" not in cabinet.text
    assert "Что важно по деньгам" not in cabinet.text
    assert "Перед отправкой" not in cabinet.text
    assert "Смарт-процесс подготовки" not in cabinet.text
    assert cabinet.text.index('id="kpi-title"') < cabinet.text.index(
        'id="readiness-card"'
    )
    assert cabinet.text.index('id="readiness-card"') < cabinet.text.index(
        'id="preflight-title"'
    )
    assert cabinet.text.index('id="quality-title"') < cabinet.text.index(
        'id="blocking-title"'
    )
    assert 'id="quality-summary-text"' in cabinet.text
    assert 'id="quality-progress-fill"' in cabinet.text
    assert "Что проверить в отчете" in cabinet.text
    assert "Как выгрузить файл из 1С" in cabinet.text
    assert "Вывести список" in cabinet.text
    assert "MXL сюда не загружаем" in cabinet.text
    assert "Открыть проблемные строки" in cabinet.text
    assert "Исправить сейчас" in cabinet.text
    assert "В работе у аналитика" in cabinet.text
    assert "Готово к отправке" in cabinet.text
    assert 'id="command-checklist"' not in cabinet.text
    assert 'id="done-reasons"' in cabinet.text
    assert 'id="next-action-button"' in cabinet.text
    assert 'id="client-output-button"' in cabinet.text
    assert 'class="report-only-control"' in cabinet.text
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
    assert "sourceRefreshNewReport" not in app_js.text
    assert "sourceRefreshIssueSummary" not in app_js.text
    assert "/mapping-file" in app_js.text
    assert "mappingUpload" in app_js.text
    assert "mappingUploadControls" in app_js.text
    assert "onMappingUpload" in app_js.text
    assert "mappingUploadRefreshStatus" in app_js.text
    assert "/source-refresh/latest" in app_js.text
    assert "/source-refresh" in app_js.text
    assert "/ozon-diagnostics?" in app_js.text
    assert "/ozon-diagnostics/export.xlsx" in app_js.text
    assert "updateOzonExcelLink" in app_js.text
    assert "Статьи экономики Ozon" in app_js.text
    assert "ozonPartnerServices" in app_js.text
    assert 'params.set("limit", "50")' in app_js.text
    assert 'params.set("period_start"' in app_js.text
    assert 'params.set("period_end"' in app_js.text
    assert 'params.set("wb_cabinet_id"' in app_js.text
    assert "params !== state.ozonDiagnosticsParams" in app_js.text
    assert 'applyTopbarFilter("cabinet")' in app_js.text
    assert "renderOzonIssues" in app_js.text
    assert "renderOzonPnl" in app_js.text
    assert "payload.expenseReconciliation || {}" in app_js.text
    assert "expenseReconciliation.articleRows" in app_js.text
    assert "Из чего состоит дельта расходов" in app_js.text
    assert "Строки без пары" in app_js.text
    assert "setOzonDiagnosticCalculationSectionsVisible" in app_js.text
    assert (
        "const showDiagnosticCalculation = !shouldUseOzonWorkingView();"
        in app_js.text
    )
    assert "if (showDiagnosticCalculation) {" in app_js.text
    assert "renderOzonBuyouts" in app_js.text
    assert "ozonVitrineStatus" in app_js.text
    assert "sourceRefreshPanel" in app_js.text
    assert "sourceRefreshSteps" in app_js.text
    assert "Сопоставление" in app_js.text
    assert "Проверка" in app_js.text
    assert "Обновление" in app_js.text
    assert "Отчет" in app_js.text
    assert "Диагностика" in app_js.text
    assert "runClientSourceRefresh" in app_js.text
    assert "sourceRefreshOzonRun" in app_js.text
    assert 'mode: "ozon-only"' in app_js.text
    assert "Загружаем Ozon + 1C без обязательного WB" in app_js.text
    assert "Проверить готовность" not in app_js.text
    assert "Запустите refresh" not in app_js.text
    assert "Отправляем файл и запускаем пересборку" in app_js.text
    assert "FormData" in app_js.text
    assert "Открыть детали источников" not in app_js.text
    assert "renderClientStructure" not in app_js.text
    assert "renderCommandChecklist" in app_js.text
    assert "renderNextAction" in app_js.text
    assert "renderAnalytics" in app_js.text
    assert "renderActionInsights" in app_js.text
    assert "renderOzonPreview" in app_js.text
    assert "loadOzonDiagnostics" in app_js.text
    assert "renderOzonDiagnosticsPayload" in app_js.text
    assert "Ozon-данные загружены" in app_js.text
    assert "const useOzonWorkingView = shouldUseOzonWorkingView();" in app_js.text
    assert "diagnostics?.ozonMart" in app_js.text
    assert "ozonUnitProfitMarginText" in app_js.text
    assert "partial_source" in app_js.text
    assert "Все кабинеты МП" in app_js.text
    assert "activeMarketplaceCabinets" in app_js.text
    assert "marketplaceCabinetLabel" in app_js.text
    assert "shouldShowOzonPreview" in app_js.text
    assert "ozonMappingRowNode" in app_js.text
    assert "Ozon → 1C" in app_js.text
    assert "offer_id → артикул 1C" in app_js.text
    assert (
        "setEmptyCabinet();\n      await loadOzonDiagnostics(context);"
        in app_js.text
    )
    assert "ozonFinanceRowNode" not in app_js.text
    assert "cash-flow" not in app_js.text
    assert "ozonCollections" in app_js.text
    assert "integrationRowsForActiveProvider" in app_js.text
    assert "Ozon еще не подключен" in app_js.text
    assert "isWbClientCabinet(item)" in app_js.text
    assert "label.includes(\"ozon seller\")" in app_js.text
    assert "syncIntegrationsEntryPoint" in app_js.text
    assert "clientLoadToken" in app_js.text
    assert "currentClientLoadContext" in app_js.text
    assert "isCurrentClientLoad(context)" in app_js.text
    assert "loadReports(currentClientLoadContext())" in app_js.text
    assert "await loadSourceRefreshStatus(context).catch" in app_js.text
    assert "Загружаем клиента" in app_js.text
    assert "renderMetrics(els.kpiGrid, []);" in app_js.text
    assert "renderMetrics(els.qualityGrid, []);" in app_js.text
    assert "!els.ozonPreviewSummary" in app_js.text
    assert "renderIntegrationRowSafe" in app_js.text
    assert "renderCabinetManagerSafe" in app_js.text
    assert "syncSelectedClientFromControl" in app_js.text
    assert "Получаем read-only подключения выбранного клиента." in app_js.text
    assert "renderIntegrationsWithFallback(state.integrationItems)" in app_js.text
    assert "renderIntegrationsRecovery" in app_js.text
    assert "const client = selectedClient();" in app_js.text
    assert "asArray(client?.companies)" in app_js.text
    assert "runAnalyticsAction" in app_js.text
    assert "selectRowsPreset" in app_js.text
    assert "openProductsPreset" in app_js.text
    assert "openProductsMonth" in app_js.text
    assert "els.onecFilterDeltaOnly.checked = true" in app_js.text
    assert 'selectDetailTab("lostSales")' in app_js.text
    assert "renderMoneyTrendChart" in app_js.text
    assert "renderUnitProfitAndLossTable" in app_js.text
    assert "renderLossDriversChart" in app_js.text
    assert "renderReturnsChart" in app_js.text
    assert "renderColumnChart" in app_js.text
    assert "profitAndLossTable" in app_js.text
    assert "analytics-column-chart" in app_js.text
    assert "analytics-pl-table" in app_js.text
    assert "dataset.analyticsAction" in app_js.text
    assert "onecReconciliationDelta" in app_js.text
    assert "renderWaterfallColumns" not in app_js.text
    assert "Chart." not in app_js.text
    assert "chart.js" not in app_js.text.lower()
    assert "echarts" not in app_js.text.lower()
    assert "d3." not in app_js.text
    assert "decisionHeadline" in app_js.text
    assert "preliminaryPeriodNotice" in app_js.text
    assert "Период предварительный: укажите это клиенту" in app_js.text
    assert "Выручка после СПП" in app_js.text
    assert "Упущенные продажи" in app_js.text
    assert "lostSalesRevenue" in app_js.text
    assert "Чистые продажи, шт" in app_js.text
    assert "Возвратность" in app_js.text
    assert "Выручка / продажа" in app_js.text
    assert "item.unitProfit" in app_js.text
    assert "Убыточных строк" in app_js.text
    assert "nonOkSourceCount" in app_js.text
    assert "refreshHasCollectionStatus" in app_js.text
    assert "applyTopbarFilter" in app_js.text
    assert "syncTopbarFiltersFromRows" in app_js.text
    assert "topbarCabinetSelect" in app_js.text
    assert "topbarPeriodStart" in app_js.text
    assert "topbarPeriodEnd" in app_js.text
    assert "newClientButton" in app_js.text
    assert "onNewClientSubmit" in app_js.text
    assert "clientCreateErrorMessage" in app_js.text
    assert "Сервер еще не подхватил обновление" in app_js.text
    assert "Такой код контура уже используется" in app_js.text
    assert "reportSelect" not in app_js.text
    assert "renderReportSelect" not in app_js.text
    assert "payload.kpis" in app_js.text
    assert "payload.analytics" in app_js.text
    assert "filteredAnalyticsSummary" in app_js.text
    assert "bindAutoApplyingFilters" in app_js.text
    assert "applyRowsFilters" in app_js.text
    assert "debounce(applyRowsFilters" in app_js.text
    assert "/api/integrations" in app_js.text
    assert "isIntegrationsPage" in app_js.text
    assert "isAiPage" in app_js.text
    assert "renderAiPageHeader" in app_js.text
    assert "openAiWidget" in app_js.text
    assert "closeAiWidget" in app_js.text
    assert "integration-feedback" in app_js.text
    assert "editingIntegrationKey" in app_js.text
    assert "draftIntegration" in app_js.text
    assert "integration-compact-row" in app_js.text
    assert "integration-edit-form" in app_js.text
    assert "integration-more" in app_js.text
    assert "Новая карточка подключения" in app_js.text
    assert "Тип подключения" in app_js.text
    assert "Создать карточку" in app_js.text
    assert "createDraftIntegrationCard" in app_js.text
    assert "provider_base" in app_js.text
    assert "Настроить" in app_js.text
    assert "Изменить" in app_js.text
    assert "Отмена" in app_js.text
    assert "renderCabinetManager" in app_js.text
    assert "onCabinetManagerSubmit" in app_js.text
    assert "clientScopedFilterOptions" in app_js.text
    assert "Сохранить кабинет" in app_js.text
    assert "buildIntegrationRows" in app_js.text
    assert "findIntegrationForCabinet" in app_js.text
    assert "cabinet_name: form.dataset.cabinetName" in app_js.text
    assert "renderOnecSecretControls" in app_js.text
    assert "onec_base_url" in app_js.text
    assert "URL 1С/OData" in app_js.text
    assert "integration-card--onec-provider" in app_js.text
    assert "integration-optional-pill" in app_js.text
    assert "integration-subtle-action" in app_js.text
    assert "Кабинет / организация" not in app_js.text
    assert "Хранение encrypted storage" not in app_js.text
    assert "Опционально" in app_js.text
    assert "Ozon Seller read-only" in app_js.text
    assert "Ozon кабинет" in app_js.text
    assert "clientId=...; apiKey=..." in app_js.text
    assert "Поля 1С заполнены" in app_js.text
    assert "Новый ключ введен в строке этого кабинета" in app_js.text
    assert "Сохранено. Секрет скрыт" in app_js.text
    assert "Сохраните ключ, затем проверьте подключение" in app_js.text
    assert "Готово к полному обновлению. Отчет еще не создан." in app_js.text
    assert "Отчет создан" in app_js.text
    assert "openClientOutputWidget" in app_js.text
    assert "openIntegrationsWidget" in app_js.text
    assert "closeAllWidgets" in app_js.text
    assert "clientOutputWidgetOverlay" in app_js.text
    assert "integrationsWidgetOverlay" in app_js.text
    assert 'body.classList.add("widget-open")' in app_js.text
    assert "renderIntegrationsEmpty" in app_js.text
    assert "integrationsBackLink" not in app_js.text
    assert "aiWidgetOverlay" in app_js.text
    assert "integrationsPanel.scrollIntoView" not in app_js.text
    assert "aiPanel.scrollIntoView" not in app_js.text
    assert "storageMode" in app_js.text
    assert "lastCheck.message" in app_js.text
    assert "status_filter" in app_js.text
    assert "loss_class" in app_js.text
    assert "document_report" not in app_js.text
    assert "liquidityRows" in app_js.text
    assert "liquidity-rows" in app_js.text
    assert "function asArray" in app_js.text
    assert "sourceLoads = asArray" in app_js.text
    assert "summary.unitRows" not in app_js.text
    assert "URLSearchParams" in app_js.text
    assert "readiness" in app_js.text
    assert "qualitySummaryText" in app_js.text
    assert "qualityProgressFill" in app_js.text
    assert "renderDoneTasks" in app_js.text
    assert "doneReasons" in app_js.text
    assert "taskStatusStorageKey" in app_js.text
    assert "setTaskReviewed" in app_js.text
    assert "detailTabs" in app_js.text
    assert "detailPanels" in app_js.text
    assert "selectDetailTab" in app_js.text
    assert "liquiditySummary" in app_js.text
    assert "liquidityMainDriver" in app_js.text
    assert "renderLiquiditySummary" in app_js.text
    assert "Красная зона" in app_js.text
    assert "Потери в выборке" in app_js.text
    assert "statusLabel" in app_js.text
    assert "Проверить тип документа WB" in app_js.text
    assert "md1Markup" in app_js.text
    assert "md6BeforeTax" in app_js.text
    assert 'selectDetailTab(tab = "products")' in app_js.text
    assert "localStorage" in app_js.text
    assert "/document-reconciliation" in app_js.text
    assert "loadOnecReconciliation" in app_js.text
    assert "renderOnecReconciliation" in app_js.text
    assert "onecReconciliationFilterParams" in app_js.text
    assert "onec_reconciliation_review" in app_js.text
    assert "Проверено" in app_js.text
    assert "Вернуть в работу" in app_js.text
    assert "reasonGuide" in app_js.text
    assert "runReasonAction" in app_js.text
    assert "showRowsPreset" not in app_js.text
    assert "openDrilldownWidget" in app_js.text
    assert "selectDrilldownPreset" in app_js.text
    assert "renderDrilldownRows" in app_js.text
    assert "renderSourceDrilldown" in app_js.text
    assert "sourceStatusText" in app_js.text
    assert "appendTableCells" in app_js.text
    assert "tableRowClass" in app_js.text
    assert "statusTone" in app_js.text
    assert "is-missing-cost" in app_js.text
    assert "has-delta" in app_js.text
    assert "products-panel\").scrollIntoView" not in app_js.text
    assert "missingMapping" in app_js.text
    assert "Показать строки сопоставления" in app_js.text
    assert "Показать источники" in app_js.text
    assert "blocked_low_disk" in app_js.text
    assert "innerHTML" not in app_js.text

    css = client.get("/static/styles.css")
    assert css.status_code == 200
    assert "@media (max-width: 560px)" in css.text
    assert ".filters-bar" in css.text
    assert ".control-room" in css.text
    assert ".money-strip" in css.text
    assert ".decision-strip" in css.text
    assert ".decision-support-grid" in css.text
    assert ".preflight-panel" in css.text
    assert ".preflight-layout" in css.text
    assert ".task-board" in css.text
    assert ".task-column" in css.text
    assert ".task-card" in css.text
    assert ".task-card-actions" in css.text
    assert ".task-done-link" in css.text
    assert ".task-reopen-link" in css.text
    assert ".is-done" in css.text
    assert ".detail-workspace" in css.text
    assert ".detail-tabs" in css.text
    assert ".detail-tab-panel" in css.text
    assert ".new-client-widget" in css.text
    assert ".new-client-form" in css.text
    assert ".liquidity-summary" in css.text
    assert ".liquidity-insight-grid" in css.text
    assert ".metric-bad" in css.text
    assert ".liquidity-table" in css.text
    assert "min-width: 2420px" in css.text
    assert ".filter-checkbox" in css.text
    assert ".quality-progress" in css.text
    assert ".reason-item" in css.text
    assert ".reason-action-link" in css.text
    assert ".reason-hint" in css.text
    assert ".quality-diagnostics" in css.text
    assert ".drilldown-widget" in css.text
    assert ".drilldown-tabs" in css.text
    assert ".drilldown-table-wrap" in css.text
    assert ".drilldown-sources" in css.text
    assert ".source-load-card" in css.text
    assert ".source-load-status" in css.text
    assert ".next-action-panel" in css.text
    assert ".command-checklist" in css.text
    assert ".command-metrics" in css.text
    assert ".action-insights-panel" in css.text
    assert ".action-insight-card" in css.text
    assert ".row-preset-bar" in css.text
    assert ".report-rows-table" in css.text
    assert ".table-badge" in css.text
    assert ".products-table tbody tr.is-loss" in css.text
    assert ".products-table tbody tr.has-delta" in css.text
    assert "position: sticky" in css.text
    assert ".next-action-upload-form" in css.text
    assert ".next-action-controls" in css.text
    assert "[data-tooltip]" in css.text
    assert "top: calc(100% + 14px)" in css.text
    assert "border-bottom-color: var(--text)" in css.text
    assert "bottom: calc(100% + 14px)" not in css.text
    assert ".upload-file-button" in css.text
    assert ".upload-guidance" in css.text
    assert ".upload-help" in css.text
    assert ".upload-submit-button" in css.text
    assert "-webkit-overflow-scrolling: touch" in css.text
    assert "width: max-content" in css.text
    assert ".ai-workspace" in css.text
    assert ".widget-overlay" in css.text
    assert ".widget-shell" in css.text
    assert ".widget-actions" in css.text
    assert "body.widget-open" in css.text
    assert ".client-output-widget" in css.text
    assert ".integrations-widget" in css.text
    assert ".ai-widget" in css.text
    assert ".integration-card" in css.text
    assert ".integration-empty" in css.text
    assert ".integration-details" in css.text
    assert ".integration-feedback" in css.text
    assert ".integration-compact-row" in css.text
    assert ".integration-edit-form" in css.text
    assert ".integration-read-badge" in css.text
    assert ".integration-more" in css.text
    assert ".integration-cabinet-manager" in css.text
    assert ".integration-card-creator-form" in css.text
    assert ".integration-type-field" in css.text
    assert ".integration-cabinet-field" in css.text
    assert ".cabinet-manager-form" in css.text
    assert ".integration-list-header" in css.text
    assert ".integration-target" not in css.text
    assert ".integration-subtle-action" in css.text
    assert ".integration-compact-field" in css.text
    assert ".integration-card--onec-provider" in css.text
    assert ".integration-form--onec" in css.text
    assert ".onec-secret-fields" in css.text
    assert ".integration-toggle-field" in css.text
    assert "grid-template-areas" in css.text
    assert '"role status"' in css.text
    assert '"secret status"' in css.text
    assert ".integration-card--ok" in css.text
    assert ".integration-status-pill" in css.text
    assert ".client-structure-grid" not in css.text
    assert ".source-refresh-panel" in css.text
    assert ".source-refresh-collections" in css.text
    assert ".ozon-preview-grid" in css.text
    assert ".ozon-issue-panel" in css.text
    assert ".ozon-issue-list" in css.text
    assert ".ozon-pnl-grid" in css.text
    assert ".ozon-pnl-table" in css.text
    assert ".ozon-buyout-table" in css.text
    assert ".ozon-preview-table" in css.text
    assert ".mapping-upload-form" not in css.text
    assert "reason-columns" not in css.text
    assert ".file-picker" in css.text
    assert "overflow-wrap: anywhere" in css.text


def test_mapping_file_upload_saves_local_source_and_audits(tmp_path: Path) -> None:
    mapping_dir = tmp_path / "mapping_uploads"
    client = make_client(
        tmp_path,
        settings_overrides={"source_refresh_mapping_dir": str(mapping_dir)},
    )
    login(client)

    content = "Товар WB\tАртикул WB\tnmId\nПлатье\tART-1\t1001\n".encode()
    response = client.post(
        "/api/reports/report-1/mapping-file",
        files={"file": ("Организация A.csv", content, "text/csv")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "uploaded"
    assert payload["fileName"] == "Организация_A.txt"
    assert payload["autoRefresh"]["status"] == "disabled"
    saved = mapping_dir / "Организация_A.txt"
    assert saved.read_bytes() == content

    audit = client.get("/api/admin/audit").json()["items"]
    event = next(item for item in audit if item["action"] == "mapping_file_uploaded")
    assert event["entityId"] == "report-1"
    assert event["payload"]["fileName"] == "Организация_A.txt"
    assert "Платье" not in str(event)


def test_mapping_file_upload_auto_refreshes_and_returns_new_report(
    tmp_path: Path,
) -> None:
    mapping_dir = tmp_path / "mapping_uploads"
    fake_service = FakeAutoRefreshService(tmp_path / "reports" / "auto-refresh.xlsx")
    client = make_client(
        tmp_path,
        settings_overrides={
            "source_refresh_enabled": True,
            "source_refresh_mapping_dir": str(mapping_dir),
        },
        auto_refresh_service=fake_service,
    )
    login(client)

    response = client.post(
        "/api/reports/report-1/mapping-file",
        files={"file": ("СопоставлениеНоменклатуры.txt", b"a\tb\n", "text/plain")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "uploaded"
    assert payload["autoRefresh"]["status"] == "report_created"
    assert payload["autoRefresh"]["jobType"] == "source_refresh"
    assert payload["autoRefresh"]["sourceReportRunId"] == "report-1"
    assert payload["autoRefresh"]["newReportRunId"] == "report-1-refresh"
    assert (
        "Автоматическая пересборка после загрузки mapping"
        in fake_service.last_reason
    )
    assert "a\tb" not in str(payload)
    assert (mapping_dir / "СопоставлениеНоменклатуры.txt").read_bytes() == b"a\tb\n"
    new_summary = client.get("/api/reports/report-1-refresh/summary").json()
    assert new_summary["quality"]["missingCostRows"] == 0


def test_mapping_file_upload_is_staff_only(tmp_path: Path) -> None:
    mapping_dir = tmp_path / "mapping_uploads"
    client = make_client(
        tmp_path,
        settings_overrides={"source_refresh_mapping_dir": str(mapping_dir)},
    )
    login(client)
    created = client.post(
        "/api/admin/users",
        json={"email": "mapping-client@example.com", "role": "client"},
    ).json()
    client.post("/api/auth/logout")
    login_as(client, "mapping-client@example.com", created["temporaryPassword"])

    forbidden = client.post(
        "/api/reports/report-1/mapping-file",
        files={"file": ("mapping.txt", b"a\tb\n", "text/plain")},
    )

    assert forbidden.status_code == 403
    assert not mapping_dir.exists()


def test_client_mapping_file_upload_and_source_refresh_controls(
    tmp_path: Path,
) -> None:
    mapping_dir = tmp_path / "client_mapping_uploads"
    fake_refresh = FakeSourceRefreshService(
        tmp_path / "reports" / "client-full-refresh.xlsx"
    )
    client = make_client(
        tmp_path,
        settings_overrides={
            "source_refresh_mapping_dir": str(mapping_dir),
            "source_refresh_enabled": True,
        },
    )
    client.app.state.source_refresh_service = fake_refresh
    login(client)

    upload = client.post(
        "/api/clients/shumeyko/mapping-file",
        files={"file": ("Галустов mapping.csv", b"wb\tonec\n", "text/csv")},
    )

    assert upload.status_code == 200
    upload_payload = upload.json()
    assert upload_payload["status"] == "uploaded"
    assert upload_payload["fileName"] == "Галустов_mapping.txt"
    assert (mapping_dir / "Галустов_mapping.txt").read_bytes() == b"wb\tonec\n"
    assert "wb\tonec" not in str(upload_payload)

    dry_run = client.post(
        "/api/clients/shumeyko/source-refresh",
        json={"mode": "full", "dry_run": True},
    )

    assert dry_run.status_code == 200
    assert dry_run.json()["latest"]["status"] == "dry_run_ready"
    assert fake_refresh.calls[-1]["dry_run"] is True
    assert fake_refresh.calls[-1]["tenant_id"] == "shumeyko"
    assert fake_refresh.calls[-1]["client_id"] == "shumeyko"

    ozon_only = client.post(
        "/api/clients/shumeyko/source-refresh",
        json={"mode": "ozon-only", "dry_run": True},
    )

    assert ozon_only.status_code == 200
    assert fake_refresh.calls[-1]["mode"] == "ozon-only"
    assert fake_refresh.calls[-1]["dry_run"] is True

    full = client.post(
        "/api/clients/shumeyko/source-refresh",
        json={"mode": "full", "dry_run": False},
    )

    assert full.status_code == 200
    payload = full.json()["latest"]
    assert payload["status"] == "queued"
    assert payload["newReportRunId"] is None
    assert payload["collections"] == []
    assert fake_refresh.calls[-1]["dry_run"] is False
    assert fake_refresh.calls[-1]["client_id"] == "shumeyko"

    latest = client.get("/api/clients/shumeyko/source-refresh/latest")
    assert latest.status_code == 200
    latest_payload = latest.json()["latest"]
    assert latest_payload["id"] == payload["id"]
    assert latest_payload["status"] == "report_created"
    assert latest_payload["newReportRunId"] == "client-full-refresh-report"
    assert latest_payload["collections"][0]["sourceType"] == "sku_mapping"
    assert latest_payload["collections"][0]["rawPath"] == ""


def test_client_ozon_diagnostics_returns_safe_latest_ozon_only_snapshot(
    tmp_path: Path,
) -> None:
    ozon_product_name = "Ozon, product, name, with, commas, in, title, example"
    mapping_dir = tmp_path / "ozon_mapping"
    mapping_dir.mkdir()
    (mapping_dir / "sopostavlenie_ozon.txt").write_text(
        (
            "Номенклатура Ozon\tНоменклатура\tХарактеристика\tУпаковка\n"
            f"{ozon_product_name}\tТовар Ozon 1C\t\t\n"
        ),
        encoding="utf-8",
    )
    client = make_client(
        tmp_path,
        settings_overrides={"source_refresh_enabled": True},
    )
    login(client)
    with client.app.state.session_factory() as db:
        user = db.query(repository.User).filter_by(email="admin@example.com").one()
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            mode="ozon-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="ozon-only-test",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 17),
            user=user,
            reason="Ozon diagnostic test",
        )
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="running",
            started_at=repository.security.utcnow(),
            root_dir="data/source_refresh/ozon-only-test",
        )
        repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="sku_mapping",
            source_label="WB ↔ 1C mapping",
            required=True,
            status="loaded",
            row_count=5,
            raw_path=str(mapping_dir),
        )
        sales_collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="onec_sales_register",
            source_label="AccumulationRegister_Продажи",
            required=True,
            status="loaded",
            row_count=48,
        )
        repository.add_source_snapshot_row(
            db,
            sales_collection,
            row_number=1,
            raw_payload_hash="onec-sales-hash-1",
            source_row_id="sales-1",
            row_payload={
                "RecordSet": [
                    {
                        "Номенклатура_Key": "ITEM-1",
                        "Количество": "2",
                        "Себестоимость": "600",
                    },
                    {
                        "Period": "2026-05-31T01:00:00",
                        "Контрагент_Key": "OZON-CP",
                        "Документ": "OZON-DOC-1",
                        "Номенклатура_Key": "ITEM-1",
                        "Количество": "3",
                        "Сумма": "900",
                        "Себестоимость": "0",
                    }
                ]
            },
        )
        commissioner_collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="onec_commissioner_reports",
            source_label="Document_ОтчетКомиссионера",
            required=True,
            status="loaded",
            row_count=1,
        )
        repository.add_source_snapshot_row(
            db,
            commissioner_collection,
            row_number=1,
            raw_payload_hash="onec-commissioner-hash-1",
            source_row_id="ozon-commissioner-1",
            row_payload={
                "Date": "2026-05-31T01:00:00",
                "Number": "НФНФ-000033",
                "Posted": True,
                "Комментарий": (
                    "ОЗОН Отчет комиссионера № 16 567 305 "
                    "от 01.05.2026 0:00:00 по 31.05.2026 0:00:00"
                ),
                "Контрагент_Key": "OZON-CP",
                "Запасы": [
                    {
                        "Номенклатура_Key": "ITEM-1",
                        "Количество": "2",
                        "Всего": "600",
                        "СуммаНДС": "100",
                    },
                    {
                        "Номенклатура_Key": "ITEM-1",
                        "Количество": "1",
                        "Всего": "400",
                        "СуммаНДС": "80",
                    },
                ],
                "ЗапасыВозвраты": [
                    {
                        "Номенклатура_Key": "ITEM-1",
                        "Количество": "1",
                        "Всего": "100",
                        "СуммаНДС": "18",
                    },
                ],
            },
        )
        expense_invoice_collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="onec_expense_invoices",
            source_label="Document_РасходнаяНакладная",
            required=False,
            status="loaded",
            row_count=3,
        )
        repository.add_source_snapshot_row(
            db,
            expense_invoice_collection,
            row_number=1,
            raw_payload_hash="onec-buyout-hash-duplicate",
            source_row_id="НФНФ-000041",
            row_payload={
                "Date": "2026-05-10T00:00:00",
                "Number": "НФНФ-000041",
                "ОснованиеПечати": "Выкуп",
                "Комментарий": "Отчет о выкупе №4767782 от 15.05.2026",
                "Запасы": [
                    {"Количество": "239", "Всего": "485503.40"},
                ],
            },
        )
        repository.add_source_snapshot_row(
            db,
            expense_invoice_collection,
            row_number=2,
            raw_payload_hash="onec-buyout-hash-1",
            source_row_id="НФНФ-000040",
            row_payload={
                "Date": "2026-05-15T00:00:00",
                "Number": "НФНФ-000040",
                "ОснованиеПечати": "Выкуп",
                "Комментарий": (
                    "ОЗОН Создан на основании отчета о выкупленных товарах "
                    "№ 4767782 от 01.05.2026 0:00:00 по 15.05.2026 0:00:00"
                ),
                "Запасы": [
                    {"Количество": "239", "Всего": "485503.40"},
                ],
            },
        )
        repository.add_source_snapshot_row(
            db,
            expense_invoice_collection,
            row_number=3,
            raw_payload_hash="onec-buyout-hash-2",
            source_row_id="НФНФ-000107",
            row_payload={
                "Date": "2026-05-31T00:00:00",
                "Number": "НФНФ-000107",
                "Комментарий": (
                    "Создан на основании отчета о выкупленных товарах "
                    "№ 4901196 от 16.05.2026 0:00:00 по 31.05.2026 0:00:00"
                ),
                "Запасы": [
                    {"Количество": "217", "Всего": "446196.64"},
                ],
            },
        )
        onec_collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="onec_nomenclature",
            source_label="Catalog_Номенклатура",
            required=True,
            status="loaded",
            row_count=2,
        )
        repository.add_source_snapshot_row(
            db,
            onec_collection,
            row_number=1,
            raw_payload_hash="onec-hash-1",
            source_row_id="ITEM-1",
            row_payload={
                "Ref_Key": "ITEM-1",
                "Description": "Товар Ozon 1C",
                "Артикул": "OZ-1",
            },
        )
        repository.add_source_snapshot_row(
            db,
            onec_collection,
            row_number=2,
            raw_payload_hash="onec-hash-2",
            source_row_id="ITEM-2",
            row_payload={
                "Ref_Key": "ITEM-2",
                "Description": "Товар Ozon дубль",
                "Артикул": "OZ-1",
            },
        )
        barcode_collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="onec_barcodes",
            source_label="InformationRegister_ШтрихкодыНоменклатуры",
            required=False,
            status="loaded",
            row_count=1,
        )
        repository.add_source_snapshot_row(
            db,
            barcode_collection,
            row_number=1,
            raw_payload_hash="barcode-hash-1",
            source_row_id="barcode-1",
            row_payload={
                "Штрихкод": "12345",
                "Номенклатура_Key": "ITEM-1",
            },
        )
        ozon_products = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="ozon_products_report",
            source_label="Ozon products report",
            required=False,
            status="loaded",
            row_count=1,
        )
        repository.add_source_snapshot_row(
            db,
            ozon_products,
            row_number=1,
            raw_payload_hash="ozon-product-hash-1",
            source_row_id="product-1",
            row_payload={
                "Название товара": ozon_product_name,
                "Артикул продавца": "OZ-1",
                "ID товара": "product-1",
                "SKU": "12345",
                "Штрихкод": "12345",
                "apiKey": "must-not-leak-product",
            },
        )
        ozon_collection = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="ozon_finance_cash_flow",
            source_label="Ozon financial cash-flow statement",
            required=True,
            status="loaded",
            row_count=2,
        )
        repository.add_source_snapshot_row(
            db,
            ozon_collection,
            row_number=1,
            raw_payload_hash="hash-1",
            source_row_id="op-1",
            row_payload={
                "marketplace": "ozon",
                "operation_id": "op-1",
                "operation_date": "2026-06-01",
                "operation_type": "cash_flow",
                "offer_id": "OZ-1",
                "sku": "12345",
                "price": "1000",
                "details": [
                    {
                        "period": {
                            "begin": "2026-05-01T00:00:00Z",
                            "end": "2026-05-31T00:00:00Z",
                        },
                        "services": {"total": "-100"},
                        "return": {"total": "0"},
                        "others": {"total": "0"},
                    }
                ],
                "apiKey": "must-not-leak",
                "raw": {"clientId": "must-not-leak-too"},
            },
        )
        repository.add_source_snapshot_row(
            db,
            ozon_collection,
            row_number=2,
            raw_payload_hash="hash-2",
            source_row_id="op-2",
            row_payload={
                "operation_id": "op-2",
                "offer_id": "OZ-2",
                "price": "2500",
            },
        )
        ozon_realization = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="ozon_realization",
            source_label="Ozon realization report",
            required=False,
            status="loaded",
            row_count=1,
        )
        repository.add_source_snapshot_row(
            db,
            ozon_realization,
            row_number=1,
            raw_payload_hash="ozon-realization-hash-1",
            source_row_id="realization-1",
            row_payload={
                "offer_id": "OZ-1",
                "sku": "12345",
                "sale_qty": "2",
                "sale_amount": "1000",
                "commission_amount": "50",
                "services_amount": "10",
                "logistics_amount": "20",
                "storage_amount": "5",
                "other_amount": "15",
            },
        )
        ozon_buyout = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="ozon_products_buyout",
            source_label="Ozon products buyout report",
            required=False,
            status="loaded",
            row_count=1,
            payload={
                "marketplace": "ozon",
                "results": [
                    {
                        "sellerAccountId": "OZON_API",
                        "pageIndex": 1,
                        "outputFile": (
                            "OZON_API_ozon_products_buyout_"
                            "2026-05-01_2026-05-31.raw.json"
                        ),
                    }
                ],
            },
        )
        repository.add_source_snapshot_row(
            db,
            ozon_buyout,
            row_number=1,
            raw_payload_hash="ozon-buyout-hash-1",
            source_row_id="ozon_products_buyout:1:1",
            row_payload={
                "seller_account_id": "OZON_API",
                "products": [
                    {"quantity": "239", "amount": "485503.40"},
                    {"quantity": "217", "amount": "446196.64"},
                ],
            },
        )
        ozon_b2b = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="ozon_b2b_sales_json",
            source_label="Ozon B2B sales JSON",
            required=False,
            status="loaded",
            row_count=1,
        )
        repository.add_source_snapshot_row(
            db,
            ozon_b2b,
            row_number=1,
            raw_payload_hash="ozon-b2b-hash-1",
            source_row_id="ozon_b2b_sales_json:1:1",
            row_payload={
                "invoices": [
                    {
                        "number": "B2B-1",
                        "amount": "777777.77",
                        "items": [{"offer_id": "OZ-1", "amount": "777777.77"}],
                    }
                ],
            },
        )
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="source_loaded",
            finished_at=repository.security.utcnow(),
        )
        db.commit()

    response = client.get("/api/clients/shumeyko/ozon-diagnostics?limit=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ready"
    assert payload["latestRun"]["mode"] == "ozon-only"
    assert payload["readiness"] == {
        "ozonFinanceLoaded": True,
        "ozonRealizationLoaded": True,
        "mappingLoaded": True,
        "onecRequiredLoaded": True,
        "reportExpected": False,
    }
    assert payload["sourceSummary"]["ozonFinance"]["rowCount"] == 2
    assert payload["sourceSummary"]["ozonRealization"]["rowCount"] == 1
    assert payload["sourceSummary"]["ozonBuyouts"]["rowCount"] == 2
    assert payload["sourceSummary"]["ozonBuyouts"]["snapshotRows"] == 1
    assert payload["sourceSummary"]["ozonBuyouts"]["productRows"] == 2
    assert payload["sourceSummary"]["ozonProducts"]["rowCount"] == 1
    assert payload["sourceSummary"]["mapping"]["rowCount"] == 5
    assert payload["sourceSummary"]["onec"]["rowCount"] == 55
    assert payload["ozonBuyouts"]["summary"] == {
        "foundInOzonApi": 2,
        "missingInOzonApi": 0,
        "matchedByReportNumber": 0,
        "matchedByPeriodTotal": 2,
        "ozonApiRows": 1,
        "ozonApiProductRows": 2,
        "ozonApiLoaded": True,
        "ozonApiAmount": 931700.04,
        "ozonApiQuantity": 456.0,
        "ozonApiLoadedAmount": 931700.04,
        "ozonApiLoadedQuantity": 456.0,
        "ozonApiLoadedProductRows": 2,
        "amount": 931700.04,
        "quantity": 456.0,
    }
    buyout_response = client.get("/api/clients/shumeyko/ozon-diagnostics?limit=5")
    assert buyout_response.status_code == 200
    assert buyout_response.json()["ozonBuyouts"]["rows"] == [
        {
            "rowNumber": 2,
            "sourceRowId": "НФНФ-000040",
            "documentNumber": "НФНФ-000040",
            "documentDate": "2026-05-15",
            "basis": "Выкуп",
            "reportNumber": "4767782",
            "periodFrom": "2026-05-01",
            "periodTo": "2026-05-15",
            "quantity": 239.0,
            "amount": 485503.4,
            "foundInOzonApi": True,
            "ozonMatchStatus": "matched_by_period_total",
            "ozonMatchedPeriodFrom": "2026-05-01",
            "ozonMatchedPeriodTo": "2026-05-31",
            "ozonMatchedQuantity": 456.0,
            "ozonMatchedAmount": 931700.04,
        },
        {
            "rowNumber": 3,
            "sourceRowId": "НФНФ-000107",
            "documentNumber": "НФНФ-000107",
            "documentDate": "2026-05-31",
            "basis": "",
            "reportNumber": "4901196",
            "periodFrom": "2026-05-16",
            "periodTo": "2026-05-31",
            "quantity": 217.0,
            "amount": 446196.64,
            "foundInOzonApi": True,
            "ozonMatchStatus": "matched_by_period_total",
            "ozonMatchedPeriodFrom": "2026-05-01",
            "ozonMatchedPeriodTo": "2026-05-31",
            "ozonMatchedQuantity": 456.0,
            "ozonMatchedAmount": 931700.04,
        },
    ]
    assert payload["ozonMapping"]["status"] == "ready"
    assert payload["ozonMapping"]["checkedRows"] == 1
    assert payload["ozonMapping"]["summary"] == {
        "matched": 1,
        "missing": 0,
        "ambiguous": 0,
        "noKey": 0,
        "notChecked": 0,
    }
    assert payload["ozonMapping"]["rows"] == [
        {
            "rowNumber": 1,
            "sourceRowId": "product-1",
            "productName": ozon_product_name,
            "offerId": "OZ-1",
            "productId": "product-1",
            "sku": "12345",
            "barcode": "12345",
            "status": "matched",
            "matchMethod": "uploaded_mapping_name",
            "matchKey": ozon_product_name,
            "onecItemId": "ITEM-1",
            "onecName": "Товар Ozon 1C",
            "onecArticle": "OZ-1",
        }
    ]
    assert payload["finance"]["rowCount"] == 2
    assert payload["finance"]["previewRowCount"] == 1
    assert payload["finance"]["previewLimited"] is True
    assert payload["finance"]["totals"]["price"] == 1000
    assert payload["financeRows"] == [
        {
            "rowNumber": 1,
            "sourceRowId": "op-1",
            "loadedAt": payload["financeRows"][0]["loadedAt"],
            "operationId": "op-1",
            "operationDate": "2026-06-01",
            "operationType": "cash_flow",
            "offerId": "OZ-1",
            "productId": "",
            "sku": "12345",
            "amount": None,
            "price": 1000.0,
            "income": None,
            "expense": None,
            "sourceEndpoint": "",
            "hasMappingKey": True,
        }
    ]
    assert payload["pnl"]["status"] == "provisional"
    assert payload["pnl"]["cashFlowRows"] == 0
    assert payload["pnl"]["realizationRows"] == 1
    assert payload["pnl"]["itemLevelRows"] == 1
    assert payload["pnl"]["costedItemRows"] == 1
    assert payload["pnl"]["totals"]["cashFlowRevenue"] == 0.0
    assert payload["pnl"]["totals"]["revenue"] == 900.0
    assert payload["pnl"]["totals"]["revenueBasis"] == "onec_sales_register"
    assert payload["pnl"]["totals"]["ozonExpenses"] == 100.0
    assert payload["pnl"]["totals"]["expenseBasis"] == "ozon_cash_flow_statement"
    assert payload["pnl"]["totals"]["profitBeforeCogs"] == 800.0
    assert payload["pnl"]["totals"]["onecCogs"] == 600.0
    assert payload["pnl"]["totals"]["profitAfterCogs"] == 200.0
    assert payload["unitRows"]["rowCount"] == 2
    assert payload["unitRows"]["previewRowCount"] == 1
    assert payload["unitRows"]["previewLimited"] is True
    assert payload["unitRows"]["summary"] == {
        "ready": 1,
        "partialSource": 0,
        "missingMapping": 0,
        "ambiguousMapping": 0,
        "missingCost": 0,
        "missing1cCommissioner": 0,
        "buyoutPeriodOnly": 1,
        "partialExpenses": 0,
    }
    assert payload["unitRows"]["rows"] == [
        {
            "rowType": "realization_item",
            "periodStart": None,
            "periodEnd": None,
            "rowNumber": 1,
            "sourceRowId": "realization-1",
            "productName": ozon_product_name,
            "offerId": "OZ-1",
            "productId": "product-1",
            "sku": "12345",
            "barcode": "12345",
            "quantity": 2.0,
            "realizationAmount": 1000.0,
            "onecRevenue": 900.0,
            "revenueAmount": 900.0,
            "revenueBasis": "onec_commissioner_sku",
            "onecItemId": "ITEM-1",
            "onecName": "Товар Ozon 1C",
            "unitCost": 300.0,
            "cogs": 600.0,
            "cogsAmount": 600.0,
            "ozonCommission": 50.0,
            "ozonServices": 10.0,
            "ozonPartnerServices": None,
            "ozonLogistics": 20.0,
            "ozonStorage": 5.0,
            "ozonOtherExpenses": 15.0,
            "ozonExpenses": 100.0,
            "profit": 200.0,
            "profitAmount": 200.0,
            "margin": 200 / 900,
            "mappingStatus": "matched",
            "qualityStatus": "ready",
            "expenseStatus": "loaded",
            "expenseBasis": "ozon_realization_sku_fields",
            "expenseAllocationBasis": "",
            "expenseAllocationShare": None,
            "problemReason": "Можно читать прибыль Ozon по товару.",
            "statusReason": "Можно читать прибыль Ozon по товару.",
            "actionText": "Действие не требуется.",
        }
    ]
    assert payload["ozonMart"]["basis"] == "staff_only_ozon_unit_economics_mart_v1"
    assert payload["ozonMart"]["summary"]["ready"] == 1
    assert payload["ozonMart"]["summary"]["buyoutPeriodOnly"] == 1
    assert payload["ozonMart"]["articleDrilldown"][0]["includedInSkuProfit"] is True
    assert payload["ozonMart"]["totals"] == {
        "quantity": 2.0,
        "onecRevenue": 900.0,
        "cogs": 600.0,
        "ozonExpenses": 100.0,
        "profit": 200.0,
        "margin": 200 / 900,
        "expenseBasis": "ozon_cash_flow_statement",
    }
    assert payload["expenseReconciliation"]["status"] == "review"
    assert payload["expenseReconciliation"]["ozonExpenseAmount"] == 100.0
    assert payload["expenseReconciliation"]["onecExpenseAmount"] is None
    assert payload["reconciliation"] == {
        "status": "review",
        "message": "Ozon realization плюс Ozon buyout пока не сходятся с 1C.",
        "commissionerAmount": 900.0,
        "buyoutAmount": 931700.04,
        "ozonTotalAmount": 932600.04,
        "onecSalesRegisterAmount": 900.0,
        "deltaAmount": -931700.04,
        "buyoutQuantity": 456.0,
        "matchedBuyouts": 2,
        "missingBuyouts": 0,
        "matchedWithoutReportNumber": 2,
    }
    assert payload["pnl"]["onecOzon"] == {
        "status": "loaded",
        "counterpartyLabel": "ООО Интернет Решения",
        "counterpartyIds": ["OZON-CP"],
        "reportCount": 1,
        "salesLines": 2,
        "returnLines": 1,
        "salesQuantity": 3.0,
        "returnQuantity": 1.0,
        "salesAmount": 1000.0,
        "returnsAmount": 100.0,
        "netSalesAmount": 900.0,
        "vatAmount": 180.0,
        "returnVatAmount": 18.0,
        "salesRegister": {
            "rowCount": 1,
            "documentCount": 1,
            "quantity": 3.0,
            "amount": 900.0,
            "cost": 0.0,
            "deltaVsCommissionerNet": 0.0,
        },
    }
    assert payload["pnl"]["periods"] == []

    export = client.get("/api/clients/shumeyko/ozon-diagnostics/export.xlsx")
    assert export.status_code == 200
    assert "ozon_unit_economics" in export.headers["content-disposition"]
    workbook = load_workbook(BytesIO(export.content), read_only=True, data_only=True)
    try:
        assert workbook.sheetnames == [
            "Сводная Ozon",
            "Юнит экономика Ozon",
            "Начисления услуг Ozon",
            "Статьи по SKU",
            "Сверка Ozon 1C",
            "Методика",
        ]
        unit_headers = [cell.value for cell in workbook["Юнит экономика Ozon"][1]]
        reconciliation_headers = [
            cell.value for cell in workbook["Сверка Ozon 1C"][1]
        ]
        reconciliation_values = [
            cell.value for cell in workbook["Сверка Ozon 1C"][2]
        ]
    finally:
        workbook.close()
    assert "Услуги партнеров / перевыставление" in unit_headers
    assert "Ozon API" in reconciliation_headers
    assert reconciliation_values

    filtered_response = client.get(
        "/api/clients/shumeyko/ozon-diagnostics"
        "?period_start=2026-06-01&period_end=2026-06-30&limit=10"
    )
    assert filtered_response.status_code == 200
    filtered_payload = filtered_response.json()
    assert filtered_payload["pnl"]["cashFlowRows"] == 0
    assert filtered_payload["pnl"]["periodFilter"] == {
        "periodStart": "2026-06-01",
        "periodEnd": "2026-06-30",
    }
    assert filtered_payload["pnl"]["totals"]["revenue"] == 0.0
    assert filtered_payload["pnl"]["totals"]["profitBeforeCogs"] == 0.0
    assert filtered_payload["pnl"]["onecOzon"]["status"] == "missing"
    assert filtered_payload["pnl"]["status"] == "partial_source"
    assert filtered_payload["unitRows"]["rows"][0]["qualityStatus"] == (
        "missing_1c_commissioner"
    )
    assert filtered_payload["unitRows"]["rows"][0]["expenseStatus"] == "loaded"
    assert filtered_payload["ozonMart"]["status"] == "partial_source"
    assert filtered_payload["unitRows"]["rows"][0]["revenueAmount"] is None
    assert filtered_payload["unitRows"]["rows"][0]["profitAmount"] is None
    assert "ozon_onec_commissioner_missing" in [
        item["code"] for item in filtered_payload["issues"]["items"]
    ]
    assert filtered_payload["pnl"]["periods"] == []
    assert payload["issues"]["blockingCount"] == 0
    assert payload["issues"]["reviewCount"] == 1
    assert payload["issues"]["items"] == [
        {
            "code": "ozon_buyout_matched_without_report_number",
            "title": "Выкупы Ozon",
            "value": "2 отчетов",
            "detail": (
                "Сумма и количество сходятся с Ozon buyout за период, "
                "но Ozon API не вернул номер выкупного отчета."
            ),
            "tone": "review",
        }
    ]
    assert "must-not-leak" not in str(payload)
    assert "raw_payload_hash" not in str(payload)


def test_ozon_mapping_prefers_onec_marketplace_ozon_mapping_before_fallback() -> None:
    indexes = {
        "byName": {},
        "byArticle": {
            "oz-1": [{"id": "ITEM-2", "name": "Fallback item", "article": "OZ-1"}]
        },
        "byCode": {},
        "byBarcode": {},
        "byOzonNameMapping": {},
        "nomenclatureRows": 1,
        "barcodeRows": 0,
    }
    indexes.update(
        repository._ozon_onec_marketplace_mapping_indexes_from_rows(
            [
                SimpleNamespace(
                    source_type="onec_marketplace_ozon_mapping",
                    row_payload={
                        "marketplace": "ozon",
                        "offer_id": "OZ-1",
                        "product_id": "product-1",
                        "sku": "12345",
                        "barcode": "4600000000000",
                        "ozon_name": "Ozon product",
                        "onec_item_id": "ITEM-1",
                        "onec_name": "Товар из 1C Ozon mapping",
                        "onec_article": "OZ-1",
                        "status": "matched",
                    },
                )
            ]
        )
    )

    checked = repository._check_ozon_mapping_candidate(
        {
            "rowNumber": 1,
            "sourceRowId": "realization-1",
            "productName": "Ozon product",
            "offerId": "OZ-1",
            "productId": "product-1",
            "sku": "12345",
            "barcode": "4600000000000",
        },
        indexes,
    )

    assert checked["statusCounter"] == "matched"
    assert checked["row"]["matchMethod"] == "onec_marketplace_ozon_offer"
    assert checked["row"]["onecItemId"] == "ITEM-1"


def test_ozon_mapping_ignores_generic_onec_marketplace_wb_rows() -> None:
    indexes = repository._ozon_onec_marketplace_mapping_indexes_from_rows(
        [
            SimpleNamespace(
                source_type="onec_marketplace_mapping",
                row_payload={
                    "marketplace": "wb",
                    "offer_id": "OZ-1",
                    "onec_item_id": "ITEM-WB",
                    "onec_name": "WB item",
                },
            ),
            SimpleNamespace(
                source_type="onec_marketplace_mapping",
                row_payload={
                    "marketplace": "ozon",
                    "offer_id": "OZ-2",
                    "onec_item_id": "ITEM-OZON",
                    "onec_name": "Ozon item",
                },
            ),
        ]
    )

    first = repository._check_ozon_mapping_candidate(
        {"offerId": "OZ-1"},
        indexes,
    )
    second = repository._check_ozon_mapping_candidate(
        {"offerId": "OZ-2"},
        indexes,
    )

    assert indexes["onecOzonMappingRows"] == 1
    assert first["statusCounter"] == "missing"
    assert second["statusCounter"] == "matched"
    assert second["row"]["onecItemId"] == "ITEM-OZON"


def test_ozon_rows_matching_period_keeps_only_requested_month_pages() -> None:
    collections = [
        SimpleNamespace(
            source_type="ozon_realization",
            payload={
                "results": [
                    {
                        "sellerAccountId": "OZON-1",
                        "pageIndex": 1,
                        "rowCount": 1,
                        "outputFile": "OZON-1_ozon_realization_2026-04.raw.json",
                    },
                    {
                        "sellerAccountId": "OZON-1",
                        "pageIndex": 1,
                        "rowCount": 1,
                        "outputFile": (
                            "OZON-1_ozon_realization_2026-05_page_0001.raw.json"
                        ),
                    },
                ]
            },
        )
    ]
    april = SimpleNamespace(
        source_row_id="OZ-APRIL",
        row_number=1,
        row_payload={"offer_id": "APRIL"},
    )
    may = SimpleNamespace(
        source_row_id="OZ-MAY",
        row_number=2,
        row_payload={"offer_id": "MAY"},
    )
    outside_manifest = SimpleNamespace(
        source_row_id="OZ-OUTSIDE",
        row_number=4,
        row_payload={"offer_id": "OUTSIDE"},
    )

    matched = repository._ozon_rows_matching_period(
        [april, may, outside_manifest],
        collections=collections,
        source_type="ozon_realization",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
    )

    assert matched == [april]


def test_client_ozon_diagnostics_filters_ozon_rows_by_cabinet(
    tmp_path: Path,
) -> None:
    client = make_client(
        tmp_path,
        settings_overrides={"source_refresh_enabled": True},
    )
    login(client)
    with client.app.state.session_factory() as db:
        user = db.query(repository.User).filter_by(email="admin@example.com").one()
        refresh_run = repository.create_source_refresh_run(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            mode="ozon-only",
            credential_source="tenant",
            dry_run=False,
            snapshot_set_id="ozon-cabinet-filter-test",
            period_start=date(2026, 5, 1),
            period_end=date(2026, 5, 31),
            user=user,
            reason="Ozon cabinet filter test",
        )
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="running",
            started_at=repository.security.utcnow(),
            root_dir="data/source_refresh/ozon-cabinet-filter-test",
        )
        ozon_realization = repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="ozon_realization",
            source_label="Ozon realization report",
            required=False,
            status="loaded",
            row_count=2,
            payload={
                "marketplace": "ozon",
                "results": [
                    {
                        "sellerAccountId": "OZON-1",
                        "wbCabinetId": "ozon-cabinet-1",
                        "pageIndex": 1,
                        "rowCount": 1,
                        "outputFile": "OZON-1_ozon_realization_2026-05.raw.json",
                    },
                    {
                        "sellerAccountId": "OZON-2",
                        "wbCabinetId": "ozon-cabinet-2",
                        "pageIndex": 2,
                        "rowCount": 1,
                        "outputFile": "OZON-2_ozon_realization_2026-05.raw.json",
                    },
                ],
            },
        )
        repository.add_source_snapshot_row(
            db,
            ozon_realization,
            row_number=1,
            raw_payload_hash="ozon-realization-cabinet-1",
            source_row_id="ozon_realization:1:1",
            wb_cabinet_id="ozon-cabinet-1",
            row_payload={
                "seller_account_id": "OZON-1",
                "offer_id": "OZ-1",
                "sku": "111",
                "sale_qty": "2",
                "sale_amount": "1000",
            },
        )
        repository.add_source_snapshot_row(
            db,
            ozon_realization,
            row_number=2,
            raw_payload_hash="ozon-realization-cabinet-2",
            source_row_id="ozon_realization:2:1",
            wb_cabinet_id="ozon-cabinet-2",
            row_payload={
                "seller_account_id": "OZON-2",
                "offer_id": "OZ-2",
                "sku": "222",
                "sale_qty": "3",
                "sale_amount": "2000",
            },
        )
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="source_loaded",
            finished_at=repository.security.utcnow(),
        )
        db.commit()

    response = client.get(
        "/api/clients/shumeyko/ozon-diagnostics"
        "?limit=10&wb_cabinet_id=ozon-cabinet-1"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["sourceSummary"]["ozonRealization"]["rowCount"] == 1
    assert payload["pnl"]["realizationRows"] == 1
    assert payload["unitRows"]["rowCount"] == 1
    assert payload["unitRows"]["rows"][0]["offerId"] == "OZ-1"
    assert payload["unitRows"]["rows"][0]["sku"] == "111"
    assert not any(
        item["sourceType"] == "ozon_realization" and item["rowCount"] != 1
        for item in payload["collections"]
    )


def test_client_ozon_diagnostics_empty_state_without_ozon_run(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    login(client)

    response = client.get("/api/clients/shumeyko/ozon-diagnostics")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "not_started"
    assert payload["latestRun"] is None
    assert payload["finance"]["rowCount"] == 0
    assert payload["financeRows"] == []
    assert payload["ozonMapping"]["status"] == "not_started"
    assert payload["ozonMapping"]["rows"] == []
    assert payload["pnl"]["status"] == "not_started"
    assert payload["pnl"]["totals"]["onecCogs"] is None
    assert payload["ozonMart"]["status"] == "not_started"
    assert payload["ozonMart"]["rows"] == []
    assert payload["issues"]["blockingCount"] == 2
    assert payload["issues"]["reviewCount"] == 1
    assert [item["code"] for item in payload["issues"]["items"]] == [
        "ozon_realization_missing",
        "ozon_mapping_source_missing",
        "ozon_onec_missing",
    ]


def test_onec_sales_cost_index_accepts_split_quantity_and_cost_rows() -> None:
    rows = [
        SimpleNamespace(
            row_payload={
                "RecordSet": [
                    {
                        "Номенклатура_Key": "ITEM-1",
                        "Количество": "10",
                        "Себестоимость": "0",
                    },
                    {
                        "Номенклатура_Key": "ITEM-1",
                        "Количество": "0",
                        "Себестоимость": "250",
                    },
                ]
            }
        )
    ]

    assert repository._onec_sales_cost_index(rows)["ITEM-1"] == 25


def test_ozon_realization_items_include_nested_item_and_quantity() -> None:
    rows = repository._iter_ozon_realization_items(
        {
            "item": {
                "name": "Ozon product",
                "offer_id": "OZ-1",
                "sku": "12345",
                "barcode": "4600000000000",
            },
            "delivery_commission": {"quantity": 3},
        }
    )

    assert rows == [
        {
            "item": {
                "name": "Ozon product",
                "offer_id": "OZ-1",
                "sku": "12345",
                "barcode": "4600000000000",
            },
            "delivery_commission": {"quantity": 3},
            "name": "Ozon product",
            "offer_id": "OZ-1",
            "sku": "12345",
            "barcode": "4600000000000",
            "quantity": 3,
        }
    ]


def test_client_source_refresh_controls_are_staff_only(tmp_path: Path) -> None:
    mapping_dir = tmp_path / "client_mapping_uploads"
    client = make_client(
        tmp_path,
        settings_overrides={"source_refresh_mapping_dir": str(mapping_dir)},
    )
    login(client)
    created = client.post(
        "/api/admin/users",
        json={"email": "refresh-client@example.com", "role": "client"},
    ).json()
    client.post("/api/auth/logout")
    login_as(client, "refresh-client@example.com", created["temporaryPassword"])

    upload = client.post(
        "/api/clients/shumeyko/mapping-file",
        files={"file": ("mapping.txt", b"a\tb\n", "text/plain")},
    )
    latest = client.get("/api/clients/shumeyko/source-refresh/latest")
    ozon_diagnostics = client.get("/api/clients/shumeyko/ozon-diagnostics")
    ozon_export = client.get("/api/clients/shumeyko/ozon-diagnostics/export.xlsx")
    run = client.post(
        "/api/clients/shumeyko/source-refresh",
        json={"mode": "full", "dry_run": True},
    )

    assert upload.status_code == 403
    assert latest.status_code == 403
    assert ozon_diagnostics.status_code == 403
    assert ozon_export.status_code == 403
    assert run.status_code == 403
    assert not mapping_dir.exists()


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
    assert summary["kpis"]["lostSalesRevenue"] == 25000
    assert summary["kpis"]["lostSalesProfit"] == 3000
    assert summary["kpis"]["lostSalesUnits"] == 5
    assert summary["monthly"]
    assert summary["expenses"]
    assert summary["lostSales"]
    assert summary["liquidityRows"]
    assert "md1Markup" in summary["liquidityRows"][0]
    assert "md6BeforeTax" in summary["liquidityRows"][0]
    assert summary["quality"]["okRows"] == 1
    assert summary["quality"]["missingCostRows"] == 1
    assert summary["quality"]["documentReconciliationRows"] == 1
    assert summary["quality"]["documentReconciliationIssues"] == 1
    assert summary["readiness"]["status"] == "partial_period"
    assert summary["readiness"]["label"] == "Неполный период"
    assert summary["readiness"]["score"] == 60
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
        "onec_reconciliation_review",
        "client_draft_missing",
    }

    rows = client.get(
        "/api/reports/report-1/rows",
        params={"preset": "losses", "query": "BAR-LOSS"},
    ).json()
    assert rows["total"] == 1
    assert rows["kpis"]["rowCount"] == 1
    assert rows["kpis"]["revenue"] == 99000
    assert rows["kpis"]["profit"] == -14704
    assert rows["kpis"]["lossRows"] == 1
    assert rows["kpis"]["lostSalesRevenue"] == 25000
    assert rows["items"][0]["product"] == "Убыточный товар"
    assert rows["analytics"]["kpis"]["revenue"] == 99000
    assert rows["analytics"]["monthly"][0]["month"] == "Апрель 2026"
    assert rows["analytics"]["liquidityRows"][0]["product"] == "Убыточный товар"
    assert rows["analytics"]["lostSales"][0]["cabinet"] == "Кабинет A"

    filtered_rows = client.get(
        "/api/reports/report-1/rows",
        params={"status_filter": "Нет себестоимости 1С", "limit": 50},
    ).json()
    assert filtered_rows["total"] == 1
    assert filtered_rows["kpis"]["rowCount"] == 1
    assert filtered_rows["kpis"]["revenue"] == 20000
    assert filtered_rows["kpis"]["profit"] == 14648
    assert filtered_rows["kpis"]["lossRows"] == 0
    assert filtered_rows["items"][0]["barcode"] == "BAR-NOCOST"

    return_rows = client.get(
        "/api/reports/report-1/rows",
        params={"preset": "returns", "limit": 50},
    ).json()
    assert return_rows["total"] == 1
    assert return_rows["kpis"]["rowCount"] == 1
    assert return_rows["kpis"]["returns"] == 8
    assert return_rows["items"][0]["barcode"] == "BAR-LOSS"

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
    assert period_rows["kpis"]["rowCount"] == 1
    assert period_rows["kpis"]["revenue"] == 20000
    assert period_rows["kpis"]["profit"] == 14648
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


def test_report_rows_period_filter_uses_month_when_week_is_missing(
    tmp_path: Path,
) -> None:
    payload = deepcopy(sample_payload())
    payload["unitRows"][0]["week"] = ""
    payload["unitRows"][0]["wbReportDate"] = ""
    client = make_client(tmp_path, payload=payload)
    login(client)

    april_may_rows = client.get(
        "/api/reports/report-1/rows",
        params={"period_start": "2026-04-01", "period_end": "2026-05-31"},
    ).json()
    assert april_may_rows["total"] == 1
    assert april_may_rows["kpis"]["rowCount"] == 1
    assert april_may_rows["kpis"]["revenue"] == 99000
    assert april_may_rows["kpis"]["profit"] == -14704
    assert april_may_rows["items"][0]["barcode"] == "BAR-LOSS"

    may_rows = client.get(
        "/api/reports/report-1/rows",
        params={"period_start": "2026-05-01", "period_end": "2026-05-31"},
    ).json()
    assert may_rows["total"] == 0
    assert may_rows["kpis"]["rowCount"] == 0
    assert may_rows["kpis"]["revenue"] == 0


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
    assert rows_payload["kpis"]["rowCount"] == 1200
    assert len(rows_payload["items"]) == 250

    capped_rows_response = client.get(
        "/api/reports/report-1/rows",
        params={"limit": 5000},
    )
    assert capped_rows_response.status_code == 200
    capped_rows_payload = capped_rows_response.json()
    assert capped_rows_payload["total"] == 1200
    assert len(capped_rows_payload["items"]) == 1000


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
    shumeyko_client = next(
        item for item in me_clients if item["clientId"] == "shumeyko"
    )
    assert shumeyko_client["name"] == "Реальный клиент"
    assert shumeyko_client["companies"]
    assert shumeyko_client["cabinets"]

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
    cabinet_a_rows = rows.json()
    assert cabinet_a_rows["total"] == 1
    assert cabinet_a_rows["items"][0]["barcode"] == "BAR-LOSS"
    assert cabinet_a_rows["analytics"]["kpis"]["revenue"] == 99000
    assert cabinet_a_rows["analytics"]["monthly"][0]["month"] == "Апрель 2026"
    assert cabinet_a_rows["analytics"]["lostSales"][0]["cabinet"] == "Кабинет A"

    cabinet_b = next(
        item for item in summary["options"]["cabinets"] if item["label"] == "Кабинет B"
    )
    cabinet_b_rows = client.get(
        "/api/reports/report-1/rows",
        params={"wb_cabinet_id": cabinet_b["id"]},
    )
    assert cabinet_b_rows.status_code == 200
    cabinet_b_payload = cabinet_b_rows.json()
    assert cabinet_b_payload["total"] == 1
    assert cabinet_b_payload["items"][0]["barcode"] == "BAR-NOCOST"
    assert cabinet_b_payload["analytics"]["kpis"]["revenue"] == 20000
    assert cabinet_b_payload["analytics"]["monthly"][0]["month"] == (
        "Июнь 2026 (неполный месяц)"
    )
    assert cabinet_b_payload["analytics"]["liquidityRows"][0]["product"] == (
        "Товар без себестоимости"
    )
    assert cabinet_b_payload["analytics"]["lostSales"] == []

    legacy_rows = client.get(
        "/api/reports/report-1/rows",
        params={"wb_cabinet_id": "Кабинет A"},
    )
    assert legacy_rows.status_code == 200
    assert legacy_rows.json()["total"] == 1

    with client.app.state.session_factory() as db:
        upsert_user(
            db,
            email="client-only@example.com",
            password="secret",
            tenant_id="shumeyko",
            role="client",
        )
        db.commit()

    login_as(client, "client-only@example.com", "secret")
    own_clients = client.get("/api/clients")
    assert own_clients.status_code == 200
    assert {item["clientId"] for item in own_clients.json()["items"]} == {"shumeyko"}
    assert client.get("/api/clients/other/reports").status_code == 404
    assert (
        client.get("/api/reports/report-1/document-reconciliation").status_code
        == 200
    )
    assert (
        client.get("/api/reports/other-report/document-reconciliation").status_code
        == 404
    )
    other_summary = client.get(
        "/api/reports/latest/summary",
        params={"client_id": "other"},
    )
    assert other_summary.status_code == 404


def test_consultant_can_create_client_workspace(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    with client.app.state.session_factory() as db:
        upsert_user(
            db,
            email="consultant@example.com",
            password="secret",
            tenant_id="shumeyko",
            role="consultant",
        )
        upsert_user(
            db,
            email="client-only@example.com",
            password="secret",
            tenant_id="shumeyko",
            role="client",
        )
        db.commit()

    login_as(client, "consultant@example.com", "secret")
    created = client.post(
        "/api/clients",
        json={
            "name": "Новый клиент",
            "tenant_id": "new-tenant",
            "client_id": "new-client",
            "companies": ["ООО Новый"],
            "cabinets": ["ООО Новый::WB Новый"],
        },
    )

    assert created.status_code == 200
    payload = created.json()["client"]
    assert payload["clientId"] == "new-client"
    assert payload["tenantId"] == "new-tenant"
    assert payload["name"] == "Новый клиент"
    assert payload["role"] == "consultant"
    assert payload["companies"][0]["label"] == "ООО Новый"
    assert payload["cabinets"][0]["label"] == "WB Новый"
    assert payload["cabinets"][0]["clientCompanyId"] == payload["companies"][0]["id"]

    clients = client.get("/api/clients").json()["items"]
    assert "new-client" in {item["clientId"] for item in clients}
    assert client.get("/api/clients/new-client/reports").json()["items"] == []
    assert client.get("/api/clients/new-client/integrations").status_code == 200
    cabinet_created = client.post(
        "/api/clients/new-client/cabinets",
        json={"label": "WB Второй", "organization_name": "ООО Новый"},
    )
    assert cabinet_created.status_code == 200
    created_cabinets = cabinet_created.json()["client"]["cabinets"]
    second_cabinet = next(
        item for item in created_cabinets if item["label"] == "WB Второй"
    )
    assert second_cabinet["clientCompanyId"] == payload["companies"][0]["id"]

    cabinet_updated = client.patch(
        f"/api/clients/new-client/cabinets/{second_cabinet['id']}",
        json={"label": "WB Второй / переименован", "organization_name": "ООО Новый"},
    )
    assert cabinet_updated.status_code == 200
    assert "WB Второй / переименован" in {
        item["label"] for item in cabinet_updated.json()["client"]["cabinets"]
    }

    duplicate = client.post(
        "/api/clients",
        json={"name": "Новый клиент", "tenant_id": "new-tenant"},
    )
    assert duplicate.status_code == 400

    client.post("/api/auth/logout")
    login_as(client, "client-only@example.com", "secret")
    forbidden = client.post("/api/clients", json={"name": "Запрещено"})
    assert forbidden.status_code == 403
    forbidden_cabinet = client.post(
        "/api/clients/shumeyko/cabinets",
        json={"label": "Запрещенный кабинет"},
    )
    assert forbidden_cabinet.status_code == 403


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
        "ozon_api",
        "onec_readonly",
    }
    provider_metadata = {
        item["providerBase"]: item for item in empty_payload["providers"]
    }
    assert provider_metadata["wb_api"] == {
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
    assert provider_metadata["ozon_api"]["label"] == "Ozon Seller API"
    assert provider_metadata["ozon_api"]["roles"][0] == {
        "id": "finance_reports",
        "label": "Финансовые отчеты",
        "default": True,
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
        assert (
            db.query(WbCabinet)
            .filter_by(client_id="shumeyko", display_name="WB кабинет")
            .one_or_none()
            is None
        )
        cabinet = (
            db.query(WbCabinet)
            .filter_by(client_id="shumeyko", display_name="Кабинет 2")
            .one()
        )
        assert cabinet.provider == extra_payload["provider"]

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


def test_ozon_live_check_accepts_any_supported_readonly_endpoint(
    monkeypatch,
) -> None:
    calls: list[tuple[str, dict]] = []

    class FakeResponse:
        def __init__(self, status_code: int) -> None:
            self.status_code = status_code

    class FakeClient:
        def __init__(self, **_kwargs) -> None:
            self._statuses = iter([403, 200])

        def __enter__(self) -> FakeClient:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, json: dict) -> FakeResponse:
            calls.append((url, json))
            return FakeResponse(next(self._statuses))

    monkeypatch.setattr(integrations.httpx, "Client", FakeClient)

    result = integrations.run_provider_check(
        WebSettings(_env_file=None),
        provider="ozon_api",
        secret='{"clientId":"12345","apiKey":"ozon-secret-key"}',
    )

    assert result.status == "check_ok"
    assert result.payload["endpointCategory"] == "stock_on_warehouses"
    assert result.payload["checkedEndpoints"] == [
        {"endpointCategory": "finance_cash_flow", "httpStatus": 403},
        {"endpointCategory": "stock_on_warehouses", "httpStatus": 200},
    ]
    assert calls[0][0].endswith("/v1/finance/cash-flow-statement/list")
    assert calls[1][0].endswith("/v2/analytics/stock_on_warehouses")
    assert "seller/info" not in str(calls)
    assert "ozon-secret-key" not in str(result.payload)


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
