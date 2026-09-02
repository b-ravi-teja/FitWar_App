"""Provider lookup by the challenge's declared verification method (Architecture §8).

Adding Health Connect, Garmin or a camera provider later means registering one more
entry here — `challenge_service` and `verification_service` never name a provider.
"""

from app.domain.verification.result import VerificationProvider
from app.integrations.verification_providers.apple_health import AppleHealthProvider

# Keyed by `models.challenge.VerificationMethod` values. MANUAL_PROOF is deliberately
# absent: it needs `MediaAsset` and the review workflow (§20.5), neither of which
# exists yet, and registering a provider that cannot work would be worse than a
# lookup that fails loudly.
_PROVIDERS: dict[str, VerificationProvider] = {
    "apple_health": AppleHealthProvider(),
}


def get_provider(verification_method: str) -> VerificationProvider | None:
    return _PROVIDERS.get(verification_method)


def supported_methods() -> tuple[str, ...]:
    return tuple(_PROVIDERS)
