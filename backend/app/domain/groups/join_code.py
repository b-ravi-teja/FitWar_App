"""Invite-code generation.

Shape matches the design's own code exactly (`K7-XR9` — two characters, hyphen, three).
The alphabet drops I/O/0/1 because these codes get read aloud and typed by hand, and
those four are where transcription errors come from.
"""

import secrets

ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
PREFIX_LENGTH = 2
SUFFIX_LENGTH = 3


def generate_join_code() -> str:
    prefix = "".join(secrets.choice(ALPHABET) for _ in range(PREFIX_LENGTH))
    suffix = "".join(secrets.choice(ALPHABET) for _ in range(SUFFIX_LENGTH))
    return f"{prefix}-{suffix}"


def normalize_join_code(raw: str) -> str:
    """Accept what a human types — lowercase, spaces, a missing hyphen — and canonicalize.

    Rejecting `k7 xr9` when the stored code is `K7-XR9` would be a needless failure.
    """
    stripped = "".join(ch for ch in raw.upper() if ch.isalnum())
    if len(stripped) != PREFIX_LENGTH + SUFFIX_LENGTH:
        return stripped
    return f"{stripped[:PREFIX_LENGTH]}-{stripped[PREFIX_LENGTH:]}"
