from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.api.v2.labby.auth import get_auth_service, set_refresh_cookie
from app.core.database import get_db
from app.core.dependencies import CurrentMembership, get_current_membership
from app.domains.identity.auth_service import AuthService
from app.domains.team.team_service import TeamService
from app.integrations.email import EmailService
from app.schemas.auth import AuthResponse
from app.schemas.team import (
    AcceptTeamInviteRequest,
    CreateTeamInviteRequest,
    InviteMutationResponse,
    PublicTeamInvite,
    TeamInvitesResponse,
)

router = APIRouter(prefix="/team", tags=["team"])


def get_team_service(
    db: Session = Depends(get_db),
    auth_service: AuthService = Depends(get_auth_service),
) -> TeamService:
    return TeamService(
        db=db,
        auth_service=auth_service,
        email_service=EmailService(),
    )


@router.get("/invites", response_model=TeamInvitesResponse)
def list_invites(
    status_filter: str | None = Query(default=None, alias="status"),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current: CurrentMembership = Depends(get_current_membership),
    service: TeamService = Depends(get_team_service),
) -> TeamInvitesResponse:
    return service.list_invites(
        current=current,
        status=status_filter,
        search=search,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/invites",
    response_model=InviteMutationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_invite(
    data: CreateTeamInviteRequest,
    current: CurrentMembership = Depends(get_current_membership),
    service: TeamService = Depends(get_team_service),
) -> InviteMutationResponse:
    invite, result = service.create_invite(
        current=current,
        nome=data.nome,
        email=str(data.email),
        role=data.role,
        module_keys=data.module_keys,
        default_module=data.default_module,
    )
    return InviteMutationResponse(
        invite=invite,
        email_sent=result.sent,
        email_error=result.error,
    )


@router.post("/invites/{invite_id}/resend", response_model=InviteMutationResponse)
def resend_invite(
    invite_id: str,
    current: CurrentMembership = Depends(get_current_membership),
    service: TeamService = Depends(get_team_service),
) -> InviteMutationResponse:
    invite, result = service.resend_invite(current=current, invite_id=invite_id)
    return InviteMutationResponse(
        invite=invite,
        email_sent=result.sent,
        email_error=result.error,
    )


@router.post("/invites/{invite_id}/revoke")
def revoke_invite(
    invite_id: str,
    current: CurrentMembership = Depends(get_current_membership),
    service: TeamService = Depends(get_team_service),
) -> dict:
    invite = service.revoke_invite(current=current, invite_id=invite_id)
    return {"invite": invite}


@router.get("/invites/accept/{token}", response_model=PublicTeamInvite)
def public_invite(
    token: str,
    service: TeamService = Depends(get_team_service),
) -> PublicTeamInvite:
    return service.public_invite(token=token)


@router.post("/invites/accept/{token}", response_model=AuthResponse)
def accept_invite(
    token: str,
    data: AcceptTeamInviteRequest,
    response: Response,
    service: TeamService = Depends(get_team_service),
) -> AuthResponse:
    auth_response, refresh_token = service.accept_invite(
        token=token,
        senha=data.senha,
        nome=data.nome,
    )
    set_refresh_cookie(response, refresh_token)
    return auth_response
