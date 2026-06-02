import os
from collections.abc import Generator
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.dependencies import CurrentMembership
from app.domains.sales.contact_service import SalesContactService

TEST_DATABASE_URL = os.getenv("LABBY_TEST_DATABASE_URL")
if not TEST_DATABASE_URL:
    pytest.skip("LABBY_TEST_DATABASE_URL not configured", allow_module_level=True)

pytestmark = pytest.mark.integration

TENANT_1 = UUID("22222222-2222-2222-2222-222222222222")
TENANT_2 = UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
USER_1 = UUID("11111111-1111-1111-1111-111111111111")
USER_2 = UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb")
MEMBERSHIP_1 = UUID("33333333-3333-3333-3333-333333333333")
MEMBERSHIP_2 = UUID("cccccccc-cccc-cccc-cccc-cccccccccccc")


@pytest.fixture(scope="session")
def migrated_engine():
    os.environ["LABBY_DATABASE_URL"] = TEST_DATABASE_URL
    get_settings.cache_clear()
    engine = create_engine(TEST_DATABASE_URL, future=True)
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA IF EXISTS public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
        conn.execute(text("GRANT ALL ON SCHEMA public TO public"))

    command.upgrade(Config("alembic.ini"), "head")
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(migrated_engine) -> Generator[Session, None, None]:
    with migrated_engine.begin() as conn:
        conn.execute(text("TRUNCATE tenants, users RESTART IDENTITY CASCADE"))

    session_factory = sessionmaker(
        bind=migrated_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )
    session = session_factory()
    seed_identity(session)
    try:
        yield session
    finally:
        session.rollback()
        session.close()


def seed_identity(session: Session) -> None:
    session.execute(
        text(
            """
            INSERT INTO users (id, nome, email_normalized, senha_hash)
            VALUES
                (:user_1, 'Admin One', 'admin1@example.com', 'hash'),
                (:user_2, 'Admin Two', 'admin2@example.com', 'hash')
            """
        ),
        {"user_1": USER_1, "user_2": USER_2},
    )
    session.execute(
        text(
            """
            INSERT INTO tenants (id, nome, slug)
            VALUES
                (:tenant_1, 'Tenant One', 'tenant-one'),
                (:tenant_2, 'Tenant Two', 'tenant-two')
            """
        ),
        {"tenant_1": TENANT_1, "tenant_2": TENANT_2},
    )
    session.execute(
        text(
            """
            INSERT INTO memberships (
                id, user_id, tenant_id, role, default_module, status
            )
            VALUES
                (:membership_1, :user_1, :tenant_1, 'admin', 'sales', 'active'),
                (:membership_2, :user_2, :tenant_2, 'admin', 'sales', 'active')
            """
        ),
        {
            "membership_1": MEMBERSHIP_1,
            "membership_2": MEMBERSHIP_2,
            "user_1": USER_1,
            "user_2": USER_2,
            "tenant_1": TENANT_1,
            "tenant_2": TENANT_2,
        },
    )
    session.execute(
        text(
            """
            INSERT INTO membership_modules (membership_id, module_key)
            VALUES (:membership_1, 'sales'), (:membership_2, 'sales')
            """
        ),
        {"membership_1": MEMBERSHIP_1, "membership_2": MEMBERSHIP_2},
    )
    session.commit()


def current_one() -> CurrentMembership:
    return CurrentMembership(
        user_id=USER_1,
        tenant_id=TENANT_1,
        membership_id=MEMBERSHIP_1,
        email="admin1@example.com",
        nome="Admin One",
        role="admin",
        modules=("sales",),
    )


def current_two() -> CurrentMembership:
    return CurrentMembership(
        user_id=USER_2,
        tenant_id=TENANT_2,
        membership_id=MEMBERSHIP_2,
        email="admin2@example.com",
        nome="Admin Two",
        role="admin",
        modules=("sales",),
    )


def count_contacts(session: Session, tenant_id: UUID) -> int:
    return session.execute(
        text("SELECT COUNT(*) FROM sales_contacts WHERE tenant_id = :tenant_id"),
        {"tenant_id": tenant_id},
    ).scalar_one()


def test_sales_contact_crud_hits_real_postgres(db_session: Session) -> None:
    service = SalesContactService(db_session)

    created = service.create_contact(
        current=current_one(),
        nome="Paula",
        telefone="(11) 99999-0000",
        email="PAULA@EXAMPLE.COM",
        grupo="Leads",
        tags=["vip"],
        notas="Contato quente",
        campos_custom={"empresa": "ACME"},
    )

    assert created["telefone"] == "(11) 99999-0000"
    contact = service.get_contact(current=current_one(), contact_id=str(created["id"]))
    assert contact["email"] == "paula@example.com"
    assert contact["campos_custom"] == {"empresa": "ACME"}

    row = db_session.execute(
        text(
            """
            SELECT phone_normalized, created_by_membership_id, updated_by_membership_id
            FROM sales_contacts
            WHERE id = :contact_id
            """
        ),
        {"contact_id": created["id"]},
    ).mappings().one()
    assert row["phone_normalized"] == "5511999990000"
    assert row["created_by_membership_id"] == MEMBERSHIP_1
    assert row["updated_by_membership_id"] == MEMBERSHIP_1


def test_sales_contact_cross_tenant_lookup_returns_404_for_real_row(
    db_session: Session,
) -> None:
    service = SalesContactService(db_session)
    created = service.create_contact(
        current=current_two(),
        nome="Contato Tenant Dois",
        telefone="(21) 99999-0000",
    )

    with pytest.raises(HTTPException) as exc:
        service.get_contact(current=current_one(), contact_id=str(created["id"]))

    assert exc.value.status_code == 404


def test_sales_contact_unique_index_blocks_same_normalized_phone(
    db_session: Session,
) -> None:
    service = SalesContactService(db_session)
    service.create_contact(
        current=current_one(),
        nome="Paula",
        telefone="(11) 99999-0000",
    )

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO sales_contacts (
                    tenant_id, name, phone, phone_normalized, created_by_membership_id,
                    updated_by_membership_id
                )
                VALUES (
                    :tenant_id, 'Duplicado', '11999990000', '5511999990000',
                    :membership_id, :membership_id
                )
                """
            ),
            {"tenant_id": TENANT_1, "membership_id": MEMBERSHIP_1},
        )
        db_session.commit()
    db_session.rollback()


def test_sales_contact_batch_skip_is_atomic_and_tolerates_bad_rows(
    db_session: Session,
) -> None:
    service = SalesContactService(db_session)

    result = service.batch_import_contacts(
        current=current_one(),
        contacts=[
            {"nome": "Primeiro", "telefone": "(11) 99999-0000"},
            {"nome": "Mesmo telefone", "telefone": "11999990000"},
            {"nome": "Nome invalido" * 30, "telefone": "(11) 99998-0000"},
            {"nome": "Segundo", "telefone": "(11) 99997-0000"},
            {"nome": "Sem telefone", "telefone": ""},
        ],
        on_duplicate="skip",
    )

    assert result["importados"] == 2
    assert result["duplicados"] == 1
    assert result["erros"] == 2
    assert result["sem_telefone"] == 1
    assert count_contacts(db_session, TENANT_1) == 2


def test_sales_contact_batch_update_uses_conflict_target(
    db_session: Session,
) -> None:
    service = SalesContactService(db_session)

    result = service.batch_import_contacts(
        current=current_one(),
        contacts=[
            {"nome": "Primeiro", "telefone": "(11) 99999-0000", "campos_custom": {"a": 1}},
            {"nome": "Atualizado", "telefone": "11999990000", "campos_custom": {"b": 2}},
        ],
        on_duplicate="update",
    )

    assert result["importados"] == 2
    assert result["duplicados"] == 0
    assert count_contacts(db_session, TENANT_1) == 1
    row = db_session.execute(
        text("SELECT name, custom_fields FROM sales_contacts WHERE tenant_id = :tenant_id"),
        {"tenant_id": TENANT_1},
    ).mappings().one()
    assert row["name"] == "Atualizado"
    assert row["custom_fields"] == {"a": 1, "b": 2}
