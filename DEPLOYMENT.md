# Production Deployment Manual & Operations Guide

This guide details the architecture, setup procedure, and operation protocols for deploying the **ForgeDeploy FastAPI** application to a production Virtual Private Server (VPS).

---

## 1. Architectural Overview

The application is deployed as an isolated, containerized multi-tier microservice architecture using **Docker Compose** and **Nginx** as a secure reverse proxy.

```mermaid
graph TD
    Client([Internet Client]) -->|HTTPS:443| Nginx[NGINX Reverse Proxy]
    
    subgraph Frontend Network (frontend-net)
        Nginx -->|Proxy Pass:8000| FastAPI[FastAPI Application]
    end

    subgraph Backend Network (backend-net)
        FastAPI -->|Postgres Protocol:5432| Postgres[(PostgreSQL DB)]
        FastAPI -->|Redis Protocol:6379| Redis[(Redis Cache)]
    end

    classDef network fill:#f9f,stroke:#333,stroke-width:2px;
    classDef service fill:#bbf,stroke:#333,stroke-width:2px;
    class Nginx,FastAPI,Postgres,Redis service;
```

### Network Isolation Security
* **`frontend-net`**: Connects Nginx and FastAPI. External traffic can only reach Nginx. Nginx forwards requests to the internal FastAPI service.
* **`backend-net`**: Connects FastAPI, PostgreSQL, and Redis. **Nginx is completely excluded from this network**, preventing direct database or cache layer exposure from the proxy level.

---

## 2. Server Prerequisites & VPS Preparation

Before initiating the deployment process, ensure the host target satisfies the following requirements:

### Target OS
* **Ubuntu Server 20.04 LTS / 22.04 LTS** (recommended)

### System Packages
Ensure Git, Docker, and Docker Compose are installed on the server:
```bash
# Update package indices
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh

# Install Docker Compose V2 (if not pre-packaged)
sudo apt install docker-compose-plugin -y

# Verify Installations
docker --version
docker compose version
```

### DNS Settings
Create DNS records with your registrar pointing to your VPS public IPv4 address:
* **A Record** `yourdomain.com` -> `VPS_PUBLIC_IP`
* **A Record** `www.yourdomain.com` -> `VPS_PUBLIC_IP` (optional)

---

## 3. Step-by-Step Production Bootstrapping

Follow these sequential instructions to deploy your application live.

### Step 3.1: Clone the Codebase on the VPS
Connect to your VPS via SSH and clone your project into `/home/deployuser/forgedeploy-fastapi` (or your preferred deployment directory matching the CI/CD settings):
```bash
mkdir -p /home/deployuser
cd /home/deployuser
git clone <YOUR_REPOSITORY_GIT_URL> forgedeploy-fastapi
cd forgedeploy-fastapi
```

### Step 3.2: Configure Environment Variables
Copy the production environment template and configure your production values:
```bash
cp .env.example .env
nano .env
```

> [!IMPORTANT]
> Change the following critical parameters in `.env` for production:
> * `ENVIRONMENT` = `production`
> * `DEBUG` = `false`
> * `SECRET_KEY` & `JWT_SECRET` = Generate strong 64-character hex keys (e.g., run `openssl rand -hex 32` to generate them).
> * `POSTGRES_PASSWORD` = Generate a strong random password (reused automatically to secure Redis).
> * `DOMAIN` = Set your active production domain (e.g., `api.yourdomain.com`).
> * `SSL_EMAIL` = Your administrator email (for Let's Encrypt expiration notifications).
> * `USE_SSL` = `true` (Enables automated Let's Encrypt challenge solving).

---

## 4. Bootstrapping NGINX & SSL Certificates

Nginx will fail to start if it is configured to use SSL certificates that do not exist yet. To solve this "chicken-and-egg" issue, we use a robust automated script `scripts/init-ssl.sh`.

```mermaid
sequenceDiagram
    participant Script as init-ssl.sh
    participant Docker as Docker Compose
    participant Nginx as Nginx Container
    participant Certbot as Certbot ACME Client
    participant LE as Let's Encrypt Authority

    Script->>Docker: Generate fallback Self-Signed Certificates
    Script->>Docker: Boot Nginx (using temporary self-signed certs)
    Script->>Certbot: Run Certbot Container (ACME HTTP Webroot challenge)
    Certbot->>LE: Solve challenge via Nginx (/.well-known/acme-challenge/)
    LE-->>Certbot: Issue production SSL Certificates
    Script->>Docker: Copy production certs to volume
    Script->>Nginx: Exec Nginx reload
    Note over Nginx: Production SSL is now active!
```

### Run the SSL Bootstrapper
Ensure the bootstrap script is executable, then run it:
```bash
chmod +x scripts/*.sh
./scripts/init-ssl.sh
```

**What this script does:**
1. Checks for a configured `.env` file containing `DOMAIN` and `SSL_EMAIL`.
2. Creates high-grade placeholder self-signed SSL certs inside the `nginx_prod_certs` Docker volume so Nginx can start successfully.
3. Launches the Nginx reverse proxy.
4. Spins up a temporary Certbot container to solve the Let's Encrypt ACME HTTP validation challenge via a shared webroot.
5. Upon successful challenge verification, overwrites the self-signed certificates with the actual Let's Encrypt keys.
6. Reloads Nginx gracefully to apply HTTPS and secure your API.

---

## 5. Automated CI/CD Deployment (GitHub Actions)

Your repository includes a professional GitHub Actions workflow (`.github/workflows/ci-cd.yml`) that automates linting, testing, and continuous deployments directly to your VPS.

### Required GitHub Secrets
To enable continuous delivery, navigate to your GitHub repository **Settings > Secrets and variables > Actions** and add the following secrets:

| Secret Name | Description | Example / Format |
| :--- | :--- | :--- |
| `VPS_HOST` | The public IP address or domain name of your VPS | `198.51.100.12` |
| `VPS_USER` | The user account executing docker commands on the VPS | `deployuser` |
| `SSH_PRIVATE_KEY` | The private SSH key authorized to connect to `VPS_USER` | `-----BEGIN OPENSSH PRIVATE KEY-----...` |
| `VPS_SSH_PORT` | The custom SSH port of your VPS (Defaults to `22` if not set) | `22` or `2222` |

### Deployment Workflow Steps
When you push code to the `main` branch:
1. **Validation**: Statically checks code syntax using **Ruff** and runs async integration tests via **Pytest**.
2. **Build & Push**: Compiles the FastAPI production Docker image and publishes it to the **GitHub Container Registry (GHCR)** using native layer caching for speed.
3. **VPS Deploy Execution**: Connects securely to your VPS via SSH, pulls new code changes, logs in to GHCR, and runs the zero-downtime container swap script (`./scripts/deploy.sh`).

---

## 6. High-Availability Zero-Downtime Swaps (Under the Hood)

The `./scripts/deploy.sh` script employs an automated zero-downtime deployment pattern:

```mermaid
stateDiagram-v2
    [*] --> Pull_Images: git push / CI-CD
    Pull_Images --> Fetch_Current_ID: Save active container ID as fallback
    Fetch_Current_ID --> Launch_New: Start new fastapi container
    
    state Health_Verification {
        [*] --> Poll_Endpoint
        Poll_Endpoint --> Verify_200: Temporary container runs curl internal network query
        Verify_200 --> Loop: Returns 000/500 (Sleep 5s, try up to 12x)
        Verify_200 --> Success_State: Returns 200
    }

    Launch_New --> Health_Verification
    
    Health_Verification --> Apply_Proxy: Healthy
    Apply_Proxy --> Reload_Nginx: Reload Nginx (sends new traffic to upgraded container)
    Reload_Nginx --> Prune_Old: Prune dangling images
    Prune_Old --> [*]: Complete

    Health_Verification --> Rollback_Seq: Unhealthy / Timeout
    Rollback_Seq --> Restart_Fallback: Re-boot previous stable container ID
    Restart_Fallback --> Alert_Operator: Exit 1 (Alert Operator)
    Alert_Operator --> [*]: Failed
```

---

## 7. Database Backups & Disaster Recovery

Your database architecture is secured using standard automated backup routines that compress archives on-the-fly and prevent credential exposure.

### Step 7.1: Automated Backups via Cron
The script `scripts/backup.sh` connects internally to the PostgreSQL container, runs a secure `pg_dump`, streams the output directly into a `gzip` file, and **automatically purges old backups older than 7 days**.

To automate this daily at 2:00 AM, register it in your VPS crontab:
```bash
# Open crontab editor
crontab -e
```
Add the following line to the end of the file:
```text
0 2 * * * /home/deployuser/forgedeploy-fastapi/scripts/backup.sh >> /home/deployuser/forgedeploy-fastapi/backups/backup.log 2>&1
```

### Step 7.2: Manual Backup
To trigger an immediate backup of your live database:
```bash
./scripts/backup.sh
```
This stores a compressed file under `./backups/db_backup_YYYYMMDD_HHMMSS.sql.gz`.

### Step 7.3: Database Restoration
To restore your database from a specific backup file:
```bash
./scripts/restore.sh ./backups/db_backup_20260527_150000.sql.gz
```

> [!WARNING]
> * Restoring a backup completely overwrites all current active data in your database.
> * The restoration script **automatically invalidates and purges all Redis cache entries** to prevent cache-database desynchronization.

---

## 8. Manual Deployment & Operations Cheatsheet

If you prefer to operate your infrastructure manually on the VPS without a CI/CD system, use the following command directives.

### Start the Infrastructure Stack
```bash
# Pull production images (if using registry)
docker compose pull

# Launch services in detached (background) mode
docker compose up -d
```

### Stop the Infrastructure Stack
```bash
# Tear down services but preserve DB and Volume storage
docker compose down

# Tear down services and completely destroy database volumes (CAUTION!)
docker compose down -v
```

### Service Health & Diagnostic Commands
```bash
# View active service statuses and port mappings
docker compose ps

# Read live aggregated logs
docker compose logs -f

# Read logs of a specific service
docker compose logs -f fastapi
docker compose logs -f nginx
docker compose logs -f postgres

# Run database shell manually
docker compose exec -it postgres psql -U appuser -d appdb
```

### Renew SSL Certificates Manually
The Let's Encrypt SSL certificates are valid for 90 days. While Certbot usually handles renewal automatically when run, you can manually force a dry run or execute a renewal request using:
```bash
docker run --rm \
    -v "nginx_prod_certs:/etc/letsencrypt" \
    -v "certbot_prod_webroot:/var/www/certbot" \
    certbot/certbot renew
```
After renewal, always reload Nginx:
```bash
docker compose exec nginx nginx -s reload
```
