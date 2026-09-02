"""S3-compatible storage. MinIO locally, AWS S3 (or any S3 API) in production."""

from functools import lru_cache

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings
from app.core.logging import get_logger
from app.integrations.storage.base import PresignedUpload

logger = get_logger(__name__)


class S3ObjectStorage:
    """Implements `ObjectStorage`."""

    def __init__(self) -> None:
        settings = get_settings().storage
        self._bucket = settings.bucket_name
        self._client = boto3.client(
            "s3",
            endpoint_url=settings.endpoint_url,
            region_name=settings.region,
            aws_access_key_id=settings.access_key_id,
            aws_secret_access_key=settings.secret_access_key.get_secret_value(),
            # Path-style addressing: MinIO doesn't do virtual-host buckets by default,
            # and S3 accepts it too, so one config works for both.
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
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
        """A POST policy rather than a plain PUT URL.

        The policy pins both the content type and a maximum length, so the size and type
        limits are enforced by storage itself — not merely promised by the client and
        checked afterwards.
        """
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
            url=post["url"], fields=post["fields"], expires_in_seconds=expires_in
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

    def delete(self, *, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            # S3 delete is already idempotent; this only catches transport/permission
            # problems, which the caller retries on the next cleanup pass.
            logger.warning("object_delete_failed", key=key, error=str(exc))


@lru_cache
def get_object_storage() -> S3ObjectStorage:
    return S3ObjectStorage()
