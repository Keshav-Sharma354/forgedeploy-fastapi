import json
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import Column, Integer, String, Text, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import Base, get_db
from app.redis_client import redis_manager

logger = logging.getLogger("app")
router = APIRouter(prefix="/items", tags=["items"])


# ==============================================================================
# Database Model
# ==============================================================================
class Item(Base):
    __tablename__ = "items"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100), nullable=False, index=True)
    description = Column(Text, nullable=True)


# ==============================================================================
# Pydantic Schemas
# ==============================================================================
class ItemBase(BaseModel):
    title: str = Field(..., max_length=100, examples=["Sample Production Item"])
    description: str | None = Field(None, examples=["A description of the production-ready component."])


class ItemCreate(ItemBase):
    pass


class ItemResponse(ItemBase):
    id: int

    class Config:
        from_attributes = True


# ==============================================================================
# API Endpoints with Caching
# ==============================================================================
@router.post("/", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(item_in: ItemCreate, db: AsyncSession = Depends(get_db)):
    """Creates a new Item in PostgreSQL database and invalidates the cached items list."""
    new_item = Item(title=item_in.title, description=item_in.description)
    db.add(new_item)
    await db.commit()
    await db.refresh(new_item)
    
    # Invalidate cache since database state changed
    try:
        redis_client = redis_manager.get_client()
        await redis_client.delete("all_items")
        logger.info("Invalidated Redis cache key: all_items")
    except Exception as e:
        logger.warning(f"Failed to invalidate cache after item creation: {e}")
        
    return new_item


@router.get("/", response_model=List[ItemResponse])
async def list_items(db: AsyncSession = Depends(get_db)):
    """
    List all items.
    Attempts to read from Redis cache first. On cache miss, queries PostgreSQL,
    populates the cache, and returns results.
    """
    cache_key = "all_items"
    
    # 1. Attempt to fetch from Redis
    try:
        redis_client = redis_manager.get_client()
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            logger.info("Cache hit: Loaded all_items from Redis.")
            items_list = json.loads(cached_data)
            return items_list
    except Exception as e:
        logger.warning(f"Failed to read from cache (checking Postgres instead): {e}")

    # 2. Cache miss: Query PostgreSQL database
    logger.info("Cache miss: Querying PostgreSQL database...")
    result = await db.execute(select(Item))
    items = result.scalars().all()
    
    # Map SQLAlchemy objects to Pydantic responses
    response_items = [ItemResponse.model_validate(item).model_dump() for item in items]
    
    # 3. Store in Redis with an Expiry (TTL: 1 hour / 3600s)
    try:
        redis_client = redis_manager.get_client()
        await redis_client.setex(
            cache_key,
            3600,
            json.dumps(response_items)
        )
        logger.info("Successfully populated Redis cache for key: all_items")
    except Exception as e:
        logger.warning(f"Failed to write to Redis cache: {e}")
        
    return response_items


@router.get("/{item_id}", response_model=ItemResponse)
async def read_item(item_id: int, db: AsyncSession = Depends(get_db)):
    """Fetch a single item from the database. Raises 404 if not found."""
    cache_key = f"item:{item_id}"
    
    # 1. Attempt to fetch from Redis
    try:
        redis_client = redis_manager.get_client()
        cached_data = await redis_client.get(cache_key)
        if cached_data:
            logger.info(f"Cache hit: Loaded item {item_id} from Redis.")
            return json.loads(cached_data)
    except Exception as e:
        logger.warning(f"Failed to read item {item_id} cache: {e}")

    # 2. Query Postgres
    result = await db.execute(select(Item).filter(Item.id == item_id))
    item = result.scalar_one_or_none()
    
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item with ID {item_id} not found."
        )
        
    response_data = ItemResponse.model_validate(item).model_dump()
    
    # 3. Store single item cache with TTL 300s
    try:
        redis_client = redis_manager.get_client()
        await redis_client.setex(cache_key, 300, json.dumps(response_data))
    except Exception as e:
        logger.warning(f"Failed to cache item {item_id}: {e}")
        
    return response_data
