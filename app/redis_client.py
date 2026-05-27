import logging
# pyrefly: ignore [missing-import]
import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger("app")


class RedisClientManager:
    def __init__(self):
        self.redis: aioredis.Redis | None = None

    async def initialize(self) -> None:
        """Initialize the Redis connection pool."""
        if not self.redis:
            logger.info("Initializing async Redis connection pool...")
            # We specify standard options for connection resilience:
            # retry_on_timeout: retry connecting if an initial connection times out
            # socket_keepalive: keep the connection alive via OS TCP signals
            self.redis = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5.0,
                retry_on_timeout=True,
            )
            # Verify connectivity immediately on startup
            await self.redis.ping()
            logger.info("Async Redis connection pool initialized successfully.")

    async def close(self) -> None:
        """Gracefully close the Redis connection pool."""
        if self.redis:
            logger.info("Closing Redis connection pool...")
            await self.redis.close()
            self.redis = None
            logger.info("Redis connection pool closed.")

    def get_client(self) -> aioredis.Redis:
        """Access the Redis client singleton."""
        if not self.redis:
            raise RuntimeError("RedisClientManager is not initialized! Call initialize() first.")
        return self.redis


# Singleton instance of the Redis client manager
redis_manager = RedisClientManager()
