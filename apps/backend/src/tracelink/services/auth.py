from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tracelink.core.config import Settings
from tracelink.domain.models import AuthSession, User

password_hash = PasswordHash.recommended()


class AuthenticationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SessionTokens:
    access_token: str
    refresh_token: str
    refresh_expires_at: datetime


def normalize_email(value: str) -> str:
    return value.strip().casefold()


def hash_refresh_token(token: str, settings: Settings) -> str:
    return hmac.new(
        settings.auth_token_pepper.get_secret_value().encode(),
        token.encode(),
        hashlib.sha256,
    ).hexdigest()


def hash_user_agent(value: str | None) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value[:1000].encode()).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


class AuthService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    def _encode(
        self,
        *,
        user_id: UUID,
        session_id: UUID,
        token_type: str,
        expires_at: datetime,
    ) -> str:
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": str(user_id),
                "sid": str(session_id),
                "typ": token_type,
                "jti": str(uuid4()),
                "iss": self.settings.auth_issuer,
                "aud": self.settings.auth_audience,
                "iat": now,
                "nbf": now,
                "exp": expires_at,
            },
            self.settings.auth_jwt_secret.get_secret_value(),
            algorithm="HS256",
        )

    def decode(self, token: str, token_type: str, *, verify_exp: bool = True) -> dict[str, object]:
        try:
            claims = jwt.decode(
                token,
                self.settings.auth_jwt_secret.get_secret_value(),
                algorithms=["HS256"],
                audience=self.settings.auth_audience,
                issuer=self.settings.auth_issuer,
                options={
                    "require": ["sub", "sid", "typ", "jti", "iss", "aud", "iat", "nbf", "exp"],
                    "verify_exp": verify_exp,
                },
            )
        except jwt.PyJWTError as exc:
            raise AuthenticationError("invalid session") from exc
        if claims.get("typ") != token_type:
            raise AuthenticationError("invalid session")
        return claims

    async def register(self, email: str, password: str, display_name: str | None) -> User:
        user = User(
            email=normalize_email(email),
            password_hash=password_hash.hash(password),
            display_name=display_name,
            is_active=True,
        )
        self.session.add(user)
        await self.session.flush()
        return user

    async def authenticate(self, email: str, password: str) -> User:
        user = await self.session.scalar(select(User).where(User.email == normalize_email(email)))
        if user is None or not user.is_active:
            password_hash.hash(password)
            raise AuthenticationError("invalid email or password")
        try:
            valid, updated = password_hash.verify_and_update(password, user.password_hash)
        except Exception as exc:
            raise AuthenticationError("invalid email or password") from exc
        if not valid:
            raise AuthenticationError("invalid email or password")
        if updated:
            user.password_hash = updated
        user.last_login_at = datetime.now(UTC)
        await self.session.flush()
        return user

    async def create_session(self, user: User, user_agent: str | None) -> SessionTokens:
        now = datetime.now(UTC)
        expires_at = now + timedelta(days=self.settings.refresh_token_days)
        auth_session = AuthSession(
            user_id=user.id,
            token_hash="pending",
            expires_at=expires_at,
            user_agent_hash=hash_user_agent(user_agent),
        )
        self.session.add(auth_session)
        await self.session.flush()
        refresh = self._encode(
            user_id=user.id,
            session_id=auth_session.id,
            token_type="refresh",
            expires_at=expires_at,
        )
        auth_session.token_hash = hash_refresh_token(refresh, self.settings)
        access = self._encode(
            user_id=user.id,
            session_id=auth_session.id,
            token_type="access",
            expires_at=now + timedelta(minutes=self.settings.access_token_minutes),
        )
        await self.session.flush()
        return SessionTokens(access, refresh, expires_at)

    async def current_user(self, access_token: str) -> User:
        claims = self.decode(access_token, "access")
        try:
            user_id = UUID(str(claims["sub"]))
            session_id = UUID(str(claims["sid"]))
        except (KeyError, ValueError) as exc:
            raise AuthenticationError("invalid session") from exc
        now = datetime.now(UTC)
        row = await self.session.execute(
            select(User, AuthSession)
            .join(AuthSession, AuthSession.user_id == User.id)
            .where(
                User.id == user_id,
                User.is_active.is_(True),
                AuthSession.id == session_id,
                AuthSession.revoked_at.is_(None),
                AuthSession.expires_at > now,
            )
        )
        result = row.one_or_none()
        if result is None:
            raise AuthenticationError("invalid session")
        return cast(User, result[0])

    async def rotate(
        self, refresh_token: str, user_agent: str | None
    ) -> tuple[User, SessionTokens]:
        claims = self.decode(refresh_token, "refresh", verify_exp=False)
        try:
            session_id = UUID(str(claims["sid"]))
            user_id = UUID(str(claims["sub"]))
            expires_value = claims["exp"]
            if not isinstance(expires_value, (int, float, str)):
                raise ValueError
            expires_timestamp = int(expires_value)
        except (KeyError, TypeError, ValueError) as exc:
            raise AuthenticationError("invalid session") from exc
        auth_session = await self.session.scalar(
            select(AuthSession).where(AuthSession.id == session_id).with_for_update()
        )
        now = datetime.now(UTC)
        if auth_session is None or auth_session.user_id != user_id:
            raise AuthenticationError("invalid session")
        supplied_hash = hash_refresh_token(refresh_token, self.settings)
        if not hmac.compare_digest(auth_session.token_hash, supplied_hash):
            auth_session.revoked_at = now
            await self.session.flush()
            raise AuthenticationError("invalid session")
        if (
            auth_session.revoked_at is not None
            or auth_session.expires_at <= now
            or expires_timestamp <= int(now.timestamp())
        ):
            auth_session.revoked_at = auth_session.revoked_at or now
            await self.session.flush()
            raise AuthenticationError("invalid session")
        user = await self.session.get(User, user_id)
        if user is None or not user.is_active:
            auth_session.revoked_at = now
            await self.session.flush()
            raise AuthenticationError("invalid session")
        new_refresh = self._encode(
            user_id=user.id,
            session_id=auth_session.id,
            token_type="refresh",
            expires_at=auth_session.expires_at,
        )
        auth_session.token_hash = hash_refresh_token(new_refresh, self.settings)
        auth_session.user_agent_hash = hash_user_agent(user_agent)
        access = self._encode(
            user_id=user.id,
            session_id=auth_session.id,
            token_type="access",
            expires_at=now + timedelta(minutes=self.settings.access_token_minutes),
        )
        await self.session.flush()
        return user, SessionTokens(access, new_refresh, auth_session.expires_at)

    async def revoke(self, access_token: str | None, refresh_token: str | None) -> None:
        token = access_token or refresh_token
        if token is None:
            return
        token_type = "access" if access_token else "refresh"
        try:
            claims = self.decode(token, token_type, verify_exp=False)
            session_id = UUID(str(claims["sid"]))
        except (AuthenticationError, KeyError, ValueError):
            return
        auth_session = await self.session.get(AuthSession, session_id)
        if auth_session is not None and auth_session.revoked_at is None:
            auth_session.revoked_at = datetime.now(UTC)
            await self.session.flush()
