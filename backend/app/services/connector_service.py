"""Connector Service — CRUD, credential encryption, connection testing, health checks.

Manages:
- Create/update/delete connectors with AES-256-GCM credential encryption
- Connection testing with 30-second timeout
- Health checks with circuit breaker pattern (3 failures → OPEN → 60s recovery)
- Deletion blocking when active pipelines reference the connector
- Credential masking in all API responses (never return plaintext)
- Memory clearing of decrypted credentials within 5 seconds after use
"""

import asyncio
import gc
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.core.circuit_breaker import (
    CircuitState,
    circuit_breaker_registry,
)
from backend.app.core.encryption import decrypt_credentials, encrypt_credentials
from backend.app.models.connectors import Connector, ConnectorConfig
from backend.app.models.pipelines import Pipeline, PipelineNode
from backend.app.schemas.connector import (
    CREDENTIAL_MASK,
    ConnectionTestResult,
    ConnectorCreate,
    ConnectorDirection,
    ConnectorListResponse,
    ConnectorResponse,
    ConnectorUpdate,
    DependentPipelineInfo,
    DestinationType,
    HealthStatus,
    SourceType,
)

logger = logging.getLogger(__name__)

# Connection test timeout
CONNECTION_TEST_TIMEOUT_SECONDS = 30

# Credential memory cleanup delay
CREDENTIAL_CLEANUP_DELAY_SECONDS = 5


class ConnectorServiceError(Exception):
    """Base exception for connector service operations."""

    def __init__(self, message: str, code: str = "CONNECTOR_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class ConnectorNotFoundError(ConnectorServiceError):
    """Raised when a connector is not found."""

    def __init__(self, connector_id: uuid.UUID):
        super().__init__(
            message=f"Connector {connector_id} not found",
            code="CONNECTOR_NOT_FOUND",
        )


class ConnectorTypeError(ConnectorServiceError):
    """Raised when connector type is invalid for the given direction."""

    def __init__(self, connector_type: str, direction: str):
        super().__init__(
            message=f"Invalid connector type '{connector_type}' for direction '{direction}'",
            code="INVALID_CONNECTOR_TYPE",
        )


class ConnectorDeletionBlockedError(ConnectorServiceError):
    """Raised when connector deletion is blocked by dependent pipelines."""

    def __init__(self, dependent_pipelines: list[DependentPipelineInfo]):
        self.dependent_pipelines = dependent_pipelines
        pipeline_names = [p.pipeline_name for p in dependent_pipelines]
        super().__init__(
            message=(
                f"Cannot delete connector: referenced by active pipelines: "
                f"{', '.join(pipeline_names)}"
            ),
            code="DELETION_BLOCKED",
        )


class ConnectorDisabledInAirGapError(ConnectorServiceError):
    """Raised when a REST API connector operation is attempted in air-gapped mode."""

    def __init__(self):
        super().__init__(
            message="REST API connectors are unavailable in air-gapped mode. "
            "This connector type requires internet connectivity.",
            code="CONNECTOR_DISABLED_AIR_GAPPED",
        )


# Message displayed when REST API connectors are disabled in air-gapped mode
AIR_GAPPED_DISABLED_MESSAGE = (
    "Disabled: REST API connectors require internet connectivity "
    "and are unavailable in air-gapped deployments."
)


class ConnectorService:
    """Service for connector CRUD operations, testing, and health checks."""

    def __init__(self, db: AsyncSession):
        self.db = db

    def _is_air_gapped(self) -> bool:
        """Check if the platform is running in air-gapped mode."""
        from backend.app.core.config import settings
        return settings.air_gapped_mode

    def _is_rest_api_connector(self, connector_type: str, direction: str) -> bool:
        """Check if a connector is a REST API source connector."""
        return connector_type == "rest_api" and direction == ConnectorDirection.SOURCE.value

    def _validate_connector_type(self, connector_type: str, direction: str) -> None:
        """Validate that the connector type is valid for the given direction.

        Also rejects REST API source connectors in air-gapped mode.

        Args:
            connector_type: The connector type string.
            direction: "source" or "destination".

        Raises:
            ConnectorTypeError: If the type is not valid for the direction.
            ConnectorDisabledInAirGapError: If REST API in air-gapped mode.
        """
        valid_source_types = {t.value for t in SourceType}
        valid_destination_types = {t.value for t in DestinationType}

        if direction == ConnectorDirection.SOURCE.value:
            if connector_type not in valid_source_types:
                raise ConnectorTypeError(connector_type, direction)
            # Block REST API connector creation in air-gapped mode
            if self._is_rest_api_connector(connector_type, direction) and self._is_air_gapped():
                raise ConnectorDisabledInAirGapError()
        elif direction == ConnectorDirection.DESTINATION.value:
            if connector_type not in valid_destination_types:
                raise ConnectorTypeError(connector_type, direction)
        else:
            raise ConnectorServiceError(
                f"Invalid direction: {direction}", code="INVALID_DIRECTION"
            )

    def _mask_credentials(self, encrypted_creds: bytes | None) -> dict[str, str]:
        """Return masked credential keys without exposing values.

        Decrypts only to extract key names, then masks all values.
        Never returns plaintext credential values.

        Args:
            encrypted_creds: The encrypted credentials bytes, or None.

        Returns:
            Dictionary with credential keys mapped to the fixed mask value.
        """
        if not encrypted_creds:
            return {}

        try:
            creds = decrypt_credentials(encrypted_creds)
            # Only expose key names with masked values
            masked = {key: CREDENTIAL_MASK for key in creds.keys()}
            # Clear the decrypted values from memory
            _clear_dict(creds)
            return masked
        except Exception:
            # If decryption fails, return empty
            return {}

    def _connector_to_response(self, connector: Connector) -> ConnectorResponse:
        """Convert a Connector model to a response schema with masked credentials.

        In air-gapped mode, REST API source connectors are marked as disabled
        with an explanatory message.
        """
        config = connector.config
        masked_creds = {}
        if config and config.encrypted_credentials:
            masked_creds = self._mask_credentials(config.encrypted_credentials)

        # Determine effective status — REST API connectors disabled in air-gapped mode
        effective_status = connector.status
        disabled_message = None
        if self._is_rest_api_connector(connector.type, connector.direction) and self._is_air_gapped():
            effective_status = "disabled"
            disabled_message = AIR_GAPPED_DISABLED_MESSAGE

        extra_params = config.extra_params if config else None
        # Attach disabled message to extra_params for API consumers
        if disabled_message:
            extra_params = extra_params or {}
            extra_params = {**extra_params, "disabled_reason": disabled_message}

        return ConnectorResponse(
            id=connector.id,
            name=connector.name,
            type=connector.type,
            direction=connector.direction,
            status=effective_status,
            host=config.host if config else None,
            port=config.port if config else None,
            database_name=config.database_name if config else None,
            credentials=masked_creds,
            extra_params=extra_params,
            created_by=connector.created_by,
            created_at=connector.created_at,
            updated_at=connector.updated_at,
        )

    async def create_connector(
        self, config: ConnectorCreate, user_id: uuid.UUID
    ) -> ConnectorResponse:
        """Create a new connector with encrypted credentials.

        Args:
            config: Connector creation schema.
            user_id: The ID of the user creating the connector.

        Returns:
            ConnectorResponse with masked credentials.

        Raises:
            ConnectorTypeError: If the type is invalid for the direction.
        """
        # Validate connector type against direction
        self._validate_connector_type(config.type, config.direction.value)

        # Create the connector record
        connector = Connector(
            name=config.name,
            type=config.type,
            direction=config.direction.value,
            status="active",
            created_by=user_id,
        )
        self.db.add(connector)
        await self.db.flush()  # Get the connector ID

        # Encrypt credentials
        encrypted_creds = None
        if config.credentials:
            encrypted_creds = encrypt_credentials(config.credentials)

        # Create the config record
        connector_config = ConnectorConfig(
            connector_id=connector.id,
            host=config.host,
            port=config.port,
            database_name=config.database_name,
            encrypted_credentials=encrypted_creds,
            extra_params=config.extra_params,
        )
        self.db.add(connector_config)
        await self.db.flush()

        # Reload with relationship
        connector.config = connector_config

        logger.info(
            "Created connector %s (type=%s, direction=%s) by user %s",
            connector.id,
            config.type,
            config.direction.value,
            user_id,
        )

        return self._connector_to_response(connector)

    async def get_connector(self, connector_id: uuid.UUID) -> ConnectorResponse:
        """Get a connector by ID with masked credentials.

        Args:
            connector_id: The connector UUID.

        Returns:
            ConnectorResponse with masked credentials.

        Raises:
            ConnectorNotFoundError: If connector doesn't exist.
        """
        connector = await self._get_connector_model(connector_id)
        return self._connector_to_response(connector)

    async def list_connectors(
        self,
        direction: str | None = None,
        connector_type: str | None = None,
        status: str | None = None,
    ) -> ConnectorListResponse:
        """List all connectors with optional filters.

        Args:
            direction: Filter by "source" or "destination".
            connector_type: Filter by connector type.
            status: Filter by status.

        Returns:
            ConnectorListResponse with masked credentials.
        """
        query = select(Connector).options(selectinload(Connector.config))

        if direction:
            query = query.where(Connector.direction == direction)
        if connector_type:
            query = query.where(Connector.type == connector_type)
        if status:
            query = query.where(Connector.status == status)

        result = await self.db.execute(query)
        connectors = result.scalars().all()

        responses = [self._connector_to_response(c) for c in connectors]
        return ConnectorListResponse(connectors=responses, total=len(responses))

    async def update_connector(
        self, connector_id: uuid.UUID, update: ConnectorUpdate
    ) -> ConnectorResponse:
        """Update a connector's configuration.

        Re-encrypts credentials if they are changed.

        Args:
            connector_id: The connector UUID.
            update: The fields to update.

        Returns:
            Updated ConnectorResponse with masked credentials.

        Raises:
            ConnectorNotFoundError: If connector doesn't exist.
        """
        connector = await self._get_connector_model(connector_id)
        config = connector.config

        # Update connector name if provided
        if update.name is not None:
            connector.name = update.name

        # Update config fields
        if config is None:
            config = ConnectorConfig(connector_id=connector.id)
            self.db.add(config)

        if update.host is not None:
            config.host = update.host
        if update.port is not None:
            config.port = update.port
        if update.database_name is not None:
            config.database_name = update.database_name
        if update.extra_params is not None:
            config.extra_params = update.extra_params

        # Re-encrypt credentials if changed
        if update.credentials is not None:
            config.encrypted_credentials = encrypt_credentials(update.credentials)

        await self.db.flush()

        logger.info("Updated connector %s", connector_id)
        return self._connector_to_response(connector)

    async def delete_connector(self, connector_id: uuid.UUID) -> None:
        """Delete a connector, blocked if active pipelines reference it.

        Args:
            connector_id: The connector UUID.

        Raises:
            ConnectorNotFoundError: If connector doesn't exist.
            ConnectorDeletionBlockedError: If active pipelines reference this connector.
        """
        connector = await self._get_connector_model(connector_id)

        # Check for dependent pipelines
        dependent_pipelines = await self._get_dependent_pipelines(connector_id)
        if dependent_pipelines:
            raise ConnectorDeletionBlockedError(dependent_pipelines)

        # Delete config first (child), then connector
        if connector.config:
            await self.db.delete(connector.config)
        await self.db.delete(connector)
        await self.db.flush()

        # Clean up circuit breaker state
        circuit_breaker_registry.remove(str(connector_id))

        logger.info("Deleted connector %s", connector_id)

    async def test_connection(self, connector_id: uuid.UUID) -> ConnectionTestResult:
        """Test connectivity to the connector's target system.

        Decrypts credentials, attempts connection with a 30-second timeout,
        and clears decrypted credentials from memory within 5 seconds.

        Args:
            connector_id: The connector UUID.

        Returns:
            ConnectionTestResult indicating success or failure.

        Raises:
            ConnectorNotFoundError: If connector doesn't exist.
        """
        connector = await self._get_connector_model(connector_id)
        config = connector.config

        # Decrypt credentials for internal use
        credentials = None
        if config and config.encrypted_credentials:
            credentials = decrypt_credentials(config.encrypted_credentials)

        start_time = time.time()
        tested_at = datetime.now(timezone.utc)

        try:
            success, message = await asyncio.wait_for(
                self._perform_connection_test(
                    connector_type=connector.type,
                    host=config.host if config else None,
                    port=config.port if config else None,
                    database_name=config.database_name if config else None,
                    credentials=credentials,
                    extra_params=config.extra_params if config else None,
                ),
                timeout=CONNECTION_TEST_TIMEOUT_SECONDS,
            )
            latency_ms = (time.time() - start_time) * 1000
        except asyncio.TimeoutError:
            success = False
            message = f"Connection test timed out after {CONNECTION_TEST_TIMEOUT_SECONDS} seconds"
            latency_ms = CONNECTION_TEST_TIMEOUT_SECONDS * 1000
        except Exception as e:
            success = False
            message = f"Connection test failed: {str(e)}"
            latency_ms = (time.time() - start_time) * 1000
        finally:
            # Clear decrypted credentials from memory
            _schedule_credential_cleanup(credentials)

        return ConnectionTestResult(
            success=success,
            message=message,
            latency_ms=round(latency_ms, 2),
            tested_at=tested_at,
        )

    async def health_check(self, connector_id: uuid.UUID) -> HealthStatus:
        """Perform a health check with circuit breaker protection.

        If the circuit is OPEN, returns cached failure without attempting connection.
        If CLOSED or HALF_OPEN, attempts connection and updates circuit state.

        Args:
            connector_id: The connector UUID.

        Returns:
            HealthStatus with circuit breaker info.

        Raises:
            ConnectorNotFoundError: If connector doesn't exist.
        """
        connector = await self._get_connector_model(connector_id)
        connector_id_str = str(connector_id)

        # Check circuit breaker state
        if not circuit_breaker_registry.is_call_allowed(connector_id_str):
            # Circuit is OPEN — return cached failure
            cb_info = circuit_breaker_registry.get_info(connector_id_str)
            return HealthStatus(
                connector_id=connector_id,
                status="unhealthy",
                circuit_breaker_state=cb_info["state"],
                failure_count=cb_info["failure_count"],
                last_check_time=datetime.now(timezone.utc),
                message="Circuit breaker is OPEN. Health check skipped. Will retry after recovery timeout.",
            )

        # Attempt health check
        test_result = await self.test_connection(connector_id)

        if test_result.success:
            circuit_breaker_registry.record_success(connector_id_str)
            connector.status = "active"
            await self.db.flush()

            cb_info = circuit_breaker_registry.get_info(connector_id_str)
            return HealthStatus(
                connector_id=connector_id,
                status="healthy",
                circuit_breaker_state=cb_info["state"],
                failure_count=cb_info["failure_count"],
                last_check_time=test_result.tested_at,
                message="Connection successful",
            )
        else:
            circuit_breaker_registry.record_failure(connector_id_str)

            # Update connector status if circuit opened
            cb_info = circuit_breaker_registry.get_info(connector_id_str)
            if cb_info["state"] == CircuitState.OPEN.value:
                connector.status = "unhealthy"
                await self.db.flush()

            return HealthStatus(
                connector_id=connector_id,
                status="unhealthy",
                circuit_breaker_state=cb_info["state"],
                failure_count=cb_info["failure_count"],
                last_check_time=test_result.tested_at,
                message=test_result.message,
            )

    async def get_decrypted_credentials(self, connector_id: uuid.UUID) -> dict[str, Any]:
        """Decrypt credentials for internal pipeline execution use only.

        WARNING: Caller is responsible for clearing the returned dict from memory
        within 5 seconds of use.

        Args:
            connector_id: The connector UUID.

        Returns:
            Decrypted credentials dictionary.

        Raises:
            ConnectorNotFoundError: If connector doesn't exist.
            ConnectorServiceError: If no credentials are stored.
        """
        connector = await self._get_connector_model(connector_id)
        config = connector.config

        if not config or not config.encrypted_credentials:
            raise ConnectorServiceError(
                "No credentials stored for this connector",
                code="NO_CREDENTIALS",
            )

        return decrypt_credentials(config.encrypted_credentials)

    # --- Private helpers ---

    async def _get_connector_model(self, connector_id: uuid.UUID) -> Connector:
        """Fetch a connector by ID with its config relationship loaded.

        Raises:
            ConnectorNotFoundError: If not found.
        """
        result = await self.db.execute(
            select(Connector)
            .options(selectinload(Connector.config))
            .where(Connector.id == connector_id)
        )
        connector = result.scalar_one_or_none()
        if connector is None:
            raise ConnectorNotFoundError(connector_id)
        return connector

    async def _get_dependent_pipelines(
        self, connector_id: uuid.UUID
    ) -> list[DependentPipelineInfo]:
        """Find active pipelines that reference this connector.

        Checks pipeline_nodes configs for connector_id references.
        """
        # Query pipeline nodes that reference this connector in their config
        # Connectors are referenced in node configs as connector_id
        connector_id_str = str(connector_id)

        # Search for pipelines with nodes that reference this connector
        # Using JSONB containment operator
        result = await self.db.execute(
            select(Pipeline)
            .join(PipelineNode, Pipeline.id == PipelineNode.pipeline_id)
            .where(
                Pipeline.status.in_(["active", "draft", "scheduled"]),
                PipelineNode.config.op("@>")(
                    f'{{"connector_id": "{connector_id_str}"}}'
                ),
            )
            .distinct()
        )
        pipelines = result.scalars().all()

        return [
            DependentPipelineInfo(
                pipeline_id=p.id,
                pipeline_name=p.name,
                status=p.status,
            )
            for p in pipelines
        ]

    async def _perform_connection_test(
        self,
        connector_type: str,
        host: str | None,
        port: int | None,
        database_name: str | None,
        credentials: dict | None,
        extra_params: dict | None,
    ) -> tuple[bool, str]:
        """Attempt to connect to the target system based on connector type.

        Returns:
            Tuple of (success: bool, message: str).
        """
        if connector_type == "postgresql":
            return await self._test_postgresql(host, port, database_name, credentials)
        elif connector_type == "mysql":
            return await self._test_mysql(host, port, database_name, credentials)
        elif connector_type == "clickhouse":
            return await self._test_clickhouse(host, port, database_name, credentials)
        elif connector_type == "csv":
            return await self._test_file_connector("CSV", extra_params)
        elif connector_type == "excel":
            return await self._test_file_connector("Excel", extra_params)
        elif connector_type == "rest_api":
            return await self._test_rest_api(host, credentials, extra_params)
        else:
            return False, f"Unsupported connector type: {connector_type}"

    async def _test_postgresql(
        self,
        host: str | None,
        port: int | None,
        database_name: str | None,
        credentials: dict | None,
    ) -> tuple[bool, str]:
        """Test PostgreSQL connectivity."""
        if not host:
            return False, "Host is required for PostgreSQL connection"

        username = credentials.get("username", "") if credentials else ""
        password = credentials.get("password", "") if credentials else ""
        db_port = port or 5432
        db_name = database_name or "postgres"

        try:
            import asyncpg

            conn = await asyncpg.connect(
                host=host,
                port=db_port,
                user=username,
                password=password,
                database=db_name,
                timeout=CONNECTION_TEST_TIMEOUT_SECONDS,
            )
            await conn.execute("SELECT 1")
            await conn.close()
            return True, "PostgreSQL connection successful"
        except Exception as e:
            return False, f"PostgreSQL connection failed: {str(e)}"

    async def _test_mysql(
        self,
        host: str | None,
        port: int | None,
        database_name: str | None,
        credentials: dict | None,
    ) -> tuple[bool, str]:
        """Test MySQL connectivity."""
        if not host:
            return False, "Host is required for MySQL connection"

        username = credentials.get("username", "") if credentials else ""
        password = credentials.get("password", "") if credentials else ""
        db_port = port or 3306
        db_name = database_name or ""

        try:
            # Use asyncio subprocess to test with mysql client or aiomysql
            # For now, we attempt a basic TCP connection as a health probe
            reader, writer = await asyncio.open_connection(host, db_port)
            writer.close()
            await writer.wait_closed()
            return True, "MySQL connection successful (TCP connectivity verified)"
        except Exception as e:
            return False, f"MySQL connection failed: {str(e)}"

    async def _test_clickhouse(
        self,
        host: str | None,
        port: int | None,
        database_name: str | None,
        credentials: dict | None,
    ) -> tuple[bool, str]:
        """Test ClickHouse connectivity via HTTP interface."""
        if not host:
            return False, "Host is required for ClickHouse connection"

        ch_port = port or 8123

        try:
            import httpx

            url = f"http://{host}:{ch_port}/ping"
            async with httpx.AsyncClient(timeout=CONNECTION_TEST_TIMEOUT_SECONDS) as client:
                response = await client.get(url)
                if response.status_code == 200:
                    return True, "ClickHouse connection successful"
                else:
                    return False, f"ClickHouse returned status {response.status_code}"
        except Exception as e:
            return False, f"ClickHouse connection failed: {str(e)}"

    async def _test_file_connector(
        self, file_type: str, extra_params: dict | None
    ) -> tuple[bool, str]:
        """Test file-based connector (CSV/Excel) — validates path accessibility."""
        if not extra_params:
            return False, f"{file_type} connector requires 'file_path' in extra_params"

        file_path = extra_params.get("file_path")
        if not file_path:
            return False, f"{file_type} connector requires 'file_path' in extra_params"

        import os

        if os.path.exists(file_path):
            return True, f"{file_type} file accessible: {file_path}"
        else:
            return False, f"{file_type} file not found: {file_path}"

    async def _test_rest_api(
        self,
        host: str | None,
        credentials: dict | None,
        extra_params: dict | None,
    ) -> tuple[bool, str]:
        """Test REST API connector connectivity."""
        from backend.app.core.config import settings

        if settings.air_gapped_mode:
            return False, "REST API connectors are unavailable in air-gapped mode"

        if not host:
            return False, "URL/host is required for REST API connection"

        try:
            import httpx

            headers = {}
            if credentials:
                api_key = credentials.get("api_key")
                if api_key:
                    headers["Authorization"] = f"Bearer {api_key}"

            async with httpx.AsyncClient(timeout=CONNECTION_TEST_TIMEOUT_SECONDS) as client:
                response = await client.get(host, headers=headers)
                if response.status_code < 500:
                    return True, f"REST API reachable (HTTP {response.status_code})"
                else:
                    return False, f"REST API returned server error: HTTP {response.status_code}"
        except Exception as e:
            return False, f"REST API connection failed: {str(e)}"


# --- Utility functions ---


def _clear_dict(d: dict | None) -> None:
    """Clear dictionary values from memory."""
    if d is None:
        return
    for key in list(d.keys()):
        d[key] = None
    d.clear()


def _schedule_credential_cleanup(credentials: dict | None) -> None:
    """Schedule clearing of decrypted credentials from memory.

    Clears the dict immediately and triggers garbage collection.
    The 5-second requirement is met because we clear synchronously here
    (well within the 5-second window) and force GC.
    """
    if credentials is None:
        return
    _clear_dict(credentials)
    # Request garbage collection to reclaim memory
    gc.collect()


def get_connector_service(db: AsyncSession) -> ConnectorService:
    """Factory function for dependency injection of ConnectorService."""
    return ConnectorService(db)
