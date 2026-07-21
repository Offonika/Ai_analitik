from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

from wb_unit_economics.maintenance_safety import (
    load_s3_backup_config,
    make_s3_client,
)


class SnapshotArchiveError(RuntimeError):
    pass


def archive_snapshot(
    snapshot: Path,
    *,
    source_root: Path,
    receipt_dir: Path,
    verify_dir: Path,
    s3_config_path: Path,
    prefix: str = "source-refresh-snapshots",
    evict: bool = False,
    pre_evict_check: Callable[[], None] | None = None,
    s3_client: Any | None = None,
) -> Path:
    root = source_root.resolve(strict=True)
    target = snapshot.resolve(strict=True)
    if target.parent != root or target.is_symlink() or not target.is_dir():
        raise SnapshotArchiveError("snapshot must be a direct regular directory child")
    files = _inventory(target)
    if not files:
        raise SnapshotArchiveError("empty snapshot cannot be archived")

    config = load_s3_backup_config(s3_config_path)
    client = s3_client or make_s3_client(config)
    try:
        versioning = client.get_bucket_versioning(Bucket=config.bucket).get("Status")
    except Exception as exc:
        raise SnapshotArchiveError("S3 bucket versioning check failed") from exc
    if versioning != "Enabled":
        raise SnapshotArchiveError("S3 bucket versioning must be enabled")

    manifest_hash = hashlib.sha256(
        json.dumps(files, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    object_prefix = f"{prefix.strip('/')}/{target.name}/{manifest_hash}"
    archived: list[dict[str, object]] = []
    verification_root = verify_dir.resolve()
    verification_root.mkdir(parents=True, exist_ok=True)
    for record in files:
        relative = str(record["path"])
        local_path = target / relative
        key = f"{object_prefix}/files/{relative}"
        try:
            client.upload_file(
                str(local_path),
                config.bucket,
                key,
                ExtraArgs={"Metadata": {"sha256": str(record["sha256"])}},
            )
            head = client.head_object(Bucket=config.bucket, Key=key)
        except Exception as exc:
            raise SnapshotArchiveError(f"S3 upload failed for {relative}") from exc
        version_id = str(head.get("VersionId") or "")
        if not version_id or version_id == "null":
            raise SnapshotArchiveError("S3 object has no immutable version id")
        if int(head.get("ContentLength", -1)) != int(record["size"]):
            raise SnapshotArchiveError("S3 object size mismatch")
        if str((head.get("Metadata") or {}).get("sha256") or "") != record["sha256"]:
            raise SnapshotArchiveError("S3 object metadata checksum mismatch")
        _download_and_verify(
            client,
            bucket=config.bucket,
            key=key,
            version_id=version_id,
            expected_size=int(record["size"]),
            expected_sha256=str(record["sha256"]),
            verify_dir=verification_root,
        )
        archived.append({**record, "key": key, "versionId": version_id})

    payload: dict[str, object] = {
        "schemaVersion": 1,
        "snapshotName": target.name,
        "sourceRoot": str(root),
        "createdAt": datetime.now(UTC).isoformat(),
        "storageType": "s3",
        "endpoint": config.endpoint_url,
        "region": config.region,
        "bucket": config.bucket,
        "manifestSha256": manifest_hash,
        "files": archived,
        "fullReadbackVerified": True,
    }
    receipt_bytes = json.dumps(
        payload, ensure_ascii=False, indent=2, sort_keys=True
    ).encode()
    receipt_key = f"{object_prefix}/receipt.json"
    try:
        response = client.put_object(
            Bucket=config.bucket,
            Key=receipt_key,
            Body=receipt_bytes,
            ContentType="application/json",
            Metadata={"manifest-sha256": manifest_hash},
        )
        receipt_version = str(response.get("VersionId") or "")
        remote = client.get_object(
            Bucket=config.bucket, Key=receipt_key, VersionId=receipt_version
        )["Body"].read()
    except Exception as exc:
        raise SnapshotArchiveError("S3 receipt verification failed") from exc
    if not receipt_version or receipt_version == "null" or remote != receipt_bytes:
        raise SnapshotArchiveError("S3 receipt readback mismatch")
    payload["receiptKey"] = receipt_key
    payload["receiptVersionId"] = receipt_version

    receipt_root = receipt_dir.resolve()
    receipt_root.mkdir(parents=True, exist_ok=True)
    receipt_root.chmod(0o700)
    receipt = receipt_root / f"{target.name}.json"
    _atomic_json(receipt, payload)
    if evict:
        if pre_evict_check is not None:
            pre_evict_check()
        quarantine = root / f".archive-evict-{target.name}-{uuid.uuid4().hex}"
        os.replace(target, quarantine)
        shutil.rmtree(quarantine)
    return receipt


def restore_snapshot(
    receipt: Path,
    *,
    source_root: Path,
    s3_config_path: Path,
    s3_client: Any | None = None,
) -> Path:
    payload = _read_receipt(receipt)
    config = load_s3_backup_config(s3_config_path)
    if (
        payload.get("bucket") != config.bucket
        or payload.get("endpoint") != config.endpoint_url
    ):
        raise SnapshotArchiveError("archive receipt does not match S3 config")
    client = s3_client or make_s3_client(config)
    root = source_root.resolve(strict=True)
    name = str(payload.get("snapshotName") or "")
    if not name or Path(name).name != name:
        raise SnapshotArchiveError("invalid snapshot name in receipt")
    target = root / name
    if target.exists() or target.is_symlink():
        raise SnapshotArchiveError("restore target already exists")
    temp = root / f".archive-restore-{name}-{uuid.uuid4().hex}"
    temp.mkdir(mode=0o700)
    try:
        for record in _receipt_files(payload):
            relative = _safe_relative(str(record["path"]))
            destination = temp / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(
                config.bucket,
                str(record["key"]),
                str(destination),
                ExtraArgs={"VersionId": str(record["versionId"])},
            )
            if destination.stat().st_size != int(record["size"]):
                raise SnapshotArchiveError("restored file size mismatch")
            if _sha256(destination) != record["sha256"]:
                raise SnapshotArchiveError("restored file checksum mismatch")
        os.replace(temp, target)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return target


def _inventory(root: Path) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    for item in sorted(root.rglob("*")):
        if item.is_symlink():
            raise SnapshotArchiveError("snapshot symlinks are not archivable")
        if item.is_dir():
            continue
        if not item.is_file():
            raise SnapshotArchiveError("snapshot contains a non-regular entry")
        relative = item.relative_to(root).as_posix()
        records.append(
            {"path": relative, "size": item.stat().st_size, "sha256": _sha256(item)}
        )
    return records


def _download_and_verify(
    client: Any,
    *,
    bucket: str,
    key: str,
    version_id: str,
    expected_size: int,
    expected_sha256: str,
    verify_dir: Path,
) -> None:
    temp = verify_dir / f"verify-{uuid.uuid4().hex}"
    try:
        client.download_file(
            bucket, key, str(temp), ExtraArgs={"VersionId": version_id}
        )
        if temp.stat().st_size != expected_size or _sha256(temp) != expected_sha256:
            raise SnapshotArchiveError("S3 full readback checksum mismatch")
    finally:
        temp.unlink(missing_ok=True)


def _safe_relative(value: str) -> Path:
    pure = PurePosixPath(value)
    if (
        pure.is_absolute()
        or not pure.parts
        or any(part in {"", ".", ".."} for part in pure.parts)
    ):
        raise SnapshotArchiveError("unsafe archive path")
    return Path(*pure.parts)


def _receipt_files(payload: dict[str, object]) -> list[dict[str, object]]:
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise SnapshotArchiveError("archive receipt has no files")
    result: list[dict[str, object]] = []
    for item in files:
        if not isinstance(item, dict):
            raise SnapshotArchiveError("invalid archive receipt file")
        _safe_relative(str(item.get("path") or ""))
        if (
            not item.get("key")
            or not item.get("versionId")
            or not item.get("sha256")
            or "size" not in item
        ):
            raise SnapshotArchiveError("incomplete archive receipt file")
        result.append(item)
    return result


def _read_receipt(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.resolve(strict=True).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError) as exc:
        raise SnapshotArchiveError("archive receipt is unreadable") from exc
    if not isinstance(payload, dict) or payload.get("fullReadbackVerified") is not True:
        raise SnapshotArchiveError("archive receipt is not verified")
    return payload


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    temp.chmod(0o600)
    os.replace(temp, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
