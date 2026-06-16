"""Factory-boy factories for AuditLog entries."""

import uuid
from datetime import datetime, timezone

import factory

from backend.app.models.audit import AuditLog


class AuditLogFactory(factory.Factory):
    """Factory for creating AuditLog instances."""

    class Meta:
        model = AuditLog

    id = factory.LazyFunction(uuid.uuid4)
    event_type = factory.Iterator([
        "USER_LOGIN",
        "USER_LOGOUT",
        "USER_CREATED",
        "USER_UPDATED",
        "USER_DELETED",
        "CONNECTOR_CREATED",
        "CONNECTOR_UPDATED",
        "CONNECTOR_DELETED",
        "PIPELINE_CREATED",
        "PIPELINE_EXECUTED",
        "PIPELINE_FAILED",
        "SCHEDULE_CREATED",
        "PERMISSION_DENIED",
        "UNAUTHENTICATED_ACCESS",
        "PASSWORD_RESET",
        "KEY_ROTATION",
    ])
    actor_id = factory.LazyFunction(uuid.uuid4)
    target_resource_id = factory.LazyAttribute(lambda o: str(uuid.uuid4()))
    target_resource_type = factory.Iterator([
        "user", "connector", "pipeline", "schedule", "endpoint", "settings"
    ])
    result = factory.Iterator(["success", "failure"])
    ip_address = factory.Sequence(lambda n: f"192.168.1.{n % 256}")
    timestamp = factory.LazyFunction(lambda: datetime.now(timezone.utc))


class LoginAuditFactory(AuditLogFactory):
    """Factory for login audit events."""

    event_type = "USER_LOGIN"
    target_resource_type = "user"
    result = "success"


class FailedLoginAuditFactory(AuditLogFactory):
    """Factory for failed login audit events."""

    event_type = "USER_LOGIN"
    target_resource_type = "user"
    result = "failure"


class PermissionDeniedAuditFactory(AuditLogFactory):
    """Factory for permission denied audit events."""

    event_type = "PERMISSION_DENIED"
    target_resource_type = "endpoint"
    result = "failure"


class PipelineExecutionAuditFactory(AuditLogFactory):
    """Factory for pipeline execution audit events."""

    event_type = "PIPELINE_EXECUTED"
    target_resource_type = "pipeline"
    result = "success"


class ConnectorAuditFactory(AuditLogFactory):
    """Factory for connector-related audit events."""

    event_type = "CONNECTOR_CREATED"
    target_resource_type = "connector"
    result = "success"
