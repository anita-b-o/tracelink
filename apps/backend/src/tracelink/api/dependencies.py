import logging
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.core.config import get_settings
from tracelink.domain.models import User
from tracelink.infrastructure.database import get_session
from tracelink.services.auth import AuthenticationError, AuthService, normalize_email

logger = logging.getLogger(__name__)


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_session)],
    access_token: Annotated[str | None, Cookie(alias="tracelink_access")] = None,
) -> User:
    settings = get_settings()
    if settings.test_auth_bypass and not access_token:
        email = normalize_email(settings.dev_bootstrap_email)
        user = await session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(email=email, password_hash="test-auth-bypass", is_active=True)
            session.add(user)
            await session.flush()
        return user
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
        )
    try:
        return await AuthService(session, settings).current_user(access_token)
    except AuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session"
        ) from exc


Session = Annotated[AsyncSession, Depends(get_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
