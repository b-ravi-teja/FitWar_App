# ADR 0008 — XP Award Amounts and Level Thresholds

## Status
Accepted

## Context
Phase 0 and the design review froze the *shape* of the XP economy but never its numbers:

- XP is strictly additive — a missed day never debits the ledger (§20.2 / ADR 0002).
- An award is composed of "completion + streak bonus" (design spec §9, the Mission Complete screen shows the breakdown).
- A level is a "linear, per-level threshold" driving the XP bar (design spec §9).

No document states how much a completed day is worth, how the streak bonus scales, or where a level boundary sits. The one number that appears anywhere — "−40 XP" for a missed mission — was explicitly ruled prototype mock data, not a rule (ADR 0002). Phase 5 cannot ship a game system without deciding, so this records the decision rather than burying the constants in code as if they had been frozen all along.

## Decision
V1 uses fixed, non-configurable constants in `domain/game/xp_rules.py`, exactly the treatment ADR 0004 gave the failure-rule threshold:

| Constant | Value | Reasoning |
|---|---|---|
| `DAILY_COMPLETION_XP` | 50 | The bulk of the economy. Showing up is the behaviour V1 wants to reward, and a flat number keeps "what did I earn?" answerable at a glance. |
| `STREAK_BONUS_PER_DAY` | 10 | Paid per consecutive day *beyond the first*, so day 1 earns the base award alone and the bonus grows as the habit holds. |
| `MAX_STREAK_BONUS_DAYS` | 5 | Caps the bonus at +50. Uncapped, a long streak would dwarf every other source and make a mid-challenge joiner unable to catch up regardless of effort. |
| `XP_PER_LEVEL` | 500 | Linear, per the design's XP bar. Level 1 starts at 0 XP, so a first completed day fills 10% of the bar — visible progress on day one without trivialising later levels. |

The server computes the level; the client renders it. The provisional client-side formula in `ProfileViewModel` (`1 + xp / 1000`) is deleted — two authorities disagreeing about a user's level is precisely the bug this prevents.

## Consequences
- These are service-layer constants, not schema. Changing them is a one-line edit that affects future awards only; the ledger is immutable, so historical awards keep the value they were granted at.
- `ChallengeRule` remains the extension point if awards ever need to vary per challenge — "read from a rule row instead of a constant", the same migration-free path ADR 0004 describes.
- Because the ledger is the source of truth and `xp_total` a transactionally-synced projection, retuning these numbers never requires a backfill: past rows stay as written.
- **These values are unvalidated by real player behaviour.** They are a starting point chosen to be legible, not a balanced economy, and should be revisited once there is usage data.
