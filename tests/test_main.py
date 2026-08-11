import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app, US_IPS, IN_IPS, get_spoofed_ip


@pytest.mark.anyio
async def test_read_root():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/")
    assert response.status_code == 200
    assert "Affiliate Link & Redirect Tracer" in response.text


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
    # Verifies default country selection and membership in expanded US_IPS pool
    assert data["country"] == "US"
    assert data["spoofed_ip"] in US_IPS


@pytest.mark.anyio
async def test_trace_url_country_override():
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        response = await ac.get("/api/trace?url=https://httpbin.org/status/200&country=IN")
    assert response.status_code == 200
    data = response.json()
    assert data["country"] == "IN"
    assert data["spoofed_ip"] in IN_IPS


def test_get_spoofed_ip_unit():
    assert get_spoofed_ip("US") in US_IPS
    assert get_spoofed_ip("IN") in IN_IPS
    assert get_spoofed_ip("UNKNOWN") in US_IPS