"""Factory-boy factories for Connector and ConnectorConfig models."""

import uuid

import factory

from backend.app.core.encryption import encrypt_credentials
from backend.app.models.connectors import Connector, ConnectorConfig


class ConnectorFactory(factory.Factory):
    """Factory for creating Connector instances."""

    class Meta:
        model = Connector

    id = factory.LazyFunction(uuid.uuid4)
    name = factory.Sequence(lambda n: f"connector_{n}")
    type = factory.Iterator(["postgresql", "mysql", "mongodb", "s3", "rest_api"])
    direction = factory.Iterator(["source", "destination", "bidirectional"])
    status = "active"
    created_by = factory.LazyFunction(uuid.uuid4)


class SourceConnectorFactory(ConnectorFactory):
    """Factory for source connectors."""

    direction = "source"
    name = factory.Sequence(lambda n: f"source_connector_{n}")


class DestinationConnectorFactory(ConnectorFactory):
    """Factory for destination connectors."""

    direction = "destination"
    name = factory.Sequence(lambda n: f"dest_connector_{n}")


class PostgreSQLConnectorFactory(ConnectorFactory):
    """Factory for PostgreSQL connectors."""

    type = "postgresql"
    name = factory.Sequence(lambda n: f"pg_connector_{n}")


class InactiveConnectorFactory(ConnectorFactory):
    """Factory for inactive/unhealthy connectors."""

    status = "unhealthy"


class ConnectorConfigFactory(factory.Factory):
    """Factory for creating ConnectorConfig instances."""

    class Meta:
        model = ConnectorConfig

    id = factory.LazyFunction(uuid.uuid4)
    connector_id = factory.LazyFunction(uuid.uuid4)
    host = factory.Sequence(lambda n: f"db-host-{n}.internal")
    port = 5432
    database_name = factory.Sequence(lambda n: f"database_{n}")
    encrypted_credentials = factory.LazyFunction(
        lambda: encrypt_credentials({"username": "db_user", "password": "db_pass_secret"})
    )
    extra_params = factory.LazyFunction(lambda: {"ssl_mode": "require", "pool_size": 10})


class ConnectorConfigWithCustomCredsFactory(ConnectorConfigFactory):
    """Factory for ConnectorConfig with custom credentials."""

    class Params:
        credentials = {"username": "custom_user", "password": "custom_pass"}

    encrypted_credentials = factory.LazyAttribute(
        lambda o: encrypt_credentials(o.credentials if hasattr(o, "credentials") else {"username": "custom", "password": "pass"})
    )


class MySQLConnectorConfigFactory(ConnectorConfigFactory):
    """Factory for MySQL connector configs."""

    port = 3306
    extra_params = factory.LazyFunction(lambda: {"charset": "utf8mb4"})


class MongoDBConnectorConfigFactory(ConnectorConfigFactory):
    """Factory for MongoDB connector configs."""

    port = 27017
    database_name = factory.Sequence(lambda n: f"mongo_db_{n}")
    extra_params = factory.LazyFunction(lambda: {"auth_source": "admin", "replica_set": "rs0"})
