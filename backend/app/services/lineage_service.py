"""Lineage Service — lineage event recording, graph traversal, time-range queries.

This service manages data lineage tracking by storing lineage events in PostgreSQL
(with the lineage_events table) and providing graph traversal capabilities for
upstream/downstream lineage analysis.

Note: While the design targets ClickHouse for high-throughput analytics,
the service currently uses PostgreSQL for lineage storage. The interface
is designed to be swappable to ClickHouse when ready.
"""

from collections import deque
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.core.config import settings
from backend.app.models.lineage import LineageEvent
from backend.app.models.pipelines import PipelineRun
from backend.app.schemas.lineage import (
    LineageEventCreate,
    LineageEventResponse,
    LineageGraph,
    LineageGraphEdge,
    LineageGraphNode,
    LineageNodeMetadata,
)


class LineageService:
    """Service for managing data lineage tracking.

    Provides:
    - record_lineage_event: Store a lineage event for a data movement step
    - get_lineage_graph: Traverse upstream/downstream lineage up to N levels
    - query_by_time_range: Filter lineage events within a time range
    - get_node_metadata: Retrieve metadata for a specific lineage node
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self._max_depth = settings.lineage_max_traversal_depth
        self._retention_days = settings.lineage_retention_days

    async def record_lineage_event(self, event: LineageEventCreate) -> LineageEvent:
        """Record a lineage event for a data movement step.

        Creates a record capturing the source, destination, transformation,
        pipeline, execution, user, and timestamp of a data movement.

        Args:
            event: The lineage event data to record.

        Returns:
            The persisted LineageEvent entry.
        """
        lineage_event = LineageEvent(
            pipeline_id=event.pipeline_id,
            execution_id=event.execution_id,
            source_system=event.source_system,
            source_table=event.source_table,
            destination_system=event.destination_system,
            destination_table=event.destination_table,
            transformation_node=event.transformation_node,
            triggered_by=event.triggered_by,
            timestamp=event.timestamp,
        )
        self.db.add(lineage_event)
        await self.db.flush()
        await self.db.refresh(lineage_event)
        return lineage_event

    async def get_lineage_graph(
        self, table_name: str, depth: int = 10
    ) -> LineageGraph:
        """Return upstream and downstream lineage graph for a table.

        Performs BFS traversal up to `depth` levels in each direction
        (upstream and downstream) from the specified table.

        Args:
            table_name: The table name to query lineage for.
            depth: Maximum traversal depth (capped at configured max, default 10).

        Returns:
            LineageGraph containing nodes and edges, or empty graph with message
            if no lineage data exists for the table.
        """
        # Cap depth at configured maximum
        effective_depth = min(depth, self._max_depth)

        # Check if the table has any lineage data
        exists_query = select(LineageEvent.id).where(
            or_(
                LineageEvent.source_table == table_name,
                LineageEvent.destination_table == table_name,
            )
        ).limit(1)
        result = await self.db.execute(exists_query)
        if result.scalar_one_or_none() is None:
            return LineageGraph(
                nodes=[],
                edges=[],
                table_name=table_name,
                depth=effective_depth,
                message=f"No lineage data available for table '{table_name}'",
            )

        nodes: dict[str, LineageGraphNode] = {}
        edges: list[LineageGraphEdge] = []
        visited_edges: set[tuple[str, str]] = set()

        # BFS upstream (traverse from destination back to source)
        await self._traverse_direction(
            table_name=table_name,
            depth=effective_depth,
            direction="upstream",
            nodes=nodes,
            edges=edges,
            visited_edges=visited_edges,
        )

        # BFS downstream (traverse from source forward to destination)
        await self._traverse_direction(
            table_name=table_name,
            depth=effective_depth,
            direction="downstream",
            nodes=nodes,
            edges=edges,
            visited_edges=visited_edges,
        )

        # Ensure the queried table itself is in the node set
        if table_name not in nodes:
            nodes[table_name] = LineageGraphNode(
                id=table_name,
                name=table_name,
                type="table",
                system=None,
                table_name=table_name,
                metadata=None,
            )

        return LineageGraph(
            nodes=list(nodes.values()),
            edges=edges,
            table_name=table_name,
            depth=effective_depth,
            message=None,
        )

    async def query_by_time_range(
        self, start: datetime, end: datetime
    ) -> list[LineageEventResponse]:
        """Filter lineage events within a time range (inclusive).

        Args:
            start: Start of the time range (inclusive).
            end: End of the time range (inclusive).

        Returns:
            List of lineage events with timestamps within [start, end].
        """
        query = (
            select(LineageEvent)
            .where(
                and_(
                    LineageEvent.timestamp >= start,
                    LineageEvent.timestamp <= end,
                )
            )
            .order_by(LineageEvent.timestamp.asc())
        )

        result = await self.db.execute(query)
        events = result.scalars().all()

        return [
            LineageEventResponse(
                id=event.id,
                pipeline_id=event.pipeline_id,
                execution_id=event.execution_id,
                source_system=event.source_system,
                source_table=event.source_table,
                destination_system=event.destination_system,
                destination_table=event.destination_table,
                transformation_node=event.transformation_node,
                triggered_by=event.triggered_by,
                timestamp=event.timestamp,
            )
            for event in events
        ]

    async def get_node_metadata(self, node_id: str) -> LineageNodeMetadata:
        """Return metadata for a lineage node.

        Retrieves the last execution timestamp, row count, and triggering user
        for the most recent execution involving the specified node.

        Args:
            node_id: The node identifier (typically a table name).

        Returns:
            LineageNodeMetadata with execution details, or message if no data.
        """
        # Find events where this node appears as source or destination
        query = (
            select(LineageEvent)
            .where(
                or_(
                    LineageEvent.source_table == node_id,
                    LineageEvent.destination_table == node_id,
                )
            )
            .order_by(LineageEvent.timestamp.desc())
        )

        result = await self.db.execute(query)
        events = result.scalars().all()

        if not events:
            return LineageNodeMetadata(
                node_id=node_id,
                last_execution=None,
                row_count=None,
                triggered_by_user=None,
                total_executions=0,
                message=f"No metadata available for node '{node_id}'",
            )

        latest_event = events[0]
        total_executions = len(events)

        # Attempt to get row count from the pipeline run's node_row_counts
        row_count = await self._get_row_count_for_node(
            latest_event.execution_id, node_id
        )

        return LineageNodeMetadata(
            node_id=node_id,
            last_execution=latest_event.timestamp,
            row_count=row_count,
            triggered_by_user=latest_event.triggered_by,
            total_executions=total_executions,
            message=None,
        )

    async def _get_row_count_for_node(
        self, execution_id, node_id: str
    ) -> int | None:
        """Look up the row count for a node from the pipeline run's node_row_counts.

        Args:
            execution_id: The execution/run ID to look up.
            node_id: The node identifier (table name).

        Returns:
            The row count if available, None otherwise.
        """
        run_query = select(PipelineRun.node_row_counts).where(
            PipelineRun.id == execution_id
        )
        result = await self.db.execute(run_query)
        row_counts = result.scalar_one_or_none()

        if row_counts and isinstance(row_counts, dict):
            # Try exact match first, then partial match on table name
            if node_id in row_counts:
                return row_counts[node_id]
            # Check if node_id appears as a value suffix (e.g., "schema.table")
            for key, value in row_counts.items():
                if key.endswith(node_id) or node_id.endswith(key):
                    return value

        return None

    @property
    def retention_days(self) -> int:
        """Return the configured retention period in days."""
        return self._retention_days

    @retention_days.setter
    def retention_days(self, value: int) -> None:
        """Set the retention period, enforcing min/max bounds."""
        if value < 30:
            raise ValueError("Retention period must be at least 30 days")
        if value > 2555:
            raise ValueError("Retention period must not exceed 2555 days")
        self._retention_days = value

    async def _traverse_direction(
        self,
        table_name: str,
        depth: int,
        direction: str,
        nodes: dict[str, LineageGraphNode],
        edges: list[LineageGraphEdge],
        visited_edges: set[tuple[str, str]],
    ) -> None:
        """BFS traversal in one direction (upstream or downstream).

        Args:
            table_name: Starting table for traversal.
            depth: Maximum number of levels to traverse.
            direction: 'upstream' or 'downstream'.
            nodes: Accumulated nodes dict (mutated in place).
            edges: Accumulated edges list (mutated in place).
            visited_edges: Set of visited edge tuples to avoid duplicates.
        """
        queue: deque[tuple[str, int]] = deque()
        queue.append((table_name, 0))
        visited_tables: set[str] = {table_name}

        while queue:
            current_table, current_depth = queue.popleft()

            if current_depth >= depth:
                continue

            if direction == "upstream":
                # Find events where current_table is a destination
                query = select(LineageEvent).where(
                    LineageEvent.destination_table == current_table
                )
            else:
                # Find events where current_table is a source
                query = select(LineageEvent).where(
                    LineageEvent.source_table == current_table
                )

            result = await self.db.execute(query)
            events = result.scalars().all()

            for event in events:
                source_id = event.source_table
                target_id = event.destination_table

                # Add source node
                if source_id not in nodes:
                    nodes[source_id] = LineageGraphNode(
                        id=source_id,
                        name=source_id,
                        type="table",
                        system=event.source_system,
                        table_name=source_id,
                        metadata=None,
                    )

                # Add transformation node if present
                if event.transformation_node:
                    transform_id = (
                        f"{source_id}__{event.transformation_node}__{target_id}"
                    )
                    if transform_id not in nodes:
                        nodes[transform_id] = LineageGraphNode(
                            id=transform_id,
                            name=event.transformation_node,
                            type="transformation",
                            system=None,
                            table_name=None,
                            metadata=None,
                        )

                    # Edge: source → transformation
                    edge_key_1 = (source_id, transform_id)
                    if edge_key_1 not in visited_edges:
                        visited_edges.add(edge_key_1)
                        edges.append(
                            LineageGraphEdge(
                                source_id=source_id,
                                target_id=transform_id,
                                pipeline_name=str(event.pipeline_id),
                                last_execution=event.timestamp,
                            )
                        )

                    # Edge: transformation → destination
                    edge_key_2 = (transform_id, target_id)
                    if edge_key_2 not in visited_edges:
                        visited_edges.add(edge_key_2)
                        edges.append(
                            LineageGraphEdge(
                                source_id=transform_id,
                                target_id=target_id,
                                pipeline_name=str(event.pipeline_id),
                                last_execution=event.timestamp,
                            )
                        )
                else:
                    # Direct edge: source → destination
                    edge_key = (source_id, target_id)
                    if edge_key not in visited_edges:
                        visited_edges.add(edge_key)
                        edges.append(
                            LineageGraphEdge(
                                source_id=source_id,
                                target_id=target_id,
                                pipeline_name=str(event.pipeline_id),
                                last_execution=event.timestamp,
                            )
                        )

                # Add destination node
                if target_id not in nodes:
                    nodes[target_id] = LineageGraphNode(
                        id=target_id,
                        name=target_id,
                        type="table",
                        system=event.destination_system,
                        table_name=target_id,
                        metadata=None,
                    )

                # Determine next table to traverse
                if direction == "upstream":
                    next_table = source_id
                else:
                    next_table = target_id

                if next_table not in visited_tables:
                    visited_tables.add(next_table)
                    queue.append((next_table, current_depth + 1))


def get_lineage_service(db: AsyncSession) -> LineageService:
    """Factory function for dependency injection of LineageService."""
    return LineageService(db)
