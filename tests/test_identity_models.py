from sqlalchemy.orm import configure_mappers

from app.models import Base


def test_identity_metadata_tables_are_registered() -> None:
    assert {
        "users",
        "tenants",
        "memberships",
        "membership_modules",
        "team_invites",
    }.issubset(Base.metadata.tables)


def test_sqlalchemy_mappers_configure_cleanly() -> None:
    configure_mappers()

