"""Tests to verify factory and fixture infrastructure works correctly."""

import uuid

import pytest

from backend.tests.factories import (
    AdminRoleFactory,
    AuditLogFactory,
    ConnectorConfigFactory,
    ConnectorFactory,
    DestinationNodeFactory,
    PipelineEdgeFactory,
    PipelineFactory,
    PipelineNodeFactory,
    PipelineVersionFactory,
    RoleFactory,
    SourceNodeFactory,
    TransformNodeFactory,
    UserFactory,
)


class TestUserFactories:
    """Verify user and role factories produce valid instances."""

    def test_role_factory_creates_role(self):
        role = RoleFactory()
        assert role.id is not None
        assert role.name.startswith("role_")
        assert role.permissions is not None

    def test_admin_role_factory(self):
        role = AdminRoleFactory()
        assert role.name == "Admin"

    def test_user_factory_creates_user(self):
        user = UserFactory()
        assert user.id is not None
        assert user.username.startswith("user_")
        assert "@" in user.email
        assert user.is_active is True
        assert user.is_deleted is False

    def test_user_factory_with_custom_role(self):
        role_id = uuid.uuid4()
        user = UserFactory(role_id=role_id)
        assert user.role_id == role_id


class TestConnectorFactories:
    """Verify connector factories produce valid instances."""

    def test_connector_factory(self):
        connector = ConnectorFactory()
        assert connector.id is not None
        assert connector.name.startswith("connector_")
        assert connector.type in ["postgresql", "mysql", "mongodb", "s3", "rest_api"]
        assert connector.direction in ["source", "destination", "bidirectional"]

    def test_connector_config_factory(self):
        config = ConnectorConfigFactory()
        assert config.id is not None
        assert config.host is not None
        assert config.port == 5432
        assert config.encrypted_credentials is not None
        assert len(config.encrypted_credentials) > 0


class TestPipelineFactories:
    """Verify pipeline factories produce valid instances."""

    def test_pipeline_factory(self):
        pipeline = PipelineFactory()
        assert pipeline.id is not None
        assert pipeline.name.startswith("pipeline_")
        assert pipeline.status == "draft"
        assert pipeline.current_version == 1

    def test_pipeline_node_factories(self):
        source = SourceNodeFactory()
        assert source.node_type == "source"

        transform = TransformNodeFactory()
        assert transform.node_type == "transform"

        dest = DestinationNodeFactory()
        assert dest.node_type == "destination"

    def test_pipeline_edge_factory(self):
        edge = PipelineEdgeFactory()
        assert edge.source_node_id is not None
        assert edge.target_node_id is not None
        assert edge.source_node_id != edge.target_node_id

    def test_pipeline_version_factory(self):
        version = PipelineVersionFactory()
        assert version.definition_snapshot is not None
        assert "nodes" in version.definition_snapshot
        assert "edges" in version.definition_snapshot


class TestAuditFactories:
    """Verify audit log factories produce valid instances."""

    def test_audit_log_factory(self):
        audit = AuditLogFactory()
        assert audit.id is not None
        assert audit.event_type is not None
        assert audit.actor_id is not None
        assert audit.result in ["success", "failure"]
        assert audit.timestamp is not None


class TestDatabaseFixtures:
    """Verify database fixtures work with async sessions."""

    @pytest.mark.asyncio
    async def test_db_session_fixture(self, db_session):
        """Verify db_session fixture provides a working session."""
        assert db_session is not None

    @pytest.mark.asyncio
    async def test_sample_role_fixture(self, sample_role):
        """Verify sample_role fixture creates a role in the DB."""
        assert sample_role.name == "Admin"
        assert sample_role.id is not None

    @pytest.mark.asyncio
    async def test_sample_user_fixture(self, sample_user):
        """Verify sample_user fixture creates a user in the DB."""
        assert sample_user.username == "test_admin"
        assert sample_user.email == "admin@example.com"
        assert sample_user.is_active is True

    @pytest.mark.asyncio
    async def test_sample_connector_fixture(self, sample_connector):
        """Verify sample_connector has encrypted credentials."""
        assert sample_connector.name == "test_pg_source"
        assert sample_connector.config is not None
        assert sample_connector.config.encrypted_credentials is not None
        assert len(sample_connector.config.encrypted_credentials) > 0

    @pytest.mark.asyncio
    async def test_sample_pipeline_fixture(self, sample_pipeline):
        """Verify sample_pipeline has nodes and edges."""
        assert sample_pipeline.name == "test_etl_pipeline"
        assert len(sample_pipeline.nodes) == 3
        assert len(sample_pipeline.edges) == 2
        # Verify node types
        node_types = [n.node_type for n in sample_pipeline.nodes]
        assert "source" in node_types
        assert "transform" in node_types
        assert "destination" in node_types


class TestAuthHeaders:
    """Verify auth_headers fixture produces valid JWTs."""

    def test_auth_headers_contains_all_roles(self, auth_headers):
        """All four roles should have headers."""
        assert "Admin" in auth_headers
        assert "Operator" in auth_headers
        assert "Data_Engineer" in auth_headers
        assert "Viewer" in auth_headers

    def test_auth_headers_format(self, auth_headers):
        """Headers should contain Bearer tokens."""
        for role, headers in auth_headers.items():
            assert "Authorization" in headers
            assert headers["Authorization"].startswith("Bearer ")
            token = headers["Authorization"].replace("Bearer ", "")
            assert len(token) > 0
