"""The one Problem Details envelope shape, exercised across every failure category
the centralized handler in core/errors.py covers."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app

EXPECTED_KEYS = {"type", "title", "status", "detail", "code"}


async def test_domain_error_response_shape(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "dup2@example.com", "password": "hunter2222", "display_name": "A"},
    )
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "dup2@example.com", "password": "hunter2222", "display_name": "A"},
    )
    body = response.json()
    assert set(body.keys()) == EXPECTED_KEYS
    assert body["status"] == 409
    assert body["code"] == "EMAIL_TAKEN"


async def test_validation_error_response_shape(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/register", json={"email": "not-an-email"})
    body = response.json()
    assert set(body.keys()) == EXPECTED_KEYS
    assert body["status"] == 422
    assert body["code"] == "VALIDATION_ERROR"
    # The detail string names the offending field, not just "invalid".
    assert (
        "email" in body["detail"]
        or "password" in body["detail"]
        or "display_name" in body["detail"]
    )


async def test_not_found_route_response_shape(client: AsyncClient) -> None:
    response = await client.get("/api/v1/this-route-does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert set(body.keys()) == EXPECTED_KEYS
    assert body["code"] == "NOT_FOUND"


async def test_unexpected_exception_maps_to_500_without_leaking_internals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.deps import get_auth_service

    app = create_app()
    # Debug mode (on by default locally, APP_DEBUG=true) intentionally shows
    # Starlette's own traceback page instead of the app's JSON handler — that's
    # correct for local development. What this test actually verifies is the
    # production contract (APP_DEBUG=false), so it's forced off here.
    app.debug = False

    def _boom() -> None:
        raise RuntimeError("db connection string: postgresql://secret@internal-host/db")

    app.dependency_overrides[get_auth_service] = _boom

    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/api/v1/auth/login", json={"email": "x@example.com", "password": "whatever1"}
        )

    assert response.status_code == 500
    body = response.json()
    assert set(body.keys()) == EXPECTED_KEYS
    assert body["code"] == "INTERNAL_ERROR"
    assert "secret" not in response.text
    assert "postgresql://" not in response.text
