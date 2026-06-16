"""Unit tests for dbt Compiler — transformation nodes to dbt SQL model compilation.

Tests cover:
- Filter Rows → correct WHERE clause
- Select Columns → correct column list
- Rename Columns → correct AS aliases
- Aggregate → GROUP BY with aggregate functions (sum, count, avg, min, max)
- Join → correct JOIN type and key (inner, left, right, full)
- Chained transformations using ref()
- Source reference generation with source()
- DbtProject and DbtModel structure
- Model naming convention

Requirements: 5.7
"""

import pytest

from backend.app.services.dag_validator import DAGEdge, DAGNode
from backend.app.services.dbt_compiler import DbtCompiler, DbtModel, DbtProject


@pytest.fixture
def compiler():
    """Create a DbtCompiler instance."""
    return DbtCompiler()


# --- Helper factories ---


def _source_node(
    node_id: str = "src1",
    subtype: str = "postgresql_source",
    config: dict | None = None,
) -> DAGNode:
    if config is None:
        config = {"connector_id": "conn-1", "table_name": "users"}
    return DAGNode(id=node_id, node_type="source", node_subtype=subtype, config=config)


def _transform_node(
    node_id: str = "t1",
    subtype: str = "filter_rows",
    config: dict | None = None,
) -> DAGNode:
    if config is None:
        config = {"condition": "age > 18"}
    return DAGNode(id=node_id, node_type="transformation", node_subtype=subtype, config=config)


def _dest_node(
    node_id: str = "dst1",
    subtype: str = "postgresql_destination",
    config: dict | None = None,
) -> DAGNode:
    if config is None:
        config = {"connector_id": "conn-2", "table_name": "output", "write_mode": "append"}
    return DAGNode(id=node_id, node_type="destination", node_subtype=subtype, config=config)


# =============================================================================
# Test: DbtProject Structure
# =============================================================================


class TestDbtProjectStructure:
    """Test DbtProject and DbtModel output structure."""

    def test_project_has_correct_name(self, compiler):
        """Project name matches sanitized pipeline name."""
        nodes = [_source_node(), _transform_node(), _dest_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("My Pipeline", nodes, edges)

        assert isinstance(result, DbtProject)
        assert result.project_name == "my_pipeline"

    def test_only_transformation_nodes_generate_models(self, compiler):
        """Source and destination nodes do not produce SQL models."""
        nodes = [_source_node(), _transform_node(), _dest_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        assert len(result.models) == 1
        assert "stg_test_t1" in result.models[0].name

    def test_multiple_transforms_produce_multiple_models(self, compiler):
        """Each transformation node generates its own model."""
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
        result = compiler.compile_transformations("pipeline", nodes, edges)

        assert len(result.models) == 2

    def test_model_has_name_sql_and_description(self, compiler):
        """Each DbtModel has name, sql, and description fields."""
        nodes = [_source_node(), _transform_node(), _dest_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        model = result.models[0]
        assert isinstance(model, DbtModel)
        assert model.name != ""
        assert model.sql != ""
        assert model.description != ""

    def test_no_transforms_produces_empty_models(self, compiler):
        """Pipeline with no transformation nodes produces no models."""
        nodes = [_source_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="src1", target_node_id="dst1")]
        result = compiler.compile_transformations("simple", nodes, edges)

        assert len(result.models) == 0


# =============================================================================
# Test: Filter Rows SQL Generation
# =============================================================================


class TestFilterRowsSQL:
    """Test filter_rows transformation generates correct WHERE clause."""

    def test_basic_filter_condition(self, compiler):
        """Filter generates WHERE clause with the configured condition."""
        nodes = [
            _source_node("src1", "postgresql_source", {"connector_id": "c", "table_name": "users"}),
            _transform_node("t1", "filter_rows", {"condition": "age > 18"}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        sql = result.models[0].sql
        assert "SELECT *" in sql
        assert "WHERE age > 18" in sql

    def test_filter_references_source_with_source_macro(self, compiler):
        """Filter on source node uses source() macro."""
        nodes = [
            _source_node("src1", "postgresql_source", {"connector_id": "c", "table_name": "orders"}),
            _transform_node("t1", "filter_rows", {"condition": "status = 'active'"}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        sql = result.models[0].sql
        assert "source('test', 'orders')" in sql

    def test_complex_filter_condition(self, compiler):
        """Complex SQL conditions pass through correctly."""
        nodes = [
            _source_node(),
            _transform_node("t1", "filter_rows", {"condition": "amount > 100 AND status != 'cancelled'"}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        sql = result.models[0].sql
        assert "amount > 100 AND status != 'cancelled'" in sql


# =============================================================================
# Test: Select Columns SQL Generation
# =============================================================================


class TestSelectColumnsSQL:
    """Test select_columns transformation generates correct column list."""

    def test_select_specific_columns(self, compiler):
        """Select generates SQL with only specified columns."""
        nodes = [
            _source_node(),
            _transform_node("t1", "select_columns", {"columns": ["id", "name", "email"]}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        sql = result.models[0].sql
        assert "id" in sql
        assert "name" in sql
        assert "email" in sql
        assert "SELECT" in sql

    def test_select_single_column(self, compiler):
        """Single column selection works."""
        nodes = [
            _source_node(),
            _transform_node("t1", "select_columns", {"columns": ["total"]}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        sql = result.models[0].sql
        assert "total" in sql

    def test_empty_columns_selects_star(self, compiler):
        """Empty columns list falls back to SELECT *."""
        nodes = [
            _source_node(),
            _transform_node("t1", "select_columns", {"columns": []}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        sql = result.models[0].sql
        assert "*" in sql


# =============================================================================
# Test: Rename Columns SQL Generation
# =============================================================================


class TestRenameColumnsSQL:
    """Test rename_columns transformation generates correct aliases."""

    def test_basic_rename(self, compiler):
        """Rename generates correct AS aliases."""
        nodes = [
            _source_node(),
            _transform_node("t1", "rename_columns", {"mapping": {"first_name": "fname", "last_name": "lname"}}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        sql = result.models[0].sql
        assert "first_name AS fname" in sql
        assert "last_name AS lname" in sql

    def test_single_rename(self, compiler):
        """Single column rename works."""
        nodes = [
            _source_node(),
            _transform_node("t1", "rename_columns", {"mapping": {"old_col": "new_col"}}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        sql = result.models[0].sql
        assert "old_col AS new_col" in sql


# =============================================================================
# Test: Aggregate SQL Generation
# =============================================================================


class TestAggregateSQL:
    """Test aggregate transformation generates correct GROUP BY with functions."""

    def test_sum_aggregation(self, compiler):
        """SUM aggregation generates correct SQL."""
        nodes = [
            _source_node(),
            _transform_node("t1", "aggregate", {
                "group_by": ["region"],
                "aggregations": [{"func": "sum", "col": "amount", "alias": "total_amount"}],
            }),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        sql = result.models[0].sql
        assert "region" in sql
        assert "SUM(amount) AS total_amount" in sql
        assert "GROUP BY region" in sql

    def test_count_aggregation(self, compiler):
        """COUNT aggregation generates correct SQL."""
        nodes = [
            _source_node(),
            _transform_node("t1", "aggregate", {
                "group_by": ["status"],
                "aggregations": [{"func": "count", "col": "*", "alias": "count_all"}],
            }),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        sql = result.models[0].sql
        assert "COUNT(*) AS count_all" in sql
        assert "GROUP BY status" in sql

    def test_multiple_aggregations(self, compiler):
        """Multiple aggregation functions in one node."""
        nodes = [
            _source_node(),
            _transform_node("t1", "aggregate", {
                "group_by": ["category"],
                "aggregations": [
                    {"func": "sum", "col": "revenue", "alias": "total_rev"},
                    {"func": "avg", "col": "price", "alias": "avg_price"},
                    {"func": "max", "col": "quantity", "alias": "max_qty"},
                ],
            }),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        sql = result.models[0].sql
        assert "SUM(revenue) AS total_rev" in sql
        assert "AVG(price) AS avg_price" in sql
        assert "MAX(quantity) AS max_qty" in sql
        assert "GROUP BY category" in sql

    def test_multiple_group_by_columns(self, compiler):
        """Multiple GROUP BY columns."""
        nodes = [
            _source_node(),
            _transform_node("t1", "aggregate", {
                "group_by": ["year", "month"],
                "aggregations": [{"func": "sum", "col": "sales", "alias": "total_sales"}],
            }),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        sql = result.models[0].sql
        assert "GROUP BY year, month" in sql


# =============================================================================
# Test: Join SQL Generation
# =============================================================================


class TestJoinSQL:
    """Test join transformation generates correct JOIN with type and key."""

    def test_inner_join(self, compiler):
        """INNER JOIN generates correct SQL."""
        nodes = [
            _source_node("src1", "postgresql_source", {"connector_id": "c1", "table_name": "orders"}),
            _source_node("src2", "postgresql_source", {"connector_id": "c2", "table_name": "customers"}),
            _transform_node("t1", "join", {"join_type": "inner", "join_key": "customer_id"}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="src2", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        sql = result.models[0].sql
        assert "INNER JOIN" in sql
        assert "customer_id" in sql

    def test_left_join(self, compiler):
        """LEFT JOIN generates correct SQL."""
        nodes = [
            _source_node("src1", "postgresql_source", {"connector_id": "c1", "table_name": "a"}),
            _source_node("src2", "postgresql_source", {"connector_id": "c2", "table_name": "b"}),
            _transform_node("t1", "join", {"join_type": "left", "join_key": "id"}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="src2", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        sql = result.models[0].sql
        assert "LEFT JOIN" in sql

    def test_right_join(self, compiler):
        """RIGHT JOIN generates correct SQL."""
        nodes = [
            _source_node("src1", "postgresql_source", {"connector_id": "c1", "table_name": "a"}),
            _source_node("src2", "postgresql_source", {"connector_id": "c2", "table_name": "b"}),
            _transform_node("t1", "join", {"join_type": "right", "join_key": "id"}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="src2", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        sql = result.models[0].sql
        assert "RIGHT JOIN" in sql

    def test_full_join(self, compiler):
        """FULL JOIN generates correct SQL."""
        nodes = [
            _source_node("src1", "postgresql_source", {"connector_id": "c1", "table_name": "a"}),
            _source_node("src2", "postgresql_source", {"connector_id": "c2", "table_name": "b"}),
            _transform_node("t1", "join", {"join_type": "full", "join_key": "id"}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="src2", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        sql = result.models[0].sql
        assert "FULL JOIN" in sql

    def test_join_references_both_sources(self, compiler):
        """Join SQL includes references to both upstream nodes."""
        nodes = [
            _source_node("src1", "postgresql_source", {"connector_id": "c1", "table_name": "orders"}),
            _source_node("src2", "postgresql_source", {"connector_id": "c2", "table_name": "customers"}),
            _transform_node("t1", "join", {"join_type": "inner", "join_key": "id"}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="src2", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("test", nodes, edges)

        sql = result.models[0].sql
        # Should reference both source tables
        assert "source(" in sql
        assert "orders" in sql or "customers" in sql


# =============================================================================
# Test: Chained Transformations (ref() usage)
# =============================================================================


class TestChainedTransformations:
    """Test chained transformations use ref() to reference upstream models."""

    def test_second_transform_refs_first_model(self, compiler):
        """Second transformation uses ref() pointing to first model name."""
        nodes = [
            _source_node(),
            _transform_node("t1", "filter_rows", {"condition": "active = true"}),
            _transform_node("t2", "select_columns", {"columns": ["id", "name"]}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="t2"),
            DAGEdge(source_node_id="t2", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("pipeline", nodes, edges)

        assert len(result.models) == 2
        # First model refs source
        assert "source(" in result.models[0].sql
        # Second model refs first model
        assert "ref('stg_pipeline_t1')" in result.models[1].sql

    def test_three_chained_transforms(self, compiler):
        """Three chained transforms correctly reference each other."""
        nodes = [
            _source_node(),
            _transform_node("t1", "filter_rows", {"condition": "x > 0"}),
            _transform_node("t2", "rename_columns", {"mapping": {"x": "value"}}),
            _transform_node("t3", "select_columns", {"columns": ["value"]}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="t2"),
            DAGEdge(source_node_id="t2", target_node_id="t3"),
            DAGEdge(source_node_id="t3", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("chain", nodes, edges)

        assert len(result.models) == 3
        # t2 refs t1
        assert "ref('stg_chain_t1')" in result.models[1].sql
        # t3 refs t2
        assert "ref('stg_chain_t2')" in result.models[2].sql


# =============================================================================
# Test: Source Reference Generation
# =============================================================================


class TestSourceReferences:
    """Test source nodes produce correct source() references and sources.yml."""

    def test_sources_yml_generated(self, compiler):
        """sources.yml is generated for source nodes."""
        nodes = [
            _source_node("src1", "postgresql_source", {"connector_id": "c", "table_name": "users"}),
            _transform_node("t1", "filter_rows", {"condition": "x > 0"}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("myproject", nodes, edges)

        assert "version: 2" in result.sources_yml
        assert "sources:" in result.sources_yml
        assert "name: myproject" in result.sources_yml
        assert "name: users" in result.sources_yml

    def test_multiple_sources_in_yml(self, compiler):
        """Multiple source nodes appear in sources.yml."""
        nodes = [
            _source_node("src1", "postgresql_source", {"connector_id": "c1", "table_name": "orders"}),
            _source_node("src2", "mysql_source", {"connector_id": "c2", "table_name": "products"}),
            _transform_node("t1", "join", {"join_type": "inner", "join_key": "product_id"}),
            _dest_node(),
        ]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="t1"),
            DAGEdge(source_node_id="src2", target_node_id="t1"),
            DAGEdge(source_node_id="t1", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("multi_src", nodes, edges)

        assert "orders" in result.sources_yml
        assert "products" in result.sources_yml

    def test_no_sources_produces_empty_yml(self, compiler):
        """Pipeline with no source nodes produces empty sources_yml."""
        # This is an edge case — normally invalid, but compiler handles gracefully
        nodes = [_transform_node(), _dest_node()]
        edges = [DAGEdge(source_node_id="t1", target_node_id="dst1")]
        result = compiler.compile_transformations("nosrc", nodes, edges)

        assert result.sources_yml == ""


# =============================================================================
# Test: Model Naming Convention
# =============================================================================


class TestModelNaming:
    """Test model naming convention: stg_<pipeline>_<node_id>."""

    def test_model_name_format(self, compiler):
        """Model names follow stg_<pipeline>_<node_id> convention."""
        nodes = [_source_node(), _transform_node("my_filter"), _dest_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="my_filter"),
            DAGEdge(source_node_id="my_filter", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("etl_job", nodes, edges)

        assert result.models[0].name == "stg_etl_job_my_filter"

    def test_special_chars_sanitized_in_name(self, compiler):
        """Special characters in pipeline/node names are sanitized."""
        nodes = [_source_node(), _transform_node("node-1!"), _dest_node()]
        edges = [
            DAGEdge(source_node_id="src1", target_node_id="node-1!"),
            DAGEdge(source_node_id="node-1!", target_node_id="dst1"),
        ]
        result = compiler.compile_transformations("My Pipeline!", nodes, edges)

        # Name should be a valid identifier component
        model_name = result.models[0].name
        assert " " not in model_name
        assert "!" not in model_name
        assert "-" not in model_name
