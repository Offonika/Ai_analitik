from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ScenarioMeta(StrictPayload):
    reportId: str
    tenantId: str
    clientId: str
    reportKind: str
    organizationId: str
    periodStart: str
    periodEnd: str
    methodologyVersion: str
    generatedAt: str
    publicationStatus: str
    sourceRefreshRunId: str = ""
    sourceSnapshotSetId: str = ""
    evidenceSha256: str = ""


class MonthCloseControlPayload(StrictPayload):
    contractVersion: str
    reportKind: Literal["month_close_control"]
    meta: ScenarioMeta
    sourceCoverage: list[dict[str, Any]] = Field(default_factory=list)
    controls: list[dict[str, Any]] = Field(default_factory=list)
    osvSummary: dict[str, Any] = Field(default_factory=dict)
    osvRows: list[dict[str, Any]] = Field(default_factory=list)
    taxSummary: dict[str, Any] = Field(default_factory=dict)
    ensSummary: dict[str, Any] = Field(default_factory=dict)
    vatSummary: dict[str, Any] = Field(default_factory=dict)
    bankSummary: dict[str, Any] = Field(default_factory=dict)
    manualOperationsSummary: dict[str, Any] = Field(default_factory=dict)
    confirmations: list[dict[str, Any]] = Field(default_factory=list)
    issues: list[dict[str, Any]] = Field(default_factory=list)
    businessRecommendation: Literal["review_required", "cannot_confirm"]
    accountantApproval: None = None


class TaxLoadPayload(StrictPayload):
    contractVersion: str
    reportKind: Literal["tax_load"]
    meta: ScenarioMeta
    ytdStart: str
    ytdEnd: str
    taxProfile: dict[str, Any] = Field(default_factory=dict)
    sourceCoverage: list[dict[str, Any]] = Field(default_factory=list)
    taxRows: list[dict[str, Any]] = Field(default_factory=list)
    vatSummary: dict[str, Any] = Field(default_factory=dict)
    vatBooks: dict[str, Any] = Field(default_factory=dict)
    ensSummary: dict[str, Any] = Field(default_factory=dict)
    paymentSchedule: list[dict[str, Any]] = Field(default_factory=list)
    usnDetail: dict[str, Any] = Field(default_factory=dict)
    taxLoadSummary: dict[str, Any]
    issues: list[dict[str, Any]] = Field(default_factory=list)
    businessStatus: Literal["preliminary", "accountant_review_required"]
    accountantApproval: None = None
