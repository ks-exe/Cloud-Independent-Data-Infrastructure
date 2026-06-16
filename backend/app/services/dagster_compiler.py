"""Dagster Compiler — Compiles validated pipeline DAGs into Dagster v1.5 job/op definitions.

Converts pipeline node/edge definitions into syntactically valid Python code that uses
Dagster's @op and @job decorators. The generated code can be written to a file and
loaded by the Dagster runtime.

Source nodes → Dagster ops that read from external systems
Transformation nodes → Dagster ops that process data
Destination nodes → Dagster ops that write to target systems
Edges → Dagster dependencies between ops

Requirements: 6.1, 6.2
"""

import re
import textwrap
from collections import defaultdict
from dataclasses import dataclass, field

from backend.app.services.dag_validator import (
    DAGEdge,
    DAGNode,
    DAGValidator,
    ValidationResult,
)


@dataclass
class DagsterDefinition:
    """Result of compiling a pipeline DAG to Dagster code."""

    code: str
    job_name: str
    op_names: list[str] = field(default_factory=list)
    is_valid: bool = True
    error: str | None = None


class DagsterCompiler:
    """Compiles validated pipeline DAGs into Dagster v1.5 op/job Python code.

    The compiler:
    1. Validates the pipeline DAG using DAGValidator
    2. Generates @op definitions for each node (source, transformation, destination)
    3. Generates a @job function wiring ops according to the DAG edges
    4. Returns a DagsterDefinition with the generated Python code
    """

    def __init__(self) -> None:
        self._validator = DAGValidator()

    def compile(self, pipeline_name: str, nodes: list[DAGNode], edges: list[DAGEdge]) -> DagsterDefinition:
        """Compile a pipeline definition into Dagster Python code.

        Args:
            pipeline_name: Human-readable pipeline name (sanitized to valid Python identifier).
            nodes: List of DAGNode instances in the pipeline.
            edges: List of DAGEdge instances connecting nodes.

        Returns:
            DagsterDefinition with generated code, or error if DAG is invalid.
        """
        # Step 1: Validate the DAG
        validation_result = self._validator.validate(nodes, edges)
        if not validation_result.is_valid:
            error_messages = "; ".join(e.message for e in validation_result.errors)
            return DagsterDefinition(
                code="",
                job_name="",
                op_names=[],
                is_valid=False,
                error=f"DAG validation failed: {error_messages}",
            )

        # Step 2: Build graph structures
        node_map = {node.id: node for node in nodes}
        job_name = self._sanitize_identifier(f"pipeline_{pipeline_name}")

        # Build adjacency and reverse adjacency for dependency resolution
        # outgoing[node_id] = list of node_ids this node feeds into
        outgoing: dict[str, list[str]] = defaultdict(list)
        # incoming[node_id] = list of node_ids that feed into this node
        incoming: dict[str, list[str]] = defaultdict(list)

        for edge in edges:
            outgoing[edge.source_node_id].append(edge.target_node_id)
            incoming[edge.target_node_id].append(edge.source_node_id)

        # Step 3: Generate op names for each node
        op_names_map: dict[str, str] = {}
        for node in nodes:
            op_names_map[node.id] = self._generate_op_name(node)

        op_names = list(op_names_map.values())

        # Step 4: Topological sort for ordering ops and job wiring
        topo_order = self._topological_sort(nodes, edges)

        # Step 5: Generate code
        code_parts: list[str] = []

        # Imports
        code_parts.append(self._generate_imports(incoming))

        # Op definitions in topological order
        for node_id in topo_order:
            node = node_map[node_id]
            op_name = op_names_map[node_id]
            input_count = len(incoming.get(node_id, []))
            code_parts.append(self._generate_op(node, op_name, input_count))

        # Job definition
        code_parts.append(
            self._generate_job(job_name, topo_order, node_map, op_names_map, incoming)
        )

        code = "\n\n".join(code_parts) + "\n"

        return DagsterDefinition(
            code=code,
            job_name=job_name,
            op_names=op_names,
            is_valid=True,
            error=None,
        )

    def _sanitize_identifier(self, name: str) -> str:
        """Convert a string to a valid Python identifier."""
        # Replace non-alphanumeric chars with underscores
        sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        # Ensure it doesn't start with a digit
        if sanitized and sanitized[0].isdigit():
            sanitized = f"_{sanitized}"
        # Collapse multiple underscores
        sanitized = re.sub(r"_+", "_", sanitized)
        # Strip trailing underscores
        sanitized = sanitized.strip("_")
        return sanitized.lower()

    def _generate_op_name(self, node: DAGNode) -> str:
        """Generate a unique op function name from a node."""
        prefix_map = {
            "source": "source",
            "transformation": "transform",
            "destination": "dest",
        }
        prefix = prefix_map.get(node.node_type, node.node_type)
        # Use subtype (without the _source/_destination suffix for clarity)
        subtype_clean = node.node_subtype.replace("_source", "").replace("_destination", "")
        name = f"{prefix}_{subtype_clean}_{node.id}"
        return self._sanitize_identifier(name)

    def _generate_imports(self, incoming: dict[str, list[str]]) -> str:
        """Generate Dagster import statements."""
        imports = ["from dagster import job, op"]
        # Only import In/Out if there are nodes with inputs
        has_inputs = any(len(deps) > 0 for deps in incoming.values())
        if has_inputs:
            imports = ["from dagster import job, op, In, Out"]
        return "\n".join(imports)

    def _generate_op(self, node: DAGNode, op_name: str, input_count: int) -> str:
        """Generate an @op function definition for a node."""
        if node.node_type == "source":
            return self._generate_source_op(node, op_name)
        elif node.node_type == "transformation":
            return self._generate_transform_op(node, op_name, input_count)
        elif node.node_type == "destination":
            return self._generate_destination_op(node, op_name, input_count)
        else:
            # Fallback — should not happen after validation
            return self._generate_generic_op(node, op_name, input_count)

    def _generate_source_op(self, node: DAGNode, op_name: str) -> str:
        """Generate a source op that reads from an external system."""
        connector_type = node.node_subtype.replace("_source", "")
        config = node.config or {}

        # Build comment describing the extraction
        if connector_type in ("postgresql", "mysql"):
            table = config.get("table_name", "unknown_table")
            comment = f"Extract from {connector_type} table: {table}"
        elif connector_type == "csv":
            file_path = config.get("file_path", "unknown_path")
            comment = f"Extract from CSV file: {file_path}"
        elif connector_type == "excel":
            file_path = config.get("file_path", "unknown_path")
            sheet = config.get("sheet_name", "Sheet1")
            comment = f"Extract from Excel file: {file_path}, sheet: {sheet}"
        elif connector_type == "rest":
            endpoint = config.get("endpoint", "/unknown")
            comment = f"Extract from REST API endpoint: {endpoint}"
        else:
            comment = f"Extract from {connector_type} connector"

        return textwrap.dedent(f"""\
            @op(out=Out())
            def {op_name}():
                # {comment}
                ...""")

    def _generate_transform_op(self, node: DAGNode, op_name: str, input_count: int) -> str:
        """Generate a transformation op that processes data."""
        config = node.config or {}
        transform_type = node.node_subtype

        # Build comment based on transformation type
        if transform_type == "filter_rows":
            condition = config.get("condition", "")
            comment = f"Apply filter: {condition}"
        elif transform_type == "select_columns":
            columns = config.get("columns", [])
            comment = f"Select columns: {', '.join(columns) if columns else 'all'}"
        elif transform_type == "rename_columns":
            mapping = config.get("mapping", {})
            renames = ", ".join(f"{k} → {v}" for k, v in mapping.items())
            comment = f"Rename columns: {renames}"
        elif transform_type == "aggregate":
            group_by = config.get("group_by", [])
            comment = f"Aggregate grouped by: {', '.join(group_by) if group_by else 'none'}"
        elif transform_type == "join":
            join_type = config.get("join_type", "inner")
            join_key = config.get("join_key", "")
            comment = f"Apply {join_type} join on key: {join_key}"
        else:
            comment = f"Apply transformation: {transform_type}"

        # Generate input parameters
        ins_decorator, params = self._build_input_spec(input_count)

        return textwrap.dedent(f"""\
            @op({ins_decorator}out=Out())
            def {op_name}({params}):
                # {comment}
                ...""")

    def _generate_destination_op(self, node: DAGNode, op_name: str, input_count: int) -> str:
        """Generate a destination op that writes to a target system."""
        connector_type = node.node_subtype.replace("_destination", "")
        config = node.config or {}
        table = config.get("table_name", "unknown_table")
        write_mode = config.get("write_mode", "append")
        comment = f"Load to {connector_type} table: {table} (mode: {write_mode})"

        # Generate input parameters
        ins_decorator, params = self._build_input_spec(input_count)

        return textwrap.dedent(f"""\
            @op({ins_decorator})
            def {op_name}({params}):
                # {comment}
                ...""")

    def _generate_generic_op(self, node: DAGNode, op_name: str, input_count: int) -> str:
        """Fallback op generation."""
        ins_decorator, params = self._build_input_spec(input_count)
        return textwrap.dedent(f"""\
            @op({ins_decorator})
            def {op_name}({params}):
                # Node: {node.id} ({node.node_type}/{node.node_subtype})
                ...""")

    def _build_input_spec(self, input_count: int) -> tuple[str, str]:
        """Build the ins= decorator fragment and function parameters.

        Returns:
            Tuple of (ins_decorator_fragment, parameter_list_string)
        """
        if input_count == 0:
            return "", ""
        elif input_count == 1:
            return 'ins={"input_data": In()}, ', "input_data"
        else:
            # Multiple inputs (fan-in, e.g. join)
            ins_parts = []
            params = []
            for i in range(input_count):
                name = f"input_{i}"
                ins_parts.append(f'"{name}": In()')
                params.append(name)
            ins_str = "ins={" + ", ".join(ins_parts) + "}, "
            return ins_str, ", ".join(params)

    def _generate_job(
        self,
        job_name: str,
        topo_order: list[str],
        node_map: dict[str, DAGNode],
        op_names_map: dict[str, str],
        incoming: dict[str, list[str]],
    ) -> str:
        """Generate the @job function that wires all ops together."""
        lines: list[str] = []
        lines.append("@job")
        lines.append(f"def {job_name}():")

        # Track variable names for each node's output
        var_names: dict[str, str] = {}

        for node_id in topo_order:
            node = node_map[node_id]
            op_name = op_names_map[node_id]
            deps = incoming.get(node_id, [])

            # Generate a variable name from the op name
            var_name = f"result_{op_name}"
            var_names[node_id] = var_name

            if len(deps) == 0:
                # Source node — no inputs
                lines.append(f"    {var_name} = {op_name}()")
            elif len(deps) == 1:
                # Single input
                dep_var = var_names[deps[0]]
                lines.append(f"    {var_name} = {op_name}({dep_var})")
            else:
                # Multiple inputs (fan-in)
                dep_vars = ", ".join(var_names[dep_id] for dep_id in deps)
                lines.append(f"    {var_name} = {op_name}({dep_vars})")

        return "\n".join(lines)

    def _topological_sort(self, nodes: list[DAGNode], edges: list[DAGEdge]) -> list[str]:
        """Compute topological order of nodes using Kahn's algorithm.

        Assumes the DAG is valid (no cycles) — caller must validate first.
        """
        from collections import deque

        node_ids = {node.id for node in nodes}
        in_degree: dict[str, int] = {nid: 0 for nid in node_ids}
        adjacency: dict[str, list[str]] = {nid: [] for nid in node_ids}

        for edge in edges:
            if edge.source_node_id in node_ids and edge.target_node_id in node_ids:
                adjacency[edge.source_node_id].append(edge.target_node_id)
                in_degree[edge.target_node_id] += 1

        queue: deque[str] = deque()
        for nid in sorted(node_ids):  # sorted for deterministic output
            if in_degree[nid] == 0:
                queue.append(nid)

        result: list[str] = []
        while queue:
            current = queue.popleft()
            result.append(current)
            for neighbor in sorted(adjacency[current]):  # sorted for determinism
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result
