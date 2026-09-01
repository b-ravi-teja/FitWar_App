"""Liveness/readiness probe. No auth, no sensitive infrastructure detail in the response."""

from fastapi import APIRouter, Response, status

from app.core.database import database_healthy
from app.core.redis import redis_healthy
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(response: Response) -> HealthResponse:
    db_ok = await database_healthy()
    redis_ok = await redis_healthy()
    overall_ok = db_ok and redis_ok

    if not overall_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthResponse(
        status="healthy" if overall_ok else "unhealthy",
        database="healthy" if db_ok else "unhealthy",
        redis="healthy" if redis_ok else "unhealthy",
    )
