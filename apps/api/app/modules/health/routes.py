from fastapi import APIRouter, Response, status

from app.modules.health.schemas import HealthStatus
from app.modules.health.service import HealthService


def router(service: HealthService) -> APIRouter:
    routes = APIRouter(prefix="/api/v1/health")

    @routes.get("/live", response_model=HealthStatus)
    async def live(response: Response) -> HealthStatus:
        response.headers["Cache-Control"] = "no-store"
        return HealthStatus(status="alive")

    @routes.get("/ready", response_model=HealthStatus)
    async def ready(response: Response) -> HealthStatus:
        response.headers["Cache-Control"] = "no-store"
        if await service.readiness():
            return HealthStatus(status="ready")
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthStatus(status="unavailable")

    return routes
