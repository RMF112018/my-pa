# Campaign Brief — my-pa Completion Campaign

```yaml
campaign_id: MYPA-CANONICAL-APPLICATION-COMPLETION-PLAN-20260809-001
completion_plan_package: MYPA-CANONICAL-APPLICATION-COMPLETION-PLAN-20260809-001
canonical_product_package: MYPA-CANONICAL-PRODUCT-DEFINITION-20260809-009
validated_audit_package: MYPA-CURRENT-STATE-PACKAGE-20260809-001
repository: RMF112018/my-pa
remote: https://github.com/RMF112018/my-pa.git
operating_lineage: recovery/pre-20260805-utc-rollback-c9fb513
operating_lineage_head: 60f8ccfba72cff3cd9be10164fca1f19af8d84e7
operating_lineage_tree: 8ccdc862e90d61858b540b3a40e881f368303269
reauthentication_date: "2026-08-09"
active_work_package: WP-03
active_work_package_name: Persistence and Alembic Migration-Chain Reconciliation
supersedes: WP-N01
completed_work_packages: [WP-01, WP-02, WP-S01]
milestone_ms0: WP-01 -> WP-02 -> WP-S01 -> WP-03
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
3. No force-push and no history rewrite. Branch/worktree deletion remains an operator decision.
4. Extreme-risk actions remain reserved to the operator (`AGENTS.md` §8.2).

## State update protocol

Update this brief's frontmatter and decision log at every material transition (work-package start, PR open, merge, blocker, invalidation). Superseded decisions move to history with their replacement identified — they are not silently rewritten.

### D-05 — WP-01 integrated into the operating lineage by fast-forward

- **Decision:** WP-01 was integrated into `recovery/pre-20260805-utc-rollback-c9fb513`, advancing it `c9fb513a… -> 49b6f034…` as a true fast-forward rather than by the squash that `CONTRIBUTING.md` sets as the default.
- **Rationale:** brief §34 requires the target lineage to advance per completed package, and leaving WP-01 unintegrated would force every later package to branch off a feature branch — the exact fragmentation this campaign exists to remove. Fast-forward was chosen over squash because squash mints a SHA that neither of WP-01's two independent exact-head reviews examined; fast-forward preserves the reviewed identity `49b6f034…` byte for byte.
- **Evidence:** push reported `c9fb513..49b6f03` (two-dot, non-forced); resulting tree `6bd5da8292acfa62a503f90bb6b7e31217226b9f` equals the reviewed WP-01 tree. PR #54 was opened as the repository-native record and GitHub marked it merged from the fast-forward. Architecture suite 1342 passed at the new head.
- **Invalidation:** none outstanding.

### D-06 — WP-02 squash-merged, deliberately, for a security reason

- **Decision:** WP-02 was squash-merged into the operating lineage rather than merged with a merge commit, and no pull request was opened for `bf/wp-02-selective-branch-reconciliation`.
- **Rationale:** an intermediate commit on that branch carried reproduction detail for a then-unpatched defect. Squashing kept it from becoming a permanent ancestor of this public lineage; opening a pull request would have minted a permanent public `refs/pull/N/head` carrying the same blob. The merged tree `d1bc78bc…` is byte-identical to the independently reviewed tree, so the review carries over on content despite the new SHA.
- **Evidence:** the commit is not an ancestor of the operating lineage; merged tree equals reviewed tree `d1bc78bc073f2980fa547507e996b94156e5e75e`. The branch `bf/wp-02-selective-branch-reconciliation` has since been deleted from the remote under operator authorization, so nothing *at head* advertises the commit. That is the whole of the claim: an earlier wording here said "nothing in this repository," which was false and contradicted the residual immediately below it. The parent commit `c3711a1…` still carries the identifier verbatim in a tracked blob, and `git log -S` over the history surfaces it in one command. Removing it from history would be a rewrite, and this campaign has declined to perform one.
- **Residual, stated plainly:** deleting the branch and omitting the SHA removes *forward signposting only*. It is not a history rewrite and the commit is not gone: it remains in GitHub's object cache and is retrievable by anyone who already holds or can guess its identifier, until GitHub Support purges it. No claim is made here that history was scrubbed or purged.
- **Invalidation:** superseded once GitHub Support confirms the purge, after which the ordinary pull-request route resumes. The defect the commit concerned is itself now patched (see the backlog item below), which lowers the value of the residual but does not remove it.

### D-07 — WP-02 ported 8 of 29 ahead-commits; the rest are declined or deferred with reasons

- **Decision:** of 29 unique ahead-commits across the four retained branches, 8 were ported, 6 declined as direction-incompatible or false-at-target, and 15 deferred to WP-03. No branch was merged wholesale and no migration file was touched.
- **Rationale:** `bf/extractions-quarantined-debt` strictly contains `bf/mcv-neutral-remainder` (identical SHAs), so the true unique population is 29, not the 36 a naive per-branch sum suggests. Every commit is accounted for exactly once.
- **Evidence:** `docs/campaign/WP-02-INTEGRATION-RECORD.md`; independently recomputed by the reviewer as 8 + 6 + 15 = 29 with zero unaccounted and zero phantom entries.
- **Invalidation:** any of the four source branch heads moves.

### D-08 — WP-S01 was inserted ahead of WP-03 by operator decision, as its own bounded package

- **Decision:** the URL-parser divergence carried out of WP-02 as backlog item 1 was fixed as its own work package, **WP-S01**, executed before WP-03 rather than deferred. The operator was presented the verified facts and chose to remove the underlying defect rather than only its disclosure, and to do so immediately as a bounded package.
- **Rationale:** the defect was live at head and the branch carrying its reproduction detail was still published. Containing the disclosure without patching the defect would have left the defect; patching without containing would have left the disclosure. Both were closed in one cycle.
- **Scope executed:** the remote branch `bf/wp-02-selective-branch-reconciliation` was deleted under explicit, narrow operator authorization — an exception to the standing prohibition on branch deletion, covering that one remote ref and nothing else. Its local counterpart was removed afterwards as an ordinary bounded work-branch cleanup under `AGENTS.md` §8.1, once its content was re-derived as fully contained in this lineage.
- **Evidence:** before deletion the branch tip differed from this lineage in exactly one file, `docs/campaign/CAMPAIGN-BRIEF.md`, and on the stale side only — every other path was byte-identical, so nothing unique was lost. Merged tree `8ccdc862e90d61858b540b3a40e881f368303269` equals the independently reviewed tree.
- **Residual:** deleting the branch removed forward signposting; it is **not** a history rewrite. See D-06.
- **Invalidation:** none outstanding.

## Triaged backlog carried out of WP-02

These are recorded decisions, not oversights. None blocks WP-03.

1. **URL-parser divergence — FIXED by WP-S01; no longer live.** `src/my_pa/bootstrap/settings.py` validated the database URL with one parser while `src/my_pa/infrastructure/database/engine.py` let the engine parse it with another, so the configuration the validator approved was not necessarily the one the engine connected to. It is now parsed exactly once, by the parser that governs the connection, and that same parse is what the engine is configured with — there is no second reading left to diverge from the first. Regression coverage is of two kinds, and saying so is the point: an earlier version of this sentence named only the first and was measured to guard **one of seven** production call sites. `tests/unit/test_settings.py` counts the parser and asserts one reading of the string per `load_settings`, and `tests/unit/test_gateway_composition.py` asserts the object validation approved is what the gateway's engines are configured with — behavioural, and between them they cover `bootstrap/gateway.py` alone. The other six callers are held structurally by `tests/architecture/test_connections_open_on_the_single_validated_parse.py`, which parses every production module's syntax tree and rejects any `create_database_engine` call whose URL argument does not resolve — through local bindings, so an aliased parse still counts — to `Settings.parsed_database_url()`. All seven sites fail that guard when reverted to `.database_url`; six of them reddened nothing before it existed. What the guard does **not** do is behavioural: it shows that no production module *asks* for a second parse, not that the engine received the approved object. That half remains the two unit tests', and it remains gateway-only. All of it is expressed as invariants rather than as inputs. This was carried out of WP-02 as its own bounded work package, which is what WP-S01 was. Reproduction detail remains withheld from this public repository under `SECURITY.md`.
2. **The conditional split of `6e491c24…` was declined** as not cleanly separable — its `settings.py` hunk and all five of its tests are welded to statement-timeout machinery WP-02 was not authorized to port. 21 files of that commit are unported and enumerated in the integration record.
3. **`docs/plans/mcv-completion-plan.md` is deliberately untouched** beyond a single re-derived count. It still presents the superseded MCV work-package order as current while remaining linked from `README.md`. This is a documentation-reconciliation item and is **not** WP-03 scope (WP-03 is the migration chain only).
4. **WP-03 acceptance condition:** WP-12E's baseline tables were authored before principal partitioning existed and carry no `principal_id`. Any re-authoring of those migrations into the single chain must address this.
5. **The database tier has now been executed in this environment — this item is withdrawn as written.** It previously read "has never been executed in this environment (no PostgreSQL reachable)," and that is no longer true. PostgreSQL 17.10 runs in a local Docker container and the full suite has been observed to pass against it end to end, twice and by two parties: at **3639 passed, zero failures and zero errors** by an independent second context that ran it itself before this correction, and at **3657 passed, zero failures and zero errors** at head `02b1f4e` by an independent reviewer who collected and ran it there, which is the same suite plus the sixteen tests this correction adds and the two further unit tests that landed after it. This sentence read **3655** when it was written, which was true at `f202fb6` and went stale by two the moment those unit tests landed without the figure being brought forward; the number here is now the head one, and it is the head, not the correction alone, that the count belongs to. An earlier run reporting `3139 passed, 500 errors` is superseded and was not evidence of defects: every one of those errors was `password authentication failed`, from supplying a password to a server configured for `trust` on loopback — a misconfiguration of the run, corrected before the figure above. The consequence for WP-02's `search.py` redaction fix is that it is no longer covered by the AST guard alone; its two end-to-end tests are inside that suite and ran. What is still **not** claimed: no continuous-integration environment has been shown to reproduce this, the container is a developer's local one rather than a provisioned tier, and WP-03 still needs a live PostgreSQL of its own to discharge its acceptance criteria.
