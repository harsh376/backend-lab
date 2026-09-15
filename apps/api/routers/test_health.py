from httpx import ASGITransport, AsyncClient

from apps.api.routers.conftest import make_app


async def test_health_endpoints(client: AsyncClient) -> None:
    liveness_response = await client.get("/health/live")
    readiness_response = await client.get("/health/ready")

    assert liveness_response.status_code == 200
    assert liveness_response.json() == {"status": "ok"}
    assert readiness_response.status_code == 200
    assert readiness_response.json() == {"status": "ready"}


async def test_readiness_reports_an_unavailable_dependency() -> None:
    async def unavailable() -> bool:
        return False

    async with AsyncClient(
        transport=ASGITransport(app=await make_app(readiness_probe=unavailable)),
        base_url="http://test",
    ) as client:
        response = await client.get("/health/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
