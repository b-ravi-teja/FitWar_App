"""Provider lookup by the challenge's declared verification method (Architecture §8).

Adding Health Connect, Garmin or a camera provider later means registering one more
entry here — `challenge_service` and `verification_service` never name a provider.
"""

from app.domain.verification.result import VerificationProvider
from app.integrations.verification_providers.apple_health import AppleHealthProvider
from app.integrations.verification_providers.manual_proof import ManualProofProvider

# Keyed by `models.challenge.VerificationMethod` values. Phase 6 added manual_proof,
# which needed MediaAsset and the review workflow (§20.5) to exist first.
_PROVIDERS: dict[str, VerificationProvider] = {
    "apple_health": AppleHealthProvider(),
    "manual_proof": ManualProofProvider(),
}


def get_provider(verification_method: str) -> VerificationProvider | None:
    return _PROVIDERS.get(verification_method)


def supported_methods() -> tuple[str, ...]:
    return tuple(_PROVIDERS)
