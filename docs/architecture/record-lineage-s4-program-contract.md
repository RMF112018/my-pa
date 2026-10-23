# Record lineage — Slice S4 Program reporting implementation contract

**Status:** proposed implementation contract under
[ADR-015](../decisions/ADR-015-record-lineage-and-issue-situations.md) (Proposed —
accepted by directive defaults; architecture/test-isolated scope only). It is the
single document S4 implementers code against, on top of the
[S1](record-lineage-s1-contract.md), [S2](record-lineage-s2-contract.md) and
[S3](record-lineage-s3-contract.md) contracts as implemented. It authorizes no migration
run, grant, deployment, client exposure, certified Program total or production use.
Where it differs from the review package (`MYPA-LINEAGE-ADVERSARIAL-REVIEW-20261017-001`,
documents 02, 03, 04, 06 and 07), this document controls for S4 and section 12 records
why.

**Basis:** `feat/lineage-s4-program@96cd60685baf1a172f22556d00817f5df4aa3ac3`
(tree `fa7e416a83d67284b0801e5f59f04189d780bbee`, identical to the reviewed S3 head
`75707a8b`); Alembic single head `6f1476b8da52` (121 revisions); 222 `Capability`
members, 59 `Purpose` members, 150 `IdKind` members, 233 audit-vocabulary capability
names, 30 lineage capabilities behind `MY_PA_LINEAGE_ENABLED`, 110 `gateway.json`
entries. "S1 §n", "S2 §n" and "S3 §n" cite the earlier contracts. Paths under `src/`
are relative to `src/my_pa/`.

All counts in this file are digits on purpose (spelled-count guard).

## 1. What S4 is

S4 is the Program-reporting slice: package work packages WP-04A, WP-04B and WP-04C
(CR-009, CR-010, CR-013, the S4 part of CR-015). After S4 an operator can name one or
more Program Entities and get, from **one database snapshot**, the exact set of
Continuity Projects that are members of each Program — derived only from typed
`member_of` edges and the Project↔Entity bridge, never from names — and the operational
position of those Projects (Commitments, Issues, Constraints) with distinct-count
Program totals that are reported only when they are complete enough to be reported
(OD-08), and otherwise say why, with the denominator in view. A report committed to the
Intelligence plane gets a separately hashed, immutable manifest that binds everything
the Markdown digest does not.

**In S4:**

- **WP-04A** — `programs.members.resolve` (section 7.1): the exact resolver of
  section 3.1, current or at a stated `valid_at`, with `historical_membership_unverified`
  for edges whose recorded dates cannot prove membership at that instant; redirects
  followed, missing and ambiguous bridges surfaced, overlapping Programs reported and
  deduplicated at portfolio grain.
- **WP-04B** — `programs.overview` (section 7.2): the server-batched metrics of section
  3.2 for every resolved Project, per Project, per Program and per portfolio, from one
  `REPEATABLE READ READ ONLY` snapshot (section 6.3), with the reportability rules of
  section 3.3; and `commitments.v2.read`, `commitments.v2.list`, `commitments.v2.search`
  and `commitments.v2.waiting_on` (section 7.3): the 4 v1 Commitment reads with
  `project_id`, `situation_id`, an optional `project_ids` filter and batched statements,
  as **sibling capabilities** — the 4 v1 names, their request schemas and their answers
  stay byte-identical.
- **WP-04C** — `knowledge.intelligence_artifact_manifests` (section 4.1): every
  artifact committed after the S4 revision gets one immutable canonical manifest
  (section 5.3), hashed separately from the unchanged Markdown digest; a report may
  reference a Program overview it was written from (section 5.4); at commit the server
  recomputes that overview for the committing caller and the manifest binds the
  server's membership set, versions, cutoff, completeness and totals as that caller
  sees them, with the verification outcome (uncertified: certification stays
  OD-08-gated); `reports.manifest` (section 7.4) reads it, and a report
  committed before the revision answers `manifest_unavailable_legacy` without any write.
- AT-015, AT-018, AT-019, AT-022, the S4 part of AT-023, with AT-026 as a regression
  (section 10).

**Not in S4** (section 11 lists the owner): finance, CPM, ERP and P6 (OD-06, S5); any
web view or `gateway.json` entry (WP-06B); Task metrics and a responsibility queue in
the Program overview; a past-dated (`as_of`) Program overview; knowledge-time
(`known_at`) Program membership; verified Commitment acceptance; any certified Program
total; any change to an attestation path (S3.1 is held on an operator rule).

## 2. Identifier kinds

**No new `IdKind` member.** A manifest is keyed by its artifact (`rpt_`); a Program read
persists nothing. Existing kinds used by S4: `ent` (Program and Project Entities),
`erel` (entity relationships — the `IdKind.ENTITY_RELATIONSHIP` prefix as it stands),
`prj`, `cmt`, `sit`, `cst`, `tsk` (a follow-up Task in `waiting_on`), `rpt`, `prn`.

## 3. Closed vocabularies and rules

New module `domain/program/vocabulary.py` (pure; no import from `domain/lineage` except
`canonical.py`, section 5). `domain/lineage/vocabulary.py` is **unchanged**: Program
answers are not lineage reads, so `LineageCompleteness` does not gain the
`not_reportable` / `source_not_integrated` members S3 §3 listed as "Program work"
(section 12, D-13).

| Vocabulary | Members |
| --- | --- |
| `MembershipMode` | `current`, `historical` |
| `MemberUnresolvedReason` | `bridge_missing`, `bridge_ambiguous`, `redirect_unresolvable` |
| `MemberUnverifiedReason` | `start_not_recorded`, `end_not_recorded` |
| `ProgramCompleteness` | `complete`, `historical_membership_unverified`, `membership_unresolved`, `truncated_budget`, `restricted_evidence` |
| `MetricGrain` | `commitment`, `issue`, `constraint` |
| `MetricValueState` | `reported`, `not_reportable`, `restricted` |
| `NotReportableReason` | `membership_unresolved`, `membership_truncated`, `acceptance_unverified`, `issue_link_unverified`, `calendar_unconfigured`, `never_synced`, `sync_unverified`, `sync_degraded`, `sync_conflict` |
| `ConstraintSourceState` | `in_sync`, `never_synced`, `unverified`, `sync_degraded`, `conflict`, `calendar_unconfigured` |
| `AcceptanceVerification` | `unverified_review_reference`, `not_accepted` |
| `ReferenceState` | `owned`, `none`, `not_owned`, `restricted` |
| `ProgramVerificationState` (manifest) | `verified_at_commit`, `changed_since_read`, `recompute_failed`, `not_attempted` |
| `RecomputeFailure` (manifest) | `budget_exceeded`, `statement_timeout`, `pool_unavailable`, `program_not_found`, `program_invalid` |
| `ManifestState` (read) | `recorded`, `manifest_unavailable_legacy`, `restricted_evidence` |
| `CandidateStatus` (manifest) | `unaccepted_candidate`, `not_a_candidate` |

`ProgramCompleteness` precedence (one `complete_state`, every applicable code in
`qualifiers`, `qualifiers[0]` is the `complete_state`, S3 D-36): `truncated_budget` >
`membership_unresolved` > `historical_membership_unverified` > `restricted_evidence` >
`complete`.

Constants: `PROGRAM_METRIC_SCHEMA_VERSION = 1`; `PROGRAM_CALCULATION_VERSION =
"program-overview-v1"`; `MAX_PROGRAMS_PER_REQUEST = 10`; `MAX_PROGRAM_PROJECTS = 100`
(the union over the request; `MAX_PORTFOLIO_PROJECTS` precedent); `MAX_MEMBER_EDGES = 400`
(edges scanned per request, the S3 edge budget's scale); `MAX_REDIRECT_HOPS = 8`;
`MAX_PROJECT_FILTER = 100`; `REPORT_MANIFEST_SCHEMA_VERSION = 1`;
`PROGRAM_REFERENCE_BLOCK_KEY = "program_overview_ref"`;
`PROGRAM_REPORTING_CAPABILITIES` (the 7 names of section 7, as strings).

### 3.1 Program membership (WP-04A, CR-009)

Repository truth the rule is built on: `entities` (`entity_type` includes `program` and
`project`; `status = 'merged_redirect'` ⇔ `superseded_by_entity_id` non-null, the
redirect principal-composite); `entity_relationships` (directed, typed by the
`entity_relationship_types` table; `member_of` is seeded with **no** source or target
type, so types are checked here, not by the taxonomy; `state` `active` | `ended` |
`superseded`; `effective_from` / `effective_to` nullable, revised **in place** by
`entities.relationships.revise`; an `end` sets `state = 'ended'`, `ended_at` and
`effective_to` to now or to the requested end (the command requires exactly one), though
no CHECK forbids an `ended` row with a null `effective_to`; a merge **reparents** edges to
the survivor and supersedes a merge-created self-edge); `project_entity_links` (PK
`(principal_id, project_id)`, at most one `bound` row per `project_entity_id` per
Principal, `unresolved_*` rows carry **no** entity id, both foreign keys
principal-composite; a merge does **not** rewrite it).

**Algorithm** (per request, inside the section 6.3 snapshot; every statement
Principal-scoped):

1. **Program.** For each requested `program_entity_id`, the row of this Principal (else
   `not_found` / `program_entity_ids` — absent and foreign answer alike). Follow
   `superseded_by_entity_id` while `status = 'merged_redirect'`, at most
   `MAX_REDIRECT_HOPS`; more hops, or a revisit, is `conflict` / `program_entity_ids`.
   The terminal entity must be `entity_type = 'program'`, else `invalid_request` /
   `program_entity_ids`. Any non-redirect status is admitted and reported
   (`program_status`). Two requested ids with one terminal are both answered, each with
   `redirected`.
2. **Edges.** Every `entity_relationships` row with `relationship_type = 'member_of'`,
   `to_entity_id` = the terminal Program and `state <> 'superseded'` (a superseded edge
   was folded or replaced; its successor, if any, is its own row), ordered by
   `(terminal program, relationship_id COLLATE "C")`, at most `MAX_MEMBER_EDGES` over
   the request (beyond: `truncated_budget`, and nothing after the bound is read).
   `scope_entity_id` is ignored.
3. **Window.** With `t` = the evaluation instant (section 3.4):
   - **current mode** (no `valid_at`; `t` = `source_cutoff_at`): a member iff
     (`effective_from IS NULL` or `effective_from <= t`) and either `effective_to > t`
     (non-null), or `effective_to IS NULL` and `state = 'active'`. A null start is no
     obstacle here: the edge is recorded as currently in force. An `ended` edge whose
     recorded end is still in the future (`entities.relationships.end` admits a future
     `effective_end`) is a member until that end — current and historical mode apply
     the same window; historical mode additionally separates verified from unverified
     members (a null-start `active` edge is a current member and, historically,
     `start_not_recorded`); an `ended` edge with a null end is not a current member.
   - **historical mode** (`valid_at` given): not a member when `effective_from > t` or
     `effective_to <= t` (both non-null comparisons); otherwise a **verified** member iff
     `effective_from` is non-null and (`effective_to` is non-null or `state = 'active'`);
     otherwise **unverified**: `start_not_recorded` when `effective_from` is null, else
     `end_not_recorded` (an ended edge with no recorded end). An unverified edge is
     never in `members`; it is listed in `unverified_members` and sets
     `historical_membership_unverified`. No period is invented.
   - Edges outside the window are counted in `excluded.outside_window` (a count of the
     caller's own rows).
4. **Member entity.** The edge's `from_entity_id`, redirect-followed as in step 1;
   `redirect_unresolvable` when the chain fails. A terminal whose `entity_type <>
   'project'` is not a Project member: counted in `excluded.non_project_members`, never
   listed as a Project. This includes a **nested Program** (`program member_of
   program`): Programs are never expanded transitively. The member entity's own status
   (`active`, `inactive`, `historical`, `archived`) is admitted and reported as
   `member_entity_status`; a Project Entity is a member by its edge, not by its status.
5. **Bridge.** The `bound` `project_entity_links` rows whose `project_entity_id`
   redirect-resolves (step 1 rule) to the member terminal `E`. Exactly 1 ⇒ its
   `project_id`; 0 ⇒ `bridge_missing` (this includes a Project whose own bridge row is
   `unresolved_missing` or `unresolved_ambiguous`, since such a row names no entity);
   more than 1 (possible only through a merge: two bound rows naming `E` and an entity
   merged into `E`) ⇒ `bridge_ambiguous` — **no Project is chosen**. An unresolved
   member is listed in `unresolved_members` with its `relationship_id`,
   `member_entity_id` and reason, and sets `membership_unresolved`.
6. **Deduplicate.** One member per `(program, project_id)`, carrying every
   `relationship_id` that reached it (sorted). A Project reachable from 2 requested
   Programs is a member of each; the `portfolio` set holds it once and `overlaps` names
   its Programs. More than `MAX_PROGRAM_PROJECTS` distinct Projects over the request ⇒
   `truncated_budget`; members are kept in `project_id` order up to the bound.
   **Which scopes a budget marks:** Programs are processed in request order; the Program
   during which the edge or Project bound is reached and every later Program carry
   `truncated_budget` (their sets are incomplete), earlier Programs do not, and the
   portfolio carries it whenever any Program does.
   **Historical mode reads only edges historically**: redirects and bridges are read as
   currently recorded, which `membership_record: "current"` states for the whole
   resolution (edges, redirects and bridge).
7. **Never.** No name, alias, canonical-name, Organization, address, participation or
   property match; no manual Project list; no write of any kind (no reconciliation, no
   bridge repair).

### 3.2 Metric catalogue (WP-04B, CR-010)

`PROGRAM_METRIC_SCHEMA_VERSION = 1`. Every metric is a count of distinct identifiers of
its grain over the resolved Project set `P` of a scope (one Project, one Program, or
the portfolio), read in the section 6.3 snapshot at the cutoff `c`. "Accepted" is native
`evidence_state = 'accepted'`; "proposed" is `'proposed'`.

| `metric_id` | Grain | Definition (Principal-scoped; `p ∈ P`) | Across Projects |
| --- | --- | --- | --- |
| `commitment_open_accepted` | `commitment` | `commitments.state = 'open'`, accepted, `project_id = p` | additive (one `project_id` per row); total gated by `acceptance_unverified` |
| `commitment_open_proposed` | `commitment` | open, proposed, `project_id = p` | additive |
| `commitment_closed_proposed` | `commitment` | `state = 'closed'`, proposed, `project_id = p` — reported so a closed proposal is never read as accepted | additive |
| `commitment_overdue_accepted` | `commitment` | open, accepted, `due_at < c` | additive; total gated by `acceptance_unverified` |
| `commitment_overdue_proposed` | `commitment` | open, proposed, `due_at < c` | additive |
| `commitment_unscheduled_accepted` | `commitment` | open, accepted, `due_at IS NULL` | additive; total gated by `acceptance_unverified` |
| `commitment_unscheduled_proposed` | `commitment` | open, proposed, `due_at IS NULL` | additive |
| `issue_outstanding` | `issue` | `situations.kind = 'issue_workstream'`, `state` ∈ `open`, `active`, `suspended` (a suspended Issue is outstanding — it is not closed — by decision), whose latest `issue_project_membership_events` row for `(p, issue)` is `active` | **nonadditive**: one Issue may impact several Projects |
| `constraint_open` | `constraint` | `project_constraints.lifecycle_state` ∈ the active states, `project_id = p` (the `constraints.portfolio_overview` `total_open`) | additive |
| `constraint_overdue` | `constraint` | active and `due_date < project_today(p)` on **p's own calendar** (`business_time.is_overdue`) | additive as a distinct count of Constraints, each classified on its own Project's calendar at the one cutoff instant (section 12, D-25) |
| `constraint_due_soon` | `constraint` | active and `project_today(p) <= due_date <= due_soon_through(project_today(p))` on p's calendar (the overview's `due_soon`) | as `constraint_overdue` |
| `constraint_in_my_court` | `constraint` | active with the Principal as native ball-in-court party (the overview's `in_my_court`) | additive |
| `constraint_draft` | `constraint` | `lifecycle_state = 'draft'`, `project_id = p` | additive |

- **Totals are `COUNT(DISTINCT id)` over the scope's Project set.** For the additive
  grains (each row names one `project_id`) the implementation may sum disjoint
  per-Project counts; the `issue` grain is computed over the set of `(project_id,
  situation_id)` pairs, so an Issue linked to 2 Projects of one Program counts once in
  that Program and once in the portfolio. A test pins every total equal to a direct
  `COUNT(DISTINCT …)` statement (section 10).
- **`nonadditive_across_projects`** is `true` exactly for `issue_outstanding`: a client
  that sums per-Project impact gets a number the answer says is not a total.
- **Commitment instants** (`due_at timestamptz`) compare with the cutoff instant; no
  Project calendar is involved. **Constraint dates** (`due_date date`) are classified on
  the Project's own calendar from `constraint_project_settings.timezone_name`, by
  `ConstraintReadService`'s portfolio path unchanged (PC-CM-RUN01-WP06): no calendar
  ⇒ no defensible overdue boundary ⇒ `calendar_unconfigured`, never a substitute zone.
- **No averages, no percentages, no sums of shared impact** (package plan §2). The
  Constraint overview's `average_open_age_business_days` is not carried.
- **Commitment Project attribution is the native `commitments.project_id`.** A
  Commitment reaches a Program only through its own Project field; an Issue membership
  never attributes a Commitment to a Project (the `issue` grain carries Issue impact).

### 3.3 Reportability (OD-08)

Default `NOT_REPORTABLE` on any material gap; per-Project figures stay visible with
their source state; **no zero is ever substituted**.

**Constraint source state, from the stored sync data (R4-F01).** The portfolio read
model's 3-way health (`_overview_of`: conflict / no target / `in_sync`) is **not** used
for reportability: it reads a Project with a registered but never-verified target, or
whose last run failed, as `in_sync`. S4 reads, in the snapshot and in one statement for
all Projects, every `constraint_sync_targets` row of the Project with its
`last_verified_at`, `last_run_id` and the `constraint_sync_runs.sync_state` of that last
run (the 10 persisted outcomes of `ConstraintSyncState`), plus the open-conflict counts
`portfolio_sync_summary` already reads. Per target:

| Target condition (checked in this order) | Target state |
| --- | --- |
| an open sync conflict on the Project | `conflict` |
| `last_verified_at IS NULL` or `last_run_id IS NULL` | `unverified` |
| last run `sync_state` ≠ `in_sync` (`db_export_pending`, `external_import_pending`, `workbook_unavailable`, `schema_unsupported`, `partial`, `verification_pending`, `verification_failed`, `conflict`, `never_synced`) | `sync_degraded`, carrying the run's `sync_state` |
| otherwise | `in_sync` |

A Project's `constraint_source_state` is: `calendar_unconfigured` when it has no usable
calendar; else `never_synced` when it has **no** target; else the **worst** of its
targets' states by precedence `conflict` > `sync_degraded` > `unverified` > `in_sync`
(a Project with 2 workbooks is `in_sync` only when both are). Overall precedence:
`calendar_unconfigured` > `conflict` > `sync_degraded` > `unverified` > `never_synced` >
`in_sync`. A run in flight (`active_run_id` set) is not consulted: the snapshot reads
the last finished-or-previewed run named by `last_run_id`, and a preview already sets a
pending `sync_state`, which reads `sync_degraded`; a run whose lease expired is rewritten
to `failed` / `partial` by the next preview (`infrastructure/persistence/constraints.py`,
the lease-expiry branch of the preview write) and reads `sync_degraded` from then on.
The per-Project answer also carries `constraint_last_run_sync_states` (the
distinct persisted run states of its targets, sorted). The existing
`ConstraintSyncHealthView` is still shown as `constraint_sync`, for continuity with
`constraints.portfolio_overview`, and decides nothing.

**Legacy Issue↔Project links (R4-F02).** S1 left existing Issue-kind
`project_situations` rows "validated, never repaired, unread" (S1 §12 row 3), and S3 §8.3
classifies one with no membership event for its triplet as `unresolved` /
`project_situation_inconsistent`. In the snapshot S4 counts, per resolved Project, the
`project_situations` rows naming an Issue (`situations.kind = 'issue_workstream'`) with
**no** `issue_project_membership_events` row for `(principal, project, issue)`, split by
the Issue's state (R4-F16): `legacy_issue_links` counts those whose Issue is outstanding
(`state` ∈ `open`, `active`, `suspended`) — such a link is neither counted nor dropped:
it makes the Issue metric unverifiable for that Project; `legacy_issue_links_closed`
counts those whose Issue is `closed` — disclosed only, never gating, because a closed
Issue cannot contribute to `issue_outstanding` whatever its link state, and these rows
are never repaired (S1 §12), so gating on them would block the metric forever.

- **Per-Project values** are `reported` whenever they are computable, carrying the
  Project's `constraint_source_state` and, for the accepted Commitment metrics,
  `acceptance: "unverified_review_reference"`. Exceptions, each `not_reportable` at
  Project grain too: a Project with no usable calendar has `calendar_unconfigured` for
  its 5 Constraint metrics (the portfolio overview omits it; it is disclosed, never
  dropped); a Project with `legacy_issue_links > 0` has `issue_link_unverified` for
  `issue_outstanding`.
- **Program and portfolio totals** are `reported` (value = the distinct count, possibly
  `0`, which is then a verified zero) unless one of these holds, in which case the value
  is `null`, `value_state = "not_reportable"` and `reasons` lists every reason (sorted):
  - `membership_unresolved` — the scope's resolution has an unresolved member (every
    metric);
  - `membership_truncated` — a budget was reached (every metric);
  - `acceptance_unverified` — the 3 accepted Commitment metrics, **always in S4**:
    no capability-reachable route verifies a Commitment's acceptance (S2 D-05/D-17,
    S3 D-11), so an accepted total is never certified; the rule is the pure function
    `domain/program/reportability.py::commitment_acceptance_proof`, which returns
    `unverified_review_reference` for every native accepted Commitment (section 12, D-04);
  - `issue_link_unverified` — `issue_outstanding`, when any Project of the scope has
    `legacy_issue_links > 0`;
  - `calendar_unconfigured`, `never_synced`, `sync_unverified`, `sync_degraded`,
    `sync_conflict` — a Constraint metric whose scope holds a Project whose
    `constraint_source_state` is respectively `calendar_unconfigured`, `never_synced`,
    `unverified`, `sync_degraded` or `conflict`.
- **`restricted`** (value `null`) replaces both when the reader may not see the
  metric's family (section 6.2); it is never a count.
- **Denominator, never hidden.** Each Program and the portfolio carry
  `denominator = {member_projects, unresolved_members, legacy_issue_links,
  legacy_issue_links_closed,
  projects_by_constraint_source_state: {in_sync, never_synced, unverified, sync_degraded,
  conflict, calendar_unconfigured}}` (integers) and `project_ids_by_constraint_source_state`
  and `project_ids_with_legacy_issue_links` (the caller's own Project ids, sorted), so
  the reader sees which Projects make a total not reportable. Their Constraint and Issue
  parts follow the family visibility of section 6.2.
- Lowering any threshold is an operator risk acceptance (OD-08, section 13); no S4 code
  path has a threshold parameter.

### 3.4 Time and the common cutoff

- **One snapshot per request.** One call of `programs.members.resolve` or
  `programs.overview` reads in one `REPEATABLE READ, READ ONLY` transaction on one
  connection (section 6.3). Every statement of that call sees the same committed state,
  so its per-Project, per-Program and portfolio figures and its membership are equal at
  a common cutoff by construction. 2 separate calls take 2 snapshots and are equal only
  when nothing changed between them. `source_cutoff_at` = `statement_timestamp()` of
  the snapshot's first query (the snapshot is taken by that query); the Commitment
  cutoff `c` of section 3.2 **and** the `now` handed to `ConstraintReadService`'s
  portfolio methods (from which `project_today` and the overview's `as_of` derive) are
  this same instant.
- **The S3 knowledge clock where it applies.** The first query also reads the
  Principal's committed lineage horizon `H` (`lineage_commit_sequences.last_marked_at`,
  null when the Principal has no lineage fact) and reports it as `lineage_known_at`. In
  the snapshot every lineage fact is committed (the allocator lock is held to commit,
  S3 §3.4), so the Issue↔Project links read are exactly those known at `H`: an
  `issues.timeline` or `records.lineage` read with `known_at = lineage_known_at` sees
  the same Project links. Native planes (Commitments, Constraints, Entities) have no
  commit-ordered clock (S3 D-01); the snapshot is their cutoff.
- **`valid_at`** (resolver only, historical mode) is business time over the edges'
  **currently recorded** effective window. The Entity plane has no knowledge clock and
  `revise` rewrites the window in place, so a historical answer can change after a later
  revision of an edge; the answer says `membership_record: "current"` (section 12,
  D-05). The clock is the database's: a `valid_at` after `source_cutoff_at` is
  `invalid_request` / `valid_at`.
- **No past-dated overview.** Commitment and Constraint planes keep no field history a
  past count could be read from; `programs.overview` is current only, and `as_of` is not
  admitted (section 12, D-05).

## 4. Schema — one additive revision

One Alembic revision, `down_revision = "6f1476b8da52"`, the new single head (file
`migrations/versions/<date>_<rev>_record_lineage_s4.py`; slug `record_lineage_s4`).
Frozen literal DDL, no domain or persistence import, declarations mirrored in
`infrastructure/persistence/tables.py` with the `TABLES_SHA256` pin and every W1 §2.2
registration step. S1–S3 §4 conventions hold (schema `knowledge`, principal partition,
`_is_identifier`, principal-composite `ON DELETE RESTRICT`, server-stamped
`timestamptz`, a restated CHECK keeps its name).

**No change to** `entities`, `entity_relationships`, `project_entity_links`,
`projects`, `commitments`, `situations`, `project_situations`,
`issue_project_membership_events`, any Constraint table or any lineage table. **No new
index**: every S4 read is served by existing indexes (`entity_relationships_by_to_entity`,
`a_project_entity_is_linked_once_per_principal`, `commitments_by_principal_state`,
the `issue_project_membership_events` unique key, the Constraint portfolio indexes);
section 10's plan test pins it, and an index is added only if that test proves the need
(CR-009 "optional index only if query plan demonstrates need").

### 4.1 New table `intelligence_artifact_manifests` (immutable)

| Column | Type / rule |
| --- | --- |
| `principal_id`, `artifact_id` (`rpt`) | PK `(principal_id, artifact_id)`; FK `(principal_id, artifact_id) → intelligence_artifacts` `ON DELETE RESTRICT` (`a_manifest_names_an_artifact_of_its_principal`) |
| `manifest_schema_version` | `integer NOT NULL`, CHECK `= 1` |
| `manifest_canonical` | `text NOT NULL`; CHECK `a_manifest_is_printable_ascii`: `manifest_canonical ~ '^[ -~]+$'` and `length(manifest_canonical) <= 262144` |
| `manifest_sha256` | `text NOT NULL`; CHECK `a_report_manifest_digest_is_its_canonical_text`: `manifest_sha256 = encode(sha256(convert_to('report-manifest-v1' || chr(10) || manifest_canonical, 'UTF8')), 'hex')` |
| `structured_content_sha256` | `text` (hex, null exactly when the artifact has no structured content) |
| `program_overview_sha256` | `text` (hex) or null: the Program reference's **claimed** digest (`program.claimed_overview_sha256`) |
| `program_verification_state` | `ProgramVerificationState` or null; CHECK `(program_overview_sha256 IS NULL) = (program_verification_state IS NULL)` |
| `recorded_at` | `timestamptz NOT NULL DEFAULT now()` |

The 3 projected columns are copies of manifest fields, for reading without parsing;
the canonical text is the fact.

Triggers:

- `a_manifest_names_its_own_artifact` (`BEFORE INSERT`): `manifest_canonical::jsonb`
  must have `manifest_schema_version = 1`, `report.report_id = NEW.artifact_id`,
  `report.content_sha256` = the artifact's stored `content_sha256`,
  `structured_content.sha256` equal to `structured_content_sha256`, and
  `program.claimed_overview_sha256` and `program.verification_state` (null when
  `program` is null) equal to the 2 Program columns; else `check_violation`.
- `intelligence_lineage_is_append_only()` (existing function of `e9b2c4d7a150`)
  attached `BEFORE UPDATE OR DELETE`; new statement trigger
  `intelligence_manifests_refuse_truncate` (`BEFORE TRUNCATE`, `restrict_violation`;
  the `c8e4a1b70d35` precedent).
- **On `intelligence_artifacts`:** constraint trigger `an_artifact_has_its_manifest`
  (`AFTER INSERT`, `DEFERRABLE INITIALLY DEFERRED`): at commit a manifest row for
  `(principal_id, artifact_id)` must exist, else `check_violation`. So no artifact
  committed after the revision can lack a manifest, whichever writer inserted it; rows
  inserted before the revision are untouched and are the legacy set.

### 4.2 Existing tables

**`audit_events`** — `capability_is_known` and `purpose_is_known` restated (BEFORE texts
byte copies of `6f1476b8da52`'s AT texts; AT texts add exactly the 7 section 7 names and
`program_reporting_read`, sorted), `_CURRENT_AUDIT_CAPABILITIES` moving with them (233 →
240), under the schema-ahead precedent with
`tests/schema/lineage_s4_schema_ahead_contract.py`.

### 4.3 Downgrade

`downgrade()` first refuses (`restrict_violation`) while an
`intelligence_artifact_manifests` row exists, or an `audit_events` row names an S4
capability or `program_reporting_read` (each family alone sufficient). Only then it
drops `an_artifact_has_its_manifest`, the table with its triggers, and restores both
audit CHECKs to their `6f1476b8da52` texts byte for byte.

## 5. Canonical encodings

- **Program canonical JSON** reuses `domain/lineage/canonical.py::canonical_json`
  (ADR-014 decision 6: NFC, sorted keys, compact separators, no floats). Every Program
  answer field is an identifier, closed token, integer, boolean, ISO-8601 string or null.

### 5.1 Overview digest

`overview_sha256 = sha256(b"program-overview-v1\n" + canonical_json(D)).hexdigest()`
where `D` is the section 7.2 result **without** its 3 read-time stamps
`overview_sha256`, `source_cutoff_at` and `lineage_known_at`. `project_today` and
`constraint_sync.last_verified_at` stay in `D` (the first decides overdue, the second
is stored data). Two overviews of an unchanged state on one Project calendar day are equal;
any change of membership, a metric value, a reportability reason, a source state or a
calendar day changes it.

### 5.2 Structured-content digest

`structured_content_sha256 = sha256(b"report-structured-content-v1\n" + J(v)).hexdigest()`,
`J(x) = json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
allow_nan=False).encode("ascii")`, where `v` is the artifact's `structured_content`
**as read back from `intelligence_artifacts` in the committing transaction** through
SQLAlchemy's `JSONB` column with psycopg 3's default JSONB loader (`json.loads`:
integers as `int`, other numbers as `float`, never `Decimal`) — JSONB normalizes numbers,
so hashing the request's parsed value would disagree with a later re-derivation from the
stored row. Producer content may hold floats; `J` renders them by Python's shortest
round-trip repr. `null` when the artifact has none. **In-memory store:**
`InMemoryIntelligenceStore` hashes the value it holds; it is not byte-comparable with the
SQL path for a number JSONB renormalizes (a request `1e2` is `100.0` in memory and `100`
from PostgreSQL), so golden vectors containing such numbers are derived from the SQL path
only, and unit vectors use integers, strings and already-normal floats (R4-F12).

### 5.3 Report manifest (WP-04C, CR-013)

`manifest_canonical = J(M).decode("ascii")`;
`manifest_sha256 = sha256(b"report-manifest-v1\n" + J(M)).hexdigest()` (the database
CHECK of section 4.1 recomputes it). `M` has exactly these keys, every one present:

```text
{"manifest_schema_version": 1,
 "report": {report_id, cycle_run_id, producer_run_id, stage, artifact_kind, focus_area_id,
            source_lane, report_date, version, supersedes_report_id, schema_version,
            producer_prompt_version, title_sha256, content_sha256, content_bytes,
            committed_at, artifact_state_at_commit, producer_completeness},
 "structured_content": {"present": bool, "sha256": hex|null},
 "candidate_status": "unaccepted_candidate" (stage collector) | "not_a_candidate",
 "dependencies": [{report_id, dependency_role, required, content_sha256,
                   structured_content_sha256, manifest_sha256, manifest_state}],
 "provenance": [{position, source_system, source_ref, relation, source_url, observed_at,
                 retrieved_at, evidence_subject_id, certification: "uncertified_reference"}],
 "program": null | ProgramManifestSection}
```

- `title_sha256` = `sha256(title.encode("utf-8"))` (no narrative in the manifest);
  every instant is rendered exactly as `%Y-%m-%dT%H:%M:%S.%fZ` in UTC (6 fractional
  digits, a literal `Z`, never `+00:00`; the S3 `_lineage_instant` format, pinned by a
  golden vector); `dependencies` sorted by `report_id`
  (`COLLATE "C"` order), `provenance` by `position`.
- **Dependencies** carry each upstream's stored `content_sha256`, its
  `structured_content_sha256` (section 5.2, recomputed from the immutable upstream row
  when the upstream is legacy), and its `manifest_sha256` with `manifest_state =
  "recorded"`, or `null` with `"manifest_unavailable_legacy"`. So replacing a dependency
  by another artifact with the same Markdown but different structured content, or a
  different upstream manifest, changes the downstream manifest.
- **Candidates are never typed.** A collector artifact's manifest says
  `unaccepted_candidate`; every provenance reference is `uncertified_reference`; the
  manifest has no field that could type a candidate or a reference as a Procore RFI, a
  financial fact or an accepted record, and section 7.4 refuses a Program reference on a
  collector or researcher artifact.
- `ProgramManifestSection` (sections 5.4, 7.4) = `{block_schema_version: 1,
  program_entity_ids, claimed_overview_sha256, claimed_source_cutoff_at,
  verification_state, recompute_failure|null, families_seen|null, server|null}` where
  `server` = `{overview_sha256, source_cutoff_at, lineage_known_at|null,
  metric_schema_version, calculation_version, complete_state, qualifiers,
  membership: [{program_entity_id, resolved_program_entity_id, membership_state,
  project_ids}], portfolio_project_ids, totals: [{scope, metric_id, value|null,
  value_state, reasons}]}` — the recomputed `programs.overview` answer **as served to the
  committing caller** (restricted families stay `restricted`, `not_reportable` values
  stay `null`), so it is the server's uncertified state at commit, never a certified
  total (OD-08). `families_seen` is the sorted subset of the overview's 5 families
  {`entity`, `project`, `commitment`, `issue`, `constraint`} visible to that caller
  during the recompute — never `situation`, from which no overview field derives
  (R4-F23). `server` and `families_seen` are non-null exactly for `verified_at_commit` and
  `changed_since_read`; `recompute_failure` is non-null exactly for `recompute_failed`;
  `not_attempted` carries only the claim. `scope` is a Program id or `"portfolio"`.
- Excluded by design: the mutable `artifact_state` after supersession and `is_current`
  (the manifest binds commit-time state), and the never-written `evaluation_*` columns
  (section 12, D-23).

### 5.4 Program reference block

A synthesizer, reporter or morning-brief artifact written from a Program overview puts,
under the reserved top-level `structured_content` key `program_overview_ref`, exactly
`{"block_schema_version": 1, "program_entity_ids": [ent_ … as requested, 1..10,
distinct], "overview_sha256": <64-hex from the overview it read>,
"source_cutoff_at": <that overview's source_cutoff_at, in the section 5.3 instant
format>}`. The block is a reference, not a copy: a whole overview can exceed
`MAX_STRUCTURED_CONTENT_BYTES` (64 KiB). The server binds its own recomputed state
beside the claim (section 7.4), so the manifest records both what the producer says it
read and what the server saw at commit; S4 certifies neither (section 12, D-09).

## 6. Authority, visibility and the read transaction

### 6.1 Authority and grants

All 7 S4 capabilities are **reads**: no attestation, no idempotency key, no reservation,
no commit mark, no Record Event. They are classified `CHATLLM_OPERATOR_DECISION_REQUIRED`
(rationale "record lineage S4 Program reporting; exposure is an operator decision
(ADR-015, OD-07)"); no grant, profile or client allowlist changes. **Remote read grant
re-check** (S3 §6.1, R3-F13): each S4 handler re-checks that a remote caller holds a
grant on its own capability for a permitted purpose, else **`unsupported`**. The
attestation paths of S1–S3 are untouched.

### 6.2 Visibility (remote callers; the S3 §6.4 rule, on every path — R4-F03)

A local caller sees everything of its Principal. A remote caller sees a family only
while it holds a grant, for one of its purposes, on one of the family's reads
(`PROGRAM_FAMILY_READS` in `domain/program/vocabulary.py`):

| Family | Reads (any one) |
| --- | --- |
| `entity` | `entities.get`, `entities.search` |
| `project` | `continuity.projects`, `continuity.projects.read` |
| `situation` (context Situation) | `continuity.situations` |
| `commitment` | `commitments.read`, `commitments.list` |
| `issue` | `issues.read`, `issues.list` |
| `constraint` | `constraints.read`, `constraints.list` |

Every field an S4 answer derives from a family is withheld when that family is
invisible — never only the headline metrics:

- **Both Program reads** need `entity` **and** `project`; without them every requested
  Program answers `not_found` / `program_entity_ids` (an invisible root, S3 §6.4).
- **`programs.overview`**, per family:
  - `commitment` invisible ⇒ the 7 Commitment metrics are `restricted` at every scope;
  - `issue` invisible ⇒ `issue_outstanding` is `restricted` at every scope,
    `lineage_known_at` is `null`, and every legacy-link field
    (`legacy_issue_links`, `legacy_issue_links_closed`, their denominator entries and
    `project_ids_with_legacy_issue_links`) is `null`;
  - `constraint` invisible ⇒ the 5 Constraint metrics are `restricted` at every scope,
    and every Constraint-derived field is `null`: per Project `calendar`,
    `constraint_source_state`, `constraint_last_run_sync_states` and `constraint_sync`;
    `denominator.projects_by_constraint_source_state` and
    `project_ids_by_constraint_source_state`.
  - A restricted field is `null` (a metric: `value_state = "restricted"`, no value, no
    reason); the answer carries `restricted_evidence`; the overview digest is computed
    over the answer as served, so it never encodes a withheld value.
- **`commitments.v2.*`**: `project_reference` is `restricted` (id `null`) when the
  `project` family is invisible to a remote caller. `situation_reference` is gated **by
  the referenced Situation's kind** (R4-F17: `commitments.situation_id` is a global,
  pattern-checked foreign key, so it can name an Issue): `issue_workstream` ⇒ the
  `issue` family, `context` ⇒ the `situation` family; the kind is read in the same
  batched reference statement. Otherwise their v1 siblings' visibility (the grant)
  applies.
- **`reports.manifest`**: a manifest whose `program.verification_state` is anything but
  `not_attempted` (`verified_at_commit`, `changed_since_read` or `recompute_failed`) is
  returned in full to a remote reader only if the reader **holds a `programs.overview`
  grant for `program_reporting_read`** (capability separation, R4-F21) **and** currently
  sees the `entity` and `project` families **and**, when `program.server` is non-null,
  **every** family in `program.families_seen` (R4-F27: a `recompute_failed` manifest's
  `program_not_found` / `program_invalid` token, and the mere presence of a server
  section, would otherwise tell an unauthorised reader whether Entity ids exist and are
  Programs). A manifest whose `program` is `null` or whose state is `not_attempted`
  carries only producer-supplied content and is ungated. Otherwise `manifest_state =
  "restricted_evidence"` with `manifest_sha256` **and** `manifest_canonical` both `null`
  (R4-F20). The digest is withheld too because almost all of `M` is derivable from what
  such a reader can read, so the digest of a withheld text would let it test candidate
  hidden totals offline; no other digest of the manifest (the 3 projected columns) is
  returned either. The artifact's existence is already disclosed by `reports.read`. A
  local reader sees it all.
- **`reports.commit`**: the recompute (section 7.4) runs with the **committing caller's**
  visibility and only when `programs.overview` is served by this build and admits that
  caller, so its recorded outcome is exactly what one `programs.overview` call by that
  caller at that instant would answer — no oracle for an invisible family or Program.
  Otherwise the commit records `not_attempted`, which depends only on the build and the
  caller's own grants.

### 6.3 The Program read transaction and its own pool (R4-F05)

**Why not the request's connection.** `ApplicationService._run` opens the request's
`UnitOfWork` (READ COMMITTED) before authorization and keeps it for the handler's whole
life, so the handler cannot raise that transaction's isolation level, and several
statements on it are several snapshots. **Why not the work pool.** A second checkout
from the work pool while the request holds its work connection is the deadlock at
`C = P` that `bootstrap/gateway.py`'s module docstring derives and
`tests/concurrency/test_gateway_connection_pool.py` measures (the existing Constraint,
Task and Commitment unit-of-work factories are already drawn from the work engine; S4
does not add to that).

**Design.** `bootstrap/gateway.py` builds a **third engine**, `program_read_engine =
create_database_engine(url, statement_timeout_ms=2000, pool_timeout_seconds=1)` — the
audit-engine fix, with the S3 per-statement budget and a 1 s checkout timeout — only when `program_reporting_enabled` is on, and passes
`lambda: SqlAlchemyProgramReadUnitOfWork(program_read_engine)` to `ApplicationService`
(`None` ⇒ the 2 Program reads are withheld). No other code draws from that pool.
`GatewayRuntime` disposes it with the other 2.

1. `program_read_engine.connect().execution_options(isolation_level="REPEATABLE READ",
   postgresql_readonly=True)`, then `begin()`; the first query — the one that takes the
   snapshot — reads `statement_timestamp()` and `H` (section 3.4). A statement cancelled
   by its timeout, or a checkout that exceeds the Program engine's 1 s checkout timeout,
   answers `unavailable` on the Program reads and is recorded as `recompute_failed` on a
   commit (section 7.4). **M1 adds `pool_timeout_seconds: float = _POOL_TIMEOUT_SECONDS`
   to `infrastructure/database/engine.py::create_database_engine`** (R4-F22): the default
   is the existing 30 s, so every existing caller is unchanged; only the Program engine
   passes 1.
2. It exposes, on that one connection: `program_membership`
   (`SqlProgramMembershipRepository`), `program_metrics` (`SqlProgramMetricsRepository`)
   and `constraints` (the existing `SqlConstraintManagementRepository(connection)`).
3. It never writes (the read-only transaction refuses a write); `__exit__` rolls back.
   Audit and authorization stay in the request's own unit of work.

**Pool arithmetic (R4-F18).** A Program read — `programs.*`, or the recompute of a
`reports.commit` — holds 1 work connection (the request's) and needs 1 Program-pool
connection; nothing that holds a Program-pool connection ever waits for a work or audit
connection (the snapshot read completes on its own connection and returns it), and a
READ ONLY snapshot read never waits on a row lock (PostgreSQL readers do not block on
writers). The wait-for graph therefore has no cycle at any `C`. Each request holds at
most 1 Program-pool connection and only while it holds a work connection; the work pool
caps those at 5 with no overflow, so in the gateway the 5-connection Program pool never
queues: at `C > 5` the excess requests queue on the **work** pool, exactly as today.
**Every composition that serves S4 is built by `build_gateway_runtime`** — the HTTP
gateway and the stdio and remote MCP transports (`apps/gateway.py`) and `apps/cli/invoke.py`
(one request at a time) — so the same per-process arithmetic holds in each; the only
other `ApplicationService` composition, `apps/cli/gsqs_b0.py`, passes no Program factory,
so `programs.*` are withheld there and a commit records `not_attempted` (R4-F22, R4-F24).
Section 10 pins it with the gateway's own pools at `C = 5` and `C = 10` (the 10 complete;
no Program-pool checkout waits). **Backends.** With the switch on, each process that
composes the Program factory builds its own 5-connection Program pool: the gateway's
"Ten backends in total" (`bootstrap/gateway.py` module docstring) becomes 15, and a
separately composed process (the remote MCP runtime, if it composes the factory) adds
its own; M1 updates that docstring and `ops/runbooks/gateway-operations.md`, and the
production budget is an operator item (section 13). READ ONLY makes the `ON CONFLICT`
hazard documented in `infrastructure/persistence/__init__.py` unreachable here (it
concerns writers).

**Statement plan, constant in the number of Programs, Projects and rows** (pinned by a
statement recorder, section 10): cutoff + horizon; Programs with redirect resolution
(1 recursive statement); member edges with member redirect resolution and types (1);
bridges with redirect resolution (1); Projects (1); Commitment aggregates grouped by
Project (1); Issue `(project_id, situation_id)` pairs (1); legacy Issue links per
Project (1); sync targets with their last run state (1); Constraint settings, overview
facts and sync summary through the existing portfolio methods (4).

## 7. Capabilities — the exact S4 set

7 new `Capability` members (222 → 229; audit vocabulary 233 → 240) and 1 new `Purpose`
(59 → 60). All are reads, `_SCOPELESS`, in no write, idempotent or additive set, and
`CHATLLM_OPERATOR_DECISION_REQUIRED`.

| Capability | Purpose | Family → feature | Answer |
| --- | --- | --- | --- |
| `programs.members.resolve` | `program_reporting_read` (new) | `programs` → `programs` (new feature row) | section 7.1 |
| `programs.overview` | `program_reporting_read` | `programs` → `programs` | section 7.2 |
| `commitments.v2.read` | `commitment_read` | `commitments` → `work` | section 7.3 |
| `commitments.v2.list` | `commitment_read` | `commitments` → `work` | section 7.3 |
| `commitments.v2.search` | `commitment_read` | `commitments` → `work` | section 7.3 |
| `commitments.v2.waiting_on` | `commitment_read` | `commitments` → `work` | section 7.3 |
| `reports.manifest` | `report_read` | `reports` → `reports` | section 7.4 |

**Purposes (R4-F15, R4-F04).** `program_reporting_read` is its own purpose under the
repository's D-91 rule — a purpose names a data domain, and reuse is refused when it
would let a grant reach data the reused purpose does not name: a Program read reaches
Entities, Projects, Commitments, Issues and Constraints of many Projects, which no
existing purpose names (`report_read` names Intelligence artifacts). Every MCP tool's
input schema carries the envelope's `$defs.Purpose.enum`, so this purpose **widens that
enum in every existing tool schema by exactly 1 member**, as S3's `lineage_backfill`
did; no payload schema changes (section 8). The `commitments.v2.*` reads reuse
`commitment_read` and `reports.manifest` reuses `report_read`: same data, same domain.

### 7.1 `programs.members.resolve`

**In:** `{program_entity_ids: [ent_] (1..10, distinct), valid_at?: ISO-8601 with offset}`.
A duplicate, empty or oversize list, or a malformed id, is `invalid_request` /
`program_entity_ids`.

**Out:**

```text
{mode: "current"|"historical", valid_at, source_cutoff_at, membership_record: "current",
 programs: [{program_entity_id, resolved_program_entity_id, redirected, program_status,
             members: [{project_id, project_entity_id, member_entity_status, project_state,
                        relationship_ids}],
             unresolved_members: [{relationship_id, member_entity_id, reason}],
             unverified_members: [{relationship_id, member_entity_id, project_id|null, reason}],
             excluded: {non_project_members, outside_window},
             complete_state, qualifiers}],
 portfolio: {project_ids, overlaps: [{project_id, program_entity_ids}]},
 complete_state, qualifiers}
```

`valid_at` is the requested instant or, in current mode, `source_cutoff_at`.
`programs` in request order; lists sorted by their identifier (`COLLATE "C"`).
`unverified_members` is empty in current mode. A member's `project_id` is that of
section 3.1 step 5.

### 7.2 `programs.overview`

**In:** `{program_entity_ids: [ent_] (1..10, distinct)}`; any other field (`as_of`,
`valid_at`, `project_ids`) is `invalid_request`.

**Out:**

```text
{source_cutoff_at, lineage_known_at, metric_schema_version: 1,
 calculation_version: "program-overview-v1",
 programs: [{program_entity_id, resolved_program_entity_id, membership_state: ProgramCompleteness,
             project_ids, unresolved_members, denominator, project_ids_by_constraint_source_state,
             project_ids_with_legacy_issue_links, totals: [MetricView]}],
 portfolio: {project_ids, overlaps, denominator, project_ids_by_constraint_source_state,
             project_ids_with_legacy_issue_links, totals: [MetricView]},
 per_project: [{project_id, project_state, calendar: {timezone_name|null, project_today|null}|null,
                constraint_source_state|null, constraint_last_run_sync_states|null,
                constraint_sync: {state, open_conflict_count, last_verified_at|null}|null,
                legacy_issue_links|null, legacy_issue_links_closed|null, metrics: [MetricView]}],
 complete_state, qualifiers, overview_sha256}
MetricView = {metric_id, grain, value: int|null, value_state, reasons: [NotReportableReason],
              nonadditive_across_projects: bool, acceptance: AcceptanceVerification|null}
```

Membership is current mode (section 3.1). `per_project` holds every resolved Project
once, sorted by `project_id`; `totals` and `metrics` hold the 13 section 3.2 metrics in
catalogue order. `constraint_sync` is the existing `ConstraintSyncHealthView`
(`state` ∈ `in_sync`, `never_synced`, `conflict`), shown for continuity and deciding
nothing; `constraint_source_state` (section 3.3) decides. The `|null` fields are `null`
only under section 6.2's family rule. `acceptance` is
`unverified_review_reference` on the 3 accepted Commitment metrics and `null`
elsewhere. Section 3.3 decides `value_state` and `reasons`; `overview_sha256` is
section 5.1.

### 7.3 `commitments.v2.read`, `.list`, `.search`, `.waiting_on`

Each takes exactly its v1 sibling's request (same fields, same rules, same cursor) and,
for `list`, `search` and `waiting_on`, an optional `project_ids: [prj_] (1..100,
distinct)`: a malformed or duplicate entry is `invalid_request` / `project_ids`; any id
that is not a Project of this Principal is `not_found` / `project_ids` (absent and
foreign alike, one statement for the set); the filter keeps rows whose stored
`project_id` is in the set, inside the v1 order and keyset.

Each answers exactly its v1 sibling's top-level keys, with the Commitment objects
replaced by the v2 views of `contracts/v1/commitments_v2.py`:

- `CommitmentV2View` = every `CommitmentView` key + `project_id`, `project_reference`,
  `situation_id`, `situation_reference`, `acceptance_verification`;
- `CommitmentV2ListEntry` = every `CommitmentListEntry` key + `evidence_state` and the 5
  keys above;
- `WaitingOnV2Entry` = every `WaitingOnEntry` key + the 5 keys above;
- the `counterparty` projection key is kept as in v1.

**Owned references only.** `commitments.project_id` and `situation_id` carry plain,
global foreign keys and `commitments.create` checks only their pattern (a pre-existing
v1 residual, section 12, D-16). A v2 view shows the stored id with `owned` when it names
a Project (or Situation) of this Principal; `null` with `none` when nothing is stored;
`null` with `not_owned` otherwise — another Principal's identifier is never echoed —
and `null` with `restricted` when the reader may not see the family (section 6.2).
`acceptance_verification` is `unverified_review_reference` when `evidence_state =
accepted`, else `not_accepted`.

**Batched.** The reference check, the follow-up Tasks of a `waiting_on` page and the
counterparty projections are each read once per page (sets of ids), so a v2 page issues
a constant number of statements whatever its size; the v1 siblings keep their per-row
reads unchanged (section 12, D-22).

### 7.4 `reports.commit` (delta) and `reports.manifest`

**`reports.commit` — request, refusals and answer unchanged** except:

- `SqlIntelligenceRepository.put_artifact(artifact, *, program_section=None)` — the
  one writer of `intelligence_artifacts` — after inserting the artifact, its
  dependencies and provenance, reads back the stored `structured_content` and the
  upstreams' digests (one statement each), builds the section 5.3 manifest with
  `domain/intelligence/source_manifest.py::build_manifest` and inserts the section 4.1
  row in the same transaction; the deferred trigger proves it at commit. Every caller of
  `put_artifact`, including a test that calls it directly, therefore writes a manifest;
  a replay never reaches it. This is bookkeeping, not exposure, and is **not behind the
  switch** (section 12, D-21).
- **When the Program plane is admitted** (section 7.6) and `structured_content` has the
  key `program_overview_ref`: the block must have exactly the section 5.4 shape and the
  stage must be `synthesizer`, `reporter` or `morning_brief`, else `invalid_request` /
  `structured_content` (a pure check, before anything is read). Then **the recompute
  (R4-F14)**, in this exact order inside `commit_artifact`:
  1. the existing pure validations, then the replay lookup (`get_receipt`, a read); a
     replay returns the stored receipt and recomputes nothing; then **every remaining
     refusal check**, all reads: `get_cycle`, dependency validation, the
     `automation_run_id` conflict and `current_head` with the stale
     `supersedes_artifact_id` check (R4-F25) — so a commit about to be refused never
     pays for a recompute;
  2. **the recompute** — immediately before the commit's first write (`put_receipt`,
     then `mark_superseded`, `put_run`, `put_artifact`) and before any lock-taking
     statement. The
     request's own `UnitOfWork` transaction is open, as it is for every handler
     (`ApplicationService._run` opens it before authorization), but the commit path has
     written nothing and holds no row lock at this point; the recompute runs on its own
     **Program-pool** connection (section 6.3) — never on the work connection and never
     a second work-pool checkout — as a READ ONLY snapshot read, which never waits on a
     row lock. It is attempted only when `programs.overview ∈ available_capabilities()`
     (so the switches, the entity plane, the Program factory and the Constraint plane all
     hold, section 7.6) **and** `programs.overview` admits the caller (its remote grant
     re-check and the `entity` and `project` families, section 6.2); otherwise the
     commit records `not_attempted` (R4-F24). It runs the `programs.overview` path for
     the block's `program_entity_ids` with **the committing caller's** section 6.2
     visibility under a **hard total budget of 5000 ms** (R4-F22): the clock starts
     before the checkout; the checkout waits at most the Program engine's 1 s; before
     each statement the remaining budget is computed, a non-positive remainder stops
     with `budget_exceeded`, and the statement runs under `SET LOCAL statement_timeout =
     min(2000, remaining)` ms. The true worst case is therefore 5000 ms plus the
     round-trip latency of the `SET LOCAL` and rollback statements — never a 30 s
     checkout and never a full 2000 ms statement started at the deadline;
  3. it records `verified_at_commit` when the recomputed `overview_sha256` equals the
     claimed one, else `changed_since_read`, and in both cases binds the `server` part of
     section 5.3 with `families_seen`. Any failure — budget exceeded, a statement
     timeout, no Program-pool connection within the checkout timeout, a Program now
     absent or not program-typed — is **recorded** as `recompute_failed` with its
     `RecomputeFailure` token and **never refuses the commit**: a slow Program plane
     cannot fail an Intelligence commit;
  4. the writes of `commit_artifact` as before; `put_artifact` receives the section and
     inserts the manifest in the commit's transaction. Two same-key commits may both
     recompute; the `put_receipt` loser replays the winner, whose manifest is the one
     bound.
  **Ordering of instants.** `report.committed_at` is the request's instant (`_now(at)`),
  taken before the recompute, so `server.source_cutoff_at` is **later** than
  `committed_at`; readers must not assume `cutoff ≤ committed_at` (R4-F25).
  **Audit.** The recompute is not a capability invocation and writes no audit row of its
  own: the record is the `reports.commit` audit row (its own capability and purpose, on
  the audit engine) together with the manifest's `verification_state`,
  `recompute_failure`, `families_seen` and `server.source_cutoff_at` (R4-F25).
  Nothing about the recompute appears in the `reports.commit` answer; it is readable only
  through `reports.manifest` under section 6.2.
- **When the Program plane is not admitted**, the key is ordinary structured content:
  nothing is interpreted and the manifest's `program` is `null`, so the switch-off
  behaviour of `reports.commit` is byte-identical to S3's.

**`reports.manifest`** — in `{report_id}` (`rpt_`; absent and foreign are `not_found` /
`artifact_id`, as `reports.read`); out `{report_id, manifest_state, manifest_schema_version|null,
manifest_sha256|null, manifest_canonical|null}`. `recorded` returns the stored row
unchanged; an artifact with no row answers `manifest_unavailable_legacy` with 3 nulls
and **writes nothing** (no backfill of legacy manifests exists or is planned); section
6.2's grant and family rule — applied to every manifest whose Program state is not
`not_attempted`, `recompute_failed` included — may answer `restricted_evidence`
(`manifest_sha256` and `manifest_canonical` both `null`). A client verifies by recomputing
`sha256(b"report-manifest-v1\n" + manifest_canonical)`.

`reports.read`, `reports.latest`, `reports.list`, `reports.search`,
`reports.resolve_set` and `reports.types.*` are unchanged; S4 registers no report type
and issues no report-type grant (package 03 "no assumption report-type grant").

### 7.5 Errors (additions to S1–S3 §7)

| Situation | Code / safe detail |
| --- | --- |
| Program id malformed, duplicate, list empty or above 10 | `invalid_request` / `program_entity_ids` |
| Program absent, foreign, or invisible to a remote reader | `not_found` / `program_entity_ids` |
| terminal Entity not `program`-typed | `invalid_request` / `program_entity_ids` |
| Program redirect chain longer than 8 or cyclic | `conflict` / `program_entity_ids` |
| `valid_at` malformed or after `source_cutoff_at` | `invalid_request` / `valid_at` |
| a field `programs.overview` does not admit | `invalid_request` |
| `project_ids` malformed, duplicate, empty or above 100 | `invalid_request` / `project_ids` |
| `project_ids` names a Project not of this Principal | `not_found` / `project_ids` |
| malformed Program reference block, or one on a collector or researcher artifact | `invalid_request` / `structured_content` |
| a Program-read statement cancelled by its timeout, or no Program-pool connection within the pool timeout | `unavailable` |
| remote read without a grant on its own capability | `unsupported` |
| switch off, or plane not composed | `unsupported` |

New `SafeDetail` members `program_entity_ids` and `project_ids`; `valid_at`,
`structured_content` and `artifact_id` are reused.

### 7.6 Admission switch, web and MCP

**Switch.** `program_reporting_enabled: bool = False` in `bootstrap/settings.py`, env
`MY_PA_PROGRAM_REPORTING_ENABLED` (fails closed like every setting), passed by
`bootstrap/gateway.py` to `ApplicationService` with the Program read factory. Following
the S3 backfill sub-switch precedent (S3 §7.7), `available_capabilities()` subtracts
`_PROGRAM_REPORTING_CAPABILITIES` (the 7 names) unless **both** `lineage_enabled` and
`program_reporting_enabled` are on, and additionally subtracts the 2 `programs.*` names
unless `relationship_intelligence_enabled` (their subjects are Entities; the memory-plane
"two conditions" precedent) and the Program read factory is composed, and subtracts
`programs.overview` also when `constraint_management_unit_of_work` is `None` — a
gateway that does not serve the Constraint plane does not serve a read built on it
(R4-F11; the factory itself is not used, the overview reads Constraint tables on its
own snapshot connection). Every S4 handler calls `_program_plane()` (and the 2 Program
handlers also their composition checks) first, before any read, answering
`unsupported`. The Program-reference interpretation of section 7.4 applies exactly when
the 7 names are admitted (`lineage_enabled` and `program_reporting_enabled`). `ops/runbooks/gateway-operations.md` gains the variable.

**Web.** None: no route, view, decoder or `gateway.json` entry (still 110); the Program
dashboard is WP-06B. **MCP.** The 7 tools are derived from their commands as every tool
is, and are withheld with the switch through `available_capabilities` like every
lineage tool; no existing tool's schema changes (section 8).

## 8. Old-client rule and compatibility

- **v1 payload shapes are byte-identical; the envelope purpose enum widens by 1
  (R4-F04, R4-F15).** No existing command gains, loses or re-means a field, so every
  existing tool's **payload** schema is unchanged (the S3 payload-schema SHA pin,
  narrowed to exclude the S4 names, stays equal). The envelope's `$defs.Purpose.enum`,
  which every tool's input schema carries, gains exactly `program_reporting_read`, as
  S3's `lineage_backfill` did; so the S3 purpose-tail assertion
  `published[-4:] == [*basis_tail, "lineage_backfill"]` is an admitted lockstep edit
  (section 10). A strict old client that never sends that purpose is unaffected. The
  tool **list** grows by the 7 S4 tools when the switch is on.
- Every existing answer is byte-identical with the switch on or off, including the 4 v1
  Commitment reads over Commitments that store a `project_id`, and `reports.read`.
  `reports.commit` is byte-identical with the switch off; with it on, it is identical
  for every request whose `structured_content` has no `program_overview_ref` key, and a
  request carrying that key may now be refused (malformed block, or a collector or
  researcher stage) (R4-F10). `contracts/v1/commitments.py` is not edited; the web
  decoders and `success.json` are untouched.
- **The opt-in is the capability name.** A strict old client never calls a
  `commitments.v2.*` name; S2's rule "a composite is a new name, not a mode" is the
  precedent, and the envelope's `contract_version` stays `"v1"` (section 12, D-02).
- **S1–S3 lineage contracts** are unchanged; S4 adds no lineage capability, no lineage
  vocabulary and no lineage table column.
- Any later change to a deployed contract needs a negotiated version (S1 §8).

## 9. File plan, registration and the work split

New modules (resolve exact names against neighbours; no refactor beyond those named):

- `domain/program/__init__.py`, `domain/program/vocabulary.py` (section 3), `domain/program/membership.py` (pure: window rule, redirect walk over fetched rows, bridge resolution, dedup and overlap, completeness), `domain/program/reportability.py` (pure: totals from per-Project facts, reasons, denominator, `commitment_acceptance_proof`), `domain/program/digest.py` (section 5.1).
- `domain/intelligence/source_manifest.py` (pure: `J`, sections 5.2–5.4, block validation, golden vectors in `tests/fixtures/report_manifest_vectors.json`).
- `application/program_membership.py` (`programs.members.resolve`), `application/program_work.py` (Commitment and Issue metrics, the overview assembly and digest), `application/program_constraints.py` (Constraint metrics over `ConstraintReadService`'s portfolio path on the snapshot connection), `application/commitments_v2.py` (the 4 v2 handlers' assembly and batching).
- `infrastructure/persistence/program_reads.py` (the unit of work of section 6.3), `infrastructure/persistence/program_membership.py`, `infrastructure/persistence/program_metrics.py` (Commitment and Issue aggregates, legacy Issue links, sync targets with their last run); additions to `infrastructure/persistence/commitment_management.py` (the `project_ids` predicate), `infrastructure/persistence/task_management.py` (follow-ups for a set of Commitments), `infrastructure/persistence/intelligence.py` (`put_artifact` builds and inserts the manifest, section 7.4; `get_manifest`) and `application/intelligence.py` (`commit_artifact` validates the reference block, then — create path only, after the replay lookup and before its first write — calls a `recompute_program_reference` callback the service supplies (it opens the Program-read unit of work with the caller's visibility and the total budget, section 7.4), and passes the section to `put_artifact`; the `InMemoryIntelligenceStore` builds the manifest from the value it holds, section 5.2's in-memory note).
- `contracts/v1/programs.py` (the 2 Program answers, `MetricView`), `contracts/v1/commitments_v2.py`, `contracts/v1/report_manifests.py`; `application/commands.py`, `adapters/normalization.py`, `application/service.py` handlers and `_program_plane()`, `domain/identity/operation.py` / `purpose.py` / `chatllm_capability_policy.py` registrations, `adapters/mcp/chatllm_gateway.py` (`"programs": "programs"`), `contracts/ports.py` (`ProgramReadUnitOfWork`, `ProgramMembershipRepository`, `ProgramMetricsRepository`; `IntelligenceStore` manifest methods), `bootstrap/settings.py`, `bootstrap/gateway.py` (the third engine of section 6.3, built only when the switch is on, disposed by `GatewayRuntime`), `application/errors.py` (2 `SafeDetail` members).
- Every W1 §2.2 / §5.4 registration step and count pin applies (capability 229, purpose 60, audit vocabulary 240, revision count 122, head literal and head-pin list, `TABLES_SHA256`, `TABLES_ABOVE`, the principal-partition guard registry for the 3 new persistence modules, the memory-row capability registry if its guard asks, spelled counts in `adapters/cli/app.py`, `bootstrap/gateway.py`, the architecture index and READMEs; `gateway.json` stays 110).
- **Sharded CI.** New test modules are placed by `tests/ci_shard.py` automatically; `tests/architecture/test_ci_shards*.py` and the partition proof stay green, and the worker adding the heavy database modules (AT-018, AT-019, AT-022, the pool test) re-measures them and adds entries to `tests/ci_shard_weights.json` when its guard asks.

**Work split** (serial; each package testable alone; one worker at a time):

| Worker | Owns | Delivers |
| --- | --- | --- |
| **M1** | the revision, `tables.py`, vocabulary, every registry, settings and switch, count pins, `ports.py` stubs, `program_reads.py`, the third engine in `bootstrap/gateway.py` and the `pool_timeout_seconds` parameter of `create_database_engine` (default unchanged) | section 4 in full; `domain/program/vocabulary.py`; registration of all 7 names (unbuilt ones answer `unsupported` until their worker, `capabilities.get` truthful, S3 D-37); the read unit of work, its own pool and the factory wiring; the S1–S3 lockstep moves; tests: S4 migration, S4 integrity guards, admission (FAST rows), the Program pool test |
| **M2** | WP-04A | `domain/program/membership.py`, `application/program_membership.py`, `infrastructure/persistence/program_membership.py`, `contracts/v1/programs.py` (resolve part), the handler; tests: AT-018, the membership rows of the domain test, isolation rows for the resolver |
| **M3** | Commitment v2 | `contracts/v1/commitments_v2.py`, `application/commitments_v2.py`, the 4 handlers, the `project_ids` predicate, the reference states and the batched reads; tests: AT-015, the strict old client, v2 statement counts, the v2 visibility rows |
| **M4** | WP-04B overview | `domain/program/reportability.py`, `domain/program/digest.py`, `application/program_work.py`, `application/program_constraints.py`, `infrastructure/persistence/program_metrics.py`, `contracts/v1/programs.py` (overview part), the handler; tests: AT-019 (with the sync-state and legacy-link rows), snapshot, statement plan and query plans, remote visibility |
| **M5** | WP-04C, hardening, docs | `domain/intelligence/source_manifest.py`, the `reports.commit` delta (block check and the Program-pool recompute before the first write), `reports.manifest` with its family gate, `contracts/v1/report_manifests.py`; tests: AT-022, AT-023 report rows, the S4 scope guard; docs sync ("as implemented" notes), full tiers |

## 10. Acceptance-test crosswalk

Same conventions as S1–S3 §10 (tier = marker selection; FAST = no marker; names binding;
a renamed test updates this table in the same commit; paths new unless marked existing).
`tests/architecture/test_record_lineage_s4_scope.py` parses this table the way the S3
scope guard parses S3 §10.

| AT (S4 part) | Module | Test functions | Tier |
| --- | --- | --- | --- |
| AT-018 | `tests/integration/test_program_member_resolver.py` | `test_three_bound_members_resolve_and_an_unrelated_project_never_does`; `test_a_same_named_unrelated_project_is_never_a_member`; `test_a_redirected_program_and_member_resolve_to_the_survivor`; `test_a_missing_bridge_is_unresolved_and_named`; `test_an_ambiguous_bridge_is_unresolved_never_chosen`; `test_a_non_project_member_is_excluded_and_counted`; `test_membership_outside_its_window_is_excluded`; `test_a_null_start_date_is_historical_membership_unverified`; `test_an_ended_edge_without_an_end_is_historical_membership_unverified`; `test_a_dated_edge_is_a_verified_historical_member`; `test_overlapping_programs_count_a_project_once_at_portfolio_grain`; `test_a_non_program_entity_is_invalid_request`; `test_a_redirect_cycle_is_conflict`; `test_the_edge_budget_answers_truncated_budget`; `test_a_budget_marks_the_cut_program_later_programs_and_the_portfolio`; `test_an_edge_ended_with_a_future_end_is_a_member_until_that_end`; `test_a_nested_program_is_not_expanded`; `test_a_member_entity_status_is_reported_not_filtered`; `test_resolution_writes_nothing` | database |
| AT-015 | `tests/contract/test_commitment_project_scoping.py` | `test_v2_reads_expose_project_and_situation`; `test_v2_list_search_and_waiting_on_filter_by_project_ids`; `test_a_foreign_project_filter_answers_like_an_absent_one`; `test_a_foreign_project_reference_is_never_shown`; `test_v2_marks_native_acceptance_unverified`; `test_a_closed_proposed_commitment_is_never_counted_as_accepted`; `test_an_unrelated_project_never_enters_a_program_count`; `test_a_foreign_principals_commitment_naming_this_project_is_never_counted` (Principal B's Commitment storing A's `prj_` and A's `sit_` appears in none of A's per-Project, Program or portfolio counts and in no `commitments.v2.list` of A with that `project_ids`); `test_v2_pages_issue_a_constant_number_of_statements` | database |
| AT-015 + AT-023 (old strict client) | `tests/contract/test_commitment_v1_strict_client.py` | `test_v1_commitment_answers_are_byte_identical` (with the switch on and Commitments storing a `project_id`); `test_v1_tool_schemas_are_unchanged_by_s4` (the S3 payload-schema SHA over the 192 v1 tools unchanged, **and** an exact pin of the envelope `$defs.Purpose.enum` equal to the basis enum plus exactly `program_reporting_read`); `test_v1_commitment_views_keep_their_keys`; `test_s4_adds_no_gateway_entry` | FAST (the first is database) |
| AT-019 | `tests/integration/test_program_metric_reconciliation.py` | `test_per_project_values_equal_their_native_reads_at_one_cutoff`; `test_every_total_equals_a_direct_distinct_count`; `test_a_shared_issue_is_counted_once_in_program_totals`; `test_per_project_issue_impact_is_flagged_nonadditive`; `test_unverified_acceptance_makes_the_accepted_total_not_reportable`; `test_an_unresolved_member_makes_every_total_not_reportable`; `test_a_never_synced_project_makes_constraint_totals_not_reportable`; `test_a_never_verified_target_is_unverified_not_in_sync`; `test_a_failed_or_partial_last_run_is_sync_degraded_not_in_sync`; `test_a_project_is_in_sync_only_when_every_target_is`; `test_a_sync_conflict_makes_constraint_totals_not_reportable`; `test_a_legacy_issue_link_makes_the_issue_metric_not_reportable`; `test_a_legacy_link_of_a_closed_issue_is_disclosed_and_never_gates`; `test_a_suspended_issue_is_outstanding`; `test_constraint_due_soon_uses_each_projects_own_calendar`; `test_a_project_without_a_calendar_is_disclosed_not_dropped`; `test_constraint_overdue_uses_each_projects_own_calendar`; `test_a_verified_zero_is_reported_as_zero`; `test_the_denominator_names_every_project_state`; `test_the_overview_digest_is_stable_and_sensitive` | database |
| AT-019 (snapshot) | `tests/concurrency/test_program_overview_snapshot.py` | `test_one_overview_reads_one_snapshot` (a Commitment and an Issue link committed by another connection between the overview's statements are absent from it); `test_lineage_known_at_matches_the_issue_links_read` | database |
| AT-019 (plans) | `tests/database/test_program_overview_plans.py` | `test_the_overview_issues_a_constant_number_of_statements`; `test_membership_reads_use_the_relationship_and_bridge_indexes`; `test_metric_reads_are_principal_scoped_aggregates` | database |
| AT-019 (pool) | `tests/concurrency/test_program_read_pool.py` | `test_five_concurrent_overviews_through_the_gateway_pools_complete_without_stall`; `test_ten_concurrent_overviews_queue_on_the_work_pool_and_complete`; `test_a_program_read_never_draws_from_the_work_pool`; `test_a_commit_recompute_draws_only_from_the_program_pool_and_completes_at_five` (5 concurrent `reports.commit` with a block, the barrier method of `tests/concurrency/test_gateway_connection_pool.py`); `test_no_program_checkout_waits_in_the_gateway` | database |
| AT-022 | `tests/integration/test_report_manifest_integrity.py` | `test_every_new_artifact_has_a_manifest`; `test_a_structured_metric_change_with_the_same_markdown_changes_the_manifest`; `test_a_dependency_change_with_the_same_markdown_changes_the_manifest`; `test_the_markdown_digest_is_unchanged`; `test_the_manifest_digest_recomputes_from_the_stored_row`; `test_a_legacy_report_answers_unavailable_and_is_never_rewritten`; `test_a_verified_program_reference_binds_the_server_state_as_the_caller_sees_it`; `test_a_changed_program_source_is_recorded_with_the_server_state`; `test_a_failed_recompute_is_recorded_and_never_refuses_the_commit`; `test_the_recompute_runs_before_the_first_write_on_the_program_pool`; `test_a_refused_commit_never_recomputes`; `test_the_recompute_respects_its_total_budget` (a statement started near the deadline is cancelled at the remaining budget; a checkout wait ends at 1 s; the whole recompute stays within 5000 ms plus round-trip latency); `test_not_attempted_when_programs_overview_is_not_served` (entity plane off, no Program factory, no Constraint factory, each in turn); `test_a_collector_cannot_carry_a_program_reference`; `test_a_collector_candidate_is_never_typed`; `test_a_replayed_commit_writes_no_second_manifest`; `test_the_program_reference_is_ordinary_content_with_the_switch_off`; `test_a_report_reproduces_its_overview_digest_from_an_unchanged_state` | database |
| AT-022 (guards) | `tests/database/test_lineage_s4_integrity_guards.py` | `test_a_manifest_digest_must_be_its_canonical_text`; `test_a_manifest_names_its_own_artifact`; `test_every_artifact_committed_after_s4_has_a_manifest`; `test_manifests_refuse_update_and_delete`; `test_manifests_refuse_truncate` | database |
| AT-012 (migration) | `tests/schema/test_record_lineage_s4_migration.py` | FAST: `test_the_revision_is_the_single_head_on_6f1476b8da52`; `test_the_revision_imports_no_domain_module`; `test_frozen_ddl_names_every_declared_constraint`; `test_before_texts_are_byte_copies_of_the_s3_texts`; `test_at_vocabulary_adds_exactly_the_s4_names`; `test_offline_downgrade_refuses_first`. DB: `test_empty_to_head`; `test_s3_head_with_artifacts_upgrades_and_leaves_them_legacy`; `test_downgrade_refuses_while_s4_rows_exist`; `test_downgrade_restores_every_s3_text`; `test_each_downgrade_refusal_family_alone_refuses` (2 cases) | FAST + migration markers |
| AT-023 (S4) | `tests/contract/test_lineage_s4_capability_admission.py` | `test_s4_capabilities_are_operator_decision_required_reads`; `test_s4_registers_no_report_type_and_issues_no_grant`; `test_switch_off_withholds_every_s4_capability`; `test_program_reads_need_the_entity_plane_and_their_factory`; `test_s4_requests_reject_server_owned_fields`; `test_program_overview_admits_no_as_of`; `test_the_program_purpose_admits_exactly_the_program_reads`; `test_program_overview_needs_the_constraint_plane`; `test_create_database_engine_keeps_its_default_checkout_timeout` (30 s for every existing caller; 1 s only for the Program engine) | FAST |
| AT-023 (S4, DB) | `tests/security/test_program_reporting_isolation.py` | `test_a_foreign_program_answers_like_an_absent_one`; `test_cross_principal_overviews_disclose_nothing`; `test_a_remote_read_without_its_grant_is_unsupported`; `test_a_remote_reader_without_entity_and_project_reads_sees_no_program`; `test_an_invisible_family_is_restricted_never_counted`; `test_an_invisible_constraint_family_hides_every_constraint_derived_field`; `test_an_invisible_issue_family_hides_the_lineage_horizon_and_legacy_links`; `test_v2_references_are_restricted_without_the_project_or_situation_family`; `test_an_issue_situation_reference_needs_the_issue_family`; `test_a_commit_outcome_reveals_nothing_beyond_the_callers_own_overview` (a remote producer missing the commitment family records exactly the totals its own `programs.overview` answers, with Commitment totals `restricted`; a remote producer `programs.overview` does not admit gets `not_attempted` whatever the Program ids name); `test_a_manifest_program_section_needs_every_family_it_was_computed_with`; `test_a_manifest_program_section_needs_the_program_grant`; `test_a_failed_recompute_manifest_needs_the_program_grant_and_entity_family`; `test_a_restricted_manifest_returns_no_digest`; `test_families_seen_names_only_the_overview_families`; `test_switch_off_answers_unsupported_for_every_s4_capability`; `test_a_program_statement_timeout_answers_unavailable` | database |
| (domain) | `tests/unit/test_program_domain.py` | `test_window_rule_table` (current and historical modes apply the same window, including a future end; historical mode additionally separates verified from unverified members, so a null-start active edge is a current member and historically `start_not_recorded`); `test_redirect_walk_bounds_and_cycles`; `test_constraint_source_state_table`; `test_bridge_resolution_counts`; `test_completeness_precedence`; `test_reportability_reasons_table`; `test_commitment_acceptance_proof_is_unverified_for_native_acceptance`; `test_a_proven_acceptance_would_report_the_distinct_total`; `test_overview_digest_golden_vectors` | FAST |
| (domain) | `tests/unit/test_report_manifest_domain.py` | `test_manifest_golden_vectors` (including the exact instant format); `test_structured_content_digest_golden_vectors` (including an already-normal float and a non-ASCII string); `test_program_reference_block_shape`; `test_the_manifest_has_every_key`; `test_candidate_status_by_stage` | FAST |
| AT-026 (S4) | `tests/architecture/test_record_lineage_s4_scope.py` | `test_every_s4_crosswalk_test_exists`; `test_s4_adds_no_record_event_family`; `test_s4_reads_stage_no_record_event`; `test_s4_changes_no_lineage_vocabulary` | FAST |
| AT-026 (regression) | existing `tests/database/test_record_event_provenance.py` | existing `test_unknown_foreign_withheld_and_non_knowledge_events_answer_alike` (unchanged, green) | database |

**S1–S3 regressions (binding, unchanged except lockstep moves):** every test of S1–S3
§10 and every v1 suite. Admitted edits, each keeping its test name and assertion: the
head literal and revision count (121 → 122) in every head-pin file and the head-pin
list (gaining the S4 migration test); count pins (`Capability` 222 → 229, `Purpose` 59 → 60, audit vocabulary 233 → 240, `TABLES_SHA256`, permitted pairs, tool, builder,
command-union, operator-decision counts, docs count claims); registry additions for the
7 names in the suites S2 D-18 (c) lists; `test_existing_v1_shapes_are_unchanged_by_s3`
excludes the S4 names beside the lineage names (its count of 192 v1 tools and both SHA
pins stay), and its purpose-tail assertion moves by exactly 1, nothing removed:
`published[-5:] == [*basis_tail, "lineage_backfill", "program_reporting_read"]` (R4-F04,
R4-F15; the S3 `lineage_backfill` precedent); the S3 migration suite accepts the S4-owned audit texts and runs its
downgrade-refusal tests at `6f1476b8da52`; any migration suite that commits artifacts at
head and then downgrades below `6f1476b8da52` seeds them at its own revision or under
`session_replication_role = replica` instead (S3 D-35 precedent), because the S4
downgrade refuses while a manifest exists; the S3 truncate probes also truncate the new
table with its refusal disabled; intelligence tests that commit artifacts through the
store see a manifest row beside each (no assertion changes). No assertion is removed, no
skip or xfail is added. Also existing and binding: `tests/database/test_intelligence_artifact_plane.py`,
`tests/contract/test_bff_gateway_contract_parity.py`,
`tests/contract/test_bff_success_decoder_parity.py`,
`web/src/lib/api/decode/registry.test.ts`.

**AT-018 / AT-019 fixture, concretely.** One synthetic Principal: Program Entity `G`
(type `program`); 3 Project Entities `B1`, `B2`, `B3`, each bound to a Continuity
Project; an active `member_of` edge from each to `G` (`B1` dated, `B2` with a null start,
`B3` dated and later revised); a 4th Project `U` whose Entity has the **same canonical
name** as `B1`'s and no edge; a 2nd Program `H` with `B3` and `U` as members; a Program
`R` merged into `G`; a member whose bridge is missing and one made ambiguous by merging
2 bound Project Entities; Commitments open/closed × accepted/proposed with and without
`due_at` across the 4 Projects; one Issue linked to `B1` and `B2`, one to `U`, one
`suspended` Issue on `B3`, and an Issue linked to `B2` only by a legacy `project_situations`
row with no membership event and a `closed` Issue linked to `B1` the same way (both
seeded under `session_replication_role = replica`); a Commitment of the 1st Principal
whose `situation_id` names one of its Issues (the global foreign key admits it);
Constraints on Projects whose sync is `in_sync` (a verified target whose last run is
`in_sync`), `never_synced` (no target), `unverified` (a target with `last_verified_at`
null), `sync_degraded` (last run `verification_failed`; and a 2nd Project whose 2
targets are one `in_sync` and one `partial`), `conflict`, and no calendar. A 2nd
Principal holds a copy of every row **and** a Commitment whose `project_id` and
`situation_id` name the 1st Principal's `B1` Project and a context Situation of the 1st
Principal (the global foreign keys admit it, D-16). Expected: `G` resolves to
exactly `B1`, `B2`, `B3` (plus the unresolved members named), `U` never; `R` resolves as
`G`, `redirected`; at a `valid_at` before `B2`'s recorded period, `B2` is
`start_not_recorded`; the portfolio of `G` and `H` holds `B3` once; the `B1`/`B2` Issue
counts once in `G`; the suspended Issue is outstanding; `B2`'s Issue metric and every
Issue total containing `B2` are `issue_link_unverified`; the unverified, degraded and
mixed-target Projects are not `in_sync` and their Constraint totals are not reportable;
the 2nd Principal's cross-referencing Commitment is in no count of the 1st; every total
names its reasons and denominator.

**Prove-red expectations** (break exactly that one guard, show the named test red for
that reason, restore; a green prove-red is reported as redundancy, a masked test or an
unreachable hazard, never as "covered"):

| Guard | Break | Test that must redden |
| --- | --- | --- |
| no name matching | resolve a member also by `canonical_name` | `test_a_same_named_unrelated_project_is_never_a_member` |
| redirect following | stop at a `merged_redirect` entity | `test_a_redirected_program_and_member_resolve_to_the_survivor` |
| ambiguity never chosen | take the first bound row | `test_an_ambiguous_bridge_is_unresolved_never_chosen` |
| member type check | admit any entity type | `test_a_non_project_member_is_excluded_and_counted` |
| window rule | ignore `effective_to` | `test_membership_outside_its_window_is_excluded` |
| null start in historical mode | treat a null start as open | `test_a_null_start_date_is_historical_membership_unverified` |
| portfolio dedup | sum the Programs' Project counts | `test_overlapping_programs_count_a_project_once_at_portfolio_grain` |
| edge budget | remove the bound | `test_the_edge_budget_answers_truncated_budget` |
| Issue distinct total | sum per-Project Issue counts | `test_a_shared_issue_is_counted_once_in_program_totals` |
| nonadditive flag | answer `false` for `issue_outstanding` | `test_per_project_issue_impact_is_flagged_nonadditive` |
| acceptance proof | treat native acceptance as proven | `test_unverified_acceptance_makes_the_accepted_total_not_reportable` |
| proposed never accepted | count closed proposed Commitments as accepted | `test_a_closed_proposed_commitment_is_never_counted_as_accepted` |
| no zero substitution (sync) | report the total for a `never_synced` Project | `test_a_never_synced_project_makes_constraint_totals_not_reportable` |
| unverified target (R4-F01) | treat a target with `last_verified_at` null as `in_sync` | `test_a_never_verified_target_is_unverified_not_in_sync` |
| last-run state (R4-F01) | treat a target whose last run failed as `in_sync` (the `_overview_of` rule) | `test_a_failed_or_partial_last_run_is_sync_degraded_not_in_sync` |
| worst target wins (R4-F01) | take the first target's state | `test_a_project_is_in_sync_only_when_every_target_is` |
| legacy Issue links (R4-F02) | ignore legacy links | `test_a_legacy_issue_link_makes_the_issue_metric_not_reportable` |
| closed-Issue legacy links never gate (R4-F16) | count legacy links of closed Issues in `legacy_issue_links` | `test_a_legacy_link_of_a_closed_issue_is_disclosed_and_never_gates` |
| suspended Issues outstanding | count `open` and `active` only | `test_a_suspended_issue_is_outstanding` |
| future end (R4-F09) | exclude every `ended` edge in current mode | `test_an_edge_ended_with_a_future_end_is_a_member_until_that_end` |
| calendar omission disclosed | drop the calendar-less Project silently | `test_a_project_without_a_calendar_is_disclosed_not_dropped` |
| unresolved membership gate | report totals with an unresolved member | `test_an_unresolved_member_makes_every_total_not_reportable` |
| one snapshot | open the Program read at READ COMMITTED | `test_one_overview_reads_one_snapshot` |
| constant statement plan | read Commitment counts per Project in a loop | `test_the_overview_issues_a_constant_number_of_statements` |
| v2 batching | fetch the follow-up Task per row | `test_v2_pages_issue_a_constant_number_of_statements` |
| owned references | show the stored foreign `project_id` | `test_a_foreign_project_reference_is_never_shown` |
| foreign filter | drop unowned ids from `project_ids` silently | `test_a_foreign_project_filter_answers_like_an_absent_one` |
| Principal scope of the Commitment aggregate (R4-F06) | drop the Principal predicate in the Commitment aggregate | `test_a_foreign_principals_commitment_naming_this_project_is_never_counted` |
| Principal scope of the v2 filter (R4-F06) | drop the Principal predicate in the `project_ids` filter | `test_a_foreign_principals_commitment_naming_this_project_is_never_counted` |
| v1 untouched | add `project_id` to `CommitmentListEntry` | `test_v1_commitment_answers_are_byte_identical`; `test_v1_tool_schemas_are_unchanged_by_s4` |
| remote grant re-check | skip it in `programs.overview` | `test_a_remote_read_without_its_grant_is_unsupported` |
| remote family visibility | count an invisible family | `test_an_invisible_family_is_restricted_never_counted` |
| Constraint-derived fields (R4-F03) | return `calendar`, `constraint_source_state` and the sync denominator to a reader without the constraint family | `test_an_invisible_constraint_family_hides_every_constraint_derived_field` |
| lineage horizon (R4-F03) | return `lineage_known_at` without the issue family | `test_an_invisible_issue_family_hides_the_lineage_horizon_and_legacy_links` |
| v2 reference visibility (R4-F03) | show an owned `project_id` without the project family | `test_v2_references_are_restricted_without_the_project_or_situation_family` |
| own pool (R4-F05) | build the Program read unit of work on the work engine | `test_five_concurrent_overviews_through_the_gateway_pools_complete_without_stall`; `test_a_program_read_never_draws_from_the_work_pool` |
| commit recompute on the Program pool (R4-F05, R4-F14) | run the recompute on a work-pool connection | `test_a_commit_recompute_draws_only_from_the_program_pool_and_completes_at_five` |
| recompute before the first write (R4-F14) | move the recompute after `put_artifact` | `test_the_recompute_runs_before_the_first_write_on_the_program_pool` |
| recompute with the caller's visibility (R4-F14) | recompute with local (full) visibility | `test_a_commit_outcome_reveals_nothing_beyond_the_callers_own_overview` |
| recompute admission (R4-F14) | recompute for a caller `programs.overview` does not admit | `test_a_commit_outcome_reveals_nothing_beyond_the_callers_own_overview` |
| failure recorded, never refused (R4-F14) | refuse the commit on a recompute error | `test_a_failed_recompute_is_recorded_and_never_refuses_the_commit` |
| total budget (R4-F14, R4-F22) | drop the deadline check; or run each statement under the fixed 2000 ms instead of `min(2000, remaining)`; or build the Program engine with the default 30 s checkout timeout | `test_the_recompute_respects_its_total_budget` |
| refusal checks before the recompute (R4-F25) | recompute before `get_cycle` | `test_a_refused_commit_never_recomputes` |
| not served ⇒ not attempted (R4-F24) | admit the recompute on the switches alone | `test_not_attempted_when_programs_overview_is_not_served` |
| gate every attempted recompute (R4-F27) | gate only manifests with a non-null `server` | `test_a_failed_recompute_manifest_needs_the_program_grant_and_entity_family` |
| no digest under restriction (R4-F20) | return `manifest_sha256` under `restricted_evidence` | `test_a_restricted_manifest_returns_no_digest` |
| Program grant on the manifest (R4-F21) | gate `program.server` on families alone | `test_a_manifest_program_section_needs_the_program_grant` |
| overview families only (R4-F23) | record every visible section 6.2 family | `test_families_seen_names_only_the_overview_families` |
| verification compares | record `verified_at_commit` without comparing | `test_a_changed_program_source_is_recorded_with_the_server_state` |
| manifest family gate (R4-F14) | release `program.server` to a reader missing a recorded family | `test_a_manifest_program_section_needs_every_family_it_was_computed_with` |
| Issue reference by kind (R4-F17) | gate every `situation_reference` by the `situation` family | `test_an_issue_situation_reference_needs_the_issue_family` |
| Constraint plane admission (R4-F11) | drop the Constraint-factory condition | `test_program_overview_needs_the_constraint_plane` |
| purpose enum widens by exactly 1 (R4-F04, R4-F15) | add a 2nd purpose, or map a Program read to `report_read` | `test_v1_tool_schemas_are_unchanged_by_s4`; `test_the_program_purpose_admits_exactly_the_program_reads` |
| switch | drop `_program_plane()` in one handler | `test_switch_off_answers_unsupported_for_every_s4_capability` |
| overview digest | omit `per_project` from `D` | `test_the_overview_digest_is_stable_and_sensitive` |
| manifest digest CHECK | drop the CHECK (direct insert) | `test_a_manifest_digest_must_be_its_canonical_text` |
| manifest names its artifact | return NEW unconditionally | `test_a_manifest_names_its_own_artifact` |
| every artifact has a manifest | drop the deferred trigger; the test inserts an artifact row by direct SQL with no manifest and expects the commit refused | `test_every_artifact_committed_after_s4_has_a_manifest` |
| structured content bound | omit `structured_content.sha256` from `M` | `test_a_structured_metric_change_with_the_same_markdown_changes_the_manifest` |
| dependency bound | omit the upstream `structured_content_sha256` | `test_a_dependency_change_with_the_same_markdown_changes_the_manifest` |
| read-back digest | hash the request's parsed value | `test_the_manifest_digest_recomputes_from_the_stored_row` (with a structured value JSONB renormalizes) |
| legacy never rewritten | insert a manifest on a legacy read | `test_a_legacy_report_answers_unavailable_and_is_never_rewritten` |
| server state bound | drop `program.server` from `M` | `test_a_verified_program_reference_binds_the_server_state_as_the_caller_sees_it` |
| collector refusal | admit the block on a collector | `test_a_collector_cannot_carry_a_program_reference` |
| switch-off content | interpret the block with the switch off | `test_the_program_reference_is_ordinary_content_with_the_switch_off` |
| append-only / truncate | detach the trigger | `test_manifests_refuse_update_and_delete`; `test_manifests_refuse_truncate` |
| downgrade refusal, each family | delete that family's clause | the matching case of `test_each_downgrade_refusal_family_alone_refuses` |

**Defence in depth, no prove-red claimed (R4-F06).** The Principal predicate on the
member-edge and bridge reads guards a hazard the schema already makes unreachable: a
foreign Program is refused at step 1, and `entity_relationships` (from, to, scope) and
`project_entity_links` carry principal-composite foreign keys, so every edge into an own
Program and every bridge row is own. Dropping that predicate leaves every test green; it
is kept and not listed as coverage.

**Not S4:** AT-020 and AT-021 → out of scope until OD-06; AT-024 Program web rows → WP-06B.

## 11. Deferred work and its owner

| Item | Owner / reason |
| --- | --- |
| Finance, contract/Owner budgets, CPM, ERP, P6 imports and panels (WP-05A/B, CR-011, CR-012, AT-020, AT-021) | S5, gated by OD-06 source commissioning; `programs.financial.overview` and `programs.schedule.milestones` (package 07) are not built |
| Program dashboard web view (WP-06B) | later web package; S4 adds no route or `gateway.json` entry |
| Task metrics and a responsibility queue in the overview (package 07 `responsibility_queue`) | not in the S4 scope; Task acceptance has its own verified and unverified routes (S2 D-17), so a later package states their rule |
| Verified Commitment acceptance, and with it reportable accepted totals | operator/Work decision (S2 D-05/D-17, S3 D-11); `commitment_acceptance_proof` is the one place it changes |
| A past-dated Program overview | needs native field history the Commitment and Constraint planes do not keep (section 3.4) |
| Knowledge-time (`known_at`) Program membership | needs a knowledge clock on the Entity plane (section 12, D-05) |
| Certified Program totals, any looser OD-08 threshold | operator risk acceptance (OD-08) |
| Ownership checks for `commitments.create` `project_id` / `situation_id` | a v1 Work-plane change; S4 only stops echoing a foreign id (D-16) |
| Commitment "upcoming" / due-soon (CR-010) | no defined window exists for an instant-dated Commitment (`due_at timestamptz`) and no Project calendar applies to it; a later package names the window. Constraints have `constraint_due_soon` (section 3.2; D-26) |
| Certified Program totals in a manifest or anywhere | operator risk acceptance (OD-08); S4 records the server's recomputed state at commit as the committing caller sees it, uncertified (D-09) |
| A dedicated pool for the existing Constraint, Task and Commitment unit-of-work factories (each a second work-pool checkout today) | a pre-existing composition residual of the Work and Constraint planes, not widened by S4 (section 6.3); operator item (section 13) |
| A backfill of manifests for legacy artifacts | not planned: a manifest is evidence of what was bound at commit and cannot be reconstructed honestly |
| Remote exposure of any S4 name | OD-07 operator decision |

## 12. Divergences — repository vs package, and resolutions

| # | Package says | Repository truth | Resolution |
| --- | --- | --- | --- |
| D-01 | 2 reads `programs.work.overview` and `programs.constraints.overview` (07, plan line 170) | Work and Constraint metrics read different planes; 2 reads would be 2 snapshots and 2 digests | one `programs.overview` over one snapshot with one digest (sections 3.4, 5.1); the 2 package modules stay as `application/program_work.py` and `program_constraints.py` |
| D-02 | CR-010 / 07: v2 via negotiated `contract_version: v2` and a v2 envelope | the envelope pins `CONTRACT_VERSION = "v1"`; MCP tool schemas derive from command fields and S3 pins their SHA; S2: "a composite is a new name, not a mode" | sibling capabilities `commitments.v2.*`; no existing command, tool schema or envelope changes (section 8) |
| D-03 | v2 fields `evidence_state`, `accepted_at?`, `coverage` | no `accepted_at` column; `coverage` has no Commitment-level meaning | `accepted_at` omitted (never sourced); `acceptance_verification`, `project_reference`, `situation_reference` added; `evidence_state` added to the list entry |
| D-04 | count accepted/open "where acceptance is proven" | no capability-reachable route verifies a Commitment's acceptance (S2 D-05/D-17, S3 D-11); counting proven ones would give a false zero | accepted Program totals are `not_reportable` / `acceptance_unverified`; per-Project accepted figures are shown, marked unverified; one pure function changes when the Work decision lands |
| D-05 | resolver `known_at`, `membership_mode`, `page_size`, `cursor`; overview `as_of` | the Entity plane has no knowledge clock and revises effective windows in place; native planes keep no field history | resolver: `valid_at` over the currently recorded window, `membership_record: "current"`, bounded single answer (10 Programs, 100 Projects, 400 edges); overview: current only |
| D-06 | `linkage_state = bound` ambiguity and missing bridges | `project_entity_links` admits one bound row per entity, and unresolved rows carry no entity id; a merge does not rewrite the bridge | ambiguity arises only through redirects and is surfaced (`bridge_ambiguous`); an unresolved bridge row is unreachable from the member side and reads `bridge_missing` |
| D-07 | "reuse … five focus areas" | the catalog admits 9 focus areas and expects 6 (`EXPECTED_FOCUS_AREAS`, including `project_program_pulse`) | unchanged; S4 adds no focus area, stage or report type |
| D-08 | CR-013: manifest fields on `reports.commit` / a versioned structure | `reports.commit` / `reports.read` are live v1 shapes; artifact body columns are trigger-immutable | a separate immutable companion table and a new `reports.manifest` read; v1 report answers unchanged |
| D-09 | the manifest binds the Program membership set, versions, cutoffs and completeness the report was built from (CR-013, WP-04C) | `structured_content` is bounded to 64 KiB, too small for a copied overview; a copy would prove nothing the server did not compute | a reference block (section 5.4) plus a **server recompute at commit** through the dedicated Program pool, before the commit's first write, with the committing caller's visibility and a 5000 ms total budget (section 7.4); the manifest binds the claim and the server's membership set, versions, cutoff, completeness and totals as that caller sees them, plus `families_seen`; `reports.manifest` releases that section only to a reader who sees every one of those families. Uncertified: certification is OD-08-gated. (An intermediate revision bound the claim only; R4-F14 refuted its premises — the Program pool cannot deadlock against the work pool, and a recompute under the caller's own visibility is no oracle.) |
| D-10 | AT-022: "source hash mismatch refused" | a Program's state legitimately moves between a producer's read and its commit; a commit must not fail because the Program plane is slow | a malformed block is refused; a digest mismatch is recorded `changed_since_read` with the server's state beside the claim; a failed recompute is recorded `recompute_failed`; neither refuses; the existing `advisory_digest` mismatch refusal is unchanged |
| D-11 | 07 `coverage_state` (`complete`, `partial`, `not_reportable`, `not_configured`, `never_synced`, `stale`, `unavailable`, `verified_zero`) | the portfolio read model derives 3 health states (and reads a never-verified or failed target as `in_sync`); the stored data has `last_verified_at` and 10 persisted run outcomes per target (R4-F01) | `value_state` + `reasons` + `ConstraintSourceState` derived from targets and their last runs (section 3.3: `in_sync`, `never_synced`, `unverified`, `sync_degraded`, `conflict`, `calendar_unconfigured`); `stale` / `unavailable` map to `sync_degraded` through the run state; a verified zero is a `reported` 0 |
| D-12 | 07 work overview with Task grain and a `responsibility_queue` | the S4 brief scopes Commitments, Issues and Constraints | deferred (section 11) |
| D-13 | S3 §3: `LineageCompleteness` gains `not_reportable`, `source_not_integrated` for Program work | Program answers are not lineage reads; widening would move the S3 web decoders' closed sets | `ProgramCompleteness` and `MetricValueState` in `domain/program/vocabulary.py`; lineage vocabulary unchanged |
| D-14 | CR-010: Commitment upcoming/overdue on the Project's civil day | `commitments.due_at` is an instant; the Project calendar lives in `constraint_project_settings` and governs date fields | Commitment overdue compares instants; Constraint dates use each Project's own calendar (PC-CM-RUN01-WP06 path) |
| D-15 | "only Program-typed Entity → Project-typed" by the edge model | `member_of` is seeded with no source or target type | the resolver checks both terminal types (section 3.1 steps 1 and 4) |
| D-16 | add `project_id` to public Commitment reads | `commitments.project_id` / `situation_id` carry global foreign keys and `commitments.create` checks only their pattern, so a stored id may name another Principal's record | v2 shows owned references only (`not_owned` otherwise); fixing the v1 writer is deferred |
| D-17 | AT-018/AT-019/AT-022/AT-023 paths and markers | tiers select by marker; S3 used slice-specific modules | the section 10 modules (AT-015 keeps the package path) |
| D-18 | WP-06B Program view | the S4 brief: minimal web exposure | none in S4 (section 7.6) |
| D-19 | 07 `excluded_inactive_count`, `authorization_state`, `source_run_ids` | no per-metric source run exists for native planes | explicit `excluded` counts, `reasons`, `denominator` and `constraint_sync` |
| D-20 | equality "at a common cutoff" by a source watermark | native planes have no commit-ordered clock (S3 D-01); S3's marks cover lineage facts only | one `REPEATABLE READ READ ONLY` snapshot is the cutoff; the lineage horizon is reported as `lineage_known_at` |
| D-21 | admission flag off by default (CR-015) | a manifest is bookkeeping of a live write, not an exposure; recording it only while a switch is on would leave post-revision artifacts unbound forever | manifests are written for every new artifact; only the reads and the Program-reference interpretation are behind the switch |
| D-22 | no N-Project fan-out; batched server reads | v1 `commitments.list` / `waiting_on` read a counterparty and a follow-up per row | the v2 siblings batch per page; the v1 reads are not changed (byte-identical rule) |
| D-23 | manifest binds "metric schema and versions" | `intelligence_artifacts.evaluation_*` columns exist and no code writes them | not in the manifest; the Program metric schema and calculation versions are |
| D-24 | 07 errors `source_unavailable`, `limit_exceeded` | the repository's codes are `unavailable` and `invalid_request` for bounds | repository codes (section 7.5) |
| D-25 | totals of `constraint_overdue` / `constraint_due_soon` | `ConstraintPortfolioOverview` states its per-Project counts "are not summable … an addition across different days" (R4-F07) | S4's total is not a sum of counts taken against one day: it is the distinct count of Constraints, each classified overdue (or due soon) on **its own** Project's calendar at the one snapshot instant — a well-defined set, so `nonadditive_across_projects` stays `false`; the per-Project `project_today` is shown beside it |
| D-26 | CR-010 "upcoming/overdue" | Constraints carry `due_soon` in the overview facts; Commitments have only an instant `due_at` and no calendar | `constraint_due_soon` added; Commitment upcoming deferred (section 11) |
| D-27 | package 07: a Program purpose | every MCP tool's input schema carries the envelope purpose enum, so a new purpose widens all 222 existing tool schemas' purpose enum (R4-F04); the repository's D-91 rule names purposes by data domain (R4-F15) | `program_reporting_read` added; the enum widening is stated (section 8) and the S3 purpose-tail assertion is an admitted lockstep edit (section 10), as S3's `lineage_backfill` was |
| D-28 | issue impact over native Project links | Issue-kind `project_situations` rows without a membership event exist (S1 §12 row 3, S3 §8.3 `project_situation_inconsistent`, package UB-005) | counted per Project as `legacy_issue_links`; any one makes the Issue metric `issue_link_unverified` at that Project and every scope holding it (section 3.3, R4-F02) |
| D-29 | Program reads on the request's transaction or the Constraint precedent's work-pool factory | a second work-pool checkout per request deadlocks at `C = P` (`bootstrap/gateway.py`, `tests/concurrency/test_gateway_connection_pool.py`) | a third engine with its own pool for Program reads only, the audit-engine fix; no cycle in the wait-for graph (section 6.3, R4-F05) |

## 13. Operator gates that remain

Ratification of ADR-015 beyond the directive defaults; any live migration, grant,
ChatLLM or client exposure, deployment (OD-07); enabling `MY_PA_PROGRAM_REPORTING_ENABLED`
anywhere but a test; any certified Program total or looser completeness threshold
(OD-08); verified
Commitment acceptance as a Work decision (D-04); finance, CPM, ERP and P6 source
commissioning (OD-06); a Program web view (WP-06B); the pre-existing second work-pool
checkout of the Constraint, Task and Commitment factories (section 11) and the size of
the new Program pool in production and the per-process backend budget it raises (5 more
backends per process that composes it — the gateway goes from 10 to 15 — section 6.3;
the `create_database_engine` default of 5 is the contract's assumption); S3.1
(attestation, held).
Nothing else in S4 is left for a worker to decide beyond local naming with no incumbent
constraint.
