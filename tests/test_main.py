import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.anyio
async def test_read_root():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/")
    assert response.status_code == 200
    assert "URL Redirect Tracer" in response.text


@pytest.mark.anyio
async def test_trace_url():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/trace?url=https://httpbin.org/status/200")
    assert response.status_code == 200
    data = response.json()
    assert "chain" in data
    assert len(data["chain"]) > 0