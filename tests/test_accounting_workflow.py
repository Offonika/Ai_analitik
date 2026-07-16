from __future__ import annotations

import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import inspect, select

from scripts import run_accounting_workflow_scheduler
from wb_unit_economics.web import accounting_workflow, repository
from wb_unit_economics.web.app import create_app
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import (
    AccountingWorkflowCard,
    AccountingWorkflowTask,
    ClientCompany,
    MonthCloseControlReport,
    ReportRun,
    TaxLoadReport,
)
from wb_unit_economics.web.settings import WebSettings


def _make_client(
    tmp_path: Path, *, workflow_enabled: bool = True
) -> tuple[TestClient, dict[str, str]]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    database_url = f"sqlite:///{tmp_path / 'workflow.sqlite3'}"
    engine = make_engine(database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        tenant = repository.ensure_tenant(db, "tenant-a", "Клиент А")
        client = repository.ensure_client_for_tenant(
            db, tenant_id=tenant.id, name="Клиент А"
        )
        company = repository.ensure_client_company(
            db,
            tenant_id=tenant.id,
            client_id=client.id,
            display_name="ООО Клиент А",
        )
        assert company is not None
        company.onec_organization_id = "org-a"
        admin = repository.upsert_user(
            db,
            email="admin@example.com",
            password="secret",
            tenant_id=tenant.id,
            role="admin",
            name="Администратор",
        )
        consultant = repository.upsert_user(
            db,
            email="consultant@example.com",
            password="secret",
            tenant_id=tenant.id,
            role="consultant",
            name="Консультант",
        )
        client_user = repository.upsert_user(
            db,
            email="client@example.com",
            password="secret",
            tenant_id=tenant.id,
            role="client",
            name="Клиент",
        )
        _add_report_pair(db, client.id, company)
        db.commit()
        ids = {
            "tenant": tenant.id,
            "client": client.id,
            "company": company.id,
            "organization": company.onec_organization_id,
            "admin": admin.id,
            "consultant": consultant.id,
            "client_user": client_user.id,
        }
    settings = WebSettings(
        _env_file=None,
        database_url=database_url,
        runtime_environment="test",
        cookie_secure=False,
        session_secret="workflow-test-secret",
        enabled_report_kinds=(
            "marketplace_unit_economics,month_close_control,tax_load"
        ),
        accounting_workflow_enabled=workflow_enabled,
        accounting_workflow_scheduler_enabled=True,
        accounting_workflow_calendar_configured=True,
        accounting_workflow_evidence_root=str(tmp_path / "evidence"),
    )
    app = create_app(settings=settings, session_factory=session_factory)
    return TestClient(app), ids


def _add_report_pair(db, client_id: str, company: ClientCompany) -> None:
    created_at = datetime.now(UTC) - timedelta(minutes=10)
    common = {
        "tenant_id": company.tenant_id,
        "client_id": client_id,
        "client_name": "Клиент А",
        "organization_id": company.onec_organization_id,
        "period_start": date(2026, 6, 1),
        "period_end": date(2026, 6, 30),
        "source_coverage_start": date(2026, 6, 1),
        "source_coverage_end": date(2026, 6, 30),
        "period_text": "Июнь 2026",
        "period_status": "полный период",
        "generated_at": created_at,
        "publication_status": "draft",
        "is_current": True,
        "lineage_type": "test",
        "source_snapshot_set_id": "snapshot-test",
        "methodology_version": "test-v1",
        "marketplace_expense_context_version": "",
        "source_workbook": "",
        "source_workbook_path": "",
        "return_reason_limitation": "",
        "created_at": created_at,
    }
    month = ReportRun(
        id="month-report",
        report_kind="month_close_control",
        title="Контроль закрытия месяца",
        status="ready_to_close",
        **common,
    )
    tax = ReportRun(
        id="tax-report",
        report_kind="tax_load",
        title="Налоговая нагрузка",
        status="accountant_review_required",
        **common,
    )
    db.add_all([month, tax])
    db.flush()
    db.add_all(
        [
            MonthCloseControlReport(
                report_run_id=month.id,
                contract_version="v1",
                payload_sha256="a" * 64,
                payload={"recommendation": "ready_to_close"},
                created_at=created_at,
            ),
            TaxLoadReport(
                report_run_id=tax.id,
                contract_version="v1",
                payload_sha256="b" * 64,
                payload={"businessStatus": "accountant_review_required"},
                created_at=created_at,
            ),
        ]
    )


def _login(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/auth/login", json={"email": email, "password": "secret"}
    )
    assert response.status_code == 200


def _csrf(client: TestClient, tenant_id: str) -> str:
    response = client.get(
        "/api/accounting-workflows/config", params={"tenantId": tenant_id}
    )
    assert response.status_code == 200
    return response.json()["csrfToken"]


def _post(client: TestClient, path: str, csrf: str, payload: dict[str, object]):
    return client.post(path, json=payload, headers={"X-CSRF-Token": csrf})


def _grant_admin_supervisor(client: TestClient, ids: dict[str, str], csrf: str) -> None:
    response = _post(
        client,
        "/api/accounting-workflows/supervisors",
        csrf,
        {"tenantId": ids["tenant"], "userId": ids["admin"], "active": True},
    )
    assert response.status_code == 200


def _create_card(
    client: TestClient, ids: dict[str, str], csrf: str
) -> dict[str, object]:
    response = _post(
        client,
        "/api/accounting-workflows/monthly-runs",
        csrf,
        {
            "tenantId": ids["tenant"],
            "periodMonth": "2026-06",
            "responsibleUserId": ids["consultant"],
            "supervisorUserId": ids["admin"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["created"][0]


def test_workflow_is_hidden_by_flag_and_from_client_roles(tmp_path: Path) -> None:
    disabled, ids = _make_client(tmp_path / "disabled", workflow_enabled=False)
    _login(disabled, "admin@example.com")
    assert disabled.get("/accounting-workflows").status_code == 404
    assert disabled.get("/api/accounting-workflows/config").status_code == 404
    assert disabled.get("/api/me").json()["accountingWorkflowEnabled"] is False

    enabled, ids = _make_client(tmp_path / "enabled")
    assert enabled.get("/accounting-workflows").status_code == 401
    _login(enabled, "client@example.com")
    assert enabled.get("/accounting-workflows").status_code == 404
    assert (
        enabled.get(
            "/api/accounting-workflows", params={"tenantId": ids["tenant"]}
        ).status_code
        == 403
    )
    assert enabled.get("/api/me").json()["accountingWorkflowEnabled"] is False
    _login(enabled, "admin@example.com")
    workflow_page = enabled.get("/accounting-workflows")
    assert workflow_page.status_code == 200
    for filter_id in (
        "filter-period",
        "filter-stage",
        "filter-client",
        "filter-organization",
        "filter-responsible",
        "filter-supervisor",
        "filter-overdue",
    ):
        assert f'id="{filter_id}"' in workflow_page.text
    assert enabled.get("/api/me").json()["accountingWorkflowEnabled"] is True
    csrf = _csrf(enabled, ids["tenant"])
    denied_without_supervisor_capability = _post(
        enabled,
        "/api/accounting-workflows/monthly-runs",
        csrf,
        {
            "tenantId": ids["tenant"],
            "periodMonth": "2026-06",
            "responsibleUserId": ids["consultant"],
            "supervisorUserId": ids["admin"],
        },
    )
    assert denied_without_supervisor_capability.status_code == 403


def test_full_workflow_is_idempotent_audited_and_requires_final_evidence(
    tmp_path: Path,
) -> None:
    client, ids = _make_client(tmp_path)
    _login(client, "admin@example.com")
    admin_csrf = _csrf(client, ids["tenant"])
    _grant_admin_supervisor(client, ids, admin_csrf)
    card = _create_card(client, ids, admin_csrf)
    card_id = str(card["id"])
    assert {item["reportKind"] for item in card["tasks"]} == {
        "month_close_control",
        "tax_load",
    }

    repeated = _post(
        client,
        "/api/accounting-workflows/monthly-runs",
        admin_csrf,
        {
            "tenantId": ids["tenant"],
            "periodMonth": "2026-06",
            "responsibleUserId": ids["consultant"],
            "supervisorUserId": ids["admin"],
        },
    )
    assert repeated.status_code == 200
    assert repeated.json()["created"] == []
    assert repeated.json()["existing"][0]["id"] == card_id

    assigned = _post(
        client,
        f"/api/accounting-workflows/{card_id}/transitions",
        admin_csrf,
        {
            "targetStage": "data_collection",
            "responsibleUserId": ids["consultant"],
            "supervisorUserId": ids["admin"],
        },
    )
    assert assigned.status_code == 200

    _login(client, "consultant@example.com")
    consultant_csrf = _csrf(client, ids["tenant"])
    started = _post(
        client,
        f"/api/accounting-workflows/{card_id}/transitions",
        consultant_csrf,
        {"targetStage": "reports_in_progress"},
    )
    assert started.status_code == 200
    tasks = {item["reportKind"]: item for item in started.json()["item"]["tasks"]}

    for report_kind, report_id, payload_hash in (
        ("month_close_control", "month-report", "a" * 64),
        ("tax_load", "tax-report", "b" * 64),
    ):
        task_id = tasks[report_kind]["id"]
        attached = _post(
            client,
            f"/api/accounting-workflows/{card_id}/tasks/{task_id}/actions",
            consultant_csrf,
            {
                "action": "attach_revision",
                "reportId": report_id,
                "payloadSha256": payload_hash,
            },
        )
        assert attached.status_code == 200, attached.text
        if report_kind == "tax_load":
            for action in ("confirm_facts", "approve_text", "mark_final"):
                response = _post(
                    client,
                    f"/api/accounting-workflows/{card_id}/tasks/{task_id}/actions",
                    consultant_csrf,
                    {"action": action},
                )
                assert response.status_code == 200, response.text
        for action in ("submit_review", "complete"):
            response = _post(
                client,
                f"/api/accounting-workflows/{card_id}/tasks/{task_id}/actions",
                consultant_csrf,
                {"action": action},
            )
            assert response.status_code == 200, response.text

    for stage in ("internal_review", "ready_to_send"):
        response = _post(
            client,
            f"/api/accounting-workflows/{card_id}/transitions",
            consultant_csrf,
            {"targetStage": stage},
        )
        assert response.status_code == 200, response.text

    bad_upload = client.post(
        f"/api/accounting-workflows/{card_id}/evidence",
        files={"evidence": ("proof.png", b"not-a-png", "image/png")},
        headers={"X-CSRF-Token": consultant_csrf},
    )
    assert bad_upload.status_code == 400
    upload = client.post(
        f"/api/accounting-workflows/{card_id}/evidence",
        files={
            "evidence": (
                "proof.png",
                b"\x89PNG\r\n\x1a\nworkflow-proof",
                "image/png",
            )
        },
        headers={"X-CSRF-Token": consultant_csrf},
    )
    assert upload.status_code == 200, upload.text
    attachment_id = upload.json()["attachment"]["id"]

    preliminary = _post(
        client,
        f"/api/accounting-workflows/{card_id}/deliveries",
        consultant_csrf,
        {
            "sentAt": datetime.now(UTC).isoformat(),
            "channel": "email",
            "maskedRecipient": "cl***@example.com",
            "attachmentId": attachment_id,
            "contactResult": "Предварительный отчет отправлен",
            "preliminary": True,
        },
    )
    assert preliminary.status_code == 200, preliminary.text
    assert preliminary.json()["item"]["stage"] == "ready_to_send"

    delivery = _post(
        client,
        f"/api/accounting-workflows/{card_id}/deliveries",
        consultant_csrf,
        {
            "sentAt": datetime.now(UTC).isoformat(),
            "channel": "email",
            "maskedRecipient": "cl***@example.com",
            "attachmentId": attachment_id,
            "contactResult": "Финальный отчет отправлен",
            "preliminary": False,
        },
    )
    assert delivery.status_code == 200, delivery.text
    delivered_card = delivery.json()["item"]
    assert delivered_card["stage"] == "ready_for_payroll_close"
    assert len(delivered_card["deliveries"]) == 2
    assert len(delivered_card["followups"]) == 2
    active_followup = next(
        item for item in delivered_card["followups"] if item["status"] != "completed"
    )

    _login(client, "admin@example.com")
    admin_csrf = _csrf(client, ids["tenant"])
    closed = _post(
        client,
        f"/api/accounting-workflows/{card_id}/transitions",
        admin_csrf,
        {"targetStage": "closed_payroll"},
    )
    assert closed.status_code == 200, closed.text
    assert closed.json()["item"]["stage"] == "closed_payroll"
    assert any(
        item["action"] == "accounting_workflow_delivery_recorded"
        for item in closed.json()["item"]["auditEvents"]
    )

    with client.app.state.session_factory() as db:
        followup = db.get(
            accounting_workflow.AccountingWorkflowFollowup,
            active_followup["id"],
        )
        assert followup is not None
        followup.due_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
    due = _post(
        client,
        "/api/accounting-workflows/followups/run-due",
        admin_csrf,
        {"tenantId": ids["tenant"]},
    )
    assert due.status_code == 200
    assert due.json()["due"] == 1

    _login(client, "consultant@example.com")
    consultant_csrf = _csrf(client, ids["tenant"])
    repeated_followup = _post(
        client,
        (
            f"/api/accounting-workflows/{card_id}/followups/"
            f"{active_followup['id']}/actions"
        ),
        consultant_csrf,
        {"action": "repeat", "result": "Клиенту написали повторно"},
    )
    assert repeated_followup.status_code == 200
    with client.app.state.session_factory() as db:
        followup = db.get(
            accounting_workflow.AccountingWorkflowFollowup,
            active_followup["id"],
        )
        assert followup is not None
        followup.escalation_due_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
    _login(client, "admin@example.com")
    admin_csrf = _csrf(client, ids["tenant"])
    escalated = _post(
        client,
        "/api/accounting-workflows/followups/run-due",
        admin_csrf,
        {"tenantId": ids["tenant"]},
    )
    assert escalated.status_code == 200
    assert escalated.json()["escalated"] == 1

    correction = _post(
        client,
        "/api/accounting-workflows/corrections",
        admin_csrf,
        {"supersedesCardId": card_id, "reason": "Существенное исправление"},
    )
    assert correction.status_code == 200, correction.text
    correction_id = correction.json()["item"]["id"]
    cancelled = _post(
        client,
        f"/api/accounting-workflows/{correction_id}/transitions",
        admin_csrf,
        {"targetStage": "cancelled", "reason": "not_applicable"},
    )
    assert cancelled.status_code == 200
    branched = _post(
        client,
        "/api/accounting-workflows/corrections",
        admin_csrf,
        {"supersedesCardId": card_id, "reason": "Попытка ветвления"},
    )
    assert branched.status_code == 409


def test_stale_report_revision_returns_card_to_rework(tmp_path: Path) -> None:
    client, ids = _make_client(tmp_path)
    _login(client, "admin@example.com")
    admin_csrf = _csrf(client, ids["tenant"])
    _grant_admin_supervisor(client, ids, admin_csrf)
    card = _create_card(client, ids, admin_csrf)
    card_id = str(card["id"])
    response = _post(
        client,
        f"/api/accounting-workflows/{card_id}/transitions",
        admin_csrf,
        {
            "targetStage": "data_collection",
            "responsibleUserId": ids["consultant"],
            "supervisorUserId": ids["admin"],
        },
    )
    assert response.status_code == 200
    _login(client, "consultant@example.com")
    consultant_csrf = _csrf(client, ids["tenant"])
    response = _post(
        client,
        f"/api/accounting-workflows/{card_id}/transitions",
        consultant_csrf,
        {"targetStage": "reports_in_progress"},
    )
    month_task = next(
        item
        for item in response.json()["item"]["tasks"]
        if item["reportKind"] == "month_close_control"
    )
    response = _post(
        client,
        f"/api/accounting-workflows/{card_id}/tasks/{month_task['id']}/actions",
        consultant_csrf,
        {
            "action": "attach_revision",
            "reportId": "month-report",
            "payloadSha256": "a" * 64,
        },
    )
    assert response.status_code == 200
    with client.app.state.session_factory() as db:
        report = db.get(ReportRun, "month-report")
        assert report is not None
        report.is_current = False
        db.commit()

    stale = _post(
        client,
        f"/api/accounting-workflows/{card_id}/tasks/{month_task['id']}/actions",
        consultant_csrf,
        {"action": "submit_review"},
    )
    assert stale.status_code == 409
    detail = client.get(f"/api/accounting-workflows/{card_id}")
    assert detail.status_code == 200
    assert detail.json()["item"]["stage"] == "rework"


def test_calendar_and_schema_constraints(tmp_path: Path) -> None:
    settings = WebSettings(
        _env_file=None,
        runtime_environment="test",
        accounting_workflow_calendar_configured=True,
        accounting_workflow_non_working_dates="2026-07-06",
    )
    calendar = accounting_workflow.BusinessCalendar(settings)
    start = datetime(2026, 7, 3, 12, tzinfo=UTC)
    assert calendar.add_working_days(start, 5).date() == date(2026, 7, 13)

    client, ids = _make_client(tmp_path / "schema")
    with client.app.state.session_factory() as db:
        cards = list(db.scalars(select(AccountingWorkflowCard)))
        tasks = list(db.scalars(select(AccountingWorkflowTask)))
        assert cards == []
        assert tasks == []
        table_names = {
            "accounting_workflow_cards",
            "accounting_workflow_tasks",
            "accounting_workflow_report_revisions",
            "accounting_workflow_attachments",
            "accounting_workflow_deliveries",
            "accounting_workflow_followups",
            "accounting_workflow_supervisors",
            "accounting_workflow_comments",
            "accounting_workflow_audit_events",
        }
        assert table_names.issubset(set(inspect(db.get_bind()).get_table_names()))


def test_scheduler_dry_run_uses_same_idempotent_service(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    client, ids = _make_client(tmp_path)
    settings = client.app.state.settings
    monkeypatch.setenv("SHUMEYKO_DATABASE_URL", settings.database_url)
    monkeypatch.setenv("SHUMEYKO_RUNTIME_ENVIRONMENT", "test")
    monkeypatch.setenv("SHUMEYKO_ACCOUNTING_WORKFLOW_ENABLED", "true")
    monkeypatch.setenv("SHUMEYKO_ACCOUNTING_WORKFLOW_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("SHUMEYKO_ACCOUNTING_WORKFLOW_CALENDAR_CONFIGURED", "true")
    monkeypatch.setenv(
        "SHUMEYKO_ENABLED_REPORT_KINDS",
        "marketplace_unit_economics,month_close_control,tax_load",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run_accounting_workflow_scheduler.py",
            "--tenant-id",
            ids["tenant"],
            "--period-month",
            "2026-06",
            "--force-monthly",
            "--dry-run",
            "--json",
        ],
    )

    assert run_accounting_workflow_scheduler.main() == 0
    output = capsys.readouterr().out
    assert '"monthlyCreationRun": true' in output
    assert '"created": 1' in output
    with client.app.state.session_factory() as db:
        assert list(db.scalars(select(AccountingWorkflowCard))) == []
