"""System settings model."""

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class SystemSetting(Base):
    """System-wide configurable settings."""

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
