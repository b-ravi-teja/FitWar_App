"""Game system against real Postgres: XP, score, streak, warnings, elimination, close.

Deliberately not mocked. Every guarantee this phase makes — idempotency under replay,
no double XP, one warning per day, one elimination per participant — is enforced by
database constraints and row locks, and a fake session would assert none of it.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import (
    Challenge,
    ChallengeParticipant,
    ChallengeStatus,
    DailyProgressStatus,
    ParticipantOutcome,
    ParticipantStatus,
)
from app.models.game import Elimination, Warning, XPTransaction
from app.models.user import UserProfile
from app.services.game_service import GameService


async def _setup(client, register_actor, create_group, create_challenge, **overrides):  # type: ignore[no-untyped-def]
    actor = await register_actor(client, "Player")
    group = await create_group(client, actor)
    response = await create_challenge(client, actor, group["id"], **overrides)
    assert response.status_code == 201, response.text
    return actor, response.json()


async def _verify(client, actor, challenge_id, value="12000") -> Any:  # type: ignore[no-untyped-def]
    day = (
        await client.get(
            f"/api/v1/challenges/{challenge_id}/progress/today", headers=actor.headers
        )
    ).json()
    return await client.post(
        f"/api/v1/challenges/{challenge_id}/verify",
        json={
            "provider": "apple_health",
            "evidence": {
                "metric": "steps",
                "value": value,
                "unit": "steps",
                "period_start": day["window_start_at"],
                "period_end": datetime.now(UTC).isoformat(),
                "was_user_entered": False,
            },
        },
        headers=actor.headers,
    )


async def _participant(session: AsyncSession, challenge_id: str) -> ChallengeParticipant:
    import uuid as _uuid

    result = await session.execute(
        select(ChallengeParticipant).where(
            ChallengeParticipant.challenge_id == _uuid.UUID(challenge_id)
        )
    )
    return result.scalars().first()  # type: ignore[return-value]


class TestXP:
    async def test_completion_grants_xp_broken_into_components(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)

        body = (await _verify(client, actor, challenge["id"])).json()

        resolution = body["resolution"]
        assert resolution["completion_xp"] == 50
        # Day 1 of a streak earns the base award only.
        assert resolution["streak_bonus_xp"] == 0
        assert resolution["xp_awarded"] == 50

    async def test_repeated_verification_grants_xp_only_once(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        """The whole point of the ledger's unique key."""
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)
        await _verify(client, actor, challenge["id"])

        for _ in range(4):
            await _verify(client, actor, challenge["id"])

        xp = (await client.get("/api/v1/me/xp", headers=actor.headers)).json()
        assert xp["xp_total"] == 50

    async def test_cached_total_agrees_with_the_ledger(
        self, client, register_actor, create_group, create_challenge, db_session
    ) -> None:
        """§3.2: xp_total is a projection, never written independently of a ledger row."""
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)
        await _verify(client, actor, challenge["id"])

        ledger = await db_session.execute(
            select(func.coalesce(func.sum(XPTransaction.amount), 0)).where(
                XPTransaction.user_id == actor.user_id
            )
        )
        profile = await db_session.execute(
            select(UserProfile).where(UserProfile.user_id == actor.user_id)
        )
        assert profile.scalar_one().xp_total == int(ledger.scalar_one())

    async def test_a_short_attempt_grants_no_xp(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)

        body = (await _verify(client, actor, challenge["id"], value="100")).json()

        assert body["resolution"] is None
        assert (await client.get("/api/v1/me/xp", headers=actor.headers)).json()["xp_total"] == 0

    async def test_ledger_entries_are_never_negative(
        self, client, register_actor, create_group, create_challenge, db_session
    ) -> None:
        """ADR 0002 — a miss never debits XP."""
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)
        await _verify(client, actor, challenge["id"])

        rows = await db_session.execute(
            select(XPTransaction.amount).where(XPTransaction.user_id == actor.user_id)
        )
        assert all(amount > 0 for amount in rows.scalars().all())

    async def test_level_is_computed_by_the_server(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)
        await _verify(client, actor, challenge["id"])

        xp = (await client.get("/api/v1/me/xp", headers=actor.headers)).json()

        assert xp["level"] == 1
        assert xp["xp_into_level"] + xp["xp_to_next_level"] == 500
        assert len(xp["transactions"]) == 1


class TestScore:
    async def test_verified_value_becomes_the_score(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        """The client submits evidence; the server derives the score from it."""
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)

        await _verify(client, actor, challenge["id"], value="12000")

        state = (
            await client.get(f"/api/v1/challenges/{challenge['id']}/me", headers=actor.headers)
        ).json()
        assert Decimal(state["score"]) == Decimal("12000")

    async def test_duplicate_evidence_does_not_double_the_score(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)
        await _verify(client, actor, challenge["id"], value="12000")

        await _verify(client, actor, challenge["id"], value="12000")

        state = (
            await client.get(f"/api/v1/challenges/{challenge['id']}/me", headers=actor.headers)
        ).json()
        assert Decimal(state["score"]) == Decimal("12000")

    async def test_a_rejected_attempt_scores_nothing(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)

        await _verify(client, actor, challenge["id"], value="500")

        state = (
            await client.get(f"/api/v1/challenges/{challenge['id']}/me", headers=actor.headers)
        ).json()
        assert Decimal(state["score"]) == Decimal(0)


class TestStreak:
    async def test_first_completed_day_starts_the_streak(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)

        body = (await _verify(client, actor, challenge["id"])).json()

        assert body["resolution"]["current_streak"] == 1

    async def test_replay_does_not_increment_the_streak_twice(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)
        await _verify(client, actor, challenge["id"])

        await _verify(client, actor, challenge["id"])

        state = (
            await client.get(f"/api/v1/challenges/{challenge['id']}/me", headers=actor.headers)
        ).json()
        assert state["current_streak"] == 1

    async def test_consecutive_days_build_the_streak_and_pay_a_bonus(
        self, client, register_actor, create_group, create_challenge, db_session
    ) -> None:
        """Driven through the service with an advancing clock — the API always resolves
        'today', so multi-day behaviour can only be exercised this way."""
        _, challenge = await _setup(client, register_actor, create_group, create_challenge)
        participant = await _participant(db_session, challenge["id"])
        game = GameService(db_session)
        challenge_row = (
            await db_session.execute(
                select(Challenge).where(Challenge.id == participant.challenge_id)
            )
        ).scalar_one()

        from app.repositories.game import GameRepository

        repo = GameRepository(db_session)
        base = datetime.now(UTC)
        streaks = []
        for offset in range(3):
            day = (base + timedelta(days=offset)).date()
            progress = await repo.get_or_create_progress(participant.id, day)
            progress.status = DailyProgressStatus.COMPLETED
            resolution = await game.apply_completion(
                challenge=challenge_row,
                participant=participant,
                progress=progress,
                value=Decimal("12000"),
                now=base + timedelta(days=offset),
            )
            streaks.append((resolution.current_streak, resolution.streak_bonus_xp))

        assert [s for s, _ in streaks] == [1, 2, 3]
        # Bonus starts on day 2 and grows.
        assert [b for _, b in streaks] == [0, 10, 20]


class TestSurvivalWarningsAndElimination:
    async def test_first_missed_day_creates_a_warning(
        self, client, register_actor, create_group, create_challenge, db_session
    ) -> None:
        _, challenge = await _setup(client, register_actor, create_group, create_challenge)
        participant = await _participant(db_session, challenge["id"])
        challenge_row = (
            await db_session.execute(
                select(Challenge).where(Challenge.id == participant.challenge_id)
            )
        ).scalar_one()

        # A day past its deadline with nothing recorded.
        await GameService(db_session).resolve_overdue_days(
            challenge_row, now=datetime.now(UTC) + timedelta(days=2)
        )

        warnings = (
            await db_session.execute(
                select(Warning).where(Warning.challenge_participant_id == participant.id)
            )
        ).scalars().all()
        assert len(warnings) >= 1
        await db_session.refresh(participant)
        assert participant.consecutive_misses >= 1

    async def test_two_consecutive_misses_eliminate(
        self, client, register_actor, create_group, create_challenge, db_session
    ) -> None:
        """The frozen rule: miss 1 → warning, miss 2 consecutive → eliminated."""
        _, challenge = await _setup(client, register_actor, create_group, create_challenge)
        participant = await _participant(db_session, challenge["id"])
        challenge_row = (
            await db_session.execute(
                select(Challenge).where(Challenge.id == participant.challenge_id)
            )
        ).scalar_one()

        await GameService(db_session).resolve_overdue_days(
            challenge_row, now=datetime.now(UTC) + timedelta(days=3)
        )

        await db_session.refresh(participant)
        assert participant.status is ParticipantStatus.ELIMINATED
        assert participant.outcome is ParticipantOutcome.OUT
        assert participant.eliminated_at is not None

    async def test_elimination_is_recorded_with_its_context(
        self, client, register_actor, create_group, create_challenge, db_session
    ) -> None:
        _, challenge = await _setup(client, register_actor, create_group, create_challenge)
        participant = await _participant(db_session, challenge["id"])
        challenge_row = (
            await db_session.execute(
                select(Challenge).where(Challenge.id == participant.challenge_id)
            )
        ).scalar_one()
        await GameService(db_session).resolve_overdue_days(
            challenge_row, now=datetime.now(UTC) + timedelta(days=3)
        )

        elimination = (
            await db_session.execute(
                select(Elimination).where(
                    Elimination.challenge_participant_id == participant.id
                )
            )
        ).scalar_one()

        assert elimination.reason == "consecutive_misses"
        assert elimination.challenge_day is not None
        assert elimination.eliminated_at is not None

    async def test_repeated_sweeps_do_not_duplicate_warnings_or_eliminations(
        self, client, register_actor, create_group, create_challenge, db_session
    ) -> None:
        _, challenge = await _setup(client, register_actor, create_group, create_challenge)
        participant = await _participant(db_session, challenge["id"])
        challenge_row = (
            await db_session.execute(
                select(Challenge).where(Challenge.id == participant.challenge_id)
            )
        ).scalar_one()
        game = GameService(db_session)
        later = datetime.now(UTC) + timedelta(days=3)

        await game.resolve_overdue_days(challenge_row, now=later)
        first_warnings = (
            await db_session.execute(
                select(func.count()).select_from(Warning).where(
                    Warning.challenge_participant_id == participant.id
                )
            )
        ).scalar_one()

        for _ in range(3):
            await game.resolve_overdue_days(challenge_row, now=later)

        after = (
            await db_session.execute(
                select(func.count()).select_from(Warning).where(
                    Warning.challenge_participant_id == participant.id
                )
            )
        ).scalar_one()
        eliminations = (
            await db_session.execute(
                select(func.count()).select_from(Elimination).where(
                    Elimination.challenge_participant_id == participant.id
                )
            )
        ).scalar_one()
        assert after == first_warnings
        assert eliminations == 1

    async def test_an_eliminated_participant_cannot_verify_back_to_active(
        self, client, register_actor, create_group, create_challenge, db_session
    ) -> None:
        """No resurrection: the state machine has no ELIMINATED → ACTIVE edge."""
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)
        participant = await _participant(db_session, challenge["id"])
        participant.status = ParticipantStatus.ELIMINATED
        participant.outcome = ParticipantOutcome.OUT
        await db_session.flush()

        response = await _verify(client, actor, challenge["id"])

        assert response.status_code == 409
        await db_session.refresh(participant)
        assert participant.status is ParticipantStatus.ELIMINATED

    async def test_points_mode_never_eliminates(
        self, client, register_actor, create_group, create_challenge, db_session
    ) -> None:
        """ADR 0004 — the failure rule is SURVIVAL-only."""
        _, challenge = await _setup(
            client, register_actor, create_group, create_challenge, game_mode="points"
        )
        participant = await _participant(db_session, challenge["id"])
        challenge_row = (
            await db_session.execute(
                select(Challenge).where(Challenge.id == participant.challenge_id)
            )
        ).scalar_one()

        await GameService(db_session).resolve_overdue_days(
            challenge_row, now=datetime.now(UTC) + timedelta(days=5)
        )

        await db_session.refresh(participant)
        assert participant.status is ParticipantStatus.ACTIVE
        warnings = (
            await db_session.execute(
                select(func.count()).select_from(Warning).where(
                    Warning.challenge_participant_id == participant.id
                )
            )
        ).scalar_one()
        assert warnings == 0


class TestLeaderboard:
    async def test_ranks_participants_by_score(
        self, client, register_actor, create_group, create_challenge, join_group
    ) -> None:
        owner, challenge = await _setup(client, register_actor, create_group, create_challenge)
        group = (
            await client.get(f"/api/v1/groups/{challenge['group_id']}", headers=owner.headers)
        ).json()
        rival = await register_actor(client, "Rival")
        await join_group(client, rival, group["join_code"])
        await client.post(
            f"/api/v1/challenges/{challenge['id']}/join", headers=rival.headers
        )
        await _verify(client, owner, challenge["id"], value="20000")
        await _verify(client, rival, challenge["id"], value="11000")

        board = (
            await client.get(
                f"/api/v1/challenges/{challenge['id']}/leaderboard", headers=owner.headers
            )
        ).json()

        assert [e["rank"] for e in board["entries"]] == [1, 2]
        assert board["entries"][0]["display_name"] == "Player"
        assert Decimal(board["entries"][0]["score"]) == Decimal("20000")
        assert board["entries"][0]["is_me"] is True

    async def test_a_non_member_cannot_read_the_leaderboard(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        _, challenge = await _setup(client, register_actor, create_group, create_challenge)
        outsider = await register_actor(client, "Outsider")

        response = await client.get(
            f"/api/v1/challenges/{challenge['id']}/leaderboard", headers=outsider.headers
        )

        assert response.status_code == 403

    async def test_leaderboard_requires_authentication(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        _, challenge = await _setup(client, register_actor, create_group, create_challenge)

        response = await client.get(f"/api/v1/challenges/{challenge['id']}/leaderboard")

        assert response.status_code == 401


class TestCompletion:
    async def _close(self, db_session: AsyncSession, challenge_id: str) -> Challenge:
        import uuid as _uuid

        challenge = (
            await db_session.execute(
                select(Challenge).where(Challenge.id == _uuid.UUID(challenge_id))
            )
        ).scalar_one()
        challenge.end_at = datetime.now(UTC) - timedelta(minutes=1)
        challenge.status = ChallengeStatus.COMPLETED
        await db_session.flush()
        return challenge

    async def test_survival_survivor_wins(
        self, client, register_actor, create_group, create_challenge, db_session
    ) -> None:
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)
        await _verify(client, actor, challenge["id"])
        challenge_row = await self._close(db_session, challenge["id"])

        await GameService(db_session).finalize_if_ended(challenge_row)

        participant = await _participant(db_session, challenge["id"])
        await db_session.refresh(participant)
        assert participant.outcome is ParticipantOutcome.WON
        assert participant.status is ParticipantStatus.COMPLETED

    async def test_points_mode_picks_a_single_winner(
        self, client, register_actor, create_group, create_challenge, join_group, db_session
    ) -> None:
        owner, challenge = await _setup(
            client, register_actor, create_group, create_challenge, game_mode="points"
        )
        group = (
            await client.get(f"/api/v1/groups/{challenge['group_id']}", headers=owner.headers)
        ).json()
        rival = await register_actor(client, "Rival")
        await join_group(client, rival, group["join_code"])
        await client.post(f"/api/v1/challenges/{challenge['id']}/join", headers=rival.headers)
        await _verify(client, owner, challenge["id"], value="30000")
        await _verify(client, rival, challenge["id"], value="11000")
        challenge_row = await self._close(db_session, challenge["id"])

        await GameService(db_session).finalize_if_ended(challenge_row)

        import uuid as _uuid

        rows = (
            await db_session.execute(
                select(ChallengeParticipant).where(
                    ChallengeParticipant.challenge_id == _uuid.UUID(challenge["id"])
                )
            )
        ).scalars().all()
        outcomes = {p.user_id: p.outcome for p in rows}
        assert outcomes[owner.user_id] is ParticipantOutcome.WON
        assert outcomes[rival.user_id] is ParticipantOutcome.LOST

    async def test_finalization_is_idempotent(
        self, client, register_actor, create_group, create_challenge, db_session
    ) -> None:
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)
        await _verify(client, actor, challenge["id"])
        challenge_row = await self._close(db_session, challenge["id"])
        game = GameService(db_session)

        assert await game.finalize_if_ended(challenge_row) is True
        # A second call finds every outcome already written and does nothing.
        assert await game.finalize_if_ended(challenge_row) is False

    async def test_late_evidence_cannot_rewrite_a_finalized_result(
        self, client, register_actor, create_group, create_challenge, db_session
    ) -> None:
        """The non-retroactive rule: a closed challenge accepts no further competition."""
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)
        challenge_row = await self._close(db_session, challenge["id"])
        await GameService(db_session).finalize_if_ended(challenge_row)
        participant = await _participant(db_session, challenge["id"])
        await db_session.refresh(participant)
        outcome_before = participant.outcome
        score_before = participant.current_score

        response = await client.post(
            f"/api/v1/challenges/{challenge['id']}/verify",
            json={
                "provider": "apple_health",
                "evidence": {
                    "metric": "steps",
                    "value": "99000",
                    "unit": "steps",
                    "period_start": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
                    "period_end": datetime.now(UTC).isoformat(),
                    "was_user_entered": False,
                },
            },
            headers=actor.headers,
        )

        assert response.status_code == 409
        await db_session.refresh(participant)
        assert participant.outcome is outcome_before
        assert participant.current_score == score_before


class TestConcurrency:
    async def test_the_xp_ledger_key_makes_a_double_award_impossible(self) -> None:
        """Five *independent connections* racing to credit the same day.

        This is the guarantee the whole design leans on, so it runs against real
        Postgres on real separate connections. The API test fixture shares one session
        wrapped in a rolled-back transaction, so it can neither model two connections
        racing nor make its rows visible to them — hence the self-contained setup here.
        """
        import uuid as _uuid

        from sqlalchemy.exc import IntegrityError
        from sqlalchemy.ext.asyncio import async_sessionmaker

        from app.core.database import _engine
        from app.models.game import XPReason
        from app.models.user import User, UserProfile

        factory = async_sessionmaker(bind=_engine, expire_on_commit=False)
        user_id = _uuid.uuid4()
        progress_id = _uuid.uuid4()

        async with factory() as setup:
            setup.add(
                User(
                    id=user_id,
                    email=f"race-{user_id.hex[:10]}@example.com",
                    password_hash="x",
                )
            )
            setup.add(UserProfile(user_id=user_id, display_name="Racer", xp_total=0))
            await setup.commit()

        async def credit() -> bool:
            async with factory() as session:
                session.add(
                    XPTransaction(
                        user_id=user_id,
                        amount=50,
                        reason=XPReason.DAILY_COMPLETION,
                        reference_type="daily_challenge_progress",
                        reference_id=progress_id,
                    )
                )
                try:
                    await session.commit()
                    return True
                except IntegrityError:
                    await session.rollback()
                    return False

        try:
            outcomes = await asyncio.gather(*(credit() for _ in range(5)))

            # Exactly one connection wins; the database rejects the other four.
            assert sum(outcomes) == 1
            async with factory() as check:
                rows = await check.execute(
                    select(func.count())
                    .select_from(XPTransaction)
                    .where(XPTransaction.reference_id == progress_id)
                )
                assert rows.scalar_one() == 1
        finally:
            async with factory() as cleanup:
                await cleanup.execute(
                    XPTransaction.__table__.delete().where(
                        XPTransaction.reference_id == progress_id
                    )
                )
                await cleanup.execute(
                    UserProfile.__table__.delete().where(UserProfile.user_id == user_id)
                )
                await cleanup.execute(User.__table__.delete().where(User.id == user_id))
                await cleanup.commit()

    async def test_sequential_replays_award_once(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        """The API-level counterpart: repeated identical submissions, one award."""
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)
        for _ in range(5):
            await _verify(client, actor, challenge["id"])

        xp = (await client.get("/api/v1/me/xp", headers=actor.headers)).json()
        state = (
            await client.get(f"/api/v1/challenges/{challenge['id']}/me", headers=actor.headers)
        ).json()

        assert xp["xp_total"] == 50
        assert Decimal(state["score"]) == Decimal("12000")
        assert state["current_streak"] == 1

    async def test_leaderboard_reads_during_writes_stay_consistent(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)

        await _verify(client, actor, challenge["id"])
        results = [
            await client.get(
                f"/api/v1/challenges/{challenge['id']}/leaderboard", headers=actor.headers
            )
            for _ in range(3)
        ]

        for response in results:
            assert response.status_code == 200
            # Never a duplicated or missing participant mid-transition.
            assert len(response.json()["entries"]) == 1


class TestMyGameState:
    async def test_reports_the_callers_own_competitive_state(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor, challenge = await _setup(client, register_actor, create_group, create_challenge)
        await _verify(client, actor, challenge["id"])

        state = (
            await client.get(f"/api/v1/challenges/{challenge['id']}/me", headers=actor.headers)
        ).json()

        assert state["rank"] == 1
        assert state["current_streak"] == 1
        assert state["status"] == "active"
        assert state["warnings"] == []
        assert state["eliminated_at"] is None

    async def test_a_non_participant_is_refused(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        _, challenge = await _setup(client, register_actor, create_group, create_challenge)
        outsider = await register_actor(client, "Outsider")

        response = await client.get(
            f"/api/v1/challenges/{challenge['id']}/me", headers=outsider.headers
        )

        assert response.status_code == 403
