"""Password reset — full HTTP-level tests against real Postgres + real Redis.

Builds its own app/client (like `test_error_handling.py`'s forced-500 test) so it can
override `get_auth_service` with a capturing email sender — the only way to observe
the raw reset token an HTTP-level test can see, since `LoggingEmailSender` only logs
it (Redis stores a hash, not the raw value, by design).
"""

from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_auth_service
from app.core.redis import get_redis
from app.main import create_app
from app.repositories.password_reset_tokens import PasswordResetTokenRepository
from app.services.auth_service import AuthService


class CapturingEmailSender:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    async def send_password_reset(self, *, to: str, token: str) -> None:
        self.sent.append((to, token))


@pytest.fixture
async def reset_client(
    db_session: AsyncSession,
) -> AsyncIterator[tuple[AsyncClient, CapturingEmailSender]]:
    app = create_app()
    email_sender = CapturingEmailSender()

    async def _override_get_db() -> AsyncIterator[AsyncSession]:
        yield db_session

    def _override_get_auth_service() -> AuthService:
        return AuthService(
            db_session,
            reset_tokens=PasswordResetTokenRepository(get_redis()),
            email_sender=email_sender,
        )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_auth_service] = _override_get_auth_service

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, email_sender


async def test_request_reset_for_existing_account_sends_token(
    reset_client: tuple[AsyncClient, CapturingEmailSender],
) -> None:
    client, email_sender = reset_client
    await client.post(
        "/api/v1/auth/register",
        json={"email": "resetme@example.com", "password": "oldpassword1", "display_name": "R"},
    )

    response = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "resetme@example.com"}
    )

    assert response.status_code == 202
    assert len(email_sender.sent) == 1
    assert email_sender.sent[0][0] == "resetme@example.com"


async def test_request_reset_for_unknown_email_still_returns_202(
    reset_client: tuple[AsyncClient, CapturingEmailSender],
) -> None:
    """Never reveals whether the account exists (this phase's §13 / ADR 0007) — same
    202, same empty body, whether or not `ghost@example.com` has an account."""
    client, email_sender = reset_client

    response = await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "ghost@example.com"}
    )

    assert response.status_code == 202
    assert email_sender.sent == []


async def test_confirm_reset_with_valid_token_changes_password(
    reset_client: tuple[AsyncClient, CapturingEmailSender],
) -> None:
    client, email_sender = reset_client
    await client.post(
        "/api/v1/auth/register",
        json={"email": "confirmme@example.com", "password": "oldpassword1", "display_name": "R"},
    )
    await client.post(
        "/api/v1/auth/password-reset/request", json={"email": "confirmme@example.com"}
    )
    _, raw_token = email_sender.sent[0]

    response = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw_token, "new_password": "newpassword1"},
    )
    assert response.status_code == 200

    login = await client.post(
        "/api/v1/auth/login", json={"email": "confirmme@example.com", "password": "newpassword1"}
    )
    assert login.status_code == 200


async def test_confirm_reset_with_invalid_token_fails(
    reset_client: tuple[AsyncClient, CapturingEmailSender],
) -> None:
    client, _ = reset_client
    response = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": "never-issued", "new_password": "newpassword1"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == "RESET_TOKEN_INVALID_OR_EXPIRED"


async def test_confirm_reset_token_cannot_be_reused(
    reset_client: tuple[AsyncClient, CapturingEmailSender],
) -> None:
    client, email_sender = reset_client
    await client.post(
        "/api/v1/auth/register",
        json={"email": "onceonly@example.com", "password": "oldpassword1", "display_name": "R"},
    )
    await client.post("/api/v1/auth/password-reset/request", json={"email": "onceonly@example.com"})
    _, raw_token = email_sender.sent[0]

    first = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw_token, "new_password": "newpassword1"},
    )
    assert first.status_code == 200

    second = await client.post(
        "/api/v1/auth/password-reset/confirm",
        json={"token": raw_token, "new_password": "anotherpassword1"},
    )
    assert second.status_code == 400
