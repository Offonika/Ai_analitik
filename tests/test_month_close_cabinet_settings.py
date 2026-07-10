from __future__ import annotations

from pathlib import Path

from cryptography.fernet import Fernet

from scripts.month_close_cabinet_settings import (
    CabinetOnecLookup,
    CabinetOnecSettingsError,
    load_onec_settings_from_cabinet,
)
from wb_unit_economics.web import integrations, repository
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.settings import WebSettings


def test_load_onec_settings_from_encrypted_cabinet_integration(
    tmp_path: Path,
    monkeypatch,
) -> None:
    settings, user = _cabinet_context(tmp_path, client_name="Галустов")
    monkeypatch.setenv(
        "SHUMEYKO_INTEGRATION_SECRET_KEY",
        settings.integration_secret_key,
    )
    onec_secret = (
        '{"baseUrl":"https://onec.example/odata/standard.odata",'
        '"username":"readonly","password":"onec-secret","verifySsl":false}'
    )
    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        user = db.get(repository.User, user.id)
        repository.save_tenant_integration(
            db,
            user=user,
            tenant_id="tenant-galustov",
            provider="onec_readonly",
            secret=onec_secret,
            secret_storage=integrations.secret_storage_payload(
                settings,
                onec_secret,
            ).payload,
        )
        db.commit()

    result = load_onec_settings_from_cabinet(
        CabinetOnecLookup(client_name="галуст", database_url=settings.database_url)
    )

    assert result.base_url == "https://onec.example/odata/standard.odata"
    assert result.username == "readonly"
    assert result.password == "onec-secret"
    assert result.verify_ssl is False


def test_load_onec_settings_reports_missing_cabinet_client(tmp_path: Path) -> None:
    settings, _user = _cabinet_context(tmp_path, client_name="Шумейко")

    try:
        load_onec_settings_from_cabinet(
            CabinetOnecLookup(
                client_name="Галустов",
                database_url=settings.database_url,
            )
        )
    except CabinetOnecSettingsError as exc:
        assert str(exc) == "client_not_found"
    else:
        raise AssertionError("expected CabinetOnecSettingsError")


def _cabinet_context(
    tmp_path: Path,
    *,
    client_name: str,
) -> tuple[WebSettings, repository.User]:
    integration_key = Fernet.generate_key().decode("ascii")
    database_url = f"sqlite:///{tmp_path / 'web.sqlite3'}"
    engine = make_engine(database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        repository.ensure_tenant(db, tenant_id="tenant-galustov", name=client_name)
        repository.ensure_client_for_tenant(
            db,
            tenant_id="tenant-galustov",
            name=client_name,
        )
        user = repository.upsert_user(
            db,
            email="admin@example.com",
            password="secret",
            tenant_id="tenant-galustov",
            role="admin",
        )
        db.commit()
        user_id = user.id
    settings = WebSettings(
        _env_file=None,
        database_url=database_url,
        integration_secret_key=integration_key,
    )
    with session_factory() as db:
        user = db.get(repository.User, user_id)
    return settings, user
