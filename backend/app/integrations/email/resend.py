"""Resend transactional email (Phase 8 audit item: no real provider was configured).

Chosen for a low-budget beta because its free tier covers FITWAR's only transactional
email — password reset — without a card on file, and because it is a plain HTTPS JSON
API, so it needs no SDK and no SMTP credentials in the environment.

The reset *code* is the secret this file handles. It is never logged, never put in a URL
and never included in an error message: a live reset token in a log stream is account
takeover for everyone who can read logs, which is a far wider group than everyone who
can read the mailbox it was sent to.
"""

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_RESEND_ENDPOINT = "https://api.resend.com/emails"


class EmailDeliveryError(RuntimeError):
    """The provider did not accept the message.

    Carries no message body, so a token can never reach a log through an exception
    string. The caller decides what to do; `AuthService` deliberately keeps its
    response identical either way, because a reset request that fails differently for a
    real address than a fake one is an account-enumeration oracle.
    """


class ResendEmailSender:
    """Implements `EmailSender`."""

    def __init__(self) -> None:
        settings = get_settings().email
        api_key = settings.api_key
        if api_key is None:
            raise ValueError("EMAIL_PROVIDER=resend requires EMAIL_API_KEY.")
        self._api_key = api_key.get_secret_value()
        self._from = settings.from_address
        self._timeout = settings.timeout_seconds

    async def send_password_reset(self, *, to: str, token: str) -> None:
        # The app asks the user to paste this code (ForgotPasswordView), so the mail
        # carries the code itself rather than a deep link. That also keeps the token out
        # of any URL, where it would end up in browser history and referrer headers.
        text = (
            "Your FITWAR password reset code:\n\n"
            f"{token}\n\n"
            "Paste it into the app to choose a new password. It expires shortly and can "
            "only be used once.\n\n"
            "If you didn't ask to reset your password, you can ignore this email — "
            "nothing has changed."
        )
        payload = {
            "from": self._from,
            "to": [to],
            "subject": "Your FITWAR password reset code",
            "text": text,
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    _RESEND_ENDPOINT,
                    json=payload,
                    headers={"Authorization": f"Bearer {self._api_key}"},
                )
        except httpx.HTTPError as exc:
            # `type(exc).__name__`, not `str(exc)`: httpx puts the request URL in its
            # message, and there is no reason to widen what gets written here.
            logger.error("password_reset_email_transport_failed", error=type(exc).__name__)
            raise EmailDeliveryError("Email transport failed.") from None

        if response.status_code >= 400:
            # Status only. The body is the provider's, and echoing an unknown payload
            # into structured logs is how secrets get copied into places nobody audits.
            logger.error("password_reset_email_rejected", status_code=response.status_code)
            raise EmailDeliveryError("Email provider rejected the message.")

        logger.info("password_reset_email_sent")
