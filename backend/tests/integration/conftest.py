"""Helpers shared by the Groups/Challenges API tests.

`Actor` bundles a registered user with their auth header so a test that needs three
people in a group reads as three lines, not thirty.
"""

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import AsyncClient


@dataclass(frozen=True)
class Actor:
    user_id: uuid.UUID
    display_name: str
    headers: dict[str, str]


@pytest.fixture
def register_actor():  # type: ignore[no-untyped-def]
    async def _register(client: AsyncClient, display_name: str) -> Actor:
        email = f"{display_name.lower()}-{uuid.uuid4().hex[:8]}@example.com"
        response = await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "hunter2222", "display_name": display_name},
        )
        assert response.status_code == 201, response.text
        body = response.json()
        return Actor(
            user_id=uuid.UUID(body["user_id"]),
            display_name=display_name,
            headers={"Authorization": f"Bearer {body['access_token']}"},
        )

    return _register


@pytest.fixture
def create_group():  # type: ignore[no-untyped-def]
    async def _create(
        client: AsyncClient,
        actor: Actor,
        name: str = "KITS FITNESS WAR",
        timezone: str = "Asia/Kolkata",
    ) -> dict[str, Any]:
        response = await client.post(
            "/api/v1/groups",
            json={"name": name, "timezone": timezone},
            headers=actor.headers,
        )
        assert response.status_code == 201, response.text
        return dict(response.json())

    return _create


@pytest.fixture
def join_group():  # type: ignore[no-untyped-def]
    async def _join(client: AsyncClient, actor: Actor, join_code: str) -> Any:
        return await client.post(
            "/api/v1/groups/join", json={"join_code": join_code}, headers=actor.headers
        )

    return _join


@pytest.fixture
def create_challenge():  # type: ignore[no-untyped-def]
    async def _create(
        client: AsyncClient,
        actor: Actor,
        group_id: str,
        **overrides: Any,
    ) -> Any:
        payload: dict[str, Any] = {
            "name": "30 DAY STEP WAR",
            "activity_type": "steps",
            "target_value": "10000",
            "unit": "steps",
            "game_mode": "survival",
            "verification_method": "apple_health",
            "duration_days": 30,
        }
        payload.update(overrides)
        return await client.post(
            f"/api/v1/groups/{group_id}/challenges", json=payload, headers=actor.headers
        )

    return _create
