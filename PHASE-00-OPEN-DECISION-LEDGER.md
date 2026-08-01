---
artifact_id: LEDGER-PKL-P00-001
artifact_type: Open-decision ledger
version: 0.1.0
status: OPEN_FOR_OPERATOR_AND_REPOSITORY_REVIEW
feature_id: FEATURE-PKL-001
phase_id: PHASE-00
repository: RMF112018/my-pa
authenticated_head_sha: 3e6f7218b424f8f7dc6c5bac78956dfffe0cb8ae
authenticated_tree_sha: UNAVAILABLE_FROM_AUTHENTICATED_CONNECTOR
planning_basis_sha: b8563870afcf87b63e4cde6e0a48bfc59f0bd5b7
classification: INTERNAL_DECISION_RECORD
supersession_state: NEW_CANDIDATE_NOT_IN_REPOSITORY
---


# Phase 00 Open-Decision Ledger


## 1. Status and use


This ledger isolates unresolved decisions so the document package remains internally consistent without pretending those decisions are approved. Recommended defaults are design recommendations, not operator decisions, implementation authority, risk acceptance, or lifecycle activation.


Authoring basis: `RMF112018/my-pa`, `main@3e6f7218b424f8f7dc6c5bac78956dfffe0cb8ae`, with the tree SHA and operator-local worktree status unavailable to the authenticated connector at the time. Phase 00 planning basis was `b8563870afcf87b63e4cde6e0a48bfc59f0bd5b7`.


Reconciled basis: `main@e773e6f2285da9e453a8ca7e11bdac23619aaf22`, tree `0c726df770c5be7581a7106bf1e399e1f0ea1e98`, one worktree, pull requests #1 through #17 merged and none open, verified locally on 2026-08-01. The authoring basis above is left as written rather than overwritten; `P00-OD-001` records the reconciliation and the rule that invalidates it.


States: `OPEN_OPERATOR`, `OPEN_REVIEW`, `DEFERRED_PHASE_GATE`, `RECOMMENDED_DEFAULT_ACTIVE_IN_PACKAGE`, `RESOLVED`, and `SUPERSEDED`. The last two were added when repository truth answered a decision the package could only defer; the original entry is left visible beside its resolution rather than rewritten. A third state, `SUPERSEDED_PENDING_OPERATOR_CONFIRMATION`, existed briefly for `P00-OD-008` while an operator-only decision awaited its operator; it is gone because the operator answered, and it is recorded here rather than erased so the sequence stays legible.


## 2. Decision summary


| Decision ID | Question | Recommended default | Deadline | Operator-only | Package consistent unresolved? | State |
|---|---|---|---|---|---|---|
| `P00-OD-001` | Exact repository head/tree/worktree basis? | Revalidate current `main`; record head/tree/clean/dirty/untracked/open PRs before writes | Before integration | Yes for worktree handling | Resolved; basis recorded | `RESOLVED` |
| `P00-OD-002` | How handle drift from `b8563870…`? | Rebase package onto current `main`; authenticated drift is workflow-pin-only | Before integration | If later drift conflicts | Resolved by integration | `RESOLVED` |
| `P00-OD-003` | MCV extractor scope? | Text/Markdown mandatory; approve one reviewed PDF extractor before Phase 04 or report unsupported | Before Phase 04 acceptance | Yes | Yes | `OPEN_OPERATOR` |
| `P00-OD-004` | Public contract versioning? | Proposed semantic `v1`; reject unknown request fields; freeze after review | Before Phase 01 contracts | Final acceptance | Yes | `OPEN_REVIEW` |
| `P00-OD-005` | Disclosure defaults? | Mandatory envelope; local/private; source-bound; `cloud_eligible=false`; explicit partial/unavailable | Before Phase 01 | Any weakening | Yes | `RECOMMENDED_DEFAULT_ACTIVE_IN_PACKAGE` |
| `P00-OD-006` | May cloud models receive MCV content? | No raw/private cloud disclosure; separate provider/purpose/field/terms/audit approval | Before cloud processing | Yes | Yes | `OPEN_OPERATOR` |
| `P00-OD-007` | Repository routing conflict? | Use requested paths; update source/architecture/security/spec routing in separate repo change | Before merge | Repo-write/merge | Resolved by integration | `RESOLVED` |
| `P00-OD-008` | Physical PostgreSQL target? | Disposable isolated DB only; physical alias/connection unresolved and fail-closed | Before existing DB access | Yes | Confirmed by the operator; the narrowed clause was restored rather than accepted | `RESOLVED` |
| `P00-OD-009` | Provider/root for MCV proof? | Synthetic fixture first; live canary only with exact root and separate authorization | Before live canary | Yes | Yes | `DEFERRED_PHASE_GATE` |
| `P00-OD-010` | HTTP/MCP authentication? | Local-only authenticated principal with one common policy path; select mechanism in Phase 05 | Before exposure | Yes | Yes | `DEFERRED_PHASE_GATE` |
| `P00-OD-011` | Numeric resource limits? | Freeze bounded semantics; set conservative measured values in implementing phases and disclose through capabilities | Before capability acceptance | Material changes only | Yes | `DEFERRED_PHASE_GATE` |
| `P00-OD-012` | Is `pg_trgm` mandatory? | FTS mandatory; add `pg_trgm` only when lexical tests justify | Before Phase 04 query freeze | No | Yes | `OPEN_REVIEW` |
| `P00-OD-013` | Audit immutability/retention? | Append-oriented events and linked corrections; destructive retention deferred | Before Phase 02 audit | Retention/deletion yes | Yes | `DEFERRED_PHASE_GATE` |
| `P00-OD-014` | Parser isolation mandatory? | Strict limits/no network/no credentials; separate process when parser review/evidence warrants | Before PDF approval | Residual risk yes | Yes | `OPEN_REVIEW` |
| `P00-OD-015` | Does Drive package complete Phase 00/activate Phase 01? | No; integration, exact-head review, evidence, and operator transition separately required | Permanent boundary | Yes | Yes | `RECOMMENDED_DEFAULT_ACTIVE_IN_PACKAGE` |


## 3. Detailed decisions


### `P00-OD-001` — Exact repository basis


- **Evidence:** Repository/default branch/head authenticated; no open PRs observed. Tree SHA and local checkout/dirty/untracked state unavailable.
- **Default:** Separately authorized local agent fetches `origin/main`, records full commit/tree, worktree path, branch/detached state, status including untracked files, and open PRs immediately before writing. Stop on unexpected drift or dirty state.
- **Deferral consequence:** Drive package is reviewable but cannot be exact-tree repository truth or completion evidence.
- **Operator-only:** Handling of local changes.
- **Invalidation:** Any later commit or local-state change.
- **Resolution, 2026-08-01:** The basis is no longer unavailable. Verified locally rather than through the connector: `RMF112018/my-pa`, `main@e773e6f2285da9e453a8ca7e11bdac23619aaf22`, tree `0c726df770c5be7581a7106bf1e399e1f0ea1e98`, one worktree, and pull requests #1 through #17 all merged with none open. The invalidation rule above is unchanged and still governs: this record is superseded by any later commit or local-state change, and the recorded default remains the procedure for the write that follows.


### `P00-OD-002` — Planning-basis drift


- **Evidence:** Current `main` is four commits ahead of `b8563870…`; authenticated comparison reports only two GitHub Action dependency-pin updates in `.github/workflows/repository-checks.yml`, with no path or product/architecture/governance document change.
- **Default:** Treat content drift as nonmaterial, integrate against fresh current `main`, and record exact tree/head. Do not alter the master plan to hide drift.
- **Deferral consequence:** Exact applicability cannot be accepted.
- **Resolution, 2026-08-01:** Resolved by integration. The package was integrated onto current `main` in pull request #5, and thirty commits have landed since `b8563870…`, the most recent being pull request #17. The package is versioned with the repository, so drift from a planning basis is no longer a question the ledger has to hold open; ordinary Git history answers it.


### `P00-OD-003` — Extractor scope


- **Evidence:** Governing plan recommends text/Markdown plus one reviewed PDF extractor; repository governance requires minimal dependencies/current need.
- **Default:** Text/Markdown mandatory. Select one maintained PDF extractor after maintenance, license, vulnerability, malformed-input, resource-limit, sandbox, and removal review. Until selected, PDF is `decision_gated`/`unsupported` and coverage says so.
- **Deadline:** Before Phase 04 implementation acceptance.
- **Deferral consequence:** Text/Markdown vertical slice may proceed; PDF acceptance cannot pass.


### `P00-OD-004` — Contract versioning


- **Default:** Proposed `v1`. Reject unknown/ambiguous request structures. After freeze, additive optional response fields only under documented consumer compatibility; breaking changes require new major version.
- **Deadline:** Before Phase 01 schemas.
- **Deferral consequence:** Incompatible/permissive transport contracts.


### `P00-OD-005` — Disclosure defaults


- **Default:** Mandatory envelope with scope, coverage, freshness, trust, truncation, limitations, source references, unavailable evidence, partial state, classification, and cloud eligibility. Default `private_local` or `synthetic_test`; `cloud_eligible=false`; no path/provider/ORM/host/DB/credential leak.
- **Deadline:** Before Phase 01.
- **Deferral consequence:** Results may overstate completeness or disclose internal details.


### `P00-OD-006` — Cloud model boundary


- **Evidence:** Repository security states local availability is not consent to transmit; governing plan recommends raw/private local-only.
- **Default:** Prohibit cloud transmission. Later decision must name provider/account, purpose, fields, eligibility, retention/training terms, redaction, audit receipt, revocation, and security review.
- **Consequence:** Local retrieval remains valid; no cloud use.


### `P00-OD-007` — Repository routing/indexes


- **Evidence:** Architecture index plans the named architecture documents; requested threat model belongs in `docs/security`; `docs/specs` and `docs/security` currently have scaffold READMEs, not owning indexes; root source index governs routing.
- **Default:** Preserve requested paths. In separate authorized integration, update `docs/00_REPOSITORY_SOURCE_INDEX.md`, architecture index, and minimal owning READMEs/indexes only as needed; route one threat model without duplication.
- **Consequence:** Drive package complete, repository navigation incomplete until integration.
- **Resolution, 2026-08-01:** Resolved by integration. Every requested path exists as requested, `docs/00_REPOSITORY_SOURCE_INDEX.md` routes each document, `docs/specs/README.md` and `docs/security/README.md` are owning indexes rather than scaffold READMEs, and the threat model is routed once from `docs/security` with the architecture index linking rather than duplicating it. The link checker in `.github/workflows/repository-checks.yml` fails the build on an unresolvable relative link, so the routing claim is checked on every run.


### `P00-OD-008` — Physical PostgreSQL


- **Evidence:** ADR-002 fixes logical `my_pa` and defers physical alias; DB identity/credentials/schema/backup unavailable.
- **Default:** Disposable isolated DB only in Phase 02. Fail closed when `MY_PA_DATABASE_URL`/compatibility metadata absent, ambiguous, or inconsistent. Never guess, inspect, connect, rename, or migrate an existing DB.
- **Consequence:** No existing DB access; synthetic MCV can proceed.
- **Supersession, 2026-08-01:** The default above is superseded in fact by the migration merged as pull requests #13 through #17. The physical target is no longer unresolved: a local PostgreSQL 17 instance holds the canonical database `my_pa`, published on loopback port `5433`, with `pg_trgm` and `unaccent` installed; Alembic owns all target DDL and stands at head `6c4d3ea82f10`; and the legacy corpus was loaded into it. No pre-existing third-party database was guessed at, renamed, or connected to; the target was created for this purpose and the legacy source is retained read-only and never written. Disposable isolated databases remain the rule for tests, and the CI database tier runs against a throwaway service that names `my_pa_ci`, never the canonical instance.
- **One part of the default did not survive, and was not disclosed when it changed.** The default above requires failing closed when `MY_PA_DATABASE_URL` is **absent**, ambiguous, or inconsistent. Absence no longer fails closed: `src/my_pa/bootstrap/settings.py` declares `database_url: str = DEFAULT_DATABASE_URL`, so an unset variable silently resolves to the canonical local instance rather than refusing to start. Malformed values still fail closed, as does any unknown `MY_PA_` name. That narrowing happened in the migration work, not in the change that records it here. The default itself was not concealed: pull request #13 stated its value verbatim. What no pull request in #13 through #17 named is that having a default contradicts this decision, and #13 described the change as fail-closed validation while introducing it. It is recorded now rather than left implicit. Whether the narrowing is acceptable is an operator decision; the safe alternative is a required setting with no default.
- **Resolved by the operator, 2026-08-01.** This decision is operator-only and the operator settled it directly. The supersession stands: the physical target is the local canonical `my_pa` instance established by the merged migration. The narrowing did **not** stand — rather than accept a default that aimed unconfigured processes at the canonical database, the operator directed that `MY_PA_DATABASE_URL` become required. `src/my_pa/bootstrap/settings.py` now declares it with no default and refuses to start without it, so the original clause of this decision — fail closed when the URL is absent — holds again in full. `docs/migration/00_MIGRATION_INDEX.md` owns the result record.
- **Why required rather than guarded.** The default's convenience was illusory. The canonical database needs a password supplied out of band, so an unset URL either failed to connect or, in the one configuration where it worked, pointed a destructive operation at the migrated corpus. A runtime identity check would not have helped: the default *was* `my_pa`, so the check would have confirmed the dangerous case. Absence now refuses to choose a target. What remains outside this decision is an operator who explicitly names the canonical database and explicitly runs a destructive migration; that is operator-gated under `AGENTS.md` section 5 and is not this decision's business.


### `P00-OD-009` — Provider/root


- **Default:** Small synthetic local fixture/provider and explicit logical root for tests. Later live canary requires exact operator authorization, approved read-only root, least privilege, and evidence. Runtime receives roots; future operator tooling uses `ssh bf-nas` only when separately authorized.
- **Consequence:** No live-source claim.


### `P00-OD-010` — Transport authentication


- **Default:** Bind test transports locally and select one explicit authenticated principal mechanism in Phase 05. Both transports pass derived identity to the same application policy. Request fields cannot self-assert operator authority.
- **Consequence:** Non-test transport remains disabled until resolved.


### `P00-OD-011` — Resource-limit values


- **Default:** Freeze fields and deny-unbounded behavior now. Set conservative numeric defaults from Phase 03–05 evidence; expose effective maxima through `capabilities.get`; adjust from measured evidence only.
- **Consequence:** Capability remains unavailable rather than unbounded.


### `P00-OD-012` — `pg_trgm`


- **Default:** PostgreSQL FTS mandatory. Add `pg_trgm` only if lexical tests show current need for tolerant matching and cost is proportionate.
- **Consequence:** MCV proceeds without fuzzy matching.


### `P00-OD-013` — Audit correction/retention


- **Default:** Append-oriented events, linked corrections, no silent overwrite, no destructive retention in MCV. Define retention/deletion later with backup/privacy/legal/operator controls.
- **Consequence:** No production retention claim.


### `P00-OD-014` — Parser isolation


- **Default:** Strict resource limits, no network/credentials/source-write handles, bounded temporary storage, quarantine. Require separate process/sandbox if selected PDF parser or adversarial evidence shows material risk not contained in-process.
- **Consequence:** PDF remains unsupported until safe decision.
- **Risk:** This session accepts none.


### `P00-OD-015` — Lifecycle effect


- **Decision boundary:** Drive publication does not complete Phase 00, unblock Phase 01, authorize repository writes/implementation/merge, or accept risk. Repository integration, checks, independent review, operator acceptance, merge, and transition remain separate.


## 4. Existing accepted decisions


- `PKL-D-001`: Neutral names `my-pa`, `my_pa`, `MY_PA_`.
- `PKL-D-002`: Modular monolith with gateway/worker/CLI (ADR-001).
- `PKL-D-003`: Logical DB `my_pa`, physical alias deferred (ADR-002).
- `PKL-D-004`: Original sources authoritative/read-only; managed writes separate.
- `PKL-D-005`: PostgreSQL structured authority; lexical before vector/graph.
- `PKL-D-006`: PostgreSQL jobs/leases/outbox before Redis/Celery.
- `PKL-D-007`: Obsidian projection noncanonical/rebuildable.
- `PKL-D-008`: Future operator NAS access uses `ssh bf-nas`; runtime receives configured roots.


## 5. Disposition impact


Open decisions do not make the documents internally false because each has a conservative fail-closed default. They prevent an unqualified completion disposition and prevent Phase 00 completion, implementation, merge, live access, or Phase 01 activation. After verified publication, the appropriate disposition is `PHASE_00_DOCUMENT_PACKAGE_PUBLISHED_WITH_OPEN_DECISIONS`.


Reconciled 2026-08-01: `P00-OD-001`, `P00-OD-002`, `P00-OD-007`, and `P00-OD-008` are resolved, so those four no longer contribute to that block, and contracts, persistence, and the migration have since been implemented and merged. The decisions still open do contribute to it, and `P00-OD-003`, `P00-OD-006`, and `P00-OD-009` remain operator-only.


## 6. Related documents


- [`docs/specs/mcv-read-only-vertical-slice.md`](docs/specs/mcv-read-only-vertical-slice.md)
- [`docs/architecture/system-context.md`](docs/architecture/system-context.md)
- [`docs/architecture/module-boundaries.md`](docs/architecture/module-boundaries.md)
- [`docs/architecture/data-authority.md`](docs/architecture/data-authority.md)
- [`docs/security/threat-model.md`](docs/security/threat-model.md)
- [`README-PHASE-00-DOCUMENT-PACKAGE.md`](README-PHASE-00-DOCUMENT-PACKAGE.md)
