"""GET/PATCH /me — full HTTP-level tests against a real Postgres session."""

from httpx import AsyncClient


async def _register_and_login(client: AsyncClient, email: str = "ravi@example.com") -> str:
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "hunter2222", "display_name": "Ravi"},
    )
    assert response.status_code == 201
    return str(response.json()["access_token"])


async def test_get_me_returns_profile(client: AsyncClient) -> None:
    access_token = await _register_and_login(client)

    response = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {access_token}"})

    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "ravi@example.com"
    assert body["display_name"] == "Ravi"
    assert body["xp_total"] == 0
    assert body["avatar_media_id"] is None


async def test_get_me_without_token_is_unauthenticated(client: AsyncClient) -> None:
    response = await client.get("/api/v1/me")
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHENTICATED"


async def test_patch_me_updates_display_name(client: AsyncClient) -> None:
    access_token = await _register_and_login(client, email="rename@example.com")

    response = await client.patch(
        "/api/v1/me",
        json={"display_name": "Ravi Teja"},
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["display_name"] == "Ravi Teja"

    follow_up = await client.get("/api/v1/me", headers={"Authorization": f"Bearer {access_token}"})
    assert follow_up.json()["display_name"] == "Ravi Teja"


async def test_patch_me_updates_notification_preferences(client: AsyncClient) -> None:
    access_token = await _register_and_login(client, email="prefs@example.com")

    response = await client.patch(
        "/api/v1/me",
        json={"notification_preferences": {"warnings": True, "chat": False}},
        headers={"Authorization": f"Bearer {access_token}"},
    )

    assert response.status_code == 200
    assert response.json()["notification_preferences"] == {"warnings": True, "chat": False}
