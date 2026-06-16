"""Connector and ConnectorConfig models."""

import uuid

from sqlalchemy import ForeignKey, Integer, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base


class Connector(Base):
    """Connector model for data source/destination connections."""

    __tablename__ = "connectors"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Relationships
    creator: Mapped["User"] = relationship(  # noqa: F821
        "User", back_populates="connectors", foreign_keys=[created_by]
    )
    config: Mapped["ConnectorConfig | None"] = relationship(
        "ConnectorConfig", back_populates="connector", uselist=False
    )


class ConnectorConfig(Base):
    """Connector configuration including encrypted credentials."""

    __tablename__ = "connector_configs"

    connector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("connectors.id"), unique=True, nullable=False
    )
    host: Mapped[str | None] = mapped_column(String(255), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    database_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    encrypted_credentials: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    extra_params: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Relationships
    connector: Mapped["Connector"] = relationship(
        "Connector", back_populates="config"
    )
