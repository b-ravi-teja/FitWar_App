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


class MediaUploadNotFoundInStorageError(ConflictError):
    code = "UPLOAD_NOT_FOUND_IN_STORAGE"


class MediaUnavailableError(ConflictError):
    """The object was deleted by retention; the record remains."""

    code = "MEDIA_EXPIRED"
