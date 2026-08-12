from fastapi import APIRouter, Depends

from tracelink.api.dependencies import get_current_user
from tracelink.api.routes.auth import router as auth_router
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
api_router.include_router(auth_router, prefix="/auth", tags=["auth"])
protected = [Depends(get_current_user)]
api_router.include_router(
    investigations_router,
    prefix="/investigations",
    tags=["investigations"],
    dependencies=protected,
)
api_router.include_router(
    investigation_workspace_router,
    prefix="/investigations",
    tags=["workspace"],
    dependencies=protected,
)
api_router.include_router(
    research_tasks_router,
    prefix="/research-tasks",
    tags=["research-tasks"],
    dependencies=protected,
)
api_router.include_router(
    entities_router, prefix="/entities", tags=["entities"], dependencies=protected
)
api_router.include_router(
    relationships_router, prefix="/relationships", tags=["relationships"], dependencies=protected
)
api_router.include_router(rag_router, tags=["rag"], dependencies=protected)
api_router.include_router(workspace_resource_router, tags=["workspace"], dependencies=protected)
api_router.include_router(review_router, tags=["review"], dependencies=protected)
