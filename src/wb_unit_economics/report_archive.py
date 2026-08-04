from __future__ import annotations

import gzip
import hashlib
import json
import os
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from wb_unit_economics.maintenance_safety import (
    load_s3_backup_config,
    make_s3_client,
)
from wb_unit_economics.web import repository, security
from wb_unit_economics.web.models import (
    ReportArchiveRecord,
    ReportRun,
    SourceLoad,
)


class ReportArchiveError(RuntimeError):
    pass


def select_archive_candidates(
    db: Session,
    *,
    cutoff: datetime,
    tenant_id: str = "",
) -> list[ReportRun]:
    statement = (
        select(ReportRun)
        .outerjoin(
            ReportArchiveRecord,
            ReportArchiveRecord.report_run_id == ReportRun.id,
        )
        .where(
            ReportRun.publication_status == "superseded",
            ReportRun.is_current.is_(False),
            ReportRun.created_at < cutoff,
            ReportArchiveRecord.id.is_(None),
        )
        .order_by(ReportRun.created_at, ReportRun.id)
    )
    if tenant_id:
        statement = statement.where(ReportRun.tenant_id == tenant_id)
    return list(db.scalars(statement))


def archive_report_to_s3(
    db: Session,
    report: ReportRun,
    *,
    s3_config_path: Path,
    prefix: str = "report-revisions",
    s3_client: Any | None = None,
) -> ReportArchiveRecord:
    if report.is_current or report.publication_status != "superseded":
        raise ReportArchiveError("only non-current superseded reports can be archived")
    config = load_s3_backup_config(s3_config_path)
    client = s3_client or make_s3_client(config)
    try:
        versioning = client.get_bucket_versioning(Bucket=config.bucket).get("Status")
    except Exception as exc:
        raise ReportArchiveError("S3 bucket versioning check failed") from exc
    if versioning != "Enabled":
        raise ReportArchiveError("S3 bucket versioning must be enabled")

    payload = _archive_payload(db, report)
    with tempfile.TemporaryDirectory(prefix="report-archive-") as temp_dir:
        bundle = Path(temp_dir) / "report.json.gz"
        _write_bundle(bundle, payload)
        bundle_hash = _file_sha256(bundle)
        bundle_size = bundle.stat().st_size
        key = (
            f"{prefix.strip('/')}/{report.tenant_id}/{report.client_id}/"
            f"{report.id}/{bundle_hash}.json.gz"
        )
        try:
            client.upload_file(
                str(bundle),
                config.bucket,
                key,
                ExtraArgs={
                    "ContentType": "application/gzip",
                    "Metadata": {"sha256": bundle_hash},
                },
            )
            head = client.head_object(Bucket=config.bucket, Key=key)
        except Exception as exc:
            raise ReportArchiveError("report archive upload failed") from exc
        version_id = str(head.get("VersionId") or "")
        if not version_id or version_id == "null":
            raise ReportArchiveError("report archive has no immutable version id")
        if int(head.get("ContentLength", -1)) != bundle_size:
            raise ReportArchiveError("report archive size mismatch")
        if str((head.get("Metadata") or {}).get("sha256") or "") != bundle_hash:
            raise ReportArchiveError("report archive metadata hash mismatch")
        _verify_readback(
            client,
            bucket=config.bucket,
            key=key,
            version_id=version_id,
            expected_hash=bundle_hash,
            expected_size=bundle_size,
        )

    now = security.utcnow()
    record = ReportArchiveRecord(
        id=f"report_archive_{uuid.uuid4().hex}",
        tenant_id=report.tenant_id,
        client_id=report.client_id,
        report_run_id=report.id,
        status="verified",
        bundle_uri=f"s3://{config.bucket}/{key}",
        bundle_sha256=bundle_hash,
        bundle_byte_size=bundle_size,
        s3_version_id=version_id,
        methodology_version=report.methodology_version,
        source_lineage=payload["sourceLineage"],
        created_at=now,
        verified_at=now,
        restored_at=None,
    )
    db.add(record)
    db.flush()
    return record


def restore_archived_report(
    db: Session,
    record: ReportArchiveRecord,
    *,
    s3_config_path: Path,
    s3_client: Any | None = None,
) -> ReportRun:
    if record.status != "verified" or not record.s3_version_id:
        raise ReportArchiveError("report archive is not verified")
    config = load_s3_backup_config(s3_config_path)
    client = s3_client or make_s3_client(config)
    bucket, key = _s3_location(record.bundle_uri)
    if bucket != config.bucket:
        raise ReportArchiveError("report archive bucket differs from configuration")
    with tempfile.TemporaryDirectory(prefix="report-restore-") as temp_dir:
        bundle = Path(temp_dir) / "report.json.gz"
        try:
            client.download_file(
                bucket,
                key,
                str(bundle),
                ExtraArgs={"VersionId": record.s3_version_id},
            )
        except Exception as exc:
            raise ReportArchiveError("report archive download failed") from exc
        if (
            bundle.stat().st_size != record.bundle_byte_size
            or _file_sha256(bundle) != record.bundle_sha256
        ):
            raise ReportArchiveError("report archive readback hash mismatch")
        payload = _read_bundle(bundle)

    metadata = payload.get("report") or {}
    dashboard = payload.get("reportPayload")
    if not isinstance(dashboard, dict):
        raise ReportArchiveError("report archive payload is invalid")
    original_report_id = str(metadata.get("id") or record.report_run_id)
    restored = repository.save_report_marts(
        db,
        dashboard,
        tenant_id=record.tenant_id,
        tenant_name=str((dashboard.get("meta") or {}).get("client") or "Restored"),
        report_id=f"restored_{original_report_id}_{uuid.uuid4().hex[:12]}",
        publication_status="archived_read_only",
        publish=False,
        source_snapshot_set_id=str(metadata.get("sourceSnapshotSetId") or ""),
    )
    restored.is_current = False
    restored.lineage_type = "restored_report_archive_v1"
    restored.methodology_version = str(
        metadata.get("methodologyVersion") or record.methodology_version
    )
    record.restored_at = security.utcnow()
    db.flush()
    return restored


def _archive_payload(db: Session, report: ReportRun) -> dict[str, Any]:
    source_lineage = [
        {
            "sourceType": item.source_type,
            "status": item.status,
            "snapshotHash": item.snapshot_hash,
            "rowCount": item.row_count,
            "coverageStart": (
                item.coverage_start.isoformat() if item.coverage_start else None
            ),
            "coverageEnd": item.coverage_end.isoformat() if item.coverage_end else None,
            "lineageRole": item.lineage_role,
            "sourceRefreshRunId": item.source_refresh_run_id,
        }
        for item in db.scalars(
            select(SourceLoad)
            .where(SourceLoad.report_run_id == report.id)
            .order_by(SourceLoad.id)
        )
    ]
    return {
        "schemaVersion": 1,
        "createdAt": datetime.now(UTC).isoformat(),
        "report": {
            "id": report.id,
            "tenantId": report.tenant_id,
            "clientId": report.client_id,
            "reportKind": report.report_kind,
            "organizationId": report.organization_id,
            "methodologyVersion": report.methodology_version,
            "sourceSnapshotSetId": report.source_snapshot_set_id,
            "publicationStatus": report.publication_status,
        },
        "sourceLineage": source_lineage,
        "reportPayload": repository.report_full_payload(db, report),
    }


def _write_bundle(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
            zipped.write(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    default=str,
                ).encode("utf-8")
            )
        raw.flush()
        os.fsync(raw.fileno())
    os.replace(temporary, path)


def _read_bundle(path: Path) -> dict[str, Any]:
    try:
        with gzip.open(path, "rt", encoding="utf-8") as stream:
            payload = json.load(stream)
    except (OSError, TypeError, ValueError) as exc:
        raise ReportArchiveError("report archive bundle is unreadable") from exc
    if not isinstance(payload, dict) or payload.get("schemaVersion") != 1:
        raise ReportArchiveError("unsupported report archive schema")
    return payload


def _verify_readback(
    client: Any,
    *,
    bucket: str,
    key: str,
    version_id: str,
    expected_hash: str,
    expected_size: int,
) -> None:
    with tempfile.NamedTemporaryFile(prefix="report-readback-", delete=False) as temp:
        path = Path(temp.name)
    try:
        client.download_file(
            bucket,
            key,
            str(path),
            ExtraArgs={"VersionId": version_id},
        )
        if path.stat().st_size != expected_size or _file_sha256(path) != expected_hash:
            raise ReportArchiveError("report archive full readback mismatch")
    except ReportArchiveError:
        raise
    except Exception as exc:
        raise ReportArchiveError("report archive full readback failed") from exc
    finally:
        path.unlink(missing_ok=True)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _s3_location(uri: str) -> tuple[str, str]:
    if not uri.startswith("s3://"):
        raise ReportArchiveError("report archive URI is invalid")
    bucket, separator, key = uri[5:].partition("/")
    if not bucket or not separator or not key:
        raise ReportArchiveError("report archive URI is invalid")
    return bucket, key
