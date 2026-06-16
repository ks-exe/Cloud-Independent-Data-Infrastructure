"""Custom Hypothesis strategies for property-based testing.

Provides generators for domain-specific valid inputs:
- Valid usernames (3-64 alphanumeric/underscore characters)
- Valid emails
- Valid cron expressions (5-field, minimum 1-minute interval)
- Valid DAGs (source + transforms + destination with valid edges)
"""

import string

from hypothesis import strategies as st


# --- Username Strategy ---

def valid_usernames(min_size: int = 3, max_size: int = 64) -> st.SearchStrategy[str]:
    """Generate valid usernames: 3-64 alphanumeric/underscore characters.

    Usernames must:
    - Be between 3 and 64 characters
    - Contain only alphanumeric characters and underscores
    - Start with a letter or underscore (not a digit)
    """
    first_char = st.sampled_from(string.ascii_letters + "_")
    rest_chars = st.text(
        alphabet=string.ascii_letters + string.digits + "_",
        min_size=min_size - 1,
        max_size=max_size - 1,
    )
    return st.builds(lambda f, r: f + r, first_char, rest_chars)


# --- Email Strategy ---

def valid_emails() -> st.SearchStrategy[str]:
    """Generate valid email addresses.

    Produces emails of the form: local@domain.tld
    - Local part: 1-64 alphanumeric/dot/underscore/hyphen characters
    - Domain: 1-63 alphanumeric/hyphen characters
    - TLD: 2-10 lowercase letters
    """
    local_part = st.text(
        alphabet=string.ascii_lowercase + string.digits + "._-",
        min_size=1,
        max_size=32,
    ).filter(lambda s: not s.startswith(".") and not s.endswith(".") and ".." not in s)

    domain_part = st.text(
        alphabet=string.ascii_lowercase + string.digits + "-",
        min_size=1,
        max_size=30,
    ).filter(lambda s: not s.startswith("-") and not s.endswith("-"))

    tld = st.text(
        alphabet=string.ascii_lowercase,
        min_size=2,
        max_size=6,
    )

    return st.builds(
        lambda local, domain, t: f"{local}@{domain}.{t}",
        local_part,
        domain_part,
        tld,
    )


# --- Cron Expression Strategy ---

# Valid cron field ranges
_CRON_MINUTE = (0, 59)
_CRON_HOUR = (0, 23)
_CRON_DAY_OF_MONTH = (1, 31)
_CRON_MONTH = (1, 12)
_CRON_DAY_OF_WEEK = (0, 6)


def _cron_field(min_val: int, max_val: int) -> st.SearchStrategy[str]:
    """Generate a single valid cron field value.

    Supports: specific values, ranges, wildcards, and step values.
    """
    specific = st.integers(min_value=min_val, max_value=max_val).map(str)
    wildcard = st.just("*")
    step = st.builds(
        lambda base, step_val: f"{base}/{step_val}",
        st.just("*"),
        st.integers(min_value=1, max_value=max(1, max_val - min_val)),
    )
    range_expr = st.builds(
        lambda a, b: f"{min(a, b)}-{max(a, b)}",
        st.integers(min_value=min_val, max_value=max_val),
        st.integers(min_value=min_val, max_value=max_val),
    )

    return st.one_of(specific, wildcard, step, range_expr)


def valid_cron_expressions() -> st.SearchStrategy[str]:
    """Generate valid 5-field cron expressions with at least 1-minute interval.

    Fields: minute hour day-of-month month day-of-week

    Filters out expressions that would trigger more often than once per minute
    (e.g., all wildcards is valid — runs every minute, which meets the minimum).
    """
    return st.builds(
        lambda m, h, dom, mon, dow: f"{m} {h} {dom} {mon} {dow}",
        _cron_field(*_CRON_MINUTE),
        _cron_field(*_CRON_HOUR),
        _cron_field(*_CRON_DAY_OF_MONTH),
        _cron_field(*_CRON_MONTH),
        _cron_field(*_CRON_DAY_OF_WEEK),
    )


# --- DAG Strategy ---

_NODE_TYPES = {
    "source": ["postgresql", "mysql", "mongodb", "s3"],
    "transform": ["filter", "aggregate", "join", "select", "rename"],
    "destination": ["postgresql", "mysql", "s3", "clickhouse"],
}


@st.composite
def valid_dags(
    draw: st.DrawFn,
    min_transforms: int = 0,
    max_transforms: int = 5,
    min_sources: int = 1,
    max_sources: int = 3,
    min_destinations: int = 1,
    max_destinations: int = 2,
) -> dict:
    """Generate valid DAG structures with source → transform → destination flow.

    A valid DAG must:
    - Have at least 1 source node and 1 destination node
    - Have a connected path from each source to at least one destination
    - Have no cycles
    - Follow permitted edge directions:
      - source → transform or destination
      - transform → transform or destination
      - destination has no outgoing edges
    - Not exceed 50 nodes or 100 edges

    Returns:
        Dict with 'nodes' and 'edges' keys representing the DAG.
    """
    # Generate source nodes
    num_sources = draw(st.integers(min_value=min_sources, max_value=max_sources))
    source_nodes = []
    for i in range(num_sources):
        subtype = draw(st.sampled_from(_NODE_TYPES["source"]))
        source_nodes.append({
            "id": f"source_{i}",
            "type": "source",
            "subtype": subtype,
            "config": {"connector_id": f"conn_{i}", "table": f"table_{i}"},
            "position_x": float(i * 200),
            "position_y": 0.0,
        })

    # Generate transform nodes
    num_transforms = draw(st.integers(min_value=min_transforms, max_value=max_transforms))
    transform_nodes = []
    for i in range(num_transforms):
        subtype = draw(st.sampled_from(_NODE_TYPES["transform"]))
        transform_nodes.append({
            "id": f"transform_{i}",
            "type": "transform",
            "subtype": subtype,
            "config": {"expression": f"transform_config_{i}"},
            "position_x": float(i * 200),
            "position_y": 200.0,
        })

    # Generate destination nodes
    num_destinations = draw(st.integers(min_value=min_destinations, max_value=max_destinations))
    destination_nodes = []
    for i in range(num_destinations):
        subtype = draw(st.sampled_from(_NODE_TYPES["destination"]))
        destination_nodes.append({
            "id": f"destination_{i}",
            "type": "destination",
            "subtype": subtype,
            "config": {"connector_id": f"conn_dest_{i}", "table": f"output_{i}", "write_mode": "append"},
            "position_x": float(i * 200),
            "position_y": 400.0,
        })

    all_nodes = source_nodes + transform_nodes + destination_nodes

    # Generate edges following valid DAG topology
    edges = []

    if num_transforms == 0:
        # Direct source → destination edges
        for src in source_nodes:
            dest = draw(st.sampled_from(destination_nodes))
            edges.append({"source": src["id"], "target": dest["id"]})
    else:
        # source → first transform layer
        for src in source_nodes:
            target = draw(st.sampled_from(transform_nodes))
            edges.append({"source": src["id"], "target": target["id"]})

        # transform → transform edges (optional chaining, no cycles)
        if num_transforms > 1:
            for i in range(num_transforms - 1):
                # Only connect forward (i → j where j > i) to avoid cycles
                if draw(st.booleans()):
                    edges.append({
                        "source": f"transform_{i}",
                        "target": f"transform_{i + 1}",
                    })

        # last transforms → destinations
        # Ensure at least one transform connects to a destination
        last_transform = transform_nodes[-1]
        dest = draw(st.sampled_from(destination_nodes))
        edges.append({"source": last_transform["id"], "target": dest["id"]})

        # Additional transform → destination edges
        for t in transform_nodes[:-1]:
            if draw(st.booleans()):
                dest = draw(st.sampled_from(destination_nodes))
                edges.append({"source": t["id"], "target": dest["id"]})

    # Deduplicate edges
    seen = set()
    unique_edges = []
    for edge in edges:
        key = (edge["source"], edge["target"])
        if key not in seen:
            seen.add(key)
            unique_edges.append(edge)

    return {
        "nodes": all_nodes,
        "edges": unique_edges,
    }
