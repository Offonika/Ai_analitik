from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts.archive_source_refresh_snapshots import _parse_args
from scripts.configure_source_refresh_s3_lifecycle import desired_rule
from wb_unit_economics.report_archive import (
    archive_report_to_s3,
    restore_archived_report,
    select_archive_candidates,
)
from wb_unit_economics.snapshot_archive import (
    SnapshotArchiveError,
    archive_snapshot,
    restore_snapshot,
)
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import ReportRun


def test_archive_full_readback_evict_and_restore(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    snapshot = source_root / "full-20260701-010101"
    (snapshot / "nested").mkdir(parents=True)
    (snapshot / "manifest.json").write_text('{"ok":true}', encoding="utf-8")
    (snapshot / "nested/data.bin").write_bytes(b"payload")
    config = _config(tmp_path)
    client = FakeS3()
    pre_evict_checks: list[bool] = []

    receipt = archive_snapshot(
        snapshot,
        source_root=source_root,
        receipt_dir=tmp_path / "receipts",
        verify_dir=tmp_path / "verify",
        s3_config_path=config,
        evict=True,
        pre_evict_check=lambda: pre_evict_checks.append(True),
        s3_client=client,
    )

    assert not snapshot.exists()
    assert pre_evict_checks == [True]
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["fullReadbackVerified"] is True
    assert all(item["versionId"] for item in payload["files"])
    assert "archive-class=raw-source" in client.tags.values()
    assert "archive-class=manifest" in client.tags.values()

    restored = restore_snapshot(
        receipt,
        source_root=source_root,
        s3_config_path=config,
        s3_client=client,
    )
    assert (restored / "manifest.json").read_text(encoding="utf-8") == '{"ok":true}'
    assert (restored / "nested/data.bin").read_bytes() == b"payload"


def test_archive_accepts_zero_byte_file(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    snapshot = source_root / "daily-20260702-020202"
    snapshot.mkdir(parents=True)
    (snapshot / "empty.marker").write_bytes(b"")
    (snapshot / "payload.json").write_text('{"ok":true}', encoding="utf-8")
    config = _config(tmp_path)
    client = FakeS3()

    receipt = archive_snapshot(
        snapshot,
        source_root=source_root,
        receipt_dir=tmp_path / "receipts",
        verify_dir=tmp_path / "verify",
        s3_config_path=config,
        evict=True,
        s3_client=client,
    )

    assert not snapshot.exists()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    sizes = {item["path"]: item["size"] for item in payload["files"]}
    assert sizes["empty.marker"] == 0

    restored = restore_snapshot(
        receipt,
        source_root=source_root,
        s3_config_path=config,
        s3_client=client,
    )
    assert (restored / "empty.marker").read_bytes() == b""


def test_archive_rejects_symlink(tmp_path: Path) -> None:
    source_root = tmp_path / "source"
    snapshot = source_root / "snapshot"
    snapshot.mkdir(parents=True)
    (snapshot / "real").write_text("x", encoding="utf-8")
    (snapshot / "link").symlink_to(snapshot / "real")

    with pytest.raises(SnapshotArchiveError, match="symlink"):
        archive_snapshot(
            snapshot,
            source_root=source_root,
            receipt_dir=tmp_path / "receipts",
            verify_dir=tmp_path / "verify",
            s3_config_path=_config(tmp_path),
            s3_client=FakeS3(),
        )


def test_archive_eligible_cli_has_no_explicit_snapshot_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sys.argv", ["archive", "archive-eligible", "--max-snapshots", "2"]
    )

    args = _parse_args()

    assert args.command == "archive-eligible"
    assert args.max_snapshots == 2
    assert not hasattr(args, "snapshot")


def test_raw_lifecycle_is_tag_scoped_and_keeps_manifests() -> None:
    rule = desired_rule()

    assert rule["Filter"] == {
        "Tag": {"Key": "archive-class", "Value": "raw-source"}
    }
    assert rule["Expiration"] == {"Days": 1095}
    assert rule["NoncurrentVersionExpiration"] == {"NoncurrentDays": 1095}


def test_superseded_report_archive_readback_and_restore_is_non_current(
    tmp_path: Path,
) -> None:
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    session_factory = make_session_factory(engine)
    client = FakeS3()
    config = _config(tmp_path)
    with session_factory() as db:
        old = repository.save_report_marts(
            db,
            _report_payload("Старая ревизия"),
            tenant_id="tenant",
            tenant_name="Tenant",
            report_id="report-old",
            publication_status="superseded",
            publish=False,
            source_snapshot_set_id="snapshot-old",
        )
        current = repository.save_report_marts(
            db,
            _report_payload("Текущая ревизия"),
            tenant_id="tenant",
            tenant_name="Tenant",
            report_id="report-current",
            publication_status="draft",
            publish=False,
            source_snapshot_set_id="snapshot-current",
        )
        old.is_current = False
        current.publication_status = "published"
        current.is_current = True
        old.created_at = datetime.now(UTC) - timedelta(days=400)
        db.commit()

        candidates = select_archive_candidates(
            db,
            cutoff=datetime.now(UTC) - timedelta(days=365),
        )
        assert [item.id for item in candidates] == [old.id]

        record = archive_report_to_s3(
            db,
            old,
            s3_config_path=config,
            s3_client=client,
        )
        db.commit()
        restored = restore_archived_report(
            db,
            record,
            s3_config_path=config,
            s3_client=client,
        )
        db.commit()

        stored_current = db.get(ReportRun, current.id)
        stored_old = db.get(ReportRun, old.id)

    assert record.status == "verified"
    assert record.s3_version_id
    assert record.restored_at is not None
    assert stored_current is not None and stored_current.is_current is True
    assert stored_old is not None and stored_old.publication_status == "superseded"
    assert restored.publication_status == "archived_read_only"
    assert restored.is_current is False
    assert restored.lineage_type == "restored_report_archive_v1"


def _report_payload(product: str) -> dict[str, Any]:
    return {
        "meta": {
            "client": "Client",
            "clientId": "client",
            "period": "01.01.2025 - 31.01.2025",
            "methodologyVersion": "archive-test-v1",
            "source": "DB report marts",
        },
        "options": {},
        "monthly": [],
        "expenses": [],
        "unitRows": [
            {
                "id": f"row-{product}",
                "product": product,
                "week": "2025-01-06",
                "month": "Январь 2025",
                "organization": "Organization",
                "cabinet": "Cabinet",
                "articleWb": "WB-1",
                "article1c": "1C-1",
                "sales": 1,
                "returns": 0,
                "revenue": 100,
                "cost": 20,
                "profitBeforeTax": 50,
                "profit": 45,
                "status": "ОК",
            }
        ],
        "returns": [],
        "lostSales": [],
        "reconciliationMonthly": [],
        "documentReconciliation": [],
    }


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "s3.json"
    path.write_text(
        json.dumps(
            {
                "endpoint_url": "https://s3.example.test",
                "region": "test-1",
                "bucket": "snapshots",
                "access_key": "test",
                "secret_key": "test",
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str, str], tuple[bytes, dict[str, str]]] = {}
        self.latest: dict[tuple[str, str], str] = {}
        self.tags: dict[tuple[str, str, str], str] = {}
        self.sequence = 0

    def get_bucket_versioning(self, **_: Any) -> dict[str, str]:
        return {"Status": "Enabled"}

    def upload_file(
        self, filename: str, bucket: str, key: str, ExtraArgs: dict[str, Any]
    ) -> None:
        version = self._put(
            bucket,
            key,
            Path(filename).read_bytes(),
            ExtraArgs["Metadata"],
        )
        self.tags[(bucket, key, version)] = str(ExtraArgs.get("Tagging") or "")

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        body = kwargs["Body"]
        if hasattr(body, "read"):
            body = body.read()
        version = self._put(
            kwargs["Bucket"], kwargs["Key"], bytes(body), kwargs.get("Metadata", {})
        )
        self.tags[(kwargs["Bucket"], kwargs["Key"], version)] = str(
            kwargs.get("Tagging") or ""
        )
        return {"VersionId": version}

    def head_object(self, **kwargs: Any) -> dict[str, Any]:
        version = (
            kwargs.get("VersionId") or self.latest[(kwargs["Bucket"], kwargs["Key"])]
        )
        data, metadata = self.objects[(kwargs["Bucket"], kwargs["Key"], version)]
        return {"VersionId": version, "ContentLength": len(data), "Metadata": metadata}

    def get_object(self, **kwargs: Any) -> dict[str, Any]:
        data, _ = self.objects[(kwargs["Bucket"], kwargs["Key"], kwargs["VersionId"])]
        return {"Body": io.BytesIO(data)}

    def download_file(
        self, bucket: str, key: str, filename: str, ExtraArgs: dict[str, str]
    ) -> None:
        data, _ = self.objects[(bucket, key, ExtraArgs["VersionId"])]
        Path(filename).write_bytes(data)

    def _put(self, bucket: str, key: str, data: bytes, metadata: dict[str, str]) -> str:
        self.sequence += 1
        version = f"v{self.sequence}"
        self.objects[(bucket, key, version)] = (data, metadata)
        self.latest[(bucket, key)] = version
        return version
