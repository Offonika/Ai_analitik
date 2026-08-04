from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import inspect, select

from wb_unit_economics.contracts import OnecUnfCostSnapshot
from wb_unit_economics.onec_odata import OnecODataMetadataCheckResult
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import (
    Client,
    ClientRefreshSchedule,
    ConsultingFirm,
    OnecUnfCostSnapshotFact,
    SourceRefreshCollection,
    SourceRefreshRun,
    SourceRefreshStageEvent,
    SourceRefreshTask,
    Tenant,
)
from wb_unit_economics.web.source_refresh import (
    _collection_failure_is_transient,
    _metadata_failure_is_transient,
)


def test_queue_schema_is_additive_and_complete() -> None:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)

    tables = set(inspect(engine).get_table_names())

    assert {
        "client_refresh_schedules",
        "onec_unf_cost_snapshots",
        "report_archive_records",
        "report_export_jobs",
        "source_refresh_stage_events",
        "source_refresh_tasks",
    } <= tables


def test_task_chain_is_idempotent_and_claim_respects_dependencies() -> None:
    session_factory, run_id = _context()
    now = datetime(2030, 8, 4, 6, 15, tzinfo=UTC)
    with session_factory() as db:
        run = db.get(SourceRefreshRun, run_id)
        assert run is not None
        first = repository.ensure_source_refresh_task_chain(db, run, priority=20)
        repeated = repository.ensure_source_refresh_task_chain(db, run, priority=20)
        db.commit()

        assert [task.id for task in first] == [task.id for task in repeated]
        assert [task.task_type for task in first] == [
            "collect_sources",
            "materialize_facts",
            "build_report",
            "export_excel",
        ]
        assert [task.depends_on_task_id for task in first] == [
            None,
            first[0].id,
            first[1].id,
            first[2].id,
        ]

        claimed = repository.claim_next_source_refresh_task(
            db,
            worker_id="collector:test",
            allowed_task_types=repository.SOURCE_REFRESH_TASK_TYPES,
            now=now,
        )
        assert claimed is not None
        assert claimed.task_type == "collect_sources"
        assert claimed.attempt == 1
        assert (
            repository.claim_next_source_refresh_task(
                db,
                worker_id="heavy:test",
                allowed_task_types=repository.SOURCE_REFRESH_TASK_TYPES,
                now=now,
            )
            is None
        )
        repository.complete_source_refresh_task(
            db,
            claimed,
            metrics={"rowCount": 12, "rawPath": "/forbidden"},
            finished_at=now + timedelta(seconds=10),
        )
        next_task = repository.claim_next_source_refresh_task(
            db,
            worker_id="heavy:test",
            allowed_task_types=repository.SOURCE_REFRESH_TASK_TYPES,
            now=now + timedelta(seconds=11),
        )

        assert next_task is not None
        assert next_task.task_type == "materialize_facts"
        assert claimed.metrics == {"rowCount": 12}


def test_task_claim_keeps_per_client_lock_but_allows_other_clients() -> None:
    session_factory, run_id = _context()
    claim_at = datetime(2030, 8, 4, 6, 15, tzinfo=UTC)
    with session_factory() as db:
        first = db.get(SourceRefreshRun, run_id)
        assert first is not None
        repository.ensure_source_refresh_task_chain(db, first)
        same_client = SourceRefreshRun(
            id="refresh-same-client",
            tenant_id=first.tenant_id,
            client_id=first.client_id,
            mode="incremental",
            credential_source="tenant",
            dry_run=False,
            status="queued",
            snapshot_set_id="snapshot-same-client",
            period_start=date(2026, 7, 7),
            period_end=date(2026, 8, 3),
            created_at=first.created_at + timedelta(seconds=1),
            updated_at=first.updated_at + timedelta(seconds=1),
        )
        other_tenant = Tenant(
            id="tenant-other",
            name="Other tenant",
            created_at=first.created_at,
        )
        other_client = Client(
            id="client-other",
            firm_id="firm",
            tenant_id=other_tenant.id,
            name="Other client",
            status="active",
            default_report_settings={},
            created_at=first.created_at,
            updated_at=first.updated_at,
        )
        other_run = SourceRefreshRun(
            id="refresh-other-client",
            tenant_id=other_tenant.id,
            client_id=other_client.id,
            mode="incremental",
            credential_source="tenant",
            dry_run=False,
            status="queued",
            snapshot_set_id="snapshot-other-client",
            period_start=date(2026, 7, 7),
            period_end=date(2026, 8, 3),
            created_at=first.created_at + timedelta(seconds=2),
            updated_at=first.updated_at + timedelta(seconds=2),
        )
        db.add_all((other_tenant, other_client))
        db.flush()
        db.add_all((same_client, other_run))
        db.flush()
        repository.ensure_source_refresh_task_chain(db, same_client)
        repository.ensure_source_refresh_task_chain(db, other_run)
        db.commit()

        first_claim = repository.claim_next_source_refresh_task(
            db,
            worker_id="collector:first",
            allowed_task_types={"collect_sources"},
            now=claim_at,
        )
        assert first_claim is not None
        second_claim = repository.claim_next_source_refresh_task(
            db,
            worker_id="collector:second",
            allowed_task_types={"collect_sources"},
            now=claim_at,
        )

        assert first_claim.refresh_run_id == first.id
        assert second_claim is not None
        assert second_claim.refresh_run_id == other_run.id


def test_transient_failure_retries_once_with_backoff_then_stops() -> None:
    session_factory, run_id = _context()
    now = datetime(2026, 8, 4, 6, 15, tzinfo=UTC)
    with session_factory() as db:
        run = db.get(SourceRefreshRun, run_id)
        assert run is not None
        task, _ = repository.create_source_refresh_task(
            db,
            run,
            task_type="collect_sources",
            idempotency_key="retry-test",
            max_attempts=2,
            not_before=now,
        )
        task = repository.claim_next_source_refresh_task(
            db,
            worker_id="collector:one",
            allowed_task_types={"collect_sources"},
            now=now,
        )
        assert task is not None
        repository.fail_source_refresh_task(
            db,
            task,
            safe_error_code="transport_timeout",
            safe_error_message="temporary timeout",
            transient=True,
            failed_at=now,
        )

        assert task.status == "queued"
        assert task.not_before == now + timedelta(seconds=15)
        assert (
            repository.claim_next_source_refresh_task(
                db,
                worker_id="collector:two",
                allowed_task_types={"collect_sources"},
                now=now + timedelta(seconds=14),
            )
            is None
        )
        retried = repository.claim_next_source_refresh_task(
            db,
            worker_id="collector:two",
            allowed_task_types={"collect_sources"},
            now=now + timedelta(seconds=15),
        )
        assert retried is not None
        repository.fail_source_refresh_task(
            db,
            retried,
            safe_error_code="transport_timeout",
            safe_error_message="token=/must/not/leak",
            transient=True,
            failed_at=now + timedelta(seconds=16),
        )

        assert retried.status == "failed"
        assert retried.attempt == 2
        assert retried.safe_error_message == "task_failed"


def test_split_run_stays_non_terminal_while_transient_task_waits_for_retry() -> None:
    session_factory, run_id = _context()
    now = datetime(2030, 8, 4, 6, 15, tzinfo=UTC)
    with session_factory() as db:
        run = db.get(SourceRefreshRun, run_id)
        assert run is not None
        tasks = repository.ensure_source_refresh_task_chain(db, run)
        task = repository.claim_next_source_refresh_task(
            db,
            worker_id="collector:first",
            allowed_task_types={"collect_sources"},
            now=now,
        )
        assert task is not None
        repository.update_source_refresh_run(
            db,
            run,
            status="running",
            worker_id="collector:first",
            started_at=now,
            heartbeat_at=now,
        )

        scheduled = repository.requeue_transient_source_refresh_task(
            db,
            run,
            task_type="collect_sources",
            safe_error_code="transport_timeout",
            safe_error_message="temporary timeout",
            failed_at=now + timedelta(seconds=1),
        )

        assert scheduled is True
        assert task.status == "queued"
        assert task.not_before == now + timedelta(seconds=16)
        assert run.status == "queued"
        assert run.finished_at is None
        assert run.worker_id == ""
        assert [item.status for item in tasks[1:]] == ["queued", "queued", "queued"]
        event = db.scalar(
            select(SourceRefreshStageEvent).where(
                SourceRefreshStageEvent.refresh_run_id == run.id
            )
        )
        assert event is not None
        assert event.status == "failed"

        retried = repository.claim_next_source_refresh_task(
            db,
            worker_id="collector:second",
            allowed_task_types={"collect_sources"},
            now=now + timedelta(seconds=16),
        )
        assert retried is task
        repository.update_source_refresh_run(
            db,
            run,
            status="running",
            worker_id="collector:second",
            heartbeat_at=now + timedelta(seconds=16),
        )
        scheduled = repository.requeue_transient_source_refresh_task(
            db,
            run,
            task_type="collect_sources",
            safe_error_code="transport_timeout",
            failed_at=now + timedelta(seconds=17),
        )

        assert scheduled is False
        assert task.status == "failed"
        assert [item.status for item in tasks[1:]] == [
            "cancelled",
            "cancelled",
            "cancelled",
        ]


def test_only_transport_source_failures_are_retryable() -> None:
    transient = SourceRefreshCollection(
        status="failed",
        error_message="ReadTimeout",
        payload={"statusCode": 503, "retryable": True},
    )
    authorization = SourceRefreshCollection(
        status="failed",
        error_message="authorization failed",
        payload={"statusCode": 401, "retryable": False},
    )
    partial = SourceRefreshCollection(
        status="partial_source",
        error_message="ReadTimeout",
        payload={"statusCode": 503, "retryable": True},
    )

    assert _collection_failure_is_transient(transient) is True
    assert _collection_failure_is_transient(authorization) is False
    assert _collection_failure_is_transient(partial) is False
    assert (
        _metadata_failure_is_transient(
            OnecODataMetadataCheckResult(
                ok=False,
                status_code=503,
                error="ServiceUnavailable",
            )
        )
        is True
    )
    assert (
        _metadata_failure_is_transient(
            OnecODataMetadataCheckResult(
                ok=False,
                status_code=403,
                error="authorization failed",
            )
        )
        is False
    )


def test_permanent_failure_cancels_dependent_pipeline_tasks() -> None:
    session_factory, run_id = _context()
    now = datetime(2030, 8, 4, 6, 15, tzinfo=UTC)
    with session_factory() as db:
        run = db.get(SourceRefreshRun, run_id)
        assert run is not None
        repository.ensure_source_refresh_task_chain(db, run)
        claimed = repository.claim_next_source_refresh_task(
            db,
            worker_id="collector:one",
            allowed_task_types={"collect_sources"},
            now=now,
        )
        assert claimed is not None

        repository.fail_source_refresh_task(
            db,
            claimed,
            safe_error_code="authorization_failed",
            transient=False,
            failed_at=now + timedelta(seconds=1),
        )
        db.flush()

        stored = list(
            db.scalars(
                select(SourceRefreshTask)
                .where(SourceRefreshTask.refresh_run_id == run.id)
                .order_by(SourceRefreshTask.created_at, SourceRefreshTask.id)
            )
        )
        assert stored[0].status == "failed"
        assert [item.status for item in stored[1:]] == [
            "cancelled",
            "cancelled",
            "cancelled",
        ]
        assert all(item.safe_error_code == "dependency_failed" for item in stored[1:])


def test_stage_events_keep_only_safe_numeric_metrics() -> None:
    session_factory, run_id = _context()
    with session_factory() as db:
        run = db.get(SourceRefreshRun, run_id)
        assert run is not None
        event = repository.begin_source_refresh_stage(db, run, stage="excel")
        repository.finish_source_refresh_stage(
            db,
            event,
            status="succeeded",
            metrics={
                "rowCount": 13_430,
                "byteCount": 15_000_000,
                "peakMemoryBytes": 1_000_000_000,
                "connectionString": "forbidden",
                "rawPath": "/forbidden",
            },
        )
        db.commit()
        stored = db.scalar(select(SourceRefreshStageEvent))

        assert stored is not None
        assert stored.safe_metrics["rowCount"] == 13_430
        assert stored.safe_metrics["byteCount"] == 15_000_000
        assert stored.safe_metrics["peakMemoryBytes"] == 1_000_000_000
        assert stored.safe_metrics["durationMs"] >= 0
        assert "connectionString" not in stored.safe_metrics
        assert "rawPath" not in stored.safe_metrics
        assert stored.row_count == 13_430
        assert stored.byte_count == 15_000_000
        assert stored.peak_memory_bytes == 1_000_000_000


def test_status_payload_exposes_safe_queue_fields() -> None:
    session_factory, run_id = _context()
    with session_factory() as db:
        run = db.get(SourceRefreshRun, run_id)
        assert run is not None
        repository.ensure_source_refresh_task_chain(db, run)
        db.commit()

        payload = repository.source_refresh_status_payload(
            db,
            tenant_id=run.tenant_id,
            client_id=run.client_id,
            include_sensitive=False,
        )["latest"]

        assert payload is not None
        assert payload["stage"] == "collect_sources"
        assert payload["stageStartedAt"] is None
        assert payload["queuePosition"] == 1
        assert payload["estimatedCompletionAt"] is not None
        assert datetime.fromisoformat(payload["estimatedCompletionAt"]) > datetime.now(
            tz=UTC
        )
        assert payload["excelStatus"] == "queued"


def test_onec_cost_contract_is_persisted_with_tenant_and_lineage() -> None:
    session_factory, run_id = _context()
    with session_factory() as db:
        run = db.get(SourceRefreshRun, run_id)
        assert run is not None
        count = repository.replace_onec_unf_cost_snapshots(
            db,
            run,
            [
                OnecUnfCostSnapshot(
                    client_id="client",
                    organization_id="org-1",
                    loaded_at=datetime(2026, 8, 4, tzinfo=UTC),
                    onec_item_id="item-1",
                    article="A-1",
                    barcode="460000000001",
                    name="Товар",
                    cost_value=Decimal("123.456789"),
                    extra_costs_value=Decimal("4.50"),
                    input_vat_value=None,
                    cost_method="sales_register",
                    effective_from=date(2026, 7, 1),
                    source_document="doc-1",
                    raw_payload_hash="a" * 64,
                )
            ],
        )
        db.commit()
        stored = db.scalar(select(OnecUnfCostSnapshotFact))

        assert count == 1
        assert stored is not None
        assert stored.tenant_id == "tenant"
        assert stored.client_id == "client"
        assert stored.organization_id == "org-1"
        assert stored.source_refresh_run_id == run_id
        assert stored.source_snapshot_set_id == "snapshot-queue"
        assert stored.cost_value == Decimal("123.456789")
        assert stored.input_vat_value is None


def test_schedule_uses_five_minute_idempotent_local_slots() -> None:
    schedule = ClientRefreshSchedule(
        id="schedule",
        tenant_id="tenant",
        client_id="client",
        timezone="Europe/Moscow",
        enabled=True,
        weekly_weekday=1,
        weekly_time="06:15",
        monthly_full_week=2,
        monthly_full_time="02:00",
        priority=100,
        last_incremental_slot="",
        last_full_slot="",
        created_at=datetime(2026, 8, 1, tzinfo=UTC),
        updated_at=datetime(2026, 8, 1, tzinfo=UTC),
    )

    incremental = repository.due_client_refresh_schedule_slot(
        schedule,
        now=datetime(2026, 8, 4, 3, 18, tzinfo=UTC),
    )
    assert incremental == (
        "incremental",
        "incremental:2026-08-04:06:15:Europe/Moscow",
    )
    schedule.last_incremental_slot = incremental[1]
    assert (
        repository.due_client_refresh_schedule_slot(
            schedule,
            now=datetime(2026, 8, 4, 3, 19, tzinfo=UTC),
        )
        is None
    )

    full = repository.due_client_refresh_schedule_slot(
        schedule,
        now=datetime(2026, 8, 8, 23, 2, tzinfo=UTC),
    )
    assert full == ("full", "full:2026-08-09:02:00:Europe/Moscow")


def test_monthly_full_week_accepts_at_most_five_enabled_clients() -> None:
    session_factory, _run_id = _context()
    now = datetime(2026, 8, 4, tzinfo=UTC)
    with session_factory() as db:
        firm = db.get(ConsultingFirm, "firm")
        assert firm is not None
        for index in range(5):
            tenant = Tenant(
                id=f"tenant-{index}",
                name=f"Tenant {index}",
                created_at=now,
            )
            client = Client(
                id=f"client-{index}",
                firm_id=firm.id,
                tenant_id=tenant.id,
                name=f"Client {index}",
                status="active",
                default_report_settings={},
                created_at=now,
                updated_at=now,
            )
            db.add_all((tenant, client))
            db.flush()
            db.add(
                ClientRefreshSchedule(
                    id=f"schedule-{index}",
                    tenant_id=tenant.id,
                    client_id=client.id,
                    timezone="Europe/Moscow",
                    enabled=True,
                    weekly_weekday=1,
                    weekly_time="06:15",
                    monthly_full_week=3,
                    monthly_full_time="02:00",
                    priority=100,
                    last_incremental_slot="",
                    last_full_slot="",
                    created_at=now,
                    updated_at=now,
                )
            )
        db.flush()

        with pytest.raises(ValueError, match="five enabled clients"):
            repository._validate_monthly_full_capacity(
                db,
                monthly_full_week=3,
                exclude_schedule_id=None,
            )


def _context():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    session_factory = make_session_factory(engine)
    now = datetime(2026, 8, 4, 6, 0, tzinfo=UTC)
    with session_factory() as db:
        db.add(Tenant(id="tenant", name="Tenant", created_at=now))
        db.add(
            ConsultingFirm(
                id="firm",
                name="Firm",
                status="active",
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        db.add(
            Client(
                id="client",
                firm_id="firm",
                tenant_id="tenant",
                name="Client",
                status="active",
                default_report_settings={},
                created_at=now,
                updated_at=now,
            )
        )
        db.flush()
        db.add(
            SourceRefreshRun(
                id="refresh-queue",
                tenant_id="tenant",
                client_id="client",
                mode="incremental",
                credential_source="tenant",
                dry_run=False,
                status="queued",
                snapshot_set_id="snapshot-queue",
                period_start=date(2026, 7, 7),
                period_end=date(2026, 8, 3),
                created_at=now,
                updated_at=now,
            )
        )
        db.commit()
    return session_factory, "refresh-queue"
