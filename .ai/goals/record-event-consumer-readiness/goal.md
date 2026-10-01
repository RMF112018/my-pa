# Goal: Record Event Consumer Readiness (RECR-1..5)

## Identity

- Goal ID: `record-event-consumer-readiness`
- Request: `MYPA-RECORD-EVENT-CONSUMER-READINESS-20261001-001` (follow-up to PR #297, merged by the operator as `17487662`)
- Authorization: issued 2026-10-01 by the operator in session 257acc32 ("proceed with the most effective path forward, do not stop until the update is complete and merged"), SHA-256 `c1795319e9673e2d3b2be6b8f6630d7ac21acb0047ba3330f2dbbbd8024845ec`
- Approved plan: `RECR-PLAN.md`, SHA-256 `e1a545c4a7977b29c80d719c0257ad3e5465cec039ff5d5a0d0ee3a2b0bb9d04`, Drive file `1QfApsSyALgwSgNjvW2ClISNsGyIDzgzu` (readback MATCH; manifest `1DB8QCwW5D30IGigFMuuV5UDik06wAROs`, receipt `1VnCZtzqRrAG_5SSPyhWw2Ftqkvkrzta5`)
- Manager rulings: MR-R01..R11 (below)
- Repository: `RMF112018/my-pa`
- Branch: `bf/record-event-consumer-readiness-20261001`
- Worktree: `/Users/bobbyfetting/my-pa-wt/record-event-consumer-readiness`
- Base: `origin/main` `174876621c880312ee3f4e32f649520fab04aa9d`, tree `3679b51ba96922814283c0588bd8765f2a47bddc`
- Head / PR: recorded per checkpoint below
- Evidence Drive folder: `CONSUMER-READINESS` `1J_8ya7b9A7FlD3qNHCGOYPCKh2cj3s3I`

## Objective and scope

Make the Record Event feed (`record_events.list`) consumable by an external consumer, on one branch and one PR. Terminal state: **PR ready for review, NOT MERGED**; the operator performs the merge.

- **RECR-1, resolvable-event invariant.** Every listed event is independently resolvable, from the event alone and under the caller's normal grants, to its current canonical record or aggregate. Delivered as two metadata-only routing fields (`routing_family`, `routing_record_id`) on the twelve families whose `record_id` is not a direct read key, computed at read time (Option R).
- **RECR-2, bootstrap protocol.** A documented no-gap initialization (W0, snapshot through existing reads, process, delta after W0), with a DB test. No synthetic historical events.
- **RECR-3, cursor hardening (Gate-2 finding F-3).** Cursor position resolution applies the page's visibility predicate: the effective families, plus the remote withholding of restricted Relationship Memory and Capture events. A hand-built cursor around a hidden event is refused, consistent with the U-002 decode order.
- **RECR-4, causal-provenance contract.** A design record only (`docs/specs`, status "Proposed / not implemented").
- **RECR-5, governance record repair.** The pre-merge review PASS of PR #297 and its operator merge are recorded in `.ai/goals/record-event-changefeed/goal.md`.
- Scope: only the plan g.2 ownership list (Option R), plus this file, plus mechanical consequences recorded per checkpoint.

## Prohibitions

No agent-performed merge; no deploy, NAS or production action; no live grant, profile, config or credential change; no live DB write; no weakening, renumbering or deselection of any existing RE-AC or test; no synthetic backfill; no Abacus consumer or writeback plane; no second PR; no edits to PR #287 or any other branch; never touch `~/my-pa`. At most one Alembic revision, and none under Option R. Stop conditions: the authorization's, plus plan g.4.

## Execution topology (AGENTS.md §8.3)

Manager → one Orchestrator → workers; at most one Orchestrator and one worker active at any moment (reviewers count as workers); Phase I CP-RECR-01..05 run serially on one opus implementer; foreground, chunked tests; single-guard prove-reds; same-head re-runs for flakes.

## Manager rulings (received 2026-10-01)

- **MR-R01 (D-1): Option R.** Routing is computed at read time inside the single page statement, from owner key columns only. It stays ONE statement (page + watermark), with no new lock. An EXPLAIN check on the local DB must show the owner lookups use indexes, and is recorded. Routing reflects the CURRENT owner (correct for "current canonical aggregate"), and that is documented.
- **MR-R02 (D-2):** keep node id `test_the_public_item_carries_exactly_its_thirteen_fields`, update its asserted set to 15, and add a comment explaining the name. No renumbering.
- **MR-R03 (D-3):** apply the full predicates. Document the re-bootstrap consequence in the consumer contract.
- **MR-R04 (D-4):** no floor for `task_comment`; recorded as an amendment to the OD-W8-1(i) premise (below).
- **MR-R05 (D-5):** documented residuals, with conditions:
  - (i) affiliation events route to the **person** side; document the residual where an entity has more than 25 affiliations;
  - (ii) an orphaned observation (null owner) gets routing `null`; the consumer contract defines null routing as "not currently resolvable; treat as a tombstone"; a test proves it;
  - (iii) R-G is documented as a consumer-grant requirement;
  - (iv) "paginated affiliation read capability" is a follow-up candidate (below). No new Capability in this PR.
- **MR-R06 (D-6):** Entity bootstrap traverses references from the enumerable roots (projects, tasks, commitments, constraints, meetings, memories, captures). The coverage limit is documented, and "entity enumeration read" is a follow-up candidate (below).
- **MR-R07 (D-7):** the consumer contract and the causal-provenance record are specs under `docs/specs`, not ADRs.
- **MR-R08 (D-8):** two routing fields, `routing_family` and `routing_record_id`.
- **MR-R09 (D-9):** keys-only guard: each of the 12 routing tables may be read for its key and owner columns only, with a single-guard prove-red (selecting a payload column turns it red). Check whether any guard-parsed claim document states the feed reader's reach; if one does, add a dated paragraph without changing existing text (MR-12 precedent).
- **MR-R10 (D-10):** operator item. PR #287 is left untouched. The contended count cells are re-derived at each integration.
- **MR-R11 (D-11):** RECR-5 replaces only the final `Pending.` section of `.ai/goals/record-event-changefeed/goal.md`; its history rows stay as written.
- **MR-R12 (CP-RECR-01 guard, 2026-10-01): WITHDRAWN** (superseded by MR-R13). It had authorized a mechanical edit to `tests/architecture/test_every_capability_reaching_a_memory_row_is_declared.py` adding `resolve_position` to the `RecordEventReader` crossing set, on condition of a claim-document check. That edit is reverted byte-exact to `17487662`.
- **MR-R13 (CP-RECR-01 redesign, 2026-10-01): supersedes MR-R12.** The security guard stays UNCHANGED. RECR-3 is redesigned at the application layer: after the shape check and the binding compare (U-002 order unchanged), the anchor `e` must be in `reader.visible_event_ids(principal_id, {e}, effective families, include_restricted_memory)` (the existing probe, which already applies the full `_visible` predicate and is one of the two reads the guard permits); otherwise `invalid_request(cursor)`, the same refusal as an unresolvable anchor. Only then is `resolve_position` called, in its original partition-and-id-only form. RECR-AC-020/021/022 are confirmed.
- Proceed: Phase I CP-RECR-01..05 serially on ONE opus implementer; draft PR after CP-RECR-01 is green, titled `feat(record-events): consumer readiness — resolvable routing, bootstrap contract, cursor hardening`; report after each checkpoint; then Phase T to an independent PASS and green CI at the same head, with no later commits. Do NOT mark ready; do NOT merge.

### MR-R04 amendment of the OD-W8-1(i) premise

OD-W8-1(i) ruled that `task_comment` takes no Entity-style floor, on the premise that "a comment event names no Task field". Under RECR-1 a `task_comment` event carries `routing_record_id` = its Task. The ruling stands (no floor), and the premise is amended: the Task id is a field the comment's own read `tasks.comments.list` already discloses (`TASK_COMMENT_CREATED_FIELDS` names `task_id`), so routing discloses nothing that read does not.

### Follow-up candidates (not in this PR)

- **"paginated affiliation read capability"** (MR-R05 iv): cures residual R-1, an affiliation past the 25th of its person's `entities.profile` collection, which no read can reach.
- **"entity enumeration read"** (MR-R06): an unfiltered Entity enumeration, so the Entity plane can be bootstrapped beyond the references reachable from the enumerable roots.

## Acceptance criteria (RECR-AC)

| ID | Criterion | Proving test | Checkpoint |
|---|---|---|---|
| RECR-AC-001 | `RECORD_EVENT_ROUTING` has exactly 12 rows (`task_comment→task`, `constraint_category→project`, the ten Entity floor families→`entity`); its complement is the 10 direct families | `tests/unit/test_record_event_routing.py::test_the_routing_table_is_the_twelve_rows_written_out` | CP-RECR-02 |
| RECR-AC-002 | Every routed family's routing kind is the lookup key of one of its mapped reads; every direct family has a read keyed by `record_id`'s kind | `tests/unit/test_record_event_routing.py::test_every_family_has_a_read_keyed_by_its_record_or_routing_id` | CP-RECR-02 |
| RECR-AC-003 | End to end, for each of the 22 families, the documented read with `record_id` or `routing_record_id` returns the record; exceptions only R-1 and R-2, asserted as documented | `tests/database/test_record_event_routing.py::test_every_family_resolves_from_the_event_alone` | CP-RECR-02 |
| RECR-AC-004 | Routing names the current owner after an Entity merge | `tests/database/test_record_event_routing.py::test_routing_follows_a_merge_to_the_survivor` | CP-RECR-02 |
| RECR-AC-005 | Routing obeys the event's grant intersection and withholding | `tests/database/test_record_event_routing.py::test_remote_routing_is_the_events_own_visibility` | CP-RECR-02 |
| RECR-AC-006 | The reader's routing reach is keys only; a planted wider read is reported | `tests/security/test_record_events_carry_no_payload.py::test_the_feed_reader_routing_reads_only_keys`, `::test_the_routing_reach_scan_sees_a_wider_read` | CP-RECR-02 |
| RECR-AC-007 | Item contract: both routing fields or neither; only on a routed family; kind matches `RECORD_EVENT_ROUTING`; opaque-id shape | `tests/contract/test_record_events_list.py::test_routing_fields_are_validated` | CP-RECR-02 |
| RECR-AC-008 | Page and routing come from one statement | `tests/database/test_record_event_routing.py::test_routing_is_read_by_the_page_statement` | CP-RECR-02 |
| RECR-AC-009 | Bootstrap: a write in flight at W0 is seen by the delta | `tests/database/test_record_events_consumer_bootstrap.py::test_a_write_in_flight_at_w0_is_seen_by_the_delta` | CP-RECR-03 |
| RECR-AC-010 | Bootstrap: a write committed between W0 and the snapshot is seen by both, applied idempotently | `…::test_a_write_committed_between_w0_and_the_snapshot_is_seen_by_both` | CP-RECR-03 |
| RECR-AC-011 | Bootstrap: a write committed during enumeration is seen by the delta; each event after W0 consumed once | `…::test_a_write_committed_during_snapshot_enumeration_is_seen_by_the_delta` | CP-RECR-03 |
| RECR-AC-012 | A hand-built cursor anchored outside the effective families is `invalid_request(cursor)` | `tests/database/test_record_events_cursor_visibility.py::test_a_hand_built_cursor_on_an_ungranted_family_event_is_refused`, `::test_a_hand_built_cursor_outside_the_requested_narrowing_is_refused` | CP-RECR-01 |
| RECR-AC-013 | A remote hand-built cursor anchored on a withheld memory or capture event is `invalid_request(cursor)`; a local one resumes | `…::test_a_hand_built_cursor_on_a_withheld_memory_event_is_refused`, `…::test_a_hand_built_cursor_on_a_withheld_capture_event_is_refused`, `…::test_a_local_caller_still_resumes_after_a_restricted_event` | CP-RECR-01 |
| RECR-AC-014 | U-002 order preserved: a wrong binding on a hidden anchor is `conflict(cursor)` with no lookup; the position resolves under exactly the effective families and disclosure | `…::test_a_wrong_binding_on_a_hidden_anchor_is_still_a_conflict`; `tests/security/test_record_events_grant_narrowing.py::test_the_position_is_resolved_under_the_effective_families_and_disclosure` | CP-RECR-01 |
| RECR-AC-015 | The consumer contract is documented (routing guide, bootstrap, recovery, residuals R-1/R-2/R-G); §15 no longer says a comment event cannot name its Task | documentation; FAST doc guards | CP-RECR-03 |
| RECR-AC-016 | The causal-provenance design record exists and is marked not implemented | documentation; FAST doc guards | CP-RECR-04 |
| RECR-AC-017 | The record-event-changefeed ledger records the pre-merge review PASS at `806a3c90` (2026-10-01T03:27Z, Drive `1OuWrO8WVh1RuRXnk1nWnYTkOdc_mvDGJ`) and the operator merge `17487662` | review of the diff | CP-RECR-01 |
| RECR-AC-018 | No existing RE-AC or test is weakened, renumbered or deselected; only declared pins change; full lanes green at the exact head | lanes + evidence map + independent review | CP-RECR-05 |
| RECR-AC-019 | Independent exact-head review PASS plus required CI green at the same head, with no later commits | review artifact + `gh run view` | terminal |
| RECR-AC-020 | (MR-R05 ii) An orphaned observation event (owner NULL) lists with `routing_family` and `routing_record_id` both null | `tests/database/test_record_event_routing.py` | CP-RECR-02 |
| RECR-AC-021 | (MR-R05 i) Affiliation events route to the person entity, asserted explicitly | RECR-AC-001/003 rows | CP-RECR-02 |
| RECR-AC-022 | (MR-R01) EXPLAIN evidence that every routing owner lookup uses an index, recorded under `evidence/` in the manager directory (untracked) and summarized here | EXPLAIN output | CP-RECR-02 |

## Checkpoint ledger

| CP | Scope | Head | Tree | RECR-AC | FAST | DB lane (local PG) | Notes |
|---|---|---|---|---|---|---|---|
| CP-RECR-01 | RECR-5; this ledger; RECR-3 (plan d.1, d.4, d.5); doc-count cells for one new test module | `e9348ad4e076fb21da73d196d9823eda10bf26d5` | `e6dee99739430c45a712014d1047bf8602e49ed4` | 012, 013, 014, 017 | 25,838 passed / 74 skipped / 0 failed; ruff, format, mypy (524) clean | PG 15 local, PGTZ=UTC: `test_record_events_cursor_visibility.py`, `test_record_events_list.py`, `test_record_events_bootstrap_race.py`, `test_record_events_grant_change.py`, `test_record_events_restart_survival.py` 29 passed | MR-R13 design; prove-reds M3a'-c' single-guard, each red on an assertion and green after a SHA-matched restore; out-of-list entries: none |
| CP-RECR-02 | RECR-1 Option R (MR-R01, R02, R05, R08, R09); 2 new test modules; doc-count cells | `f75a2263f7ae885aea9b773c441da7be32a7d5dc` | `aafbf7a5761adea22df250417e34952d9fb6a492` | 001-008, 020, 021, 022 | 25,850 passed / 74 skipped / 0 failed; ruff, format, mypy (524) clean | PG 15 local, PGTZ=UTC: every `tests/database/test_*record_event*` module 254 passed; other `record_event` modules' DB part (incl. `test_record_events_carry_no_payload.py`) 6 passed; full `-m recovery` 53 passed; no 40P01/lock_timeout | prove-reds M1a-e single-guard, each red on an assertion and green after a SHA-matched restore; EXPLAIN recorded; out-of-list entries: none |
| CP-RECR-03 | RECR-2 bootstrap module; consumer-contract spec; specs README row; mcv-limitations §15; doc-count cells | _(Orchestrator fills after commit)_ | _(Orchestrator fills after commit)_ | 009, 010, 011, 015 | 25,850 passed / 74 skipped / 0 failed; doc guards green; ruff, format, mypy (524) clean | PG 15 local, PGTZ=UTC: `test_record_events_consumer_bootstrap.py` + `test_record_events_bootstrap_race.py` 10 passed; the new module 3/3 passed in three consecutive runs; no 40P01/lock_timeout | W0-after-snapshot prove-red red on the final-state assertion, green after a SHA-matched restore; out-of-list entries: none |

## Working notes

### CP-RECR-01

- RECR-3 (MR-R13 design): `list_record_events` resolves a cursor anchor through `_anchor_position`, which first asks the reader's existing `visible_event_ids` probe about exactly `{e}` under the effective families and the request's disclosure flag, and returns `None` for a hidden anchor, so `decode_cursor` raises `invalid_request(cursor)` exactly as for an unknown one. Only a visible anchor reaches `resolve_position`, which is unchanged (partition and id only). The U-002 decode order is unchanged: shape, then binding, then visibility and position. `src/my_pa/contracts/ports.py`, `src/my_pa/infrastructure/persistence/record_events.py` and `tests/conftest.py` are byte-identical to `17487662`. In `tests/security/test_record_events_grant_narrowing.py`, `FakeReader.visible_event_ids` also records its arguments and admits a listed row under its own family; no existing assertion changed.
- Plan assumption [A] "no guard parses `.ai/goals/**`" re-verified: the citation guard's `SEARCHED_ROOTS` and the spelled-count sweep exclude `.ai/`; the README-routing guard reads only `README.md` files; `test_wp12_slice_a_checkpoint.py` reads only `.ai/goals/wp-12-apple-mcc`.
- Counts re-derived by measurement: test modules 645 → 646; FAST collection 25,911 → 25,912 (`25912/29082`); database-or-recovery-or-e2e collection 3,152 → 3,158; architecture 5,990 unchanged.
- Validation (MR-R13 tree): FAST 25,838 passed / 74 skipped / 0 failed (unit+schema 15,386; architecture 3,227 + 71 skipped and 2,692; rest 4,533 + 3 skipped), equal to the relationship-intelligence plan FAST cell; the unchanged memory-row guard file 75 passed; ruff, format and `MYPYPATH=src` mypy (524 files) clean; DB lane 29 passed.
- Prove-reds (MR-R13): M3a' (all families instead of effective), M3b' (disclosure forced for remote), M3c' (visibility check removed), each a single-guard mutant of `_anchor_position`, red on an assertion and green after a SHA-matched restore. The MR-R03-design mutants M3a-c are superseded.
- **Permission-denial history.** Under the first design, `resolve_position` itself applied `_visible`, which made it a third `RecordEventReader` method reaching a memory row, and `tests/architecture/test_every_capability_reaching_a_memory_row_is_declared.py::test_the_port_crossings_that_reach_a_memory_row_are_the_two_planes` failed. MR-R12 authorized adding it to the guard's set; running the edited guard was then refused by the permission classifier as "Security Test Removal". Per the authorization that was a STOP. It was resolved by the MR-R13 redesign: the guard is untouched and passes as written.
- **Claim-document finding (stands): no edit needed.** The WP-RE-06 paragraph of `evidence/acceptance/RI-FINAL-COMPLETION-RM-AC-DELTA-20260828.md` states `record_events.list`'s reach (two of the eight tables, remote-only, inside the OD-8 (i) `EXISTS` over `memory_id`, `current_version_id`, `memory_version_id` and `classification`); under MR-R13 the anchor check reaches memory only through `visible_event_ids`, an already-described read, so the paragraph stays exact. The document has no capture paragraph.
- **CP-RECR-01 out-of-list entries:** none.

### CP-RECR-02

- RECR-1 (Option R, MR-R01): `SqlRecordEventReader.page` adds one computed column, `routing_record_id`, to the outer SELECT of its single statement. It is a `CASE` over the page's family, one branch per routed family, each a keyed scalar subquery on the child table's primary key under `partition_criterion`, selecting only the owner column (`_ROUTING_OWNERS`). `routing_family` is derived in `_item` from `RECORD_EVENT_ROUTING` only when the id is not null. The page, the routing and the watermark stay ONE statement, with no lock, no migration and no emitter change. Routing reflects the record's CURRENT owner: an Entity merge moves the routing of the absorbed entity's earlier child events to the survivor (RECR-AC-004).
- MR-R08 / MR-R02: two fields, `routing_family` and `routing_record_id`, on `RecordEventFeedItem` (defaulted) and `RecordEventItemView`. The validator requires both or neither, a routed family only, the kind `RECORD_EVENT_ROUTING` names, and that kind's identifier shape; both null is admitted on a routed family ("not currently resolvable"). The RE-AC-072 node id `test_the_public_item_carries_exactly_its_thirteen_fields` is kept, with its asserted set now 15 and a comment explaining the name; `ITEM_FIELDS` is 15. No other existing assertion changed.
- MR-R05 (i) / RECR-AC-021: affiliations route to `person_entity_id`, asserted in `tests/unit/test_record_event_routing.py::test_the_reader_reads_one_owner_column_per_routed_family` and in the RECR-AC-003 affiliation case. MR-R05 (ii) / RECR-AC-020: an observation with no Entity lists with both routing fields null, and is reachable only through the `unresolved_only` scan (R-2).
- MR-R09 / RECR-AC-006: `tests/security/test_record_events_carry_no_payload.py::test_the_feed_reader_routing_reads_only_keys` holds the reader to the key, owner and partition columns of the 12 tables, with a seven-case planted control. Claim-document check: the only guard-parsed claim document about the feed reader's reach (`evidence/acceptance/RI-FINAL-COMPLETION-RM-AC-DELTA-20260828.md`) covers the eight Relationship Memory tables; none of the 12 routing tables is among them, so no paragraph was added.
- M1c adapted: `infrastructure/persistence/record_events.py` is registered `PER_MODULE_ONLY` in `tests/architecture/test_principal_partition_is_reached_through_the_guard.py`, which checks only that the module calls the guard somewhere, so dropping the criterion from the routing subquery would not turn that test red. The M1c target is instead the new DB test `test_routing_never_reads_another_partition` (a forged event naming another Principal's comment routes nowhere).
- **RECR-AC-022, EXPLAIN (PostgreSQL 15.15, local clone populated through the production writers; the production page statement compiled with literal binds; full output in the manager directory `cp/CP-RECR-02/EXPLAIN.txt`, untracked).** No sequential scan anywhere, under the planner default and under `enable_seqscan = off` alike. Every one of the 12 owner lookups is an index scan: six on a unique key index (`an_external_identifier_is_identified_within_its_principal`, `an_alias_…`, `an_assignment_…`, `an_entity_relationship_…`, `an_observation_…` with `(key, principal_id)` as the index condition, and an index-only scan of `task_comments_by_principal_task_created` on `(principal_id, comment_id)`); the other six (categories, names, addresses, communication methods, participations, affiliations) on the table's `principal_id` index with the key as a filter, which the planner prefers at this fixture's size. Each of the 12 tables also has a unique primary-key index on the key column (listed in the evidence). The page and watermark use `a_record_event_sequence_is_unique_within_its_principal`.
- Counts re-derived by measurement: test modules 646 → 648; FAST collection 25,912 → 25,924 (`25924/29121`); database-or-recovery-or-e2e collection 3,158 → 3,185; architecture 5,990 unchanged.
- **CP-RECR-02 out-of-list entries:** none.

### CP-RECR-03

- RECR-2: `tests/database/test_record_events_consumer_bootstrap.py` implements the documented bootstrap as an in-test consumer (W0 under the consumption page size and narrowing; snapshot through `tasks.list` paged, `tasks.read` and `tasks.comments.list`; upsert by `(family, record_id)`; delta from W0 rereading `task_comment` through `routing_record_id`). The interleavings use the allocator gate and lock-wait probe of `test_record_events_bootstrap_race.py` and test-driven hooks, never a sleep. Each test ends with the consumer's state equal to a fresh canonical enumeration, nothing at or before W0 consumed, every event after W0 consumed exactly once, and a null final `next_cursor`.
- Prove-red (plan c.4): the consumer takes W0 after the snapshot and its interleaving hook. RECR-AC-009 goes red on the final-state assertion (the in-flight comment is lost), and RECR-AC-011 goes red too; RECR-AC-010 stays green, since its write is already in the snapshot. The production single-snapshot guard (RE-AC-065, R-08) is already prove-red-covered and was not re-mutated.
- Docs (MR-R07): `docs/specs/record-event-consumer-contract-v0.1.md` (routing guide; current owner, MR-R01; null routing as a tombstone, MR-R05 (ii); the bootstrap contract; the Entity plane as reference-driven from the enumerable roots, with its coverage limit, MR-R06; recovery by re-bootstrap, MR-R03; residuals R-1, R-2 and R-G as a consumer-grant requirement, MR-R05 (i)/(iii); the two follow-up candidates). One row in `docs/specs/README.md` (the RECR-4 row is CP-RECR-04). In `docs/operations/mcv-limitations.md` section 15: the comment/Task sentence now says the routing reference names the Task, a routing-and-bootstrap paragraph points to the spec, and three evidence items are added.
- Counts re-derived by measurement: test modules 648 → 649; FAST collection 25,924 unchanged (`25924/29124`); database-or-recovery-or-e2e collection 3,185 → 3,188; architecture 5,990 unchanged.
- **CP-RECR-03 out-of-list entries:** none.
