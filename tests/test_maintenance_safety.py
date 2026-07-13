from __future__ import annotations

import hashlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from scripts.create_maintenance_backup import _roles_command
from scripts.online_repack_source_snapshot_rows import (
    _pg_repack_command,
    _postgres_admin_command,
)
from wb_unit_economics.maintenance_safety import (
    BackupVerificationError,
    verify_backup_bundle,
)


def test_backup_bundle_requires_database_roles_and_custom_format(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mount = tmp_path / "external"
    mount.mkdir()
    database_dump = mount / "database.dump"
    roles_dump = mount / "roles.sql"
    database_dump.write_bytes(b"PGDMP-test")
    roles_dump.write_text("CREATE ROLE readonly;", encoding="utf-8")
    monkeypatch.setattr("os.path.ismount", lambda value: Path(value) == mount)
    verification = tmp_path / "verification.json"
    verification.write_text(
        json.dumps(
            {
                "databaseDumpPath": str(database_dump),
                "databaseDumpSha256": _sha(database_dump),
                "rolesDumpPath": str(roles_dump),
                "rolesDumpSha256": _sha(roles_dump),
                "createdAt": datetime.now(UTC).isoformat(),
                "offHostVerified": True,
                "restoreListChecked": True,
                "backupMount": str(mount),
                "backupDevice": str(database_dump.stat().st_dev),
            }
        ),
        encoding="utf-8",
    )

    result = verify_backup_bundle(
        verification,
        postgres_data_path=tmp_path / "missing-postgres",
        source_data_path=tmp_path / "missing-data",
        run_restore_list=False,
    )

    assert result.database_dump_path == database_dump
    assert result.roles_dump_path == roles_dump


def test_backup_bundle_rejects_same_device_as_source_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mount = tmp_path / "external"
    mount.mkdir()
    database_dump = mount / "database.dump"
    roles_dump = mount / "roles.sql"
    database_dump.write_bytes(b"PGDMP-test")
    roles_dump.write_text("roles", encoding="utf-8")
    monkeypatch.setattr("os.path.ismount", lambda value: Path(value) == mount)
    verification = tmp_path / "verification.json"
    verification.write_text(
        json.dumps(
            {
                "databaseDumpPath": str(database_dump),
                "databaseDumpSha256": _sha(database_dump),
                "rolesDumpPath": str(roles_dump),
                "rolesDumpSha256": _sha(roles_dump),
                "createdAt": datetime.now(UTC).isoformat(),
                "offHostVerified": True,
                "restoreListChecked": True,
                "backupMount": str(mount),
                "backupDevice": str(database_dump.stat().st_dev),
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BackupVerificationError, match="different"):
        verify_backup_bundle(
            verification,
            postgres_data_path=tmp_path,
            source_data_path=tmp_path,
            run_restore_list=False,
        )


def test_s3_backup_bundle_checks_versions_hashes_and_readback(
    tmp_path: Path,
) -> None:
    credentials = _s3_credentials(tmp_path)
    database = b"PGDMP-test-archive"
    roles = b"CREATE ROLE readonly;"
    client = _FakeS3Client(
        {
            ("ai-analitik", "maintenance/database.dump", "db-v1"): database,
            ("ai-analitik", "maintenance/roles.sql", "roles-v1"): roles,
        }
    )
    verification = tmp_path / "s3-verification.json"
    verification.write_text(
        json.dumps(
            {
                "storageType": "s3",
                "databaseDumpUri": "s3://ai-analitik/maintenance/database.dump",
                "databaseDumpVersionId": "db-v1",
                "databaseDumpSha256": hashlib.sha256(database).hexdigest(),
                "databaseDumpSize": len(database),
                "rolesDumpUri": "s3://ai-analitik/maintenance/roles.sql",
                "rolesDumpVersionId": "roles-v1",
                "rolesDumpSha256": hashlib.sha256(roles).hexdigest(),
                "rolesDumpSize": len(roles),
                "s3Endpoint": "https://s3.twcstorage.ru",
                "s3Region": "ru-1",
                "s3Bucket": "ai-analitik",
                "createdAt": datetime.now(UTC).isoformat(),
                "offHostVerified": True,
                "restoreListChecked": True,
            }
        ),
        encoding="utf-8",
    )

    result = verify_backup_bundle(
        verification,
        run_restore_list=False,
        s3_credentials_path=credentials,
        s3_client=client,
    )

    assert result.storage_type == "s3"
    assert result.database_dump_location.endswith("/database.dump")
    assert client.ranges


def test_s3_backup_bundle_rejects_changed_object(tmp_path: Path) -> None:
    credentials = _s3_credentials(tmp_path)
    database = b"PGDMP-changed"
    roles = b"roles"
    client = _FakeS3Client(
        {
            ("ai-analitik", "maintenance/database.dump", "db-v1"): database,
            ("ai-analitik", "maintenance/roles.sql", "roles-v1"): roles,
        }
    )
    verification = tmp_path / "s3-verification.json"
    verification.write_text(
        json.dumps(
            {
                "storageType": "s3",
                "databaseDumpUri": "s3://ai-analitik/maintenance/database.dump",
                "databaseDumpVersionId": "db-v1",
                "databaseDumpSha256": "0" * 64,
                "databaseDumpSize": len(database),
                "rolesDumpUri": "s3://ai-analitik/maintenance/roles.sql",
                "rolesDumpVersionId": "roles-v1",
                "rolesDumpSha256": hashlib.sha256(roles).hexdigest(),
                "rolesDumpSize": len(roles),
                "s3Endpoint": "https://s3.twcstorage.ru",
                "s3Region": "ru-1",
                "s3Bucket": "ai-analitik",
                "createdAt": datetime.now(UTC).isoformat(),
                "offHostVerified": True,
                "restoreListChecked": True,
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(BackupVerificationError, match="checksum mismatch"):
        verify_backup_bundle(
            verification,
            run_restore_list=False,
            s3_credentials_path=credentials,
            s3_client=client,
        )


def test_s3_restore_list_may_close_stdin_before_full_hash_readback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    credentials = _s3_credentials(tmp_path)
    database = b"PGDMP" + (b"x" * (2 * 1024 * 1024))
    roles = b"roles"
    client = _FakeS3Client(
        {
            ("ai-analitik", "maintenance/database.dump", "db-v1"): database,
            ("ai-analitik", "maintenance/roles.sql", "roles-v1"): roles,
        }
    )
    verification = tmp_path / "s3-verification.json"
    verification.write_text(
        json.dumps(
            {
                "storageType": "s3",
                "databaseDumpUri": "s3://ai-analitik/maintenance/database.dump",
                "databaseDumpVersionId": "db-v1",
                "databaseDumpSha256": hashlib.sha256(database).hexdigest(),
                "databaseDumpSize": len(database),
                "rolesDumpUri": "s3://ai-analitik/maintenance/roles.sql",
                "rolesDumpVersionId": "roles-v1",
                "rolesDumpSha256": hashlib.sha256(roles).hexdigest(),
                "rolesDumpSize": len(roles),
                "s3Endpoint": "https://s3.twcstorage.ru",
                "s3Region": "ru-1",
                "s3Bucket": "ai-analitik",
                "createdAt": datetime.now(UTC).isoformat(),
                "offHostVerified": True,
                "restoreListChecked": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("shutil.which", lambda _: "/bin/true")

    result = verify_backup_bundle(
        verification,
        run_restore_list=True,
        s3_credentials_path=credentials,
        s3_client=client,
    )

    assert result.database_dump_sha256 == hashlib.sha256(database).hexdigest()


def test_pg_repack_command_waits_without_killing_backends() -> None:
    command, env = _pg_repack_command(
        "postgresql+psycopg://user:secret@localhost:5432/database"
    )

    assert "--wait-timeout" in command
    assert "--no-kill-backend" in command
    assert command[command.index("--table") + 1] == (
        "wb_unit_economics.source_snapshot_rows"
    )
    assert env["PGPASSWORD"] == "secret"


def test_pg_repack_superuser_command_uses_local_socket_without_password() -> None:
    command, env = _pg_repack_command(
        "postgresql+psycopg://user:secret@localhost:55433/database",
        system_user="postgres",
    )

    assert command[:3] == ["sudo", "-u", "postgres"]
    assert "--host" not in command
    assert command[command.index("--port") + 1] == "55433"
    assert "--username" not in command
    assert "PGPASSWORD" not in env


def test_postgres_admin_command_uses_local_system_user() -> None:
    command, env = _postgres_admin_command(
        "postgresql://app:secret@localhost:55433/database",
        sql="CREATE EXTENSION IF NOT EXISTS pg_repack",
        system_user="postgres",
    )

    assert command[:3] == ["sudo", "-u", "postgres"]
    assert command[command.index("--dbname") + 1] == "database"
    assert command[command.index("--port") + 1] == "55433"
    assert command[command.index("--command") + 1] == (
        "CREATE EXTENSION IF NOT EXISTS pg_repack"
    )
    assert "PGPASSWORD" not in env


def test_roles_dump_can_use_local_postgres_system_user() -> None:
    command, env = _roles_command(
        "/usr/bin/pg_dumpall",
        database_url="postgresql://app:secret@localhost:55433/database",
        connection_args=["--host", "localhost", "--username", "app"],
        connection_env={"PGPASSWORD": "secret"},
        system_user="postgres",
    )

    assert command == [
        "sudo",
        "-u",
        "postgres",
        "/usr/bin/pg_dumpall",
        "--roles-only",
        "--port",
        "55433",
    ]
    assert "PGPASSWORD" not in env


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _s3_credentials(tmp_path: Path) -> Path:
    path = tmp_path / "s3-backup.json"
    path.write_text(
        json.dumps(
            {
                "endpoint_url": "https://s3.twcstorage.ru",
                "region": "ru-1",
                "bucket": "ai-analitik",
                "access_key": "access",
                "secret_key": "secret",
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


class _FakeBody(io.BytesIO):
    pass


class _FakeS3Client:
    def __init__(self, objects: dict[tuple[str, str, str], bytes]) -> None:
        self.objects = objects
        self.ranges: list[str] = []

    def get_bucket_versioning(self, **kwargs: Any) -> dict[str, str]:
        return {"Status": "Enabled"}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        identity = (kwargs["Bucket"], kwargs["Key"], kwargs["VersionId"])
        content = self.objects[identity]
        return {
            "ContentLength": len(content),
            "VersionId": kwargs["VersionId"],
            "LastModified": datetime.now(UTC),
        }

    def get_object(self, **kwargs: Any) -> dict[str, _FakeBody]:
        identity = (kwargs["Bucket"], kwargs["Key"], kwargs["VersionId"])
        content = self.objects[identity]
        range_value = kwargs["Range"]
        self.ranges.append(range_value)
        start_text, end_text = range_value.removeprefix("bytes=").split("-", 1)
        start = int(start_text)
        end = int(end_text)
        return {"Body": _FakeBody(content[start : end + 1])}
