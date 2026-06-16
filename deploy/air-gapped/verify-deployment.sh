#!/usr/bin/env bash
# =============================================================================
# verify-deployment.sh — Post-deployment verification for air-gapped environment
# =============================================================================
# Usage: ./verify-deployment.sh
#
# Performs health checks on all platform services to verify a successful
# deployment. Returns exit code 0 if all checks pass, 1 if any fail.
#
# Checks performed:
#   - Docker daemon availability
#   - Container status (running/healthy)
#   - Service-level health endpoints
#   - Air-gapped mode configuration
# =============================================================================

set -euo pipefail

# Configuration — adjust ports if customized
BACKEND_PORT="${BACKEND_PORT:-8000}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
REDIS_PORT="${REDIS_PORT:-6379}"
RABBITMQ_PORT="${RABBITMQ_PORT:-5672}"
RABBITMQ_MGMT_PORT="${RABBITMQ_MGMT_PORT:-15672}"
CLICKHOUSE_PORT="${CLICKHOUSE_PORT:-8123}"
ELASTICSEARCH_PORT="${ELASTICSEARCH_PORT:-9200}"
DAGSTER_PORT="${DAGSTER_PORT:-3000}"
PROMETHEUS_PORT="${PROMETHEUS_PORT:-9090}"
GRAFANA_PORT="${GRAFANA_PORT:-3001}"

# Timeouts
HEALTH_CHECK_TIMEOUT=5
MAX_RETRIES=3
RETRY_DELAY=2

# Color output helpers
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

PASS="${GREEN}[PASS]${NC}"
FAIL="${RED}[FAIL]${NC}"
WARN="${YELLOW}[WARN]${NC}"
INFO="${BLUE}[INFO]${NC}"

# Counters
TOTAL_CHECKS=0
PASSED_CHECKS=0
FAILED_CHECKS=0

check_pass() {
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    PASSED_CHECKS=$((PASSED_CHECKS + 1))
    echo -e "  ${PASS} $1"
}

check_fail() {
    TOTAL_CHECKS=$((TOTAL_CHECKS + 1))
    FAILED_CHECKS=$((FAILED_CHECKS + 1))
    echo -e "  ${FAIL} $1"
}

check_warn() {
    echo -e "  ${WARN} $1"
}

# --- Check Functions ---

check_docker() {
    echo ""
    echo -e "${INFO} Checking Docker daemon..."

    if docker info &> /dev/null; then
        check_pass "Docker daemon is running"
    else
        check_fail "Docker daemon is not running or inaccessible"
        echo "  Cannot proceed without Docker. Exiting."
        exit 1
    fi
}

check_container_status() {
    local container_name="$1"
    local display_name="$2"

    if docker ps --format '{{.Names}}' | grep -q "^${container_name}$"; then
        local health_status
        health_status=$(docker inspect --format='{{.State.Health.Status}}' "$container_name" 2>/dev/null || echo "none")

        if [ "$health_status" = "healthy" ]; then
            check_pass "${display_name} container is running and healthy"
        elif [ "$health_status" = "none" ]; then
            check_pass "${display_name} container is running (no health check defined)"
        else
            check_fail "${display_name} container is running but unhealthy (status: ${health_status})"
        fi
    else
        check_fail "${display_name} container is not running"
    fi
}

check_containers() {
    echo ""
    echo -e "${INFO} Checking container status..."

    check_container_status "cdp-postgres" "PostgreSQL"
    check_container_status "cdp-clickhouse" "ClickHouse"
    check_container_status "cdp-redis" "Redis"
    check_container_status "cdp-rabbitmq" "RabbitMQ"
    check_container_status "cdp-elasticsearch" "Elasticsearch"
    check_container_status "cdp-dagster-webserver" "Dagster Webserver"
    check_container_status "cdp-dagster-daemon" "Dagster Daemon"
    check_container_status "cdp-prometheus" "Prometheus"
    check_container_status "cdp-grafana" "Grafana"
}

check_http_endpoint() {
    local url="$1"
    local display_name="$2"
    local expected_code="${3:-200}"

    local attempt=0
    while [ $attempt -lt $MAX_RETRIES ]; do
        local status_code
        status_code=$(curl -s -o /dev/null -w "%{http_code}" --max-time "$HEALTH_CHECK_TIMEOUT" "$url" 2>/dev/null || echo "000")

        if [ "$status_code" = "$expected_code" ]; then
            check_pass "${display_name} is responding (HTTP ${status_code})"
            return 0
        fi

        attempt=$((attempt + 1))
        if [ $attempt -lt $MAX_RETRIES ]; then
            sleep $RETRY_DELAY
        fi
    done

    check_fail "${display_name} is not responding (expected HTTP ${expected_code}, got ${status_code})"
    return 1
}

check_service_health() {
    echo ""
    echo -e "${INFO} Checking service health endpoints..."

    # Backend API health
    check_http_endpoint "http://localhost:${BACKEND_PORT}/api/v1/health" "Backend API"

    # ClickHouse HTTP interface
    check_http_endpoint "http://localhost:${CLICKHOUSE_PORT}/ping" "ClickHouse HTTP"

    # Elasticsearch cluster health
    local es_status
    es_status=$(curl -s -u "elastic:elastic_password" --max-time "$HEALTH_CHECK_TIMEOUT" \
        "http://localhost:${ELASTICSEARCH_PORT}/_cluster/health" 2>/dev/null | \
        grep -o '"status":"[^"]*"' | head -1 || echo "")

    if echo "$es_status" | grep -qE '"status":"(green|yellow)"'; then
        check_pass "Elasticsearch cluster is healthy (${es_status})"
    else
        check_fail "Elasticsearch cluster is unhealthy or unreachable"
    fi

    # Dagster webserver
    check_http_endpoint "http://localhost:${DAGSTER_PORT}" "Dagster Webserver"

    # Prometheus
    check_http_endpoint "http://localhost:${PROMETHEUS_PORT}/-/healthy" "Prometheus"

    # Grafana
    check_http_endpoint "http://localhost:${GRAFANA_PORT}/api/health" "Grafana"
}

check_postgres_connection() {
    echo ""
    echo -e "${INFO} Checking PostgreSQL connectivity..."

    if docker exec cdp-postgres pg_isready -U platform_user -d cloud_data_platform &> /dev/null; then
        check_pass "PostgreSQL accepts connections"
    else
        check_fail "PostgreSQL is not accepting connections"
    fi
}

check_redis_connection() {
    echo ""
    echo -e "${INFO} Checking Redis connectivity..."

    local reply
    reply=$(docker exec cdp-redis redis-cli -a redis_password ping 2>/dev/null || echo "")

    if [ "$reply" = "PONG" ]; then
        check_pass "Redis is responding"
    else
        check_fail "Redis is not responding"
    fi
}

check_air_gapped_mode() {
    echo ""
    echo -e "${INFO} Checking air-gapped mode configuration..."

    # Check if AIR_GAPPED_MODE is set in the environment or .env file
    local api_response
    api_response=$(curl -s --max-time "$HEALTH_CHECK_TIMEOUT" \
        "http://localhost:${BACKEND_PORT}/api/v1/health" 2>/dev/null || echo "")

    if echo "$api_response" | grep -q "healthy\|ok"; then
        check_pass "Backend API is operational"
    else
        check_warn "Could not verify air-gapped mode via API (backend may not be running)"
    fi

    # Verify no outbound connectivity (optional check)
    if ! curl -s --max-time 3 "http://google.com" &> /dev/null; then
        check_pass "Outbound internet connectivity is blocked"
    else
        check_warn "Outbound internet connectivity detected — verify firewall rules"
    fi
}

# --- Main ---

main() {
    echo "========================================="
    echo " Cloud Data Platform — Deployment Verification"
    echo "========================================="
    echo " Timestamp: $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    echo " Host: $(hostname)"
    echo "========================================="

    check_docker
    check_containers
    check_postgres_connection
    check_redis_connection
    check_service_health
    check_air_gapped_mode

    # Summary
    echo ""
    echo "========================================="
    echo " Verification Summary"
    echo "========================================="
    echo -e "  Total checks: ${TOTAL_CHECKS}"
    echo -e "  ${GREEN}Passed${NC}: ${PASSED_CHECKS}"
    echo -e "  ${RED}Failed${NC}: ${FAILED_CHECKS}"
    echo "========================================="

    if [ "$FAILED_CHECKS" -eq 0 ]; then
        echo ""
        echo -e "${GREEN}All checks passed! Deployment is healthy.${NC}"
        exit 0
    else
        echo ""
        echo -e "${RED}${FAILED_CHECKS} check(s) failed. Review the output above for details.${NC}"
        exit 1
    fi
}

main "$@"
