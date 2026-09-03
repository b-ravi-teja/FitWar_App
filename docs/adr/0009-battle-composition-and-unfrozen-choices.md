# ADR 0009 — Battles Compose the Challenge Engine, and the Four Choices Phase 0 Left Open

## Status
Accepted

## Context
The frozen architecture defines a great deal about 1v1 battles and leaves a few things
genuinely undecided. What it *does* fix:

- `Battle` has `challenge_id`, `group_id`, `creator_id`, `status (pending|active|completed|cancelled)`,
  `timezone`, `start_at`, `end_at`; `BattleParticipant` has `status (invited|accepted|declined|active|won|lost)`
  and `score` (§4 ERD). The ERD's cardinality makes both the group and the backing
  challenge mandatory on the battle side.
- `1V1` is one of V1's three game modes (§20.3, design spec §11).
- The 1v1 outcome is "higher final score, tie-broken by the fixed five-step rule,
  **mirrored onto both `BattleParticipant.status` and the linked `ChallengeParticipant.outcome`**" (§20.3).
- Battles have no elimination — they resolve purely by final score over a fixed
  duration (§20.4).
- A battle tied to a group uses that group's frozen timezone (§11).
- The endpoint set: `GET /battles`, `GET /battles/rivals`, `POST /battles`,
  `GET /battles/{id}`, `POST /battles/{id}/accept`, `POST /battles/{id}/decline`,
  `POST /battles/{id}/verify`, `WS /ws/battles/{id}` (API_SPEC).
- "Battle win" is a named reason in the XP ledger (design spec §9).

What it does not fix: the amount of the win bonus, the default daily target when the
optional `target_value` is omitted, which group hosts a battle between two people who
share several, and whether a battle may be verified by manual video proof.

## Decision

### 1. A battle is a two-player arrangement around the existing challenge engine
Every `Battle` owns a `Challenge` with `game_mode = 1v1`, and each `BattleParticipant`
has a matching `ChallengeParticipant`. This is the reading the frozen model already
forces — §20.3 cannot mirror an outcome onto "the linked `ChallengeParticipant`" unless
one exists — and it is the only reading that satisfies "do not create a second
independent game architecture."

The consequence is that battles add **no** scoring code: verification, the challenge-day
window, the daily target comparison, per-day XP, the streak, `rank_key`'s five-step
tie-break and `points_outcomes` are all the Phase 4/5 implementations, reused unchanged.
What Phase 7 adds is the invitation, the acceptance, and the finalization that turns two
scores into one recorded verdict.

**The backing challenge is not reachable through the challenge API.** `ChallengeService.get`
raises `CHALLENGE_NOT_FOUND` for a 1v1, and every challenge listing and clock sweep
excludes them. This is a security boundary, not tidiness: `POST /challenges/{id}/join`
would otherwise be a way to put a third player into a 1v1.

### 2. `BATTLE_WIN_XP = 100`
Twice a daily completion (ADR 0008's 50). Winning a head-to-head should read as a bigger
deal than banking one more day, without letting battle spam outrun the daily habit the
economy is built to reward. Paid to the winner only; the loser is not debited, because
the ledger is strictly additive (ADR 0002) and §20.11 gives the Defeat screen no XP
block at all. Idempotent through `uq_xp_transaction_idempotency` on
`(user, reason, reference_type='battle', reference_id=battle.id)`.

### 3. Default daily targets
`POST /battles` makes `target_value` optional, so the server needs its own defaults
rather than trusting a client to supply one: steps 10,000, active calories 500,
distance 5 km. These match the per-activity defaults the design's create flow already
shows, so the two surfaces cannot disagree.

### 4. Group resolution, and one live battle per pair
The frozen rival list is group-scoped (`GET /battles/rivals?group_id=`), so the product
rule is "you may challenge someone you share a squad with". `POST /battles` therefore
takes an **optional** `group_id` — an addition to the frozen request body, not a change
to it: omitted, the server infers the group when exactly one is shared, and answers
`GROUP_REQUIRED` when several are, rather than guessing which squad a battle belongs to.

Two users have at most one *live* (pending or active) battle between them, enforced by a
partial unique index on a symmetric `pair_key`. This is what makes the frozen
`409 ALREADY_PENDING_WITH_USER` a database guarantee rather than a best-effort lookup,
and it matches the design's own Battles screen, which shows one live battle. Being
partial, it never blocks a rematch once a battle is finished or cancelled.

### 5. V1 battles verify from health data only
`POST /battles` accepts only activities Apple Health can measure, and the backing
challenge's `verification_method` is always `apple_health`.

Manual video proof needs a reviewer who is not competing. The frozen reviewer set is
"the challenge's creator plus the group's admins" (§20.5), and in a battle the creator
*is* one of the two competitors — so the frozen rule puts a player in the chair to judge
their own match. Rather than invent an impartial-reviewer rule the architecture does not
define, V1 restricts battles to the automatic path. The frozen `POST /battles` body
never carried a `verification_method` field, which is consistent with battles verifying
one way.

## Consequences
- A push-ups battle is not possible in V1. This is stated to the user at creation time
  (the client offers only the three measurable activities) rather than failing later.
- Adding manual-proof battles later needs a reviewer rule, not new infrastructure: the
  media, upload, retention and review machinery from Phase 6 already works against the
  backing challenge.
- Because a battle *is* a challenge underneath, anything added to the challenge engine —
  a new provider, a new metric, a change to the tie-break — reaches battles with no
  battle-side work at all. The reverse is also true: a bug in `rank_key` is a bug in
  both, which is the point.
- `BATTLE_WIN_XP` and the default targets are unvalidated by real player behaviour, the
  same caveat ADR 0008 carries. Changing them affects future awards only; the ledger is
  immutable.
