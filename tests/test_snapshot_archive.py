from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest

from scripts.archive_source_refresh_snapshots import _parse_args
from wb_unit_economics.snapshot_archive import (
    SnapshotArchiveError,
    archive_snapshot,
    restore_snapshot,
)


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
        self.sequence = 0

    def get_bucket_versioning(self, **_: Any) -> dict[str, str]:
        return {"Status": "Enabled"}

    def upload_file(
        self, filename: str, bucket: str, key: str, ExtraArgs: dict[str, Any]
    ) -> None:
        self._put(bucket, key, Path(filename).read_bytes(), ExtraArgs["Metadata"])

    def put_object(self, **kwargs: Any) -> dict[str, str]:
        body = kwargs["Body"]
        if hasattr(body, "read"):
            body = body.read()
        version = self._put(
            kwargs["Bucket"], kwargs["Key"], bytes(body), kwargs.get("Metadata", {})
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
