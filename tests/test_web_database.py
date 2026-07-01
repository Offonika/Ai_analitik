from __future__ import annotations

from pathlib import Path

from wb_unit_economics.web.database import make_engine


def test_make_engine_recycles_and_pre_pings_non_sqlite() -> None:
    engine = make_engine("postgresql+psycopg://user:pass@localhost/db")

    assert getattr(engine.pool, "_pre_ping", False) is True
    assert getattr(engine.pool, "_recycle", -1) == 1800


def test_make_engine_keeps_sqlite_file_setup(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "web.sqlite3"
    engine = make_engine(f"sqlite:///{db_path}")

    assert db_path.parent.exists()
    assert getattr(engine.pool, "_pre_ping", False) is False
