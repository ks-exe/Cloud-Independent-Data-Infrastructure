#!/usr/bin/env bash
# =============================================================================
# save-images.sh — Export all platform container images as tar archives
# =============================================================================
# Usage: ./save-images.sh [output_directory]
#
# Pulls (if needed) and saves all required container images for air-gapped
# deployment. Output is a set of .tar files that can be transferred to the
# target environment and loaded with load-images.sh.
#
# Requirements:
#   - Docker Engine >= 24.0
#   - Internet connectivity (to pull images)
#   - ~15 GB free disk space for image archives
# =============================================================================

set -euo pipefail

# Default output directory
OUTPUT_DIR="${1:-./images}"

# Platform container images with pinned versions
IMAGES=(
    "postgres:16.1-alpine"
    "clickhouse/clickhouse-server:24.1.5"
    "redis:7.2.4-alpine"
    "rabbitmq:3.13.0-management-alpine"
    "docker.elastic.co/elasticsearch/elasticsearch:8.13.0"
    "dagster/dagster-k8s:1.5.14"
    "prom/prometheus:v2.49.1"
    "grafana/grafana:10.3.1"
)

# Application images (built locally)
APP_IMAGES=(
    "cdp-backend:latest"
    "cdp-frontend:latest"
)

# Color output helpers
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    if ! command -v docker &> /dev/null; then
        log_error "Docker is not installed or not in PATH"
        exit 1
    fi

    if ! docker info &> /dev/null; then
        log_error "Docker daemon is not running or current user lacks permissions"
        exit 1
    fi
}

# Convert image name to a safe filename
image_to_filename() {
    local image="$1"
    echo "$image" | sed 's|/|_|g' | sed 's|:|_|g'
}

# Main execution
main() {
    check_prerequisites

    log_info "Saving container images to: ${OUTPUT_DIR}"
    mkdir -p "${OUTPUT_DIR}"

    local total=${#IMAGES[@]}
    local count=0
    local failed=0

    # Pull and save infrastructure images
    log_info "=== Saving infrastructure images (${total} total) ==="
    for image in "${IMAGES[@]}"; do
        count=$((count + 1))
        local filename
        filename=$(image_to_filename "$image")
        local output_path="${OUTPUT_DIR}/${filename}.tar"

        echo ""
        log_info "[${count}/${total}] Processing: ${image}"

        # Pull the image if not already present
        if ! docker image inspect "$image" &> /dev/null; then
            log_info "  Pulling image..."
            if ! docker pull "$image"; then
                log_error "  Failed to pull ${image}"
                failed=$((failed + 1))
                continue
            fi
        else
            log_info "  Image already present locally"
        fi

        # Save to tar archive
        log_info "  Saving to ${output_path}..."
        if docker save -o "$output_path" "$image"; then
            local size
            size=$(du -h "$output_path" | cut -f1)
            log_info "  Saved successfully (${size})"
        else
            log_error "  Failed to save ${image}"
            failed=$((failed + 1))
        fi
    done

    # Save application images (must be built first)
    echo ""
    log_info "=== Saving application images ==="
    for image in "${APP_IMAGES[@]}"; do
        local filename
        filename=$(image_to_filename "$image")
        local output_path="${OUTPUT_DIR}/${filename}.tar"

        log_info "Processing: ${image}"

        if ! docker image inspect "$image" &> /dev/null; then
            log_warn "  Image ${image} not found locally. Build it first with 'docker compose build'"
            failed=$((failed + 1))
            continue
        fi

        log_info "  Saving to ${output_path}..."
        if docker save -o "$output_path" "$image"; then
            local size
            size=$(du -h "$output_path" | cut -f1)
            log_info "  Saved successfully (${size})"
        else
            log_error "  Failed to save ${image}"
            failed=$((failed + 1))
        fi
    done

    # Summary
    echo ""
    log_info "========================================="
    log_info "Image export complete!"
    log_info "  Output directory: ${OUTPUT_DIR}"
    log_info "  Total images: $((total + ${#APP_IMAGES[@]}))"
    log_info "  Failed: ${failed}"

    local total_size
    total_size=$(du -sh "${OUTPUT_DIR}" | cut -f1)
    log_info "  Total archive size: ${total_size}"
    log_info "========================================="

    if [ "$failed" -gt 0 ]; then
        log_warn "Some images failed to save. Check the output above for details."
        exit 1
    fi

    log_info "Transfer the '${OUTPUT_DIR}' directory to the air-gapped environment."
    log_info "Then run: ./load-images.sh ${OUTPUT_DIR}"
}

main "$@"
