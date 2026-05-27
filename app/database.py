import logging
from typing import AsyncGenerator
# pyrefly: ignore [missing-import]
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
# pyrefly: ignore [missing-import]
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

logger = logging.getLogger("app")

# Ensure SQLalchemy async engine is initialized with proper connection pool size & limits
# pool_size: The number of connections to keep open inside the connection pool
# max_overflow: The number of connections to allow beyond pool_size under peak loads
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,  # Set to True to log generated SQL statements (development only)
    pool_size=20,
    max_overflow=10,
    pool_timeout=30,
    pool_recycle=1800,  # Recycle connections after 30 minutes to prevent stale links
)

# Async session factory
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Keep attributes accessible after transaction commits
)


# Base class for all database tables
class Base(DeclarativeBase):
    pass


# Dependency injection provider for FastAPI endpoints
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            logger.error(f"Database session error occurred: {e}", exc_info=True)
            await session.rollback()
            raise
        finally:
            await session.close()
