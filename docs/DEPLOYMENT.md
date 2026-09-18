# FITWAR — Deployment

How the backend gets from a commit to a running staging or production service, what you
have to create by hand, and what each of those things costs.

Nothing in this repository contains a secret. Everything sensitive is created in a
provider's dashboard and pasted into GitHub or Render, which is why the setup below is a
checklist rather than a script.

---

## 1. Architecture

```
GitHub  ──push to main──▶  GitHub Actions
                                │
                    ┌───────────┴───────────┐
                    │  CI: ruff, mypy,      │
                    │  alembic, 558 tests   │
                    └───────────┬───────────┘
                                │ passes
                                ▼
                 build ONE image ──▶ GHCR (tagged by commit SHA)
                                │
                         ┌──────┴──────┐
                         ▼             ▼
                 alembic upgrade   deploy by DIGEST
                         │             │
                         └──────┬──────┘
                                ▼
                          Render (Docker)
                                │
                              FastAPI
                                │
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
   Supabase Postgres      Upstash Redis        Cloudflare R2
   (session pooler)     (rate limits,          (proof video,
                         pub/sub, reset          presigned PUT)
                         tokens)

   Scheduled: deadline sweep (15 min) · media cleanup (hourly)
```

The application does not know any of those brand names. It reads `DATABASE_URL`,
`REDIS_URL` and the `STORAGE_*` variables, because Supabase is Postgres, Upstash is
Redis, and R2 is an S3 API. The abstractions from Architecture §8/§9 are unchanged.

---

## 2. What you have to create

Six accounts. Each row's **Copy** column is what you paste somewhere in §3.

| # | Account | Create | Copy |
|---|---|---|---|
| 1 | **GitHub** (have) | Nothing — the repo exists | — |
| 2 | **Supabase** | A project named `fitwar-staging`, region nearest your users | The **Session pooler** connection string |
| 3 | **Upstash** | A Redis database named `fitwar-staging`, same region | The `rediss://` URL |
| 4 | **Cloudflare** | An R2 bucket `fitwar-staging-media`, **private** | Account ID, Access Key ID, Secret Access Key |
| 5 | **Render** | A Web Service, "Deploy an existing image" | The service ID (`srv-…`) and an API key |
| 6 | **Resend** | An API key, and verify your sending domain | The API key and your from-address |

Plus **a domain you own**, for `staging-api.<your-domain>`.

### 2.1 Supabase — use the session pooler, not the direct connection

Dashboard → **Connect** → **Session pooler**. It looks like:

```
postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres
```

Take it from the dashboard; do not assemble it by hand.

Why the session pooler and not the direct connection: the direct connection
(`db.<ref>.supabase.co`) is **IPv6-only** unless you buy the IPv4 add-on, and Render does
not give services IPv6 egress. The shared session pooler is IPv4 on all plans, and —
unlike the *transaction* pooler on port 6543 — it supports prepared statements, which
asyncpg uses by default. Port **5432**, not 6543.

If you are ever forced onto a transaction-mode pooler, set
`DATABASE_DISABLE_PREPARED_STATEMENTS=true`. Without it you get
`InvalidSQLStatementNameError` under concurrency and nothing at startup.

Add `?sslmode=require` if the copied string does not already have it. The app translates
libpq's `sslmode` into asyncpg's `ssl` argument itself (`normalize_asyncpg_dsn`), so you
do not have to edit the string.

**Do not create tables in the Supabase table editor.** Alembic owns the schema; anything
made by hand becomes drift that `alembic check` will fail on.

### 2.2 Upstash — the standard Redis protocol, not the REST API

Copy the **`rediss://`** URL (TLS). `redis-py` handles it with no code change —
`Redis.from_url` reads the scheme.

**Do not configure the REST API.** The console shows `UPSTASH_REDIS_REST_URL` and
`UPSTASH_REDIS_REST_TOKEN` prominently, and they are the wrong thing here: FITWAR uses
Redis **pub/sub** for realtime (`app/core/realtime.py`), and the REST API has no pub/sub.

The two are related, which is a useful shortcut and a trap. The REST token doubles as the
Redis password, and the REST URL's host is the Redis host, so:

```
REST:  https://<name>.upstash.io  +  token
Redis: rediss://default:<token>@<name>.upstash.io:6379
```

Verified working, pub/sub included. TLS is mandatory — `redis://` on port 6379 is closed
by the server immediately.

### 2.3 Cloudflare R2 — private bucket, and a genuine incompatibility

Create the bucket with **no public access** and **no custom public domain**. Proof videos
are private; every read goes through a short-lived presigned GET the API issues.

Then R2 → **Manage R2 API Tokens** → create a token scoped to *this bucket only*, with
**Object Read & Write**. You get an Access Key ID and a Secret Access Key, and your
endpoint is `https://<account-id>.r2.cloudflarestorage.com`.

`STORAGE_REGION` must be `auto` — R2 accepts nothing else.

**The incompatibility:** R2 does not implement S3's `PostObject`. Its presigned URLs cover
GET, PUT, HEAD and DELETE only. FITWAR's upload flow was built on a presigned **POST
policy**, whose `content-length-range` condition let storage itself reject an oversized
upload before storing it.

So an R2 deployment sets `STORAGE_UPLOAD_METHOD=put` and the flow becomes:

```
iPhone ──▶ POST /media/upload-url ──▶ signed PUT URL (content-type signed)
iPhone ──────────────── PUT bytes ───────────────▶ R2
iPhone ──▶ POST /media/{id}/complete ──▶ server HEADs the object and checks its size
```

The size ceiling still holds — `MediaService.complete_upload` reads the stored object
back and rejects anything over `MEDIA_MAX_PROOF_BYTES`, deleting it. What changes is
*where* an oversized upload is stopped: on S3/MinIO the bytes never land, on R2 they land
and are then deleted. R2 charges nothing for ingress, so the cost of that is a Class A
operation, not bandwidth. Video bytes still never pass through Render either way.

Keep `STORAGE_UPLOAD_METHOD=post` anywhere the backend is S3 or MinIO — it is the
stronger of the two.

### 2.4 Render — deploy an image, do not build from the repo

New → **Web Service** → **Existing image**. Enter any image to get the service created;
the deploy workflow replaces it with a digest on every deploy.

- Health check path: `/health`
- Do **not** enable auto-deploy. GitHub Actions drives deploys, so that both environments
  get the same artifact.
- Render sets `$PORT`; the image already honours it.
- The image is private on GHCR, so add a **registry credential**: Render → Settings →
  Registry Credentials → GitHub, with a PAT that has `read:packages`.

Then Settings → **Custom Domain** → `staging-api.<your-domain>`, and add the CNAME Render
gives you at your DNS provider. Render provisions the TLS certificate. WebSockets need
nothing extra — Render forwards `Upgrade`, so `wss://` works once `https://` does.

Get the service ID from the URL: `dashboard.render.com/web/srv-XXXX` → `srv-XXXX`.
Create an API key under Account Settings → API Keys.

### 2.5 Resend

Verify your domain (DNS records they give you), create an API key, and set
`EMAIL_FROM_ADDRESS` to an address on that domain. Until the domain is verified you can
send only to your own address, which is enough to test the reset flow but not enough for
a beta.

---

## 3. Where each value goes

Repository → Settings → **Environments** → create `staging` and `production`.
On `production`, add yourself under **Required reviewers** — that approval is what
actually gates a production deploy.

### Environment secrets — `staging`

| Secret | Value |
|---|---|
| `STAGING_DATABASE_URL` | Supabase session pooler URI |
| `STAGING_REDIS_URL` | Upstash `rediss://` URL |
| `STAGING_JWT_SECRET` | `openssl rand -hex 32` — a fresh one, not reused from anywhere |
| `STAGING_STORAGE_ENDPOINT_URL` | `https://<account-id>.r2.cloudflarestorage.com` |
| `STAGING_STORAGE_BUCKET_NAME` | `fitwar-staging-media` |
| `STAGING_STORAGE_ACCESS_KEY_ID` | R2 token access key |
| `STAGING_STORAGE_SECRET_ACCESS_KEY` | R2 token secret |
| `STAGING_EMAIL_API_KEY` | Resend API key |
| `STAGING_SMOKE_EMAIL` | e.g. `smoke@<your-domain>` — a normal-looking domain; `EmailStr` rejects special-use TLDs like `.invalid` and `.test` with a 422 |
| `STAGING_SMOKE_PASSWORD` | `openssl rand -base64 24` |
| `RENDER_API_KEY` | Render API key |
| `RENDER_STAGING_SERVICE_ID` | `srv-…` |

### Environment variables (not secrets) — `staging`

| Variable | Value |
|---|---|
| `STAGING_API_URL` | `https://staging-api.<your-domain>` |

`production` takes the same list with `PRODUCTION_` prefixes and its own separate
Supabase project, Upstash database, R2 bucket and JWT secret. Sharing any of them between
environments defeats the isolation in Architecture §15.

### Render service environment

Set these in the Render dashboard (or import `render.yaml` as a Blueprint, which prompts
for each `sync: false` value):

`APP_ENV=staging` · `APP_DEBUG=false` · `APP_CORS_ORIGINS=[]` · `WEB_CONCURRENCY=1` ·
`DATABASE_URL` · `DATABASE_POOL_SIZE=5` · `DATABASE_MAX_OVERFLOW=0` · `REDIS_URL` ·
`AUTH_JWT_SECRET` · `RATE_LIMIT_TRUSTED_PROXY_COUNT=1` · `RATE_LIMIT_ENABLED=true` ·
`RATE_LIMIT_FAIL_OPEN=false` · `STORAGE_ENDPOINT_URL` · `STORAGE_REGION=auto` ·
`STORAGE_BUCKET_NAME` · `STORAGE_ACCESS_KEY_ID` · `STORAGE_SECRET_ACCESS_KEY` ·
`STORAGE_UPLOAD_METHOD=put` · `EMAIL_PROVIDER=resend` · `EMAIL_API_KEY` ·
`EMAIL_FROM_ADDRESS` · `SCHEDULER_DISABLED_JOBS=["deadline_sweep","media_cleanup"]`

Two of those are easy to get wrong:

- **`RATE_LIMIT_TRUSTED_PROXY_COUNT=1`.** Render is exactly one proxy. At `0` every
  request looks like it came from Render and per-IP rate limiting collapses into one
  global bucket. Too high and a client can spoof its own address via `X-Forwarded-For`.
- **`APP_CORS_ORIGINS=[]`.** The iOS app is not a browser and sends no `Origin` header.
  An empty list is correct; `["*"]` is refused at boot by the production config guard.

`APP_ENV=staging` turns that guard on: the process refuses to start with debug enabled, a
short or placeholder JWT secret, wildcard CORS, fail-open or disabled rate limiting, or
no real email provider.

---

## 4. CI

`.github/workflows/ci.yml`, on every pull request and every push to `main`.

```
ruff → mypy --strict → alembic upgrade head → alembic check
     → alembic downgrade/upgrade round trip → pytest (558) → docker build
```

Against **real** Postgres, Redis and MinIO service containers, not mocks. The integration
suites exercise `SELECT … FOR UPDATE`, partial indexes, Redis sliding windows and
presigned uploads; a mock reproduces none of those, and they are where this codebase's
bugs have actually been.

`alembic check` fails on drift between the ORM models and the migrations. The
downgrade/upgrade round trip proves the newest migration is reversible, which is what
makes rollback an option rather than a hope.

## 5. CD

**Staging** — `.github/workflows/deploy-staging.yml`, automatic on push to `main`:

```
CI (same run) → build+push image :sha → alembic upgrade head
  → deploy digest to Render → wait for live → /health from outside → smoke test
```

**Production** — `.github/workflows/deploy-production.yml`, `workflow_dispatch` only:

```
digest input + confirmation phrase → required reviewer approves
  → verify image exists → pg_dump backup → alembic upgrade head
  → deploy same digest → /health → smoke test → roll back service on failure
```

Production builds nothing. You pass it the digest that already passed staging — take it
from the `staging-image` artifact of the run you want to ship. That is what makes "staging
and production run the same bytes" checkable instead of assumed.

> **A note on ordering.** The brief's Phase M put the migration *after* the deploy. This
> runs it *before*, matching Phase P. Deploying first leaves new code running against the
> old schema for the length of the deploy, which is the window a migration exists to
> avoid. Migrating first is safe here only because the migrations are additive — see §6.

## 6. Migration strategy

Migrations must be **backward compatible**: the currently-deployed code has to keep
working against the new schema, because both are live at once during a deploy and again
during a rollback. In practice that means additive changes — new nullable columns, new
tables, new indexes.

A change that is not backward compatible is done in two deploys:

1. Add the new column, write to both, keep reading the old one.
2. Once every instance is on the new code, stop writing the old column; drop it in a
   later release.

**Rollback** rolls back the *application only*. `alembic downgrade` never runs
automatically — an automatic schema downgrade after a failed deploy is how a bad deploy
becomes lost data. Because migrations are additive, the previous image runs fine against
the migrated schema.

**Migrations that cannot be rolled back** — a dropped column, a narrowed type, a
destructive backfill — have no code path back. For those:

1. The `pg_dump` taken immediately before the migration (uploaded as a workflow artifact,
   30-day retention) is the only way back. Verify it restores into a scratch database
   *before* you run the deploy, not after.
2. Prefer Supabase's own point-in-time recovery if you are on a plan that has it.
3. Split the change so the irreversible half ships on its own, after the reversible half
   has been live long enough to be trusted.

## 7. Scheduled jobs

Both must run whether or not anyone opens the app: the deadline sweep is what turns a
missed day into a warning or an elimination, and media cleanup is what stops proof videos
outliving their retention window. Both are idempotent, so overlapping or repeated runs
are safe.

| Job | Command | Interval |
|---|---|---|
| Deadline sweep | `python -m app.workers.deadline_sweep` | every 15 min |
| Media cleanup | `python -m app.workers.media_cleanup` | hourly |

Same image, same entry points a developer runs by hand, so "scheduled" and "run it
manually" cannot drift apart.

**Pick one of two options — running both just doubles the metered work:**

- **`.github/workflows/scheduled-jobs.yml`** — free. GitHub's scheduler is best-effort and
  can be delayed several minutes under load, which a 15-minute interval absorbs.
- **The `cron` services in `render.yaml`** — Render has no free cron tier, so this costs
  money (see §9). Better isolation, and it keeps the database URL out of Actions.

A third option exists and does **not** work on Render's free tier: the app's own
in-process scheduler (`SCHEDULER_DISABLED_JOBS=[]`). A free web service sleeps after 15
minutes of no traffic, so the loop stops with it. It becomes viable the moment the web
service is on a paid plan that does not sleep, and is then the simplest of the three.

## 8. Monitoring

Deliberately nothing new. An expensive observability stack for a beta with no users is
infrastructure added because it is available.

| Need | Where |
|---|---|
| Is it up | Render health checks, driven by `/health` (503 when Postgres or Redis is down) |
| Logs | Render dashboard → Logs. Structured JSON via structlog, request-id on every line |
| Errors | Same stream — every unhandled error is one `Problem Details` log entry |
| Deploys | GitHub Actions run history; Render deploy list |
| Database | Supabase dashboard → Database Health |
| Redis | Upstash console → usage and command count |

Set up one external uptime check against `https://staging-api.<domain>/health` when you
want to know about outages without looking. Any free tier will do; nothing in the repo
depends on it.

## 9. Cost

Every figure below is the provider's published free allowance at the time of writing.
**A free tier is not an SLA.** None of these carry an uptime guarantee, and Render and
Supabase both suspend free resources on inactivity. That is acceptable for staging and is
a decision to revisit before real users depend on it.

| Service | Tier | Included | The limitation that matters | Cost trigger |
|---|---|---|---|---|
| GitHub | Free | Private repos, 2,000 Actions min/mo | Deploys and scheduled jobs both consume minutes | Scheduled jobs every 15 min ≈ 2,880 runs/mo — **will exceed the free minutes on a private repo** |
| GHCR | Free | 500MB private storage | Every commit to main pushes an image | Old images accumulate; prune them |
| Render (web) | Free | 750 instance-hrs/mo, 512MB | **Sleeps after 15 min idle; ~1 min cold start** | One always-on service costs 730 hrs — a second free service exhausts the pool. Starter ≈ $7/mo removes sleep |
| Render (cron) | **Not free** | — | No free tier for cron jobs at all | Each cron service is billed; use the Actions workflow instead to stay at zero |
| Supabase | Free | 500MB database, 2 projects | **Pauses after 7 days of inactivity**; no automatic backups | Staging pausing over a quiet week is fine; production is not |
| Upstash | Free | **500K commands/mo**, 256MB, 10GB bandwidth | Rate limiting and pub/sub both spend commands | ≈16K/day. With `RATE_LIMIT_FAIL_OPEN=false`, **exhausting the quota makes login fail closed** — watch this one |
| Cloudflare R2 | Free | 10GB storage, 1M Class A, 10M Class B ops/mo, **zero egress** | Class A covers PUT/POST/LIST | 24-hour retention keeps stored bytes low; egress being free is why video playback costs nothing |
| Resend | Free | 3,000 emails/mo, 100/day | Custom from-address needs a verified domain | Password reset only — nowhere near the cap |

**Realistic beta cost: $0/month**, using the GitHub Actions scheduler and accepting that
staging sleeps. The first thing worth paying for is Render Starter (~$7/mo) to stop the
cold starts, which also makes the in-process scheduler viable and removes the Actions
minutes problem.

Two of these will bite before anything else does: Upstash's 500K commands with rate
limiting failing closed, and GitHub Actions minutes on a private repo if you run the
15-minute sweep from CI.

## 9a. What has been verified against real services

As of commit `86732cb` + this one, run from a laptop rather than from Render:

| Checked | Result |
|---|---|
| Supabase session pooler, TLS | Connected — PostgreSQL 17.6, IPv4, prepared statements fine |
| Full Alembic history on an empty database | 7 revisions applied, `alembic check` clean |
| Schema | 20 tables, 30 FKs, 55 indexes, 13 unique constraints, 0 naive timestamps |
| `uq_battle_live_pair` partial index | Present with the uppercase enum predicate (the Phase 7 fix) |
| Upstash over `rediss://` | Connected, PING and pub/sub both working |
| Production image, `APP_ENV=staging`, against both | `/health` 200, all 13 smoke checks pass |
| Redis unreachable | `/health` 503 and login 429 — fails closed, as configured |

Not yet verified against a real service: Cloudflare R2, Render, Resend, and anything over
a public HTTPS hostname (the WebSocket check above ran over plain HTTP to a local
container, so it proves the handshake and pub/sub, not TLS termination).

## 10. First deploy

```bash
# 1. Everything in §2 and §3 exists.
# 2. Migrate the empty Supabase database from your machine, once, to see it work:
cd backend
DATABASE_URL='postgresql://...pooler.supabase.com:5432/postgres?sslmode=require' \
  alembic upgrade head
DATABASE_URL='...' alembic check          # expect: No new upgrade operations detected.

# 3. Push to main. CI runs, the image is built, staging deploys, smoke tests run.

# 4. Verify from outside:
curl https://staging-api.<your-domain>/health
```

Then set `API_BASE_URL` in `frontend/FITWAR/App/Config/Staging.xcconfig` to
`https://staging-api.<your-domain>` and build the Staging scheme. `AppConfig` refuses to
launch a non-Debug build still pointing at a `.example` host, at localhost, or at plain
http — so a TestFlight build made from the placeholder crashes on launch instead of
quietly talking to nothing.

## 11. Rollback

```bash
# Application only. The schema stays where it is; the migrations are additive, so the
# previous image runs against it unchanged.
curl -X POST "https://api.render.com/v1/services/$SERVICE_ID/rollback" \
     -H "Authorization: Bearer $RENDER_API_KEY"
```

Or re-run `deploy-production.yml` with the previous known-good digest. Schema rollback is
a human decision — see §6.
