from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.check_source_refresh_worker import cli_worker_process_exists
from scripts.run_source_refresh_worker import (
    WorkerInterrupted,
    _start_heartbeat_process,
    _stop_heartbeat_process,
    claim_next_run,
    process_run,
    recover_stale_worker_runs,
    worker_heartbeat_marker_is_fresh,
    worker_heartbeat_marker_path,
    write_worker_heartbeat_marker,
)
from wb_unit_economics.web import repository, security
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import SourceRefreshRun
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import source_refresh_progress_payload
from wb_unit_economics.web.source_refresh_worker import (
    SourceRefreshWorkerLaunchError,
    SystemdSourceRefreshWorkerLauncher,
    launch_source_refresh_worker,
    production_source_refresh_worker_launcher,
)


def test_production_worker_launcher_uses_systemd_without_shell(monkeypatch) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(
        "wb_unit_economics.web.source_refresh_worker.subprocess.run",
        fake_run,
    )
    settings = WebSettings(
        _env_file=None,
        database_url="postgresql+psycopg://localhost/example",
    )
    launcher = production_source_refresh_worker_launcher(settings)

    assert launcher is not None
    unit = launcher.launch("source_refresh_123")

    assert unit == "shumeiko-source-refresh-worker@source_refresh_123.service"
    assert calls[0][0] == ["systemctl", "start", "--no-block", unit]
    assert calls[0][1]["timeout"] == 15


def test_worker_launcher_is_not_used_for_local_sqlite() -> None:
    settings = WebSettings(_env_file=None, database_url="sqlite:///:memory:")

    assert production_source_refresh_worker_launcher(settings) is None


def test_worker_launcher_rejects_unsafe_run_id() -> None:
    launcher = SystemdSourceRefreshWorkerLauncher(WebSettings(_env_file=None))

    with pytest.raises(SourceRefreshWorkerLaunchError):
        launcher.launch("../../unsafe")


def test_launch_failure_marks_queued_run_failed_without_deleting_data(
    tmp_path: Path,
) -> None:
    factory = _worker_factory(tmp_path)
    with factory() as db:
        refresh_run = _queued_run(db, suffix="launch-failure")
        repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="onec_sales_register",
            source_label="1C sales register",
            required=True,
            status="loaded",
            row_count=4,
        )
        refresh_run_id = refresh_run.id
        db.commit()

    class _FailingLauncher:
        def launch(self, _refresh_run_id: str) -> str:
            raise SourceRefreshWorkerLaunchError("worker start failed")

    with factory() as db, pytest.raises(SourceRefreshWorkerLaunchError):
        launch_source_refresh_worker(
            db,
            refresh_run_id=refresh_run_id,
            worker_launcher=_FailingLauncher(),
        )

    with factory() as db:
        refresh_run = db.get(SourceRefreshRun, refresh_run_id)
        assert refresh_run is not None
        assert refresh_run.status == "failed"
        assert refresh_run.failure_code == "worker_launch_failed"
        assert len(refresh_run.collections) == 1
        assert refresh_run.collections[0].row_count == 4


def test_external_worker_launch_records_systemd_owner(tmp_path: Path) -> None:
    factory = _worker_factory(tmp_path)
    with factory() as db:
        refresh_run = _queued_run(db, suffix="external-launch")
        refresh_run_id = refresh_run.id
        db.commit()
    launched: list[str] = []

    class _Launcher:
        def launch(self, run_id: str) -> str:
            launched.append(run_id)
            return f"shumeiko-source-refresh-worker@{run_id}.service"

    with factory() as db:
        payload = launch_source_refresh_worker(
            db,
            refresh_run_id=refresh_run_id,
            worker_launcher=_Launcher(),
        )

    assert launched == [refresh_run_id]
    assert payload["status"] == "queued"
    assert payload["workerAssigned"] is True
    with factory() as db:
        refresh_run = db.get(SourceRefreshRun, refresh_run_id)
        assert refresh_run is not None
        assert refresh_run.worker_id == f"systemd:{refresh_run_id}"
        assert refresh_run.heartbeat_at is not None


def test_cli_worker_process_check_requires_live_refresh_command(monkeypatch) -> None:
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda _path: b"python\0scripts/run_source_refresh.py\0",
    )
    assert cli_worker_process_exists("cli:123:source_refresh_1") is True
    assert cli_worker_process_exists("cli:source_refresh_1") is False


def test_cli_worker_process_check_rejects_missing_pid(monkeypatch) -> None:
    def missing(_path):
        raise FileNotFoundError

    monkeypatch.setattr(Path, "read_bytes", missing)
    assert cli_worker_process_exists("cli:123:source_refresh_1") is False


def test_source_refresh_progress_reads_only_safe_manifest_aggregates(
    tmp_path: Path,
) -> None:
    root = tmp_path / "source_refresh"
    run_root = root / "full-progress"
    finance = run_root / "wb_finance"
    finance.mkdir(parents=True)
    page = finance / "account_page_1.raw.json"
    page.write_text("[]", encoding="utf-8")
    (finance / "manifest.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "seller_account_id": "SECRET_ACCOUNT",
                        "page_index": 1,
                        "status": "ok",
                        "row_count": 100000,
                        "output_file": page.name,
                    },
                    {
                        "seller_account_id": "SECRET_ACCOUNT",
                        "page_index": 2,
                        "status": "no_data",
                        "row_count": 0,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    now = datetime.now().astimezone()
    refresh_run = SourceRefreshRun(
        id="source_refresh_progress",
        tenant_id="shumeyko",
        client_id="shumeyko",
        mode="full",
        credential_source="tenant",
        dry_run=False,
        status="running",
        reason="",
        snapshot_set_id=run_root.name,
        period_start=date(2026, 3, 1),
        period_end=date(2026, 7, 10),
        root_dir=str(run_root),
        workbook_path="",
        error_message="",
        worker_id="worker",
        failure_code="",
        created_at=now,
        updated_at=now,
    )

    payload = source_refresh_progress_payload(refresh_run, source_root=root)
    last_activity_at = payload.pop("lastActivityAt")

    assert payload == {
        "stage": "wb_finance",
        "currentSource": "WB",
        "completedSources": 0,
        "totalSources": 0,
        "wbAccountsCompleted": 1,
        "wbAccountsTotal": 1,
        "pagesLoaded": 1,
        "rowsLoaded": 100000,
        "bytesWritten": 2,
    }
    assert last_activity_at is not None
    assert datetime.fromisoformat(last_activity_at).tzinfo is not None
    assert "SECRET_ACCOUNT" not in str(payload)


def _worker_factory(tmp_path: Path):
    engine = make_engine(f"sqlite:///{tmp_path / 'worker.sqlite3'}")
    init_db(engine)
    factory = make_session_factory(engine)
    with factory() as db:
        repository.ensure_tenant(db, "tenant-1", "Tenant 1")
        db.commit()
    return factory


def _queued_run(db, *, suffix: str):
    return repository.create_source_refresh_run(
        db,
        tenant_id="tenant-1",
        client_id="tenant-1",
        mode="full",
        credential_source="tenant",
        dry_run=False,
        snapshot_set_id=f"snapshot-{suffix}",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        reason=f"worker test {suffix}",
    )


def test_worker_claims_queued_run_once(tmp_path: Path) -> None:
    factory = _worker_factory(tmp_path)
    with factory() as db:
        refresh_run = _queued_run(db, suffix="claim")
        refresh_run_id = refresh_run.id
        db.commit()
    with factory() as db:
        claimed = claim_next_run(db, worker_id="systemd-source-refresh-worker:test")
        assert claimed is not None
        assert claimed.id == refresh_run_id
        repository.update_source_refresh_run(db, claimed, status="running")
        db.commit()
    with factory() as db:
        assert claim_next_run(db, worker_id="another-worker") is None


def test_worker_stale_recovery_preserves_collections(tmp_path: Path) -> None:
    factory = _worker_factory(tmp_path)
    with factory() as db:
        refresh_run = _queued_run(db, suffix="stale")
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="rebuilding",
            worker_id="systemd-source-refresh-worker:old",
            heartbeat_at=security.utcnow() - timedelta(minutes=10),
        )
        repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="onec_sales_register",
            source_label="1C sales register",
            required=True,
            status="loaded",
            row_count=35,
        )
        refresh_run_id = refresh_run.id
        db.commit()
    with factory() as db:
        assert recover_stale_worker_runs(
            db,
            worker_name="systemd-source-refresh-worker",
            stale_after_seconds=300,
        ) == 1
    with factory() as db:
        refresh_run = db.get(SourceRefreshRun, refresh_run_id)
        assert refresh_run is not None
        assert refresh_run.status == "failed"
        assert refresh_run.failure_code == "worker_heartbeat_stale"
        assert len(refresh_run.collections) == 1
        assert refresh_run.collections[0].row_count == 35


def test_fresh_file_heartbeat_protects_run_with_stale_db_heartbeat(
    tmp_path: Path,
) -> None:
    factory = _worker_factory(tmp_path)
    source_root = tmp_path / "source-refresh"
    run_root = source_root / "snapshot-file-heartbeat"
    run_root.mkdir(parents=True)
    with factory() as db:
        refresh_run = _queued_run(db, suffix="file-heartbeat")
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="rebuilding",
            worker_id="systemd-source-refresh-worker:live",
            heartbeat_at=security.utcnow() - timedelta(minutes=10),
            root_dir=str(run_root),
        )
        refresh_run_id = refresh_run.id
        marker = worker_heartbeat_marker_path(
            refresh_run,
            source_refresh_root=source_root,
        )
        assert write_worker_heartbeat_marker(marker) is True
        db.commit()

    with factory() as db:
        refresh_run = db.get(SourceRefreshRun, refresh_run_id)
        assert refresh_run is not None
        assert worker_heartbeat_marker_is_fresh(
            refresh_run,
            source_refresh_root=source_root,
            cutoff=security.utcnow() - timedelta(minutes=5),
        )
        assert recover_stale_worker_runs(
            db,
            worker_name="systemd-source-refresh-worker",
            stale_after_seconds=300,
            source_refresh_root=source_root,
        ) == 0

    with factory() as db:
        refresh_run = db.get(SourceRefreshRun, refresh_run_id)
        assert refresh_run is not None
        assert refresh_run.status == "rebuilding"
        assert refresh_run.finished_at is None


def test_worker_heartbeat_uses_companion_process_without_database_url_in_argv(
    monkeypatch,
    tmp_path: Path,
) -> None:
    factory = _worker_factory(tmp_path)
    source_root = tmp_path / "source-refresh"
    with factory() as db:
        refresh_run = _queued_run(db, suffix="heartbeat-process")
        refresh_run_id = refresh_run.id
        db.commit()
    settings = WebSettings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'worker.sqlite3'}",
        source_refresh_root=str(source_root),
    )
    service = SimpleNamespace(settings=settings)
    calls: list[tuple[list[str], dict[str, object]]] = []

    class _Process:
        terminated = False

        def poll(self):
            return None

        def terminate(self):
            self.terminated = True

        def wait(self, *, timeout):
            assert timeout == 5
            return 0

    process = _Process()

    def fake_popen(command, **kwargs):
        calls.append((command, kwargs))
        return process

    monkeypatch.setattr(
        "scripts.run_source_refresh_worker.subprocess.Popen",
        fake_popen,
    )

    started = _start_heartbeat_process(
        factory,
        service,
        refresh_run_id,
        heartbeat_seconds=30,
    )

    assert started is process
    command, kwargs = calls[0]
    assert command[1].endswith("scripts/run_source_refresh_heartbeat.py")
    assert command[-2:] == ["--heartbeat-seconds", "30"]
    assert settings.database_url not in command
    assert kwargs["env"]["SHUMEYKO_DATABASE_URL"] == settings.database_url
    assert kwargs["env"]["SHUMEYKO_SOURCE_REFRESH_ROOT"] == str(source_root)
    marker = source_root / "snapshot-heartbeat-process" / ".worker-heartbeat"
    assert marker.is_file()

    _stop_heartbeat_process(started)

    assert process.terminated is True


def test_file_heartbeat_rejects_symlinked_run_root(tmp_path: Path) -> None:
    source_root = tmp_path / "source-refresh"
    outside = tmp_path / "outside"
    source_root.mkdir()
    outside.mkdir()
    linked_root = source_root / "linked"
    linked_root.symlink_to(outside, target_is_directory=True)
    refresh_run = SourceRefreshRun(
        id="source_refresh_symlink",
        tenant_id="tenant-1",
        client_id="tenant-1",
        mode="full",
        credential_source="tenant",
        dry_run=False,
        status="rebuilding",
        snapshot_set_id="linked",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        root_dir=str(linked_root),
        workbook_path="",
        error_message="",
        worker_id="systemd-source-refresh-worker:unsafe",
        failure_code="",
        created_at=security.utcnow(),
        updated_at=security.utcnow(),
    )

    marker = worker_heartbeat_marker_path(
        refresh_run,
        source_refresh_root=source_root,
        create_parent=True,
    )

    assert marker is None
    assert not (outside / ".worker-heartbeat").exists()


def test_file_heartbeat_rejects_run_root_outside_configured_root(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source-refresh"
    outside = tmp_path / "outside"
    source_root.mkdir()
    outside.mkdir()
    refresh_run = SourceRefreshRun(
        id="source_refresh_outside",
        tenant_id="tenant-1",
        client_id="tenant-1",
        mode="full",
        credential_source="tenant",
        dry_run=False,
        status="rebuilding",
        snapshot_set_id="outside",
        period_start=date(2026, 4, 1),
        period_end=date(2026, 4, 30),
        root_dir=str(outside),
        workbook_path="",
        error_message="",
        worker_id="systemd-source-refresh-worker:unsafe",
        failure_code="",
        created_at=security.utcnow(),
        updated_at=security.utcnow(),
    )

    marker = worker_heartbeat_marker_path(
        refresh_run,
        source_refresh_root=source_root,
        create_parent=True,
    )

    assert marker is None
    assert not (outside / ".worker-heartbeat").exists()


def test_worker_interruption_marks_run_failed_and_preserves_collections(
    tmp_path: Path,
) -> None:
    factory = _worker_factory(tmp_path)
    with factory() as db:
        refresh_run = _queued_run(db, suffix="interrupt")
        repository.update_source_refresh_run(
            db,
            refresh_run,
            status="running",
            worker_id=f"systemd:{refresh_run.id}",
            heartbeat_at=security.utcnow(),
        )
        repository.add_source_refresh_collection(
            db,
            refresh_run,
            source_type="onec_sales_register",
            source_label="1C sales register",
            required=True,
            status="loaded",
            row_count=8,
        )
        refresh_run_id = refresh_run.id
        db.commit()

    class _InterruptedService:
        def run_existing(self, _db, _refresh_run_id):
            raise WorkerInterrupted("SIGTERM")

    with pytest.raises(WorkerInterrupted):
        process_run(
            factory,
            _InterruptedService(),
            refresh_run_id,
            heartbeat_seconds=30,
        )

    with factory() as db:
        refresh_run = db.get(SourceRefreshRun, refresh_run_id)
        assert refresh_run is not None
        assert refresh_run.status == "failed"
        assert refresh_run.failure_code == "worker_interrupted"
        assert len(refresh_run.collections) == 1
        assert refresh_run.collections[0].row_count == 8


def test_worker_unit_has_memory_limit_and_failure_repair() -> None:
    project_root = Path(__file__).resolve().parents[1]
    unit = (
        project_root / "deploy/systemd/shumeiko-source-refresh-worker@.service"
    ).read_text(encoding="utf-8")

    assert "scripts/run_source_refresh_worker.py" in unit
    assert "Slice=shumeiko-source-refresh.slice" in unit
    assert "MemoryHigh=1536M" in unit
    assert "MemoryMax=2G" in unit
    assert "MemorySwapMax=0" in unit
    assert "ManagedOOMMemoryPressure=auto" in unit
    assert "OOMScoreAdjust=500" in unit
    assert "OOMPolicy=stop" in unit
    assert "TasksMax=256" in unit
    assert "repair_source_refresh_run.py" in unit
    assert (
        "ExecStart=/usr/bin/env "
        "SHUMEYKO_ALLOWED_EXPORT_ROOT=/data/shumeyko/prod/reports "
        in unit
    )
    assert "SHUMEYKO_SOURCE_REFRESH_ONEC_MAX_PAGES=1000 " in unit
    assert "RuntimeMaxSec=4h" in unit
    assert "TimeoutStopSec=60" in unit

    collector = (
        project_root
        / "deploy/systemd/shumeiko-source-refresh-collector@.service"
    ).read_text(encoding="utf-8")
    collector_timer = (
        project_root / "deploy/systemd/shumeiko-source-refresh-collector@.timer"
    ).read_text(encoding="utf-8")
    dispatcher = (
        project_root / "deploy/systemd/shumeiko-source-refresh-dispatcher.service"
    ).read_text(encoding="utf-8")
    dispatcher_slot = (
        project_root
        / "deploy/systemd/shumeiko-source-refresh-dispatcher@.service"
    ).read_text(encoding="utf-8")
    dispatcher_slot_timer = (
        project_root / "deploy/systemd/shumeiko-source-refresh-dispatcher@.timer"
    ).read_text(encoding="utf-8")
    resource_slice = (
        project_root / "deploy/systemd/shumeiko-source-refresh.slice"
    ).read_text(encoding="utf-8")

    assert "run_source_refresh_pipeline_task.py --worker-class collector" in collector
    assert "MemoryHigh=768M" in collector
    assert "MemoryMax=1G" in collector
    assert "MemorySwapMax=0" in collector
    assert "Unit=shumeiko-source-refresh-collector@%i.service" in collector_timer
    assert "run_source_refresh_heavy_dispatcher.py" in dispatcher
    assert "MemoryHigh=1536M" in dispatcher
    assert "MemoryMax=2G" in dispatcher
    assert "MemorySwapMax=0" in dispatcher
    assert "SHUMEYKO_SOURCE_REFRESH_HEAVY_CONCURRENCY=1" in dispatcher
    assert "run_source_refresh_heavy_dispatcher.py" in dispatcher_slot
    assert "SHUMEYKO_SOURCE_REFRESH_HEAVY_CONCURRENCY=2" in dispatcher_slot
    assert "MemoryHigh=1536M" in dispatcher_slot
    assert "MemoryMax=2G" in dispatcher_slot
    assert "MemorySwapMax=0" in dispatcher_slot
    assert (
        "Unit=shumeiko-source-refresh-dispatcher@%i.service"
        in dispatcher_slot_timer
    )
    assert "MemoryMax=5G" in resource_slice
    assert "CPUQuota=500%" in resource_slice


def test_default_onec_page_budget_covers_heavy_sales_register() -> None:
    settings = WebSettings(_env_file=None)

    assert settings.source_refresh_onec_max_pages == 1000
