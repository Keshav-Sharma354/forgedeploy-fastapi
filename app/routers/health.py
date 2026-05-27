import logging
import time
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from app.database import get_db
from app.redis_client import redis_manager

logger = logging.getLogger("app")
router = APIRouter()


@router.get(
    "/health",
    status_code=status.HTTP_200_OK,
    summary="Perform a deep system health check",
    response_description="A JSON object detailing statuses of connected dependencies"
)
async def health_check(db: AsyncSession = Depends(get_db)):
    """
    Evaluates backend container operational readiness.
    Checks connections to:
    - **PostgreSQL**: Performs a test query (`SELECT 1`)
    - **Redis**: Asserts a cache Ping response
    """
    health_status = {
        "status": "healthy",
        "timestamp": time.time(),
        "services": {
            "api": "healthy"
        }
    }
    
    # 1. Verify PostgreSQL Database connection
    try:
        start_time = time.perf_counter()
        await db.execute(text("SELECT 1"))
        db_duration = (time.perf_counter() - start_time) * 1000.0
        health_status["services"]["database"] = {
            "status": "healthy",
            "latency_ms": round(db_duration, 2)
        }
    except Exception as e:
        logger.error(f"Database healthcheck failure: {e}", exc_info=True)
        health_status["status"] = "unhealthy"
        health_status["services"]["database"] = {
            "status": "unhealthy",
            "error": str(e)
        }

    # 2. Verify Redis cache connection
    try:
        redis_client = redis_manager.get_client()
        start_time = time.perf_counter()
        await redis_client.ping()
        redis_duration = (time.perf_counter() - start_time) * 1000.0
        health_status["services"]["redis"] = {
            "status": "healthy",
            "latency_ms": round(redis_duration, 2)
        }
    except Exception as e:
        logger.error(f"Redis healthcheck failure: {e}", exc_info=True)
        health_status["status"] = "unhealthy"
        health_status["services"]["redis"] = {
            "status": "unhealthy",
            "error": str(e)
        }

    # If any underlying service failed, raise a HTTP 503
    if health_status["status"] == "unhealthy":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=health_status
        )
        
    return health_status
