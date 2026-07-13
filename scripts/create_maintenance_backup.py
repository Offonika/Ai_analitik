#!/usr/bin/env python3
"""Create and verify an off-host PostgreSQL maintenance backup bundle."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.maintenance_safety import (
    BackupVerificationError,
    load_s3_backup_config,
    make_s3_client,
    verify_backup_bundle,
)


@dataclass(frozen=True)
class UploadedObject:
    uri: str
    version_id: str
    sha256: str
    size: int


class HashingReader:
    def __init__(self, raw: BinaryIO) -> None:
        self.raw = raw
        self.digest = hashlib.sha256()
        self.size = 0
        self.lock = threading.Lock()

    def read(self, size: int = -1) -> bytes:
        with self.lock:
            chunk = self.raw.read(size)
            if chunk:
                self.digest.update(chunk)
                self.size += len(chunk)
            return chunk

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return False


def main() -> int:
    args = _parse_args()
    database_url = args.database_url or os.getenv("SHUMEYKO_DATABASE_URL") or ""
    if not database_url:
        raise SystemExit("SHUMEYKO_DATABASE_URL is required")
    pg_dump = shutil.which("pg_dump")
    pg_dumpall = shutil.which("pg_dumpall")
    pg_restore = shutil.which("pg_restore")
    if not pg_dump or not pg_dumpall or not pg_restore:
        raise SystemExit("pg_dump, pg_dumpall and pg_restore are required")
    connection_args, env, database = _connection_args(database_url)
    roles_command, roles_env = _roles_command(
        pg_dumpall,
        database_url=database_url,
        connection_args=connection_args,
        connection_env=env,
        system_user=args.roles_system_user,
    )
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if args.s3_config:
        verification = _create_s3_bundle(
            args=args,
            timestamp=timestamp,
            database_command=[
                pg_dump,
                *connection_args,
                "--format=custom",
                database,
            ],
            roles_command=roles_command,
            process_env=env,
            roles_env=roles_env,
        )
    else:
        verification = _create_filesystem_bundle(
            args=args,
            timestamp=timestamp,
            database_command=[
                pg_dump,
                *connection_args,
                "--format=custom",
                database,
            ],
            roles_command=roles_command,
            process_env=env,
            roles_env=roles_env,
        )
    print(verification)
    return 0


def _create_s3_bundle(
    *,
    args: argparse.Namespace,
    timestamp: str,
    database_command: list[str],
    roles_command: list[str],
    process_env: dict[str, str],
    roles_env: dict[str, str],
) -> Path:
    credentials_path = Path(args.s3_config)
    try:
        config = load_s3_backup_config(credentials_path)
        client = make_s3_client(config)
    except BackupVerificationError as exc:
        raise SystemExit(str(exc)) from exc
    prefix = f"shumeiko-maintenance/{timestamp}"
    uploaded: list[UploadedObject] = []
    try:
        database = _upload_command_output(
            client,
            bucket=config.bucket,
            key=f"{prefix}/database.dump",
            command=database_command,
            env=process_env,
            content_type="application/octet-stream",
        )
        uploaded.append(database)
        roles = _upload_command_output(
            client,
            bucket=config.bucket,
            key=f"{prefix}/roles.sql",
            command=roles_command,
            env=roles_env,
            content_type="application/sql",
        )
        uploaded.append(roles)
        verification_dir = Path(args.verification_dir).resolve()
        verification_dir.mkdir(parents=True, exist_ok=True)
        verification_dir.chmod(0o700)
        verification = verification_dir / f"{timestamp}-backup-verification.json"
        payload = {
            "storageType": "s3",
            "databaseDumpUri": database.uri,
            "databaseDumpVersionId": database.version_id,
            "databaseDumpSha256": database.sha256,
            "databaseDumpSize": database.size,
            "rolesDumpUri": roles.uri,
            "rolesDumpVersionId": roles.version_id,
            "rolesDumpSha256": roles.sha256,
            "rolesDumpSize": roles.size,
            "s3Endpoint": config.endpoint_url,
            "s3Region": config.region,
            "s3Bucket": config.bucket,
            "createdAt": datetime.now(UTC).isoformat(),
            "offHostVerified": True,
            "restoreListChecked": True,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ).encode("utf-8")
        verification.write_bytes(encoded)
        verification.chmod(0o600)
        verify_backup_bundle(
            verification,
            postgres_data_path=Path(args.postgres_data_path),
            source_data_path=Path(args.source_data_path),
            s3_credentials_path=credentials_path,
            s3_client=client,
        )
        receipt = _upload_bytes(
            client,
            bucket=config.bucket,
            key=f"{prefix}/backup-verification.json",
            content=encoded,
            content_type="application/json",
        )
        uploaded.append(receipt)
        _verify_small_object(client, receipt, encoded)
    except BaseException:
        for item in reversed(uploaded):
            _delete_uploaded_object(client, item)
        raise
    print(f"offHostVerification=s3://{config.bucket}/{prefix}/backup-verification.json")
    return verification


def _create_filesystem_bundle(
    *,
    args: argparse.Namespace,
    timestamp: str,
    database_command: list[str],
    roles_command: list[str],
    process_env: dict[str, str],
    roles_env: dict[str, str],
) -> Path:
    mount = Path(args.backup_mount).resolve(strict=True)
    if not mount.is_dir() or not os.path.ismount(mount):
        raise SystemExit("backup mount is not a mounted filesystem")
    device = str(mount.stat().st_dev)
    forbidden_devices = {
        str(path.resolve(strict=True).stat().st_dev)
        for path in (Path(args.postgres_data_path), Path(args.source_data_path))
        if path.exists()
    }
    if device in forbidden_devices:
        raise SystemExit("backup mount must differ from PostgreSQL and /data")
    output_dir = mount / "shumeiko-maintenance" / timestamp
    output_dir.mkdir(parents=True, exist_ok=False)
    database_dump = output_dir / "database.dump"
    roles_dump = output_dir / "roles.sql"
    with database_dump.open("wb") as handle:
        subprocess.run(database_command, env=process_env, check=True, stdout=handle)
    with roles_dump.open("wb") as handle:
        subprocess.run(roles_command, env=roles_env, check=True, stdout=handle)
    verification = output_dir / "backup-verification.json"
    verification.write_text(
        json.dumps(
            {
                "storageType": "filesystem",
                "databaseDumpPath": str(database_dump),
                "databaseDumpSha256": _sha256(database_dump),
                "rolesDumpPath": str(roles_dump),
                "rolesDumpSha256": _sha256(roles_dump),
                "createdAt": datetime.now(UTC).isoformat(),
                "offHostVerified": True,
                "restoreListChecked": True,
                "backupMount": str(mount),
                "backupDevice": device,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    verify_backup_bundle(
        verification,
        postgres_data_path=Path(args.postgres_data_path),
        source_data_path=Path(args.source_data_path),
    )
    return verification


def _upload_command_output(
    client: Any,
    *,
    bucket: str,
    key: str,
    command: list[str],
    env: dict[str, str],
    content_type: str,
) -> UploadedObject:
    try:
        from boto3.s3.transfer import TransferConfig
    except ImportError as exc:
        raise SystemExit("boto3 is required for S3 backup") from exc
    with tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(
            command,
            env=env,
            stdout=subprocess.PIPE,
            stderr=stderr,
        )
        if process.stdout is None:
            process.kill()
            raise RuntimeError("backup process stdout is unavailable")
        reader = HashingReader(process.stdout)
        try:
            client.upload_fileobj(
                reader,
                bucket,
                key,
                ExtraArgs={"ContentType": content_type},
                Config=TransferConfig(
                    multipart_threshold=16 * 1024 * 1024,
                    multipart_chunksize=16 * 1024 * 1024,
                    max_concurrency=4,
                    use_threads=True,
                ),
            )
        except BaseException:
            process.kill()
            process.wait()
            _delete_latest_object(client, bucket=bucket, key=key)
            raise
        finally:
            process.stdout.close()
        return_code = process.wait()
        if return_code != 0:
            _delete_latest_object(client, bucket=bucket, key=key)
            stderr.seek(0)
            detail = stderr.read(4096).decode("utf-8", errors="replace").strip()
            raise RuntimeError(
                f"backup command failed with status {return_code}: {detail}"
            )
    head = client.head_object(Bucket=bucket, Key=key)
    version_id = str(head.get("VersionId") or "")
    if not version_id:
        _delete_latest_object(client, bucket=bucket, key=key)
        raise RuntimeError("S3 upload did not return an object version")
    if int(head.get("ContentLength") or -1) != reader.size:
        _delete_latest_object(client, bucket=bucket, key=key)
        raise RuntimeError("S3 upload size mismatch")
    return UploadedObject(
        uri=f"s3://{bucket}/{key}",
        version_id=version_id,
        sha256=reader.digest.hexdigest(),
        size=reader.size,
    )


def _upload_bytes(
    client: Any,
    *,
    bucket: str,
    key: str,
    content: bytes,
    content_type: str,
) -> UploadedObject:
    response = client.put_object(
        Bucket=bucket,
        Key=key,
        Body=content,
        ContentType=content_type,
    )
    version_id = str(response.get("VersionId") or "")
    if not version_id:
        head = client.head_object(Bucket=bucket, Key=key)
        version_id = str(head.get("VersionId") or "")
    if not version_id:
        raise RuntimeError("S3 upload did not return an object version")
    return UploadedObject(
        uri=f"s3://{bucket}/{key}",
        version_id=version_id,
        sha256=hashlib.sha256(content).hexdigest(),
        size=len(content),
    )


def _verify_small_object(
    client: Any, uploaded: UploadedObject, expected: bytes
) -> None:
    bucket, key = _parse_s3_uri(uploaded.uri)
    response = client.get_object(
        Bucket=bucket,
        Key=key,
        VersionId=uploaded.version_id,
    )
    body = response["Body"]
    try:
        actual = body.read()
    finally:
        body.close()
    if actual != expected:
        raise RuntimeError("S3 verification receipt readback mismatch")


def _delete_uploaded_object(client: Any, uploaded: UploadedObject) -> None:
    try:
        bucket, key = _parse_s3_uri(uploaded.uri)
        client.delete_object(
            Bucket=bucket,
            Key=key,
            VersionId=uploaded.version_id,
        )
    except Exception:
        pass


def _delete_latest_object(client: Any, *, bucket: str, key: str) -> None:
    try:
        head = client.head_object(Bucket=bucket, Key=key)
        version_id = str(head.get("VersionId") or "")
        arguments = {"Bucket": bucket, "Key": key}
        if version_id:
            arguments["VersionId"] = version_id
        client.delete_object(**arguments)
    except Exception:
        pass


def _parse_s3_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    return parsed.netloc, parsed.path.lstrip("/")


def _connection_args(database_url: str) -> tuple[list[str], dict[str, str], str]:
    normalized = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise SystemExit("maintenance backup requires PostgreSQL")
    database = parsed.path.lstrip("/")
    if not database:
        raise SystemExit("database name is missing")
    args: list[str] = []
    if parsed.hostname:
        args.extend(["--host", parsed.hostname])
    if parsed.port:
        args.extend(["--port", str(parsed.port)])
    if parsed.username:
        args.extend(["--username", unquote(parsed.username)])
    env = os.environ.copy()
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    return args, env, database


def _roles_command(
    pg_dumpall: str,
    *,
    database_url: str,
    connection_args: list[str],
    connection_env: dict[str, str],
    system_user: str,
) -> tuple[list[str], dict[str, str]]:
    if not system_user:
        return [pg_dumpall, *connection_args, "--roles-only"], connection_env
    if not re.fullmatch(r"[a-z_][a-z0-9_-]*", system_user):
        raise SystemExit("invalid roles system user")
    normalized = database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    parsed = urlparse(normalized)
    command = ["sudo", "-u", system_user, pg_dumpall, "--roles-only"]
    if parsed.port:
        command.extend(["--port", str(parsed.port)])
    return command, os.environ.copy()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="")
    destination = parser.add_mutually_exclusive_group(required=True)
    destination.add_argument("--backup-mount", default="")
    destination.add_argument("--s3-config", default="")
    parser.add_argument(
        "--verification-dir",
        default="/var/lib/shumeiko/maintenance-backups",
    )
    parser.add_argument("--postgres-data-path", default="/var/lib/postgresql")
    parser.add_argument("--source-data-path", default="/data")
    parser.add_argument(
        "--roles-system-user",
        default="",
        help="local OS user used for pg_dumpall --roles-only",
    )
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
