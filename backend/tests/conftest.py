"""Shared pytest fixtures and configuration for backend tests.

Provides:
- db_session: Async SQLite in-memory database session for unit tests
- client: httpx.AsyncClient wired to the FastAPI app
- auth_headers: Pre-built auth headers with valid JWT for each role
- sample_user: Fixture providing a created user in the DB
- sample_connector: Fixture providing a connector with encrypted credentials
- sample_pipeline: Fixture providing a pipeline with nodes and edges
"""

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import JSON, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.core.encryption import encrypt_credentials
from backend.app.core.security import create_access_token, hash_password
from backend.app.main import create_app
from backend.app.models.audit import AuditLog
from backend.app.models.base import Base
from backend.app.models.connectors import Connector, ConnectorConfig
from backend.app.models.pipelines import (
    Pipeline,
    PipelineEdge,
    PipelineNode,
    PipelineVersion,
)
from backend.app.models.users import Role, User


def _apply_sqlite_type_overrides():
    """Override PostgreSQL-specific types to work with SQLite for testing.

    Maps JSONB → JSON and UUID → String(36) so that the same models
    work against an in-memory SQLite database.
    """
    from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID

    # Register JSONB as JSON for SQLite
    from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler

    if not hasattr(SQLiteTypeCompiler, "visit_JSONB"):
        SQLiteTypeCompiler.visit_JSONB = SQLiteTypeCompiler.visit_JSON


# Apply overrides at import time
_apply_sqlite_type_overrides()


# --- Database Fixtures ---

@pytest_asyncio.fixture
async def db_engine():
    """Create an async SQLite in-memory engine for testing."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Provide an async database session using SQLite in-memory for unit tests."""
    session_factory = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with session_factory() as session:
        yield session
        await session.rollback()


# --- Application & Client Fixtures ---

@pytest_asyncio.fixture
async def app(db_engine):
    """Create a FastAPI app instance for testing."""
    from backend.app.core import database as db_module

    # Override the database engine/session for testing
    test_session_factory = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    application = create_app()

    # Override the get_db dependency
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        async with test_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    from backend.app.core.database import get_db
    application.dependency_overrides[get_db] = override_get_db

    yield application

    application.dependency_overrides.clear()


@pytest_asyncio.fixture
async def client(app) -> AsyncGenerator[AsyncClient, None]:
    """Provide an httpx.AsyncClient for API testing."""
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as ac:
        yield ac


# --- Auth Header Fixtures ---

@pytest.fixture
def _role_ids() -> dict[str, uuid.UUID]:
    """Provide fixed role IDs for test JWT generation."""
    return {
        "Admin": uuid.UUID("10000000-0000-0000-0000-000000000001"),
        "Operator": uuid.UUID("10000000-0000-0000-0000-000000000002"),
        "Data_Engineer": uuid.UUID("10000000-0000-0000-0000-000000000003"),
        "Viewer": uuid.UUID("10000000-0000-0000-0000-000000000004"),
    }


@pytest.fixture
def _user_ids() -> dict[str, uuid.UUID]:
    """Provide fixed user IDs for test JWT generation."""
    return {
        "Admin": uuid.UUID("20000000-0000-0000-0000-000000000001"),
        "Operator": uuid.UUID("20000000-0000-0000-0000-000000000002"),
        "Data_Engineer": uuid.UUID("20000000-0000-0000-0000-000000000003"),
        "Viewer": uuid.UUID("20000000-0000-0000-0000-000000000004"),
    }


@pytest.fixture
def auth_headers(_user_ids) -> dict[str, dict[str, str]]:
    """Pre-built auth headers with a valid JWT for each role.

    Returns a dict keyed by role name, each value is a headers dict:
        auth_headers["Admin"] -> {"Authorization": "Bearer <token>"}
        auth_headers["Operator"] -> {"Authorization": "Bearer <token>"}
        auth_headers["Data_Engineer"] -> {"Authorization": "Bearer <token>"}
        auth_headers["Viewer"] -> {"Authorization": "Bearer <token>"}
    """
    headers = {}
    for role_name, user_id in _user_ids.items():
        token, _, _ = create_access_token(
            user_id=str(user_id),
            role=role_name,
        )
        headers[role_name] = {"Authorization": f"Bearer {token}"}
    return headers


# --- Sample Data Fixtures ---

@pytest_asyncio.fixture
async def sample_role(db_session: AsyncSession) -> Role:
    """Create and persist a sample role in the test database."""
    role = Role(
        id=uuid.UUID("10000000-0000-0000-0000-000000000001"),
        name="Admin",
        description="Full system administrator",
        permissions={"resources": ["*"], "actions": ["*"]},
    )
    db_session.add(role)
    await db_session.flush()
    return role


@pytest_asyncio.fixture
async def sample_user(db_session: AsyncSession, sample_role: Role) -> User:
    """Create and persist a sample user in the test database."""
    user = User(
        id=uuid.UUID("20000000-0000-0000-0000-000000000001"),
        username="test_admin",
        email="admin@example.com",
        password_hash=hash_password("AdminPassword123!"),
        display_name="Test Admin",
        role_id=sample_role.id,
        is_active=True,
        is_deleted=False,
    )
    db_session.add(user)
    await db_session.flush()
    return user


@pytest_asyncio.fixture
async def sample_connector(
    db_session: AsyncSession, sample_user: User
) -> Connector:
    """Create and persist a sample connector with encrypted credentials."""
    connector = Connector(
        id=uuid.uuid4(),
        name="test_pg_source",
        type="postgresql",
        direction="source",
        status="active",
        created_by=sample_user.id,
    )
    db_session.add(connector)
    await db_session.flush()

    config = ConnectorConfig(
        id=uuid.uuid4(),
        connector_id=connector.id,
        host="db.internal.test",
        port=5432,
        database_name="test_database",
        encrypted_credentials=encrypt_credentials({
            "username": "db_readonly",
            "password": "secret_password_123",
        }),
        extra_params={"ssl_mode": "require", "pool_size": 5},
    )
    db_session.add(config)
    await db_session.flush()

    # Attach config to connector for easy access
    connector.config = config
    return connector


@pytest_asyncio.fixture
async def sample_pipeline(
    db_session: AsyncSession, sample_user: User
) -> Pipeline:
    """Create and persist a pipeline with nodes and edges."""
    pipeline = Pipeline(
        id=uuid.uuid4(),
        name="test_etl_pipeline",
        description="A test ETL pipeline with source, transform, and destination",
        status="active",
        current_version=1,
        created_by=sample_user.id,
    )
    db_session.add(pipeline)
    await db_session.flush()

    # Create nodes
    source_node = PipelineNode(
        id=uuid.uuid4(),
        pipeline_id=pipeline.id,
        version=1,
        node_type="source",
        node_subtype="postgresql",
        config={"connector_id": str(uuid.uuid4()), "table": "customers"},
        position_x=0.0,
        position_y=0.0,
    )

    transform_node = PipelineNode(
        id=uuid.uuid4(),
        pipeline_id=pipeline.id,
        version=1,
        node_type="transform",
        node_subtype="filter",
        config={"expression": "status = 'active'"},
        position_x=200.0,
        position_y=0.0,
    )

    destination_node = PipelineNode(
        id=uuid.uuid4(),
        pipeline_id=pipeline.id,
        version=1,
        node_type="destination",
        node_subtype="postgresql",
        config={"connector_id": str(uuid.uuid4()), "table": "active_customers", "write_mode": "upsert"},
        position_x=400.0,
        position_y=0.0,
    )

    db_session.add_all([source_node, transform_node, destination_node])
    await db_session.flush()

    # Create edges: source → transform → destination
    edge1 = PipelineEdge(
        id=uuid.uuid4(),
        pipeline_id=pipeline.id,
        version=1,
        source_node_id=source_node.id,
        target_node_id=transform_node.id,
    )
    edge2 = PipelineEdge(
        id=uuid.uuid4(),
        pipeline_id=pipeline.id,
        version=1,
        source_node_id=transform_node.id,
        target_node_id=destination_node.id,
    )

    db_session.add_all([edge1, edge2])
    await db_session.flush()

    # Create a version snapshot
    version = PipelineVersion(
        id=uuid.uuid4(),
        pipeline_id=pipeline.id,
        version_number=1,
        definition_snapshot={
            "nodes": [
                {"id": str(source_node.id), "type": "source", "subtype": "postgresql"},
                {"id": str(transform_node.id), "type": "transform", "subtype": "filter"},
                {"id": str(destination_node.id), "type": "destination", "subtype": "postgresql"},
            ],
            "edges": [
                {"source": str(source_node.id), "target": str(transform_node.id)},
                {"source": str(transform_node.id), "target": str(destination_node.id)},
            ],
        },
        created_by=sample_user.id,
    )
    db_session.add(version)
    await db_session.flush()

    # Attach nodes/edges for easy access in tests
    pipeline.nodes = [source_node, transform_node, destination_node]
    pipeline.edges = [edge1, edge2]
    pipeline.versions = [version]

    return pipeline


@pytest.fixture
def anyio_backend():
    """Configure anyio to use asyncio."""
    return "asyncio"
