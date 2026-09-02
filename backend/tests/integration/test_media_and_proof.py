"""Media lifecycle, retention, and manual-proof review against real MinIO + Postgres.

Not mocked: the retention rules are the product's storage-cost guarantee (§33), and the
"pending proof is never deleted" rule is mandatory (§31). Both are properties of real
objects in real storage, so they are tested against real storage.
"""

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.config import get_settings
from app.integrations.storage.s3 import get_object_storage
from app.models.media import MediaAsset, MediaStatus
from app.models.verification import VerificationRecord, VerificationStatus
from app.services.media_service import MediaService

# A tiny but genuine byte payload — enough to prove a real object exists in storage.
FAKE_VIDEO = b"\x00\x00\x00\x18ftypmp42" + b"fitwar-test-video" * 8


@pytest.fixture(autouse=True)
def _bucket() -> None:
    get_object_storage().ensure_bucket()


async def _upload(client, actor) -> str:  # type: ignore[no-untyped-def]
    """Full real upload: reserve → PUT to MinIO → confirm. Returns media id."""
    prepared = await client.post(
        "/api/v1/media/upload-url",
        json={"content_type": "video/mp4"},
        headers=actor.headers,
    )
    assert prepared.status_code == 201, prepared.text
    grant = prepared.json()

    async with httpx.AsyncClient() as raw:
        posted = await raw.post(
            grant["url"],
            data=grant["fields"],
            files={"file": ("proof.mp4", FAKE_VIDEO, "video/mp4")},
        )
    assert posted.status_code in (200, 204), posted.text

    completed = await client.post(
        f"/api/v1/media/{grant['media_id']}/complete", headers=actor.headers
    )
    assert completed.status_code == 200, completed.text
    return str(grant["media_id"])


async def _manual_challenge(client, actor, create_group, create_challenge):  # type: ignore[no-untyped-def]
    group = await create_group(client, actor)
    response = await create_challenge(
        client,
        actor,
        group["id"],
        activity_type="pushups",
        unit="reps",
        target_value="50",
        verification_method="manual_proof",
    )
    assert response.status_code == 201, response.text
    return group, response.json()


async def _submit_proof(client, actor, challenge_id, media_id, value="60"):  # type: ignore[no-untyped-def]
    day = (
        await client.get(
            f"/api/v1/challenges/{challenge_id}/progress/today", headers=actor.headers
        )
    ).json()
    return await client.post(
        f"/api/v1/challenges/{challenge_id}/verify",
        json={
            "provider": "manual_proof",
            "evidence": {
                "metric": "pushups",
                "value": value,
                "unit": "reps",
                "period_start": day["window_start_at"],
                "period_end": datetime.now(UTC).isoformat(),
                "media_id": media_id,
            },
        },
        headers=actor.headers,
    )


class TestUpload:
    async def test_real_round_trip_to_object_storage(
        self, client, register_actor, db_session
    ) -> None:
        actor = await register_actor(client, "Uploader")

        media_id = await _upload(client, actor)

        asset = (
            await db_session.execute(
                select(MediaAsset).where(MediaAsset.id == uuid.UUID(media_id))
            )
        ).scalar_one()
        assert asset.status is MediaStatus.PROCESSED
        # Size was read back from the object, not taken from the client's word.
        assert asset.size_bytes == len(FAKE_VIDEO)
        assert get_object_storage().head(key=asset.storage_key) is not None

    async def test_storage_key_is_server_generated_and_owner_namespaced(
        self, client, register_actor, db_session
    ) -> None:
        """The client never chooses a key — that is what stops cross-user overwrite."""
        actor = await register_actor(client, "Namespaced")
        media_id = await _upload(client, actor)

        asset = (
            await db_session.execute(
                select(MediaAsset).where(MediaAsset.id == uuid.UUID(media_id))
            )
        ).scalar_one()

        assert str(actor.user_id) in asset.storage_key
        assert asset.storage_key.startswith("verification_proof/")

    async def test_rejects_a_disallowed_type(self, client, register_actor) -> None:
        actor = await register_actor(client, "BadType")

        response = await client.post(
            "/api/v1/media/upload-url",
            json={"content_type": "application/zip"},
            headers=actor.headers,
        )

        assert response.status_code == 400
        assert response.json()["code"] == "UNSUPPORTED_MEDIA_TYPE"

    async def test_completing_twice_is_idempotent(self, client, register_actor) -> None:
        actor = await register_actor(client, "Twice")
        media_id = await _upload(client, actor)

        again = await client.post(
            f"/api/v1/media/{media_id}/complete", headers=actor.headers
        )

        assert again.status_code == 200
        assert again.json()["status"] == "processed"

    async def test_completing_without_uploading_fails(
        self, client, register_actor
    ) -> None:
        actor = await register_actor(client, "NoBytes")
        prepared = (
            await client.post(
                "/api/v1/media/upload-url",
                json={"content_type": "video/mp4"},
                headers=actor.headers,
            )
        ).json()

        response = await client.post(
            f"/api/v1/media/{prepared['media_id']}/complete", headers=actor.headers
        )

        assert response.status_code == 409
        assert response.json()["code"] == "UPLOAD_NOT_FOUND_IN_STORAGE"

    async def test_another_user_cannot_read_or_complete_it(
        self, client, register_actor
    ) -> None:
        """Owner isolation: someone else's media id is indistinguishable from a missing one."""
        owner = await register_actor(client, "Owner")
        media_id = await _upload(client, owner)
        attacker = await register_actor(client, "Attacker")

        read = await client.get(f"/api/v1/media/{media_id}", headers=attacker.headers)
        complete = await client.post(
            f"/api/v1/media/{media_id}/complete", headers=attacker.headers
        )

        assert read.status_code == 404
        assert complete.status_code == 404

    async def test_upload_requires_authentication(self, client) -> None:
        response = await client.post(
            "/api/v1/media/upload-url", json={"content_type": "video/mp4"}
        )
        assert response.status_code == 401


class TestRetention:
    async def test_abandoned_upload_expires_and_is_deleted(
        self, client, register_actor, db_session
    ) -> None:
        """An upload never attached to a proof costs money for nothing (§33)."""
        actor = await register_actor(client, "Abandoner")
        media_id = await _upload(client, actor)
        asset = (
            await db_session.execute(
                select(MediaAsset).where(MediaAsset.id == uuid.UUID(media_id))
            )
        ).scalar_one()
        key = asset.storage_key
        ttl = get_settings().media.abandoned_upload_ttl_hours

        await MediaService(db_session).run_cleanup(
            now=datetime.now(UTC) + timedelta(hours=ttl + 1)
        )

        # Scoped to this asset: the sweep is global, so a count assertion would depend
        # on the rest of the table being empty.
        assert get_object_storage().head(key=key) is None
        await db_session.refresh(asset)
        assert asset.status is MediaStatus.EXPIRED
        assert asset.object_deleted_at is not None

    async def test_pending_review_video_is_never_deleted(
        self, client, register_actor, create_group, create_challenge, db_session
    ) -> None:
        """The mandatory rule (§6, §31): the reviewer still has to watch it."""
        actor = await register_actor(client, "Pending")
        _, challenge = await _manual_challenge(client, actor, create_group, create_challenge)
        media_id = await _upload(client, actor)
        submitted = await _submit_proof(client, actor, challenge["id"], media_id)
        assert submitted.status_code == 200

        # Sweep far into the future — a pending proof must survive it regardless.
        await MediaService(db_session).run_cleanup(
            now=datetime.now(UTC) + timedelta(days=365)
        )

        asset = (
            await db_session.execute(
                select(MediaAsset).where(MediaAsset.id == uuid.UUID(media_id))
            )
        ).scalar_one()
        # The mandatory guarantee is about *this* video, not the sweep's total.
        assert asset.expires_at is None, "a pending proof must have no deletion deadline"
        assert asset.object_deleted_at is None
        assert get_object_storage().head(key=asset.storage_key) is not None

    async def test_cleanup_is_idempotent_and_survives_a_missing_object(
        self, client, register_actor, db_session
    ) -> None:
        actor = await register_actor(client, "Repeat")
        media_id = await _upload(client, actor)
        asset = (
            await db_session.execute(
                select(MediaAsset).where(MediaAsset.id == uuid.UUID(media_id))
            )
        ).scalar_one()
        service = MediaService(db_session)
        later = datetime.now(UTC) + timedelta(days=2)

        await service.run_cleanup(now=later)
        # Deleting an object that is already gone must not raise.
        get_object_storage().delete(key=asset.storage_key)
        second = await service.run_cleanup(now=later)
        third = await service.run_cleanup(now=later)

        await db_session.refresh(asset)
        assert asset.status is MediaStatus.EXPIRED
        assert get_object_storage().head(key=asset.storage_key) is None
        # Once swept, this row is never swept again — repeated runs are no-ops for it.
        assert second == 0 and third == 0


class TestManualProofSubmission:
    async def test_submission_is_pending_not_verified(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        """A video is not a number — V1 has no computer vision, so a human decides."""
        actor = await register_actor(client, "Prover")
        _, challenge = await _manual_challenge(client, actor, create_group, create_challenge)
        media_id = await _upload(client, actor)

        body = (await _submit_proof(client, actor, challenge["id"], media_id)).json()

        assert body["verification"]["status"] == "pending_review"
        assert body["day_status"] == "pending"
        # Nothing competitive happened yet.
        assert body["resolution"] is None

    async def test_submission_requires_a_completed_upload(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        actor = await register_actor(client, "NoMedia")
        _, challenge = await _manual_challenge(client, actor, create_group, create_challenge)

        response = await _submit_proof(client, actor, challenge["id"], None)

        assert response.status_code == 400
        assert response.json()["code"] == "INVALID_EVIDENCE"

    async def test_cannot_submit_someone_elses_upload(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        owner = await register_actor(client, "MediaOwner")
        media_id = await _upload(client, owner)
        other = await register_actor(client, "Thief")
        _, challenge = await _manual_challenge(client, other, create_group, create_challenge)

        response = await _submit_proof(client, other, challenge["id"], media_id)

        assert response.status_code == 404


class TestReviewAuthorization:
    async def test_participant_cannot_review_their_own_proof(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        """Even the challenge creator — authorized as a reviewer — cannot self-approve."""
        actor = await register_actor(client, "SelfApprover")
        _, challenge = await _manual_challenge(client, actor, create_group, create_challenge)
        media_id = await _upload(client, actor)
        record_id = (await _submit_proof(client, actor, challenge["id"], media_id)).json()[
            "verification"
        ]["id"]

        response = await client.post(
            f"/api/v1/challenges/{challenge['id']}/proofs/{record_id}/review",
            json={"approve": True},
            headers=actor.headers,
        )

        assert response.status_code == 403
        assert response.json()["code"] == "CANNOT_REVIEW_OWN_PROOF"

    async def test_a_non_reviewer_member_is_refused(
        self, client, register_actor, create_group, create_challenge, join_group
    ) -> None:
        owner = await register_actor(client, "Owner")
        group, challenge = await _manual_challenge(
            client, owner, create_group, create_challenge
        )
        member = await register_actor(client, "PlainMember")
        await join_group(client, member, group["join_code"])

        response = await client.get(
            f"/api/v1/challenges/{challenge['id']}/proofs/pending", headers=member.headers
        )

        assert response.status_code == 403
        assert response.json()["code"] == "NOT_A_REVIEWER"

    async def test_an_outsider_cannot_see_the_queue(
        self, client, register_actor, create_group, create_challenge
    ) -> None:
        owner = await register_actor(client, "Owner")
        _, challenge = await _manual_challenge(client, owner, create_group, create_challenge)
        outsider = await register_actor(client, "Outsider")

        response = await client.get(
            f"/api/v1/challenges/{challenge['id']}/proofs/pending",
            headers=outsider.headers,
        )

        assert response.status_code == 403

    async def test_proof_is_private_from_other_participants(
        self, client, register_actor, create_group, create_challenge, join_group
    ) -> None:
        """Submitting proof must never publish it to the group (§14)."""
        owner = await register_actor(client, "Owner")
        group, challenge = await _manual_challenge(
            client, owner, create_group, create_challenge
        )
        rival = await register_actor(client, "Rival")
        await join_group(client, rival, group["join_code"])
        await client.post(
            f"/api/v1/challenges/{challenge['id']}/join", headers=rival.headers
        )
        rival_media = await _upload(client, rival)
        record_id = (
            await _submit_proof(client, rival, challenge["id"], rival_media)
        ).json()["verification"]["id"]

        # Another plain participant cannot fetch it.
        stranger = await register_actor(client, "Stranger")
        await join_group(client, stranger, group["join_code"])
        response = await client.get(
            f"/api/v1/challenges/{challenge['id']}/proofs/{record_id}/media",
            headers=stranger.headers,
        )

        assert response.status_code == 403
        # And the media route itself is owner-only.
        direct = await client.get(
            f"/api/v1/media/{rival_media}", headers=stranger.headers
        )
        assert direct.status_code == 404


class TestReviewDecision:
    async def _setup_reviewable(
        self, client, register_actor, create_group, create_challenge, join_group
    ):  # type: ignore[no-untyped-def]
        """Owner reviews; a separate participant submits."""
        owner = await register_actor(client, "Reviewer")
        group, challenge = await _manual_challenge(
            client, owner, create_group, create_challenge
        )
        participant = await register_actor(client, "Submitter")
        await join_group(client, participant, group["join_code"])
        await client.post(
            f"/api/v1/challenges/{challenge['id']}/join", headers=participant.headers
        )
        media_id = await _upload(client, participant)
        record_id = (
            await _submit_proof(client, participant, challenge["id"], media_id)
        ).json()["verification"]["id"]
        return owner, participant, challenge, media_id, record_id

    async def test_approval_runs_the_normal_game_pipeline(
        self, client, register_actor, create_group, create_challenge, join_group
    ) -> None:
        """The same XP/score/streak path HealthKit uses — not a parallel system."""
        owner, participant, challenge, _, record_id = await self._setup_reviewable(
            client, register_actor, create_group, create_challenge, join_group
        )

        response = await client.post(
            f"/api/v1/challenges/{challenge['id']}/proofs/{record_id}/review",
            json={"approve": True},
            headers=owner.headers,
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "verified"
        assert body["xp_awarded"] == 50
        assert body["current_streak"] == 1

        state = (
            await client.get(
                f"/api/v1/challenges/{challenge['id']}/me", headers=participant.headers
            )
        ).json()
        assert state["current_streak"] == 1
        xp = (await client.get("/api/v1/me/xp", headers=participant.headers)).json()
        assert xp["xp_total"] == 50

    async def test_duplicate_approval_awards_nothing_extra(
        self, client, register_actor, create_group, create_challenge, join_group
    ) -> None:
        owner, participant, challenge, _, record_id = await self._setup_reviewable(
            client, register_actor, create_group, create_challenge, join_group
        )
        await client.post(
            f"/api/v1/challenges/{challenge['id']}/proofs/{record_id}/review",
            json={"approve": True},
            headers=owner.headers,
        )

        for _ in range(3):
            repeat = await client.post(
                f"/api/v1/challenges/{challenge['id']}/proofs/{record_id}/review",
                json={"approve": True},
                headers=owner.headers,
            )
            assert repeat.json()["already_resolved"] is True

        xp = (await client.get("/api/v1/me/xp", headers=participant.headers)).json()
        state = (
            await client.get(
                f"/api/v1/challenges/{challenge['id']}/me", headers=participant.headers
            )
        ).json()
        assert xp["xp_total"] == 50
        assert state["current_streak"] == 1

    async def test_rejection_runs_no_pipeline(
        self, client, register_actor, create_group, create_challenge, join_group
    ) -> None:
        owner, participant, challenge, _, record_id = await self._setup_reviewable(
            client, register_actor, create_group, create_challenge, join_group
        )

        response = await client.post(
            f"/api/v1/challenges/{challenge['id']}/proofs/{record_id}/review",
            json={"approve": False, "note": "Not a full rep."},
            headers=owner.headers,
        )

        assert response.json()["status"] == "rejected"
        assert response.json()["xp_awarded"] is None
        xp = (await client.get("/api/v1/me/xp", headers=participant.headers)).json()
        assert xp["xp_total"] == 0

    async def test_a_resolved_proof_cannot_be_flipped(
        self, client, register_actor, create_group, create_challenge, join_group
    ) -> None:
        """Review resolution is immutable — approve→reject would rewrite a result."""
        owner, participant, challenge, _, record_id = await self._setup_reviewable(
            client, register_actor, create_group, create_challenge, join_group
        )
        await client.post(
            f"/api/v1/challenges/{challenge['id']}/proofs/{record_id}/review",
            json={"approve": True},
            headers=owner.headers,
        )

        flip = await client.post(
            f"/api/v1/challenges/{challenge['id']}/proofs/{record_id}/review",
            json={"approve": False},
            headers=owner.headers,
        )

        assert flip.json()["already_resolved"] is True
        assert flip.json()["status"] == "verified"
        xp = (await client.get("/api/v1/me/xp", headers=participant.headers)).json()
        assert xp["xp_total"] == 50

    async def test_resolution_starts_the_retention_clock(
        self, client, register_actor, create_group, create_challenge, join_group, db_session
    ) -> None:
        """Protected while pending, deletable once resolved (§6)."""
        owner, _, challenge, media_id, record_id = await self._setup_reviewable(
            client, register_actor, create_group, create_challenge, join_group
        )
        asset = (
            await db_session.execute(
                select(MediaAsset).where(MediaAsset.id == uuid.UUID(media_id))
            )
        ).scalar_one()
        assert asset.expires_at is None

        await client.post(
            f"/api/v1/challenges/{challenge['id']}/proofs/{record_id}/review",
            json={"approve": True},
            headers=owner.headers,
        )

        await db_session.refresh(asset)
        assert asset.expires_at is not None
        hours = get_settings().media.resolved_retention_hours
        assert asset.expires_at <= datetime.now(UTC) + timedelta(hours=hours, minutes=1)

    async def test_metadata_survives_the_deleted_video(
        self, client, register_actor, create_group, create_challenge, join_group, db_session
    ) -> None:
        """The mandatory retention test (§31): object gone, competitive record intact."""
        owner, participant, challenge, media_id, record_id = await self._setup_reviewable(
            client, register_actor, create_group, create_challenge, join_group
        )
        await client.post(
            f"/api/v1/challenges/{challenge['id']}/proofs/{record_id}/review",
            json={"approve": True},
            headers=owner.headers,
        )
        asset = (
            await db_session.execute(
                select(MediaAsset).where(MediaAsset.id == uuid.UUID(media_id))
            )
        ).scalar_one()
        key = asset.storage_key
        hours = get_settings().media.resolved_retention_hours

        await MediaService(db_session).run_cleanup(
            now=datetime.now(UTC) + timedelta(hours=hours + 1)
        )

        assert get_object_storage().head(key=key) is None
        # Everything that mattered is still here.
        await db_session.refresh(asset)
        assert asset.status is MediaStatus.EXPIRED
        record = (
            await db_session.execute(
                select(VerificationRecord).where(
                    VerificationRecord.id == uuid.UUID(record_id)
                )
            )
        ).scalar_one()
        assert record.status is VerificationStatus.VERIFIED
        assert record.reviewed_by_user_id == owner.user_id
        assert record.reviewed_at is not None
        xp = (await client.get("/api/v1/me/xp", headers=participant.headers)).json()
        assert xp["xp_total"] == 50

    async def test_media_url_is_none_once_the_object_is_gone(
        self, client, register_actor, create_group, create_challenge, join_group, db_session
    ) -> None:
        """No broken player: the UI is told the media is unavailable (§27)."""
        owner, _, challenge, _, record_id = await self._setup_reviewable(
            client, register_actor, create_group, create_challenge, join_group
        )
        await client.post(
            f"/api/v1/challenges/{challenge['id']}/proofs/{record_id}/review",
            json={"approve": True},
            headers=owner.headers,
        )
        hours = get_settings().media.resolved_retention_hours
        await MediaService(db_session).run_cleanup(
            now=datetime.now(UTC) + timedelta(hours=hours + 1)
        )

        response = await client.get(
            f"/api/v1/challenges/{challenge['id']}/proofs/{record_id}/media",
            headers=owner.headers,
        )

        assert response.status_code == 200
        assert response.json()["playback_url"] is None
        assert response.json()["status"] == "expired"

    async def test_reviewer_can_fetch_a_pending_proofs_video(
        self, client, register_actor, create_group, create_challenge, join_group
    ) -> None:
        owner, _, challenge, _, record_id = await self._setup_reviewable(
            client, register_actor, create_group, create_challenge, join_group
        )

        queue = await client.get(
            f"/api/v1/challenges/{challenge['id']}/proofs/pending", headers=owner.headers
        )
        media = await client.get(
            f"/api/v1/challenges/{challenge['id']}/proofs/{record_id}/media",
            headers=owner.headers,
        )

        assert len(queue.json()) == 1
        assert queue.json()[0]["participant_display_name"] == "Submitter"
        assert media.json()["playback_url"] is not None

    async def test_a_finalized_challenge_refuses_review(
        self, client, register_actor, create_group, create_challenge, join_group, db_session
    ) -> None:
        """Case B (§13): approval after finalization cannot rewrite a closed result."""
        from app.models.challenge import Challenge, ChallengeStatus

        owner, participant, challenge, _, record_id = await self._setup_reviewable(
            client, register_actor, create_group, create_challenge, join_group
        )
        row = (
            await db_session.execute(
                select(Challenge).where(Challenge.id == uuid.UUID(challenge["id"]))
            )
        ).scalar_one()
        row.end_at = datetime.now(UTC) - timedelta(minutes=1)
        row.status = ChallengeStatus.COMPLETED
        await db_session.flush()

        response = await client.post(
            f"/api/v1/challenges/{challenge['id']}/proofs/{record_id}/review",
            json={"approve": True},
            headers=owner.headers,
        )

        assert response.status_code == 409
        xp = (await client.get("/api/v1/me/xp", headers=participant.headers)).json()
        assert xp["xp_total"] == 0
