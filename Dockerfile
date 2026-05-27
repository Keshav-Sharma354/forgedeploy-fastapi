# ==============================================================================
# STAGE 1: Builder (Dependency Compiler)
# ==============================================================================
# Use a full Python image to compile dependencies and wheels safely.
FROM python:3.11-slim AS builder

# Prevent python from writing pyc files to disk and enable stdout/stderr buffering
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /build

# Install system dependencies needed for compiling certain python packages (e.g. pg_config, gcc)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Create and activate virtual environment to isolate dependencies cleanly
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install python dependencies. Layer caching ensures this stage runs only when requirements.txt changes.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# ==============================================================================
# STAGE 2: Runner (Minimal Production Runtime)
# ==============================================================================
# Use the highly secure, lightweight slim image for the actual runtime
FROM python:3.11-slim AS runner

# Environment optimizations:
# 1. Force python logs to stream directly to stdout/stderr without buffering (essential for Docker logs)
# 2. Prevent writing .pyc files to minimize container filesystem modifications
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    PORT=8000

WORKDIR /app

# Install runtime dependencies (e.g. libpq for Postgres integration)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy the isolated, pre-compiled virtual environment from builder stage.
# This keeps compiler utilities (gcc, make) and build cache out of the production image!
COPY --from=builder /opt/venv /opt/venv

# Copy only the application source code
COPY app/ /app/app/

# Create a custom non-root system user and group for running the server.
# This is a critical security hardening step: if the app is compromised, 
# the attacker only obtains restricted permissions, preventing container breakout.
RUN groupadd -g 10001 webgroup && \
    useradd -r -u 10001 -g webgroup webuser && \
    chown -R webuser:webgroup /app

# Switch context to the non-root user
USER webuser

# Expose the API port
EXPOSE 8000

# Native container-level healthcheck instruction.
# Runs every 30 seconds. Checks if FastAPI server responds with status 200/OK.
# Using Python's built-in urllib.request is highly secure, fast, and removes the need 
# to install curl or wget inside the final slim container.
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)"]

# Production startup command using Uvicorn.
# - Running with 4 workers or scaling via compose is recommended.
# - Bound to 0.0.0.0 so Docker can map and reverse proxy traffic.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
