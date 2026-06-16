"""Unit tests for Dagster Compiler — pipeline DAG to Dagster code compilation.

Tests cover:
- Valid pipeline compilation (source → transform → destination)
- Source node → @op generation
- Transformation node → @op generation with inputs
- Destination node → @op generation with inputs
- Edge wiring in @job function
- Invalid DAG rejection
- DagsterDefinition dataclass fields
- Pipeline name sanitization
- Multiple sources / fan-out / fan-in topologies

Requirements: 6.1, 6.2
"""

import pytest

from backend.app.services.dag_validator import DAGEdge, DAGNode
from backend.app.services.dagster_compiler import DagsterCompiler, DagsterDefinition


@pytest.fixture
def compiler():
    """Create a DagsterCompiler instance."""
    return DagsterCompiler()


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
# Test: DagsterDefinition dataclass
# =============================================================================


class TestDagsterDefinition:
    """Test that DagsterDefinition fields are correctly populated."""

    def test_valid_definition_fields(self, compiler):
        """Successful compilation populates all fields."""
        nodes = [_source_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("my_pipeline", nodes, edges)

        assert isinstance(result, DagsterDefinition)
        assert result.is_valid is True
        assert result.error is None
        assert result.job_name == "pipeline_my_pipeline"
        assert len(result.op_names) == 2
        assert isinstance(result.code, str)
        assert len(result.code) > 0

    def test_invalid_definition_fields(self, compiler):
        """Failed compilation sets is_valid=False and provides error."""
        # No source node — will fail validation
        nodes = [_transform_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="t1", target_node_id="dst1")]
        result = compiler.compile("bad_pipeline", nodes, edges)

        assert isinstance(result, DagsterDefinition)
        assert result.is_valid is False
        assert result.error is not None
        assert "DAG validation failed" in result.error
        assert result.code == ""
        assert result.job_name == ""
        assert result.op_names == []


# =============================================================================
# Test: Valid Pipeline Compilation
# =============================================================================


class TestValidPipelineCompilation:
    """Test that valid pipelines compile to valid Dagster code."""

    def test_simple_source_to_destination(self, compiler):
        """Minimal pipeline: source → destination produces valid code."""
        nodes = [_source_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("simple", nodes, edges)

        assert result.is_valid is True
        assert "@op" in result.code
        assert "@job" in result.code
        assert "from dagster import" in result.code

    def test_source_transform_destination(self, compiler):
        """source → transform → destination produces ops with correct wiring."""
        nodes = [_source_node(), _transform_node(), _dest_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile("etl_pipeline", nodes, edges)

        assert result.is_valid is True
        assert result.job_name == "pipeline_etl_pipeline"
        assert len(result.op_names) == 3
        # All ops should be defined
        for op_name in result.op_names:
            assert f"def {op_name}" in result.code

    def test_multiple_transformations_chained(self, compiler):
        """source → t1 → t2 → destination compiles correctly."""
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
        result = compiler.compile("chained", nodes, edges)

        assert result.is_valid is True
        assert len(result.op_names) == 4

    def test_fan_out_source_to_multiple_destinations(self, compiler):
        """One source fans out to two destinations."""
        nodes = [
            _source_node(),
            _dest_node("dst1", "postgresql_destination", {"connector_id": "c1", "table_name": "a", "write_mode": "append"}),
            _dest_node("dst2", "clickhouse_destination", {"connector_id": "c2", "table_name": "b", "write_mode": "replace"}),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="dst1"),
            DAGEdge(source_node_id="src1", target_node_id="dst2"),
        ]
        result = compiler.compile("fan_out", nodes, edges)

        assert result.is_valid is True
        assert len(result.op_names) == 3

    def test_fan_in_join_multiple_sources(self, compiler):
        """Two sources merge into join → destination."""
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
        result = compiler.compile("fan_in", nodes, edges)

        assert result.is_valid is True
        assert len(result.op_names) == 4
        # The join op should have multiple inputs
        assert "In()" in result.code


# =============================================================================
# Test: Source Node Op Generation
# =============================================================================


class TestSourceNodeOpGeneration:
    """Test that source nodes generate correct @op definitions."""

    def test_postgresql_source_op(self, compiler):
        """PostgreSQL source generates extract op with Out()."""
        nodes = [
            _source_node("src1", "postgresql_source", {"connector_id": "c", "table_name": "users"}),
            _dest_node(),
        ]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("pg_extract", nodes, edges)

        assert result.is_valid is True
        assert "@op(out=Out())" in result.code
        # Source op should have no input parameters
        source_op = [n for n in result.op_names if "source" in n][0]
        # The function definition should not have In() for source
        assert f"def {source_op}():" in result.code

    def test_csv_source_op(self, compiler):
        """CSV source generates extract op."""
        nodes = [
            _source_node("src1", "csv_source", {"file_path": "/data/file.csv"}),
            _dest_node(),
        ]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("csv_extract", nodes, edges)

        assert result.is_valid is True
        assert "csv" in result.code.lower()

    def test_excel_source_op(self, compiler):
        """Excel source generates extract op."""
        nodes = [
            _source_node("src1", "excel_source", {"file_path": "/data/f.xlsx", "sheet_name": "Sheet1"}),
            _dest_node(),
        ]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("excel_extract", nodes, edges)

        assert result.is_valid is True
        assert "excel" in result.code.lower()

    def test_rest_source_op(self, compiler):
        """REST source generates extract op."""
        nodes = [
            _source_node("src1", "rest_source", {"connector_id": "c", "endpoint": "/api/data"}),
            _dest_node(),
        ]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("rest_extract", nodes, edges)

        assert result.is_valid is True
        assert "rest" in result.code.lower()

    def test_source_op_has_no_inputs(self, compiler):
        """Source ops should not have any In() decorators."""
        nodes = [_source_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("no_input", nodes, edges)

        # Find source op lines — it should have out=Out() but no ins=
        lines = result.code.split("\n")
        source_op_name = [n for n in result.op_names if "source" in n][0]
        for i, line in enumerate(lines):
            if f"def {source_op_name}" in line:
                # Check decorator on preceding line
                decorator_line = lines[i - 1]
                assert "In()" not in decorator_line
                break


# =============================================================================
# Test: Transformation Node Op Generation
# =============================================================================


class TestTransformationNodeOpGeneration:
    """Test that transformation nodes generate correct @op definitions."""

    def test_filter_rows_op_has_input_and_output(self, compiler):
        """Filter transform has In() and Out()."""
        nodes = [_source_node(), _transform_node("t1", "filter_rows", {"condition": "x > 0"}), _dest_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile("filter_test", nodes, edges)

        assert result.is_valid is True
        assert "In()" in result.code
        assert "Out()" in result.code

    def test_select_columns_op(self, compiler):
        """Select columns transform compiles correctly."""
        nodes = [
            _source_node(),
            _transform_node("t1", "select_columns", {"columns": ["col1", "col2"]}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile("select_test", nodes, edges)

        assert result.is_valid is True
        transform_op = [n for n in result.op_names if "transform" in n][0]
        assert f"def {transform_op}" in result.code

    def test_rename_columns_op(self, compiler):
        """Rename columns transform compiles correctly."""
        nodes = [
            _source_node(),
            _transform_node("t1", "rename_columns", {"mapping": {"old": "new"}}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile("rename_test", nodes, edges)

        assert result.is_valid is True

    def test_aggregate_op(self, compiler):
        """Aggregate transform compiles correctly."""
        nodes = [
            _source_node(),
            _transform_node("t1", "aggregate", {"group_by": ["region"], "aggregations": [{"func": "sum"}]}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile("agg_test", nodes, edges)

        assert result.is_valid is True

    def test_join_op_with_multiple_inputs(self, compiler):
        """Join transform has multiple In() parameters."""
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
        result = compiler.compile("join_test", nodes, edges)

        assert result.is_valid is True
        # Join op should have 2 input parameters
        join_op = [n for n in result.op_names if "join" in n.lower()][0]
        # Should have input_0 and input_1
        assert "input_0" in result.code
        assert "input_1" in result.code


# =============================================================================
# Test: Destination Node Op Generation
# =============================================================================


class TestDestinationNodeOpGeneration:
    """Test that destination nodes generate correct @op definitions."""

    def test_destination_op_has_input_no_output(self, compiler):
        """Destination ops have In() but no Out()."""
        nodes = [_source_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("dest_test", nodes, edges)

        assert result.is_valid is True
        dest_op = [n for n in result.op_names if "dest" in n][0]
        # Find the destination op decorator - should have ins but no out
        lines = result.code.split("\n")
        for i, line in enumerate(lines):
            if f"def {dest_op}" in line:
                decorator_line = lines[i - 1]
                assert "In()" in decorator_line
                # Destination ops should NOT have Out() in their decorator
                assert "out=Out()" not in decorator_line
                break

    def test_postgresql_destination_op(self, compiler):
        """PostgreSQL destination generates load op."""
        nodes = [
            _source_node(),
            _dest_node("dst1", "postgresql_destination", {"connector_id": "c", "table_name": "output", "write_mode": "append"}),
        ]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("pg_load", nodes, edges)

        assert result.is_valid is True
        assert "postgresql" in result.code.lower()

    def test_clickhouse_destination_op(self, compiler):
        """ClickHouse destination generates load op."""
        nodes = [
            _source_node(),
            _dest_node("dst1", "clickhouse_destination", {"connector_id": "c", "table_name": "analytics", "write_mode": "replace"}),
        ]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("ch_load", nodes, edges)

        assert result.is_valid is True
        assert "clickhouse" in result.code.lower()


# =============================================================================
# Test: Edge Wiring in @job Function
# =============================================================================


class TestJobWiring:
    """Test that edges are correctly wired in the @job function."""

    def test_job_function_defined(self, compiler):
        """The @job decorator and function are present."""
        nodes = [_source_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("wiring_test", nodes, edges)

        assert "@job" in result.code
        assert "def pipeline_wiring_test():" in result.code

    def test_source_called_without_arguments(self, compiler):
        """Source ops are called with no args in the job body."""
        nodes = [_source_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("no_args", nodes, edges)

        source_op = [n for n in result.op_names if "source" in n][0]
        # In the job body, source op is called with ()
        assert f"{source_op}()" in result.code

    def test_downstream_ops_receive_upstream_result(self, compiler):
        """Downstream ops receive the result of upstream ops as arguments."""
        nodes = [_source_node(), _transform_node(), _dest_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile("wire_test", nodes, edges)

        # The job body should wire outputs to inputs
        # Source result is passed to transform, transform result to dest
        source_op = [n for n in result.op_names if "source" in n][0]
        transform_op = [n for n in result.op_names if "transform" in n][0]
        dest_op = [n for n in result.op_names if "dest" in n][0]

        # Source is called standalone
        assert f"result_{source_op} = {source_op}()" in result.code
        # Transform receives source result
        assert f"result_{transform_op} = {transform_op}(result_{source_op})" in result.code
        # Dest receives transform result
        assert f"result_{dest_op} = {dest_op}(result_{transform_op})" in result.code

    def test_fan_in_wiring_multiple_inputs(self, compiler):
        """Fan-in nodes receive multiple upstream results."""
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
        result = compiler.compile("fan_in_wire", nodes, edges)

        join_op = [n for n in result.op_names if "join" in n.lower()][0]
        # Join op should be called with two arguments
        assert f"{join_op}(" in result.code


# =============================================================================
# Test: Invalid DAG Rejection
# =============================================================================


class TestInvalidDAGRejection:
    """Test that invalid DAGs are rejected with descriptive errors."""

    def test_rejects_missing_source(self, compiler):
        """DAG without source node is rejected."""
        nodes = [_transform_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="t1", target_node_id="dst1")]
        result = compiler.compile("no_source", nodes, edges)

        assert result.is_valid is False
        assert result.error is not None
        assert "DAG validation failed" in result.error

    def test_rejects_missing_destination(self, compiler):
        """DAG without destination node is rejected."""
        nodes = [_source_node(), _transform_node()]
        edges = [DAGEdge(source_node_id="src1", target_node_id="t1")]
        result = compiler.compile("no_dest", nodes, edges)

        assert result.is_valid is False
        assert result.error is not None

    def test_rejects_cycle(self, compiler):
        """DAG with cycle is rejected."""
        nodes = [
            _source_node(),
            _transform_node("t1", "filter_rows", {"condition": "x"}),
            _transform_node("t2", "select_columns", {"columns": ["a"]}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="t2"),
            DAGEdge(source_node_id="t2", target_node_id="t1"),  # cycle
            DAGEdge(source_node_id="t2", target_node_id="dst1"),
        ]
        result = compiler.compile("cyclic", nodes, edges)

        assert result.is_valid is False
        assert "DAG validation failed" in result.error

    def test_rejects_disconnected_graph(self, compiler):
        """DAG with no path from source to destination is rejected."""
        nodes = [_source_node(), _dest_node()]
        edges = []  # No edges
        result = compiler.compile("disconnected", nodes, edges)

        assert result.is_valid is False
        assert result.error is not None

    def test_rejects_invalid_edge_direction(self, compiler):
        """DAG with destination having outgoing edge is rejected."""
        nodes = [_source_node(), _dest_node(), _transform_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="dst1"),
            DAGEdge(source_node_id="dst1", target_node_id="t1"),
        ]
        result = compiler.compile("bad_edge", nodes, edges)

        assert result.is_valid is False
        assert result.error is not None

    def test_rejects_missing_config_fields(self, compiler):
        """DAG with nodes missing required config is rejected."""
        nodes = [
            _source_node("src1", "postgresql_source", {}),  # missing connector_id, table_name
            _dest_node(),
        ]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("missing_config", nodes, edges)

        assert result.is_valid is False
        assert result.error is not None


# =============================================================================
# Test: Pipeline Name Sanitization
# =============================================================================


class TestPipelineNameSanitization:
    """Test that pipeline names are sanitized to valid Python identifiers."""

    def test_spaces_replaced_with_underscores(self, compiler):
        """Spaces in pipeline name become underscores."""
        nodes = [_source_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("my pipeline name", nodes, edges)

        assert result.is_valid is True
        assert result.job_name == "pipeline_my_pipeline_name"

    def test_special_characters_removed(self, compiler):
        """Special characters in pipeline name are replaced."""
        nodes = [_source_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("my-pipeline!v2", nodes, edges)

        assert result.is_valid is True
        # Should be a valid Python identifier
        assert result.job_name.isidentifier()

    def test_numeric_start_handled(self, compiler):
        """Pipeline name starting with digit gets prefixed."""
        nodes = [_source_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("123_pipeline", nodes, edges)

        assert result.is_valid is True
        assert result.job_name.isidentifier()

    def test_case_lowered(self, compiler):
        """Pipeline names are lowercased."""
        nodes = [_source_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("MyPipeline", nodes, edges)

        assert result.is_valid is True
        assert result.job_name == "pipeline_mypipeline"


# =============================================================================
# Test: Generated Code Structure
# =============================================================================


class TestGeneratedCodeStructure:
    """Test structural properties of the generated Dagster code."""

    def test_imports_include_dagster_primitives(self, compiler):
        """Generated code starts with dagster imports."""
        nodes = [_source_node(), _transform_node(), _dest_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile("imports_test", nodes, edges)

        assert "from dagster import job, op" in result.code
        assert "In" in result.code
        assert "Out" in result.code

    def test_ops_defined_before_job(self, compiler):
        """@op definitions appear before @job function."""
        nodes = [_source_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("order_test", nodes, edges)

        job_pos = result.code.find("@job")
        op_pos = result.code.find("@op")
        assert op_pos < job_pos

    def test_topological_order_respected(self, compiler):
        """Ops are defined in topological order (sources first, then transforms, then dests)."""
        nodes = [_source_node(), _transform_node(), _dest_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile("topo_test", nodes, edges)

        source_op = [n for n in result.op_names if "source" in n][0]
        transform_op = [n for n in result.op_names if "transform" in n][0]
        dest_op = [n for n in result.op_names if "dest" in n][0]

        src_pos = result.code.find(f"def {source_op}")
        transform_pos = result.code.find(f"def {transform_op}")
        dest_pos = result.code.find(f"def {dest_op}")

        assert src_pos < transform_pos < dest_pos

    def test_generated_code_is_syntactically_valid_python(self, compiler):
        """Generated code can be parsed as valid Python."""
        nodes = [_source_node(), _transform_node(), _dest_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile("syntax_test", nodes, edges)

        # compile() as Python to check syntax validity
        import ast
        try:
            ast.parse(result.code)
        except SyntaxError as e:
            pytest.fail(f"Generated code has syntax error: {e}")

    def test_code_ends_with_newline(self, compiler):
        """Generated code ends with a newline character."""
        nodes = [_source_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile("newline_test", nodes, edges)

        assert result.code.endswith("\n")
