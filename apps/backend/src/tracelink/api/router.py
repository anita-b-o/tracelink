from fastapi import APIRouter

from tracelink.api.routes.entities import router as entities_router
from tracelink.api.routes.health import router as health_router
from tracelink.api.routes.investigations import router as investigations_router
from tracelink.api.routes.rag import router as rag_router
from tracelink.api.routes.relationships import router as relationships_router
from tracelink.api.routes.research_tasks import router as research_tasks_router
from tracelink.api.routes.review import router as review_router
from tracelink.api.routes.workspace import (
    investigation_router as investigation_workspace_router,
)
from tracelink.api.routes.workspace import (
    resource_router as workspace_resource_router,
)

api_router = APIRouter()
api_router.include_router(health_router, prefix="/health", tags=["health"])
api_router.include_router(investigations_router, prefix="/investigations", tags=["investigations"])
api_router.include_router(
    investigation_workspace_router, prefix="/investigations", tags=["workspace"]
)
api_router.include_router(research_tasks_router, prefix="/research-tasks", tags=["research-tasks"])
api_router.include_router(entities_router, prefix="/entities", tags=["entities"])
api_router.include_router(relationships_router, prefix="/relationships", tags=["relationships"])
api_router.include_router(rag_router, tags=["rag"])
api_router.include_router(workspace_resource_router, tags=["workspace"])
api_router.include_router(review_router, tags=["review"])
