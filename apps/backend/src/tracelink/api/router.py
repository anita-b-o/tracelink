from fastapi import APIRouter

from tracelink.api.routes.entities import router as entities_router
from tracelink.api.routes.health import router as health_router
from tracelink.api.routes.investigations import router as investigations_router

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(investigations_router, prefix="/investigations", tags=["investigations"])
api_router.include_router(entities_router, prefix="/entities", tags=["entities"])
