import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine, Base
from app.redis_client import redis_manager
from app.middleware.logging import setup_structured_logging, StructuredLoggingMiddleware
from app.routers import health, items

# Configure root logger with custom JSONFormatter
setup_structured_logging()
logger = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Manages application lifecycle events (Startup and Shutdown).
    Ensures persistent database and cache connection pools are fully functional.
    """
    logger.info("Booting FastAPI application...")
    
    # 1. Initialize Redis connection pool
    try:
        await redis_manager.initialize()
    except Exception as e:
        logger.critical(f"Failed to initialize Redis pool during startup: {e}", exc_info=True)
        raise e

    # 2. Bootstrap database tables (if running in standard container dev/test or production deployment)
    try:
        logger.info("Creating database tables if not existing...")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables verified.")
    except Exception as e:
        logger.critical(f"Database connection and bootstrapping failed: {e}", exc_info=True)
        raise e

    logger.info("FastAPI Application fully operational.")
    
    yield  # Application serves requests here...
    
    # 3. Graceful shutdown sequences
    logger.info("Shutting down FastAPI application...")
    await redis_manager.close()
    
    # Dispose SQLAlchemy async database engine
    logger.info("Disposing database connection pool...")
    await engine.dispose()
    logger.info("Database connection pool disposed. Shutdown complete.")


# Initialize FastAPI Instance
app = FastAPI(
    title=settings.PROJECT_NAME,
    version="1.0.0",
    description="Production-grade FastAPI, Docker, and NGINX Backend Infrastructure",
    lifespan=lifespan,
    docs_url="/docs" if settings.ENVIRONMENT != "production" else None,
    redoc_url="/redoc" if settings.ENVIRONMENT != "production" else None,
)

# 1. Mount Security Headers / CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[f"https://{settings.DOMAIN}"] if settings.ENVIRONMENT == "production" else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# 2. Mount Custom Structured Request Logging Middleware
app.add_middleware(StructuredLoggingMiddleware)

# 3. Register API Routers
app.include_router(health.router)
app.include_router(items.router, prefix="/api/v1")


@app.get("/")
async def root():
    return {
        "message": "Welcome to ForgeDeploy API Portal.",
        "status": "online",
        "documentation": "/docs" if settings.ENVIRONMENT != "production" else "disabled in production"
    }
