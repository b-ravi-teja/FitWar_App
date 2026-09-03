"""1v1 battles end to end against real Postgres.

Nothing here is mocked. The guarantees Phase 7 makes — exactly two players, one
authoritative outcome, one win bonus, no third-party access — are enforced by
constraints and locks, and a fake session would assert none of them.
"""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.battle import Battle, BattleParticipant
from app.models.challenge import Challenge, ChallengeParticipant, ChallengeStatus, GameMode
from app.models.game import XPReason, XPTransaction
from app.models.user import UserProfile

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _squad(client, register_actor, create_group, join_group, size: int = 2):  # type: ignore[no-untyped-def]
    """A group with `size` members. The first is the owner."""
    actors = [await register_actor(client, f"Player{index}") for index in range(size)]
    group = await create_group(client, actors[0])
    for actor in actors[1:]:
        response = await join_group(client, actor, group["join_code"])
        assert response.status_code == 200, response.text
    return actors, group


async def _create_battle(client, actor, opponent, group, **overrides) -> Any:  # type: ignore[no-untyped-def]
    payload: dict[str, Any] = {
        "opponent_user_id": str(opponent.user_id),
        "activity_type": "steps",
        "target_value": "10000",
        "duration_days": 1,
        "group_id": group["id"],
    }
    payload.update(overrides)
    return await client.post("/api/v1/battles", json=payload, headers=actor.headers)


async def _verify(client, actor, battle_id, value="12000") -> Any:  # type: ignore[no-untyped-def]
    """Submit today's steps through the battle's own verify endpoint.

    The window comes from the battle response, which the server computed from the
    battle's frozen timezone — never from the test's own clock arithmetic.
    """
    battle = (
        await client.get(f"/api/v1/battles/{battle_id}", headers=actor.headers)
    ).json()
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
        headers=actor.headers,
    )


async def _played_battle(client, register_actor, create_group, join_group, **overrides):  # type: ignore[no-untyped-def]
    """A finished 1-day battle: A scores 12000, B scores 11000, A wins."""
    (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
    battle = (await _create_battle(client, alpha, bravo, group, **overrides)).json()
    await client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers)
    await _verify(client, alpha, battle["id"], value="12000")
    final = (await _verify(client, bravo, battle["id"], value="11000")).json()
    return alpha, bravo, group, final["battle"]


def _side(battle: dict[str, Any], user_id: uuid.UUID) -> dict[str, Any]:
    return next(side for side in battle["sides"] if side["user_id"] == str(user_id))


# ---------------------------------------------------------------------------


class TestCreation:
    async def test_a_battle_starts_pending_with_exactly_two_sides(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)

        response = await _create_battle(client, alpha, bravo, group)

        assert response.status_code == 201, response.text
        body = response.json()
        assert body["status"] == "pending"
        assert len(body["sides"]) == 2
        assert {side["user_id"] for side in body["sides"]} == {
            str(alpha.user_id),
            str(bravo.user_id),
        }
        assert _side(body, alpha.user_id)["status"] == "accepted"
        assert _side(body, bravo.user_id)["status"] == "invited"

    async def test_scores_start_at_zero_and_no_winner_exists_yet(
        self, client, register_actor, create_group, join_group
    ) -> None:
        """A "current winner" before finalization is exactly the mutable source of
        truth §8 forbids — there is no field for one until the battle is decided."""
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)

        body = (await _create_battle(client, alpha, bravo, group)).json()

        assert body["winner_user_id"] is None
        assert body["my_outcome"] is None
        assert all(Decimal(side["score"]) == 0 for side in body["sides"])

    async def test_the_target_defaults_when_omitted(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)

        body = (
            await _create_battle(client, alpha, bravo, group, target_value=None)
        ).json()

        assert Decimal(body["target_value"]) == Decimal(10_000)

    async def test_the_group_is_inferred_when_only_one_is_shared(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        payload = {
            "opponent_user_id": str(bravo.user_id),
            "activity_type": "steps",
            "duration_days": 3,
        }

        response = await client.post("/api/v1/battles", json=payload, headers=alpha.headers)

        assert response.status_code == 201, response.text
        assert response.json()["group_id"] == group["id"]

    async def test_sharing_several_squads_asks_rather_than_guessing(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), _first = await _squad(
            client, register_actor, create_group, join_group
        )
        second = await create_group(client, alpha, name="SECOND SQUAD")
        assert (await join_group(client, bravo, second["join_code"])).status_code == 200

        response = await client.post(
            "/api/v1/battles",
            json={
                "opponent_user_id": str(bravo.user_id),
                "activity_type": "steps",
                "duration_days": 3,
            },
            headers=alpha.headers,
        )

        assert response.status_code == 409
        assert response.json()["code"] == "GROUP_REQUIRED"

    async def test_a_stranger_cannot_be_challenged(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, _), group = await _squad(client, register_actor, create_group, join_group)
        stranger = await register_actor(client, "Stranger")

        response = await _create_battle(client, alpha, stranger, group)

        assert response.status_code == 403
        assert response.json()["code"] == "OPPONENT_NOT_AVAILABLE"

    async def test_a_nonexistent_user_gives_the_same_answer_as_a_stranger(
        self, client, register_actor, create_group, join_group
    ) -> None:
        """Otherwise `POST /battles` is an account-existence oracle."""
        (alpha, _), group = await _squad(client, register_actor, create_group, join_group)

        response = await client.post(
            "/api/v1/battles",
            json={
                "opponent_user_id": str(uuid.uuid4()),
                "activity_type": "steps",
                "duration_days": 1,
                "group_id": group["id"],
            },
            headers=alpha.headers,
        )

        assert response.status_code == 403
        assert response.json()["code"] == "OPPONENT_NOT_AVAILABLE"

    async def test_you_cannot_battle_yourself(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, _), group = await _squad(client, register_actor, create_group, join_group)

        response = await _create_battle(client, alpha, alpha, group)

        assert response.status_code == 403

    async def test_an_activity_health_cannot_measure_is_refused(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)

        response = await _create_battle(client, alpha, bravo, group, activity_type="pushups")

        assert response.status_code == 409
        assert response.json()["code"] == "INVALID_BATTLE_CONFIG"

    async def test_a_second_live_battle_with_the_same_player_is_refused(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        assert (await _create_battle(client, alpha, bravo, group)).status_code == 201

        response = await _create_battle(client, alpha, bravo, group)

        assert response.status_code == 409
        assert response.json()["code"] == "ALREADY_PENDING_WITH_USER"

    async def test_the_reverse_invitation_is_the_same_live_battle(
        self, client, register_actor, create_group, join_group
    ) -> None:
        """`pair_key` is symmetric, so B cannot open a second one back at A."""
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        assert (await _create_battle(client, alpha, bravo, group)).status_code == 201

        response = await _create_battle(client, bravo, alpha, group)

        assert response.status_code == 409

    async def test_a_rematch_is_allowed_once_the_first_battle_is_over(
        self, client, register_actor, create_group, join_group
    ) -> None:
        """The live-pair index is partial — history never blocks the next fight."""
        alpha, bravo, group, battle = await _played_battle(
            client, register_actor, create_group, join_group
        )
        assert battle["status"] == "completed"

        response = await _create_battle(client, alpha, bravo, group)

        assert response.status_code == 201


class TestExactlyTwoParticipants:
    async def test_the_backing_challenge_is_invisible_to_the_challenge_api(
        self, client, register_actor, create_group, join_group, db_session: AsyncSession
    ) -> None:
        """The hole this closes: `POST /challenges/{id}/join` would otherwise put a
        third player into a 1v1."""
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group)).json()
        challenge_id = (
            await db_session.execute(
                select(Battle.challenge_id).where(Battle.id == uuid.UUID(battle["id"]))
            )
        ).scalar_one()

        assert (
            await client.get(f"/api/v1/challenges/{challenge_id}", headers=alpha.headers)
        ).status_code == 404
        join = await client.post(
            f"/api/v1/challenges/{challenge_id}/join", headers=alpha.headers
        )
        assert join.status_code == 404

    async def test_an_outsider_cannot_join_the_backing_challenge(
        self, client, register_actor, create_group, join_group, db_session: AsyncSession
    ) -> None:
        (alpha, bravo, charlie), group = await _squad(
            client, register_actor, create_group, join_group, size=3
        )
        battle = (await _create_battle(client, alpha, bravo, group)).json()
        challenge_id = (
            await db_session.execute(
                select(Battle.challenge_id).where(Battle.id == uuid.UUID(battle["id"]))
            )
        ).scalar_one()

        response = await client.post(
            f"/api/v1/challenges/{challenge_id}/join", headers=charlie.headers
        )

        assert response.status_code == 404
        count = (
            await db_session.execute(
                select(func.count())
                .select_from(ChallengeParticipant)
                .where(ChallengeParticipant.challenge_id == challenge_id)
            )
        ).scalar_one()
        assert count == 1  # only the challenger, until the opponent accepts

    async def test_a_battle_never_appears_in_the_wars_list(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        await _create_battle(client, alpha, bravo, group)

        mine = (await client.get("/api/v1/challenges", headers=alpha.headers)).json()
        in_group = (
            await client.get(
                f"/api/v1/groups/{group['id']}/challenges", headers=alpha.headers
            )
        ).json()

        assert mine == []
        assert in_group == []

    async def test_a_1v1_challenge_cannot_be_created_through_the_challenge_api(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor = await register_actor(client, "Solo")
        group = await create_group(client, actor)

        response = await create_challenge(client, actor, group["id"], game_mode="1v1")

        assert response.status_code == 409
        assert response.json()["code"] == "INVALID_CHALLENGE_CONFIG"

    async def test_the_slot_constraint_refuses_a_third_row(
        self, client, register_actor, create_group, join_group, db_session: AsyncSession
    ) -> None:
        """The structural guarantee, asserted directly: no service code involved."""
        from sqlalchemy.exc import IntegrityError

        (alpha, bravo, charlie), group = await _squad(
            client, register_actor, create_group, join_group, size=3
        )
        battle = (await _create_battle(client, alpha, bravo, group)).json()

        db_session.add(
            BattleParticipant(
                battle_id=uuid.UUID(battle["id"]),
                user_id=charlie.user_id,
                slot=3,
                score=Decimal(0),
            )
        )
        with pytest.raises(IntegrityError):
            await db_session.flush()
        await db_session.rollback()


class TestAcceptance:
    async def test_the_invited_player_can_accept(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group)).json()

        response = await client.post(
            f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers
        )

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["status"] == "active"
        assert all(side["status"] == "active" for side in body["sides"])

    async def test_acceptance_is_idempotent(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group)).json()
        first = await client.post(
            f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers
        )

        second = await client.post(
            f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers
        )

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["start_at"] == first.json()["start_at"]

    async def test_the_challenger_cannot_accept_their_own_invitation(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group)).json()

        response = await client.post(
            f"/api/v1/battles/{battle['id']}/accept", headers=alpha.headers
        )

        assert response.status_code == 409
        assert response.json()["code"] == "NOT_INVITED"

    async def test_a_non_participant_cannot_accept(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo, charlie), group = await _squad(
            client, register_actor, create_group, join_group, size=3
        )
        battle = (await _create_battle(client, alpha, bravo, group)).json()

        response = await client.post(
            f"/api/v1/battles/{battle['id']}/accept", headers=charlie.headers
        )

        assert response.status_code == 404
        assert response.json()["code"] == "BATTLE_NOT_FOUND"

    async def test_a_declined_battle_cannot_be_accepted(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group)).json()
        await client.post(f"/api/v1/battles/{battle['id']}/decline", headers=bravo.headers)

        response = await client.post(
            f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers
        )

        assert response.status_code == 409

    async def test_declining_cancels_the_battle_without_writing_a_result(
        self, client, register_actor, create_group, join_group
    ) -> None:
        """A refused invitation is not a forfeit — nothing was played, so nothing is
        recorded in either player's history."""
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group)).json()

        response = await client.post(
            f"/api/v1/battles/{battle['id']}/decline", headers=bravo.headers
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "cancelled"
        assert body["winner_user_id"] is None
        assert _side(body, bravo.user_id)["status"] == "declined"

    async def test_declining_is_idempotent(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group)).json()
        await client.post(f"/api/v1/battles/{battle['id']}/decline", headers=bravo.headers)

        response = await client.post(
            f"/api/v1/battles/{battle['id']}/decline", headers=bravo.headers
        )

        assert response.status_code == 200
        assert response.json()["status"] == "cancelled"

    async def test_an_active_battle_cannot_be_declined(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group)).json()
        await client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers)

        response = await client.post(
            f"/api/v1/battles/{battle['id']}/decline", headers=bravo.headers
        )

        assert response.status_code == 409
        assert response.json()["code"] == "BATTLE_NOT_PENDING"

    async def test_the_opponent_only_enters_the_challenge_on_acceptance(
        self, client, register_actor, create_group, join_group, db_session: AsyncSession
    ) -> None:
        """Which is also what makes the challenger's `joined_at` earlier — tie-break 4."""
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group)).json()
        challenge_id = (
            await db_session.execute(
                select(Battle.challenge_id).where(Battle.id == uuid.UUID(battle["id"]))
            )
        ).scalar_one()
        await client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers)

        rows = (
            await db_session.execute(
                select(ChallengeParticipant)
                .where(ChallengeParticipant.challenge_id == challenge_id)
                .order_by(ChallengeParticipant.joined_at.asc())
            )
        ).scalars().all()

        assert [row.user_id for row in rows] == [alpha.user_id, bravo.user_id]


class TestScoring:
    async def test_evidence_is_verified_by_the_shared_provider_pipeline(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group, duration_days=5)).json()
        await client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers)

        response = await _verify(client, alpha, battle["id"], value="12000")

        assert response.status_code == 200, response.text
        body = response.json()
        assert body["verification"]["day_status"] == "completed"
        assert body["verification"]["verification"]["provider"] == "apple_health"
        assert Decimal(_side(body["battle"], alpha.user_id)["score"]) == Decimal(12000)

    async def test_short_of_target_scores_nothing_and_leaves_the_day_open(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group, duration_days=5)).json()
        await client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers)

        body = (await _verify(client, alpha, battle["id"], value="500")).json()

        assert body["verification"]["day_status"] == "pending"
        assert Decimal(_side(body["battle"], alpha.user_id)["score"]) == 0

    async def test_invalid_evidence_is_rejected_without_being_recorded(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group, duration_days=5)).json()
        await client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers)

        response = await client.post(
            f"/api/v1/battles/{battle['id']}/verify",
            json={
                "provider": "apple_health",
                "evidence": {
                    "metric": "distance",  # not what this battle measures
                    "value": "12000",
                    "unit": "km",
                    "period_start": datetime.now(UTC).isoformat(),
                    "period_end": datetime.now(UTC).isoformat(),
                    "was_user_entered": False,
                },
            },
            headers=alpha.headers,
        )

        assert response.status_code == 400
        assert response.json()["code"] == "INVALID_EVIDENCE"

    async def test_a_client_supplied_score_has_nowhere_to_go(
        self, client, register_actor, create_group, join_group
    ) -> None:
        """The request schema has no score, winner, XP or rank field — extra keys are
        dropped, and the server derives every number from the evidence itself."""
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group, duration_days=5)).json()
        await client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers)
        window = (
            await client.get(f"/api/v1/battles/{battle['id']}", headers=alpha.headers)
        ).json()

        response = await client.post(
            f"/api/v1/battles/{battle['id']}/verify",
            json={
                "provider": "apple_health",
                "score": "999999",
                "winner_user_id": str(alpha.user_id),
                "xp_awarded": 99999,
                "evidence": {
                    "metric": "steps",
                    "value": "12000",
                    "unit": "steps",
                    "period_start": window["start_at"],
                    "period_end": datetime.now(UTC).isoformat(),
                    "was_user_entered": False,
                },
            },
            headers=alpha.headers,
        )

        body = response.json()
        assert Decimal(_side(body["battle"], alpha.user_id)["score"]) == Decimal(12000)
        assert body["verification"]["resolution"]["xp_awarded"] == 50

    async def test_you_cannot_submit_evidence_for_your_opponent(
        self, client, register_actor, create_group, join_group
    ) -> None:
        """The side evidence lands on comes from the token, never the body."""
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group, duration_days=5)).json()
        await client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers)

        body = (await _verify(client, alpha, battle["id"], value="12000")).json()

        assert Decimal(_side(body["battle"], bravo.user_id)["score"]) == 0

    async def test_a_non_participant_cannot_submit_evidence(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo, charlie), group = await _squad(
            client, register_actor, create_group, join_group, size=3
        )
        battle = (await _create_battle(client, alpha, bravo, group, duration_days=5)).json()
        await client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers)

        # Posted directly rather than through `_verify`, which reads the battle first —
        # a squad-mate cannot even read it, which is the point.
        response = await client.post(
            f"/api/v1/battles/{battle['id']}/verify",
            json={
                "provider": "apple_health",
                "evidence": {
                    "metric": "steps",
                    "value": "12000",
                    "unit": "steps",
                    "period_start": battle["start_at"],
                    "period_end": datetime.now(UTC).isoformat(),
                    "was_user_entered": False,
                },
            },
            headers=charlie.headers,
        )

        assert response.status_code == 404
        assert response.json()["code"] == "BATTLE_NOT_FOUND"

    async def test_a_pending_battle_accepts_no_evidence(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group)).json()

        response = await _verify(client, alpha, battle["id"])

        assert response.status_code == 409
        assert response.json()["code"] == "BATTLE_NOT_ACTIVE"

    async def test_a_replayed_submission_scores_once(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group, duration_days=5)).json()
        await client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers)
        await _verify(client, alpha, battle["id"], value="12000")

        for _ in range(3):
            body = (await _verify(client, alpha, battle["id"], value="12000")).json()

        assert body["verification"]["idempotent_replay"] is True
        assert Decimal(_side(body["battle"], alpha.user_id)["score"]) == Decimal(12000)


class TestOutcome:
    async def test_the_higher_score_wins_and_the_lower_loses(
        self, client, register_actor, create_group, join_group
    ) -> None:
        alpha, bravo, _, battle = await _played_battle(
            client, register_actor, create_group, join_group
        )

        assert battle["status"] == "completed"
        assert battle["winner_user_id"] == str(alpha.user_id)
        assert _side(battle, alpha.user_id)["status"] == "won"
        assert _side(battle, bravo.user_id)["status"] == "lost"

    async def test_both_players_see_the_same_verdict_from_their_own_side(
        self, client, register_actor, create_group, join_group
    ) -> None:
        alpha, bravo, _, battle = await _played_battle(
            client, register_actor, create_group, join_group
        )

        winners_view = (
            await client.get(f"/api/v1/battles/{battle['id']}", headers=alpha.headers)
        ).json()
        losers_view = (
            await client.get(f"/api/v1/battles/{battle['id']}", headers=bravo.headers)
        ).json()

        assert winners_view["my_outcome"] == "won"
        assert losers_view["my_outcome"] == "lost"
        assert winners_view["winner_user_id"] == losers_view["winner_user_id"]

    async def test_a_tied_score_still_produces_exactly_one_winner(
        self, client, register_actor, create_group, join_group
    ) -> None:
        """Equal scores fall through to "who reached it first" — the challenger here,
        because they submitted first. Never a draw (§7)."""
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group)).json()
        await client.post(f"/api/v1/battles/{battle['id']}/accept", headers=bravo.headers)
        await _verify(client, alpha, battle["id"], value="12000")
        final = (await _verify(client, bravo, battle["id"], value="12000")).json()["battle"]

        statuses = sorted(side["status"] for side in final["sides"])
        assert statuses == ["lost", "won"]
        assert final["winner_user_id"] == str(alpha.user_id)

    async def test_a_finalized_result_cannot_be_rewritten_by_later_evidence(
        self, client, register_actor, create_group, join_group
    ) -> None:
        alpha, bravo, _, battle = await _played_battle(
            client, register_actor, create_group, join_group
        )

        late = await _verify(client, bravo, battle["id"], value="999999")

        assert late.status_code == 409
        assert late.json()["code"] == "BATTLE_NOT_ACTIVE"
        after = (
            await client.get(f"/api/v1/battles/{battle['id']}", headers=bravo.headers)
        ).json()
        assert after["winner_user_id"] == str(alpha.user_id)
        assert Decimal(_side(after, bravo.user_id)["score"]) == Decimal(11000)

    async def test_repeated_reads_never_re_decide_the_battle(
        self, client, register_actor, create_group, join_group
    ) -> None:
        alpha, _, _, battle = await _played_battle(
            client, register_actor, create_group, join_group
        )

        seen = set()
        for _ in range(5):
            body = (
                await client.get(f"/api/v1/battles/{battle['id']}", headers=alpha.headers)
            ).json()
            seen.add((body["winner_user_id"], body["completed_at"]))

        assert len(seen) == 1

    async def test_the_outcome_is_mirrored_onto_the_backing_challenge(
        self, client, register_actor, create_group, join_group, db_session: AsyncSession
    ) -> None:
        """§20.3: the 1v1 result is written to both `BattleParticipant.status` and the
        linked `ChallengeParticipant.outcome`."""
        alpha, bravo, _, battle = await _played_battle(
            client, register_actor, create_group, join_group
        )
        challenge_id = (
            await db_session.execute(
                select(Battle.challenge_id).where(Battle.id == uuid.UUID(battle["id"]))
            )
        ).scalar_one()

        rows = (
            await db_session.execute(
                select(ChallengeParticipant).where(
                    ChallengeParticipant.challenge_id == challenge_id
                )
            )
        ).scalars().all()
        challenge = (
            await db_session.execute(select(Challenge).where(Challenge.id == challenge_id))
        ).scalar_one()

        assert challenge.game_mode is GameMode.ONE_V_ONE
        assert challenge.status is ChallengeStatus.COMPLETED
        outcomes = {row.user_id: row.outcome.value for row in rows}
        assert outcomes[alpha.user_id] == "won"
        assert outcomes[bravo.user_id] == "lost"

    async def test_nobody_is_eliminated_in_a_battle(
        self, client, register_actor, create_group, join_group, db_session: AsyncSession
    ) -> None:
        """§20.4: the two-strike failure rule is SURVIVAL-only."""
        from app.models.game import Warning

        _, _, _, battle = await _played_battle(
            client, register_actor, create_group, join_group, duration_days=1
        )
        challenge_id = (
            await db_session.execute(
                select(Battle.challenge_id).where(Battle.id == uuid.UUID(battle["id"]))
            )
        ).scalar_one()

        warnings = (
            await db_session.execute(
                select(func.count())
                .select_from(Warning)
                .join(
                    ChallengeParticipant,
                    ChallengeParticipant.id == Warning.challenge_participant_id,
                )
                .where(ChallengeParticipant.challenge_id == challenge_id)
            )
        ).scalar_one()

        assert warnings == 0


class TestXP:
    async def test_the_winner_is_awarded_the_battle_bonus_exactly_once(
        self, client, register_actor, create_group, join_group, db_session: AsyncSession
    ) -> None:
        alpha, _, _, battle = await _played_battle(
            client, register_actor, create_group, join_group
        )

        rows = (
            await db_session.execute(
                select(XPTransaction).where(
                    XPTransaction.user_id == alpha.user_id,
                    XPTransaction.reason == XPReason.BATTLE_WIN,
                )
            )
        ).scalars().all()

        assert len(rows) == 1
        assert rows[0].amount == 100
        assert rows[0].reference_type == "battle"
        assert rows[0].reference_id == uuid.UUID(battle["id"])

    async def test_the_loser_is_not_debited(
        self, client, register_actor, create_group, join_group, db_session: AsyncSession
    ) -> None:
        """ADR 0002 — the ledger is strictly additive; losing simply earns no bonus."""
        _, bravo, _, _ = await _played_battle(
            client, register_actor, create_group, join_group
        )

        rows = (
            await db_session.execute(
                select(XPTransaction).where(XPTransaction.user_id == bravo.user_id)
            )
        ).scalars().all()

        assert all(row.amount > 0 for row in rows)
        assert not any(row.reason is XPReason.BATTLE_WIN for row in rows)

    async def test_repeated_finalization_attempts_award_nothing_further(
        self, client, register_actor, create_group, join_group, db_session: AsyncSession
    ) -> None:
        alpha, _, _, battle = await _played_battle(
            client, register_actor, create_group, join_group
        )
        for _ in range(5):
            await client.get(f"/api/v1/battles/{battle['id']}", headers=alpha.headers)
            await client.get("/api/v1/battles", headers=alpha.headers)

        total = (
            await db_session.execute(
                select(func.count())
                .select_from(XPTransaction)
                .where(
                    XPTransaction.user_id == alpha.user_id,
                    XPTransaction.reason == XPReason.BATTLE_WIN,
                )
            )
        ).scalar_one()

        assert total == 1

    async def test_the_cached_total_reconciles_with_the_ledger(
        self, client, register_actor, create_group, join_group, db_session: AsyncSession
    ) -> None:
        alpha, _, _, _ = await _played_battle(
            client, register_actor, create_group, join_group
        )

        ledger = (
            await db_session.execute(
                select(func.coalesce(func.sum(XPTransaction.amount), 0)).where(
                    XPTransaction.user_id == alpha.user_id
                )
            )
        ).scalar_one()
        cached = (
            await db_session.execute(
                select(UserProfile.xp_total).where(UserProfile.user_id == alpha.user_id)
            )
        ).scalar_one()

        # 50 daily completion + 100 battle win.
        assert ledger == 150
        assert cached == ledger

    async def test_the_battle_win_appears_in_the_xp_ledger_endpoint(
        self, client, register_actor, create_group, join_group
    ) -> None:
        alpha, _, _, _ = await _played_battle(
            client, register_actor, create_group, join_group
        )

        body = (await client.get("/api/v1/me/xp", headers=alpha.headers)).json()

        assert any(entry["reason"] == "battle_win" for entry in body["transactions"])


class TestAuthorization:
    async def test_a_non_participant_reads_the_same_404_as_a_made_up_id(
        self, client, register_actor, create_group, join_group
    ) -> None:
        """Object ids are not secrets — a stranger must not learn a battle exists."""
        (alpha, bravo, charlie), group = await _squad(
            client, register_actor, create_group, join_group, size=3
        )
        battle = (await _create_battle(client, alpha, bravo, group)).json()

        real = await client.get(
            f"/api/v1/battles/{battle['id']}", headers=charlie.headers
        )
        invented = await client.get(
            f"/api/v1/battles/{uuid.uuid4()}", headers=charlie.headers
        )

        assert real.status_code == invented.status_code == 404
        assert real.json()["code"] == invented.json()["code"] == "BATTLE_NOT_FOUND"

    async def test_battles_are_private_to_their_two_players_not_the_squad(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo, charlie), group = await _squad(
            client, register_actor, create_group, join_group, size=3
        )
        await _create_battle(client, alpha, bravo, group)

        listed = (await client.get("/api/v1/battles", headers=charlie.headers)).json()

        assert listed == []

    async def test_an_unauthenticated_caller_gets_401(self, client: AsyncClient) -> None:
        assert (await client.get("/api/v1/battles")).status_code == 401
        assert (await client.get(f"/api/v1/battles/{uuid.uuid4()}")).status_code == 401


class TestRivals:
    async def test_squad_mates_are_listed_with_their_head_to_head_record(
        self, client, register_actor, create_group, join_group
    ) -> None:
        alpha, bravo, group, _ = await _played_battle(
            client, register_actor, create_group, join_group
        )

        for actor, expected in ((alpha, (1, 0)), (bravo, (0, 1))):
            body = (
                await client.get(
                    "/api/v1/battles/rivals",
                    params={"group_id": group["id"]},
                    headers=actor.headers,
                )
            ).json()
            assert len(body) == 1
            assert (body[0]["wins_against"], body[0]["losses_against"]) == expected

    async def test_a_live_battle_is_surfaced_so_the_ui_does_not_offer_a_duplicate(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)
        battle = (await _create_battle(client, alpha, bravo, group)).json()

        body = (
            await client.get(
                "/api/v1/battles/rivals",
                params={"group_id": group["id"]},
                headers=alpha.headers,
            )
        ).json()

        assert body[0]["live_battle_id"] == battle["id"]

    async def test_the_caller_is_not_their_own_rival(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (alpha, bravo), group = await _squad(client, register_actor, create_group, join_group)

        body = (
            await client.get(
                "/api/v1/battles/rivals",
                params={"group_id": group["id"]},
                headers=alpha.headers,
            )
        ).json()

        assert [rival["user_id"] for rival in body] == [str(bravo.user_id)]

    async def test_a_non_member_cannot_enumerate_a_squad(
        self, client, register_actor, create_group, join_group
    ) -> None:
        (_, _), group = await _squad(client, register_actor, create_group, join_group)
        outsider = await register_actor(client, "Outsider")

        response = await client.get(
            "/api/v1/battles/rivals",
            params={"group_id": group["id"]},
            headers=outsider.headers,
        )

        assert response.status_code == 403


class TestHistory:
    async def test_history_preserves_opponent_result_score_and_time(
        self, client, register_actor, create_group, join_group
    ) -> None:
        alpha, bravo, _, _ = await _played_battle(
            client, register_actor, create_group, join_group
        )

        body = (
            await client.get(
                "/api/v1/battles", params={"status": "completed"}, headers=bravo.headers
            )
        ).json()

        assert len(body) == 1
        record = body[0]
        assert record["my_outcome"] == "lost"
        assert record["winner_user_id"] == str(alpha.user_id)
        assert record["completed_at"] is not None
        assert Decimal(_side(record, alpha.user_id)["score"]) == Decimal(12000)
        assert Decimal(_side(record, bravo.user_id)["score"]) == Decimal(11000)

    async def test_the_list_can_be_filtered_by_status(
        self, client, register_actor, create_group, join_group
    ) -> None:
        alpha, bravo, group, _ = await _played_battle(
            client, register_actor, create_group, join_group
        )
        await _create_battle(client, alpha, bravo, group)  # a fresh, pending rematch

        pending = (
            await client.get(
                "/api/v1/battles", params={"status": "pending"}, headers=alpha.headers
            )
        ).json()
        everything = (await client.get("/api/v1/battles", headers=alpha.headers)).json()

        assert [b["status"] for b in pending] == ["pending"]
        assert len(everything) == 2

    async def test_a_battle_screen_never_exposes_the_opponents_private_record(
        self, client, register_actor, create_group, join_group
    ) -> None:
        """§18: the opponent's competitive numbers, and nothing underneath them."""
        alpha, bravo, _, battle = await _played_battle(
            client, register_actor, create_group, join_group
        )

        body = (
            await client.get(f"/api/v1/battles/{battle['id']}", headers=bravo.headers)
        ).json()

        side = _side(body, alpha.user_id)
        assert set(side) == {
            "user_id",
            "display_name",
            "status",
            "score",
            "days_completed",
            "is_me",
        }
        serialized = str(body)
        for leaked in ("evidence", "media", "raw_payload", "verification", "reason_code"):
            assert leaked not in serialized
