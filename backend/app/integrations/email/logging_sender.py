from app.core.logging import get_logger

logger = get_logger(__name__)


class LoggingEmailSender:
    """Dev/local stand-in — no real email provider is configured yet (ADR 0007).

    Logging the raw reset token is intentional ONLY because this is the no-provider
    fallback: it makes the token visible to a developer running the stack locally,
    the same way one would read it from an inbox. This must be replaced with a real
    provider (SES/Postmark/etc.) before any real deployment — logging a live reset
    token in a production log stream would be a genuine credential leak.
    """

    async def send_password_reset(self, *, to: str, token: str) -> None:
        logger.info("password_reset_email_not_sent_dev_mode", to=to, token=token)
