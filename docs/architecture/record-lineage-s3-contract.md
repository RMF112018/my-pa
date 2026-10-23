# Record lineage — Slice S3 implementation contract

**Status:** proposed implementation contract under
[ADR-015](../decisions/ADR-015-record-lineage-and-issue-situations.md) (Proposed —
accepted by directive defaults; architecture/test-isolated scope only). It is the
single document S3 implementers code against, on top of the
[S1 contract](record-lineage-s1-contract.md) and the
[S2 contract](record-lineage-s2-contract.md) as implemented. It authorizes no migration
run, grant, deployment, backfill run against any real database, or production use.
Where it differs from the review package (`MYPA-LINEAGE-ADVERSARIAL-REVIEW-20261017-001`,
documents 02, 03, 04, 06 and 07), this document controls for S3 and section 12 records
why.

**Basis:** `feat/lineage-s3-graph@84ddab379c1c69c9a422f9894130aa5096e218fa`
(tree `4264ed7b3ec97cad16295799fd317558fcf0a8b9`), the S2 head on
`feat/lineage-s2-workflow`; Alembic single head `d020b532ad7d` (120 revisions);
214 `Capability` members, 58 `Purpose` members, 225 audit-vocabulary capability names,
22 lineage capabilities behind `MY_PA_LINEAGE_ENABLED`, 107 `gateway.json` entries.
"S1 §n" and "S2 §n" cite the earlier contracts. Paths under `src/` are relative to
`src/my_pa/`.

All counts in this file are digits on purpose (spelled-count guard).

**As implemented.** Sections 3, 7.2, 7.3, 7.6, 9 and 10 carry "as implemented" notes, and
section 12.1 lists every resolution the S3 workers (L1–L6) made where the code settled a
point this contract left open or placed something elsewhere; each was accepted by the
Orchestrator. After L6 `gateway.json` holds 110 entries.

## 1. What S3 is

S3 is the historical and bounded-read slice (plan WP-03A in full, WP-03B, the S3 part of
WP-06A) plus the S2 residuals S2 §11 assigned to it. After S3 a reader can start from
any record of an Issue and recover the same Issue-scoped graph **as it was known at a
stated time**, page through it under a cursor that cannot outlive the reader's grants,
read the Issue's history and timeline, see disputed claims as disputed, correct a
mis-recorded handoff without rewriting it, and an operator can classify the legacy
corpus in a dry run before any source-backed link is materialized.

**In S3:**

- a **knowledge clock** (section 4.2): every lineage write takes one per-Principal,
  commit-ordered **commit mark** from a row-locked allocator, and every lineage fact row
  carries its mark; `known_at` reads are anchored to the committed mark horizon, so a
  later commit, including a late correction, never changes the lineage facts of an answer already
  given for a `known_at` at or before that horizon (the one named residual is the
  note-version cut, section 3.4);
- `records.lineage` widened (section 7.2): `known_at`, `valid_at`, `page_size` and an
  opaque grant-bound `cursor`; per-family visibility for remote readers; path
  explanations; `restricted_evidence` and `scope_changed_restart_required`; all 14
  AT-001 roots equal at one `known_at` / `valid_at`;
- 3 new reads: `issues.history`, `issues.timeline` (lineage plane as of `known_at`,
  native plane as currently recorded, `historical_fields_partial` where native history
  recorded no former value, past Constraint ball-in-court from native revision
  snapshots), `records.associations.history`;
- `contest` / `reinstate` and the `contested` state on semantic links, and a contested
  link in an Issue's context as a closure-gate blocker (closing the S2 §3.3 forward
  obligation);
- `related_context` (symmetric, stored once in canonical order, Issue-scoped);
- handoff correction (`issues.handoffs.correct`: `retime` or `void`, append-only,
  honoured by `known_at` / `valid_at` reads);
- the WP-03B backfill **dry run** (section 8.3): `records.backfill.plan` (a frozen
  population, every item classified into one of the 5 classes, a durable resumable
  ledger) and `records.backfill.report`, both operator-only, behind their own switch
  `MY_PA_LINEAGE_BACKFILL_ENABLED` (default off), invoked through the ordinary CLI
  transport; it writes no link; tests on synthetic fixtures only;
- WP-06A S3 (section 7.6): an Issues index, an accessible Issue view (breadcrumb,
  timeline, paged lineage table with path explanations, note-version drilldown against
  the current note, hidden-data and source-status messages, keyboard/phone/tablet), and
  a minimal Meeting view carrying the related-Issue panel;
- the S3 part of AT-001 and AT-006, and AT-007 (contested), AT-008, AT-011, AT-013,
  AT-014, AT-016, AT-023, AT-024, AT-025, with AT-026 as a regression (section 10).

**Not in S3** (section 11 lists the owner): materializing any backfill item (the
backfill apply, an operator-gated later package with the binding requirements of section
11); proposals and review (`irp`, `ldec`); Record Event emission for lineage (`irec`); Decision membership; native virtual edges other
than `meeting_note_version_of`; `records.associations.list_for_record`; a valid-time
interval on links; contesting memberships; verified Commitment acceptance; Constraint
close evidence in the Constraint plane; any closure exception authority.

## 2. Identifier kinds

2 new `IdKind` members (`domain/common/identifiers.py`), verified free at the basis
commit against all 148 existing values (none is a string prefix of either, and neither
is a prefix of any); re-run the collision check before the revision is written.

| `IdKind` member | Prefix | Identifies |
| --- | --- | --- |
| `ISSUE_HANDOFF_CORRECTION` | `ihcr` | one immutable handoff correction (`issue_responsibility_corrections.correction_id`) |
| `LINEAGE_BACKFILL_RUN` | `lbfr` | one backfill run (`lineage_backfill_runs.run_id`) |

Commit marks, the allocator row and backfill items are composite-keyed (no prefix).
`irp`, `ldec` and `irec` stay reserved and unused (section 11). Existing kinds used by
S3: `sit`, `prj`, `psit`, `mtg`, `mnote`, `tsk`, `cmt`, `cst`, `cap`, `capver`, `asrt`,
`span`, `ent`, `prn`, `irs`, `irl`, `irv`, `ian`, `ipme`, `ihnd`, `rcev`, `crev`.

## 3. Closed vocabularies

Widened in `domain/lineage/vocabulary.py` and in the S3 revision's CHECKs together
(S1 §3 rule). **As implemented (L1):** the backfill vocabularies (`BackfillClass`,
`BackfillSourceKind`, `BackfillReason`, `BackfillRunState`) and `BACKFILL_VALIDATOR_VERSION`
live in `domain/lineage_backfill/vocabulary.py`, not in `domain/lineage/vocabulary.py`,
because the binding S2 test forbids the token `meeting_series` under `domain/lineage`
(section 12.1, D-34); every other row of the table is in `domain/lineage/vocabulary.py`.

| Vocabulary | S1 + S2 admit | S3 adds | Still later |
| --- | --- | --- | --- |
| `RelationType` | 7 members | `related_context` | — |
| `LinkRevisionAction` | `assert`, `end`, `correct_evidence` | `contest`, `reinstate` | — |
| `LinkLifecycleState` | `active`, `ended` | `contested` | — |
| `AcceptanceBasis` | `user_confirmed` | — | `source_backed_verified` (the deferred backfill apply), `review_accepted`, `system_deterministic` (not scheduled) |
| `EvidenceAvailability` (read only) | `available`, `archived`, `legacy_unversioned` | `restricted` | `redacted`, `unavailable`, `withdrawn`, `superseded` |
| `LineageCompleteness` (read only) | 4 members | `restricted_evidence`, `scope_changed_restart_required` | `source_not_integrated`, `not_reportable` (Program work) |
| `NativeVirtualEdge` (read only) | `meeting_note_version_of` | — (section 12, D-05) | — |
| `MemberRole` | 6 members | — (section 12, D-10) | `decision` |
| `HandoffCorrectionAction` (new) | — | `retime`, `void` | — |
| `TimelineEntryKind` (new, read only) | — | `issue_revision`, `project_link`, `membership`, `association`, `handoff`, `handoff_correction`, `native_event` | — |
| `BackfillClass` (new) | — | `native_virtual_proven`, `source_backed_accepted`, `review_candidate`, `unresolved`, `refused` | — |
| `BackfillSourceKind` (new) | — | `task_follow_up`, `constraint_follow_up`, `meeting_series`, `project_situation`, `work_origin_assertion`, `work_origin_capture_root`, `work_origin_other`, `situation_object_ref` | — |
| `BackfillReason` (new) | — | section 8.3 table | — |
| `BackfillRunState` (new) | — | `enumerated`, `classified` | `applying`, `applied` (the deferred apply) |
| `ExistingLinkState` (new, read only) | — | `none`, `active`, `contested`, `ended` | — |

`LineageCompleteness` precedence (one `complete_state`, every applicable code also in
`qualifiers`): `scope_changed_restart_required` > `unresolved_ambiguity` >
`truncated_budget` > `restricted_evidence` > `partial_native_history` > `complete`.
`historical_fields_partial` is a per-entry boolean of the timeline (section 7.3), not a
`LineageCompleteness` member (section 12, D-23).

New constants in `vocabulary.py`: `LIVE_LINK_STATES = {active, contested}` (the states
that hold an identity and are traversed); `CONTESTABLE_RELATIONS` = every semantic
relation; `LINEAGE_READ_GENERATION = 1` (bumped by any change to traversal, visibility,
ordering or paging rules; bound in every cursor); `LINEAGE_FAMILY_READS` (section 6.4);
`BACKFILL_VALIDATOR_VERSION = 1`; `LINK_REVISION_CAPABILITIES` gains
`records.associations.contest` and `records.associations.reinstate`; new
`HANDOFF_CORRECTION_CAPABILITIES = {"issues.handoffs.correct"}` (the fact-writing set of
the corrections table) and `BACKFILL_WRITE_CAPABILITIES = {"records.backfill.plan"}` (it
writes ledger rows only, no fact and no mark); `LINEAGE_WRITE_CAPABILITIES`, the union of
the lineage write sets, gains both new sets and becomes the 19 lineage write names (S2's 15
plus `records.associations.contest`, `records.associations.reinstate`,
`issues.handoffs.correct`, `records.backfill.plan`); it is the set the
`lineage_write_requests` capability CHECK admits. `RECORD_LINK_CAPABILITIES` is
unchanged (no S3 write creates a root other than through `records.associations.assert`).
`LINEAGE_BACKFILL_CAPABILITIES = {"records.backfill.plan", "records.backfill.report"}`
(the sub-switch set, section 7.7).

### 3.1 S3 relation matrix addition and link transitions

| Relation | From / To | Written by | Rule (application; `invalid_request` / named detail unless stated) |
| --- | --- | --- | --- |
| `related_context` (`semantic`, symmetric) | any 2 distinct records of `meeting`, `meeting_note_version`, `task`, `commitment`, `constraint`, `capture_version` | `records.associations.assert` (and `correct`/`contest`/`reinstate`/`end`) | `context_issue_id` required (`context_issue_id`); both endpoints are *inside* the context Issue at assert time — an active member or a member of an active member's pair set (S1 §7.2) — (`to_record` / `from_record`); ≥1 `immutable_version` anchor with role `corroborates` (`evidence_anchors`); the stored `from` is the endpoint with the smaller `(family token, record_id)` and `to` the larger, compared by code point (Python `str` order; `COLLATE "C"` in SQL, section 4.1) — a request naming them the other way round is normalized, not refused, so both orders have one `normalized_identity`; `from` = `to` is refused (`to_record`; also a CHECK) |

**Link transitions** (semantic links only; a membership `link_id` is
`invalid_request` / `link_id` on `contest` and `reinstate`, the S1 symmetric rule):

| Action | Admitted from (head state) | Result state | Evidence rule (complete new set, 1..32, S1 admission) |
| --- | --- | --- | --- |
| `contest` | `active` | `contested` | ≥1 `immutable_version` anchor with role `contradicts`; any other roles admitted |
| `reinstate` | `contested` | `active` | the relation's own evidence rule (S1 §3.1, S2 §3.1, above), as `correct` re-applies it |
| `correct_evidence` | `active` | `active` | unchanged (S1, S2 R2-F07) |
| `end` | `active` or `contested` | `ended` | unchanged (0..32) |

`ended` stays terminal (S1). A `contested` link keeps its identity:
`records.associations.assert` of an identity whose head is `contested` is `conflict` /
`state` (never `created: false`, which would hand back a disputed claim as success);
the one-live-head database index covers `active` and `contested` (section 4.1).
`contest` and `reinstate` re-run no state, membership, Project, time or cycle rule
(S2 R2-F07 reasoning: they change no endpoint); `reinstate` of a `blocks` link does not
re-run the cycle search because a contested `blocks` head stays in the cycle search's
input (section 6.2), so no cycle can have formed through it.

### 3.2 The closure gate (S2 §3.3, extended) and "in the Issue's context"

**Definition, used everywhere below and nowhere narrowed.** A link is *in the context of
Issue I* at a cut when it is one the S1 §7.2 step 4 traversal follows for I: a membership
from I; or a semantic link whose `context_issue_id` is I; or a semantic link with an
endpoint equal to I (whatever its context); or a semantic link with a null context whose 2
endpoints are both *inside* I (I, an active member, or a member of an active member's
pair set) at that cut. The cut is the current head state for writes and the gate, and the
read's cut (section 3.4) for reads. This one predicate
(`domain/lineage/closure.py::in_issue_context`, persistence `links_in_issue_context`) is
used by the gate, by `contested_links` in readiness, by the frozen-closed refusals and by
the timeline's `association` selection (section 7.3).

The S2 gate is unchanged and gains one condition: **no link in the Issue's context has a
`contested` head.** Memberships cannot be contested in S3 (their dispute is a
`contradicts` anchor recorded by `issues.memberships.correct`, which S2 already reports
as `resolution_evidence_contradicted`), and anchors are not links, so this one rule is the
whole of S2's forward obligation (section 12, D-09). `issues.close` with a contested link
in context answers `conflict` / `closure_gate`; `issues.closure_readiness` gains
`contested_links` (section 7.1) and is `ready: false` while it is non-empty. The close's
section 6.2 step 3 `FOR SHARE` set gains the endpoints of every in-context semantic link
it evaluates, and every `contest` / `reinstate` takes `FOR SHARE` on every Issue the link
is in the context of (its context Issue, and an Issue endpoint), so a contest and a close
serialize. The frozen closed Issue (S2 §3.3) also refuses `contest`, `reinstate`,
`correct` and `end` of any link in its context, including a null-context link with both
endpoints inside it and a link naming it as an endpoint, and `issues.handoffs.correct`
of any of its handoffs (`conflict` / `state`), so a closed Issue cannot acquire or lose
a dispute; reopen first. A null-context link that is inside several Issues is refused
while any of them is closed.

### 3.3 Handoff correction (CR-005 residual)

A correction is one append-only `issue_responsibility_corrections` row (`ihcr`) naming
one handoff event; it never changes the event.

- **`retime`**: the event happened, at another business time. `effective_at` (ISO-8601 with offset) must be at or after the Commitment's `created_at`, at or after the *current effective time* of the previous **live** event of the chain, at or before the current effective time of the next live event, and at or before the correction's `recorded_at`; else `invalid_request` / `effective_at`. Evidence: exactly 1 `immutable_version` anchor with role `handoff`.
- **`void`**: the event did not happen. Only the chain's **last live event** can be voided (`invalid_request` / `handoff_id` otherwise), so holder continuity is never broken. Evidence: exactly 1 `immutable_version` anchor with role `contradicts`.
- **Live** = not voided by a correction known at the read's `known_at`. The *current effective time* of an event is the `effective_at` of its latest `retime` known at `known_at`, else its own.
- A voided event is terminal: any further correction of it is `conflict` / `state`.
- **The chain skips voided events** (replacing S2 §3.4's "event *n − 1*"): the leaving holder of a new handoff is the arrival holder of the chain's last live event and its `effective_at` must be at or after that event's current effective time. **When no earlier event is live** (every earlier event is voided, or there is none), the application applies the S2 event-1 rule (the leaving holder is the Principal or the Commitment's current counterparty, `from` names its side) and the effective time is bounded only by the Commitment's `created_at`; the database, as S2's trigger does for event 1, then checks no holder predecessor and checks `effective_at` against the Commitment's `created_at` only. `issues.handoffs.record` and the replaced database triggers (section 4.1) both apply this.
- Corrections take the S2 `:handoff:` advisory key of their chain, so a correction and a new handoff of one chain serialize.

### 3.4 Time (ADR-015 decision 8, made concrete)

- **Known time** is the commit mark (section 4.2). A fact is *known at `T`* iff its `commit_seq ≤ W(T)`, where `W(T)` is the largest mark of the Principal whose `marked_at ≤ T`; a fact written before the S3 revision (`commit_seq IS NULL`) is known at `T` iff its own `recorded_at ≤ T`.
- **Effective `known_at`**: `T_k = min(requested known_at, or server now when omitted; H)`, where `H` is the committed horizon, the allocator row's `last_marked_at` read without a lock. A requested `known_at` after server now is `invalid_request` / `known_at`. A Principal with no allocator row has no lineage fact; `T_k` is then `null` and every lineage set is empty.
- **Why this is commit-safe.** The allocator row is locked from allocation to commit, and `marked_at` is `greatest(clock_timestamp(), previous + 1 µs)` under that lock, so every mark that is not committed when `H` is read — one in flight, or any later one — has `marked_at > H`. Every fact known at a `T ≤ H` is therefore committed and immutable when it is read, and no later commit can add one. A transaction that began before `T` but commits later is invisible to every answer at `T`, now and forever (section 10, `test_the_horizon_excludes_an_in_flight_write`).
- **Valid time.** A link revision, an Issue revision and a Project link event record no business-effective time; each takes effect when it became known (its mark). A handoff event takes effect at its current effective time. For a requested `valid_at` (`invalid_request` / `valid_at` after server now), the read uses `T_v = min(valid_at, T_k)` (default `T_k`): links, Issue revisions and Project link events at `W(T_v)`; handoffs and corrections known at `W(T_k)` and in effect at `T_v`. `T_v` is the **lineage-plane** valid cut only. The response reports `known_at = T_k`, `valid_at` = the requested `valid_at` (or `T_k` when omitted) and, when they differ, `lineage_valid_at = T_v` (otherwise `lineage_valid_at = valid_at`).
- **What a late correction changes.** A correction recorded at `D + 5` that retimes a handoff to `D − 2` has a mark after `D + 5`: an answer at `known_at = D + 1` never contains it; an answer at `known_at = D + 6`, `valid_at = D − 1` does (AT-008).
- **Meeting note versions are cut by their own `recorded_at`, at the native cut** (R3-F01, R3-F20). A note version is native and takes no mark, so it is never cut at the lineage horizon. The **native cut** is `N = min(valid_at?, known_at?, read time)` over the values the request supplies, where the read time is the first page's statement time: the requested `valid_at` or `known_at` when given, else the server's read time. A reached Meeting's note versions — in its `meeting_note_version_of` virtual edges and in its pair set (S1 §7.2) — are those with `meeting_note_versions.recorded_at ≤ N`. The answer reports `native_cut_at = N`, and the cursor freezes it (section 5), so later pages use the same cut. So a current read (no `known_at`) shows a note saved after `H` (section 10, `test_a_current_read_shows_a_note_saved_after_the_lineage_horizon`, and the binding S1 regression `test_reverse_read_from_m1_n1_c1_and_issue_yields_one_graph`). **Residual (named, not commit-ordered):** `recorded_at` is the native writer's transaction stamp, not commit order (the D-01 reasoning), so for an explicit `known_at` a note save whose transaction began before that instant and commits after an answer can make a later answer at the same `known_at` include it; the window is that one native transaction's duration. A note saved after an explicit `known_at` never changes the answer (`test_a_note_saved_after_known_at_leaves_the_answer_unchanged`).
- **The native plane has its own valid cut** (R3-F02). Native timeline entries (section 7.3) are never clamped to `T_k`: they are bounded by `occurred_at ≤ valid_at` (the requested value, itself at or before server now) under the Record Event watermark frozen on the first page. So a native change made after the last lineage write (after `H`) is shown at a later `valid_at`, which is how past ball-in-court is read.
- **What is current, by design.** Evidence availability (ADR-015 decision 8), native existence re-resolution (S1 §7.2 step 5), the reader's grants (section 6.4) and native-plane timeline entries (section 7.3) are read as they are now; none of them is a fact of the lineage plane, and none rewrites one.

## 4. Schema — one additive revision

One Alembic revision, `down_revision = "d020b532ad7d"`, the new single head (file
`migrations/versions/<date>_<rev>_record_lineage_s3.py`; slug `record_lineage_s3`).
Frozen literal DDL, no domain or persistence import, declarations mirrored in
`infrastructure/persistence/tables.py` with the `TABLES_SHA256` pin and every W1 §2.2
registration step. S1 §4 and S2 §4 conventions hold (schema `knowledge`, principal
partition, `_is_identifier` on every identifier column, principal-composite
`ON DELETE RESTRICT` foreign keys, server-stamped `timestamptz`; a widened CHECK is
dropped and re-added under the **same name**; a replaced function is
`CREATE OR REPLACE` and `downgrade()` restores its S2 body byte for byte).

### 4.1 Existing tables (additive only)

**The 4 fact tables** `issue_revisions`, `issue_project_membership_events`,
`record_link_revisions`, `issue_responsibility_events`:

- `ADD COLUMN commit_seq bigint` (existing rows stay null; no row is updated), FK `(principal_id, commit_seq) → lineage_commit_marks (principal_id, commit_seq)` named `a_lineage_fact_names_its_commit_mark`, and index `<table>_by_commit (principal_id, commit_seq)`.
- Trigger `a_lineage_fact_takes_its_commit_mark` (`BEFORE INSERT`): `NEW.commit_seq` must be null or equal to `knowledge.lineage_commit_mark(NEW.principal_id)` (else `check_violation`), and is then set to it. So every row written after the revision carries the mark of its own transaction, whichever writer wrote it, and no caller can forge one.

**`record_links`**

- Widen `a_record_link_relation_type_is_known` (+ `related_context`) and `a_record_link_pair_is_admitted` (+ the section 3.1 row: `from_family` and `to_family` each in the 6 families). `a_record_link_capability_is_known` is unchanged.
- New CHECK `a_related_context_is_canonical_and_scoped`: `relation_type <> 'related_context' OR (context_issue_id IS NOT NULL AND (from_family COLLATE "C", from_id COLLATE "C") < (to_family COLLATE "C", to_id COLLATE "C"))` — code-point order whatever the database collation (precedent `20260804_8c4d1e7a2b90`, `ORDER BY bucket_id COLLATE "C"`). Every SQL `ORDER BY` and keyset predicate that must match a Python order in this contract (section 7.2 output order and `p`, section 7.3 order, `link_id` orders) also uses `COLLATE "C"` on text keys.

**`record_link_revisions`**

- Widen `a_link_revision_action_is_known` (+ `contest`, `reinstate`), `a_link_revision_state_is_known` (+ `contested`), `a_link_revision_capability_is_known` (+ `records.associations.contest`, `records.associations.reinstate`) and `a_link_revision_states_its_reason` (`action NOT IN ('correct_evidence','end','contest','reinstate') OR reason IS NOT NULL`). `a_link_revision_ends_exactly_when_it_ends` is unchanged; new CHECKs `a_link_revision_contests_exactly_when_contested` (`(action = 'contest') = (lifecycle_state = 'contested')`) and `a_reinstatement_is_active` (`action <> 'reinstate' OR lifecycle_state = 'active'`).
- `CREATE OR REPLACE FUNCTION knowledge.a_link_revision_follows_an_active_predecessor()` with the section 3.1 transition table (predecessor state `active` for `correct_evidence`, `contest`; `active` or `contested` for `end`; `contested` for `reinstate`).
- `a_lineage_row_is_local_operator_attested` and `a_link_revision_acceptance_basis_is_known` are unchanged.

**`record_link_heads`** — widen `a_link_head_state_is_known` (+ `contested`); drop and recreate
the partial unique index `record_link_one_active_identity (principal_id, normalized_identity) WHERE lifecycle_state IN ('active','contested')` under the same name.

**`issue_responsibility_events`** — `CREATE OR REPLACE` both S2 functions so the chain
skips voided events (section 3.3): `a_handoff_follows_its_predecessor()` compares
`NEW`'s from-holder with the arrival holder of the latest event of the chain with
`sequence_no < NEW.sequence_no` that has no `void` correction, and admits any
from-holder when there is no such event (S2 event-1 behaviour; the application rule of
section 3.3 applies); `a_handoff_is_effective_in_order()` compares `NEW.effective_at`
with that event's current effective time (its latest `retime`'s `effective_at`, else its
own) and with the Commitment's `created_at`. The `predecessor_sequence_no` FK and CHECKs
are unchanged (the ledger sequence still counts every event).

**`lineage_write_requests`**

- `ADD COLUMN commit_seq bigint` (FK to the mark, `UNIQUE (principal_id, commit_seq)`; set at completion by every write that took a mark — every write after the revision except `records.backfill.plan` — and null on a pre-S3 row), `result_handoff_correction_id text` (`ihcr`, FK), `result_backfill_run_id text` (`lbfr`, FK), `result_backfill_checkpoint integer` (`>= 0`).
- Widen the capability CHECK (+ the 4 S3 writes: `LINEAGE_WRITE_CAPABILITIES`), `an_incomplete_lineage_write_request_names_no_result` (+ the 4 new columns null), every S1/S2 completion CHECK (the 3 new result columns null), and add `a_completed_handoff_correction_names_its_correction` (`issues.handoffs.correct` ⇒ only `result_handoff_correction_id`), `a_completed_backfill_write_names_its_run` (`records.backfill.plan` ⇒ only `result_backfill_run_id` and `result_backfill_checkpoint`, and `commit_seq IS NULL`), and `a_completed_link_write_names_its_revision` widened with `records.associations.contest` and `reinstate` (`result_created IS NULL`).
- `CREATE OR REPLACE FUNCTION knowledge.a_lineage_write_request_completes_once()` so the 4 new columns are among those that may change, only from reserved, only once.

**`audit_events`** — `capability_is_known` and `purpose_is_known` restated (BEFORE texts
byte copies of `d020b532ad7d`'s AT texts; AT texts add exactly the 8 section 7 names and
`lineage_backfill`, sorted), `_CURRENT_AUDIT_CAPABILITIES` moving with them, under the
schema-ahead precedent (S1 §4.3) with `tests/schema/lineage_s3_schema_ahead_contract.py`.

No change to `situations`, `project_situations`, `record_link_revision_evidence`,
`issue_revision_evidence`, `lineage_evidence_anchors`, `lineage_write_request_links`,
`meeting_note_versions`, `capture_versions`, `record_events` or any native table.

### 4.2 New tables

**`lineage_commit_sequences`** (the allocator; one mutable row per Principal; precedent
`record_event_sequences`)

Columns `principal_id` (PK), `last_seq bigint NOT NULL CHECK (last_seq >= 0)`,
`last_marked_at timestamptz NOT NULL`. Trigger `a_commit_sequence_advances_by_one`
(`BEFORE UPDATE OR DELETE`): an update keeps `principal_id`, sets
`last_seq = OLD.last_seq + 1` and `last_marked_at > OLD.last_marked_at`; `DELETE` is
`restrict_violation`. The revision **seeds** one row per Principal that holds any row in
the 4 fact tables: `last_seq = 0`, `last_marked_at` = the greatest `recorded_at` of that
Principal's fact rows (an `INSERT … SELECT` into the new table; no existing row changes).

**`lineage_commit_marks`** (immutable)

Columns `principal_id`, `commit_seq bigint (>= 1)`, `marked_at timestamptz`,
`recorded_xact xid8`; PK `(principal_id, commit_seq)`;
`UNIQUE (principal_id, recorded_xact)`; index
`lineage_commit_marks_by_time (principal_id, marked_at)`. Trigger
`a_commit_mark_is_its_allocation` (`BEFORE INSERT`): `NEW.commit_seq` and
`NEW.marked_at` equal the allocator row's values as this transaction sees them and
`NEW.recorded_xact = pg_current_xact_id()`.

**Function `knowledge.lineage_commit_mark(p_principal text) RETURNS bigint`**
(`plpgsql`, `SECURITY INVOKER`, `VOLATILE`): returns the mark this transaction already
holds for `p_principal` (`recorded_xact = pg_current_xact_id()`), else allocates one —
`INSERT INTO lineage_commit_sequences … ON CONFLICT (principal_id) DO UPDATE SET last_seq = last_seq + 1, last_marked_at = greatest(clock_timestamp(), last_marked_at + interval '1 microsecond') RETURNING …`
(a first row is `(1, clock_timestamp())`), then inserts the mark — and returns it. One
mark per (Principal, transaction); marks of one Principal are contiguous from 1.

**`issue_responsibility_corrections`** (immutable; section 3.3)

| Column | Type / rule |
| --- | --- |
| `principal_id`, `correction_id` (`ihcr`) | PK |
| `handoff_id` (`ihnd`) | FK `(principal_id, handoff_id) → issue_responsibility_events` |
| `correction_no` (`>= 1`), `predecessor_correction_no` | `UNIQUE (principal_id, handoff_id, correction_no)`; FK to self; CHECK `correction_no = 1` ⇔ predecessor null, else `= correction_no − 1` |
| `action` | `HandoffCorrectionAction` |
| `corrected_effective_at` | `timestamptz`; CHECK `(action = 'retime') = (corrected_effective_at IS NOT NULL)`; CHECK `corrected_effective_at <= recorded_at` |
| `evidence_anchor_id` (`ian`), `evidence_role` | NOT NULL, FK → `lineage_evidence_anchors`; CHECK `retime` ⇒ `handoff`, `void` ⇒ `contradicts` |
| `reason` | `length(trim(reason)) BETWEEN 1 AND 2000` |
| `acceptance_basis` (`user_confirmed`), `authority_class`, `decision_channel`, `source_capability` (`issues.handoffs.correct`), `recorded_at` | `a_lineage_row_is_local_operator_attested` (S1 text) |
| `commit_seq` | `bigint NOT NULL`, FK to the mark; `a_lineage_fact_takes_its_commit_mark` attaches here too |

Index `issue_responsibility_corrections_by_handoff (principal_id, handoff_id, correction_no)`.
Trigger `a_handoff_correction_is_admissible` (`BEFORE INSERT`): refuses
(`check_violation`) a correction of a voided event; a `void` unless the event is the
last live event of its `(issue, commitment)` chain; a `retime` whose
`corrected_effective_at` is before the Commitment's `created_at`, before the previous
live event's current effective time or after the next live event's.

**`lineage_backfill_runs`** (guarded mutable; section 8.3)

Columns `principal_id`, `run_id` (`lbfr`, PK), `state` (`BackfillRunState`),
`validator_version` (`= 1`), `commit_seq_cutoff bigint` (the Principal's committed
`last_seq` read in the enumerating statement, 0 when none; it is the lineage cut every
item's `existing_link_*` columns are computed at, section 8.3), `source_cutoff_at
timestamptz` (statement time of the enumeration), `population_count integer (>= 0)`,
`classified_count integer`, `plan_digest text` (sha256 hex; set exactly when `state`
becomes `classified`), `census jsonb` (the enumeration census of section 8.3, canonical,
counts and tokens only), `created_at`, `classified_at`, `authority_class`,
`decision_channel` (`a_lineage_row_is_local_operator_attested`). CHECKs:
`0 <= classified_count <= population_count`; `(state = 'enumerated') = (plan_digest IS NULL)`;
`state = 'classified'` ⇒ `classified_count = population_count`. Trigger
`a_backfill_run_moves_forward` (`BEFORE UPDATE OR DELETE`): only `state` (from
`enumerated` to `classified`, once), `classified_count` (non-decreasing), `plan_digest`
and `classified_at` (once each) may change; `DELETE` refused.

**`lineage_backfill_items`** (guarded mutable)

| Column | Type / rule |
| --- | --- |
| `principal_id`, `run_id`, `item_no` (`>= 1`) | PK; FK `(principal_id, run_id) → lineage_backfill_runs` |
| `source_kind`, `source_family`, `source_id`, `source_ref` | `BackfillSourceKind`; the native record and the referenced value as an **ASCII token**, bounded 1..256: an identifier-shaped reference (an `IdKind` prefix and its pattern) is stored as itself; for `work_origin_other` it is `<shape>:<sha256 hex of the UTF-8 bytes of the exact stored ref>`, where `<shape>` is `prefix:<the IdKind prefix>` for an identifier-shaped ref of an unsupported kind and `free_text` otherwise — the ref text itself is never stored, digested or displayed (R3-F22); `UNIQUE (principal_id, run_id, source_kind, source_id, source_ref)` |
| `source_version` | native `version` at enumeration, null for a family without one |
| `source_digest` | sha256 hex, computed **in the enumerating statement** by `knowledge.lineage_backfill_source_digest` (below) |
| `classification`, `reason` | `BackfillClass`, `BackfillReason`; null until classified, then set once |
| `candidate_identity` | the candidate's `normalized_identity` (S1 §5.3) or null; non-null only for `source_backed_accepted` and a `review_candidate` with a derivable link |
| `candidate` | canonical JSON (S1 §5 rules) of the candidate link with its anchor objects, or null |
| `existing_link_id`, `existing_link_state` | the lowest `link_id` (`COLLATE "C"`) of any link with the candidate's `(from, relation_type, to)` endpoints, **in any context and any state**, known at `commit_seq_cutoff`, and its state there (`ExistingLinkState`, `none` when there is none); set with the classification |
| `quarantined` | `boolean NOT NULL DEFAULT false`; CHECK `quarantined = (classification IN ('unresolved','refused'))` once classified |
| `classified_at` | |

Trigger `a_backfill_item_is_settled_once` (`BEFORE UPDATE OR DELETE`): `classification`,
`reason`, `candidate_identity`, `candidate`, `existing_link_id`, `existing_link_state`,
`quarantined` and `classified_at` change only together, only from unclassified, once;
nothing else changes; `DELETE` refused.

**Function `knowledge.lineage_backfill_source_document(p_principal text, p_kind text, p_family text, p_source_id text, p_source_ref text) RETURNS text`**
(`plpgsql`, `STABLE`, `SECURITY INVOKER`; frozen DDL, R3-F09): the canonical JSON of section
5's source document, built per kind with a `CASE` by concatenation in sorted-key order with
`coalesce(to_json(value)::text, 'null')` per string and `coalesce(value::text, 'null')` per
integer (the S1 §5.5 technique), list facts aggregated with `ORDER BY … COLLATE "C"`; every
fact is an identifier, closed token, integer or hex digest (ASCII; a free-text
`origin_evidence_ref` enters only as the section 4.2 token, computed in SQL as
`encode(sha256(convert_to(ref, 'UTF8')), 'hex')` over the stored text with no
normalization, exactly as Python hashes `ref.encode("utf-8")`), so it is byte-identical
to `domain/lineage/backfill.py::source_document`. **`knowledge.lineage_backfill_source_digest(…same arguments…) RETURNS text`** =
`encode(sha256(convert_to('lineage-backfill-source-v1' || chr(10) || lineage_backfill_source_document(…), 'UTF8')), 'hex')`.
Golden vectors are shared: one fixture file drives the Python unit test and the SQL parity
test (section 10); it includes a `work_origin_other` source whose ref is non-ASCII and
not NFC-normalized, and one whose ref begins `asrt_` but is not identifier-shaped (its
`source_ref` is the `free_text` token). Enumeration stores the digest; classification recomputes it (SQL) and
compares (section 8.3). `downgrade()` drops both functions after the tables.

### 4.3 Shared triggers, protection, downgrade

- `lineage_rows_are_append_only()` attaches to `lineage_commit_marks` and `issue_responsibility_corrections`; `lineage_relations_refuse_truncate()` attaches to all 5 new tables (S1 semantics). The backfill tables are guarded mutable ledgers: a plan run is a durable write that `downgrade()` refuses on (section 8.3).
- `a_linked_record_is_not_deleted` is unchanged.
- No role grant changes; the S1 §4.3 DML-not-DDL and `TRUNCATE … CASCADE` residuals apply unchanged to the new tables.
- `downgrade()` first refuses (`restrict_violation`) while any of these holds, each family alone sufficient: a `lineage_commit_marks` row; a `lineage_commit_sequences` row with `last_seq > 0`; an `issue_responsibility_corrections` row; a `lineage_backfill_runs` row; a `record_links` row with `related_context`; a `record_link_revisions` row with an S3 action, state or capability; a `lineage_write_requests` row naming an S3 capability; an `audit_events` row naming an S3 capability or `lineage_backfill`. Only then it drops the seeded allocator rows with their table, restores every widened CHECK, the index predicate and every replaced function to its S2 text, and drops the new columns, triggers, functions and tables in reverse order.

## 5. Canonical encodings

S1 §5 and S2 §5 are reused unchanged. Additions:

- **Cursor** (records.lineage, issues.timeline): unpadded base64url of canonical JSON (`record_events.list` encoding: ASCII, sorted keys) `{"v": 1, "b": <64-hex binding>, "s": <64-hex scope digest>, "k": <T_k ISO-8601 UTC or null>, "t": <T_v or null>, "n": <the native cut N, ISO-8601 UTC, for records.lineage; null for issues.timeline, which has no note-version cut — its native plane is bounded by the requested `valid_at` and `r` (R3-F26)>, "r": <rcev_ or null>, "p": <position>}`, at most 2048 characters. `b = sha256(canonical({"cursor_version": 1, "capability", "principal_id", "request": <the parsed request without cursor, optional fields null>, "known_at": k, "valid_at": t, "native_cut_at": n, "record_event_watermark": r}))`; `s = sha256(canonical({"grant_digest": <section 6.4 digest or null>, "generation": LINEAGE_READ_GENERATION}))`. `p` is the last emitted item's key: `"n:<family>:<record_id>"`, `"e:<link_id>"` or `"v:<note_version_id>"` (records.lineage), or the canonical JSON array `[at, plane_rank, kind_rank, entry_id]` (issues.timeline). `r` is the timeline's native watermark, computed over the Issue's covered member records under the reader's own Record Event visibility (section 7.3; never an event outside the Issue); null for records.lineage. No HMAC: no authority is carried (section 12, D-02).
- **Backfill source document and digest**: the document is `canonical_json({"schema_version": 1, "source_kind", "source_family", "source_id", "source_ref", "source_version", "facts": <the closed per-kind fact object of section 8.3>})` (ASCII only, so NFC is the identity); the digest is `sha256(b"lineage-backfill-source-v1\n" + document)`; both are computed in SQL by the section 4.2 functions and mirrored in Python with shared golden vectors. **Plan digest**: `sha256(b"lineage-backfill-plan-v1\n" + canonical_json({"schema_version": 1, "run_id", "validator_version", "items": [[item_no, source_digest, classification, reason, candidate_identity] in item_no order]}))`.
- **Request digest** (S1 §5.4): `known_at`, `valid_at` and `effective_at` as the UTC ISO-8601 string of the parsed instant.

## 6. Authority, locks, visibility and the transaction

### 6.1 Authority

S1 §6.1 / S2 §6.1 reused. **Every S3 write is attested** (local operator only, `denied`
before any row and before any replay lookup): `records.associations.contest`,
`records.associations.reinstate`, `issues.handoffs.correct`, `records.backfill.plan`.
The 2 backfill capabilities are also `_OPERATOR_ONLY` and sit behind their own switch
(section 7.7).

**Remote read grant re-check (R3-F13).** `invoke` does not check the grant set
(G1-RD-008), so every lineage read handler — the 3 S3 reads, the widened
`records.lineage`, and the S1/S2 reads `issues.read`, `issues.list`,
`issues.handoffs.list`, `issues.closure_readiness`, `meetings.notes.versions` and
`meetings.notes.read_version` — re-checks that a remote caller holds a grant on that
capability for one of its permitted purposes and otherwise answers **`unsupported`**,
exactly as `_record_events_list` and `_knowledge_plane` do: the capability is hidden from
a client that was never granted it rather than announced as forbidden. (A purpose the
capability does not admit is still `denied` by `invoke`, as S1's
`test_note_body_needs_the_history_purpose` pins.)

### 6.2 Lock order (S2 §6.2, extended)

1. Reserve the `lineage_write_requests` row. A replay returns here.
   1a. `records.backfill.plan` with a `run_id`: the run row `FOR UPDATE`.
   1b. **Every write that writes a fact row** (every S1, S2 and S3 lineage write except `records.backfill.plan`): `SELECT knowledge.lineage_commit_mark(:principal)` — the allocator row lock, held to commit. Taken before any other lock, it serializes a Principal's lineage writers; native writers never take it, so it adds no cycle with them, and no lineage writer waits on another's anchor or head while holding it (section 12, D-20).
2. – 5. As S2 §6.2. Additions: `contest` / `reinstate` take `FOR SHARE` on every Issue the link is in the context of (section 3.2); `issues.handoffs.correct` takes the Issue and the Commitment `FOR SHARE`, then the chain's `:handoff:` advisory key, then reads the chain; `issues.close` also shares the endpoints of every in-context semantic link it evaluates.
6. The `blocks` cycle search (S2 §3.1) reads `active` **and** `contested` `blocks` heads.

Reads take no locks; the horizon is the allocator row's committed value. Because every
fact a read selects has `commit_seq ≤ W` (committed before `H` was read) or is a
pre-S3 row, a multi-statement read under READ COMMITTED sees one consistent fact set.

### 6.3 Transaction order (S2 §6.3, extended)

1. Switch (`_lineage_plane`), authority, strict parse.
2. Request digest; reserve (replay: rebuild from the immutable rows the result names, including a backfill batch from its run and the items classified up to `result_backfill_checkpoint`, which never change once classified).
3. Commit mark (6.2 step 1b).
4. Locks; validation; write-specific checks (transition table 3.1; gate 3.2; correction rules 3.3; backfill 8.3).
5. Write rows; complete the request row with its result and `commit_seq`; commit; deferred triggers verify.

### 6.4 Visibility (CR-008 grant re-evaluation)

A **local** caller (no capability grants) sees every family. A **remote** caller sees a
record family only while it holds a grant, for one of its purposes, on one of the
family's reads (`LINEAGE_FAMILY_READS`, precedent `RECORD_EVENT_FAMILY_READS`):

| Lineage family | Reads (any one) |
| --- | --- |
| `situation` (Issue) | `issues.read`, `issues.list` |
| `meeting`, `meeting_note_version` | `meetings.read`, `meetings.list` |
| `task` | `tasks.read`, `tasks.list` |
| `commitment` | `commitments.read`, `commitments.list` |
| `constraint` | `constraints.read`, `constraints.list` |
| `capture_version` | `capture.read`, `capture.list` |

An evidence anchor is visible iff its source family is (`meeting_note_version` via the
Meeting reads; `capture_version` and legacy `capture` via the Capture reads).

**S1/S2 Issue reads (R3-F13).** Section 6.4 also applies to `issues.read` (a membership
whose member is invisible is withheld), `issues.list` and `issues.read` themselves (an
Issue is served only when `situation` is visible, else `not_found` / `issue_id` or not
listed), `issues.handoffs.list` (needs Commitment visibility, else `not_found` /
`commitment_id`) and `issues.closure_readiness` (a blocker or contested link whose member
or endpoint is invisible is withheld; `ready` is computed over everything, so it stays
`false`). Each of these 4 answers gains one key, `restricted: bool`, true exactly when
something was withheld (no count). At the basis no binding S1/S2 test invokes these reads
as a remote caller (the remote lineage invocations are write refusals and S1's
purpose-denial test); an implementer who finds one that this changes stops and reports it.

**Rules (every lineage read):** an invisible root is
`not_found` / `origin` (as absent); an invisible Issue is never a candidate, never
selectable (`not_found` / `issue_id`) and never a timeline subject; an invisible node is
not emitted, not expanded and not counted, and a typed edge is emitted only when both
endpoints are visible — so a record reachable only through an invisible one is not
reached; an invisible anchor is dropped from its view; a timeline entry about an
invisible record is withheld. Whenever anything was withheld, the answer carries
`restricted_evidence` (a state, never a count or an identifier). **Grant digest:**
`sha256` over the sorted `(capability, purpose)` pairs of the caller's grants on the
reads above and on the called capability; `null` locally. A legacy `capture` anchor
whose root currently has any `restricted_local` version reads `restricted` (S1 F24's
forward rule): a local reader sees it so labelled; for a remote reader it is withheld.

## 7. Capabilities — the exact S3 set

8 new `Capability` members (214 → 222; audit vocabulary 225 → 233) and 1 new `Purpose`
(58 → 59). All are `_SCOPELESS`, family `issues` or `records` → feature `lineage`, and
join `_LINEAGE_CAPABILITIES` (22 → 30). The 6 lineage reads and writes below are
classified `CHATLLM_OPERATOR_DECISION_REQUIRED` with rationale "record lineage S3;
exposure is an operator decision (ADR-015, OD-07)"; the 2 backfill capabilities are
`CHATLLM_CONTROL_PLANE_EXCLUDED` with rationale "operator-only lineage backfill" and are
`_OPERATOR_ONLY`. The 4 writes are in `_WRITE_CAPABILITIES` and
`_IDEMPOTENT_REMOTE_CAPABILITIES`; `records.backfill.plan` is also
`_ADDITIVE_WRITE_CAPABILITIES`; `lineage_backfill` joins `_WRITE_PURPOSES`. No
`CHATLLM_DATA_PROFILE_VERSION` change is expected; if the profile diff test says
otherwise, bump it and record why.

| Capability | W/R | Purpose | Idempotency / authority | Purpose of the call |
| --- | --- | --- | --- | --- |
| `records.associations.contest` | W | `record_lineage_authoring` | key + `expected_revision`, attested | dispute a semantic link |
| `records.associations.reinstate` | W | `record_lineage_authoring` | key + `expected_revision`, attested | resolve a dispute back to active |
| `records.associations.history` | R | `record_lineage_read` | — | one link's revisions with evidence, as of `known_at` |
| `issues.history` | R | `issue_read` | — | an Issue's revisions with closure basis, as of `known_at` |
| `issues.timeline` | R | `issue_read` | — | an Issue's ordered lineage and native events |
| `issues.handoffs.correct` | W | `issue_authoring` | key, attested | retime or void one handoff |
| `records.backfill.plan` | W | `lineage_backfill` (new) | key + `expected_checkpoint`, attested, operator-only | enumerate or classify the next batch |
| `records.backfill.report` | R | `lineage_backfill` | operator-only | a run's counts and items |

`lineage_backfill` is its own purpose because a backfill reads the whole native corpus
of the Principal and writes a durable ledger: no lineage or Issue grant may become one.

### 7.1 Shared shapes (additions)

- Requests are `StrictModel`s / frozen command dataclasses (S1 §7.1 rule; no server-owned field, no `commit_seq`, no `marked_at`, no `grant`).
- `AssociationView` admits `related_context` and `contested`; `EvidenceAnchorView.availability` admits `restricted`. No key changes.
- The `issues.closure_readiness` answer (S2 §7.2) gains `contested_links: [{link_id, relation_type}]` (≤ 100, ordered by `link_id`) and `contested_links_truncated: bool`.
- `HandoffView` (S2 §7.1) keeps `effective_at` as recorded on the event (its S2 meaning, R3-F18) and gains `current_effective_at` (the current effective time at the read's `known_at`: the latest known `retime`'s value, else `effective_at`), `voided: bool` and `correction_ids: [ihcr_]` (≤ 32, in `correction_no` order). `issues.handoffs.list` gains `known_at?` and answers `known_at`; a voided event is still listed, `voided: true`.
- `HandoffCorrectionView` = `{correction_id, handoff_id, correction_no, action, effective_at (retime) | null, reason, evidence: EvidenceAnchorView, recorded_at, authority_class}`.
- `LineagePathStep` (on each lineage node) = `reached_from: RecordRef | null` (null for the root) and `reached_via: {"edge": "typed", "link_id": irl_} | {"edge": "virtual", "edge_type": "meeting_note_version_of"} | null`: the deterministic breadth-first parent (section 7.2), so following `reached_from` from any node reaches the root.

### 7.2 `records.lineage` (S1 §7.2, widened)

**In:** `{origin, issue_id?, max_depth? (0..4, default 4), known_at?, valid_at?, page_size? (10..100), cursor?}`.
`include` stays refused. `cursor` without `page_size` is `invalid_request` / `cursor`;
`page_size` outside 10..100 is `invalid_request` / `page_size` (never clamped). The
minimum of 10 bounds the cost of paging (R3-F15): the repository has no per-Principal
rate limiter (the `rate_limited` error code is used only by the WebAuthn adapter), and
every page recomputes the bounded result, so a whole query costs at most 65 recomputations
(650 items / 10), each under the step 5 deadline.

**Out:**

```text
{root, selected_issue_id, issues_matching_root (<= 20), nodes, typed_edges, virtual_native_edges,
 complete_state, qualifiers: [LineageCompleteness], known_at: T_k|null, valid_at: instant|null,
 lineage_valid_at: T_v|null, native_cut_at: N, next_cursor: str|null}
nodes[i] = S1 node keys + reached_from + reached_via
```

**Algorithm** (S1 §7.2 steps 1–7 with these changes):

1. Visibility (6.4) applies to the root, the candidate Issues and every node, edge and anchor.
2. **As-of selection.** Compute `T_k`, `T_v`, `W(T_v)` once (from the cursor on later pages). Every link, membership and Issue title/state is read at `W(T_v)` from revisions — the latest revision of each link with `commit_seq ≤ W(T_v)` (or pre-S3 with `recorded_at ≤ T_v`) — never from `record_link_heads`. *Live* links are those whose selected revision is `active` or `contested`; they replace S1's "active". Issue nodes and candidates carry the title and state of the Issue revision selected the same way. A reached Meeting's note versions — its pair set and its `meeting_note_version_of` virtual edges — are only those with `recorded_at ≤ N`, the native cut of section 3.4 (never the lineage horizon), with its named residual.
3. **Issue context is carried per breadth-first state.** Each frontier state is `(record, I)` with the one selected Issue *I*; the S1 followable rule is applied per state and *I* never changes, so a shared Meeting (or Project, Series or participant) never expands into another Issue's links (AT-006). `related_context` is followed like any context-scoped link, so it never bridges Issues.
4. **Path explanations.** When a state first reaches a record, the edge and parent that reached it are recorded; ties are broken by the S1 expansion order (frontier `(depth, family, record_id)`, edges `(created_at, link_id)`, then the `meeting_note_version_of` step).
5. **Budgets** (whole query, all pages): 250 nodes, 400 edges (typed plus virtual), 4 depth; per page at most `page_size` items and 512 KiB serialized; a traversal deadline of 2000 ms per page and a 2000 ms `SET LOCAL statement_timeout` per statement. Reaching the node or edge budget stops expansion and sets `truncated_budget`. Reaching the deadline sets `truncated_budget` and **ends paging** (`next_cursor: null`), because a time cut is not reproducible; a statement timeout is `unavailable`. The AT-016 benchmark records, at the `full` scale, the per-page p50/p95 and the total time to page a 650-item result at `page_size` 10 (65 recomputations); it is a recorded expectation, not a service level.
6. **Output order and paging.** The bounded result is ordered nodes `(depth, family, record_id)`, then typed edges by `link_id`, then virtual edges by `(meeting_id, version_number)`. Without `page_size` the S1 single-page rule holds (everything in one answer, the S1 serialized-size loop, `next_cursor: null`). With `page_size` each page carries the next items after `p` until `page_size` items or 512 KiB, and the same top-level keys; `next_cursor` is non-null exactly when items remain.
7. **Cursor checks, in this order** (precedent: record_events U-002): shape, length and version (`invalid_request` / `cursor`); `b` against the binding re-derived from this request and the carried `k`, `t`, `n`, `r` (`conflict` / `cursor` — another Principal's cursor or changed filters land here); `k` after the current horizon, `t` after `k`, `n` after the current server time, or `n` after the request's own `known_at` or `valid_at` when either is given (`invalid_request` / `cursor`; `n` is never compared with `k`, because a current read's native cut is its read time and lies after `T_k = H` by design, R3-F25); `s` against the scope re-derived from the caller's **current** grants and generation — on mismatch the page answers `complete_state: scope_changed_restart_required`, no root, nodes, edges or candidates beyond the request's own `origin`, and `next_cursor: null`; finally `p`: a `p` of the wrong shape or prefix is `invalid_request` / `cursor` (checked with the shape, first); **every well-formed `p` that is not an item of the recomputed result answers `scope_changed_restart_required`** (R3-F14, R3-F23). Neither `b` nor `s` covers `p` and the cursor is unsigned (D-02), so the server cannot tell a `p` that vanished between pages (a native record stopped resolving, or visibility changed) from one a client edited; it does not try, and both get the restart answer, which discloses nothing (any absent `p`, hidden, nonexistent or vanished, answers alike). The whole bounded result is recomputed on each page under the frozen `T_k`, `T_v` and current visibility; the union of pages equals the one-page answer **only while** no grant is revoked and no reached native record stops resolving between pages, and any such change surfaces as `scope_changed_restart_required` or, for an item later than `p`, as the S1 `partial_native_history` of the page that would have carried it.
8. **Completeness**: `restricted_evidence` when anything was withheld (6.4); the S1 codes as before; `complete` only when nothing applies. `qualifiers` lists every applicable code, sorted by precedence.

Native virtual edges stay `meeting_note_version_of` only, cut by the note version's own
`recorded_at` (step 2); see section 12, D-05.

**As implemented (L3).** An origin that is not known at the cut answers `not_found` /
`origin` (an Issue root whose first revision is after `T_k` included); a statement timeout
is raised as `LineageReadTimeoutError` inside the bounded read runner every lineage read
uses, and answers `unavailable` (section 12.1, D-38).

### 7.3 `issues.timeline`, `issues.history`, `records.associations.history`

**`issues.timeline`** — in `{issue_id, known_at?, valid_at?, page_size? (10..100, default 25), cursor?}`;
out `{issue_id, known_at, valid_at, lineage_valid_at, entries: [TimelineEntryView], complete_state, qualifiers, next_cursor}` (`valid_at` the requested value or `T_k`; `lineage_valid_at` = `T_v`, section 3.4).

*Lineage plane*, as of section 3.4: the Issue's revisions (`issue_revision`); its Project
link events (`project_link`); the revisions of its memberships (`membership`); the
revisions of every semantic link **in the Issue's context** at the read's cut (section
3.2's one definition: context = I, an endpoint = I, or null context with both endpoints
inside I) (`association`); its handoff events (`handoff`, at their current effective time,
`voided` as known) and corrections (`handoff_correction`).

*Native plane*, **only when `known_at` is omitted** (section 12, D-04): the Record Events
of the Issue's members at `W(T_v)` — a Task, Commitment, Constraint or Meeting member by
its own family, a note-version member by its Meeting, a Capture-version member by its
Capture — with `occurred_at ≤ valid_at` (the **requested** `valid_at`, at or before
server now; no bound when omitted), never clamped to `T_k` (R3-F02), and with
`sequence_number` at or below the watermark `r` frozen on the first page. At most the
first 250 members by `(family, record_id COLLATE "C")` are covered, beyond that
`truncated_budget`. With an explicit `known_at`, native entries are omitted and the
answer carries `partial_native_history` whenever any member has a native family.

**Native-plane disclosure (R3-F03, R3-F04).** The native read is built with the Record
Event reader's own predicate — `_visible(...)` in `infrastructure/persistence/record_events.py`
with its `_withheld_remotely(...)` clauses (OD-8 restricted memory, the WP-RE-08 capture
classification, the KLP-WP-03 assertion `withheld_remote`) — **imported, not copied**;
the one admitted refactor is exporting that builder under a public name with no change
to its body. **As implemented (L4):** instead of exporting the builder, the native read
itself is a function of the feed module, `record_events.issue_member_events`, which
applies `_visible(...)` unchanged inside the module that owns it (the feed-tables guard
and the `trigger_receipts` precedent keep feed SQL in that module);
`infrastructure/persistence/issue_timeline.py` calls it (section 12.1, D-41). For a remote reader `include_restricted_memory` is false and the families
are the member families the reader can see (section 6.4 intersected with
`RECORD_EVENT_FAMILY_READS`). A withheld event never reaches an entry, the member-budget
`truncated_budget` count or the watermark. **`r` is computed exactly as
`record_events.list` computes its high watermark** — the newest event under that same
predicate, **restricted to the events of the Issue's covered member records** (the same
member set and the same rows the native plane reads), in the same statement as the first
page — so `r` names only an event this timeline itself could show this reader, never an
event of a record outside the Issue, and needs no `record_events.list` grant; `r` is `null`
when no such event exists, and later pages resolve it with the reader's
`resolve_position` after the same visibility check (record_events U-002 step 3).

`TimelineEntryView` = `{entry_id, kind, plane: "lineage"|"native", at, recorded_at, subject: RecordRef|null, action, historical_fields_partial: bool, …kind keys}` where `entry_id`
is the row's own identifier (`irs_`, `ipme_`, `irv_`, `ihnd_`, `ihcr_`, `rcev_`), `at` is
the current effective time for `handoff`, `occurred_at` for `native_event` and
`recorded_at` otherwise, and the kind keys (every other key `null`) are:

| Kind | Keys |
| --- | --- |
| `issue_revision` | `issue_version`, `state`, `title`, `closed_at`, `outcome` (the revision's recorded values) |
| `project_link` | `project_id`, `membership_revision_no`, `link_state` |
| `membership`, `association` | `link_id`, `revision_no`, `relation_type`, `member_role`, `lifecycle_state`, `from`, `to` |
| `handoff` | `handoff_id`, `commitment_id`, `sequence_no`, `from_holder`, `to_holder`, `voided` |
| `handoff_correction` | `handoff_id`, `correction_id`, `correction_action`, `corrected_effective_at` |
| `native_event` | `native: {record_family, record_id, event_kind, record_version, changed_fields, source_capability}`, `recorded_fields` |

`action` is the revision action, membership-event action, `recorded` (handoff), the
correction action, or the Record Event kind. `historical_fields_partial` is `false` for
every lineage entry (its values are the recorded ones) and `true` for a native entry,
which never carries a former or current field value — **except** a Constraint native
event whose `record_version` names a stored Constraint revision: it carries
`recorded_fields = {lifecycle_state, ball_in_court}` from that immutable revision
snapshot (`ball_in_court` rendered exactly as `constraints.read` renders `bic`) and
`historical_fields_partial: false`. That is how a past ball-in-court is read: the
current timeline with `valid_at` (WP-02C "present/past BIC"). A Project link entry
never carries a Project name. Entries carry no evidence anchors (the 2 history reads
do). Order: `(at, plane_rank (lineage 0, native 1), kind_rank (the table order),
entry_id)`, keyset-paged under the section 5 cursor with the section 7.2 step 7 checks.

**`issues.history`** — in `{issue_id, known_at?, page_size? (1..100, default 25), after? (int >= 1)}`;
out `{issue_id, known_at, revisions: [IssueHistoryEntryView], next_cursor: int|null, restricted: bool}`,
ordered by `version` ascending. `IssueHistoryEntryView` = the S1 `IssueRevisionView` keys
plus `closed_at`, `outcome`, `reason` and `evidence: [EvidenceAnchorView]` (the
revision's closure or reopening set, visibility-filtered). A client paging with an
explicit `known_at` (the value the first page returned) reads a fixed set; without one,
later pages may include newer revisions (the S1 list rule). `restricted` is true exactly
when an anchor of this page was withheld (section 6.4; FR3-F04). An Issue the reader may
not see is `not_found` / `issue_id`, as absent.

**`records.associations.history`** — in `{link_id, known_at?, page_size? (1..100, default 25), after? (int >= 1)}`;
out `{link: {link_id, kind, relation_type, from, to, member_role, context_issue_id, created_at}, known_at, revisions: [{revision_no, revision_id, action, lifecycle_state, acceptance_basis, authority_class, reason, evidence: [EvidenceAnchorView], recorded_at}], next_cursor, restricted: bool}`.
Memberships and semantic links alike (a read). A link whose root is not known at
`T_k`, or (remote) whose endpoint is invisible, is `not_found` / `link_id`; so is
(remote) an Issue-scoped link (`context_issue_id` non-null) for a reader without Issue
visibility, because its root names the Issue (FR3-F03). `restricted` is true exactly when
an anchor of this page was withheld (FR3-F04).

**As implemented (L4).** The timeline views are `contracts/v1/issue_timeline.py`
(`IssueTimelineView`, `TimelineEntryView`, `TimelineNativeView`), beside rather than in
`contracts/v1/issues.py`, so the S1 Issue shapes stay free of the Record Event vocabulary
(the S1 scope guard). A native entry's subject is the member it is read for: a note
version's Record Events are its Meeting's and a Capture version's its Capture's, found
through the resolved record's `parent_root_id`. An `association` entry's `subject` is
`null` (its endpoints are `from` and `to`); a `membership` entry's is the member. The
cursor checks (section 7.2 step 7) run before the Issue's existence is read, so a
malformed or foreign cursor answers alike for any `issue_id`. `issues.timeline` is
declared in the memory-row capability registry and its RI-FINAL evidence delta (the
`record_events.provenance` precedent): for a remote caller its native plane passes the
feed's own visibility predicate, whose OD-8 term joins `relationship_memories` and
`relationship_memory_versions`; its families are never `relationship_memory`, so the term
matches no event and no memory column enters the answer (section 12.1, D-41).

### 7.4 Writes

**`records.associations.contest`** — in `{link_id, expected_revision, idempotency_key, reason (1..2000), evidence_anchors ([1..32])}`;
out `{association, replayed}`. Section 3.1 rules; writes revision `n + 1` action
`contest`, state `contested`.

**`records.associations.reinstate`** — same shape; from `contested` only; writes action
`reinstate`, state `active`.

**`records.associations.assert` (S3 delta)** — admits `related_context` (3.1), normalizes
its endpoint order before the request digest is computed (so both orders are one
request under one key), and answers `conflict` / `state` for a contested identity.

**`issues.handoffs.correct`** — in `{handoff_id, action ("retime"|"void"), effective_at? (retime only, ISO-8601 with offset), reason (1..2000), evidence_anchor: EvidenceAnchorInput, idempotency_key}`;
out `{correction: HandoffCorrectionView, handoff: HandoffView (at the new horizon), replayed}`.
The handoff is checked in the S1 §3.2 order (`ihnd_` prefix, then Principal-scoped
existence, `not_found` / `handoff_id`), then its Issue's state (`conflict` / `state` when
closed), then section 3.3.

**`issues.closure_readiness` / `issues.close`** — section 3.2.

### 7.5 Errors (additions to S1 §7.3, S2 §7.3)

| Situation | Code / safe detail |
| --- | --- |
| `known_at` / `valid_at` after now; malformed instant | `invalid_request` / `known_at`, `valid_at` |
| malformed cursor (encoding, version, or a `p` of the wrong shape or prefix), beyond-horizon cursor; cursor without `page_size` | `invalid_request` / `cursor` |
| well-formed `p` not in the recomputed result | success, `complete_state: scope_changed_restart_required`, nothing else disclosed |
| cursor bound to another request or Principal | `conflict` / `cursor` |
| grants or generation changed under a cursor | success, `complete_state: scope_changed_restart_required`, nothing else disclosed |
| remote read without a grant on its own capability | `unsupported` (hides the capability; G1-RD-008 precedent) |
| `page_size` outside 10..100 | `invalid_request` / `page_size` |
| contest of a non-active, reinstate of a non-contested link; assert of a contested identity; correction of a voided handoff | `conflict` / `state` |
| contested link in the Issue's context at close | `conflict` / `closure_gate` |
| void of a handoff that is not the chain's last live event | `invalid_request` / `handoff_id` |
| retime out of order | `invalid_request` / `effective_at` |
| backfill checkpoint moved | `conflict` / `checkpoint` |
| backfill run absent or foreign | `not_found` / `run_id` |
| backfill switch off | `unsupported` |
| ordinary or remote caller on an S3 write or backfill read | `denied` |
| switch off | `unsupported` |

New `SafeDetail` members (`known_at`, `valid_at`, `handoff_id`, `checkpoint`,
`run_id`, and any other named here that is absent) are added with the
code that reports them; reuse an existing member with the same token.

### 7.6 Web (WP-06A S3)

**Routes and views** (new files under `web/` are `git add -f` and `git ls-tree` checked):

- `web/src/app/(app)/work/issues/page.tsx` — Issues index (`issues.list`, state filter, keyset "More"); `IssueList` in `web/src/components/issues/issue-list.tsx`.
- `web/src/app/(app)/work/issues/[issueId]/page.tsx` — `IssueView` (`web/src/components/issues/issue-view.tsx`): breadcrumb "Work › Issues › *title*" as a `nav` with `aria-label="Breadcrumb"`; header from `issues.read` (title, state, Project links, closure outcome when closed); `IssueTimeline` (`issue-timeline.tsx`); `IssueLineageTable` (`issue-lineage-table.tsx`, `records.lineage` with the Issue as origin and `issue_id`); `NoteVersionDrilldown` (`note-version-drilldown.tsx`).
- `web/src/app/(app)/work/meetings/[meetingId]/page.tsx` — the minimal Meeting view: header from the existing `/api/meetings/[meetingId]` (`meetings.read`, decoder exists) and the S1 `RelatedIssuesPanel` with family `meeting` (S1 §7.4's deferred Meeting display; a Meeting in 3 Issues shows the 3-choice radio group).
- `RelatedIssuesPanel` Issue titles link to the Issue view.

**BFF** (one gateway call per view and per page; no per-node or per-edge fetch, no
client-side join): `GET /api/issues` (`issues.list`), `GET /api/issues/[issueId]`
(`issues.read`), `GET /api/issues/[issueId]/timeline?pageSize=&cursor=&knownAt=`
(`issues.timeline`), `GET /api/issues/[issueId]/lineage?pageSize=&cursor=&knownAt=`
(`records.lineage`, origin the Issue). Each uses `workGet` with `strictQuery`, the S1
identifier patterns (`sit_`), a cursor pattern `^[A-Za-z0-9_-]{1,2048}$`, and the S1
projection guard (an answer for another Issue or origin is `upstream_contract_invalid`).
The related-issues route admits family `meeting` (prefix `mtg`).

**Contract and decoders.** `gateway.json` gains `issues.list`, `issues.read`,
`issues.timeline` (107 → 110), each with a synthetic probe; the S1 `records.lineage`
entry's `payloadFields` gain `known_at`, `valid_at`, `page_size`, `cursor`. New strict
decoders `issues.list.ts`, `issues.read.ts`, `issues.timeline.ts`; the
`records.lineage` decoder is widened in lockstep (new keys and the section 3 closed sets;
precedent S2 §7.4), registered in `decode/index.ts` / `types.ts`; `success.json` gains
exactly the 3 new keys and the regenerated `records.lineage` fixture; the parity tests
stay green.

**What the Issue view shows.**

- *Timeline*: entries in server order as a list with time, plain-language action and subject links (Task, Commitment, Meeting and Issue to their views; a Constraint and a note version as text, since their views need context the read does not carry); a native entry with `historical_fields_partial` reads "Field values were not recorded for this change"; a Constraint entry shows its recorded ball-in-court; "Show more" requests the next page with `next_cursor` only.
- *Lineage table*: one accessible table (stacked rows below 640 px) of nodes with family, link, depth and the path explanation "reached from *X* via *relation*"; edges with relation, direction words (S1/S2 words plus "related to" and "contested"), state, basis and actor class; anchors open the note drilldown; "Show more" pages with the cursor.
- *Note drilldown*: the cited note version is opened only on explicit action; when it is not current, the view says "Version *n*; the current version is *m*" and offers a separate "Show the current note" action (`meetings.read`), never mixing the 2 bodies.
- *Messages, never a count*: `restricted_evidence` — "Some related records or evidence are hidden by your access."; `scope_changed_restart_required` — "Your access changed. Start again." with a restart button; `truncated_budget` — "Only part of this Issue's lineage is shown."; `partial_native_history` (as-of timeline) — "Changes to related records are not shown for an earlier point in time."; anchor availability `archived`, `restricted`, `legacy_unversioned` in words.
- *Accessibility*: sections with headings, keyboard-reachable controls, visible focus, no state by colour alone, usable at 375 px, tablet and desktop widths.

**As implemented (L6).**

- The decoders export their closed sets (`RELATION_TYPES`, `ISSUE_STATES`, `LINK_LIFECYCLE_STATES`, `EVIDENCE_AVAILABILITIES`, `LINEAGE_COMPLETENESS` in `records.lineage.ts`; `TIMELINE_ENTRY_KINDS`, `HANDOFF_CORRECTION_ACTIONS` in `issues.timeline.ts`), and `test_the_web_lineage_decoders_admit_exactly_the_server_vocabulary` compares each with its Python enum. `issues.read.ts` decodes both closed answers (with and without `include_members`); the web route asks without members and refuses an answer that carries them. A timeline entry's kind keys must be non-null on their own kind except `closed_at`, `outcome`, `member_role`, `corrected_effective_at` and `recorded_fields`.
- `GET /api/issues` admits `pageSize` (1..100), `after` (`sit_`) and `state`; it does not admit `projectId` (the index has no Project filter). The timeline and lineage routes admit `pageSize` (10..100), `cursor` and `knownAt`, refuse a `cursor` without `pageSize`, and refuse `validAt` (no view asks for one). The lineage route's projection also refuses an answer under another selected Issue.
- The Issue view's components are `components/issues/{issue-list,issue-view,issue-timeline,issue-lineage-table,note-version-drilldown,presentation}.tsx`; the Meeting view is `app/(app)/work/meetings/[meetingId]/meeting-view.tsx` beside its page. The lineage table is 2 tables (Records and Links) with the stacked layout below 640 px.
- *Note drilldown wording:* before the current note is read the drilldown says "Version *n*; a later version is current" (the cited `meetings.notes.read_version` answer says only `is_current`); after the user asks for it with "Show the current note", it says "Version *n*; the current version is *m*" and shows the current body in its own region.
- The S1 panel's selected Issue title is a link whose text is the S1 "Issue: *title*"; a contested link reads "*relation* (contested)". The related-issues route admits `meeting` (`mtg`), so the S1 route-test row that refused `meeting` now refuses a Meeting family with a Commitment id (section 10 note).

### 7.7 Admission switch

S1 §7.5 unchanged: `MY_PA_LINEAGE_ENABLED` (default off) withholds all 30 lineage
capabilities; every S3 handler calls `_lineage_plane` first. The S3 web routes render
nothing (or "not available") on `unsupported`.

**Backfill sub-switch (R3-F12).** `lineage_backfill_enabled: bool = False` in
`bootstrap/settings.py`, env `MY_PA_LINEAGE_BACKFILL_ENABLED` (fails closed like every
setting), passed by `bootstrap/gateway.py` to `ApplicationService`. Following the
`_ENTITY_WRITE_CAPABILITIES` sub-switch precedent, `available_capabilities()` subtracts
`LINEAGE_BACKFILL_CAPABILITIES` unless **both** switches are on (subtracted after the
lineage line, as the entity write half is), and each backfill handler calls a
`_lineage_backfill_plane()` guard after `_lineage_plane()` and before authority,
reservation or replay, answering `unsupported`. Enabling lineage therefore never enables
a backfill; `ops/runbooks/gateway-operations.md` gains the variable. Test environments
turn it on only in the AT-025 and admission tests that need it.

## 8. Old-client rule, compatibility and the backfill

### 8.1 Old clients

- **v1 shapes are byte-identical** (`tasks.*`, `commitments.*`, `constraints.*`, `meetings.*`, `continuity.*`, `record_events.list`). S3 changes no native writer and no native table.
- **S1/S2 lineage contracts** (server-only, never deployed): widened only additively as section 7 lists; every key keeps its meaning. `records.lineage` without the S3 request fields answers the S1 single-page result with 5 added top-level keys (`qualifiers`, `known_at`, `valid_at`, `lineage_valid_at`, `native_cut_at`), `next_cursor` now typed string-or-null (still `null` there), and the 2 node keys; `issues.read`, `issues.list`, `issues.handoffs.list` and `issues.closure_readiness` each gain `restricted` (section 6.4), the last also `contested_links` and `contested_links_truncated`, and `HandoffView` gains 3 keys with `effective_at` unchanged; its remote visibility narrows to section 6.4 (no client holds a lineage grant; section 12, D-21).
- **The strict web client** keeps every existing `gateway.json` entry, decoder and `success.json` key byte for byte except the lockstep `records.lineage` widening (7.6), guarded by the S3 scope test that the decoder's closed sets equal the server vocabulary.
- Any later change to a deployed contract needs a negotiated version (S1 §8).

### 8.2 Serialization of lineage writers

The allocator (6.2 step 1b) serializes one Principal's lineage writes from their mark to
commit. S1/S2 behaviour and refusals are unchanged; concurrent writers now queue instead
of interleaving. Writers of different Principals never wait on each other.

### 8.3 The backfill dry run (WP-03B, CR-014)

**Shape.** 2 operator-only capabilities behind the section 7.7 sub-switch, invoked
through the ordinary CLI transport (`my-pa records.backfill.plan --payload …`;
module-boundaries §5.7: the CLI is not a privileged bypass). `records.backfill.plan` is
attested. **A plan run is a durable write, not a no-op**: its run and item rows are
guarded ledger rows that refuse `DELETE` and `TRUNCATE` and make `downgrade()` refuse
(section 4.3). It writes no link, no fact and no commit mark, and nothing in S3
materializes an item (the apply is deferred, section 11). Tests run it on synthetic
fixtures only; no worker runs it against any other database (section 13).

**`records.backfill.plan`** — in `{run_id?: lbfr_ | null, expected_checkpoint?: int, batch_size? (1..500, default 200), idempotency_key}`;
out `{run: BackfillRunView, items: [BackfillItemView] (this batch), replayed}`.

- *No `run_id`*: creates a run and **enumerates the population in one `INSERT … SELECT` statement** (one snapshot) over the source kinds below, computing each item's `source_version` and `source_digest` in that statement (section 4.2 functions), and in the same statement the census and `commit_seq_cutoff`; state `enumerated`, checkpoint 0. Nothing is classified yet.
- *With `run_id`*: requires `expected_checkpoint = classified_count` (`conflict` / `checkpoint`), classifies the next `batch_size` items in `item_no` order, advances `classified_count`; when every item is classified, sets `plan_digest` and state `classified`. Each call is one transaction: an interrupted call leaves the previous checkpoint, and calling again resumes. Classifying an item first recomputes `knowledge.lineage_backfill_source_digest` for it; a different digest is `unresolved` / `source_changed` (quarantined) whatever the source would otherwise classify as. Otherwise classification is a pure function of the stored source document, so a resumed run and an uninterrupted run produce identical items and `plan_digest` (AT-025).
- **`commit_seq_cutoff`** is the lineage cut of the run: each item's `existing_link_id` / `existing_link_state` (section 4.2) is computed over link revisions known at it (section 3.4), so the report states, for every candidate, whether a link between the same endpoints already exists in any context and in which state, as it stood when the population was frozen — stable whatever lineage writes follow. It is the high-watermark reconciliation of WP-03B for the dry run; lineage writes after it are not this run's facts.

**`records.backfill.report`** — in `{run_id, page_size? (1..100), after? (item_no), classification?}`;
out `{run, census, counts: {per class, per reason, quarantined, per existing_link_state}, late_source_count, items, next_cursor}`.
`late_source_count` counts in-scope sources present now that are not in the frozen
population (written after enumeration; they belong to a new run, never to this one).
`census` is the run's stored enumeration census: per source kind, the number of native
rows examined, and the number enumerated (equal by construction: every in-scope row is
enumerated, section below), plus per kind the reference-shape counts (`asrt_`, `cap_`,
other prefix, not an identifier) of `origin_evidence_ref` and the `project_situation`
consistency counts. Counts and tokens only; no identifier of a hidden row exists (the
caller is the local operator over its own partition).

**Population and classification** (per Principal, at the enumeration snapshot). The
denominator is **every** row of each listed shape — nothing is pre-filtered:

| Source kind | Population | Classification and `reason` |
| --- | --- | --- |
| `task_follow_up` | each Task with a `commitment_id` | `native_virtual_proven` / `native_follow_up` — never a link |
| `constraint_follow_up` | each `project_constraint_relationships` row of type `follow_up_of` | `native_virtual_proven` / `native_constraint_follow_up` |
| `meeting_series` | each Meeting with a series | `native_virtual_proven` / `native_meeting_series` |
| `project_situation` | each `project_situations` row | `native_virtual_proven` / `native_project_situation` when its Situation is a context Situation of the same Principal, its Project exists in the same Principal and (for an Issue) its membership-event ledger has an event for the triplet; otherwise `unresolved` / `project_situation_inconsistent` (quarantined). The S1 principal-composite foreign keys make most mismatches unrepresentable; the check is the census of what remains (orphan or Issue-ledger mismatch) |
| `work_origin_assertion` | each Task or Commitment whose `origin_evidence_ref` matches the `asrt_` `IdKind` pattern in full (population is assigned by identifier shape, not by prefix, R3-F27) | `source_backed_accepted` / `exact_original_span` when the assertion resolves in the Principal, is `accepted` and not superseded, its Capture root is neither archived nor withdrawn, its version is not `restricted_local`, and it cites (`capture_assertion_spans`) 1..32 spans with `processing_text_id IS NULL` and `offset_basis = unicode_code_point_v1` on that version whose re-derived slice of `capture_versions.content` hashes to `quoted_text_sha256` — candidate `originated_from` (record → `capture_version`) with one `origin` anchor per such span; `review_candidate` / `passage_unproven` when the version is exact but no span qualifies (or more than 32 do); `refused` / `assertion_not_current`, `source_withdrawn` or `source_restricted`; `unresolved` / `reference_unresolvable` when the `asrt_` does not resolve in the Principal |
| `work_origin_capture_root` | each Task or Commitment whose `origin_evidence_ref` matches the `cap_` `IdKind` pattern in full | `unresolved` / `no_exact_version` (a root pins no version; S1 §3.1) |
| `work_origin_other` | each Task or Commitment with any other non-null `origin_evidence_ref`: another `IdKind`'s identifier (`mnote_`, `capver_`, `mdoc_`, `rdec_`, …), free text, or text that merely begins `asrt_` or `cap_` without matching the pattern | `unresolved` / `origin_ref_unsupported` (quarantined): the reference is counted, never interpreted; its `source_ref` is the section 4.2 shape-and-digest token, so neither the ledger nor the report carries its text |
| `situation_object_ref` | each element of a context Situation's `object_refs` | `review_candidate` / `object_ref_unproven` when it is the identifier of an owned record of a lineage family; `unresolved` / `reference_unresolvable` otherwise |

`unresolved` and `refused` items are quarantined. `source_backed_accepted` is a
**classification in the report only**: S3 writes nothing for it. `review_candidate` items
are reported only; the review path is the operator's own attested assert with evidence
(S1/S2), after reading the report (section 12, D-07). No item is derived from words,
names, a shared Project, Series, participant or date (OD-05). The source document
(`facts`) per kind is the closed set of native values the classification reads (for
`work_origin_assertion`: the assertion's `state`, `superseded_by_assertion_id`,
`version_id`, root lifecycle state, version classification and each cited span's
`span_id`, offsets, basis, processing text and digest; for `project_situation`: the
Situation kind, both principals and whether the triplet has a membership event). 100 %
of the population is classified when the run is `classified`
(`classified_count = population_count`, a CHECK).

`BackfillRunView` = `{run_id, state, validator_version, population_count, classified_count, plan_digest, source_cutoff_at, created_at, classified_at}`;
`BackfillItemView` = `{item_no, source_kind, source_family, source_id, source_ref, classification, reason, quarantined, candidate_relation, existing_link_id, existing_link_state}`,
where `candidate_relation` is derived from `candidate` (its `relation_type`, null when
there is no candidate) and is not a column. No body, title, description or other
narrative is carried (the Constraint legacy-import redaction precedent).

## 9. File plan, registration and the work split

New modules (resolve exact names against neighbours; no refactor beyond the extractions
named):

- `domain/lineage/vocabulary.py` (widened), `domain/lineage/asof.py` (pure: `KnowledgeCut`, `T_k`/`T_v` rules, precedence), `domain/lineage/cursor.py` (pure: encode, decode, binding, scope digest; golden vectors), `domain/lineage/handoff.py` (chain skips voided events; retime order), `domain/lineage/closure.py` (contested-link condition), `domain/lineage/backfill.py` (pure source document and digests, mirroring the section 4.2 SQL functions; the classification table).
- `application/record_lineage.py` (as-of traversal, paging, path explanations, contest/reinstate, `related_context`), `application/lineage_visibility.py` (section 6.4), `application/issue_timeline.py` (`issues.timeline`), `application/issues.py` (`issues.history`, readiness and close delta), `application/issue_handoffs.py` (`correct`, as-of list), `application/lineage_backfill.py` (plan, report).
- `infrastructure/persistence/record_lineage.py` (as-of reads: `live_links_incident(principal, refs, cut)`, `link_revisions`, mark resolution, `take_commit_mark`), `infrastructure/persistence/issues.py` (history, as-of Issue revisions), `infrastructure/persistence/issue_handoffs.py` (corrections), `infrastructure/persistence/issue_timeline.py` (the lineage and native timeline reads, the Constraint revision snapshot join), `infrastructure/persistence/lineage_backfill.py`; `contracts/v1/record_lineage.py`, `contracts/v1/issues.py` (S3 views), `application/commands.py`, `adapters/normalization.py`, `application/service.py` handlers, `domain/identity/operation.py` / `purpose.py` / `chatllm_capability_policy.py` registrations, `ports.py` (`RecordLineageRepository`, `IssueRepository` additions; `UnitOfWork` gains abstract `issue_timeline` and `lineage_backfill`, implemented or stubbed in every subclass).
- **Every writer calls `take_commit_mark` immediately after a non-replay reservation** (S1 `record_lineage.py` writers, S1/S2 `issues.py`, `issue_handoffs.py`, `issue_work.py`, and the S3 writers); the database trigger makes a missed call still correct but serializes later, so the call is required and pinned by a test.
- Every W1 §2.2 / §5.4 registration step and count pin applies (capability 222, purpose 59, audit vocabulary 233, revision count 121, head literal and head-pin list, `TABLES_SHA256`, `TABLES_ABOVE`, principal-partition guard registry, spelled counts in `adapters/cli/app.py`, `bootstrap/gateway.py`, the architecture index and READMEs, `gateway.json` 110).
- **As implemented.** Beside the modules above, S3 added `domain/lineage_backfill/__init__.py` and `domain/lineage_backfill/vocabulary.py` (L1, D-34), `contracts/v1/issue_timeline.py` (L4, section 7.3 note) and `contracts/v1/lineage_backfill.py` (L5), and the feed function `record_events.issue_member_events` in `infrastructure/persistence/record_events.py` (L4, D-41). `ports.py` methods a test double does not implement raise `NotImplementedError` by default (the K1 precedent; D-37). The web files are listed in the section 7.6 note.

**Work split** (serial; each package testable alone; one worker at a time):

| Worker | Owns | Delivers |
| --- | --- | --- |
| **L1** | the revision, `tables.py`, `IdKind`, vocabulary, all registries, settings and count pins, `ports.py` stubs | section 4 in full, including the 2 backfill SQL functions with `domain/lineage/backfill.py::source_document` and their shared golden vectors; registration of all 8 names and the backfill sub-switch (unbuilt ones answer `unsupported` until their worker, and `capabilities.get` stays truthful); `take_commit_mark` and its call in every S1/S2 writer; mark resolution and horizon in persistence; `domain/lineage/asof.py`; tests: commit marks, S3 integrity guards, S3 migration, backfill digest parity, the S1/S2 lockstep moves |
| **L2** | link and handoff writes | contest/reinstate and the transition table; `related_context`; the in-context predicate (section 3.2) and the contested gate, readiness and frozen-closed rules; the one-line widening of the S1 head-based reader (`active_links_incident` selects `LIVE_LINK_STATES`), so a contested link is followed and shown before L3 replaces that reader; handoff correction and the as-of `issues.handoffs.list`; tests: contest/reinstate, related context, handoff corrections, S3 races, S3 attested writes (writes part) |
| **L3** | the as-of read core and visibility | widened `records.lineage` (as-of over revisions, note-version cut, visibility, paging, cursor, path explanations, budgets, deadline); section 6.4 visibility and the grant re-check on every lineage read, including the S1/S2 Issue reads; `issues.history`; `records.associations.history`; `domain/lineage/cursor.py`; tests: bitemporal (AT-008), projection rebuild (AT-014 rebuild row, which needs L2's contest and this read), reverse roots (AT-001 S3), cursor revocation (AT-011, lineage rows), isolation (AT-006 S3), history, bounds, query plans, benchmark, S3 attested writes (read rows) |
| **L4** | the timeline | `issues.timeline` (lineage plane with the in-context predicate, native plane through the exported Record Event predicate, Constraint snapshots, its cursor and watermark); tests: AT-001/AT-013 timeline row, the timeline rows of AT-011 |
| **L5** | the backfill dry run | `records.backfill.plan` and `records.backfill.report` on L1's functions; classification and census; tests: AT-025 |
| **L6** | web, hardening, docs | section 7.6 in full, `gateway.json`, decoders, BFF routes, e2e and accessibility, the S3 scope guard, AT-023/AT-024 web rows, docs sync ("as implemented" notes), full tiers |

## 10. Acceptance-test crosswalk

Same conventions as S1 §10 and S2 §10 (tier = marker selection; FAST = no marker; names
binding; a renamed test updates this table in the same commit; paths new unless marked
existing). `tests/architecture/test_record_lineage_s3_scope.py` parses this table the
way the S2 scope guard parses S2 §10.

| AT (S3 part) | Module | Test functions | Tier |
| --- | --- | --- | --- |
| AT-014 (knowledge clock) | `tests/database/test_lineage_commit_marks.py` | `test_every_lineage_write_takes_exactly_one_commit_mark`; `test_every_writer_takes_its_mark_before_any_other_lock`; `test_a_replay_takes_no_commit_mark`; `test_a_refused_write_leaves_no_commit_mark`; `test_commit_marks_are_contiguous_and_strictly_increasing`; `test_a_fact_row_cannot_carry_a_forged_commit_seq`; `test_every_fact_row_names_an_existing_mark`; `test_the_horizon_excludes_an_in_flight_write`; `test_a_past_known_at_answer_never_changes_after_later_commits`; `test_pre_s3_rows_are_known_by_their_recorded_at` | database |
| AT-014 (rebuild) | `tests/recovery/test_lineage_projection_rebuild.py` | `test_a_write_killed_before_commit_leaves_no_mark_head_or_request`; `test_rebuilt_heads_equal_stored_heads_after_s3_actions`; `test_the_as_of_read_at_the_horizon_equals_the_head_read`; `test_repeated_rebuilds_are_byte_identical`; `test_a_side_channel_head_edit_is_refused`; `test_marks_requests_and_facts_are_consistent` | database + recovery |
| AT-008 | `tests/database/test_lineage_bitemporal.py` | `test_known_at_before_a_correction_shows_the_old_belief`; `test_known_at_after_a_correction_shows_the_corrected_past`; `test_a_retimed_handoff_moves_the_holder_only_for_later_knowledge`; `test_a_voided_handoff_is_present_before_and_absent_after_its_void`; `test_lineage_valid_at_is_bounded_by_known_at`; `test_known_at_or_valid_at_after_now_is_refused`; `test_a_note_saved_after_known_at_leaves_the_answer_unchanged`; `test_a_current_read_shows_a_note_saved_after_the_lineage_horizon`; `test_a_link_revision_takes_effect_at_its_commit_mark`; `test_issue_titles_and_states_are_read_at_known_at`; `test_an_as_of_read_writes_nothing` | database |
| S2 residual (handoff correction) | `tests/database/test_issue_handoff_corrections.py` | `test_a_retime_needs_a_handoff_anchor_and_stays_in_order`; `test_only_the_last_live_handoff_can_be_voided`; `test_a_void_needs_a_contradicting_anchor`; `test_a_voided_handoff_is_not_the_chain_holder`; `test_a_correction_of_a_voided_handoff_is_refused`; `test_a_correction_on_a_closed_issue_is_refused`; `test_handoffs_list_reports_corrections_at_known_at`; `test_a_foreign_handoff_answers_like_an_absent_one` | database |
| AT-007 (S3) + S2 residual (contest) | `tests/database/test_lineage_contest_reinstate.py` | `test_contest_needs_a_contradicting_exact_anchor`; `test_contest_then_reinstate_restores_active`; `test_reinstate_reapplies_the_relation_evidence_rule`; `test_a_contested_identity_cannot_be_asserted_again`; `test_an_ended_link_cannot_be_reinstated`; `test_a_membership_cannot_be_contested`; `test_a_contested_link_in_the_issue_context_blocks_closure`; `test_closure_readiness_lists_contested_links`; `test_contest_in_a_closed_issue_context_is_refused`; `test_a_contested_blocks_link_still_refuses_a_cycle`; `test_a_contested_link_reads_as_contested_in_lineage`; `test_a_contested_link_naming_the_issue_as_endpoint_blocks_closure`; `test_a_contested_null_context_link_inside_the_issue_blocks_closure`; `test_a_closed_issue_refuses_contest_of_a_null_context_link_inside_it` | database |
| S2 residual (`related_context`) | `tests/database/test_related_context.py` | `test_related_context_is_stored_once_in_canonical_order`; `test_related_context_needs_a_context_and_both_endpoints_inside`; `test_related_context_needs_corroborating_exact_evidence`; `test_a_related_context_self_link_is_refused`; `test_related_context_is_never_followed_across_issues`; `test_mixed_case_endpoints_are_ordered_by_code_point` | database |
| AT-001 (S3 part) | `tests/integration/test_issue_lineage_reverse_roots.py` | `test_every_root_yields_the_same_graph_at_one_known_at_and_valid_at`; `test_the_stage_9_answer_of_the_12_stage_9_roots_is_unchanged_after_stage_14`; `test_m4_and_n4_at_the_stage_9_cut_match_no_issue`; `test_paging_from_every_root_exhausts_to_the_one_page_answer`; `test_every_node_explains_its_path_to_the_root`; `test_a_remote_reader_without_the_meeting_grant_sees_no_note_node_and_no_count` | database |
| AT-001 + AT-013 (timeline) | `tests/integration/test_issue_timeline.py` | `test_the_timeline_orders_the_fourteen_stages`; `test_a_renamed_task_is_a_partial_event_never_its_title`; `test_a_constraint_event_carries_its_recorded_ball_in_court`; `test_past_ball_in_court_is_read_at_valid_at`; `test_an_as_of_timeline_omits_native_events_and_says_partial`; `test_a_project_link_entry_carries_no_project_name`; `test_a_timeline_never_names_another_issues_record`; `test_timeline_pages_reconstruct_the_whole_timeline`; `test_a_native_change_after_the_horizon_is_shown_at_a_later_valid_at`; `test_association_entries_use_the_issue_context_definition` | database |
| AT-011 | `tests/security/test_lineage_cursor_revocation.py` | `test_pages_under_one_cursor_reconstruct_the_one_page_answer`; `test_a_write_between_pages_changes_no_later_page`; `test_a_revoked_family_grant_answers_restart_required_without_identifiers`; `test_a_revoked_read_grant_is_unsupported`; `test_a_cursor_of_another_principal_is_conflict`; `test_a_cursor_with_changed_filters_is_conflict`; `test_a_cursor_with_a_tampered_cut_is_conflict` (edits `k` or `t`, which `b` binds); `test_a_malformed_cursor_is_invalid_request` (edits the encoding, the version, or `p` into a wrong shape or prefix); `test_an_unknown_well_formed_position_answers_restart_required` (edits `p` to a well-formed key of no item); `test_a_cursor_beyond_the_horizon_is_invalid_request` (a `k` re-bound by the test to a future instant); `test_a_vanished_emitted_item_answers_restart_required`; `test_a_current_read_pages_after_the_lineage_horizon` (a lineage write, a wait, then a paged current read followed to the end); `test_restricted_nodes_are_neither_counted_nor_identifiable`; `test_a_timeline_cursor_is_bound_and_revoked_the_same_way`; `test_a_timeline_cursor_names_no_hidden_event`; `test_withheld_record_events_never_reach_a_timeline_entry_count_or_watermark`; `test_s1_and_s2_issue_reads_apply_family_visibility_for_remote_readers` | database |
| AT-011 (section 6.4 remote reads, FR3) | `tests/security/test_lineage_remote_visibility.py` | `test_handoff_pages_never_name_a_withheld_handoff`; `test_memberships_truncated_counts_only_visible_members`; `test_a_timeline_without_commitment_visibility_shows_no_handoff_or_correction`; `test_readiness_withholds_a_contested_link_to_an_invisible_record`; `test_association_history_with_an_invisible_endpoint_is_not_found`; `test_issue_history_without_issue_visibility_is_not_found`; `test_association_history_of_an_issue_scoped_link_needs_issue_visibility`; `test_history_reads_say_restricted_when_evidence_is_withheld`; `test_a_handoff_scan_stops_at_its_bound_without_naming_a_withheld_handoff`; `test_a_membership_scan_stops_at_its_bound`; `test_a_handoff_list_statement_timeout_answers_unavailable`; `test_an_issue_read_statement_timeout_answers_unavailable` | database |
| AT-006 (S3 part) | `tests/integration/test_issue_context_isolation_asof.py` | `test_a_three_issue_meeting_pages_only_its_issue_at_known_at`; `test_a_shared_meeting_never_carries_another_issue_context_across_pages`; `test_an_issue_chosen_from_the_meeting_view_reads_only_its_records` | database |
| AT-007 (history) | `tests/integration/test_issue_history.py` | `test_history_lists_every_revision_with_its_closure_basis`; `test_history_at_known_at_omits_later_revisions`; `test_history_pages_by_version`; `test_association_history_lists_every_revision_with_its_evidence`; `test_a_foreign_issue_or_link_history_is_not_found` | database |
| AT-016 | `tests/database/test_lineage_bounds.py` | `test_each_page_stays_within_its_item_and_byte_budget`; `test_node_and_edge_budgets_answer_truncated_budget`; `test_a_deadline_hit_answers_truncated_budget_without_a_cursor`; `test_expansion_order_is_deterministic_on_a_dense_hub`; `test_a_high_degree_meeting_never_fans_out_to_other_issues`; `test_page_size_below_the_minimum_is_refused`; `test_mixed_case_link_ids_page_in_code_point_order` | database |
| AT-016 (plans) | `tests/database/test_lineage_query_plans.py` | `test_incident_link_reads_use_the_endpoint_indexes`; `test_as_of_revision_reads_use_the_revision_key`; `test_mark_resolution_uses_the_marked_at_index`; `test_timeline_reads_use_the_issue_and_record_event_indexes` | database |
| AT-016 (benchmark, recorded, not an SLA) | `tests/database/test_lineage_benchmark.py` | `test_records_the_synthetic_scale_benchmark` (scale from `MY_PA_LINEAGE_BENCHMARK_SCALE`: `small` by default, `full` = 100000 records and 1000000 links, run once locally and recorded, including the per-page p50/p95 and total time to page 650 items at `page_size` 10) | database + slow |
| AT-025 | `tests/database/test_lineage_backfill.py` | `test_every_source_in_scope_is_classified_once`; `test_every_origin_reference_is_enumerated_and_unsupported_ones_are_unresolved`; `test_a_plan_writes_no_link_fact_or_mark`; `test_an_exact_original_span_origin_is_source_backed_in_the_report_only`; `test_a_normalized_text_span_is_only_a_review_candidate`; `test_object_refs_are_never_accepted`; `test_a_capture_root_origin_is_unresolved`; `test_an_inconsistent_project_situation_is_quarantined`; `test_existing_links_are_reported_in_any_context_and_state_at_the_cutoff`; `test_an_interrupted_plan_resumes_to_the_same_plan_digest`; `test_a_source_changed_after_enumeration_is_quarantined`; `test_a_late_source_is_reported_not_classified`; `test_the_census_counts_every_examined_row`; `test_the_report_carries_no_origin_reference_text`; `test_no_candidate_comes_from_words_projects_series_or_dates`; `test_backfill_is_operator_only_attested_and_behind_its_own_switch` | database |
| AT-025 (digest parity) | `tests/database/test_lineage_backfill_digest_parity.py` | `test_sql_source_document_matches_the_golden_vectors`; `test_sql_source_digest_matches_python`; `test_a_non_ascii_non_nfc_free_text_ref_digests_alike_in_sql_and_python` | database |
| AT-012 (S3 guards) | `tests/database/test_lineage_s3_integrity_guards.py` | `test_s3_immutable_tables_refuse_update_and_delete` (2 tables); `test_s3_tables_refuse_truncate` (5 tables, each holding a row); `test_the_allocator_only_advances_by_one`; `test_a_commit_mark_is_its_allocation`; `test_a_link_revision_follows_the_s3_transitions`; `test_one_live_head_per_identity_includes_contested`; `test_a_related_context_root_is_canonical_and_scoped`; `test_a_retime_must_stay_in_order_in_the_database`; `test_only_the_last_live_handoff_can_be_voided_in_the_database`; `test_new_handoffs_follow_the_last_live_holder`; `test_a_backfill_run_moves_forward_only`; `test_a_backfill_item_is_settled_once`; `test_an_s3_write_request_completes_once` | database |
| AT-012 (migration) | `tests/schema/test_record_lineage_s3_migration.py` | FAST: `test_the_revision_is_the_single_head_on_d020b532ad7d`; `test_the_revision_imports_no_domain_module`; `test_frozen_ddl_names_every_declared_constraint`; `test_before_texts_are_byte_copies_of_the_s2_texts`; `test_at_vocabulary_adds_exactly_the_s3_names`; `test_offline_downgrade_refuses_first`. DB: `test_empty_to_head`; `test_s2_head_with_rows_upgrades_and_seeds_the_horizon`; `test_downgrade_refuses_while_s3_rows_exist`; `test_downgrade_restores_every_s2_text`; `test_each_downgrade_refusal_family_alone_refuses` (8 cases) | FAST + migration markers |
| AT-012 (races) | `tests/concurrency/test_lineage_s3_races.py` | `test_two_writers_of_one_principal_serialize_on_the_allocator`; `test_writers_of_two_principals_do_not_wait`; `test_contest_racing_a_close_serializes`; `test_a_void_racing_a_new_handoff_serializes`; `test_a_reader_never_sees_a_half_committed_mark` | database |
| AT-023 (S3) | `tests/contract/test_lineage_s3_capability_admission.py` | `test_s3_capabilities_are_operator_decision_required`; `test_backfill_capabilities_are_operator_only_and_control_plane_excluded`; `test_the_backfill_sub_switch_withholds_both_backfill_capabilities`; `test_s3_requests_reject_server_owned_fields`; `test_existing_v1_shapes_are_unchanged_by_s3`; `test_s1_and_s2_views_keep_every_key`; `test_records_lineage_without_s3_fields_keeps_the_s1_answer`; `test_switch_off_withholds_every_s3_capability`; `test_the_web_routes_call_exactly_the_capabilities_mcp_serves` | FAST |
| AT-023 (S3, DB) | `tests/database/test_lineage_s3_attested_writes.py` | `test_an_ordinary_remote_client_is_denied_every_s3_write`; `test_a_replayed_s3_write_from_an_ordinary_client_is_denied_before_the_replay_lookup`; `test_switch_off_answers_unsupported_for_every_s3_capability`; `test_every_s3_capability_answers_a_foreign_subject_like_an_absent_one`; `test_a_remote_lineage_read_without_its_grant_is_unsupported`; `test_cross_principal_reads_disclose_nothing` | database |
| (domain) | `tests/unit/test_lineage_s3_domain.py` | `test_cursor_golden_vectors_and_malformed_tokens` (including a timeline cursor with `n: null`); `test_the_binding_changes_with_every_bound_field`; `test_the_scope_digest_changes_with_family_grants_and_generation`; `test_known_and_valid_cut_rules`; `test_link_transition_table`; `test_related_context_canonical_order`; `test_in_issue_context_predicate`; `test_backfill_source_document_golden_vectors`; `test_handoff_chain_skips_voided_events`; `test_backfill_classification_table`; `test_completeness_precedence` | FAST |
| AT-024 (S3, web decoders) | `web/src/lib/api/decode/capabilities/issues.timeline.test.ts`; `web/src/lib/api/decode/capabilities/issues.read.test.ts`; existing `web/src/lib/api/decode/capabilities/records.lineage.test.ts` | `decodes an Issue timeline page`; `refuses an unknown timeline entry kind`; `decodes an Issue with its Project links`; `decodes an S3 lineage page with a cursor and path steps`; `refuses a lifecycle state outside the S3 vocabulary` | vitest |
| AT-024 (S3, web components) | `web/src/components/issues/issue-timeline.test.tsx`; `web/src/components/issues/issue-lineage-table.test.tsx`; `web/src/components/issues/note-version-drilldown.test.tsx`; existing `web/src/components/work/related-issues.test.tsx` | `renders timeline entries in server order and labels partial native entries`; `shows the hidden-data message without a count`; `requests the next timeline page with the cursor only`; `renders nodes with their path explanations and record links`; `shows the restricted, truncated and restart messages`; `opens a cited note version only on explicit action and offers the current note separately`; `renders a contested relation and a related context` | vitest |
| AT-024 (S3, routes and views) | `web/src/app/api/issues/issue-routes.test.ts`; `web/src/app/(app)/work/meetings/[meetingId]/meeting-view.test.tsx` | `calls issues.timeline once per page with only the cursor and page size`; `calls records.lineage once with the Issue as origin`; `refuses unknown query fields and malformed cursors without a gateway call`; `mounts the related-Issue panel on the Meeting view` | vitest |
| AT-024 (S3, browser) | `web/e2e/lineage-issue-timeline.spec.ts` | `the Issue page is keyboard reachable at phone, tablet and desktop width`; `a Meeting in 3 Issues asks for one before showing lineage`; `the Issue page has no detectable accessibility violations` | playwright (own `npm run e2e`, seeded synthetic data) |
| AT-026 (S3) | `tests/architecture/test_record_lineage_s3_scope.py` | `test_s3_adds_no_record_event_family`; `test_s3_modules_stage_no_lineage_record_event`; `test_every_s3_crosswalk_test_exists`; `test_the_web_lineage_decoders_admit_exactly_the_server_vocabulary` | FAST |
| AT-026 (regression) | existing `tests/database/test_record_event_provenance.py` | existing `test_unknown_foreign_withheld_and_non_knowledge_events_answer_alike` (unchanged, green) | database |

**S1/S2 regressions (binding, unchanged except lockstep moves):** every test of S1 §10
and S2 §10 and every v1 suite. Admitted edits, each keeping its test name and assertion:
the head literal and revision count (120 → 121) in every head-pin file and the head-pin
list (gaining the S3 migration test); count pins (`Capability` 214 → 222, `Purpose`
58 → 59, audit vocabulary 225 → 233, `TABLES_SHA256`, permitted pairs, tool, builder,
command-union, exempt-property, operator-decision and control-plane-excluded counts,
`gateway.json` 107 → 110, docs count claims); registry additions for the 8 names in the
suites S2 D-18 (c) lists; S1/S2 lineage tests narrowed to the S1/S2 subset of a widened
set (`declared` switch sets, `S1_LINEAGE_WRITE_CAPABILITIES`, the S2 lineage write set,
AT vocabulary checks of the S1/S2 migration suites); the S1/S2 migration suites accept a
constraint, column, function body or index predicate owned by the S3 revision; the
S1/S2 truncate probes also truncate the 5 S3 tables with their own refusals disabled;
the S1 `records.lineage` read-contract tests accept the 5 added top-level keys and 2
node keys, and the S1/S2 Issue-read and handoff contract tests the keys listed in section
8.1. No assertion is removed without its S1/S2 equivalent, no skip or xfail is
added. In particular the S1 vertical test
`tests/integration/test_issue_lineage_s1_vertical.py::test_reverse_read_from_m1_n1_c1_and_issue_yields_one_graph`
(a note saved after the last lineage write is a virtual edge of a current read) stays
binding and green unchanged (R3-F20). Also existing and binding: `tests/contract/test_bff_gateway_contract_parity.py`,
`tests/contract/test_bff_success_decoder_parity.py`,
`web/src/lib/api/decode/registry.test.ts`.

**As implemented (L6).** Every row above exists (`test_every_s3_crosswalk_test_exists`,
which skips no row and reads Python and TypeScript modules alike). The `AT-024 (S3,
browser)` spec runs in each geometry project (`desktop`, `tablet`, `mobile`) with its own
`npm run e2e`; the `mobile` project is the `Pixel 7` emulation profile, not a resized
desktop window. Lockstep edits beyond the list above, each keeping its test name: the S1
`web/src/app/api/records/related-issues-route.test.ts` row that refused family `meeting`
now refuses a Meeting family with a Commitment id (section 7.6 admits `meeting`), with a
new row proving `meeting` is admitted; `web/e2e/global-setup.ts` warms the 3 new pages;
`success.json` and `tests/contract/test_bff_success_decoder_parity.py` gain the 3 new
capabilities. The query-plan rows (`AT-016 (plans)`) were proved red by dropping each
relied-on index in the test's scratch database (section 12.1, D-41).

**AT-001 S3 part, concretely.** On the S2 14-stage fixture:

- With `known_at` = the horizon after stage 14 and `valid_at` = the same, `records.lineage` from each of M1, M2, M3, M4, N1, N2, N3, N4, C1, C2, C3, T1, X1 and I returns one node set, one typed-edge `link_id` set, one virtual-edge set and `complete`.
- With `known_at` = `H₉`, the horizon after stage 9, the **12 roots that exist and are related at stage 9** (M1, M2, M3, N1, N2, N3, C1, C2, C3, T1, X1 and I) each return the stage-9 graph, both before and after stages 10–14 commit. Each read passes `known_at = H₉`, so the native cut is `H₉` and N1b is included exactly when its `recorded_at ≤ H₉` (section 3.4).
- M4 and N4 exist only from stage 12. After stage 14, a read at `H₉` from either of them answers as follows:
  - with `issue_id = I`: `not_found` / `issue_id` (no Issue matches at that cut);
  - without it: no Issue context (`issues_matching_root: []`, the S1 one-hop read with nothing to follow), and no N4 virtual edge, because N4's `recorded_at` is after `H₉`.
- Paging each root with `page_size` 10 and following `next_cursor` to null yields exactly the one-page answer.
- Every node's `reached_from` chain ends at its root.
- `issues.timeline` lists the stage writes in stage order.
- A remote reader holding `records.lineage`, `issues.read`, `tasks.read`, `commitments.read` and `constraints.read`, but no Meeting read, sees:
  - no Meeting or note node;
  - no `discusses` edge;
  - no note anchor;
  - `restricted_evidence`, with no count anywhere in the answer.

**Prove-red expectations** (break exactly that one guard, show the named test red for
that reason, restore; a green prove-red is reported as redundancy, a masked test or an
unreachable hazard, never as "covered"):

| Guard | Break | Test that must redden |
| --- | --- | --- |
| `a_lineage_fact_takes_its_commit_mark` | let a supplied `commit_seq` through | `test_a_fact_row_cannot_carry_a_forged_commit_seq` |
| `a_lineage_fact_names_its_commit_mark` (FK) | drop the FK on `record_link_revisions` | `test_every_fact_row_names_an_existing_mark` |
| `a_commit_sequence_advances_by_one` | return NEW unconditionally | `test_the_allocator_only_advances_by_one` |
| `a_commit_mark_is_its_allocation` | return NEW unconditionally | `test_a_commit_mark_is_its_allocation` |
| horizon cap on `known_at` | use server now instead of `last_marked_at` | `test_the_horizon_excludes_an_in_flight_write` |
| `marked_at` monotonicity | use `clock_timestamp()` alone; the test seeds the allocator row with `last_marked_at` in the future, so only the `greatest(…)` term keeps the trigger satisfied | `test_commit_marks_are_contiguous_and_strictly_increasing` |
| as-of selection | read heads instead of revisions at `W` | `test_a_past_known_at_answer_never_changes_after_later_commits` |
| writer's early `take_commit_mark` | remove it from `issues.memberships.add` | `test_every_writer_takes_its_mark_before_any_other_lock` |
| `a_link_revision_follows_an_active_predecessor` (S3 body) | admit `reinstate` from `active` | `test_a_link_revision_follows_the_s3_transitions` |
| one live head index predicate | restore `= 'active'` | `test_one_live_head_per_identity_includes_contested` |
| contested identity at assert | return the head with `created: false` | `test_a_contested_identity_cannot_be_asserted_again` |
| contested gate condition | skip it | `test_a_contested_link_in_the_issue_context_blocks_closure` |
| contest evidence rule | admit a set without `contradicts` | `test_contest_needs_a_contradicting_exact_anchor` |
| cycle search reads contested heads | read active heads only | `test_a_contested_blocks_link_still_refuses_a_cycle` |
| `a_related_context_is_canonical_and_scoped` | drop the CHECK (direct insert) | `test_a_related_context_root_is_canonical_and_scoped` |
| `related_context` inside rule | skip it | `test_related_context_needs_a_context_and_both_endpoints_inside` |
| `a_handoff_correction_is_admissible` | return NEW unconditionally | `test_a_retime_must_stay_in_order_in_the_database` |
| void only the last live event (application) | skip the check; the test asserts the application's `invalid_request` / `handoff_id` and that no correction `INSERT` was issued (a statement recorder on the connection), so the trigger's later refusal cannot mask the break | `test_only_the_last_live_handoff_can_be_voided` |
| `a_handoff_follows_its_predecessor` (S3 body) | restore the S2 body | `test_new_handoffs_follow_the_last_live_holder` |
| corrections honoured at `known_at` | ignore corrections in reads | `test_known_at_after_a_correction_shows_the_corrected_past` |
| visibility pruning | emit invisible nodes | `test_restricted_nodes_are_neither_counted_nor_identifiable` |
| handoff pages over visible entries (FR3-F01) | take `next_cursor` from the unfiltered repository page | `test_handoff_pages_never_name_a_withheld_handoff` |
| `memberships_truncated` over visible members (FR3-F01) | count every membership | `test_memberships_truncated_counts_only_visible_members` |
| timeline handoff Commitment visibility (FR3 M8) | drop the `sees(commitment)` check in `_handoff_entries` | `test_a_timeline_without_commitment_visibility_shows_no_handoff_or_correction` |
| readiness contested-link endpoints (FR3 M12) | show every contested link | `test_readiness_withholds_a_contested_link_to_an_invisible_record` |
| link-history endpoint visibility (FR3 M13) | drop the endpoint clause of the `not_found` check | `test_association_history_with_an_invisible_endpoint_is_not_found` |
| Issue-history Issue visibility (FR3 M17) | drop `not visibility.sees(issue_ref)` | `test_issue_history_without_issue_visibility_is_not_found` |
| Issue-scoped link history needs Issue visibility (FR3-F03) | skip the context-Issue check | `test_association_history_of_an_issue_scoped_link_needs_issue_visibility` |
| history `restricted` (FR3-F04) | answer `restricted: false` in either history read | `test_history_reads_say_restricted_when_evidence_is_withheld` |
| handoff scan bound (FR3-F08) | remove the bound; or take the cursor from the unfiltered page at the bound | `test_a_handoff_scan_stops_at_its_bound_without_naming_a_withheld_handoff` |
| membership scan bound and keyset (FR3-F08) | remove the bound; or re-read from the start each batch | `test_a_membership_scan_stops_at_its_bound` |
| Issue-read statement timeout (FR3-F08) | drop the lineage `_run` timeout classification; or skip `bound_read_statements` in `issues.handoffs.list` | `test_a_handoff_list_statement_timeout_answers_unavailable` |
| `issues.read` statement timeout (FR3-F10, mutant P6) | delete the `bound_read_statements` line in `_issues_read` | `test_an_issue_read_statement_timeout_answers_unavailable` |
| scope digest | omit the grant digest from `s` | `test_a_revoked_family_grant_answers_restart_required_without_identifiers` |
| binding digest | omit `principal_id` from `b` | `test_a_cursor_of_another_principal_is_conflict` |
| horizon check on a cursor | skip it | `test_a_cursor_beyond_the_horizon_is_invalid_request` |
| grant re-check in read handlers | skip it in `records.lineage`; skip it in `issues.read` | `test_a_revoked_read_grant_is_unsupported`; `test_s1_and_s2_issue_reads_apply_family_visibility_for_remote_readers` |
| issue context per state | follow every live incident link | `test_a_shared_meeting_never_carries_another_issue_context_across_pages` |
| deadline ends paging | keep the cursor on a deadline hit | `test_a_deadline_hit_answers_truncated_budget_without_a_cursor` |
| native plane omitted at explicit `known_at` | include it | `test_an_as_of_timeline_omits_native_events_and_says_partial` |
| native entries carry no values | render a current title | `test_a_renamed_task_is_a_partial_event_never_its_title` |
| `a_backfill_run_moves_forward` / `a_backfill_item_is_settled_once` | return NEW unconditionally, each in turn | `test_a_backfill_run_moves_forward_only` / `test_a_backfill_item_is_settled_once` |
| plan resumability | classify by wall time | `test_an_interrupted_plan_resumes_to_the_same_plan_digest` |
| source-changed quarantine | skip the digest re-derivation | `test_a_source_changed_after_enumeration_is_quarantined` |
| span basis rule | admit a normalized-text span | `test_a_normalized_text_span_is_only_a_review_candidate` |
| note-version cut (R3-F01, R3-F20), both directions | read every current note version of a reached Meeting; and, separately, cut by `T_v` (the lineage horizon) when `known_at` is omitted | `test_a_note_saved_after_known_at_leaves_the_answer_unchanged`; `test_a_current_read_shows_a_note_saved_after_the_lineage_horizon` (and the S1 `test_reverse_read_from_m1_n1_c1_and_issue_yields_one_graph`) |
| native plane valid cut (R3-F02) | bound native entries by `T_v` | `test_a_native_change_after_the_horizon_is_shown_at_a_later_valid_at` |
| Record Event withholding reused (R3-F03) | build the native read with family visibility only | `test_withheld_record_events_never_reach_a_timeline_entry_count_or_watermark` |
| timeline watermark under the reader's predicate (R3-F04) | take `r` as the Principal's latest event | `test_a_timeline_cursor_names_no_hidden_event` |
| in-context predicate (R3-F05) | use `context_issue_id = I` only, in the gate | `test_a_contested_null_context_link_inside_the_issue_blocks_closure` (the endpoint case `test_a_contested_link_naming_the_issue_as_endpoint_blocks_closure` reddens with it) |
| in-context predicate in the frozen rule | use `context_issue_id = I` only, in the frozen-closed refusal | `test_a_closed_issue_refuses_contest_of_a_null_context_link_inside_it` |
| backfill source digest SQL function (R3-F09) | change one fact's serialization in the SQL function | `test_sql_source_document_matches_the_golden_vectors` |
| every origin reference enumerated (R3-F08) | enumerate only `asrt_` and `cap_` | `test_every_origin_reference_is_enumerated_and_unsupported_ones_are_unresolved` |
| existing-link check in any context and state (R3-F07) | look for live heads with the candidate's identity only | `test_existing_links_are_reported_in_any_context_and_state_at_the_cutoff` |
| `COLLATE "C"` (R3-F10) | drop it from the `related_context` CHECK; drop it from the edge ordering | `test_mixed_case_endpoints_are_ordered_by_code_point`; `test_mixed_case_link_ids_page_in_code_point_order` |
| backfill sub-switch (R3-F12) | drop `_lineage_backfill_plane()` in the plan handler | `test_backfill_is_operator_only_attested_and_behind_its_own_switch` |
| absent well-formed `p` (R3-F14, R3-F23) | answer `invalid_request` for an absent `p` | `test_a_vanished_emitted_item_answers_restart_required`; `test_an_unknown_well_formed_position_answers_restart_required` |
| free-text reference token (R3-F22) | store the first 256 code points of the ref | `test_the_report_carries_no_origin_reference_text` (and `test_a_non_ascii_non_nfc_free_text_ref_digests_alike_in_sql_and_python`) |
| native-cut cursor check (R3-F25) | compare `n` with `k` | `test_a_current_read_pages_after_the_lineage_horizon` |
| page-size minimum (R3-F15) | admit `page_size` 1 | `test_page_size_below_the_minimum_is_refused` |
| append-only / truncate on each new table | detach for one table | the parametrized case for that table |
| attested S3 writes; switch | use `lineage_authority`; drop `_lineage_plane` in one handler | `test_an_ordinary_remote_client_is_denied_every_s3_write`; `test_switch_off_answers_unsupported_for_every_s3_capability` |
| downgrade refusal, each family | delete that family's clause | the matching case of `test_each_downgrade_refusal_family_alone_refuses` |
| decoder closed sets | add a value the server never sends | `refuses a lifecycle state outside the S3 vocabulary` |

**Not S3:** AT-015 Program reads, AT-018, AT-019, AT-022, AT-023 Commitment v2 →
Program/report work packages; AT-020, AT-021 → out of scope until OD-06.

## 11. Deferred work and its owner

| Item | Owner / reason |
| --- | --- |
| Proposals and review (`records.associations.propose`/`review`, `irp`, `ldec`, `review_accepted`) | not scheduled; S3's review path for backfill candidates is the operator's attested assert (D-07) |
| Lineage Record Event family, `link_mutation_event_receipts` (`irec`) | not scheduled; commit marks are the lineage receipts (D-06) |
| Decision membership (`decision` role, `continuity_decision`) | needs a Continuity Decision capability family first (no capability writes or reads `cdec_`; S2 D-11); not scheduled |
| Native virtual edges `follow_up`, `constraint_follow_up`, `meeting_in_series`, `project_issue`, `entity_member_of` in reads | not scheduled: their native fields are mutable with no as-of history (D-05) |
| `records.associations.list_for_record` | not scheduled; `records.lineage` from the record serves it |
| Valid-time intervals on links (`valid_from` / `valid_to`) | not scheduled (D-14) |
| Contesting memberships | not scheduled; `contradicts` corrections serve (D-09) |
| Native-plane entries in as-of timelines | needs a commit-ordered native knowledge time (D-04) |
| Verified Commitment acceptance (S2 D-05, D-17) | operator/Work decision (D-11) |
| Constraint close evidence in the Constraint plane (S2 D-06) | Constraint-plane decision; the membership `resolution` anchor stays the proof (D-12) |
| A composite Constraint create; a closure exception authority | as S2 §11 |
| Runtime-role provisioning; remote attested lineage writer; native writers through `is_transaction_conflict` | as S1 §11 |
| **The backfill apply** (materializing `source_backed_accepted` items; package WP-03B, CR-014) | an operator-gated later package (section 13; D-26). Binding requirements for it, from R3-F06/F07: it materializes only items of a `classified` run whose `plan_digest` the operator states; before writing, it looks for **any** link between the candidate's `(from, relation_type, to)` endpoints **in any context and any state**, answering `already_present` for a live one and a distinct `previously_ended` (never a re-write) for an ended one, so an operator's recorded end is never reversed and no context-scoped duplicate is created; it re-derives each source digest and refuses a changed source; it writes through `insert_new_link` under the S1/S2 locks with a new acceptance basis (`source_backed_verified`, then admitted with its CHECK) and a commit mark per transaction; and it requires an independent readback of a sample of every materialized class (CR-014 "one independent readback per accepted class") before a run is reported applied |
| Running the backfill dry run against any real database | operator gate (section 13) |
| Program, report manifest, finance, P6 | own work packages; finance/P6 gated by OD-06 |

## 12. Divergences — repository vs package, and resolutions

| # | Package says | Repository truth | Resolution |
| --- | --- | --- | --- |
| D-01 | CR-008 / §13: `known_at` anchored to a "Record Event high watermark" | lineage writes emit no Record Event (ADR-015 decision 14); `record_events.recorded_at` defaults to `now()`, the transaction start, which is not commit order, so a timestamp cut over it admits late commits | per-Principal commit marks from a row-locked allocator (the `record_event_sequences` precedent), stamped on every fact by a trigger, with `known_at` capped at the committed horizon (sections 3.4, 4.2) |
| D-02 | §13: HMAC-signed cursor binding Principal, grant digest, root, Issue, filters, cutoff, projection version | `record_events.list` binds a SHA-256 binding and re-derives authority every call, so the token carries no authority and needs no secret | unsigned binding cursor (section 5); a forged token can only ask what the caller could ask directly; the horizon check refuses a future cut |
| D-03 | `scope_changed_restart_required` on grant change; repository precedent answers `conflict` / `cursor` on any binding mismatch | both are needed: a different query is a client error, a revoked grant is not | `b` mismatch → `conflict` / `cursor`; `s` mismatch → a `scope_changed_restart_required` page that discloses nothing |
| D-04 | merge native histories into as-of timelines | no native plane has a commit-ordered knowledge time (D-01) | native entries only in current timelines, bounded by the Record Event watermark frozen on page 1; as-of timelines omit them and say `partial_native_history` |
| D-05 | native virtual edges `follow_up`, `constraint_follow_up`, `meeting_in_series`, `project_issue`, `entity_member_of` | `tasks.commitment_id` is mutable (`tasks.update` replaces it; `TaskManagementService.link_commitment` sets it) and none of these fields is versioned, so showing them would make an as-of answer change; Series must never propagate (WP-02D) | only `meeting_note_version_of`, whose rows are immutable but whose *set* grows, so it is cut by the note version's own `recorded_at` (section 3.4, with the named residual that this cut is not commit-ordered: R3-F01); the backfill classifies the others `native_virtual_proven` and never copies them |
| D-06 | `link_mutation_event_receipts` and a lineage Record Event family (D-15 of S2) | the changefeed contract, family reads, routing and role separation would all widen for no S3 AT | commit marks plus `lineage_write_requests.commit_seq` are the receipts; event/projection consistency is tested over marks, requests, facts and heads (AT-014) |
| D-07 | WP-03B review queue; ADR-015 consequences "from S3, propose" | no proposal plane exists; building `irp`/`ldec` is a full review workflow | S3 builds no proposal capability; `review_candidate` and `source_backed_accepted` items are reported only, and the review path is the operator's own attested assert; model clients stay read-only |
| D-08 | operator-only CLI run | `adapters/cli/app.py`: the CLI invokes capabilities through `normalize`; it is not a privileged bypass | 2 operator-only backfill capabilities (the plan attested), behind their own switch, invoked from the CLI |
| D-09 | S2 §3.3: contested membership, closure-set anchor and resolution anchor must block | anchors are not links; a membership dispute is already a gate blocker through `contradicts` | contest is for semantic links; any contested link in the Issue's context blocks closure (section 3.2) |
| D-10 | WP-02D / S2 D-11: Decision membership | no capability creates or reads a `cdec_` | carried (section 11) |
| D-11 | close the client-supplied `rdec_` acceptance if possible | the only server check, `SqlSituationRepository.accept`, proves that *some* capture review case accepted something in the Principal's partition — `capture_review_decisions` binds a review case, never a Commitment — so checking the id would make the residual look closed without closing it | carried as an operator/Work decision; the S2 composite keeps its D-05 behaviour |
| D-12 | stage 13 Constraint close "with verified source E1 approved under Constraint rules" | unchanged since S2 D-06 | carried; the membership `resolution` anchor stays X1's proof |
| D-13 | WP-02C "present/past BIC" | `project_constraint_revisions` keeps one immutable snapshot per applied version and `project_constraint_revision_parties` (role `bic`) its ball-in-court parties; no capability reads a revision (`constraints.history` returns receipts only) | past ball-in-court is read from those immutable snapshots in the current `issues.timeline` with `valid_at`; the Constraint plane is unchanged |
| D-14 | `records.associations.assert` with `valid_from` / `valid_to` | no S1/S2 writer records a business time for a link | a link takes effect at its mark; `valid_at` bounds links by `min(valid_at, known_at)`; intervals carried |
| D-15 | CR-007 edges ≤ 500, §13 edges 400; 2 s statement and 5 s request budgets | S1 fixed 400 | 400 kept; a 2000 ms traversal deadline per page that ends paging, and a 2000 ms statement timeout |
| D-16 | test paths `tests/performance`, `tests/migration/test_lineage_backfill_resume.py`, `tests/end_to_end/…` | repository tiers select by marker; no `performance` marker exists | the section 10 modules and markers |
| D-17 | `records.associations.list_for_record` | `records.lineage` from a root already answers it, bounded and scoped | not built |
| D-18 | WP-06A Meeting view (S1 §7.4 deferred it) | `web/` has `/api/meetings/[meetingId]` (`meetings.read`) and its decoder, no page | a minimal Meeting page with the existing panel |
| D-19 | strict v1 clients unchanged | the `records.lineage` decoder is S1-added, unmerged and undeployed | lockstep widening (S2 D-14 precedent) |
| D-20 | lock order lists the event allocator last | an allocator taken at the first fact insert would hold its lock while a composite inserts later anchors, which a second writer may hold uncommitted (a deadlock) | the mark is taken right after reservation, before any other lock; it serializes a Principal's lineage writers |
| D-21 | S1 `records.lineage` returned every reached record to any holder of its grant | CR-008 requires re-authorizing every node; no client holds a lineage grant | section 6.4 family visibility for remote readers; local readers unchanged |
| D-22 | void any handoff | voiding a middle event breaks holder continuity | only the chain's last live event can be voided |
| D-23 | `historical_fields_partial` as a completeness code | it describes one entry, not the answer | a per-entry boolean |
| D-24 | S2 §3.4 handoff chain uses event *n − 1* | voids exist from S3 | the S2 trigger functions are replaced to skip voided events; the ledger sequence is unchanged |
| D-25 | S1/S2 §10 "no other test edited" | 8 names, 1 purpose, 5 tables, 2 SQL functions, columns, triggers and a new head move registries and pins as in S2 D-18 | the section 10 lockstep list; each edit keeps its test name and assertion |
| D-26 | WP-03B: materialize `SOURCE_BACKED_ACCEPTED` links idempotently (package 03 §2: S3 is WP-03B "read/dry-run", "no automatic historical semantic acceptance") | a bulk materializer approved by one plan-digest attestation is acceptance by class, not by item (R3-F06) | S3 ships the dry run only (plan + report); the apply and `source_backed_verified` are an operator-gated later package with the section 11 binding requirements |
| D-27 | CR-014 preflight: Principal, type, orphan, merge-redirect census | the enumerated families (Tasks, Commitments, Meetings, Constraint relationships, `project_situations`, context Situations) have no merge redirect (Commitments are never merged — `application/identity_correction.py` refuses an Entity merge that would leave a Commitment naming a merged-away counterparty — and Entities are not enumerated); the S1 principal-composite foreign keys make Principal mismatch unrepresentable | the run's census (section 8.3) counts every examined row, reference shape and `project_situation` consistency; no merge-redirect census is built |
| D-28 | independent sample readback | it reads back materialized links, and S3 materializes none | moves with the apply (section 11) |
| D-29 | `known_at` / `valid_at` as one pair for every plane | the native plane has no commit-ordered time and is shown as currently recorded (D-04); clamping it to the lineage horizon hid native changes after the last lineage write (R3-F02) | lineage selection uses `T_v = min(valid_at, T_k)`; native entries use the requested `valid_at`; the answer reports both (`valid_at`, `lineage_valid_at`) |
| D-30 | a remote reader lacking a grant is `denied` (the first draft of this contract) | `_record_events_list` and `_knowledge_plane` answer `unsupported` (R3-F13) | `unsupported` for a missing grant on the called capability; `denied` stays for a purpose the capability does not admit |
| D-31 | S1/S2 Issue reads disclose member, endpoint and link ids to any holder of their grant | CR-008 visibility must hold on every lineage read, and no client holds a lineage grant | section 6.4 applies to `issues.read`, `issues.list`, `issues.handoffs.list` and `issues.closure_readiness`, each gaining `restricted` |
| D-32 | page size 1..100 | full recomputation per page makes `page_size` 1 a cost amplifier, and the repository has no per-Principal rate limiter (`rate_limited` is a WebAuthn-adapter code only) | paged reads take `page_size` 10..100 (R3-F15) |
| D-33 | S2 `HandoffView.effective_at` | corrections exist from S3 | `effective_at` keeps its recorded meaning; `current_effective_at` is added (R3-F18) |

### 12.1 As implemented (S3 workers L1–L6)

Every resolution below was reported in the worker's handoff and accepted by the
Orchestrator; none changes a section 10 test name or a binding assertion.

| # | Point | Contract text | As implemented | Residual |
| --- | --- | --- | --- | --- |
| D-34 | backfill vocabulary placement (L1) | section 3: widened in `domain/lineage/vocabulary.py` | `domain/lineage_backfill/vocabulary.py` holds the 4 backfill enums and `BACKFILL_VALIDATOR_VERSION`; `LINEAGE_BACKFILL_CAPABILITIES` and `BACKFILL_WRITE_CAPABILITIES` stay in `domain/lineage/vocabulary.py`. The binding S2 test forbids the token `meeting_series` under `domain/lineage`, and `BackfillSourceKind` has a `meeting_series` member | none |
| D-35 | S1/S2 lockstep moves (L1) | section 10 lockstep list | the S1/S2 migration suites seed their rows by SQL under `session_replication_role = replica` and run their downgrade-refusal tests at `d020b532ad7d`; the S1 `records.lineage` vocabulary and the web `RELATION_TYPES` were widened by L1 ahead of L2 (S2 D-14 precedent) | none |
| D-36 | completeness and source facts (L1) | sections 3 and 8.3 | `complete` is listed in `qualifiers` when it is the `complete_state` (`qualifiers[0]` is always the `complete_state`); the per-kind fact sets are the closed `SOURCE_FACT_KEYS` of `domain/lineage/backfill.py` | none |
| D-37 | unbuilt names and port defaults (L1–L5) | section 9 | each worker's names answered `unsupported` until built, with `capabilities.get` truthful (the K1 precedent); port methods a double does not implement raise `NotImplementedError` | none; every S3 name is built at L5 |
| D-38 | S3 write and read refusals (L2, L3) | sections 7.4, 7.5 | `contest` of a non-`active` and `reinstate` of a non-`contested` link answer `conflict` / `state`, while `correct` and `end` keep their S1 `conflict` / `stale_version` for a wrong `expected_revision`; `related_context` is normalized to canonical order by the command, then refused in the order context, self-link, evidence, inside; the frozen-closed rule also refuses `correct` / `end` of a null-context link inside the closed Issue; `known_at` is read at microsecond precision; a current `issues.handoffs.list` with no allocator row (`T_k` null) is empty; a replayed `issues.handoffs.correct` answers as of its own `correction_no`; an origin (or an Issue root) not known at the cut is `not_found` / `origin`, and an `issues.history` Issue not known at the cut answers `not_found`; a statement timeout is `LineageReadTimeoutError`, raised inside the bounded read runner every lineage read uses, answering `unavailable` | none |
| D-39 | visibility of S1/S2 Issue reads (L3) | section 6.4 | a handoff view's evidence anchor and an `issues.read` closure anchor go through the same section 6.4 filter; a remote reader's handoff entry whose anchor is withheld is itself withheld and sets `restricted` | a local reader's `issues.read` labels a restricted legacy Capture anchor `restricted` rather than withholding it (S1 F24 forward rule) |
| D-40 | benchmark and seeding (L3) | section 10, AT-016 benchmark | the benchmark seeds without a statement timeout and reads only its own `MY_PA_LINEAGE_BENCHMARK_*` variables; read-path tests seed volume by SQL under replica (synthetic databases only). Recorded locally at `small`: 650 items at `page_size` 10, p50 300 ms, p95 350 ms, 20 s total; at `full` (100000 records, 1000000 links; PostgreSQL 15, Darwin, recorded by FR3): 650 items in 65 pages, p50 302.4 ms, p95 370.9 ms, 20.3 s total. Neither is a service level | none |
| D-41 | timeline placement (L4) | section 7.3 | the native read is `record_events.issue_member_events` in the feed module (section 7.3 note); views in `contracts/v1/issue_timeline.py`; subjects resolved through `parent_root_id`; `association` entries carry `subject: null`; cursor checks run before the Issue's existence; `issues.timeline` declared in the memory-row registry and the RI-FINAL evidence delta. L6 proved the 4 query-plan rows red by dropping `record_links_outgoing`, the `record_link_revisions` primary key, `lineage_commit_marks_by_time`, `record_events_by_principal_record` and `issue_responsibility_events_by_issue` | none |
| D-42 | backfill classification inputs (L5) | section 8.3: classification is a pure function of the stored source document | a `situation_object_ref` item's ownership (is the token an owned record of a lineage family) is read at classification time; a `work_origin_assertion` item's capture-version identity is read from the immutable version row; `project_situation` consistency reads the Situation kind and the Issue ledger | **named residual:** `situation_object_ref` classification is not purely a function of the stored document; an object deleted or created between enumeration and classification can change an item's class without changing its digest |
| D-43 | backfill shapes (L5) | section 8.3 | refused assertions name the first failing rule (`assertion_not_current`, `source_withdrawn`, `source_restricted`, in that order); a `passage_unproven` candidate carries no anchors; an object-ref `source_ref` is the section 4.2 shape-and-digest token; the census and report shapes are the models of `contracts/v1/lineage_backfill.py`; an enumerating call answers `items: []` (nothing is classified yet) | none |
| D-44 | web (L6) | section 7.6 | the section 7.6 note: drilldown wording before the current note is read, the routes' admitted query fields, the 2 lineage tables, the Meeting family admitted in the related-issues route | none |
| D-45 | remote-read visibility corrections (L3, FR3-F01..F04, F07) | sections 6.4, 7.1, 7.3 | `issues.handoffs.list` reads batches at one frozen cut until `page_size + 1` visible entries are found or the set ends, so `next_cursor` is always a shown entry and the page sequence never depends on a withheld one; `memberships_truncated` counts visible members only; both history reads carry `restricted`; an Issue-scoped link's history needs Issue visibility; the unreachable Issue-family branches of `issues.list` / `issues.read` are removed (their own grant makes the Issue family visible). **Bounded (FR3-F08):** both visibility-filtered loops read at most `MAX_VISIBILITY_SCAN` = 400 entries per request (the 400-edge budget's scale) -- handoffs in batches of at least 100, memberships keyset-wise in batches of 101; reaching the bound on `issues.handoffs.list` answers the entries shown, a `next_cursor` only from a shown entry (else `null`) and the disclosure truncation `visibility_scan_bound` -- never a withheld identifier -- and on `issues.read` sets `memberships_truncated: true`. Both reads run under the 2000 ms lineage `statement_timeout`; any lineage persistence statement cancelled by its timeout answers `unavailable` | past the bound a reader may need a fresh request (or may not reach a later visible entry) when more than 400 consecutive entries are withheld from it. **Threshold signal (FR3-F09):** reaching the bound tells a remote reader that at least about `bound − shown` entries were withheld in the scanned range (the handoff truncation, or `memberships_truncated: true` with few memberships shown) -- a bounded threshold, never a count or an identifier; accepted for the same reasons as D-21 and D-46 (no client holds a lineage grant; the remote principal is always the operator) |
| D-46 | horizon timing (FR3-F05) | sections 3.4, 7.2, 7.3 | a current read reports `known_at = T_k = H`, the Principal's latest committed lineage mark, and the cursor's `k` carries it; `H` moves when any lineage fact is written, including one about records a remote reader may not see | **named residual** beside D-01 and D-04: a remote reader can observe *when* lineage writes happen (not what they name) on records it may not see. Not handled in S3 because no client holds a lineage grant and the remote principal is always the operator (D-21); a per-reader horizon would need the mark resolution under the reader's visibility, as the timeline's `r` already is (R3-F04) |

Lock and transaction rules not restated here are S1's and S2's, including S1 §12 and
S2 §12.

## 13. Operator gates that remain

Ratification of ADR-015 beyond the directive defaults; any live migration, grant,
ChatLLM or client exposure, deployment (OD-07); **enabling `MY_PA_LINEAGE_BACKFILL_ENABLED` or
running the backfill dry run against any real database, and the whole backfill apply
package of section 11** (OD-05, OD-07); any closure exception or
completeness-threshold risk acceptance (OD-03, OD-08); verified Commitment acceptance
(D-11) as a Work decision; Constraint close evidence and a joined-transaction
Constraint create as Constraint-plane decisions; a proposal/review plane; source
commissioning for finance and P6 (OD-06); runtime-role provisioning; the benchmark
numbers as any service level. Nothing else in S3 is left for a worker to decide beyond
local naming with no incumbent constraint.
