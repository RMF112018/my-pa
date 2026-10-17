# Record lineage WP-00A preflight — base `ac24e3bf`

**Status:** read-only repository-truth evidence for Slice S1 implementers of the
record lineage programme (`MYPA-LINEAGE-ADVERSARIAL-REVIEW-20261017-001`,
successor plan WP-00A, AT-026, spec CR-014). It is neither an architecture
decision, a schema change, an authorization, nor a test-completion receipt. No
source, schema, migration, grant, live record or deployment was changed to
produce it.

**Candidate identity:** branch `feat/lineage-s1-integration`, commit
`ac24e3bf55e3d038250edd1f4cfa4709022c1481`, tree
`d4d2f462318986941cf164af9bad2316092c42e1` (identical to `origin/main` at the
time of inspection and to the identity the review package was bound to).

**Evidence boundary:** every fact below was read from the checked-out tree or
produced by a command run against it from the worktree with `PYTHONPATH=src`.
The live gateway profile, deployed commit and production database stamp were
**not** inspected (not authorized); statements about them are quoted from the
package and marked `PACKAGE-REPORTED`. Database observations come only from a
disposable Homebrew PostgreSQL 15.15 cluster on a loopback port, removed after
use (CI uses PostgreSQL 17).

Line references are `path:line` at this commit. `src/` paths are relative to
`src/my_pa/` unless they start with `src/`, `tests/`, `migrations/` or `web/`.

## 1. Repository and migration identity

| Item | Observed | Evidence |
| --- | --- | --- |
| HEAD / tree | `ac24e3bf55e3…` / `d4d2f462318…` | `git rev-parse HEAD HEAD^{tree}` |
| `alembic heads` | `b9025e7fb738 (head)` — exactly one head | `PYTHONPATH=src ~/my-pa/.venv/bin/python -m alembic heads` (script directory, offline; no DB) |
| Head parent | `b9025e7fb738` ← `5c1e7a9b3d42` ← `c8f7ae406d47` | `migrations/versions/20261015_b9025e7fb738_reconcile_legacy_project_entity_links.py:94-95`, `…20261014_5c1e7a9b3d42_commitment_counterparty_entity.py:64-65` |
| Revision count | 118 revisions (`ScriptDirectory.walk_revisions`); `migrations/versions/*.py` glob = 118 | single base `5d75f23847c9` |
| Branch points (all re-merged) | `7c2e9b4a1d80`, `4f6a9c2d8e17`, `9d5e2f7b4c61`; merges `b7c4e9a2d518`, `7504585e3ca5`, `c8f4a2d9e761` | `alembic branches`; `ScriptDirectory` walk |
| Isolated empty→head | 13 `migration_empty_to_head` tests passed on scratch PG 15 | section 8 |
| Production / NAS DB stamp | **not obtained** (not authorized) | — |
| Deployed runtime commit | `UNVERIFIED` (`PACKAGE-REPORTED`) | RV-CKPT-01 |

A new S1 revision must set `down_revision = "b9025e7fb738"` and become the single
head. Doing so moves literals that pin the head and the file count (section 5.4).

## 2. Capability and authorization baseline

### 2.1 Current sets (derived, not hand-counted)

| Set | Count | Where |
| --- | --- | --- |
| `Capability` (public) | 192 | `domain/identity/operation.py:38` (enum) |
| `NativeSourceCapability` | 11 | `domain/identity/operation.py:975` |
| Audit capability vocabulary (`capability_is_known`) | 203 = 192 + 11 | `infrastructure/persistence/tables.py:364` `_CURRENT_AUDIT_CAPABILITIES`, `:1013`; last restated by `migrations/versions/20261011_a591b81f10a2_intelligence_report_type_registry.py:37-41,504-507` |
| `Purpose` | 52 | `domain/identity/purpose.py:14` |
| Write capabilities / operator-only | 102 / 5 public (`is_write_capability`, `is_operator_only`) | `operation.py:1529`, `:1046` |
| ChatLLM policy classes | DATA_REQUIRED 74, DATA_CONDITIONAL 97, CONTROL_PLANE_EXCLUDED 17, COMPATIBILITY_ONLY 2, OPERATOR_DECISION_REQUIRED 2 (sum 192); profile `chatllm-data-v9` | `domain/identity/chatllm_capability_policy.py:18,50,138,249,256,286` |
| `RecordEventFamily` | 23 (no `situation`, no lineage family) | `domain/record_events.py:130-162` |
| `IdKind` | 142, all distinct | `domain/common/identifiers.py:31` |

Confirmed absent from `Capability` (every package-proposed name, from
`07_PROPOSED_API_CONTRACTS.json` `capabilities`, 28 entries): no member starts with
`issues.`, `records.`, `programs.` or `evidence.`; no `records.lineage`; no
`meetings.notes.*` (the Meeting family is exactly `meetings.create`, `.read`,
`.list`, `.search`, `.update`, `.series.update`). All 28 proposed names are free.
The existing names the package proposes to *extend* all exist: `tasks.create`,
`commitments.create|read|list|search|waiting_on`, `meetings.update`,
`constraints.create`, `constraints.close`, `reports.commit`.

`reports.types.create` and `reports.types.list` **do** exist in code (added by
`f604d518`, revision `a591b81f10a2`), classified DATA_REQUIRED / ALWAYS. The
package's live observation of 169 eligible operations without `reports.types.*`
(`PACKAGE-REPORTED`) is consistent with 74 + 97 − 2 = 169, i.e. with a runtime
that predates `a591b81f10a2`; this is not verifiable here.

### 2.2 End-to-end registration checklist for one new capability

Derived from the two most recent analogous additions: `d6c706bb` (6
`meetings.*` + 2 purposes + revision `7d9a450dfd07`, 124 files) and `6a5d5612`
(`record_events.provenance`, 63 files), cross-checked against `f604d518`.

**Domain / authorization**

1. `domain/identity/operation.py` — `Capability` member (`:38`); `_PERMITTED_PURPOSES` (`:1065`); `_WRITE_CAPABILITIES` (`:1529`) and, for creates, `_ADDITIVE_WRITE_CAPABILITIES` (`:1678`); `_OPERATOR_ONLY` (`:1046`) only if it widens scope.
2. `domain/identity/purpose.py:14` — new `Purpose` if needed (e.g. `issue_read`/`issue_authoring`).
3. `domain/identity/chatllm_capability_policy.py` — exactly one classification set; a missing entry fails import (`:1-6`). Bump `CHATLLM_DATA_PROFILE_VERSION` (`:18`) when the data profile changes. Family is the first dotted segment (`:356-366`).
4. `domain/policy/decision.py:148` `_SCOPELESS` — product-owned records carry no source scope.
5. `application/authorization.py:370-` `_requested_scope` match arm (cf. `ReadMeeting()` at `:655`).
6. `domain/record_events.py:900` `RECORD_EVENT_FAMILY_READS` / `:978` routing — only if a new Record Event family is admitted (also a `record_family` CHECK change, `tables.py:14118`).

**Application / adapters**

7. `application/commands.py` — frozen dataclass with `capability: ClassVar` and `mcp_payload_properties` (pattern `ReadMeeting`, `:10748-10765`); add to `type Command` union (`:11912`).
8. `application/service.py` — handler in `_HANDLERS` (`:14977`; e.g. `:15172`).
9. `adapters/normalization.py` — builder in `_BUILDERS` (`:2512`; e.g. `:2691`).
10. `adapters/mcp/remote.py:46` `_WRITE_PURPOSES` — any new *write* purpose, or the write is classified a remote read.
11. `adapters/remote_request.py:146` `_IDEMPOTENT_REMOTE_CAPABILITIES` (writes with an `idempotency_key`) or `:51` `_SERVER_REPLAY_REMOTE_CAPABILITIES` (writes with none).
12. `adapters/mcp/chatllm_gateway.py:47` `_FEATURE_BY_FAMILY` — `issues`, `records`, `programs` are absent and would fall to `"other"` (`:109`).
13. `contracts/v1/<module>.py` — StrictModel views (no `principal_id`, key or digest); `contracts/ports.py` repository port and abstract `UnitOfWork` property (cf. `:6243`).
14. Spelled counts in `adapters/cli/app.py` and `bootstrap/gateway.py` docstrings ("the N capabilities").

**Schema** — one Alembic revision that restates `capability_is_known` and (if purposes change) `purpose_is_known` on `knowledge.audit_events` as frozen BEFORE/AT literals (pattern `a591b81f10a2:316-507`); without it the audit sink refuses the row at runtime. Update `_CURRENT_AUDIT_CAPABILITIES` (`tables.py:364`). `identity.remote_capability_grants.capability` is free `varchar(128)` with no CHECK (`migrations/versions/20260813_e3b7a1d5c942_add_remote_oauth_identity_and_grants.py`), so grants need no schema change — and live grant rows are operator-only.

**Every `UnitOfWork` subclass** (abstract property, D-10 closure) — `infrastructure/persistence/unit_of_work.py:1193`, `infrastructure/gsqs_b0_evaluation.py:139`, `tests/conftest.py:9608` (`FakeUnitOfWork`), `tests/schema/test_audit_durability.py:184`, `tests/concurrency/test_gateway_connection_pool.py:135`.

**Tests that pin counts, names or manifests** (the set `reports.types.list` touches, plus the Meeting precedent):
`tests/contract/test_capabilities_and_readiness.py:58` (`len(Capability) == 192` and the published name list), `tests/architecture/test_spelled_counts_match_the_sets_they_name.py` (ordinal table ~`:505`), `tests/architecture/test_readme_state_claims.py`, `tests/contract/test_chatllm_capability_policy.py`, `tests/contract/test_chatllm_data_profile_diff.py`, `tests/contract/test_chatllm_mcp_gateway.py`, `tests/contract/test_transport_parity.py`, `tests/contract/test_mcp_transport.py`, `tests/contract/test_http_transport.py`, `tests/contract/test_remote_mcp_transport.py`, `tests/contract/test_cli_transport.py`, `tests/policy/test_application_authorization.py`, `tests/unit/test_policy.py`, `tests/unit/test_remote_mcp_chatllm_profile.py`, `tests/unit/test_remote_request.py`, `tests/security/test_http_negative_evidence.py`, `tests/security/test_mcp_and_cli_negative_evidence.py`, `tests/security/test_no_capability_accepts_a_server_owned_field.py`, `tests/architecture/test_mcp_is_a_thin_adapter.py`, `tests/schema/test_*_migration.py` files that restate the audit vocabulary (`test_meeting_records_migration.py`, `test_knowledge_assertion_migration.py`, `test_capture_schema_migration.py`, …), `tests/contract/test_bff_success_decoder_parity.py`.

**Docs/README claims** — README.md, `docs/architecture/{00_ARCHITECTURE_INDEX,module-boundaries,system-context}.md`, `docs/operations/mcv-limitations.md`, `docs/plans/mcv-completion-plan.md`, `docs/plans/relationship-intelligence-implementation-plan.md`, `ops/runbooks/{mcp-and-cli-operations,gateway-operations,managed-knowledge-context}.md` were edited by each precedent because guard tests derive their counts.

**Web strict client** (only if the BFF calls the capability) — `web/src/contracts/gateway.json` (105 capabilities today; checked against Python by `tests/contract/test_bff_gateway_contract_parity.py`), a decoder in `web/src/lib/api/decode/capabilities/<name>.ts` registered in `web/src/lib/api/decode/index.ts` and `types.ts` (`registry.test.ts:7` "covers exactly the gateway.json capabilities"), and the regenerated `web/src/lib/api/decode/fixtures/python/success.json` (105 keys; parity-checked by `tests/contract/test_bff_success_decoder_parity.py`). New files under `web/` are git-excluded: `git add -f` and verify with `git ls-tree`.

## 3. Identifier prefix inventory

Shape: `<prefix>_<8..64 alphanumerics>`, total length at most 72; the prefix is
everything before the first `_` and must be an `IdKind` value
(`domain/common/identifiers.py:27-28,515-538`). DB columns carry
`_is_identifier` CHECKs `^<prefix>_<suffix>$` (`tables.py:438-450`). Uniqueness of
values is asserted by `tests/unit/test_identifiers.py:313-318`; the Knowledge
prefixes are additionally pinned at `:384-395`.

All 142 current prefixes: `abcred aff alias asn asrt audit bulk cap capver ccat cchst ccls cclt cdec cevd chst clbl clev clink clrcpt cmt cmthst conv corr cov cpart cpref cpty crel crev cst csyc csyr csyrh csyt ctxm dups eadr eals easev east ecmm efev eiam eief eiop eipv emrg emut enam enr ent eobs eppt eprp erdc erel frm iobs ires kadec kaevd kamut kaprp kasr kasub kdcp kdcpr kdsp kn lce matc matt mctx mdlce mdoc mdrcpt mdsub mdver mem memsub memver men mevd mhst micr mnote mpev mprop mser mshst mtg nacct nauth nbkt nbrg nbrun ncfg ncp ndisc njob nlg nrun nsim nsimr obj op org per phst poaf prj prn prop psit ptext puls rcev rcpt rdec revt rpt rrc rrun rvw sevd sit smem sobs span src stage sub tcm thst tli trc trec tsk umen ver xid`
(complete set dumped from `[k.value for k in IdKind]`).

Collision check of package-proposed new prefixes (spec 02 §2 line 42; 07 uses only
the generic pattern `^[a-z]+_[A-Za-z0-9]{8,64}$`):

| Proposed | Status |
| --- | --- |
| `irl`, `irv`, `ian`, `irp`, `irec`, `irs` | **free** (not an `IdKind`; no quoted `<p>_` literal anywhere in `src`, `tests`, `web/src`, `migrations`) |
| `ires` | **COLLIDES** — `IdKind.IDENTITY_RESOLUTION = "ires"` (`identifiers.py:90`, discussed `:343`) |
| `rlnk`, `rlrv`, `mnotev`, `rlink`, `ilnk`, `lrev`, `lanc`, `lreq`, `lprp`, `ldec`, `ihnd`, `isnap`, `lsnap`, `ipme`, `brun`, `bitm` (candidate alternatives checked) | free |
| `mnote`, `capver`, `mdver` | **existing** native version kinds (`MEETING_NOTE_VERSION`, `CAPTURE_VERSION`, `MANAGED_DOCUMENT_VERSION`), correctly referenced by the package as existing, not new |

The package's `07` ID pattern (`[a-z]+`) is looser than repo truth: a prefix must
be an `IdKind` member and the whole identifier at most 72 characters.

## 4. Native endpoint inventory (S1 families)

Schema for all tables: `knowledge` (`tables.py:356`).

| Family | Table (decl.) | PK | Principal column | Version / CAS | Archive / merge / terminal state | Composite principal targets & FKs |
| --- | --- | --- | --- | --- | --- | --- |
| Situation (`sit`) | `situations` `:2978-3002` | `situation_id` | `principal_id` | **none** (no `version`, no `kind`) | `state` ∈ open/active/suspended/closed; closed ⇔ `closed_at` | **No** `UNIQUE(situation_id, principal_id)`; inbound FKs are single-column (`commitments.situation_id :7073`, `tasks :7236`, `decisions :7147`, `project_situations :3218`, `frames :3012`) |
| Project (`prj`) | `projects` `:3067-3144` | `project_id` | `principal_id` | `version` + `project_history` `:3150` | state active/on_hold/closed | `UNIQUE(project_id, principal_id)` `a_project_is_identified_within_its_principal` `:3124` |
| Project↔Situation (`psit`) | `project_situations` `:3208-3239` | `project_situation_id` | `principal_id` | none | none (no end/effective columns) | single-column FKs to `projects.project_id`, `situations.situation_id`; `UNIQUE(project_id, situation_id)`; nullable `association_evidence_ref` (added `8f2b6c4d1a37`); **no** composite principal FK, no triplet unique |
| Meeting (`mtg`) | `meetings` `:13519-13618` | `meeting_id` | `principal_id` | `version` + `meeting_history` `:13770` | `status` scheduled/cancelled | `UNIQUE(meeting_id, principal_id)` `:13571`; composite FKs to series and project |
| Meeting note version (`mnote`) | `meeting_note_versions` `:13823-13905` | `note_version_id` | `principal_id` | immutable chain: `version_number`, unique `supersedes_note_version_id` | n/a (append-only trigger) | `UNIQUE(note_version_id, meeting_id, principal_id)` `:13853` — the exact target the spec's `lineage_meeting_note_anchor_binding` FK needs; composite FK to `meetings` and to its `meeting_history` receipt, all `RESTRICT` |
| Capture (`cap`) | `captures` `:1059-1067` | `capture_id` | **`owner_principal_id`** | no column; version = `max(version_number)` | lifecycle is a projection of append-only `capture_lifecycle_events` `:1420` | `UNIQUE(capture_id, owner_principal_id)` added by ALTER in `0641c354ca85` (deliberately not declared, `:1049-1053`) |
| Capture version (`capver`) | `capture_versions` `:1105-1164` | `version_id` | `owner_principal_id` | `version_number`, `UNIQUE(capture_id, version_number)` | append-only trigger `capture_versions_are_append_only` (`1a4c9e77b2d5:174,289`) | FK to `captures.capture_id` **`ON DELETE CASCADE`**; **no** `UNIQUE(version_id, capture_id, owner_principal_id)` composite target |
| Commitment (`cmt`) | `commitments` `:7061-7130` | `commitment_id` | `principal_id` | `version` + `commitment_history` `:7642` | `state` open/closed; `evidence_state` proposed/accepted (independent) | `UNIQUE(principal_id, commitment_id)` (**column order principal first**) `:7116`; composite counterparty FK; `project_id`, `situation_id` single-column FKs |
| Task (`tsk`) | `tasks` `:7224-7360` | `task_id` | `principal_id` | `version` + `task_history` `:7482` | `state` open/closed, `lifecycle_state` (6), `archived_at` | `UNIQUE(principal_id, task_id)` `:7339`; composite FKs `(principal_id, commitment_id)` and `(project_id, principal_id)`; `situation_id` single-column; `role` ∈ {`follow_up`} |
| Constraint (`cst`) | `project_constraints` `:11876-12027` | `constraint_id` | `principal_id` | `version` + `current_revision_id` → `project_constraint_revisions` (deferred) + `project_constraint_history` | 7 states incl. closed/void (`domain/project_controls/constraint.py:62-71`) | `UNIQUE(principal_id, constraint_id)` `:11983`; composite FKs to project and category; `crel_` relationships `:12503` |
| Entity (`ent`) | `entities` `:3279-3349` | `entity_id` | `principal_id` | `version` | `merged_redirect` with `superseded_by_entity_id`; `archived` | `UNIQUE(entity_id, principal_id)` `:3333` |
| Record Event (`rcev`) | `record_events` `:14083-14169` | `event_id` | `principal_id` | `sequence_number` per Principal | append-only + TRUNCATE refusal | `UNIQUE(event_id, principal_id)` `:14147` — matches spec's `link_mutation_event_receipts` FK target |

Composite-FK column-order note: `projects`, `meetings`, `entities`,
`record_events`, `meeting_note_versions` uniques are `(id, principal_id)`;
`commitments`, `tasks`, `project_constraints` are `(principal_id, id)`. A new FK must
list columns in the order of the referenced unique.

**Meeting notes today.** Each `meetings.create`/`meetings.update` that supplies notes
inserts one immutable full-body row (`infrastructure/persistence/meetings.py:924-941`);
`notes_mode` `append` composes `prior + "\n\n" + chunk`, `replace` stores the supplied
body exactly (`domain/meeting/model.py:630-650`); bodies are 1..100000 characters,
stored exactly, no normalization (`:404-410`); `content_sha256 =
sha256(body.encode("utf-8"))` (`:653-655`). Only the current head is readable
(`current_note`, `meetings.py:945-970`; view `contracts/v1/meetings.py:144-156`,
which exposes `note_version_id`, `version_number`, body and `recorded_at` but **not**
`content_sha256`). There is no capability that reads a non-current version.

**Work evidence today.** `ApplicationService._require_work_evidence`
(`application/service.py:4390-4407`) delegates to
`_Captures.accepts_work_evidence_reference` (`infrastructure/persistence/unit_of_work.py:547-576`):
`cap_` = an owned Capture **root** that is not archived (raises `CaptureWithdrawnError`
→ `denied/capture_withdrawn`); `asrt_` = an accepted, unsuperseded **capture
assertion** (`capture_assertions`, ADR-006 extraction plane — not a Knowledge
Assertion `kasr_`); anything else, including `capver_` and `mnote_`, is
`invalid_request/invalid_evidence_reference`. Port contract `contracts/ports.py:4102`.

**Record Event provenance.** `application/record_events.py:608-644` serves
`record_events.provenance` only for `RecordEventFamily.KNOWLEDGE_ASSERTION`; every
other family answers `not_found(subject)`. Confirmed. The Capture-event case is
already exercised by
`tests/database/test_record_event_provenance.py::test_unknown_foreign_withheld_and_non_knowledge_events_answer_alike`
(`:629-653`, creates a Capture and asserts its event answers exactly as unknown,
remote and local).

**Situation write paths (material).** The only authorized Situation capabilities are
`continuity.situations` (list, `service.py:6282`) and `continuity.situations.create`
(`service.py:6756`, via `continuity_authoring.author_situation`,
`infrastructure/persistence/continuity_authoring.py:312-345`, idempotency in
`continuity_authoring_submissions` `tables.py:7622`). `SqlSituationRepository.close_situation`
(`situation_repository.py:280-334`, no CAS, no row lock) and
`SqlProjectRepository.link_situation` (`:649-720`, the **only** writer of
`project_situations`) are reached only through the standalone `SituationService`
(`application/situation_service.py:62-116`), whose commands are deliberately not
in the `Command` union and hold no `Capability` (`application/commands.py:12116-12125`).
No production code reads `project_situations` (only `tables.py`,
`situation_repository.py`, `situation_service.py` name it). Situation mutations emit
no Record Event (no `situation` family).

## 5. Test inventory

### 5.1 Tiers and markers
Markers (`pyproject.toml` `[tool.pytest.ini_options]`, `--strict-markers`): `slow`,
`database`, `network`, `connector`, `evaluation`, `e2e`, `recovery`,
`database_clone`, `database_transactional`, `migration`, `migration_edge`,
`migration_empty_to_head`, `migration_historical`. Ordinary `database` tests default
to `database_clone` (`tests/db/fixtures.py:62-`).

CI jobs (`.github/workflows/repository-checks.yml`): `validate` (markdown relative-link
check `:59-104`, `ruff check .`, `ruff format --check .`, bare `mypy`, FAST pytest
`-m "not slow and not database and not network and not connector and not evaluation and not e2e and not recovery"`);
`dependency-floor` (`:308`, installs `name==floor` pins derived from `pyproject.toml`
— SQLAlchemy 2.0.32, alembic 1.13, psycopg 3.2.1, pydantic 2.12 — then bare `mypy` and
FAST at the floor); `database-current-head` (`:589`, PG 17, `-m "(database_clone or database_transactional) and not recovery and not e2e and not migration_edge and not migration_empty_to_head and not migration"`);
`database-recovery` (`-m recovery`); `migration-empty-to-head` (`-m migration_empty_to_head`);
`migration-edge` (`-m "migration_edge or migration"`); `web-security` (`npm ci`, tests,
lint, typecheck, build).

### 5.2 How a DB test gets a database
Session fixtures in `tests/db/fixtures.py` (`worker_head_template` `:156`, clone per
test `cloned_database_url` `:183`, `db_engine` `:254`, `migrated_engine` `:263`,
`empty_database_url` `:270`, `transactional_connection` `:326`) read
`MY_PA_DATABASE_URL` and `MY_PA_MIGRATION_DATABASE_URL`; CI passes the password in
`PGPASSWORD`, never inline (`repository-checks.yml:662-664`). Local route used here:
Homebrew `postgresql@15` `initdb --auth=trust` on a loopback port, password-less URLs,
`createdb my_pa_ci`, torn down after.

### 5.3 Migration test convention (precedent `tests/schema/test_meeting_records_migration.py`)
FAST: revision is the single head directly on its predecessor (`:150`), chain file
count (`:167`), revision imports no domain/persistence module (`:174`), frozen DDL
names every declared constraint/index (`:187`), BEFORE texts are byte copies of the
vocabulary predecessor (`:212`), AT texts add exactly the new vocabulary sorted
(`:238`), head admits every declared capability/purpose (`:289`), offline upgrade
emits everything (`:310`), offline downgrade refuses first (`:329`). Database:
empty→head (`:604`, marked `migration_empty_to_head`), previous head with rows → head
(`:622`), downgrade refuses while rows or audit rows exist (`:677`, `:693`),
append-only ledgers (`:706`), write request completes once (`:760`), cross-Principal
FK refusal (`:821`). Revisions use frozen literal DDL, no package import, no enum
derivation (`D-48`/`D-69`; enforced by
`tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py:894`), and a
data-refusing `downgrade` (`restrict_violation`).

### 5.4 Pins a new revision / table moves
- Head literal `"b9025e7fb738"` in 44 test files (`grep -rlE '"b9025e7fb738"' tests`), e.g. `tests/schema/test_reconcile_legacy_project_entity_links_migration.py:33`.
- `migrations/versions/*.py` count `== 118` in 22 files (e.g. `tests/schema/test_auth_identity_and_grants_migration.py:161`).
- `TABLES_SHA256` of `tables.py` in `tests/architecture/test_capture_project_binding.py:29,53` (currently `103244de…3aae31`, matches the file) — every `tables.py` edit must update it with a comment.
- `TABLES_ABOVE` sets for tables created above older revisions: `tests/schema/test_audit_schema_migration.py:362`, `test_extraction_schema_migration.py` (and `:773` `test_every_declared_table_is_created_by_exactly_one_revision`), `test_capture_schema_migration.py`, `test_enrollment_objects_migration.py`, `test_entity_*_migration.py`.
- Principal-partition guard registry `tests/architecture/test_principal_partition_is_reached_through_the_guard.py` (exact set of modules naming partitioned tables; use `infrastructure/persistence/principal_scope.py:177` `principal_scoped`).
- Test-module counts in `docs/plans/mcv-completion-plan.md` and `docs/plans/relationship-intelligence-implementation-plan.md` (`tests/architecture/test_claimed_test_counts_match_collection.py`).

### 5.5 Docs guards relevant to this file
`tests/architecture/test_spelled_counts_match_the_sets_they_name.py` and
`test_entity_plane_prose_matches_the_capability_sets.py` sweep every `docs/**/*.md`
for spelled set sizes (this file uses digits only); `test_non_scaffold_readmes_are_routed.py`
routes README directories (`docs/evidence/README.md` is `SCAFFOLD_ONLY`); the
`validate` link check resolves relative links. `docs/evidence/` needs no index entry:
`nas-credential-configuration-inventory-44b25b47.md` was merged (#274) as a single
file.

## 6. Append-only and privilege precedents to reuse

| Need in spec §2 | Repo precedent |
| --- | --- |
| Row-level immutable ledger (`BEFORE UPDATE OR DELETE … RAISE … restrict_violation`) | `migrations/versions/20260927_7d9a450dfd07_meeting_records.py:619-640,713-726` (`meeting_history`, `meeting_note_versions`, `meeting_series_history`); test `tests/schema/test_meeting_records_migration.py::test_the_ledgers_are_append_only` |
| `reserved → completed` exactly once (spec `record_link_requests`) | `7d9a450dfd07:642-668` `meeting_write_request_completes_once()`; test `::test_a_write_request_completes_exactly_once`. Same-transaction guarantee: Knowledge `knowledge_submission_is_never_left_reserved` `CONSTRAINT TRIGGER … AFTER INSERT DEFERRABLE INITIALLY DEFERRED` (`migrations/versions/20261004_6734f039f7a6_knowledge_assertion_layer.py:1811-1828`); test `tests/schema/test_knowledge_assertion_migration.py::test_a_submission_completes_once_and_is_never_committed_reserved` (`:2870`) |
| Controls-only mutation / insert-only registries | `6734f039f7a6:1783-1950` (`*_mutates_controls_only`, `*_is_insert_only`, `*_is_append_only`); tests `:2458`, `:2545`, `:2765`, `:3065` |
| `BEFORE TRUNCATE` statement trigger | `migrations/versions/20261002_c8e4a1b70d35_record_event_truncate_refusal.py` (only Record Event relations have one; Meeting and Knowledge ledgers do **not**); test `tests/schema/test_record_event_truncate_refusal_migration.py` |
| Role separation (owner / migrator / runtime, NOLOGIN, runtime least privilege) | `infrastructure/database/record_event_roles.py:1-80` (`my_pa_owner`, `my_pa_migrator`, `my_pa_runtime`), gate `record_event_privilege_gate.py`; test `tests/database/test_record_event_role_privileges.py` (`:116` runtime cannot truncate/update/delete; `:145` owner reaches refusal triggers). It is the **only** role provisioner; the Knowledge layer has none. |
| Code-level never-rewritten scan | `tests/architecture/test_record_events_are_never_rewritten.py` |
| Downgrade refusal with data | `7d9a450dfd07:672-697`, `a591b81f10a2:295-314` |
| Canonical digest / fingerprint discipline | ADR-014 clause 6 (`docs/decisions/ADR-014-knowledge-assertion-layer.md:32`): NFC strings, `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, UTF-8, SHA-256 hex, nulls present; Meeting request digest `application/meetings.py:320` |
| Native history without DB trigger | `commitment_history`, `task_history`, `project_history`, `continuity_lifecycle_events` have **no** append-only trigger (append-only by code only) |

Next ADR number: `ADR-015` is free (`docs/decisions/` holds ADR-001..ADR-014; index `docs/decisions/00_ADR_INDEX.md:18`).

## 7. Divergences — repository truth vs package (S1 scope)

1. **`ires` collides** with `IdKind.IDENTITY_RESOLUTION` (spec 02 §2 line 42 lists it as new). The other six proposed prefixes are free.
2. **`knowledge.situations` lacks `UNIQUE(situation_id, principal_id)`**; spec §2-A adds it, and every proposed `(…_id, principal_id) REFERENCES knowledge.situations` FK depends on it. Existing inbound Situation FKs are single-column.
3. **`project_situations` is not a live native authority.** Its only writer (`link_situation`) and `close_situation` are unreachable from any capability; no capability or read path touches the table (section 4). The spec (§0.3, CR-001, §10.1 `issues.project_links.*`) treats it as the authoritative, live Project↔Situation link with legacy consumers to compatibility-test; in repo truth there are none, and `continuity.situations.create` accepts no `project_id`. Production row content is unknown (no DB inspection).
4. **Situation emits no Record Event** — `RecordEventFamily` has no `situation` member; an Issue family requires a `record_family` CHECK change and admission, as spec §2.4 step 5 anticipates.
5. **Composite column order differs by table** (`commitments`/`tasks`/`project_constraints` are `(principal_id, id)`); spec SQL for those families must match.
6. **`capture_versions` has no composite `(version_id, capture_id, owner_principal_id)` unique and cascades on Capture delete**; a `capver_` evidence binding with `RESTRICT` (spec §2.1) needs a new unique and cannot rely on the existing FK's delete behaviour. The partition column is `owner_principal_id`, not `principal_id`.
7. **`asrt_` Work evidence is a capture assertion** (`capture_assertions`), not a Knowledge Assertion (`kasr_`); spec §2.1/CR-003 "Knowledge Assertion (read/evidence only)" is a different plane from today's accepted `asrt_`.
8. **`meetings.read` view omits `content_sha256`**; a client cannot obtain the stored digest today, so N1 evidence anchoring needs the proposed version read (CR-003) or server-side digest resolution.
9. **No common endpoint lock helper exists** (spec §2.1 "established lock helpers"): locking is per plane — `FOR UPDATE`/`FOR SHARE` in Meeting persistence (sorted Entity `FOR SHARE`), `pg_advisory_xact_lock` in `constraints.py:2851`, `identifier_claim_lock.py:39`, `entity_reenrichment.py:330`, `native_sources.py:571`. A lineage lock order must be designed, not reused.
10. **TRUNCATE refusal and role separation exist only for Record Events**; spec §2 "additional mandatory operations" requires both for every new immutable table — new work, modelled on `c8e4a1b70d35` and `record_event_roles.py`.
11. **`reports.types.*` exists in code** (DATA_REQUIRED); RV-CKPT-01/COORDINATION-RESPONSE say it is absent from the eligible live profile — consistent only with a pre-`a591b81f10a2` runtime (unverified).
12. **AT-026 Capture-provenance case is already covered** by an existing database test (section 4); the package's `NEW_PROPOSED_PATH tests/contract/test_record_event_provenance_scope.py` does not exist and would partly duplicate it.
13. **07 identifier pattern `^[a-z]+_[A-Za-z0-9]{8,64}$`** is looser than repo truth (closed `IdKind` prefix, 72-character cap).
14. Spec line anchors checked and matching at this commit: `situation.py:382-418`, `situation_repository.py:243-336`, `tables.py:3208-3239`, `3357-3395`, `7061-7130`, `13823-13900`, `unit_of_work.py:547-576`, `1193-`, `service.py:4390-4407`, `meetings.py:924-970`, `record_events.py:608-644`, `domain/record_events.py:130-162`, `authorization.py:769-`, `task.py:50`, `commitment.py:45`, `commands.py:3123`. Approximate: `situation_repository.py:670-730` (actual `link_situation` `:649-720`); `commands.py:12135-12180` (the internal `OpenSituationCommand`/`CloseSituationCommand` at `:12133`/`:12154`, not reachable by capability).

## 8. Commands run (worktree, foreground)

| Command | Result | Duration |
| --- | --- | --- |
| `PYTHONPATH=src ~/my-pa/.venv/bin/python -m alembic heads` / `branches` | single head `b9025e7fb738`; 3 branch points | <5 s |
| `PYTHONPATH=src … -c 'ScriptDirectory…'` | 118 revisions, base `5d75f23847c9` | <5 s |
| `~/my-pa/.venv/bin/python -m pytest -m migration_empty_to_head -q -p no:cacheprovider` (scratch PG 15.15, password-less loopback URLs) | 13 passed, 34817 deselected | 143.6 s |
| `… -m database -k "test_record_event_role_privileges or test_the_ledgers_are_append_only or test_a_write_request_completes_exactly_once or test_append_only_ledgers_refuse_update_and_delete or test_a_submission_completes_once_and_is_never_committed_reserved"` | 11 passed, 34819 deselected | 114.1 s |

These establish isolated PostgreSQL feasibility for G0 on PG 15; CI (PG 17) remains the
authority for the database tiers.

## 9. Not performed

Production/NAS database stamp, live gateway profile, deployed commit, live grant
inspection, raw `project_situations` row inspection, full FAST and database tiers.
