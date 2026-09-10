"""The transactional email provider wired up for deployment (Phase 8 audit item).

Two properties matter here and neither is about whether mail arrives: the reset code
must never reach a log, and a delivery failure must not change what
`POST /auth/password-reset/request` returns.
"""

import httpx
import pytest

from app.core.config import get_settings
from app.integrations.email.resend import EmailDeliveryError, ResendEmailSender

TOKEN = "reset-token-that-must-never-be-logged-4a91f2"


@pytest.fixture
def sender(monkeypatch) -> ResendEmailSender:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(get_settings().email, "api_key", _Secret("re_test_key"))
    monkeypatch.setattr(get_settings().email, "from_address", "FITWAR <no-reply@example.com>")
    return ResendEmailSender()


class _Secret:
    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


def _capture_post(monkeypatch, response: httpx.Response):  # type: ignore[no-untyped-def]
    sent: dict[str, object] = {}

    async def _post(self, url, *, json=None, headers=None):  # type: ignore[no-untyped-def]
        sent["url"] = url
        sent["json"] = json
        sent["headers"] = headers
        return response

    monkeypatch.setattr(httpx.AsyncClient, "post", _post)
    return sent


class TestResendEmailSender:
    async def test_it_sends_the_code_to_the_requested_address(
        self, sender, monkeypatch
    ) -> None:
        sent = _capture_post(monkeypatch, httpx.Response(200, json={"id": "x"}))

        await sender.send_password_reset(to="someone@example.com", token=TOKEN)

        assert sent["url"] == "https://api.resend.com/emails"
        assert sent["json"]["to"] == ["someone@example.com"]  # type: ignore[index]
        # The app asks the user to paste the code, so it has to be in the body.
        assert TOKEN in sent["json"]["text"]  # type: ignore[index]

    async def test_the_code_never_appears_in_a_url(self, sender, monkeypatch) -> None:
        """A token in a URL ends up in browser history, referrer headers and access
        logs — none of which are places a live credential should be."""
        sent = _capture_post(monkeypatch, httpx.Response(200, json={"id": "x"}))

        await sender.send_password_reset(to="someone@example.com", token=TOKEN)

        assert TOKEN not in str(sent["url"])
        assert TOKEN not in sent["json"]["text"].split("\n")[0]  # type: ignore[index]

    async def test_a_rejected_message_raises_without_echoing_the_body(
        self, sender, monkeypatch, caplog
    ) -> None:
        _capture_post(monkeypatch, httpx.Response(422, text=f"bad recipient {TOKEN}"))

        with pytest.raises(EmailDeliveryError):
            await sender.send_password_reset(to="someone@example.com", token=TOKEN)

        assert TOKEN not in caplog.text

    async def test_a_transport_failure_raises(self, sender, monkeypatch) -> None:
        async def _boom(self, url, *, json=None, headers=None):  # type: ignore[no-untyped-def]
            raise httpx.ConnectError("no route to host")

        monkeypatch.setattr(httpx.AsyncClient, "post", _boom)

        with pytest.raises(EmailDeliveryError):
            await sender.send_password_reset(to="someone@example.com", token=TOKEN)


class TestResetRequestSurvivesDeliveryFailure:
    async def test_the_response_is_the_same_whether_or_not_email_sends(
        self, client, register_actor, monkeypatch
    ) -> None:
        """Otherwise a broken provider reinstates the account-enumeration oracle the
        uniform 202 exists to close: a real address would 500 while an unknown one
        still returned 202.

        The sender is replaced rather than httpx being patched, because the test client
        is itself an `httpx.AsyncClient` — patching the transport would break the very
        requests this test makes.
        """
        actor = await register_actor(client, "ResetRequester")
        email = (await client.get("/api/v1/me", headers=actor.headers)).json()["email"]

        class _BrokenSender:
            async def send_password_reset(self, *, to: str, token: str) -> None:
                raise EmailDeliveryError("provider down")

        monkeypatch.setattr(
            "app.services.auth_service.get_email_sender", lambda: _BrokenSender()
        )

        existing = await client.post(
            "/api/v1/auth/password-reset/request", json={"email": email}
        )
        unknown = await client.post(
            "/api/v1/auth/password-reset/request",
            json={"email": "definitely-not-registered@example.com"},
        )

        assert existing.status_code == unknown.status_code == 202
        assert existing.json() == unknown.json()
