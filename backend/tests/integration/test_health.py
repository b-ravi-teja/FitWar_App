import pytest
from httpx import AsyncClient

from app.api import health as health_module


async def test_health_reports_healthy_when_dependencies_up(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body == {"status": "healthy", "database": "healthy", "redis": "healthy"}


async def test_health_reports_503_when_database_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_unhealthy() -> bool:
        return False

    monkeypatch.setattr(health_module, "database_healthy", _fake_unhealthy)

    response = await client.get("/health")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["database"] == "unhealthy"
    assert body["redis"] == "healthy"


async def test_health_response_never_leaks_connection_details(client: AsyncClient) -> None:
    response = await client.get("/health")
    body_text = response.text.lower()
    assert "password" not in body_text
    assert "asyncpg" not in body_text
    assert "5433" not in body_text
