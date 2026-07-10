from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from wb_unit_economics.document_exports import markdown_sha256, render_markdown_docx
from wb_unit_economics.web import repository
from wb_unit_economics.web.models import (
    ReportArtifact,
    ReportDocumentReconciliationRow,
    ReportLostSalesRow,
    ReportRun,
    ReportUnitRow,
)

READY_STATUS = "ready"
SAFE_REPORT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


class AcceptancePackageError(ValueError):
    pass


@dataclass(frozen=True)
class AcceptancePackageArtifacts:
    output_dir: Path
    markdown_path: Path
    docx_path: Path
    manifest_path: Path


def build_client_acceptance_package(
    db: Session,
    report: ReportRun,
    *,
    output_dir: Path,
) -> AcceptancePackageArtifacts:
    _validate_report(report)
    summary = repository.report_summary_payload(
        db,
        report,
        include_staff_readiness=False,
    )
    readiness = summary.get("readiness") or {}
    readiness_status = str(readiness.get("status") or "")
    if readiness_status != READY_STATUS:
        raise AcceptancePackageError(
            "Report is not ready for client acceptance: "
            f"{readiness_status or 'missing_readiness'}"
        )

    manifest = build_acceptance_manifest(db, report, summary=summary)
    markdown = build_acceptance_markdown(manifest)
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "acceptance-package.md"
    docx_path = output_dir / "acceptance-package.docx"
    manifest_path = output_dir / "manifest.json"
    markdown_path.write_text(markdown, encoding="utf-8")
    render_markdown_docx(
        markdown,
        docx_path,
        branded=False,
        landscape=False,
        footer_text="Шумейко и Партнеры · Пакет приемки отчета",
        source_sha256=markdown_sha256(markdown),
    )
    manifest["packageFiles"] = [
        _package_file_record(markdown_path),
        _package_file_record(docx_path),
    ]
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return AcceptancePackageArtifacts(
        output_dir=output_dir,
        markdown_path=markdown_path,
        docx_path=docx_path,
        manifest_path=manifest_path,
    )


def build_acceptance_manifest(
    db: Session,
    report: ReportRun,
    *,
    summary: dict[str, Any],
) -> dict[str, Any]:
    meta = summary.get("meta") or {}
    readiness = summary.get("readiness") or {}
    artifacts = list(
        db.scalars(
            select(ReportArtifact)
            .where(
                ReportArtifact.report_run_id == report.id,
                ReportArtifact.status == "ready",
            )
            .order_by(ReportArtifact.artifact_type, ReportArtifact.id)
        )
    )
    return {
        "version": 1,
        "report": {
            "id": report.id,
            "tenantId": report.tenant_id,
            "clientId": report.client_id,
            "client": report.client_name,
            "title": report.title,
            "publicationStatus": report.publication_status,
            "isCurrent": bool(report.is_current),
            "reportPeriod": {
                "start": report.period_start.isoformat(),
                "end": report.period_end.isoformat(),
                "label": meta.get("reportPeriod") or meta.get("period") or "",
            },
            "sourceCoverage": {
                "start": meta.get("sourceCoverageStart") or None,
                "end": meta.get("sourceCoverageEnd") or None,
                "label": meta.get("sourceCoverage") or "",
            },
            "methodologyVersion": report.methodology_version,
            "lineageType": report.lineage_type,
            "generatedAt": (
                meta.get("generatedAtIso") or report.generated_at.isoformat()
            ),
        },
        "readiness": {
            "status": readiness.get("status") or "",
            "label": readiness.get("label") or "",
            "score": readiness.get("score"),
            "blockingReasonCount": len(readiness.get("blockingReasons") or []),
            "reviewReasonCount": len(readiness.get("reviewReasons") or []),
        },
        "counts": {
            "unitRows": _count(db, ReportUnitRow, report.id),
            "lostSalesRows": _count(db, ReportLostSalesRow, report.id),
            "documentReconciliationRows": _count(
                db,
                ReportDocumentReconciliationRow,
                report.id,
            ),
            "readyArtifacts": len(artifacts),
        },
        "artifacts": [
            {
                "type": artifact.artifact_type,
                "sha256": artifact.sha256,
                "byteSize": artifact.byte_size,
                "status": artifact.status,
            }
            for artifact in artifacts
        ],
    }


def build_acceptance_markdown(manifest: dict[str, Any]) -> str:
    report = manifest["report"]
    readiness = manifest["readiness"]
    counts = manifest["counts"]
    lines = [
        "# Пакет приемки отчета AI-аналитика",
        "",
        "Документ сформирован из опубликованной расчетной БД для конкретного "
        "`report_id`. Он не определяет текущий отчет и не содержит исходных строк "
        "или реквизитов подключений.",
        "",
        "## Ревизия",
        "",
        f"- Report ID (идентификатор отчета): `{report['id']}`",
        f"- Клиент: {report['client']}",
        f"- Период отчета: {report['reportPeriod']['label']}",
        f"- Покрытие источников: {report['sourceCoverage']['label']}",
        f"- Версия методики: `{report['methodologyVersion']}`",
        f"- Статус публикации: `{report['publicationStatus']}`",
        f"- Статус готовности: {readiness['label'] or readiness['status']}",
        f"- Оценка готовности: {readiness['score']}",
        "",
        "## Контрольные количества",
        "",
        f"- Строк юнит-экономики: {counts['unitRows']}",
        f"- Строк упущенных продаж: {counts['lostSalesRows']}",
        "- Строк сверки документов: "
        f"{counts['documentReconciliationRows']}",
        f"- Готовых артефактов: {counts['readyArtifacts']}",
        "",
        "## Артефакты",
        "",
        "| Тип | SHA-256 | Размер, байт | Статус |",
        "| --- | --- | ---: | --- |",
    ]
    for artifact in manifest["artifacts"]:
        lines.append(
            "| {type} | `{sha256}` | {byteSize} | {status} |".format(**artifact)
        )
    if not manifest["artifacts"]:
        lines.append("| нет |  | 0 | отсутствуют |")
    lines.extend(
        [
            "",
            "## Проверка перед передачей",
            "",
            "- Период отчета и покрытие источников совпадают с кабинетом.",
            "- Статус готовности — `ready` («готов»).",
            "- Версия методики совпадает с Excel и web-кабинетом.",
            "- Hash (контрольная сумма) каждого передаваемого артефакта совпадает "
            "с manifest (реестром пакета).",
            "- В пакете нет raw data (исходных данных), токенов, паролей и URL с "
            "учетными данными.",
            "",
        ]
    )
    return "\n".join(lines)


def _validate_report(report: ReportRun) -> None:
    if not SAFE_REPORT_ID_RE.fullmatch(report.id):
        raise AcceptancePackageError("Report id is not safe for an output directory")
    if report.publication_status != "published":
        raise AcceptancePackageError("Report is not published")
    if report.status != "final":
        raise AcceptancePackageError(f"Report status is not final: {report.status}")


def _count(db: Session, model: Any, report_id: str) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(model)
            .where(model.report_run_id == report_id)
        )
        or 0
    )


def _package_file_record(path: Path) -> dict[str, Any]:
    return {
        "name": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "byteSize": path.stat().st_size,
    }
