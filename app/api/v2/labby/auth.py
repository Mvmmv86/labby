from typing import Annotated

from fastapi import APIRouter, Body, Cookie, Depends, HTTPException, Response, status
from redis import Redis
from sqlalchemy.orm import Session

from app.core.config import PROTECTED_ENVIRONMENTS, get_settings
from app.core.database import get_db
from app.core.dependencies import CurrentMembership, get_current_membership
from app.core.redis import get_redis
from app.domains.identity.auth_service import AuthService
from app.domains.identity.token_store import PasswordResetStore, RefreshTokenStore
from app.schemas.auth import (
    AuthResponse,
    ForgotPasswordRequest,
    LoginRequest,
    MeResponse,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    SwitchTenantRequest,
)

router = APIRouter(prefix="/auth", tags=["auth"])

REFRESH_COOKIE_NAME = "labby_refresh_token"


def get_auth_service(
    db: Session = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> AuthService:
    settings = get_settings()
    refresh_ttl = settings.refresh_token_expire_days * 24 * 60 * 60
    return AuthService(
        db=db,
        refresh_store=RefreshTokenStore(redis, ttl_seconds=refresh_ttl),
        password_reset_store=PasswordResetStore(redis),
    )


@router.post("/register", response_model=AuthResponse)
def register(
    data: RegisterRequest,
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    auth_response, refresh_token = service.register(
        nome=data.nome,
        email=str(data.email),
        senha=data.senha,
        empresa=data.empresa,
    )
    set_refresh_cookie(response, refresh_token)
    return auth_response


@router.post("/login", response_model=AuthResponse)
def login(
    data: LoginRequest,
    response: Response,
    service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    auth_response, refresh_token = service.login(email=str(data.email), senha=data.senha)
    set_refresh_cookie(response, refresh_token)
    return auth_response


@router.post("/refresh", response_model=AuthResponse)
def refresh(
    response: Response,
    data: Annotated[RefreshRequest | None, Body()] = None,
    refresh_cookie: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    refresh_token = refresh_cookie or (data.refresh_token if data else None)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token ausente")
    auth_response, new_refresh_token = service.refresh(refresh_token)
    set_refresh_cookie(response, new_refresh_token)
    return auth_response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    response: Response,
    data: Annotated[RefreshRequest | None, Body()] = None,
    refresh_cookie: str | None = Cookie(default=None, alias=REFRESH_COOKIE_NAME),
    service: AuthService = Depends(get_auth_service),
) -> None:
    refresh_token = refresh_cookie or (data.refresh_token if data else None)
    service.logout(refresh_token)
    clear_refresh_cookie(response)


@router.get("/me", response_model=MeResponse)
def me(
    current: CurrentMembership = Depends(get_current_membership),
    service: AuthService = Depends(get_auth_service),
) -> MeResponse:
    return service.me(str(current.membership_id))


@router.post("/switch-tenant", response_model=AuthResponse)
def switch_tenant(
    data: SwitchTenantRequest,
    response: Response,
    current: CurrentMembership = Depends(get_current_membership),
    service: AuthService = Depends(get_auth_service),
) -> AuthResponse:
    auth_response, refresh_token = service.switch_tenant(
        user_id=str(current.user_id),
        membership_id=data.membership_id,
    )
    set_refresh_cookie(response, refresh_token)
    return auth_response


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
def forgot_password(
    data: ForgotPasswordRequest,
    service: AuthService = Depends(get_auth_service),
) -> None:
    service.forgot_password(email=str(data.email))


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(
    data: ResetPasswordRequest,
    service: AuthService = Depends(get_auth_service),
) -> None:
    service.reset_password(token=data.token, senha=data.senha)


def set_refresh_cookie(response: Response, token: str) -> None:
    settings = get_settings()
    environment = settings.environment.lower()
    secure = environment in PROTECTED_ENVIRONMENTS
    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=token,
        max_age=settings.refresh_token_expire_days * 24 * 60 * 60,
        httponly=True,
        secure=secure,
        samesite="none" if secure else "lax",
        path="/api/v2/labby/auth",
    )


def clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path="/api/v2/labby/auth",
    )
