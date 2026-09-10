"""GET/PATCH /me — full HTTP-level tests against a real Postgres session."""

import uuid

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


class TestOnboardingState:
    """Server-backed first-run onboarding progress.

    The client used to infer "needs onboarding" from a transient UI callback, which lost
    a race against its own view's teardown and skipped onboarding for every new account.
    The answer now lives here, where it survives reinstall, a second device, and
    logout/login.
    """

    async def test_a_new_registration_starts_at_the_first_step(self, client) -> None:
        registered = (
            await client.post(
                "/api/v1/auth/register",
                json={
                    "email": f"onb-{uuid.uuid4().hex[:8]}@example.com",
                    "password": "hunter2222",
                    "display_name": "Newbie",
                },
            )
        ).json()
        headers = {"Authorization": f"Bearer {registered['access_token']}"}

        me = (await client.get("/api/v1/me", headers=headers)).json()

        assert me["onboarding_stage"] == "discipline"
        assert me["onboarding_completed_at"] is None

    async def test_progress_advances_and_persists(self, client, register_actor) -> None:
        actor = await register_actor(client, "Stepper")

        for stage in ("health", "profile"):
            response = await client.patch(
                "/api/v1/me", json={"onboarding_stage": stage}, headers=actor.headers
            )
            assert response.status_code == 200
            assert response.json()["onboarding_stage"] == stage

        # A fresh read, not the write's echo — this is what a relaunch would see.
        me = (await client.get("/api/v1/me", headers=actor.headers)).json()
        assert me["onboarding_stage"] == "profile"
        assert me["onboarding_completed_at"] is None

    async def test_completion_is_stamped_once_and_never_moves(self, client, register_actor) -> None:
        actor = await register_actor(client, "Finisher")

        first = (
            await client.patch(
                "/api/v1/me", json={"onboarding_stage": "completed"}, headers=actor.headers
            )
        ).json()
        assert first["onboarding_stage"] == "completed"
        assert first["onboarding_completed_at"] is not None

        # A retried request must not rewrite when the user finished.
        again = (
            await client.patch(
                "/api/v1/me", json={"onboarding_stage": "completed"}, headers=actor.headers
            )
        ).json()
        assert again["onboarding_completed_at"] == first["onboarding_completed_at"]

    async def test_logging_back_in_does_not_reset_onboarding(self, client) -> None:
        """The property a device flag could not give: completion survives a new session."""
        email = f"relog-{uuid.uuid4().hex[:8]}@example.com"
        registered = (
            await client.post(
                "/api/v1/auth/register",
                json={"email": email, "password": "hunter2222", "display_name": "Relog"},
            )
        ).json()
        headers = {"Authorization": f"Bearer {registered['access_token']}"}
        await client.patch("/api/v1/me", json={"onboarding_stage": "completed"}, headers=headers)

        logged_in = (
            await client.post(
                "/api/v1/auth/login", json={"email": email, "password": "hunter2222"}
            )
        ).json()
        fresh = {"Authorization": f"Bearer {logged_in['access_token']}"}

        me = (await client.get("/api/v1/me", headers=fresh)).json()
        assert me["onboarding_stage"] == "completed"

    async def test_an_unknown_stage_is_refused(self, client, register_actor) -> None:
        actor = await register_actor(client, "Bogus")

        response = await client.patch(
            "/api/v1/me", json={"onboarding_stage": "teleportation"}, headers=actor.headers
        )

        assert response.status_code == 422

    async def test_onboarding_state_is_scoped_to_the_caller(
        self, client, register_actor
    ) -> None:
        """It is per-account state, so one user's progress must not read as another's."""
        first = await register_actor(client, "OnbA")
        second = await register_actor(client, "OnbB")
        await client.patch(
            "/api/v1/me", json={"onboarding_stage": "completed"}, headers=first.headers
        )

        other = (await client.get("/api/v1/me", headers=second.headers)).json()

        assert other["onboarding_stage"] == "discipline"

    async def test_it_does_not_touch_competitive_state(self, client, register_actor) -> None:
        """Onboarding is client-driven, so it must grant nothing a cheat would want."""
        actor = await register_actor(client, "OnbXP")
        before = (await client.get("/api/v1/me/xp", headers=actor.headers)).json()

        await client.patch(
            "/api/v1/me",
            json={"onboarding_stage": "completed", "xp_total": 99999},
            headers=actor.headers,
        )

        after = (await client.get("/api/v1/me/xp", headers=actor.headers)).json()
        assert after["xp_total"] == before["xp_total"] == 0
