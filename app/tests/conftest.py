import asyncio
import pytest
from typing import Generator
from httpx import AsyncClient

# Force asyncio loop to behave in test environments
@pytest.fixture(scope="session")
def event_loop() -> Generator[asyncio.AbstractEventLoop, None, None]:
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def mock_db_session(mocker):
    """Fixture to mock SQLAlchemy AsyncSession."""
    mock_session = mocker.AsyncMock()
    # Mock return values for standard operations
    mock_session.execute.return_value = mocker.AsyncMock()
    return mock_session
