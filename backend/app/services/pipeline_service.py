"""Pipeline Service — CRUD, DAG validation, versioning.

Manages:
- Create pipelines with nodes and edges, validate DAG, save as version 1
- Update pipelines: validate DAG, create new version while retaining prior versions
- Get pipeline with current version nodes/edges
- List pipelines with pagination
- Delete pipeline (check for active schedules first)
- Get version history for a pipeline
- Node deletion removes connected edges automatically

Uses DAGValidator from dag_validator.py for validation.

Requirements: 5.1, 5.2, 5.5, 5.6, 5.8, 5.9, 5.10, 5.12
"""

import logging
import uuid
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models.pipelines import (
    Pipeline,
    PipelineEdge,
    PipelineNode,
    PipelineSchedule,
    PipelineVersion,
)
from backend.app.schemas.pipeline import (
    EdgeResponse,
    EdgeSchema,
    NodeResponse,
    NodeSchema,
    PipelineCreate,
    PipelineListResponse,
    PipelineResponse,
    PipelineUpdate,
    PipelineValidationError,
    PipelineValidationResponse,
    PipelineVersionResponse,
)
from backend.app.services.dag_validator import DAGEdge, DAGNode, DAGValidator

logger = logging.getLogger(__name__)


class PipelineServiceError(Exception):
    """Base exception for pipeline service operations."""

    def __init__(self, message: str, code: str = "PIPELINE_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class PipelineNotFoundError(PipelineServiceError):
    """Raised when a pipeline is not found."""

    def __init__(self, pipeline_id: uuid.UUID):
        super().__init__(
            message=f"Pipeline {pipeline_id} not found",
            code="PIPELINE_NOT_FOUND",
        )


class PipelineValidationFailedError(PipelineServiceError):
    """Raised when DAG validation fails."""

    def __init__(self, errors: list[PipelineValidationError]):
        self.errors = errors
        messages = [e.message for e in errors]
        super().__init__(
            message=f"Pipeline validation failed: {'; '.join(messages)}",
            code="VALIDATION_FAILED",
        )


class PipelineDeletionBlockedError(PipelineServiceError):
    """Raised when pipeline deletion is blocked by active schedules."""

    def __init__(self, pipeline_id: uuid.UUID, active_schedules: int):
        self.active_schedules = active_schedules
        super().__init__(
            message=(
                f"Cannot delete pipeline {pipeline_id}: "
                f"{active_schedules} active schedule(s) exist. "
                f"Pause or delete schedules before removing the pipeline."
            ),
            code="DELETION_BLOCKED",
        )


class PipelineService:
    """Service for pipeline CRUD operations, DAG validation, and versioning."""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.dag_validator = DAGValidator()

    def _nodes_to_dag_nodes(self, nodes: list[NodeSchema]) -> list[DAGNode]:
        """Convert schema nodes to DAGNode instances for validation."""
        return [
            DAGNode(
                id=node.id,
                node_type=node.node_type,
                node_subtype=node.node_subtype,
                config=node.config,
            )
            for node in nodes
        ]

    def _edges_to_dag_edges(self, edges: list[EdgeSchema]) -> list[DAGEdge]:
        """Convert schema edges to DAGEdge instances for validation."""
        return [
            DAGEdge(
                source_node_id=edge.source_node_id,
                target_node_id=edge.target_node_id,
            )
            for edge in edges
        ]

    def _build_definition_snapshot(
        self, nodes: list[NodeSchema], edges: list[EdgeSchema]
    ) -> dict[str, Any]:
        """Build a JSON-serializable snapshot of the pipeline definition."""
        return {
            "nodes": [node.model_dump() for node in nodes],
            "edges": [edge.model_dump() for edge in edges],
        }

    def _pipeline_to_response(self, pipeline: Pipeline) -> PipelineResponse:
        """Convert a Pipeline model to a PipelineResponse schema."""
        current_version = pipeline.current_version

        # Filter nodes and edges to the current version
        current_nodes = [
            NodeResponse(
                id=n.id,
                node_type=n.node_type,
                node_subtype=n.node_subtype,
                config=n.config,
                position_x=n.position_x,
                position_y=n.position_y,
            )
            for n in pipeline.nodes
            if n.version == current_version
        ]

        current_edges = [
            EdgeResponse(
                id=e.id,
                source_node_id=e.source_node_id,
                target_node_id=e.target_node_id,
            )
            for e in pipeline.edges
            if e.version == current_version
        ]

        return PipelineResponse(
            id=pipeline.id,
            name=pipeline.name,
            description=pipeline.description,
            status=pipeline.status,
            current_version=pipeline.current_version,
            created_by=pipeline.created_by,
            created_at=pipeline.created_at,
            updated_at=pipeline.updated_at,
            nodes=current_nodes,
            edges=current_edges,
        )

    def validate_dag(
        self, nodes: list[NodeSchema], edges: list[EdgeSchema]
    ) -> PipelineValidationResponse:
        """Validate pipeline DAG structure without persisting.

        Args:
            nodes: List of node schemas.
            edges: List of edge schemas.

        Returns:
            PipelineValidationResponse with is_valid and errors.
        """
        dag_nodes = self._nodes_to_dag_nodes(nodes)
        dag_edges = self._edges_to_dag_edges(edges)

        result = self.dag_validator.validate(dag_nodes, dag_edges)

        errors = [
            PipelineValidationError(
                node_id=e.node_id,
                error_type=e.error_type.value,
                message=e.message,
            )
            for e in result.errors
        ]

        return PipelineValidationResponse(is_valid=result.is_valid, errors=errors)

    async def create_pipeline(
        self, definition: PipelineCreate, user_id: uuid.UUID
    ) -> PipelineResponse:
        """Create a new pipeline with nodes and edges.

        Validates the DAG, saves the pipeline as version 1.

        Args:
            definition: Pipeline creation schema with nodes and edges.
            user_id: The ID of the user creating the pipeline.

        Returns:
            PipelineResponse with the created pipeline.

        Raises:
            PipelineValidationFailedError: If DAG validation fails.
        """
        # Validate the DAG
        validation = self.validate_dag(definition.nodes, definition.edges)
        if not validation.is_valid:
            raise PipelineValidationFailedError(validation.errors)

        # Create the pipeline record
        pipeline = Pipeline(
            name=definition.name,
            description=definition.description,
            status="draft",
            current_version=1,
            created_by=user_id,
        )
        self.db.add(pipeline)
        await self.db.flush()

        # Create version 1 snapshot
        snapshot = self._build_definition_snapshot(definition.nodes, definition.edges)
        version = PipelineVersion(
            pipeline_id=pipeline.id,
            version_number=1,
            definition_snapshot=snapshot,
            created_by=user_id,
        )
        self.db.add(version)

        # Create node records
        node_id_map: dict[str, uuid.UUID] = {}
        for node_schema in definition.nodes:
            node = PipelineNode(
                pipeline_id=pipeline.id,
                version=1,
                node_type=node_schema.node_type,
                node_subtype=node_schema.node_subtype,
                config=node_schema.config,
                position_x=node_schema.position_x,
                position_y=node_schema.position_y,
            )
            self.db.add(node)
            await self.db.flush()
            node_id_map[node_schema.id] = node.id

        # Create edge records
        for edge_schema in definition.edges:
            source_db_id = node_id_map.get(edge_schema.source_node_id)
            target_db_id = node_id_map.get(edge_schema.target_node_id)
            if source_db_id and target_db_id:
                edge = PipelineEdge(
                    pipeline_id=pipeline.id,
                    version=1,
                    source_node_id=source_db_id,
                    target_node_id=target_db_id,
                )
                self.db.add(edge)

        await self.db.flush()

        # Reload the pipeline with relationships for response
        pipeline = await self._get_pipeline_model(pipeline.id)

        logger.info(
            "Created pipeline %s (version 1) with %d nodes and %d edges by user %s",
            pipeline.id,
            len(definition.nodes),
            len(definition.edges),
            user_id,
        )

        return self._pipeline_to_response(pipeline)

    async def update_pipeline(
        self, pipeline_id: uuid.UUID, definition: PipelineUpdate, user_id: uuid.UUID
    ) -> PipelineResponse:
        """Update a pipeline definition, creating a new version.

        Validates the DAG, creates a new version while retaining all prior versions.

        Args:
            pipeline_id: The pipeline UUID.
            definition: Pipeline update schema with new nodes and edges.
            user_id: The ID of the user updating the pipeline.

        Returns:
            PipelineResponse with the updated pipeline.

        Raises:
            PipelineNotFoundError: If pipeline doesn't exist.
            PipelineValidationFailedError: If DAG validation fails.
        """
        pipeline = await self._get_pipeline_model(pipeline_id)

        # Validate the DAG
        validation = self.validate_dag(definition.nodes, definition.edges)
        if not validation.is_valid:
            raise PipelineValidationFailedError(validation.errors)

        # Increment version
        new_version = pipeline.current_version + 1
        pipeline.current_version = new_version

        # Update name/description if provided
        if definition.name is not None:
            pipeline.name = definition.name
        if definition.description is not None:
            pipeline.description = definition.description

        # Create version snapshot
        snapshot = self._build_definition_snapshot(definition.nodes, definition.edges)
        version = PipelineVersion(
            pipeline_id=pipeline.id,
            version_number=new_version,
            definition_snapshot=snapshot,
            created_by=user_id,
        )
        self.db.add(version)

        # Create new node records for the new version
        node_id_map: dict[str, uuid.UUID] = {}
        for node_schema in definition.nodes:
            node = PipelineNode(
                pipeline_id=pipeline.id,
                version=new_version,
                node_type=node_schema.node_type,
                node_subtype=node_schema.node_subtype,
                config=node_schema.config,
                position_x=node_schema.position_x,
                position_y=node_schema.position_y,
            )
            self.db.add(node)
            await self.db.flush()
            node_id_map[node_schema.id] = node.id

        # Create new edge records for the new version
        for edge_schema in definition.edges:
            source_db_id = node_id_map.get(edge_schema.source_node_id)
            target_db_id = node_id_map.get(edge_schema.target_node_id)
            if source_db_id and target_db_id:
                edge = PipelineEdge(
                    pipeline_id=pipeline.id,
                    version=new_version,
                    source_node_id=source_db_id,
                    target_node_id=target_db_id,
                )
                self.db.add(edge)

        await self.db.flush()

        # Reload
        pipeline = await self._get_pipeline_model(pipeline.id)

        logger.info(
            "Updated pipeline %s to version %d with %d nodes and %d edges by user %s",
            pipeline_id,
            new_version,
            len(definition.nodes),
            len(definition.edges),
            user_id,
        )

        return self._pipeline_to_response(pipeline)

    async def get_pipeline(self, pipeline_id: uuid.UUID) -> PipelineResponse:
        """Get a pipeline with its current version nodes and edges.

        Args:
            pipeline_id: The pipeline UUID.

        Returns:
            PipelineResponse with current version data.

        Raises:
            PipelineNotFoundError: If pipeline doesn't exist.
        """
        pipeline = await self._get_pipeline_model(pipeline_id)
        return self._pipeline_to_response(pipeline)

    async def list_pipelines(
        self,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        name: str | None = None,
    ) -> PipelineListResponse:
        """List all pipelines with pagination and optional filters.

        Args:
            page: Page number (1-based).
            page_size: Number of items per page.
            status: Optional status filter.
            name: Optional name search (partial match).

        Returns:
            PipelineListResponse with paginated results.
        """
        # Build base query
        query = select(Pipeline).options(
            selectinload(Pipeline.nodes),
            selectinload(Pipeline.edges),
        )

        # Apply filters
        if status:
            query = query.where(Pipeline.status == status)
        if name:
            query = query.where(Pipeline.name.ilike(f"%{name}%"))

        # Get total count
        count_query = select(func.count(Pipeline.id))
        if status:
            count_query = count_query.where(Pipeline.status == status)
        if name:
            count_query = count_query.where(Pipeline.name.ilike(f"%{name}%"))

        count_result = await self.db.execute(count_query)
        total = count_result.scalar() or 0

        # Apply pagination
        offset = (page - 1) * page_size
        query = query.offset(offset).limit(page_size).order_by(Pipeline.updated_at.desc())

        result = await self.db.execute(query)
        pipelines = result.scalars().unique().all()

        responses = [self._pipeline_to_response(p) for p in pipelines]

        return PipelineListResponse(
            pipelines=responses,
            total=total,
            page=page,
            page_size=page_size,
        )

    async def delete_pipeline(self, pipeline_id: uuid.UUID) -> None:
        """Delete a pipeline after checking for active schedules.

        Args:
            pipeline_id: The pipeline UUID.

        Raises:
            PipelineNotFoundError: If pipeline doesn't exist.
            PipelineDeletionBlockedError: If active schedules exist.
        """
        pipeline = await self._get_pipeline_model(pipeline_id)

        # Check for active schedules
        active_schedules_query = select(func.count(PipelineSchedule.id)).where(
            PipelineSchedule.pipeline_id == pipeline_id,
            PipelineSchedule.status == "active",
        )
        active_result = await self.db.execute(active_schedules_query)
        active_count = active_result.scalar() or 0

        if active_count > 0:
            raise PipelineDeletionBlockedError(pipeline_id, active_count)

        # Delete edges, nodes, versions, schedules, then pipeline
        await self.db.execute(
            delete(PipelineEdge).where(PipelineEdge.pipeline_id == pipeline_id)
        )
        await self.db.execute(
            delete(PipelineNode).where(PipelineNode.pipeline_id == pipeline_id)
        )
        await self.db.execute(
            delete(PipelineVersion).where(PipelineVersion.pipeline_id == pipeline_id)
        )
        await self.db.execute(
            delete(PipelineSchedule).where(
                PipelineSchedule.pipeline_id == pipeline_id,
                PipelineSchedule.status != "active",
            )
        )
        await self.db.delete(pipeline)
        await self.db.flush()

        logger.info("Deleted pipeline %s", pipeline_id)

    async def get_versions(self, pipeline_id: uuid.UUID) -> list[PipelineVersionResponse]:
        """Get all versions for a pipeline.

        Args:
            pipeline_id: The pipeline UUID.

        Returns:
            List of PipelineVersionResponse ordered by version number descending.

        Raises:
            PipelineNotFoundError: If pipeline doesn't exist.
        """
        # Verify pipeline exists
        await self._get_pipeline_model(pipeline_id)

        result = await self.db.execute(
            select(PipelineVersion)
            .where(PipelineVersion.pipeline_id == pipeline_id)
            .order_by(PipelineVersion.version_number.desc())
        )
        versions = result.scalars().all()

        return [
            PipelineVersionResponse(
                id=v.id,
                pipeline_id=v.pipeline_id,
                version_number=v.version_number,
                definition_snapshot=v.definition_snapshot,
                created_by=v.created_by,
                created_at=v.created_at,
            )
            for v in versions
        ]

    async def delete_node(
        self, pipeline_id: uuid.UUID, node_id: uuid.UUID, user_id: uuid.UUID
    ) -> PipelineResponse:
        """Delete a node and all its connected edges from the current version.

        Creates a new version reflecting the deletion.

        Args:
            pipeline_id: The pipeline UUID.
            node_id: The node UUID to delete.
            user_id: The user performing the deletion.

        Returns:
            Updated PipelineResponse.

        Raises:
            PipelineNotFoundError: If pipeline doesn't exist.
        """
        pipeline = await self._get_pipeline_model(pipeline_id)
        current_version = pipeline.current_version

        # Get current version nodes and edges
        current_nodes = [n for n in pipeline.nodes if n.version == current_version]
        current_edges = [e for e in pipeline.edges if e.version == current_version]

        # Find the node to delete
        node_to_delete = None
        for node in current_nodes:
            if node.id == node_id:
                node_to_delete = node
                break

        if node_to_delete is None:
            raise PipelineServiceError(
                message=f"Node {node_id} not found in pipeline {pipeline_id}",
                code="NODE_NOT_FOUND",
            )

        # Build new version without the deleted node and its connected edges
        remaining_nodes = [n for n in current_nodes if n.id != node_id]
        remaining_edges = [
            e for e in current_edges
            if e.source_node_id != node_id and e.target_node_id != node_id
        ]

        # Build node schemas for the new version
        new_nodes = [
            NodeSchema(
                id=str(n.id),
                node_type=n.node_type,
                node_subtype=n.node_subtype,
                config=n.config or {},
                position_x=n.position_x,
                position_y=n.position_y,
            )
            for n in remaining_nodes
        ]

        new_edges = [
            EdgeSchema(
                source_node_id=str(e.source_node_id),
                target_node_id=str(e.target_node_id),
            )
            for e in remaining_edges
        ]

        # Create the update definition (skip validation for node deletion —
        # an incomplete pipeline after deletion is acceptable as draft)
        new_version = pipeline.current_version + 1
        pipeline.current_version = new_version

        # Create version snapshot
        snapshot = self._build_definition_snapshot(new_nodes, new_edges)
        version = PipelineVersion(
            pipeline_id=pipeline.id,
            version_number=new_version,
            definition_snapshot=snapshot,
            created_by=user_id,
        )
        self.db.add(version)

        # Create new node records
        node_id_map: dict[str, uuid.UUID] = {}
        for node_schema in new_nodes:
            node = PipelineNode(
                pipeline_id=pipeline.id,
                version=new_version,
                node_type=node_schema.node_type,
                node_subtype=node_schema.node_subtype,
                config=node_schema.config,
                position_x=node_schema.position_x,
                position_y=node_schema.position_y,
            )
            self.db.add(node)
            await self.db.flush()
            node_id_map[node_schema.id] = node.id

        # Create new edge records
        for edge_schema in new_edges:
            source_db_id = node_id_map.get(edge_schema.source_node_id)
            target_db_id = node_id_map.get(edge_schema.target_node_id)
            if source_db_id and target_db_id:
                edge = PipelineEdge(
                    pipeline_id=pipeline.id,
                    version=new_version,
                    source_node_id=source_db_id,
                    target_node_id=target_db_id,
                )
                self.db.add(edge)

        await self.db.flush()

        # Reload
        pipeline = await self._get_pipeline_model(pipeline.id)

        logger.info(
            "Deleted node %s from pipeline %s, created version %d",
            node_id,
            pipeline_id,
            new_version,
        )

        return self._pipeline_to_response(pipeline)

    # --- Private helpers ---

    async def _get_pipeline_model(self, pipeline_id: uuid.UUID) -> Pipeline:
        """Fetch a pipeline by ID with nodes and edges loaded.

        Raises:
            PipelineNotFoundError: If not found.
        """
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
            raise PipelineNotFoundError(pipeline_id)
        return pipeline


def get_pipeline_service(db: AsyncSession) -> PipelineService:
    """Factory function for dependency injection of PipelineService."""
    return PipelineService(db)
