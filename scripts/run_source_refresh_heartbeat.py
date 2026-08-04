# ruff: noqa: E402

from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from scripts.run_source_refresh_worker import (
    _heartbeat_loop,
    _settings,
    worker_heartbeat_marker_path,
)
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import SourceRefreshRun


def main() -> int:
    args = _parse_args()
    settings = _settings(args.database_url)
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        refresh_run = db.get(SourceRefreshRun, args.run_id)
        if refresh_run is None or refresh_run.finished_at is not None:
            return 0
        heartbeat_marker = worker_heartbeat_marker_path(
            refresh_run,
            source_refresh_root=settings.source_refresh_root_path,
            create_parent=True,
        )

    stop_event = threading.Event()

    def stop(_signum, _frame):  # type: ignore[no-untyped-def]
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        _heartbeat_loop(
            session_factory,
            refresh_run_id=args.run_id,
            heartbeat_marker=heartbeat_marker,
            interval_seconds=args.heartbeat_seconds,
            stop_event=stop_event,
        )
    finally:
        engine.dispose()
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Maintain source refresh DB and file heartbeat."
    )
    parser.add_argument("--database-url", default="")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--heartbeat-seconds", type=int, default=30)
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
