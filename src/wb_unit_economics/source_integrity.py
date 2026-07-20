from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class RawIntegrityError(ValueError):
    pass


@dataclass(frozen=True)
class RawIntegrityResult:
    manifest_sha256: str
    file_count: int
    row_count: int
    verified_at: datetime

    def as_payload(self) -> dict[str, object]:
        return {
            "status": "verified",
            "manifestSha256": self.manifest_sha256,
            "fileCount": self.file_count,
            "rowCount": self.row_count,
            "verifiedAt": self.verified_at.isoformat(),
        }


def verify_raw_directory(
    raw_path: Path,
    *,
    source_type: str,
    source_root: Path | None = None,
    collection_results: Sequence[Mapping[str, Any]] | None = None,
    collection_row_count: int | None = None,
    collection_snapshot_hash: str | None = None,
) -> RawIntegrityResult:
    try:
        resolved_raw = raw_path.resolve(strict=True)
    except OSError as exc:
        raise RawIntegrityError("raw directory is missing") from exc
    if not resolved_raw.is_dir():
        raise RawIntegrityError("raw path is not a directory")
    if source_root is not None:
        try:
            resolved_root = source_root.resolve(strict=True)
        except OSError as exc:
            raise RawIntegrityError("source root is missing") from exc
        if resolved_raw != resolved_root and not resolved_raw.is_relative_to(
            resolved_root
        ):
            raise RawIntegrityError("raw directory is outside source root")

    manifest_path = resolved_raw / "manifest.json"
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise RawIntegrityError("manifest is unreadable") from exc
    if not isinstance(manifest, dict) or not isinstance(manifest.get("results"), list):
        raise RawIntegrityError("manifest results must be a list")
    manifest_results = manifest["results"]
    if not all(isinstance(item, dict) for item in manifest_results):
        raise RawIntegrityError("manifest result must be an object")

    if collection_results is not None:
        if collection_snapshot_hash is None:
            raise RawIntegrityError("collection snapshot hash is missing")
        actual_snapshot_hash = canonical_payload_hash(list(collection_results))
        if actual_snapshot_hash != collection_snapshot_hash:
            raise RawIntegrityError("collection snapshot hash mismatch")
        if _normalized_results(manifest_results) != _normalized_results(
            list(collection_results)
        ):
            raise RawIntegrityError("manifest and collection results differ")

    manifest_outputs = _output_map(manifest_results)
    manifest_content_outputs = _content_output_map(manifest_results)
    if collection_results is not None:
        collection_outputs = _output_map(list(collection_results))
        collection_content_outputs = _content_output_map(list(collection_results))
        if set(manifest_outputs) != set(collection_outputs):
            raise RawIntegrityError("manifest output file set is incomplete")
        if manifest_content_outputs != collection_content_outputs:
            raise RawIntegrityError("manifest content hashes differ from collection")

    row_count = (
        _collection_data_row_count(collection_results)
        if collection_results is not None
        else sum(
            _result_int(item, "row_count", "rowCount", "flat_row_count")
            for item in manifest_results
        )
    )
    if collection_row_count is not None and row_count != int(collection_row_count):
        raise RawIntegrityError("manifest row count differs from collection")

    verified_files = 0
    for output_file, expected_hash in manifest_outputs.items():
        if Path(output_file).name != output_file:
            raise RawIntegrityError("manifest output path is unsafe")
        output_path = (resolved_raw / output_file).resolve(strict=False)
        if not output_path.is_relative_to(resolved_raw) or not output_path.is_file():
            raise RawIntegrityError("manifest output file is missing or unsafe")
        expected_content_hash = manifest_content_outputs.get(output_file)
        actual_hash = (
            hashlib.sha256(output_path.read_bytes()).hexdigest()
            if expected_content_hash
            else _payload_file_hash(output_path, source_type)
        )
        if actual_hash != (expected_content_hash or expected_hash):
            raise RawIntegrityError("raw payload hash mismatch")
        verified_files += 1
    if row_count > 0 and verified_files == 0:
        raise RawIntegrityError("non-empty collection has no raw files")

    return RawIntegrityResult(
        manifest_sha256=hashlib.sha256(manifest_bytes).hexdigest(),
        file_count=verified_files,
        row_count=row_count,
        verified_at=datetime.now(UTC),
    )


def _collection_data_row_count(
    results: Sequence[Mapping[str, Any]],
) -> int:
    """Count data rows while excluding asynchronous report control responses."""
    has_report_control = any(
        _result_text(item, "source_endpoint", "sourceEndpoint") == "/v1/report/info"
        for item in results
    )
    if has_report_control:
        return sum(
            _result_int(item, "row_count", "rowCount", "flat_row_count")
            for item in results
            if _result_text(item, "source_endpoint", "sourceEndpoint") == "report_file"
        )
    return sum(
        _result_int(item, "row_count", "rowCount", "flat_row_count") for item in results
    )


def canonical_payload_hash(payload: object) -> str:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _normalized_results(
    results: Sequence[Mapping[str, Any]],
) -> list[dict[str, object]]:
    normalized = []
    for item in results:
        normalized.append(
            {
                "seller": _result_text(item, "seller_account_id", "sellerAccountId"),
                "page": _result_int(item, "page_index", "pageIndex"),
                "rows": _result_int(
                    item,
                    "row_count",
                    "rowCount",
                    "flat_row_count",
                ),
                "statusCode": _result_int(item, "status_code", "statusCode"),
                "hash": _result_text(item, "raw_payload_hash", "rawPayloadHash"),
                "contentHash": _result_text(
                    item,
                    "raw_content_sha256",
                    "rawContentSha256",
                ),
                "output": _result_text(item, "output_file", "outputFile"),
                "flatHash": _result_text(
                    item,
                    "flat_payload_hash",
                    "flatPayloadHash",
                ),
                "flatOutput": _result_text(
                    item,
                    "flat_output_file",
                    "flatOutputFile",
                ),
            }
        )
    return normalized


def _output_map(results: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    outputs: dict[str, str] = {}
    for item in results:
        output_file = _result_text(item, "output_file", "outputFile")
        raw_hash = _result_text(item, "raw_payload_hash", "rawPayloadHash")
        if not output_file:
            if raw_hash:
                raise RawIntegrityError("result hash has no output file")
            continue
        if not raw_hash:
            raise RawIntegrityError("output file has no raw payload hash")
        if output_file in outputs:
            raise RawIntegrityError("duplicate output file in manifest")
        outputs[output_file] = raw_hash
        flat_output_file = _result_text(
            item,
            "flat_output_file",
            "flatOutputFile",
        )
        flat_payload_hash = _result_text(
            item,
            "flat_payload_hash",
            "flatPayloadHash",
        )
        if flat_output_file:
            if not flat_payload_hash:
                raise RawIntegrityError("flat output file has no payload hash")
            if flat_output_file in outputs:
                raise RawIntegrityError("duplicate flat output file in manifest")
            outputs[flat_output_file] = flat_payload_hash
        elif flat_payload_hash:
            raise RawIntegrityError("flat payload hash has no output file")
    return outputs


def _content_output_map(results: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    outputs: dict[str, str] = {}
    for item in results:
        output_file = _result_text(item, "output_file", "outputFile")
        content_hash = _result_text(
            item,
            "raw_content_sha256",
            "rawContentSha256",
        )
        if content_hash and not output_file:
            raise RawIntegrityError("content hash has no output file")
        if content_hash:
            if output_file in outputs:
                raise RawIntegrityError("duplicate content hash output file")
            outputs[output_file] = content_hash
    return outputs


def _payload_file_hash(path: Path, source_type: str) -> str:
    if path.suffix.lower() != ".json":
        return hashlib.sha256(path.read_bytes()).hexdigest()
    if source_type == "wb_finance_detail":
        return _canonical_json_list_file_hash(path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        raise RawIntegrityError("raw JSON is unreadable") from exc
    kwargs: dict[str, object] = {
        "ensure_ascii": False,
        "sort_keys": True,
        "default": str,
    }
    if not source_type.startswith("ozon_"):
        kwargs["separators"] = (",", ":")
    serialized = json.dumps(payload, **kwargs)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _canonical_json_list_file_hash(
    path: Path,
    *,
    chunk_size: int = 1024 * 1024,
) -> str:
    """Hash a JSON array canonically without retaining the full payload."""

    digest = hashlib.sha256()
    digest.update(b"[")
    first = True
    for item in iter_json_array(path, chunk_size=chunk_size):
        if not first:
            digest.update(b",")
        digest.update(
            json.dumps(
                item,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        )
        first = False
    digest.update(b"]")
    return digest.hexdigest()


def iter_json_array(
    path: Path,
    *,
    chunk_size: int = 1024 * 1024,
) -> Iterator[Any]:
    """Yield a top-level JSON array without materializing the whole file."""

    decoder = json.JSONDecoder()
    buffer = ""
    pos = 0
    seen_array_start = False
    with path.open("r", encoding="utf-8") as handle:
        while True:
            chunk = handle.read(chunk_size)
            eof = chunk == ""
            buffer += chunk
            while True:
                while pos < len(buffer) and buffer[pos].isspace():
                    pos += 1
                if not seen_array_start:
                    if pos >= len(buffer):
                        break
                    if buffer[pos] != "[":
                        raise RawIntegrityError("raw JSON must be a list")
                    seen_array_start = True
                    pos += 1
                    continue
                while pos < len(buffer) and buffer[pos].isspace():
                    pos += 1
                if pos >= len(buffer):
                    break
                if buffer[pos] == "]":
                    return
                if buffer[pos] == ",":
                    pos += 1
                    continue
                try:
                    item, next_pos = decoder.raw_decode(buffer, pos)
                except json.JSONDecodeError as exc:
                    if eof:
                        raise RawIntegrityError("raw JSON is unreadable") from exc
                    break
                yield item
                pos = next_pos
            if eof:
                if seen_array_start:
                    raise RawIntegrityError("raw JSON list is unterminated")
                raise RawIntegrityError("raw JSON file is empty")
            if pos > chunk_size:
                buffer = buffer[pos:]
                pos = 0


def _result_text(item: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if value is not None:
            return str(value).strip()
    return ""


def _result_int(item: Mapping[str, Any], *keys: str) -> int:
    for key in keys:
        value = item.get(key)
        if value is None or value == "":
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            raise RawIntegrityError(f"invalid integer field: {key}") from None
    return 0
