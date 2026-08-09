# Campaign Brief — my-pa Completion Campaign

```yaml
campaign_id: MYPA-CANONICAL-APPLICATION-COMPLETION-PLAN-20260809-001
completion_plan_package: MYPA-CANONICAL-APPLICATION-COMPLETION-PLAN-20260809-001
canonical_product_package: MYPA-CANONICAL-PRODUCT-DEFINITION-20260809-009
validated_audit_package: MYPA-CURRENT-STATE-PACKAGE-20260809-001
repository: RMF112018/my-pa
remote: https://github.com/RMF112018/my-pa.git
operating_lineage: recovery/pre-20260805-utc-rollback-c9fb513
operating_lineage_head: c9fb513a2afadf98f29b6d5ec3ad69db69e5ec1a
operating_lineage_tree: 9975318c731ac6150f251df7bdee5475c3b529d8
reauthentication_date: "2026-08-09"
active_work_package: WP-01
active_work_package_name: Lineage, Goal-State, and Repository Current-State Correction Foundation
supersedes: WP-N01
completed_work_packages: []
milestone_ms0: WP-01 -> WP-02 -> WP-03
```

This brief is the campaign's continuity aid, not a governance ledger. `AGENTS.md` remains the normative policy; this file states where the campaign currently stands against it.

## Supersession: WP-N01 -> WP-01

`WP-N01` was a local, improvised, pre-canonical work package. It was stopped mid-flight and produced **zero output and zero repository mutation**. It is superseded by canonical **WP-01 — Lineage, Goal-State, and Repository Current-State Correction Foundation**, defined by `MYPA-CANONICAL-APPLICATION-COMPLETION-PLAN-20260809-001`. Canonical WP-01 differs materially from WP-N01: it centers on documentation and goal-state correction and explicitly excludes branch move/merge, whereas WP-N01 had included repo-hygiene operations.

## Dependency status

- WP-01 has no dependencies.
- WP-01 -> WP-02 -> WP-03 forms milestone MS-0.
- Completed work packages: none yet.
- Remaining work: 34 bounded work packages across 8 workstreams per the completion plan.

## Open blocking findings

None. An independent review of WP-01 passed with no blocking findings; the two disclosed non-blocking gaps it raised are recorded below and are not blockers.

## Non-blocking follow-ups

- **Stale documentation outside WP-01 scope, pending follow-up:** `web/README.md` still declares `Status: IMPLEMENTING (WP-02/R1)` and lists "the Microsoft Graph connector (WP-07)" as pending delivery; `docs/architecture/system-context.md` cites a stale eleven-revision Alembic head (the actual head on the operating lineage is `d2e3f4a5b6c7` across 21 revision files). Both files were outside WP-01's declared in-scope path list and were deliberately left unchanged. They present pre-correction sequencing language to a reader, and `README.md` links to `web/README.md`. Route to a follow-up work package.
- **Archival note:** the superseded Moss v4.0 per-work-package merge ledger (merge SHAs and per-PR test counts) was not carried into this brief; it remains recoverable from `git log origin/main`.

## Specification prerequisites (open-decision register)

- `OD-COMP-001` — the supported native mechanism supplying Apple Tasks/To-Do is undefined; resolved in WP-14. Microsoft Graph must **not** be used as an implicit fallback. Blocks WP-19.
- `OD-COMP-002` — the current GoodNotes source path / runtime integration requires fresh investigation; the historical NAS-path package is not current authority. Resolved in WP-25. Blocks WP-26.
- `OD-COMP-004` — the offline encryption-key and signed-out/stale-auth policy must close before WP-08 acceptance.

## Source-of-truth direction

- **Apple-first personal-data ingestion**: Apple Mail, Apple Calendar, Apple Contacts, and Apple Tasks/To-Do, captured through the first-party native Apple architecture (`native/apple-source-host/`).
- **Microsoft Graph is retained but off by default**, and is **not** the active personal-data ingestion path. Entra authentication (used for the frontend's synthetic identity boundary) is a separate concern from Graph connector activation. A disabled Graph connector must never be reported as a degraded active source.

## Extreme-risk operator-only decisions

Reserved to the operator under `AGENTS.md` §8.2 (production activation, destructive/irreversible operations, credential mutation, live personal-data access, material risk acceptance, policy amendment, and the rest of that list). Not restated here.

## Invalidation rules

Any of the following invalidates this brief's identity binding and requires re-diff/review before continuing:

- a commit lands on the operating lineage (`recovery/pre-20260805-utc-rollback-c9fb513`);
- any source branch head listed in the topology table below moves;
- any of the three canonical packages named above changes.

## Operating lineage identity

- Repository: `RMF112018/my-pa` (`https://github.com/RMF112018/my-pa.git`)
- Operator-designated operating lineage: `recovery/pre-20260805-utc-rollback-c9fb513`
- Base head: `c9fb513a2afadf98f29b6d5ec3ad69db69e5ec1a`
- Tree: `9975318c731ac6150f251df7bdee5475c3b529d8`
- Reauthentication date: 2026-08-09 — exact match to the completion plan's planning-time claim; no drift.

## Branch topology (recomputed against recovery, 2026-08-09)

Format: "recovery-only / ref-only" = commits recovery is ahead / commits the ref is ahead.

| Ref | Head | Merge-base with recovery | recovery-only / ref-only |
|---|---|---|---|
| `origin/bf/wp-12e-frozen-baseline` | `6348b246f8be66f3db044d50a71b5d90aeeb3f57` | `88e8d81` | 7 / 2 |
| `origin/bf/mcv-neutral-remainder` | `86f13426fab91b4711c5557b10113800ea90a68a` | `634890e` | 11 / 7 |
| `origin/bf/extractions-quarantined-debt` | `688cc5047a06f6c193468568765378f23055250b` | `634890e` | 11 / 26 |
| `origin/dependabot/github_actions/actions/checkout-7.0.1` | `73bed38b1a6459789ff443c1882e49de9da88041` | `c9fb513` (= recovery) | 0 / 1 |
| `origin/main` | `6e491c24db97bd1ff2c537be4fbb58ff75ed2b81` | `634890e` | 11 / 2 |

Drift vs. the completion plan's planning-time claims: `bf/extractions-quarantined-debt` advanced from `f21e2f6000016a4c973f219d10a267b07e990c2a` (25 ahead) to `688cc5047a06f6c193468568765378f23055250b` (26 ahead). All other branch heads match their planning-time claims.

Local-vs-origin divergence in the primary checkout: local `main` and local `bf/wp-12e-frozen-baseline` both point at `88e8d8193095afa8d903db08324a588a5786908b` (an ancestor of recovery, 7 behind), differing from both `origin/main` and `origin/bf/wp-12e-frozen-baseline`.

Open PRs (2026-08-09, none draft): #44 `bf/wp-12e-frozen-baseline` -> `main`; #50 `dependabot/github_actions/actions/checkout-7.0.1` -> `main`; #53 `bf/mcv-neutral-remainder` -> `main`.

## Branch-reconciliation posture

Change-selective porting only. **No whole-branch merge** of `bf/wp-12e-frozen-baseline`, `bf/mcv-neutral-remainder`, or `bf/extractions-quarantined-debt` into the operating lineage. The dependabot branch (`dependabot/github_actions/actions/checkout-7.0.1`) is a simple candidate port: workflow-only, 1 commit directly ahead of recovery. Historical feature branches are preserved as history and are not remerged wholesale.

## Migration facts (bound to recovery head `c9fb513a…`)

21 revision files under `migrations/versions/`; exactly one Alembic head, `d2e3f4a5b6c7` (`20260805_d2e3f4a5b6c7_create_situation_frame_trace_project_tables.py`). No multi-head anomaly.

## Repository size (bound to recovery head `c9fb513a…`)

135 `.py` files under `src/`; 131 `.py` test files (149 files total) under `tests/`.

## Preservation record

The in-flight WP-12E slice-E work that was uncommitted in the primary checkout (26 entries) is preserved in commit `b2d597927a6b548830a1ed16340f8d19925496a1` on local branch `bf/wp-12e-slice-e-wip` (local only, not pushed). `bf/wp-12e-frozen-baseline` was left unchanged at `88e8d81`.

## Decisions

### D-01 — Operating lineage is recovery, not `main`

- **Decision:** the operating lineage is `recovery/pre-20260805-utc-rollback-c9fb513` at `c9fb513a2afadf98f29b6d5ec3ad69db69e5ec1a`, reauthenticated 2026-08-09.
- **Rationale:** GitHub's default branch is metadata, not operating-lineage authority; the operator designated recovery as the working lineage.
- **Evidence:** `c9fb513a2afadf98f29b6d5ec3ad69db69e5ec1a` — exact match to the completion plan's planning-time claim.
- **Invalidation:** a commit lands on `recovery/pre-20260805-utc-rollback-c9fb513` moving its head past `c9fb513a…`.

### D-02 — WP-12E slice-E work preserved, local-only

- **Decision:** the uncommitted WP-12E slice-E working-tree changes (26 entries) were committed to local branch `bf/wp-12e-slice-e-wip` at `b2d597927a6b548830a1ed16340f8d19925496a1` before WP-01 began; `bf/wp-12e-frozen-baseline` was left unchanged at `88e8d81`.
- **Rationale:** preserve in-flight work without altering the frozen-baseline branch. Kept local-only because `bf/wp-12e-slice-e-wip` diverges from its origin ref and pushing would require a force-push, which is prohibited under this work package.
- **Evidence:** commit `b2d597927a6b548830a1ed16340f8d19925496a1` on local `bf/wp-12e-slice-e-wip`.
- **Invalidation:** `bf/wp-12e-slice-e-wip` is pushed, merged, or its local head moves without a recorded reason.

### D-03 — Campaign brief location

- **Decision:** this brief lives at `docs/campaign/CAMPAIGN-BRIEF.md`, not the repository root.
- **Rationale:** canonical WP-01's in-scope path list is authoritative and does not include a repo-root brief.
- **Evidence:** WP-01 authorization's in-scope path list.
- **Invalidation:** a future canonical work package explicitly relocates it.

### D-04 — `bf/extractions-quarantined-debt` drift

- **Decision:** record the drift rather than silently re-deriving it.
- **Rationale:** `bf/extractions-quarantined-debt` advanced from the plan's `f21e2f6000016a4c973f219d10a267b07e990c2a` (25 ahead) to `688cc5047a06f6c193468568765378f23055250b` (26 ahead) between planning time and this reauthentication.
- **Evidence:** `origin/bf/extractions-quarantined-debt` at `688cc5047a06f6c193468568765378f23055250b`.
- **Invalidation:** WP-02 must re-diff against the current head before any porting decision from that branch.

## Operating rules in force

1. Repository governance (`AGENTS.md`) governs execution; the canonical completion plan governs product/roadmap intent; authenticated runtime and repository evidence outranks both when facts conflict.
2. No whole-branch merge of the three long-lived `bf/*` branches named above.
3. No push, no PR, no branch/worktree deletion under WP-01.
4. Extreme-risk actions remain reserved to the operator (`AGENTS.md` §8.2).

## State update protocol

Update this brief's frontmatter and decision log at every material transition (work-package start, PR open, merge, blocker, invalidation). Superseded decisions move to history with their replacement identified — they are not silently rewritten.
