# Record lineage — Slice S2 implementation contract

**Status:** proposed implementation contract under
[ADR-015](../decisions/ADR-015-record-lineage-and-issue-situations.md) (Proposed —
accepted by directive defaults; architecture/test-isolated scope only). It is the
single document S2 implementers code against, on top of the
[S1 contract](record-lineage-s1-contract.md) as implemented. It authorizes no migration
run, grant, deployment, backfill or production use. Where it differs from the review
package (`MYPA-LINEAGE-ADVERSARIAL-REVIEW-20261017-001`, documents 02, 03, 04, 06 and
07), this document controls for S2 and section 12 records why.

**Implementation:** S2 is implemented on `feat/lineage-s2-workflow` (workers K1 to K4,
revision `d020b532ad7d`) and exercised only against isolated synthetic test databases
and mocked web gateways; it is not merged, migrated anywhere live, granted, exposed or
deployed. Sections 6.1, 7.2, 7.4, 8 and 10 carry "as implemented" notes where the code
resolved a point this contract left open; the paths named below as new now exist.

**Basis:** `feat/lineage-s2-workflow@75dcd96ae1807238a68d5804ef1ad79973600920`
(tree `3be1a1827939e9beee4f4c831500209f3515bc8c`), the S1 head on
`feat/lineage-s1-integration`; Alembic single head `264310e0416a` (119 revisions);
206 `Capability` members, 57 `Purpose` members, 217 audit-vocabulary capability names.
"S1 §n" cites the S1 contract. Paths under `src/` are relative to `src/my_pa/`.

All counts in this file are digits on purpose (spelled-count guard).

## 1. What S2 is

S2 is the lifecycle slice (plan WP-01C remainder, WP-02B, WP-02C, WP-02D): an Issue
can close and reopen behind a gate, a responsibility handoff is an explicit ledger
fact, delegated and resolving work is created atomically with its lineage, a formal
Constraint is escalated from a Task by an explicit evidenced assertion, a blocking
assertion refuses cycles, and the full 14-stage synthetic workflow of package 04 §A
runs end to end against the database.

**In S2:**

- `issues.close` / `issues.reopen` with the OD-03 gate (section 3.3), the `closed`,
  `reopened` and `corrected` Issue revision actions, closure evidence frozen on the
  closing revision, and a read-only `issues.closure_readiness`;
- `issues.memberships.correct`, the membership evidence correction the gate's
  resolution evidence is recorded with (the S1 `correct_evidence` revision, for
  memberships);
- the responsibility handoff ledger (`ihnd`, section 3.4): `issues.handoffs.record`
  and `issues.handoffs.list`;
- 2 composite writes (CR-006, section 6.4): `issues.work.create_task` and
  `issues.work.create_commitment`, each a native create, its Issue membership and its
  association intents in one unit of work;
- 4 relation types (section 3.1): `delegated_from`, `escalated_from`, `blocks` (with
  cycle refusal), `created_to_resolve`;
- the frozen closed Issue: every lineage write that names a closed Issue is refused
  (section 3.3);
- the 14-stage AT-001, AT-005, AT-006, AT-007, the S2 part of AT-015, AT-017, and the
  S2 part of the reverse-root equivalence (section 10);
- the lockstep widening of the S1 `records.lineage` web decoder and panel for the new
  relation types and the `closed` Issue state (section 7.4).

**Not in S2** (section 11 lists the owner slice): `related_context`; `contest` /
`reinstate` link revisions and the `contested` state; `issues.history`,
`records.associations.history`, `list_for_record`, `known_at` / `valid_at` reads,
cursors and the 14-stage time ordering of the reverse-root equivalence; Decision
membership (`decision` role, `continuity_decision` family); native virtual edges other
than `meeting_note_version_of` (`follow_up`, `constraint_follow_up`,
`meeting_in_series`, …); a composite Constraint create; proposals and review; Record
Event emission for lineage; Issue pages, timeline and graph; Managed Document and
Knowledge Assertion evidence; restricted evidence; any closure exception authority.

## 2. Identifier kinds

One new `IdKind` member (`domain/common/identifiers.py`), verified free at the basis
commit (no existing value is a string prefix of it or prefixed by it); re-run the
collision check before the revision is written.

| `IdKind` member | Prefix | Identifies |
| --- | --- | --- |
| `ISSUE_HANDOFF` | `ihnd` | one immutable responsibility handoff event (`issue_responsibility_events.handoff_id`) |

No other kind is added. Closure evidence rows and composite request rows are
composite-keyed (no prefix). Still reserved for S3: `irp`, `ldec`, `irec` (S1 §2).
Existing kinds used by S2: `sit`, `prj`, `mtg`, `mnote`, `tsk`, `cmt`, `cst`, `cap`,
`capver`, `ent`, `prn`, `irs`, `irl`, `irv`, `ian`, `ipme`, `rdec`.

## 3. Closed vocabularies

Widened in `domain/lineage/vocabulary.py` and in the S2 revision's CHECKs together
(S1 §3 rule: an enum and its CHECK move together, the revision restates frozen
literals and imports nothing from `src/`).

| Vocabulary | S1 admits | S2 adds | Still later |
| --- | --- | --- | --- |
| Issue states (`ISSUE_STATES`, a subset of `SituationState`, which already has `closed`) | `open`, `active`, `suspended` | `closed` | — |
| `IssueRevisionAction` | `created`, `updated`, `activated`, `suspended` | `closed`, `reopened`, `corrected` | — |
| `RelationType` | `issue_member`, `originated_from`, `discusses` | `delegated_from`, `escalated_from`, `blocks`, `created_to_resolve` | `related_context` (S3) |
| `MemberRole` | 6 members (S1 §3) | — | `decision` (S3, with `continuity_decision`) |
| `RecordFamily` | 7 members (S1 §3) | — | unchanged list (S1 §3) |
| `LinkRevisionAction` | `assert`, `end`, `correct_evidence` | — (`correct_evidence` now also on memberships) | `contest`, `reinstate` (S3) |
| `LinkLifecycleState` | `active`, `ended` | — | `contested` (S3) |
| `AcceptanceBasis` | `user_confirmed` | — | `review_accepted`, `system_deterministic`, `source_backed_verified` (S3) |
| `EvidenceRole` | 6 members incl. `handoff`, `resolution` | — (S2 gives `handoff` and `resolution` their first rules) | — |
| `HandoffHolderKind` (new) | — | `principal`, `entity` | `unassigned` (not scheduled) |
| `HandoffSide` (new, request only) | — | `principal`, `counterparty` | — |
| `IssueClosureBlocker` (new, read only) | — | `native_open`, `native_terminal_unsuccessful`, `native_not_accepted`, `role_family_not_closable`, `resolution_evidence_missing`, `resolution_evidence_unavailable`, `resolution_evidence_contradicted`, `resolution_evidence_stale` | — |
| `NativeVirtualEdge` (read only) | `meeting_note_version_of` | — | the rest (S3) |
| `LineageCompleteness` (read only) | 4 members | — | the rest (S3) |

New constants in `vocabulary.py`: `MANDATORY_MEMBER_ROLES = {work, constraint}`;
`COMPOSITE_CAPABILITIES = {"issues.work.create_task", "issues.work.create_commitment"}`;
`COMPOSITE_ONLY_RELATIONS = {delegated_from, created_to_resolve}`;
`ISSUE_REVISION_CAPABILITIES` gains `issues.close`, `issues.reopen`;
`LINK_REVISION_CAPABILITIES` gains `issues.memberships.correct` and the 2 composites;
`RECORD_LINK_CAPABILITIES` gains the 2 composites; `LINEAGE_WRITE_CAPABILITIES`
becomes the 15 lineage write names (S1's 9 plus section 7's 6). `ISSUE_STATES` gains
`closed`.

### 3.1 S2 relation matrix additions (the closed policy)

The S1 §3.1 rows are unchanged. Each added row is a `semantic` link.

| Relation | From | To | Written by | Rule (application; refused with `invalid_request` / the named detail unless stated) |
| --- | --- | --- | --- | --- |
| `delegated_from` | `commitment` | `task` | `issues.work.create_commitment` only | context = the composite's Issue; ≥1 `immutable_version` anchor with role `origin` (`evidence_anchors`); the new Commitment's `direction` is `owed_to_principal` (`direction`); the Task is an active `issue_member` of the Issue (`to_record`), not terminal and not archived (`endpoint`) |
| `escalated_from` | `constraint` | `task` | `records.associations.assert` (and `correct`/`end`) | `context_issue_id` required (`context_issue_id`); ≥1 `immutable_version` anchor with role `origin` (`evidence_anchors`); the Constraint is not `draft` (`endpoint`) and its `created_at` is not before the Task's (`from_record`); its `project_id` has an **active** Project link to the context Issue (`project_id`); the Task is an active `issue_member` of the context Issue (`to_record`) |
| `blocks` | `task`, `constraint` | `task`, `constraint` | `records.associations.assert` (and `correct`/`end`) | `context_issue_id` optional; ≥1 `immutable_version` anchor with role `corroborates` (`evidence_anchors`); `from` ≠ `to` (`to_record`; also a database CHECK); no cycle over the Principal's active `blocks` heads (`blocks_cycle`, section 6.3) |
| `created_to_resolve` | `task`, `commitment` | `situation` (Issue), `constraint` | the 2 composites only | context = the composite's Issue; a `purpose` text (1..2000) stored as revision 1's `reason` (`purpose`; also a database trigger); 0..32 anchors, any role; a `situation` target equals the composite's Issue (`to_record`); a `constraint` target is an active `issue_member` of it (`to_record`) |

`records.associations.assert` refuses `delegated_from` and `created_to_resolve` with
`invalid_request` / `relation_type` exactly as it refuses `issue_member`: they assert
that a record was *created* by delegation or for a purpose, which only the creating
transaction can attest. `escalated_from` is an explicit later assertion because the
Constraint plane owns its own transaction (section 12, D-03).

**Assert-time versus correction-time rules (R2-F07).** A correction
(`records.associations.correct`) re-applies **only the evidence-anchor rules** of its
relation (the anchor count, roles and kinds above, with S1 anchor admission), exactly
as S1 `_revise` re-applies `require_relation_evidence`. The state, membership, Project
and time rules (Task not terminal or archived, active membership, active Project link,
Constraint not `draft`, `created_at` order, Commitment direction, no `blocks` cycle) are
**assert-time only**: they describe the world when the relation was asserted, and a
later native change (T1 completing at stage 11) must not make C2's `delegated_from`
evidence uncorrectable. A correction never re-runs the cycle search, because it changes
no endpoint. `end` is as S1.

**Cycle rule.** Only `blocks` is cycle-sensitive. `delegated_from` (Commitment → Task)
and `escalated_from` (Constraint → Task) are bipartite and single-hop, so no cycle
can form; `created_to_resolve` targets an Issue or a Constraint, neither of which can
be its `from` family; `originated_from` targets immutable versions; `discusses` and
memberships are non-causal. A `blocks` assert computes reachability from `to` over
active `blocks` heads (any context) and refuses if `from` is reached; the search visits
at most 1000 records and refuses (`invalid_request` / `blocks_cycle`) if the bound is
hit before the frontier is exhausted, so an undecidable answer is a refusal, never an
admission.

### 3.2 Endpoint linkability (S2 additions)

S1 §3.2 is unchanged, including its 3-step check order (prefix, then Principal-scoped
existence and parent, then linkability). S2 adds only relation-specific rules
(section 3.1) and the closed-Issue rule: an Issue in state `closed` named as an
endpoint, a membership owner or a `context_issue_id` of any lineage write is refused
with `conflict` / `state`, after the existence check (so a foreign closed Issue is
`not_found`). The only writes admitted on a closed Issue are `issues.reopen` and an
`issues.update` correction (section 7.2).

### 3.3 The closure gate (OD-03)

**Mandatory members.** An active `issue_member` link whose `member_role` is `work` or
`constraint`. Every other role (`origin_evidence`, `discussion`, `supporting_evidence`,
`reference`) is evaluated for nothing. Semantic links are not gated; an ended
membership is not a member.

**A mandatory member is satisfied** when all of the following hold; every failing
condition is reported as a blocker reason, in this table's order and then the
evidence order below:

| Member family | Native condition (never written by the gate) | Blocker when it fails |
| --- | --- | --- |
| `task` | `lifecycle_state = completed` and `evidence_state = accepted` | `native_open` (non-terminal), `native_terminal_unsuccessful` (`cancelled`), `native_not_accepted` |
| `commitment` | `state = closed` and `evidence_state = accepted` | `native_open`, `native_not_accepted` (closed but `proposed`: AT-015) |
| `constraint` | `lifecycle_state = closed` | `native_open` (`draft` or active), `native_terminal_unsuccessful` (`void`) |
| any other family | — | `role_family_not_closable` |

and the membership's **head revision evidence** contains ≥1 anchor with role
`resolution` and `source_version_kind = immutable_version` whose availability at
evaluation time is `available` (`resolution_evidence_missing` when there is none,
`resolution_evidence_unavailable` when every such anchor reads `archived`), and
contains no anchor with role `contradicts` (`resolution_evidence_contradicted`). A
`legacy_unversioned` anchor never satisfies anything. Resolution evidence is recorded
with `issues.memberships.correct` (section 7.2) after the native close; it proves the
member's resolution independently of the native record, as stages 4, 10, 11 and 13 of
AT-001 do.

**The evidence is bound to the native close it proves (R2-F01, option b).** Task,
Commitment and Constraint each carry a monotonic native `version` (the optimistic
concurrency counter `tasks.transition`, `commitments.close` and `constraints.close`
check as `expected_version`), and every membership writer reads it under its section 6.2
step 3 `FOR SHARE`, so it cannot change while the write is in flight. Every membership
revision written by `issues.memberships.add`, `issues.memberships.correct` or a
composite whose member is a Task, Commitment or Constraint stores that observed value in
`record_link_revisions.member_native_version` (section 4.1); `end` revisions, other
families and **every semantic link revision, including a composite's association-intent
revisions** (R2-F16), store null — the application writes null there even though the
`only_membership_writes_record_a_member_version` CHECK, which sees only the capability,
would admit a value. The gate requires the head revision's `member_native_version` to
**equal** the member's current native `version`; otherwise the member carries
`resolution_evidence_stale`. So evidence recorded before a reopen and re-close (X1 v5,
reopened v6, re-closed v7), or while T1 was still open, never satisfies the later
close. The rule is deliberately conservative: *any* native change after the evidence was
recorded (an archive of a completed Task, a Constraint commentary update) also makes it
stale, and the operator re-affirms.

**Re-affirmation.** `issues.memberships.correct` normally refuses a set whose digest
equals the head's (S1 rule). It admits an identical set when the head's
`member_native_version` differs from the member's current native `version` and the set
contains ≥1 `resolution` anchor: the new `correct_evidence` revision carries the same
digest and the new observed version. Any other same-digest correction is still
`invalid_request` / `evidence_anchors`.

**The Issue's own closure evidence** (`issues.close`): 1..32 anchors, ≥1 with role
`resolution` and `immutable_version`, none with role `contradicts`, admitted by the S1
anchor rules (so an archived Capture root is `denied` / `capture_withdrawn`, a
restricted version `invalid_request`, a legacy root only `corroborates`/`contradicts`
and never counted). A Meeting note passage is admissible closure evidence like any
exact version; what it cannot do is close a member (the M4 case: words in a note do not
change a native state).

**No exception, no cascade.** The gate has no override field (an `exception` or any
unknown key is `invalid_request`), consults no allowlist and accepts no risk. A member
that will never be satisfied (a cancelled Task, a void Constraint) leaves the gate
closed until the operator ends that membership with `issues.memberships.end` and a
reason — an attested, recorded change of scope, not an exception (this reading of OD-03
is recorded as section 12, D-16). Closing or reopening
an Issue changes no Task, Commitment, Constraint, membership, link or Project link;
closing a member never closes or reopens the Issue.

**Contested evidence (forward obligation).** S2 approximates OD-03's "contested
evidence blocks closure" with `contradicts` anchors, the only contradiction S2 can
record. When S3 admits `contest` / `contested`, a contested mandatory membership, a
contested closure-set anchor's link and a contested resolution anchor **must** become
gate blockers in the same change; S3 may not ship `contested` without them.

**The frozen closed Issue.** While an Issue is `closed`, `issues.update` (other than a
correction), `issues.project_links.add/end`, `issues.memberships.add/end/correct`,
`records.associations.assert/correct/end` naming it as an endpoint or context,
`issues.handoffs.record` and both composites answer `conflict` / `state`. This adds no
refusal reachable in S1 (no Issue could be closed), and it is what keeps the gate's
answer true after the close: a member cannot be added to or ended from a closed Issue.

### 3.4 The responsibility handoff model (CR-005)

A handoff is one append-only `issue_responsibility_events` row (`ihnd`): within an
Issue, the next management action on one Commitment moves from one holder to another,
effective at a stated business time, recorded with an exact evidence anchor and a
reason, by the local operator. It is **never inferred**: `commitments.close`,
`tasks.transition`, a composite create, an Issue close and a membership change write
none, and a handoff changes no native field (C1 stays closed, its counterparty and
direction unchanged).

- **Subject:** a Commitment of the Principal, checked in the S1 §3.2 order: the `cmt_` prefix (`invalid_request`), then Principal-scoped existence (absent and foreign alike `not_found` / `commitment_id`), and only then active `issue_member` of the Issue (`invalid_request` / `commitment_id` otherwise). Tasks are Principal-held and Constraints carry native ball-in-court, so neither is a handoff subject in S2.
- **Holders (R2-F02, option a).** The request names only the side the responsibility leaves (`from: principal | counterparty`); the server resolves both holders, so a client never supplies an Entity or Principal identifier.
  - The **leaving** holder is, for event 1, the Principal or the Commitment's current `counterparty_entity_id`; for event *n* > 1 it is **the chain's last holder** (event *n − 1*'s `to` holder), and `from` must name that holder's side (`principal` for a Principal holder, `counterparty` for an Entity holder), else `invalid_request` / `from`.
  - The **arriving** holder is the Principal when the leaving one is an Entity, and the Commitment's **current** `counterparty_entity_id` when the leaving one is the Principal.
  - So a counterparty re-pointed by `commitments.update` from P1 to P1′ never wedges the chain: with P1 holding, the next event records P1 → Principal; with the Principal holding, it records Principal → P1′. Each is explicit, and a former counterparty can only ever *leave*.
  - **No reachable state is unrecoverable.** The only refusals are `invalid_request` / `from` (the request named the wrong side; restate it), `conflict` / `stale_version` (a concurrent event took the sequence number; re-read and retry) and the time rule below. The trigger's predecessor equality (section 4.2) holds by construction.
  - **Identity merge (affected family).** A future Commitment or Entity identity-merge work package (Commitment merge is currently BLOCKED in `application/identity_correction.py`) must treat `issue_responsibility_events.from_entity_id`, `to_entity_id` and `commitment_id` as an affected family: the rows are immutable, so a merge redirects reads, never rewrites them.
- **Sequence:** per `(issue, commitment)`, `sequence_no` 1, 2, …; event *n* > 1 must leave the holder event *n − 1* arrived at (a database trigger).
- **Time (R2-F03).** `effective_at` is client-stated business time and must be at or before the server's `recorded_at` (a CHECK), at or after the Commitment's `created_at`, and at or after event *n − 1*'s `effective_at` (a database trigger, `a_handoff_is_effective_in_order`); every violation is `invalid_request` / `effective_at`. So valid-time order never contradicts sequence order. `recorded_at` is server-stamped. No `valid_at` read exists in S2.
- **No correction in S2 (interim rule).** A handoff cannot be corrected or voided in S2: a mis-recorded event **stands** as recorded, and the operator must not record a reverse handoff to "undo" it, because that would assert a business event that never happened. Handoff correction/void (an append-only correcting event that S3's `valid_at` reads honour) is owned by S3 (section 11).
- **Evidence:** exactly 1 `EvidenceAnchorInput` with role `handoff` and `immutable_version`, admitted by the S1 anchor rules.

Several Commitments can have independent handoff chains at once, and a Principal can
hold several next actions; no read derives "the owner" of an Issue (package
`multiple_holders` is a property of reads S3 adds, not of this ledger).

## 4. Schema — one additive revision

One Alembic revision, `down_revision = "264310e0416a"`, the new single head (file
`migrations/versions/<date>_<rev>_record_lineage_s2.py`; the `record_lineage_s2` slug
is what the scope guard finds it by). Frozen literal DDL, no domain or persistence
import, declarations mirrored in `infrastructure/persistence/tables.py` with the
`TABLES_SHA256` pin and every W1 §2.2 registration step (S1 §9) applied. S1 §4
conventions hold: schema `knowledge`, `principal_id` partition with `_is_identifier`,
`_is_identifier` on every identifier column, every foreign key principal-composite and
`ON DELETE RESTRICT`, server-stamped `timestamptz`, sha256 hex digests. A CHECK the S1
revision created is widened by `DROP CONSTRAINT` + `ADD CONSTRAINT` under the **same
name**; an S1 function is changed by `CREATE OR REPLACE FUNCTION` and `downgrade()`
restores the S1 body byte for byte.

### 4.1 Existing tables (additive only)

**`issue_revisions`**

- `ADD COLUMN closed_at timestamptz`, `outcome text`, `reason text`,
  `evidence_count smallint NOT NULL DEFAULT 0`, `evidence_set_digest text` (existing
  rows: nulls and 0; adding them updates no row, so the append-only trigger is not
  engaged).
- Widen `an_issue_revision_action_is_known` (+ `closed`, `corrected`, `reopened`),
  `an_issue_revision_state_is_known` (+ `closed`), `an_issue_revision_capability_is_known`
  (+ `issues.close`, `issues.reopen`).
- New CHECKs:
  - `an_issue_revision_closes_exactly_when_closed` — `(state = 'closed') = (closed_at IS NOT NULL) AND (state = 'closed') = (outcome IS NOT NULL)`;
  - `an_issue_revision_outcome_is_bounded` — `outcome IS NULL OR length(trim(outcome)) BETWEEN 1 AND 2000`; `an_issue_revision_reason_is_bounded` — `reason IS NULL OR length(trim(reason)) BETWEEN 1 AND 2000`;
  - `an_issue_revision_action_matches_its_state` — `closed` ⇒ state `closed`; `corrected` ⇒ state `closed`; `reopened` ⇒ state `active`; every other action ⇒ state `<> 'closed'`;
  - `an_issue_revision_action_matches_its_capability` — `closed` ⇔ `issues.close`; `reopened` ⇔ `issues.reopen`; `corrected` ⇒ `issues.update`;
  - `a_reopening_states_its_reason` — `(action = 'reopened') = (reason IS NOT NULL)`;
  - `an_issue_revision_evidence_is_bounded` — `evidence_count BETWEEN 0 AND 32` and `(evidence_count = 0) = (evidence_set_digest IS NULL)` and digest `~ '^[0-9a-f]{64}$'`;
  - `only_closure_revisions_carry_evidence` — `action IN ('closed','reopened') OR evidence_count = 0`; `an_issue_closing_revision_has_evidence` — `action <> 'closed' OR evidence_count >= 1`;
  - `an_issue_closure_is_operator_attested` — `action NOT IN ('closed','reopened','corrected') OR (authority_class = 'local_operator' AND decision_channel IN ('local_cli','local_web'))` (R2-F10: a correction of a closed Issue is attested too, so no remote or model client can rewrite a closed Issue's title or description).
- New trigger `an_issue_closure_follows_its_predecessor` (`BEFORE INSERT`): for
  `version > 1` it reads the predecessor revision and requires: `closed` follows a
  non-closed state; `reopened` and `corrected` follow `closed`; every other action
  follows a non-closed state; a `corrected` revision copies the predecessor's
  `closed_at` and `outcome` exactly.
- `CREATE OR REPLACE FUNCTION knowledge.an_issue_matches_its_latest_revision()`: the
  current `situations` row must have an `issue_revisions` row at its `version` with equal
  `state`, `title`, `description`, **and** `closed_at`, `outcome` (`IS NOT DISTINCT FROM`
  each); the S1 clause `closed_at IS NULL AND outcome IS NULL` is replaced by that
  equality. `situations` keeps its existing `a_closed_situation_records_when_it_closed`
  CHECK; a close writes `state = 'closed'`, `closed_at`, `outcome`, `version + 1`; a
  reopen writes `state = 'active'`, `closed_at = NULL`, `outcome = NULL`, `version + 1`.

**`record_links`**

- Widen `a_record_link_relation_type_is_known` (+ 4 types), `a_record_link_pair_is_admitted`
  (+ the 4 section 3.1 rows as disjuncts) and `a_record_link_capability_is_known`
  (+ `issues.work.create_task`, `issues.work.create_commitment`).
- New CHECKs: `a_blocks_link_names_two_records` — `relation_type <> 'blocks' OR NOT (from_family = to_family AND from_id = to_id)`;
  `a_creation_link_is_written_by_its_composite` — `relation_type NOT IN ('delegated_from','created_to_resolve') OR (context_issue_id IS NOT NULL AND source_capability IN ('issues.work.create_commitment','issues.work.create_task'))`, and `relation_type <> 'delegated_from' OR source_capability = 'issues.work.create_commitment'`;
  `an_escalation_is_issue_scoped` — `relation_type <> 'escalated_from' OR context_issue_id IS NOT NULL`.
- `knowledge.lineage_record_link_identity` is unchanged (the relation type is a parameter).

**`record_link_revisions`**

- Widen `a_link_revision_capability_is_known` (+ `issues.memberships.correct`, the 2 composites).
- `ADD COLUMN member_native_version integer` (null on every existing row), CHECK
  `a_member_native_version_is_positive` (`member_native_version IS NULL OR member_native_version >= 1`)
  and CHECK `only_membership_writes_record_a_member_version`
  (`member_native_version IS NULL OR source_capability IN ('issues.memberships.add','issues.memberships.correct','issues.work.create_commitment','issues.work.create_task')`).
  Which membership revisions must carry it (a Task, Commitment or Constraint member) is
  an application rule (section 3.3), because the member family is on the root.
- New trigger `a_resolution_link_states_its_purpose` (`BEFORE INSERT`): revision 1 of a
  root whose `relation_type = 'created_to_resolve'` requires `reason IS NOT NULL`.

**`lineage_write_requests`**

- `ADD COLUMN result_handoff_id text` (`_is_identifier` `ihnd`, FK `(principal_id, result_handoff_id) → issue_responsibility_events`),
  `result_record_family text`, `result_record_id text` (CHECK family ∈ `task`, `commitment`, with the family's prefix).
- Widen `a_lineage_write_request_capability_is_known` (+ the 6 section 7 writes),
  `an_incomplete_lineage_write_request_names_no_result` (+ the 3 new columns null),
  `a_completed_issue_write_names_its_revision` (+ `issues.close`, `issues.reopen`; the
  3 new columns null), `a_completed_project_link_write_names_its_event` (3 new columns
  null), `a_completed_link_write_names_its_revision` (+ `issues.memberships.correct`
  with `result_created IS NULL`; 3 new columns null).
- New CHECKs `a_completed_handoff_write_names_its_event` (`issues.handoffs.record` ⇒
  only `result_handoff_id`) and `a_completed_composite_write_names_its_record` (a
  composite ⇒ only `result_record_family`, `result_record_id` and `result_created IS NULL`;
  its links are in `lineage_write_request_links`).
- `CREATE OR REPLACE FUNCTION knowledge.a_lineage_write_request_completes_once()` so the
  3 new result columns are among those that may change, only from reserved, only once.

**`audit_events`** — `capability_is_known` and `purpose_is_known` restated (BEFORE texts
byte copies of `264310e0416a`'s AT texts; AT texts add exactly the 8 section 7
capability names and `issue_work_authoring`, sorted), `_CURRENT_AUDIT_CAPABILITIES`
moving with them, under the S1 schema-ahead precedent (S1 §4.3): a
`tests/schema/lineage_s2_schema_ahead_contract.py` gap that is empty once the domain
declares every name.

No change to `situations` constraints, `project_situations`, `issue_project_membership_events`,
`lineage_evidence_anchors`, `record_link_revision_evidence`, `record_link_heads`,
`meeting_note_versions`, `capture_versions` or any native table.

### 4.2 New tables

**`issue_revision_evidence`** (immutable; the closure and reopening evidence set)

Columns `principal_id, issue_id, version, ordinal (smallint 1..32), anchor_id, role (EvidenceRole)`;
PK `(principal_id, issue_id, version, ordinal)`; `UNIQUE (principal_id, issue_id, version, anchor_id)`;
FKs `(principal_id, issue_id, version) → issue_revisions` and `(principal_id, anchor_id) → lineage_evidence_anchors`.
Constraint triggers `an_issue_revision_evidence_set_is_frozen` on this table and on
`issue_revisions` (deferred): at commit the row count for the revision equals its
`evidence_count`. `ordinal` is the S1 §5.1 canonical position;
`evidence_set_digest` is the S1 §5.1 digest over the same anchor objects.

**`issue_responsibility_events`** (immutable; section 3.4)

| Column | Type / rule |
| --- | --- |
| `principal_id`, `handoff_id` (`ihnd`) | PK |
| `issue_id` (`sit`), `issue_kind` (constant `issue_workstream`) | FK `(issue_id, principal_id, issue_kind) → situations (situation_id, principal_id, kind)` |
| `commitment_id` (`cmt`) | FK `(principal_id, commitment_id) → commitments (principal_id, commitment_id)` |
| `sequence_no` (`>= 1`), `predecessor_sequence_no` | `UNIQUE (principal_id, issue_id, commitment_id, sequence_no)`; FK `(principal_id, issue_id, commitment_id, predecessor_sequence_no) → self` |
| `from_holder_kind`, `to_holder_kind` | `HandoffHolderKind` |
| `from_entity_id`, `to_entity_id` (`ent`) | null iff the side's kind is `principal`; FK `(…_entity_id, principal_id) → entities (entity_id, principal_id)` each |
| `effective_at`, `recorded_at` | `timestamptz NOT NULL` |
| `evidence_anchor_id` (`ian`) | NOT NULL, FK → `lineage_evidence_anchors` |
| `reason` | `length(trim(reason)) BETWEEN 1 AND 2000` |
| `acceptance_basis` | `user_confirmed` |
| `authority_class`, `decision_channel`, `source_capability` (`issues.handoffs.record`) | |

CHECKs: `a_handoff_holder_is_whole` (kind/entity pairing per side);
`a_handoff_changes_its_holder` (the two sides differ: not both `principal`, and not the
same entity); `a_handoff_is_not_effective_after_recording` (`effective_at <= recorded_at`);
`a_handoff_follows_the_prior_sequence` (`sequence_no = 1` ⇔ predecessor null; else
predecessor `= sequence_no - 1`); `a_lineage_row_is_local_operator_attested` (S1 name and
text). Trigger `a_handoff_follows_its_predecessor` (`BEFORE INSERT`): event *n* > 1
requires event *n − 1* to exist with `to_holder_kind = NEW.from_holder_kind` and
`to_entity_id IS NOT DISTINCT FROM NEW.from_entity_id`. Trigger
`a_handoff_is_effective_in_order` (`BEFORE INSERT`): `NEW.effective_at` is at or after
the Commitment's `created_at` and, for event *n* > 1, at or after event *n − 1*'s
`effective_at` (`check_violation`). Index
`issue_responsibility_events_by_issue (principal_id, issue_id, recorded_at, handoff_id)`.

**`lineage_write_request_links`** (immutable; a composite request's links, for replay)

Columns `principal_id, capability, idempotency_key, ordinal (smallint 1..5), link_id, revision_no`;
PK `(principal_id, capability, idempotency_key, ordinal)`; `UNIQUE (principal_id, link_id)`;
FKs `(principal_id, capability, idempotency_key) → lineage_write_requests` and
`(principal_id, link_id, revision_no) → record_link_revisions`; CHECK `capability` is a
composite. Ordinal 1 is the membership; 2..5 are the association intents in request
order. Constraint trigger `a_composite_request_names_its_links` (`AFTER INSERT OR UPDATE`
on `lineage_write_requests`, deferred): a completed composite request has ordinal 1, its
ordinals are contiguous, and ordinal 1 names an `issue_member` root whose `to_id` is
`result_record_id`.

### 4.3 Shared triggers, protection, downgrade

- `lineage_rows_are_append_only()` attaches to the 3 new tables; `lineage_relations_refuse_truncate()` attaches to the 3 new tables (S1 semantics: refused while the table holds a row).
- `a_linked_record_is_not_deleted` is unchanged; a handoff's Commitment is also held by its `RESTRICT` FK.
- No role grant changes; the S1 §4.3 DML-not-DDL and `TRUNCATE … CASCADE` residuals apply unchanged to the new tables.
- `downgrade()` first refuses (`restrict_violation`) while any row exists in the 3 new tables, any `issue_revisions` row has an S2 action or state, any `record_links` row has an S2 relation type or source capability, any `record_link_revisions` or `lineage_write_requests` row names an S2 capability, or any `audit_events` row names an S2 capability or purpose; only then restores every widened CHECK and replaced function to its S1 text and drops the new columns, triggers and tables in reverse order.

## 5. Canonical encodings

S1 §5 is reused unchanged: anchor objects, ordering, `evidence_set_digest`,
`normalized_identity`, the SQL rebuild functions. Additions:

- **Issue closure evidence** uses the S1 evidence-set digest over the closing (or reopening) revision's anchors; it is stored, rebuilt and parity-tested, and **withheld** from every view (FR1-F05 reasoning applies identically).
- **Request digest** (S1 §5.4, no NFC): for a composite, `request` holds the nested native object as the native command's fields, every optional native field present (`null` when absent), instants as UTC ISO-8601 strings, enums by value, party or list fields in received order, and the intents in received order with each intent's anchors in S1 §5.1 order. For `issues.handoffs.record`, `effective_at` is the UTC ISO-8601 string of the parsed instant.

## 6. Authority, locks and the transaction

### 6.1 Authority

S1 §6.1 is reused: `lineage_authority` / `attested_lineage_authority`
(`application/lineage_authority.py`) with both Knowledge allowlists empty. **Every S2
write is attested** (local-operator only, `denied` before any row and before any
replay lookup): `issues.close`, `issues.reopen`, `issues.memberships.correct`,
`issues.handoffs.record`, `issues.work.create_task`, `issues.work.create_commitment`.
An `issues.update` on a **closed** Issue (a correction, action `corrected`) is attested
too (R2-F10): the handler derives `attested_lineage_authority` once it has locked the
Issue and found it closed, so a correction from any other caller is `denied` and writes
nothing; an `issues.update` on a non-closed Issue stays a recorded write, as in S1.

**The invariant, stated precisely (R2-F14, option a).** No attested result is ever
returned to, and no attested row is ever written for, a caller that is not
local-operator. (Precisely: no attested *write response*, first-time or replayed. The
rows an attested write produced are still served by the reads — `issues.read`,
`issues.list` and `issues.handoffs.list` — to any caller holding `issue_read`, as
intended; R2-F17.) For the writes listed above (the S2 set), attestation is derived before any row and
before the replay lookup (S1 §6.1). For `issues.update`, whose attestation depends on
the Issue's state, it is derived at the two points where that state is known: (1) on a
**replay hit** whose stored result (`result_issue_id`, `result_issue_version`) names a
`corrected` revision, the handler derives `attested_lineage_authority` **before**
building or returning the replayed response, so a non-attested caller replaying an
operator's correction is `denied`; (2) on a first-time write, after the Issue lock finds
it closed. A replay whose stored revision is not `corrected` is returned as in S1. Stored acceptance basis is `user_confirmed`; the native
rows a composite creates are written with `TaskMutationActor.PRINCIPAL`, as the v1
writers do.

### 6.2 Lock order (S1 §6.2, extended)

1. Reserve the `lineage_write_requests` row.
2. The Issue the write changes `FOR UPDATE`: only `issues.close`, `issues.reopen`, `issues.update`.
3. `FOR SHARE`, ordered by `(family token, identifier)`: every other endpoint, **the context or owning Issue of every link write (new in S2, including S1's `issues.memberships.end` and `records.associations.correct/end`, so they serialize with a close)**, the Commitment of a handoff, the member's native row for every membership write on a Task, Commitment or Constraint member (to read `member_native_version`, section 3.3), the mandatory members' native rows (close), the `project_situations` triplet of a project-qualification check, and every evidence source (S1 rules). **For `issues.close` the evidence sources are both the closure set's and the sources of every `resolution` anchor in every mandatory member's head revision** (the Capture root via `share_capture_root`, which an archive waits on; note versions are immutable and need only `FOR SHARE`), so a Capture archive cannot commit between the gate's availability check and the close (R2-F06).
4. `pg_advisory_xact_lock(LINEAGE_ADVISORY_NAMESPACE, hashtext(key))` with key `principal_id || ':' || normalized_identity` (S1), `principal_id || ':blocks'` (every `blocks` assert, before the cycle search), or `principal_id || ':handoff:' || issue_id || ':' || commitment_id` (a handoff, before reading the latest event). **Total order (R2-F06):** within one write, advisory keys are taken sorted by `(class, key text)` with class order identity < `:blocks` < `:handoff:`; several identity keys (a composite's links) are taken in ascending `normalized_identity` byte order, not ordinal order. Every lineage writer follows this order, so two writers never wait on each other's advisory keys in opposite orders.
5. Association heads `FOR UPDATE` (writers); for `issues.close`, every active membership head of the Issue `FOR SHARE`, ordered by `link_id`.
6. Composite only: the native create (section 6.4) runs after steps 1–4 for its intents' targets (their `FOR SHARE` and any `:blocks`/`:handoff:` key — a composite takes neither). **Its own links' identity locks cannot precede it**, because each identity contains the new record's id (R2-F16): they are taken after the native create and before those links' step 5, all of them in ascending `normalized_identity` byte order. They are fresh and uncontended, so this changes no ordering against another writer.

Reads take no locks. The S1 deadlock analysis and its mapping (lineage side
`conflict` via `TransactionConflictError`; native side a recorded residual) apply
unchanged; a native writer racing a close (for example `constraints.reopen` on a
mandatory Constraint) waits on the close's `FOR SHARE` and proceeds after it commits,
which leaves a closed Issue with a reopened member — a later native fact the Issue
does not follow (no cascade, by design).

### 6.3 Transaction order (S1 §6.3, extended)

1. Switch (`_lineage_plane`), then authority (section 6.1), then strict parse.
2. Request digest; reserve (replay: rebuild from the immutable rows the result names).
3. Locks (6.2); validate endpoints, the matrix (3.1), anchors, expected versions and revisions (`conflict` when stale), the closed-Issue rule (3.2).
4. Write-specific checks: the closure gate (3.3) for `issues.close`; the cycle search (3.1) for `blocks`; the handoff chain (3.4); the composite's native create (6.4).
5. Write rows: anchors (reuse-or-insert, canonical order); Issue revision + evidence + `situations` update; or link root + revision 1 + evidence + head; or link revision + evidence + head update; or the handoff event; composite links and their `lineage_write_request_links` rows.
6. Complete the request row; commit; deferred triggers verify. Any failure rolls back everything, including a composite's native row, its native history receipt and its staged native Record Event.

### 6.4 Composite writes (CR-006)

A composite is one capability whose transaction performs a native create and its
lineage, all on the one `UnitOfWork` `invoke` opened:

- **Native create.** `issues.work.create_task` runs exactly the `tasks.create` path and `issues.work.create_commitment` exactly the `commitments.create` path: the same command class built from the nested object (`CreateTask` / `CreateCommitment`, so every v1 validation and refusal applies unchanged), the same first-write validation (`_validate_task_commitment_state`, Project existence, `_require_work_evidence`, `_require_commitment_create_eligibility`), and the same service call with `active_uow=unit_of_work`, `idempotency_key=None` (the lineage request row is the composite's only idempotency record, reserved first), `source_capability` = the composite's name and `actor = PRINCIPAL`. The implementer extracts the body of `_tasks_create` / `_commitments_create` into a helper both the v1 handler and the composite call; the v1 handlers' behaviour, payloads and responses do not change.
- **Native Record Event.** The native service stages its existing `task` or `commitment` Record Event exactly as for a v1 create, with `source_capability` = the composite name; S2 adds no Record Event family and no lineage event.
- **Membership.** Always written, as ordinal 1: `issue_member` from the Issue to the new record, role `work`, evidence `membership_evidence_anchors` (0..32, S1 membership rule).
- **Intents.** 0..4 `association_intents`, each `{relation_type, to_record, evidence_anchors, purpose?}` with the new record as `from` and the composite's Issue as `context_issue_id`, refused as a whole when any is outside the section 3.1 rules or two share a normalized identity (`invalid_request` / `association_intents`). Admitted relations: `create_task` — `originated_from`, `created_to_resolve`; `create_commitment` — `originated_from`, `delegated_from`, `created_to_resolve`. `originated_from` keeps its S1 rule.
- **Project qualification.** A nested `project_id`, when set, must have an active Project link to the Issue (`invalid_request` / `project_id`), so a cross-Project record joins an Issue only through a Project the Issue is scoped to (AT-017).
- **Refused native fields.** Both nested objects refuse `idempotency_key` and `situation_id` (unknown field ⇒ `invalid_request`). The `task` object of `issues.work.create_task` **also refuses `accepted_by_review_decision_id`** (R2-F04): a Task has a native, non-client acceptance route — `origin_kind: direct_principal` creates it `accepted` with `acceptance_kind = direct_principal` and no review decision (`TaskManagementService.create_task`) — so a composite Task reaches the gate's `accepted` condition only that way; an evidence-origin composite Task is `proposed` and cannot satisfy the gate. The `commitment` object keeps `accepted_by_review_decision_id` with its v1 meaning, because a Commitment has **no** capability-reachable acceptance route other than that field (section 12, D-05 and D-17).
- **Result and replay.** `{record: {family, record_id}, membership: AssociationView, associations: [AssociationView], replayed}`. The request row stores the record and each link revision; a replay rebuilds the views from those immutable revisions (S1 replay rule) and never re-runs the native create. The native record's own view is read with `tasks.read` / `commitments.read`; it is not echoed, so the composite response is byte-stable.

## 7. Capabilities — the exact S2 set

8 new `Capability` members (206 → 214; audit vocabulary 217 → 225) and 1 new `Purpose`
(57 → 58). All are `_SCOPELESS`, classified `CHATLLM_OPERATOR_DECISION_REQUIRED` with
rationale "record lineage S2; exposure is an operator decision (ADR-015, OD-07)", none
operator-only, family `issues` → feature `lineage` in `adapters/mcp/chatllm_gateway.py`.
The 6 writes are in `_WRITE_CAPABILITIES` and `_IDEMPOTENT_REMOTE_CAPABILITIES`;
`issues.handoffs.record`, `issues.work.create_task` and `issues.work.create_commitment`
are also `_ADDITIVE_WRITE_CAPABILITIES`; `issue_work_authoring` joins `_WRITE_PURPOSES`.
All 8 join `_LINEAGE_CAPABILITIES` (section 7.5). Nested request objects declare
`mcp_payload_properties` (precedent `CreateConstraintDraft`). No
`CHATLLM_DATA_PROFILE_VERSION` change is expected; if the profile diff test says
otherwise, bump it and record why.

| Capability | W/R | Purpose | Idempotency / authority | Purpose of the call |
| --- | --- | --- | --- | --- |
| `issues.close` | W | `issue_authoring` | key + `expected_version`, attested | close behind the gate |
| `issues.reopen` | W | `issue_authoring` | key + `expected_version`, attested | reopen a closed Issue |
| `issues.closure_readiness` | R | `issue_read` | — | evaluate the gate without writing |
| `issues.memberships.correct` | W | `issue_authoring` | key + `expected_revision`, attested | replace a membership's evidence set |
| `issues.handoffs.record` | W | `issue_authoring` | key, attested | append one handoff event |
| `issues.handoffs.list` | R | `issue_read` | — | keyset page of an Issue's handoffs |
| `issues.work.create_task` | W | `issue_work_authoring` (new) | key, attested | Task + membership + intents, one UOW |
| `issues.work.create_commitment` | W | `issue_work_authoring` (new) | key, attested | Commitment + membership + intents, one UOW |

`issue_work_authoring` is its own purpose because a composite writes native Work rows:
a grant for Issue authoring must not silently become a grant to create Tasks and
Commitments.

### 7.1 Shared shapes (additions to S1 §7.1)

- Request models are `StrictModel`s / frozen command dataclasses as in S1; no request carries `principal_id`, any holder identifier, `actor_class`, `authority_class`, `decision_channel`, `acceptance_basis`, `review_decision_id` (the one exception: `accepted_by_review_decision_id` inside `issues.work.create_commitment`'s nested `commitment` object, section 6.4), `recorded_at`, `closed_at`, a selector or an exception/override field.
- `IssueClosureView` = `{version, closed_at, outcome, evidence: [EvidenceAnchorView]}` — the latest `closed` revision at or below the current version (a `corrected` revision copies its `closed_at`/`outcome`, the evidence stays the closing revision's). No digest.
- `IssueView` (S1) gains exactly one key, `closure: IssueClosureView | null` (non-null only while `state = closed`). Every S1 key keeps its meaning; `state` may now be `closed`.
- `IssueRevisionView` keeps exactly its S1 keys; `state` and `action` admit the S2 values.
- `ClosureBlockerView` = `{link_id, member: RecordRef, role, native_state, evidence_state (task/commitment, else null), reasons: [IssueClosureBlocker]}`; `native_state` is the native lifecycle token (`lifecycle_state` or `state`).
- `HandoffHolderView` = `{kind: "principal"|"entity", entity_id: ent_|null}`.
- `HandoffView` = `{handoff_id, issue_id, commitment_id, sequence_no, from: HandoffHolderView, to: HandoffHolderView, effective_at, recorded_at, reason, evidence: EvidenceAnchorView, acceptance_basis, authority_class}`.
- `AssociationView` (S1) admits the 4 new `relation_type` values; no key changes.
- Availability in every evidence view is computed at read time (S1 F19), so a replay is byte-identical apart from `replayed` and any availability that changed since.

### 7.2 Per-capability contract

**`issues.close`** — in `{issue_id, expected_version, idempotency_key, outcome (1..2000, non-blank), closure_evidence_anchors ([1..32])}`;
out `{issue: IssueRevisionView, closure: IssueClosureView, replayed}`. The Issue must be
`open`, `active` or `suspended` (`closed` is `conflict` / `state`). Evaluates the gate
(3.3) under the section 6.2 locks; any blocker, or a closure set without an available
`immutable_version` `resolution` anchor, is refused — a blocker as `conflict` /
`closure_gate`, a set rule as `invalid_request` / `closure_evidence_anchors`; nothing is
written. Writes revision `version + 1` action `closed`, state `closed`, `closed_at` =
server now, `outcome`, its evidence rows and digest, and the `situations` row.

**`issues.reopen`** — in `{issue_id, expected_version, idempotency_key, reason (1..2000, non-blank), evidence_anchors? ([0..32])}`;
out `{issue: IssueRevisionView, reopening: {reason, evidence: [EvidenceAnchorView]}, replayed}`.
Only from `closed` (`conflict` / `state` otherwise). The anchors are admitted by the
S1 rules with any role and stored as the revision's evidence set. Writes action `reopened`, state
`active`, clears `closed_at`/`outcome` on `situations`. Reopens no member, link or
native record.

**`issues.update` (S2 delta)** — on a closed Issue: attested (section 6.1, else
`denied`), `title`/`description`/`clear_fields` only (a `state` is `invalid_request` /
`state`), action `corrected`, state stays `closed`, `closed_at`/`outcome` copied. `state: closed` is never admitted
(`invalid_request` / `state`); closing is `issues.close` only. Otherwise S1.

**`issues.closure_readiness`** — in `{issue_id}`; out
`{issue_id, version, state, ready, blockers: [ClosureBlockerView] (<= 100), blockers_truncated}`.
Current state, no locks. `ready` is true only when the Issue is not `closed` and no
mandatory member is blocked; it says nothing about closure evidence (that is supplied
to `issues.close`). Blockers are ordered by `(member family, member record_id, link_id)`;
satisfied members are not listed. A closed Issue answers `ready: false`, `blockers: []`.

**`issues.memberships.correct`** — in `{link_id, expected_revision, idempotency_key, reason (1..2000), evidence_anchors ([0..32])}`;
out `{membership: AssociationView, replayed}`. Membership links only (a semantic id is
`invalid_request` / `link_id`, the S1 symmetric rule). The set is the complete new set,
satisfies the membership rule (0..32, any role) and differs from the current digest
(else `invalid_request` / `evidence_anchors`), except the section 3.3 re-affirmation (an
identical set with ≥1 `resolution` anchor when the member's native `version` has moved
since the head's `member_native_version`). Writes `correct_evidence` with the observed
`member_native_version`; root, role and identity never change. This is how resolution
evidence (role `resolution`) is recorded on a mandatory member, after its native close.

**`issues.handoffs.record`** — in `{issue_id, commitment_id, from ("principal"|"counterparty"), effective_at (ISO-8601 with offset), reason (1..2000), evidence_anchor: EvidenceAnchorInput, idempotency_key}`;
out `{handoff: HandoffView, replayed}`. Section 3.4 rules; the anchor's role must be
`handoff` and its kind `immutable_version` (`invalid_request` / `evidence_anchor`).
Writes event `sequence_no = latest + 1`. **As implemented (K2):** the request key is
`from_side` (`from` is a Python keyword); its refusal still names `from`.

**`issues.handoffs.list`** — in `{issue_id, commitment_id?, page_size? (1..100, default 25), after? (ihnd_)}`;
out `{handoffs: [HandoffView], next_cursor}` ordered `(recorded_at, handoff_id)`
ascending, `next_cursor` the last `handoff_id` when more rows exist; `page_size` above
100 is `invalid_request` / `page_size` (never clamped) and is further bounded by
`max_page_size`; an `after` outside the filter is `invalid_request` / `cursor`. The
Issue and a supplied `commitment_id` are checked in the S1 §3.2 order: an absent or
foreign Issue or Commitment is `not_found` (`issue_id` / `commitment_id`), alike; an
owned Commitment with no event in this Issue answers an empty page, never `not_found`.

**`issues.work.create_task`** — in `{issue_id, idempotency_key, task: {the tasks.create payload without idempotency_key and situation_id}, membership_evidence_anchors? ([0..32]), association_intents? ([0..4])}`;
out section 6.4. A follow-up Task (`role: follow_up`, `commitment_id`) of a **closed**
Commitment is admitted, because the v1 rule admits it (section 12, D-04); the
Commitment is not reopened or changed.

**`issues.work.create_commitment`** — in `{issue_id, idempotency_key, commitment: {the commitments.create payload without idempotency_key and situation_id}, membership_evidence_anchors? ([0..32]), association_intents? ([0..4])}`;
out section 6.4. A `delegated_from` intent needs the nested `direction:
owed_to_principal`; the native Commitment's counterparty, direction, due date and
acceptance are exactly what the nested object states, and no handoff is written.

S1 capabilities other than `issues.update` keep their S1 request shapes; their only S2
behaviour changes are the closed-Issue refusal (3.2), the new Issue `FOR SHARE` lock on
link revisions (6.2), the widened `relation_type` set on `records.associations.assert`
(`escalated_from`, `blocks` admitted; `delegated_from`, `created_to_resolve` refused),
`issues.list`'s `state` filter admitting `closed`, and the `IssueView.closure` key.

### 7.3 Errors (additions to S1 §7.3)

| Situation | Code / safe detail |
| --- | --- |
| an unsatisfied mandatory member at close | `conflict` / `closure_gate` |
| a write naming a closed Issue (3.2); close of a closed or reopen of a non-closed Issue | `conflict` / `state` |
| a concurrent handoff took the sequence number | `conflict` / `stale_version` (retry after re-reading) |
| handoff `from` names a side the chain's last holder is not on | `invalid_request` / `from` |
| a correction of a closed Issue by a non-attested caller | `denied` |
| closure set rule; handoff anchor role/kind | `invalid_request` / `closure_evidence_anchors`, `evidence_anchor` |
| `blocks` would close a cycle or exceed the search bound | `invalid_request` / `blocks_cycle` |
| `effective_at` after now, before the Commitment's creation or before the previous handoff's; missing `purpose`; composite intent rule; project not linked | `invalid_request` / `effective_at`, `purpose`, `association_intents`, `project_id` |
| `delegated_from` direction | `invalid_request` / `direction` |
| ordinary or remote caller on any S2 write | `denied` |
| switch off | `unsupported` |

New `SafeDetail` members (`closure_gate`, `closure_evidence_anchors`, `evidence_anchor`,
`blocks_cycle`, `effective_at`, `purpose`, `association_intents`, `direction`, `from`, and any
other named here that is absent) are added with the code that reports them; reuse an
existing member when one with the same token exists.

### 7.4 Web (lockstep widening of the S1 display)

S2 adds no `gateway.json` entry (107 stay 107) and no BFF route. `records.lineage` is
the one served lineage contract with a strict web decoder, and S2 widens two of its
closed sets, so the decoder moves in the same change:

- `web/src/lib/api/decode/capabilities/records.lineage.ts`: `relation_type` admits the 4 S2 types; `ISSUE_STATES` admits `closed`. Nothing else changes; an unknown value still refuses the whole answer.
- `web/src/components/work/related-issues.tsx`: direction words "delegated from", "escalated from", "blocks" / "blocked by" (by which endpoint is the viewed record), "created to resolve"; a `closed` Issue reads "closed".
- `web/src/lib/api/decode/fixtures/python/success.json` keeps its keys (no new key); the parity tests stay green.
- **As implemented (K4):** the decoder exports the two widened closed sets as
  `RELATION_TYPES` and `ISSUE_STATES`; the panel words an incoming
  `created_to_resolve` (the viewed Constraint is the target) as "A Task was created to
  resolve it" (or "A Commitment …"). `gateway.json` still holds 107 entries.

This is admissible only because `records.lineage` was added by S1 on this unmerged,
undeployed branch line; once any lineage contract is deployed, a widening needs a
negotiated version (section 8).

### 7.5 Admission switch

S1 §7.5 unchanged: `MY_PA_LINEAGE_ENABLED` (default off) withholds all 22 lineage
capabilities (the 14 S1 names and the 8 above) through `_LINEAGE_CAPABILITIES`, and every
S2 handler calls `_lineage_plane` first, so a byte-identical replay of a write
committed while on answers `unsupported` when off. The composites are served only
when the switch is on; turning it off leaves the v1 `tasks.create` / `commitments.create`
paths untouched.

## 8. Old-client compatibility rule

- **v1 shapes are byte-identical.** No v1 request or response changes: `tasks.*`, `commitments.*` (including `commitments.read`'s single `follow_up_task_*` fields, section 12, D-04), `constraints.*`, `meetings.*`, `continuity.*`. A row created by a composite is indistinguishable in every v1 read from a `tasks.create` / `commitments.create` row with the same fields; the only trace is the native Record Event's `source_capability` string, a field whose v1 type is an unconstrained bounded operation name.
- **The strict web client** keeps every `gateway.json` entry, decoder and `success.json` key byte-for-byte except the 2 enum widenings of section 7.4 in the S1-added `records.lineage` decoder, guarded by a vitest that the decoder's closed sets equal the server vocabulary. **As implemented (K4):** the vitest pins the literals from the web side and the FAST `test_the_web_lineage_decoder_admits_exactly_the_server_vocabulary` (`tests/architecture/test_record_lineage_s2_scope.py`) reads the decoder source and compares both sets with `RelationType` and `ISSUE_STATES`, so the equality is checked across the language boundary.
- **S1 lineage contracts** (server-only, never deployed): widened only by the additions section 7 lists; no S1 key is removed, renamed or re-meant.
- **`continuity.situations`** still lists context Situations only; a closed Issue is still an Issue and never appears there.
- Any later change to a deployed contract needs an explicit negotiated version and a strict-client regression fixture (S1 §8).

## 9. File plan and registration

New modules (resolve exact names against neighbours; no refactor beyond the extractions named):

- `domain/lineage/vocabulary.py` (widened), `domain/situation/issue_lifecycle.py` (close/reopen/correct moves), new `domain/lineage/closure.py` (pure gate: `member_blockers(member, native, head_evidence, availability) -> tuple[IssueClosureBlocker, ...]`, `MANDATORY_MEMBER_ROLES`), new `domain/lineage/handoff.py` (holder resolution and chain rule).
- `application/issues.py` (close, reopen, readiness, correction), `application/record_lineage.py` (`correct_membership`; the Issue `FOR SHARE` in `_revise`; the S2 matrix rules and `blocks` cycle search, via `lineage_endpoints.py`), new `application/issue_handoffs.py`, new `application/issue_work.py` (the 2 composites; it calls the extracted native helpers and the root-writing helper extracted from `RecordLineageApplication._assert_root`, whose S1 behaviour is unchanged).
- `infrastructure/persistence/issues.py`, `infrastructure/persistence/record_lineage.py` (closure evidence, readiness reads, `blocks` reachability, request links), new `infrastructure/persistence/issue_handoffs.py`; `contracts/v1/issues.py`, `contracts/v1/record_lineage.py` (S2 views), `application/commands.py`, `adapters/normalization.py`, `application/service.py` handlers, `domain/identity/operation.py` / `purpose.py` registrations, `ports.py` (`IssueRepository` / `RecordLineageRepository` additions; `UnitOfWork` gains abstract `issue_handoffs`, implemented or stubbed in every subclass).
- Every W1 §2.2 / §5.4 registration step and count pin applies (capability, purpose and audit counts, head literal and head-pin list, revision count, `TABLES_SHA256`, `TABLES_ABOVE`, principal-partition guard registry, spelled counts in `adapters/cli/app.py`, `bootstrap/gateway.py`, the architecture index and READMEs).

Work split (the S2 run plan): **K1** the revision and `tables.py` (all of section 4, including tables later workers use), vocabulary and `IdKind`, Issue close/reopen/correct, closure evidence, `issues.closure_readiness`, `issues.memberships.correct`, the closed-Issue rule and the Issue `FOR SHARE` on link revisions, and the registration of all 8 names; **K2** handoffs and the 2 composites with `delegated_from` and `created_to_resolve`; **K3** `escalated_from`, `blocks` and its cycle refusal, the WP-02D Series and context-isolation tests, AT-017; **K4** AT-001 14 stages, the web widening, hardening, docs sync.

## 10. Acceptance-test crosswalk

Same conventions as S1 §10 (tier = marker selection; FAST = no marker; names binding;
a renamed test updates this table in the same commit; every path new unless marked
existing). `tests/architecture/test_record_lineage_s2_scope.py` parses this table the
way the S1 scope guard parses S1 §10.

| AT (S2 part) | Module | Test functions | Tier |
| --- | --- | --- | --- |
| AT-001 (all 14 stages, scenarios A, B, H) | `tests/integration/test_issue_lineage_14step.py` | `test_fourteen_stages_end_to_end_with_reconciliation_gates`; `test_stage_14_before_stage_13_is_refused_and_writes_nothing`; `test_closing_c1_records_no_handoff_and_creates_no_task`; `test_t1_follows_up_a_closed_c1_without_reopening_it`; `test_a_shared_series_a_links_no_other_issue`; `test_creating_x1_changes_no_task_or_issue_state`; `test_one_delegate_closing_leaves_the_other_open`; `test_m3_in_series_b_imports_no_series_sibling`; `test_completing_t1_changes_no_constraint_or_issue`; `test_m4_resolution_words_cannot_close_x1_or_the_issue`; `test_every_root_yields_the_same_current_issue_graph_after_stage_14`; `test_n1b_never_retargets_c1_across_the_workflow` | database |
| AT-005 | `tests/integration/test_responsibility_handoff.py` | `test_closing_a_commitment_writes_no_handoff`; `test_an_explicit_handoff_records_counterparty_then_principal`; `test_a_handoff_needs_an_exact_handoff_anchor`; `test_a_handoff_names_only_the_principal_and_the_counterparty`; `test_a_handoff_chain_continues_from_the_last_holder`; `test_a_handoff_effective_after_now_is_refused`; `test_a_handoff_subject_must_be_an_active_member`; `test_a_follow_up_task_of_a_closed_commitment_is_admitted`; `test_two_delegations_create_two_independent_commitments`; `test_delegated_from_requires_an_owed_to_principal_commitment`; `test_creation_relations_are_refused_by_assert`; `test_completing_t1_closes_no_delegated_commitment`; `test_no_handoff_is_inferred_for_a_delegate`; `test_handoffs_list_returns_the_sequence_in_order`; `test_a_counterparty_repoint_leaves_the_chain_continuable`; `test_a_handoff_from_the_wrong_side_is_refused`; `test_a_handoff_effective_before_its_predecessor_is_refused`; `test_a_foreign_commitment_answers_like_an_absent_one_for_handoffs`; `test_handoffs_list_of_a_foreign_commitment_is_not_found` | database |
| AT-005 / CR-006 (composites) | `tests/database/test_issue_work_composites.py` | `test_a_composite_writes_native_row_membership_and_links_atomically`; `test_a_refused_composite_writes_no_native_row_or_request`; `test_a_composite_replay_returns_the_original_result_without_a_native_write`; `test_a_composite_refuses_situation_id_and_idempotency_key_inside_the_native_object`; `test_a_composite_project_outside_the_issue_links_is_refused`; `test_a_composite_emits_only_its_native_record_event`; `test_a_composite_native_row_reads_like_a_v1_create`; `test_created_to_resolve_needs_a_purpose`; `test_a_composite_task_refuses_a_review_decision_id` | database |
| AT-006 + WP-02D | `tests/integration/test_issue_context_isolation.py` | `test_a_meeting_with_three_issues_offers_three_choices`; `test_each_issue_returns_only_its_own_passage_links`; `test_one_shared_meeting_imports_no_other_issue_member`; `test_series_reassignment_changes_no_lineage_row_or_answer`; `test_a_cross_series_meeting_keeps_its_series_and_imports_no_sibling` | database |
| AT-007 + AT-015 (S2) | `tests/integration/test_issue_close_reopen.py` | `test_close_requires_an_available_resolution_anchor`; `test_a_legacy_anchor_never_satisfies_closure`; `test_a_contradicting_anchor_refuses_closure`; `test_an_open_mandatory_member_refuses_closure`; `test_a_cancelled_task_member_refuses_closure`; `test_a_void_constraint_member_refuses_closure`; `test_a_proposed_closed_commitment_is_not_counted_accepted`; `test_a_member_without_resolution_evidence_refuses_closure`; `test_archived_resolution_evidence_refuses_closure`; `test_a_contradicted_member_refuses_closure`; `test_non_mandatory_members_do_not_gate_closure`; `test_ending_a_membership_is_the_only_way_past_an_unsatisfiable_member`; `test_close_changes_no_member_or_link`; `test_reopen_changes_no_member_or_link`; `test_a_reopened_constraint_does_not_reopen_the_issue`; `test_a_closed_issue_refuses_lineage_writes`; `test_closure_readiness_names_each_blocked_member`; `test_an_exception_field_is_refused`; `test_correcting_a_closed_issue_keeps_it_closed`; `test_closure_is_never_admitted_through_issues_update`; `test_resolution_evidence_recorded_before_a_reclose_refuses_closure`; `test_resolution_evidence_recorded_while_the_task_was_open_refuses_closure`; `test_a_same_set_reaffirmation_after_a_reclose_is_admitted`; `test_a_correction_of_a_closed_issue_needs_the_local_operator` (both cases: a first-time correction and a byte-identical replay of an operator's committed correction by a non-attested caller, each `denied`); `test_a_same_set_correction_without_a_resolution_anchor_stays_refused` (FR2-F03). As implemented (FR2-F02): `test_a_closed_issue_refuses_lineage_writes` also refuses `records.associations.correct` and `records.associations.end` of a `blocks` link whose `context_issue_id` is the closed Issue, and `issues.project_links.end` of a Project link active at the close | database |
| AT-007 (races) | `tests/concurrency/test_issue_close_races.py` | `test_concurrent_closes_with_one_expected_version_admit_one`; `test_close_racing_a_membership_add_serializes`; `test_close_racing_a_membership_end_serializes`; `test_close_racing_a_constraint_reopen_serializes`; `test_concurrent_blocks_asserts_cannot_form_a_cycle`; `test_concurrent_handoffs_on_one_commitment_admit_one`; `test_close_racing_a_resolution_source_archive_serializes`; `test_concurrent_reopens_with_one_expected_version_admit_one` | database |
| AT-017 (scenario D) | `tests/integration/test_shared_issue_crossproject.py` | `test_one_issue_links_two_projects_once_each`; `test_two_constraints_in_two_projects_are_independent_members`; `test_closing_one_constraint_closes_neither_the_other_nor_the_issue`; `test_an_escalation_outside_a_linked_project_is_refused`; `test_project_links_create_no_generic_membership` | database |
| WP-02C relation rules | `tests/database/test_lineage_s2_relation_rules.py` | `test_s2_relations_are_admitted_only_in_the_matrix`; `test_escalated_from_needs_an_origin_anchor_and_a_context`; `test_escalated_from_refuses_a_draft_or_an_older_constraint`; `test_blocks_needs_corroborating_evidence`; `test_a_blocks_self_loop_is_refused`; `test_a_blocks_cycle_is_refused`; `test_a_blocks_search_past_its_bound_is_refused`; `test_task_completion_closes_no_constraint_or_issue`; `test_a_correction_reapplies_only_the_evidence_rules`; `test_lineage_writes_leave_constraint_bic_unchanged` (as implemented: the direct-insert refusal of a context-free escalation by `an_escalation_is_issue_scoped` is asserted inside `test_escalated_from_needs_an_origin_anchor_and_a_context`) | database |
| AT-012 (S2 guards) | `tests/database/test_lineage_s2_integrity_guards.py` | `test_s2_immutable_tables_refuse_update_and_delete` (3 tables); `test_s2_tables_refuse_truncate` (3 tables, each holding a row); `test_an_issue_cannot_close_without_a_matching_revision`; `test_a_closure_revision_follows_the_lifecycle`; `test_a_closed_revision_carries_its_closure_fields`; `test_a_closing_revision_has_evidence`; `test_issue_closure_evidence_is_frozen`; `test_an_issue_closure_row_is_local_operator_attested`; `test_a_handoff_follows_its_predecessor_holder`; `test_a_handoff_changes_its_holder`; `test_a_handoff_cannot_be_effective_after_recording`; `test_a_handoff_cannot_be_effective_before_its_commitment`; `test_a_handoff_cannot_be_effective_before_its_predecessor`; `test_a_member_native_version_is_recorded_only_by_membership_writes`; `test_a_blocks_root_cannot_name_itself`; `test_a_creation_link_needs_its_composite`; `test_created_to_resolve_revision_one_states_its_purpose`; `test_a_composite_request_names_its_record_and_links`; `test_an_s2_write_request_completes_once`; `test_closure_evidence_digest_rebuilds_from_stored_rows` | database |
| AT-012 (migration) | `tests/schema/test_record_lineage_s2_migration.py` | FAST: `test_the_revision_is_the_single_head_on_264310e0416a`; `test_the_revision_imports_no_domain_module`; `test_frozen_ddl_names_every_declared_constraint`; `test_before_texts_are_byte_copies_of_the_s1_texts`; `test_at_vocabulary_adds_exactly_the_s2_names`; `test_offline_downgrade_refuses_first`. DB: `test_empty_to_head`; `test_s1_head_with_rows_upgrades_unchanged`; `test_downgrade_refuses_while_s2_rows_exist`; `test_downgrade_restores_every_s1_text`; `test_each_downgrade_refusal_family_alone_refuses` (FR2-F01: one case per refusal predicate family, 9 cases, each seeding exactly one S2 fact, one of them an S1-capability `issues.memberships.add` revision carrying `member_native_version`) | FAST + migration markers |
| AT-023 (S2) | `tests/contract/test_lineage_s2_capability_admission.py` | `test_s2_capabilities_are_operator_decision_required`; `test_s2_requests_reject_server_owned_fields`; `test_existing_v1_shapes_are_unchanged_by_s2`; `test_s1_lineage_views_keep_every_s1_key`; `test_switch_off_withholds_every_s2_capability`; `test_composite_native_objects_mirror_the_v1_requests` (expected difference, exactly: both objects lack `idempotency_key` and `situation_id`; the `task` object also lacks `accepted_by_review_decision_id`); `test_issue_work_authoring_is_its_own_purpose`; `test_assert_admits_exactly_the_s2_relations_it_writes` (added by K3: the assert's published `relation_type` set is the semantic relations less the composite-only ones); `test_composite_native_objects_refuse_malformed_values_like_the_v1_requests` (FR2-F05: the composites' own nested conversion refuses each malformed `due_at`, `priority`, `role`, `origin_kind`, `direction`, `title`, `summary` and counterparty value with the same error class, safe details and choices as `tasks.create` / `commitments.create`) | FAST |
| AT-023 (S2, DB) | `tests/database/test_lineage_s2_attested_writes.py` | `test_an_ordinary_remote_client_is_denied_every_s2_write`; `test_a_replayed_s2_write_from_an_ordinary_client_is_denied_before_the_replay_lookup`; `test_switch_off_answers_unsupported_for_every_s2_capability`; `test_every_s2_capability_answers_a_foreign_subject_like_an_absent_one` | database |
| (domain) | `tests/unit/test_issue_closure_gate.py` | `test_mandatory_roles_are_work_and_constraint`; `test_member_blockers_by_family_and_state`; `test_resolution_evidence_rules`; `test_close_reopen_and_correct_moves`; `test_handoff_holders_follow_the_chain_and_the_current_counterparty` | FAST |
| AT-024 (S2, web decoder) | existing `web/src/lib/api/decode/capabilities/records.lineage.test.ts` | `decodes the S2 relation types and a closed Issue`; `refuses a relation type outside the S2 vocabulary` | vitest |
| AT-024 (S2, web component) | existing `web/src/components/work/related-issues.test.tsx` | `renders delegated, escalated, blocking and resolving relations in words`; `renders a closed Issue as closed` | vitest |
| AT-026 (S2) | `tests/architecture/test_record_lineage_s2_scope.py` | `test_s2_adds_no_record_event_family`; `test_every_s2_crosswalk_test_exists`; `test_s2_modules_stage_no_lineage_record_event`; `test_the_web_lineage_decoder_admits_exactly_the_server_vocabulary` (added by K4, section 8) | FAST |

**As implemented (K4).** Every row above exists (`test_every_s2_crosswalk_test_exists`)
and executes: the 14 Python modules collect 183 tests (parametrized cases included), all
selected by their tier markers, and at the K4 FR2-corrective head all 183 pass with none
skipped; the 4 vitest titles pass in `npm test`. Tests not named by the package were added
and are listed in their rows (`test_assert_admits_exactly_the_s2_relations_it_writes`, K3;
`test_the_web_lineage_decoder_admits_exactly_the_server_vocabulary`, K4; the FR2-F01,
F03 and F05 tests). In AT-001 a
note version that no link names (N1b, and J's own note) is reached only as its
Meeting's virtual edge, never as a node, as S1 section 7.2 resolved.

**S1 regressions (binding, must stay green; unchanged except the listed lockstep
moves, R2-F08):** every test of S1 §10 and every v1 suite. The only edits admitted,
each keeping its test name and changing only the moved literal or set:

- `tests/unit/test_lineage_canonical.py` `test_issue_states_are_the_non_terminal_situation_states`: its oracle moves from `SituationState − {closed}` to all 4 `SituationState` members (the name stays; the docstring states S2 admits `closed`).
- `tests/schema/test_record_lineage_s1_migration.py` `test_the_revision_is_the_single_head_on_b9025e7fb738`: keeps asserting the S1 revision's place in the chain; its head literal and revision count (119 → 120) move.
- **Head pins:** every file named by the head-pin list (`test_the_head_pin_list_is_the_files_that_actually_pin_the_head`, 49 test files under `tests/` cite `264310e0416a` at the basis, including v1 suites such as `tests/schema/test_work_task_commitment_migration.py`) moves its head literal to the S2 revision, and only that literal; the list gains the S2 migration test.
- **Count pins:** tests and docs pinning the capability count (206), purpose count (57), audit-vocabulary count (217), revision count and `TABLES_SHA256` move to the S2 values (section 7), and only those literals.
- The `records.lineage` decoder and component tests gain cases without losing any.
- **The further lockstep edits recorded as section 12, D-18** (registry and parametrization additions for the 8 S2 names, S1 lineage tests narrowed to the S1 subset of a set S2 widened, the S1 migration suite reading columns the S2 revision now owns, and the S1 truncate probe including the 3 S2 tables). Each keeps its test name and its S1 assertion.

No other S1 or v1 test is edited. Also existing and binding:
`tests/contract/test_bff_gateway_contract_parity.py`,
`tests/contract/test_bff_success_decoder_parity.py`,
`web/src/lib/api/decode/registry.test.ts`, and the v1 Work, Constraint and Meeting
suites (no v1 test edited).

**AT-001 stage → call map** (synthetic Principal A and B; Series A and B; M1..M4 with
note versions N1..N4 and N1b; C1..C3; T1; X1 in Project P linked to I; counterparties
P1..P3 as `ent_` rows from the existing Entity fixtures; E0, E1 synthetic Capture
versions). **Acceptance (R2-F04):** T1 is created `origin_kind: direct_principal`, so it
is natively `accepted` (`acceptance_kind = direct_principal`) with no review decision;
C1, C2 and C3 carry a synthetic `rdec_` in the nested `accepted_by_review_decision_id`,
the only route a Commitment has to `accepted` (section 12, D-05, D-17). Each
`memberships.correct` with a `resolution` anchor runs after its member's native close,
so its `member_native_version` is the closed version:

| Stage | Calls | Gate asserted after the stage |
| --- | --- | --- |
| 1 | `meetings.create` M1 (Series A); `issues.create` I; `issues.project_links.add` I→P; `issues.memberships.add` I→M1 `discussion` | no Commitment exists |
| 2 | `meetings.update` M1 note → N1 | N1 immutable, digest H1 |
| 3 | `issues.work.create_commitment` C1 (P1, `owed_to_principal`) with an `originated_from` N1 intent | lineage from I = {I, M1, N1, C1} |
| 4 | `commitments.close` C1; `issues.memberships.correct` I→C1 + `resolution` (E0); `issues.handoffs.record` C1 `from: counterparty` | 0 handoffs before the record call; then 1 (P1 → Principal); no Task |
| 5 | `issues.work.create_task` T1 (`direct_principal`, `follow_up`, `commitment_id` C1) | C1 version and state unchanged |
| 6 | `meetings.create` M2 (Series A) + N2; `issues.memberships.add` I→M2; `records.associations.assert` `discusses` N2→T1 | nodes add T1, M2, N2; Issue J on another Series A Meeting not reached |
| 7 | `constraints.create_published` X1 (Project P); `issues.memberships.add` I→X1 `constraint`; `records.associations.assert` `escalated_from` X1→T1 | T1 and I unchanged |
| 8 | `issues.work.create_commitment` C2 (P2) and C3 (P3), each `delegated_from` T1 | 2 Commitments, 0 new handoffs |
| 9 | `meetings.create` M3 (Series B) + N3; `issues.memberships.add` I→M3; 4 `discusses` N3→T1, X1, C2, C3 on 4 passages | nodes add X1, C2, C3, M3, N3; a Series B sibling linked to J not reached |
| 10 | `commitments.close` C2, then `memberships.correct` C2; later the same for C3 | between the two, readiness blocks C3, T1, X1 |
| 11 | `tasks.transition` T1 `completed`; `memberships.correct` T1 | X1 open; I open; readiness blocks X1 only |
| 12 | `meetings.create` M4 (Series A) + N4; `issues.memberships.add` I→M4; `discusses` N4→I, X1, T1; `issues.close` with an N4 `resolution` anchor | the close is `conflict` / `closure_gate`, no row |
| 13 | `constraints.close` X1; `memberships.correct` I→X1 + `resolution` (E1) | readiness `ready`; I still open |
| 14 | `issues.close` I (`resolution` E1, `corroborates` N4) | I closed at `version + 1`; reverse roots below |

**Reverse-root equivalence.** S2 part: after stage 14, `records.lineage` with
`issue_id = I` from each of M1, M2, M3, M4, N1, N2, N3, N4, C1, C2, C3, T1, X1 and I
returns the same node set, the same typed-edge `link_id` set, the same virtual-edge set
and `complete_state = complete` (every note version that matters is a link endpoint, so
it is a node from every root). S3 part: equality at one `known_at` / `valid_at`, the
14-stage event ordering, cursor exhaustion, path explanations and revoked-body
redaction.

**Prove-red expectations** (break exactly that one guard, show the named test red for
that reason, restore; a green prove-red is reported as redundancy, a masked test or an
unreachable hazard, never as "covered"):

| Guard | Break | Test that must redden |
| --- | --- | --- |
| `an_issue_matches_its_latest_revision` (replaced) | drop the `closed_at`/`outcome` equality | `test_an_issue_cannot_close_without_a_matching_revision` |
| `an_issue_closure_follows_its_predecessor` | return NEW unconditionally | `test_a_closure_revision_follows_the_lifecycle` |
| `an_issue_revision_closes_exactly_when_closed` | drop the CHECK | `test_a_closed_revision_carries_its_closure_fields` |
| `an_issue_closing_revision_has_evidence` | drop the CHECK | `test_a_closing_revision_has_evidence` |
| `an_issue_revision_evidence_set_is_frozen` | drop either trigger | `test_issue_closure_evidence_is_frozen` |
| `an_issue_closure_is_operator_attested` | drop the CHECK | `test_an_issue_closure_row_is_local_operator_attested` |
| `a_handoff_follows_its_predecessor` | return NEW unconditionally | `test_a_handoff_follows_its_predecessor_holder` |
| `a_handoff_is_effective_in_order`, Commitment clause | drop that clause only (direct database insert) | `test_a_handoff_cannot_be_effective_before_its_commitment` |
| `a_handoff_is_effective_in_order`, predecessor clause | drop that clause only (direct database insert) | `test_a_handoff_cannot_be_effective_before_its_predecessor` |
| handoff application time check | remove the application check (the trigger still refuses; the test asserts the safe `invalid_request` / `effective_at` answer and no row, so it reddens only if the trigger's refusal is mapped differently — report a green result as the trigger masking the check) | `test_a_handoff_effective_before_its_predecessor_is_refused` |
| `only_membership_writes_record_a_member_version` | drop the CHECK | `test_a_member_native_version_is_recorded_only_by_membership_writes` |
| gate: stale resolution evidence | skip the `member_native_version` equality | `test_resolution_evidence_recorded_before_a_reclose_refuses_closure` (the T1-open variant `test_resolution_evidence_recorded_while_the_task_was_open_refuses_closure` reddens with it) |
| re-affirmation admission | keep refusing every same-digest correction | `test_a_same_set_reaffirmation_after_a_reclose_is_admitted` |
| handoff leaving side from the chain | resolve the leaving side from the current counterparty | `test_a_counterparty_repoint_leaves_the_chain_continuable` |
| close shares member resolution sources | share only the closure set's sources | `test_close_racing_a_resolution_source_archive_serializes` |
| corrected revisions attested (`an_issue_closure_is_operator_attested` covers `corrected`; handler derives attested authority) | drop `corrected` from the CHECK and use `lineage_authority` | `test_a_correction_of_a_closed_issue_needs_the_local_operator` |
| attested replay of a `corrected` revision | return the replay before deriving attestation | `test_a_correction_of_a_closed_issue_needs_the_local_operator` (replay case) |
| composite Task refuses a review decision id | admit the field | `test_a_composite_task_refuses_a_review_decision_id` |
| `a_handoff_changes_its_holder` / `a_handoff_is_not_effective_after_recording` | drop each CHECK in turn | `test_a_handoff_changes_its_holder` / `test_a_handoff_cannot_be_effective_after_recording` |
| `a_blocks_link_names_two_records` | drop the CHECK (application check bypassed by a direct insert) | `test_a_blocks_root_cannot_name_itself` |
| `a_creation_link_is_written_by_its_composite` | drop the CHECK | `test_a_creation_link_needs_its_composite` |
| `a_resolution_link_states_its_purpose` | drop the trigger | `test_created_to_resolve_revision_one_states_its_purpose` |
| `a_composite_request_names_its_links` | drop the trigger | `test_a_composite_request_names_its_record_and_links` |
| append-only / truncate on each new table | detach for one table | the parametrized case for that table |
| gate: native state | treat every member as satisfied | `test_an_open_mandatory_member_refuses_closure` |
| gate: acceptance | ignore `evidence_state` | `test_a_proposed_closed_commitment_is_not_counted_accepted` |
| gate: resolution evidence / availability / contradiction | skip each check in turn | `test_a_member_without_resolution_evidence_refuses_closure` / `test_archived_resolution_evidence_refuses_closure` / `test_a_contradicted_member_refuses_closure` |
| closure set rule | admit a set with no `resolution` anchor | `test_close_requires_an_available_resolution_anchor` |
| closed-Issue rule | skip it in `issues.memberships.add` | `test_a_closed_issue_refuses_lineage_writes` |
| Issue `FOR SHARE` in `_revise` | remove it | `test_close_racing_a_membership_end_serializes` |
| `blocks` cycle search / advisory lock | skip the search; skip the lock | `test_a_blocks_cycle_is_refused`; `test_concurrent_blocks_asserts_cannot_form_a_cycle` |
| handoff advisory lock | skip it | `test_concurrent_handoffs_on_one_commitment_admit_one` |
| handoff holder pairing / membership | accept any holder; skip the membership check | `test_a_handoff_names_only_the_principal_and_the_counterparty`; `test_a_handoff_subject_must_be_an_active_member` |
| `delegated_from` direction; escalation project link | skip each | `test_delegated_from_requires_an_owed_to_principal_commitment`; `test_an_escalation_outside_a_linked_project_is_refused` |
| composite atomicity | commit the native create before the links | `test_a_refused_composite_writes_no_native_row_or_request` |
| attested S2 writes; switch | use `lineage_authority`; drop `_lineage_plane` in one handler | `test_an_ordinary_remote_client_is_denied_every_s2_write`; `test_switch_off_answers_unsupported_for_every_s2_capability` |
| decoder closed set | add a value the server never sends | `refuses a relation type outside the S2 vocabulary` |
| downgrade refusal, each predicate family (FR2-F01) | delete that family's clause from `_REFUSE_DOWNGRADE` (for `record_link_revisions`, only `OR member_native_version IS NOT NULL`) | the matching case of `test_each_downgrade_refusal_family_alone_refuses` |
| closed-Issue rule on semantic-link context and Project-link end (FR2-F02) | name the context Issue for memberships only; skip the closed check on `issues.project_links.end` | `test_a_closed_issue_refuses_lineage_writes` |
| re-affirmation needs a `resolution` anchor (FR2-F03) | drop `has_resolution_anchor` from the re-affirmation condition | `test_a_same_set_correction_without_a_resolution_anchor_stays_refused` |
| composite nested conversion parity (FR2-F05) | change one composite-side refusal detail | `test_composite_native_objects_refuse_malformed_values_like_the_v1_requests` |

**Not S2:** AT-008, AT-011, AT-013, AT-014, AT-016, AT-024 Meeting view, timeline and
graph, AT-025, the S3 part of the reverse-root equivalence → S3; AT-015 Program v2
reads and project-scoped Commitment lists, AT-018, AT-019, AT-022, AT-023 Commitment
v2 → Program/report work packages; AT-020, AT-021 → out of scope until OD-06.

## 11. Deferred work and its owner slice

| Item | Slice |
| --- | --- |
| `related_context` (symmetric canonical order), `contest` / `reinstate`, `contested` state | S3 |
| `issues.history`, `records.associations.history`, `list_for_record`, `known_at` / `valid_at`, cursors, native virtual edges beyond `meeting_note_version_of`, `explain_paths`, timeline | S3 |
| Decision membership (`decision` role, `continuity_decision` family) and a Decision capability family | S3 |
| A composite Constraint create (needs the Constraint plane to accept a joined unit of work) | a Constraint-plane decision, not scheduled |
| A closure exception authority (OD-03) | not built; operator decision |
| Proposals and review (`irp`, `ldec`), Record Event family for lineage (`irec`) | S3 |
| Verified native Commitment acceptance (a review decision that must exist), and the same for v1 evidence-origin Tasks | ADR-006 / Work follow-up, not scheduled (section 12, D-05, D-17) |
| Handoff correction/void (an append-only correcting event honoured by `valid_at` reads); until then a mis-recorded handoff stands and no reverse handoff may be recorded to undo it (section 3.4) | S3 |
| Past Constraint ball-in-court (WP-02C "present/past BIC"): BIC stays native and unchanged by lineage (`test_lineage_writes_leave_constraint_bic_unchanged`); reading a past BIC is a `valid_at` read | S3 |
| `contested` as a closure-gate blocker (mandatory once `contest` is admitted, section 3.3) | S3 |
| Issue pages with close/reopen/handoff controls; the Meeting record view | S3 (WP-06A) |
| Runtime-role provisioning, remote attested lineage writer, native writers through `is_transaction_conflict` | as S1 §11 |
| Backfill, Program, report manifest, finance, P6 | as S1 §11 |

## 12. Divergences — repository vs package, and resolutions

| # | Package says | Repository truth | Resolution |
| --- | --- | --- | --- |
| D-01 | CR-006: `association_intents` on the existing Work/Meeting/Constraint writers | ADR-015 decision 13 forbids a silent extra field on a v1 contract; the v1 handlers are shared with the strict web client | 2 new composite capabilities; the v1 writers are untouched |
| D-02 | CR-005 `issue_responsibility_events` with `before/after_holder_kind ∈ principal, entity, unassigned`, `action_ref`, `cause_anchor_id`, `accepted_at` | `ires` collides (S1 §2); Tasks are Principal-held; a Commitment has exactly one counterparty | `ihnd`; subject = a Commitment member; holders = the Principal and a counterparty (the leaving side from the chain's last holder, an arriving counterparty from the current one), resolved by the server; `unassigned` and `accepted_at` dropped (acceptance is the attested write) |
| D-03 | CR-006: X1 created with its escalation in one UOW | `ConstraintManagementService.create_published` takes no `active_uow` by design (its docstring) and the general `UnitOfWork` has no Constraint repository | X1 is created by v1 `constraints.create_published`; `escalated_from` is an explicit, evidenced, Project-qualified assertion afterwards; the intermediate state (X1 not yet in the Issue) is honest and visible |
| D-04 | WP-02B: avoid the "single open follow-up" assumption; "do not prohibit follow-up solely because C1 is closed" | `tasks.create` validates only same-Principal Commitment existence (`_validate_task_commitment_state`), so a closed C1 is admitted; no unique index limits follow-ups; `commitments.read` shows one `follow_up_task_*` (`get_follow_up_for_commitment`: latest created) | nothing to unblock; the v1 single-follow-up display is a v1 read property left unchanged; lineage never relies on it |
| D-05 | OD-03 / CR-004: acceptance is server-derived | v1 `commitments.create` admits a client-supplied `accepted_by_review_decision_id` checked only for its `rdec_` pattern | the gate reads native `evidence_state` as native truth (AT-015 needs exactly that); the unverified v1 acceptance is a pre-existing residual recorded here and in section 11, not widened by S2 (the Commitment composite keeps the v1 field and meaning, under attested local-operator authority). **The same residual applies to Tasks created by v1 `tasks.create`** with `origin_kind: evidence` and a client `accepted_by_review_decision_id` (`TaskManagementService.create_task` marks them `accepted`/`review` on the pattern-checked id) and then added as members; the Task composite refuses the field (D-17) |
| D-06 | Stage 13: X1 closes "with verified source E1 approved under Constraint rules" | `constraints.close` takes no evidence; `project_constraint_evidence_links` admits only `cap_`/`asrt_`/`mdoc_`/`mdver_` refs and has no writer on the close path | X1's proof is an exact-version `resolution` anchor on its Issue membership (`issues.memberships.correct`); the Constraint plane is unchanged |
| D-07 | `issues.close` "returns evaluated unresolved required memberships" | the error envelope carries one safe detail | refusal `conflict` / `closure_gate`, plus the read `issues.closure_readiness` listing blockers |
| D-08 | `issues.history` in WP-01C | the S2 ATs need the closure basis, which `IssueView.closure` and the immutable revisions carry | `issues.history` stays S3 (S1 placed it there) |
| D-09 | `delegated_from` Commitment → Task **or Issue action**; `escalated_from` → Task **or Issue**; `blocks` over milestones; `created_to_resolve` from Decisions | no milestone family; no Decision capability; the 14 stages need only the narrower pairs | narrower matrix (section 3.1); widening needs an ADR-015 amendment and tests |
| D-10 | ADR-015 decision 6: the 4 other semantic types "admitted in S2" | `related_context` serves no S2 AT and needs symmetric canonical ordering | `related_context` moves to S3; recorded in the ADR implementation status |
| D-11 | WP-02D: Decision authority with its own native record | `cdec_` Decisions exist (`domain/situation/continuity.py`) but no capability writes or reads them (S1 §8: the internal writers are unreachable) | no `decision` role or family in S2; a Meeting statement stays discussion; S3 |
| D-12 | WP-02D: Series reassignment history | `meetings.update` reassigns `meeting_series_id` with its own `meeting_history` receipt; lineage reads no Series | lineage writes nothing on reassignment and no answer changes; tested, not built |
| D-13 | AT-015 `tests/contract/test_commitment_project_scoping.py` | its Program v2 reads are a later work package | the S2 part lives in `tests/integration/test_issue_close_reopen.py` |
| D-14 | S1 `records.lineage` web decoder is strict on `relation_type` and Issue `state` | S2 widens both server vocabularies | lockstep decoder widening on the unmerged branch (section 7.4) |
| D-15 | Package composite "same UOW receipt" includes a Record Event and `link_mutation_event_receipts` | S1 defers lineage Record Events to S3 | composites emit only their native Record Event; lineage events stay S3 |
| D-16 | OD-03 / stage 14: no unfulfilled mandatory duty "unless explicitly operator-authorized exception" | no exception authority exists, and S2 builds none | **interpretation:** ending a mandatory membership (`issues.memberships.end`, attested, with a reason) or recording work under a non-mandatory role is a recorded change of the Issue's scope, not an exception to the gate; it is visible in the membership revisions and their reasons. A future exception authority is a separate operator decision (section 13) |
| D-17 | OD-03 / CR-004: acceptance must be server-derived, never a client field (R2-F04) | Tasks have a native non-client route (`origin_kind: direct_principal` ⇒ `accepted`, `acceptance_kind = direct_principal`, in `TaskManagementService.create_task`); Commitments have none reachable from a capability: `SqlSituationRepository.accept` verifies a `capture_review_decisions` row with an accepting disposition, but no application code calls it, and `commitments.create` takes the client `rdec_` | the Task composite refuses `accepted_by_review_decision_id`; the Commitment composite keeps it (D-05 residual); wiring a verified Commitment acceptance route is the section 11 Work follow-up |
| D-18 | Section 10: only the listed lockstep moves may edit an S1 or v1 test (FR2-F04) | Adding 8 capability names, 1 purpose, 3 tables, columns and a new head moves more than head literals and counts: parametrized registries enumerate every capability, S1 lineage tests assert sets S2 widens, the S1 migration suite reads its columns from the revision that now owns them, and the S1 truncate probe must truncate the S2 tables that reference its tables | accepted lockstep edits, each keeping its test name and its S1 assertion: (a) head literal and revision count (119 → 120) in every head-pin file and the S1 migration test's `down_revision`/head literals, and the head-pin list itself (`test_constraint_read_plane_boundaries.py` leaves it, since it now names the S1 revision historically); (b) count pins (`Capability` 206 → 214, `Purpose` 57 → 58, audit vocabulary, `TABLES_SHA256`, permitted pairs 208 → 216, tool, builder, command-union, exempt-property and operator-decision counts, the README/architecture count claims); (c) registry and count additions only — the S2 names, triggers, functions and tables appended to the migration suites' admitted sets (the `TABLES_ABOVE`, trigger and audit-vocabulary lists of `tests/schema/*_migration.py` and `tests/database/*_migration.py`, under the S1 section 4.3 schema-ahead rule) and to `test_http_transport.py`, `test_transport_parity.py`, `test_mcp_transport.py`, `test_cli_transport.py`, `test_capabilities_and_readiness.py`, `test_chatllm_capability_policy.py`, `test_knowledge_assertion_capabilities.py`, `test_application_authorization.py`, `test_policy.py`, `test_http_negative_evidence.py`, `test_mcp_and_cli_negative_evidence.py`, `test_no_capability_accepts_a_server_owned_field.py`, `test_mcp_is_a_thin_adapter.py` (composites in `ISSUE_AUTHORING_EXEMPTION`, own-partition writes that move no source), `test_principal_partition_is_reached_through_the_guard.py`, and the `issue_handoffs` unit-of-work stub in `tests/conftest.py`, `test_audit_durability.py` and `test_gateway_connection_pool.py`; (d) S1 lineage tests narrowed to the S1 subset of a widened set — `test_lineage_capability_admission.py` (`declared` is the S1 part of the switch set), `test_lineage_attested_writes.py` (`S1_LINEAGE_WRITE_CAPABILITIES`), and the AT vocabulary checks of `test_record_lineage_s1_migration.py` and `test_knowledge_assertion_migration.py` (the S2 names subtracted); (e) `test_record_lineage_s1_migration.py` `test_frozen_ddl_names_every_declared_constraint` accepts a name or column found in the S2 revision text (the later revision owns it) and its two downgrade tests assert presence at the S2 revision; (f) `test_lineage_integrity_guards.py::test_lineage_tables_refuse_truncate` also truncates the 3 S2 tables, with their own refusals disabled, because they reference the S1 tables (each S1 table's own refusal is still the one under test); (g) `test_lineage_canonical.py` as listed. No assertion is removed without its S1 equivalent, no skip or xfail is added, and every S1 behaviour stays pinned; additions only extend coverage |

Lock and transaction rules not restated here are S1's, including its resolutions in
S1 §12.

## 13. Operator gates that remain

Ratification of ADR-015 beyond the directive defaults; any live migration, grant,
ChatLLM or client exposure, deployment or backfill (OD-07); any closure exception
authority or completeness-threshold risk acceptance (OD-03, OD-08); verified native
Commitment acceptance (D-05) as a Work decision; a joined-transaction Constraint create
(D-03) as a Constraint-plane decision; source commissioning for finance and P6 (OD-06);
runtime-role provisioning. Nothing else in S2 is left for a worker to decide beyond
local naming with no incumbent constraint.
