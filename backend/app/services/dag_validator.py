"""DAG Validator — Validates pipeline DAG topology, flow rules, cycles, limits, and completeness.

Validates:
- Edge flow direction: source→transform/destination, transform→transform/destination,
  destination has no outgoing, source has no incoming
- Cycle detection using Kahn's algorithm (topological sort)
- Limits: maximum 50 nodes, 100 edges
- Completeness: at least one source, one destination, connected path, required config fields
- Returns structured validation errors identifying each invalid/incomplete node

Requirements: 5.3, 5.4, 5.9, 5.11, 5.13
"""

from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class NodeType(str, Enum):
    """Allowed pipeline node types."""

    SOURCE = "source"
    TRANSFORMATION = "transformation"
    DESTINATION = "destination"


class ValidationErrorType(str, Enum):
    """Types of DAG validation errors."""

    INVALID_EDGE = "invalid_edge"
    CYCLE_DETECTED = "cycle_detected"
    EXCEEDS_NODE_LIMIT = "exceeds_node_limit"
    EXCEEDS_EDGE_LIMIT = "exceeds_edge_limit"
    MISSING_SOURCE = "missing_source"
    MISSING_DESTINATION = "missing_destination"
    DISCONNECTED_GRAPH = "disconnected_graph"
    MISSING_CONFIG = "missing_config"
    INVALID_NODE_TYPE = "invalid_node_type"
    INVALID_NODE_SUBTYPE = "invalid_node_subtype"


@dataclass
class ValidationError:
    """A single validation error with context."""

    node_id: str | None
    error_type: ValidationErrorType
    message: str


@dataclass
class ValidationResult:
    """Result of DAG validation."""

    is_valid: bool
    errors: list[ValidationError] = field(default_factory=list)


@dataclass
class DAGNode:
    """Represents a node in the DAG for validation purposes."""

    id: str
    node_type: str  # "source", "transformation", "destination"
    node_subtype: str  # e.g., "postgresql_source", "filter_rows"
    config: dict[str, Any] = field(default_factory=dict)


@dataclass
class DAGEdge:
    """Represents a directed edge in the DAG."""

    source_node_id: str
    target_node_id: str


# Maximum limits per pipeline
MAX_NODES = 50
MAX_EDGES = 100

# Valid node subtypes per type
VALID_SOURCE_SUBTYPES = {
    "postgresql_source",
    "mysql_source",
    "csv_source",
    "excel_source",
    "rest_source",
}

VALID_TRANSFORMATION_SUBTYPES = {
    "select_columns",
    "filter_rows",
    "rename_columns",
    "aggregate",
    "join",
}

VALID_DESTINATION_SUBTYPES = {
    "postgresql_destination",
    "clickhouse_destination",
}

# Required configuration fields per node subtype
REQUIRED_CONFIG_FIELDS: dict[str, list[str]] = {
    # Sources
    "postgresql_source": ["connector_id", "table_name"],
    "mysql_source": ["connector_id", "table_name"],
    "csv_source": ["file_path"],
    "excel_source": ["file_path", "sheet_name"],
    "rest_source": ["connector_id", "endpoint"],
    # Transformations
    "select_columns": ["columns"],
    "filter_rows": ["condition"],
    "rename_columns": ["mapping"],
    "aggregate": ["group_by", "aggregations"],
    "join": ["join_type", "join_key"],
    # Destinations
    "postgresql_destination": ["connector_id", "table_name", "write_mode"],
    "clickhouse_destination": ["connector_id", "table_name", "write_mode"],
}

# Allowed edge flow rules:
# source → transformation (allowed)
# source → destination (allowed)
# transformation → transformation (allowed)
# transformation → destination (allowed)
# destination → anything (NOT allowed)
# anything → source (NOT allowed — sources have no incoming)
ALLOWED_EDGE_TARGETS: dict[str, set[str]] = {
    NodeType.SOURCE: {NodeType.TRANSFORMATION, NodeType.DESTINATION},
    NodeType.TRANSFORMATION: {NodeType.TRANSFORMATION, NodeType.DESTINATION},
    NodeType.DESTINATION: set(),  # No outgoing edges from destinations
}


class DAGValidator:
    """Validates pipeline DAG structure, topology, and completeness.

    Performs the following validations:
    1. Node type and subtype validity
    2. Edge flow direction rules
    3. Cycle detection (Kahn's algorithm)
    4. Size limits (max 50 nodes, 100 edges)
    5. Completeness (at least 1 source, 1 destination, connected path, required config)
    """

    def validate(self, nodes: list[DAGNode], edges: list[DAGEdge]) -> ValidationResult:
        """Validate the complete DAG structure.

        Args:
            nodes: List of DAGNode instances in the pipeline.
            edges: List of DAGEdge instances connecting nodes.

        Returns:
            ValidationResult with is_valid flag and list of errors.
        """
        errors: list[ValidationError] = []

        # Build lookup maps
        node_map: dict[str, DAGNode] = {node.id: node for node in nodes}

        # 1. Validate size limits
        errors.extend(self._validate_limits(nodes, edges))

        # 2. Validate node types and subtypes
        errors.extend(self._validate_node_types(nodes))

        # 3. Validate edge flow direction
        errors.extend(self._validate_edge_flow(edges, node_map))

        # 4. Detect cycles using Kahn's algorithm
        errors.extend(self._detect_cycles(nodes, edges))

        # 5. Validate completeness
        errors.extend(self._validate_completeness(nodes, edges, node_map))

        # 6. Validate required config fields
        errors.extend(self._validate_config_fields(nodes))

        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
        )

    def _validate_limits(
        self, nodes: list[DAGNode], edges: list[DAGEdge]
    ) -> list[ValidationError]:
        """Check that node and edge counts are within allowed limits."""
        errors: list[ValidationError] = []

        if len(nodes) > MAX_NODES:
            errors.append(
                ValidationError(
                    node_id=None,
                    error_type=ValidationErrorType.EXCEEDS_NODE_LIMIT,
                    message=f"Pipeline has {len(nodes)} nodes, maximum allowed is {MAX_NODES}",
                )
            )

        if len(edges) > MAX_EDGES:
            errors.append(
                ValidationError(
                    node_id=None,
                    error_type=ValidationErrorType.EXCEEDS_EDGE_LIMIT,
                    message=f"Pipeline has {len(edges)} edges, maximum allowed is {MAX_EDGES}",
                )
            )

        return errors

    def _validate_node_types(self, nodes: list[DAGNode]) -> list[ValidationError]:
        """Validate that all node types and subtypes are recognized."""
        errors: list[ValidationError] = []
        valid_types = {t.value for t in NodeType}

        all_valid_subtypes = (
            VALID_SOURCE_SUBTYPES | VALID_TRANSFORMATION_SUBTYPES | VALID_DESTINATION_SUBTYPES
        )

        for node in nodes:
            if node.node_type not in valid_types:
                errors.append(
                    ValidationError(
                        node_id=node.id,
                        error_type=ValidationErrorType.INVALID_NODE_TYPE,
                        message=f"Node '{node.id}' has invalid type '{node.node_type}'. "
                        f"Must be one of: {', '.join(sorted(valid_types))}",
                    )
                )
            elif node.node_subtype not in all_valid_subtypes:
                errors.append(
                    ValidationError(
                        node_id=node.id,
                        error_type=ValidationErrorType.INVALID_NODE_SUBTYPE,
                        message=f"Node '{node.id}' has invalid subtype '{node.node_subtype}'",
                    )
                )
            else:
                # Validate subtype belongs to the correct type
                if node.node_type == NodeType.SOURCE and node.node_subtype not in VALID_SOURCE_SUBTYPES:
                    errors.append(
                        ValidationError(
                            node_id=node.id,
                            error_type=ValidationErrorType.INVALID_NODE_SUBTYPE,
                            message=f"Node '{node.id}' subtype '{node.node_subtype}' is not a valid source subtype",
                        )
                    )
                elif node.node_type == NodeType.TRANSFORMATION and node.node_subtype not in VALID_TRANSFORMATION_SUBTYPES:
                    errors.append(
                        ValidationError(
                            node_id=node.id,
                            error_type=ValidationErrorType.INVALID_NODE_SUBTYPE,
                            message=f"Node '{node.id}' subtype '{node.node_subtype}' is not a valid transformation subtype",
                        )
                    )
                elif node.node_type == NodeType.DESTINATION and node.node_subtype not in VALID_DESTINATION_SUBTYPES:
                    errors.append(
                        ValidationError(
                            node_id=node.id,
                            error_type=ValidationErrorType.INVALID_NODE_SUBTYPE,
                            message=f"Node '{node.id}' subtype '{node.node_subtype}' is not a valid destination subtype",
                        )
                    )

        return errors

    def _validate_edge_flow(
        self, edges: list[DAGEdge], node_map: dict[str, DAGNode]
    ) -> list[ValidationError]:
        """Validate that edges follow permitted flow direction rules.

        Rules:
        - source → transformation/destination (allowed)
        - transformation → transformation/destination (allowed)
        - destination → anything (NOT allowed — no outgoing from destination)
        - anything → source (NOT allowed — source has no incoming)
        """
        errors: list[ValidationError] = []

        for edge in edges:
            source_node = node_map.get(edge.source_node_id)
            target_node = node_map.get(edge.target_node_id)

            if source_node is None or target_node is None:
                # Skip edges referencing non-existent nodes (will be caught elsewhere)
                continue

            source_type = source_node.node_type
            target_type = target_node.node_type

            # Rule: destination nodes cannot have outgoing edges
            if source_type == NodeType.DESTINATION:
                errors.append(
                    ValidationError(
                        node_id=edge.source_node_id,
                        error_type=ValidationErrorType.INVALID_EDGE,
                        message=f"Destination node '{edge.source_node_id}' cannot have outgoing edges",
                    )
                )
            # Rule: source nodes cannot have incoming edges
            elif target_type == NodeType.SOURCE:
                errors.append(
                    ValidationError(
                        node_id=edge.target_node_id,
                        error_type=ValidationErrorType.INVALID_EDGE,
                        message=f"Source node '{edge.target_node_id}' cannot have incoming edges",
                    )
                )
            # Check allowed target types for the source node type
            elif target_type not in ALLOWED_EDGE_TARGETS.get(source_type, set()):
                errors.append(
                    ValidationError(
                        node_id=edge.source_node_id,
                        error_type=ValidationErrorType.INVALID_EDGE,
                        message=f"Edge from '{source_type}' node '{edge.source_node_id}' to "
                        f"'{target_type}' node '{edge.target_node_id}' is not allowed",
                    )
                )

        return errors

    def _detect_cycles(
        self, nodes: list[DAGNode], edges: list[DAGEdge]
    ) -> list[ValidationError]:
        """Detect cycles using Kahn's algorithm (topological sort).

        If not all nodes can be processed through topological sort,
        a cycle exists in the graph.

        Returns:
            List with a single CYCLE_DETECTED error if a cycle exists, empty otherwise.
        """
        if not nodes:
            return []

        # Build adjacency list and in-degree map
        node_ids = {node.id for node in nodes}
        in_degree: dict[str, int] = {node_id: 0 for node_id in node_ids}
        adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_ids}

        for edge in edges:
            if edge.source_node_id in node_ids and edge.target_node_id in node_ids:
                adjacency[edge.source_node_id].append(edge.target_node_id)
                in_degree[edge.target_node_id] += 1

        # Initialize queue with nodes that have no incoming edges
        queue: deque[str] = deque()
        for node_id, degree in in_degree.items():
            if degree == 0:
                queue.append(node_id)

        processed_count = 0

        while queue:
            current = queue.popleft()
            processed_count += 1

            for neighbor in adjacency[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        if processed_count < len(node_ids):
            # Cycle detected — identify nodes involved
            cycle_nodes = [
                node_id for node_id, degree in in_degree.items() if degree > 0
            ]
            return [
                ValidationError(
                    node_id=None,
                    error_type=ValidationErrorType.CYCLE_DETECTED,
                    message=f"Cycle detected in pipeline graph involving nodes: "
                    f"{', '.join(sorted(cycle_nodes))}",
                )
            ]

        return []

    def _validate_completeness(
        self,
        nodes: list[DAGNode],
        edges: list[DAGEdge],
        node_map: dict[str, DAGNode],
    ) -> list[ValidationError]:
        """Validate pipeline completeness requirements.

        - At least 1 source node
        - At least 1 destination node
        - Connected path from at least one source to at least one destination
        """
        errors: list[ValidationError] = []

        source_nodes = [n for n in nodes if n.node_type == NodeType.SOURCE]
        destination_nodes = [n for n in nodes if n.node_type == NodeType.DESTINATION]

        if not source_nodes:
            errors.append(
                ValidationError(
                    node_id=None,
                    error_type=ValidationErrorType.MISSING_SOURCE,
                    message="Pipeline must have at least one source node",
                )
            )

        if not destination_nodes:
            errors.append(
                ValidationError(
                    node_id=None,
                    error_type=ValidationErrorType.MISSING_DESTINATION,
                    message="Pipeline must have at least one destination node",
                )
            )

        # Only check connectivity if we have both sources and destinations
        if source_nodes and destination_nodes:
            if not self._has_connected_path(source_nodes, destination_nodes, nodes, edges):
                errors.append(
                    ValidationError(
                        node_id=None,
                        error_type=ValidationErrorType.DISCONNECTED_GRAPH,
                        message="Pipeline must have a connected path from at least one "
                        "source to at least one destination",
                    )
                )

        return errors

    def _has_connected_path(
        self,
        source_nodes: list[DAGNode],
        destination_nodes: list[DAGNode],
        nodes: list[DAGNode],
        edges: list[DAGEdge],
    ) -> bool:
        """Check if there's a connected path from any source to any destination.

        Uses BFS from each source node to check reachability.
        """
        # Build adjacency list
        adjacency: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            adjacency[edge.source_node_id].append(edge.target_node_id)

        destination_ids = {n.id for n in destination_nodes}

        # BFS from each source
        for source in source_nodes:
            visited: set[str] = set()
            queue: deque[str] = deque([source.id])
            visited.add(source.id)

            while queue:
                current = queue.popleft()
                if current in destination_ids:
                    return True

                for neighbor in adjacency.get(current, []):
                    if neighbor not in visited:
                        visited.add(neighbor)
                        queue.append(neighbor)

        return False

    def _validate_config_fields(self, nodes: list[DAGNode]) -> list[ValidationError]:
        """Validate that all nodes have their required configuration fields populated."""
        errors: list[ValidationError] = []

        for node in nodes:
            required_fields = REQUIRED_CONFIG_FIELDS.get(node.node_subtype, [])
            if not required_fields:
                continue

            config = node.config or {}

            for field_name in required_fields:
                value = config.get(field_name)
                if value is None or (isinstance(value, (str, list, dict)) and not value):
                    errors.append(
                        ValidationError(
                            node_id=node.id,
                            error_type=ValidationErrorType.MISSING_CONFIG,
                            message=f"Node '{node.id}' ({node.node_subtype}) is missing "
                            f"required config field '{field_name}'",
                        )
                    )

        return errors
