"""Application-startup checks: the app must construct cleanly and expose a valid
OpenAPI schema — the smallest possible proof that config, routing, and every
imported module wire together correctly."""

from httpx import AsyncClient

from app.main import create_app


def test_app_constructs_without_error() -> None:
    app = create_app()
    assert app.title == "FITWAR API"


async def test_openapi_schema_loads(client: AsyncClient) -> None:
    response = await client.get("/openapi.json")
    assert response.status_code == 200
    schema = response.json()
    assert "/api/v1/auth/register" in schema["paths"]
    assert "/api/v1/auth/login" in schema["paths"]
    assert "/api/v1/auth/refresh" in schema["paths"]
    assert "/api/v1/auth/logout" in schema["paths"]
    assert "/health" in schema["paths"]


async def test_docs_ui_loads(client: AsyncClient) -> None:
    response = await client.get("/docs")
    assert response.status_code == 200
