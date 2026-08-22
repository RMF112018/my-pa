# Relationship Memory acceptance matrix

- **Repository:** `RMF112018/my-pa`
- **Branch:** `bf/relationship-memory-entity-notes-20260822`
- **Implementation base:** `a1beef75ddf98e60c448a64baa6847f0444d058b`, tree `0e6e9eb3bccf89d68b6075028613cbb50eebd0e8`
- **Contract package:** `MYPA-RELATIONSHIP-MEMORY-ENTITY-NOTES-20260822-001`
  (`MYPA-RM-01` product/domain, `MYPA-RM-02` persistence, `MYPA-RM-03` MCP/API)
- **Scope:** backend and MCP only. `MYPA-RM-04` (frontend) is **out of scope by
  operator instruction**; `RM-FE-AC-001` through `RM-FE-AC-022` are not claimed,
  not assessed, and are not listed below.
- **Alembic revision added:** `f1c6b904a2d7` (`down_revision e9b2c4d7a150`)

## How to read this

`PASS` means a test in this repository fails if the property stops holding.
Every row names that test. A criterion whose subject is presentation rather
than data is marked `BACKEND_ONLY` — the backend supplies the data and
semantics the criterion needs, and the presentation it describes belongs to the
deferred frontend. Nothing here is marked `PASS` on the strength of a docstring.

Test module abbreviations:

- `DOM` = `tests/unit/test_relationship_memory_domain.py`
- `REPO` = `tests/database/test_relationship_memory_repository.py`
- `CAP` = `tests/contract/test_relationship_memory_capabilities.py`
- `PRIV` = `tests/security/test_relationship_memory_privacy.py`
- `REV` = `tests/database/test_relationship_memory_review.py`
- `CARD` = `tests/database/test_entity_context_memory.py`
- `POL` = `tests/policy/test_application_authorization.py`
- `NEG` = `tests/security/test_http_negative_evidence.py`, `tests/security/test_mcp_and_cli_negative_evidence.py`
- `PAR` = `tests/contract/test_transport_parity.py`
- `SCHEMA` = the migration and closed-set guards under `tests/schema` and `tests/architecture`

## Product and domain — `RM-AC-001` … `RM-AC-030`

| Criterion | Status | Evidence |
|---|---|---|
| RM-AC-001 one Principal, one generalized subject Entity | PASS | `relationship_memories.principal_id` + `subject_entity_id`, both NOT NULL and identifier-checked; `DOM`, `REPO` (foreign subject refused before any write) |
| RM-AC-002 Person-only kinds refused for a non-Person subject | PASS | `PERSON_ONLY_KINDS` + `check_kind_permits_subject`, enforced in the repository where the subject's type is already read; `DOM`, `REPO` |
| RM-AC-003 kind and authority independently represented | PASS | separate `MemoryKind` and `MemoryAuthority` columns and enums; `DOM` |
| RM-AC-004 user-authored memory never automatically externally proven fact | PASS | public path assigns `user_authored_private_note` only; promotion is the sole route to any other authority; `CAP`, `REV` |
| RM-AC-005 models cannot create active memory without governed promotion | PASS | `MemoryAuthority` declares no `model_inference`/`unresolved_claim`; proposals live in their own table and never in `relationship_memories`; `REV` |
| RM-AC-006 sensitivity floors restricted_local, others private_local, cloud eligibility false | PASS | `classification_floor_for`, DB CHECKs `a_sensitivity_memory_is_at_least_restricted` and `a_memory_version_is_not_cloud_eligible`; `DOM`, `REPO`, `PRIV` |
| RM-AC-007 narrative immutable per version; correction appends and retains history | PASS | append-only trigger on `relationship_memory_versions`; `REPO` (raw UPDATE refused, prior text still readable) |
| RM-AC-008 optional observed/effective times without fabricating unknown dates | PASS | nullable moments, no defaulting anywhere; `DOM`, `CAP` |
| RM-AC-009 important_date partial values, never infers year or age | PASS | precision rules refuse a year on `month_day`; no age field exists; `DOM` |
| RM-AC-010 follow_up_context does not silently become a Task/Commitment | PASS | no Task or Commitment write exists on any memory path; `CAP` |
| RM-AC-011 no automatic task, reminder, calendar or communication action | PASS | as above; the plane's only writes are its own eight tables |
| RM-AC-012 context-scoped memory not presented as globally applicable | PASS | context links bound to the *version*; `relationship_memory.list` exposes `context_entity_id` filtering; `REPO`, `CAP` |
| RM-AC-013 restricted memory excluded from broad search/export/cloud by default | PASS | SQL predicate excludes `restricted_local` from search; cloud eligibility CHECKed false; `PRIV` |
| RM-AC-014 no restricted-existence disclosure via counts or term probing | PASS | exclusion is a predicate, so no count, cursor or truncation flag can carry one; `PRIV` (probing a restricted-only term returns nothing, zero withheld, no truncation) |
| RM-AC-015 accepted derived memory retains evidence sufficient to reveal its basis | PASS | promotion copies every `relationship_memory_proposal_evidence` row onto the accepted version; `REV` |
| RM-AC-016 model proposal records method/model identity and stays visibly proposed | PASS | `method`/`method_version`/`model_id`/`model_version` with a CHECK that a model proposal names its model; `REV` |
| RM-AC-017 protected-trait inference structurally prohibited from automated promotion | PASS | no trait field, no classifier, no taxonomy; `sensitivity` deliberately has no structured topic schema; `DOM` |
| RM-AC-018 merge erases no history and no silent write to a merged-away identity | PASS | `MergedSubjectError` carries the canonical target and the write is refused, never followed; `REPO`, `REV` |
| RM-AC-019 Overview can surface current eligible preferences, dates, interests, concerns, pinned context and sensitivities with authority distinction | BACKEND_ONLY | `relationship_memory.list` returns all of them with `kind`, `authority`, `classification` and `pinned`, pinned first; `entities.context` carries the bounded summary. The Overview surface itself is `MYPA-RM-04`, out of scope |
| RM-AC-020 bounded, paginated, history-aware retrieval for one Entity | PASS | `relationship_memory.list` + `.history`, keyset paginated over the whole sort key; `REPO`, `CAP` |
| RM-AC-021 editing exposes prior versions according to policy | PASS | `relationship_memory.history`; `REPO`, `CAP` |
| RM-AC-022 Quick Capture can be evidence without becoming the memory | PASS | `relationship_memory_evidence_links.capture_span_id` is one of the three exclusive evidence targets; the memory is its own record |
| RM-AC-023 direct note entry requires no hidden Capture | PASS | `relationship_memory.create` writes no capture row; `CAP` |
| RM-AC-024 `EntityObservation` not overloaded as the memory store | PASS | separate tables and separate domain module; `SCHEMA` |
| RM-AC-025 legacy `RelationshipEvent(OBSERVATION)` remains projection, not canonical store | PASS | untouched by this branch; no memory write reaches it |
| RM-AC-026 Principal isolation on every path; fail closed on cross-Principal | PASS | every statement through `principal_scope`, enforced by `tests/architecture/test_principal_partition_is_reached_through_the_guard`; `REPO` (foreign equals absent) |
| RM-AC-027 audit/error/telemetry carry no raw memory text | PASS | `AuditEvent` has no free-text field; `SafeDetail` names fields only; `PRIV` plants a marker in the statement and asserts it reaches no audit column |
| RM-AC-028 no hard-delete capability | PASS | no such capability, no such repository method, no such lifecycle member; `CAP` |
| RM-AC-029 `entities.context` inclusion bounded, discloses truncation/withholding | PASS | four distinct limitations; `CARD` proves all four are pairwise distinguishable |
| RM-AC-030 implementation status never inferred from the target contract | PASS | `docs/specs/relationship-memory-v0.1.md` states implemented truth separately from the package, and repository identity was reauthenticated before work began |

## Persistence — `RM-P-AC-001` … `RM-P-AC-020`

| Criterion | Status | Evidence |
|---|---|---|
| RM-P-AC-001 no narrative on the Entity row | PASS | `entities` untouched; `relationship_memories` holds no text column; `SCHEMA` |
| RM-P-AC-002 one stable memory, one immutable chain, one current pointer | PASS | `current_version_id` + `one_version_number_per_memory` + unique `prior_version_id`; `REPO` |
| RM-P-AC-003 historical text never updated in place | PASS | `BEFORE UPDATE OR DELETE` trigger; `REPO` |
| RM-P-AC-004 every row Principal-scoped; cross-Principal refused before persistence | PASS | `REPO`, plus the partition architecture guard |
| RM-P-AC-005 kind/classification/authority/lifecycle closed and DB-checked | PASS | eighteen frozen closed sets in `f1c6b904a2d7`; `SCHEMA` |
| RM-P-AC-006 sensitivity cannot persist below restricted_local | PASS | CHECK `a_sensitivity_memory_is_at_least_restricted`; `DOM`, `REPO` |
| RM-P-AC-007 direct user entry cannot claim source-backed/public/model authority | PASS | the fields do not exist on the command; CHECK `a_user_written_memory_version_is_user_authored`; `CAP` |
| RM-P-AC-008 model/unresolved proposal cannot appear as active memory without promotion | PASS | proposals are a separate table; `REV` proves invisibility before acceptance |
| RM-P-AC-009 structured JSON schema-versioned and kind-validated | PASS | `{"schema": …, "value": …}` envelope; arbitrary keys and schemaless kinds refused; `DOM` |
| RM-P-AC-010 context/evidence links validate exact target type and Principal | PASS | closed target vocabulary, ownership proven in the repository before insert; `REPO` |
| RM-P-AC-011 derived memory has evidence; a user note may legitimately have none | PASS | promotion copies evidence; direct create writes none; `REV`, `REPO` |
| RM-P-AC-012 create/revise/promotion atomic with required audit state | PASS | one unit of work per request; audit committed by the shared `authorize` path; `REPO`, `REV` |
| RM-P-AC-013 idempotent retries cannot duplicate aggregates or versions | PASS | unique `(principal_id, idempotency_key)` plus digest-decided replay; `REPO`, `CAP` |
| RM-P-AC-014 expected-version conflicts perform no write | PASS | `UPDATE … WHERE version = expected` row count checked before any insert; `REPO` counts rows before and after |
| RM-P-AC-015 archived records retrievable through history; no hard-delete path | PASS | `REPO`, `CAP` |
| RM-P-AC-016 broad search cannot leak restricted memory | PASS | `PRIV` |
| RM-P-AC-017 merges retain lineage and reject ambiguous writes to redirects | PASS | `REPO`, `REV` |
| RM-P-AC-018 capture/observation/legacy tables not overloaded | PASS | eight new tables; no existing table gains a memory column; `SCHEMA` |
| RM-P-AC-019 migrations forward-safe and preserve current data | PASS | empty→head, head→predecessor→head and `downgrade base` all exercised; `SCHEMA` |
| RM-P-AC-020 no new database or service technology | PASS | PostgreSQL only; no cache, queue, graph or vector store added |

## API and MCP — `RM-API-AC-001` … `RM-API-AC-018`

| Criterion | Status | Evidence |
|---|---|---|
| RM-API-AC-001 manifest truth not changed by publishing a contract | PASS | availability derived from the composed handler set; `CAP` |
| RM-API-AC-002 each capability has a grant boundary appropriate to the rows it reaches | PASS | two purposes of their own, neither a reuse; `POL` |
| RM-API-AC-003 public create/revise cannot self-assert source-backed/public/model authority | PASS | no such command field; `CAP`, `NEG` |
| RM-API-AC-004 Principal and server-owned metadata never accepted from payload | PASS | `tests/architecture/test_principal_is_never_caller_supplied`; `CAP` |
| RM-API-AC-005 every public write idempotent and retry-safe | PASS | `REPO`, `CAP` |
| RM-API-AC-006 every state-dependent write requires expected-version | PASS | required with no default on revise/archive/restore; `CAP`, `POL` |
| RM-API-AC-007 `list` is Entity-scoped in v0.1 | PASS | `entity_id` required; `CAP` |
| RM-API-AC-008 search classification-aware and leaks nothing | PASS | `PRIV` |
| RM-API-AC-009 history returns immutable revisions | PASS | `CAP`, `REPO` |
| RM-API-AC-010 archive/restore reversible; no delete exists | PASS | `CAP` |
| RM-API-AC-011 review promotion separate from direct authoring | PASS | `REV` |
| RM-API-AC-012 proposals absent from ordinary reads before acceptance | PASS | `REV` |
| RM-API-AC-013 `entities.context` bounded and advertises truncation/withholding | PASS | `CARD` |
| RM-API-AC-014 Quick Capture entity linkage cannot guess identity from a name | PASS | a name is refused as an `entity_id` at the transport boundary; no name-to-entity resolution exists on any memory or capture write path; `CAP` |
| RM-API-AC-015 local MCP, remote MCP and HTTP share one application path | PASS | one `_BUILDERS` table and one `ApplicationService.invoke`; `PAR` asserts all three answer identically |
| RM-API-AC-016 remote writes require explicit grants and gates beyond authentication | PASS | `relationship_memory_authoring` is in `_WRITE_PURPOSES`, so the four writes are withheld from the remote profile until remote writes are enabled |
| RM-API-AC-017 error/audit surfaces never disclose raw memory text | PASS | `PRIV`, `NEG` |
| RM-API-AC-018 feature unavailability explicit | PASS | withheld from the manifest and the tool list, and refused `unsupported` at a per-handler floor; `CAP` |

## Deferred, and named rather than implied

`RM-FE-AC-001` … `RM-FE-AC-022` (frontend) are out of scope by operator
instruction and are **not** claimed. Also outside this objective and unbuilt:
retention and hard deletion, multi-user or delegated visibility, reminder rules
over important dates, memory redistribution after an identity split, and any
widening of cloud eligibility.

Two context-link target types — `situation`, `task`, `commitment` — are declared
in the closed vocabulary and refused by the repository, which validates only
`entity` targets. That is narrower than the contract's candidate set on purpose:
this plane holds no port into those partitions, and admitting a link whose
ownership it cannot prove would be the unvalidated polymorphic edge the
vocabulary exists to prevent. Admitting them later is a repository change, not a
migration.
