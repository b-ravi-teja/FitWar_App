"""Persistence for health connections and verification records."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.challenge import ChallengeParticipant, DailyChallengeProgress
from app.models.verification import (
    HealthConnection,
    HealthConnectionStatus,
    HealthProvider,
    VerificationRecord,
    VerificationStatus,
)


class HealthConnectionRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_for_user(self, user_id: uuid.UUID) -> list[HealthConnection]:
        result = await self._session.execute(
            select(HealthConnection)
            .where(HealthConnection.user_id == user_id)
            .order_by(HealthConnection.created_at.desc())
        )
        return list(result.scalars().all())

    async def get(
        self, user_id: uuid.UUID, provider: HealthProvider
    ) -> HealthConnection | None:
        result = await self._session.execute(
            select(HealthConnection).where(
                HealthConnection.user_id == user_id,
                HealthConnection.provider == provider,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_id(
        self, user_id: uuid.UUID, connection_id: uuid.UUID
    ) -> HealthConnection | None:
        """Scoped to the owner — a connection id from another account never resolves."""
        result = await self._session.execute(
            select(HealthConnection).where(
                HealthConnection.id == connection_id,
                HealthConnection.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def connect(
        self, user_id: uuid.UUID, provider: HealthProvider
    ) -> HealthConnection:
        """Idempotent: reconnecting an existing link revives it rather than duplicating.

        UNIQUE(user_id, provider) makes a second row impossible anyway; this turns that
        constraint into defined behaviour instead of an integrity error.
        """
        existing = await self.get(user_id, provider)
        if existing is not None:
            existing.status = HealthConnectionStatus.CONNECTED
            existing.revoked_at = None
            await self._session.flush()
            return existing

        connection = HealthConnection(
            user_id=user_id, provider=provider, status=HealthConnectionStatus.CONNECTED
        )
        self._session.add(connection)
        await self._session.flush()
        return connection

    async def revoke(self, connection: HealthConnection) -> None:
        connection.status = HealthConnectionStatus.REVOKED
        connection.revoked_at = datetime.now(UTC)
        await self._session.flush()

    async def mark_synced(self, user_id: uuid.UUID, provider: HealthProvider) -> None:
        """Record that evidence actually arrived — the server's own observation, not a
        client claim about its permission state."""
        connection = await self.get(user_id, provider)
        if connection is None:
            return
        connection.last_synced_at = datetime.now(UTC)
        await self._session.flush()


class VerificationRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, record_id: uuid.UUID) -> VerificationRecord | None:
        result = await self._session.execute(
            select(VerificationRecord).where(VerificationRecord.id == record_id)
        )
        return result.scalar_one_or_none()

    async def list_for_progress(self, progress_id: uuid.UUID) -> list[VerificationRecord]:
        result = await self._session.execute(
            select(VerificationRecord)
            .where(VerificationRecord.daily_challenge_progress_id == progress_id)
            .order_by(VerificationRecord.created_at.asc())
        )
        return list(result.scalars().all())

    async def pending_review_for_challenge(
        self, challenge_id: uuid.UUID
    ) -> list[tuple[VerificationRecord, ChallengeParticipant, str]]:
        """The reviewer's queue, scoped to one challenge.

        Four-table join, bounded by `status='pending_review'` — the index note in
        Architecture §4.1 anticipated exactly this query and deliberately chose the join
        over a denormalized challenge_id column.
        """
        from app.models.user import User, UserProfile

        result = await self._session.execute(
            select(VerificationRecord, ChallengeParticipant, UserProfile.display_name)
            .join(
                DailyChallengeProgress,
                DailyChallengeProgress.id == VerificationRecord.daily_challenge_progress_id,
            )
            .join(
                ChallengeParticipant,
                ChallengeParticipant.id == DailyChallengeProgress.challenge_participant_id,
            )
            .join(User, User.id == ChallengeParticipant.user_id)
            .join(UserProfile, UserProfile.user_id == User.id)
            .where(
                ChallengeParticipant.challenge_id == challenge_id,
                VerificationRecord.status == VerificationStatus.PENDING_REVIEW,
            )
            .order_by(VerificationRecord.created_at.asc())
        )
        return [(row[0], row[1], row[2]) for row in result.all()]

    async def progress_and_participant(
        self, record: VerificationRecord
    ) -> tuple[DailyChallengeProgress | None, ChallengeParticipant | None]:
        result = await self._session.execute(
            select(DailyChallengeProgress, ChallengeParticipant)
            .join(
                ChallengeParticipant,
                ChallengeParticipant.id == DailyChallengeProgress.challenge_participant_id,
            )
            .where(DailyChallengeProgress.id == record.daily_challenge_progress_id)
        )
        row = result.first()
        return (row[0], row[1]) if row else (None, None)

    async def add(
        self,
        *,
        progress_id: uuid.UUID,
        provider: str,
        metric: str,
        value: Decimal,
        target: Decimal,
        status: VerificationStatus,
        reason_code: str | None,
        source_timestamp: datetime,
        raw_payload: dict[str, Any] | None,
    ) -> VerificationRecord:
        record = VerificationRecord(
            daily_challenge_progress_id=progress_id,
            provider=provider,
            metric=metric,
            value=value,
            target=target,
            status=status,
            reason_code=reason_code,
            source_timestamp=source_timestamp,
            verified_at=datetime.now(UTC) if status is VerificationStatus.VERIFIED else None,
            raw_payload=raw_payload,
        )
        self._session.add(record)
        await self._session.flush()
        return record
