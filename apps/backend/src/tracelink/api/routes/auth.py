from __future__ import annotations

import hashlib
import logging
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.api.dependencies import CurrentUser
from tracelink.api.rate_limit import RatePolicy, client_ip, enforce_rate_limit
from tracelink.api.schemas.auth import CsrfResponse, LoginRequest, RegisterRequest, UserRead
from tracelink.core.config import Settings, get_settings
from tracelink.domain.models import User
from tracelink.infrastructure.database import get_session
from tracelink.services.auth import (
    AuthenticationError,
    AuthService,
    SessionTokens,
    new_csrf_token,
    normalize_email,
)

router = APIRouter()
logger = logging.getLogger(__name__)
Session = Annotated[AsyncSession, Depends(get_session)]


def _email_reference(value: str) -> str:
    return hashlib.sha256(normalize_email(value).encode()).hexdigest()[:12]


def _set_session_cookies(response: Response, tokens: SessionTokens, settings: Settings) -> None:
    access_max_age = settings.access_token_minutes * 60
    refresh_max_age = max(0, int((tokens.refresh_expires_at - datetime.now(UTC)).total_seconds()))
    response.set_cookie(
        "tracelink_access",
        tokens.access_token,
        max_age=access_max_age,
        path="/",
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
    )
    response.set_cookie(
        "tracelink_refresh",
        tokens.refresh_token,
        max_age=refresh_max_age,
        path="/api/auth",
        httponly=True,
        secure=settings.secure_cookies,
        samesite="lax",
    )
    response.set_cookie(
        "tracelink_csrf",
        new_csrf_token(),
        max_age=refresh_max_age,
        path="/",
        httponly=False,
        secure=settings.secure_cookies,
        samesite="lax",
    )


def _clear_session_cookies(response: Response, settings: Settings) -> None:
    response.delete_cookie(
        "tracelink_access", path="/", secure=settings.secure_cookies, samesite="lax"
    )
    response.delete_cookie(
        "tracelink_refresh", path="/api/auth", secure=settings.secure_cookies, samesite="lax"
    )
    response.delete_cookie(
        "tracelink_csrf", path="/", secure=settings.secure_cookies, samesite="lax"
    )


@router.get("/csrf", response_model=CsrfResponse)
async def csrf(response: Response) -> CsrfResponse:
    settings = get_settings()
    token = new_csrf_token()
    response.set_cookie(
        "tracelink_csrf",
        token,
        max_age=settings.refresh_token_days * 86_400,
        path="/",
        httponly=False,
        secure=settings.secure_cookies,
        samesite="lax",
    )
    return CsrfResponse(csrf_token=token)


@router.post("/register", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest, request: Request, response: Response, session: Session
) -> User:
    settings = get_settings()
    if not settings.registration_is_enabled:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="registration disabled")
    await enforce_rate_limit(
        request,
        RatePolicy("register", settings.rate_limit_register_count, 3600),
        client_ip(request),
    )
    service = AuthService(session, settings)
    try:
        user = await service.register(str(payload.email), payload.password, payload.display_name)
        tokens = await service.create_session(user, request.headers.get("user-agent"))
        user.last_login_at = datetime.now(UTC)
        await session.commit()
        await session.refresh(user)
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="email already registered"
        ) from exc
    _set_session_cookies(response, tokens, settings)
    logger.info(
        "registration succeeded", extra={"user_id": str(user.id), "auth_event": "register_success"}
    )
    return user


@router.post("/login", response_model=UserRead)
async def login(
    payload: LoginRequest, request: Request, response: Response, session: Session
) -> User:
    settings = get_settings()
    reference = _email_reference(str(payload.email))
    await enforce_rate_limit(
        request,
        RatePolicy("login", settings.rate_limit_login_count, 60),
        f"{client_ip(request)}:{reference}",
    )
    service = AuthService(session, settings)
    try:
        user = await service.authenticate(str(payload.email), payload.password)
    except AuthenticationError as exc:
        logger.warning("login failed", extra={"auth_event": "login_failure"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid email or password"
        ) from exc
    tokens = await service.create_session(user, request.headers.get("user-agent"))
    await session.commit()
    await session.refresh(user)
    _set_session_cookies(response, tokens, settings)
    logger.info("login succeeded", extra={"user_id": str(user.id), "auth_event": "login_success"})
    return user


@router.post("/refresh", response_model=UserRead)
async def refresh(
    request: Request,
    response: Response,
    session: Session,
    refresh_token: Annotated[str | None, Cookie(alias="tracelink_refresh")] = None,
) -> User:
    settings = get_settings()
    identity = hashlib.sha256((refresh_token or client_ip(request)).encode()).hexdigest()
    await enforce_rate_limit(
        request,
        RatePolicy("refresh", settings.rate_limit_refresh_count, 60),
        f"{client_ip(request)}:{identity}",
    )
    if not refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")
    try:
        user, tokens = await AuthService(session, settings).rotate(
            refresh_token, request.headers.get("user-agent")
        )
        await session.commit()
        await session.refresh(user)
    except AuthenticationError as exc:
        await session.commit()
        _clear_session_cookies(response, settings)
        logger.warning("refresh failed", extra={"auth_event": "refresh_failure"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session"
        ) from exc
    _set_session_cookies(response, tokens, settings)
    return user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    session: Session,
    access_token: Annotated[str | None, Cookie(alias="tracelink_access")] = None,
    refresh_token: Annotated[str | None, Cookie(alias="tracelink_refresh")] = None,
) -> None:
    settings = get_settings()
    await AuthService(session, settings).revoke(access_token, refresh_token)
    await session.commit()
    _clear_session_cookies(response, settings)
    logger.info("logout", extra={"auth_event": "logout"})


@router.get("/me", response_model=UserRead)
async def me(user: CurrentUser) -> User:
    return user
