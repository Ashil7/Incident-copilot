"""Account and hashed refresh-token persistence for authentication."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.database import Base
from app.models.common import CreatedMixin, IdentityMixin, UpdatedMixin


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    ANALYST = "ANALYST"


class User(IdentityMixin, CreatedMixin, UpdatedMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "email = lower(trim(email)) AND length(email) > 0", name="ck_users_email_normalized"
        ),
    )

    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(200))
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=False, create_constraint=True),
        default=UserRole.ANALYST,
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    @validates("email")
    def normalize_email(self, key: str, value: str) -> str:
        return value.strip().lower()


class RefreshToken(IdentityMixin, CreatedMixin, Base):
    __tablename__ = "refresh_tokens"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
