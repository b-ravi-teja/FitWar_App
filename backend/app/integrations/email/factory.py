"""Which `EmailSender` this deployment uses — a configuration choice, not a code one."""

from functools import lru_cache

from app.core.config import get_settings
from app.integrations.email.base import EmailSender
from app.integrations.email.logging_sender import LoggingEmailSender
from app.integrations.email.resend import ResendEmailSender


@lru_cache
def get_email_sender() -> EmailSender:
    """Build the configured sender once.

    `LoggingEmailSender` refuses to construct in a production environment (it writes the
    reset token to the log), so a staging or production deployment that forgets
    EMAIL_PROVIDER fails loudly at the first reset request rather than quietly logging
    live tokens.
    """
    if get_settings().email.provider == "resend":
        return ResendEmailSender()
    return LoggingEmailSender()
