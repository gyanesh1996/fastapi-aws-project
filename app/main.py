from fastapi import FastAPI

from app.api.v1.router import api_router
from app.core.config import settings

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=(
        "Full affiliate/tracking-link redirect tracer. Follows HTTP, meta-refresh, "
        "JavaScript and JSON redirects through real residential/geo proxies and "
        "identifies the tracking platform and app-store destination at each hop."
    ),
)

app.include_router(api_router)
