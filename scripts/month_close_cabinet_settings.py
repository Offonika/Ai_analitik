from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select

from wb_unit_economics.onec_odata import OnecODataSettings
from wb_unit_economics.web import integrations
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.models import Client, TenantIntegration
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import READY_INTEGRATION_STATUSES


@dataclass(frozen=True)
class CabinetOnecLookup:
    client_name: str = ""
    tenant_id: str = ""
    provider: str = "onec_readonly"
    database_url: str = ""


class CabinetOnecSettingsError(ValueError):
    pass


def load_onec_settings_from_cabinet(
    lookup: CabinetOnecLookup,
) -> OnecODataSettings:
    settings = _web_settings(lookup.database_url)
    tenant_id = _resolve_tenant_id(settings, lookup)
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        integration = db.scalar(
            select(TenantIntegration).where(
                TenantIntegration.tenant_id == tenant_id,
                TenantIntegration.provider == lookup.provider,
            )
        )
        if integration is None:
            raise CabinetOnecSettingsError("onec_integration_not_found")
        if integration.status not in READY_INTEGRATION_STATUSES:
            raise CabinetOnecSettingsError(
                f"onec_integration_not_runtime_ready:{integration.status}"
            )
        payload = integration.config_payload or {}
        if payload.get("storage") != "encrypted":
            storage = payload.get("storage", "hash_only")
            raise CabinetOnecSettingsError(
                f"onec_integration_storage_is_not_encrypted:{storage}"
            )
        try:
            secret = integrations.decrypt_secret(settings, payload)
            return integrations.onec_odata_settings_from_secret(secret)
        except integrations.IntegrationSecretError as exc:
            raise CabinetOnecSettingsError(str(exc)) from exc


def _resolve_tenant_id(settings: WebSettings, lookup: CabinetOnecLookup) -> str:
    if lookup.tenant_id.strip():
        return lookup.tenant_id.strip()
    client_name = lookup.client_name.strip()
    if not client_name:
        raise CabinetOnecSettingsError("client_name_or_tenant_id_required")
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    needle = client_name.casefold()
    with session_factory() as db:
        clients = [
            client
            for client in db.scalars(select(Client).order_by(Client.name))
            if needle in client.name.casefold()
        ]
    if not clients:
        raise CabinetOnecSettingsError("client_not_found")
    if len(clients) > 1:
        raise CabinetOnecSettingsError("client_name_is_ambiguous")
    return clients[0].tenant_id


def _web_settings(database_url: str) -> WebSettings:
    if database_url.strip():
        return WebSettings(_env_file=None, database_url=database_url.strip())
    return WebSettings(_env_file=None)
