"""Object storage abstraction (Architecture §9).

The protocol exists so nothing above `integrations/` names S3. Swapping MinIO for AWS,
R2 or GCS is a new implementation of this, not a change to media or proof logic.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PresignedUpload:
    """A short-lived, single-object write grant.

    The client never holds bucket credentials (§34) — it gets this, scoped to one
    server-chosen key, and it expires.
    """

    url: str
    fields: dict[str, str]
    expires_in_seconds: int


class ObjectStorage(Protocol):
    def presigned_upload(
        self, *, key: str, content_type: str, max_bytes: int, expires_in: int
    ) -> PresignedUpload: ...

    def presigned_download(self, *, key: str, expires_in: int) -> str: ...

    def head(self, *, key: str) -> tuple[int, str] | None:
        """(size_bytes, content_type) for an existing object, or None if absent."""
        ...

    def delete(self, *, key: str) -> bool:
        """Delete one object. Returns whether storage confirmed it is gone.

        Idempotent — deleting an absent object succeeds. A `False` means the delete did
        not happen (transport failure, permissions), and the caller must **not** record
        the object as removed: doing so orphans the bytes forever while the metadata
        claims they are gone.
        """
        ...
