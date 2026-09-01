# FITWAR API Specification

Validated against `docs/FITWAR_DESIGN_SPEC.md`. Builds on the Phase 0 architecture (`docs/ARCHITECTURE.md` §5–7) — every endpoint below is justified by an actual screen/interaction in the design, not added speculatively. Versioned under `/api/v1`. Full machine-readable contract is FastAPI-generated OpenAPI (`/openapi.json`, `/docs`); this document is the human-readable companion.

**Conventions**
- Auth: `Bearer <access_jwt>` unless marked `Public`.
- Errors: Problem-Details envelope — `{ "type", "title", "status", "detail", "code" }` (Phase 0 §12). Only endpoint-specific error `code`s are listed per route; `VALIDATION_ERROR` (422) and `UNAUTHENTICATED` (401) apply universally and aren't repeated per row.
- Pagination: cursor-based, `?cursor=&limit=` on all list endpoints, response wraps `{ "items": [...], "next_cursor": "..." }`.
- IDs: UUIDs everywhere.

---

## Auth

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `POST /auth/register` | Public | `{ email, password, display_name }` | `201 { user_id, access_token, refresh_token, expires_in }` | `409 EMAIL_TAKEN` |
| `POST /auth/login` | Public | `{ email, password }` | `200 { access_token, refresh_token, expires_in }` | `401 INVALID_CREDENTIALS`, `403 ACCOUNT_DELETED` |
| `POST /auth/refresh` | Public (refresh token in body) | `{ refresh_token }` | `200 { access_token, refresh_token, expires_in }` (rotated) | `401 REFRESH_INVALID`, `401 REFRESH_REUSE_DETECTED` (revokes token family) |
| `POST /auth/logout` | Required | `{ refresh_token }` | `204` | — |
| `POST /auth/password-reset/request` | Public | `{ email }` | `202` always (never reveals whether the email exists) — issues a single-use opaque token, hashed and stored in Redis with TTL, delivered via `EmailSender` abstraction | — |
| `POST /auth/password-reset/confirm` | Public | `{ token, new_password }` | `200`, revokes all existing refresh-token families for the user | `400 RESET_TOKEN_INVALID_OR_EXPIRED` |

Sign in with Apple: architecture-compatible (`auth_provider` column) but **not implemented in V1** — no `/auth/oauth/apple` endpoint yet. Design spec §20.8: the iOS Login screen ships without an Apple button until this exists.

Design note: onboarding's "I already have an account" now routes to the real Login screen added per the design-review decisions (design spec §18, item 8; Architecture §20.8) — the endpoint contract above was already correct and needed no change.

## Me / Profile

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /me` | Required | — | `{ id, email, display_name, avatar_media_id, level, xp_total, xp_to_next_level, current_streak, notification_preferences }` | — |
| `PATCH /me` | Required | `{ display_name?, avatar_media_id?, notification_preferences? }` | `200` updated profile — backs both Account and Notification-preferences sections of Settings (design spec §20.9) | `422` |
| `DELETE /me` | Required | — | `204` (soft-delete, see Phase 0 §7) | — |
| `GET /me/xp` | Required | `?cursor=` | paginated `XPTransaction` rows: `{ id, amount, reason_type, reference_type, reference_id, created_at }` | — |
| `GET /me/achievements` | Required | — | list of `{ achievement_key, name, unlocked_at }` | — |
| `GET /me/challenge-history` | Required | `?cursor=` | list of `{ challenge_id, name, ended_at, outcome }` — `outcome ∈ {WON, LOST, OUT, LEFT}`, computed per the fixed rule in Architecture §20.3 | — |
| `POST /me/health-connections` | Required | `{ provider }` (`apple_health` \| `health_connect`) | `201 { connection_id, status }` | `409 ALREADY_CONNECTED` |
| `DELETE /me/health-connections/{id}` | Required, owner | — | `204` | `404` |

## Groups

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /groups` | Required | — | groups the caller belongs to: `{ id, name, timezone, member_count, active_challenge_count }[]` | — |
| `POST /groups` | Required | `{ name, timezone }` | `201` group, caller becomes owner | `422` |
| `GET /groups/{id}` | Required, member | — | group detail | `403 NOT_A_MEMBER` |
| `PATCH /groups/{id}` | Required, admin | `{ name?, timezone? }` | `200` updated | `403 FORBIDDEN` |
| `POST /groups/{id}/join` | Required | `{ join_code }` | `200` membership created | `404 INVALID_CODE`, `409 ALREADY_MEMBER`, `409 GROUP_FULL` |
| `POST /groups/{id}/leave` | Required, member | — | `204` | `409 OWNER_CANNOT_LEAVE` |
| `GET /groups/{id}/members` | Required, member | — | roster: `{ user_id, display_name, role, status, current_streak, warning_count, is_eliminated_in_active_challenge }[]` (backs the Group→Roster tab) | — |
| `PATCH /groups/{id}/members/{user_id}` | Required, admin | `{ role? , status? }` | `200` | `403` |

## Chat / Group Feed

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /groups/{id}/messages` | Required, member | `?cursor=` | paginated `{ id, sender_id, content, message_type, media_id, created_at }` (backs Group→Chat tab) | — |
| `POST /groups/{id}/messages` | Required, member | `{ content }` | `201` message | `429 RATE_LIMITED` |
| `GET /groups/{id}/activity` | Required, member | `?cursor=` | paginated feed: shared-proof posts + passive activity log entries, merged/sorted by time (backs Group→Feed tab) | — |
| `WS /ws/groups/{id}` | Required, member (JWT on connect) | — | pushes: `chat_message`, `reaction_added`, `leaderboard_updated`, `warning_issued`, `eliminated` | connection rejected if not a member |

## Challenges

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /challenges` | Required | `?scope=mine&status=&group_id=` (no `discover` scope — no public challenge discovery in V1, ADR 0001) | list, same shape as Home/Challenges cards: `{ id, name, meta, status, status_color_hint, progress_label, rank_label, progress_pct }[]` | — |
| `POST /groups/{id}/challenges` | Required, member | `{ name, activity_type, target_value, unit, game_mode, verification_method, duration_days, participant_limit?, rules: {...} }` | `201` challenge (`timezone` snapshotted from group per Phase 0 §11) | `422`, `403` |
| `GET /challenges/{id}` | Required, participant-or-group-member | — | full detail incl. today's metric, countdown, verification method, leaderboard preview | `403` |
| `PATCH /challenges/{id}` | Required, creator/admin, pre-start only | `{ name?, target_value?, rules? }` | `200` | `409 CHALLENGE_ALREADY_ACTIVE` |
| `POST /challenges/{id}/join` | Required, group member | — | `201` participant created | `409 ALREADY_JOINED`, `409 PARTICIPANT_LIMIT_REACHED` |
| `POST /challenges/{id}/leave` | Required, participant | — | `204` | `409 CHALLENGE_ALREADY_ENDED` |
| `GET /challenges/{id}/participants` | Required, participant-or-admin | — | `{ user_id, status, current_score, current_streak }[]` | — |

**Resolved:** design spec §18 unknown #1 is decided — no public/discoverable challenges in V1 (ADR 0001). The Challenges screen's DISCOVER tab is dropped from the delivered app (ACTIVE/COMPLETED tabs only); `Group.privacy` stays in the schema, dormant, so a future `GET /groups?visibility=public` + join flow can add discovery without a migration.

## Verification / Daily Progress

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /challenges/{id}/progress/today` | Required, participant | — | `{ challenge_day, status, current_value, target, remaining, deadline_at, last_synced_at }` (backs Verify screen) | — |
| `GET /challenges/{id}/progress/{date}` | Required, participant | — | historical single-day record | `404` |
| `POST /challenges/{id}/verify` | Required, participant | `{ provider, evidence: {...} }` — shape depends on provider (health-query result vs. media reference) | `200 { status: completed\|pending_review\|rejected, xp_awarded?, new_streak?, new_rank? }` (backs Mission Complete) | `409 ALREADY_VERIFIED_TODAY` (idempotent — returns existing result, not an error, on exact retry), `409 CHALLENGE_NOT_ACTIVE` |
| `GET /challenges/{id}/warnings` | Required, self or admin | — | `{ reason, challenge_day, created_at }[]` | — |

## Verification Review (manual proof — Architecture §20.5)

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /challenges/{id}/proofs/pending` | Required, `challenge_reviewer` (creator or group admin) | `?cursor=` | paginated `{ verification_record_id, participant: { user_id, display_name }, challenge_day, media_id, submitted_at }[]` — backs the minimal review-queue screen (design spec §20.14) | `403 NOT_A_REVIEWER` |
| `POST /verification-records/{id}/review` | Required, `challenge_reviewer` | `{ decision: "APPROVE"\|"REJECT", note? }` | `200 { status: verified\|rejected }` — APPROVE resumes the standard XP/streak/score pipeline; REJECT ends it. Deadline-driven resolution (Architecture §20.5) means this call's effect on the daily-miss outcome depends on whether the challenge-day deadline has already passed. | `409 ALREADY_REVIEWED`, `403` |

## Leaderboards

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /challenges/{id}/leaderboard` | Required, participant-or-group-member | — | ranked list `{ rank, user_id, display_name, score, delta, sub_label }[]` + `gap_to_leader` (backs both the Detail preview and full Leaderboard screen) | — |

## Media

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `POST /media/upload-url` | Required | `{ content_type, context_type, context_id, size_bytes }` | `{ media_id, upload_url, expires_at }` (presigned PUT) | `422 UNSUPPORTED_TYPE`, `413 TOO_LARGE` |
| `POST /media/{id}/complete` | Required, owner | — | `200 { status: processed\|failed }` | `409 UPLOAD_NOT_FOUND_IN_STORAGE` |
| `POST /media/{id}/share` | Required, owner | `{ visibility: "group_shared" }` | `200` updated media (backs "SHARE WITH GROUP") | `403` |
| `GET /media/{id}` | Required, owner-or-group-member-if-shared | — | signed GET URL | `403 PRIVATE_MEDIA` |

## Battles

| Method & Path | Auth | Request | Response | Errors |
|---|---|---|---|---|
| `GET /battles` | Required | `?scope=mine` | live/pending battles: `{ id, status, opponent, my_score, their_score, day, duration_days, time_remaining }[]` | — |
| `GET /battles/rivals` | Required | `?group_id=` | challengeable users with head-to-head record: `{ user_id, display_name, wins_against, losses_against }[]` (backs "CHALLENGE SOMEONE" list — not in the original Phase 0 sketch, added because the design requires it) | — |
| `POST /battles` | Required | `{ opponent_user_id, activity_type, target_value?, duration_days }` | `201` battle, status=pending | `409 ALREADY_PENDING_WITH_USER` |
| `GET /battles/{id}` | Required, participant | — | detail | `403` |
| `POST /battles/{id}/accept` | Required, invited participant | — | `200`, status=active | `409 NOT_INVITED` |
| `POST /battles/{id}/decline` | Required, invited participant | — | `200`, status=cancelled | — |
| `POST /battles/{id}/verify` | Required, participant | `{ provider, evidence }` | same shape as challenge verify; on final day, resolves battle and returns victor | `409 BATTLE_NOT_ACTIVE` |
| `WS /ws/battles/{id}` | Required, participant | — | pushes `battle_status_changed`, `battle_completed` | — |

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

---

## Endpoints intentionally NOT added

- No `/settings` endpoint — Settings (design spec §20.9) is deliberately backed entirely by existing endpoints (`PATCH /me`, `GET/DELETE /me/health-connections`, `DELETE /me`, `POST /auth/logout`); it doesn't need its own resource.
- No dedicated "defeat" response shape for battles — `battle_completed` push and the battle detail response carry win/loss symmetrically; the Defeat screen (§20.11) reads the same data Victory always did.
- No group-switcher/list-of-groups-with-active-context endpoint beyond plain `GET /groups` — resolved (§20.7): the Groups List screen is a direct, unmodified consumer of the endpoint that already existed.
- No public-challenge-discovery endpoint — resolved (§20.1): not built in V1, schema stays extensible.
