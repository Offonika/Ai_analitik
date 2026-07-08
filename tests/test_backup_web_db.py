from __future__ import annotations

import gzip
import io

import pytest

from scripts import backup_web_db


def test_write_pg_dump_backup_streams_stdout_to_gzip(monkeypatch, tmp_path) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []
    dump_bytes = b"CREATE TABLE report_runs(id text);\n" * 3

    class FakeProcess:
        stdout = io.BytesIO(dump_bytes)

        def wait(self) -> int:
            return 0

    def fake_popen(args: list[str], **kwargs: object) -> FakeProcess:
        calls.append((args, kwargs))
        return FakeProcess()

    monkeypatch.setattr(backup_web_db.subprocess, "Popen", fake_popen)
    target = tmp_path / "shumeiko-web.sql.gz"

    backup_web_db.write_pg_dump_backup(
        "postgresql://readonly:secret@example:55433/db", target
    )

    with gzip.open(target, "rb") as handle:
        assert handle.read() == dump_bytes
    assert not target.with_name(f"{target.name}.tmp").exists()
    assert calls[0][0] == ["pg_dump", "--no-owner", "--no-privileges"]
    assert calls[0][1]["stdout"] == backup_web_db.subprocess.PIPE
    assert calls[0][1]["env"]["PGHOST"] == "example"
    assert calls[0][1]["env"]["PGPORT"] == "55433"
    assert calls[0][1]["env"]["PGUSER"] == "readonly"
    assert calls[0][1]["env"]["PGPASSWORD"] == "secret"
    assert calls[0][1]["env"]["PGDATABASE"] == "db"
    assert "secret" not in " ".join(calls[0][0])
    assert "capture_output" not in calls[0][1]


def test_write_pg_dump_backup_removes_partial_file_on_failure(
    monkeypatch, tmp_path
) -> None:
    class FakeProcess:
        stdout = io.BytesIO(b"partial dump\n")

        def __init__(self, stderr) -> None:
            stderr.write(b"permission denied")

        def wait(self) -> int:
            return 1

    def fake_popen(_args: list[str], **kwargs: object) -> FakeProcess:
        return FakeProcess(kwargs["stderr"])

    monkeypatch.setattr(backup_web_db.subprocess, "Popen", fake_popen)
    target = tmp_path / "shumeiko-web.sql.gz"

    with pytest.raises(SystemExit, match="permission denied"):
        backup_web_db.write_pg_dump_backup("postgresql://example/db", target)

    assert not target.exists()
    assert not target.with_name(f"{target.name}.tmp").exists()
