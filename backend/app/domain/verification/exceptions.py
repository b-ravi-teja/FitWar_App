"""Verification domain errors. Pure — no HTTP status codes (Architecture §12)."""

from app.domain.common.exceptions import (
    ConflictError,
    DomainError,
    ForbiddenError,
    NotFoundError,
)


class InvalidEvidenceError(DomainError):
    """Malformed or incompatible evidence — a client bug, not a failed attempt."""

    code = "INVALID_EVIDENCE"


class VerificationMethodMismatchError(ConflictError):
    """Evidence submitted through a provider this challenge does not use."""

    code = "VERIFICATION_METHOD_MISMATCH"


class AlreadyVerifiedError(ConflictError):
    """The day already holds a verified result.

    Carries the existing result so the API can answer an exact retry idempotently
    rather than failing it (API_SPEC: `ALREADY_VERIFIED_TODAY`).
    """

    code = "ALREADY_VERIFIED_TODAY"


class HealthConnectionNotFoundError(NotFoundError):
    """A 404, and deliberately the same 404 another user's connection id produces —
    the lookup is owner-scoped, so this can't be used to probe for valid ids."""

    code = "HEALTH_CONNECTION_NOT_FOUND"


class ProofNotFoundError(NotFoundError):
    """Also returned when a proof belongs to a challenge the caller doesn't review —
    an identical 404, so this cannot enumerate proofs outside the reviewer's scope."""

    code = "PROOF_NOT_FOUND"


class SelfReviewForbiddenError(ForbiddenError):
    """A participant may never approve their own proof, whatever else they administer."""

    code = "CANNOT_REVIEW_OWN_PROOF"


class ProofAlreadyResolvedError(ConflictError):
    code = "PROOF_ALREADY_RESOLVED"


class NotAReviewerError(ForbiddenError):
    code = "NOT_A_REVIEWER"
