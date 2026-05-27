#!/bin/bash
# ==============================================================================
# Automated PostgreSQL Backup Script (Cron-Compatible)
# ==============================================================================
# Performs structured pg_dump backups from the running Postgres docker container,
# compresses the output file into gzip format, and purges archives older
# than the specified retention window (default: 7 days).

set -euo pipefail

# Configuration parameters
BACKUP_DIR="backups"
RETENTION_DAYS=7
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/db_backup_${TIMESTAMP}.sql.gz"

log() {
    echo -e "\e[1;32m[BACKUP]\e[0m $1"
}

error() {
    echo -e "\e[1;31m[ERROR]\e[0m $1"
}

# 1. Setup absolute paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PARENT_DIR"

# 2. Source database credentials from environmental variables
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
else
    error ".env config file not found. Ensure it is placed in the project root."
    exit 1
fi

# Ensure backup destination folder exists locally
mkdir -p "$BACKUP_DIR"

log "Starting database backup for database: $POSTGRES_DB..."

# 3. Check if Postgres container is running
if ! docker compose ps postgres | grep -q "Up"; then
    error "Postgres container is not currently running! Cannot proceed with backup."
    exit 1
fi

# 4. Stream database backup directly from docker container and pipe to gzip compressor
# Saves disk space by compressing on-the-fly and prevents raw credential exposure in command logs.
if docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > "$BACKUP_FILE"; then
    log "Backup completed successfully!"
    log "Backup stored at: $BACKUP_FILE"
    log "Backup size: $(du -sh "$BACKUP_FILE" | cut -f1)"
else
    error "Database pg_dump stream failed!"
    # Remove half-written files on failure to maintain backup integrity
    rm -f "$BACKUP_FILE"
    exit 1
fi

# 5. Clean up old backups based on RETENTION_DAYS
log "Pruning database backups older than $RETENTION_DAYS days..."
find "$BACKUP_DIR" -name "db_backup_*.sql.gz" -type f -mtime +"$RETENTION_DAYS" -exec rm -v {} \;
log "Pruning step finished."
