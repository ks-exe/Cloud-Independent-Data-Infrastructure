"""Audit log model with immutability enforcement."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class AuditLog(Base):
    """Immutable audit log entry.

    This table enforces immutability via a PostgreSQL trigger that prevents
    UPDATE and DELETE operations. The created_at and updated_at columns from
    the base are included but effectively immutable.
    """

    __tablename__ = "audit_logs"

    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    target_resource_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    target_resource_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True
    )
    result: Mapped[str] = mapped_column(String(50), nullable=False)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
