"""S3-compatible storage. MinIO locally, AWS S3 or Cloudflare R2 in production."""

from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.integrations.storage.base import PresignedUpload

logger = get_logger(__name__)


class S3ObjectStorage:
    """Implements `ObjectStorage`."""

    def __init__(self) -> None:
        settings = get_settings().storage
        self._bucket = settings.bucket_name
        self._upload_method = settings.upload_method
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint_url,
            region_name=settings.region,
            aws_access_key_id=settings.access_key_id,
            aws_secret_access_key=settings.secret_access_key.get_secret_value(),
            # Path-style addressing by default: MinIO doesn't do virtual-host buckets,
            # and S3 and R2 both accept it, so one config works everywhere.
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": settings.addressing_style},
            ),
        )

    def ensure_bucket(self) -> None:
        """Create the bucket if absent. Local-dev convenience; harmless in prod where
        the bucket is provisioned by infrastructure."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except ClientError:
            try:
                self._client.create_bucket(Bucket=self._bucket)
            except ClientError as exc:  # already exists, or no permission in prod
                logger.info("bucket_create_skipped", error=str(exc))

    def presigned_upload(
        self, *, key: str, content_type: str, max_bytes: int, expires_in: int
    ) -> PresignedUpload:
        """A single-object write grant, in whichever shape the backend supports.

        POST is preferred and is the default: its policy pins the content type *and* a
        content-length range, so storage rejects an oversized or mistyped upload itself
        and the bytes are never stored.

        PUT exists for Cloudflare R2, which does not implement S3's PostObject — R2
        presigned URLs cover GET/PUT/HEAD/DELETE only, so there is no policy document to
        put a length range in. The content type is still signed, so that much remains
        enforced by storage; the size ceiling moves to `MediaService.complete_upload`,
        which reads the object back and rejects it if it exceeds `max_bytes`. The
        difference that leaves is *where* an oversized upload is stopped, not whether:
        on R2 the bytes land before being rejected and deleted.
        """
        if self._upload_method == "put":
            url = self._client.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": self._bucket,
                    "Key": key,
                    # Signed, so a client that sends a different type fails the
                    # signature check rather than storing a mislabelled object.
                    "ContentType": content_type,
                },
                ExpiresIn=expires_in,
            )
            return PresignedUpload(
                url=url,
                fields={},
                expires_in_seconds=expires_in,
                method="PUT",
                headers={"Content-Type": content_type},
            )

        post = self._client.generate_presigned_post(
            Bucket=self._bucket,
            Key=key,
            Fields={"Content-Type": content_type},
            Conditions=[
                {"Content-Type": content_type},
                ["content-length-range", 1, max_bytes],
            ],
            ExpiresIn=expires_in,
        )
        return PresignedUpload(
            url=post["url"],
            fields=post["fields"],
            expires_in_seconds=expires_in,
            method="POST",
        )

    def presigned_download(self, *, key: str, expires_in: int) -> str:
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": key},
            ExpiresIn=expires_in,
        )

    def head(self, *, key: str) -> tuple[int, str] | None:
        try:
            response = self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError:
            return None
        return int(response["ContentLength"]), str(response.get("ContentType", ""))

    def delete(self, *, key: str) -> bool:
        """True when storage confirmed the object is gone.

        S3's delete is already idempotent, so a missing object is a success. Everything
        else — permissions, an unreachable endpoint, a transport fault — returns False so
        the caller leaves the row alone and retries on the next pass. `BotoCoreError` is
        caught alongside `ClientError` because an endpoint outage raises the former, and
        letting it escape would abort the whole sweep on the first unreachable object.
        """
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except (ClientError, BotoCoreError) as exc:
            logger.warning("object_delete_failed", key=key, error=str(exc))
            return False
        return True


@lru_cache
def get_object_storage() -> S3ObjectStorage:
    return S3ObjectStorage()
