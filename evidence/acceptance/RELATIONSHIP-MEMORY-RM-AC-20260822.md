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
Every row names that test. A row that cannot be held by a test — because it is a
claim about process, or about the absence of code nobody wrote — is marked
`NOT_APPLICABLE` with the reason, rather than marked `PASS` on the strength of
being true. A criterion whose subject is presentation rather than data is marked
`BACKEND_ONLY` — the backend supplies the data and semantics the criterion
needs, and the presentation it describes belongs to the deferred frontend. A
criterion the code does not satisfy is marked `NOT_MET` and the row says exactly
what is missing; `BACKEND_ONLY` is not a place to park one, because a criterion
whose data the backend does not supply is not waiting on a frontend.

Nothing here is marked `PASS` on the strength of a docstring, and three rows
that were have been corrected: an independent reviewer deleted the constraints
two of them cited and watched the suite stay green, and found that the test the
third named did not exist.

**Every row whose evidence is `REV` describes a plane no composed build can
reach.** Nothing in `src/`, `apps/` or `ops/` writes
`relationship_memory_proposals` or `relationship_memory_proposal_evidence`; only
test fixtures do. The promotion path — three of the eight tables, the whole of
`infrastructure/persistence/relationship_memory_review.py`, three domain records
and the three-variant `ReviewRepository.cases` union — is implemented and tested
but has no producer, and `docs/specs/relationship-memory-v0.1.md` section 11
states what would have to exist for one and why it was built now. Those rows are
`PASS` about the behaviour of code that runs when a proposal exists, which is a
narrower claim than "promotion works in this product", and the rows that would
otherwise read as the wider claim say so individually below.

**The plane is also unreachable by composition, which is a different claim from
being unreachable for want of a producer.** `SqlAlchemyUnitOfWork` takes
`relationship_memory_enabled` and `_Reviews` consults it before querying the
memory tables and before routing a decision to them; `bootstrap.gateway` passes
the same `relationship_intelligence_enabled and relationship_memory_enabled`
conjunction that decides the eight capability names. The absent producer is a
fact about the rows and stops holding the day one is admitted; the switch is a
fact about the build and does not. Both are stated because either alone would
overstate what holds.

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
| RM-AC-005 models cannot create active memory without governed promotion | PASS | `MemoryAuthority` declares no `model_inference`/`unresolved_claim`; proposals live in their own table and never in `relationship_memories`; `REV`. Structural today by a second route as well: no producer writes a proposal, so no promotion can occur at all (spec §11) |
| RM-AC-006 sensitivity floors restricted_local, others private_local, cloud eligibility false | PASS | `classification_floor_for`, DB CHECKs `a_sensitivity_memory_is_at_least_restricted` and `a_memory_version_is_not_cloud_eligible`; `DOM`, `REPO`, `PRIV`. The CHECK was corrected before this row could be claimed: it read `classification <> 'private_local' OR memory_kind <> 'sensitivity'`, which named one forbidden value instead of a minimum and admitted `synthetic_test` — a rank *below* `private_local` that `satisfies_floor` refuses. `PRIV` now asks the server directly, at both ranks below the floor and at the floor itself |
| RM-AC-007 narrative immutable per version; correction appends and retains history | PASS | append-only trigger on `relationship_memory_versions`; `REPO` (raw UPDATE refused, prior text still readable) |
| RM-AC-008 optional observed/effective times without fabricating unknown dates | PASS | nullable moments, no defaulting anywhere; `DOM`, `CAP` |
| RM-AC-009 important_date partial values, never infers year or age | PASS | precision rules refuse a year on `month_day`; no age field exists; `DOM` |
| RM-AC-010 follow_up_context does not silently become a Task/Commitment | PASS | `REPO` records a `follow_up_context` memory and asserts the task, commitment and capture tables hold exactly the rows they held before |
| RM-AC-011 no automatic task, reminder, calendar or communication action | PASS | `REPO` counts the task, commitment and capture planes before and after a memory write and asserts they are unchanged. Stated as a bounded claim rather than a containment guard: it proves this write reaches no other plane, not that a future writer could not |
| RM-AC-012 context-scoped memory not presented as globally applicable | PASS | context links bound to the *version*; `relationship_memory.list` exposes `context_entity_id` filtering; `REPO`, `CAP` |
| RM-AC-013 restricted memory excluded from broad search/export/cloud by default | PASS | SQL predicate excludes `restricted_local` from search; cloud eligibility CHECKed false; `PRIV` |
| RM-AC-014 no restricted-existence disclosure via counts or term probing | PASS | exclusion is a predicate, so no count, cursor or truncation flag can carry one; `PRIV` (probing a restricted-only term returns nothing, zero withheld, no truncation) |
| RM-AC-015 accepted derived memory retains evidence sufficient to reveal its basis | PASS | promotion copies every `relationship_memory_proposal_evidence` row onto the accepted version; `REV`. No derived memory exists in a composed build, because no producer writes a proposal (spec §11) |
| RM-AC-016 model proposal records method/model identity and stays visibly proposed | PASS | `method`/`method_version`/`model_id`/`model_version` with a CHECK that a model proposal names its model; `REV`. No model proposal is produced by this build (spec §11) |
| RM-AC-017 protected-trait inference structurally prohibited from automated promotion | PASS | no trait field, no classifier, no taxonomy; `sensitivity` deliberately has no structured topic schema; `DOM` |
| RM-AC-018 merge erases no history and no silent write to a merged-away identity | PASS | `MergedSubjectError` carries the canonical target and the write is refused, never followed; `REPO`, `REV` |
| RM-AC-019 Overview can surface current eligible preferences, dates, interests, concerns, pinned context and sensitivities with authority distinction | PASS | `relationship_memory.list` returns every kind, pinned first, with `memory_id`, `subject_entity_id`, `kind`, **`authority`**, **`classification`**, `lifecycle`, `version`, `current_version_number`, `pinned`, `created_at`, `updated_at` and — when the caller asks — the statement. The two provenance fields are unconditional and `statement` is not: withholding the note is a caller's choice, withholding where it came from is not. The authority distinction is asserted where it can actually be exercised, on two memories that differ in nothing else: `REV::test_a_listing_tells_a_promoted_assertion_apart_from_the_users_own_note` puts a reviewer-promoted `source_backed_assertion` and a `user_authored_private_note` on one subject, one kind, both unpinned, and asserts the two authorities differ through `page_for_entity` *and* `search`; `CAP::test_the_assistants_listing_tells_a_promoted_finding_from_the_users_own_note` makes the same claim through `ApplicationService.invoke` against a real database, which is the surface an assistant reads. `REPO::test_both_listing_reads_carry_the_current_versions_authority_and_classification` binds the two rendered values to the version's own, and `CAP::test_withholding_the_statement_still_states_where_the_memory_came_from` holds them present under `include_statement=False`. Carried as one `MemoryListingFacts` per memory rather than as parallel mappings, so statement, authority and classification cannot drift apart; `MemoryPage.__post_init__` requires exactly one record per disclosed memory, and `REPO::test_a_withheld_memory_leaves_no_facts_record_behind` proves a withheld restricted memory leaves none. This row previously read `PASS` on a claim that was false, then `NOT_MET`; the third state is the first one that a test fails if it stops holding. Mutation-checked: dropping `"authority"` from `_memory_summary_view` reddens four tests, and hard-coding the authority in `_page` reddens the two that name the distinction |
| RM-AC-020 bounded, paginated, history-aware retrieval for one Entity | PASS | `relationship_memory.list` + `.history`, keyset paginated over the whole sort key; `REPO`, `CAP` |
| RM-AC-021 editing exposes prior versions according to policy | PASS | `relationship_memory.history`; `REPO`, `CAP` |
| RM-AC-022 Quick Capture can be evidence without becoming the memory | PASS | `REV` promotes a proposal whose only evidence is capture spans and asserts they land in `capture_span_id` on the accepted version — not in the observation column, which would make a capture indistinguishable from a source observation. The exclusive-target CHECK is asked of the server directly in both `REPO` and `REV`, in the naming-two and naming-none directions |
| RM-AC-023 direct note entry requires no hidden Capture | PASS | `relationship_memory.create` writes no capture row; `CAP` |
| RM-AC-024 `EntityObservation` not overloaded as the memory store | PASS | separate tables and separate domain module; `SCHEMA` |
| RM-AC-025 legacy `RelationshipEvent(OBSERVATION)` remains projection, not canonical store | NOT_APPLICABLE | this branch adds no projection and writes nothing to `relationship_events`. The criterion is satisfied by absence, which no test can assert without asserting a negative over the whole tree |
| RM-AC-026 Principal isolation on every path; fail closed on cross-Principal | PASS | `REPO` covers all four reads — `detail`, `history`, `page_for_entity` and `search` — each asserting a foreign answer *equal* to an absent one, and a cross-Principal write refused before any row. The architecture guard registers both persistence modules at module level, which proves they reach `principal_scope` and does **not** prove it per statement; the four read tests are what hold the predicates in place, and a reviewer demonstrated that by deleting one and watching them redden |
| RM-AC-027 audit/error/telemetry carry no raw memory text | PASS | `AuditEvent` has no free-text field; `SafeDetail` names fields only; `PRIV` plants a marker in the statement and asserts it reaches no audit column |
| RM-AC-028 no hard-delete capability | PASS | no such capability, no such repository method, no such lifecycle member; `CAP` |
| RM-AC-029 `entities.context` inclusion bounded, discloses truncation/withholding | PASS | four distinct limitations; `CARD` proves all four are pairwise distinguishable |
| RM-AC-030 implementation status never inferred from the target contract | NOT_APPLICABLE | a process criterion about how the work was conducted, not a property of the code. `docs/specs/relationship-memory-v0.1.md` records implemented truth separately from the package; repository identity was reauthenticated at `a1beef75` before any edit |

## Persistence — `RM-P-AC-001` … `RM-P-AC-020`

| Criterion | Status | Evidence |
|---|---|---|
| RM-P-AC-001 no narrative on the Entity row | PASS | `entities` untouched; `relationship_memories` holds no text column; `SCHEMA` |
| RM-P-AC-002 one stable memory, one immutable chain, one current pointer | PASS | `current_version_id` + `one_version_number_per_memory` + unique `prior_version_id`; `REPO` |
| RM-P-AC-003 historical text never updated in place | PASS | `BEFORE UPDATE OR DELETE` trigger; `REPO` |
| RM-P-AC-004 every row Principal-scoped; cross-Principal refused before persistence | PASS | `REPO`, plus the partition architecture guard |
| RM-P-AC-005 kind/classification/authority/lifecycle closed and DB-checked | PASS | eighteen frozen closed sets in `f1c6b904a2d7`; `SCHEMA` |
| RM-P-AC-006 sensitivity cannot persist below restricted_local | PASS | CHECKs `a_sensitivity_memory_is_at_least_restricted` and `a_sensitivity_proposal_is_at_least_restricted`, both now expressing the floor as `kind <> 'sensitivity' OR classification = 'restricted_local'`; `DOM`, `REPO`, `PRIV` (raw INSERT at `synthetic_test` and `private_local` refused on both tables, `restricted_local` admitted). Neither is one of the eighteen frozen closed sets, correctly: a frozen set is a vocabulary and these are conditional pairing rules between two columns, so `f1c6b904a2d7` emits whatever `tables.py` states and the correction reaches a fresh database |
| RM-P-AC-007 direct user entry cannot claim source-backed/public/model authority | PASS | the fields do not exist on the command; CHECK `a_user_written_memory_version_is_user_authored`; `CAP` |
| RM-P-AC-008 model/unresolved proposal cannot appear as active memory without promotion | PASS | proposals are a separate table; `REV` proves invisibility before acceptance. Nothing produces a proposal in a composed build, so the promotion route is unreachable rather than merely governed (spec §11) |
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
| RM-P-AC-020 no new database or service technology | PASS | `tests/architecture/test_no_vector_retrieval_exists` and `test_scope_and_hygiene` both scan for a second store or driver; the branch adds no dependency (`pyproject.toml` unchanged) |

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
| RM-API-AC-011 review promotion separate from direct authoring | PASS | `REV`. Separate *and* dormant, now for two independent reasons rather than one. The first is the data: no producer writes a proposal, so there is nothing for `review.list` to surface (spec §11) — true, but a fact about rows rather than about the build, and it stops holding the day a producer is admitted. The second is the composition: `SqlAlchemyUnitOfWork` takes `relationship_memory_enabled` and `_Reviews` skips the memory query and the memory branch of the decide router unless it is set, which `bootstrap.gateway` sets from the same `relationship_intelligence_enabled and relationship_memory_enabled` conjunction that gates the eight capability names. `REV::test_a_build_without_the_memory_plane_composed_never_reaches_a_memory_case` puts a real proposal, its evidence and its review case in the database and asserts an uncomposed unit of work discloses no case while a composed one discloses it, so the empty answer is the composition and not the fixture. Before this change the review plane was reached unconditionally, and `review.list` in a build that had never enabled the plane would have disclosed a memory case's `subject_entity_id` and `proposed_kind` |
| RM-API-AC-012 proposals absent from ordinary reads before acceptance | PASS | `REV`. In a composed build there are no proposals to be absent, because none is produced (spec §11) |
| RM-API-AC-013 `entities.context` bounded and advertises truncation/withholding | PASS | `CARD` |
| RM-API-AC-014 Quick Capture entity linkage cannot guess identity from a name | PASS | a name is refused as an `entity_id` at the transport boundary; no name-to-entity resolution exists on any memory or capture write path; `CAP` |
| RM-API-AC-015 local MCP, remote MCP and HTTP share one application path | PASS | one `_BUILDERS` table and one `ApplicationService.invoke`; `PAR` asserts all three answer identically |
| RM-API-AC-016 remote writes require explicit grants and gates beyond authentication | PASS | `relationship_memory_authoring` is in `_WRITE_PURPOSES`, so `remote_tool_names` withholds the four writes until remote writes are enabled; `CAP` asserts the profile with writes disabled and enabled |
| RM-API-AC-017 error/audit surfaces never disclose raw memory text | PASS | `PRIV`, `NEG` |
| RM-API-AC-018 feature unavailability explicit | PASS | withheld from the manifest and the tool list, and refused `unsupported` at a per-handler floor; `CAP`. The *shared* Review surface is now withheld on the same switch, which is where unavailability had a hole: `review.list` and `review.decide` are capabilities of the capture plane and stay published, so they could not be withheld — instead the memory plane is not reached from them unless it is composed, and a decision naming a memory case in an uncomposed build raises the identical `ReviewNotFoundError` an invented identifier raises. `REV::test_deciding_a_memory_case_in_an_uncomposed_build_answers_as_an_absent_one` asserts that as an equality of the two refusals and counts the four promotion tables before and after, because "it refused" and "it wrote nothing" are different claims |

## Deferred, and named rather than implied

`RM-FE-AC-001` … `RM-FE-AC-022` (frontend) are out of scope by operator
instruction and are **not** claimed. Also outside this objective and unbuilt:
retention and hard deletion, multi-user or delegated visibility, reminder rules
over important dates, memory redistribution after an identity split, and any
widening of cloud eligibility.

Three context-link target types — `situation`, `task` and `commitment` — are declared
in the closed vocabulary and refused by the repository, which validates only
`entity` targets. That is narrower than the contract's candidate set on purpose:
this plane holds no port into those partitions, and admitting a link whose
ownership it cannot prove would be the unvalidated polymorphic edge the
vocabulary exists to prevent. Admitting them later is a repository change, not a
migration.
