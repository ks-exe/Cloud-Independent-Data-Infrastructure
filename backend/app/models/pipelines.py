"""Pipeline-related models."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base


class Pipeline(Base):
    """Pipeline model."""

    __tablename__ = "pipelines"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Relationships
    creator: Mapped["User"] = relationship(  # noqa: F821
        "User", back_populates="pipelines", foreign_keys=[created_by]
    )
    versions: Mapped[list["PipelineVersion"]] = relationship(
        "PipelineVersion", back_populates="pipeline"
    )
    nodes: Mapped[list["PipelineNode"]] = relationship(
        "PipelineNode", back_populates="pipeline"
    )
    edges: Mapped[list["PipelineEdge"]] = relationship(
        "PipelineEdge", back_populates="pipeline"
    )
    schedules: Mapped[list["PipelineSchedule"]] = relationship(
        "PipelineSchedule", back_populates="pipeline"
    )
    runs: Mapped[list["PipelineRun"]] = relationship(
        "PipelineRun", back_populates="pipeline"
    )


class PipelineVersion(Base):
    """Pipeline version with full DAG snapshot."""

    __tablename__ = "pipeline_versions"

    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipelines.id"), nullable=False
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    definition_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Relationships
    pipeline: Mapped["Pipeline"] = relationship(
        "Pipeline", back_populates="versions"
    )


class PipelineNode(Base):
    """Pipeline node (source, transform, destination)."""

    __tablename__ = "pipeline_nodes"

    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipelines.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    node_type: Mapped[str] = mapped_column(String(50), nullable=False)
    node_subtype: Mapped[str] = mapped_column(String(50), nullable=False)
    config: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    position_x: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    position_y: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    # Relationships
    pipeline: Mapped["Pipeline"] = relationship(
        "Pipeline", back_populates="nodes"
    )


class PipelineEdge(Base):
    """Pipeline edge connecting two nodes."""

    __tablename__ = "pipeline_edges"

    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipelines.id"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    source_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_nodes.id"), nullable=False
    )
    target_node_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_nodes.id"), nullable=False
    )

    # Relationships
    pipeline: Mapped["Pipeline"] = relationship(
        "Pipeline", back_populates="edges"
    )
    source_node: Mapped["PipelineNode"] = relationship(
        "PipelineNode", foreign_keys=[source_node_id]
    )
    target_node: Mapped["PipelineNode"] = relationship(
        "PipelineNode", foreign_keys=[target_node_id]
    )


class PipelineSchedule(Base):
    """Pipeline schedule with cron expression."""

    __tablename__ = "pipeline_schedules"

    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipelines.id"), nullable=False
    )
    cron_expression: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    dagster_schedule_name: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Relationships
    pipeline: Mapped["Pipeline"] = relationship(
        "Pipeline", back_populates="schedules"
    )


class PipelineRun(Base):
    """Pipeline execution run record."""

    __tablename__ = "pipeline_runs"

    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipelines.id"), nullable=False
    )
    pipeline_version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    trigger_type: Mapped[str] = mapped_column(String(20), nullable=False)
    triggered_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    node_row_counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    duration_ms: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # Relationships
    pipeline: Mapped["Pipeline"] = relationship(
        "Pipeline", back_populates="runs"
    )
    logs: Mapped[list["PipelineRunLog"]] = relationship(
        "PipelineRunLog", back_populates="run"
    )


class PipelineRunLog(Base):
    """Log entries for pipeline execution runs."""

    __tablename__ = "pipeline_run_logs"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("pipeline_runs.id"), nullable=False
    )
    level: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Relationships
    run: Mapped["PipelineRun"] = relationship(
        "PipelineRun", back_populates="logs"
    )
