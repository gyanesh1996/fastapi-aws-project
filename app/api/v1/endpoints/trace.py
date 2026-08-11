from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.models.schemas import TraceResult
from app.services import profiles
from app.services.fetcher import Fetcher
from app.services.tracer import trace_url

router = APIRouter()


@router.get("/trace", response_model=TraceResult)
async def trace(
    url: str = Query(..., description="Tracking / affiliate URL to trace"),
    device: str = Query("desktop", description="desktop | android | ios"),
    country: str = Query("US", description="ISO country code, e.g. US, IN, GB"),
    tier: str = Query(None, description="auto | basic | premium | ultra (defaults to server config)"),
    screenshot: bool = Query(False, description="Capture a screenshot of the final page"),
) -> TraceResult:
    if not url or not url.strip():
        raise HTTPException(status_code=422, detail="A URL is required.")
    try:
        return await trace_url(
            url,
            device=device,
            country=country,
            tier=tier,
            screenshot=screenshot,
        )
    except Exception as exc:  # noqa: BLE001 - surface engine errors to the client
        raise HTTPException(status_code=502, detail=f"Trace failed: {exc}") from exc


@router.get("/egress-ip")
async def egress_ip(country: str = Query("US")):
    """Return the real proxy exit IP for a country (verifies geo egress works)."""
    country = profiles.normalize_country(country)
    if not settings.scraperapi_enabled:
        return {"enabled": False, "country": country, "ip": None,
                "note": "SCRAPERAPI_KEY not configured; running in direct mode."}
    fetcher = Fetcher(country, "desktop")
    result = await fetcher.fetch(
        "https://httpbin.org/ip",
        headers=profiles.build_headers("desktop", country),
        tier="basic",
        timeout=25.0,
    )
    ip = None
    if result.ok_transport and result.text:
        import json

        try:
            ip = json.loads(result.text).get("origin")
        except Exception:
            ip = None
    return {"enabled": True, "country": country, "ip": ip,
            "note": None if ip else "Could not read egress IP (proxy may still work for tracing)."}


@router.get("/config")
async def config():
    """Non-secret runtime info for the UI."""
    return {
        "engine": "scraperapi" if settings.scraperapi_enabled else "direct",
        "scraperapi_enabled": settings.scraperapi_enabled,
        "default_tier": settings.PROXY_TIER,
        "max_hops": settings.MAX_HOPS,
        "countries": {code: prof["label"] for code, prof in profiles.COUNTRY_PROFILES.items()},
        "version": settings.VERSION,
    }
