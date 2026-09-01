"""Full-stack auth endpoint tests: real HTTP client, real Postgres (via the
transaction-rollback `db_session`/`client` fixtures in conftest.py).

Note: `/auth/register|login|refresh|logout` are the only auth endpoints built in
Phase 1 (Architecture §17's Foundation phase). There is no `/me` endpoint yet, so
account-deletion-blocks-login is covered at the service-unit level
(`tests/unit/test_auth_service.py::test_login_deleted_account_raises`) rather than
through HTTP here — see the Phase 1 report's scoping notes.
"""

import uuid
from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_refresh_token
from app.repositories.refresh_tokens import RefreshTokenRepository
from app.repositories.users import UserRepository


async def test_register_valid(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "ravi@example.com", "password": "hunter2222", "display_name": "Ravi"},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["user_id"]
    assert body["access_token"]
    assert body["refresh_token"]
    assert body["expires_in"] == 15 * 60


async def test_register_duplicate_email(client: AsyncClient) -> None:
    payload = {"email": "dup@example.com", "password": "hunter2222", "display_name": "A"}
    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409
    body = second.json()
    assert body["code"] == "EMAIL_TAKEN"


async def test_register_invalid_email(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "not-an-email", "password": "hunter2222", "display_name": "A"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_register_invalid_password_too_short(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": "shortpw@example.com", "password": "short", "display_name": "A"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


async def test_login_valid_credentials(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "ravi@example.com", "password": "hunter2222", "display_name": "Ravi"},
    )
    response = await client.post(
        "/api/v1/auth/login", json={"email": "ravi@example.com", "password": "hunter2222"}
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"]
    assert body["refresh_token"]


async def test_login_invalid_credentials(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "ravi@example.com", "password": "hunter2222", "display_name": "Ravi"},
    )
    response = await client.post(
        "/api/v1/auth/login", json={"email": "ravi@example.com", "password": "wrong-password"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


async def test_login_unknown_user(client: AsyncClient) -> None:
    response = await client.post(
        "/api/v1/auth/login", json={"email": "ghost@example.com", "password": "whatever1"}
    )
    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


async def test_login_deleted_user(client: AsyncClient, db_session: AsyncSession) -> None:
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": "gone@example.com", "password": "hunter2222", "display_name": "G"},
    )
    assert register.status_code == 201

    users = UserRepository(db_session)
    user = await users.get_by_email("gone@example.com")
    assert user is not None
    await users.soft_delete(user)

    response = await client.post(
        "/api/v1/auth/login", json={"email": "gone@example.com", "password": "hunter2222"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "ACCOUNT_DELETED"


async def test_refresh_valid(client: AsyncClient) -> None:
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": "ravi@example.com", "password": "hunter2222", "display_name": "Ravi"},
    )
    refresh_token = register.json()["refresh_token"]

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    body = response.json()
    assert body["refresh_token"] != refresh_token


async def test_refresh_unrecognized_token(client: AsyncClient) -> None:
    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": "not-a-real-token"})
    assert response.status_code == 401
    assert response.json()["code"] == "REFRESH_INVALID"


async def test_refresh_expired_token(client: AsyncClient, db_session: AsyncSession) -> None:
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": "ravi@example.com", "password": "hunter2222", "display_name": "Ravi"},
    )
    user_id = uuid.UUID(register.json()["user_id"])

    tokens = RefreshTokenRepository(db_session)
    raw_expired = "expired-raw-token-value"
    await tokens.create(
        user_id=user_id,
        token_hash=hash_refresh_token(raw_expired),
        family_id=uuid.uuid4(),
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": raw_expired})
    assert response.status_code == 401
    assert response.json()["code"] == "REFRESH_INVALID"


async def test_refresh_reuse_detected(client: AsyncClient) -> None:
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": "ravi@example.com", "password": "hunter2222", "display_name": "Ravi"},
    )
    original_refresh = register.json()["refresh_token"]

    first = await client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh})
    assert first.status_code == 200

    replay = await client.post("/api/v1/auth/refresh", json={"refresh_token": original_refresh})
    assert replay.status_code == 401
    assert replay.json()["code"] == "REFRESH_REUSE_DETECTED"

    # The whole family is revoked, including the token issued by the legitimate rotation.
    rotated_refresh = first.json()["refresh_token"]
    also_dead = await client.post("/api/v1/auth/refresh", json={"refresh_token": rotated_refresh})
    assert also_dead.status_code == 401


async def test_logout_then_refresh_fails(client: AsyncClient) -> None:
    register = await client.post(
        "/api/v1/auth/register",
        json={"email": "ravi@example.com", "password": "hunter2222", "display_name": "Ravi"},
    )
    refresh_token = register.json()["refresh_token"]

    logout = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_token})
    assert logout.status_code == 204

    response = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 401
