"""Media upload endpoints. Thin translation layer only."""

import uuid

from fastapi import APIRouter, status

from app.core.config import get_settings
from app.core.deps import CurrentUser, MediaServiceDep
from app.models.media import MediaAsset, MediaContextType
from app.schemas.media import (
    MediaAssetResponse,
    PrepareUploadRequest,
    PresignedUploadResponse,
)

router = APIRouter(prefix="/media", tags=["media"])


async def _asset_response(asset: MediaAsset, media: MediaServiceDep) -> MediaAssetResponse:
    return MediaAssetResponse(
        id=asset.id,
        status=asset.status,
        content_type=asset.content_type,
        size_bytes=asset.size_bytes,
        playback_url=await media.playback_url(asset),
        expires_at=asset.expires_at,
        object_deleted_at=asset.object_deleted_at,
    )


@router.post(
    "/upload-url",
    response_model=PresignedUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def prepare_upload(
    body: PrepareUploadRequest, current_user: CurrentUser, media: MediaServiceDep
) -> PresignedUploadResponse:
    """Reserve an asset and return a short-lived grant to upload it.

    The storage key is server-generated and namespaced by owner, so a client can neither
    pick a key nor overwrite another user's object (§5).
    """
    asset, grant = await media.prepare_upload(
        owner_id=current_user.id,
        content_type=body.content_type,
        context_type=MediaContextType.VERIFICATION_PROOF,
    )
    return PresignedUploadResponse(
        media_id=asset.id,
        url=grant.url,
        fields=grant.fields,
        expires_in_seconds=grant.expires_in_seconds,
        max_bytes=get_settings().media.max_proof_bytes,
    )


@router.post("/{media_id}/complete", response_model=MediaAssetResponse)
async def complete_upload(
    media_id: uuid.UUID, current_user: CurrentUser, media: MediaServiceDep
) -> MediaAssetResponse:
    """Confirm the upload landed. Idempotent — repeating it returns the same asset.

    The server reads size and type back from storage rather than trusting the client.
    """
    asset = await media.complete_upload(owner_id=current_user.id, media_id=media_id)
    return await _asset_response(asset, media)


@router.get("/{media_id}", response_model=MediaAssetResponse)
async def get_media(
    media_id: uuid.UUID, current_user: CurrentUser, media: MediaServiceDep
) -> MediaAssetResponse:
    """Owner-scoped. Another user's media id returns the same 404 a missing one does.

    Reviewers reach a participant's proof through the review queue instead, which is
    authorized per challenge — proof is private by default (§14).
    """
    asset = await media.get_owned(media_id, current_user.id)
    return await _asset_response(asset, media)
