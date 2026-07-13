from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urlparse


class BackupVerificationError(ValueError):
    pass


@dataclass(frozen=True)
class S3BackupConfig:
    endpoint_url: str
    region: str
    bucket: str
    access_key: str
    secret_key: str


@dataclass(frozen=True)
class VerifiedBackupBundle:
    storage_type: str
    database_dump_location: str
    database_dump_sha256: str
    roles_dump_location: str
    roles_dump_sha256: str
    created_at: datetime
    database_dump_path: Path | None = None
    roles_dump_path: Path | None = None
    backup_mount: Path | None = None
    backup_device: str = ""


def verify_backup_bundle(
    verification_path: Path,
    *,
    max_age_hours: int = 24,
    postgres_data_path: Path = Path("/var/lib/postgresql"),
    source_data_path: Path = Path("/data"),
    run_restore_list: bool = True,
    s3_credentials_path: Path | None = None,
    s3_client: Any | None = None,
) -> VerifiedBackupBundle:
    payload = _verification_payload(verification_path)
    if payload.get("offHostVerified") is not True:
        raise BackupVerificationError("off-host backup verification is required")
    if payload.get("restoreListChecked") is not True:
        raise BackupVerificationError("pg_restore --list verification is required")

    created_at = _created_at(payload.get("createdAt"))
    _require_fresh(created_at, max_age_hours=max_age_hours)
    storage_type = str(payload.get("storageType") or "filesystem").strip().lower()
    if storage_type == "s3":
        return _verify_s3_bundle(
            payload,
            created_at=created_at,
            max_age_hours=max_age_hours,
            run_restore_list=run_restore_list,
            credentials_path=s3_credentials_path,
            client=s3_client,
        )
    if storage_type != "filesystem":
        raise BackupVerificationError("unsupported backup storageType")
    return _verify_filesystem_bundle(
        payload,
        created_at=created_at,
        max_age_hours=max_age_hours,
        postgres_data_path=postgres_data_path,
        source_data_path=source_data_path,
        run_restore_list=run_restore_list,
    )


def load_s3_backup_config(path: Path) -> S3BackupConfig:
    try:
        resolved = path.resolve(strict=True)
        mode = stat.S_IMODE(resolved.stat().st_mode)
        if mode & 0o077:
            raise BackupVerificationError(
                "S3 credential file must not be accessible by group or others"
            )
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except BackupVerificationError:
        raise
    except (OSError, TypeError, ValueError) as exc:
        raise BackupVerificationError("S3 credential file is unreadable") from exc
    if not isinstance(payload, dict):
        raise BackupVerificationError("S3 credential file must be an object")
    required = {
        "endpoint_url",
        "region",
        "bucket",
        "access_key",
        "secret_key",
    }
    if set(payload) != required:
        raise BackupVerificationError("S3 credential file has unexpected fields")
    values = {key: str(payload.get(key) or "").strip() for key in required}
    if not all(values.values()):
        raise BackupVerificationError("S3 credential file has empty fields")
    endpoint = urlparse(values["endpoint_url"])
    if (
        endpoint.scheme != "https"
        or not endpoint.netloc
        or endpoint.path not in {"", "/"}
    ):
        raise BackupVerificationError("S3 endpoint must be an HTTPS origin")
    return S3BackupConfig(
        endpoint_url=values["endpoint_url"].rstrip("/"),
        region=values["region"],
        bucket=values["bucket"],
        access_key=values["access_key"],
        secret_key=values["secret_key"],
    )


def make_s3_client(config: S3BackupConfig) -> Any:
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise BackupVerificationError("boto3 is required for S3 backup") from exc
    return boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        region_name=config.region,
        aws_access_key_id=config.access_key,
        aws_secret_access_key=config.secret_key,
        config=Config(signature_version="s3v4", retries={"max_attempts": 5}),
    )


def _verification_payload(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as exc:
        raise BackupVerificationError(
            "backup verification JSON is unreadable"
        ) from exc
    if not isinstance(payload, dict):
        raise BackupVerificationError("backup verification JSON must be an object")
    return payload


def _verify_filesystem_bundle(
    payload: dict[str, object],
    *,
    created_at: datetime,
    max_age_hours: int,
    postgres_data_path: Path,
    source_data_path: Path,
    run_restore_list: bool,
) -> VerifiedBackupBundle:
    database_dump = _required_file(payload, "databaseDumpPath")
    roles_dump = _required_file(payload, "rolesDumpPath")
    database_sha = _required_sha(payload, "databaseDumpSha256")
    roles_sha = _required_sha(payload, "rolesDumpSha256")
    if _file_sha256(database_dump) != database_sha:
        raise BackupVerificationError("database dump checksum mismatch")
    if _file_sha256(roles_dump) != roles_sha:
        raise BackupVerificationError("roles dump checksum mismatch")
    with database_dump.open("rb") as handle:
        custom_format_header = handle.read(5)
    if custom_format_header != b"PGDMP":
        raise BackupVerificationError("database dump is not PostgreSQL custom format")
    if roles_dump.stat().st_size <= 0:
        raise BackupVerificationError("roles dump is empty")

    oldest_file_time = min(database_dump.stat().st_mtime, roles_dump.stat().st_mtime)
    file_created_at = datetime.fromtimestamp(oldest_file_time, tz=UTC)
    _require_fresh(file_created_at, max_age_hours=max_age_hours, label="backup files")

    try:
        mount = Path(str(payload.get("backupMount") or "")).resolve(strict=True)
    except OSError as exc:
        raise BackupVerificationError("backupMount is unreadable") from exc
    if not mount.is_dir() or not os.path.ismount(mount):
        raise BackupVerificationError("backupMount is not a mounted filesystem")
    if not database_dump.resolve().is_relative_to(mount):
        raise BackupVerificationError("database dump is outside backupMount")
    if not roles_dump.resolve().is_relative_to(mount):
        raise BackupVerificationError("roles dump is outside backupMount")
    dump_device = str(database_dump.stat().st_dev)
    roles_device = str(roles_dump.stat().st_dev)
    declared_device = str(payload.get("backupDevice") or "").strip()
    if dump_device != roles_device or declared_device != dump_device:
        raise BackupVerificationError("backup device metadata does not match files")
    forbidden_devices = {
        str(path.resolve(strict=True).stat().st_dev)
        for path in (postgres_data_path, source_data_path)
        if path.exists()
    }
    if dump_device in forbidden_devices:
        raise BackupVerificationError(
            "backup must use a device different from PostgreSQL and /data"
        )

    if run_restore_list:
        _run_pg_restore_file(database_dump)

    return VerifiedBackupBundle(
        storage_type="filesystem",
        database_dump_location=str(database_dump),
        database_dump_sha256=database_sha,
        roles_dump_location=str(roles_dump),
        roles_dump_sha256=roles_sha,
        created_at=created_at,
        database_dump_path=database_dump,
        roles_dump_path=roles_dump,
        backup_mount=mount,
        backup_device=dump_device,
    )


def _verify_s3_bundle(
    payload: dict[str, object],
    *,
    created_at: datetime,
    max_age_hours: int,
    run_restore_list: bool,
    credentials_path: Path | None,
    client: Any | None,
) -> VerifiedBackupBundle:
    path = credentials_path or Path(
        os.getenv(
            "SHUMEYKO_S3_BACKUP_CONFIG",
            "/root/.config/shumeyko/s3-backup.json",
        )
    )
    config = load_s3_backup_config(path)
    declared_endpoint = str(payload.get("s3Endpoint") or "").rstrip("/")
    declared_region = str(payload.get("s3Region") or "")
    declared_bucket = str(payload.get("s3Bucket") or "")
    if (
        declared_endpoint != config.endpoint_url
        or declared_region != config.region
        or declared_bucket != config.bucket
    ):
        raise BackupVerificationError("S3 verification metadata does not match config")
    database_uri = _required_s3_uri(payload, "databaseDumpUri", config.bucket)
    roles_uri = _required_s3_uri(payload, "rolesDumpUri", config.bucket)
    database_version = _required_text(payload, "databaseDumpVersionId")
    roles_version = _required_text(payload, "rolesDumpVersionId")
    database_sha = _required_sha(payload, "databaseDumpSha256")
    roles_sha = _required_sha(payload, "rolesDumpSha256")
    database_size = _required_positive_int(payload, "databaseDumpSize")
    roles_size = _required_positive_int(payload, "rolesDumpSize")
    s3 = client or make_s3_client(config)
    try:
        versioning = s3.get_bucket_versioning(Bucket=config.bucket).get("Status")
    except Exception as exc:
        raise BackupVerificationError("S3 bucket versioning check failed") from exc
    if versioning != "Enabled":
        raise BackupVerificationError("S3 bucket versioning must be enabled")

    _, database_key = _parse_s3_uri(database_uri)
    _, roles_key = _parse_s3_uri(roles_uri)
    _verify_s3_object(
        s3,
        bucket=config.bucket,
        key=database_key,
        version_id=database_version,
        expected_size=database_size,
        expected_sha=database_sha,
        max_age_hours=max_age_hours,
        require_custom_header=True,
        run_restore_list=run_restore_list,
    )
    _verify_s3_object(
        s3,
        bucket=config.bucket,
        key=roles_key,
        version_id=roles_version,
        expected_size=roles_size,
        expected_sha=roles_sha,
        max_age_hours=max_age_hours,
        require_custom_header=False,
        run_restore_list=False,
    )
    return VerifiedBackupBundle(
        storage_type="s3",
        database_dump_location=database_uri,
        database_dump_sha256=database_sha,
        roles_dump_location=roles_uri,
        roles_dump_sha256=roles_sha,
        created_at=created_at,
    )


def _verify_s3_object(
    client: Any,
    *,
    bucket: str,
    key: str,
    version_id: str,
    expected_size: int,
    expected_sha: str,
    max_age_hours: int,
    require_custom_header: bool,
    run_restore_list: bool,
) -> None:
    try:
        head = client.head_object(Bucket=bucket, Key=key, VersionId=version_id)
    except Exception as exc:
        raise BackupVerificationError("S3 backup object is not readable") from exc
    if int(head.get("ContentLength") or -1) != expected_size:
        raise BackupVerificationError("S3 backup object size mismatch")
    returned_version = str(head.get("VersionId") or "")
    if returned_version and returned_version != version_id:
        raise BackupVerificationError("S3 backup object version mismatch")
    last_modified = head.get("LastModified")
    if isinstance(last_modified, datetime):
        if last_modified.tzinfo is None:
            last_modified = last_modified.replace(tzinfo=UTC)
        _require_fresh(
            last_modified.astimezone(UTC),
            max_age_hours=max_age_hours,
            label="S3 backup object",
        )

    restore_process: subprocess.Popen[bytes] | None = None
    restore_input: BinaryIO | None = None
    if run_restore_list:
        pg_restore = shutil.which("pg_restore")
        if pg_restore is None:
            raise BackupVerificationError("pg_restore is required for backup check")
        restore_process = subprocess.Popen(
            [pg_restore, "--list"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        restore_input = restore_process.stdin

    digest = hashlib.sha256()
    received = 0
    header = b""
    try:
        for chunk in _iter_s3_object(
            client,
            bucket=bucket,
            key=key,
            version_id=version_id,
            size=expected_size,
        ):
            if len(header) < 5:
                header = (header + chunk)[:5]
            digest.update(chunk)
            received += len(chunk)
            if restore_input is not None:
                try:
                    restore_input.write(chunk)
                except BrokenPipeError:
                    restore_input.close()
                    restore_input = None
    except Exception as exc:
        if restore_process is not None:
            restore_process.kill()
            restore_process.wait()
        raise BackupVerificationError("S3 backup object readback failed") from exc
    finally:
        if restore_input is not None:
            restore_input.close()

    if restore_process is not None:
        return_code = restore_process.wait()
        if return_code != 0:
            raise BackupVerificationError("pg_restore --list failed")
    if received != expected_size:
        raise BackupVerificationError("S3 backup object length mismatch")
    if digest.hexdigest() != expected_sha:
        raise BackupVerificationError("S3 backup object checksum mismatch")
    if require_custom_header and header != b"PGDMP":
        raise BackupVerificationError("database dump is not PostgreSQL custom format")


def _iter_s3_object(
    client: Any,
    *,
    bucket: str,
    key: str,
    version_id: str,
    size: int,
    range_size: int = 64 * 1024 * 1024,
) -> Iterator[bytes]:
    for start in range(0, size, range_size):
        end = min(size - 1, start + range_size - 1)
        response = client.get_object(
            Bucket=bucket,
            Key=key,
            VersionId=version_id,
            Range=f"bytes={start}-{end}",
        )
        body = response["Body"]
        expected = end - start + 1
        received = 0
        try:
            while received < expected:
                chunk = body.read(min(1024 * 1024, expected - received))
                if not chunk:
                    break
                received += len(chunk)
                yield chunk
        finally:
            body.close()
        if received != expected:
            raise BackupVerificationError("S3 range response was truncated")


def _run_pg_restore_file(database_dump: Path) -> None:
    pg_restore = shutil.which("pg_restore")
    if pg_restore is None:
        raise BackupVerificationError("pg_restore is required for backup check")
    result = subprocess.run(
        [pg_restore, "--list", str(database_dump)],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode != 0:
        raise BackupVerificationError("pg_restore --list failed")


def _required_file(payload: dict[str, object], key: str) -> Path:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise BackupVerificationError(f"{key} is required")
    try:
        path = Path(value).resolve(strict=True)
    except OSError as exc:
        raise BackupVerificationError(f"{key} is not readable") from exc
    if not path.is_file():
        raise BackupVerificationError(f"{key} is not a file")
    return path


def _required_sha(payload: dict[str, object], key: str) -> str:
    value = str(payload.get(key) or "").strip().lower()
    if len(value) != 64 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise BackupVerificationError(f"{key} must be a SHA-256 hex digest")
    return value


def _required_text(payload: dict[str, object], key: str) -> str:
    value = str(payload.get(key) or "").strip()
    if not value:
        raise BackupVerificationError(f"{key} is required")
    return value


def _required_positive_int(payload: dict[str, object], key: str) -> int:
    try:
        value = int(payload.get(key) or 0)
    except (TypeError, ValueError) as exc:
        raise BackupVerificationError(f"{key} must be a positive integer") from exc
    if value <= 0:
        raise BackupVerificationError(f"{key} must be a positive integer")
    return value


def _required_s3_uri(
    payload: dict[str, object], key: str, expected_bucket: str
) -> str:
    value = _required_text(payload, key)
    bucket, object_key = _parse_s3_uri(value)
    if bucket != expected_bucket:
        raise BackupVerificationError(f"{key} uses an unexpected bucket")
    parts = object_key.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise BackupVerificationError(f"{key} contains an unsafe object key")
    return value


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "s3" or not parsed.netloc or not parsed.path.lstrip("/"):
        raise BackupVerificationError("invalid S3 URI")
    if parsed.params or parsed.query or parsed.fragment:
        raise BackupVerificationError("invalid S3 URI")
    return parsed.netloc, parsed.path.lstrip("/")


def _created_at(value: object) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise BackupVerificationError("createdAt must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise BackupVerificationError("createdAt must include a timezone")
    return parsed.astimezone(UTC)


def _require_fresh(
    created_at: datetime,
    *,
    max_age_hours: int,
    label: str = "verified backup",
) -> None:
    age_seconds = max(0.0, (datetime.now(UTC) - created_at).total_seconds())
    if age_seconds > max(1, int(max_age_hours)) * 3600:
        raise BackupVerificationError(f"{label} is too old")


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
