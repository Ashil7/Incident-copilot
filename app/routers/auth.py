"""JSON login and refresh contracts; roles are never accepted during registration."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth_dependencies import get_current_user
from app.auth_schemas import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from app.database import get_db
from app.models import User, UserRole
from app.services import auth
from app.services.audit import record_event

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])
DatabaseSession = Annotated[Session, Depends(get_db)]


@router.post("/register", response_model=UserResponse, status_code=201)
def register(payload: RegisterRequest, request: Request, session: DatabaseSession):
    if not request.app.state.settings.allow_registration:
        raise HTTPException(403, "Public registration is disabled.")
    try:
        if session.scalar(select(User.id).where(User.email == str(payload.email))) is not None:
            raise HTTPException(409, "Account already exists.")
        user = User(
            email=str(payload.email),
            full_name=payload.full_name,
            password_hash=auth.password_hasher.hash(payload.password.get_secret_value()),
            role=UserRole.ANALYST,
            is_active=True,
        )
        session.add(user)
        session.flush()
        result = UserResponse.model_validate(user)
        record_event(session, user.id, "user.registered", "user", user.id)
        session.commit()
        return result
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, "Account already exists.") from None
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(503, "Authentication unavailable.") from None


@router.post("/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, session: DatabaseSession):
    try:
        return auth.login(
            session,
            str(payload.email),
            payload.password.get_secret_value(),
            request.app.state.settings,
        )
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(503, "Authentication unavailable.") from None


@router.post("/refresh", response_model=TokenResponse)
def refresh(payload: RefreshRequest, request: Request, session: DatabaseSession):
    try:
        return auth.refresh(
            session, payload.refresh_token.get_secret_value(), request.app.state.settings
        )
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(503, "Authentication unavailable.") from None


@router.post("/logout", status_code=204)
def logout(payload: RefreshRequest, session: DatabaseSession):
    try:
        auth.logout(session, payload.refresh_token.get_secret_value())
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(503, "Authentication unavailable.") from None
    return Response(status_code=204)


@router.get("/me", response_model=UserResponse)
def me(user: Annotated[User, Depends(get_current_user)]):
    return user
