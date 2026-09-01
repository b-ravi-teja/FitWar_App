# ADR 0007 — Password Reset via Redis-Backed Single-Use Tokens

## Status
Accepted

## Context
Adding a real Login screen (per the V1 design decisions) required a real "forgot password" flow rather than a dead link, which Phase 0 had not designed. A reset mechanism needs a token that's issued, single-use, and short-lived — similar in spirit to `RefreshToken` but with a different lifecycle (minutes, not weeks; always single-use; no rotation/family concept needed).

## Decision
Password reset tokens are **not** a new Postgres table. `POST /auth/password-reset/request` generates a random opaque token, stores its hash in **Redis** with a short TTL (e.g. 30 minutes), and deletes it on first successful use (or expiry). `POST /auth/password-reset/confirm` validates against Redis, sets the new `password_hash`, and revokes every existing refresh-token family for that user (a reset is a full re-authentication event).

Delivery is behind an `EmailSender` protocol (same abstraction pattern as `ObjectStorage`/`VerificationProvider`) — the concrete transactional-email provider (SES, Postmark, etc.) is a deployment-time configuration choice, not a Phase 1–7 implementation blocker. Local/dev logs the token instead of sending real email.

## Consequences
- No new Postgres table, no new migration, no new retention/cleanup job — Redis TTL handles expiry for free, consistent with Phase 0's existing use of Redis for exactly this kind of ephemeral, short-lived data.
- The `EmailSender` abstraction means Phase 1–2 can implement and test the full reset flow (with a logging/no-op sender) before a real email provider is chosen — the provider decision doesn't gate auth work.
