# Record lineage — Slice S1 implementation contract

**Status:** proposed implementation contract under
[ADR-015](../decisions/ADR-015-record-lineage-and-issue-situations.md) (Proposed —
accepted by directive defaults; architecture/test-isolated scope only). It is the
single document S1 implementers code against. It authorizes no migration run, grant,
deployment, backfill or production use. Where it differs from the review package
(`MYPA-LINEAGE-ADVERSARIAL-REVIEW-20261017-001`, documents 02, 03, 04 and 07), this
document controls for S1 and section 12 records why.

**Basis:** `feat/lineage-s1-integration@253b7d445db521ac7354843ed4e9a84bd8aae7f3`
(tree `188035885e68c0b35bdb9a64469abc2e37b12c74`), Alembic single head
`b9025e7fb738`, repository truth in
[`record-lineage-wp00a-preflight-ac24e3bf.md`](../evidence/record-lineage-wp00a-preflight-ac24e3bf.md)
(cited below as "W1 §n"). Paths under `src/` are relative to `src/my_pa/`.

All counts in this file are digits on purpose (spelled-count guard).

## 1. What S1 is

S1 is the first durable vertical proof (plan WP-01A/B/C/D, WP-02A, the S1 part of
WP-03A): a synthetic Meeting M1 with note version N1, a Commitment C1 asserted
`originated_from` an exact N1 passage inside Issue I, a later note version N1b that
does not retarget C1, a bounded reverse read from M1, N1, C1 or I, and fail-closed
refusal of wrong-parent, stale-digest and foreign-Principal references.

**In S1:** Issue Situations (create, read, list, update of title/description and the
non-terminal states), native Issue↔Project links with an append-only event ledger,
Issue memberships, three semantic relation types, exact Meeting note version evidence,
immutable roots/revisions/evidence/heads, idempotency and CAS, a bounded single-page
`records.lineage`, two Meeting note history reads, and the minimal WP-06A related-Issue
display on the Task, Commitment and Constraint record views (section 7.4).

**Not in S1** (section 11 lists the owner slice): Issue close/reopen, history and
bitemporal reads, proposals and review, contest/reinstate/replacement corrections,
the other four semantic types, Capture/Managed Document/Knowledge Assertion/external
evidence, version selectors other than `root`, cursors on `records.lineage`, Record
Event emission, composite Work/Meeting/Constraint writes, responsibility/handoff,
backfill, Program reads, role-separated grants, the S3 Issue timeline/graph UI, and a
Meeting record view (none exists in `web/` to extend; section 7.4).

## 2. Identifier kinds

New `IdKind` members (`domain/common/identifiers.py`), each verified free at the
basis commit (W1 §3); re-run the collision check before the revision is written.

| `IdKind` member | Prefix | Identifies |
| --- | --- | --- |
| `ISSUE_REVISION` | `irs` | one immutable Issue revision (`issue_revisions.revision_id`) |
| `ISSUE_PROJECT_MEMBERSHIP_EVENT` | `ipme` | one Issue↔Project membership event |
| `RECORD_LINK` | `irl` | one immutable association root |
| `RECORD_LINK_REVISION` | `irv` | one immutable association revision |
| `LINEAGE_EVIDENCE_ANCHOR` | `ian` | one immutable evidence anchor |

Reserved for later slices, not added in S1: `irp` (S3 proposal), `ldec` (S3 proposal
decision), `ihnd` (S2 responsibility/handoff event; replaces the package's colliding
`ires`), `irec` (S3 Record Event receipt). An Issue keeps its `sit_` identifier; there
is no `issue_` kind. Existing kinds used: `sit`, `prj`, `psit`, `mtg`, `mnote`, `tsk`,
`cmt`, `cst`, `prn`.

## 3. Closed vocabularies

Defined once in `NEW domain/lineage/vocabulary.py` as `StrEnum`s and restated by the
revision as frozen literals (no enum import in the revision, D-48/D-69). "S1 admits"
is also exactly what the S1 database CHECKs admit; a later slice widens both together.

| Vocabulary | S1 admits | Specified, admitted later |
| --- | --- | --- |
| `SituationKind` | `context`, `issue_workstream` | — |
| Issue state (existing `SituationState`) | `open`, `active`, `suspended` | `closed` (S2) |
| `IssueRevisionAction` | `created`, `updated`, `activated`, `suspended` | `closed`, `reopened`, `corrected` (S2) |
| `IssueProjectMembershipAction` | `assert`, `end`, `reinstate` | `correct` (S3) |
| `IssueProjectMembershipState` | `active`, `ended` | `contested` (S3) |
| `RecordFamily` (endpoint) | `situation`, `meeting`, `meeting_note_version`, `task`, `commitment`, `constraint` | `project`, `entity`, `capture`, `capture_version`, `managed_document`, `managed_document_version`, `knowledge_assertion`, `continuity_decision` |
| `RecordLinkKind` | `issue_membership`, `semantic` | — |
| `RelationType` | `issue_member`, `originated_from`, `discusses` | `delegated_from`, `escalated_from`, `blocks`, `created_to_resolve`, `related_context` (S2) |
| `MemberRole` | `origin_evidence`, `discussion`, `work`, `constraint`, `supporting_evidence`, `reference` | `decision` (S2, with `continuity_decision`) |
| `Selector` | `root` | `immutable_version`, `aggregate_version` (S3) |
| `LinkRevisionAction` | `assert`, `end`, `correct_evidence` | `contest`, `reinstate` (S2) |
| `LinkLifecycleState` | `active`, `ended` | `contested` (S2) |
| `AcceptanceBasis` | `user_confirmed` | `review_accepted`, `system_deterministic`, `source_backed_verified` (S2/S3) |
| `EvidenceSourceFamily` | `meeting_note_version` | `capture_version`, `capture` (`legacy_unversioned`), `managed_document_version`, `knowledge_assertion`, `external_version` |
| `SourceVersionKind` | `immutable_version` | `aggregate_version`, `external_version`, `legacy_unversioned` |
| `EvidenceRole` | `origin`, `corroborates`, `contradicts`, `discussion`, `handoff`, `resolution` | — |
| `EvidenceAvailability` (read only) | `available` | `archived`, `restricted`, `redacted`, `unavailable`, `withdrawn`, `superseded`, `legacy_unversioned` |
| `LineageCompleteness` (read only) | `complete`, `truncated_budget`, `unresolved_ambiguity`, `partial_native_history` | `restricted_evidence`, `scope_changed_restart_required`, `source_not_integrated`, `not_reportable` |
| `NativeVirtualEdge` (read only) | `meeting_note_version_of` | `follow_up`, `constraint_follow_up`, `meeting_in_series`, `project_issue`, `entity_member_of` |
| Authority class (reused, `KnowledgeReviewAuthorityClass`) | `local_operator`, `remote_operator_attested`, `ordinary_reviewer` | — |
| Decision channel (reused, `KnowledgeDecisionChannel`) | `local_cli`, `local_web`, `local_unattested`, `remote_interactive`, `remote_operator_review` | — |

### 3.1 S1 relation matrix (the closed policy)

| Relation (kind) | From | To | Evidence rule (checked in the application, refused with `invalid_request` / `evidence_anchors`) |
| --- | --- | --- | --- |
| `issue_member` (`issue_membership`) | `situation` (Issue) | `meeting`, `meeting_note_version`, `task`, `commitment`, `constraint` | 0..32 anchors, any role; `member_role` required |
| `originated_from` (`semantic`) | `commitment`, `task`, `constraint` | `meeting_note_version` | ≥1 anchor with role `origin`, a passage, and `source_version_id` equal to the `to` note version |
| `discusses` (`semantic`) | `meeting`, `meeting_note_version` | `situation` (Issue), `task`, `commitment`, `constraint` | ≥1 anchor with role `discussion` whose note version is the `from` note version, or belongs to the `from` Meeting |

Any other `(from, to, relation)` is `invalid_request` / `relation_type`. `issue_member`
is written only by `issues.memberships.add`; `records.associations.assert` refuses it.
A Project is never an `issue_member`; Project scope is `issues.project_links.*`.

### 3.2 Endpoint linkability (S1)

| Family | Native row (Principal-scoped) | Linkable when | Lock |
| --- | --- | --- | --- |
| `situation` | `situations` | `kind = 'issue_workstream'`; a context Situation is `invalid_request` / `endpoint` | `FOR UPDATE` when the write changes the Issue, else `FOR SHARE` |
| `meeting` | `meetings` | any `status` | `FOR SHARE` |
| `meeting_note_version` | `meeting_note_versions` | always (immutable) | `FOR SHARE` |
| `task` | `tasks` | `archived_at IS NULL`, else `invalid_request` / `endpoint` | `FOR SHARE` |
| `commitment` | `commitments` | any `state` and `evidence_state` (acceptance of the Commitment is its own) | `FOR SHARE` |
| `constraint` | `project_constraints` | any state | `FOR SHARE` |

An identifier with the wrong prefix for its family is `invalid_request`; an absent or
other-Principal record is `not_found` with the same safe detail and no write.

## 4. Schema — one additive revision

One Alembic revision, `down_revision = "b9025e7fb738"`, the new single head
(file `migrations/versions/<date>_<rev>_record_lineage_s1.py`). Frozen literal DDL; no
domain or persistence import; declarations mirrored in
`infrastructure/persistence/tables.py` with the `TABLES_SHA256` pin updated. Names
below are the constraint/trigger names to use. Every new table is in schema
`knowledge`, has `principal_id text NOT NULL` with `_is_identifier(…, PRINCIPAL)`, an
`_is_identifier` CHECK on every identifier column, and every foreign key is
`ON DELETE RESTRICT`. Timestamps are `timestamptz NOT NULL`, server-stamped. Digest
columns are `text` with the Meeting digest pattern `^[0-9a-f]{64}$`.

### 4.1 Existing tables (additive only)

**`situations`**

- `ADD COLUMN kind text NOT NULL DEFAULT 'context'`, CHECK `a_situation_kind_is_known` (`kind IN ('context','issue_workstream')`).
- `ADD COLUMN version integer NOT NULL DEFAULT 1`, CHECK `a_situation_version_is_positive`.
- `UNIQUE (situation_id, principal_id)` `a_situation_is_identified_within_its_principal`.
- `UNIQUE (situation_id, principal_id, kind)` `a_situation_is_identified_with_its_kind` — the target of every Issue-only foreign key.
- Trigger `a_situation_kind_is_fixed` (`BEFORE UPDATE`): refuses any change of `kind`, `situation_id` or `principal_id`; on an `issue_workstream` row requires `NEW.version = OLD.version + 1`; on a `context` row requires `NEW.version = OLD.version`. A `BEFORE INSERT` branch requires `version = 1`.
- Constraint trigger `an_issue_matches_its_latest_revision` (`AFTER INSERT OR UPDATE`, `DEFERRABLE INITIALLY DEFERRED`, row `WHEN (NEW.kind = 'issue_workstream')`): re-reads the **current** row and requires an `issue_revisions` row at `(principal_id, situation_id, version)` with equal `state`, `title` and `description` (`IS NOT DISTINCT FROM`), and `closed_at IS NULL AND outcome IS NULL`.
- Existing rows: all become `kind = 'context'`, `version = 1`; nothing else changes. The legacy no-CAS `close_situation` keeps working for context rows and is refused for Issues by the version rule.

**`project_situations`**

- `UNIQUE (principal_id, project_id, situation_id)` `a_project_situation_is_identified_within_its_principal`.
- `FOREIGN KEY (project_id, principal_id) REFERENCES projects (project_id, principal_id)` `a_project_situation_names_a_project_of_its_principal`.
- `FOREIGN KEY (situation_id, principal_id) REFERENCES situations (situation_id, principal_id)` `a_project_situation_names_a_situation_of_its_principal`.
- Constraint trigger `an_issue_project_link_has_a_membership_event` (`AFTER INSERT`, deferred): when the named Situation is an Issue, an `issue_project_membership_events` row for the triplet must exist at commit.
- **Migration preflight:** before adding the foreign keys, count rows whose `principal_id` differs from the referenced Project's or Situation's. A non-zero count raises with the two counts and no identifiers; nothing is repaired, re-dated or given evidence. Existing rows are untouched; they all name context Situations and S1 never reads them.

**`meeting_note_versions`**

- `UNIQUE (note_version_id, meeting_id, principal_id, content_sha256)` `a_meeting_note_digest_is_identified_within_its_meeting` — the anchor foreign key target, so the database proves an anchor's digest.

### 4.2 New tables

**`issue_revisions`** (immutable)

| Column | Type / rule |
| --- | --- |
| `principal_id`, `issue_id` (`sit`), `version` (`>= 1`) | PK `(principal_id, issue_id, version)` |
| `issue_kind` | `text NOT NULL DEFAULT 'issue_workstream'`, CHECK `= 'issue_workstream'` |
| `revision_id` (`irs`) | `UNIQUE (principal_id, revision_id)` |
| `predecessor_version` | nullable |
| `action` | S1 `IssueRevisionAction` |
| `state` | `open`, `active`, `suspended` |
| `title` | `length(trim(title)) BETWEEN 1 AND 500` |
| `description` | nullable, `length <= 10000` |
| `authority_class`, `decision_channel` | reused vocabularies |
| `source_capability` | `issues.create` or `issues.update` |
| `recorded_at` | |

FKs: `(issue_id, principal_id, issue_kind) → situations (situation_id, principal_id, kind)`;
`(principal_id, issue_id, predecessor_version) → issue_revisions`. CHECK
`an_issue_revision_follows_its_predecessor`: `(version = 1 AND action = 'created' AND predecessor_version IS NULL AND state = 'open') OR (version > 1 AND predecessor_version = version - 1 AND action <> 'created')`.
Constraint trigger `an_issue_revision_is_not_ahead_of_its_issue` (deferred): at commit
`situations.version >= NEW.version`.

**`issue_project_membership_events`** (immutable)

| Column | Type / rule |
| --- | --- |
| `principal_id`, `membership_event_id` (`ipme`) | PK |
| `project_id` (`prj`), `issue_id` (`sit`), `issue_kind` (constant as above) | |
| `revision_no` (`>= 1`), `predecessor_revision_no` | `UNIQUE (principal_id, project_id, issue_id, revision_no)` |
| `action`, `state` | S1 vocabularies |
| `evidence_anchor_id` (`ian`) | nullable |
| `reason` | nullable, `length BETWEEN 1 AND 2000` |
| `acceptance_basis` | `user_confirmed` |
| `authority_class`, `decision_channel`, `source_capability`, `recorded_at` | |

FKs: `(principal_id, project_id, issue_id) → project_situations (principal_id, project_id, situation_id)`;
`(issue_id, principal_id, issue_kind) → situations (situation_id, principal_id, kind)`;
`(principal_id, project_id, issue_id, predecessor_revision_no) → self`;
`(principal_id, evidence_anchor_id) → lineage_evidence_anchors`. CHECKs: revision 1
⇔ `action = 'assert'` with no predecessor; `revision_no > 1` ⇒ predecessor `= revision_no - 1`;
`action = 'end'` ⇔ `state = 'ended'`; `action = 'end'` ⇒ `reason IS NOT NULL`.
Trigger `a_membership_event_follows_its_predecessor` (`BEFORE INSERT`): `end` needs an
`active` predecessor, `reinstate` an `ended` one.

**`record_links`** (immutable root)

| Column | Type / rule |
| --- | --- |
| `principal_id`, `link_id` (`irl`) | PK |
| `kind` | `RecordLinkKind` |
| `from_family`, `from_id`, `to_family`, `to_id` | S1 `RecordFamily`; ids `_is_identifier` per family via CHECK on family/prefix pair |
| `relation_type` | S1 `RelationType` |
| `member_role` | nullable, S1 `MemberRole` |
| `context_issue_id` (`sit`), `context_issue_kind` | both null or both set; kind `= 'issue_workstream'` |
| `normalized_identity` | `length BETWEEN 1 AND 1024` (section 5.3) |
| `authority_class`, `decision_channel`, `source_capability`, `created_at` | |

FK `(context_issue_id, principal_id, context_issue_kind) → situations (situation_id, principal_id, kind)`.
CHECKs: `a_membership_link_is_issue_scoped` — `kind <> 'issue_membership' OR (from_family = 'situation' AND relation_type = 'issue_member' AND context_issue_id = from_id AND member_role IS NOT NULL)`;
`a_semantic_link_is_not_a_membership` — `kind <> 'semantic' OR (relation_type <> 'issue_member' AND member_role IS NULL)`;
`a_record_link_pair_is_admitted` — the section 3.1 matrix as a disjunction. Indexes
`record_links_outgoing (principal_id, from_family, from_id, kind, relation_type, link_id)`,
`record_links_incoming (principal_id, to_family, to_id, kind, relation_type, link_id)`,
`record_links_by_issue (principal_id, context_issue_id, kind, link_id)`.

**`record_link_revisions`** (immutable)

| Column | Type / rule |
| --- | --- |
| `principal_id`, `link_id`, `revision_no` (`>= 1`) | PK `(principal_id, link_id, revision_no)` |
| `revision_id` (`irv`) | `UNIQUE (principal_id, revision_id)` |
| `predecessor_revision_no` | nullable |
| `action`, `lifecycle_state`, `acceptance_basis` | S1 vocabularies |
| `authority_class`, `decision_channel`, `source_capability` | |
| `reason` | nullable, `length BETWEEN 1 AND 2000` |
| `evidence_count` | `smallint`, `BETWEEN 0 AND 32` |
| `evidence_set_digest` | sha256 hex |
| `recorded_at` | |

FKs to `record_links (principal_id, link_id)` and to self on the predecessor. CHECK
`a_link_revision_follows_its_predecessor`: `(revision_no = 1 AND action = 'assert' AND predecessor_revision_no IS NULL AND lifecycle_state = 'active') OR (revision_no > 1 AND predecessor_revision_no = revision_no - 1 AND action <> 'assert')`;
`action = 'end'` ⇔ `lifecycle_state = 'ended'`; `action IN ('end','correct_evidence')` ⇒ `reason IS NOT NULL`.
Trigger `a_link_revision_follows_an_active_predecessor` (`BEFORE INSERT`). Constraint
trigger `a_link_head_is_its_latest_revision` (deferred): the head's `revision_no`
equals the link's maximum revision at commit.

**`lineage_evidence_anchors`** (immutable)

| Column | Type / rule |
| --- | --- |
| `principal_id`, `anchor_id` (`ian`) | PK |
| `source_family` | S1 `meeting_note_version` only |
| `source_root_id` (`mtg`), `source_version_kind` (`immutable_version`), `source_version_id` (`mnote`) | |
| `source_sha256` | sha256 hex |
| `passage_start_cp`, `passage_end_cp`, `passage_sha256` | all null, or `0 <= start < end` with digest |
| `meeting_id`, `note_version_id` | binding columns; CHECK equal to `source_root_id` / `source_version_id` |
| `anchor_identity` | canonical JSON (section 5.1, without `role`); `UNIQUE (principal_id, anchor_identity)` |
| `recorded_at` | |

FK `a_lineage_anchor_binds_an_exact_meeting_note`:
`(note_version_id, meeting_id, principal_id, source_sha256) → meeting_note_versions (note_version_id, meeting_id, principal_id, content_sha256)`.
Trigger `a_lineage_anchor_passage_matches_its_note` (`BEFORE INSERT`): refuses unless
`server_encoding = 'UTF8'`; with a passage, requires `passage_end_cp <= char_length(content_markdown)`
and `passage_sha256 = encode(sha256(convert_to(substr(content_markdown, passage_start_cp + 1, passage_end_cp - passage_start_cp), 'UTF8')), 'hex')`.
(PostgreSQL `substr`/`char_length` count code points in a UTF-8 database, matching
Python `str` slicing.)

**`record_link_revision_evidence`** (immutable)

Columns `principal_id, link_id, revision_no, ordinal (smallint 1..32), anchor_id, role (EvidenceRole)`;
PK `(principal_id, link_id, revision_no, ordinal)`; `UNIQUE (principal_id, link_id, revision_no, anchor_id)`;
FKs to `record_link_revisions` and `lineage_evidence_anchors`. `ordinal` is the
1-based position in the section 5.1 canonical order. Constraint triggers
`a_link_revision_evidence_set_is_frozen` on both this table and
`record_link_revisions` (deferred): at commit the row count for the revision equals
its `evidence_count`. A later transaction adding evidence to a committed revision
therefore fails.

**`record_link_heads`** (rebuildable projection)

Columns `principal_id, link_id, revision_no, lifecycle_state, normalized_identity`;
PK `(principal_id, link_id)`; FK `(principal_id, link_id, revision_no) → record_link_revisions`;
partial unique index `record_link_one_active_identity (principal_id, normalized_identity) WHERE lifecycle_state = 'active'`.
Trigger `a_link_head_follows_its_revisions`: `INSERT` requires `revision_no = 1` and the
root's `normalized_identity`; `UPDATE` requires the same key and identity,
`NEW.revision_no = OLD.revision_no + 1` and `lifecycle_state` equal to that revision's;
`DELETE` refused.

**`lineage_write_requests`** (idempotency; precedent `meeting_write_requests`)

| Column | Type / rule |
| --- | --- |
| `principal_id`, `capability`, `idempotency_key` | PK; `capability` is one of the Slice S1 write capabilities of section 7 (9 in all); key `length BETWEEN 1 AND 128` |
| `request_digest` | sha256 hex |
| `result_issue_id`, `result_issue_version` | FK → `issue_revisions` |
| `result_link_id`, `result_link_revision_no` | FK → `record_link_revisions` |
| `result_membership_event_id` | FK → `issue_project_membership_events` |
| `created_at`, `completed_at` | |

CHECK: reserved rows (`completed_at IS NULL`) carry no result; a completed row carries
exactly one result group, the one its capability produces. Trigger
`a_lineage_write_request_completes_once` (`BEFORE UPDATE OR DELETE`): only
`completed_at` and the result columns may change, only from reserved, only once;
`DELETE` refused. Constraint trigger `a_lineage_write_request_is_never_left_reserved`
(`AFTER INSERT`, deferred; precedent `knowledge_submission_is_never_left_reserved`).

### 4.3 Shared triggers, protection of linked records, downgrade

- `lineage_rows_are_append_only()` — `BEFORE UPDATE OR DELETE … FOR EACH ROW`, raises `restrict_violation`; attached to `issue_revisions`, `issue_project_membership_events`, `record_links`, `record_link_revisions`, `lineage_evidence_anchors`, `record_link_revision_evidence`.
- `lineage_relations_refuse_truncate()` — `BEFORE TRUNCATE … FOR EACH STATEMENT`; attached to all 8 new tables (precedent `c8e4a1b70d35`).
- `a_linked_record_is_not_deleted()` — `BEFORE DELETE … FOR EACH ROW` on `situations`, `meetings`, `tasks`, `commitments`, `project_constraints`: refuses when any `record_links` row of the same Principal names the row as `from` or `to` (served by the two endpoint indexes). `meeting_note_versions` already refuses deletes.
- No role grants change (ADR-015 decision 10); the triggers bind the connecting role, including the owner.
- `downgrade()` first refuses (`restrict_violation`) while any row exists in the 8 new tables, any Situation has `kind = 'issue_workstream'`, or any `audit_events` row names an S1 capability or purpose; only then drops in reverse order.
- The revision restates `capability_is_known` and `purpose_is_known` on `knowledge.audit_events` (BEFORE texts byte copies of the latest restating revision, AT texts add exactly the S1 names sorted), and `_CURRENT_AUDIT_CAPABILITIES` moves with it (W1 §2.2 "Schema").

## 5. Canonical encodings

One module, `NEW domain/lineage/canonical.py`, pure functions with golden vectors.
"Canonical JSON" is ADR-014 decision 6: NFC-normalized strings,
`json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, UTF-8,
no floats, every fixed key present (`null` when absent).

### 5.1 Anchor object, order, evidence-set digest

Anchor object keys (exactly): `source_family`, `source_root_id`, `source_version_kind`,
`source_version_id`, `source_version_no`, `source_sha256`, `passage_start_cp`,
`passage_end_cp`, `passage_sha256`, `role`. `anchor_identity` is the same object
without `role`, canonical JSON. Order: by the tuple of those ten values, with `null`
before any value and integers compared numerically. Duplicates (equal objects) in one
request are `invalid_request` / `evidence_anchors`.

`evidence_set_digest = sha256(b"lineage-evidence-set-v1\n" + canonical_json({"schema_version": 1, "anchors": [ordered anchor objects]})).hexdigest()`.
Anchor identifiers are not in it. The empty set is legal where section 3.1 allows it.

### 5.2 Passage

`passage_start_cp`/`passage_end_cp` index the stored `content_markdown` as a Python
`str` (code points), zero-based, end-exclusive; `passage_sha256 = sha256(body[start:end].encode("utf-8")).hexdigest()`.
The body is never normalized. Mismatch, out of range, `start >= end`, or a partial
triple is `invalid_request` / `evidence_anchors`.

### 5.3 Normalized identity

`normalized_identity = canonical_json({"schema_version": 1, "kind", "relation_type", "from": {"family", "record_id", "selector": "root"}, "to": {...}, "member_role", "context_issue_id"})`.
Stored in full; uniqueness never relies on a hash.

### 5.4 Request digest

`request_digest = sha256(b"lineage-request-v1\n" + canonical_json({"capability", "principal_id", "request"})).hexdigest()`,
where `request` is the parsed payload without `idempotency_key`, optional fields
present as `null`, anchors in section 5.1 order, `clear_fields` sorted.

## 6. Authority, locks and the transaction

### 6.1 Authority

`NEW application/lineage_authority.py` calls `derive_knowledge_review_authority`
(`domain/policy/knowledge_review_authority.py`) with the server-stamped operator
surface, transport, operator flag, authenticated client id, the exact operator-review
allowlist, `manager_allowlist=frozenset()` and the grant-ceiling flag.

- **Attested writes** — `issues.project_links.add/end`, `issues.memberships.add/end`, `records.associations.assert/correct/end`: class must be `local_operator` or `remote_operator_attested`, else `denied` before any row is written. Stored `acceptance_basis = 'user_confirmed'`.
- **Recorded writes** — `issues.create`, `issues.update`: any admitted caller; class and channel recorded on the Issue revision.
- `InconsistentKnowledgeReviewCompositionError` → `internal_error`; `UnsupportedKnowledgeReviewCompositionError` → `unsupported` (as Knowledge does).

### 6.2 Lock order (every S1 writer, one transaction)

1. Reserve the `lineage_write_requests` row (`INSERT … ON CONFLICT DO NOTHING`; on conflict read the completed row: same digest → replay, else `conflict`).
2. Issue Situation(s) the write changes: `FOR UPDATE`, identifier order.
3. Every other endpoint, Issue context and evidence note version: `FOR SHARE`, ordered by `(family token, identifier)`.
4. `pg_advisory_xact_lock(<lineage namespace>, hashtext(principal_id || ':' || normalized_identity))` for an association/membership write; the namespace constant is new and must differ from every advisory key already in `src/` (W1 §7 item 9 lists the existing users).
5. The association head `FOR UPDATE`, or the `project_situations` triplet row `FOR UPDATE` after `INSERT … ON CONFLICT DO NOTHING`.

Reads take no locks. A deadlock or serialization failure maps to `unavailable` with
`bounded_retry`; the request row rolls back with everything else.

### 6.3 Transaction order (02 §2.4, S1 form)

1. Authorize capability/purpose/grant; strict-parse; derive authority (refuse here).
2. Compute the request digest; reserve (6.2 step 1).
3. Acquire locks (6.2 steps 2–5); validate endpoints (3.2), the matrix (3.1), every anchor against its locked note version (5.1, 5.2), and expected versions/revisions (`conflict` when stale).
4. Write: reuse-or-insert anchors; root and revision 1, or the next revision; revision evidence; head insert or update — or the Issue revision and the Situation update — or the `project_situations` row (new link) and the membership event.
5. Complete the request row with its result.
6. Commit; deferred triggers verify. No Record Event is emitted in S1. Any failure rolls everything back, so a refused write leaves no row and no request.

## 7. Capabilities — the exact S1 set

14 new `Capability` members (192 → 206; audit vocabulary 203 → 217) and 5 new
`Purpose` members (52 → 57). All are `_SCOPELESS`, classified
`CHATLLM_OPERATOR_DECISION_REQUIRED` with rationale "record lineage S1; exposure is an
operator decision (ADR-015, OD-07)", and none is operator-only. Families `issues` and
`records` map to feature `lineage` in `adapters/mcp/chatllm_gateway.py`;
`meetings.notes.*` stays `meetings`. The 9 writes are in `_WRITE_CAPABILITIES` and
`_IDEMPOTENT_REMOTE_CAPABILITIES`; `issues.create`, `issues.project_links.add`,
`issues.memberships.add` and `records.associations.assert` are also
`_ADDITIVE_WRITE_CAPABILITIES`; `issue_authoring` and `record_lineage_authoring` join
`_WRITE_PURPOSES`. No `CHATLLM_DATA_PROFILE_VERSION` change is expected (no data-class
member moves); if the profile diff test says otherwise, bump it and record why.

| Capability | W/R | Purpose (new unless noted) | Idempotency | Purpose of the call |
| --- | --- | --- | --- | --- |
| `issues.create` | W | `issue_authoring` | key, recorded | create Issue v1 `open` |
| `issues.read` | R | `issue_read` | — | one Issue, Project links, optional memberships |
| `issues.list` | R | `issue_read` | — | keyset page of Issues |
| `issues.update` | W | `issue_authoring` | key + `expected_version` | title/description/non-terminal state |
| `issues.project_links.add` | W | `issue_authoring` | key + `expected_membership_revision`, attested | assert or reinstate a native Project link |
| `issues.project_links.end` | W | `issue_authoring` | key + `expected_membership_revision`, attested | end a native Project link |
| `issues.memberships.add` | W | `issue_authoring` | key, attested | Issue membership of a non-Project record |
| `issues.memberships.end` | W | `issue_authoring` | key + `expected_revision`, attested | end a membership |
| `records.associations.assert` | W | `record_lineage_authoring` | key, attested | assert a semantic association |
| `records.associations.correct` | W | `record_lineage_authoring` | key + `expected_revision`, attested | replace the evidence set (S1: evidence only) |
| `records.associations.end` | W | `record_lineage_authoring` | key + `expected_revision`, attested | end a semantic association |
| `records.lineage` | R | `record_lineage_read` | — | bounded Issue-scoped reverse read |
| `meetings.notes.versions` | R | `meeting_read` (existing) | — | note version metadata, no body |
| `meetings.notes.read_version` | R | `meeting_note_history_read` | — | one exact note version, body on request |

`meeting_note_history_read` is its own purpose because a historical body is a
widening over `meeting_read` (`domain/identity/purpose.py` reasoning). Lineage and
Issue reads never return a body.

### 7.1 Shared request/response shapes

- Request models are `StrictModel` (unknown field ⇒ `invalid_request`). No request carries `principal_id`, `actor_class`, `authority_class`, `decision_channel`, `acceptance_basis`, `review_decision_id`, `recorded_at` or a `selector` (S1 is `root` only).
- `RecordRef` = `{family: RecordFamily, record_id: str}`.
- `EvidenceAnchorInput` = `{family: "meeting_note_version", root_id: mtg_, version_kind: "immutable_version", version_id: mnote_, source_sha256: hex64, passage_start_cp?: int >= 0, passage_end_cp?: int >= 1, passage_sha256?: hex64, role: EvidenceRole}`; `version_no` is not accepted.
- `EvidenceAnchorView` = the input fields with `anchor_id`, plus `availability: "available"`.
- `AssociationView` = `{link_id, kind, relation_type, from: RecordRef, to: RecordRef, member_role, context_issue_id, revision_no, lifecycle_state, acceptance_basis, authority_class, evidence_set_digest, evidence: [EvidenceAnchorView], created_at, recorded_at}` (`recorded_at` of the current revision).
- `IssueView` = `{issue_id, kind: "issue_workstream", version, state, title, description, opened_at, created_at, updated_at, project_links: [ProjectLinkView], project_links_truncated: bool}`; at most 100 links, active first, then `project_id`.
- `ProjectLinkView` = `{project_id, project_situation_id, state: "active"|"ended", membership_revision_no, acceptance_basis, evidence_anchor_id, recorded_at}`.
- Write results add `replayed: bool`; association/membership adds also `created: bool`.
- Envelope, disclosure and error mapping are the existing v1 ones.

### 7.2 Per-capability contract

**`issues.create`** — in `{title (1..500, non-blank), description? (<=10000), idempotency_key}`;
out `{issue: IssueView, replayed}`. Inserts `situations` (`kind = 'issue_workstream'`,
`version = 1`, `state = 'open'`) and `issue_revisions` v1 `created`. No Project, no
`object_refs` (stored `[]`).

**`issues.read`** — in `{issue_id, include_members? = false}`; out `{issue, memberships?, memberships_truncated?}`.
`memberships` are active `issue_membership` links as `AssociationView`, at most 100,
ordered `(created_at, link_id)`. A context Situation id is `not_found`.

**`issues.list`** — in `{page_size? (1..100, default 25), after? (sit_), state?, project_id?}`;
out `{issues: [{issue_id, version, state, title, updated_at}], next_cursor}`, ordered
`(created_at DESC, situation_id DESC)`; `next_cursor` is the last `issue_id` when more
rows exist. `project_id` filters to an active Project link. `after` outside the filter
is `invalid_request` (the `meetings.list` rule).

**`issues.update`** — in `{issue_id, expected_version, idempotency_key, title?, description?, state? ("active"|"suspended"), clear_fields? ⊆ ["description"]}`;
out `{issue, replayed}`. Allowed state moves: `open → active` (`activated`),
`open|active → suspended` (`suspended`), `suspended → active` (`activated`); with no
state move the action is `updated`. A request that changes nothing, or both sets and
clears `description`, is `invalid_request`. Writes the next revision and the
Situation row (`version + 1`, `updated_at`).

**`issues.project_links.add`** — in `{issue_id, project_id, expected_membership_revision (>= 0), idempotency_key, evidence_anchor?: EvidenceAnchorInput, reason? (1..2000)}`;
out `{project_link: ProjectLinkView, issue_id, replayed}`. `0` ⇒ no link may exist:
inserts `project_situations` (`psit_`, `linked_at`, `association_evidence_ref` = the
anchor id or `NULL`) and event 1 `assert`. `n >= 1` ⇒ the latest event must be `n` and
`ended`: event `n + 1` `reinstate`. An active link is `conflict`. The Issue's
`version` does not change.

**`issues.project_links.end`** — in `{issue_id, project_id, expected_membership_revision (>= 1), idempotency_key, reason (1..2000)}`;
out as add. The latest event must be `n` and `active`; writes `end`. The
`project_situations` row is never deleted.

**`issues.memberships.add`** — in `{issue_id, member: RecordRef, role: MemberRole, idempotency_key, evidence_anchors? ([0..32])}`;
out `{membership: AssociationView, created, replayed}`. `member.family` per section
3.1. An active membership with the same identity (same member and role) returns it
with `created: false`; its authority and evidence never change.

**`issues.memberships.end`** — in `{link_id, expected_revision, idempotency_key, reason}`;
out `{membership, replayed}`. A semantic link id is `invalid_request` / `link_id`.

**`records.associations.assert`** — in `{from: RecordRef, to: RecordRef, relation_type, idempotency_key, evidence_anchors ([1..32]), context_issue_id?}`;
out `{association, created, replayed}`. `relation_type = issue_member` is
`invalid_request`. `context_issue_id` must be an Issue; for `discusses` with an Issue
`to`, a supplied context must equal it. Duplicate active identity ⇒ existing
association, `created: false`.

**`records.associations.correct`** — in `{link_id, expected_revision, idempotency_key, reason, evidence_anchors ([1..32])}`;
out `{association, replayed}`. Semantic links only. The supplied set is the complete
new set, must satisfy the relation's rule, and must differ from the current digest
(else `invalid_request`). Writes `correct_evidence`; the root never changes. A
`replacement` field is not accepted in S1.

**`records.associations.end`** — in `{link_id, expected_revision, idempotency_key, reason, evidence_anchors? ([0..32])}`;
out `{association, replayed}`. Semantic links only; writes `end`. An ended link is
terminal in S1; re-asserting the same meaning creates a new root.

**`records.lineage`** — in `{origin: RecordRef, issue_id?, max_depth? (0..4, default 4)}`;
`cursor`, `page_size`, `valid_at`, `known_at` and `include` are refused in S1. Out:

```text
{root: RecordRef, selected_issue_id: sit_|null,
 issues_matching_root: [{issue_id, title, state}] (<= 20),
 nodes: [{family, record_id, depth, meeting_id (note versions only), title and state (Issue nodes only)}],
 typed_edges: [AssociationView],
 virtual_native_edges: [{edge_type: "meeting_note_version_of", from: RecordRef(meeting_note_version), to: RecordRef(meeting)}],
 complete_state: complete|truncated_budget|unresolved_ambiguity|partial_native_history,
 next_cursor: null}
```

Algorithm (deterministic, Principal-scoped, current state, active links only):

1. Resolve the root in its native table (absent/foreign ⇒ `not_found`; a context Situation or an S1-unadmitted family ⇒ `invalid_request`).
2. Matching Issues: the root itself if it is an Issue; Issues with an active membership of the root, of the root's Meeting (for a note version) or of any note version of the root (for a Meeting); `context_issue_id` of active semantic links incident to the root; and Issue `to` endpoints of active `discusses` links from the root.
3. `issue_id` given and not matching ⇒ `not_found`. Not given: exactly one ⇒ selected; more than one ⇒ return the candidates (sorted, at most 20), `complete_state = unresolved_ambiguity`, no traversal; none ⇒ one hop over active semantic links incident to the root with `context_issue_id IS NULL`, plus its virtual note edge, no expansion.
4. With Issue *I* selected, breadth-first from the root to `max_depth`, following only: *I*'s active membership links; active semantic links whose `context_issue_id = I`, whose endpoint is *I*, or whose context is null and whose two endpoints are both in *I* (*I*, an active member, or a note version/Meeting paired with an active member); and `meeting_note_version_of` between a reached node and its pair. Links scoped to another Issue are never followed.
5. Re-resolve every reached node in its native table; a node that no longer resolves is dropped with its edges and sets `partial_native_history`.
6. Budgets (design values, not benchmarks): 250 nodes, 400 edges (typed plus virtual), 512 KiB serialized. Reaching one stops expansion and sets `truncated_budget`. Expansion order: frontier by `(depth, family, record_id)`, edges by `(created_at, link_id)`, virtual edges by `version_number`. Output order: nodes by `(depth, family, record_id)`, edges by `link_id`.
7. No body, no title other than an Issue's own title and state, and no hidden count is returned; `next_cursor` is always `null` in S1 and does not imply completeness.

**`meetings.notes.versions`** — in `{meeting_id, page_size? (1..100, default 25), after? (mnote_)}`;
out `{meeting_id, versions: [{note_version_id, version_number, supersedes_note_version_id, content_sha256, character_count, recorded_at, is_current}], next_cursor}`
ordered `version_number DESC`. No body.

**`meetings.notes.read_version`** — in `{meeting_id, note_version_id, include_body? = false}`;
out `{note: {note_version_id, meeting_id, version_number, supersedes_note_version_id, content_sha256, character_count, recorded_at, is_current, body_markdown (only when include_body)}, evidence_availability: "available"}`.
A note version that is not this Meeting's, or not this Principal's, is `not_found`.

### 7.3 Errors

| Situation | Code / safe detail |
| --- | --- |
| schema, type, bound, unknown field, wrong prefix, matrix miss, evidence rule miss, digest/passage mismatch, no-op change | `invalid_request` / the field (`relation_type`, `evidence_anchors`, `member`, `endpoint`, `expected_version`, …) |
| absent, other-Principal or wrong-parent record, note version, Issue or link | `not_found` / the subject |
| missing grant/purpose, or attested write without attestation | `denied` |
| stale `expected_version`/`expected_revision`/`expected_membership_revision`, key reused with another digest, Project link already active | `conflict` |
| deadlock or serialization failure | `unavailable`, `bounded_retry` |

New `SafeDetail` members are added with the code that reports them.

### 7.4 Minimal WP-06A related-Issue display (S1)

Plan 03 WP-06A S1 card, bounded to the record views that exist in `web/` at the basis
commit. Read-only: no write control, no graph, no timeline.

**Where.** One new component, `web/src/components/work/related-issues.tsx`
(`RelatedIssuesPanel`), mounted in:

- the Task detail: `TaskDetailViewInner` in `web/src/components/work/work-detail.tsx` (serves `/work/tasks/[taskId]` and the Work-hosted sheet);
- the Commitment detail: `CommitmentDetailView` in the same file (serves `/work/commitments/[commitmentId]`);
- the Constraint detail: `ConstraintInspector` in `web/src/app/(app)/work/projects/[projectId]/constraints/constraint-inspector.tsx`.

`web/` has no Meeting record view (only the BFF route
`web/src/app/api/meetings/[meetingId]/route.ts`). Building one is new UX outside this
card, so the Meeting display moves to the S3 WP-06A stage. This is a limit set by what
the repository contains, recorded in section 12.

**BFF (server-batched, one call per view).**

- `GET /api/records/[family]/[recordId]/related-issues?issueId=`: new
  `web/src/app/api/records/[family]/[recordId]/related-issues/route.ts`, using
  `workGet(request, "related-issues", "records.lineage", { issueId: { gateway: "issue_id", type: "string" } }, { origin: { family, record_id: recordId }, max_depth: 1 }, { strictQuery: true })`.
  `family` is allow-listed to `task`, `commitment` and `constraint`; anything else is a
  local `invalid_request` without a gateway call.
- `GET /api/meetings/[meetingId]/notes/[noteVersionId]?includeBody=true`: new
  `web/src/app/api/meetings/[meetingId]/notes/[noteVersionId]/route.ts`, calling
  `meetings.notes.read_version`. It is called only when the user opens an anchor.
- The panel never calls `issues.read`, never fetches per Issue or per edge, and never
  joins records client-side. Everything it renders comes from the one `records.lineage`
  response (Issue title and state on Issue nodes, section 7.2) and, on demand, the one
  note-version read.

**Contract and decoders.** `web/src/contracts/gateway.json` gains two entries:

- `records.lineage`: purpose `record_lineage_read`; `payloadFields` `origin`, `issue_id`, `max_depth`.
- `meetings.notes.read_version`: purpose `meeting_note_history_read`; `payloadFields` `meeting_id`, `note_version_id`, `include_body`.

Each entry has a synthetic `probe`. Decoders
`web/src/lib/api/decode/capabilities/records.lineage.ts` and
`meetings.notes.read_version.ts` are strict (unknown keys refused) and decode the
section 7.2 shapes. They are registered in `web/src/lib/api/decode/index.ts` and
`types.ts`. `web/src/lib/api/decode/fixtures/python/success.json` is regenerated with
exactly the two new keys. Client calls go through a new `fetchRelatedIssues` /
`fetchNoteVersion` pair in `web/src/lib/api/work-client.ts`. New files under `web/`
must be added with `git add -f` and checked with `git ls-tree`.

**What it shows.**

- **One Issue** (the selected or only match): the Issue title and state, as plain text
  (Issue pages are S3). Then each typed edge between the record and the Issue context:
  - the membership role, or the relation type with its direction in words ("originated from", "discussed in");
  - `lifecycle_state`, `acceptance_basis` and `authority_class`, as plain words;
  - each evidence anchor, as "Meeting note version *n*, characters *start*–*end*". A
    button opens the note-version read in an inline disclosure; the body appears only
    after that explicit action.
- **Several Issues** (`unresolved_ambiguity`): the candidates (title, state) as a
  labelled radio group. Choosing one re-queries with `issueId`. No Issue is chosen for
  the user.
- **No match:** "No related Issue is recorded for this record."
- **Incomplete or failed reads:**
  - `partial_native_history`: "Some related records could not be shown."
  - `truncated_budget`: "Only part of this record's lineage is shown."
  - a gateway `not_found`, `denied` or `unavailable`: "Related Issues are unavailable."
  - never a count of what is hidden.
- **Accessibility:** a `section` with a heading, the choices as a radio group, the
  disclosure as a button with `aria-expanded`, usable at phone width, and no state
  conveyed by colour alone.

## 8. Old-client compatibility rule (v1)

S1 adds capabilities and changes **no** existing request or response, so no version
negotiation is introduced. `continuity.situations` and `continuity.situations.create`
keep their exact keys (an Issue appears in `continuity.situations` as a Situation, with
no `kind` or `version` key); `meetings.read`'s `MeetingNoteView` keeps omitting
`content_sha256`; `tasks.create`/`commitments.create` keep the `cap_`/`asrt_`
`origin_evidence_ref` rule and still refuse `mnote_`; `web/src/contracts/gateway.json`
keeps every existing entry, its decoder and its `success.json` fixture byte-for-byte; S1
adds exactly two entries (`records.lineage`, `meetings.notes.read_version`; 105 → 107
entries) with their own decoders. Any later change
to an existing contract needs an explicit negotiated version and a strict-client
regression fixture.

## 9. File plan and registration

New modules (resolve exact names against neighbours; no refactor of existing ones):
`domain/lineage/{__init__,vocabulary,canonical,model}.py`,
`domain/situation/issue_lifecycle.py`, `application/issues.py`,
`application/record_lineage.py`, `application/lineage_endpoints.py`,
`application/lineage_authority.py`, `infrastructure/persistence/issues.py`,
`infrastructure/persistence/record_lineage.py`, `contracts/v1/issues.py`,
`contracts/v1/record_lineage.py`, and new note-history view classes appended to
`contracts/v1/meetings.py`. `Situation` gains `kind` (default `context`) and `version`
(default 1). `SqlSituationRepository.close_situation` and
`SqlProjectRepository.link_situation` refuse an Issue (`kind = issue_workstream`).
`UnitOfWork` gains abstract `issues` and `record_lineage` properties, implemented or
stubbed in every subclass (W1 §2.2). Every registration step, count pin and docs claim
in W1 §2.2 and §5.4 applies (capability count, audit vocabulary, head literal, revision
count, `TABLES_SHA256`, `TABLES_ABOVE`, principal-partition guard registry, spelled
counts in `adapters/cli/app.py` and `bootstrap/gateway.py`, README/architecture/runbook
claims).

## 10. Acceptance-test crosswalk

Tier = repository marker selection (W1 §5.1). "FAST" = no marker. Database tests use
`@pytest.mark.database` (default `database_clone`); migration tests use the precedent
markers. Every path below is new unless marked existing. Names are binding for S1
implementers; a renamed test must update this table in the same commit.

| AT (S1 part) | Module | Test functions | Tier |
| --- | --- | --- | --- |
| AT-001 (stages 1–3 + reverse roots) | `tests/integration/test_issue_lineage_s1_vertical.py` | `test_m1_alone_creates_no_link`; `test_c1_originates_from_an_exact_n1_passage`; `test_reverse_read_from_m1_n1_c1_and_issue_yields_one_graph`; `test_n1b_does_not_retarget_c1`; `test_a_meeting_in_two_issues_requires_an_issue_choice` | database |
| AT-002 | `tests/database/test_meeting_note_lineage_asof.py` | `test_origin_anchor_survives_a_later_note_replace`; `test_origin_anchor_survives_a_later_note_append`; `test_read_version_returns_the_original_body_and_digest`; `test_versions_list_exposes_each_digest_without_bodies`; `test_a_digest_of_the_newer_note_is_refused_for_the_older_version` | database |
| AT-003 | `tests/integration/test_work_evidence_note_version.py` | `test_an_exact_note_passage_is_admitted_as_origin_evidence`; `test_a_note_version_under_another_meeting_is_not_found`; `test_a_spoofed_source_digest_is_refused`; `test_a_spoofed_passage_digest_is_refused`; `test_a_passage_outside_the_body_is_refused`; `test_a_hash_of_the_normalized_passage_is_refused`; `test_a_foreign_principal_note_is_not_found`; `test_a_refused_evidence_write_leaves_no_row_or_request`; `test_legacy_work_origin_evidence_ref_is_unchanged` | database |
| AT-004 | `tests/database/test_lineage_revision_evidence.py` | `test_each_revision_reads_its_own_evidence_set`; `test_the_stored_digest_rebuilds_from_stored_rows`; `test_evidence_cannot_be_added_to_a_committed_revision`; `test_identical_evidence_has_one_digest_across_revisions` | database |
| AT-004 / AT-010 (encodings) | `tests/unit/test_lineage_canonical.py` | `test_evidence_set_digest_golden_vectors`; `test_request_digest_golden_vectors`; `test_normalized_identity_golden_vectors`; `test_anchor_order_is_total_with_nulls_first`; `test_passage_hash_counts_code_points_not_bytes_or_graphemes` | FAST |
| AT-009 | `tests/security/test_lineage_reference_isolation.py` | `test_absent_and_foreign_endpoints_answer_alike`; `test_a_context_situation_is_not_an_issue_endpoint`; `test_a_wrong_parent_note_version_is_not_found`; `test_an_archived_task_is_not_linkable`; `test_a_foreign_issue_context_is_not_found`; `test_a_lineage_read_of_a_foreign_root_is_not_found`; `test_a_linked_native_record_cannot_be_deleted`; `test_no_row_is_written_for_a_refused_reference` | database |
| AT-010 | `tests/concurrency/test_lineage_idempotency.py` | `test_identical_replay_returns_one_root_revision_and_request`; `test_same_key_different_payload_is_conflict`; `test_distinct_keys_same_identity_return_the_existing_association`; `test_a_duplicate_assert_never_changes_authority`; `test_concurrent_identical_asserts_create_one_active_head`; `test_a_stale_expected_revision_is_conflict`; `test_concurrent_issue_updates_admit_one`; `test_concurrent_project_link_adds_admit_one` | database |
| AT-012 | `tests/database/test_lineage_integrity_guards.py` | `test_immutable_lineage_tables_refuse_update_and_delete` (parametrized, 6 tables); `test_lineage_tables_refuse_truncate` (8 tables); `test_a_head_admits_only_the_next_revision`; `test_a_head_cannot_lag_its_revisions_at_commit`; `test_a_write_request_completes_once`; `test_a_write_request_is_never_committed_reserved`; `test_an_issue_cannot_change_without_a_matching_revision`; `test_a_situation_kind_is_fixed`; `test_cross_principal_foreign_keys_refuse`; `test_an_anchor_binds_the_note_digest_and_parent`; `test_the_anchor_trigger_verifies_the_passage`; `test_rebuilt_heads_equal_stored_heads` | database |
| AT-012 (migration) | `tests/schema/test_record_lineage_s1_migration.py` | FAST: `test_the_revision_is_the_single_head_on_b9025e7fb738`; `test_the_revision_imports_no_domain_module`; `test_frozen_ddl_names_every_declared_constraint`; `test_before_vocabulary_is_a_byte_copy`; `test_at_vocabulary_adds_exactly_the_s1_names`; `test_offline_downgrade_refuses_first`. DB: `test_empty_to_head` (`migration_empty_to_head`); `test_previous_head_with_rows_upgrades`, `test_upgrade_refuses_a_cross_principal_project_situation`, `test_existing_situations_and_project_links_survive_unchanged`, `test_downgrade_refuses_while_lineage_rows_exist` (`migration`) | FAST + migration markers |
| AT-023 (S1) | `tests/contract/test_lineage_capability_admission.py` | `test_s1_capabilities_are_operator_decision_required`; `test_no_s1_capability_is_in_the_chatllm_data_profile`; `test_s1_requests_reject_server_owned_fields`; `test_existing_v1_shapes_are_unchanged`; `test_note_body_needs_the_history_purpose`; `test_lineage_authority_ignores_the_knowledge_manager_allowlist` | FAST |
| AT-023 (S1, DB) | `tests/database/test_lineage_attested_writes.py` | `test_an_ordinary_remote_client_is_denied_accepted_lineage_writes`; `test_a_local_operator_write_records_its_class_and_channel` | database |
| AT-024 (S1, server) | `tests/contract/test_lineage_read_contract.py` | `test_edges_carry_relation_direction_basis_and_evidence`; `test_reads_carry_no_body_or_hidden_count_and_only_issue_titles`; `test_completeness_is_stated_even_with_a_null_cursor` | FAST |
| AT-024 (S1, web component) | `web/src/components/work/related-issues.test.tsx` | `renders the related Issue with relation, direction, basis and actor class`; `lists candidate Issues as a radio group and re-queries with the chosen issueId`; `shows the empty message when no Issue matches`; `shows the partial and truncated messages without hidden counts`; `shows the unavailable message on not_found, denied and unavailable`; `opens a note-version anchor only on explicit action`; `issues exactly one lineage request per render` | vitest |
| AT-024 (S1, mounting) | `web/src/components/work/work-detail.related-issues.test.tsx`; `web/src/app/(app)/work/projects/[projectId]/constraints/constraint-inspector.related-issues.test.tsx` | `mounts the related-Issue panel on the Task detail`; `mounts the related-Issue panel on the Commitment detail`; `mounts the related-Issue panel in the Constraint inspector` | vitest |
| AT-024 (S1, browser) | `web/e2e/lineage-related-issues.spec.ts` | `related Issues on a Task are keyboard reachable and readable at phone width`; `an ambiguous record asks for an Issue before showing lineage` | playwright (own `npm run e2e`, seeded synthetic data) |
| AT-023 (S1, BFF) | `web/src/app/api/records/related-issues-route.test.ts`; `web/src/app/api/meetings/note-version-route.test.ts` | `calls records.lineage once with origin and max_depth 1`; `refuses a family outside task, commitment and constraint without a gateway call`; `refuses unknown query fields`; `calls meetings.notes.read_version only with an explicit includeBody` | vitest |
| AT-023 (S1, strict client) | `web/src/lib/api/decode/capabilities/records.lineage.test.ts`; `web/src/lib/api/decode/capabilities/meetings.notes.read_version.test.ts`; existing `web/src/lib/api/decode/registry.test.ts`; existing `tests/contract/test_bff_gateway_contract_parity.py`, `tests/contract/test_bff_success_decoder_parity.py` | `decodes the S1 lineage response`; `refuses an unknown key`; `decodes a note version with and without a body`; the existing registry and parity tests stay green with exactly two new entries and every existing entry unchanged | vitest + FAST |
| AT-026 (S1) | existing `tests/database/test_record_event_provenance.py` | existing `test_unknown_foreign_withheld_and_non_knowledge_events_answer_alike` (must stay green, unchanged) | database |
| AT-026 (S1) | `tests/architecture/test_record_lineage_s1_scope.py` | `test_s1_adds_no_record_event_family`; `test_every_s1_crosswalk_test_exists` (parses this table: Python rows by function name, vitest/playwright rows by test title) | FAST |
| (domain, unmapped) | `tests/unit/test_issue_lifecycle.py` | `test_allowed_state_moves`; `test_refused_state_moves`; `test_update_action_follows_the_state_move` | FAST |

**Not S1:** AT-001 stages 4–14 and AT-005, AT-006 (full), AT-007, AT-017 → S2;
AT-008, AT-011, AT-013, AT-014, AT-016, AT-024 Meeting view, timeline and graph, AT-025, AT-001 full
reverse-root equivalence → S3; AT-015, AT-018, AT-019, AT-022, AT-023 Commitment v2 →
Program/report work packages; AT-020, AT-021 → out of scope until OD-06.

## 11. Deferred work and its owner slice

| Item | Slice |
| --- | --- |
| `issues.close`/`reopen` with closure evidence and mandatory-member gate; `closed`/`reopened`/`corrected` actions | S2 |
| `delegated_from`, `escalated_from`, `blocks` (with type-specific cycle refusal), `created_to_resolve`, `related_context`; `contest`/`reinstate` link revisions | S2 |
| Capture version evidence (`UNIQUE (version_id, capture_id, owner_principal_id)`, RESTRICT binding), `legacy_unversioned` Capture roots, Managed Document versions, Knowledge Assertion evidence | S2 |
| Composite Work/Meeting/Constraint writes with `association_intents` (CR-006), responsibility/handoff (`ihnd`) | S2 |
| `issues.history`, `records.associations.history`, `records.associations.list_for_record`, `known_at`/`valid_at`, version selectors, cursors with grant-bound continuation, other native virtual edges, timeline, `explain_paths` | S3 |
| `records.associations.propose`/`review`, proposal roots/decisions/heads (`irp`, `ldec`) | S3 |
| Record Event family for lineage, `link_mutation_event_receipts` (`irec`) | S3 |
| Lineage runtime-role provisioning and privilege gate | CR-014 follow-up, operator-gated |
| Meeting record view and its related-Issue display; Issue pages, timeline and graph (WP-06A S3 stage) | S3 |
| Backfill/dry-run (WP-03B), Program, report manifest, finance, P6 | own work packages; finance/P6 gated by OD-06 |

## 12. W1 divergences — resolution

| W1 §7 | Resolution |
| --- | --- |
| 1 `ires` collides | S2 handoff uses `ihnd`; S1 prefixes in section 2 |
| 2 no Situation composite unique | added (section 4.1), plus the kind-bearing unique |
| 3 `project_situations` has no live writer | `issues.project_links.*` become its only Issue writer; legacy repository paths refuse Issues; existing rows validated, never repaired, unread by S1 |
| 4 no Situation Record Event | S1 adds no family; revisions are the receipts; S3 owns events |
| 5 composite column order | every new FK lists the referenced unique's order (`situations`, `projects`, `meeting_note_versions`, `record_links` as written above) |
| 6 `capture_versions` | not an S1 evidence family; S2 handling fixed in section 11 |
| 7 `asrt_` vs `kasr_` | `knowledge_assertion` = `kasr_`; `asrt_` stays Work-only and is not lineage evidence |
| 8 `meetings.read` omits digest | unchanged; `meetings.notes.*` expose it |
| 9 no common lock helper | section 6.2 order; `FOR SHARE` is honoured by every native writer |
| 10 TRUNCATE/roles only for Record Events | TRUNCATE refusal on all 8 tables in S1; roles deferred |
| 11 `reports.types.*` | not S1 |
| 12 AT-026 Capture case exists | existing test bound; no duplicate module |
| 13 07 id pattern | `IdKind` validation, 72-character cap |
| 14 anchors | informational |

Further package corrections made here: error codes are the repository's (ADR-015
decision 14); idempotency is scoped `(principal, capability, key)` as in Meetings, not
by `client_scope`; `issues.list`/`meetings.notes.versions` use `after`/`next_cursor` as
in `meetings.list`; Project link and membership writes do not bump the Issue version and
use their own revision CAS; Project link evidence is optional because S1's only
evidence family is Meeting notes; the meeting-note anchor binding is inline columns
with a digest-bearing composite FK rather than a separate binding table; the package's
`hidden_node_count` is omitted because hidden counts must not be disclosed. The WP-06A S1 display covers the Task, Commitment and Constraint
views only, because `web/` has no Meeting record view to extend; `records.lineage`
returns Issue titles (and only Issue titles) so the display needs no per-Issue read.

## 13. Operator gates that remain

Ratification of ADR-015 beyond the directive defaults; any live migration, grant,
ChatLLM or client exposure, deployment or backfill (OD-07); source commissioning for
finance and P6 (OD-06); runtime-role provisioning; and any closure-exception or
completeness-threshold risk acceptance (OD-03, OD-08). Nothing else in S1 is left for a
worker to decide beyond local naming that has no incumbent constraint.
