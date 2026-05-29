from uuid import UUID

import pytest
from fastapi import HTTPException

from app.core.dependencies import CurrentMembership
from app.domains.team.team_service import TeamService


def make_current(role: str = "admin", modules: tuple[str, ...] = ("social_media",)):
    return CurrentMembership(
        user_id=UUID("11111111-1111-1111-1111-111111111111"),
        tenant_id=UUID("22222222-2222-2222-2222-222222222222"),
        membership_id=UUID("33333333-3333-3333-3333-333333333333"),
        email="admin@example.com",
        nome="Admin",
        role=role,
        modules=modules,
    )


def test_admin_cannot_invite_module_they_do_not_have() -> None:
    service = TeamService(db=None, auth_service=None, email_service=None)

    with pytest.raises(HTTPException) as exc:
        service._validate_invite_access(
            current=make_current(role="admin", modules=("social_media",)),
            role="agent",
            module_keys=["sales"],
            default_module="sales",
        )

    assert exc.value.status_code == 403


def test_owner_can_invite_any_valid_module() -> None:
    service = TeamService(db=None, auth_service=None, email_service=None)

    access = service._validate_invite_access(
        current=make_current(role="owner", modules=("social_media",)),
        role="admin",
        module_keys=["sales"],
        default_module="sales",
    )

    assert access.modules == ("sales",)
