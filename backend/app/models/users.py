"""User, Role, and Permission models."""

import uuid

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base


class Role(Base):
    """Role model for RBAC."""

    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    permissions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    users: Mapped[list["User"]] = relationship("User", back_populates="role")
    permission_entries: Mapped[list["Permission"]] = relationship(
        "Permission", back_populates="role"
    )


class User(Base):
    """User model."""

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relationships
    role: Mapped["Role"] = relationship("Role", back_populates="users")
    connectors: Mapped[list["Connector"]] = relationship(  # noqa: F821
        "Connector", back_populates="creator", foreign_keys="Connector.created_by"
    )
    pipelines: Mapped[list["Pipeline"]] = relationship(  # noqa: F821
        "Pipeline", back_populates="creator", foreign_keys="Pipeline.created_by"
    )


class Permission(Base):
    """Permission model for fine-grained access control."""

    __tablename__ = "permissions"

    resource: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False
    )

    # Relationships
    role: Mapped["Role"] = relationship("Role", back_populates="permission_entries")
