# ADR 0005 — Manual Proof Review Workflow and Deadline-Driven Resolution

## Status
Accepted

## Context
The design shows a manual video-proof submission flow ending in "PENDING GROUP REVIEW," but no reviewer UI or resolution logic. The product decision specified an explicit creator/admin approve/reject step, but left one structural question unresolved: since review is asynchronous and human-paced, and Phase 0 §11 requires challenge-day deadlines to be deterministic and never blocked on external input, what happens when review hasn't completed by the time the challenge-day deadline passes — and what does a rejection actually do to the day's failure-rule outcome?

## Decision

1. Submission → `MediaAsset` (private) → `VerificationRecord.status = PENDING_REVIEW`, `DailyChallengeProgress.status` stays `pending`.
2. The challenge's creator or a group admin (`challenge_reviewer` authorization) reviews via a minimal queue UI and calls `APPROVE` or `REJECT`.
3. **APPROVE** → `VerificationRecord.status = VERIFIED` → `DailyChallengeProgress.status = completed` → the standard XP/streak/score transaction runs.
4. **REJECT** → `VerificationRecord.status = REJECTED` → no further pipeline runs for that record.

**Deadline-driven resolution:** a deadline-sweep resolves any day with no `VERIFIED` record at the moment the challenge-day deadline passes as `missed`, regardless of whether a submission is still `PENDING_REVIEW` — the warning/elimination pipeline fires from that state, on schedule, never blocked on a human reviewer.

- A rejection therefore only has a visible effect if it happens **before** the deadline (frees the participant to resubmit); after the deadline it's a no-op for failure-rule purposes.
- A late approval (after the deadline, after `missed`/warning already fired) still credits XP/streak/history for record-keeping, but **never retroactively reverses** an already-issued `Warning` or `Elimination`.

Camera-AI automated review remains explicitly future-only and out of scope.

## Consequences
- `VerificationRecord` gains three columns (`reviewed_by_user_id`, `reviewed_at`, `review_note`) — no new table.
- Review decisions are written to `AuditLog`.
- Product tradeoff worth monitoring post-launch: slow reviewers mean more proofs resolve as "missed" at the deadline even when eventually approved. Not a V1 blocker, but a UX/ops risk to watch (tracked in `docs/ARCHITECTURE.md` §18 risks table).
- Failure-rule timing stays deterministic under all conditions, preserving Phase 0 §11's non-negotiable.
