# Air-Gapped Deployment Guide

This guide covers deploying the Cloud-Independent Data Platform in an air-gapped environment — a network with no connectivity to the public internet.

## Prerequisites

### Hardware Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 8 cores | 16 cores |
| RAM | 32 GB | 64 GB |
| Disk | 200 GB SSD | 500 GB SSD |
| Network | 1 Gbps internal | 10 Gbps internal |

### Software Requirements

- **Docker Engine** >= 24.0 with Docker Compose plugin v2.x
- **Operating System**: Linux (Ubuntu 22.04 LTS, RHEL 9, or Rocky Linux 9 recommended)
- **Filesystem**: ext4 or xfs with sufficient space for container images (~15 GB)
- **User permissions**: `root` or a user in the `docker` group

### Pre-Transfer Checklist

Before transferring artifacts to the air-gapped environment, ensure you have:

- [ ] All container image `.tar` archives (generated via `save-images.sh`)
- [ ] The platform source bundle or release archive
- [ ] This documentation
- [ ] The `.env.example` file for configuration reference

---

## Container Image Loading

All platform container images are distributed as OCI-compliant tar archives. These can be transferred to the air-gapped host via physical media (USB drive, DVD) or internal network file share.

### Step 1: Transfer Image Archives

Copy the `images/` directory containing all `.tar` files to the air-gapped host:

```bash
# Example: from USB mounted at /mnt/usb
cp -r /mnt/usb/cdp-images/ /opt/cdp/images/
```

### Step 2: Load Images into Docker

Use the provided script to load all images:

```bash
cd /opt/cdp/deploy/air-gapped
chmod +x load-images.sh
./load-images.sh /opt/cdp/images
```

This will load the following images into the local Docker daemon:

- `postgres:16.1-alpine`
- `clickhouse/clickhouse-server:24.1.5`
- `redis:7.2.4-alpine`
- `rabbitmq:3.13.0-management-alpine`
- `docker.elastic.co/elasticsearch/elasticsearch:8.13.0`
- `dagster/dagster-k8s:1.5.14`
- `prom/prometheus:v2.49.1`
- `grafana/grafana:10.3.1`
- `cdp-backend:latest` (platform backend)
- `cdp-frontend:latest` (platform frontend)

### Step 3: Verify Loaded Images

```bash
docker images | grep -E "postgres|clickhouse|redis|rabbitmq|elasticsearch|dagster|prometheus|grafana|cdp-"
```

---

## Initial Configuration

### Step 1: Create Environment File

Copy and edit the environment configuration:

```bash
cp .env.example .env
```

### Step 2: Configure Air-Gapped Mode

Set the following environment variables in `.env`:

```bash
# Enable air-gapped mode (disables REST API connectors, blocks outbound connections)
AIR_GAPPED_MODE=true

# Application settings
APP_ENV=production
APP_DEBUG=false

# Security — CHANGE THESE IN PRODUCTION
SECRET_KEY=<generate-a-random-64-char-string>
CREDENTIAL_ENCRYPTION_KEY=<generate-a-32-byte-hex-key>
CSRF_SECRET_KEY=<generate-a-random-secret>

# Database credentials — customize as needed
POSTGRES_USER=platform_user
POSTGRES_PASSWORD=<strong-password>
POSTGRES_DB=cloud_data_platform

# Redis
REDIS_PASSWORD=<strong-password>

# RabbitMQ
RABBITMQ_USER=platform_user
RABBITMQ_PASSWORD=<strong-password>

# Elasticsearch
ELASTICSEARCH_PASSWORD=<strong-password>

# ClickHouse
CLICKHOUSE_PASSWORD=<strong-password>
```

### Step 3: Generate Secrets (on a connected machine or offline)

```bash
# Generate SECRET_KEY
python3 -c "import secrets; print(secrets.token_hex(32))"

# Generate CREDENTIAL_ENCRYPTION_KEY (32 bytes = 64 hex chars)
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## Service Startup Sequence

Services must be started in the correct order to respect dependencies.

### Step 1: Start Infrastructure Services

```bash
docker compose up -d postgres redis rabbitmq clickhouse elasticsearch
```

Wait for health checks to pass:

```bash
docker compose ps
# Ensure all services show "(healthy)" status
```

### Step 2: Start Orchestration Services

```bash
docker compose up -d dagster-webserver dagster-daemon
```

### Step 3: Start Monitoring Stack

```bash
docker compose up -d prometheus grafana
```

### Step 4: Start Application Services

```bash
docker compose up -d backend frontend
```

### Full Stack (Single Command)

If you prefer starting everything at once (Docker Compose handles dependency ordering):

```bash
docker compose up -d
```

---

## Post-Deployment Verification

Use the provided verification script to confirm all services are healthy:

```bash
cd /opt/cdp/deploy/air-gapped
chmod +x verify-deployment.sh
./verify-deployment.sh
```

### Manual Verification Steps

1. **PostgreSQL**: `docker exec cdp-postgres pg_isready -U platform_user`
2. **Redis**: `docker exec cdp-redis redis-cli -a redis_password ping`
3. **RabbitMQ**: Visit `http://<host>:15672` (management UI)
4. **Elasticsearch**: `curl -u elastic:<password> http://localhost:9200/_cluster/health`
5. **Dagster**: Visit `http://<host>:3000` (Dagster webserver UI)
6. **Prometheus**: Visit `http://<host>:9090` (Prometheus UI)
7. **Grafana**: Visit `http://<host>:3001` (default: admin/grafana_password)
8. **Backend API**: `curl http://localhost:8000/api/v1/health`
9. **Frontend**: Visit `http://<host>:80`

### Verify Air-Gapped Mode

Confirm REST API source connectors are disabled:

```bash
curl -s http://localhost:8000/api/v1/connectors/types | python3 -m json.tool
# REST API source type should show as disabled with a message
```

---

## Offline Update Procedure

### Step 1: Prepare Update Artifacts (on a connected machine)

On a machine with internet access, pull the updated images and save them:

```bash
cd deploy/air-gapped
./save-images.sh /path/to/output/directory
```

Package the updated source code and images:

```bash
tar czf cdp-update-v<version>.tar.gz \
  /path/to/output/directory/*.tar \
  docker-compose.yml \
  deploy/ \
  backend/ \
  frontend/
```

### Step 2: Transfer to Air-Gapped Environment

Transfer `cdp-update-v<version>.tar.gz` via:
- USB drive / removable media
- Internal file share (if available within the isolated network)
- Optical media (for high-security environments)

### Step 3: Apply the Update

```bash
# Extract update archive
tar xzf cdp-update-v<version>.tar.gz -C /opt/cdp/

# Load new images
cd /opt/cdp/deploy/air-gapped
./load-images.sh /opt/cdp/images

# Apply database migrations
docker compose exec backend alembic upgrade head

# Restart services with new images
docker compose up -d --force-recreate

# Verify deployment
./verify-deployment.sh
```

### Rollback Procedure

If the update fails verification:

```bash
# Stop services
docker compose down

# Restore previous images
./load-images.sh /opt/cdp/images-backup

# Restore previous configuration
cp .env.backup .env

# Start with previous version
docker compose up -d

# Verify
./verify-deployment.sh
```

---

## Network Isolation (Firewall Rules)

In an air-gapped deployment, all outbound internet connections must be blocked. The platform is designed to operate without any runtime external dependencies.

### Recommended iptables Rules

```bash
# Block all outbound traffic to public networks
# Allow only internal/private network ranges
iptables -A OUTPUT -d 10.0.0.0/8 -j ACCEPT
iptables -A OUTPUT -d 172.16.0.0/12 -j ACCEPT
iptables -A OUTPUT -d 192.168.0.0/16 -j ACCEPT
iptables -A OUTPUT -d 127.0.0.0/8 -j ACCEPT
iptables -A OUTPUT -o lo -j ACCEPT

# Block everything else (outbound to public internet)
iptables -A OUTPUT -j DROP

# Log blocked attempts for audit purposes
iptables -I OUTPUT -j LOG --log-prefix "CDP-BLOCKED-OUTBOUND: " --log-level 4
```

### Docker Network Isolation

Restrict Docker containers from accessing external networks:

```bash
# In docker-compose.yml, use internal networks:
# networks:
#   cdp-internal:
#     internal: true
#
# Or via Docker daemon config (/etc/docker/daemon.json):
{
  "iptables": true,
  "icc": true,
  "dns": ["<internal-dns-ip>"]
}
```

### DNS Configuration

Since external DNS is unavailable:

```bash
# /etc/hosts or internal DNS entries for all services
127.0.0.1 localhost
<host-ip> cdp-postgres cdp-redis cdp-rabbitmq cdp-clickhouse cdp-elasticsearch
```

---

## Troubleshooting

### Images Not Loading

```bash
# Check available disk space
df -h

# Verify tar archive integrity
tar -tzf <image>.tar > /dev/null && echo "OK" || echo "CORRUPTED"
```

### Services Not Starting

```bash
# Check logs for a specific service
docker compose logs <service-name> --tail=50

# Check resource usage
docker stats --no-stream
```

### Database Migration Failures

```bash
# Check current migration state
docker compose exec backend alembic current

# View migration history
docker compose exec backend alembic history

# Downgrade if needed
docker compose exec backend alembic downgrade -1
```

---

## Security Considerations

1. **No telemetry**: The platform sends zero telemetry or analytics data externally
2. **No license checks**: No runtime license validation against external servers
3. **No update checks**: Automatic update checking is disabled; updates are applied manually
4. **Pinned dependencies**: All Python, npm, and system dependencies use exact pinned versions
5. **OCI-compliant images**: All container images follow OCI image specification for portability
6. **Audit logging**: All blocked outbound connection attempts are logged to the audit system
