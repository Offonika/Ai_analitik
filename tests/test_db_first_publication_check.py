from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from openpyxl import Workbook

from scripts.check_db_first_publication import (
    _excel_counts,
    _source_refresh_disk_status,
)
from wb_unit_economics.report_exports import file_sha256
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.settings import WebSettings


def test_excel_counts_skip_lost_sales_preface_rows(tmp_path: Path) -> None:
    workbook_path = tmp_path / "report.xlsx"
    workbook = Workbook()
    unit = workbook.active
    unit.title = "Юнит экономика"
    unit.append(["Неделя", "Товар"])
    unit.append(["2026-03-01", "Товар 1"])

    lost = workbook.create_sheet("Упущенные продажи")
    lost.append(["Упущенные продажи: предварительная оценка"])
    lost.append(["Методика"])
    lost.append(["Ограничение"])
    lost.append([])
    lost.append(["Показатель", "Значение"])
    lost.append(["Источник WB stock-history", "snapshot"])
    lost.append(["Период stock-history", "2026-04-01 - 2026-06-17"])
    lost.append(["Строк CSV", 9155])
    lost.append(["Дневных колонок", 78])
    lost.append(["Источник 1С остатков", "snapshot"])
    lost.append(["Строк 1С остатков", 366])
    lost.append(["Товаров с днями без остатка", 1])
    lost.append([])
    lost.append(["Кабинет WB", "Товар"])
    lost.append(
        [None, "Рассчитано только за доступный период", "partial_provider_window"]
    )
    lost.append(["Кабинет A", "Товар 1"])
    workbook.save(workbook_path)

    assert _excel_counts(workbook_path) == (1, 1)


def test_source_refresh_disk_status_warns_below_guard(tmp_path: Path) -> None:
    settings = WebSettings(
        _env_file=None,
        source_refresh_root=str(tmp_path / "missing" / "source_refresh"),
        source_refresh_min_free_gb=1_000_000,
    )

    status, warning = _source_refresh_disk_status(settings)

    assert "Source refresh root free GiB:" in status
    assert warning is not None
    assert warning.startswith("source refresh low disk:")


def test_check_db_first_publication_reports_current_and_integration_blocker(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'web.sqlite3'}"
    engine = make_engine(database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        report = repository.save_report_marts(
            db,
            _payload(),
            tenant_id="shumeyko",
            tenant_name="Шумейко и Партнеры",
            report_id="report-current",
        )
        for artifact_type in ("csv", "docx", "excel", "html", "pdf"):
            path = tmp_path / "reports" / f"report-current.{artifact_type}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("ready\n", encoding="utf-8")
            repository.record_report_artifact(
                db,
                report,
                artifact_type=artifact_type,
                path=path,
                sha256=file_sha256(path),
                byte_size=path.stat().st_size,
            )
        db.commit()

    ok = _run_check(
        tmp_path,
        database_url,
        "--report-id",
        "report-current",
        "--expected-unit-rows",
        "1",
        "--expected-lost-sales-rows",
        "1",
        "--expected-artifacts",
        "5",
        "--skip-file-counts",
    )
    assert ok.returncode == 0
    assert "Report: report-current" in ok.stdout
    assert "Unit rows: 1" in ok.stdout
    assert "Lost sales rows: 1" in ok.stdout
    assert "tenant integrations are not configured" in ok.stdout
    assert "Health: ok" in ok.stdout

    blocked = _run_check(
        tmp_path,
        database_url,
        "--report-id",
        "report-current",
        "--expected-unit-rows",
        "1",
        "--expected-lost-sales-rows",
        "1",
        "--expected-artifacts",
        "5",
        "--skip-file-counts",
        "--require-integrations",
    )
    assert blocked.returncode == 1
    assert "Health: failed" in blocked.stdout
    assert "tenant integrations are not configured" in blocked.stdout


def test_check_db_first_publication_accepts_expected_immutable_draft(
    tmp_path: Path,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'web.sqlite3'}"
    engine = make_engine(database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        report = repository.save_report_marts(
            db,
            _payload(),
            tenant_id="shumeyko",
            tenant_name="Шумейко и Партнеры",
            report_id="report-draft",
        )
        report.publication_status = "draft"
        report.is_current = False
        for artifact_type in ("csv", "docx", "excel", "html", "pdf"):
            path = tmp_path / "reports" / f"report-draft.{artifact_type}"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("ready\n", encoding="utf-8")
            repository.record_report_artifact(
                db,
                report,
                artifact_type=artifact_type,
                path=path,
                sha256=file_sha256(path),
                byte_size=path.stat().st_size,
            )
        db.commit()

    result = _run_check(
        tmp_path,
        database_url,
        "--report-id",
        "report-draft",
        "--expected-publication-status",
        "draft",
        "--expected-current",
        "false",
        "--expected-unit-rows",
        "1",
        "--expected-lost-sales-rows",
        "1",
        "--expected-artifacts",
        "5",
        "--skip-file-counts",
    )

    assert result.returncode == 0
    assert "Publication status: draft" in result.stdout
    assert "Current: False" in result.stdout
    assert "Health: ok" in result.stdout


def _payload() -> dict:
    return {
        "meta": {
            "title": "Кабинет юнит-экономики WB",
            "client": "Шумейко и Партнеры",
            "period": "01.03.2026 - 17.06.2026",
            "periodText": "март-июнь 2026",
            "periodStatus": "",
            "methodologyVersion": "DB-first publication check test",
            "generatedAt": "23.06.2026 13:00",
            "sourceWorkbook": "",
            "returnReasonLimitation": "",
        },
        "readiness": {},
        "options": {},
        "monthly": [],
        "expenses": [],
        "unitRows": [
            {
                "id": "unit-1",
                "week": "2026-04-06",
                "month": "Апрель 2026",
                "documentReport": "Отчет комиссионера",
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
        "lostSales": [
            {
                "id": "lost-1",
                "cabinet": "Кабинет A",
                "product": "Товар",
                "article1c": "A-1",
                "barcode": "BAR-1",
                "zeroStockDays": 2,
                "onecStock": 5,
                "onecWarehouses": "Склад 1",
                "sales": 3,
                "lostUnits": 1,
                "lostRevenue": 1000,
                "lostProfit": 300,
                "note": "test",
            }
        ],
        "reconciliation": [],
        "reconciliationMonthly": [],
        "documentReconciliation": [],
    }


def _run_check(
    tmp_path: Path, database_url: str, *args: str
) -> subprocess.CompletedProcess:
    project_root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [
            sys.executable,
            "scripts/check_db_first_publication.py",
            "--database-url",
            database_url,
            *args,
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )
