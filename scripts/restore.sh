#!/bin/bash
# ==============================================================================
# PostgreSQL Database Restoration Script
# ==============================================================================
# Safely streams a gzipped or raw SQL backup archive directly back into the
# active PostgreSQL Docker database container.
#
# Usage:
#   ./scripts/restore.sh <path_to_backup_file.sql.gz>

set -euo pipefail

log() {
    echo -e "\e[1;32m[RESTORE]\e[0m $1"
}

error() {
    echo -e "\e[1;31m[ERROR]\e[0m $1"
}

# 1. Setup paths and check arguments
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PARENT_DIR"

if [ $# -ne 1 ]; then
    error "Usage: $0 <path_to_backup_file.sql.gz>"
    exit 1
fi

BACKUP_PATH="$1"

if [ ! -f "$BACKUP_PATH" ]; then
    error "Backup file not found at path: $BACKUP_PATH"
    exit 1
fi

# 2. Source database credentials
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
else
    error ".env config file not found. Ensure it is placed in the project root."
    exit 1
fi

# 3. Check if Postgres container is online
if ! docker compose ps postgres | grep -q "Up"; then
    error "Postgres database container is not running! Start the stack first."
    exit 1
fi

# 4. Prompt for safety confirmation
echo -e "\e[1;33m[WARNING] This action will OVERWRITE all data in database: '${POSTGRES_DB}'!\e[0m"
read -p "Are you absolutely sure you want to proceed? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    log "Restoration aborted by user."
    exit 0
fi

log "Initiating database restoration from: $BACKUP_PATH..."

# 5. Determine if compression is gzip or raw sql, then stream into Postgres psql client
if [[ "$BACKUP_PATH" =~ \.gz$ ]]; then
    # Gzipped SQL streaming
    if gunzip -c "$BACKUP_PATH" | docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"; then
        log "Restoration of compressed backup file successful!"
    else
        error "Compressed database restoration failed!"
        exit 1
    fi
else
    # Raw SQL streaming
    if docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" < "$BACKUP_PATH"; then
        log "Restoration of raw SQL file successful!"
    else
        error "Raw database restoration failed!"
        exit 1
    fi
fi

# 6. Post-restoration cache clearance
log "Database restored. Invalidating all Redis caches to ensure no stale data lies in client..."
if docker compose ps redis | grep -q "Up"; then
    docker compose exec -T redis redis-cli -a "$POSTGRES_PASSWORD" flushall || warn "Failed to execute Redis cache flushall."
    log "Redis cache successfully invalidated."
fi

log "System successfully recovered and verified."
