"""Helpers shared by the Groups/Challenges API tests.

`Actor` bundles a registered user with their auth header so a test that needs three
people in a group reads as three lines, not thirty.
"""

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient


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


@pytest.fixture
async def live_client():  # type: ignore[no-untyped-def]
    """An API client on **real, committed** transactions — one connection per request.

    The default `client` fixture pins every request to one session inside a rolled-back
    transaction. That is right for almost everything and useless for concurrency: two
    requests sharing one session cannot race, and rows one never commits are invisible
    to another connection. Anything that has to prove a database constraint or a row
    lock actually holds needs this instead.

    Everything it creates is real, so the fixture tracks the users involved and removes
    them and their whole object graph afterwards. Ordered by foreign key, deepest first.
    """
    import uuid as _uuid

    from sqlalchemy import delete, select, update

    from app.core.database import _session_factory
    from app.main import create_app
    from app.models.auth import RefreshToken
    from app.models.battle import Battle, BattleParticipant
    from app.models.challenge import (
        Challenge,
        ChallengeParticipant,
        DailyChallengeProgress,
    )
    from app.models.game import Elimination, Warning, XPTransaction
    from app.models.group import Group, GroupMember
    from app.models.media import GroupMessage, MediaAsset, MessageReaction
    from app.models.user import User, UserProfile
    from app.models.verification import HealthConnection, VerificationRecord

    created_users: list[_uuid.UUID] = []
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        ac.created_users = created_users  # type: ignore[attr-defined]
        yield ac

    if not created_users:
        return
    async with _session_factory() as session:
        group_ids = list(
            (
                await session.execute(
                    select(GroupMember.group_id).where(
                        GroupMember.user_id.in_(created_users)
                    )
                )
            ).scalars().all()
        )
        challenge_ids = list(
            (
                await session.execute(
                    select(Challenge.id).where(
                        Challenge.group_id.in_(group_ids or [_uuid.uuid4()])
                    )
                )
            ).scalars().all()
        ) or [_uuid.uuid4()]
        participant_ids = list(
            (
                await session.execute(
                    select(ChallengeParticipant.id).where(
                        ChallengeParticipant.challenge_id.in_(challenge_ids)
                    )
                )
            ).scalars().all()
        ) or [_uuid.uuid4()]
        progress_ids = list(
            (
                await session.execute(
                    select(DailyChallengeProgress.id).where(
                        DailyChallengeProgress.challenge_participant_id.in_(participant_ids)
                    )
                )
            ).scalars().all()
        ) or [_uuid.uuid4()]
        group_ids = group_ids or [_uuid.uuid4()]

        # `daily_challenge_progress.verification_record_id` and
        # `verification_record.daily_challenge_progress_id` point at each other, so the
        # link is broken before either table is emptied.
        await session.execute(
            update(DailyChallengeProgress)
            .where(DailyChallengeProgress.id.in_(progress_ids))
            .values(verification_record_id=None)
        )
        await session.execute(
            delete(VerificationRecord).where(
                VerificationRecord.daily_challenge_progress_id.in_(progress_ids)
            )
        )
        await session.execute(
            delete(DailyChallengeProgress).where(
                DailyChallengeProgress.id.in_(progress_ids)
            )
        )
        await session.execute(
            delete(Elimination).where(
                Elimination.challenge_participant_id.in_(participant_ids)
            )
        )
        await session.execute(
            delete(Warning).where(Warning.challenge_participant_id.in_(participant_ids))
        )
        await session.execute(
            delete(BattleParticipant).where(BattleParticipant.user_id.in_(created_users))
        )
        await session.execute(delete(Battle).where(Battle.group_id.in_(group_ids)))
        await session.execute(
            delete(ChallengeParticipant).where(
                ChallengeParticipant.id.in_(participant_ids)
            )
        )
        await session.execute(delete(Challenge).where(Challenge.id.in_(challenge_ids)))
        await session.execute(
            delete(MessageReaction).where(MessageReaction.user_id.in_(created_users))
        )
        await session.execute(delete(GroupMessage).where(GroupMessage.group_id.in_(group_ids)))
        await session.execute(
            delete(MediaAsset).where(MediaAsset.owner_id.in_(created_users))
        )
        await session.execute(delete(GroupMember).where(GroupMember.group_id.in_(group_ids)))
        await session.execute(delete(Group).where(Group.id.in_(group_ids)))
        await session.execute(
            delete(XPTransaction).where(XPTransaction.user_id.in_(created_users))
        )
        await session.execute(
            delete(HealthConnection).where(HealthConnection.user_id.in_(created_users))
        )
        await session.execute(delete(RefreshToken).where(RefreshToken.user_id.in_(created_users)))
        await session.execute(delete(UserProfile).where(UserProfile.user_id.in_(created_users)))
        await session.execute(delete(User).where(User.id.in_(created_users)))
        await session.commit()
