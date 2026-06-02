from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi import HTTPException

from app.core.dependencies import CurrentMembership
from app.domains.sales.contact_service import SalesContactService, normalize_phone


class FakeResult:
    def __init__(self, *, row=None, rows=None, scalar=None) -> None:
        self.row = row
        self.rows = rows or []
        self.scalar = scalar

    def mappings(self):
        return self

    def first(self):
        return self.row

    def all(self):
        return self.rows

    def scalar_one(self):
        return self.scalar


class FakeSession:
    def __init__(self, results: list[FakeResult]) -> None:
        self.results = results
        self.calls = []
        self.commits = 0
        self.rollbacks = 0

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return self.results.pop(0)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def begin_nested(self):
        return FakeNestedTransaction()


class FakeNestedTransaction:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False


def make_current(role: str = "admin", modules: tuple[str, ...] = ("sales",)):
    return CurrentMembership(
        user_id=UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id=UUID("22222222-2222-2222-2222-222222222222"),
        membership_id=UUID("33333333-3333-3333-3333-333333333333"),
        email="admin@example.com",
        nome="Admin",
        role=role,
        modules=modules,
    )


def make_contact_row(**overrides):
    now = datetime(2026, 6, 1, tzinfo=UTC)
    row = {
        "id": UUID("44444444-4444-4444-4444-444444444444"),
        "tenant_id": UUID("22222222-2222-2222-2222-222222222222"),
        "name": "Paula",
        "phone": "(11) 99999-0000",
        "phone_normalized": "5511999990000",
        "email_normalized": "paula@example.com",
        "group_name": "Leads",
        "tags": ["vip"],
        "notes": "Contato quente",
        "custom_fields": {"empresa": "ACME"},
        "status": "active",
        "optout": False,
        "total_messages_sent": 0,
        "total_messages_received": 0,
        "last_interaction_at": None,
        "created_at": now,
        "updated_at": now,
    }
    row.update(overrides)
    return row


def test_normalize_phone_uses_brazilian_ddi_when_missing() -> None:
    assert normalize_phone("(11) 99999-0000") == "5511999990000"
    assert normalize_phone("+55 11 99999-0000") == "5511999990000"
    assert normalize_phone("") is None


def test_admin_without_sales_module_is_blocked() -> None:
    service = SalesContactService(db=None)

    with pytest.raises(HTTPException) as exc:
        service._assert_sales_access(make_current(modules=("social_media",)))

    assert exc.value.status_code == 403


def test_list_contacts_filters_by_tenant_and_paginates() -> None:
    db = FakeSession(
        [
            FakeResult(scalar=1),
            FakeResult(rows=[make_contact_row()]),
        ]
    )
    service = SalesContactService(db)

    result = service.list_contacts(
        current=make_current(),
        search="paula",
        grupo="Leads",
        tag="vip",
        page=2,
        per_page=10,
    )

    assert result["total"] == 1
    assert result["contacts"][0]["nome"] == "Paula"
    assert db.calls[0][1]["tenant_id"] == "22222222-2222-2222-2222-222222222222"
    assert db.calls[1][1]["offset"] == 10
    assert "tenant_id = :tenant_id" in db.calls[0][0]
    assert "tags @> CAST(:tag AS jsonb)" in db.calls[0][0]


def test_create_contact_normalizes_phone_email_and_records_actor() -> None:
    db = FakeSession(
        [
            FakeResult(row=None),
            FakeResult(row=make_contact_row()),
        ]
    )
    service = SalesContactService(db)

    result = service.create_contact(
        current=make_current(),
        nome=" Paula ",
        telefone="(11) 99999-0000",
        email="PAULA@EXAMPLE.COM",
        grupo="Leads",
        tags=["vip", "vip"],
        notas="Contato quente",
        campos_custom={"empresa": "ACME"},
    )

    assert result["id"] == UUID("44444444-4444-4444-4444-444444444444")
    insert_params = db.calls[1][1]
    assert insert_params["tenant_id"] == "22222222-2222-2222-2222-222222222222"
    assert insert_params["membership_id"] == "33333333-3333-3333-3333-333333333333"
    assert insert_params["phone_normalized"] == "5511999990000"
    assert insert_params["email_normalized"] == "paula@example.com"
    assert insert_params["tags"] == '["vip"]'
    assert db.commits == 1


def test_get_contact_rejects_cross_tenant_row() -> None:
    db = FakeSession([FakeResult(row=None)])
    service = SalesContactService(db)

    with pytest.raises(HTTPException) as exc:
        service.get_contact(
            current=make_current(),
            contact_id="44444444-4444-4444-4444-444444444444",
        )

    assert exc.value.status_code == 404
    assert "tenant_id = :tenant_id" in db.calls[0][0]
    assert db.calls[0][1]["tenant_id"] == "22222222-2222-2222-2222-222222222222"


def test_batch_import_is_idempotent_by_tenant_phone() -> None:
    db = FakeSession(
        [
            FakeResult(row={"inserted": True}),
            FakeResult(row=None),
        ]
    )
    service = SalesContactService(db)

    result = service.batch_import_contacts(
        current=make_current(),
        contacts=[
            {"nome": "Paula", "telefone": "(11) 99999-0000", "tags": "vip,lead"},
            {"nome": "Paula 2", "telefone": "(11) 99999-0000"},
            {"nome": "Sem telefone", "telefone": ""},
        ],
        on_duplicate="skip",
    )

    assert result["total_enviados"] == 3
    assert result["importados"] == 1
    assert result["duplicados"] == 1
    assert result["erros"] == 1
    assert result["sem_telefone"] == 1
    assert db.commits == 1
    assert "ON CONFLICT (tenant_id, phone_normalized)" in db.calls[0][0]
    assert "DO NOTHING" in db.calls[0][0]
