# ADR 0001 — No Public/Discoverable Challenges in V1

## Status
Accepted

## Context
The approved design (`FITWAR.dc.html`) shows a DISCOVER tab on the Challenges screen with large, presumably-public challenges (e.g. a 1,204-player "CITY STEP LEAGUE") joinable without prior group membership. The Phase 0 domain model assumes every challenge belongs to a group the user already belongs to (`Group → Challenge`), so this was flagged as the one place the design plausibly conflicted with the frozen architecture.

## Decision
V1 ships **no public challenge discovery**. Every challenge is reached through an existing group, joined via invite link or invite code. No `GET /challenges?scope=discover` endpoint or equivalent is built.

`Group.privacy` (`invite | public`) remains in the schema exactly as originally designed, but is dormant in V1 — nothing sets or reads it as `public`.

## Consequences
- The Challenges screen ships with ACTIVE and COMPLETED tabs only; DISCOVER is dropped from the delivered app.
- No schema migration is needed to add discovery later: the natural extension is "a public `Group` anyone can self-join," which `Group.privacy` already supports. Only a new `GET /groups?visibility=public` endpoint and join flow would be needed.
- Authorization for the `challenges` module stays simple — every challenge access check is "is the caller a member of this challenge's group," with no branch for anonymous/public access.
