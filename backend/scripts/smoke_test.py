"""Post-deployment smoke test. Exercises a deployed FITWAR API over the public internet.

Deliberately *not* part of the pytest suite: those tests import the app and talk to a
database directly, which proves the code is correct and proves nothing about whether a
deployment is reachable, terminates TLS, resolves its database, or has the environment
variables it needs. This drives the same paths a phone would, through the same URL.

Run against the same image that was deployed:

    docker run --rm ghcr.io/<owner>/fitwar-backend:<sha> \\
        python -m scripts.smoke_test https://staging-api.example.com

Test data: one dedicated account per environment, reused across runs, named by
SMOKE_EMAIL/SMOKE_PASSWORD. Registering a fresh account every run would leave a trail of
abandoned users in the database of whatever environment this points at, which is not
something a production smoke test should do.
"""

import asyncio
import os
import sys
import uuid
from dataclasses import dataclass, field

import httpx
import websockets

TIMEOUT = httpx.Timeout(30.0)


@dataclass
class Results:
    passed: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)

    def ok(self, name: str) -> None:
        self.passed.append(name)
        print(f"  PASS  {name}", flush=True)

    def fail(self, name: str, detail: str) -> None:
        self.failed.append((name, detail))
        print(f"  FAIL  {name}: {detail}", flush=True)


def _ws_url(base_url: str, path: str) -> str:
    """wss for https, ws for http — never a hardcoded scheme, so this works against a
    local container and a TLS-terminated deployment without editing."""
    if base_url.startswith("https://"):
        return "wss://" + base_url[len("https://") :] + path
    return "ws://" + base_url[len("http://") :] + path


async def run(base_url: str, email: str, password: str) -> Results:
    base_url = base_url.rstrip("/")
    r = Results()

    async with httpx.AsyncClient(base_url=base_url, timeout=TIMEOUT) as http:
        # --- Public -----------------------------------------------------------
        try:
            resp = await http.get("/health")
            body = resp.json()
            if resp.status_code == 200 and body.get("status") == "healthy":
                r.ok("health: 200, database and redis healthy")
            else:
                r.fail("health", f"status={resp.status_code} body={body}")
                # Everything below needs a working database and Redis; continuing would
                # produce a wall of failures that all say the same thing.
                return r
        except Exception as exc:
            r.fail("health", f"{type(exc).__name__}: {exc}")
            return r

        # --- Authentication ---------------------------------------------------
        tokens: dict[str, str] = {}
        try:
            resp = await http.post(
                "/api/v1/auth/login", json={"email": email, "password": password}
            )
            if resp.status_code == 401:
                # First run against this environment: create the dedicated account.
                reg = await http.post(
                    "/api/v1/auth/register",
                    json={"email": email, "password": password, "display_name": "Smoke"},
                )
                if reg.status_code not in (200, 201):
                    r.fail("auth: register smoke account", f"status={reg.status_code}")
                    return r
                r.ok("auth: registered dedicated smoke account")
                resp = await http.post(
                    "/api/v1/auth/login", json={"email": email, "password": password}
                )
            if resp.status_code == 200:
                tokens = resp.json()
                r.ok("auth: login returned tokens")
            else:
                r.fail("auth: login", f"status={resp.status_code}")
                return r
        except Exception as exc:
            r.fail("auth: login", f"{type(exc).__name__}: {exc}")
            return r

        access = tokens.get("access_token", "")
        auth = {"Authorization": f"Bearer {access}"}

        # --- Token refresh ----------------------------------------------------
        try:
            resp = await http.post(
                "/api/v1/auth/refresh", json={"refresh_token": tokens.get("refresh_token", "")}
            )
            if resp.status_code == 200 and resp.json().get("access_token"):
                r.ok("auth: refresh rotated the token")
            else:
                r.fail("auth: refresh", f"status={resp.status_code}")
        except Exception as exc:
            r.fail("auth: refresh", f"{type(exc).__name__}: {exc}")

        # --- Database round trip ---------------------------------------------
        try:
            resp = await http.get("/api/v1/me", headers=auth)
            if resp.status_code == 200 and resp.json().get("email") == email:
                r.ok("db: /me returned the authenticated user")
            else:
                r.fail("db: /me", f"status={resp.status_code}")
        except Exception as exc:
            r.fail("db: /me", f"{type(exc).__name__}: {exc}")

        # --- Authorization ----------------------------------------------------
        try:
            resp = await http.get("/api/v1/me")
            if resp.status_code == 401:
                r.ok("authz: /me without a token is 401")
            else:
                r.fail("authz: unauthenticated /me", f"expected 401, got {resp.status_code}")
        except Exception as exc:
            r.fail("authz: unauthenticated /me", f"{type(exc).__name__}: {exc}")

        # --- Game read --------------------------------------------------------
        try:
            resp = await http.get("/api/v1/challenges", headers=auth)
            if resp.status_code == 200 and isinstance(resp.json(), list):
                r.ok("game: challenge list read")
            else:
                r.fail("game: challenge list", f"status={resp.status_code}")
        except Exception as exc:
            r.fail("game: challenge list", f"{type(exc).__name__}: {exc}")

        # --- Group (also the subject of the websocket check below) -------------
        # Reused across runs like the account is, for the same reason: a group per run
        # would accumulate in whatever environment this points at.
        try:
            resp = await http.get("/api/v1/groups", headers=auth)
            groups = resp.json() if resp.status_code == 200 else []
            if not groups:
                created = await http.post(
                    "/api/v1/groups",
                    headers=auth,
                    json={"name": "Smoke Test", "timezone": "UTC"},
                )
                if created.status_code == 201:
                    groups = [created.json()]
                    r.ok("game: created the dedicated smoke group")
                else:
                    r.fail("game: create group", f"status={created.status_code}")
            if groups:
                group_id = groups[0]["id"]
                r.ok("game: group read")
            else:
                group_id = None
        except Exception as exc:
            r.fail("game: group", f"{type(exc).__name__}: {exc}")
            group_id = None

        # --- Media ------------------------------------------------------------
        # Asks for a grant only. Uploading a real object would leave bytes in the
        # bucket of whatever environment this runs against.
        try:
            resp = await http.post(
                "/api/v1/media/upload-url", headers=auth, json={"content_type": "video/mp4"}
            )
            if resp.status_code == 201:
                grant = resp.json()
                url = grant.get("url", "")
                # A deployed API must hand out https upload URLs — a presigned grant is
                # a bearer credential in a query string. Asserted only when the API
                # itself is https, so this same script still passes against a local
                # container talking to MinIO over http.
                if base_url.startswith("https://") and not url.startswith("https://"):
                    r.fail("media: presigned grant", "upload URL is not https")
                elif url:
                    scheme = url.split(":")[0]
                    method = grant.get("method", "POST")
                    r.ok(f"media: presigned {method} grant ({scheme})")
                else:
                    r.fail("media: presigned grant", "no upload URL returned")
            else:
                r.fail("media: presigned grant", f"status={resp.status_code}")
        except Exception as exc:
            r.fail("media: presigned grant", f"{type(exc).__name__}: {exc}")

        # --- Rate limiting ----------------------------------------------------
        # Confirms the limiter is actually reachable in the deployed environment: a
        # missing Redis with RATE_LIMIT_FAIL_OPEN left on would silently never 429.
        try:
            statuses = []
            for _ in range(25):
                bad = await http.post(
                    "/api/v1/auth/login",
                    json={"email": f"nobody-{uuid.uuid4()}@example.com", "password": "wrong-pw-1"},
                )
                statuses.append(bad.status_code)
                if bad.status_code == 429:
                    break
            if 429 in statuses:
                r.ok(f"rate limit: 429 after {len(statuses)} bad logins")
            else:
                r.fail("rate limit", "no 429 within 25 failed logins")
        except Exception as exc:
            r.fail("rate limit", f"{type(exc).__name__}: {exc}")

    # --- Realtime -------------------------------------------------------------
    # Through the public hostname, so this covers TLS termination and whether the proxy
    # in front of the app actually forwards an Upgrade — the part a local container
    # cannot tell you anything about.
    if group_id is None:
        r.fail("realtime: websocket", "no group available to subscribe to")
    else:
        try:
            url = _ws_url(base_url, f"/api/v1/ws/groups/{group_id}?token={access}")
            async with websockets.connect(url, open_timeout=20) as ws:
                await ws.ping()
                r.ok("realtime: authorized websocket handshake and ping")
        except Exception as exc:
            r.fail("realtime: websocket", f"{type(exc).__name__}: {exc}")

        # An unauthenticated socket must be refused, or the gateway is an open channel.
        try:
            url = _ws_url(base_url, f"/api/v1/ws/groups/{group_id}")
            async with websockets.connect(url, open_timeout=20) as ws:
                await ws.recv()
            r.fail("realtime: unauthenticated websocket", "connection was accepted")
        except Exception:
            r.ok("realtime: unauthenticated websocket refused")

    return r


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python -m scripts.smoke_test <base-url>", file=sys.stderr)
        raise SystemExit(2)

    base_url = sys.argv[1]
    email = os.environ.get("SMOKE_EMAIL")
    password = os.environ.get("SMOKE_PASSWORD")
    if not email or not password:
        print("SMOKE_EMAIL and SMOKE_PASSWORD must be set.", file=sys.stderr)
        raise SystemExit(2)

    print(f"FITWAR smoke test against {base_url}", flush=True)
    results = asyncio.run(run(base_url, email, password))

    print(f"\n{len(results.passed)} passed, {len(results.failed)} failed", flush=True)
    raise SystemExit(1 if results.failed else 0)


if __name__ == "__main__":
    main()
