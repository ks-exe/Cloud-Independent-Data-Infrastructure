"""Unit tests for DAG Validator — pipeline graph topology validation.

Tests cover:
- Valid DAG acceptance
- Edge flow direction validation
- Cycle detection (Kahn's algorithm)
- Size limit enforcement (50 nodes, 100 edges)
- Completeness validation (source, destination, connected path)
- Config field validation per node subtype

Requirements: 5.3, 5.4, 5.9, 5.11, 5.13
"""

import pytest

from backend.app.services.dag_validator import (
    DAGEdge,
    DAGNode,
    DAGValidator,
    ValidationErrorType,
    ValidationResult,
)


@pytest.fixture
def validator():
    """Create a DAGValidator instance."""
    return DAGValidator()


# --- Helper factories ---

def _source_node(
    node_id: str = "src1",
    subtype: str = "postgresql_source",
    config: dict | None = None,
) -> DAGNode:
    """Helper to create a valid source node."""
    if config is None:
        config = {"connector_id": "conn-1", "table_name": "users"}
    return DAGNode(id=node_id, node_type="source", node_subtype=subtype, config=config)


def _transform_node(
    node_id: str = "t1",
    subtype: str = "filter_rows",
    config: dict | None = None,
) -> DAGNode:
    """Helper to create a valid transformation node."""
    if config is None:
        config = {"condition": "age > 18"}
    return DAGNode(id=node_id, node_type="transformation", node_subtype=subtype, config=config)


def _dest_node(
    node_id: str = "dst1",
    subtype: str = "postgresql_destination",
    config: dict | None = None,
) -> DAGNode:
    """Helper to create a valid destination node."""
    if config is None:
        config = {"connector_id": "conn-2", "table_name": "output", "write_mode": "append"}
    return DAGNode(id=node_id, node_type="destination", node_subtype=subtype, config=config)


# =============================================================================
# Test: Valid DAG Acceptance
# =============================================================================


class TestValidDAGAcceptance:
    """Test that valid DAGs pass validation."""

    def test_simple_source_to_destination(self, validator):
        """Minimal valid pipeline: source → destination."""
        nodes = [_source_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = validator.validate(nodes, edges)
        assert result.is_valid is True
        assert result.errors == []

    def test_source_transform_destination(self, validator):
        """source → transformation → destination."""
        nodes = [_source_node(), _transform_node(), _dest_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is True
        assert result.errors == []

    def test_multiple_transformations_chained(self, validator):
        """source → t1 → t2 → destination."""
        nodes = [
            _source_node(),
            _transform_node("t1", "filter_rows", {"condition": "x > 0"}),
            _transform_node("t2", "select_columns", {"columns": ["a", "b"]}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="t2"),
            DAGEdge(source_node_id="t2", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is True

    def test_multiple_sources_single_destination(self, validator):
        """Two sources merge into one destination via a join."""
        nodes = [
            _source_node("src1", "postgresql_source", {"connector_id": "c1", "table_name": "t1"}),
            _source_node("src2", "mysql_source", {"connector_id": "c2", "table_name": "t2"}),
            _transform_node("join1", "join", {"join_type": "inner", "join_key": "id"}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="join1"),
            DAGEdge(source_node_id="src2", target_node_id="join1"),
            DAGEdge(source_node_id="join1", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is True

    def test_fan_out_source_to_multiple_destinations(self, validator):
        """One source fans out to two separate destinations."""
        nodes = [
            _source_node(),
            _dest_node("dst1", "postgresql_destination", {"connector_id": "c1", "table_name": "a", "write_mode": "append"}),
            _dest_node("dst2", "clickhouse_destination", {"connector_id": "c2", "table_name": "b", "write_mode": "replace"}),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="dst1"),
            DAGEdge(source_node_id="src1", target_node_id="dst2"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is True

    def test_all_source_subtypes_valid(self, validator):
        """All source subtypes pass validation with correct config."""
        configs = {
            "postgresql_source": {"connector_id": "c", "table_name": "t"},
            "mysql_source": {"connector_id": "c", "table_name": "t"},
            "csv_source": {"file_path": "/data/file.csv"},
            "excel_source": {"file_path": "/data/file.xlsx", "sheet_name": "Sheet1"},
            "rest_source": {"connector_id": "c", "endpoint": "/api/data"},
        }
        for i, (subtype, config) in enumerate(configs.items()):
            nodes = [_source_node(f"src{i}", subtype, config), _dest_node()]
            edges = [DAGEdge(source_node_id=f"src{i}", target_node_id="dst1")]
            result = validator.validate(nodes, edges)
            assert result.is_valid is True, f"Failed for source subtype: {subtype}"


# =============================================================================
# Test: Edge Flow Direction Validation
# =============================================================================


class TestEdgeFlowValidation:
    """Test edge direction rules are enforced."""

    def test_destination_cannot_have_outgoing_edge(self, validator):
        """Destination → anything is NOT allowed."""
        nodes = [_source_node(), _dest_node(), _transform_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="dst1"),
            DAGEdge(source_node_id="dst1", target_node_id="t1"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        invalid_edges = [e for e in result.errors if e.error_type == ValidationErrorType.INVALID_EDGE]
        assert len(invalid_edges) >= 1
        assert any("dst1" in e.message for e in invalid_edges)

    def test_source_cannot_have_incoming_edge(self, validator):
        """Anything → source is NOT allowed (source has no incoming)."""
        nodes = [_source_node("src1"), _source_node("src2", config={"connector_id": "c", "table_name": "t"}), _dest_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="src2"),
            DAGEdge(source_node_id="src1", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        invalid_edges = [e for e in result.errors if e.error_type == ValidationErrorType.INVALID_EDGE]
        assert len(invalid_edges) >= 1
        assert any("src2" in e.message for e in invalid_edges)

    def test_destination_to_destination_not_allowed(self, validator):
        """Destination → destination is NOT allowed."""
        nodes = [
            _source_node(),
            _dest_node("dst1"),
            _dest_node("dst2", config={"connector_id": "c", "table_name": "t", "write_mode": "append"}),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="dst1"),
            DAGEdge(source_node_id="dst1", target_node_id="dst2"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        invalid_edges = [e for e in result.errors if e.error_type == ValidationErrorType.INVALID_EDGE]
        assert len(invalid_edges) >= 1

    def test_source_to_transformation_allowed(self, validator):
        """source → transformation is allowed."""
        nodes = [_source_node(), _transform_node(), _dest_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is True

    def test_transformation_to_transformation_allowed(self, validator):
        """transformation → transformation is allowed."""
        nodes = [
            _source_node(),
            _transform_node("t1", "filter_rows", {"condition": "x > 0"}),
            _transform_node("t2", "select_columns", {"columns": ["col1"]}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="t2"),
            DAGEdge(source_node_id="t2", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is True

    def test_transformation_to_destination_allowed(self, validator):
        """transformation → destination is allowed."""
        nodes = [_source_node(), _transform_node(), _dest_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is True


# =============================================================================
# Test: Cycle Detection
# =============================================================================


class TestCycleDetection:
    """Test cycle detection using Kahn's algorithm."""

    def test_simple_cycle_detected(self, validator):
        """A → B → A creates a cycle."""
        nodes = [
            _source_node(),
            _transform_node("t1", "filter_rows", {"condition": "x"}),
            _transform_node("t2", "select_columns", {"columns": ["a"]}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="t2"),
            DAGEdge(source_node_id="t2", target_node_id="t1"),  # creates cycle
            DAGEdge(source_node_id="t2", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        cycle_errors = [e for e in result.errors if e.error_type == ValidationErrorType.CYCLE_DETECTED]
        assert len(cycle_errors) == 1
        assert "t1" in cycle_errors[0].message
        assert "t2" in cycle_errors[0].message

    def test_three_node_cycle_detected(self, validator):
        """A → B → C → A creates a cycle."""
        nodes = [
            _source_node(),
            _transform_node("t1", "filter_rows", {"condition": "x"}),
            _transform_node("t2", "select_columns", {"columns": ["a"]}),
            _transform_node("t3", "rename_columns", {"mapping": {"a": "b"}}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="t2"),
            DAGEdge(source_node_id="t2", target_node_id="t3"),
            DAGEdge(source_node_id="t3", target_node_id="t1"),  # creates cycle
            DAGEdge(source_node_id="t3", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        cycle_errors = [e for e in result.errors if e.error_type == ValidationErrorType.CYCLE_DETECTED]
        assert len(cycle_errors) == 1

    def test_no_cycle_in_valid_dag(self, validator):
        """Linear DAG has no cycle."""
        nodes = [_source_node(), _transform_node(), _dest_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        cycle_errors = [e for e in result.errors if e.error_type == ValidationErrorType.CYCLE_DETECTED]
        assert len(cycle_errors) == 0


# =============================================================================
# Test: Size Limit Enforcement
# =============================================================================


class TestSizeLimits:
    """Test max nodes (50) and max edges (100) enforcement."""

    def test_exceeds_max_nodes(self, validator):
        """Pipeline with 51 nodes should fail."""
        nodes = [_source_node()]
        for i in range(49):
            nodes.append(_transform_node(f"t{i}", "filter_rows", {"condition": "x"}))
        nodes.append(_dest_node())
        # 51 nodes total — exceeds limit of 50
        edges = [DAGEdge(source_node_id="src1", target_node_id="t0")]
        for i in range(48):
            edges.append(DAGEdge(source_node_id=f"t{i}", target_node_id=f"t{i+1}"))
        edges.append(DAGEdge(source_node_id="t48", target_node_id="dst1"))

        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        limit_errors = [e for e in result.errors if e.error_type == ValidationErrorType.EXCEEDS_NODE_LIMIT]
        assert len(limit_errors) == 1
        assert "51" in limit_errors[0].message

    def test_exactly_50_nodes_is_valid(self, validator):
        """Pipeline with exactly 50 nodes should pass size limit check."""
        nodes = [_source_node()]
        for i in range(48):
            nodes.append(_transform_node(f"t{i}", "filter_rows", {"condition": "x"}))
        nodes.append(_dest_node())
        # 50 nodes total — within limit
        edges = [DAGEdge(source_node_id="src1", target_node_id="t0")]
        for i in range(47):
            edges.append(DAGEdge(source_node_id=f"t{i}", target_node_id=f"t{i+1}"))
        edges.append(DAGEdge(source_node_id="t47", target_node_id="dst1"))

        result = validator.validate(nodes, edges)
        limit_errors = [e for e in result.errors if e.error_type == ValidationErrorType.EXCEEDS_NODE_LIMIT]
        assert len(limit_errors) == 0

    def test_exceeds_max_edges(self, validator):
        """Pipeline with 101 edges should fail."""
        # Create enough nodes to support 101 edges
        # Fan-out pattern: source connects to many transforms, each to destination
        nodes = [_source_node()]
        for i in range(100):
            nodes.append(_transform_node(f"t{i}", "filter_rows", {"condition": "x"}))
        nodes.append(_dest_node())

        # 101 edges: source→t0..t99 (100 edges) + t0→dst1 (1 edge) = 101
        edges = []
        for i in range(100):
            edges.append(DAGEdge(source_node_id="src1", target_node_id=f"t{i}"))
        edges.append(DAGEdge(source_node_id="t0", target_node_id="dst1"))

        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        limit_errors = [e for e in result.errors if e.error_type == ValidationErrorType.EXCEEDS_EDGE_LIMIT]
        assert len(limit_errors) == 1
        assert "101" in limit_errors[0].message

    def test_exactly_100_edges_is_valid(self, validator):
        """Pipeline with exactly 100 edges should pass edge limit check."""
        nodes = [_source_node()]
        for i in range(99):
            nodes.append(_transform_node(f"t{i}", "filter_rows", {"condition": "x"}))
        nodes.append(_dest_node())

        # 100 edges: source→t0..t98 (99 edges) + t0→dst1 (1 edge) = 100
        edges = []
        for i in range(99):
            edges.append(DAGEdge(source_node_id="src1", target_node_id=f"t{i}"))
        edges.append(DAGEdge(source_node_id="t0", target_node_id="dst1"))

        result = validator.validate(nodes, edges)
        limit_errors = [e for e in result.errors if e.error_type == ValidationErrorType.EXCEEDS_EDGE_LIMIT]
        assert len(limit_errors) == 0


# =============================================================================
# Test: Completeness Validation
# =============================================================================


class TestCompletenessValidation:
    """Test pipeline completeness (source, destination, connected path)."""

    def test_missing_source_node(self, validator):
        """Pipeline with no source node fails."""
        nodes = [_transform_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="t1", target_node_id="dst1")]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        missing_src = [e for e in result.errors if e.error_type == ValidationErrorType.MISSING_SOURCE]
        assert len(missing_src) == 1

    def test_missing_destination_node(self, validator):
        """Pipeline with no destination node fails."""
        nodes = [_source_node(), _transform_node()]
        edges = [DAGEdge(source_node_id="src1", target_node_id="t1")]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        missing_dst = [e for e in result.errors if e.error_type == ValidationErrorType.MISSING_DESTINATION]
        assert len(missing_dst) == 1

    def test_disconnected_source_and_destination(self, validator):
        """Source and destination exist but no path between them."""
        nodes = [_source_node(), _dest_node()]
        edges = []  # No edges connecting them
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        disconnected = [e for e in result.errors if e.error_type == ValidationErrorType.DISCONNECTED_GRAPH]
        assert len(disconnected) == 1

    def test_connected_path_exists_through_transforms(self, validator):
        """Connected path via transformation nodes passes."""
        nodes = [_source_node(), _transform_node(), _dest_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        disconnected = [e for e in result.errors if e.error_type == ValidationErrorType.DISCONNECTED_GRAPH]
        assert len(disconnected) == 0

    def test_missing_both_source_and_destination(self, validator):
        """Pipeline with neither source nor destination fails with both errors."""
        nodes = [_transform_node()]
        edges = []
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        error_types = {e.error_type for e in result.errors}
        assert ValidationErrorType.MISSING_SOURCE in error_types
        assert ValidationErrorType.MISSING_DESTINATION in error_types


# =============================================================================
# Test: Config Field Validation
# =============================================================================


class TestConfigValidation:
    """Test required config fields per node subtype."""

    def test_postgresql_source_missing_connector_id(self, validator):
        """postgresql_source without connector_id fails."""
        nodes = [
            _source_node("src1", "postgresql_source", {"table_name": "users"}),
            _dest_node(),
        ]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        config_errors = [e for e in result.errors if e.error_type == ValidationErrorType.MISSING_CONFIG]
        assert any("connector_id" in e.message for e in config_errors)

    def test_postgresql_source_missing_table_name(self, validator):
        """postgresql_source without table_name fails."""
        nodes = [
            _source_node("src1", "postgresql_source", {"connector_id": "c1"}),
            _dest_node(),
        ]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        config_errors = [e for e in result.errors if e.error_type == ValidationErrorType.MISSING_CONFIG]
        assert any("table_name" in e.message for e in config_errors)

    def test_csv_source_missing_file_path(self, validator):
        """csv_source without file_path fails."""
        nodes = [
            _source_node("src1", "csv_source", {}),
            _dest_node(),
        ]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        config_errors = [e for e in result.errors if e.error_type == ValidationErrorType.MISSING_CONFIG]
        assert any("file_path" in e.message for e in config_errors)

    def test_excel_source_missing_sheet_name(self, validator):
        """excel_source without sheet_name fails."""
        nodes = [
            _source_node("src1", "excel_source", {"file_path": "/data/f.xlsx"}),
            _dest_node(),
        ]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        config_errors = [e for e in result.errors if e.error_type == ValidationErrorType.MISSING_CONFIG]
        assert any("sheet_name" in e.message for e in config_errors)

    def test_rest_source_missing_endpoint(self, validator):
        """rest_source without endpoint fails."""
        nodes = [
            _source_node("src1", "rest_source", {"connector_id": "c1"}),
            _dest_node(),
        ]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        config_errors = [e for e in result.errors if e.error_type == ValidationErrorType.MISSING_CONFIG]
        assert any("endpoint" in e.message for e in config_errors)

    def test_select_columns_missing_columns_list(self, validator):
        """select_columns without columns fails."""
        nodes = [
            _source_node(),
            _transform_node("t1", "select_columns", {}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        config_errors = [e for e in result.errors if e.error_type == ValidationErrorType.MISSING_CONFIG]
        assert any("columns" in e.message for e in config_errors)

    def test_select_columns_empty_columns_list(self, validator):
        """select_columns with empty columns list fails."""
        nodes = [
            _source_node(),
            _transform_node("t1", "select_columns", {"columns": []}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        config_errors = [e for e in result.errors if e.error_type == ValidationErrorType.MISSING_CONFIG]
        assert any("columns" in e.message for e in config_errors)

    def test_filter_rows_missing_condition(self, validator):
        """filter_rows without condition fails."""
        nodes = [
            _source_node(),
            _transform_node("t1", "filter_rows", {}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        config_errors = [e for e in result.errors if e.error_type == ValidationErrorType.MISSING_CONFIG]
        assert any("condition" in e.message for e in config_errors)

    def test_rename_columns_empty_mapping(self, validator):
        """rename_columns with empty mapping dict fails."""
        nodes = [
            _source_node(),
            _transform_node("t1", "rename_columns", {"mapping": {}}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        config_errors = [e for e in result.errors if e.error_type == ValidationErrorType.MISSING_CONFIG]
        assert any("mapping" in e.message for e in config_errors)

    def test_aggregate_missing_group_by(self, validator):
        """aggregate without group_by fails."""
        nodes = [
            _source_node(),
            _transform_node("t1", "aggregate", {"aggregations": [{"func": "sum", "col": "amount"}]}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        config_errors = [e for e in result.errors if e.error_type == ValidationErrorType.MISSING_CONFIG]
        assert any("group_by" in e.message for e in config_errors)

    def test_join_missing_join_type(self, validator):
        """join without join_type fails."""
        nodes = [
            _source_node(),
            _transform_node("t1", "join", {"join_key": "id"}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        config_errors = [e for e in result.errors if e.error_type == ValidationErrorType.MISSING_CONFIG]
        assert any("join_type" in e.message for e in config_errors)

    def test_destination_missing_write_mode(self, validator):
        """postgresql_destination without write_mode fails."""
        nodes = [
            _source_node(),
            _dest_node("dst1", "postgresql_destination", {"connector_id": "c", "table_name": "t"}),
        ]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        config_errors = [e for e in result.errors if e.error_type == ValidationErrorType.MISSING_CONFIG]
        assert any("write_mode" in e.message for e in config_errors)

    def test_clickhouse_destination_missing_fields(self, validator):
        """clickhouse_destination without required fields fails."""
        nodes = [
            _source_node(),
            _dest_node("dst1", "clickhouse_destination", {}),
        ]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        config_errors = [e for e in result.errors if e.error_type == ValidationErrorType.MISSING_CONFIG]
        missing_fields = [e.message for e in config_errors]
        assert any("connector_id" in m for m in missing_fields)
        assert any("table_name" in m for m in missing_fields)
        assert any("write_mode" in m for m in missing_fields)

    def test_valid_config_passes(self, validator):
        """All required fields present → no config errors."""
        nodes = [
            _source_node("src1", "postgresql_source", {"connector_id": "c", "table_name": "t"}),
            _transform_node("t1", "aggregate", {"group_by": ["region"], "aggregations": [{"func": "count"}]}),
            _dest_node("dst1", "clickhouse_destination", {"connector_id": "c", "table_name": "out", "write_mode": "append"}),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        config_errors = [e for e in result.errors if e.error_type == ValidationErrorType.MISSING_CONFIG]
        assert len(config_errors) == 0


# =============================================================================
# Test: Node Type / Subtype Validation
# =============================================================================


class TestNodeTypeValidation:
    """Test invalid node types and subtypes are rejected."""

    def test_invalid_node_type(self, validator):
        """Unknown node type is rejected."""
        nodes = [
            DAGNode(id="x1", node_type="unknown", node_subtype="postgresql_source", config={}),
            _dest_node(),
        ]
        edges = [DAGEdge(source_node_id="x1", target_node_id="dst1")]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        type_errors = [e for e in result.errors if e.error_type == ValidationErrorType.INVALID_NODE_TYPE]
        assert len(type_errors) >= 1

    def test_invalid_subtype(self, validator):
        """Unknown node subtype is rejected."""
        nodes = [
            DAGNode(id="src1", node_type="source", node_subtype="oracle_source", config={}),
            _dest_node(),
        ]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        subtype_errors = [e for e in result.errors if e.error_type == ValidationErrorType.INVALID_NODE_SUBTYPE]
        assert len(subtype_errors) >= 1

    def test_subtype_type_mismatch(self, validator):
        """Source subtype assigned to transformation type is rejected."""
        nodes = [
            _source_node(),
            DAGNode(id="t1", node_type="transformation", node_subtype="postgresql_source", config={}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        subtype_errors = [e for e in result.errors if e.error_type == ValidationErrorType.INVALID_NODE_SUBTYPE]
        assert len(subtype_errors) >= 1


# =============================================================================
# Test: ValidationResult structure
# =============================================================================


class TestValidationResultStructure:
    """Test the ValidationResult dataclass structure."""

    def test_valid_result_has_no_errors(self, validator):
        """A valid pipeline returns is_valid=True and empty errors list."""
        nodes = [_source_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = validator.validate(nodes, edges)
        assert isinstance(result, ValidationResult)
        assert result.is_valid is True
        assert isinstance(result.errors, list)
        assert len(result.errors) == 0

    def test_invalid_result_contains_error_details(self, validator):
        """Each ValidationError has node_id, error_type, and message."""
        nodes = [_transform_node()]  # no source, no dest
        edges = []
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        for error in result.errors:
            assert hasattr(error, "node_id")
            assert hasattr(error, "error_type")
            assert hasattr(error, "message")
            assert isinstance(error.error_type, ValidationErrorType)
            assert isinstance(error.message, str)

    def test_multiple_errors_accumulated(self, validator):
        """Multiple validation issues produce multiple errors."""
        # No source, no destination, invalid config
        nodes = [_transform_node("t1", "filter_rows", {})]
        edges = []
        result = validator.validate(nodes, edges)
        assert result.is_valid is False
        assert len(result.errors) >= 2  # at least missing_source and missing_destination
