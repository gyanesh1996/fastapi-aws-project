from fastapi import APIRouter

from app.api.v1.endpoints import health, trace, web

api_router = APIRouter()
api_router.include_router(web.router, tags=["Web Page"])
api_router.include_router(health.router, tags=["Health"])
api_router.include_router(trace.router, prefix="/api", tags=["Trace"])
