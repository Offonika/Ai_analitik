"""Wildberries unit economics Excel MVP."""

from wb_unit_economics.calculation import build_unit_economics_report
from wb_unit_economics.contracts import (
    AccountOrgMapping,
    MappingStatus,
    OnecUnfCostSnapshot,
    SalesModel,
    SkuMapping,
    TaxProfile,
    UnitEconomicsReport,
    VatMode,
    WbApiSnapshot,
)

__all__ = [
    "AccountOrgMapping",
    "MappingStatus",
    "OnecUnfCostSnapshot",
    "SalesModel",
    "SkuMapping",
    "TaxProfile",
    "UnitEconomicsReport",
    "VatMode",
    "WbApiSnapshot",
    "build_unit_economics_report",
]
