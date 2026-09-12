"""Password verification, signed access tokens, and single-use refresh rotation."""

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from fastapi import HTTPException
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth_schemas import TokenResponse
from app.config import Settings
from app.models import RefreshToken, User
from app.services.audit import record_event

password_hasher = PasswordHash.recommended()
# Unknown accounts still perform a password verification to avoid a cheap timing shortcut.
dummy_hash = password_hasher.hash(secrets.token_urlsafe(32))


def unauthorized() -> HTTPException:
    return HTTPException(
        401, "Invalid credentials or token.", headers={"WWW-Authenticate": "Bearer"}
    )


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue_tokens(session: Session, user: User, settings: Settings) -> TokenResponse:
    now = datetime.now(timezone.utc)
    access = jwt.encode(
        {
            "sub": user.id,
            "type": "access",
            "jti": str(uuid4()),
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_minutes),
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        settings.jwt_secret_key.get_secret_value(),
        algorithm="HS256",
    )
    refresh = secrets.token_urlsafe(48)
    session.add(
        RefreshToken(
            user_id=user.id,
            token_hash=token_hash(refresh),
            expires_at=now + timedelta(days=settings.refresh_token_days),
        )
    )
    return TokenResponse(
        access_token=access, refresh_token=refresh, expires_in=settings.access_token_minutes * 60
    )


def login(session: Session, email: str, password: str, settings: Settings) -> TokenResponse:
    user = session.scalar(select(User).where(User.email == email))
    try:
        valid, replacement = password_hasher.verify_and_update(
            password, user.password_hash if user else dummy_hash
        )
    except (UnknownHashError, ValueError):
        valid, replacement = False, None
    if not valid or user is None or not user.is_active:
        raise unauthorized()
    if replacement:
        user.password_hash = replacement
    result = issue_tokens(session, user, settings)
    record_event(session, user.id, "auth.login", "user", user.id)
    session.commit()
    return result


def refresh(session: Session, token: str, settings: Settings) -> TokenResponse:
    now = datetime.now(timezone.utc)
    row = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash(token)))
    if row is None:
        raise unauthorized()
    user = session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise unauthorized()
    # Atomic consumption: even simultaneous requests cannot both rotate the same token.
    claimed = session.execute(
        update(RefreshToken)
        .where(
            RefreshToken.id == row.id,
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
        .values(revoked_at=now)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        raise unauthorized()
    result = issue_tokens(session, user, settings)
    record_event(session, user.id, "auth.refreshed", "user", user.id)
    session.commit()  # Consumption and replacement are committed together.
    return result


def logout(session: Session, token: str) -> None:
    row = session.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash(token)))
    revoked = session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == token_hash(token), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    if row is not None and revoked.rowcount == 1:
        record_event(session, row.user_id, "auth.logout", "user", row.user_id)
    session.commit()


def access_subject(token: str, settings: Settings) -> str:
    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["sub", "type", "jti", "iat", "exp", "iss", "aud"]},
        )
        if claims["type"] != "access":
            raise unauthorized()
        return claims["sub"]
    except jwt.InvalidTokenError:
        raise unauthorized() from None
