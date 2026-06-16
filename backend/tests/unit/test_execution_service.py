"""Unit tests for PipelineExecutionService — execution, polling, retry, lineage.

Tests:
- execute_pipeline validates connectors, compiles DAG, creates run record
- execute_pipeline rejects when connectors are unhealthy
- execute_pipeline rejects when DAG compilation fails
- poll_execution_status returns current status
- poll_execution_status updates run from Dagster
- retry_execution increments retry count
- retry_execution rejects when retry limit exceeded (max 3)
- retry_execution rejects non-failed runs
- record_lineage_events creates events for data movement steps
- execute_with_db_retry retries with exponential backoff
- execute_with_db_retry fails after 3 attempts

Requirements: 6.1, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 16.5
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.services.execution_service import (
    CompilationError,
    ConnectorUnhealthyError,
    DatabaseConnectionError,
    ExecutionServiceError,
    MockDagsterClient,
    PipelineExecutionService,
    PipelineRunNotFoundError,
    RetryLimitExceededError,
    DB_RETRY_BASE_INTERVAL_SECONDS,
    DB_RETRY_MAX_ATTEMPTS,
    MAX_RETRIES,
)


# --- Helpers ---


def _make_pipeline_model(
    pipeline_id=None,
    name="Test Pipeline",
    current_version=1,
    nodes=None,
    edges=None,
):
    """Create a mock Pipeline model for testing."""
    if pipeline_id is None:
        pipeline_id = uuid.uuid4()
    if nodes is None:
        nodes = []
    if edges is None:
        edges = []

    pipeline = MagicMock()
    pipeline.id = pipeline_id
    pipeline.name = name
    pipeline.current_version = current_version
    pipeline.nodes = nodes
    pipeline.edges = edges
    return pipeline


def _make_node_model(
    node_id=None,
    version=1,
    node_type="source",
    node_subtype="postgresql_source",
    config=None,
):
    """Create a mock PipelineNode model."""
    if node_id is None:
        node_id = uuid.uuid4()
    if config is None:
        config = {"connector_id": str(uuid.uuid4()), "table_name": "test_table"}

    node = MagicMock()
    node.id = node_id
    node.version = version
    node.node_type = node_type
    node.node_subtype = node_subtype
    node.config = config
    node.position_x = 100.0
    node.position_y = 200.0
    return node


def _make_edge_model(version=1, source_node_id=None, target_node_id=None):
    """Create a mock PipelineEdge model."""
    if source_node_id is None:
        source_node_id = uuid.uuid4()
    if target_node_id is None:
        target_node_id = uuid.uuid4()

    edge = MagicMock()
    edge.version = version
    edge.source_node_id = source_node_id
    edge.target_node_id = target_node_id
    return edge


def _make_run_model(
    run_id=None,
    pipeline_id=None,
    status="queued",
    retry_count=0,
    pipeline_version=1,
    trigger_type="manual",
    triggered_by=None,
):
    """Create a mock PipelineRun model."""
    if run_id is None:
        run_id = uuid.uuid4()
    if pipeline_id is None:
        pipeline_id = uuid.uuid4()
    if triggered_by is None:
        triggered_by = uuid.uuid4()

    run = MagicMock()
    run.id = run_id
    run.pipeline_id = pipeline_id
    run.pipeline_version = pipeline_version
    run.status = status
    run.trigger_type = trigger_type
    run.triggered_by = triggered_by
    run.retry_count = retry_count
    run.node_row_counts = None
    run.started_at = None
    run.completed_at = None
    run.duration_ms = None
    run.created_at = datetime.now(timezone.utc)
    run.updated_at = datetime.now(timezone.utc)
    return run


# --- Tests ---


class TestExecutePipeline:
    """Tests for execute_pipeline method."""

    @pytest.mark.asyncio
    async def test_execute_pipeline_success(self):
        """Execution should validate connectors, compile DAG, create run, and submit to Dagster."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        dagster_client = AsyncMock(spec=MockDagsterClient)
        dagster_client.submit_execution = AsyncMock(return_value="dagster-run-abc123")

        service = PipelineExecutionService(db=db, dagster_client=dagster_client)

        # Setup pipeline with source and destination nodes
        source_node = _make_node_model(
            node_type="source",
            node_subtype="postgresql_source",
            config={"connector_id": str(uuid.uuid4()), "table_name": "users"},
        )
        dest_node = _make_node_model(
            node_type="destination",
            node_subtype="postgresql_destination",
            config={
                "connector_id": str(uuid.uuid4()),
                "table_name": "users_copy",
                "write_mode": "append",
            },
        )
        edge = _make_edge_model(
            source_node_id=source_node.id,
            target_node_id=dest_node.id,
        )

        pipeline = _make_pipeline_model(
            nodes=[source_node, dest_node],
            edges=[edge],
        )

        service._get_pipeline_with_nodes = AsyncMock(return_value=pipeline)
        service._validate_connector_health = AsyncMock(return_value=[])

        # Patch PipelineRun to provide an id and timestamps on creation
        run_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        with patch("backend.app.services.execution_service.PipelineRun") as MockRun:
            mock_run_instance = MagicMock()
            mock_run_instance.id = run_id
            mock_run_instance.pipeline_id = pipeline.id
            mock_run_instance.pipeline_version = 1
            mock_run_instance.status = "queued"
            mock_run_instance.trigger_type = "manual"
            mock_run_instance.triggered_by = uuid.uuid4()
            mock_run_instance.retry_count = 0
            mock_run_instance.node_row_counts = None
            mock_run_instance.started_at = None
            mock_run_instance.completed_at = None
            mock_run_instance.duration_ms = None
            mock_run_instance.created_at = now
            mock_run_instance.updated_at = now
            MockRun.return_value = mock_run_instance

            user_id = uuid.uuid4()
            result = await service.execute_pipeline(pipeline.id, user_id)

        assert result.status == "queued"
        assert result.trigger_type == "manual"
        assert result.retry_count == 0
        assert result.id == run_id
        dagster_client.submit_execution.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_rejects_unhealthy_connectors(self):
        """Execution should fail if any referenced connector is unhealthy."""
        db = AsyncMock()
        service = PipelineExecutionService(db=db)

        source_node = _make_node_model(
            node_type="source",
            node_subtype="postgresql_source",
            config={"connector_id": str(uuid.uuid4()), "table_name": "users"},
        )
        dest_node = _make_node_model(
            node_type="destination",
            node_subtype="postgresql_destination",
            config={
                "connector_id": str(uuid.uuid4()),
                "table_name": "out",
                "write_mode": "append",
            },
        )
        edge = _make_edge_model(
            source_node_id=source_node.id,
            target_node_id=dest_node.id,
        )

        pipeline = _make_pipeline_model(nodes=[source_node, dest_node], edges=[edge])
        service._get_pipeline_with_nodes = AsyncMock(return_value=pipeline)
        service._validate_connector_health = AsyncMock(
            return_value=[
                {"id": uuid.uuid4(), "name": "Bad DB", "status": "unhealthy", "type": "postgresql"}
            ]
        )

        with pytest.raises(ConnectorUnhealthyError) as exc_info:
            await service.execute_pipeline(pipeline.id, uuid.uuid4())

        assert len(exc_info.value.unhealthy_connectors) == 1
        assert exc_info.value.code == "CONNECTOR_UNHEALTHY"

    @pytest.mark.asyncio
    async def test_execute_rejects_compilation_failure(self):
        """Execution should fail if DAG compilation fails."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        service = PipelineExecutionService(db=db)

        # Create a pipeline that will fail compilation (empty nodes/edges)
        pipeline = _make_pipeline_model(nodes=[], edges=[])
        service._get_pipeline_with_nodes = AsyncMock(return_value=pipeline)
        service._validate_connector_health = AsyncMock(return_value=[])

        with pytest.raises(CompilationError) as exc_info:
            await service.execute_pipeline(pipeline.id, uuid.uuid4())

        assert exc_info.value.code == "COMPILATION_FAILED"


class TestPollExecutionStatus:
    """Tests for poll_execution_status method."""

    @pytest.mark.asyncio
    async def test_poll_returns_terminal_status_without_dagster_call(self):
        """If run is already succeeded/failed, return directly without querying Dagster."""
        db = AsyncMock()
        dagster_client = AsyncMock(spec=MockDagsterClient)

        service = PipelineExecutionService(db=db, dagster_client=dagster_client)

        run = _make_run_model(status="succeeded")
        run.started_at = datetime.now(timezone.utc)
        run.completed_at = datetime.now(timezone.utc)
        run.duration_ms = 5000

        service._get_run = AsyncMock(return_value=run)

        result = await service.poll_execution_status(run.id)

        assert result.status == "succeeded"
        dagster_client.get_run_status.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_updates_run_from_dagster(self):
        """Should query Dagster and update the run status when not terminal."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        dagster_client = AsyncMock(spec=MockDagsterClient)
        dagster_client.get_run_status = AsyncMock(return_value={
            "status": "running",
            "error_message": None,
            "failing_node": None,
            "node_row_counts": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": None,
        })

        service = PipelineExecutionService(db=db, dagster_client=dagster_client)

        run = _make_run_model(status="queued")
        service._get_run = AsyncMock(return_value=run)
        service._get_dagster_run_id = AsyncMock(return_value="dagster-run-123")

        result = await service.poll_execution_status(run.id)

        assert result.status == "running"
        dagster_client.get_run_status.assert_called_once_with("dagster-run-123")

    @pytest.mark.asyncio
    async def test_poll_not_found_raises(self):
        """Should raise PipelineRunNotFoundError for unknown run ID."""
        db = AsyncMock()
        service = PipelineExecutionService(db=db)
        service._get_run = AsyncMock(
            side_effect=PipelineRunNotFoundError(uuid.uuid4())
        )

        with pytest.raises(PipelineRunNotFoundError):
            await service.poll_execution_status(uuid.uuid4())


class TestRetryExecution:
    """Tests for retry_execution method."""

    @pytest.mark.asyncio
    async def test_retry_increments_count_and_requeues(self):
        """Retry should increment retry_count and set status back to queued."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        dagster_client = AsyncMock(spec=MockDagsterClient)
        dagster_client.submit_reexecution = AsyncMock(return_value="dagster-rerun-xyz")

        service = PipelineExecutionService(db=db, dagster_client=dagster_client)

        run = _make_run_model(status="failed", retry_count=1)
        service._get_run = AsyncMock(return_value=run)
        service._get_dagster_run_id = AsyncMock(return_value="dagster-run-original")

        user_id = uuid.uuid4()
        result = await service.retry_execution(run.id, user_id)

        assert result.status == "queued"
        assert result.retry_count == 2
        dagster_client.submit_reexecution.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_rejects_at_max_limit(self):
        """Retry should raise RetryLimitExceededError when retry_count >= 3."""
        db = AsyncMock()
        service = PipelineExecutionService(db=db)

        run = _make_run_model(status="failed", retry_count=3)
        service._get_run = AsyncMock(return_value=run)

        with pytest.raises(RetryLimitExceededError) as exc_info:
            await service.retry_execution(run.id, uuid.uuid4())

        assert exc_info.value.code == "RETRY_LIMIT_EXCEEDED"

    @pytest.mark.asyncio
    async def test_retry_rejects_non_failed_run(self):
        """Retry should only be allowed on failed runs."""
        db = AsyncMock()
        service = PipelineExecutionService(db=db)

        run = _make_run_model(status="running", retry_count=0)
        service._get_run = AsyncMock(return_value=run)

        with pytest.raises(ExecutionServiceError) as exc_info:
            await service.retry_execution(run.id, uuid.uuid4())

        assert exc_info.value.code == "INVALID_RETRY_STATE"

    @pytest.mark.asyncio
    async def test_retry_limit_is_exactly_three(self):
        """The system should allow exactly 3 retries (retry_count 0, 1, 2 → allow; 3 → reject)."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        dagster_client = AsyncMock(spec=MockDagsterClient)
        dagster_client.submit_reexecution = AsyncMock(return_value="dagster-rerun-new")

        service = PipelineExecutionService(db=db, dagster_client=dagster_client)

        # retry_count=2 should still be allowed (3rd retry)
        run = _make_run_model(status="failed", retry_count=2)
        service._get_run = AsyncMock(return_value=run)
        service._get_dagster_run_id = AsyncMock(return_value="dagster-run-123")

        result = await service.retry_execution(run.id, uuid.uuid4())
        assert result.retry_count == 3

        # retry_count=3 should be rejected (4th attempt)
        run2 = _make_run_model(status="failed", retry_count=3)
        service._get_run = AsyncMock(return_value=run2)

        with pytest.raises(RetryLimitExceededError):
            await service.retry_execution(run2.id, uuid.uuid4())


class TestRecordLineageEvents:
    """Tests for record_lineage_events method."""

    @pytest.mark.asyncio
    async def test_records_events_for_source_to_dest(self):
        """Should create a lineage event for each source→destination pair."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        service = PipelineExecutionService(db=db)

        run = _make_run_model(status="succeeded")
        service._get_run = AsyncMock(return_value=run)

        # Nodes: 1 source, 1 transform, 2 destinations
        source = _make_node_model(
            node_type="source",
            node_subtype="postgresql_source",
            config={"connector_id": str(uuid.uuid4()), "table_name": "users"},
        )
        transform = _make_node_model(
            node_type="transformation",
            node_subtype="filter_rows",
            config={"condition": "active = true"},
        )
        dest1 = _make_node_model(
            node_type="destination",
            node_subtype="postgresql_destination",
            config={"connector_id": str(uuid.uuid4()), "table_name": "active_users"},
        )
        dest2 = _make_node_model(
            node_type="destination",
            node_subtype="clickhouse_destination",
            config={"connector_id": str(uuid.uuid4()), "table_name": "analytics_users"},
        )

        user_id = uuid.uuid4()
        events = await service.record_lineage_events(
            run.id,
            [source, transform, dest1, dest2],
            user_id,
        )

        # 1 source × 2 destinations = 2 lineage events
        assert len(events) == 2
        assert db.add.call_count >= 2

    @pytest.mark.asyncio
    async def test_lineage_event_fields_populated(self):
        """Each lineage event should have all required fields populated."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        service = PipelineExecutionService(db=db)

        run = _make_run_model(status="succeeded")
        service._get_run = AsyncMock(return_value=run)

        source = _make_node_model(
            node_type="source",
            node_subtype="mysql_source",
            config={"connector_id": str(uuid.uuid4()), "table_name": "orders"},
        )
        dest = _make_node_model(
            node_type="destination",
            node_subtype="clickhouse_destination",
            config={"connector_id": str(uuid.uuid4()), "table_name": "order_archive"},
        )

        user_id = uuid.uuid4()
        events = await service.record_lineage_events(run.id, [source, dest], user_id)

        assert len(events) == 1
        event = events[0]
        assert event.source_system == "mysql"
        assert event.source_table == "orders"
        assert event.destination_system == "clickhouse"
        assert event.destination_table == "order_archive"
        assert event.pipeline_id == run.pipeline_id
        assert event.execution_id == run.id
        assert event.triggered_by == user_id
        assert event.timestamp is not None


class TestDatabaseConnectionRetry:
    """Tests for execute_with_db_retry — exponential backoff (Requirement 16.5)."""

    @pytest.mark.asyncio
    async def test_succeeds_on_first_attempt(self):
        """Should return result immediately if first attempt succeeds."""
        db = AsyncMock()
        service = PipelineExecutionService(db=db)

        operation = AsyncMock(return_value="success")
        result = await service.execute_with_db_retry(operation)

        assert result == "success"
        assert operation.call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_connection_error(self):
        """Should retry on ConnectionError with exponential backoff."""
        db = AsyncMock()
        service = PipelineExecutionService(db=db)

        # Fails twice, succeeds on third attempt
        operation = AsyncMock(
            side_effect=[ConnectionError("refused"), ConnectionError("timeout"), "success"]
        )

        with patch("backend.app.services.execution_service.asyncio.sleep") as mock_sleep:
            result = await service.execute_with_db_retry(operation)

        assert result == "success"
        assert operation.call_count == 3
        # Verify exponential backoff delays: 1s, 2s
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1)  # 1s * 2^0
        mock_sleep.assert_any_call(2)  # 1s * 2^1

    @pytest.mark.asyncio
    async def test_fails_after_max_retries(self):
        """Should raise DatabaseConnectionError after 3 failed attempts."""
        db = AsyncMock()
        service = PipelineExecutionService(db=db)

        operation = AsyncMock(
            side_effect=[
                ConnectionError("attempt 1"),
                ConnectionError("attempt 2"),
                ConnectionError("attempt 3"),
            ]
        )

        with patch("backend.app.services.execution_service.asyncio.sleep"):
            with pytest.raises(DatabaseConnectionError) as exc_info:
                await service.execute_with_db_retry(operation)

        assert exc_info.value.code == "DB_CONNECTION_FAILED"
        assert operation.call_count == 3

    @pytest.mark.asyncio
    async def test_exponential_backoff_delays(self):
        """Backoff delays should be 1s, 2s, 4s (base * 2^attempt)."""
        db = AsyncMock()
        service = PipelineExecutionService(db=db)

        operation = AsyncMock(
            side_effect=[OSError("err1"), OSError("err2"), OSError("err3")]
        )

        with patch("backend.app.services.execution_service.asyncio.sleep") as mock_sleep:
            with pytest.raises(DatabaseConnectionError):
                await service.execute_with_db_retry(operation)

        # 3 failures → 3 sleep calls with backoff: 1s, 2s, 4s
        # Actually: attempts 0,1,2 → sleeps at 1, 2, 4 (but only called before retry)
        # attempt 0 fails → sleep(1) → attempt 1 fails → sleep(2) → attempt 2 fails → raise
        assert mock_sleep.call_count == 2  # Only 2 sleeps (no sleep after final failure)
        calls = [c.args[0] for c in mock_sleep.call_args_list]
        assert calls == [1, 2]  # 1s * 2^0, 1s * 2^1

    @pytest.mark.asyncio
    async def test_retries_on_os_and_io_errors(self):
        """Should retry on OSError and IOError in addition to ConnectionError."""
        db = AsyncMock()
        service = PipelineExecutionService(db=db)

        operation = AsyncMock(
            side_effect=[OSError("network"), IOError("disk"), "success"]
        )

        with patch("backend.app.services.execution_service.asyncio.sleep"):
            result = await service.execute_with_db_retry(operation)

        assert result == "success"
        assert operation.call_count == 3


class TestMockDagsterClient:
    """Tests for the MockDagsterClient implementation."""

    @pytest.mark.asyncio
    async def test_submit_execution_returns_run_id(self):
        """Mock client should return a string run ID."""
        client = MockDagsterClient()
        result = await client.submit_execution("test_job", "code...")
        assert isinstance(result, str)
        assert result.startswith("dagster-run-")

    @pytest.mark.asyncio
    async def test_get_run_status_returns_succeeded(self):
        """Mock client should return a succeeded status dict."""
        client = MockDagsterClient()
        result = await client.get_run_status("dagster-run-abc")
        assert result["status"] == "succeeded"
        assert result["error_message"] is None

    @pytest.mark.asyncio
    async def test_submit_reexecution_returns_rerun_id(self):
        """Mock client should return a new run ID for re-execution."""
        client = MockDagsterClient()
        result = await client.submit_reexecution("dagster-run-original")
        assert isinstance(result, str)
        assert result.startswith("dagster-rerun-")


class TestExecutionConstants:
    """Tests for execution service configuration constants."""

    def test_max_retries_is_three(self):
        """Maximum retries should be exactly 3."""
        assert MAX_RETRIES == 3

    def test_db_retry_max_attempts_is_three(self):
        """Database retry max attempts should be exactly 3."""
        assert DB_RETRY_MAX_ATTEMPTS == 3

    def test_db_retry_base_interval_is_one_second(self):
        """Database retry base interval should be 1 second."""
        assert DB_RETRY_BASE_INTERVAL_SECONDS == 1
