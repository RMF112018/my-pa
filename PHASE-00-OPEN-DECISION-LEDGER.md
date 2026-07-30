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


Authenticated basis: `RMF112018/my-pa`, `main@3e6f7218b424f8f7dc6c5bac78956dfffe0cb8ae`. Current tree SHA and operator-local worktree status are unavailable. Phase 00 planning basis was `b8563870afcf87b63e4cde6e0a48bfc59f0bd5b7`.


States: `OPEN_OPERATOR`, `OPEN_REVIEW`, `DEFERRED_PHASE_GATE`, and `RECOMMENDED_DEFAULT_ACTIVE_IN_PACKAGE`.


## 2. Decision summary


| Decision ID | Question | Recommended default | Deadline | Operator-only | Package consistent unresolved? | State |
|---|---|---|---|---|---|---|
| `P00-OD-001` | Exact repository head/tree/worktree basis? | Revalidate current `main`; record head/tree/clean/dirty/untracked/open PRs before writes | Before integration | Yes for worktree handling | Yes, marked unavailable | `OPEN_OPERATOR` |
| `P00-OD-002` | How handle drift from `b8563870…`? | Rebase package onto current `main`; authenticated drift is workflow-pin-only | Before integration | If later drift conflicts | Yes | `OPEN_REVIEW` |
| `P00-OD-003` | MCV extractor scope? | Text/Markdown mandatory; approve one reviewed PDF extractor before Phase 04 or report unsupported | Before Phase 04 acceptance | Yes | Yes | `OPEN_OPERATOR` |
| `P00-OD-004` | Public contract versioning? | Proposed semantic `v1`; reject unknown request fields; freeze after review | Before Phase 01 contracts | Final acceptance | Yes | `OPEN_REVIEW` |
| `P00-OD-005` | Disclosure defaults? | Mandatory envelope; local/private; source-bound; `cloud_eligible=false`; explicit partial/unavailable | Before Phase 01 | Any weakening | Yes | `RECOMMENDED_DEFAULT_ACTIVE_IN_PACKAGE` |
| `P00-OD-006` | May cloud models receive MCV content? | No raw/private cloud disclosure; separate provider/purpose/field/terms/audit approval | Before cloud processing | Yes | Yes | `OPEN_OPERATOR` |
| `P00-OD-007` | Repository routing conflict? | Use requested paths; update source/architecture/security/spec routing in separate repo change | Before merge | Repo-write/merge | Yes | `OPEN_REVIEW` |
| `P00-OD-008` | Physical PostgreSQL target? | Disposable isolated DB only; physical alias/connection unresolved and fail-closed | Before existing DB access | Yes | Yes | `DEFERRED_PHASE_GATE` |
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


### `P00-OD-002` — Planning-basis drift


- **Evidence:** Current `main` is four commits ahead of `b8563870…`; authenticated comparison reports only two GitHub Action dependency-pin updates in `.github/workflows/repository-checks.yml`, with no path or product/architecture/governance document change.
- **Default:** Treat content drift as nonmaterial, integrate against fresh current `main`, and record exact tree/head. Do not alter the master plan to hide drift.
- **Deferral consequence:** Exact applicability cannot be accepted.


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


### `P00-OD-008` — Physical PostgreSQL


- **Evidence:** ADR-002 fixes logical `my_pa` and defers physical alias; DB identity/credentials/schema/backup unavailable.
- **Default:** Disposable isolated DB only in Phase 02. Fail closed when `MY_PA_DATABASE_URL`/compatibility metadata absent, ambiguous, or inconsistent. Never guess, inspect, connect, rename, or migrate an existing DB.
- **Consequence:** No existing DB access; synthetic MCV can proceed.


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


## 6. Related documents


- [`docs/specs/mcv-read-only-vertical-slice.md`](docs/specs/mcv-read-only-vertical-slice.md)
- [`docs/architecture/system-context.md`](docs/architecture/system-context.md)
- [`docs/architecture/module-boundaries.md`](docs/architecture/module-boundaries.md)
- [`docs/architecture/data-authority.md`](docs/architecture/data-authority.md)
- [`docs/security/threat-model.md`](docs/security/threat-model.md)
- [`README-PHASE-00-DOCUMENT-PACKAGE.md`](README-PHASE-00-DOCUMENT-PACKAGE.md)
