# R01-WP08 — Capture Project transport, replay integrity, Conversation lineage proof, canonical Task handoff

## Identity

- **Execution coordination ID:** `MYPA-PC-CM-R01-WP08-IMPLEMENTATION-EXEC-20260922-001`
- **Parent dispatch:** `MYPA-PC-CM-R01-WP08-IMPLEMENTATION-DISPATCH-20260922-001`
- **Parent hardening review:** `MYPA-PC-CM-WP08-PACKAGE-HARDENING-REVIEW-20260922-001`
- **Work item:** R01-WP08
- **Repository:** `RMF112018/my-pa`

## Authorization boundary

Activated implementation prompt `LOCAL-AGENT-IMPLEMENTATION-PROMPT-R01-WP08.md`
(Drive `1iDa_tBfgLHPDRSgAMOH4c0XXjuff_XaS`, 28546 bytes,
SHA-256 `6720327e240fabdab7cbf66d0df389d6bcef3bc2fd7663524dcb1868cc9ce63b`) — verified byte-exact before mutation.

Dispatch receipt `1-_lgI1DXq1_ywMKRvNiEVZQINoiPhneB` (8501 bytes,
SHA-256 `07b460c0a500c5d1c1ef3eccc9af8b121d62cc5c4e7ce9118ba94cb44876ec86`) — verified.

Hardening review receipt `1hkmjjfmxBIiADShqK8GTkjFzRRQHgaGN` (10585 bytes,
SHA-256 `c33b8fd806a066da41fb863c57801043cd66e59b12ae6b580f6c45feb5276778`) — verified.

Controlling execution specification: `WP08-HARDENED-IMPLEMENTATION-SPECIFICATION.md`
(Drive `11z7uCEPhCLZaCW6wRjIv_uHit_RVns_2`) plus the mandatory companion matrices.

## Repository identity

| Field | Value |
|---|---|
| Authorized base HEAD | `5625004cc612e804807454d533bfe297d1d07da1` |
| Authorized base tree | `a751ec95f173aac1760b271fa6d2ebb4c80d8201` |
| Authorized base parent | `44b25b4709772a760ed35e3f2e4035a266ae98d7` |
| Baseline PR | `#277` |
| Branch | `bf/pc-cm-run01-wp08-capture-project-20260922` |
| Worktree | `/Users/bobbyfetting/.local/share/my-pa-worktrees/pc-cm-run01-wp08` |
| PR | recorded on creation |

Preflight verdict: `EXACT_BASE_CONFIRMED_NO_DRIFT`.

## Objective

Implement the hardened WP08 specification exactly: browser Capture Project transport with canonical
persisted acknowledgement; one local Capture Project Context and minimum bounded selector; frozen
online intent with duplicate-submit mutex; versioned encrypted (v2) offline Capture intent with
origin-scoped serialization and verified atomic replay deletion; canonical Task handoff with frozen
Project precedence and result gate; real Conversation lineage proof; exact required CI selectors.

## Scope

In scope, and no more: the ADD/MODIFY paths in the WP08 path/symbol execution matrix, plus tests
T01–T24 and the named `.github/workflows/frontend-quality.yml` selector changes.

## Acceptance

Accepted universe remains exactly 406 criteria (143 CM-BE, 165 PC-CM-FE, 24 PC-CM-UX,
32 PC-CM-SCOPE, 30 PC-CM-CAPTURE, 12 PC-CM-CAPTURE-PROJECT). WP08 implements, regression-proves, or
evidences only the criteria routed to it by the complete reconciliation artifact, including all
twelve `PC-CM-CAPTURE-PROJECT` criteria as classified there. Composite criteria awaiting later
Run02 / four-form / physical-device evidence are not marked PASS.

## Constraints and prohibited actions

No merge to `main`; no direct push to `main`; no post-merge cleanup; no deployment or production
activation; no live migration; no live personal/project data; no credential, OAuth, grant, secret,
external-provider, workbook, DNS, firewall or production-configuration mutation; no destructive
action; no expenditure; no risk acceptance; no acceptance-criterion weakening; no terminal
406-criterion closure.

No backend migration; no IndexedDB schema/version upgrade; no historical backfill; no new
Capture/Task backend domain, persistence, capability or idempotency ledger; no new Conversation
Project column or domain association; no generic Capture Task write/offline queue; no generic
Capture Constraint kind/path; no absorption of WP09/WP10/Run02 scope.

`PC-CM-WP07-CARRIED-REORDER-DIGEST` remains carried/open and outside this work item.

## Execution topology

Mandatory `AGENTS.md §8.3` Manager → dedicated Orchestrator → Specialized Workers. The parent
review's single-context §8.3 exception is not inherited. Worker ownership domains are Worker A
(BFF, Phase 1), Worker B (offline, Phase 2), Worker C (shell/Task, Phase 3), Worker D (proof/CI,
Phase 4), followed by a fresh non-authoring exact-head independent reviewer with blocking authority.

## Test and evidence results

Recorded in the terminal governed response
`COORDINATION-RESPONSE-MYPA-PC-CM-R01-WP08-IMPLEMENTATION-EXEC-20260922-001.md` and its verified
roundtrip receipt. Drive execution folder: `1ZTAND_xAlqiUBa40RVSFdLo9y7G76W2C`.

## Final state

Target: `R01_WP08_IMPLEMENTATION_COMPLETE_REVIEWED_EXACT_HEAD / PR_READY_FOR_OPERATOR_MERGE_DECISION`.

**NO MERGE AUTHORITY.** Merge is an operator decision.
