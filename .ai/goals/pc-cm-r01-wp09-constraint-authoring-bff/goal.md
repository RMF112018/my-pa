# R01-WP09 — Constraint authoring BFF routes, exact-Project admission, safe mutation decoders, reorder digest correction

## Identity

- **Execution coordination ID:** `MYPA-PC-CM-R01-WP09-IMPLEMENTATION-EXEC-20260923-001`
- **Work item:** R01-WP09
- **Repository:** `RMF112018/my-pa`

## Authorization boundary

Approved Gate-1 plan
`COORDINATION-RESPONSE-MYPA-PC-CM-R01-WP09-IMPLEMENTATION-EXEC-20260923-001-PLAN.md`
(Drive `1OxeeQ1a0vA1dKyKDXXmoV6f1SEH4Qi6H`, 44112 bytes,
SHA-256 `b3fbd1e103ffa082cc116aedb58ee57f9d53f1a4a1da66917b1b2d6cc294ce8a`) — approved by the
operator (`PLAN_APPROVED`, 2026-09-23).

| Artifact | Drive ID |
|---|---|
| Dispatch | `1atOtN2pK9RINXV_Sa1MDoB3by-bQXy8q1ybuCr-PT8E` |
| Hardening review receipt | `1qPP4jeYB1cHB-gKNvuf545BJ-wsg_oIWLOHlEItRJcc` |
| Implementation package folder | `1V-MqGaE21rOxntFf1QWe8LGrdNuNEgUY` |

Controlling execution specification: package artifact 17
(`17_WP09_HARDENED_IMPLEMENTATION_SPECIFICATION.txt`), with artifacts 18 and 19.

## Repository identity

| Field | Value |
|---|---|
| Authorized base HEAD | `8b1f739f6d8e1c65148029954618f1329be7dcaa` |
| Authorized base tree | `b0899586eab5a20e83ae7fc4d08b7a3558d8e3ad` |
| Branch | `bf/pc-cm-r01-wp09-constraint-authoring-bff-20260923` |
| Worktree | `/Users/bobbyfetting/.local/share/my-pa-worktrees/pc-cm-r01-wp09` |
| PR | recorded on creation |

## Objective

Provide a browser-safe authoring transport over the already-landed Constraint and Constraint
Category mutation backend. The work covers 13 BFF mutation routes with exact-Project admission,
allowlist-projected success decoders that strip principal, idempotency, digest, client-context,
correlation and recorded-at metadata, and one backend correction: the Category reorder request
digest now includes its expected versions (`PC-CM-WP07-CARRIED-REORDER-DIGEST`). This is not the
WP10 authoring UI. It needs no schema or migration change, and it is online-only (no offline
mutation queue).

## Constraints and prohibited actions

No merge to `main`; no direct push to `main`; no post-merge cleanup; no deployment or production
activation; no live migration; no live personal/project data; no credential, OAuth, grant, secret,
external-provider or production-configuration mutation; no destructive action; no risk
acceptance; no acceptance-criterion weakening.

No backend schema change; no generic object passthrough; no offline authoring mutation; no
absorption of WP10/Run02 scope.

## Execution topology

`AGENTS.md §8.3` Manager → Orchestrator → Workers topology is **waived by the operator for this
effort only**. The local agent integrates every shared file (one writer). At most one worker
subagent runs at a time, and its output is reviewed before the next worker starts. The effort ends
with a fresh, non-authoring, exact-head independent review.

## Test and evidence results

Recorded in the terminal governed response for the execution coordination ID above.

## Final state

**NO MERGE AUTHORITY.** Merge is an operator decision.
