"""Verification use cases.

The one place that turns submitted evidence into a resolved challenge day. It selects a
provider from the registry by the challenge's declared method, hands it plain values,
and writes the outcome — it never names HealthKit, and neither does anything downstream
of it (Architecture §8).

Scope note: this resolves `DailyChallengeProgress` and records the evidence. It does not
award XP, move scores, or touch streaks — those belong to the XP/Streak phase
(Architecture §17 step 5), and inventing them here would create competitive state that
the rest of the system isn't ready to keep consistent.
"""

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.challenges.challenge_day import (
    day_deadline_utc,
    day_start_utc,
    resolve_challenge_day,
)
from app.domain.challenges.exceptions import ChallengeNotActiveError
from app.domain.verification.evidence import HealthEvidence
from app.domain.verification.exceptions import (
    InvalidEvidenceError,
    VerificationMethodMismatchError,
)
from app.domain.verification.metrics import ActivityKind
from app.domain.verification.result import (
    VerificationContext,
    VerificationStatus,
)
from app.integrations.verification_providers.manual_proof import SOURCE as MANUAL_PROOF
from app.integrations.verification_providers.registry import get_provider
from app.models.challenge import (
    Challenge,
    ChallengeParticipant,
    ChallengeStatus,
    DailyChallengeProgress,
    DailyProgressStatus,
    ParticipantStatus,
)
from app.models.verification import HealthProvider, VerificationRecord
from app.models.verification import VerificationStatus as DBVerificationStatus
from app.repositories.challenges import DailyProgressRepository
from app.repositories.verification import (
    HealthConnectionRepository,
    VerificationRecordRepository,
)
from app.services.game_service import DayResolution, GameService
from app.services.media_service import MediaService


class VerificationOutcome:
    """What the API reports back: the record plus the day it produced."""

    def __init__(
        self,
        *,
        record: VerificationRecord,
        progress: DailyChallengeProgress,
        challenge_day: date,
        deadline_at: datetime,
        idempotent_replay: bool,
        resolution: "DayResolution | None" = None,
    ) -> None:
        self.record = record
        self.progress = progress
        self.challenge_day = challenge_day
        self.deadline_at = deadline_at
        self.idempotent_replay = idempotent_replay
        # What the competitive pipeline did, when this submission completed a day.
        self.resolution = resolution


class VerificationService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._progress = DailyProgressRepository(session)
        self._records = VerificationRecordRepository(session)
        self._connections = HealthConnectionRepository(session)
        self._game = GameService(session)
        self._media = MediaService(session)

    async def submit(
        self,
        *,
        challenge: Challenge,
        participant: ChallengeParticipant,
        provider_name: str,
        evidence: HealthEvidence,
        raw_payload: dict[str, Any] | None = None,
        media_id: uuid.UUID | None = None,
        now: datetime | None = None,
    ) -> VerificationOutcome:
        """Evaluate evidence for today and resolve the day.

        Everything below happens in the caller's transaction: the record write and the
        progress update commit together or not at all, so there is no state where a day
        reads COMPLETED without the evidence that made it so.
        """
        now = now or datetime.now(UTC)

        if challenge.status != ChallengeStatus.ACTIVE:
            raise ChallengeNotActiveError(
                f"Challenge is '{challenge.status.value}' and accepts no verification."
            )
        if participant.status != ParticipantStatus.ACTIVE:
            # An eliminated or departed participant has no open day to resolve.
            raise ChallengeNotActiveError(
                f"You are '{participant.status.value}' in this challenge."
            )

        if provider_name != challenge.verification_method.value:
            raise VerificationMethodMismatchError(
                f"This challenge verifies via '{challenge.verification_method.value}'."
            )
        provider = get_provider(provider_name)
        if provider is None:
            raise VerificationMethodMismatchError(
                f"'{provider_name}' verification isn't available yet."
            )

        # The day, and its exact UTC bounds, come from the challenge's frozen timezone
        # — never from the client, and never from server-local time (§11).
        # Resolve anything already past its deadline first (§20.5). This is what stops
        # a participant who should already be eliminated from verifying their way out.
        await self._game.resolve_overdue_days(challenge, now=now)
        await self._session.refresh(participant)
        if participant.status != ParticipantStatus.ACTIVE:
            raise ChallengeNotActiveError(
                f"You are '{participant.status.value}' in this challenge."
            )

        challenge_day = resolve_challenge_day(now, challenge.timezone)
        day_start = day_start_utc(challenge_day, challenge.timezone)
        deadline = day_deadline_utc(challenge_day, challenge.timezone)

        progress = await self._progress.get_or_create(participant.id, challenge_day)

        # Idempotency: once a day is COMPLETED, a repeat submission returns the result
        # that completed it instead of writing a second one (API_SPEC:
        # ALREADY_VERIFIED_TODAY is idempotent, "returns existing result, not an error").
        if progress.status == DailyProgressStatus.COMPLETED:
            existing = await self._existing_record(progress)
            if existing is not None:
                return VerificationOutcome(
                    record=existing,
                    progress=progress,
                    challenge_day=challenge_day,
                    deadline_at=deadline,
                    idempotent_replay=True,
                )

        context = VerificationContext(
            activity=ActivityKind(challenge.activity_type.value),
            target_value=Decimal(challenge.target_value),
            challenge_day=challenge_day,
            day_start_at=day_start,
            day_end_at=deadline,
            now=now,
        )
        # Manual proof must reference a completed upload the caller owns. Checked before
        # the provider runs so a proof can never be recorded without its video.
        asset = None
        if provider_name == MANUAL_PROOF:
            if media_id is None:
                raise InvalidEvidenceError("Video proof requires an uploaded file.")
            asset = await self._media.require_processed(media_id, participant.user_id)

        result = provider.evaluate(context=context, evidence=evidence)

        # A malformed submission is a client error, not a stored attempt: recording it
        # would pollute a participant's evidence history with bugs.
        if result.status is VerificationStatus.REJECTED and _is_client_error(result.reason_code):
            raise InvalidEvidenceError(_rejection_detail(result.reason_code))

        record = await self._records.add(
            progress_id=progress.id,
            provider=result.source,
            metric=result.metric,
            value=result.value,
            target=result.target,
            status=DBVerificationStatus(result.status.value),
            reason_code=result.reason_code,
            source_timestamp=result.source_timestamp,
            raw_payload=raw_payload,
        )

        if asset is not None:
            record.evidence_media_id = asset.id
            asset.context_id = progress.id
            # Pending review means protected from cleanup: the reviewer still has to
            # watch it (§6, the mandatory rule).
            await self._media.protect_from_cleanup(asset)

        resolution: DayResolution | None = None
        if result.verified:
            progress.status = DailyProgressStatus.COMPLETED
            progress.completed_at = now
            progress.verification_record_id = record.id
            # Score, XP and streak, in this same transaction (Architecture §3.4).
            resolution = await self._game.apply_completion(
                challenge=challenge,
                participant=participant,
                progress=progress,
                value=result.value,
                now=now,
            )
        # A short-of-target or inconclusive attempt leaves the day PENDING on purpose.
        # The day is only MISSED once its deadline passes with no verified record — a
        # deadline sweep the failure-rule phase owns (§20.5), not something a partial
        # sync should decide early.

        if result.source == HealthProvider.APPLE_HEALTH.value:
            await self._connections.mark_synced(
                participant.user_id, HealthProvider.APPLE_HEALTH
            )

        await self._session.flush()
        return VerificationOutcome(
            record=record,
            progress=progress,
            challenge_day=challenge_day,
            deadline_at=deadline,
            idempotent_replay=False,
            resolution=resolution,
        )

    async def _existing_record(
        self, progress: DailyChallengeProgress
    ) -> VerificationRecord | None:
        if progress.verification_record_id is None:
            return None
        return await self._records.get(progress.verification_record_id)

    async def history(self, progress_id: uuid.UUID) -> list[VerificationRecord]:
        return await self._records.list_for_progress(progress_id)


# Rejections that mean "the client sent something wrong" rather than "the attempt
# didn't qualify". The first group is a 4xx; the second is a stored, non-verified
# attempt the user can act on.
_CLIENT_ERROR_REASONS = {
    "INCOMPATIBLE_METRIC",
    "UNSUPPORTED_UNIT",
    "NEGATIVE_VALUE",
    "INVERTED_PERIOD",
    "PERIOD_IN_FUTURE",
    "METRIC_NOT_HEALTH_READABLE",
    "OUTSIDE_CHALLENGE_DAY",
}

_REJECTION_DETAIL = {
    "INCOMPATIBLE_METRIC": "That measurement doesn't match this challenge's activity.",
    "UNSUPPORTED_UNIT": "That unit isn't accepted for this challenge's activity.",
    "NEGATIVE_VALUE": "A measured value can't be negative.",
    "INVERTED_PERIOD": "The measurement period ends before it starts.",
    "PERIOD_IN_FUTURE": "The measurement period is in the future.",
    "METRIC_NOT_HEALTH_READABLE": "This activity can't be measured from health data.",
    "OUTSIDE_CHALLENGE_DAY": (
        "That measurement falls outside today's challenge window. The challenge day is "
        "set by the group's timezone, not your device's."
    ),
}


def _is_client_error(reason_code: str | None) -> bool:
    return reason_code in _CLIENT_ERROR_REASONS


def _rejection_detail(reason_code: str | None) -> str:
    return _REJECTION_DETAIL.get(reason_code or "", "That evidence couldn't be accepted.")
