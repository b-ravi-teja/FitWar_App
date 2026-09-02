from typing import Protocol


class EmailSender(Protocol):
    """Same abstraction pattern as `ObjectStorage`/`VerificationProvider` (Architecture
    §8/§9): the concrete transactional-email provider is a deployment-time config
    choice, never imported by domain or service code directly (ADR 0007)."""

    async def send_password_reset(self, *, to: str, token: str) -> None: ...
