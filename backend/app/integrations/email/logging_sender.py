from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmailProviderNotConfiguredError(RuntimeError):
    """No real email provider is configured, and the dev fallback is not safe here."""


class LoggingEmailSender:
    """Dev/local stand-in — no real email provider is configured yet (ADR 0007).

    Logging the raw reset token is intentional ONLY as the no-provider fallback: it makes
    the token visible to a developer running the stack locally, the same way one would
    read it from an inbox.

    In production that is a credential leak — a live password-reset token in a log stream
    is account takeover for anyone who can read logs, which is typically a much wider
    group than those who can read mailboxes. The docstring used to say so and nothing
    enforced it, so a deployment with no provider configured would have leaked silently.
    It now refuses instead: `POST /auth/password-reset/request` fails loudly rather than
    appearing to work while writing tokens to disk.
    """

    def __init__(self) -> None:
        if get_settings().app.is_production:
            raise EmailProviderNotConfiguredError(
                "No email provider is configured. The development LoggingEmailSender "
                "writes password-reset tokens to the log and must never run in "
                "production — configure a real transactional-email provider."
            )

    async def send_password_reset(self, *, to: str, token: str) -> None:
        logger.info("password_reset_email_not_sent_dev_mode", to=to, token=token)
