from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from scripts.prepare_test_database import _safe_current_source

ROOT = Path(__file__).resolve().parents[1]


def _read_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, value = line.split("=", 1)
        values[key] = value.strip().strip('"')
    return values


def test_runtime_env_generator_removes_production_secrets_from_test(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.env"
    production = tmp_path / "production.env"
    test = tmp_path / "test.env"
    source.write_text(
        "\n".join(
            (
                'SHUMEYKO_DATABASE_URL="postgresql+psycopg://app:db-secret@db/prod"',
                'SHUMEYKO_SESSION_SECRET="session-secret"',
                'SHUMEYKO_BOOTSTRAP_PASSWORD="bootstrap-secret"',
                'SHUMEYKO_INTEGRATION_SECRET_KEY="integration-secret"',
                'SHUMEYKO_OPENAI_API_KEY="openai-secret"',
            )
        )
        + "\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        (
            sys.executable,
            str(ROOT / "scripts/create_runtime_env_files.py"),
            "--source",
            str(source),
            "--production-output",
            str(production),
            "--test-output",
            str(test),
            "--apply",
        ),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    production_values = _read_env(production)
    test_values = _read_env(test)
    assert production_values["SHUMEYKO_BOOTSTRAP_PASSWORD"] == "bootstrap-secret"
    assert test_values["SHUMEYKO_BOOTSTRAP_PASSWORD"] == ""
    assert test_values["SHUMEYKO_INTEGRATION_SECRET_KEY"] == ""
    assert test_values["SHUMEYKO_OPENAI_API_KEY"] == ""
    assert test_values["ONEC_ODATA_PASSWORD"] == ""
    assert test_values["SHUMEYKO_EXTERNAL_INTEGRATIONS_ENABLED"] == "false"
    assert test_values["SHUMEYKO_CLIENT_LOGIN_ENABLED"] == "false"
    assert test_values["SHUMEYKO_DATABASE_URL"].endswith(
        "/shumeyko_web_cabinet_test"
    )
    assert test_values["SHUMEYKO_SESSION_SECRET"] != "session-secret"
    assert production.stat().st_mode & 0o777 == 0o600
    assert test.stat().st_mode & 0o777 == 0o600


def test_runtime_env_generator_accepts_separate_test_database_role(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.env"
    production = tmp_path / "production.env"
    test = tmp_path / "test.env"
    source.write_text(
        'SHUMEYKO_DATABASE_URL="postgresql+psycopg://prod-app:placeholder@db/prod"\n',
        encoding="utf-8",
    )

    result = subprocess.run(
        (
            sys.executable,
            str(ROOT / "scripts/create_runtime_env_files.py"),
            "--source",
            str(source),
            "--production-output",
            str(production),
            "--test-output",
            str(test),
            "--apply",
        ),
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "SHUMEYKO_TEST_DATABASE_URL": (
                "postgresql+psycopg://test-app:placeholder@db/"
                "shumeyko_web_cabinet_test"
            ),
        },
    )

    assert result.returncode == 0, result.stderr
    assert "placeholder" not in result.stdout
    test_values = _read_env(test)
    assert test_values["SHUMEYKO_DATABASE_URL"].startswith(
        "postgresql+psycopg://test-app:"
    )
    assert test_values["SHUMEYKO_DATABASE_URL"].endswith(
        "/shumeyko_web_cabinet_test"
    )


def test_test_database_sanitizer_reuses_safe_test_artifact(
    tmp_path: Path,
) -> None:
    production_root = tmp_path / "production"
    test_root = tmp_path / "test"
    production_root.mkdir()
    test_root.mkdir()
    test_artifact = test_root / "report" / "workbook-report.xlsx"
    test_artifact.parent.mkdir()
    test_artifact.write_bytes(b"safe-test-artifact")

    source, already_in_test = _safe_current_source(
        str(test_artifact),
        production_root,
        test_root,
    )

    assert source == test_artifact.resolve()
    assert already_in_test is True
