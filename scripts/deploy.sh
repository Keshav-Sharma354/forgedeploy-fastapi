#!/bin/bash
# ==============================================================================
# VPS Minimal Downtime Deployment & Rollback Script
# ==============================================================================
# Handles pulling production images, executing container swapping, executing
# post-deployment health verification, and triggering rollbacks on failure.

set -euo pipefail

log() {
    echo -e "\e[1;32m[DEPLOY]\e[0m $1"
}

error() {
    echo -e "\e[1;31m[ERROR]\e[0m $1"
}

warn() {
    echo -e "\e[1;33m[WARNING]\e[0m $1"
}

# 1. Setup paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PARENT_DIR"

log "Starting deployment sequence..."

# 2. Check for required environmental configurations
if [ ! -f .env ]; then
    error "Production environment configuration (.env) missing in root directory!"
    exit 1
fi

export $(grep -v '^#' .env | xargs)

# 3. Pull latest docker images from registry (e.g. Docker Hub or GHCR)
log "Pulling latest docker container images..."
docker compose pull fastapi postgres redis nginx

# 4. Save current operational container ID as fallback tag
PREVIOUS_CONTAINER_ID=$(docker compose ps -q fastapi || echo "")

log "Starting container upgrade swap..."
# Launch new fastapi instance. --no-deps prevents restarting Postgres and Redis (zero DB disruption!)
docker compose up -d --no-deps fastapi

# 5. Monitor and verify new container healthcheck status
log "Verifying healthcheck of the new application release..."
MAX_ATTEMPTS=12
ATTEMPT=1
HEALTHY=false

# Fetch current port mapping or target internally
API_URL="http://localhost:8000/health" # Direct docker mapping bypass or internal query

# We'll run health check queries inside the Docker network structure using a temporary container, 
# ensuring that even if FastAPI is not bound to a host port directly, we can verify its health!
# This is an incredibly elegant and robust way to check internal docker network health.
while [ $ATTEMPT -le $MAX_ATTEMPTS ]; do
    log "Polling FastAPI health endpoint (Attempt $ATTEMPT/$MAX_ATTEMPTS)..."
    
    # Run container tool to check internal URL status
    STATUS_CODE=$(docker compose run --rm --network forgedeploy-fastapi_frontend-net --entrypoint "" nginx sh -c "
        apk add --no-cache curl >/dev/null 2>&1
        curl -s -o /dev/null -w '%{http_code}' http://fastapi:8000/health || echo '000'
    " || echo "000")
    
    # Clean output whitespace
    STATUS_CODE=$(echo "$STATUS_CODE" | tr -d '[:space:]')
    
    if [ "$STATUS_CODE" = "200" ]; then
        HEALTHY=true
        break
    fi
    
    ATTEMPT=$((ATTEMPT + 1))
    sleep 5
done

# 6. Success or Rollback execution
if [ "$HEALTHY" = true ]; then
    log "======================================================================"
    log "SUCCESS: New deployment version is verified healthy."
    log "Reloading NGINX reverse proxy proxy bindings to prune stale links..."
    docker compose exec -T nginx nginx -s reload
    log "Deployment cycle complete!"
    log "======================================================================"
else
    error "FastAPI application failed health check verification (returned status: $STATUS_CODE)!"
    warn "Initiating automated rollback sequence..."
    
    if [ -n "$PREVIOUS_CONTAINER_ID" ]; then
        # Re-start previous container if still present
        warn "Recovering previous stable container: $PREVIOUS_CONTAINER_ID..."
        docker start "$PREVIOUS_CONTAINER_ID"
        log "Rollback recovery execution complete. Please inspect docker application logs."
    else
        error "No fallback container available to recover! Immediate operator manual support required!"
    fi
    exit 1
fi
