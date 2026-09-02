"""Manual-proof review (Architecture §20.5).

Approval routes into the **existing** Phase 5 pipeline — `GameService.apply_completion`
— rather than touching XP, score or streaks itself. That is the rule this file exists to
honour: there is one game system, and manual proof is just another way to reach it.

Two timing rules, which are different and both frozen:

- **After the day's deadline, challenge still running** — a late approval still completes
  the day and credits XP/streak/history, but never reverses a `Warning` or `Elimination`
  that already fired. §20.5: elimination is a persisted decision, not something that
  un-happens because a reviewer was slow.
- **After the challenge is finalized** — refused outright. Phase 5 writes `outcome` once
  and closed standings are immutable, so there is nothing left to rewrite.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import DomainEvent, EventType, publish
from app.domain.challenges.exceptions import ChallengeNotActiveError
from app.domain.verification.exceptions import (
    ProofNotFoundError,
    SelfReviewForbiddenError,
)
from app.models.challenge import (
    Challenge,
    ChallengeParticipant,
    ChallengeStatus,
    DailyChallengeProgress,
    DailyProgressStatus,
    ParticipantStatus,
)
from app.models.verification import VerificationRecord, VerificationStatus
from app.repositories.game import GameRepository
from app.repositories.verification import VerificationRecordRepository
from app.services.game_service import DayResolution, GameService
from app.services.media_service import MediaService


class ReviewOutcome:
    def __init__(
        self,
        *,
        record: VerificationRecord,
        progress: DailyChallengeProgress,
        resolution: DayResolution | None,
        already_resolved: bool,
    ) -> None:
        self.record = record
        self.progress = progress
        self.resolution = resolution
        self.already_resolved = already_resolved


class ProofReviewService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._records = VerificationRecordRepository(session)
        self._game = GameService(session)
        self._media = MediaService(session)
        self._repo = GameRepository(session)

    async def pending_for_challenge(
        self, challenge_id: uuid.UUID
    ) -> list[tuple[VerificationRecord, ChallengeParticipant, str]]:
        return await self._records.pending_review_for_challenge(challenge_id)

    async def review(
        self,
        *,
        record_id: uuid.UUID,
        challenge: Challenge,
        reviewer_id: uuid.UUID,
        approve: bool,
        note: str | None = None,
        now: datetime | None = None,
    ) -> ReviewOutcome:
        """Resolve one pending proof. Authorization is the caller's job (the
        `challenge_reviewer` dependency); everything else is enforced here."""
        now = now or datetime.now(UTC)

        record = await self._records.get(record_id)
        if record is None:
            raise ProofNotFoundError("No such proof.")

        progress, participant = await self._records.progress_and_participant(record)
        if progress is None or participant is None or participant.challenge_id != challenge.id:
            # Belongs to another challenge — same error a missing id gives, so this
            # can't be used to probe for proofs outside the reviewer's scope.
            raise ProofNotFoundError("No such proof.")

        if participant.user_id == reviewer_id:
            # Even a challenge creator cannot approve their own submission.
            raise SelfReviewForbiddenError("You can't review your own proof.")

        # Idempotent: a resolved proof is returned as-is rather than resolved twice.
        # Checked before any state change, so a duplicate approve/reject — or a race
        # between the two — produces exactly one transition.
        if record.status is not VerificationStatus.PENDING_REVIEW:
            return ReviewOutcome(
                record=record, progress=progress, resolution=None, already_resolved=True
            )

        if challenge.status is ChallengeStatus.COMPLETED:
            # Standings are final; there is nothing a decision could still affect.
            raise ChallengeNotActiveError(
                "This challenge is finished — its result can no longer change."
            )

        locked = await self._repo.lock_participant(participant.id)
        participant = locked or participant

        record.reviewed_by_user_id = reviewer_id
        record.reviewed_at = now
        record.review_note = note

        resolution: DayResolution | None = None
        if approve:
            record.status = VerificationStatus.VERIFIED
            record.verified_at = now
            resolution = await self._approve(challenge, participant, progress, record, now)
        else:
            record.status = VerificationStatus.REJECTED
            record.reason_code = "REVIEW_REJECTED"

        # The video's retention clock starts now, on either decision — it is only
        # protected from cleanup while review is outstanding (§6).
        if record.evidence_media_id is not None:
            asset = await self._media._repo.get(record.evidence_media_id)
            if asset is not None:
                await self._media.schedule_deletion(asset, resolved_at=now)

        await self._session.flush()
        self._publish(challenge, participant, approve)
        return ReviewOutcome(
            record=record, progress=progress, resolution=resolution, already_resolved=False
        )

    async def _approve(
        self,
        challenge: Challenge,
        participant: ChallengeParticipant,
        progress: DailyChallengeProgress,
        record: VerificationRecord,
        now: datetime,
    ) -> DayResolution | None:
        """Complete the day through the ordinary Phase 5 pipeline.

        Nothing here computes XP, score or streaks — `apply_completion` does, exactly as
        it does for HealthKit, and its ledger unique-key makes a replayed approval a
        no-op rather than a second award.
        """
        if progress.status is DailyProgressStatus.COMPLETED:
            # Already credited by an earlier decision or another provider.
            return None

        # A late approval still credits the day for record-keeping, but an elimination
        # that already fired stands — §20.5's non-retroactive rule.
        progress.status = DailyProgressStatus.COMPLETED
        progress.completed_at = now
        progress.verification_record_id = record.id

        if participant.status is not ParticipantStatus.ACTIVE:
            # Eliminated or departed: the day is recorded, but no competitive credit —
            # crediting score to an eliminated player would resurrect them by the back
            # door.
            await self._session.flush()
            return None

        return await self._game.apply_completion(
            challenge=challenge,
            participant=participant,
            progress=progress,
            value=record.value,
            now=now,
        )

    def _publish(
        self, challenge: Challenge, participant: ChallengeParticipant, approved: bool
    ) -> None:
        publish(
            DomainEvent(
                type=EventType.VERIFICATION_COMPLETED,
                challenge_id=challenge.id,
                user_id=participant.user_id,
                occurred_at=datetime.now(UTC),
                payload={"decision": "approved" if approved else "rejected"},
            )
        )
