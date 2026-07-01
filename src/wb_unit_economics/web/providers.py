from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderRole:
    id: str
    label: str


@dataclass(frozen=True)
class ProviderDefinition:
    provider_base: str
    label: str
    roles: tuple[ProviderRole, ...]
    default_role: str
    check_handler: str
    supports_multiple: bool = True
    read_only: bool = True

    @property
    def primary_provider_id(self) -> str:
        return self.provider_base


PROVIDER_DEFINITIONS: dict[str, ProviderDefinition] = {
    "wb_api": ProviderDefinition(
        provider_base="wb_api",
        label="Wildberries API",
        default_role="finance_reports",
        check_handler="wb_api",
        roles=(
            ProviderRole("finance_reports", "Финансовые отчеты"),
            ProviderRole("analytics_stocks", "Аналитика и остатки"),
            ProviderRole("content_cards", "Карточки товаров"),
            ProviderRole("full_readonly", "Полный read-only доступ"),
        ),
    ),
    "onec_readonly": ProviderDefinition(
        provider_base="onec_readonly",
        label="1С read-only",
        default_role="cost_documents",
        check_handler="onec_readonly",
        roles=(
            ProviderRole("cost_documents", "Себестоимость и документы"),
            ProviderRole("stocks_warehouses", "Остатки и склады"),
            ProviderRole("full_readonly", "Полный read-only доступ"),
        ),
    ),
}
PROVIDER_ORDER = tuple(PROVIDER_DEFINITIONS)


def provider_base(provider: str) -> str:
    return provider.strip().split(":", 1)[0]


def connection_key(provider: str) -> str:
    normalized = provider.strip()
    if ":" not in normalized:
        return "primary"
    return normalized.split(":", 1)[1]


def is_primary_provider(provider: str) -> bool:
    return ":" not in provider.strip()


def provider_definition(provider: str) -> ProviderDefinition:
    base = provider_base(provider)
    try:
        return PROVIDER_DEFINITIONS[base]
    except KeyError as exc:
        raise ValueError("invalid integration provider") from exc


def is_supported_provider(provider: str) -> bool:
    return provider_base(provider) in PROVIDER_DEFINITIONS


def provider_label(provider: str) -> str:
    return provider_definition(provider).label


def normalize_role(provider: str, connection_role: str) -> str:
    definition = provider_definition(provider)
    role = connection_role.strip().lower()
    allowed = {item.id for item in definition.roles}
    return role if role in allowed else definition.default_role


def validate_provider(provider: str) -> None:
    normalized = provider.strip()
    provider_definition(normalized)
    key = connection_key(normalized)
    if not is_primary_provider(normalized) and (
        not key or not all(ch.isalnum() or ch in {"_", "-"} for ch in key)
    ):
        raise ValueError("invalid integration provider")


def public_provider_metadata() -> list[dict[str, object]]:
    return [
        {
            "providerBase": item.provider_base,
            "label": item.label,
            "readOnly": item.read_only,
            "supportsMultiple": item.supports_multiple,
            "primaryProviderId": item.primary_provider_id,
            "roles": [
                {
                    "id": role.id,
                    "label": role.label,
                    "default": role.id == item.default_role,
                }
                for role in item.roles
            ],
        }
        for item in PROVIDER_DEFINITIONS.values()
    ]
