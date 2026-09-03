"""Battle races against real Postgres, on real independent connections.

Every test here uses `live_client`, which commits: the default fixture pins all
requests to one rolled-back session, where two "concurrent" requests would serialize
on a single connection and prove nothing. The claims below are about database
constraints and row locks, so they are made where those actually apply.

What is being proven, in the language of §13:

    one battle              = exactly two participants
    one completed battle    = exactly one final outcome
    one completed battle    = at most one XP award per intended ledger entry
"""

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.database import _session_factory
from app.models.battle import Battle, BattleParticipant, BattleParticipantStatus, BattleStatus
from app.models.challenge import ChallengeParticipant
from app.models.game import XPReason, XPTransaction


async def _register(client, display_name: str):  # type: ignore[no-untyped-def]
    email = f"{display_name.lower()}-{uuid.uuid4().hex[:10]}@example.com"
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "hunter2222", "display_name": display_name},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    user_id = uuid.UUID(body["user_id"])
    client.created_users.append(user_id)
    return user_id, {"Authorization": f"Bearer {body['access_token']}"}


async def _pair(client):  # type: ignore[no-untyped-def]
    """Two squad-mates on a live client."""
    alpha_id, alpha = await _register(client, "Racer")
    bravo_id, bravo = await _register(client, "Rival")
    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "RACE SQUAD", "timezone": "Asia/Kolkata"},
            headers=alpha,
        )
    ).json()
    joined = await client.post(
        "/api/v1/groups/join", json={"join_code": group["join_code"]}, headers=bravo
    )
    assert joined.status_code == 200, joined.text
    return (alpha_id, alpha), (bravo_id, bravo), group


async def _open_battle(client, alpha, bravo_id, group, duration_days: int = 1) -> Any:  # type: ignore[no-untyped-def]
    response = await client.post(
        "/api/v1/battles",
        json={
            "opponent_user_id": str(bravo_id),
            "activity_type": "steps",
            "target_value": "10000",
            "duration_days": duration_days,
            "group_id": group["id"],
        },
        headers=alpha,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def _verify(client, headers, battle_id: str, value: str) -> Any:  # type: ignore[no-untyped-def]
    battle = (await client.get(f"/api/v1/battles/{battle_id}", headers=headers)).json()
    return await client.post(
        f"/api/v1/battles/{battle_id}/verify",
        json={
            "provider": "apple_health",
            "evidence": {
                "metric": "steps",
                "value": value,
                "unit": "steps",
                "period_start": battle["start_at"],
                "period_end": datetime.now(UTC).isoformat(),
                "was_user_entered": False,
            },
        },
        headers=headers,
    )


async def _count(model: Any, *conditions: Any) -> int:
    async with _session_factory() as session:
        result = await session.execute(
            select(func.count()).select_from(model).where(*conditions)
        )
        return int(result.scalar_one())


class TestCreationRace:
    async def test_simultaneous_invitations_produce_one_battle(self, live_client) -> None:  # type: ignore[no-untyped-def]
        """Five requests, five connections, one live battle.

        There is no check-then-insert here to lose: `uq_battle_live_pair` decides, so
        the four losers learn it from the database rather than from a stale read.
        """
        (_, alpha), (bravo_id, _), group = await _pair(live_client)
        payload = {
            "opponent_user_id": str(bravo_id),
            "activity_type": "steps",
            "duration_days": 1,
            "group_id": group["id"],
        }

        responses = await asyncio.gather(
            *(
                live_client.post("/api/v1/battles", json=payload, headers=alpha)
                for _ in range(5)
            )
        )

        created = [r for r in responses if r.status_code == 201]
        refused = [r for r in responses if r.status_code == 409]
        assert len(created) == 1
        assert len(refused) == 4
        assert all(r.json()["code"] == "ALREADY_PENDING_WITH_USER" for r in refused)
        assert await _count(Battle, Battle.group_id == uuid.UUID(group["id"])) == 1

    async def test_invitations_in_both_directions_at_once_produce_one_battle(
        self, live_client
    ) -> None:  # type: ignore[no-untyped-def]
        """A challenges B while B challenges A. `pair_key` is symmetric, so one wins."""
        (alpha_id, alpha), (bravo_id, bravo), group = await _pair(live_client)

        responses = await asyncio.gather(
            live_client.post(
                "/api/v1/battles",
                json={
                    "opponent_user_id": str(bravo_id),
                    "activity_type": "steps",
                    "duration_days": 1,
                    "group_id": group["id"],
                },
                headers=alpha,
            ),
            live_client.post(
                "/api/v1/battles",
                json={
                    "opponent_user_id": str(alpha_id),
                    "activity_type": "steps",
                    "duration_days": 1,
                    "group_id": group["id"],
                },
                headers=bravo,
            ),
        )

        assert sorted(r.status_code for r in responses) == [201, 409]
        assert await _count(Battle, Battle.group_id == uuid.UUID(group["id"])) == 1


class TestAcceptanceRace:
    async def test_concurrent_acceptances_start_the_battle_once(self, live_client) -> None:  # type: ignore[no-untyped-def]
        """Five simultaneous accepts serialize on the battle row's lock.

        All five succeed as far as the client is concerned — acceptance is idempotent —
        but the battle starts once, and exactly two people are in the challenge behind it.
        """
        (_, alpha), (bravo_id, bravo), group = await _pair(live_client)
        battle = await _open_battle(live_client, alpha, bravo_id, group)

        responses = await asyncio.gather(
            *(
                live_client.post(
                    f"/api/v1/battles/{battle['id']}/accept", headers=bravo
                )
                for _ in range(5)
            ),
            return_exceptions=True,
        )

        ok = [r for r in responses if getattr(r, "status_code", None) == 200]
        assert len(ok) == 5
        # One start instant across every reply — no accept restarted the battle.
        assert len({r.json()["start_at"] for r in ok}) == 1

        async with _session_factory() as session:
            row = (
                await session.execute(
                    select(Battle).where(Battle.id == uuid.UUID(battle["id"]))
                )
            ).scalar_one()
            assert row.status is BattleStatus.ACTIVE
            participants = (
                await session.execute(
                    select(func.count())
                    .select_from(ChallengeParticipant)
                    .where(ChallengeParticipant.challenge_id == row.challenge_id)
                )
            ).scalar_one()
            assert participants == 2

    async def test_accept_and_decline_at_once_leave_one_coherent_state(
        self, live_client
    ) -> None:  # type: ignore[no-untyped-def]
        """Whichever lands first wins the lock; the other is refused, never both."""
        (_, alpha), (bravo_id, bravo), group = await _pair(live_client)
        battle = await _open_battle(live_client, alpha, bravo_id, group)

        accepted, declined = await asyncio.gather(
            live_client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo),
            live_client.post(f"/api/v1/battles/{battle['id']}/decline", headers=bravo),
        )

        assert {accepted.status_code, declined.status_code} == {200, 409}
        async with _session_factory() as session:
            row = (
                await session.execute(
                    select(Battle).where(Battle.id == uuid.UUID(battle["id"]))
                )
            ).scalar_one()
            assert row.status in (BattleStatus.ACTIVE, BattleStatus.CANCELLED)

    async def test_only_two_participant_rows_can_ever_exist(self, live_client) -> None:  # type: ignore[no-untyped-def]
        """The slot constraint under a real race, not a service-level count."""
        from sqlalchemy.exc import IntegrityError

        (_, alpha), (bravo_id, bravo), group = await _pair(live_client)
        charlie_id, charlie = await _register(live_client, "Gatecrasher")
        assert (
            await live_client.post(
                "/api/v1/groups/join",
                json={"join_code": group["join_code"]},
                headers=charlie,
            )
        ).status_code == 200
        battle = await _open_battle(live_client, alpha, bravo_id, group)
        await live_client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo)

        async def gatecrash(slot: int) -> bool:
            async with _session_factory() as session:
                session.add(
                    BattleParticipant(
                        battle_id=uuid.UUID(battle["id"]),
                        user_id=charlie_id,
                        slot=slot,
                        score=Decimal(0),
                    )
                )
                try:
                    await session.commit()
                    return True
                except IntegrityError:
                    await session.rollback()
                    return False

        outcomes = await asyncio.gather(*(gatecrash(slot) for slot in (1, 2, 3)))

        assert not any(outcomes)
        assert (
            await _count(
                BattleParticipant,
                BattleParticipant.battle_id == uuid.UUID(battle["id"]),
            )
            == 2
        )


class TestFinalizationRace:
    async def test_simultaneous_final_submissions_produce_one_outcome(
        self, live_client
    ) -> None:  # type: ignore[no-untyped-def]
        """Both players post the evidence that ends a one-day battle, at the same time.

        Either submission can be the one that closes it. The lock decides which, and
        there is exactly one winner, one loser and one win bonus either way.
        """
        (alpha_id, alpha), (bravo_id, bravo), group = await _pair(live_client)
        battle = await _open_battle(live_client, alpha, bravo_id, group)
        await live_client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo)

        first, second = await asyncio.gather(
            _verify(live_client, alpha, battle["id"], "12000"),
            _verify(live_client, bravo, battle["id"], "11000"),
        )

        assert first.status_code == 200, first.text
        assert second.status_code == 200, second.text
        async with _session_factory() as session:
            rows = (
                await session.execute(
                    select(BattleParticipant).where(
                        BattleParticipant.battle_id == uuid.UUID(battle["id"])
                    )
                )
            ).scalars().all()
            statuses = sorted(row.status.value for row in rows)
            assert statuses == ["lost", "won"]
            winner = next(
                row for row in rows if row.status is BattleParticipantStatus.WON
            )
            assert winner.user_id == alpha_id  # 12000 beats 11000

        assert (
            await _count(
                XPTransaction,
                XPTransaction.reason == XPReason.BATTLE_WIN,
                XPTransaction.reference_id == uuid.UUID(battle["id"]),
            )
            == 1
        )

    async def test_a_storm_of_reads_finalizes_the_battle_once(self, live_client) -> None:  # type: ignore[no-untyped-def]
        """Reads sweep, so ten simultaneous reads all try to finalize. One does."""
        (alpha_id, alpha), (bravo_id, bravo), group = await _pair(live_client)
        battle = await _open_battle(live_client, alpha, bravo_id, group)
        await live_client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo)
        await _verify(live_client, alpha, battle["id"], "12000")

        # Bravo's completion makes the battle finalizable; then everyone reads at once.
        await _verify(live_client, bravo, battle["id"], "11000")
        reads = await asyncio.gather(
            *(
                live_client.get(f"/api/v1/battles/{battle['id']}", headers=headers)
                for headers in (alpha, bravo) * 5
            )
        )

        bodies = [r.json() for r in reads]
        assert {b["winner_user_id"] for b in bodies} == {str(alpha_id)}
        assert len({b["completed_at"] for b in bodies}) == 1
        assert (
            await _count(
                XPTransaction,
                XPTransaction.reason == XPReason.BATTLE_WIN,
                XPTransaction.reference_id == uuid.UUID(battle["id"]),
            )
            == 1
        )

    async def test_duplicate_verifications_racing_award_daily_xp_once(
        self, live_client
    ) -> None:  # type: ignore[no-untyped-def]
        """Five identical submissions on five connections; one day's XP."""
        (alpha_id, alpha), (bravo_id, bravo), group = await _pair(live_client)
        battle = await _open_battle(live_client, alpha, bravo_id, group, duration_days=5)
        await live_client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo)

        await asyncio.gather(
            *(_verify(live_client, alpha, battle["id"], "12000") for _ in range(5)),
            return_exceptions=True,
        )

        assert (
            await _count(
                XPTransaction,
                XPTransaction.user_id == alpha_id,
                XPTransaction.reason == XPReason.DAILY_COMPLETION,
            )
            == 1
        )
        async with _session_factory() as session:
            score = (
                await session.execute(
                    select(ChallengeParticipant.current_score).where(
                        ChallengeParticipant.user_id == alpha_id
                    )
                )
            ).scalar_one()
            assert Decimal(score) == Decimal(12000)

    async def test_late_evidence_after_finalization_changes_nothing(
        self, live_client
    ) -> None:  # type: ignore[no-untyped-def]
        (alpha_id, alpha), (bravo_id, bravo), group = await _pair(live_client)
        battle = await _open_battle(live_client, alpha, bravo_id, group)
        await live_client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo)
        await _verify(live_client, alpha, battle["id"], "12000")
        await _verify(live_client, bravo, battle["id"], "11000")

        late = await asyncio.gather(
            *(_verify(live_client, bravo, battle["id"], "999999") for _ in range(3)),
            return_exceptions=True,
        )

        assert all(getattr(r, "status_code", None) == 409 for r in late)
        after = (
            await live_client.get(f"/api/v1/battles/{battle['id']}", headers=bravo)
        ).json()
        assert after["winner_user_id"] == str(alpha_id)
        their_side = next(
            side for side in after["sides"] if side["user_id"] == str(bravo_id)
        )
        assert Decimal(their_side["score"]) == Decimal(11000)
