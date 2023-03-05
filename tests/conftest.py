import pytest
import asyncio
from gyver.config import AdapterConfigFactory


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.get_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def factory():
    return AdapterConfigFactory()
