"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings with environment variable overrides."""

    # Application
    app_name: str = "cloud-data-platform"
    app_env: str = "development"
    app_debug: bool = True
    app_version: str = "1.0.0"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    api_prefix: str = "/api/v1"

    # Security
    secret_key: str = "change-this-to-a-random-secret-key-in-production"
    jwt_access_token_expire_minutes: int = 30
    jwt_refresh_token_expire_days: int = 7
    jwt_algorithm: str = "HS256"
    bcrypt_cost_factor: int = 12
    credential_encryption_key: str = "change-this-to-a-32-byte-hex-key-in-production"
    csrf_secret_key: str = "change-this-csrf-secret-in-production"

    # PostgreSQL
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "cloud_data_platform"
    postgres_user: str = "platform_user"
    postgres_password: str = "platform_password"
    database_url: str = "postgresql+asyncpg://platform_user:platform_password@localhost:5432/cloud_data_platform"

    # ClickHouse
    clickhouse_host: str = "localhost"
    clickhouse_port: int = 8123
    clickhouse_db: str = "lineage"
    clickhouse_user: str = "default"
    clickhouse_password: str = "clickhouse_password"

    # Redis
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str = "redis_password"
    redis_url: str = "redis://:redis_password@localhost:6379/0"

    # RabbitMQ
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "platform_user"
    rabbitmq_password: str = "rabbitmq_password"
    celery_broker_url: str = "amqp://platform_user:rabbitmq_password@localhost:5672//"

    # Celery
    celery_result_backend: str = "redis://:redis_password@localhost:6379/1"
    celery_task_always_eager: bool = False
    celery_worker_concurrency: int = 4

    # Elasticsearch
    elasticsearch_host: str = "localhost"
    elasticsearch_port: int = 9200
    elasticsearch_user: str = "elastic"
    elasticsearch_password: str = "elastic_password"
    elasticsearch_url: str = "http://elastic:elastic_password@localhost:9200"
    elasticsearch_log_retention_days: int = 90

    # Dagster
    dagster_webserver_host: str = "localhost"
    dagster_webserver_port: int = 3000

    # Rate Limiting
    rate_limit_requests_per_minute: int = 100
    rate_limit_window_seconds: int = 60

    # Notifications
    notification_retention_days: int = 30
    notification_dedup_window_minutes: int = 15

    # Audit
    audit_log_retention_days: int = 730
    audit_log_storage_warning_threshold: float = 0.9
    audit_log_max_export_records: int = 100000

    # Lineage
    lineage_retention_days: int = 365
    lineage_max_traversal_depth: int = 10

    # Pipeline
    pipeline_max_nodes: int = 50
    pipeline_max_edges: int = 100
    pipeline_max_retries: int = 3
    pipeline_status_poll_interval_seconds: int = 5

    # Payload limits
    max_payload_size_mb: int = 10

    # Air-gapped mode
    air_gapped_mode: bool = False

    # Account security
    account_lockout_threshold: int = 5
    account_lockout_duration_minutes: int = 15
    password_reset_token_expiry_hours: int = 24

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "case_sensitive": False}


settings = Settings()
