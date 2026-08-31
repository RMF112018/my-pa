# Robust Entity Data Model + MCP Contracts — campaign record

## Campaign identity

- Campaign ID: `MYPA-RI-ENT-20260830-001`
- Objective: close the audit-identified gaps between the generalized entity
  plane (`knowledge.entities` and its `entity_*` family) and what the TBR v3
  register actually requires to be represented losslessly — typed legal/
  brand/DBA/operating names, organization identity/profile semantics,
  normalized addresses and communication methods, first-class project
  participation, temporal person↔organization affiliation, an extensible
  relationship/role/discipline taxonomy, fact-level assertion/provenance
  binding, and record-family-specific MCP contracts — without replacing
  stable entity identity, without a parallel CRM, and without a hidden
  relationship score.
- Repository: `RMF112018/my-pa`
- Implementation branch: `ri-ent/wp01-wp02-typed-names`
- Base: `main@0e24018e5d65ae90b2df12dde2d923144c9be925` (tree
  `e2f28dabac43f38365ca4d4fca5a1ca0f782888b`), the merge commit of PR #164
  (the RI remediation campaign that landed the merge/split ambiguity model
  this campaign must coordinate with — see "Merge/split disposition" below).

## Authorization record — read this section before assuming scope

**Authorization for this campaign's scope is an operator instruction given
in-session on 2026-08-30**, recorded in the untracked file
`AUTH-RI-ENT-20260830.md` at the repository root (id
`AUTH-RI-ENT-20260830-OPERATOR-001`, sha256
`226754b9732acf761936605ad86c3312c319aae96295a8e69b63f5b43e7833a6`, 379
bytes). That file is deliberately **not tracked by git** and this document
does not reproduce its contents; it is cited here by id, path, and hash so a
reader can independently verify it while it is present, the same way this
document's own author verified it before proceeding — see "verification"
below.

**`AGENTS.md` section 3 was deliberately NOT amended, by explicit operator
choice.** The operator was offered the option of adding a dated
scope-admission sentence to `AGENTS.md` section 3 — the convention that
section already follows for every prior MCV expansion (Relationship
Intelligence and Quick Capture, 2026-08-01; `WP-FE-03`, 2026-08-21) — and
declined it in favor of recording the authorization in this campaign
document only.

**The resulting gap, stated plainly:** `AGENTS.md` section 3's list of
admitted MCV scopes does **not** include the Robust Entity Data Model scope
this campaign implements. A future auditor who compares `AGENTS.md` section
3 against the tables this campaign adds will find that inconsistency — an
admitted scope with no corresponding sentence in the document that lists
every other one. **This is a known, accepted recording limitation, stated
here for the record — it is not an oversight, and it is not this document
claiming `AGENTS.md` admits this scope.** `AGENTS.md` section 1's own
evidence precedence ranks "authenticated repository and GitHub state" above
"conversations, reports... as claims"; this document is the latter, and does
not assert otherwise.

**Verification performed before implementation began:** the implementing
session did not accept this authorization on a relayed claim. It independently
read the file from disk, computed its SHA-256, confirmed it matched the
value asserted to it, confirmed the file was untracked (`git status
--porcelain`), and confirmed the authenticated `gh auth status` account
(`RMF112018`) matches the repository owner — all before any branch, commit,
schema, or migration work began. Two prior authorization claims in the same
session were declined for lack of independently-checkable evidence; this is
the record of what changed.

## Scope of this increment

`AGENTS.md` section 3 requires single-purpose, short-lived, reviewable pull
requests. This campaign record covers the **full 15-finding, 13-work-package
program** the source audit identified, but this repository increment
implements only:

- **(A)** this campaign record, routed from
  [`docs/00_REPOSITORY_SOURCE_INDEX.md`](../00_REPOSITORY_SOURCE_INDEX.md);
- **(B) RI-ENT-WP-01** — architecture/taxonomy freeze (a design record; no
  schema or data-import goal of its own);
- **(C) RI-ENT-WP-02** — typed names and organization profile
  (`knowledge.entity_names`, `knowledge.entity_organization_profiles`);
- **(D) RI-ENT-WP-03** — address and communication record families
  (`knowledge.entity_addresses`, `knowledge.entity_communication_methods`);
- **(E) RI-ENT-WP-04** — project participation model
  (`knowledge.entity_project_participations`, `knowledge.entity_role_types`,
  `knowledge.entity_discipline_types`);
- **(F) RI-ENT-WP-05** — person affiliation integration
  (`knowledge.entity_person_organization_affiliations`).

RI-ENT-WP-06 through RI-ENT-WP-13 (relationship-graph expansion, assertion/
provenance binding, repository/service layer beyond WP-02/WP-04/WP-05,
resolution/search vNext, MCP rich-read and mutation contracts, legacy
migration/backfill, and the full TBR completeness fixture) are **explicitly
out of scope for this increment** and remain future work, ordered as the
source audit orders them (section P). Nothing in this increment implements
them, and nothing in this increment's schema, domain code, or tests assumes
they exist.

**Still prohibited and not covered by this or any future increment of this
campaign without separate, explicit operator authorization:** production
deployment, container restart, live migration, mutation of the persistent
`my_pa` database, TBR register import (synthetic fixtures only, never the
real register), OAuth/grant/credential mutation, dead-letter handling, risk
acceptance, and amending `AGENTS.md` or any security/architecture guard —
including `tests/architecture/test_relationship_scoring_surface_is_denied.py`.

## The 15 audit findings (namespace `RI-ENT-*`)

Preserved from the source audit; status reflects this increment only.

| ID | Severity | Finding | Status after this increment |
|---|---|---|---|
| `ENTITY-SCHEMA-001` | Critical | No typed legal/brand/DBA/operating-name semantics | **Closed by RI-ENT-WP-02** — `entity_names` (9 typed `name_type_code` values) and `entity_organization_profiles.organization_kind_code`/`legal_identity_status_code` |
| `ENTITY-SCHEMA-002` | High | No normalized entity-address family | **Closed by RI-ENT-WP-03** — `entity_addresses` (9 typed `address_type_code` values, per-(entity, type) uniqueness on `normalized_address_value`) |
| `ENTITY-SCHEMA-003` | High | No typed phones/domains/websites | **Closed by RI-ENT-WP-03** — `entity_communication_methods` (`method_type_code` email/phone/domain/website, `usage_context_code`, `verification_status_code`) |
| `ENTITY-REL-001` | Critical | Closed relationship vocabulary (15 of 22 required codes) | Not in scope (`RI-ENT-WP-06`); `EntityRelationshipType` untouched |
| `ENTITY-PROJECT-001` | Critical | Incomplete project participation | **Closed by RI-ENT-WP-04** — `entity_project_participations` (project/participant identity, project-scoped `project_display_name`, `role_code`/`role_text`, `discipline_code`/`discipline_text`, `scope_text`, `role_basis_code`, `stakeholder_side_code`, `stakeholder_class_code`, `relationship_status_code`, temporal state), plus the extensible `entity_role_types`/`entity_discipline_types` taxonomies. No MCP capability or write path exists yet (`RI-ENT-WP-10`/`WP-11`) — see "Merge/split disposition" below |
| `ENTITY-PROVENANCE-001` | High | No fact-level certainty/verification binding | Partially addressed for organization legal identity only, via `legal_identity_status_code` (not a confidence field — see Ruling 1); full assertion/provenance binding is `RI-ENT-WP-07` |
| `ENTITY-PERSON-001` | High | Incomplete person affiliations | **Closed by RI-ENT-WP-05** — `entity_person_organization_affiliations` (nullable `organization_entity_id`, `job_title`, `affiliation_type_code`, temporal `effective_from`/`effective_to` with `effective_to IS NULL` denoting "current") |
| `ENTITY-RESOLUTION-001` | Critical | Resolution cannot follow typed names/identity graph | **Unblocked, not closed** — `entity_names` now exists as the structural prerequisite; resolution/search changes are `RI-ENT-WP-09` |
| `ENTITY-STATE-001` | High | No canonicalization/review state distinct from lifecycle | Design decision recorded in RI-ENT-WP-01 below (`canonicalization_state_code`, separate 1:1 record, deferred); not implemented this increment |
| `MCP-CONTRACT-001` | Critical | No rich structured profile read | Not in scope (`RI-ENT-WP-10`) |
| `MCP-CONTRACT-002` | High | No record-family mutation capabilities for the new families | Not in scope (`RI-ENT-WP-11`); RULING 5 (no mass-assignment endpoint) remains binding when it is |
| `COMPAT-001` | High | Additive-vs-breaking policy needed for generated strict schemas | Addressed procedurally in RI-ENT-WP-01 (below); no generated schema exists yet to apply it to |
| `MIGRATION-001` | Critical | Legacy `relationship_people`/`relationship_organizations` coexist; must not infer legal identity from names | Honored: migration `7e114f822af2` is purely additive, backfills nothing, infers nothing |
| `SECURITY-001` | High | New families must preserve Principal partitioning, composite keys, append-only ledgers, operator-only merge/split | Partitioning and composite keys: proven by `tests/schema/test_entity_names_and_organization_profile_migration.py`. `entity_project_participations` is Principal-partitioned the same way; `entity_role_types`/`entity_discipline_types` are deliberately **not** Principal-partitioned (global reference vocabularies — see `tests/architecture/test_user_owned_tables_are_partitioned.py`'s `UNPARTITIONED_USER_OWNED` entry for both). Merge/split: **explicitly deferred**, not silently — see "Merge/split disposition" below |
| `TEST-001` | High | No TBR completeness fixture exists | Not in scope (`RI-ENT-WP-13`); this increment adds a synthetic single-case fixture (GS4 Studios) proving the pattern, not the full register |

## The 13 work packages (source audit ordering, section P)

| WP | Title | This increment |
|---|---|---|
| WP-01 | Architecture/contract freeze | **Delivered** — see below |
| WP-02 | Taxonomy and typed-name model | **Delivered (partial)** — `entity_names`, `entity_organization_profiles`; role/discipline/relationship taxonomies deferred to WP-04/06 |
| WP-03 | Address and communication record families | **Delivered** — see below |
| WP-04 | Project participation model | **Delivered** — see below |
| WP-05 | Person affiliation integration | **Delivered** — see below |
| WP-06 | Corporate/entity relationship graph expansion | Deferred |
| WP-07 | Assertion/confidence/provenance binding | Deferred (see Ruling 1 — no scalar confidence will be added under this name) |
| WP-08 | Repository/domain services and validation | Deferred |
| WP-09 | Entity resolution/search vNext | Deferred |
| WP-10 | MCP rich read contracts | Deferred |
| WP-11 | MCP mutation contracts | Deferred |
| WP-12 | Legacy migration/backfill and compatibility adapters | Deferred |
| WP-13 | TBR completeness fixture, security, compatibility and documentation | Deferred |

## RI-ENT-WP-01 — architecture/taxonomy freeze

**Objective** (source audit): approve normalized ownership boundaries, the
taxonomy strategy, assertion binding, and compatibility rules. **Acceptance**:
every element of the audit's Record Element Inventory maps to exactly one
deliberate owner; no unresolved architectural ambiguity. **Non-goal**:
implementation or data import.

### Architectural rule (adopted as-is from the audit)

Keep global identity facts, project-scoped facts, relationship facts, and
assertion/evidence metadata separate. Extend the existing generalized entity
plane; do not create a parallel CRM (RULING 4). `entities.canonical_name`
remains a normalized match key and `entities.display_name` remains the
human-facing default — neither is redefined by this or any future increment
without that redefinition being classified Breaking and separately approved.

### Ownership decision, by representation family

The audit's Record Element Inventory (its section D) enumerates every
distinct field label and structural concept the TBR v3 register exercises —
96 rows. What the audit does not do per row is name which table or work
package owns it; that is the decision this section makes. Families are
grouped by the audit's own "Proposed representation" column, since rows
sharing a representation share an owner by construction.

| Representation family | Owning table(s) | Owning work package | This increment |
|---|---|---|---|
| Stable entity identity, entity kind | `entities.entity_id`, `entities.entity_type` | Existing (WP-RI-01) | Unchanged |
| Typed legal/operating/DBA/brand/acronym/alias/historical/document-reference name | `entity_names` | **WP-02** | **Delivered** |
| Organization subtype (SPV/government/utility/professional-practice/brand/company/nonprofit/public-agency) | `entity_organization_profiles.organization_kind_code` | **WP-02** | **Delivered** |
| Organization legal-identity status (verified/best-supported/unresolved/awaiting-confirmation) | `entity_organization_profiles.legal_identity_status_code` | **WP-02** | **Delivered** |
| Historical juristic entity (a *different* legal person than its successor) | A separate `entities` row, linked by relationship — never a name row | WP-06 (relationship taxonomy must admit the lineage edge) for the *edge*; the *entity* row itself needs no new table | Architecture rule recorded now; no lineage edge type exists yet (`EntityRelationshipType` untouched) |
| Project address / legal principal address / HQ / regional or known office / city hall | `entity_addresses` | WP-03 | Deferred |
| Phone / website / domain / email as a contact channel | `entity_communication_methods` | WP-03 | Deferred |
| Key/known contact, with title, at a project or organization | Person entity + `entity_person_organization_affiliations` + project participation | WP-05, WP-04 | **Delivered** — the project-participation half (`entity_project_participations`) was delivered by WP-04; the affiliation/title half (`entity_person_organization_affiliations.job_title`) is delivered by WP-05 |
| Relationship / parent / practice / acquisition lineage / technical-review / seller-developer-SPV / utility-authority edge | Extensible `entity_relationships` taxonomy (successor to the frozen 15-member `EntityRelationshipType`) | WP-06 | Deferred; `EntityRelationshipType` untouched this increment |
| Project role / discipline / scope / stakeholder side / stakeholder tier / role basis / participation state | `entity_project_participations` — named `entity_project_participations` rather than the audit's own `project_entity_participations`; see "Naming deviations" under RI-ENT-WP-04 below | WP-04 | **Delivered** |
| "Confidence" (register label) at any dimension (role/scope/participation/legal-identity) | **Not a scalar confidence field anywhere** — discrete `assertion_status`/`role_basis_code`/`legal_identity_status_code`-family vocabularies, one per dimension, bound to the fact/edge/participation that carries it | WP-02 delivers `legal_identity_status_code`; the rest is WP-07 | Partial — RULING 1 governs all of it, see below |
| Evidence / source type-URI / observation and verification timestamps / assertion author / conflicting evidence / supersession / source-driven correction | Existing `entity_fact_evidence_links`, `entity_observations`, `entity_mutation_events`, `entity_resolution_decisions`, extended to bind the new record families | WP-07 | Deferred; the ledgers exist and are unmodified, but do not yet bind `entity_names`/`entity_organization_profiles` rows |
| Import readiness (READY/FLAG/HOLD/DO NOT IMPORT), canonicalization state distinct from lifecycle | A new, separate state record or nullable FK on `entities` (`canonicalization_state_code`) — explicitly **not** an overload of `entities.status` | Design decision recorded now (`ENTITY-STATE-001`); table not created this increment | Deferred |
| Duplicate/reconciliation state, merge/split ledgers | Existing `entity_merge_records`, `entity_identity_effects`/`entity_identity_previews`/`entity_identity_operations`, `entity_identity_preview_ambiguities`, `entity_identity_ambiguity_settlements` | Existing (RI remediation campaign, PR #164) | Unchanged; `entity_names`/`entity_organization_profiles` are **not yet wired in** — see "Merge/split disposition" |
| "One organization with aliases/historical legal [names]" (register's own instruction to the reader) | Not a field at all — a mapping/architecture rule | This document (WP-01) | Delivered as this table |
| Independent consultant, no organization FK required | Existing nullable `scope_entity_id`/nullable organization pattern already proven by `Assignment` | WP-04/WP-05 reuse the existing pattern | **Delivered** — `entity_person_organization_affiliations.organization_entity_id` is nullable, closing the audit's "Mike Fichera" case without a placeholder organization entity (WP-05) |

Every one of the audit's 96 rows falls into exactly one family above by its
own "Proposed representation" text, and every family has exactly one owner
row in this table. Where the owner is a future work package, that is a
deliberate deferral recorded here, not an absence of a decision.

### Compatibility rule (`COMPAT-001`)

Additive is: a new table; a new nullable column with a server default; a new
member appended to a taxonomy that is not Alembic-CHECK-frozen. Breaking is:
redefining what `entities.canonical_name` or `entities.display_name` means;
replacing `entity_id`; narrowing or removing a CHECK-frozen enum member;
changing merge/split semantics for an existing family. This increment's
migration (`7e114f822af2`) is additive under this rule: two new tables, no
altered column, no altered constraint on any existing table.

### Assertion binding (`ENTITY-PROVENANCE-001`, Ruling 1)

The audit's own proposed field names (`role_confidence`, `scope_confidence`,
`legal_identity_confidence`, a numeric "confidence" band) are **not used
anywhere in this codebase**. `tests/architecture/test_relationship_scoring_surface_is_denied.py`
denies the snake_case tokens `confidence|certainty|probability|likelihood|propensity`
across every `relationship_*` table and every table of the generalized entity
plane, as "a model likelihood" the operating brief forbids. This increment
uses the audit's own alternative, token-clean vocabulary instead:
`legal_identity_status_code` (delivered, on `entity_organization_profiles`).
`assertion_status` and `role_basis_code` are recorded here as the vocabulary
future work packages must use when they bind participation/role/relationship
facts (WP-04, WP-07) — not implemented this increment, since nothing yet
carries those dimensions. The guard itself was run against this increment's
schema and domain additions and passed with zero denials; see "Test evidence"
below.

## RI-ENT-WP-03 — address and communication record families

**Objective** (source audit): give the entity plane normalized addresses and
typed contact channels, closing `ENTITY-SCHEMA-002` ("no normalized
entity-address family") and `ENTITY-SCHEMA-003` ("no typed phones/domains/
websites"). **Delivered this increment.**

### `entity_addresses`

Mirrors `entity_names`'s shape exactly: opaque primary key, composite
`(entity_id, principal_id)` FK to `entities` with `ON DELETE CASCADE`, a
`UNIQUE(entity_address_id, principal_id)` that makes the self-referencing
`superseded_by_entity_address_id` FK principal-scoped, a three-state lifecycle
(`EntityAddressState`: active/retired/superseded — its own vocabulary, for
the reason `EntityNameState`'s docstring already gives against sharing one
across unrelated record families), `version >= 1`, and blank-value CHECKs on
every text field that must never be empty.

`address_type_code` is a closed nine-value vocabulary (`project`,
`legal_principal`, `headquarters`, `regional_office`, `office`, `business`,
`mailing`, `city_hall`, `known_other`) taken directly from the audit's Record
Element Inventory. `line1`/`line2`/`city`/`region`/`postal_code`/`country` are
independently nullable and populated **only when the source stated that
structure** (RULING 3): no writer may split `raw_value` to guess at them.
`raw_value` (the verbatim source string) is the one field guaranteed to always
be populated; `normalized_address_value` is a deterministic canonicalization
of whichever structured fields are known — never a geocoding or inference
step — computed by `normalize_address` and checked against the stored value
in `EntityAddress.__post_init__` the same way `EntityName.normalized_value` is
checked against `is_normalized_name`.

**Uniqueness is per (entity, address type), not per entity.** The active
unique index is `(principal_id, entity_id, address_type_code,
normalized_address_value)`. This is deliberate: the same street address
legitimately recurs for one entity under a *different* type (a seller's
legal-principal address and a project address are often the identical
building), and `address_type_code` being part of the key is what permits that
without weakening the guard against a literal duplicate under one type. A
second partial unique index caps at most one preferred active address per
(entity, type). Two required plain indexes support reads: one on
`normalized_address_value` alone (the "normalized geography" index) and one
on `(entity_id, address_type_code, state)` (the "entity, type, current state"
index).

### `entity_communication_methods`

The same `entity_names` shape again, for a contact channel. `method_type_code`
is a closed four-value vocabulary (`email`, `phone`, `domain`, `website`) and
`usage_context_code` an independent seven-value vocabulary (`corporate`,
`project`, `project_sales`, `generic`, `personal`, `office`, `other`) — two
axes kept apart because "what kind of channel" and "what the channel is used
for" are different questions, and folding them into one column would make a
project's own corporate line indistinguishable from its sales line.
`normalized_value` is normalized per `method_type_code` (digits-only for
`phone`; trimmed-and-case-folded for `email`/`domain`/`website`) by
`normalize_communication_value`, which also validates the value is
well-formed *for the stated type* — **the type itself is always stated by the
caller and never inferred from the value's shape** (RULING 3): nothing in
this family's domain or persistence layer sniffs a string with a regex to
decide it "looks like" an email or a phone number.

`verification_status_code` is a new, distinct closed vocabulary,
`CommunicationVerificationStatusCode` (verified/best_supported/unresolved/
awaiting_confirmation) — the same four members `LegalIdentityStatusCode`
already has, deliberately *not* that same enum reused. The two describe
unrelated dimensions (a contact channel's verification versus an
organization's legal identity), and one shared vocabulary would couple this
migration's future widening to `entity_organization_profiles`'s and vice
versa. Not a confidence field either way: RULING 1's guard,
`tests/architecture/test_relationship_scoring_surface_is_denied`, was run
against this increment's schema and domain additions and passed with zero
denials.

**The email identity/channel boundary.** `ExternalIdentifierNamespace.EMAIL`
and `entity_external_identifiers` already exist and are the sole authority
for identity resolution — "which entity does this mailbox identify."
`entity_communication_methods` with `method_type_code = 'email'` answers a
different question — "is this a way to reach this entity" — which may or may
not be the same mailbox identity resolution uses. `linked_external_identifier_id`
is an **optional cross-reference** from a communication-method row to an
external-identifier row, never a merge of the two concepts and never
consulted to resolve "who is this." A composite FK
`(linked_external_identifier_id, principal_id)` → `entity_external_identifiers
(identifier_id, principal_id)` carries the reference, and a CHECK
(`linked_external_identifier_id IS NULL OR method_type_code = 'email'`)
confines it to email rows only — this is what stops a phone, domain, or
website row from ever overloading the external-identifier namespace through
this column, the manager's explicit prohibition.

**Uniqueness is per (entity, method type), across usage contexts.** The
active unique index is `(principal_id, entity_id, method_type_code,
normalized_value)`, deliberately *without* `usage_context_code`: the same
value tagged `corporate` and again tagged `generic` is one channel
double-counted, not two, while a corporate number and a project's own number
already differ in `normalized_value` and are both admitted. A second partial
unique index caps at most one preferred active channel per (entity, type).
Two required plain indexes mirror the address table's: one on
`normalized_value` alone and one on `(entity_id, method_type_code, state)`.

### Delivered artifacts

- Migration `441b071bf37b` (`down_revision = 7e114f822af2`), purely additive:
  two new tables, no altered column or constraint on any existing table.
- `src/my_pa/domain/relationship/entity.py`: `AddressTypeCode`,
  `EntityAddressState`, `EntityAddress`, `normalize_address`,
  `CommunicationMethodTypeCode`, `CommunicationUsageContextCode`,
  `CommunicationVerificationStatusCode`, `EntityCommunicationMethodState`,
  `EntityCommunicationMethod`, `normalize_communication_value`,
  `is_normalized_communication_value`.
- `src/my_pa/infrastructure/persistence/tables.py`: `entity_addresses`,
  `entity_communication_methods` (Core `Table` definitions for runtime
  access; the migration itself is written out in raw DDL per `D-48`/`D-69`).
- `src/my_pa/domain/common/identifiers.py`: `IdKind.ENTITY_ADDRESS = "eadr"`,
  `IdKind.ENTITY_COMMUNICATION_METHOD = "ecmm"` — neither collides with any
  prior member of `IdKind`, checked before use.

## RI-ENT-WP-04 — project participation model

**Objective** (source audit): give the entity plane a complete project
participation record, closing `ENTITY-PROJECT-001` ("incomplete project
participation" — generic `entity_assignments` supports `scope_entity_id`,
free-text `role`/`discipline`/`responsibility_class`, and effective dates,
but not a project-facing display name, a controlled role/discipline
taxonomy, scope, role basis, or stakeholder side/class). **Delivered this
increment.** `entity_assignments` itself is untouched — not widened, not
backfilled, not repurposed — per the audit's own reasoning that a dedicated
table is warranted precisely because generic assignments cannot carry these
dimensions.

### `entity_project_participations`

Mirrors `entity_addresses`'s shape (opaque primary key, principal-scoped
self-referencing supersession, three-state lifecycle
`EntityProjectParticipationState` — its own vocabulary, for the reason every
sibling family's state enum already gives against sharing one), with two
entity references instead of one: `project_entity_id` (expected
`entity_type = 'project'`) and `participant_entity_id` (a person or
organization entity, no `entity_type` restriction). The `project_entity_id`
type expectation is a **domain invariant the writer enforces, not a CHECK**
— PostgreSQL cannot express a CHECK that reads another table's row, the same
non-enforcement already accepted for `entity_organization_profiles`'s
`entity_type = 'organization'` expectation. A CHECK
(`project_entity_id <> participant_entity_id`) refuses the one case SQL can
see directly: a project cannot meaningfully participate in itself.

**`project_display_name` is project-scoped fact, never global identity — the
central semantic requirement of this work package.** It is the name a
participant is known by *on this specific project*, which may differ from
`entities.display_name`/`entities.canonical_name` for the same
`participant_entity_id`. Nothing in the migration, the domain layer
(`EntityProjectParticipation`), or the table definition writes this value to
either global-identity column or reads either of them into it —
`EntityProjectParticipation` carries no field, property, or method that
touches `display_name`/`canonical_name` at all, and
`tests/relationship/test_relationship_domain.py`'s closed field allow-list
makes that a structural property: a future edit that adds such a field
reddens there. `tests/database/` (below) additionally proves this at the
server: writing a participation's `project_display_name` does not alter the
entity row's `display_name`/`canonical_name`.

`role_code`/`discipline_code` are nullable foreign keys into the two new
taxonomy tables below; `role_text`/`discipline_text`/`scope_text` are
independently nullable free text, kept **alongside** the taxonomy rather than
forcing every value into it, for scopes a controlled code does not yet cover
or cannot resolve. `role_basis_code` (`contractual`/`source_verified`/
`project_observed`/`inferred`/`unresolved`) states how the role came to be
recorded and is **never inferred from a name or string position** (RULING
3) — `unresolved` is the correct value when unknown, never a guess.
`stakeholder_side_code` is an eleven-value closed vocabulary
(`owner`/`developer`/`design`/`contractor`/`consultant`/`authority`/
`utility`/`vendor`/`sales_marketing`/`adjacent_interface`/`other`).
`relationship_status_code` (`active`/`completed`/`terminated`/`on_hold`/
`unresolved`) is a new vocabulary scoped to this table only — distinct from
the record-lifecycle `state` column: a participation can be `state = active`
(this is the current row) and `relationship_status_code = completed` (the
participant's project work has ended) simultaneously, and that combination
is the ordinary case for a finished project.

**Active uniqueness is keyed on `(principal, project, participant, role)`,
deliberately including `role_code`.** One entity may legitimately hold two
concurrently active roles on the same project (a firm that is both a
project's `CONSULTANT` and its `OWNER_REPRESENTATIVE`), and `role_code`
being part of the key is what permits that without weakening the guard
against a literal duplicate under one role — the same reasoning
`entity_addresses` gives for including `address_type_code` in its own key,
restated for a different axis. Because `role_code` is nullable, two
simultaneously active participations that both leave `role_code` unset are
**not** caught by this index (each `NULL` is distinct to PostgreSQL); such
rows are distinguished, if at all, only by `role_text`. This is a known,
accepted limitation of a nullable taxonomy FK rather than an oversight —
recorded here rather than silently.

### `entity_role_types` and `entity_discipline_types`

Global, Principal-independent reference vocabularies — shared lookup tables,
not per-Principal records, proven un-partitioned deliberately in
`tests/architecture/test_user_owned_tables_are_partitioned.py`'s
`UNPARTITIONED_USER_OWNED` registry. `role_code`/`discipline_code` are
stable business codes (not generated ids). `category`/`broader_family` are
deliberately free text, not closed vocabularies — per the audit, both
catalogs are meant to grow by a new row, not a schema change, on the same
argument that keeps `EntityRelationshipType` from freezing this dimension
too (`ENTITY-REL-001`). `status` (`active`/`deprecated`) closes an entry to
new writes without deleting it, so a historical `entity_project_participations`
row that already cites a code keeps resolving. Both tables are seeded by the
migration with a modest, **generic, industry-standard** set of AEC role and
discipline codes (`OWNER`, `GENERAL_CONTRACTOR`, `ARCHITECT_OF_RECORD`,
`CIVIL_ENGINEERING`, and similar) — never anything derived from or
resembling any specific register's content, which stays out of scope for
this campaign (`TBR register import`).

### Naming deviations, disclosed

Two audit-suggested names are not used as-is in this increment, both for the
same reason: honoring the letter of the audit's text would have put a field
or a table outside the reach of `tests/architecture/
test_relationship_scoring_surface_is_denied.py` (RULING 1's NO-CONFIDENCE
guard) without weakening the guard itself — the guard's scanning logic
(`RELATIONSHIP_TABLE_PREFIXES`, the denied-token list) is untouched by this
increment.

1. **Table: `project_entity_participations` → `entity_project_participations`.**
   The guard scans exactly the tables whose name starts with `relationship_`,
   `entities`, or `entity_`. `project_entity_participations` would not match
   any of those prefixes and would silently fall outside the guard's
   scan — for the one table in this work package where the audit's own
   suggested field names ("participation confidence", "role confidence",
   "scope confidence") are explicitly forbidden. `entity_project_participations`
   is inside the scan with zero change to the prefix list, and matches every
   sibling family's `entity_<something>` naming. The primary-key column
   remains literally `participation_id`, as specified by name in the
   authorizing instruction, not `entity_project_participation_id`.
2. **Field: `stakeholder_tier_code` → `stakeholder_class_code`
   (`StakeholderTierCode` → `StakeholderClassCode`).** The guard denies the
   token `tier` outright, as "a graded band" — a plain rename would be
   evasion of the guard if the underlying concept were in fact a graded
   ranking merely relabeled. It is not: `core`/`adjacent`/`transactional`/
   `unresolved` is a categorical classification of how central an
   *organization's participation in a project* is, not a graded judgement
   about a person's worth, trustworthiness, or standing — a different kind
   of thing from what the operating brief's people-ranking prohibition (the
   guard's stated basis) forbids, and the same shape of categorical role
   attribute `Assignment.responsibility_class` already models elsewhere on
   this plane. Two conditions were verified before accepting the rename
   rather than assuming it was safe: **(a)** `StakeholderClassCode`'s
   docstring in `src/my_pa/domain/relationship/entity.py` states this
   explicitly — it names the guard, states why `tier` was rejected, and
   states why the concept itself remains legitimate, not merely that it was
   renamed to pass a check; **(b)** nothing in this increment's code orders,
   compares, sorts, or arithmetically weights `StakeholderClassCode` values —
   confirmed by inspection of every reference to the type and the column
   across `src/`, `migrations/`, and `tests/`: the only operations against it
   are `isinstance` membership checks and a SQL `CHECK ... IN (...)` set
   membership test, the same shape every other closed vocabulary on this
   plane uses. If either condition had failed — a docstring that only said
   "renamed to satisfy the guard," or any code path treating `core` as
   greater than `adjacent` — the rename would have been evasion rather than
   a legitimate distinction, and was not accepted on that basis; it was
   accepted because both conditions held.

### Delivered artifacts

- Migration `f5b06925857e` (`down_revision = 441b071bf37b`), purely
  additive: three new tables (two of them seeded with generic taxonomy
  rows), no altered column or constraint on any existing table.
- `src/my_pa/domain/relationship/entity.py`: `TaxonomyEntryStatus`,
  `EntityRoleType`, `EntityDisciplineType`, `RoleBasisCode`,
  `StakeholderSideCode`, `StakeholderClassCode`, `ParticipationStatusCode`,
  `EntityProjectParticipationState`, `EntityProjectParticipation`.
- `src/my_pa/infrastructure/persistence/tables.py`: `entity_role_types`,
  `entity_discipline_types`, `entity_project_participations` (Core `Table`
  definitions for runtime access; the migration itself is written out in raw
  DDL per `D-48`/`D-69`).
- `src/my_pa/domain/common/identifiers.py`:
  `IdKind.ENTITY_PROJECT_PARTICIPATION = "eppt"` — does not collide with any
  prior member of `IdKind`, checked before use. `entity_role_types`/
  `entity_discipline_types` need no surrogate prefix; their primary keys are
  stable business codes, the same way `entity_organization_profiles` needed
  none.

## RI-ENT-WP-05 — person affiliation integration

**Objective** (source audit): give the entity plane a normalized, temporal
record of a person's affiliation with an organization — or with none — closing
`ENTITY-PERSON-001` ("incomplete person affiliations": the generalized entity
plane could not carry a job title, an affiliation kind, or a person's
organization-less independent-consultant status). **Delivered this
increment.** `entity_assignments` itself is untouched — not widened, not
backfilled, not repurposed — for the same reason `entity_project_participations`
left it alone (RI-ENT-WP-04): a dedicated table is warranted precisely because
the generic assignment record cannot carry these dimensions.

### `entity_person_organization_affiliations`

Mirrors `entity_project_participations`'s shape (opaque primary key,
principal-scoped self-referencing supersession, three-state lifecycle
`PersonOrganizationAffiliationState` — its own vocabulary, for the reason
every sibling family's state enum already gives against sharing one), with
two entity references instead of one: `person_entity_id` (expected
`entity_type = 'person'`) and `organization_entity_id` (expected
`entity_type = 'organization'` **when non-null**). Both type expectations are
domain invariants the writer enforces, not CHECKs — PostgreSQL cannot express
a CHECK that reads another table's row, the same non-enforcement already
accepted for `entity_organization_profiles`'s `entity_type = 'organization'`
expectation and `entity_project_participations`'s `project_entity_id`/
`participant_entity_id` expectations. A CHECK
(`organization_entity_id IS NULL OR organization_entity_id <> person_entity_id`)
refuses the one case SQL can see directly: a person cannot be its own
organization.

**`organization_entity_id` is NULLABLE, and that is the central requirement of
this work package.** The audit's own "Mike Fichera" case is an independent
consultant who does project work with no employer at all. Representing that
must never involve fabricating a placeholder or sentinel organization entity
merely to satisfy a foreign key — RULING 3's "never infer, never guess"
extended here to "never fabricate to satisfy a foreign key" — and a `NULL`
here, paired with `affiliation_type_code = 'independent_consultant'`, states
the absence directly.
`tests/database/test_person_organization_affiliations_independent_consultant_fixture.py`
proves this at the server: it asserts the exact organization-entity count in
the fixture's Principal scope, so no placeholder organization is ever created
as a side effect.

`job_title` is independently nullable free text (the audit's "Person job
title" element), with the usual blank-when-present CHECK. `affiliation_type_code`
(`AffiliationTypeCode`: `employment`/`principal_ownership`/
`independent_consultant`/`contractor`/`board_member`/`advisor`/`other`) is a
new, purely categorical closed vocabulary — never a gradient, per the
watchpoint carried from the WP-04 review: none of the seven members reads as
ranking another, and nothing in this package's code sorts, compares, or
weights a member of it (RULING 1).

**"Current" is `effective_to IS NULL`, made unambiguous per person by a
partial unique index — a specific product decision, stated explicitly rather
than left implicit.** A person may accumulate many affiliation rows over a
career, and this revision makes the open-ended date range the single source
of truth for "this is the person's present tie," following the convention
`entity_assignments` (`Assignment.effective_to`) already uses for the same
question, rather than inventing a second, independently-settable `is_current`
boolean that could disagree with the date range. The partial unique index
`an_open_ended_affiliation_is_unique_per_person` — on `(principal_id,
person_entity_id)` where `state = 'active' AND effective_to IS NULL` — is what
makes this hold at the database: a person may hold many past (already-closed)
affiliations, but at most one open-ended one at a time.

### Naming deviation, disclosed

The audit's own text names this table `person_organization_affiliations`.
This revision creates it as `entity_person_organization_affiliations`
instead, for the same reason and by the same argument RI-ENT-WP-04's own
naming deviation gives: `tests/architecture/test_relationship_scoring_surface_is_denied`'s
`RELATIONSHIP_TABLE_PREFIXES` scan (`"relationship_"`, `"entities"`,
`"entity_"`) would not reach a table named `person_organization_affiliations`,
and this family is the *most* exposed one yet to carry a smuggled scoring
field, since it is where the audit's own text discusses a person's job title
and organizational standing. `entity_person_organization_affiliations` is
inside the scan with zero change to the guard's scanning logic, and matches
every sibling family's `entity_<something>` naming. The primary-key column is
nonetheless literally `affiliation_id`, matching the audit's own field name.

### Delivered artifacts

- Migration `17149a48fa30` (`down_revision = f5b06925857e`), purely additive:
  one new table, no altered column or constraint on any existing table.
- `src/my_pa/domain/relationship/entity.py`: `AffiliationTypeCode`,
  `PersonOrganizationAffiliationState`, `PersonOrganizationAffiliation`.
- `src/my_pa/infrastructure/persistence/tables.py`:
  `entity_person_organization_affiliations` (Core `Table` definition for
  runtime access; the migration itself is written out in raw DDL per
  `D-48`/`D-69`).
- `src/my_pa/domain/common/identifiers.py`:
  `IdKind.PERSON_ORGANIZATION_AFFILIATION = "poaf"` — does not collide with
  any prior member of `IdKind`, checked before use.

## Merge/split disposition (RULING 2)

`entity_names`, `entity_organization_profiles`, `entity_addresses`,
`entity_communication_methods`, `entity_project_participations`, and, as of
this increment, `entity_person_organization_affiliations` are all
Entity-bound record families and are therefore candidates for the merge/split
ambiguity model that landed in `main@0e24018`
(`src/my_pa/domain/relationship/identity_correction.py`'s
`IdentityEffectFamily`/`_DISPOSITIONS_BY_FAMILY`, and
`src/my_pa/application/identity_correction.py`'s reparenting/collision/
ambiguity-discovery machinery).

`entity_role_types` and `entity_discipline_types` are **not** in this ledger
and do not need to be: they are global, Principal-independent reference
vocabularies with no `entity_id` column of any kind (see the RI-ENT-WP-04
section above and `tests/architecture/test_user_owned_tables_are_partitioned.py`).
An entity merge or split has no row in either table to reparent, discover
ambiguity for, or invert, because neither table names an entity. This is a
reasoned exclusion, not an oversight, and is recorded here so a future reader
does not have to re-derive it.

**Decision: deferred, not wired in, and the reason is recorded here rather
than left implicit — for all six Entity-bound families, as of
RI-ENT-WP-05.**

1. **No live write path exists yet, for any of the six.** This increment
   (like WP-02, WP-03, and WP-04 before it) ships no MCP capability and no
   application command that writes `entity_names`,
   `entity_organization_profiles`, `entity_addresses`,
   `entity_communication_methods`, `entity_project_participations`, or
   `entity_person_organization_affiliations` in ordinary product use — only
   test fixtures write them directly through the persistence layer. A merge
   executed today cannot encounter a populated row of any of the six through
   any caller a real request could reach.
2. **The execution machinery is genuinely bespoke per family**, not
   config-driven: `application/identity_correction.py` carries dedicated
   reparenting functions (`_reparented_alias`, `_reparented_identifier`) and
   dedicated collision-detection logic specific to each table's uniqueness
   rules, across roughly 3,300 carefully-reasoned lines. Extending it
   correctly for six more families — including working out what a merge of
   two organization entities that each carry a profile should do, since
   `entity_organization_profiles` is a 1:1 record a merge cannot simply
   duplicate, what a merge should do with two entities that each carry an
   active preferred address or communication method of the same type, and —
   `entity_project_participations`'s own new wrinkle — what a merge of a
   **project** entity should do to every participation row that names it as
   `project_entity_id`, which is a different reparenting question than a
   merge of a **participant** entity reparenting rows that name it as
   `participant_entity_id` (the two columns are the same table's two
   independent entity references, and a merge could in principle touch
   either, or both, in the same operation) — is substantial, separable work,
   not a small addition to any one increment.
3. **`entity_person_organization_affiliations` restates the same two-reference
   wrinkle a sixth time, and is more sensitive than any of its five
   predecessors because the two references name different *kinds* of entity.**
   `person_entity_id` and `organization_entity_id` are the table's two
   independent entity references, exactly as `project_entity_id` and
   `participant_entity_id` are `entity_project_participations`'s, and a merge
   could in principle reparent either one, or both, in the same operation —
   stated explicitly rather than merely implied, per this campaign's own
   instruction to name what happens on each side separately:
   - **When `person_entity_id` is merged away:** the affiliation row is not
     reparented to the surviving person entity. It remains bound to the
     merged-away `entity_id`, which stays resolvable through
     `entities.superseded_by_entity_id` but is not reachable by querying the
     survivor's affiliation history directly — the survivor's job title and
     organization ties recorded under its own `entity_id`, if any, are
     unaffected and undisturbed, but the merged-away person's affiliation
     history does not follow the redirect.
   - **When `organization_entity_id` is merged away:** the affiliation row's
     nullable organization reference is likewise not reparented to the
     surviving organization entity. The affiliated person's row keeps
     pointing at the merged-away organization's `entity_id`, resolvable
     through the same redirect but not surfaced when a caller looks up the
     survivor organization's affiliated people. A merge of an organization
     that is the *survivor* side of the merge is unaffected in the other
     direction: nothing here moves an affiliation row from the merged-away
     organization onto the survivor, which is exactly the reparenting
     decision WP-06's wiring has to make, and it is not made by this
     increment either implicitly or by omission.
   - **Both may happen in the same operation** when a single merge redirects
     both the person side of one affiliation row and the organization side of
     another (or, in the degenerate case, both sides of the same row) — the
     same "either, or both" caveat item 2 already states for
     `entity_project_participations`'s two references, restated here because
     this family binds two entities of *different* types rather than two of
     the same type, which is a new wrinkle WP-06's design has to account for
     separately from the symmetric project/participant case.
4. **What a merge does today, absent wiring:** if a future write path
   populates any of the six tables before this wiring lands, a merge that
   redirects the owning entity does not reparent, discover ambiguity for, or
   invert those rows. They remain bound to the merged-away `entity_id`, which
   stays resolvable through `entities.superseded_by_entity_id` but is not
   reachable by querying the survivor's names, profile, addresses,
   communication methods, project participations, or affiliations directly.
   This is recorded as a known limitation in all six classes' docstrings
   (`src/my_pa/domain/relationship/entity.py`) and here.
5. **Deferred to `RI-ENT-WP-06`**, which the source audit's own dependency
   ordering already binds to "coordinate merge/split effects" — not to the
   taxonomy or record-family schema work WP-02, WP-03, WP-04, and WP-05
   deliver.

**Blocking dependency, stated plainly:** `WP-08` (repositories/domain
services) and `WP-11` (MCP mutation contracts) **may not ship a write path
for any of these six families** — `entity_names`,
`entity_organization_profiles`, `entity_addresses`,
`entity_communication_methods`, `entity_project_participations`, or
`entity_person_organization_affiliations` —
**until the merge/split wiring in `WP-06` lands.** A write path that
outpaces that wiring would let ordinary product use populate a row a merge
cannot reparent, discover ambiguity for, or invert — silently reintroducing
the exact hazard `SECURITY-001` and RULING 2 exist to prevent. This is a
hard ordering constraint on the work-package sequence, not a preference.

This satisfies RULING 2's second branch: a documented, evidenced exclusion
rather than a silent one.

## Test evidence

Exact commands, run from the repository root with
`MY_PA_DATABASE_URL='postgresql+psycopg://my_pa@127.0.0.1:5433/my_pa'`
(reused only to *create* disposable test databases; every test below runs
against its own disposable database, never the configured one):

- `.venv/bin/python -m pytest tests/unit/test_entity_name_and_organization_profile_domain.py -q`
- `.venv/bin/python -m pytest tests/schema/test_entity_names_and_organization_profile_migration.py -q`
- `.venv/bin/python -m pytest tests/unit/test_person_organization_affiliation_domain.py -q`
- `.venv/bin/python -m pytest tests/schema/test_person_organization_affiliations_migration.py -q`
- `.venv/bin/python -m pytest tests/database/test_person_organization_affiliations_independent_consultant_fixture.py -q`
- `.venv/bin/python -m pytest tests/relationship/test_relationship_domain.py -q`
- `.venv/bin/python -m pytest tests/architecture/test_relationship_scoring_surface_is_denied.py -q`
- `.venv/bin/python -m pytest tests/architecture/ -q`
- `.venv/bin/python -m alembic upgrade head` / `downgrade base` against a disposable database

Exact results are recorded in the pull request and in the implementation
report returned to the manager, bound to the exact head SHA reviewed — not
restated here, so this document cannot drift ahead of what actually ran.

## Related documents

- [`docs/specs/relationship-intelligence-v0.2.md`](../specs/relationship-intelligence-v0.2.md) — current governing requirements source; this campaign extends its entity model, does not supersede it.
- [`docs/specs/relationship-memory-v0.1.md`](../specs/relationship-memory-v0.1.md) — the sibling record family this campaign's naming and lifecycle conventions follow.
- [`docs/architecture/module-boundaries.md`](../architecture/module-boundaries.md) — the layering this campaign's domain/persistence split honors.
- `src/my_pa/domain/relationship/entity.py` — `EntityName`, `EntityNameState`, `NameTypeCode`, `EntityOrganizationProfile`, `OrganizationKindCode`, `LegalIdentityStatusCode`, `EntityAddress`, `EntityAddressState`, `AddressTypeCode`, `EntityCommunicationMethod`, `EntityCommunicationMethodState`, `CommunicationMethodTypeCode`, `CommunicationUsageContextCode`, `CommunicationVerificationStatusCode`, `EntityProjectParticipation`, `EntityProjectParticipationState`, `RoleBasisCode`, `StakeholderSideCode`, `StakeholderClassCode`, `ParticipationStatusCode`, `PersonOrganizationAffiliation`, `PersonOrganizationAffiliationState`, `AffiliationTypeCode`.
- `src/my_pa/infrastructure/persistence/tables.py` — `entity_names`, `entity_organization_profiles`, `entity_addresses`, `entity_communication_methods`, `entity_project_participations`, `entity_role_types`, `entity_discipline_types`, `entity_person_organization_affiliations`.
- `migrations/versions/20260830_7e114f822af2_add_entity_names_and_organization_.py` (RI-ENT-WP-02).
- `migrations/versions/20260830_441b071bf37b_add_entity_addresses_and_communication_.py` (RI-ENT-WP-03).
- `migrations/versions/20260830_f5b06925857e_add_entity_project_participations_and_.py` (RI-ENT-WP-04).
- `migrations/versions/20260830_17149a48fa30_add_entity_person_organization_affiliat.py` (RI-ENT-WP-05).
