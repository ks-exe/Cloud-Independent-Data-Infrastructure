"""Test factories for generating test data.

Exports all factory classes and Hypothesis strategies for convenient imports:
    from backend.tests.factories import UserFactory, ConnectorFactory, valid_dags
"""

from backend.tests.factories.audit_factory import (
    AuditLogFactory,
    ConnectorAuditFactory,
    FailedLoginAuditFactory,
    LoginAuditFactory,
    PermissionDeniedAuditFactory,
    PipelineExecutionAuditFactory,
)
from backend.tests.factories.connector_factory import (
    ConnectorConfigFactory,
    ConnectorFactory,
    DestinationConnectorFactory,
    InactiveConnectorFactory,
    MongoDBConnectorConfigFactory,
    MySQLConnectorConfigFactory,
    PostgreSQLConnectorFactory,
    SourceConnectorFactory,
)
from backend.tests.factories.pipeline_factory import (
    ActivePipelineFactory,
    ArchivedPipelineFactory,
    DestinationNodeFactory,
    FailedRunFactory,
    PipelineEdgeFactory,
    PipelineFactory,
    PipelineNodeFactory,
    PipelineRunFactory,
    PipelineRunLogFactory,
    PipelineScheduleFactory,
    PipelineVersionFactory,
    SourceNodeFactory,
    SuccessfulRunFactory,
    TransformNodeFactory,
)
from backend.tests.factories.strategies import (
    valid_cron_expressions,
    valid_dags,
    valid_emails,
    valid_usernames,
)
from backend.tests.factories.user_factory import (
    AdminRoleFactory,
    AdminUserFactory,
    DataEngineerRoleFactory,
    DeletedUserFactory,
    InactiveUserFactory,
    OperatorRoleFactory,
    PermissionFactory,
    RoleFactory,
    UserFactory,
    ViewerRoleFactory,
)

__all__ = [
    # User factories
    "RoleFactory",
    "AdminRoleFactory",
    "OperatorRoleFactory",
    "DataEngineerRoleFactory",
    "ViewerRoleFactory",
    "UserFactory",
    "AdminUserFactory",
    "InactiveUserFactory",
    "DeletedUserFactory",
    "PermissionFactory",
    # Connector factories
    "ConnectorFactory",
    "SourceConnectorFactory",
    "DestinationConnectorFactory",
    "PostgreSQLConnectorFactory",
    "InactiveConnectorFactory",
    "ConnectorConfigFactory",
    "MySQLConnectorConfigFactory",
    "MongoDBConnectorConfigFactory",
    # Pipeline factories
    "PipelineFactory",
    "ActivePipelineFactory",
    "ArchivedPipelineFactory",
    "PipelineVersionFactory",
    "PipelineNodeFactory",
    "PipelineEdgeFactory",
    "SourceNodeFactory",
    "TransformNodeFactory",
    "DestinationNodeFactory",
    "PipelineScheduleFactory",
    "PipelineRunFactory",
    "SuccessfulRunFactory",
    "FailedRunFactory",
    "PipelineRunLogFactory",
    # Audit factories
    "AuditLogFactory",
    "LoginAuditFactory",
    "FailedLoginAuditFactory",
    "PermissionDeniedAuditFactory",
    "PipelineExecutionAuditFactory",
    "ConnectorAuditFactory",
    # Hypothesis strategies
    "valid_usernames",
    "valid_emails",
    "valid_cron_expressions",
    "valid_dags",
]
