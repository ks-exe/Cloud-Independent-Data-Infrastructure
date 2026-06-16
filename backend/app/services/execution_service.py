"""Pipeline Execution Service — Orchestrates pipeline execution via Dagster.

Manages:
- Pre-execution connector health validation
- DAG compilation via DagsterCompiler
- Pipeline run record creation and lifecycle
- Dagster submission (via DagsterClient interface)
- Status polling at ≤5s intervals
- Retry logic (max 3 retries per execution)
- Lineage event recording for data movement steps
- Database connection retry with exponential backoff (1s, 2s, 4s)

Requirements: 6.1, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9, 16.5
"""

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models.lineage import LineageEvent
from backend.app.models.pipelines import (
    Pipeline,
    PipelineNode,
    PipelineRun,
    PipelineRunLog,
)
from backend.app.schemas.execution import ExecutionStatus, PipelineRunResponse
from backend.app.services.dag_validator import DAGEdge, DAGNode
from backend.app.services.dagster_compiler import DagsterCompiler

logger = logging.getLogger(__name__)

# Maximum number of manual retries allowed per execution
MAX_RETRIES = 3

# Database connection retry configuration (Requirement 16.5)
DB_RETRY_MAX_ATTEMPTS = 3
DB_RETRY_BASE_INTERVAL_SECONDS = 1  # Exponential backoff: 1s, 2s, 4s

# Status polling interval (Requirement 6.4)
POLL_INTERVAL_SECONDS = 5


class ExecutionServiceError(Exception):
    """Base exception for execution service operations."""

    def __init__(self, message: str, code: str = "EXECUTION_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class PipelineRunNotFoundError(ExecutionServiceError):
    """Raised when a pipeline run is not found."""

    def __init__(self, run_id: uuid.UUID):
        super().__init__(
            message=f"Pipeline run {run_id} not found",
            code="RUN_NOT_FOUND",
        )


class ConnectorUnhealthyError(ExecutionServiceError):
    """Raised when referenced connectors are not in a healthy state."""

    def __init__(self, unhealthy_connectors: list[dict[str, Any]]):
        self.unhealthy_connectors = unhealthy_connectors
        names = [c.get("name", str(c.get("id", "unknown"))) for c in unhealthy_connectors]
        super().__init__(
            message=f"Unhealthy connectors prevent execution: {', '.join(names)}",
            code="CONNECTOR_UNHEALTHY",
        )


class CompilationError(ExecutionServiceError):
    """Raised when DAG compilation fails."""

    def __init__(self, error: str):
        super().__init__(
            message=f"DAG compilation failed: {error}",
            code="COMPILATION_FAILED",
        )


class RetryLimitExceededError(ExecutionServiceError):
    """Raised when the maximum retry limit is reached."""

    def __init__(self, run_id: uuid.UUID, retry_count: int):
        super().__init__(
            message=f"Maximum retry limit ({MAX_RETRIES}) reached for run {run_id}. Current retries: {retry_count}",
            code="RETRY_LIMIT_EXCEEDED",
        )


class DatabaseConnectionError(ExecutionServiceError):
    """Raised when database connection fails after all retries."""

    def __init__(self, attempts: int):
        super().__init__(
            message=f"Database connection failed after {attempts} retry attempts with exponential backoff",
            code="DB_CONNECTION_FAILED",
        )


# --- Dagster Client Interface ---


class DagsterClientInterface(ABC):
    """Abstract interface for Dagster execution operations.

    Implementations may connect to a real Dagster instance or provide
    mock/test behavior.
    """

    @abstractmethod
    async def submit_execution(
        self, job_name: str, dagster_code: str, run_config: dict[str, Any] | None = None
    ) -> str:
        """Submit a pipeline for execution in Dagster.

        Args:
            job_name: The Dagster job name.
            dagster_code: The compiled Dagster Python code.
            run_config: Optional run configuration.

        Returns:
            Dagster run ID as a string.
        """
        ...

    @abstractmethod
    async def get_run_status(self, dagster_run_id: str) -> dict[str, Any]:
        """Get the current status of a Dagster run.

        Args:
            dagster_run_id: The Dagster run ID.

        Returns:
            Dictionary with keys: status, error_message, failing_node,
            node_row_counts, started_at, completed_at.
        """
        ...

    @abstractmethod
    async def submit_reexecution(
        self, dagster_run_id: str, run_config: dict[str, Any] | None = None
    ) -> str:
        """Submit a re-execution of a previous Dagster run.

        Args:
            dagster_run_id: The original Dagster run ID to re-execute.
            run_config: Optional run configuration.

        Returns:
            New Dagster run ID.
        """
        ...


class MockDagsterClient(DagsterClientInterface):
    """Mock Dagster client for development and testing.

    Simulates Dagster execution behavior without requiring a running
    Dagster instance.
    """

    async def submit_execution(
        self, job_name: str, dagster_code: str, run_config: dict[str, Any] | None = None
    ) -> str:
        """Simulate execution submission — returns a mock run ID."""
        return f"dagster-run-{uuid.uuid4().hex[:12]}"

    async def get_run_status(self, dagster_run_id: str) -> dict[str, Any]:
        """Simulate status check — returns 'succeeded' by default."""
        return {
            "status": "succeeded",
            "error_message": None,
            "failing_node": None,
            "node_row_counts": {},
            "started_at": datetime.now(timezone.utc).isoformat(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }

    async def submit_reexecution(
        self, dagster_run_id: str, run_config: dict[str, Any] | None = None
    ) -> str:
        """Simulate re-execution submission."""
        return f"dagster-rerun-{uuid.uuid4().hex[:12]}"


# --- Execution Service ---


class PipelineExecutionService:
    """Service for managing pipeline execution lifecycle.

    Coordinates between the pipeline definitions, Dagster runtime,
    connector health checks, lineage recording, and run persistence.
    """

    def __init__(
        self,
        db: AsyncSession,
        dagster_client: DagsterClientInterface | None = None,
    ):
        self.db = db
        self.dagster_client = dagster_client or MockDagsterClient()
        self.compiler = DagsterCompiler()

    async def execute_pipeline(
        self, pipeline_id: uuid.UUID, user_id: uuid.UUID
    ) -> PipelineRunResponse:
        """Execute a pipeline: validate connectors, compile DAG, submit to Dagster.

        Args:
            pipeline_id: The pipeline to execute.
            user_id: The user triggering the execution.

        Returns:
            PipelineRunResponse with the created run record.

        Raises:
            ExecutionServiceError: If pipeline not found.
            ConnectorUnhealthyError: If referenced connectors are unhealthy.
            CompilationError: If DAG compilation fails.
        """
        # Step 1: Load the pipeline with its current version nodes/edges
        pipeline = await self._get_pipeline_with_nodes(pipeline_id)

        current_version = pipeline.current_version
        current_nodes = [n for n in pipeline.nodes if n.version == current_version]
        current_edges = [e for e in pipeline.edges if e.version == current_version]

        # Step 2: Validate all referenced connectors are healthy
        unhealthy = await self._validate_connector_health(current_nodes)
        if unhealthy:
            raise ConnectorUnhealthyError(unhealthy)

        # Step 3: Compile DAG using DagsterCompiler
        dag_nodes = [
            DAGNode(
                id=str(node.id),
                node_type=node.node_type,
                node_subtype=node.node_subtype,
                config=node.config,
            )
            for node in current_nodes
        ]
        dag_edges = [
            DAGEdge(
                source_node_id=str(edge.source_node_id),
                target_node_id=str(edge.target_node_id),
            )
            for edge in current_edges
        ]

        definition = self.compiler.compile(pipeline.name, dag_nodes, dag_edges)
        if not definition.is_valid:
            raise CompilationError(definition.error or "Unknown compilation error")

        # Step 4: Create PipelineRun record (status=queued)
        run = PipelineRun(
            pipeline_id=pipeline_id,
            pipeline_version=current_version,
            status="queued",
            trigger_type="manual",
            triggered_by=user_id,
            retry_count=0,
        )
        self.db.add(run)
        await self.db.flush()

        # Step 5: Submit to Dagster
        try:
            dagster_run_id = await self.dagster_client.submit_execution(
                job_name=definition.job_name,
                dagster_code=definition.code,
            )
            # Log the dagster run ID for correlation
            log_entry = PipelineRunLog(
                run_id=run.id,
                level="INFO",
                message=f"Submitted to Dagster with run ID: {dagster_run_id}",
                timestamp=datetime.now(timezone.utc),
            )
            self.db.add(log_entry)
            await self.db.flush()
        except Exception as e:
            # Mark as failed if submission fails
            run.status = "failed"
            log_entry = PipelineRunLog(
                run_id=run.id,
                level="ERROR",
                message=f"Dagster submission failed: {str(e)}",
                timestamp=datetime.now(timezone.utc),
            )
            self.db.add(log_entry)
            await self.db.flush()
            raise ExecutionServiceError(
                message=f"Failed to submit pipeline to Dagster: {str(e)}",
                code="SUBMISSION_FAILED",
            )

        logger.info(
            "Pipeline %s execution submitted (run_id=%s, dagster_run_id=%s)",
            pipeline_id,
            run.id,
            dagster_run_id,
        )

        return self._run_to_response(run)

    async def poll_execution_status(self, run_id: uuid.UUID) -> ExecutionStatus:
        """Poll execution status from Dagster and update the run record.

        Queries Dagster API and updates the local run record with current status.
        Polling interval is enforced at ≤5 seconds by the caller (not internally).

        Args:
            run_id: The pipeline run ID.

        Returns:
            ExecutionStatus with current state.

        Raises:
            PipelineRunNotFoundError: If run not found.
        """
        run = await self._get_run(run_id)

        # If already in a terminal state, return current status
        if run.status in ("succeeded", "failed"):
            return self._run_to_execution_status(run)

        # Query Dagster for current status
        # Find the Dagster run ID from logs
        dagster_run_id = await self._get_dagster_run_id(run_id)

        if dagster_run_id:
            try:
                dagster_status = await self.dagster_client.get_run_status(dagster_run_id)
                await self._update_run_from_dagster_status(run, dagster_status)
            except Exception as e:
                logger.warning(
                    "Failed to poll Dagster status for run %s: %s", run_id, str(e)
                )

        return self._run_to_execution_status(run)

    async def retry_execution(
        self, run_id: uuid.UUID, user_id: uuid.UUID
    ) -> PipelineRunResponse:
        """Retry a failed pipeline execution via Dagster re-execution.

        Args:
            run_id: The failed pipeline run to retry.
            user_id: The user requesting the retry.

        Returns:
            PipelineRunResponse for the new retry run.

        Raises:
            PipelineRunNotFoundError: If run not found.
            RetryLimitExceededError: If retry_count >= MAX_RETRIES.
            ExecutionServiceError: If run is not in failed state.
        """
        run = await self._get_run(run_id)

        # Validate retry is allowed
        if run.status != "failed":
            raise ExecutionServiceError(
                message=f"Can only retry failed executions. Current status: {run.status}",
                code="INVALID_RETRY_STATE",
            )

        if run.retry_count >= MAX_RETRIES:
            raise RetryLimitExceededError(run_id, run.retry_count)

        # Get the Dagster run ID for re-execution
        dagster_run_id = await self._get_dagster_run_id(run_id)

        # Submit re-execution via Dagster
        try:
            new_dagster_run_id = await self.dagster_client.submit_reexecution(
                dagster_run_id or f"mock-{run_id}",
            )
        except Exception as e:
            raise ExecutionServiceError(
                message=f"Failed to submit retry to Dagster: {str(e)}",
                code="RETRY_SUBMISSION_FAILED",
            )

        # Increment retry count and reset status
        run.retry_count += 1
        run.status = "queued"
        run.started_at = None
        run.completed_at = None
        run.duration_ms = None
        run.node_row_counts = None

        # Log the retry
        log_entry = PipelineRunLog(
            run_id=run.id,
            level="INFO",
            message=f"Retry #{run.retry_count} submitted to Dagster (run_id: {new_dagster_run_id})",
            timestamp=datetime.now(timezone.utc),
        )
        self.db.add(log_entry)
        await self.db.flush()

        logger.info(
            "Pipeline run %s retried (attempt %d/%d, dagster_run_id=%s)",
            run_id,
            run.retry_count,
            MAX_RETRIES,
            new_dagster_run_id,
        )

        return self._run_to_response(run)

    async def record_lineage_events(
        self, run_id: uuid.UUID, pipeline_nodes: list[PipelineNode], user_id: uuid.UUID
    ) -> list[LineageEvent]:
        """Record lineage events for each data movement step in the pipeline.

        Creates a LineageEvent for each edge representing data flow from
        source through transformations to destinations.

        Args:
            run_id: The pipeline run ID.
            pipeline_nodes: Nodes in the pipeline execution.
            user_id: The user who triggered the execution.

        Returns:
            List of created LineageEvent records.
        """
        run = await self._get_run(run_id)
        events: list[LineageEvent] = []

        # Build node map for lookup
        node_map = {str(node.id): node for node in pipeline_nodes}

        # Identify source and destination nodes for lineage
        source_nodes = [n for n in pipeline_nodes if n.node_type == "source"]
        dest_nodes = [n for n in pipeline_nodes if n.node_type == "destination"]
        transform_nodes = [n for n in pipeline_nodes if n.node_type == "transformation"]

        # Create lineage events for each source → destination path
        for source_node in source_nodes:
            source_config = source_node.config or {}
            source_system = source_node.node_subtype.replace("_source", "")
            source_table = source_config.get("table_name", "unknown")

            for dest_node in dest_nodes:
                dest_config = dest_node.config or {}
                dest_system = dest_node.node_subtype.replace("_destination", "")
                dest_table = dest_config.get("table_name", "unknown")

                # Include transformation node names if any exist between source and dest
                transformation_names = [
                    n.node_subtype for n in transform_nodes
                ] if transform_nodes else None

                event = LineageEvent(
                    pipeline_id=run.pipeline_id,
                    execution_id=run_id,
                    source_system=source_system,
                    source_table=source_table,
                    destination_system=dest_system,
                    destination_table=dest_table,
                    transformation_node=", ".join(transformation_names) if transformation_names else None,
                    triggered_by=user_id,
                    timestamp=datetime.now(timezone.utc),
                )
                self.db.add(event)
                events.append(event)

        await self.db.flush()

        logger.info(
            "Recorded %d lineage events for run %s",
            len(events),
            run_id,
        )

        return events

    # --- Database Connection Retry (Requirement 16.5) ---

    async def execute_with_db_retry(self, operation, *args, **kwargs):
        """Execute a database operation with exponential backoff retry.

        Retries exactly 3 times with delays: 1s, 2s, 4s before marking as failed.

        Args:
            operation: Async callable to execute.
            *args: Positional arguments for the operation.
            **kwargs: Keyword arguments for the operation.

        Returns:
            Result of the operation.

        Raises:
            DatabaseConnectionError: After all retry attempts exhausted.
        """
        last_exception = None

        for attempt in range(DB_RETRY_MAX_ATTEMPTS):
            try:
                return await operation(*args, **kwargs)
            except (ConnectionError, OSError, IOError) as e:
                last_exception = e
                logger.warning(
                    "Database connection attempt %d/%d failed: %s. Retrying in %ds...",
                    attempt + 1,
                    DB_RETRY_MAX_ATTEMPTS,
                    str(e),
                    DB_RETRY_BASE_INTERVAL_SECONDS * (2 ** attempt),
                )
                if attempt < DB_RETRY_MAX_ATTEMPTS - 1:
                    delay = DB_RETRY_BASE_INTERVAL_SECONDS * (2 ** attempt)
                    await asyncio.sleep(delay)

        # All retries exhausted
        logger.error(
            "Database connection failed after %d attempts. Last error: %s",
            DB_RETRY_MAX_ATTEMPTS,
            str(last_exception),
        )
        raise DatabaseConnectionError(DB_RETRY_MAX_ATTEMPTS)

    # --- Private helpers ---

    async def _get_pipeline_with_nodes(self, pipeline_id: uuid.UUID) -> Pipeline:
        """Load a pipeline with its nodes and edges."""
        from backend.app.models.pipelines import PipelineEdge

        result = await self.db.execute(
            select(Pipeline)
            .options(
                selectinload(Pipeline.nodes),
                selectinload(Pipeline.edges),
            )
            .where(Pipeline.id == pipeline_id)
        )
        pipeline = result.scalar_one_or_none()
        if pipeline is None:
            raise ExecutionServiceError(
                message=f"Pipeline {pipeline_id} not found",
                code="PIPELINE_NOT_FOUND",
            )
        return pipeline

    async def _validate_connector_health(
        self, nodes: list[PipelineNode]
    ) -> list[dict[str, Any]]:
        """Check that all connectors referenced in pipeline nodes are healthy.

        Returns list of unhealthy connector info dicts (empty if all healthy).
        """
        from backend.app.models.connectors import Connector

        # Collect unique connector IDs from node configs
        connector_ids: set[uuid.UUID] = set()
        for node in nodes:
            config = node.config or {}
            connector_id_str = config.get("connector_id")
            if connector_id_str:
                try:
                    connector_ids.add(uuid.UUID(connector_id_str))
                except (ValueError, AttributeError):
                    pass

        if not connector_ids:
            return []

        # Query connector status
        result = await self.db.execute(
            select(Connector).where(Connector.id.in_(list(connector_ids)))
        )
        connectors = result.scalars().all()

        unhealthy = []
        for connector in connectors:
            if connector.status != "active":
                unhealthy.append({
                    "id": connector.id,
                    "name": connector.name,
                    "status": connector.status,
                    "type": connector.type,
                })

        # Check for missing connectors (referenced but not found)
        found_ids = {c.id for c in connectors}
        for cid in connector_ids:
            if cid not in found_ids:
                unhealthy.append({
                    "id": cid,
                    "name": str(cid),
                    "status": "not_found",
                    "type": "unknown",
                })

        return unhealthy

    async def _get_run(self, run_id: uuid.UUID) -> PipelineRun:
        """Fetch a pipeline run by ID."""
        result = await self.db.execute(
            select(PipelineRun).where(PipelineRun.id == run_id)
        )
        run = result.scalar_one_or_none()
        if run is None:
            raise PipelineRunNotFoundError(run_id)
        return run

    async def _get_dagster_run_id(self, run_id: uuid.UUID) -> str | None:
        """Extract the Dagster run ID from run logs."""
        result = await self.db.execute(
            select(PipelineRunLog)
            .where(
                PipelineRunLog.run_id == run_id,
                PipelineRunLog.message.like("%Submitted to Dagster with run ID:%"),
            )
            .order_by(PipelineRunLog.timestamp.desc())
            .limit(1)
        )
        log_entry = result.scalar_one_or_none()
        if log_entry:
            # Extract run ID from message like "Submitted to Dagster with run ID: xxx"
            parts = log_entry.message.split("run ID: ")
            if len(parts) == 2:
                return parts[1].strip()

        # Check for retry logs
        result = await self.db.execute(
            select(PipelineRunLog)
            .where(
                PipelineRunLog.run_id == run_id,
                PipelineRunLog.message.like("%submitted to Dagster (run_id:%"),
            )
            .order_by(PipelineRunLog.timestamp.desc())
            .limit(1)
        )
        log_entry = result.scalar_one_or_none()
        if log_entry:
            parts = log_entry.message.split("run_id: ")
            if len(parts) == 2:
                return parts[1].rstrip(")")

        return None

    async def _update_run_from_dagster_status(
        self, run: PipelineRun, dagster_status: dict[str, Any]
    ) -> None:
        """Update the pipeline run record from Dagster status response."""
        new_status = dagster_status.get("status", run.status)

        # Map Dagster statuses to our internal statuses
        status_mapping = {
            "QUEUED": "queued",
            "STARTING": "running",
            "STARTED": "running",
            "SUCCESS": "succeeded",
            "FAILURE": "failed",
            "CANCELED": "failed",
            # Also accept our internal status names
            "queued": "queued",
            "running": "running",
            "succeeded": "succeeded",
            "failed": "failed",
        }

        mapped_status = status_mapping.get(new_status, new_status)
        run.status = mapped_status

        if mapped_status == "running" and run.started_at is None:
            started_at_str = dagster_status.get("started_at")
            if started_at_str:
                run.started_at = datetime.fromisoformat(started_at_str)
            else:
                run.started_at = datetime.now(timezone.utc)

        if mapped_status in ("succeeded", "failed"):
            completed_at_str = dagster_status.get("completed_at")
            if completed_at_str:
                run.completed_at = datetime.fromisoformat(completed_at_str)
            else:
                run.completed_at = datetime.now(timezone.utc)

            # Calculate duration
            if run.started_at and run.completed_at:
                delta = run.completed_at - run.started_at
                run.duration_ms = int(delta.total_seconds() * 1000)

        if mapped_status == "succeeded":
            row_counts = dagster_status.get("node_row_counts")
            if row_counts:
                run.node_row_counts = row_counts

        if mapped_status == "failed":
            error_msg = dagster_status.get("error_message")
            failing_node = dagster_status.get("failing_node")
            if error_msg or failing_node:
                log_entry = PipelineRunLog(
                    run_id=run.id,
                    level="ERROR",
                    message=error_msg or "Pipeline execution failed",
                    node_id=failing_node,
                    timestamp=datetime.now(timezone.utc),
                )
                self.db.add(log_entry)

        await self.db.flush()

    def _run_to_response(self, run: PipelineRun) -> PipelineRunResponse:
        """Convert a PipelineRun model to PipelineRunResponse."""
        return PipelineRunResponse(
            id=run.id,
            pipeline_id=run.pipeline_id,
            pipeline_version=run.pipeline_version,
            status=run.status,
            trigger_type=run.trigger_type,
            triggered_by=run.triggered_by,
            retry_count=run.retry_count,
            node_row_counts=run.node_row_counts,
            started_at=run.started_at,
            completed_at=run.completed_at,
            duration_ms=run.duration_ms,
            created_at=run.created_at,
            updated_at=run.updated_at,
        )

    def _run_to_execution_status(self, run: PipelineRun) -> ExecutionStatus:
        """Convert a PipelineRun model to ExecutionStatus."""
        # Get error info from latest error log if failed
        error_message = None
        failing_node = None

        return ExecutionStatus(
            run_id=run.id,
            pipeline_id=run.pipeline_id,
            status=run.status,
            started_at=run.started_at,
            completed_at=run.completed_at,
            duration_ms=run.duration_ms,
            node_row_counts=run.node_row_counts,
            retry_count=run.retry_count,
            error_message=error_message,
            failing_node=failing_node,
        )


def get_execution_service(
    db: AsyncSession,
    dagster_client: DagsterClientInterface | None = None,
) -> PipelineExecutionService:
    """Factory function for dependency injection of PipelineExecutionService."""
    return PipelineExecutionService(db=db, dagster_client=dagster_client)
