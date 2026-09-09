"""Application health endpoints."""

from fastapi import APIRouter
from fastapi.responses import JSONResponse, Response

from app.api.dependencies import ReadinessProbeDependency

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/ready")
async def readiness(readiness_probe: ReadinessProbeDependency) -> Response:
    ready = readiness_probe is None or await readiness_probe()
    return JSONResponse(
        content={"status": "ready" if ready else "unavailable"},
        status_code=200 if ready else 503,
    )
