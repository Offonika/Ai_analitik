from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace

import pytest

from scripts.enqueue_accounting_report import _resolve_client_scope
from scripts.verify_month_close_canary import _accounting_baseline_matches


class _FakeDb:
    def __init__(self, clients: list[SimpleNamespace]) -> None:
        self.clients = clients

    def scalars(self, _statement: object) -> list[SimpleNamespace]:
        return self.clients

    def get(self, _model: object, client_id: str) -> SimpleNamespace | None:
        return next(
            (client for client in self.clients if client.id == client_id),
            None,
        )


def test_canary_scope_resolves_unique_client_match() -> None:
    db = _FakeDb(
        [
            SimpleNamespace(
                id="client-galustov",
                tenant_id="tenant-galustov",
                name="Галустов",
            ),
            SimpleNamespace(id="client-other", tenant_id="tenant-other", name="Другой"),
        ]
    )

    tenant_id, client_id = _resolve_client_scope(
        db,
        Namespace(client_match="галуст", tenant_id=None, client_id=None),
    )

    assert tenant_id == "tenant-galustov"
    assert client_id == "client-galustov"


def test_canary_scope_rejects_mismatched_explicit_tenant_and_client() -> None:
    db = _FakeDb(
        [
            SimpleNamespace(
                id="client-galustov",
                tenant_id="tenant-galustov",
                name="Галустов",
            )
        ]
    )

    with pytest.raises(SystemExit, match="tenant and client scope do not match"):
        _resolve_client_scope(
            db,
            Namespace(
                client_match=None,
                tenant_id="tenant-wrong",
                client_id="client-galustov",
            ),
        )


def test_canary_verifier_rejects_accounting_baseline_drift() -> None:
    args = Namespace(
        expected_report_accounts=33,
        expected_reference_accounts=40,
        expected_common_accounts=31,
        expected_exact_accounts=30,
        expected_mismatch_accounts=1,
        expected_report_only_accounts=2,
        expected_reference_only_accounts=9,
    )
    actual = {
        "report_accounts": 49,
        "reference_accounts": 40,
        "common_accounts": 29,
        "exact_accounts": 16,
        "mismatch_accounts": 13,
        "report_only_accounts": 20,
        "reference_only_accounts": 11,
    }

    assert _accounting_baseline_matches(args, actual) is False
