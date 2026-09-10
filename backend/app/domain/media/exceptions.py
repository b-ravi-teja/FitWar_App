"""Media domain errors. Pure — no HTTP status codes (Architecture §12)."""

from app.domain.common.exceptions import ConflictError, DomainError, NotFoundError


class MediaNotFoundError(NotFoundError):
    """Deliberately the same 404 another owner's media id produces — the lookup is
    owner-scoped, so this cannot be used to probe for valid ids."""

    code = "MEDIA_NOT_FOUND"


class MediaTypeNotAllowedError(DomainError):
    code = "UNSUPPORTED_MEDIA_TYPE"


class MediaNotReadyError(ConflictError):
    code = "MEDIA_NOT_READY"


class MediaTooLargeError(ConflictError):
    """The uploaded object exceeds the configured maximum proof size.

    Only reachable when the storage backend could not enforce the ceiling itself — a
    POST policy rejects an oversized upload before it is stored, whereas a presigned PUT
    has no length condition to carry (Cloudflare R2 has no PostObject). The check runs
    for both, so the limit holds whichever backend is deployed.
    """

    code = "MEDIA_TOO_LARGE"


class MediaUploadNotFoundInStorageError(ConflictError):
    code = "UPLOAD_NOT_FOUND_IN_STORAGE"


class MediaUnavailableError(ConflictError):
    """The object was deleted by retention; the record remains."""

    code = "MEDIA_EXPIRED"
