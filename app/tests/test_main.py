import pytest
from unittest.mock import AsyncMock, patch
from httpx import AsyncClient

# Inject dummy settings during test execution to bypass .env load requirements
with patch.dict("os.environ", {
    "SECRET_KEY": "test-secret-key-12345678901234567890123456789012",
    "JWT_SECRET": "test-jwt-secret-12345678901234567890123456789012",
    "POSTGRES_USER": "testuser",
    "POSTGRES_PASSWORD": "testpassword",
    "POSTGRES_DB": "testdb",
    "POSTGRES_HOST": "localhost",
    "REDIS_HOST": "localhost",
}):
    from app.main import app
    from app.database import get_db



@pytest.mark.asyncio
async def test_read_root():
    """Verify that root endpoint responds with standard greeting."""
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "online"
    assert "message" in response.json()


@pytest.mark.asyncio
@patch("app.routers.health.redis_manager")
async def test_health_endpoint_healthy(mock_redis_mgr):
    """Test health check returns healthy status when DB and Redis are up."""
    # 1. Mock Database session
    mock_db = AsyncMock()
    mock_db.execute.return_value = AsyncMock()
    
    # 2. Mock Redis client
    mock_redis = AsyncMock()
    mock_redis.ping.return_value = True
    mock_redis_mgr.get_client.return_value = mock_redis
    
    # Overwrite dependency overrides
    app.dependency_overrides[get_db] = lambda: mock_db
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/health")
        
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["services"]["api"] == "healthy"
    assert data["services"]["database"]["status"] == "healthy"
    assert data["services"]["redis"]["status"] == "healthy"
    
    # Clear overrides
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@patch("app.routers.health.redis_manager")
async def test_health_endpoint_unhealthy(mock_redis_mgr):
    """Test health check returns 503 status when DB connection fails."""
    # 1. Mock DB failure
    mock_db = AsyncMock()
    mock_db.execute.side_effect = Exception("Database connection timeout")
    
    # 2. Mock Redis client healthy
    mock_redis = AsyncMock()
    mock_redis.ping.return_value = True
    mock_redis_mgr.get_client.return_value = mock_redis
    
    app.dependency_overrides[get_db] = lambda: mock_db
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.get("/health")
        
    assert response.status_code == 503
    data = response.json()["detail"]
    assert data["status"] == "unhealthy"
    assert data["services"]["database"]["status"] == "unhealthy"
    assert "Database connection timeout" in data["services"]["database"]["error"]
    
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@patch("app.routers.items.redis_manager")
async def test_create_item_and_invalidate_cache(mock_redis_mgr):
    """Test creating an item inserts in DB and deletes Redis key."""
    # Mock Redis client
    mock_redis = AsyncMock()
    mock_redis_mgr.get_client.return_value = mock_redis
    
    # Mock DB session
    mock_db = AsyncMock()
    mock_db.add.return_value = None
    mock_db.commit.return_value = None
    mock_db.refresh.return_value = None
    
    app.dependency_overrides[get_db] = lambda: mock_db
    
    payload = {"title": "Test Item", "description": "Pytest verification description"}
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        response = await ac.post("/api/v1/items/", json=payload)
        
    assert response.status_code == 201
    # Check that it triggered Redis cache key invalidation
    mock_redis.delete.assert_called_once_with("all_items")
    
    app.dependency_overrides.clear()
