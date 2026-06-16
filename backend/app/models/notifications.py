"""Notification model."""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class Notification(Base):
    """User notification entry."""

    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    source_resource_id: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    recurrence_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
