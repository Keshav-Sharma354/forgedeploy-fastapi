#!/bin/bash
# ==============================================================================
# SSL Bootstrap & Let's Encrypt Certbot Initializer
# ==============================================================================
# This script handles the "chicken-and-egg" issue of NGINX failing to start
# because the production SSL certificates do not exist yet.
#
# Process:
# 1. Prompts for Domain and Admin Email.
# 2. Creates mock self-signed fallback certs in the 'nginx_certs' volume path.
# 3. Bootstraps NGINX HTTP only service to respond to Let's Encrypt challenges.
# 4. Solves Let's Encrypt HTTP challenge.
# 5. Overwrites self-signed certs with actual secure production certs.
# 6. Restarts NGINX to activate production SSL.

set -euo pipefail

# Standard log print styling
log() {
    echo -e "\e[1;32m[SSL-INIT]\e[0m $1"
}

warn() {
    echo -e "\e[1;33m[WARNING]\e[0m $1"
}

error() {
    echo -e "\e[1;31m[ERROR]\e[0m $1"
}

# 1. Setup absolute script paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PARENT_DIR"

# Source environment variables if .env exists
if [ -f .env ]; then
    log "Sourcing .env configurations..."
    export $(grep -v '^#' .env | xargs)
else
    error ".env file not found in parent directory. Please copy .env.example to .env first."
    exit 1
fi

DOMAIN="${DOMAIN:-}"
SSL_EMAIL="${SSL_EMAIL:-}"
USE_SSL="${USE_SSL:-false}"

if [ -z "$DOMAIN" ] || [ -z "$SSL_EMAIL" ]; then
    error "DOMAIN and SSL_EMAIL must be specified inside .env."
    exit 1
fi

# If SSL is explicitly bypassed for local/dev, let the user know
if [ "$USE_SSL" != "true" ]; then
    warn "USE_SSL is set to false in .env. Skipping SSL provisioning."
    log "Generating local self-signed certificate for local HTTPS testing..."
fi

# Define directories matching Named Docker Volume maps
# In a local VPS environment, Docker named volumes are located at /var/lib/docker/volumes/...
# To be platform-independent and secure, we'll create a local folder and copy the certs into NGINX
# using a temporary container, or use docker compose run to mount and write them!
# This is an incredibly elegant solution that requires NO host path permissions:
# We run a temporary Alpine container with compose volume mounts to write the certs directly!

log "Initializing certificate volume with placeholder self-signed SSL certs for domain: $DOMAIN"

# Generate self-signed certificate inside the nginx_certs volume using a lightweight docker tool
docker compose run --rm --entrypoint "" nginx sh -c "
    mkdir -p /etc/nginx/ssl
    if [ ! -f /etc/nginx/ssl/fullchain.pem ] || [ ! -f /etc/nginx/ssl/privkey.pem ]; then
        echo 'Generating self-signed SSL certificate fallback...'
        apk add --no-cache openssl
        openssl req -x509 -nodes -days 365 -newkey rsa:2048 \\
            -keyout /etc/nginx/ssl/privkey.pem \\
            -out /etc/nginx/ssl/fullchain.pem \\
            -subj '/CN=localhost'
        echo 'Fallback self-signed cert successfully written.'
    else
        echo 'Existing certificate assets found. Skipping self-signed placeholder creation.'
    fi
"

# Start the NGINX container so it can serve the Certbot ACME HTTP validation challenge
log "Booting NGINX reverse proxy container..."
docker compose up -d nginx

if [ "$USE_SSL" != "true" ]; then
    log "Self-signed certificate is operational. NGINX booted successfully without Let's Encrypt."
    log "Access local environment via: https://localhost"
    exit 0
fi

# Provisioning real production SSL Certificates via Certbot
log "Checking if production Let's Encrypt certificates exist..."
# Run a dry check to see if we've already done Let's Encrypt
CERT_EXISTS=$(docker compose run --rm --entrypoint "" nginx sh -c "
    if [ -s /etc/nginx/ssl/fullchain.pem ] && grep -q 'Let\'s Encrypt' /etc/nginx/ssl/fullchain.pem; then
        echo 'true'
    else
        echo 'false'
    fi
")

if [ "$CERT_EXISTS" == "true" ]; then
    log "Production Let's Encrypt certificates are already active! Skipping renewal request."
    exit 0
fi

log "Initiating Certbot validation with domain: $DOMAIN and email: $SSL_EMAIL..."

# We execute Certbot container mounting the shared webroot and certs volumes
docker run --rm \
    -v "nginx_prod_certs:/etc/letsencrypt" \
    -v "certbot_prod_webroot:/var/www/certbot" \
    certbot/certbot certonly \
    --webroot \
    --webroot-path=/var/www/certbot \
    --email "$SSL_EMAIL" \
    --agree-tos \
    --no-eff-email \
    -d "$DOMAIN" \
    --non-interactive \
    --keep-until-expiring

log "Copying Let's Encrypt certificates to production volume..."
# We copy the keys from the Certbot live folder structure into the root /etc/nginx/ssl directory
docker compose run --rm --entrypoint "" nginx sh -c "
    if [ -f /etc/letsencrypt/live/$DOMAIN/fullchain.pem ]; then
        cp /etc/letsencrypt/live/$DOMAIN/fullchain.pem /etc/nginx/ssl/fullchain.pem
        cp /etc/letsencrypt/live/$DOMAIN/privkey.pem /etc/nginx/ssl/privkey.pem
        echo 'Successfully linked Certbot Let\'s Encrypt keys to production volume.'
    else
        echo 'ERROR: Certbot failed to generate certificates. Check logs above.'
        exit 1
    fi
"

log "Reloading NGINX to apply secure production SSL certificates..."
docker compose exec nginx nginx -s reload

log "======================================================================"
log "SUCCESS: Production SSL certificates active via Let's Encrypt!"
log "FastAPI app is now secured at: https://$DOMAIN"
log "======================================================================"
