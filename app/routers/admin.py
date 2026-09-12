"""Administrator user management and safe audit inspection."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.auth_dependencies import require_admin
from app.auth_schemas import UserResponse
from app.database import get_db
from app.models import AuditEvent, User, UserRole
from app.services.audit import record_event

router = APIRouter(prefix="/api/v1/admin", tags=["Administration"])
Admin = Annotated[User, Depends(require_admin)]
DatabaseSession = Annotated[Session, Depends(get_db)]


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: UserRole | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def require_changes(self):
        if not self.model_fields_set or any(
            getattr(self, field) is None for field in self.model_fields_set
        ):
            raise ValueError("Provide a role or active state; null is not allowed.")
        return self


class AuditResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    user_id: str | None
    action: str
    resource_type: str
    resource_id: str
    request_id: str | None
    created_at: datetime


@router.get("/users", response_model=list[UserResponse])
def list_users(
    admin: Admin,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return list(
        session.scalars(select(User).order_by(User.email, User.id).offset(offset).limit(limit))
    )


@router.patch("/users/{user_id}", response_model=UserResponse)
def update_user(user_id: UUID, payload: UserUpdate, admin: Admin, session: DatabaseSession):
    if str(user_id) == admin.id:
        raise HTTPException(409, "Use another administrator to change your account.")
    try:
        # Serialize role edits, including simultaneous attempts to deactivate each other.
        administrators = list(
            session.scalars(
                select(User)
                .where(User.role == UserRole.ADMIN)
                .order_by(User.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if not any(item.id == admin.id and item.is_active for item in administrators):
            raise HTTPException(403, "Administrator access required.")
        target = session.scalar(select(User).where(User.id == str(user_id)).with_for_update())
        if target is None:
            raise HTTPException(404, "User not found.")
        changes = payload.model_dump(exclude_unset=True)
        for key, value in changes.items():
            setattr(target, key, value)
        record_event(
            session,
            admin.id,
            "user.updated",
            "user",
            target.id,
            {
                key: str(value) if isinstance(value, UserRole) else value
                for key, value in changes.items()
            },
        )
        session.commit()
        return target
    except SQLAlchemyError:
        session.rollback()
        raise HTTPException(503, "Unable to update user.") from None


@router.get("/audit-events", response_model=list[AuditResponse])
def list_audit(
    admin: Admin,
    session: DatabaseSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
):
    return list(
        session.scalars(
            select(AuditEvent)
            .order_by(AuditEvent.created_at.desc(), AuditEvent.id)
            .offset(offset)
            .limit(limit)
        )
    )
