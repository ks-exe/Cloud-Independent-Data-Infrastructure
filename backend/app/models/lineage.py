"""Lineage event model."""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class LineageEvent(Base):
    """Lineage event recording data movement steps."""

    __tablename__ = "lineage_events"

    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipelines.id"), nullable=False
    )
    execution_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_runs.id"), nullable=False
    )
    source_system: Mapped[str] = mapped_column(String(255), nullable=False)
    source_table: Mapped[str] = mapped_column(String(255), nullable=False)
    destination_system: Mapped[str] = mapped_column(String(255), nullable=False)
    destination_table: Mapped[str] = mapped_column(String(255), nullable=False)
    transformation_node: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    triggered_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
