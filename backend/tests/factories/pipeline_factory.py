"""Factory-boy factories for Pipeline, PipelineVersion, PipelineNode, PipelineEdge."""

import uuid

import factory

from backend.app.models.pipelines import (
    Pipeline,
    PipelineEdge,
    PipelineNode,
    PipelineRun,
    PipelineRunLog,
    PipelineSchedule,
    PipelineVersion,
)


class PipelineFactory(factory.Factory):
    """Factory for creating Pipeline instances."""

    class Meta:
        model = Pipeline

    id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"pipeline_{n}")
    description = factory.LazyAttribute(lambda o: f"Description for {o.name}")
    status = "draft"
    current_version = 1
    created_by = factory.LazyFunction(uuid.uuid4)


class ActivePipelineFactory(PipelineFactory):
    """Factory for active/published pipelines."""

    status = "active"


class ArchivedPipelineFactory(PipelineFactory):
    """Factory for archived pipelines."""

    status = "archived"


class PipelineVersionFactory(factory.Factory):
    """Factory for creating PipelineVersion instances."""

    class Meta:
        model = PipelineVersion

    id = factory.LazyFunction(uuid.uuid4)
    pipeline_id = factory.LazyFunction(uuid.uuid4)
    version_number = factory.Sequence(lambda n: n + 1)
    definition_snapshot = factory.LazyFunction(
        lambda: {
            "nodes": [
                {"id": "src_1", "type": "source", "subtype": "postgresql", "config": {}},
                {"id": "dst_1", "type": "destination", "subtype": "postgresql", "config": {}},
            ],
            "edges": [{"source": "src_1", "target": "dst_1"}],
        }
    )
    created_by = factory.LazyFunction(uuid.uuid4)


class PipelineNodeFactory(factory.Factory):
    """Factory for creating PipelineNode instances."""

    class Meta:
        model = PipelineNode

    id = factory.LazyFunction(uuid.uuid4)
    pipeline_id = factory.LazyFunction(uuid.uuid4)
    version = 1
    node_type = "source"
    node_subtype = "postgresql"
    config = factory.LazyFunction(lambda: {"connector_id": str(uuid.uuid4()), "table": "users"})
    position_x = factory.Sequence(lambda n: float(n * 200))
    position_y = factory.Sequence(lambda n: float(n * 100))


class SourceNodeFactory(PipelineNodeFactory):
    """Factory for source nodes."""

    node_type = "source"
    node_subtype = factory.Iterator(["postgresql", "mysql", "mongodb", "s3"])


class TransformNodeFactory(PipelineNodeFactory):
    """Factory for transform nodes."""

    node_type = "transform"
    node_subtype = factory.Iterator(["filter", "aggregate", "join", "select", "rename"])
    config = factory.LazyFunction(lambda: {"sql": "SELECT * FROM input WHERE active = true"})


class DestinationNodeFactory(PipelineNodeFactory):
    """Factory for destination nodes."""

    node_type = "destination"
    node_subtype = factory.Iterator(["postgresql", "mysql", "s3", "clickhouse"])
    config = factory.LazyFunction(
        lambda: {"connector_id": str(uuid.uuid4()), "table": "output_table", "write_mode": "append"}
    )


class PipelineEdgeFactory(factory.Factory):
    """Factory for creating PipelineEdge instances."""

    class Meta:
        model = PipelineEdge

    id = factory.LazyFunction(uuid.uuid4)
    pipeline_id = factory.LazyFunction(uuid.uuid4)
    version = 1
    source_node_id = factory.LazyFunction(uuid.uuid4)
    target_node_id = factory.LazyFunction(uuid.uuid4)


class PipelineScheduleFactory(factory.Factory):
    """Factory for creating PipelineSchedule instances."""

    class Meta:
        model = PipelineSchedule

    id = factory.LazyFunction(uuid.uuid4)
    pipeline_id = factory.LazyFunction(uuid.uuid4)
    cron_expression = "0 */6 * * *"
    status = "active"
    dagster_schedule_name = factory.LazyAttribute(
        lambda o: f"schedule_{o.pipeline_id}"
    )
    created_by = factory.LazyFunction(uuid.uuid4)


class PipelineRunFactory(factory.Factory):
    """Factory for creating PipelineRun instances."""

    class Meta:
        model = PipelineRun

    id = factory.LazyFunction(uuid.uuid4)
    pipeline_id = factory.LazyFunction(uuid.uuid4)
    pipeline_version = 1
    status = "running"
    trigger_type = "manual"
    triggered_by = factory.LazyFunction(uuid.uuid4)
    retry_count = 0
    node_row_counts = None
    started_at = None
    completed_at = None
    duration_ms = None


class SuccessfulRunFactory(PipelineRunFactory):
    """Factory for successful pipeline runs."""

    status = "success"
    duration_ms = 12500


class FailedRunFactory(PipelineRunFactory):
    """Factory for failed pipeline runs."""

    status = "failed"
    duration_ms = 5000


class PipelineRunLogFactory(factory.Factory):
    """Factory for creating PipelineRunLog instances."""

    class Meta:
        model = PipelineRunLog

    id = factory.LazyFunction(uuid.uuid4)
    run_id = factory.LazyFunction(uuid.uuid4)
    level = factory.Iterator(["INFO", "WARNING", "ERROR", "DEBUG"])
    message = factory.Sequence(lambda n: f"Log message {n}")
    node_id = None
