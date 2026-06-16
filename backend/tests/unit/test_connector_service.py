"""Unit tests for ConnectorService."""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.core.encryption import encrypt_credentials
from backend.app.schemas.connector import (
    CREDENTIAL_MASK,
    ConnectorCreate,
    ConnectorDirection,
    ConnectorUpdate,
    SourceType,
    DestinationType,
)
from backend.app.services.connector_service import (
    ConnectorDeletionBlockedError,
    ConnectorNotFoundError,
    ConnectorService,
    ConnectorTypeError,
)


# --- Helpers ---


def _make_key() -> bytes:
    import os
    return os.urandom(32)


def _make_connector_model(
    connector_id=None,
    name="Test Connector",
    connector_type="postgresql",
    direction="source",
    status="active",
    user_id=None,
    host="localhost",
    port=5432,
    database_name="testdb",
    credentials=None,
):
    """Create a mock Connector model with config."""
    if connector_id is None:
        connector_id = uuid.uuid4()
    if user_id is None:
        user_id = uuid.uuid4()

    connector = MagicMock()
    connector.id = connector_id
    connector.name = name
    connector.type = connector_type
    connector.direction = direction
    connector.status = status
    connector.created_by = user_id
    connector.created_at = datetime.now(timezone.utc)
    connector.updated_at = datetime.now(timezone.utc)

    config = MagicMock()
    config.connector_id = connector_id
    config.host = host
    config.port = port
    config.database_name = database_name
    config.extra_params = None

    if credentials:
        config.encrypted_credentials = encrypt_credentials(credentials)
    else:
        config.encrypted_credentials = None

    connector.config = config
    return connector


# --- Tests ---


class TestConnectorTypeValidation:
    """Tests for connector type validation logic."""

    def test_valid_source_types(self):
        service = ConnectorService(db=AsyncMock())
        for source_type in SourceType:
            # Should not raise
            service._validate_connector_type(source_type.value, "source")

    def test_valid_destination_types(self):
        service = ConnectorService(db=AsyncMock())
        for dest_type in DestinationType:
            service._validate_connector_type(dest_type.value, "destination")

    def test_invalid_source_type_raises(self):
        service = ConnectorService(db=AsyncMock())
        with pytest.raises(ConnectorTypeError):
            service._validate_connector_type("clickhouse", "source")

    def test_invalid_destination_type_raises(self):
        service = ConnectorService(db=AsyncMock())
        with pytest.raises(ConnectorTypeError):
            service._validate_connector_type("csv", "destination")

    def test_invalid_direction_raises(self):
        from backend.app.services.connector_service import ConnectorServiceError
        service = ConnectorService(db=AsyncMock())
        with pytest.raises(ConnectorServiceError):
            service._validate_connector_type("postgresql", "invalid")


class TestCredentialMasking:
    """Tests for credential masking in API responses."""

    def test_mask_credentials_returns_masked_values(self):
        service = ConnectorService(db=AsyncMock())
        creds = {"username": "admin", "password": "secret123"}
        encrypted = encrypt_credentials(creds)
        masked = service._mask_credentials(encrypted)
        assert masked == {"username": CREDENTIAL_MASK, "password": CREDENTIAL_MASK}

    def test_mask_credentials_never_exposes_plaintext(self):
        service = ConnectorService(db=AsyncMock())
        creds = {"api_key": "sk-1234567890"}
        encrypted = encrypt_credentials(creds)
        masked = service._mask_credentials(encrypted)
        assert "sk-1234567890" not in str(masked)
        assert masked["api_key"] == CREDENTIAL_MASK

    def test_mask_credentials_with_none_returns_empty(self):
        service = ConnectorService(db=AsyncMock())
        masked = service._mask_credentials(None)
        assert masked == {}

    def test_connector_response_has_masked_credentials(self):
        service = ConnectorService(db=AsyncMock())
        connector = _make_connector_model(
            credentials={"username": "admin", "password": "topsecret"}
        )
        response = service._connector_to_response(connector)
        assert response.credentials["username"] == CREDENTIAL_MASK
        assert response.credentials["password"] == CREDENTIAL_MASK
        assert "topsecret" not in str(response.credentials)


class TestCreateConnector:
    """Tests for create_connector method."""

    @pytest.mark.asyncio
    async def test_create_postgresql_source_connector(self):
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        service = ConnectorService(db=db)
        config = ConnectorCreate(
            name="My PostgreSQL Source",
            type="postgresql",
            direction=ConnectorDirection.SOURCE,
            host="db.example.com",
            port=5432,
            database_name="mydb",
            credentials={"username": "user", "password": "pass"},
        )
        user_id = uuid.uuid4()

        # Patch Connector and ConnectorConfig model creation to set proper IDs
        with patch("backend.app.services.connector_service.Connector") as MockConnector, \
             patch("backend.app.services.connector_service.ConnectorConfig") as MockConfig:
            mock_connector = MagicMock()
            mock_connector.id = uuid.uuid4()
            mock_connector.name = "My PostgreSQL Source"
            mock_connector.type = "postgresql"
            mock_connector.direction = "source"
            mock_connector.status = "active"
            mock_connector.created_by = user_id
            mock_connector.created_at = datetime.now(timezone.utc)
            mock_connector.updated_at = datetime.now(timezone.utc)
            mock_connector.config = None
            MockConnector.return_value = mock_connector

            mock_config = MagicMock()
            mock_config.host = "db.example.com"
            mock_config.port = 5432
            mock_config.database_name = "mydb"
            mock_config.encrypted_credentials = encrypt_credentials({"username": "user", "password": "pass"})
            mock_config.extra_params = None
            MockConfig.return_value = mock_config

            result = await service.create_connector(config, user_id)

        assert result.name == "My PostgreSQL Source"
        assert result.type == "postgresql"
        assert result.direction == "source"
        assert result.credentials["username"] == CREDENTIAL_MASK
        assert result.credentials["password"] == CREDENTIAL_MASK

    @pytest.mark.asyncio
    async def test_create_connector_invalid_type_raises(self):
        db = AsyncMock()
        service = ConnectorService(db=db)
        config = ConnectorCreate(
            name="Bad Connector",
            type="mongodb",  # Not a supported type
            direction=ConnectorDirection.SOURCE,
            credentials={},
        )
        with pytest.raises(ConnectorTypeError):
            await service.create_connector(config, uuid.uuid4())


class TestDeleteConnector:
    """Tests for delete_connector with pipeline dependency check."""

    @pytest.mark.asyncio
    async def test_delete_blocked_by_dependent_pipelines(self):
        connector_id = uuid.uuid4()
        connector = _make_connector_model(connector_id=connector_id)

        db = AsyncMock()
        service = ConnectorService(db=db)

        # Mock _get_connector_model to return the connector
        service._get_connector_model = AsyncMock(return_value=connector)

        # Mock _get_dependent_pipelines to return a pipeline
        from backend.app.schemas.connector import DependentPipelineInfo
        dependent = [
            DependentPipelineInfo(
                pipeline_id=uuid.uuid4(),
                pipeline_name="ETL Pipeline",
                status="active",
            )
        ]
        service._get_dependent_pipelines = AsyncMock(return_value=dependent)

        with pytest.raises(ConnectorDeletionBlockedError) as exc_info:
            await service.delete_connector(connector_id)

        assert len(exc_info.value.dependent_pipelines) == 1
        assert exc_info.value.dependent_pipelines[0].pipeline_name == "ETL Pipeline"

    @pytest.mark.asyncio
    async def test_delete_succeeds_when_no_dependent_pipelines(self):
        connector_id = uuid.uuid4()
        connector = _make_connector_model(connector_id=connector_id)

        db = AsyncMock()
        db.delete = AsyncMock()
        db.flush = AsyncMock()
        service = ConnectorService(db=db)

        service._get_connector_model = AsyncMock(return_value=connector)
        service._get_dependent_pipelines = AsyncMock(return_value=[])

        # Should not raise
        await service.delete_connector(connector_id)
        assert db.delete.called


class TestConnectorNotFound:
    """Tests for connector not found error handling."""

    @pytest.mark.asyncio
    async def test_get_nonexistent_connector_raises(self):
        db = AsyncMock()
        service = ConnectorService(db=db)

        # Mock _get_connector_model directly since it has complex ORM logic
        service._get_connector_model = AsyncMock(
            side_effect=ConnectorNotFoundError(uuid.uuid4())
        )

        with pytest.raises(ConnectorNotFoundError):
            await service.get_connector(uuid.uuid4())


class TestConnectionTest:
    """Tests for connection test functionality."""

    @pytest.mark.asyncio
    async def test_connection_test_timeout(self):
        """Connection test should respect 30-second timeout."""
        connector = _make_connector_model(
            connector_type="postgresql",
            credentials={"username": "user", "password": "pass"},
        )

        db = AsyncMock()
        service = ConnectorService(db=db)
        service._get_connector_model = AsyncMock(return_value=connector)

        # Mock _perform_connection_test to simulate a timeout
        import asyncio

        async def slow_test(*args, **kwargs):
            await asyncio.sleep(100)  # Much longer than timeout
            return True, "Success"

        service._perform_connection_test = slow_test

        # The test should time out at 30 seconds, but in unit test we patch the timeout
        with patch(
            "backend.app.services.connector_service.CONNECTION_TEST_TIMEOUT_SECONDS", 0.1
        ):
            result = await service.test_connection(connector.id)

        assert result.success is False
        assert "timed out" in result.message.lower()

    @pytest.mark.asyncio
    async def test_connection_test_success(self):
        connector = _make_connector_model(
            connector_type="postgresql",
            credentials={"username": "user", "password": "pass"},
        )

        db = AsyncMock()
        service = ConnectorService(db=db)
        service._get_connector_model = AsyncMock(return_value=connector)

        async def mock_test(*args, **kwargs):
            return True, "Connection successful"

        service._perform_connection_test = mock_test

        result = await service.test_connection(connector.id)
        assert result.success is True
        assert "successful" in result.message.lower()
        assert result.latency_ms is not None
        assert result.latency_ms >= 0


class TestSupportedConnectorTypes:
    """Tests verifying all required connector types are supported."""

    def test_source_types_include_all_required(self):
        """Requirement 4.6: PostgreSQL, MySQL, CSV, Excel, REST API."""
        required = {"postgresql", "mysql", "csv", "excel", "rest_api"}
        actual = {t.value for t in SourceType}
        assert required == actual

    def test_destination_types_include_all_required(self):
        """Requirement 4.7: PostgreSQL, ClickHouse."""
        required = {"postgresql", "clickhouse"}
        actual = {t.value for t in DestinationType}
        assert required == actual
