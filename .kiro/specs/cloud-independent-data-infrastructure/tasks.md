# Implementation Plan: Cloud-Independent Data Infrastructure

## Overview

This plan implements a cloud-independent, self-service data platform as a modular Python/FastAPI backend with React frontend, Dagster orchestration, and comprehensive testing. Tasks are ordered to establish foundational infrastructure first, then layer services incrementally with property-based and unit tests validating correctness at each stage.

## Tasks

- [x] 1. Set up project structure, base models, and core infrastructure
  - [x] 1.1 Create project directory structure and configuration files
    - Create `backend/`, `frontend/`, `tests/`, `deploy/` directory trees
    - Add `pyproject.toml` with FastAPI, SQLAlchemy, Alembic, Celery, Redis, Hypothesis, pytest dependencies (pinned versions)
    - Add `frontend/package.json` with React, TypeScript, Material UI, React Flow, D3.js dependencies
    - Create `.env.example` with all environment variables documented with defaults
    - Create `docker-compose.yml` for development (PostgreSQL, ClickHouse, Redis, RabbitMQ, Elasticsearch, Dagster)
    - _Requirements: 15.2, 15.7, 12.3_

  - [x] 1.2 Implement SQLAlchemy base models and Alembic migrations
    - Create `Base` declarative base with `id` (UUID), `created_at`, `updated_at` mixins
    - Define all 16 SQLAlchemy models: users, roles, permissions, connectors, connector_configs, pipelines, pipeline_versions, pipeline_nodes, pipeline_edges, pipeline_schedules, pipeline_runs, pipeline_run_logs, lineage_events, audit_logs, notifications, system_settings
    - Create initial Alembic migration generating all tables
    - Add audit_logs immutability trigger (prevent UPDATE/DELETE)
    - _Requirements: 10.5, 1.1, 4.1, 5.9_

  - [x] 1.3 Implement FastAPI application skeleton with middleware
    - Create FastAPI app with versioned router (`/api/v1/`)
    - Implement global exception handler that sanitizes internal details (no stack traces, SQL, paths, hostnames)
    - Add structured error response format with `error_code`, `field`, `rejected_value`, `message`
    - Implement request validation middleware returning HTTP 422 with error arrays
    - Add payload size limit middleware (default 10MB, returns HTTP 413)
    - Add CORS and CSRF token-based protection for state-modifying endpoints
    - Add API version header to all responses
    - _Requirements: 13.1, 13.3, 13.5, 13.6, 16.2, 16.3, 16.4_

  - [x] 1.4 Implement rate limiting middleware with Redis sliding window
    - Create sliding window rate limiter using Redis with key pattern `rate_limit:{user_id}:{window_start}`
    - Configure default threshold: 100 requests/minute per user
    - Return HTTP 429 with `Retry-After` header when limit exceeded
    - Make thresholds configurable via system_settings
    - _Requirements: 13.4_

  - [x] 1.5 Implement health check endpoints for all service components
    - Create `/health` endpoint for each service component
    - Return HTTP 200 with JSON `{"service_name": "...", "status": "healthy"}` when healthy
    - Return HTTP 503 when unhealthy
    - Ensure response time does not exceed 2 seconds
    - _Requirements: 15.6_

  - [x]* 1.6 Write property tests for rate limiting and health checks
    - **Property 31: Rate limiting enforcement** — after exceeding 100 requests in sliding window, subsequent requests receive HTTP 429 with Retry-After header
    - **Property 35: Health check endpoint response format** — healthy returns 200 with service_name/status JSON, unhealthy returns 503
    - **Validates: Requirements 13.4, 15.6**

  - [x]* 1.7 Write property test for validation error responses
    - **Property 30: Validation error response completeness** — requests with M errors return exactly M error entries with error_code, field_name, rejected_value, message; no internal details exposed
    - **Validates: Requirements 13.3, 16.2, 16.3**

- [x] 2. Implement Authentication and User Management services
  - [x] 2.1 Implement user CRUD operations
    - Create UserService with create, update, disable, delete operations
    - Validate username (3–64 alphanumeric/underscore), email format, single role assignment
    - Implement duplicate username/email detection with specific field identification in error
    - Implement self-deactivation prevention for Admin accounts
    - Mark deleted users as soft-deleted, preserve audit_log entries
    - Create `/api/v1/users` routes (GET, POST, PUT, DELETE)
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.7, 1.8_

  - [x] 2.2 Implement Authentication Service (login, logout, JWT, lockout)
    - Implement bcrypt password hashing with cost factor 12
    - Implement JWT access token (configurable expiry, default 30 min) and refresh token (default 7 days) issuance
    - Implement token validation and refresh flow
    - Add token blacklist in Redis (invalidated JWTs with TTL matching remaining lifetime)
    - Implement failed attempt counter in Redis with 5-attempt lockout for 15 minutes
    - Implement generic authentication failure messages (no reveal of which field is wrong)
    - Implement password reset token generation (single-use, 24-hour expiry, invalidates predecessors)
    - Create `/api/v1/auth` routes (login, logout, refresh, reset-password-request, reset-password-confirm)
    - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 1.6, 1.9_

  - [x] 2.3 Implement RBAC enforcement middleware
    - Create permission definitions for all 5 roles (Admin, Data_Engineer, Operator, Auditor, Viewer)
    - Implement RBAC middleware validating user role against endpoint permissions on every request
    - Return HTTP 401 for unauthenticated requests to protected endpoints
    - Return HTTP 403 for authenticated users lacking required permissions
    - Propagate role changes on next API request without re-authentication
    - Record all 401/403 events in audit_log
    - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 3.7, 3.8, 3.9_

  - [ ]* 2.4 Write property tests for user management
    - **Property 1: User creation round-trip** — valid username/email/role creates user retrievable with identical attributes
    - **Property 2: Duplicate user rejection identifies correct field** — duplicate username or email rejected with correct field identification
    - **Property 3: User deactivation revokes all access** — disabling user results in zero valid sessions
    - **Property 4: Role assignment updates permissions immediately** — role change reflected on next request
    - **Property 5: Password reset token invalidates predecessors** — only most recent token accepted
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 3.1, 3.9**

  - [ ]* 2.5 Write property tests for authentication and RBAC
    - **Property 6: JWT token lifecycle round-trip** — login produces valid tokens, refresh works before expiry, logout invalidates both
    - **Property 7: Account lockout after consecutive failures** — 5 failures locks for 15 min, then resets
    - **Property 8: RBAC enforcement on all endpoints** — access granted iff role has permission; 401 for unauth, 403 for insufficient
    - **Validates: Requirements 2.1, 2.2, 2.3, 2.4, 2.6, 3.1, 3.7, 3.8**

  - [ ]* 2.6 Write unit tests for user and auth services
    - Test user CRUD operations with valid and invalid inputs
    - Test role-specific permission examples for each of 5 roles
    - Test lockout timing and counter reset
    - Test token expiry edge cases
    - _Requirements: 1.1–1.9, 2.1–2.8, 3.1–3.9_

- [x] 3. Checkpoint - Ensure authentication and user management tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Implement Connector and Credential Management services
  - [x] 4.1 Implement Connector Service with credential encryption
    - Create ConnectorService with CRUD operations
    - Implement AES-256-GCM encryption for credentials with per-connector IV
    - Store encrypted credentials in `connector_configs.encrypted_credentials`
    - Support source types: PostgreSQL, MySQL, CSV, Excel, REST API
    - Support destination types: PostgreSQL, ClickHouse
    - Implement connection test with 30-second timeout
    - Implement health check with circuit breaker (3 failures → OPEN → 60s recovery)
    - Block deletion when active pipelines reference the connector (return dependent pipeline list)
    - Never return plaintext credentials in API responses (use fixed mask value)
    - Clear decrypted credentials from memory within 5 seconds after use
    - Create `/api/v1/connectors` routes (CRUD, test, health-check)
    - _Requirements: 4.1, 4.2, 4.3, 4.4, 4.5, 4.6, 4.7, 4.8, 11.1, 11.2, 11.3_

  - [x] 4.2 Implement master encryption key rotation
    - Implement key rotation that re-encrypts all credentials with new key
    - Ensure no connector re-creation required
    - Ensure no interruption to active pipeline executions during rotation
    - Implement rollback to previous key on partial rotation failure
    - Record rotation success/failure in audit_log
    - _Requirements: 11.4, 11.5, 11.6_

  - [ ]* 4.3 Write property tests for connector and credential management
    - **Property 9: Credential encryption round-trip survives key rotation** — encrypt produces non-plaintext ciphertext, decrypt returns original; key rotation preserves decryptability
    - **Property 10: Credential masking in API responses** — all API responses use fixed mask, reveal no portion of original
    - **Property 11: Connector deletion blocked by dependent pipelines** — deletion rejected with complete dependent pipeline list
    - **Property 28: Key rotation rollback on failure** — partial failure leaves all credentials decryptable with previous key
    - **Validates: Requirements 4.1, 4.3, 4.4, 11.1, 11.2, 11.4, 11.6**

  - [ ]* 4.4 Write unit tests for connector service
    - Test each connector type instantiation (PostgreSQL, MySQL, CSV, Excel, REST)
    - Test connection test timeout handling
    - Test circuit breaker state transitions
    - Test credential masking in various API response scenarios
    - _Requirements: 4.1–4.8, 11.1–11.6_

- [x] 5. Implement Audit Service
  - [x] 5.1 Implement Audit Service with immutable logging
    - Create AuditService with record_event, search_logs, export_logs, check_storage_capacity
    - Record events: login, logout, user CRUD, pipeline CRUD, pipeline execution, connector CRUD
    - Store with: event_type, actor_id, target_resource_id, timestamp (UTC ISO 8601), ip_address, result
    - Implement append-only storage (PostgreSQL triggers prevent UPDATE/DELETE)
    - Implement search with filters: event_type, user, resource, time_range, result — paginated at 100/page
    - Implement export in CSV and JSON (max 100,000 records per export)
    - Implement configurable retention (default 730 days) with automatic archival
    - Emit warning notification when storage reaches 90% capacity
    - Create `/api/v1/audit` routes (search, export)
    - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5, 10.6, 10.7, 2.8_

  - [ ]* 5.2 Write property tests for audit service
    - **Property 25: Audit log entry structure and immutability** — entries contain all required fields, UPDATE/DELETE attempts fail
    - **Property 26: Audit log search correctness** — search returns exactly matching entries for any filter combination, paginated at 100/page
    - **Property 27: Audit log export correctness** — export produces valid CSV/JSON with min(N, 100000) matching records
    - **Validates: Requirements 10.2, 10.3, 10.4, 10.5**

  - [ ]* 5.3 Write unit tests for audit service
    - Test event recording for each event type
    - Test filter combinations and pagination
    - Test export format validation (CSV headers, JSON structure)
    - Test storage capacity warning threshold
    - _Requirements: 10.1–10.7_

- [x] 6. Checkpoint - Ensure connector and audit service tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 7. Implement Pipeline Service and Visual Builder
  - [x] 7.1 Implement DAG validation logic
    - Create DAGValidator with topology validation
    - Validate edge flow direction: source→transform/destination, transform→transform/destination, destination has no outgoing
    - Detect cycles using topological sort (reject with validation error)
    - Enforce limits: maximum 50 nodes, 100 edges
    - Validate completeness: at least one source, one destination, connected path, all required config fields populated
    - Return structured validation errors identifying each invalid/incomplete node
    - _Requirements: 5.3, 5.4, 5.9, 5.11, 5.13_

  - [ ] 7.2 Implement Pipeline Service CRUD and versioning
    - Create PipelineService with create, update, validate, get, delete operations
    - Implement pipeline versioning: each save creates a new `pipeline_versions` record with full JSON snapshot
    - Track `pipelines.current_version` pointer to latest version
    - Implement node deletion that removes connected edges automatically
    - Support source nodes: PostgreSQL, MySQL, CSV, Excel, REST
    - Support transformation nodes: Select Columns, Filter Rows, Rename Columns, Aggregate, Join
    - Support destination nodes: PostgreSQL Destination, ClickHouse Destination
    - Create `/api/v1/pipelines` routes (CRUD, validate, versions)
    - _Requirements: 5.1, 5.2, 5.5, 5.6, 5.8, 5.9, 5.10, 5.12_

  - [ ] 7.3 Implement Dagster definition compilation from pipeline
    - Create compiler that converts validated pipeline DAG into Dagster v1.5 repository/asset definitions
    - Generate syntactically valid Dagster code representing the same DAG topology
    - Handle source node → Dagster asset/op mapping
    - Handle transformation node → Dagster op mapping
    - Handle destination node → Dagster asset/op mapping
    - Reject compilation if DAG is invalid with descriptive error
    - _Requirements: 6.1, 6.2_

  - [x] 7.4 Implement dbt model compilation from transformation nodes
    - Create dbt compiler for transformation nodes (Filter, Aggregate, Join, Select, Rename)
    - Generate dbt v1.10 project structure with valid SQL models
    - Map Filter node config → SQL WHERE clause
    - Map Aggregate node config → SQL GROUP BY with aggregate functions
    - Map Join node config → SQL JOIN with specified keys
    - Map Select Columns → SQL SELECT specific columns
    - Map Rename Columns → SQL column aliases
    - _Requirements: 5.7_

  - [ ]* 7.5 Write property tests for DAG validation and pipeline operations
    - **Property 12: DAG topology validation** — accepts valid flow directions, rejects cycles, rejects >50 nodes or >100 edges
    - **Property 13: Pipeline save validates completeness and creates version** — valid pipelines save with new version, invalid fail with specific errors
    - **Property 14: Node deletion removes connected edges** — deleting node removes all connected edges
    - **Validates: Requirements 5.3, 5.4, 5.9, 5.10, 5.11, 5.12, 5.13**

  - [ ]* 7.6 Write property tests for compilation
    - **Property 15: Dagster definition compilation from valid pipeline** — valid DAG compiles to syntactically valid Dagster definition with same topology
    - **Property 16: dbt model compilation from transformation nodes** — valid transformation config compiles to syntactically valid dbt model with correct SQL
    - **Validates: Requirements 5.7, 6.1**

  - [ ]* 7.7 Write unit tests for pipeline service
    - Test specific node type configurations
    - Test versioning with sequential saves
    - Test DAG validation edge cases (disconnected nodes, multiple sources)
    - Test dbt compilation for each transformation type
    - _Requirements: 5.1–5.13, 6.1, 6.2_

- [x] 8. Implement Pipeline Execution service
  - [x] 8.1 Implement pipeline execution flow with Dagster integration
    - Create execution flow: validate connectors healthy → compile DAG → submit to Dagster
    - Poll Dagster API at ≤5 second intervals to track status (queued, running, succeeded, failed)
    - Record completion: timestamp, row counts per node, total duration
    - Capture Dagster error logs on failure, identify failing node
    - Implement manual retry via Dagster re-execution (max 3 retries per execution)
    - Record lineage events for each data movement step during execution
    - Create `/api/v1/pipelines/{id}/execute` and `/api/v1/pipelines/runs/{id}/retry` routes
    - _Requirements: 6.1, 6.3, 6.4, 6.5, 6.6, 6.7, 6.8, 6.9_

  - [x] 8.2 Implement database connection retry with exponential backoff
    - Implement retry logic: 3 attempts with exponential backoff (1s, 2s, 4s)
    - Mark execution as failed after all retries exhausted
    - Apply to database connection losses during pipeline execution
    - Also implement Redis retry (3x, 500ms/1s/2s) and Dagster API retry (2x, 5s fixed)
    - _Requirements: 16.5_

  - [ ]* 8.3 Write property tests for pipeline execution
    - **Property 17: Pipeline execution retry limit enforcement** — max 3 retries, 4th attempt rejected
    - **Property 18: Pre-execution connector health gate** — unhealthy connectors block execution with error identifying them
    - **Property 34: Database connection retry with exponential backoff** — exactly 3 retries with 1s/2s/4s delays before failure
    - **Validates: Requirements 6.7, 6.9, 16.5**

  - [ ]* 8.4 Write unit tests for pipeline execution
    - Test execution status polling and state transitions
    - Test failure capture with node identification
    - Test retry count enforcement
    - Test connector health pre-check scenarios
    - _Requirements: 6.1–6.9, 16.5_

- [x] 9. Implement Scheduler Service
  - [x] 9.1 Implement Scheduler Service with Dagster integration
    - Create SchedulerService with create, update, pause, resume, delete operations
    - Validate cron expressions: standard 5-field format, minimum interval ≥1 minute
    - Map schedules to Dagster Schedule Definitions
    - Implement pause/resume by activating/deactivating Dagster schedules
    - Queue execution if previous run still active (concurrency handling)
    - Skip execution if pipeline fails validation (missing connector, deleted pipeline, invalid DAG)
    - Record skip reason and generate notification to pipeline owner
    - Create `/api/v1/schedules` routes (CRUD, pause, resume)
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [ ]* 9.2 Write property tests for scheduler
    - **Property 19: Cron expression validation** — accepts valid 5-field cron with ≥1 min interval, rejects invalid with syntax violation message
    - **Property 20: Scheduled execution concurrency queueing** — running execution causes new trigger to queue, starts after completion
    - **Validates: Requirements 7.1, 7.5, 7.7**

  - [ ]* 9.3 Write unit tests for scheduler service
    - Test valid and invalid cron expression examples
    - Test schedule lifecycle (create, pause, resume, delete)
    - Test concurrency queueing behavior
    - Test skip scenarios with notification generation
    - _Requirements: 7.1–7.7_

- [x] 10. Checkpoint - Ensure pipeline and scheduler tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 11. Implement Lineage Service
  - [x] 11.1 Implement Lineage Service with ClickHouse storage
    - Create LineageService with record_lineage_event, get_lineage_graph, query_by_time_range, get_node_metadata
    - Store lineage events in ClickHouse partitioned by month
    - Record all required fields: source_system, source_table, destination_system, destination_table, transformation_node, pipeline_id, execution_id, triggered_by, timestamp
    - Implement graph traversal up to 10 levels upstream/downstream
    - Implement time-range filtering (inclusive)
    - Return empty graph with message for tables with no lineage data
    - Implement configurable retention (default 365 days, min 30, max 2555)
    - Create `/api/v1/lineage` routes (graph, query, node-metadata)
    - _Requirements: 9.1, 9.2, 9.4, 9.5, 9.6, 9.7_

  - [ ]* 11.2 Write property tests for lineage service
    - **Property 22: Lineage event completeness** — K data movement steps produce exactly K events with all required fields
    - **Property 23: Lineage graph traversal depth limit** — traversal returns min(L, 10) levels, never exceeds 10
    - **Property 24: Lineage time-range filtering** — returns exactly events with timestamps within [start, end] inclusive
    - **Validates: Requirements 9.1, 9.2, 9.6**

  - [ ]* 11.3 Write unit tests for lineage service
    - Test lineage recording for multi-step pipelines
    - Test graph traversal with various depths
    - Test time-range filtering edge cases
    - Test empty lineage response for unknown tables
    - _Requirements: 9.1–9.7_

- [x] 12. Implement Notification Service
  - [x] 12.1 Implement Notification Service with Celery async delivery
    - Create NotificationService with create, get_user_notifications, mark_as_read, suppress_duplicate, cleanup_expired
    - Implement notification generation for: pipeline failure (→ owner + Operators), connector failure (→ Data_Engineers + Operators), resource threshold (→ Admins)
    - Include event-specific fields: pipeline name, execution ID, failure timestamp, failing node name
    - Implement deduplication: suppress same source/event_type within 15 min of unacknowledged notification, increment recurrence_count
    - Implement 30-day retention with automatic cleanup
    - Display as chronological list with event_type, summary, source_resource, timestamp, read status
    - Use Celery tasks via RabbitMQ for async notification dispatch
    - Create `/api/v1/notifications` routes (list, mark-read)
    - _Requirements: 14.1, 14.2, 14.3, 14.4, 14.5, 14.6_

  - [ ]* 12.2 Write property tests for notification service
    - **Property 32: Critical event notification targeting** — correct role-based recipients for each event type with required fields
    - **Property 33: Notification deduplication within suppression window** — same source within 15 min suppressed with recurrence_count increment
    - **Validates: Requirements 14.1, 14.2, 14.3, 14.6**

  - [ ]* 12.3 Write unit tests for notification service
    - Test notification content format for each event type
    - Test role-based targeting logic
    - Test deduplication window boundary cases
    - Test 30-day cleanup behavior
    - _Requirements: 14.1–14.6_

- [x] 13. Implement Monitoring Service
  - [x] 13.1 Implement Monitoring Service with Elasticsearch and Prometheus
    - Create MonitoringService with get_dashboard_metrics, get_system_health, query_logs, expose_prometheus_metrics
    - Dashboard metrics: running pipelines, failed in 24h, succeeded in 24h, avg execution time, task queue size, retry count, system health status (healthy/degraded/unhealthy)
    - Update failed pipeline count within 10 seconds of failure
    - Stream logs (stdout/stderr, Dagster events, worker activities) into Elasticsearch v8.13
    - Query logs: chronological, timestamped, paginated at 100/page, return within 5 seconds
    - Expose Prometheus metrics: execution count, duration, failure count, queue size, retry count
    - Implement configurable log retention (default 90 days) with automatic deletion
    - Create `/api/v1/monitoring` routes (dashboard, health, logs)
    - _Requirements: 8.1, 8.2, 8.3, 8.4, 8.5, 8.6, 8.8_

  - [ ]* 13.2 Write property test for log pagination
    - **Property 21: Log query pagination correctness** — N entries with page size 100, page P returns chronological entries at positions [(P-1)*100, min(P*100, N)) with correct total
    - **Validates: Requirements 8.5**

  - [ ]* 13.3 Write unit tests for monitoring service
    - Test dashboard metric calculations
    - Test system health status determination (healthy/degraded/unhealthy)
    - Test Elasticsearch log query and pagination
    - Test Prometheus metric exposure format
    - _Requirements: 8.1–8.8_

- [x] 14. Checkpoint - Ensure lineage, notification, and monitoring tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 15. Implement React Frontend - Pipeline Builder and Dashboard
  - [x] 15.1 Set up React frontend with routing and layout
    - Create React app with TypeScript, Material UI theming, and route structure
    - Implement authenticated routes with JWT token management
    - Create layout with navigation sidebar and notification panel
    - Implement role-based UI route guards matching RBAC policy
    - Set up API client with interceptors for token refresh and error handling
    - _Requirements: 3.1, 2.6, 13.6_

  - [x] 15.2 Implement Visual Pipeline Builder with React Flow
    - Create canvas with React Flow for drag-and-drop pipeline building
    - Implement node palette with source, transformation, and destination nodes
    - Implement node configuration panels triggered on node placement/selection
    - Implement edge validation (permitted flow directions, cycle detection with visual feedback)
    - Implement node/edge deletion with connected edge cleanup
    - Implement save with DAG validation feedback (highlight invalid nodes, error summary)
    - Implement version history view
    - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6, 5.8, 5.9, 5.10, 5.11, 5.12_

  - [x] 15.3 Implement Monitoring Dashboard UI
    - Create dashboard displaying: running count, failed in 24h, succeeded in 24h, avg execution time, queue size, retry count, system health
    - Implement real-time update (failed count within 10 seconds)
    - Implement execution log viewer with chronological display and pagination
    - _Requirements: 8.1, 8.2, 8.3, 8.5_

  - [x] 15.4 Implement Lineage Visualization with D3.js
    - Create directed graph layout for lineage visualization using D3.js
    - Show nodes (tables/systems/transformation steps) and edges (data flows)
    - Implement node selection showing metadata (last execution, row count, triggering user)
    - Implement time-range filtering controls
    - Handle empty lineage with appropriate message
    - _Requirements: 9.2, 9.3, 9.4, 9.6, 9.7_

  - [x] 15.5 Implement Admin, Connector, and Notification UI pages
    - Create user management page (CRUD, role assignment, password reset)
    - Create connector management page (CRUD, test connection, health status)
    - Create notification list with read/unread status and recurrence indicators
    - Create audit log search and export page
    - Create system settings page
    - Implement client-side input validation matching server-side rules
    - _Requirements: 1.1–1.9, 4.1–4.8, 10.3, 10.4, 14.4, 16.1_

  - [ ]* 15.6 Write unit tests for frontend components
    - Test Pipeline Builder node placement and edge validation
    - Test dashboard metric display
    - Test role-based route guards
    - Test form validation logic
    - _Requirements: 5.1–5.13, 8.1–8.3, 3.1–3.6_

- [x] 16. Checkpoint - Ensure frontend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 17. Implement Air-Gapped Deployment and Infrastructure
  - [x] 17.1 Implement air-gapped deployment support
    - Ensure no runtime dependency on public internet (no telemetry, license validation, update checks, external DNS)
    - Mark REST API source connectors as disabled in air-gapped mode with appropriate message
    - Block outbound public internet connections and record attempts in audit_log
    - Provide OCI-compliant container images loadable from local registries or filesystem archives
    - Bundle all dependencies (Python packages, npm packages, system libraries) with pinned versions
    - Support offline updates via versioned artifacts transferable via physical media
    - _Requirements: 12.1, 12.2, 12.3, 12.5, 12.6, 12.7_

  - [ ]* 17.2 Write property test for air-gapped connector availability
    - **Property 29: Air-gapped connector availability** — all types available except REST_API which is disabled with message
    - **Validates: Requirements 12.5**

  - [x] 17.3 Create Dockerfiles and Docker Compose configuration
    - Create Dockerfiles for: backend API, frontend, Celery workers, Dagster scheduler
    - Create Docker Compose for development with all services (PostgreSQL, ClickHouse, Redis, RabbitMQ, Elasticsearch, Dagster)
    - Single `docker-compose up` starts entire stack
    - _Requirements: 15.1, 15.2_

  - [x] 17.4 Create Kubernetes manifests and NGINX configuration
    - Create Kubernetes manifests with Deployments, Services, ConfigMaps, Secrets
    - Configure Horizontal Pod Autoscaler for API and worker pods
    - Create NGINX config for reverse proxy, TLS termination, and static asset serving
    - Externalize all environment-specific configuration via environment variables
    - _Requirements: 15.3, 15.4, 15.7_

  - [x] 17.5 Create GitHub Actions CI/CD workflows
    - Create workflow with stages: lint, unit-tests, property-tests, integration-tests, e2e-tests, build, publish
    - Configure 30-minute timeout
    - Block merge if tests fail or coverage drops below 80%
    - Build and publish container images on successful pipeline
    - _Requirements: 15.5, 17.4_

  - [x] 17.6 Create Grafana dashboards and Prometheus configuration
    - Configure Prometheus to scrape platform metrics
    - Create pre-configured Grafana dashboards for pipeline monitoring
    - Include panels: execution count, duration, failure rate, queue size, retry trends
    - _Requirements: 8.6, 8.7_

- [x] 18. Implement Input Validation and OpenAPI documentation
  - [x] 18.1 Implement comprehensive input validation
    - Add client-side and server-side validation for all user inputs
    - Enforce: required fields, data type correctness, format conformance (email, cron), max length (255 for text, 5000 for descriptions)
    - Return structured error arrays with all detected errors per request
    - Ensure error messages exclude internal details (stack traces, queries, paths, hostnames)
    - _Requirements: 16.1, 16.2, 16.3, 16.6_

  - [x] 18.2 Configure OpenAPI auto-generation and documentation
    - Enable FastAPI auto-generated OpenAPI 3.0 spec at dedicated endpoint (no auth required)
    - Organize endpoints by domain: auth, users, connectors, pipelines, schedules, monitoring, lineage, audit, notifications
    - Ensure all endpoints have proper request/response schema documentation
    - _Requirements: 13.1, 13.2_

- [x] 19. Implement Testing Infrastructure
  - [x] 19.1 Create test factories and fixtures
    - Create `factory_boy` factories for all domain models (users, connectors, pipelines, audit_logs, etc.)
    - Create pytest fixtures providing pre-configured test states
    - Create custom Hypothesis strategies for DAGs, cron expressions, usernames, emails
    - Ensure all test data is self-contained with no network access required
    - _Requirements: 17.5_

  - [ ]* 19.2 Write integration tests for all API endpoints
    - Test every API endpoint defined in OpenAPI spec
    - Verify request validation, response structure, database state changes
    - Use Docker Compose test environment with real PostgreSQL, Redis, RabbitMQ, Elasticsearch
    - _Requirements: 17.2_

  - [ ]* 19.3 Write end-to-end tests for critical workflows
    - Test: Login → Create Connector → Test Connection → Build Pipeline → Save → Execute → View Lineage
    - Test: Login → Create Schedule → Verify Execution Triggered → View Logs
    - Test: Admin Login → Create User → Assign Role → Verify Permissions
    - Test: Pipeline Failure → Notification Generated → Operator Views → Retry
    - _Requirements: 17.3_

- [x] 20. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation at major milestones
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The backend uses Python 3.11 with FastAPI, SQLAlchemy, Alembic, Celery, Redis, RabbitMQ
- The frontend uses React with TypeScript, Material UI, React Flow, D3.js
- Dagster v1.5 handles pipeline orchestration; dbt v1.10 handles SQL transformations
- Elasticsearch v8.13 stores structured logs; ClickHouse stores lineage analytics
- All services are co-located in the same FastAPI process for v1 (synchronous calls)
- Async operations (pipeline execution, notifications, log indexing) use Celery via RabbitMQ

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3"] },
    { "id": 2, "tasks": ["1.4", "1.5"] },
    { "id": 3, "tasks": ["1.6", "1.7"] },
    { "id": 4, "tasks": ["2.1", "5.1"] },
    { "id": 5, "tasks": ["2.2", "2.3", "5.2", "5.3"] },
    { "id": 6, "tasks": ["2.4", "2.5", "2.6"] },
    { "id": 7, "tasks": ["4.1"] },
    { "id": 8, "tasks": ["4.2", "4.3", "4.4"] },
    { "id": 9, "tasks": ["7.1"] },
    { "id": 10, "tasks": ["7.2", "7.3", "7.4"] },
    { "id": 11, "tasks": ["7.5", "7.6", "7.7"] },
    { "id": 12, "tasks": ["8.1", "9.1"] },
    { "id": 13, "tasks": ["8.2", "8.3", "8.4", "9.2", "9.3"] },
    { "id": 14, "tasks": ["11.1", "12.1"] },
    { "id": 15, "tasks": ["11.2", "11.3", "12.2", "12.3", "13.1"] },
    { "id": 16, "tasks": ["13.2", "13.3"] },
    { "id": 17, "tasks": ["15.1"] },
    { "id": 18, "tasks": ["15.2", "15.3", "15.4", "15.5"] },
    { "id": 19, "tasks": ["15.6"] },
    { "id": 20, "tasks": ["17.1", "17.3"] },
    { "id": 21, "tasks": ["17.2", "17.4", "17.5", "17.6"] },
    { "id": 22, "tasks": ["18.1", "18.2"] },
    { "id": 23, "tasks": ["19.1"] },
    { "id": 24, "tasks": ["19.2", "19.3"] }
  ]
}
```
