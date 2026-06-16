# Cloud-Independent Data Infrastructure

An open-source, self-service data platform that enables organizations to build, schedule, monitor, and audit data pipelines entirely on their own infrastructure — without relying on public cloud services.

Designed as an on-premises alternative to Fivetran, Stitch, and other cloud-only data integration tools for regulated industries where data sovereignty, security, and compliance are critical.

![Python](https://img.shields.io/badge/Python-3.11-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.109-green?logo=fastapi)
![React](https://img.shields.io/badge/React-18.2-blue?logo=react)
![TypeScript](https://img.shields.io/badge/TypeScript-5.3-blue?logo=typescript)
![Docker](https://img.shields.io/badge/Docker-Compose-blue?logo=docker)
![License](https://img.shields.io/badge/License-MIT-yellow)

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [User Roles](#user-roles)
- [API Documentation](#api-documentation)
- [Deployment](#deployment)
- [Testing](#testing)
- [Configuration](#configuration)
- [Target Industries](#target-industries)
- [Contributing](#contributing)
- [License](#license)

---

## Features

### Visual Pipeline Builder
- Drag-and-drop pipeline creation with React Flow
- Source, transformation, and destination nodes
- Real-time DAG validation (cycle detection, flow rules)
- Pipeline versioning with full history
- No-code workflow building

### Connectors (v1)
| Sources | Destinations |
|---------|-------------|
| PostgreSQL | PostgreSQL |
| MySQL | ClickHouse |
| CSV Files | |
| Excel Files | |
| REST API | |

### Pipeline Orchestration
- Dagster v1.5 for DAG execution and scheduling
- dbt v1.10 for SQL-based transformations
- Cron-based scheduling with concurrency handling
- Automatic retry with exponential backoff (max 3 retries)
- Pre-execution connector health validation

### Data Lineage
- End-to-end lineage tracking (source → transformation → destination)
- D3.js force-directed graph visualization
- BFS traversal up to 10 levels upstream/downstream
- Time-range filtering
- Per-node metadata (last execution, row count, triggering user)

### Monitoring & Observability
- Real-time dashboard with 10-second polling
- Pipeline execution metrics (running, failed, succeeded, avg time)
- Prometheus metrics endpoint for Grafana integration
- Elasticsearch-powered log search with pagination
- System health status (healthy/degraded/unhealthy)

### Security & Compliance
- JWT authentication with refresh tokens
- Role-Based Access Control (5 roles)
- AES-256-GCM credential encryption with key rotation
- Immutable append-only audit logs
- Account lockout after 5 failed attempts
- CSRF protection, rate limiting, input validation
- Air-gapped deployment support

### Audit & Governance
- Immutable audit log for all platform actions
- Search/filter by event type, user, resource, time range
- CSV/JSON export (up to 100,000 records)
- 730-day configurable retention
- Storage capacity monitoring with admin alerts

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        NGINX (Reverse Proxy)                         │
│                    TLS Termination + Static Assets                    │
└──────────────────────────┬──────────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
┌───────▼───────┐  ┌───────▼───────┐  ┌───────▼───────┐
│   React UI    │  │  FastAPI API  │  │   Grafana     │
│  (Frontend)   │  │   (Backend)   │  │ (Dashboards)  │
└───────────────┘  └───────┬───────┘  └───────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
┌───────▼───────┐  ┌───────▼───────┐  ┌───────▼───────┐
│    Celery     │  │    Dagster    │  │  Prometheus   │
│   Workers     │  │  Orchestrator │  │   Metrics     │
└───────┬───────┘  └───────┬───────┘  └───────────────┘
        │                  │
┌───────▼──────────────────▼──────────────────────────────────────────┐
│                        Data Layer                                     │
│  ┌──────────┐  ┌──────────┐  ┌───────┐  ┌──────────┐  ┌─────────┐ │
│  │PostgreSQL│  │ClickHouse│  │ Redis │  │ RabbitMQ │  │Elastic- │ │
│  │(Metadata)│  │(Lineage) │  │(Cache)│  │ (Queue)  │  │search   │ │
│  └──────────┘  └──────────┘  └───────┘  └──────────┘  └─────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11, FastAPI, SQLAlchemy, Alembic, Celery |
| **Orchestration** | Dagster v1.5, dbt v1.10 |
| **Frontend** | React 18, TypeScript 5.3, Material UI 5, React Flow 11, D3.js 7 |
| **Databases** | PostgreSQL 16, ClickHouse 24.1 |
| **Caching** | Redis 7.2 |
| **Messaging** | RabbitMQ 3.13 |
| **Search** | Elasticsearch 8.13 |
| **Monitoring** | Prometheus 2.49, Grafana 10.3 |
| **Infrastructure** | Docker, Docker Compose, Kubernetes, NGINX |
| **CI/CD** | GitHub Actions |

---

## Quick Start

### Prerequisites

- Docker Engine >= 24.0
- Docker Compose v2.x
- 16 GB RAM (recommended)
- 20 GB free disk space

### 1. Clone the Repository

```bash
git clone https://github.com/ks-exe/Cloud-Independent-Data-Infrastructure.git
cd Cloud-Independent-Data-Infrastructure
```

### 2. Create Environment File

```bash
cp .env.example .env
```

The default `.env.example` values work out of the box for local development. No external API keys needed.

### 3. Start All Services

```bash
docker-compose up -d
```

This starts all 12 services with a single command:
- PostgreSQL, ClickHouse, Redis, RabbitMQ, Elasticsearch
- Dagster (webserver + daemon)
- Prometheus, Grafana
- Backend API, Frontend, Celery Worker, Scheduler

### 4. Access the Platform

| Service | URL | Credentials |
|---------|-----|-------------|
| **Frontend** | http://localhost:80 | (login via API) |
| **Backend API (Swagger)** | http://localhost:8000/docs | — |
| **Dagster** | http://localhost:3000 | — |
| **Grafana** | http://localhost:3001 | admin / grafana_password |
| **RabbitMQ Management** | http://localhost:15672 | platform_user / rabbitmq_password |
| **Prometheus** | http://localhost:9090 | — |

### 5. Run Database Migrations

```bash
docker-compose exec backend alembic upgrade head
```

### 6. Create Initial Admin User

```bash
docker-compose exec backend python -m backend.app.scripts.create_admin
```

Or via the API:
```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "email": "admin@example.com", "password": "Admin123!", "role": "Admin"}'
```

---

## Project Structure

```
├── backend/                    # Python FastAPI backend
│   ├── app/
│   │   ├── api/v1/           # API route handlers (9 domains)
│   │   ├── core/             # Config, security, encryption, health, metrics
│   │   ├── middleware/       # Rate limiting, CSRF, error handling, payload limits
│   │   ├── models/           # SQLAlchemy ORM models (16 tables)
│   │   ├── schemas/          # Pydantic request/response schemas
│   │   ├── services/         # Business logic services (12 services)
│   │   └── tasks/            # Celery async tasks
│   ├── alembic/              # Database migrations
│   └── tests/                # Unit, integration, property, e2e tests
│       ├── unit/             # 500+ unit tests
│       ├── integration/      # API integration tests
│       ├── properties/       # Hypothesis property-based tests
│       ├── e2e/              # End-to-end workflow tests
│       └── factories/        # Test data factories + Hypothesis strategies
├── frontend/                  # React TypeScript frontend
│   └── src/
│       ├── components/       # Reusable UI components
│       │   ├── pipeline/     # Pipeline Builder (React Flow nodes, palette, config)
│       │   ├── lineage/      # D3.js lineage graph, node details, time filter
│       │   ├── monitoring/   # Metric cards, health indicator, log viewer
│       │   └── notifications/# Notification panel with badge
│       ├── pages/            # Route page components (10 pages)
│       ├── services/         # API client services
│       ├── hooks/            # React hooks (auth context)
│       └── types/            # TypeScript type definitions
├── deploy/                    # Deployment configurations
│   ├── docker/               # Dockerfiles (backend, frontend, worker, scheduler)
│   ├── kubernetes/           # K8s manifests (11 files)
│   ├── nginx/                # NGINX reverse proxy config
│   ├── grafana/              # Grafana dashboards + datasources
│   ├── prometheus/           # Prometheus scrape config
│   └── air-gapped/           # Air-gapped deployment scripts + docs
├── .github/workflows/         # CI/CD pipelines
│   ├── ci.yml                # Main CI (lint → test → build → publish)
│   └── release.yml           # Release pipeline (versioned images + changelog)
├── docker-compose.yml         # Full development stack (12 services)
├── pyproject.toml             # Python dependencies (pinned)
└── .env.example               # Environment variable reference
```

---

## User Roles

| Role | Capabilities |
|------|-------------|
| **Admin** | Full access: users, connectors, pipelines, settings, audit logs |
| **Data Engineer** | Create/manage connectors and pipelines, schedule executions |
| **Operator** | Monitor executions, view logs, retry failed pipelines |
| **Auditor** | View lineage, audit logs, generate compliance reports |
| **Viewer** | Read-only access to dashboards and pipeline status |

---

## API Documentation

The platform exposes a complete REST API documented via OpenAPI 3.0:

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

### API Domains

| Domain | Endpoints | Description |
|--------|-----------|-------------|
| `/api/v1/auth` | 5 | Login, logout, refresh, password reset |
| `/api/v1/users` | 6 | User CRUD, role assignment |
| `/api/v1/connectors` | 7 | Connector CRUD, test, health check |
| `/api/v1/pipelines` | 10 | Pipeline CRUD, validate, execute, retry, versions |
| `/api/v1/schedules` | 8 | Schedule CRUD, pause, resume, validate cron |
| `/api/v1/monitoring` | 5 | Dashboard metrics, health, logs, Prometheus |
| `/api/v1/lineage` | 4 | Graph traversal, time-range query, node metadata |
| `/api/v1/audit` | 3 | Search, export, storage capacity |
| `/api/v1/notifications` | 2 | List, mark as read |
| `/api/v1/settings` | 1 | Key rotation |
| `/api/v1/health` | 1 | Detailed system health check |

---

## Deployment

### Development (Docker Compose)

```bash
docker-compose up -d          # Start all services
docker-compose down           # Stop all services
docker-compose down -v        # Stop and remove volumes
docker-compose logs backend   # View backend logs
```

### Production (Kubernetes)

```bash
kubectl apply -f deploy/kubernetes/namespace.yaml
kubectl apply -f deploy/kubernetes/
```

Features:
- Horizontal Pod Autoscaler (API: 2-5 replicas, Workers: 1-10)
- NGINX Ingress with TLS termination
- PersistentVolumeClaims for data persistence
- ConfigMaps and Secrets for configuration

### Air-Gapped Deployment

For environments without internet connectivity:

```bash
# On a connected machine: export all images
cd deploy/air-gapped
./save-images.sh ./images

# Transfer images to air-gapped host, then:
./load-images.sh ./images
docker-compose up -d
./verify-deployment.sh
```

See [deploy/air-gapped/README.md](deploy/air-gapped/README.md) for the complete guide.

---

## Testing

### Run Unit Tests

```bash
cd backend
python -m pytest tests/unit/ -v --cov=app --cov-fail-under=80
```

### Run All Tests

```bash
# Unit tests
python -m pytest tests/unit/ -v

# Property-based tests (Hypothesis)
python -m pytest tests/properties/ -v

# Integration tests (requires Docker services)
python -m pytest tests/integration/ -v

# Frontend tests
cd frontend && npm test
```

### Test Coverage

The project targets 80% minimum line coverage enforced in CI.

---

## Configuration

All configuration is via environment variables. See [.env.example](.env.example) for the complete reference.

### Key Configuration Categories

| Category | Variables | Notes |
|----------|-----------|-------|
| Security | `SECRET_KEY`, `CREDENTIAL_ENCRYPTION_KEY`, `CSRF_SECRET_KEY` | Generate unique values for production |
| Database | `POSTGRES_*`, `CLICKHOUSE_*` | Connection details |
| Cache | `REDIS_*` | Rate limiting, token blacklist |
| Queue | `RABBITMQ_*`, `CELERY_*` | Async task processing |
| Search | `ELASTICSEARCH_*` | Log storage and retrieval |
| Orchestration | `DAGSTER_*` | Pipeline execution |
| Limits | `RATE_LIMIT_*`, `MAX_PAYLOAD_SIZE_MB` | API protection |
| Retention | `AUDIT_LOG_RETENTION_DAYS`, `LINEAGE_RETENTION_DAYS` | Data lifecycle |
| Air-Gapped | `AIR_GAPPED_MODE` | Disables REST API connectors |

---

## Target Industries

This platform is designed for organizations in regulated sectors:

- **Banking** — Data sovereignty, audit trails, compliance reporting
- **Healthcare** — HIPAA-aligned data handling, lineage tracking
- **Government** — Air-gapped deployments, security clearance environments
- **Telecom** — High-volume data pipelines, on-premises processing
- **Defense** — Complete isolation, no external dependencies

---

## Key Design Decisions

1. **Dagster for orchestration** — Native DAG execution, scheduling, retry logic, and observability without building a custom orchestrator
2. **dbt for transformations** — Visual transformation nodes compile to SQL models executed inside the destination warehouse
3. **Dual database strategy** — PostgreSQL for transactional/metadata; ClickHouse for analytical lineage queries
4. **Elasticsearch for logs** — Structured log storage with full-text search and configurable retention
5. **Event-driven notifications** — Celery + RabbitMQ for async task processing, decoupling event production from consumption
6. **Air-gapped first** — All dependencies pinned and bundled; no runtime external network calls; OCI-compliant containers

---

## Security Features

| Feature | Implementation |
|---------|---------------|
| Authentication | JWT access tokens (30 min) + refresh tokens (7 days) |
| Password Storage | bcrypt with cost factor 12 |
| Authorization | RBAC enforced on every API endpoint and UI route |
| Credential Encryption | AES-256-GCM with per-connector IV |
| Key Rotation | Admin-triggered with automatic rollback on failure |
| Rate Limiting | Redis sliding window (100 req/min per user) |
| Account Protection | Lockout after 5 failed attempts (15 min) |
| Audit Trail | Immutable append-only logs with PostgreSQL triggers |
| Input Validation | Server-side + client-side, structured error responses |
| CSRF Protection | Double-submit cookie for state-modifying endpoints |
| API Security | Payload size limits (10 MB), version headers, sanitized errors |

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -m 'feat: add my feature'`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

### Development Setup

```bash
# Backend
cd backend
pip install -e ".[dev]"
python -m pytest tests/unit/ -v

# Frontend
cd frontend
npm install
npm run dev
```

---

## License

This project is open-source and available under the [MIT License](LICENSE).

---

## Acknowledgments

Built as a Final Year Project demonstrating production-ready data infrastructure design and implementation for regulated industries.
