"""Resolve the bearer token to a current, active database user."""

from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import User, UserRole
from app.services.auth import access_subject, unauthorized

bearer = HTTPBearer(auto_error=False)


def get_current_user(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    session: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None or len(credentials.credentials) > 4096:
        raise unauthorized()
    subject = access_subject(credentials.credentials, request.app.state.settings)
    try:
        user = session.get(User, subject)
    except SQLAlchemyError:
        raise HTTPException(503, "Authentication unavailable.") from None
    if user is None or not user.is_active:
        raise unauthorized()
    request.state.user_id = user.id
    return user


def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != UserRole.ADMIN:
        raise HTTPException(403, "Administrator access required.")
    return user
