# FITWAR API Specification

Validated against `docs/FITWAR_DESIGN_SPEC.md`. Builds on the Phase 0 architecture (`docs/ARCHITECTURE.md` §5–7) — every endpoint below is justified by an actual screen/interaction in the design, not added speculatively. Versioned under `/api/v1`. Full machine-readable contract is FastAPI-generated OpenAPI (`/openapi.json`, `/docs`); this document is the human-readable companion.

**Conventions**
- Auth: `Bearer <access_jwt>` unless marked `Public`.
- Errors: Problem-Details envelope — `{ "type", "title", "status", "detail", "code" }` (Phase 0 §12). Only endpoint-specific error `code`s are listed per route; `VALIDATION_ERROR` (422) and `UNAUTHENTICATED` (401) apply universally and aren't repeated per row.
- Rate limiting: throttled endpoints (marked 🔒 below) return `429 RATE_LIMITED` in the same envelope with one extra field, `retry_after_seconds`, and a matching standard `Retry-After` header. It is the only response that carries that field. Clients should honour it rather than retrying immediately; the iOS client surfaces it as "try again in N seconds". Limits, key strategy, and the Redis-failure policy are in Architecture §7.
- Pagination: cursor-based, `?cursor=&limit=` on all list endpoints, response wraps `{ "items": [...], "next_cursor": "..." }`.
- IDs: UUIDs everywhere.

---

## Auth

**Status: all rows below are implemented** (Phase 1 built register/login/refresh/logout; Phase 2 added password-reset).

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `POST /auth/register` 🔒 | Public | `{ email, password, display_name }` | `201 { user_id, access_token, refresh_token, expires_in }` | `409 EMAIL_TAKEN` |
| `POST /auth/login` 🔒 | Public | `{ email, password }` | `200 { access_token, refresh_token, expires_in }` | `401 INVALID_CREDENTIALS`, `403 ACCOUNT_DELETED` |
| `POST /auth/refresh` 🔒 | Public (refresh token in body) | `{ refresh_token }` | `200 { access_token, refresh_token, expires_in }` (rotated) | `401 REFRESH_INVALID`, `401 REFRESH_REUSE_DETECTED` (revokes token family) |
| `POST /auth/logout` | Public (refresh token in body) | `{ refresh_token }` | `204`, revokes just the presented token (not its family — family revocation is reserved for reuse detection). Idempotent: an unknown or already-revoked token still returns `204`, so it never signals whether a token was valid | — |
| `POST /auth/password-reset/request` 🔒 | Public | `{ email }` | `202` always (never reveals whether the email exists) — issues a single-use opaque token, hashed and stored in Redis with TTL, delivered via `EmailSender` abstraction (`LoggingEmailSender` in dev — no real provider configured yet) | — |
| `POST /auth/password-reset/confirm` | Public | `{ token, new_password }` | `200`, revokes all existing refresh tokens for the user | `400 RESET_TOKEN_INVALID_OR_EXPIRED` |

🔒 = rate limited. Login: 20/5 min per IP **and** 10/15 min per submitted email. Register: 10/hour per IP. Refresh: 120/5 min per IP. Password-reset request: 10/hour per IP and 5/hour per submitted email. The per-email buckets count whatever address was submitted, real or not, and return an identical body either way — so a 429 never reveals whether an account exists (Architecture §7).

Sign in with Apple: architecture-compatible (`auth_provider` column) but **not implemented in V1** — no `/auth/oauth/apple` endpoint yet. Design spec §20.8: the iOS Login screen ships without an Apple button until this exists.

Design note: onboarding's "I already have an account" now routes to the real Login screen added per the design-review decisions (design spec §18, item 8; Architecture §20.8) — the endpoint contract above was already correct and needed no change.

## Me / Profile

**Status:** `GET /me` and `PATCH /me` are implemented (Phase 2, added because Onboarding's profile step and the Profile screen needed somewhere real to read/write). Their shape is **trimmed from the original Phase 0 sketch** — everything else below is still just designed, not built, pending the phases that back it.

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /me` ✅ | Required | — | `{ id, email, display_name, avatar_media_id, xp_total, notification_preferences }` — **no `level`/`xp_to_next_level`/`current_streak`**: those need the XP/Streak/Challenge domains, which don't exist yet. Not silently dropped — deliberately deferred | — |
| `PATCH /me` ✅ | Required | `{ display_name?, notification_preferences? }` — **no `avatar_media_id`**: `MediaAsset` doesn't exist until the Media phase, so there's nothing to set it to yet | `200` updated profile — backs Onboarding's profile step and Settings' future Account/Notification sections (design spec §20.9) | `422` |
| `DELETE /me` | Required | — | `204` (soft-delete, see Phase 0 §7) — **not yet implemented**, no screen needs it before the Settings phase | — |
| `GET /me/xp` ✅ | Required | — | `{ xp_total, level, xp_into_level, xp_to_next_level, transactions: [{ id, amount, reason, created_at }] }` (most recent 50). **Level is server-computed** (ADR 0008) — the client renders it and never derives it. The ledger is the source of truth and `xp_total` its transactionally-synced projection (§3.2). Entries are strictly positive: a missed day never debits XP (ADR 0002). **Not cursor-paginated** — a capped recent list is what the XP screen shows, and a cursor would be unused surface | — |
| `GET /me/achievements` | Required | — | list of unlocked achievements | — (not yet implemented — Achievements/XP phase) |
| `GET /me/challenge-history` | Required | `?cursor=` | list of `{ challenge_id, name, ended_at, outcome }` | — (not yet implemented — Challenges phase) |
| `GET /me/health-connections` ✅ **[added]** | Required | — | `{ id, provider, status, last_synced_at, connected_at }[]` — the caller's links only. `last_synced_at` is the server's own observation of evidence arriving, never a client claim about permissions | — |
| `POST /me/health-connections` ✅ | Required | `{ provider }` (`apple_health` \| `health_connect`) | `201` connection. Idempotent — re-connecting an existing link revives it rather than failing, which is what the client needs when a user re-grants permission in iOS Settings | `422` |
| `DELETE /me/health-connections/{id}` ✅ | Required, owner | — | `204`, marks the link revoked | `404 HEALTH_CONNECTION_NOT_FOUND` — the same 404 another account's id produces, so this can't probe for valid ids |

## Groups

**Status: all rows below are implemented** (Phase 3).

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /groups` ✅ | Required | — | groups the caller belongs to: `{ id, name, timezone, member_count, active_challenge_count }[]` | — |
| `POST /groups` ✅ | Required | `{ name, timezone }` | `201` group, caller becomes owner. `timezone` must be an IANA identifier | `400 INVALID_TIMEZONE`, `422` |
| `GET /groups/{id}` ✅ | Required, member | — | group detail, incl. `join_code` and the caller's `my_role` | `403 NOT_A_MEMBER`, `404 GROUP_NOT_FOUND` |
| `PATCH /groups/{id}` ✅ | Required, admin | `{ name?, timezone? }` | `200` updated. Editing `timezone` never affects challenges already created — each snapshotted its own copy (Architecture §11) | `403 FORBIDDEN`, `400 INVALID_TIMEZONE` |
| `POST /groups/join` ✅ **[added]** | Required | `{ join_code }` | `200` membership created, resolved from the code alone | `404 INVALID_CODE`, `409 ALREADY_MEMBER`, `403 MEMBER_REMOVED` |
| `POST /groups/{id}/join` ✅ | Required | `{ join_code }` | `200` membership created; the code must belong to `{id}`, so a valid code for another group can't open this one | `404 INVALID_CODE`, `409 ALREADY_MEMBER`, `403 MEMBER_REMOVED` |
| `POST /groups/{id}/leave` ✅ | Required, member | — | `204` | `409 OWNER_CANNOT_LEAVE` |
| `GET /groups/{id}/members` ✅ | Required, member | — | roster: `{ user_id, display_name, role, status, joined_at, active_challenge_count }[]` — **no `current_streak`/`warning_count`/`is_eliminated_in_active_challenge`**: those need the Streak and Warning domains (Phases 5–6), and zeros would render as real standings | `403 NOT_A_MEMBER` |
| `PATCH /groups/{id}/members/{user_id}` ✅ | Required, admin | `{ role?, status? }` | `200` | `403 FORBIDDEN`, `403 CANNOT_MODIFY_OWNER` |

**Invite mechanism.** No standalone invite table: `Group.join_code` is a unique 5-character
code (design shape `K7-XR9`), generated at creation and shown on the Group screen to
admins. `POST /groups/{id}/join` is the spec'd route and backs invite *links*, which carry
the group id. `POST /groups/join` was added because the design's JOIN CODE card supports
typing a code with no group id in hand; both delegate to one service method.

**Rejoin policy** (not specified in Phase 0, decided here): a member whose status is
`left` may rejoin with a valid code, reactivating their membership. A member whose status
is `removed` may **not** — removal is an admin moderation decision, and an invite code
must not route around it; an admin reinstates them via `PATCH .../members/{user_id}`.

**`409 GROUP_FULL` is not implemented** — the frozen `Group` schema has no member-cap
column and no ADR sets one, so there is no state in which V1 can return it.

## Chat / Group Feed

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /groups/{id}/messages` ✅ | Required, member | `?before=&before_id=&limit=` (max 50) | `{ items: [{ id, group_id, sender_id, sender_display_name, content, message_type, created_at, reactions: [{ emoji, count, reacted_by_me }] }], next_cursor, next_cursor_id }`, newest first. The cursor is a **pair** — timestamps tie, so `before_id` is required to page past them | `403 NOT_A_MEMBER` |
| `POST /groups/{id}/messages` ✅ | Required, member | `{ content }` (1–1000) | `201` message. Persisted to Postgres **first**, then published to Redis — a Redis outage costs live delivery, never the message | `403 NOT_A_MEMBER` (including a member who has left) |
| `POST /groups/{id}/messages/{message_id}/reactions` ✅ **[added]** | Required, member | `{ emoji, add }` | `204`. Idempotent both ways: a repeated add is a no-op (`UNIQUE(message,user,emoji)`), removing an absent reaction is nothing to delete. Emoji is a fixed allow-list | `400 REACTION_NOT_ALLOWED`, `404 MESSAGE_NOT_FOUND` (also for a message in another group) |
| `GET /groups/{id}/activity` ✅ | Required, member | — | `{ kind, actor_display_name, text, occurred_at }[]` (backs Group→Feed tab). Phase 3 derives this from records it already writes — `member_joined` and `challenge_created` — with **no activity table**. Shared-proof posts need the Media phase and are absent rather than mocked. Not yet paginated: the response is capped at 20 entries, which is below the point where a cursor earns its complexity | `403 NOT_A_MEMBER` |
| `WS /api/v1/ws/groups/{id}?token=` ✅ | Required, member | — | pushes `chat_message`, `system_message`, `reaction_changed`, and game events. **Authorization is per-resource**: a valid JWT is not enough — membership is checked before accept. Unauthenticated, non-member and unknown-group all close with the same code `4403`, so nothing leaks about whether a private group exists. Token is a query param because a WS handshake carries no custom headers. Delivery is **not exactly-once** — clients re-read over REST | closes `4403`; `1013` if Redis is unavailable (REST still serves everything) |

## Challenges

**Status: all rows below are implemented** (Phase 3).

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /challenges` ✅ | Required | `?status=&group_id=` — no `scope` parameter: `mine` is the only scope V1 has, so it isn't accepted-and-ignored (ADR 0001) | `{ id, group_id, name, activity_type, game_mode, status, target_value, unit, day_index, duration_days, participant_count, my_status }[]`. **No `progress_pct`/`rank_label`**: both need verified daily values and leaderboard rank, which don't exist until Phases 4–5 | — |
| `POST /groups/{id}/challenges` ✅ | Required, member | `{ name, activity_type, target_value, unit, game_mode, verification_method, duration_days, participant_limit?, start_at? }` | `201` challenge (`timezone` snapshotted from the group per Phase 0 §11; creator auto-joins as a participant). **No `status` in the request** — the server derives DRAFT vs ACTIVE from `start_at` against the clock | `403 NOT_A_MEMBER`, `409 INVALID_CHALLENGE_CONFIG`, `422` |
| `GET /groups/{id}/challenges` ✅ | Required, member | — | every challenge in the group, same summary shape as `GET /challenges` (incl. the caller's `my_status`). Backs the Group Detail screen's challenge list, where the scope is the group rather than the caller's own participation — so unlike `GET /challenges`, it lists challenges the caller hasn't joined | `403 NOT_A_MEMBER` |
| `GET /challenges/{id}` ✅ | Required, participant-or-group-member | — | full detail incl. `failure_rule`, `day_index`, `my_status`, and the participant list. **No leaderboard preview** — every score is 0 until verification exists, so ranking them would present an order that means nothing | `403 NOT_A_PARTICIPANT`, `404 CHALLENGE_NOT_FOUND` |
| `PATCH /challenges/{id}` ✅ | Required, creator/group-admin, pre-start only | `{ name?, target_value? }` — no `rules`, since V1 writes no `ChallengeRule` rows (ADR 0004) | `200` | `409 CHALLENGE_ALREADY_ACTIVE`, `403` |
| `POST /challenges/{id}/cancel` ✅ **[added]** | Required, creator/group-admin | — | `200`, DRAFT → CANCELLED. The only route to CANCELLED, and the only way the mandated `DRAFT → CANCELLED` edge is reachable. An ACTIVE challenge is never cancellable — participants already hold real daily progress | `409 INVALID_STATE_TRANSITION`, `403` |
| `POST /challenges/{id}/join` ✅ | Required, group member | — | `201` full challenge detail | `403 NOT_A_MEMBER`, `409 ALREADY_JOINED`, `409 PARTICIPANT_LIMIT_REACHED`, `409 CANNOT_REJOIN`, `409 CHALLENGE_ALREADY_ENDED` |
| `POST /challenges/{id}/leave` ✅ | Required, participant | — | `204`, sets `outcome = left` | `409 CHALLENGE_ALREADY_ENDED`, `403 NOT_A_PARTICIPANT` |
| `GET /challenges/{id}/participants` ✅ | Required, participant-or-group-member | — | `{ user_id, display_name, status, outcome, current_score, current_streak, rank, joined_at }[]`. `rank` is assigned at read time from score ordering and never persisted (Architecture §3.2) | `403` |

**Challenge status is never client-supplied.** `DRAFT → ACTIVE` and `ACTIVE → COMPLETED`
are applied server-side on every read/write path by comparing the clock to the
challenge's own frozen timezone — no background scheduler is needed at V1 scale, and no
request can name a target status. Every transition is checked against the domain state
machine, so an illegal one is a `409 INVALID_STATE_TRANSITION`, never a silent write.

**Rejoin policy** (not specified in Phase 0, decided here): participant statuses are
terminal (Architecture §3.3), so `left`, `completed`, and `eliminated` participants cannot
re-enter the same challenge — reviving one would make elimination meaningless in
SURVIVAL. Joining a *different* challenge is always available.

**Resolved:** design spec §18 unknown #1 is decided — no public/discoverable challenges in V1 (ADR 0001). The Challenges screen's DISCOVER tab is dropped from the delivered app (ACTIVE/COMPLETED tabs only); `Group.privacy` stays in the schema, dormant, so a future `GET /groups?visibility=public` + join flow can add discovery without a migration.

## Verification / Daily Progress

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /challenges/{id}/progress/today` ✅ | Required, participant | — | `{ challenge_day, day_index, status, target, unit, window_start_at, deadline_at, completed_at }`. `challenge_day` is resolved server-side from the challenge's frozen timezone, never from the client. Creates the row PENDING on first look — idempotent via `UNIQUE(participant, challenge_day)`. **No `current_value`/`remaining`/`last_synced_at`**: verification is Phase 4, and a `0` would render as "you've done nothing today", which is not what PENDING means | `403 NOT_A_PARTICIPANT`, `409 CHALLENGE_NOT_ACTIVE` |
| `GET /challenges/{id}/progress/{date}` ✅ | Required, participant | — | historical single-day record, read-only — unlike `/today` this never creates a row, since back-filling a day nobody looked at would invent history | `404 DAY_OUT_OF_RANGE`, `403` |
| `POST /challenges/{id}/verify` ✅ | Required, participant | `{ provider, evidence }` — `provider` is `apple_health` or `manual_proof`. Normalized evidence, never raw HealthKit objects (manual proof adds `media_id`, referencing a completed upload the caller owns): `{ metric, value (decimal string), unit, period_start, period_end, source_name?, source_bundle_id?, was_user_entered }`. Instants must carry a UTC offset and fall inside the window the server published for today (Architecture §21.2) | `200 { verification, challenge_day, day_status, deadline_at, idempotent_replay, resolution }` — `resolution` is `{ xp_awarded, completion_xp, streak_bonus_xp, score_delta, current_streak }` when the submission completed the day, and **null** on a replay or short attempt (zeros would render as a real award of 0 XP). It backs Mission Complete's XP breakdown. `day_status` is authoritative — the client never computes completion. Phase 5 added `resolution`; `new_rank` is still absent — the client reads rank from the leaderboard rather than having it duplicated here | `400 INVALID_EVIDENCE` (wrong metric/unit/day), `409 VERIFICATION_METHOD_MISMATCH`, `409 CHALLENGE_NOT_ACTIVE`, `403 NOT_A_PARTICIPANT`. An exact retry after completion is **not** an error — it returns the original record with `idempotent_replay: true` |
| `GET /challenges/{id}/warnings` | Required, self or admin | — | `{ reason, challenge_day, created_at }[]` | — |

## Verification Review (manual proof — Architecture §20.5)

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /challenges/{id}/proofs/pending` ✅ | Required, `challenge_reviewer` (creator or group admin) | — | `{ verification_record_id, participant_user_id, participant_display_name, challenge_day, claimed_value, target, submitted_at, media_id, media_available }[]`. The only route exposing another participant's proof — proof is private by default | `403 NOT_A_REVIEWER` |
| `GET /challenges/{id}/proofs/{record_id}/media` ✅ **[added]** | Required, `challenge_reviewer` | — | the proof's media with a short-lived signed `playback_url`. Authorized **by challenge, not by ownership** — this is the one path by which someone other than the owner may view a private proof, scoped to reviewers of the challenge it belongs to. `playback_url` is null once retention deleted the object | `403 NOT_A_REVIEWER`, `404 PROOF_NOT_FOUND` |
| `POST /challenges/{id}/proofs/{record_id}/review` ✅ **[moved]** | Required, `challenge_reviewer` | `{ approve, note? }` | `200 { verification_record_id, status, reviewed_at, already_resolved, xp_awarded, current_streak }`. Approval runs the **existing Phase 5 pipeline** — no separate XP/score/streak path. Nested under the challenge so reviewer authorization is scoped by the same dependency everything else uses | `403 CANNOT_REVIEW_OWN_PROOF` (even for the creator), `403 NOT_A_REVIEWER`, `404 PROOF_NOT_FOUND` (also for a proof in another challenge), `409 CHALLENGE_NOT_ACTIVE` (finalized — standings are immutable). A duplicate decision is **not** an error: it returns the existing one with `already_resolved: true` |

## Leaderboards

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /challenges/{id}/leaderboard` ✅ | Required, participant-or-group-member | — | `{ challenge_id, game_mode, is_final, entries: [{ rank, user_id, display_name, score, current_streak, status, outcome, is_me }] }`. `rank` is assigned at read time from the frozen §20.3 tie-break and never persisted; the read sweeps overdue days first, so standings can't show someone as still in it after their deadline passed. Eliminated/departed participants appear with their status rather than being hidden. `is_final` means the challenge closed and these standings are immutable. **No `delta`/`gap_to_leader`** — both need rank history the system doesn't keep | `403 NOT_A_MEMBER` |
| `GET /challenges/{id}/me` ✅ **[added]** | Required, participant | — | the caller's own competitive state: `{ rank, score, current_streak, longest_streak, consecutive_misses, status, outcome, warnings: [{ challenge_day, reason, created_at }], eliminated_at }`. Scoped to the caller — warnings and miss counts are not exposed for other participants through any route | `403 NOT_A_PARTICIPANT` |

## Media

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `POST /media/upload-url` ✅ | Required | `{ content_type }` (`video/mp4` \| `video/quicktime`) | `201 { media_id, url, fields, expires_in_seconds, max_bytes }` — a **presigned POST policy**, not a bucket credential. The storage key is server-generated and owner-namespaced, so a client can neither choose a key nor overwrite another user's object; the policy pins content type and max size, so storage itself rejects an oversized or mistyped upload | `400 UNSUPPORTED_MEDIA_TYPE` |
| `POST /media/{id}/complete` ✅ | Required, owner | — | `200` asset. The server reads size and content type back **from the object**, never from the request. Idempotent — repeating returns the same asset | `409 UPLOAD_NOT_FOUND_IN_STORAGE`, `404 MEDIA_NOT_FOUND` |
| `POST /media/{id}/share` | Required, owner | `{ visibility }` | `200` updated media — **not implemented in V1**. Proof is private by default; explicit sharing is a later phase | — |
| `GET /media/{id}` ✅ | Required, **owner only** | — | `{ id, status, content_type, size_bytes, playback_url, expires_at, object_deleted_at }`. `playback_url` is a short-lived signed GET, and **null once retention deleted the object** (`status: expired`) so the UI shows "no longer available" rather than a broken player. Another user's media id returns the same 404 a missing one does | `404 MEDIA_NOT_FOUND` |

## Battles

**Status: all rows below are implemented** (Phase 7).

A battle is private to its **two players** — not to its squad. Every `/battles/{id}` route
answers `404 BATTLE_NOT_FOUND` for a non-participant, byte-identical to a made-up id, so
none of them confirms that a private battle exists. There is no viewer tier.

Underneath, each battle owns a `Challenge` with `game_mode = 1v1` that carries the rules,
the days and the scoring (Architecture §24.1). That challenge is **not reachable through
the challenge API** — `GET/PATCH/POST /challenges/{id}/*` all answer `CHALLENGE_NOT_FOUND`
for it, and it never appears in `GET /challenges` or `GET /groups/{id}/challenges`. This
is a security boundary: `POST /challenges/{id}/join` would otherwise add a third player to
a 1v1 (§24.2).

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /battles` ✅ | Required | `?status=pending\|active\|completed\|cancelled` (omit for all) | the caller's battles, newest first — see the shape below. `scope=mine` is not a parameter because it is the only scope: a battle you are not in is never selected, not filtered out | — |
| `GET /battles/rivals` ✅ | Required, group member | `?group_id=` (required) | `{ user_id, display_name, wins_against, losses_against, live_battle_id }[]` — squad-mates the caller can challenge, with the head-to-head record counted from finalized battles. `live_battle_id` is set when a battle with that rival is already pending or active, so the UI offers "VIEW" instead of a "CHALLENGE" the server would refuse | `403 NOT_A_MEMBER` |
| `POST /battles` ✅ | Required | `{ opponent_user_id, activity_type, target_value?, duration_days, group_id? }` | `201` battle, `status=pending`. `target_value` omitted → the activity's default (ADR 0009). `group_id` omitted → inferred when exactly one squad is shared | `409 ALREADY_PENDING_WITH_USER`, `409 GROUP_REQUIRED`, `409 INVALID_BATTLE_CONFIG`, `403 OPPONENT_NOT_AVAILABLE` |
| `GET /battles/{id}` ✅ | Required, participant | — | battle detail (shape below). Sweeps first, so a battle whose window closed never reads as still live | `404 BATTLE_NOT_FOUND` |
| `POST /battles/{id}/accept` ✅ | Required, invited participant | — | `200`, `status=active`; the battle's window starts now. **Idempotent** — accepting again returns the same battle with the same `start_at` | `409 NOT_INVITED`, `409 BATTLE_NOT_PENDING`, `404 BATTLE_NOT_FOUND` |
| `POST /battles/{id}/decline` ✅ | Required, invited participant | — | `200`, `status=cancelled`. **Idempotent.** No outcome is written on either side — a refused invitation started nothing, so it is not a forfeit (§24.3) | `409 NOT_INVITED`, `409 BATTLE_NOT_PENDING` |
| `POST /battles/{id}/verify` ✅ | Required, participant | `{ provider, evidence }` — the **same body** as challenge verify | `{ verification: <challenge-verify response>, battle: <battle detail> }`. The side the evidence lands on comes from the token, never the body. Finalizes the battle if this settled the last open day, and the returned `battle` is then the final one | `409 BATTLE_NOT_ACTIVE`, `400 INVALID_EVIDENCE`, `404 BATTLE_NOT_FOUND` |
| `WS /ws/battles/{id}` ✅ | Required, **participant** | `?token=` | pushes `battle_status_changed`, `battle_progress`, `battle_completed`. A squad-mate who is not playing is refused with close code `4403`, identically to an unknown battle | — |

**Battle shape** (returned by every row above):

```
{ id, group_id, status, activity_type, target_value, unit,
  day_index, duration_days, timezone, start_at, end_at, completed_at,
  time_remaining_seconds,
  sides: [{ user_id, display_name, status, score, days_completed, is_me }],
  winner_user_id, my_outcome, my_xp_awarded }
```

- `time_remaining_seconds` is server-computed. The battle day belongs to the battle's
  frozen timezone, so two devices with different clocks must not disagree about it.
- `sides` carries the **contest** — name, score, banked days, status — and has no field
  for evidence, proof media, health records or verification metadata (§24.9).
- `winner_user_id` and `my_outcome` are `null` until the battle is finalized. There is no
  provisional winner: a mutable "current winner" is exactly what §20.3 forbids.
- `my_xp_awarded` is read back out of the XP ledger, not restated from a constant. `null`
  for the loser and while unfinished — a `0` would render as "you earned nothing", which
  is a different claim.

**Outcome** is the frozen §20.3 rule, unchanged and shared with POINTS-mode close and
leaderboard ordering: highest score → earliest to reach it → longer streak → earlier join
→ lower `user_id`. A battle never draws.

**Finalization** is due when the window closes *or* every day is resolved for both
players, and runs once in one locked transaction (§24.6). Afterwards the result is
immutable: winner, loser, scores and the XP award cannot change, and **late evidence is
refused with `409 BATTLE_NOT_ACTIVE`** rather than silently ignored.

**Verification method:** V1 battles verify from Apple Health only, so `activity_type` must
be one Health can measure (`steps`, `active_calories`, `distance`). `pushups` returns
`409 INVALID_BATTLE_CONFIG` — video proof needs a reviewer who is not competing, and a
two-player contest has none (ADR 0009).

## Error Contract — verified behaviour

Every error response uses the Problem Details envelope
(`{ type, title, status, detail, code }`), including validation failures. This was
exercised directly in Phase 8 against malformed input on every public surface: invalid
UUIDs, oversized and negative numbers, unknown enum values, naive timestamps, inverted
periods, malformed JSON, 3 MB bodies, and 400-level-deep nesting. Two paths returned 500
and are fixed (Architecture §25.6); the rest already answered 4xx.

- **No stack traces reach clients in production.** `APP_DEBUG=true` makes Starlette
  render a traceback *instead of* this envelope, so the boot guard in `core/config.py`
  refuses to start a production environment with it on (§25.5).
- **Extra request fields are ignored, never applied.** Posting `score`, `winner_user_id`,
  `xp_awarded` or `rank` alongside real evidence changes nothing — verified against the
  running server for both challenge and battle verification.
- **`429` carries `retry_after_seconds`** plus a standard `Retry-After` header, and is
  the only response with that field.

## Notifications

**Resolved (design spec §18 unknown #6, ADR 0006):** no dedicated notification-inbox screen in V1 iOS. The API is built regardless — push delivery depends on the persisted `Notification` row existing either way (Phase 0 §10), and `unread-count` backs the nav badge dot.

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /notifications` | Required | `?cursor=` | paginated `{ id, type, payload, read_at, created_at }` — no V1 screen consumes this yet; kept for the future inbox and for debugging/support | — |
| `GET /notifications/unread-count` | Required | — | `{ count }` — cheap, backs the unread badge without paginating the full list | — |
| `POST /notifications/{id}/read` | Required, owner | — | `204` | `404` |

## Reports (abuse hook)

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `POST /reports` | Required | `{ target_type, target_id, reason }` | `201` | `422` |

## Operations

Not under `/api/v1` — an infrastructure probe, not part of the product contract, so it is unversioned and consumed by Docker/deployment health checks rather than the app.

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /health` ✅ | Public | — | `200 { status, database, redis }`, or the same body with `503` when either dependency is down. Deliberately coarse: it reports up/down per dependency and never leaks hostnames, versions, or connection detail | — |

---

## Endpoints intentionally NOT added

- No `/settings` endpoint — Settings (design spec §20.9) is deliberately backed entirely by existing endpoints (`PATCH /me`, `GET/DELETE /me/health-connections`, `DELETE /me`, `POST /auth/logout`); it doesn't need its own resource.
- No dedicated "defeat" response shape for battles — `battle_completed` push and the battle detail response carry win/loss symmetrically; the Defeat screen (§20.11) reads the same data Victory always did.
- No group-switcher/list-of-groups-with-active-context endpoint beyond plain `GET /groups` — resolved (§20.7): the Groups List screen is a direct, unmodified consumer of the endpoint that already existed.
- No public-challenge-discovery endpoint — resolved (§20.1): not built in V1, schema stays extensible.
