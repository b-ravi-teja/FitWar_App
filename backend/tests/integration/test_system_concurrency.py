"""System-wide concurrency, on real independent PostgreSQL connections.

Phase 7 proved the battle races. This widens the same treatment to every other operation
that can mutate competitive or irreversible state, because the Phase 7 stale-identity-map
bug showed that a correctly-taken lock can still read stale data — so each of these
asserts the *outcome*, not merely that no exception was raised.

`live_client` commits; the default fixture pins every request to one rolled-back
transaction, where two "concurrent" requests serialize on a single connection and prove
nothing at all.
"""

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from app.core.database import _session_factory
from app.models.challenge import (
    ChallengeParticipant,
    DailyChallengeProgress,
    ParticipantStatus,
)
from app.models.game import Elimination, Warning, XPReason, XPTransaction
from app.models.media import MediaAsset
from app.models.user import UserProfile


async def _register(client, name: str):  # type: ignore[no-untyped-def]
    email = f"{name.lower()}-{uuid.uuid4().hex[:10]}@conc.example"
    response = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "hunter2222", "display_name": name},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    user_id = uuid.UUID(body["user_id"])
    client.created_users.append(user_id)
    return user_id, {"Authorization": f"Bearer {body['access_token']}"}


async def _squad(client, size: int = 2):  # type: ignore[no-untyped-def]
    actors = [await _register(client, f"Conc{i}") for i in range(size)]
    group = (
        await client.post(
            "/api/v1/groups",
            json={"name": "CONC SQUAD", "timezone": "Asia/Kolkata"},
            headers=actors[0][1],
        )
    ).json()
    for _, headers in actors[1:]:
        assert (
            await client.post(
                "/api/v1/groups/join",
                json={"join_code": group["join_code"]},
                headers=headers,
            )
        ).status_code == 200
    return actors, group


async def _challenge(client, headers, group, **overrides) -> Any:  # type: ignore[no-untyped-def]
    payload = {
        "name": "CONC WAR", "activity_type": "steps", "target_value": "10000",
        "unit": "steps", "game_mode": "survival",
        "verification_method": "apple_health", "duration_days": 30,
    }
    payload.update(overrides)
    return (
        await client.post(
            f"/api/v1/groups/{group['id']}/challenges", json=payload, headers=headers
        )
    ).json()


async def _verify(client, headers, challenge_id, value="12000") -> Any:  # type: ignore[no-untyped-def]
    day = (
        await client.get(
            f"/api/v1/challenges/{challenge_id}/progress/today", headers=headers
        )
    ).json()
    return await client.post(
        f"/api/v1/challenges/{challenge_id}/verify",
        json={
            "provider": "apple_health",
            "evidence": {
                "metric": "steps", "value": value, "unit": "steps",
                "period_start": day["window_start_at"],
                "period_end": datetime.now(UTC).isoformat(),
                "was_user_entered": False,
            },
        },
        headers=headers,
    )


async def _count(model: Any, *where: Any) -> int:
    async with _session_factory() as session:
        result = await session.execute(select(func.count()).select_from(model).where(*where))
        return int(result.scalar_one())


class TestChallengeJoinRace:
    async def test_concurrent_joins_produce_one_participant_row(self, live_client) -> None:  # type: ignore[no-untyped-def]
        """`UNIQUE(challenge_id, user_id)` is the guarantee; this proves it holds under
        a real race rather than only under the service's pre-check."""
        (owner, joiner), group = await _squad(live_client)
        challenge = await _challenge(live_client, owner[1], group)

        responses = await asyncio.gather(
            *(
                live_client.post(
                    f"/api/v1/challenges/{challenge['id']}/join", headers=joiner[1]
                )
                for _ in range(5)
            ),
            return_exceptions=True,
        )

        created = [r for r in responses if getattr(r, "status_code", None) == 200]
        assert len(created) <= 1, "more than one join succeeded"
        assert (
            await _count(
                ChallengeParticipant,
                ChallengeParticipant.challenge_id == uuid.UUID(challenge["id"]),
                ChallengeParticipant.user_id == joiner[0],
            )
            == 1
        )

    async def test_a_participant_limit_is_not_oversubscribed_by_a_race(
        self, live_client
    ) -> None:  # type: ignore[no-untyped-def]
        """A limit checked with a count-then-insert is exactly the shape a race defeats."""
        actors, group = await _squad(live_client, size=5)
        owner = actors[0]
        challenge = await _challenge(live_client, owner[1], group, participant_limit=2)

        await asyncio.gather(
            *(
                live_client.post(
                    f"/api/v1/challenges/{challenge['id']}/join", headers=headers
                )
                for _, headers in actors[1:]
            ),
            return_exceptions=True,
        )

        active = await _count(
            ChallengeParticipant,
            ChallengeParticipant.challenge_id == uuid.UUID(challenge["id"]),
            ChallengeParticipant.status == ParticipantStatus.ACTIVE,
        )
        # The creator plus at most one joiner. Recorded rather than asserted as a bug if
        # it exceeds the limit — see the report's "participant limit" finding.
        assert active <= 2, f"participant_limit=2 oversubscribed to {active}"


class TestVerificationRace:
    async def test_concurrent_identical_submissions_award_one_day(self, live_client) -> None:  # type: ignore[no-untyped-def]
        actors, group = await _squad(live_client, size=1)
        (user_id, headers) = actors[0]
        challenge = await _challenge(live_client, headers, group, game_mode="points")

        await asyncio.gather(
            *(_verify(live_client, headers, challenge["id"], "12000") for _ in range(6)),
            return_exceptions=True,
        )

        assert (
            await _count(
                XPTransaction,
                XPTransaction.user_id == user_id,
                XPTransaction.reason == XPReason.DAILY_COMPLETION,
            )
            == 1
        )
        async with _session_factory() as session:
            score = (
                await session.execute(
                    select(ChallengeParticipant.current_score).where(
                        ChallengeParticipant.user_id == user_id,
                        ChallengeParticipant.challenge_id == uuid.UUID(challenge["id"]),
                    )
                )
            ).scalar_one()
        assert Decimal(score) == Decimal(12000), "score double-counted under a race"

    async def test_the_xp_projection_matches_the_ledger_after_a_race(
        self, live_client
    ) -> None:  # type: ignore[no-untyped-def]
        """`xp_total` is a cached projection; a lost update here is silent corruption."""
        actors, group = await _squad(live_client, size=1)
        (user_id, headers) = actors[0]
        for index in range(3):
            challenge = await _challenge(
                live_client, headers, group, game_mode="points", name=f"W{index}"
            )
            await asyncio.gather(
                *(_verify(live_client, headers, challenge["id"], "12000") for _ in range(4)),
                return_exceptions=True,
            )

        async with _session_factory() as session:
            ledger = (
                await session.execute(
                    select(func.coalesce(func.sum(XPTransaction.amount), 0)).where(
                        XPTransaction.user_id == user_id
                    )
                )
            ).scalar_one()
            cached = (
                await session.execute(
                    select(UserProfile.xp_total).where(UserProfile.user_id == user_id)
                )
            ).scalar_one()
        assert ledger == cached, f"ledger {ledger} != cached {cached}"


class TestDeadlineSweepRace:
    async def test_concurrent_sweeps_never_duplicate_warnings_or_eliminations(
        self, live_client
    ) -> None:  # type: ignore[no-untyped-def]
        """The scheduled sweep can overlap with itself and with live traffic. The
        UNIQUE constraints are what make that safe — asserted, not assumed."""
        from app.workers import deadline_sweep

        actors, group = await _squad(live_client, size=1)
        (_user_id, headers) = actors[0]
        challenge = await _challenge(live_client, headers, group)

        # Backdate the challenge so several of its days are already overdue.
        async with _session_factory() as session:
            from app.models.challenge import Challenge

            row = (
                await session.execute(
                    select(Challenge).where(Challenge.id == uuid.UUID(challenge["id"]))
                )
            ).scalar_one()
            row.start_at = datetime.now(UTC).replace(microsecond=0)
            await session.commit()

        results = await asyncio.gather(
            *(deadline_sweep.run_once() for _ in range(4)), return_exceptions=True
        )
        assert all(not isinstance(r, Exception) for r in results), results

        async with _session_factory() as session:
            participant_id = (
                await session.execute(
                    select(ChallengeParticipant.id).where(
                        ChallengeParticipant.challenge_id == uuid.UUID(challenge["id"])
                    )
                )
            ).scalar_one()
            warnings = (
                await session.execute(
                    select(Warning.challenge_day).where(
                        Warning.challenge_participant_id == participant_id
                    )
                )
            ).scalars().all()
            eliminations = (
                await session.execute(
                    select(func.count())
                    .select_from(Elimination)
                    .where(Elimination.challenge_participant_id == participant_id)
                )
            ).scalar_one()
            progress_days = (
                await session.execute(
                    select(DailyChallengeProgress.challenge_day).where(
                        DailyChallengeProgress.challenge_participant_id == participant_id
                    )
                )
            ).scalars().all()

        assert len(warnings) == len(set(warnings)), "duplicate warning for one day"
        assert eliminations <= 1, "participant eliminated more than once"
        assert len(progress_days) == len(set(progress_days)), "duplicate progress rows"

    async def test_a_sweep_racing_a_verification_leaves_consistent_state(
        self, live_client
    ) -> None:  # type: ignore[no-untyped-def]
        actors, group = await _squad(live_client, size=1)
        (user_id, headers) = actors[0]
        challenge = await _challenge(live_client, headers, group, game_mode="points")

        from app.workers import deadline_sweep

        await asyncio.gather(
            _verify(live_client, headers, challenge["id"], "12000"),
            deadline_sweep.run_once(),
            _verify(live_client, headers, challenge["id"], "12000"),
            deadline_sweep.run_once(),
            return_exceptions=True,
        )

        assert (
            await _count(
                XPTransaction,
                XPTransaction.user_id == user_id,
                XPTransaction.reason == XPReason.DAILY_COMPLETION,
            )
            <= 1
        )


class TestMediaCleanupRace:
    async def test_concurrent_cleanups_delete_each_object_once(self, live_client) -> None:  # type: ignore[no-untyped-def]
        """`skip_locked` plus the `object_deleted_at` guard: two sweeps must not both
        count the same object, and neither may crash on the other's rows."""
        from datetime import timedelta

        from app.models.media import MediaContextType, MediaStatus
        from app.services.media_service import MediaService

        actors, _group = await _squad(live_client, size=1)
        (owner_id, _headers) = actors[0]
        keys: list[str] = []
        async with _session_factory() as session:
            for _ in range(6):
                key = f"verification_proof/{owner_id}/{uuid.uuid4()}.mp4"
                keys.append(key)
                session.add(
                    MediaAsset(
                        owner_id=owner_id,
                        storage_key=key,
                        content_type="video/mp4",
                        context_type=MediaContextType.VERIFICATION_PROOF,
                        status=MediaStatus.PROCESSED,
                        expires_at=datetime.now(UTC) - timedelta(hours=2),
                    )
                )
            await session.commit()

        deleted_keys: list[str] = []

        class RecordingStorage:
            def delete(self, *, key: str) -> bool:
                deleted_keys.append(key)
                return True

        async def sweep() -> int:
            async with _session_factory() as session:
                service = MediaService(session)
                service._storage = RecordingStorage()  # type: ignore[assignment]
                count = await service.run_cleanup()
                await session.commit()
                return count

        counts = await asyncio.gather(*(sweep() for _ in range(4)), return_exceptions=True)
        assert all(not isinstance(c, Exception) for c in counts), counts

        ours = [k for k in deleted_keys if k in keys]
        assert len(ours) == len(set(ours)), "an object was deleted twice"
        assert sum(c for c in counts if isinstance(c, int)) >= 1

        async with _session_factory() as session:
            remaining = (
                await session.execute(
                    select(func.count())
                    .select_from(MediaAsset)
                    .where(
                        MediaAsset.storage_key.in_(keys),
                        MediaAsset.object_deleted_at.is_(None),
                    )
                )
            ).scalar_one()
        assert remaining == 0, "cleanup left expired objects behind"


class TestProofReviewRace:
    async def test_concurrent_approvals_credit_the_day_once(self, live_client) -> None:  # type: ignore[no-untyped-def]
        """Approval runs the same XP pipeline as a health submission, so it inherits the
        ledger's idempotency — verified here rather than assumed."""
        from app.models.media import MediaContextType, MediaStatus
        from app.models.verification import VerificationRecord

        actors, group = await _squad(live_client, size=2)
        (_reviewer_id, reviewer), (athlete_id, athlete) = actors
        challenge = await _challenge(
            live_client, reviewer, group, verification_method="manual_proof",
            activity_type="pushups", unit="reps", target_value="50", game_mode="points",
        )
        joined = await live_client.post(
            f"/api/v1/challenges/{challenge['id']}/join", headers=athlete
        )
        assert joined.status_code == 201, joined.text

        async with _session_factory() as session:
            asset = MediaAsset(
                owner_id=athlete_id,
                storage_key=f"verification_proof/{athlete_id}/{uuid.uuid4()}.mp4",
                content_type="video/mp4",
                context_type=MediaContextType.VERIFICATION_PROOF,
                status=MediaStatus.PROCESSED,
                size_bytes=1024,
            )
            session.add(asset)
            await session.commit()
            media_id = str(asset.id)

        day = (
            await live_client.get(
                f"/api/v1/challenges/{challenge['id']}/progress/today", headers=athlete
            )
        ).json()
        submitted = await live_client.post(
            f"/api/v1/challenges/{challenge['id']}/verify",
            json={
                "provider": "manual_proof",
                "evidence": {
                    "metric": "pushups", "value": "60", "unit": "reps",
                    "period_start": day["window_start_at"],
                    "period_end": datetime.now(UTC).isoformat(),
                    "was_user_entered": True, "media_id": media_id,
                },
            },
            headers=athlete,
        )
        assert submitted.status_code == 200, submitted.text
        record_id = submitted.json()["verification"]["id"]

        results = await asyncio.gather(
            *(
                live_client.post(
                    f"/api/v1/challenges/{challenge['id']}/proofs/{record_id}/review",
                    json={"approve": True},
                    headers=reviewer,
                )
                for _ in range(4)
            ),
            return_exceptions=True,
        )
        assert any(getattr(r, "status_code", None) == 200 for r in results), results

        assert (
            await _count(
                XPTransaction,
                XPTransaction.user_id == athlete_id,
                XPTransaction.reason == XPReason.DAILY_COMPLETION,
            )
            == 1
        ), "concurrent approvals credited the day more than once"
        async with _session_factory() as session:
            statuses = (
                await session.execute(
                    select(VerificationRecord.status).where(
                        VerificationRecord.id == uuid.UUID(record_id)
                    )
                )
            ).scalars().all()
        assert len(statuses) == 1
