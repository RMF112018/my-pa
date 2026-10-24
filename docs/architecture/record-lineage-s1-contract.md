# Record lineage — Slice S1 implementation contract

**Status:** proposed implementation contract under
[ADR-015](../decisions/ADR-015-record-lineage-and-issue-situations.md) (Proposed —
accepted by directive defaults; architecture/test-isolated scope only). It is the
single document S1 implementers code against. It authorizes no migration run, grant,
deployment, backfill or production use. Where it differs from the review package
(`MYPA-LINEAGE-ADVERSARIAL-REVIEW-20261017-001`, documents 02, 03, 04 and 07), this
document controls for S1 and section 12 records why.

**Implementation:** S1 is implemented on `feat/lineage-s1-integration` (workers I1 to I5)
and exercised only against isolated synthetic test databases; it is not merged, migrated
anywhere live, granted, exposed or deployed. Sections 4.3, 6.2, 7.2, 7.4 and 7.5 carry
"as implemented" notes where the code resolved a point this contract left open.

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
Issue memberships, three semantic relation types, exact Meeting note version and Capture
version evidence plus labelled `legacy_unversioned` Capture roots (WP-02A), a
`lineage_enabled` switch that is off by default (section 7.5), refusal of Issue
`situation_id` references by the existing Work/Memory writers (section 8),
immutable roots/revisions/evidence/heads, idempotency and CAS, a bounded single-page
`records.lineage`, two Meeting note history reads, and the minimal WP-06A related-Issue
display on the Task, Commitment and Constraint record views (section 7.4).

**Not in S1** (section 11 lists the owner slice): Issue close/reopen, history and
bitemporal reads, proposals and review, contest/reinstate/replacement corrections,
the other four semantic types, Managed Document/Knowledge Assertion/external evidence, version selectors other than `root`, cursors on `records.lineage`, Record
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
`cmt`, `cst`, `cap`, `capver`, `prn`.

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
| `RecordFamily` (endpoint) | `situation`, `meeting`, `meeting_note_version`, `task`, `commitment`, `constraint`, `capture_version` | `project`, `entity`, `capture`, `managed_document`, `managed_document_version`, `knowledge_assertion`, `continuity_decision` |
| `RecordLinkKind` | `issue_membership`, `semantic` | — |
| `RelationType` | `issue_member`, `originated_from`, `discusses` | `delegated_from`, `escalated_from`, `blocks`, `created_to_resolve`, `related_context` (S2) |
| `MemberRole` | `origin_evidence`, `discussion`, `work`, `constraint`, `supporting_evidence`, `reference` | `decision` (S2, with `continuity_decision`) |
| `Selector` | `root` | `immutable_version`, `aggregate_version` (S3) |
| `LinkRevisionAction` | `assert`, `end`, `correct_evidence` | `contest`, `reinstate` (S2) |
| `LinkLifecycleState` | `active`, `ended` | `contested` (S2) |
| `AcceptanceBasis` | `user_confirmed` | `review_accepted`, `system_deterministic`, `source_backed_verified` (S2/S3) |
| `EvidenceSourceFamily` | `meeting_note_version`, `capture_version`, `capture` (root only, `legacy_unversioned`) | `managed_document_version`, `knowledge_assertion`, `external_version` |
| `SourceVersionKind` | `immutable_version`, `legacy_unversioned` | `aggregate_version`, `external_version` |
| `EvidenceRole` | `origin`, `corroborates`, `contradicts`, `discussion`, `handoff`, `resolution` | — |
| `EvidenceAvailability` (read only) | `available`, `archived`, `legacy_unversioned` | `restricted`, `redacted`, `unavailable`, `withdrawn`, `superseded` |
| `LineageCompleteness` (read only) | `complete`, `truncated_budget`, `unresolved_ambiguity`, `partial_native_history` | `restricted_evidence`, `scope_changed_restart_required`, `source_not_integrated`, `not_reportable` |
| `NativeVirtualEdge` (read only) | `meeting_note_version_of` | `follow_up`, `constraint_follow_up`, `meeting_in_series`, `project_issue`, `entity_member_of` |
| Authority class (reused, `KnowledgeReviewAuthorityClass`) | `local_operator`, `ordinary_reviewer` (`remote_operator_attested` is unreachable in S1, section 6.1); attested tables admit only `local_operator` (CHECK, section 4.2), `ordinary_reviewer` appears only on Issue revisions | — |
| Decision channel (reused, `KnowledgeDecisionChannel`) | `local_cli`, `local_web`, `local_unattested`, `remote_interactive`, `remote_operator_review` | — |

### 3.1 S1 relation matrix (the closed policy)

| Relation (kind) | From | To | Evidence rule (checked in the application, refused with `invalid_request` / `evidence_anchors`) |
| --- | --- | --- | --- |
| `issue_member` (`issue_membership`) | `situation` (Issue) | `meeting`, `meeting_note_version`, `task`, `commitment`, `constraint`, `capture_version` | 0..32 anchors, any role (legacy roots: see below); `member_role` required |
| `originated_from` (`semantic`) | `commitment`, `task`, `constraint` | `meeting_note_version`, `capture_version` | ≥1 `immutable_version` anchor of the `to` family with role `origin`, a passage, and `source_version_id` equal to the `to` version |
| `discusses` (`semantic`) | `meeting`, `meeting_note_version` | `situation` (Issue), `task`, `commitment`, `constraint` | ≥1 anchor with role `discussion` whose note version is the `from` note version, or belongs to the `from` Meeting |

Any other `(from, to, relation)` is `invalid_request` / `relation_type`. `issue_member`
is written only by `issues.memberships.add`; `records.associations.assert` refuses it.
A Project is never an `issue_member`; Project scope is `issues.project_links.*`.

**Legacy Capture roots.** An anchor with `source_family = capture` and
`source_version_kind = legacy_unversioned` names a `cap_` root and pins no version, digest
or passage. It is admitted only with role `corroborates` or `contradicts`, never counts
toward any "≥1 anchor" rule above, is reported with availability `legacy_unversioned`,
and can never satisfy an exact-version or closure requirement (S2's Issue close refuses
it). It exists so a Work record's legacy `origin_evidence_ref = cap_…` can be cited
honestly, not upgraded. Because a root has no classification of its own, a legacy root
is refused (`invalid_request` / `evidence_anchors`, after the ownership check) when **any**
version of it is `restricted_local` (F21). The rule is **point-in-time** (F24): it is
checked at write against the root's committed versions and guarantees nothing afterwards
(a concurrent or later revise may add a restricted version; `FOR SHARE` does not
serialize with a revise). A restricted version added later is out of S1 scope: the legacy
anchor still discloses only the `cap_` id with no digest, version or offsets, and it
becomes the S3 `restricted` availability and remote withholding (section 11).

### 3.2 Endpoint linkability (S1)

| Family | Native row (Principal-scoped) | Linkable when | Lock |
| --- | --- | --- | --- |
| `situation` | `situations` | `kind = 'issue_workstream'`; a context Situation is `invalid_request` / `endpoint` | `FOR UPDATE` when the write changes the Issue, else `FOR SHARE` |
| `meeting` | `meetings` | any `status` | `FOR SHARE` |
| `meeting_note_version` | `meeting_note_versions` | always (immutable) | `FOR SHARE` |
| `task` | `tasks` | `archived_at IS NULL`, else `invalid_request` / `endpoint` (a Task is archived by `tasks.update` with `archived: true`, the repository's only archive route) | `FOR SHARE` |
| `commitment` | `commitments` | any `state` and `evidence_state` (acceptance of the Commitment is its own) | `FOR SHARE` |
| `constraint` | `project_constraints` | any state | `FOR SHARE` |
| `capture_version` | `capture_versions` (partition `owner_principal_id`) | its Capture root is neither archived nor withdrawn (lifecycle projection, as `accepts_work_evidence_reference`), else `denied` / `capture_withdrawn`; `classification` is `synthetic_test` or `private_local`, else `invalid_request` / `endpoint` (restricted evidence is S3) | root via `share_capture_root` (`FOR SHARE`, which archive's `FOR NO KEY UPDATE` waits on), version row `FOR SHARE` |

**Check order (every endpoint, Issue context and evidence source, no exception):**
(1) identifier prefix for the family, else `invalid_request`; (2) Principal-scoped
existence and the correct parent, else `not_found` with the same safe detail for absent,
foreign and wrong-parent; (3) only then linkability, archive/withdrawal and
classification. So a foreign archived Task and a foreign context Situation answer
`not_found` exactly like a foreign live Task, and no write happens. The same three rules
apply to anchors (the Capture root of a `capture`/`capture_version` anchor, the Meeting
of a note anchor).

## 4. Schema — one additive revision

One Alembic revision, `down_revision = "b9025e7fb738"`, the new single head
(file `migrations/versions/<date>_<rev>_record_lineage_s1.py`). Frozen literal DDL; no
domain or persistence import; declarations mirrored in
`infrastructure/persistence/tables.py` with the `TABLES_SHA256` pin updated — **except**
the one constraint marked database-only in section 4.1, which a historical revision
would otherwise emit. Names
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

**`capture_versions`**

- `UNIQUE (version_id, capture_id, owner_principal_id, content_sha256)` `a_capture_version_digest_is_identified_within_its_capture` — the Capture-version anchor target (W1 §7 item 6). Additive; `capture_versions` is append-only already, so adding the constraint rewrites nothing. **Database-only (F20):** it is added by the S1 revision with `ALTER TABLE … ADD CONSTRAINT` and is **not** declared on `capture_versions` in `tables.py`, because historical revision `1a4c9e77b2d5` builds `capture_versions` from the live declaration and would then emit it at base (breaking `migration_empty_to_head` and changing a historical revision). A comment beside the `capture_versions` declaration records it, as the `captures` comment records `0641c354ca85`'s root unique. The anchor FK declared in `tables.py` may still reference it, as the lifecycle FKs reference that root unique.
- The existing `capture_id → captures ON DELETE CASCADE` is **left unchanged**: it is not required to change, because `capture_versions` already refuses `DELETE` by trigger (`1a4c9e77b2d5`) and the new anchor FK is `RESTRICT`, so a `captures` delete that would cascade into an evidenced version fails rather than removing it. `src/` has no Capture hard-delete path.
- The legacy root anchor targets the existing `UNIQUE (capture_id, owner_principal_id)` added by `0641c354ca85` (database-only; look up its name in that revision).

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
CHECK `a_lineage_row_is_local_operator_attested` as on `record_links`. Trigger
`a_membership_event_follows_its_predecessor` (`BEFORE INSERT`): `end` needs an
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
`a_record_link_pair_is_admitted` — the section 3.1 matrix as a disjunction;
`a_lineage_row_is_local_operator_attested` — `authority_class = 'local_operator' AND decision_channel IN ('local_cli','local_web')` (F21; the same CHECK, same name, on `record_link_revisions` and `issue_project_membership_events`; it is widened only together with the ADR-015 amendment a remote attested writer needs). Trigger
`a_record_link_identity_is_canonical` (`BEFORE INSERT`): `normalized_identity` must
equal `knowledge.lineage_record_link_identity(...)` over the row's columns (section 5.5),
so a writer that serializes differently cannot create a second active head for one
meaning. Indexes
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
`action = 'end'` ⇔ `lifecycle_state = 'ended'`; `action IN ('end','correct_evidence')` ⇒ `reason IS NOT NULL`;
`a_lineage_row_is_local_operator_attested` as on `record_links`.
Trigger `a_link_revision_follows_an_active_predecessor` (`BEFORE INSERT`). Constraint
trigger `a_link_head_is_its_latest_revision` (deferred): the head's `revision_no`
equals the link's maximum revision at commit.

**`lineage_evidence_anchors`** (immutable)

| Column | Type / rule |
| --- | --- |
| `principal_id`, `anchor_id` (`ian`) | PK |
| `source_family` | S1 `EvidenceSourceFamily` |
| `source_root_id` (`mtg` or `cap`), `source_version_kind`, `source_version_id` (`mnote`, `capver` or null) | |
| `source_version_no` | server-derived `version_number` of the bound version; null for a legacy root |
| `source_sha256` | sha256 hex; null only for a legacy root |
| `passage_start_cp`, `passage_end_cp`, `passage_sha256` | all null, or `0 <= start < end` with digest |
| `meeting_id`, `note_version_id`, `capture_id`, `capture_version_id` | binding columns; CHECK `an_anchor_binds_exactly_its_family`: a note anchor sets only the Meeting pair (equal to root/version, kind `immutable_version`, digest set); a `capture_version` anchor sets only the Capture pair (equal to root/version, kind `immutable_version`, digest set); a `capture` anchor sets only `capture_id` (equal to root, kind `legacy_unversioned`, version, number, digest and passage null) |
| `anchor_identity` | canonical JSON (section 5.1, without `role`); `UNIQUE (principal_id, anchor_identity)` |
| `recorded_at` | |

FKs (all `RESTRICT`; `MATCH SIMPLE`, so each applies only when its binding columns are set):
`a_lineage_anchor_binds_an_exact_meeting_note`
`(note_version_id, meeting_id, principal_id, source_sha256) → meeting_note_versions (note_version_id, meeting_id, principal_id, content_sha256)`;
`a_lineage_anchor_binds_an_exact_capture_version`
`(capture_version_id, capture_id, principal_id, source_sha256) → capture_versions (version_id, capture_id, owner_principal_id, content_sha256)`;
`a_lineage_anchor_names_a_capture_of_its_principal`
`(capture_id, principal_id) → captures (capture_id, owner_principal_id)`.
Trigger `a_lineage_anchor_passage_matches_its_source` (`BEFORE INSERT`): refuses unless
`server_encoding = 'UTF8'`; requires `source_version_no` to equal the bound row's
`version_number`; with a passage, requires `passage_end_cp <= char_length(body)` and
`passage_sha256 = encode(sha256(convert_to(substr(body, passage_start_cp + 1, passage_end_cp - passage_start_cp), 'UTF8')), 'hex')`,
where `body` is `meeting_note_versions.content_markdown` or `capture_versions.content`.
Trigger `a_lineage_anchor_identity_is_canonical` (`BEFORE INSERT`, F12): `anchor_identity`
must equal `knowledge.lineage_anchor_identity(...)` over the row's columns (section 5.5).
(PostgreSQL `substr`/`char_length` count code points in a UTF-8 database, matching
Python `str` slicing.)

**`record_link_revision_evidence`** (immutable)

Columns `principal_id, link_id, revision_no, ordinal (smallint 1..32), anchor_id, role (EvidenceRole)`;
PK `(principal_id, link_id, revision_no, ordinal)`; `UNIQUE (principal_id, link_id, revision_no, anchor_id)`;
FKs to `record_link_revisions` and `lineage_evidence_anchors`. `ordinal` is the
1-based position in the section 5.1 canonical order. The anchor unique means one source
passage carries one role per revision; the application refuses a set that repeats an
`anchor_identity` (section 5.1) before any insert, so the unique is never the error a
caller sees. Constraint triggers
`a_link_revision_evidence_set_is_frozen` on both this table and
`record_link_revisions` (deferred): at commit the row count for the revision equals
its `evidence_count`. A later transaction adding evidence to a committed revision
therefore fails.

**`record_link_heads`** (derived projection, verified by rebuild parity)

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
| `result_created` | `boolean`; required (NOT NULL when completed) for `issues.memberships.add` and `records.associations.assert`, null otherwise |
| `created_at`, `completed_at` | |

CHECK: reserved rows (`completed_at IS NULL`) carry no result; a completed row carries
exactly one result group, the one its capability produces. Trigger
`a_lineage_write_request_completes_once` (`BEFORE UPDATE OR DELETE`): only
`completed_at` and the result columns may change, only from reserved, only once;
`DELETE` refused. Constraint trigger `a_lineage_write_request_is_never_left_reserved`
(`AFTER INSERT`, deferred; precedent `knowledge_submission_is_never_left_reserved`).

### 4.3 Shared triggers, protection of linked records, downgrade

- `lineage_rows_are_append_only()` — `BEFORE UPDATE OR DELETE … FOR EACH ROW`, raises `restrict_violation`; attached to `issue_revisions`, `issue_project_membership_events`, `record_links`, `record_link_revisions`, `lineage_evidence_anchors`, `record_link_revision_evidence`.
- `lineage_relations_refuse_truncate()` — `BEFORE TRUNCATE … FOR EACH STATEMENT`; attached to all 8 new tables (precedent `c8e4a1b70d35`). It refuses when the truncated table holds a row; a `TRUNCATE` of an empty table is admitted, since it removes nothing (I1 divergence, accepted).
- `a_linked_record_is_not_deleted()` — `BEFORE DELETE … FOR EACH ROW` on `situations`, `meetings`, `tasks`, `commitments`, `project_constraints`: refuses when any `record_links` row of the same Principal names the row as `from` or `to` (served by the two endpoint indexes). `meeting_note_versions` and `capture_versions` already refuse deletes.
- No role grants change (ADR-015 decision 10). The triggers bind **DML** by every role, the owner included; the table owner and a superuser can still `ALTER TABLE … DISABLE TRIGGER` or drop them, so S1's immutability is a DML guarantee, not a DDL one. Closing that gap is the CR-014 role-separation follow-up (owner/migrator/runtime, the `record_event_roles.py` pattern), operator-gated.
- **`TRUNCATE … CASCADE` residual (FR1-F06).** `a_linked_record_is_not_deleted` is a row-level `BEFORE DELETE` trigger, so it does not fire for `TRUNCATE`. `TRUNCATE knowledge.tasks CASCADE` (likewise `commitments` and `project_constraints`, which no foreign-key chain joins to the lineage tables) removes linked rows and leaves `record_links` naming absent records; `situations` and `meetings` are reached through their foreign-key chains and refuse. This is an owner-level operation of the same class as `DISABLE TRIGGER`: no runtime path issues `TRUNCATE` (only test fixtures do), and the CR-014 role separation, which denies the runtime role `TRUNCATE`, closes it. S1 adds no statement-level refusal.
- `downgrade()` first refuses (`restrict_violation`) while any row exists in the 8 new tables, any Situation has `kind = 'issue_workstream'`, or any `audit_events` row names an S1 capability or purpose; only then drops in reverse order.
- The revision restates `capability_is_known` and `purpose_is_known` on `knowledge.audit_events` (BEFORE texts byte copies of the latest restating revision, AT texts add exactly the S1 names sorted), and `_CURRENT_AUDIT_CAPABILITIES` moves with it (W1 §2.2 "Schema").
  The schema-ahead gap this opened (`tests/schema/lineage_schema_ahead_contract.py`, the
  Knowledge precedent's shape) is **closed** on the implementation branch: the domain
  declares all 14 capability and 5 purpose names, both declared sets equal the full S1
  sets and `LINEAGE_S1_DECLARED_BY_DOMAIN` is true, measured (not trusted) by
  `tests/schema/test_record_lineage_s1_migration.py`.

## 5. Canonical encodings

One module, `NEW domain/lineage/canonical.py`, pure functions with golden vectors.
"Canonical JSON" is ADR-014 decision 6: NFC-normalized strings,
`json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, UTF-8,
no floats, every fixed key present (`null` when absent). The anchor, evidence-set and
identity objects contain only identifiers, closed tokens, integers, hex and `null`, all
ASCII, so NFC is the identity on them and SQL can rebuild them exactly (5.5). The request
digest (5.4) is deliberately **not** NFC-normalized.

### 5.1 Anchor object, order, evidence-set digest

Anchor object keys (exactly): `source_family`, `source_root_id`, `source_version_kind`,
`source_version_id`, `source_version_no`, `source_sha256`, `passage_start_cp`,
`passage_end_cp`, `passage_sha256`, `role`. `anchor_identity` is the same object
without `role`, canonical JSON. Order: by the tuple of those ten values, with `null`
before any value and integers compared numerically. A set in which two anchors share an
`anchor_identity` — whether or not their roles differ — is `invalid_request` /
`evidence_anchors`. `source_version_no` is never client-supplied: the server fills it
from the bound version row before computing any digest.

**Anchor writes.** Anchors are written in this canonical order, each by
`INSERT … ON CONFLICT (principal_id, anchor_identity) DO NOTHING` followed by a `SELECT`
of the row, so two transactions reusing overlapping anchors acquire them in the same
order and cannot deadlock on each other.

`evidence_set_digest = sha256(b"lineage-evidence-set-v1\n" + canonical_json({"schema_version": 1, "anchors": [ordered anchor objects]})).hexdigest()`.
Anchor identifiers are not in it. The empty set is legal where section 3.1 allows it.

### 5.2 Passage

`passage_start_cp`/`passage_end_cp` index the stored body (`meeting_note_versions.content_markdown` or `capture_versions.content`) as a Python
`str` (code points), zero-based, end-exclusive; `passage_sha256 = sha256(body[start:end].encode("utf-8")).hexdigest()`.
The body is never normalized. Mismatch, out of range, `start >= end`, or a partial
triple is `invalid_request` / `evidence_anchors`.

### 5.3 Normalized identity

`normalized_identity = canonical_json({"schema_version": 1, "kind", "relation_type", "from": {"family", "record_id", "selector": "root"}, "to": {...}, "member_role", "context_issue_id"})`.
Stored in full; uniqueness never relies on a hash.

### 5.4 Request digest

`request_digest = sha256(b"lineage-request-v1\n" + json.dumps({"capability", "principal_id", "request"}, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()`,
where `request` is the parsed payload without `idempotency_key`, optional fields
present as `null`, anchors in section 5.1 order, `clear_fields` sorted. **No NFC** is
applied, matching the Meetings request digest (`application/meetings.py`): free text is
hashed as the exact code points received and stored, so an NFD and an NFC title under one
key are different requests (`conflict`), never a replay.

### 5.5 SQL rebuild of the identities (F12)

The revision defines two `IMMUTABLE` SQL functions,
`knowledge.lineage_record_link_identity(kind, relation_type, from_family, from_id, to_family, to_id, member_role, context_issue_id)`
and `knowledge.lineage_anchor_identity(source_family, source_root_id, source_version_kind, source_version_id, source_version_no, source_sha256, passage_start_cp, passage_end_cp, passage_sha256)`,
that build the section 5.1/5.3 strings by concatenation in sorted-key order, with
`coalesce(to_json(value)::text, 'null')` for each string and `coalesce(value::text, 'null')`
for each integer (a bare `to_json(NULL)` is SQL `NULL` and would null the whole string) —
byte-identical to `canonical.py` for the ASCII inputs above. The two `BEFORE INSERT`
triggers in section 4.2 compare against them. Golden vectors are shared: the same fixture
file drives the Python unit test and the SQL parity test (section 10). `downgrade()` drops
both functions after their triggers.

## 6. Authority, locks and the transaction

### 6.1 Authority

`NEW application/lineage_authority.py` calls `derive_knowledge_review_authority`
(`domain/policy/knowledge_review_authority.py`) with the server-stamped operator
surface, transport, operator flag, authenticated client id and grant-ceiling flag, and
with **`operator_review_allowlist=frozenset()` and `manager_allowlist=frozenset()`**.
The Knowledge operator-review allowlist (`knowledge_operator_review_client_ids`,
`MY_PA_KNOWLEDGE_OPERATOR_REVIEW_OAUTH_CLIENT_IDS`) is not read, reused or widened: its
clients are narrowed to the `knowledge-operator-review-v1` profile
(`bootstrap/knowledge_discovery_profiles.py`), which holds no S1 capability, and S1
introduces no lineage allowlist or settings key.

- **Attested writes** — `issues.project_links.add/end`, `issues.memberships.add/end`, `records.associations.assert/correct/end`: **S1 attested writes are local-operator only.** The class must be `local_operator` (the CLI, and the HTTP gateway `invoke` route that stamps `OperatorSurface.HTTP_GATEWAY`), else `denied` before any row is written, including before a replay lookup. With both allowlists empty the derivation cannot return `remote_operator_attested`; the code may keep that branch, but it is unreachable in S1, and a remote attested lineage writer needs its own allowlist, settings key, disjointness rule and ADR-015 amendment. Stored `acceptance_basis = 'user_confirmed'`.
- **Recorded writes** — `issues.create`, `issues.update`: any admitted caller; class and channel recorded on the Issue revision.
- `InconsistentKnowledgeReviewCompositionError` → `internal_error`; `UnsupportedKnowledgeReviewCompositionError` → `unsupported` (as Knowledge does).

### 6.2 Lock order (every S1 writer, one transaction)

1. Reserve the `lineage_write_requests` row (`INSERT … ON CONFLICT DO NOTHING`; on conflict read the completed row: same digest → replay, else `conflict`).
2. Issue Situation(s) the write changes: `FOR UPDATE`, identifier order.
3. Every other endpoint, Issue context, evidence note version, Capture root (via `share_capture_root`) and Capture version: `FOR SHARE`, ordered by `(family token, identifier)`.
4. `pg_advisory_xact_lock(<lineage namespace>, hashtext(principal_id || ':' || normalized_identity))` for an association/membership write; the namespace constant is new and must differ from every advisory key already in `src/`. W1 §7 item 9 is incomplete (it omits at least `infrastructure/security/origin_authorization.py`, key `7420196`, `infrastructure/persistence/intelligence.py` and `infrastructure/persistence/goodnotes.py`); the implementer greps `src/` for `advisory` and records every key it found in the PR.
5. The association head `FOR UPDATE`, or the `project_situations` triplet row `FOR UPDATE` after `INSERT … ON CONFLICT DO NOTHING`.

Reads take no locks.

**Deadlocks are possible.** The `(family token, identifier)` order sorts, for example,
`commitment` before `task`; a native writer that holds `FOR UPDATE` on a Task and then
updates a Commitment, while a lineage writer holds `FOR SHARE` on that Commitment and
waits on the Task, forms a cycle PostgreSQL breaks by aborting one side. The lineage side
runs its statements through the unit of work's `is_transaction_conflict` wrapper, so a
deadlock (`40P01`) or serialization failure (`40001`) becomes `TransactionConflictError`
and the existing `_port_failure` mapping answers `conflict` (guidance `after_refresh`),
the repository's idiom for a lost race; the request row rolls back with everything else.
**Residual:** native Work/Meeting/Constraint writers are not all routed through that
wrapper, so the native side of such a deadlock may surface as `internal_error` rather than
`conflict`. S1 does not change native writers; the residual is pinned by a test that
records the native side's code as observed, and fixing it is a separate work package.
The pin (`test_the_native_side_of_a_lineage_deadlock_is_recorded`) drives the native side
at the **SQL level** on a second connection (`SELECT … FOR UPDATE` on the Task, then an
`UPDATE` of the Issue row), not through a native capability, and observes the raw
`40P01`; the lineage side, through `ApplicationService.invoke`, commits. Which side
PostgreSQL aborts is made deterministic by setting `deadlock_timeout` per session, which
needs a **superuser** test role: CI's `my_pa` service user is one, and a local run needs
the same (for example an `initdb` cluster whose bootstrap user runs the tests).

### 6.3 Transaction order (02 §2.4, S1 form)

1. Authorize capability/purpose/grant; strict-parse; derive authority (refuse here).
2. Compute the request digest; reserve (6.2 step 1).
3. Acquire locks (6.2 steps 2–5); validate endpoints (3.2), the matrix (3.1), every anchor against its locked source version or Capture root (5.1, 5.2), and expected versions/revisions (`conflict` when stale).
4. Write: reuse-or-insert anchors; root and revision 1, or the next revision; revision evidence; head insert or update — or the Issue revision and the Situation update — or the `project_situations` row (new link) and the membership event.
5. Complete the request row with its result (and `result_created` where required).

**Replay.** A replay (same key, same digest) rebuilds its response from the immutable rows
the stored result names, never from current state: the Issue revision at
`result_issue_version`, the link revision at `result_link_revision_no` with that
revision's evidence, or the membership event; `created` is `result_created`; `replayed` is
`true`. The response is therefore byte-identical to the original apart from `replayed`, as
Meetings guarantees, even if the link or Issue has moved on since.
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
- `EvidenceAnchorInput` = `{family: "meeting_note_version"|"capture_version"|"capture", root_id: mtg_|cap_, version_kind: "immutable_version"|"legacy_unversioned", version_id?: mnote_|capver_, source_sha256?: hex64, passage_start_cp?: int >= 0, passage_end_cp?: int >= 1, passage_sha256?: hex64, role: EvidenceRole}`; `version_no` is not accepted. `immutable_version` requires `version_id` and `source_sha256`; `legacy_unversioned` (family `capture` only) forbids `version_id`, digests and passage.
- `EvidenceAnchorView` = `{anchor_id, family, root_id, version_kind, version_id, source_version_no (server-derived), passage_start_cp, passage_end_cp, role, availability: "available"|"archived"|"legacy_unversioned"}`. `availability` is computed **at read time** (F19): `archived` when the anchor's Capture root (for `capture_version` and legacy `capture` anchors) is currently archived in its lifecycle projection; else `legacy_unversioned` for a legacy root; else `available`. Note anchors are always `available`. Archiving or restoring the Capture writes no lineage row and changes no revision, digest or link; a restore returns the anchor to `available` (or `legacy_unversioned`). This is ADR-015 decision 8: availability is reported, never written back. **No `source_sha256` and no `passage_sha256`** (F11): a short passage's digest is brute-forceable, so digests are revealed only by `meetings.notes.read_version` (note content digest) and the existing Capture read surfaces under their own grants. Offsets and version ids remain.
- `AssociationView` = `{link_id, kind, relation_type, from: RecordRef, to: RecordRef, member_role, context_issue_id, revision_no, lifecycle_state, acceptance_basis, authority_class, evidence: [EvidenceAnchorView], created_at, recorded_at}` (`recorded_at` of the revision shown). The stored `evidence_set_digest` is **withheld** from every read and write view (FR1-F05): it is SHA-256 over the anchor objects, which carry the withheld `source_sha256` and `passage_sha256` beside every field the view shows, so for a short note or Capture body a caller could confirm a guessed body by rebuilding it. It stays stored, rebuilt and parity-tested (section 10, AT-004).
- `IssueView` = `{issue_id, kind: "issue_workstream", version, state, title, description, opened_at, created_at, updated_at, project_links: [ProjectLinkView], project_links_truncated: bool}`; at most 100 links, active first, then `project_id`.
- `ProjectLinkView` = `{project_id, project_situation_id, state: "active"|"ended", membership_revision_no, acceptance_basis, evidence_anchor_id, recorded_at}`.
- `IssueRevisionView` (write responses of `issues.create`/`issues.update`) = `{issue_id, kind, version, state, title, description, revision_id, action, opened_at, created_at, recorded_at}` — rebuilt from the immutable revision, so a replay is byte-stable; it carries no Project links.
- Write results add `replayed: bool`; association/membership adds also `created: bool` (stored as `result_created`).
- Envelope, disclosure and error mapping are the existing v1 ones.

### 7.2 Per-capability contract

**`issues.create`** — in `{title (1..500, non-blank), description? (<=10000), idempotency_key}`;
out `{issue: IssueRevisionView, replayed}`. Inserts `situations` (`kind = 'issue_workstream'`,
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
out `{issue: IssueRevisionView, replayed}`. Allowed state moves: `open → active` (`activated`),
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

**`records.associations.assert`** — in `{from_record: RecordRef, to_record: RecordRef, relation_type, idempotency_key, evidence_anchors ([1..32]), context_issue_id?}`;
out `{association, created, replayed}`. The **request** keys are `from_record`/`to_record`
(`from` is a Python keyword and every payload key is a command dataclass field, the
`payload_schema_for` rule); the **view** keys of `AssociationView` and of a virtual edge
stay `from`/`to` (section 7.1). An unknown `from`/`to` key in the request is
`invalid_request` like any unknown field. `relation_type = issue_member` is
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
2. Matching Issues. Let the root's **pair set** *P* be the root alone, plus its Meeting when the root is a note version, plus every note version of the root when the root is a Meeting. The matching Issues are: the root itself if it is an Issue; Issues with an active membership of any member of *P*; the `context_issue_id` of every active semantic link incident to any member of *P*; and the Issue `to` endpoint of every active `discusses` link from any member of *P*. The pair extension applies to all three sources alike, so M1 and N1 always match the same Issues.
3. `issue_id` given and not matching ⇒ `not_found`. Not given: exactly one ⇒ selected; more than one ⇒ return the candidates (sorted, at most 20), `complete_state = unresolved_ambiguity`, no traversal; none ⇒ one hop over active semantic links incident to the root with `context_issue_id IS NULL`, plus its virtual note edge, no expansion.
4. With Issue *I* selected, breadth-first from the root to `max_depth`, following only: *I*'s active membership links; active semantic links whose `context_issue_id = I`, whose endpoint is *I*, or whose context is null and whose two endpoints are both in *I* (*I*, an active member, or a member of the pair set of an active member); and `meeting_note_version_of` between a reached node and its pair. Links scoped to another Issue are never followed.
   **As implemented** (`application/record_lineage.py`, the I3 resolution of this step):
   expanding a node expands its pair set — a note version also follows the followable
   links incident to its Meeting, and a Meeting those incident to its note versions; a
   followed link adds its far endpoint and, when it was reached through a pair member,
   that member as nodes. A reached note version always reaches its Meeting (next depth)
   along `meeting_note_version_of`. A reached Meeting does **not** make its other note
   versions nodes: they appear only as its virtual edges (step 6 order). So in the AT-001
   fixture every root yields {I, M1, N1, C1} and N1b is a virtual edge of M1 only. With no
   Issue matched (step 3), the one hop also reaches a note-version root's Meeting.
5. Re-resolve every reached node in its native table; a node that no longer resolves is dropped with its edges and sets `partial_native_history`. A `capture_version` node whose Capture root is currently archived is kept and carries `availability: "archived"` (nodes gain an `availability` field for this family only); its anchors read `archived` as in section 7.1.
6. Budgets (design values, not benchmarks): 250 nodes, 400 edges (typed plus virtual), 512 KiB serialized. Reaching one stops expansion and sets `truncated_budget`. Expansion order: frontier by `(depth, family, record_id)`, edges by `(created_at, link_id)`, virtual edges by `version_number`. Output order: nodes by `(depth, family, record_id)`, edges by `link_id`.
7. No body, no title other than an Issue's own title and state, and no hidden count is returned; `next_cursor` is always `null` in S1 and does not imply completeness.

**AT-001 S1 fixture (explicit).** Issue *I*; Meeting M1 with note versions N1 then N1b;
Commitment C1. Memberships: `I → M1` role `discussion` and `I → C1` role `work`.
Association: `C1 originated_from N1` with `context_issue_id = I` and one `origin` anchor on
an N1 passage. N1 has **no** membership of its own. From each of M1, N1, C1 and *I*, the
read selects *I* and returns the same node set {I, M1, N1, C1} (N1b is reachable only as a
virtual note edge of M1 and never as C1's origin) and the same typed edges. A second
fixture without the `I → M1` membership must still reach C1 from M1 (through the pair set
and the link's context), and a link scoped to another Issue *J* on N1 must not make *J*
selectable from M1 when `issue_id = I` is given.

**`meetings.notes.versions`** — in `{meeting_id, page_size? (1..100, default 25), after? (mnote_)}`;
out `{meeting_id, versions: [{note_version_id, version_number, supersedes_note_version_id, character_count, recorded_at, is_current}], next_cursor}`
ordered `version_number DESC`. No body and no digest; `content_sha256` is returned only by
`meetings.notes.read_version`. The page cap is 100: a `page_size` above it is
`invalid_request` / `page_size` (never clamped), an omitted one is 25, and the size used is
further bounded by the process `max_page_size`. An absent or foreign Meeting is `not_found`
/ `meeting_id`; an `after` that is not a note version of this Meeting is `invalid_request`
/ `cursor`.

**`meetings.notes.read_version`** — in `{meeting_id, note_version_id, include_body? = false}`;
out `{note: {note_version_id, meeting_id, version_number, supersedes_note_version_id, content_sha256, character_count, recorded_at, is_current, body_markdown (only when include_body)}, evidence_availability: "available"}`.
A note version that is not this Meeting's, or not this Principal's, is `not_found`, with
the one safe detail `note_version_id` for absent, foreign and wrong-Meeting alike (the
Meeting is not checked separately, so an absent Meeting answers the same).

### 7.3 Errors

| Situation | Code / safe detail |
| --- | --- |
| schema, type, bound, unknown field, wrong prefix, matrix miss, evidence rule miss, digest/passage mismatch, no-op change | `invalid_request` / the field (`relation_type`, `evidence_anchors`, `member`, `endpoint`, `expected_version`, …) |
| absent, other-Principal or wrong-parent record, note version, Issue or link | `not_found` / the subject |
| missing grant/purpose, or attested write without attestation | `denied` |
| stale `expected_version`/`expected_revision`/`expected_membership_revision`, key reused with another digest, Project link already active | `conflict` |
| deadlock or serialization failure on the lineage side | `conflict` (`after_refresh`), via `TransactionConflictError` |
| switch off (section 7.5) | `unsupported` |
| archived or withdrawn Capture root behind an endpoint or anchor | `denied` / `capture_withdrawn` (the Work-evidence idiom) |

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
- **As implemented (I4):** `recordId` must carry the family's prefix (`tsk`, `cmt`,
  `cst`), `meetingId` `mtg` and `noteVersionId` `mnote`, and `issueId` must match
  `^sit_[A-Za-z0-9]{8,64}$`; each is otherwise a local `invalid_request` without a gateway
  call. `includeBody` is required (`strictQuery`). After the strict decode, each route
  applies a **projection guard**: a lineage answer whose `root` is not the requested
  record, or a note answer for another Meeting or note version, or one carrying
  `body_markdown` when `includeBody` was not `true`, is refused as
  `upstream_contract_invalid` (503, `unavailable`) rather than passed on. The browser
  client (`fetchRelatedIssues` / `fetchNoteVersion`) decodes the route's result **strictly
  again**, so a route that drifted from the contract fails closed in the client too.
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
  - each evidence anchor, as "Meeting note version *n*, characters *start*–*end*" (or "Capture version *n*", or "Capture, version not recorded" for a legacy root, with "Capture archived" appended when `availability` is `archived`), from `source_version_no` and the offsets in the view. A
    button opens the note-version read in an inline disclosure; the body appears only
    after that explicit action. Once open, the cited passage (the anchor's offsets
    applied to the returned body as Unicode code points, as the server counts them) is
    shown first as "Cited passage", then the whole note version text.
- **Several Issues** (`unresolved_ambiguity`): the candidates (title, state) as a
  labelled radio group. Choosing one re-queries with `issueId`. No Issue is chosen for
  the user. The radio group **stays visible** after a choice (its legend drops the
  "Choose one" prompt) whenever the answer still lists more than one candidate; while
  the re-query is in flight the group stays mounted with a "Reading related Issues…"
  status (the previous Issue's edges are hidden), so the chosen radio keeps its focus
  and checked state.
- **No match:** "No related Issue is recorded for this record."
- **Incomplete or failed reads:**
  - `partial_native_history`: "Some related records could not be shown."
  - `truncated_budget`: "Only part of this record's lineage is shown."
  - a gateway `not_found`, `denied` or `unavailable`: "Related Issues are unavailable."
  - `unsupported` (switch off): the panel is not rendered at all.
  - never a count of what is hidden.
- **Accessibility:** a `section` with a heading, the choices as a radio group, the
  disclosure as a button with `aria-expanded`, usable at phone width, and no state
  conveyed by colour alone.

### 7.5 Admission switch (F03)

- **Setting:** `lineage_enabled: bool = False` in `bootstrap/settings.py`, env
  `MY_PA_LINEAGE_ENABLED` (the `MY_PA_` prefix; unknown or unparseable values fail closed
  as every setting does). Default **off**.
- **Composition:** `bootstrap/gateway.py` passes `lineage_enabled=settings.lineage_enabled`
  to `ApplicationService`, next to `knowledge_assertions_enabled`. No dependency on another
  switch.
- **Off:** `available_capabilities()` subtracts all 14 S1 names (a new
  `_LINEAGE_CAPABILITIES` set), exactly as it subtracts `_KNOWLEDGE_ASSERTION_CAPABILITIES`,
  so they are absent from `capabilities.get`, readiness's implemented set, the MCP tool list
  and the ChatLLM profile. An invocation of any of them — read or write — answers
  `unsupported` and writes nothing. **The invocation guard is the handler floor**: as for
  every other switched plane in `application/service.py`, `available_capabilities`
  governs publication and the manifest, not dispatch, so each S1 handler checks the
  switch first (`_lineage_plane`), before authority, reservation or a replay lookup — a
  byte-identical replay of a write committed while the switch was on answers
  `unsupported` (I5 prove-red: removing one handler's check reddens
  `test_switch_off_answers_unsupported_even_for_a_committed_replay`). The section 8 refusal of Issue
  `situation_id` references stays on whatever the switch says (an Issue created while on
  must not become a Work hint after it is turned off).
- **On:** the 14 names are served subject to the ordinary grant, purpose and section 6.1
  rules. Turning the switch on or off changes no row; the schema is present and dormant
  either way.
- Docs: `ops/runbooks/gateway-operations.md` gains the variable beside
  `MY_PA_KNOWLEDGE_ASSERTIONS_ENABLED`.
- **Test environments:** the e2e stack harness `web/e2e/stack.sh` sets
  `MY_PA_LINEAGE_ENABLED=true` beside `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED=true`, so
  the playwright rows of section 10 run with the plane on; BFF and component vitest
  tests mock the gateway and need no variable; Python database tests compose the service
  with `lineage_enabled=True` explicitly, except the switch-off tests.

## 8. Old-client compatibility rule (v1)

S1 adds capabilities and changes **no** existing request or response, so no version
negotiation is introduced. `continuity.situations` and `continuity.situations.create`
keep their exact keys and shape. **Selection rule (F22):** `continuity.situations`
selects context Situations only — Issue-kind Situations are excluded from its result
(the site is the shared `SqlSituationRepository.list_situations`, whose port docstring
in `contracts/ports.py` states it selects `kind = 'context'`; the frames/traces/work
workspace beside it is unchanged). Because `context.prepare`'s continuity gather
(`application/context/providers.py`) reads the same method, its Situation evidence also
excludes Issues, with its shape unchanged; `derive_pulse` needs no change (it joins
`frames`, and `enter_frame` refuses Issues), so the listing never offers a value the section 8 writers refuse. Context
Situations are listed exactly as before. Issues are reached through `issues.list` and
`issues.read`; `meetings.read`'s `MeetingNoteView` keeps omitting
`content_sha256`; `tasks.create`/`commitments.create` keep the `cap_`/`asrt_`
`origin_evidence_ref` rule and still refuse `mnote_`;

**Issue `situation_id` refusal (F04).** The existing writers that accept a client
`situation_id` — `tasks.create` (`CreateTask`), `commitments.create` (`CreateCommitment`),
`continuity.tasks.create` (`RecordTask`) — and the Relationship Memory writers that accept
`context_links` with `target_type = situation` — `relationship_memory.create`,
`relationship_memory.revise`, `relationship_memory.propose` — refuse a `sit_` whose
Situation has `kind = 'issue_workstream'` with `invalid_request` / `situation_id` (the
existing `SafeDetail.SITUATION_ID`; for memory, the existing context-link detail). The
lookup is Principal-scoped, so a foreign or absent `sit_` keeps answering exactly what it
answers today. Context Situations behave as before, so no existing request changes
meaning; the only new refusal names an object that did not exist before S1. The internal
`SituationService` frame/decision writers are unreachable from any capability and refuse
Issues in their repository methods (section 9). Native Issue association therefore has one
route, the attested ledger. Conversation pins (`_PIN_KINDS` admits `IdKind.SITUATION`,
`application/commands.py`) may still pin an Issue: a pin is a context-preference
bookmark, not an association, and no lineage read or later backfill treats it as one.

For the web client, `web/src/contracts/gateway.json`
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
`SqlProjectRepository.link_situation` refuse an Issue (`kind = issue_workstream`), as do
`enter_frame` and `propose_decision`. The section 8 writers gain one Principal-scoped kind
check each. `bootstrap/settings.py` and `bootstrap/gateway.py` gain the section 7.5
switch. **Head rebuild parity:** `infrastructure/persistence/record_lineage.py` exposes
the read-only `rebuild_link_heads(connection, context) -> tuple[LinkHeadRow, ...]`,
which derives every head from roots and revisions; the parity test compares it with
`record_link_heads`. A mismatch is a defect to report: the head table admits no in-place
repair, so repair is an operator-gated migration.
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
| AT-001 (stages 1–3 + reverse roots) | `tests/integration/test_issue_lineage_s1_vertical.py` | `test_m1_alone_creates_no_link`; `test_c1_originates_from_an_exact_n1_passage`; `test_reverse_read_from_m1_n1_c1_and_issue_yields_one_graph` (the section 7.2 fixture); `test_m1_reaches_c1_through_the_pair_set_without_an_m1_membership`; `test_a_link_scoped_to_another_issue_is_not_followed_from_the_pair`; `test_n1b_does_not_retarget_c1`; `test_a_meeting_in_two_issues_requires_an_issue_choice` | database |
| AT-002 | `tests/database/test_meeting_note_lineage_asof.py` | `test_origin_anchor_survives_a_later_note_replace`; `test_origin_anchor_survives_a_later_note_append`; `test_read_version_returns_the_original_body_and_digest`; `test_versions_list_carries_no_body_or_digest`; `test_a_digest_of_the_newer_note_is_refused_for_the_older_version` | database |
| AT-003 | `tests/integration/test_work_evidence_note_version.py` | `test_an_exact_note_passage_is_admitted_as_origin_evidence`; `test_a_note_version_under_another_meeting_is_not_found`; `test_a_spoofed_source_digest_is_refused`; `test_a_spoofed_passage_digest_is_refused`; `test_a_passage_outside_the_body_is_refused`; `test_a_hash_of_the_normalized_passage_is_refused`; `test_a_foreign_principal_note_is_not_found`; `test_a_refused_evidence_write_leaves_no_row_or_request`; `test_legacy_work_origin_evidence_ref_is_unchanged`; `test_an_exact_capture_version_passage_is_admitted_as_origin_evidence`; `test_a_capture_version_under_another_capture_is_not_found`; `test_a_spoofed_capture_digest_is_refused`; `test_an_archived_capture_root_is_capture_withdrawn`; `test_a_restricted_capture_version_is_refused`; `test_a_legacy_capture_root_is_admitted_only_as_corroboration`; `test_a_legacy_root_with_a_restricted_version_is_refused`; `test_an_anchor_reads_archived_after_its_capture_is_archived`; `test_an_anchor_reads_available_again_after_restore`; `test_archive_and_restore_write_no_lineage_row`; `test_a_legacy_capture_root_never_satisfies_an_origin_rule`; `test_a_legacy_anchor_reads_as_legacy_unversioned`; `test_an_origin_anchor_on_a_sibling_note_version_is_refused`; `test_an_origin_needs_the_origin_role`; `test_a_whole_version_origin_is_refused`; `test_a_discussion_anchor_on_another_meetings_note_is_refused`; `test_a_discusses_context_other_than_its_issue_is_refused`; `test_a_correction_must_keep_its_relation_rule` | database |
| AT-004 | `tests/database/test_lineage_revision_evidence.py` | `test_each_revision_reads_its_own_evidence_set`; `test_the_stored_digest_rebuilds_from_stored_rows`; `test_evidence_cannot_be_added_to_a_committed_revision`; `test_identical_evidence_has_one_digest_across_revisions`; `test_a_mixed_note_capture_and_legacy_set_rebuilds_its_digest`; `test_the_same_anchor_twice_in_one_set_is_refused`; `test_overlapping_anchor_reuse_in_two_transactions_does_not_deadlock`; `test_no_view_carries_the_evidence_set_digest` | database |
| AT-004 / AT-010 (encodings) | `tests/unit/test_lineage_canonical.py` | `test_evidence_set_digest_golden_vectors`; `test_request_digest_golden_vectors`; `test_normalized_identity_golden_vectors`; `test_anchor_order_is_total_with_nulls_first`; `test_passage_hash_counts_code_points_not_bytes_or_graphemes`; `test_request_digest_does_not_nfc_normalize`; `test_anchor_identity_excludes_role` | FAST |
| AT-004 / AT-012 (SQL parity) | `tests/database/test_lineage_canonical_sql_parity.py` | `test_sql_link_identity_matches_the_golden_vectors`; `test_sql_anchor_identity_matches_the_golden_vectors`; `test_a_non_canonical_link_identity_is_refused`; `test_a_non_canonical_anchor_identity_is_refused` | database |
| AT-009 | `tests/security/test_lineage_reference_isolation.py` | `test_absent_and_foreign_endpoints_answer_alike`; `test_a_context_situation_is_not_an_issue_endpoint`; `test_a_wrong_parent_note_version_is_not_found`; `test_an_archived_task_is_not_linkable`; `test_a_foreign_issue_context_is_not_found`; `test_a_lineage_read_of_a_foreign_root_is_not_found`; `test_a_linked_native_record_cannot_be_deleted`; `test_no_row_is_written_for_a_refused_reference`; `test_a_foreign_archived_task_answers_not_found`; `test_a_foreign_context_situation_answers_not_found`; `test_read_version_of_a_foreign_note_is_not_found`; `test_read_version_under_the_wrong_meeting_is_not_found`; `test_a_foreign_capture_root_anchor_is_not_found`; `test_a_link_id_of_the_other_kind_is_invalid_request` | database |
| AT-010 | `tests/concurrency/test_lineage_idempotency.py` | `test_identical_replay_returns_one_root_revision_and_request`; `test_same_key_different_payload_is_conflict`; `test_distinct_keys_same_identity_return_the_existing_association`; `test_a_duplicate_assert_never_changes_authority`; `test_concurrent_identical_asserts_create_one_active_head`; `test_a_stale_expected_revision_is_conflict`; `test_concurrent_issue_updates_admit_one`; `test_concurrent_project_link_adds_admit_one`; `test_a_replay_rebuilds_the_original_response_after_the_link_moved_on`; `test_a_replay_reports_the_recorded_created_flag`; `test_nfd_and_nfc_titles_under_one_key_conflict`; `test_a_stale_expected_revision_on_an_active_link_is_conflict`; `test_concurrent_corrects_with_one_expected_revision_admit_one`; `test_a_correction_to_the_same_evidence_is_refused` | database |
| AT-012 (races, two connections) | `tests/concurrency/test_lineage_endpoint_races.py` | `test_a_native_delete_waiting_on_an_assert_is_refused_after_the_assert_commits`; `test_an_assert_waiting_on_a_native_delete_answers_not_found_after_the_delete_commits`; `test_an_assert_proceeds_after_a_native_delete_rolls_back`; `test_task_archive_racing_a_membership_add_serializes` (`tasks.update` with `archived: true`, the repository's archive route, vs `issues.memberships.add`; either one membership plus a later archive, or `invalid_request` / `endpoint` and no rows); `test_capture_archive_racing_a_capture_anchor_serializes`; `test_a_lineage_deadlock_answers_conflict_and_writes_nothing`; `test_the_native_side_of_a_lineage_deadlock_is_recorded` (residual pin, section 6.2) | database |
| AT-012 | `tests/database/test_lineage_integrity_guards.py` | `test_immutable_lineage_tables_refuse_update_and_delete` (parametrized, 6 tables); `test_lineage_tables_refuse_truncate` (8 tables, each holding a row); `test_a_head_admits_only_the_next_revision`; `test_a_head_cannot_lag_its_revisions_at_commit`; `test_a_write_request_completes_once`; `test_a_write_request_is_never_committed_reserved`; `test_an_issue_cannot_change_without_a_matching_revision`; `test_a_situation_kind_is_fixed`; `test_cross_principal_foreign_keys_refuse`; `test_an_anchor_binds_the_note_digest_and_parent`; `test_an_anchor_binds_the_capture_version_digest_and_parent`; `test_an_anchor_binds_exactly_its_family`; `test_attested_tables_refuse_a_non_local_operator_row`; `test_the_anchor_trigger_verifies_the_passage`; `test_rebuilt_heads_equal_stored_heads` (calls `rebuild_link_heads`) | database |
| AT-012 (migration) | `tests/schema/test_record_lineage_s1_migration.py` | FAST: `test_the_revision_is_the_single_head_on_b9025e7fb738`; `test_the_revision_imports_no_domain_module`; `test_frozen_ddl_names_every_declared_constraint`; `test_before_vocabulary_is_a_byte_copy`; `test_at_vocabulary_adds_exactly_the_s1_names`; `test_offline_downgrade_refuses_first`. DB: `test_empty_to_head` (`migration_empty_to_head`); `test_previous_head_with_rows_upgrades`, `test_upgrade_refuses_a_cross_principal_project_situation`, `test_existing_situations_and_project_links_survive_unchanged`, `test_capture_versions_gain_only_the_digest_unique` (also asserts the `tables.py` declaration does not carry it and that `1a4c9e77b2d5` emits byte-identical offline DDL before and after S1), `test_downgrade_refuses_while_lineage_rows_exist` (`migration`) | FAST + migration markers |
| AT-023 (S1) | `tests/contract/test_lineage_capability_admission.py` | `test_s1_capabilities_are_operator_decision_required`; `test_no_s1_capability_is_in_the_chatllm_data_profile`; `test_s1_requests_reject_server_owned_fields`; `test_existing_v1_shapes_are_unchanged`; `test_continuity_situations_keeps_exactly_the_old_keys`; `test_continuity_situations_excludes_issues_and_keeps_contexts`; `test_context_prepare_returns_no_issue_situation_id`; `test_switch_off_withholds_every_s1_capability`; `test_note_body_needs_the_history_purpose`; `test_lineage_authority_ignores_the_knowledge_manager_allowlist` | FAST |
| AT-023 (S1, DB) | `tests/database/test_lineage_attested_writes.py` | `test_an_ordinary_remote_client_is_denied_accepted_lineage_writes`; `test_a_local_operator_write_records_its_class_and_channel`; `test_an_operator_review_client_cannot_call_any_s1_write`; `test_a_replayed_attested_write_from_an_ordinary_client_is_denied_before_the_replay_lookup`; `test_switch_off_answers_unsupported_and_writes_nothing`; `test_work_and_memory_writers_refuse_an_issue_situation_id`; `test_work_writers_still_accept_a_context_situation_id`; `test_a_foreign_issue_situation_id_answers_as_before`; `test_frame_and_project_link_writers_refuse_an_issue` | database |
| AT-024 (S1, server) | `tests/contract/test_lineage_read_contract.py` | `test_edges_carry_relation_direction_basis_and_evidence`; `test_reads_carry_no_body_or_hidden_count_and_only_issue_titles`; `test_views_carry_no_source_or_passage_digest`; `test_anchor_views_carry_the_server_derived_version_number`; `test_completeness_is_stated_even_with_a_null_cursor` | FAST |
| AT-024 (S1, web component) | `web/src/components/work/related-issues.test.tsx` | `renders the related Issue with relation, direction, basis and actor class`; `lists candidate Issues as a radio group and re-queries with the chosen issueId`; `shows the empty message when no Issue matches`; `shows the partial and truncated messages without hidden counts`; `shows the unavailable message on not_found, denied and unavailable`; `opens a note-version anchor only on explicit action`; `labels a legacy capture anchor as version not recorded`; `labels an archived capture anchor as capture archived`; `renders nothing when the capability is unsupported`; `issues exactly one lineage request per render` | vitest |
| AT-024 (S1, mounting) | `web/src/components/work/work-detail.related-issues.test.tsx`; `web/src/app/(app)/work/projects/[projectId]/constraints/constraint-inspector.related-issues.test.tsx` | `mounts the related-Issue panel on the Task detail`; `mounts the related-Issue panel on the Commitment detail`; `mounts the related-Issue panel in the Constraint inspector` | vitest |
| AT-024 (S1, browser) | `web/e2e/lineage-related-issues.spec.ts` | `related Issues on a Task are keyboard reachable and readable at phone width`; `an ambiguous record asks for an Issue before showing lineage` | playwright (own `npm run e2e`, seeded synthetic data) |
| AT-023 (S1, BFF) | `web/src/app/api/records/related-issues-route.test.ts`; `web/src/app/api/meetings/note-version-route.test.ts` | `calls records.lineage once with origin and max_depth 1`; `refuses a family outside task, commitment and constraint without a gateway call`; `refuses unknown query fields`; `calls meetings.notes.read_version only with an explicit includeBody` | vitest |
| AT-023 (S1, strict client) | `web/src/lib/api/decode/capabilities/records.lineage.test.ts`; `web/src/lib/api/decode/capabilities/meetings.notes.read_version.test.ts`; existing `web/src/lib/api/decode/registry.test.ts`; existing `tests/contract/test_bff_gateway_contract_parity.py`, `tests/contract/test_bff_success_decoder_parity.py` | `decodes the S1 lineage response`; `refuses an unknown key`; `decodes a note version with and without a body`; the existing registry and parity tests stay green with exactly two new entries and every existing entry unchanged | vitest + FAST |
| AT-026 (S1) | existing `tests/database/test_record_event_provenance.py` | existing `test_unknown_foreign_withheld_and_non_knowledge_events_answer_alike` (must stay green, unchanged) | database |
| AT-026 (S1) | `tests/architecture/test_record_lineage_s1_scope.py` | `test_s1_adds_no_record_event_family`; `test_every_s1_crosswalk_test_exists` (parses this table: Python rows by function name, vitest/playwright rows by test title) | FAST |
| AT-009 / AT-023 / AT-002 (I5 hardening, extras) | `tests/security/test_lineage_reference_isolation.py`; `tests/database/test_lineage_attested_writes.py`; `tests/database/test_meeting_note_lineage_asof.py` | `test_every_s1_capability_answers_a_foreign_subject_like_an_absent_one`; `test_no_s1_answer_carries_a_source_digest_or_body_except_read_version`; `test_every_replayed_attested_write_is_denied_before_the_replay_lookup`; `test_switch_off_answers_unsupported_even_for_a_committed_replay`; `test_versions_list_defaults_to_twenty_five_per_page` | database |
| (domain, unmapped) | `tests/unit/test_issue_lifecycle.py` | `test_allowed_state_moves`; `test_refused_state_moves`; `test_update_action_follows_the_state_move` | FAST |

**Not S1:** AT-001 stages 4–14 and AT-005, AT-006 (full), AT-007, AT-017 → S2;
AT-008, AT-011, AT-013, AT-014, AT-016, AT-024 Meeting view, timeline and graph, AT-025, AT-001 full
reverse-root equivalence → S3; AT-015, AT-018, AT-019, AT-022, AT-023 Commitment v2 →
Program/report work packages; AT-020, AT-021 → out of scope until OD-06.
The S2 tests are bound in the [S2 contract](record-lineage-s2-contract.md) section 10,
and the S3 tests in the [S3 contract](record-lineage-s3-contract.md) section 10, not in
this table.

## 11. Deferred work and its owner slice

| Item | Slice |
| --- | --- |
| `issues.close`/`reopen` with closure evidence and mandatory-member gate; `closed`/`reopened`/`corrected` actions | S2 |
| `delegated_from`, `escalated_from`, `blocks` (with type-specific cycle refusal), `created_to_resolve`, `related_context`; `contest`/`reinstate` link revisions | S2 |
| Managed Document version and Knowledge Assertion evidence; restricted-classification Capture evidence with remote withholding | S2 / S3 |
| Composite Work/Meeting/Constraint writes with `association_intents` (CR-006), responsibility/handoff (`ihnd`) | S2 |
| `issues.history`, `records.associations.history`, `records.associations.list_for_record`, `known_at`/`valid_at`, version selectors, cursors with grant-bound continuation, other native virtual edges, timeline, `explain_paths` | S3 |
| `records.associations.propose`/`review`, proposal roots/decisions/heads (`irp`, `ldec`) | S3 |
| Record Event family for lineage, `link_mutation_event_receipts` (`irec`) | S3 |
| Lineage runtime-role provisioning and privilege gate (closes the owner `DISABLE TRIGGER` gap) | CR-014 follow-up, operator-gated |
| A remote attested lineage writer (own allowlist, settings key, ADR-015 amendment) | not scheduled; needs an operator decision |
| Routing native writers through `is_transaction_conflict` (section 6.2 residual) | separate work package |
| Meeting record view and its related-Issue display; Issue pages, timeline and graph (WP-06A S3 stage) | S3 |
| Backfill/dry-run (WP-03B), Program, report manifest, finance, P6 | own work packages; finance/P6 gated by OD-06 |

The S2 rows above are specified by the [S2 contract](record-lineage-s2-contract.md),
which narrows them: S2 admits `delegated_from`, `escalated_from`, `blocks` and
`created_to_resolve`, and moves `related_context` and `contest`/`reinstate` to S3; the
composite writes are `issues.work.create_task` and `issues.work.create_commitment` (no
composite Constraint create); restricted-classification evidence stays S3 (S2
contract sections 11 and 12). The S3 rows are specified by the
[S3 contract](record-lineage-s3-contract.md), which builds `issues.history`,
`records.associations.history`, `known_at` / `valid_at` reads and grant-bound cursors on
`records.lineage`, `issues.timeline`, `related_context`, `contest` / `reinstate`, the
WP-03B backfill dry run (no link materialized) and the WP-06A Issue and Meeting views, and carries proposals and review,
the lineage Record Event family, `list_for_record`, version selectors and the other
native virtual edges (S3 contract sections 11 and 12).

## 12. W1 divergences — resolution

| W1 §7 | Resolution |
| --- | --- |
| 1 `ires` collides | S2 handoff uses `ihnd`; S1 prefixes in section 2 |
| 2 no Situation composite unique | added (section 4.1), plus the kind-bearing unique |
| 3 `project_situations` has no live writer | `issues.project_links.*` become its only Issue writer; legacy repository paths refuse Issues; existing rows validated, never repaired, unread by S1 |
| 4 no Situation Record Event | S1 adds no family; revisions are the receipts; S3 owns events |
| 5 composite column order | every new FK lists the referenced unique's order (`situations`, `projects`, `meeting_note_versions`, `record_links` as written above) |
| 6 `capture_versions` | S1 evidence family: additive digest-bearing unique, RESTRICT anchor FK, CASCADE left unchanged (section 4.1) |
| 7 `asrt_` vs `kasr_` | `knowledge_assertion` = `kasr_`; `asrt_` stays Work-only and is not lineage evidence |
| 8 `meetings.read` omits digest | unchanged; only `meetings.notes.read_version` exposes it |
| 9 no common lock helper | section 6.2 order; `FOR SHARE` is honoured by every native writer; deadlocks remain possible and are mapped (lineage side) or pinned as a residual (native side); W1's advisory inventory is corrected in 6.2 |
| 10 TRUNCATE/roles only for Record Events | TRUNCATE refusal on all 8 tables in S1; roles deferred |
| 11 `reports.types.*` | not S1 |
| 12 AT-026 Capture case exists | existing test bound; no duplicate module |
| 13 07 id pattern | `IdKind` validation, 72-character cap |
| 14 anchors | informational |

Further package corrections made here: error codes are the repository's (ADR-015
decision 14); idempotency is scoped `(principal, capability, key)` as in Meetings, not
by `client_scope`; `issues.list`/`meetings.notes.versions` use `after`/`next_cursor` as
in `meetings.list`; Project link and membership writes do not bump the Issue version and
use their own revision CAS; Project link evidence is optional (an explicit attested
local-operator assertion is the authority; anchors are additional); the anchor binding is inline columns
with a digest-bearing composite FK rather than a separate binding table; the package's
`hidden_node_count` is omitted because hidden counts must not be disclosed. The WP-06A S1 display covers the Task, Commitment and Constraint
views only, because `web/` has no Meeting record view to extend; `records.lineage`
returns Issue titles (and only Issue titles) so the display needs no per-Issue read.

R1 review corrections (`reviews/R1-g0-review.md`), with the plan cards they touch:

- **Attested writes are local-operator only** (F01); the package's remote attested path is
  not reachable without a new allowlist and is not built.
- **WP-02A Capture evidence is in S1** (F02), as plan 03 places it; no S1 scope is narrowed.
- **WP-01B "digest plus canonical bytes comparison"** (F10): S1 stores the request digest
  only and does not NFC-normalize it, matching Meetings; equal digests are treated as equal
  canonical bytes under SHA-256, exactly as `meeting_write_requests` does.
- **WP-01C card lists `close`/`reopen`/`history` in S1** (F17); this contract follows plan 03
  §2 (line 58), which puts closure in S2 and history in S3, because the closure gate needs
  S2's mandatory-member and Constraint rules.
- **CR-015 minimal UX includes an Issue detail, and `web/src/app/(app)/situations` exists**
  (F17); S1 shows Issues only inside record views, and Issue pages are S3, because an
  Issue page without close/reopen/history would expose an incomplete lifecycle.
- **Package "deadlock ⇒ retry"**: the repository maps a lost race to `conflict`
  (`after_refresh`), not `unavailable`; S1 follows the repository (F14).
- **Digest disclosure** (F11): digests are withheld from metadata views; the package's
  views carried them.
- **The stored evidence-set digest is withheld too** (FR1-F05): section 7.1 first kept
  `evidence_set_digest` on `AssociationView`; it is over the withheld digests and the
  shown anchor fields, so it would confirm a guessed low-entropy body. It stays stored,
  rebuilt and parity-tested.
- **The Relationship Memory refusal of an Issue holds only because memory validates
  Entity targets alone** (FR1-F07): section 8 says the memory writers refuse an Issue
  `situation_id` with the existing context-link detail. They gained no kind check; an
  Issue target is refused today because every Situation target is (the test asserts
  the Issue and context answers are identical). A later change that admits Situation
  targets in memory `context_links` must add the Issue-kind refusal at the same time.

## 13. Operator gates that remain

Ratification of ADR-015 beyond the directive defaults; any live migration, grant,
ChatLLM or client exposure, deployment or backfill (OD-07); source commissioning for
finance and P6 (OD-06); runtime-role provisioning; and any closure-exception or
completeness-threshold risk acceptance (OD-03, OD-08). Nothing else in S1 is left for a
worker to decide beyond local naming that has no incumbent constraint.
