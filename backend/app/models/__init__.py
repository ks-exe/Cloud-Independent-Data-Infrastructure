"""SQLAlchemy models — import all models here so Alembic can discover them."""

from backend.app.models.base import Base
from backend.app.models.users import User, Role, Permission
from backend.app.models.connectors import Connector, ConnectorConfig
from backend.app.models.pipelines import (
    Pipeline,
    PipelineVersion,
    PipelineNode,
    PipelineEdge,
    PipelineSchedule,
    PipelineRun,
    PipelineRunLog,
)
from backend.app.models.lineage import LineageEvent
from backend.app.models.audit import AuditLog
from backend.app.models.notifications import Notification
from backend.app.models.settings import SystemSetting

__all__ = [
    "Base",
    "User",
    "Role",
    "Permission",
    "Connector",
    "ConnectorConfig",
    "Pipeline",
    "PipelineVersion",
    "PipelineNode",
    "PipelineEdge",
    "PipelineSchedule",
    "PipelineRun",
    "PipelineRunLog",
    "LineageEvent",
    "AuditLog",
    "Notification",
    "SystemSetting",
]
