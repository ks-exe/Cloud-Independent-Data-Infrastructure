"""Unit tests for the Lineage Service."""

import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.schemas.lineage import (
    LineageEventCreate,
    LineageEventResponse,
    LineageGraph,
    LineageGraphEdge,
    LineageGraphNode,
    LineageNodeMetadata,
    LineageRetentionConfig,
)
from backend.app.services.lineage_service import LineageService


# ---------- Helpers ----------


def _make_lineage_event_create(
    source_system: str = "postgres_source",
    source_table: str = "orders",
    destination_system: str = "clickhouse_dest",
    destination_table: str = "orders_analytics",
    transformation_node: str | None = "agg_orders",
    pipeline_id: uuid.UUID | None = None,
    execution_id: uuid.UUID | None = None,
    triggered_by: uuid.UUID | None = None,
    timestamp: datetime | None = None,
) -> LineageEventCreate:
    """Create a LineageEventCreate schema for testing."""
    return LineageEventCreate(
        pipeline_id=pipeline_id or uuid.uuid4(),
        execution_id=execution_id or uuid.uuid4(),
        source_system=source_system,
        source_table=source_table,
        destination_system=destination_system,
        destination_table=destination_table,
        transformation_node=transformation_node,
        triggered_by=triggered_by or uuid.uuid4(),
        timestamp=timestamp or datetime.now(timezone.utc),
    )


def _make_mock_lineage_event(
    source_system: str = "postgres_source",
    source_table: str = "orders",
    destination_system: str = "clickhouse_dest",
    destination_table: str = "orders_analytics",
    transformation_node: str | None = "agg_orders",
    pipeline_id: uuid.UUID | None = None,
    execution_id: uuid.UUID | None = None,
    triggered_by: uuid.UUID | None = None,
    timestamp: datetime | None = None,
) -> MagicMock:
    """Create a mock LineageEvent ORM object."""
    event = MagicMock()
    event.id = uuid.uuid4()
    event.pipeline_id = pipeline_id or uuid.uuid4()
    event.execution_id = execution_id or uuid.uuid4()
    event.source_system = source_system
    event.source_table = source_table
    event.destination_system = destination_system
    event.destination_table = destination_table
    event.transformation_node = transformation_node
    event.triggered_by = triggered_by or uuid.uuid4()
    event.timestamp = timestamp or datetime.now(timezone.utc)
    return event


# ---------- Schema Tests ----------


class TestLineageSchemas:
    """Tests for lineage Pydantic schema validation."""

    def test_lineage_event_create_valid(self):
        event = _make_lineage_event_create()
        assert event.source_system == "postgres_source"
        assert event.source_table == "orders"
        assert event.destination_system == "clickhouse_dest"
        assert event.destination_table == "orders_analytics"
        assert event.transformation_node == "agg_orders"

    def test_lineage_event_create_without_transformation(self):
        event = _make_lineage_event_create(transformation_node=None)
        assert event.transformation_node is None

    def test_lineage_event_create_requires_source_system(self):
        with pytest.raises(ValueError):
            LineageEventCreate(
                pipeline_id=uuid.uuid4(),
                execution_id=uuid.uuid4(),
                source_system="",  # empty not allowed (min_length=1)
                source_table="orders",
                destination_system="dest",
                destination_table="dest_table",
                triggered_by=uuid.uuid4(),
                timestamp=datetime.now(timezone.utc),
            )

    def test_lineage_event_create_requires_source_table(self):
        with pytest.raises(ValueError):
            LineageEventCreate(
                pipeline_id=uuid.uuid4(),
                execution_id=uuid.uuid4(),
                source_system="src",
                source_table="",  # empty not allowed
                destination_system="dest",
                destination_table="dest_table",
                triggered_by=uuid.uuid4(),
                timestamp=datetime.now(timezone.utc),
            )

    def test_lineage_event_create_requires_destination_system(self):
        with pytest.raises(ValueError):
            LineageEventCreate(
                pipeline_id=uuid.uuid4(),
                execution_id=uuid.uuid4(),
                source_system="src",
                source_table="tbl",
                destination_system="",  # empty not allowed
                destination_table="dest_table",
                triggered_by=uuid.uuid4(),
                timestamp=datetime.now(timezone.utc),
            )

    def test_lineage_event_create_requires_destination_table(self):
        with pytest.raises(ValueError):
            LineageEventCreate(
                pipeline_id=uuid.uuid4(),
                execution_id=uuid.uuid4(),
                source_system="src",
                source_table="tbl",
                destination_system="dest",
                destination_table="",  # empty not allowed
                triggered_by=uuid.uuid4(),
                timestamp=datetime.now(timezone.utc),
            )

    def test_lineage_event_response_model(self):
        resp = LineageEventResponse(
            id=uuid.uuid4(),
            pipeline_id=uuid.uuid4(),
            execution_id=uuid.uuid4(),
            source_system="src",
            source_table="src_tbl",
            destination_system="dst",
            destination_table="dst_tbl",
            transformation_node="transform_1",
            triggered_by=uuid.uuid4(),
            timestamp=datetime.now(timezone.utc),
        )
        assert resp.source_system == "src"
        assert resp.transformation_node == "transform_1"

    def test_lineage_graph_empty(self):
        graph = LineageGraph(
            nodes=[],
            edges=[],
            table_name="unknown_table",
            depth=10,
            message="No lineage data available for table 'unknown_table'",
        )
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0
        assert graph.message is not None

    def test_lineage_graph_with_nodes_and_edges(self):
        node1 = LineageGraphNode(
            id="orders", name="orders", type="table", system="pg", table_name="orders"
        )
        node2 = LineageGraphNode(
            id="analytics", name="analytics", type="table", system="ch", table_name="analytics"
        )
        edge = LineageGraphEdge(
            source_id="orders", target_id="analytics", pipeline_name="ETL Pipeline"
        )
        graph = LineageGraph(
            nodes=[node1, node2],
            edges=[edge],
            table_name="orders",
            depth=10,
            message=None,
        )
        assert len(graph.nodes) == 2
        assert len(graph.edges) == 1
        assert graph.edges[0].source_id == "orders"

    def test_lineage_node_metadata_with_data(self):
        meta = LineageNodeMetadata(
            node_id="orders",
            last_execution=datetime.now(timezone.utc),
            row_count=15000,
            triggered_by_user=uuid.uuid4(),
            total_executions=5,
            message=None,
        )
        assert meta.row_count == 15000
        assert meta.total_executions == 5

    def test_lineage_node_metadata_empty(self):
        meta = LineageNodeMetadata(
            node_id="unknown",
            last_execution=None,
            row_count=None,
            triggered_by_user=None,
            total_executions=0,
            message="No metadata available for node 'unknown'",
        )
        assert meta.last_execution is None
        assert meta.message is not None

    def test_retention_config_default(self):
        config = LineageRetentionConfig()
        assert config.retention_days == 365

    def test_retention_config_min_bound(self):
        config = LineageRetentionConfig(retention_days=30)
        assert config.retention_days == 30

    def test_retention_config_max_bound(self):
        config = LineageRetentionConfig(retention_days=2555)
        assert config.retention_days == 2555

    def test_retention_config_below_min_raises(self):
        with pytest.raises(ValueError):
            LineageRetentionConfig(retention_days=29)

    def test_retention_config_above_max_raises(self):
        with pytest.raises(ValueError):
            LineageRetentionConfig(retention_days=2556)


# ---------- LineageService.record_lineage_event ----------


class TestLineageServiceRecordEvent:
    """Tests for recording lineage events."""

    @pytest.mark.asyncio
    async def test_record_event_persists_to_db(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)

        event = _make_lineage_event_create()
        result = await service.record_lineage_event(event)

        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()
        mock_db.refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_record_event_sets_all_fields(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)

        pipeline_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        triggered_by = uuid.uuid4()
        ts = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)

        event = _make_lineage_event_create(
            source_system="mysql_prod",
            source_table="customers",
            destination_system="warehouse",
            destination_table="dim_customers",
            transformation_node="join_address",
            pipeline_id=pipeline_id,
            execution_id=execution_id,
            triggered_by=triggered_by,
            timestamp=ts,
        )

        await service.record_lineage_event(event)

        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.source_system == "mysql_prod"
        assert added_obj.source_table == "customers"
        assert added_obj.destination_system == "warehouse"
        assert added_obj.destination_table == "dim_customers"
        assert added_obj.transformation_node == "join_address"
        assert added_obj.pipeline_id == pipeline_id
        assert added_obj.execution_id == execution_id
        assert added_obj.triggered_by == triggered_by
        assert added_obj.timestamp == ts

    @pytest.mark.asyncio
    async def test_record_event_without_transformation(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)

        event = _make_lineage_event_create(transformation_node=None)
        await service.record_lineage_event(event)

        added_obj = mock_db.add.call_args[0][0]
        assert added_obj.transformation_node is None


# ---------- LineageService.get_lineage_graph ----------


class TestLineageServiceGetGraph:
    """Tests for lineage graph traversal."""

    @pytest.mark.asyncio
    async def test_get_graph_no_data_returns_empty_with_message(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)

        # Mock the exists query to return None (no data)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        graph = await service.get_lineage_graph("unknown_table")

        assert isinstance(graph, LineageGraph)
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0
        assert graph.table_name == "unknown_table"
        assert graph.message is not None
        assert "No lineage data" in graph.message

    @pytest.mark.asyncio
    async def test_get_graph_caps_depth_at_max(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)

        # Mock the exists query to return None (no data) — tests depth capping
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        graph = await service.get_lineage_graph("orders", depth=20)

        # Depth should be capped at 10 (configured max)
        assert graph.depth == 10

    @pytest.mark.asyncio
    async def test_get_graph_uses_requested_depth_when_under_max(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        graph = await service.get_lineage_graph("orders", depth=5)

        assert graph.depth == 5

    @pytest.mark.asyncio
    async def test_get_graph_with_data_performs_bfs(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)

        # First call: exists check — returns an id (data exists)
        mock_exists_result = MagicMock()
        mock_exists_result.scalar_one_or_none.return_value = uuid.uuid4()

        # Subsequent calls for BFS traversal
        # Upstream: find events where "orders" is destination
        upstream_event = _make_mock_lineage_event(
            source_table="raw_orders",
            destination_table="orders",
            source_system="mysql",
            destination_system="pg",
            transformation_node=None,
        )
        mock_upstream_result = MagicMock()
        mock_upstream_scalars = MagicMock()
        mock_upstream_scalars.all.return_value = [upstream_event]
        mock_upstream_result.scalars.return_value = mock_upstream_scalars

        # Second level upstream: find events where "raw_orders" is destination — empty
        mock_empty_result = MagicMock()
        mock_empty_scalars = MagicMock()
        mock_empty_scalars.all.return_value = []
        mock_empty_result.scalars.return_value = mock_empty_scalars

        # Downstream: find events where "orders" is source
        downstream_event = _make_mock_lineage_event(
            source_table="orders",
            destination_table="orders_analytics",
            source_system="pg",
            destination_system="ch",
            transformation_node="agg_daily",
        )
        mock_downstream_result = MagicMock()
        mock_downstream_scalars = MagicMock()
        mock_downstream_scalars.all.return_value = [downstream_event]
        mock_downstream_result.scalars.return_value = mock_downstream_scalars

        # Second level downstream: "orders_analytics" as source — empty
        mock_empty_downstream = MagicMock()
        mock_empty_downstream_scalars = MagicMock()
        mock_empty_downstream_scalars.all.return_value = []
        mock_empty_downstream.scalars.return_value = mock_empty_downstream_scalars

        mock_db.execute = AsyncMock(
            side_effect=[
                mock_exists_result,
                mock_upstream_result,
                mock_empty_result,
                mock_downstream_result,
                mock_empty_downstream,
            ]
        )

        graph = await service.get_lineage_graph("orders", depth=10)

        assert isinstance(graph, LineageGraph)
        assert graph.table_name == "orders"
        assert graph.message is None
        # Should have nodes: raw_orders, orders, orders_analytics, and transformation node
        assert len(graph.nodes) >= 3
        # Should have edges connecting them
        assert len(graph.edges) >= 2

    @pytest.mark.asyncio
    async def test_get_graph_includes_queried_table_as_node(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)

        # Data exists but no upstream/downstream events for the table itself
        mock_exists_result = MagicMock()
        mock_exists_result.scalar_one_or_none.return_value = uuid.uuid4()

        mock_empty_result = MagicMock()
        mock_empty_scalars = MagicMock()
        mock_empty_scalars.all.return_value = []
        mock_empty_result.scalars.return_value = mock_empty_scalars

        # exists + upstream BFS + downstream BFS (both empty)
        mock_db.execute = AsyncMock(
            side_effect=[mock_exists_result, mock_empty_result, mock_empty_result]
        )

        graph = await service.get_lineage_graph("isolated_table", depth=10)

        # The queried table should always be present as a node
        node_ids = [n.id for n in graph.nodes]
        assert "isolated_table" in node_ids


# ---------- LineageService.query_by_time_range ----------


class TestLineageServiceQueryByTimeRange:
    """Tests for time-range filtering."""

    @pytest.mark.asyncio
    async def test_query_returns_events_in_range(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)

        ts1 = datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
        ts2 = datetime(2024, 6, 15, 10, 0, 0, tzinfo=timezone.utc)

        event1 = _make_mock_lineage_event(timestamp=ts1, source_table="t1")
        event2 = _make_mock_lineage_event(timestamp=ts2, source_table="t2")

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [event1, event2]
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        start = datetime(2024, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2024, 6, 30, 23, 59, 59, tzinfo=timezone.utc)

        results = await service.query_by_time_range(start, end)

        assert len(results) == 2
        assert all(isinstance(r, LineageEventResponse) for r in results)

    @pytest.mark.asyncio
    async def test_query_returns_empty_for_no_matches(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        start = datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        end = datetime(2024, 1, 31, 23, 59, 59, tzinfo=timezone.utc)

        results = await service.query_by_time_range(start, end)

        assert results == []

    @pytest.mark.asyncio
    async def test_query_maps_all_fields_to_response(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)

        pipeline_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        user_id = uuid.uuid4()
        ts = datetime(2024, 7, 1, 12, 0, 0, tzinfo=timezone.utc)

        event = _make_mock_lineage_event(
            source_system="src_sys",
            source_table="src_tbl",
            destination_system="dst_sys",
            destination_table="dst_tbl",
            transformation_node="transform_x",
            pipeline_id=pipeline_id,
            execution_id=execution_id,
            triggered_by=user_id,
            timestamp=ts,
        )

        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = [event]
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        results = await service.query_by_time_range(
            datetime(2024, 7, 1, tzinfo=timezone.utc),
            datetime(2024, 7, 2, tzinfo=timezone.utc),
        )

        assert len(results) == 1
        r = results[0]
        assert r.source_system == "src_sys"
        assert r.source_table == "src_tbl"
        assert r.destination_system == "dst_sys"
        assert r.destination_table == "dst_tbl"
        assert r.transformation_node == "transform_x"
        assert r.pipeline_id == pipeline_id
        assert r.execution_id == execution_id
        assert r.triggered_by == user_id
        assert r.timestamp == ts


# ---------- LineageService.get_node_metadata ----------


class TestLineageServiceGetNodeMetadata:
    """Tests for node metadata retrieval."""

    @pytest.mark.asyncio
    async def test_get_metadata_no_data_returns_empty(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)

        # No events found for this node
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = []
        mock_result.scalars.return_value = mock_scalars
        mock_db.execute = AsyncMock(return_value=mock_result)

        metadata = await service.get_node_metadata("nonexistent_table")

        assert isinstance(metadata, LineageNodeMetadata)
        assert metadata.node_id == "nonexistent_table"
        assert metadata.last_execution is None
        assert metadata.row_count is None
        assert metadata.triggered_by_user is None
        assert metadata.total_executions == 0
        assert metadata.message is not None
        assert "No metadata" in metadata.message

    @pytest.mark.asyncio
    async def test_get_metadata_returns_latest_event_data(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)

        user_id = uuid.uuid4()
        execution_id = uuid.uuid4()
        latest_ts = datetime(2024, 8, 15, 10, 0, 0, tzinfo=timezone.utc)
        older_ts = datetime(2024, 7, 1, 10, 0, 0, tzinfo=timezone.utc)

        event1 = _make_mock_lineage_event(
            triggered_by=user_id,
            execution_id=execution_id,
            timestamp=latest_ts,
            source_table="orders",
        )
        event2 = _make_mock_lineage_event(
            triggered_by=uuid.uuid4(),
            timestamp=older_ts,
            source_table="orders",
        )

        # First query: get events for node (ordered by timestamp desc)
        mock_events_result = MagicMock()
        mock_events_scalars = MagicMock()
        mock_events_scalars.all.return_value = [event1, event2]
        mock_events_result.scalars.return_value = mock_events_scalars

        # Second query: get row counts from pipeline run
        mock_row_count_result = MagicMock()
        mock_row_count_result.scalar_one_or_none.return_value = {"orders": 5000}

        mock_db.execute = AsyncMock(
            side_effect=[mock_events_result, mock_row_count_result]
        )

        metadata = await service.get_node_metadata("orders")

        assert metadata.node_id == "orders"
        assert metadata.last_execution == latest_ts
        assert metadata.triggered_by_user == user_id
        assert metadata.total_executions == 2
        assert metadata.row_count == 5000
        assert metadata.message is None

    @pytest.mark.asyncio
    async def test_get_metadata_row_count_none_when_not_available(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)

        event = _make_mock_lineage_event(source_table="orders")

        mock_events_result = MagicMock()
        mock_events_scalars = MagicMock()
        mock_events_scalars.all.return_value = [event]
        mock_events_result.scalars.return_value = mock_events_scalars

        # Row counts not available
        mock_row_count_result = MagicMock()
        mock_row_count_result.scalar_one_or_none.return_value = None

        mock_db.execute = AsyncMock(
            side_effect=[mock_events_result, mock_row_count_result]
        )

        metadata = await service.get_node_metadata("orders")

        assert metadata.row_count is None

    @pytest.mark.asyncio
    async def test_get_metadata_partial_key_match_for_row_count(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)

        event = _make_mock_lineage_event(source_table="orders")

        mock_events_result = MagicMock()
        mock_events_scalars = MagicMock()
        mock_events_scalars.all.return_value = [event]
        mock_events_result.scalars.return_value = mock_events_scalars

        # Row counts has a partial key match (schema.table format)
        mock_row_count_result = MagicMock()
        mock_row_count_result.scalar_one_or_none.return_value = {
            "public.orders": 8000
        }

        mock_db.execute = AsyncMock(
            side_effect=[mock_events_result, mock_row_count_result]
        )

        metadata = await service.get_node_metadata("orders")

        # Should match via partial key "public.orders" ends with "orders"
        assert metadata.row_count == 8000


# ---------- LineageService Retention ----------


class TestLineageServiceRetention:
    """Tests for retention configuration."""

    def test_retention_default_value(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)
        # Default from config is 365
        assert service.retention_days == 365

    def test_retention_setter_valid(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)
        service.retention_days = 90
        assert service.retention_days == 90

    def test_retention_setter_min_bound(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)
        service.retention_days = 30
        assert service.retention_days == 30

    def test_retention_setter_max_bound(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)
        service.retention_days = 2555
        assert service.retention_days == 2555

    def test_retention_setter_below_min_raises(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)
        with pytest.raises(ValueError, match="at least 30 days"):
            service.retention_days = 29

    def test_retention_setter_above_max_raises(self):
        mock_db = AsyncMock()
        service = LineageService(mock_db)
        with pytest.raises(ValueError, match="must not exceed 2555"):
            service.retention_days = 2556
