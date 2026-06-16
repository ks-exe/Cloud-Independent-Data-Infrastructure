"""Unit tests for PipelineService — CRUD, DAG validation, and versioning.

Tests:
- create_pipeline validates DAG and saves as version 1
- update_pipeline creates new version while retaining prior versions
- get_pipeline returns current version nodes/edges
- list_pipelines returns paginated results
- delete_pipeline blocked by active schedules
- get_versions returns all versions
- Node deletion removes connected edges

Requirements: 5.1, 5.2, 5.5, 5.6, 5.8, 5.9, 5.10, 5.12
"""

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.schemas.pipeline import (
    EdgeSchema,
    NodeSchema,
    PipelineCreate,
    PipelineUpdate,
)
from backend.app.services.pipeline_service import (
    PipelineDeletionBlockedError,
    PipelineNotFoundError,
    PipelineService,
    PipelineValidationFailedError,
)


# --- Helpers ---


def _make_valid_nodes() -> list[NodeSchema]:
    """Create a minimal valid set of nodes (source → destination)."""
    return [
        NodeSchema(
            id="source-1",
            node_type="source",
            node_subtype="postgresql_source",
            config={"connector_id": str(uuid.uuid4()), "table_name": "users"},
            position_x=100.0,
            position_y=200.0,
        ),
        NodeSchema(
            id="dest-1",
            node_type="destination",
            node_subtype="postgresql_destination",
            config={
                "connector_id": str(uuid.uuid4()),
                "table_name": "users_copy",
                "write_mode": "append",
            },
            position_x=400.0,
            position_y=200.0,
        ),
    ]


def _make_valid_edges() -> list[EdgeSchema]:
    """Create edges connecting source-1 → dest-1."""
    return [
        EdgeSchema(source_node_id="source-1", target_node_id="dest-1"),
    ]


def _make_pipeline_model(
    pipeline_id=None,
    name="Test Pipeline",
    description="A test pipeline",
    status="draft",
    current_version=1,
    user_id=None,
    nodes=None,
    edges=None,
):
    """Create a mock Pipeline model."""
    if pipeline_id is None:
        pipeline_id = uuid.uuid4()
    if user_id is None:
        user_id = uuid.uuid4()
    if nodes is None:
        nodes = []
    if edges is None:
        edges = []

    pipeline = MagicMock()
    pipeline.id = pipeline_id
    pipeline.name = name
    pipeline.description = description
    pipeline.status = status
    pipeline.current_version = current_version
    pipeline.created_by = user_id
    pipeline.created_at = datetime.now(timezone.utc)
    pipeline.updated_at = datetime.now(timezone.utc)
    pipeline.nodes = nodes
    pipeline.edges = edges
    return pipeline


def _make_node_model(
    node_id=None,
    pipeline_id=None,
    version=1,
    node_type="source",
    node_subtype="postgresql_source",
    config=None,
    position_x=100.0,
    position_y=200.0,
):
    """Create a mock PipelineNode model."""
    if node_id is None:
        node_id = uuid.uuid4()
    if pipeline_id is None:
        pipeline_id = uuid.uuid4()
    if config is None:
        config = {"connector_id": str(uuid.uuid4()), "table_name": "test"}

    node = MagicMock()
    node.id = node_id
    node.pipeline_id = pipeline_id
    node.version = version
    node.node_type = node_type
    node.node_subtype = node_subtype
    node.config = config
    node.position_x = position_x
    node.position_y = position_y
    return node


def _make_edge_model(
    edge_id=None,
    pipeline_id=None,
    version=1,
    source_node_id=None,
    target_node_id=None,
):
    """Create a mock PipelineEdge model."""
    if edge_id is None:
        edge_id = uuid.uuid4()
    if pipeline_id is None:
        pipeline_id = uuid.uuid4()
    if source_node_id is None:
        source_node_id = uuid.uuid4()
    if target_node_id is None:
        target_node_id = uuid.uuid4()

    edge = MagicMock()
    edge.id = edge_id
    edge.pipeline_id = pipeline_id
    edge.version = version
    edge.source_node_id = source_node_id
    edge.target_node_id = target_node_id
    return edge


# --- Tests ---


class TestDAGValidation:
    """Tests for validate_dag method."""

    def test_valid_dag_passes(self):
        """A valid source → destination DAG should pass validation."""
        service = PipelineService(db=AsyncMock())
        nodes = _make_valid_nodes()
        edges = _make_valid_edges()

        result = service.validate_dag(nodes, edges)

        assert result.is_valid is True
        assert result.errors == []

    def test_cycle_detected(self):
        """A DAG with a cycle should fail validation."""
        service = PipelineService(db=AsyncMock())
        nodes = [
            NodeSchema(
                id="t1",
                node_type="transformation",
                node_subtype="filter_rows",
                config={"condition": "x > 0"},
            ),
            NodeSchema(
                id="t2",
                node_type="transformation",
                node_subtype="select_columns",
                config={"columns": ["a", "b"]},
            ),
        ]
        edges = [
            EdgeSchema(source_node_id="t1", target_node_id="t2"),
            EdgeSchema(source_node_id="t2", target_node_id="t1"),
        ]

        result = service.validate_dag(nodes, edges)

        assert result.is_valid is False
        error_types = [e.error_type for e in result.errors]
        assert "cycle_detected" in error_types

    def test_missing_source_node(self):
        """A pipeline without a source node should fail validation."""
        service = PipelineService(db=AsyncMock())
        nodes = [
            NodeSchema(
                id="dest-1",
                node_type="destination",
                node_subtype="postgresql_destination",
                config={
                    "connector_id": str(uuid.uuid4()),
                    "table_name": "out",
                    "write_mode": "append",
                },
            ),
        ]
        edges = []

        result = service.validate_dag(nodes, edges)

        assert result.is_valid is False
        error_types = [e.error_type for e in result.errors]
        assert "missing_source" in error_types

    def test_missing_destination_node(self):
        """A pipeline without a destination node should fail validation."""
        service = PipelineService(db=AsyncMock())
        nodes = [
            NodeSchema(
                id="source-1",
                node_type="source",
                node_subtype="postgresql_source",
                config={"connector_id": str(uuid.uuid4()), "table_name": "in"},
            ),
        ]
        edges = []

        result = service.validate_dag(nodes, edges)

        assert result.is_valid is False
        error_types = [e.error_type for e in result.errors]
        assert "missing_destination" in error_types

    def test_exceeds_node_limit(self):
        """A pipeline with more than 50 nodes should fail validation."""
        service = PipelineService(db=AsyncMock())
        # Create 51 transformation nodes
        nodes = [
            NodeSchema(
                id=f"t-{i}",
                node_type="transformation",
                node_subtype="filter_rows",
                config={"condition": "x > 0"},
            )
            for i in range(51)
        ]
        edges = []

        result = service.validate_dag(nodes, edges)

        assert result.is_valid is False
        error_types = [e.error_type for e in result.errors]
        assert "exceeds_node_limit" in error_types

    def test_destination_cannot_have_outgoing_edge(self):
        """Destination nodes cannot have outgoing connections."""
        service = PipelineService(db=AsyncMock())
        nodes = [
            NodeSchema(
                id="source-1",
                node_type="source",
                node_subtype="postgresql_source",
                config={"connector_id": str(uuid.uuid4()), "table_name": "in"},
            ),
            NodeSchema(
                id="dest-1",
                node_type="destination",
                node_subtype="postgresql_destination",
                config={
                    "connector_id": str(uuid.uuid4()),
                    "table_name": "out",
                    "write_mode": "append",
                },
            ),
            NodeSchema(
                id="dest-2",
                node_type="destination",
                node_subtype="clickhouse_destination",
                config={
                    "connector_id": str(uuid.uuid4()),
                    "table_name": "out2",
                    "write_mode": "append",
                },
            ),
        ]
        edges = [
            EdgeSchema(source_node_id="source-1", target_node_id="dest-1"),
            EdgeSchema(source_node_id="dest-1", target_node_id="dest-2"),  # Invalid!
        ]

        result = service.validate_dag(nodes, edges)

        assert result.is_valid is False
        error_types = [e.error_type for e in result.errors]
        assert "invalid_edge" in error_types


class TestCreatePipeline:
    """Tests for create_pipeline method."""

    @pytest.mark.asyncio
    async def test_create_pipeline_valid_dag(self):
        """Creating a pipeline with a valid DAG should succeed."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        service = PipelineService(db=db)

        # Mock the _get_pipeline_model to return a properly structured pipeline
        pipeline_id = uuid.uuid4()
        user_id = uuid.uuid4()
        source_node_id = uuid.uuid4()
        dest_node_id = uuid.uuid4()
        edge_id = uuid.uuid4()

        source_node = _make_node_model(
            node_id=source_node_id,
            pipeline_id=pipeline_id,
            version=1,
            node_type="source",
            node_subtype="postgresql_source",
            config={"connector_id": str(uuid.uuid4()), "table_name": "users"},
            position_x=100.0,
            position_y=200.0,
        )
        dest_node = _make_node_model(
            node_id=dest_node_id,
            pipeline_id=pipeline_id,
            version=1,
            node_type="destination",
            node_subtype="postgresql_destination",
            config={
                "connector_id": str(uuid.uuid4()),
                "table_name": "users_copy",
                "write_mode": "append",
            },
            position_x=400.0,
            position_y=200.0,
        )
        edge_model = _make_edge_model(
            edge_id=edge_id,
            pipeline_id=pipeline_id,
            version=1,
            source_node_id=source_node_id,
            target_node_id=dest_node_id,
        )

        mock_pipeline = _make_pipeline_model(
            pipeline_id=pipeline_id,
            name="ETL Pipeline",
            description="Test ETL",
            status="draft",
            current_version=1,
            user_id=user_id,
            nodes=[source_node, dest_node],
            edges=[edge_model],
        )

        service._get_pipeline_model = AsyncMock(return_value=mock_pipeline)

        definition = PipelineCreate(
            name="ETL Pipeline",
            description="Test ETL",
            nodes=_make_valid_nodes(),
            edges=_make_valid_edges(),
        )

        result = await service.create_pipeline(definition, user_id)

        assert result.name == "ETL Pipeline"
        assert result.status == "draft"
        assert result.current_version == 1
        assert len(result.nodes) == 2
        assert len(result.edges) == 1

    @pytest.mark.asyncio
    async def test_create_pipeline_invalid_dag_raises(self):
        """Creating a pipeline with an invalid DAG should raise an error."""
        db = AsyncMock()
        service = PipelineService(db=db)

        # Pipeline with no destination
        definition = PipelineCreate(
            name="Bad Pipeline",
            nodes=[
                NodeSchema(
                    id="source-1",
                    node_type="source",
                    node_subtype="postgresql_source",
                    config={"connector_id": str(uuid.uuid4()), "table_name": "t"},
                ),
            ],
            edges=[],
        )

        with pytest.raises(PipelineValidationFailedError) as exc_info:
            await service.create_pipeline(definition, uuid.uuid4())

        assert len(exc_info.value.errors) > 0


class TestUpdatePipeline:
    """Tests for update_pipeline method — versioning logic."""

    @pytest.mark.asyncio
    async def test_update_increments_version(self):
        """Updating a pipeline should create a new version."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        service = PipelineService(db=db)

        pipeline_id = uuid.uuid4()
        user_id = uuid.uuid4()

        # Initial pipeline at version 1
        initial_pipeline = _make_pipeline_model(
            pipeline_id=pipeline_id,
            current_version=1,
            user_id=user_id,
        )

        # After update, return pipeline at version 2
        source_node_id = uuid.uuid4()
        dest_node_id = uuid.uuid4()
        updated_pipeline = _make_pipeline_model(
            pipeline_id=pipeline_id,
            current_version=2,
            user_id=user_id,
            nodes=[
                _make_node_model(
                    node_id=source_node_id,
                    pipeline_id=pipeline_id,
                    version=2,
                    node_type="source",
                    node_subtype="postgresql_source",
                    config={"connector_id": str(uuid.uuid4()), "table_name": "users"},
                ),
                _make_node_model(
                    node_id=dest_node_id,
                    pipeline_id=pipeline_id,
                    version=2,
                    node_type="destination",
                    node_subtype="postgresql_destination",
                    config={
                        "connector_id": str(uuid.uuid4()),
                        "table_name": "out",
                        "write_mode": "append",
                    },
                ),
            ],
            edges=[
                _make_edge_model(
                    pipeline_id=pipeline_id,
                    version=2,
                    source_node_id=source_node_id,
                    target_node_id=dest_node_id,
                ),
            ],
        )

        # First call returns the initial pipeline, second returns updated
        service._get_pipeline_model = AsyncMock(
            side_effect=[initial_pipeline, updated_pipeline]
        )

        definition = PipelineUpdate(
            nodes=_make_valid_nodes(),
            edges=_make_valid_edges(),
        )

        result = await service.update_pipeline(pipeline_id, definition, user_id)

        assert result.current_version == 2
        assert db.add.called

    @pytest.mark.asyncio
    async def test_update_pipeline_not_found_raises(self):
        """Updating a non-existent pipeline should raise PipelineNotFoundError."""
        db = AsyncMock()
        service = PipelineService(db=db)

        service._get_pipeline_model = AsyncMock(
            side_effect=PipelineNotFoundError(uuid.uuid4())
        )

        definition = PipelineUpdate(
            nodes=_make_valid_nodes(),
            edges=_make_valid_edges(),
        )

        with pytest.raises(PipelineNotFoundError):
            await service.update_pipeline(uuid.uuid4(), definition, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_update_with_invalid_dag_raises(self):
        """Updating with an invalid DAG should raise validation error."""
        db = AsyncMock()
        service = PipelineService(db=db)

        pipeline = _make_pipeline_model(current_version=1)
        service._get_pipeline_model = AsyncMock(return_value=pipeline)

        # No destination node
        definition = PipelineUpdate(
            nodes=[
                NodeSchema(
                    id="source-1",
                    node_type="source",
                    node_subtype="postgresql_source",
                    config={"connector_id": str(uuid.uuid4()), "table_name": "t"},
                ),
            ],
            edges=[],
        )

        with pytest.raises(PipelineValidationFailedError):
            await service.update_pipeline(uuid.uuid4(), definition, uuid.uuid4())


class TestGetPipeline:
    """Tests for get_pipeline method."""

    @pytest.mark.asyncio
    async def test_get_pipeline_returns_current_version_data(self):
        """get_pipeline should return nodes/edges for the current version only."""
        db = AsyncMock()
        service = PipelineService(db=db)

        pipeline_id = uuid.uuid4()
        node_v1 = _make_node_model(pipeline_id=pipeline_id, version=1)
        node_v2 = _make_node_model(pipeline_id=pipeline_id, version=2)
        edge_v2 = _make_edge_model(pipeline_id=pipeline_id, version=2)

        pipeline = _make_pipeline_model(
            pipeline_id=pipeline_id,
            current_version=2,
            nodes=[node_v1, node_v2],
            edges=[edge_v2],
        )

        service._get_pipeline_model = AsyncMock(return_value=pipeline)

        result = await service.get_pipeline(pipeline_id)

        # Should only include version 2 nodes
        assert len(result.nodes) == 1
        assert result.nodes[0].id == node_v2.id
        assert len(result.edges) == 1

    @pytest.mark.asyncio
    async def test_get_pipeline_not_found(self):
        """get_pipeline for non-existent ID should raise."""
        db = AsyncMock()
        service = PipelineService(db=db)

        service._get_pipeline_model = AsyncMock(
            side_effect=PipelineNotFoundError(uuid.uuid4())
        )

        with pytest.raises(PipelineNotFoundError):
            await service.get_pipeline(uuid.uuid4())


class TestDeletePipeline:
    """Tests for delete_pipeline method."""

    @pytest.mark.asyncio
    async def test_delete_blocked_by_active_schedules(self):
        """Deletion should be blocked if active schedules exist."""
        db = AsyncMock()
        service = PipelineService(db=db)

        pipeline_id = uuid.uuid4()
        pipeline = _make_pipeline_model(pipeline_id=pipeline_id)
        service._get_pipeline_model = AsyncMock(return_value=pipeline)

        # Mock active schedules count
        mock_result = MagicMock()
        mock_result.scalar.return_value = 2
        db.execute = AsyncMock(return_value=mock_result)

        with pytest.raises(PipelineDeletionBlockedError) as exc_info:
            await service.delete_pipeline(pipeline_id)

        assert exc_info.value.active_schedules == 2

    @pytest.mark.asyncio
    async def test_delete_succeeds_no_active_schedules(self):
        """Deletion should succeed when no active schedules exist."""
        db = AsyncMock()
        db.delete = AsyncMock()
        db.flush = AsyncMock()

        service = PipelineService(db=db)

        pipeline_id = uuid.uuid4()
        pipeline = _make_pipeline_model(pipeline_id=pipeline_id)
        service._get_pipeline_model = AsyncMock(return_value=pipeline)

        # Mock active schedules count = 0
        mock_result = MagicMock()
        mock_result.scalar.return_value = 0
        db.execute = AsyncMock(return_value=mock_result)

        await service.delete_pipeline(pipeline_id)

        assert db.delete.called


class TestNodeDeletion:
    """Tests for delete_node method — removes connected edges."""

    @pytest.mark.asyncio
    async def test_node_deletion_removes_connected_edges(self):
        """Deleting a node should remove all edges connected to it."""
        db = AsyncMock()
        db.flush = AsyncMock()
        db.add = MagicMock()

        service = PipelineService(db=db)

        pipeline_id = uuid.uuid4()
        user_id = uuid.uuid4()
        source_id = uuid.uuid4()
        transform_id = uuid.uuid4()
        dest_id = uuid.uuid4()

        source_node = _make_node_model(
            node_id=source_id,
            pipeline_id=pipeline_id,
            version=1,
            node_type="source",
            node_subtype="postgresql_source",
            config={"connector_id": str(uuid.uuid4()), "table_name": "users"},
        )
        transform_node = _make_node_model(
            node_id=transform_id,
            pipeline_id=pipeline_id,
            version=1,
            node_type="transformation",
            node_subtype="filter_rows",
            config={"condition": "age > 18"},
        )
        dest_node = _make_node_model(
            node_id=dest_id,
            pipeline_id=pipeline_id,
            version=1,
            node_type="destination",
            node_subtype="postgresql_destination",
            config={
                "connector_id": str(uuid.uuid4()),
                "table_name": "out",
                "write_mode": "append",
            },
        )

        edge1 = _make_edge_model(
            pipeline_id=pipeline_id,
            version=1,
            source_node_id=source_id,
            target_node_id=transform_id,
        )
        edge2 = _make_edge_model(
            pipeline_id=pipeline_id,
            version=1,
            source_node_id=transform_id,
            target_node_id=dest_id,
        )

        pipeline = _make_pipeline_model(
            pipeline_id=pipeline_id,
            current_version=1,
            user_id=user_id,
            nodes=[source_node, transform_node, dest_node],
            edges=[edge1, edge2],
        )

        # After deletion, return pipeline at version 2 without the transform node
        updated_pipeline = _make_pipeline_model(
            pipeline_id=pipeline_id,
            current_version=2,
            user_id=user_id,
            nodes=[
                _make_node_model(
                    pipeline_id=pipeline_id,
                    version=2,
                    node_type="source",
                    node_subtype="postgresql_source",
                    config={"connector_id": str(uuid.uuid4()), "table_name": "users"},
                ),
                _make_node_model(
                    pipeline_id=pipeline_id,
                    version=2,
                    node_type="destination",
                    node_subtype="postgresql_destination",
                    config={
                        "connector_id": str(uuid.uuid4()),
                        "table_name": "out",
                        "write_mode": "append",
                    },
                ),
            ],
            edges=[],  # No edges after deleting the middle node
        )

        service._get_pipeline_model = AsyncMock(
            side_effect=[pipeline, updated_pipeline]
        )

        result = await service.delete_node(pipeline_id, transform_id, user_id)

        # The transform node and its edges should be removed
        assert result.current_version == 2
        assert len(result.nodes) == 2
        assert len(result.edges) == 0


class TestGetVersions:
    """Tests for get_versions method."""

    @pytest.mark.asyncio
    async def test_get_versions_returns_all(self):
        """get_versions should return all version records."""
        db = AsyncMock()
        service = PipelineService(db=db)

        pipeline_id = uuid.uuid4()
        pipeline = _make_pipeline_model(pipeline_id=pipeline_id, current_version=3)
        service._get_pipeline_model = AsyncMock(return_value=pipeline)

        # Mock version query results
        versions = []
        for v in [3, 2, 1]:
            ver = MagicMock()
            ver.id = uuid.uuid4()
            ver.pipeline_id = pipeline_id
            ver.version_number = v
            ver.definition_snapshot = {"nodes": [], "edges": []}
            ver.created_by = uuid.uuid4()
            ver.created_at = datetime.now(timezone.utc)
            versions.append(ver)

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = versions
        db.execute = AsyncMock(return_value=mock_result)

        result = await service.get_versions(pipeline_id)

        assert len(result) == 3
        assert result[0].version_number == 3
        assert result[2].version_number == 1


class TestPipelineResponseStructure:
    """Tests for response structure correctness."""

    def test_pipeline_response_filters_by_version(self):
        """_pipeline_to_response should only include current version nodes/edges."""
        db = AsyncMock()
        service = PipelineService(db=db)

        pipeline_id = uuid.uuid4()
        # Create nodes for version 1 and version 2
        node_v1 = _make_node_model(pipeline_id=pipeline_id, version=1)
        node_v2a = _make_node_model(pipeline_id=pipeline_id, version=2)
        node_v2b = _make_node_model(pipeline_id=pipeline_id, version=2)
        edge_v1 = _make_edge_model(pipeline_id=pipeline_id, version=1)
        edge_v2 = _make_edge_model(pipeline_id=pipeline_id, version=2)

        pipeline = _make_pipeline_model(
            pipeline_id=pipeline_id,
            current_version=2,
            nodes=[node_v1, node_v2a, node_v2b],
            edges=[edge_v1, edge_v2],
        )

        result = service._pipeline_to_response(pipeline)

        # Should only include version 2 items
        assert len(result.nodes) == 2
        assert len(result.edges) == 1
        assert result.current_version == 2
