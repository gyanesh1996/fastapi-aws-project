import pytest


@pytest.fixture
def anyio_backend():
    # Run async tests on asyncio only (trio isn't installed).
    return "asyncio"
