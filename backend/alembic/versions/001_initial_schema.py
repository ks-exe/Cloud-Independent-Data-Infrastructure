"""Initial schema - all 16 tables with audit_logs immutability trigger.

Revision ID: 001_initial_schema
Revises:
Create Date: 2024-01-01 00:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- roles ---
    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("permissions", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # --- users ---
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(64), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username"),
        sa.UniqueConstraint("email"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
    )

    # --- permissions ---
    op.create_table(
        "permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource", sa.String(100), nullable=False),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"]),
    )

    # --- connectors ---
    op.create_table(
        "connectors",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )

    # --- connector_configs ---
    op.create_table(
        "connector_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("connector_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("host", sa.String(255), nullable=True),
        sa.Column("port", sa.Integer(), nullable=True),
        sa.Column("database_name", sa.String(255), nullable=True),
        sa.Column("encrypted_credentials", sa.LargeBinary(), nullable=True),
        sa.Column("extra_params", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connector_id"),
        sa.ForeignKeyConstraint(["connector_id"], ["connectors.id"]),
    )

    # --- pipelines ---
    op.create_table(
        "pipelines",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )

    # --- pipeline_versions ---
    op.create_table(
        "pipeline_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("definition_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )

    # --- pipeline_nodes ---
    op.create_table(
        "pipeline_nodes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("node_type", sa.String(50), nullable=False),
        sa.Column("node_subtype", sa.String(50), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=True),
        sa.Column("position_x", sa.Float(), nullable=False, server_default="0"),
        sa.Column("position_y", sa.Float(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"]),
    )

    # --- pipeline_edges ---
    op.create_table(
        "pipeline_edges",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("source_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_node_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"]),
        sa.ForeignKeyConstraint(["source_node_id"], ["pipeline_nodes.id"]),
        sa.ForeignKeyConstraint(["target_node_id"], ["pipeline_nodes.id"]),
    )

    # --- pipeline_schedules ---
    op.create_table(
        "pipeline_schedules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cron_expression", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("dagster_schedule_name", sa.String(255), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
    )

    # --- pipeline_runs ---
    op.create_table(
        "pipeline_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("trigger_type", sa.String(20), nullable=False),
        sa.Column("triggered_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("node_row_counts", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"]),
        sa.ForeignKeyConstraint(["triggered_by"], ["users.id"]),
    )

    # --- pipeline_run_logs ---
    op.create_table(
        "pipeline_run_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("level", sa.String(20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("node_id", sa.String(255), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["run_id"], ["pipeline_runs.id"]),
    )

    # --- lineage_events ---
    op.create_table(
        "lineage_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pipeline_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_system", sa.String(255), nullable=False),
        sa.Column("source_table", sa.String(255), nullable=False),
        sa.Column("destination_system", sa.String(255), nullable=False),
        sa.Column("destination_table", sa.String(255), nullable=False),
        sa.Column("transformation_node", sa.String(255), nullable=True),
        sa.Column("triggered_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["pipeline_id"], ["pipelines.id"]),
        sa.ForeignKeyConstraint(["execution_id"], ["pipeline_runs.id"]),
        sa.ForeignKeyConstraint(["triggered_by"], ["users.id"]),
    )

    # --- audit_logs ---
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_resource_id", sa.String(255), nullable=True),
        sa.Column("target_resource_type", sa.String(100), nullable=True),
        sa.Column("result", sa.String(50), nullable=False),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
    )

    # --- notifications ---
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("source_resource_id", sa.String(255), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("recurrence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )

    # --- system_settings ---
    op.create_table(
        "system_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=True),
        sa.Column("category", sa.String(100), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"]),
    )

    # --- Audit logs immutability trigger ---
    # Prevent UPDATE and DELETE on audit_logs table
    op.execute("""
        CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_logs table is immutable: % operations are not allowed', TG_OP;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER audit_logs_prevent_update
        BEFORE UPDATE ON audit_logs
        FOR EACH ROW
        EXECUTE FUNCTION prevent_audit_log_modification();
    """)

    op.execute("""
        CREATE TRIGGER audit_logs_prevent_delete
        BEFORE DELETE ON audit_logs
        FOR EACH ROW
        EXECUTE FUNCTION prevent_audit_log_modification();
    """)

    # --- Useful indexes ---
    op.create_index("ix_users_username", "users", ["username"])
    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_audit_logs_event_type", "audit_logs", ["event_type"])
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"])
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_pipeline_runs_pipeline_id", "pipeline_runs", ["pipeline_id"])
    op.create_index("ix_pipeline_runs_status", "pipeline_runs", ["status"])
    op.create_index("ix_lineage_events_pipeline_id", "lineage_events", ["pipeline_id"])
    op.create_index("ix_lineage_events_timestamp", "lineage_events", ["timestamp"])
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_is_read", "notifications", ["is_read"])


def downgrade() -> None:
    # Drop triggers first
    op.execute("DROP TRIGGER IF EXISTS audit_logs_prevent_delete ON audit_logs;")
    op.execute("DROP TRIGGER IF EXISTS audit_logs_prevent_update ON audit_logs;")
    op.execute("DROP FUNCTION IF EXISTS prevent_audit_log_modification();")

    # Drop indexes
    op.drop_index("ix_notifications_is_read", table_name="notifications")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_index("ix_lineage_events_timestamp", table_name="lineage_events")
    op.drop_index("ix_lineage_events_pipeline_id", table_name="lineage_events")
    op.drop_index("ix_pipeline_runs_status", table_name="pipeline_runs")
    op.drop_index("ix_pipeline_runs_pipeline_id", table_name="pipeline_runs")
    op.drop_index("ix_audit_logs_timestamp", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_event_type", table_name="audit_logs")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_index("ix_users_username", table_name="users")

    # Drop tables in reverse dependency order
    op.drop_table("system_settings")
    op.drop_table("notifications")
    op.drop_table("audit_logs")
    op.drop_table("lineage_events")
    op.drop_table("pipeline_run_logs")
    op.drop_table("pipeline_runs")
    op.drop_table("pipeline_schedules")
    op.drop_table("pipeline_edges")
    op.drop_table("pipeline_nodes")
    op.drop_table("pipeline_versions")
    op.drop_table("pipelines")
    op.drop_table("connector_configs")
    op.drop_table("connectors")
    op.drop_table("permissions")
    op.drop_table("users")
    op.drop_table("roles")
