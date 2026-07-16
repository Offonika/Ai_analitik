from __future__ import annotations

from dataclasses import asdict, dataclass

MARKETPLACE_UNIT_ECONOMICS = "marketplace_unit_economics"
MONTH_CLOSE_CONTROL = "month_close_control"
TAX_LOAD = "tax_load"
ACCOUNTING_REPORT_KINDS = {MONTH_CLOSE_CONTROL, TAX_LOAD}


@dataclass(frozen=True)
class ReportKindDefinition:
    kind: str
    title: str
    period_granularity: str
    requires_organization: bool
    roles: tuple[str, ...]
    artifacts: tuple[str, ...]
    readiness_mode: str
    client_publication: bool

    def payload(self) -> dict[str, object]:
        payload = asdict(self)
        return {
            "kind": payload["kind"],
            "title": payload["title"],
            "periodGranularity": payload["period_granularity"],
            "requiresOrganization": payload["requires_organization"],
            "roles": list(payload["roles"]),
            "artifacts": list(payload["artifacts"]),
            "readinessMode": payload["readiness_mode"],
            "clientPublication": payload["client_publication"],
        }


REPORT_KIND_REGISTRY: dict[str, ReportKindDefinition] = {
    MARKETPLACE_UNIT_ECONOMICS: ReportKindDefinition(
        kind=MARKETPLACE_UNIT_ECONOMICS,
        title="Юнит-экономика",
        period_granularity="date_range",
        requires_organization=False,
        roles=("admin", "consultant", "client", "client_owner", "client_viewer"),
        artifacts=("web", "excel", "docx", "pdf", "html", "csv"),
        readiness_mode="enforced",
        client_publication=True,
    ),
    MONTH_CLOSE_CONTROL: ReportKindDefinition(
        kind=MONTH_CLOSE_CONTROL,
        title="Контроль закрытия месяца",
        period_granularity="calendar_month",
        requires_organization=True,
        roles=("admin", "consultant"),
        artifacts=("web", "excel"),
        readiness_mode="advisory",
        client_publication=False,
    ),
    TAX_LOAD: ReportKindDefinition(
        kind=TAX_LOAD,
        title="Налоговая нагрузка",
        period_granularity="calendar_month_ytd",
        requires_organization=True,
        roles=("admin", "consultant"),
        artifacts=("web", "excel"),
        readiness_mode="advisory",
        client_publication=False,
    ),
}


def require_report_kind(kind: str) -> ReportKindDefinition:
    try:
        return REPORT_KIND_REGISTRY[kind]
    except KeyError as exc:
        raise ValueError("unsupported report kind") from exc


def enabled_report_kind_set(value: str) -> set[str]:
    requested = {item.strip() for item in value.split(",") if item.strip()}
    return requested & REPORT_KIND_REGISTRY.keys()
