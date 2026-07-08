from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import Client, ClientCompany, WbCabinet


def test_repair_web_client_hierarchy_is_dry_run_first(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'web.sqlite3'}"
    engine = make_engine(database_url)
    init_db(engine)

    dry_run = _run_repair(
        database_url,
        "--tenant-id",
        "second-client",
        "--client-id",
        "second-client",
        "--client-name",
        "Второй клиент",
        "--company",
        "ООО Второй клиент",
        "--cabinet",
        "ООО Второй клиент::WB Второй клиент",
    )

    assert dry_run.returncode == 0
    assert "DRY RUN" in dry_run.stdout
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        assert db.get(Client, "second-client") is None

    applied = _run_repair(
        database_url,
        "--tenant-id",
        "second-client",
        "--client-id",
        "second-client",
        "--client-name",
        "Второй клиент",
        "--company",
        "ООО Второй клиент",
        "--cabinet",
        "ООО Второй клиент::WB Второй клиент",
        "--apply",
    )

    assert applied.returncode == 0
    assert "APPLIED" in applied.stdout
    with session_factory() as db:
        client = db.get(Client, "second-client")
        assert client is not None
        assert client.name == "Второй клиент"
        companies = db.query(ClientCompany).filter_by(client_id="second-client").all()
        cabinets = db.query(WbCabinet).filter_by(client_id="second-client").all()
        assert [item.display_name for item in companies] == ["ООО Второй клиент"]
        assert [item.display_name for item in cabinets] == ["WB Второй клиент"]
        assert cabinets[0].client_company_id == companies[0].id


def _run_repair(database_url: str, *args: str) -> subprocess.CompletedProcess[str]:
    project_root = Path(__file__).resolve().parents[1]
    return subprocess.run(
        [
            sys.executable,
            "scripts/repair_web_client_hierarchy.py",
            "--database-url",
            database_url,
            *args,
        ],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )
