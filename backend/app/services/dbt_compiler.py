"""dbt Compiler — Compiles pipeline transformation nodes into dbt v1.10 SQL models.

Converts visual transformation configurations (Filter, Aggregate, Join, Select, Rename)
into native dbt model files with correct SQL semantics and ref() usage for upstream
dependencies.

Source nodes → dbt source() references
Transformation nodes → dbt model SQL files with ref() to upstream models
Model naming convention: stg_<pipeline_name>_<node_id>

Requirements: 5.7
"""

import re
from collections import defaultdict
from dataclasses import dataclass, field

from backend.app.services.dag_validator import DAGEdge, DAGNode


@dataclass
class DbtModel:
    """A single dbt SQL model file."""

    name: str  # Model file name without .sql
    sql: str  # The SQL content
    description: str = ""


@dataclass
class DbtProject:
    """A compiled dbt project with models and source definitions."""

    project_name: str
    models: list[DbtModel] = field(default_factory=list)
    sources_yml: str = ""  # dbt sources.yml content


class DbtCompiler:
    """Compiles pipeline transformation nodes into dbt v1.10 SQL model files.

    Each transformation node produces one SQL model file. Source nodes are
    referenced using dbt's source() macro. Transformation nodes reference
    their upstream dependencies using ref().
    """

    def compile_transformations(
        self, pipeline_name: str, nodes: list[DAGNode], edges: list[DAGEdge]
    ) -> DbtProject:
        """Compile all transformation nodes into a dbt project.

        Args:
            pipeline_name: Human-readable pipeline name.
            nodes: All pipeline nodes (sources, transforms, destinations).
            edges: All pipeline edges.

        Returns:
            DbtProject with models for each transformation node and sources.yml.
        """
        sanitized_name = self._sanitize_name(pipeline_name)
        node_map = {node.id: node for node in nodes}

        # Build upstream map: node_id -> list of upstream node_ids
        incoming: dict[str, list[str]] = defaultdict(list)
        for edge in edges:
            incoming[edge.target_node_id].append(edge.source_node_id)

        # Generate model name map for all nodes
        model_names: dict[str, str] = {}
        for node in nodes:
            model_names[node.id] = f"stg_{sanitized_name}_{self._sanitize_name(node.id)}"

        # Collect source nodes for sources.yml
        source_nodes = [n for n in nodes if n.node_type == "source"]
        sources_yml = self._generate_sources_yml(sanitized_name, source_nodes)

        # Generate SQL models for transformation nodes only
        models: list[DbtModel] = []
        transform_nodes = [n for n in nodes if n.node_type == "transformation"]

        for node in transform_nodes:
            upstream_ids = incoming.get(node.id, [])
            upstream_refs = self._build_upstream_refs(
                upstream_ids, node_map, model_names, sanitized_name
            )
            sql = self._generate_sql(node, upstream_refs)
            model_name = model_names[node.id]
            models.append(
                DbtModel(
                    name=model_name,
                    sql=sql,
                    description=f"{node.node_subtype} transformation for pipeline {pipeline_name}",
                )
            )

        return DbtProject(
            project_name=sanitized_name,
            models=models,
            sources_yml=sources_yml,
        )

    def _sanitize_name(self, name: str) -> str:
        """Convert a name to a valid dbt model identifier."""
        sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        sanitized = re.sub(r"_+", "_", sanitized).strip("_").lower()
        if sanitized and sanitized[0].isdigit():
            sanitized = f"m_{sanitized}"
        return sanitized or "model"

    def _build_upstream_refs(
        self,
        upstream_ids: list[str],
        node_map: dict[str, DAGNode],
        model_names: dict[str, str],
        project_name: str,
    ) -> list[str]:
        """Build dbt ref() or source() expressions for upstream nodes.

        Source nodes → {{ source('project_name', 'table_name') }}
        Transform nodes → {{ ref('model_name') }}
        """
        refs: list[str] = []
        for uid in upstream_ids:
            upstream_node = node_map.get(uid)
            if upstream_node is None:
                continue
            if upstream_node.node_type == "source":
                table_name = upstream_node.config.get("table_name", "unknown")
                refs.append(f"{{{{ source('{project_name}', '{table_name}') }}}}")
            else:
                model_name = model_names.get(uid, uid)
                refs.append(f"{{{{ ref('{model_name}') }}}}")
        return refs

    def _generate_sql(self, node: DAGNode, upstream_refs: list[str]) -> str:
        """Generate SQL for a transformation node based on its subtype."""
        config = node.config or {}
        subtype = node.node_subtype

        if subtype == "filter_rows":
            return self._generate_filter_sql(config, upstream_refs)
        elif subtype == "select_columns":
            return self._generate_select_sql(config, upstream_refs)
        elif subtype == "rename_columns":
            return self._generate_rename_sql(config, upstream_refs)
        elif subtype == "aggregate":
            return self._generate_aggregate_sql(config, upstream_refs)
        elif subtype == "join":
            return self._generate_join_sql(config, upstream_refs)
        else:
            # Fallback: passthrough
            source_ref = upstream_refs[0] if upstream_refs else "{{ ref('unknown') }}"
            return f"SELECT *\nFROM {source_ref}"

    def _generate_filter_sql(self, config: dict, upstream_refs: list[str]) -> str:
        """Generate SQL for filter_rows: SELECT * FROM upstream WHERE condition."""
        condition = config.get("condition", "TRUE")
        source_ref = upstream_refs[0] if upstream_refs else "{{ ref('unknown') }}"
        return f"SELECT *\nFROM {source_ref}\nWHERE {condition}"

    def _generate_select_sql(self, config: dict, upstream_refs: list[str]) -> str:
        """Generate SQL for select_columns: SELECT col1, col2 FROM upstream."""
        columns = config.get("columns", [])
        if not columns:
            col_list = "*"
        else:
            col_list = ",\n    ".join(columns)
        source_ref = upstream_refs[0] if upstream_refs else "{{ ref('unknown') }}"
        return f"SELECT\n    {col_list}\nFROM {source_ref}"

    def _generate_rename_sql(self, config: dict, upstream_refs: list[str]) -> str:
        """Generate SQL for rename_columns: SELECT old AS new FROM upstream."""
        mapping = config.get("mapping", {})
        if not mapping:
            col_list = "*"
        else:
            col_list = ",\n    ".join(
                f"{old_name} AS {new_name}" for old_name, new_name in mapping.items()
            )
        source_ref = upstream_refs[0] if upstream_refs else "{{ ref('unknown') }}"
        return f"SELECT\n    {col_list}\nFROM {source_ref}"

    def _generate_aggregate_sql(self, config: dict, upstream_refs: list[str]) -> str:
        """Generate SQL for aggregate: SELECT group_cols, AGG(val) FROM upstream GROUP BY."""
        group_by = config.get("group_by", [])
        aggregations = config.get("aggregations", [])
        source_ref = upstream_refs[0] if upstream_refs else "{{ ref('unknown') }}"

        # Build select list
        select_parts: list[str] = list(group_by)
        for agg in aggregations:
            func = agg.get("func", "COUNT").upper()
            col = agg.get("col", "*")
            alias = agg.get("alias", f"{func.lower()}_{col}")
            select_parts.append(f"{func}({col}) AS {alias}")

        col_list = ",\n    ".join(select_parts) if select_parts else "*"
        group_clause = ", ".join(group_by) if group_by else ""

        sql = f"SELECT\n    {col_list}\nFROM {source_ref}"
        if group_clause:
            sql += f"\nGROUP BY {group_clause}"
        return sql

    def _generate_join_sql(self, config: dict, upstream_refs: list[str]) -> str:
        """Generate SQL for join: SELECT * FROM left JOIN right ON key."""
        join_type = config.get("join_type", "INNER").upper()
        join_key = config.get("join_key", "id")

        if len(upstream_refs) >= 2:
            left_ref = upstream_refs[0]
            right_ref = upstream_refs[1]
        elif len(upstream_refs) == 1:
            left_ref = upstream_refs[0]
            right_ref = "{{ ref('unknown') }}"
        else:
            left_ref = "{{ ref('left') }}"
            right_ref = "{{ ref('right') }}"

        return (
            f"SELECT\n"
            f"    left_table.*,\n"
            f"    right_table.*\n"
            f"FROM {left_ref} AS left_table\n"
            f"{join_type} JOIN {right_ref} AS right_table\n"
            f"    ON left_table.{join_key} = right_table.{join_key}"
        )

    def _generate_sources_yml(self, project_name: str, source_nodes: list[DAGNode]) -> str:
        """Generate dbt sources.yml content for source nodes."""
        if not source_nodes:
            return ""

        tables: list[str] = []
        for node in source_nodes:
            table_name = node.config.get("table_name", "unknown")
            connector_type = node.node_subtype.replace("_source", "")
            tables.append(
                f"      - name: {table_name}\n"
                f"        description: \"Source from {connector_type} connector\""
            )

        tables_str = "\n".join(tables)
        return (
            f"version: 2\n\n"
            f"sources:\n"
            f"  - name: {project_name}\n"
            f"    tables:\n"
            f"{tables_str}\n"
        )
