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
  (`knowledge.entity_person_organization_affiliations`);
- **(G) RI-ENT-WP-06a** — relationship taxonomy expansion
  (`knowledge.entity_relationship_types`), a first slice of RI-ENT-WP-06 --
  see "RI-ENT-WP-06a" below for exactly what is and is not in this slice.

The remainder of RI-ENT-WP-06 (merge/split coordination for the six
Entity-bound record families WP-02/WP-04/WP-05 delivered) and RI-ENT-WP-07
through RI-ENT-WP-13 (assertion/provenance binding, repository/service layer
beyond WP-02/WP-04/WP-05, resolution/search vNext, MCP rich-read and mutation
contracts, legacy migration/backfill, and the full TBR completeness fixture)
are **explicitly out of scope for this increment** and remain future work,
ordered as the source audit orders them (section P). Nothing in this
increment implements them, and nothing in this increment's schema, domain
code, or tests assumes they exist. **The merge/split half of RI-ENT-WP-06 is
a separate, later, independent pull request (PR2) from the relationship-
taxonomy slice this document's "RI-ENT-WP-06a" section covers (PR1); PR2 does
not touch `entity_relationship_types` or `EntityRelationshipType`, and this
document's existing "Merge/split disposition" ledger below is unmodified by
PR1 and remains PR2's scope exactly as recorded.**

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
| `ENTITY-REL-001` | Critical | Closed relationship vocabulary (15 of 22 required codes) | **Closed by RI-ENT-WP-06a** — `entity_relationship_types` (global, table-backed taxonomy seeded with the fifteen existing codes plus twenty new ones; `entity_relationships.relationship_type` now a foreign key into it). `EntityRelationshipType` itself stays at fifteen codes, disclosed and deliberate — see `EntityRelationshipType`'s docstring |
| `ENTITY-PROJECT-001` | Critical | Incomplete project participation | **Closed by RI-ENT-WP-04** — `entity_project_participations` (project/participant identity, project-scoped `project_display_name`, `role_code`/`role_text`, `discipline_code`/`discipline_text`, `scope_text`, `role_basis_code`, `stakeholder_side_code`, `stakeholder_class_code`, `relationship_status_code`, temporal state), plus the extensible `entity_role_types`/`entity_discipline_types` taxonomies. No MCP capability or write path exists yet (`RI-ENT-WP-10`/`WP-11`) — see "Merge/split disposition" below |
| `ENTITY-PROVENANCE-001` | High | No fact-level certainty/verification binding | Partially addressed for organization legal identity only, via `legal_identity_status_code` (not a confidence field — see Ruling 1); full assertion/provenance binding is `RI-ENT-WP-07` |
| `ENTITY-PERSON-001` | High | Incomplete person affiliations | **Closed by RI-ENT-WP-05** — `entity_person_organization_affiliations` (nullable `organization_entity_id`, `job_title`, `affiliation_type_code`, temporal `effective_from`/`effective_to` with `state = 'active' AND effective_to IS NULL` denoting "current") |
| `ENTITY-RESOLUTION-001` | Critical | Resolution cannot follow typed names/identity graph | **Unblocked, not closed** — `entity_names` now exists as the structural prerequisite; resolution/search changes are `RI-ENT-WP-09` |
| `ENTITY-STATE-001` | High | No canonicalization/review state distinct from lifecycle | Design decision recorded in RI-ENT-WP-01 below (`canonicalization_state_code`, separate 1:1 record, deferred); not implemented this increment |
| `MCP-CONTRACT-001` | Critical | No rich structured profile read | Not in scope (`RI-ENT-WP-10`) |
| `MCP-CONTRACT-002` | High | No record-family mutation capabilities for the new families | Not in scope (`RI-ENT-WP-11`); RULING 5 (no mass-assignment endpoint) remains binding when it is |
| `COMPAT-001` | High | Additive-vs-breaking policy needed for generated strict schemas | Addressed procedurally in RI-ENT-WP-01 (below); no generated schema exists yet to apply it to |
| `MIGRATION-001` | Critical | Legacy `relationship_people`/`relationship_organizations` coexist; must not infer legal identity from names | Honored: migration `7e114f822af2` is purely additive, backfills nothing, infers nothing |
| `SECURITY-001` | High | New families must preserve Principal partitioning, composite keys, append-only ledgers, operator-only merge/split | Partitioning and composite keys: proven by `tests/schema/test_entity_names_and_organization_profile_migration.py`. `entity_project_participations` is Principal-partitioned the same way; `entity_role_types`/`entity_discipline_types` are deliberately **not** Principal-partitioned (global reference vocabularies — see `tests/architecture/test_user_owned_tables_are_partitioned.py`'s `UNPARTITIONED_USER_OWNED` entry for both). Merge/split: **fully wired as of RI-ENT-WP-06b** for all six Entity-bound families (deferred, not silently, through RI-ENT-WP-05) — see "Merge/split disposition" below |
| `TEST-001` | High | No TBR completeness fixture exists | Not in scope (`RI-ENT-WP-13`); this increment adds a synthetic single-case fixture (GS4 Studios) proving the pattern, not the full register |

## The 13 work packages (source audit ordering, section P)

| WP | Title | This increment |
|---|---|---|
| WP-01 | Architecture/contract freeze | **Delivered** — see below |
| WP-02 | Taxonomy and typed-name model | **Delivered (partial)** — `entity_names`, `entity_organization_profiles`; role/discipline/relationship taxonomies deferred to WP-04/06 |
| WP-03 | Address and communication record families | **Delivered** — see below |
| WP-04 | Project participation model | **Delivered** — see below |
| WP-05 | Person affiliation integration | **Delivered** — see below |
| WP-06 | Corporate/entity relationship graph expansion | **Delivered (partial, RI-ENT-WP-06a)** — `entity_relationship_types` taxonomy and the twenty new codes; merge/split coordination for the six WP-02/04/05 record families remains deferred to a separate PR2 |
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
| Historical juristic entity (a *different* legal person than its successor) | A separate `entities` row, linked by relationship — never a name row | WP-06a (relationship taxonomy must admit the lineage edge) for the *edge*; the *entity* row itself needs no new table | **Delivered** — `historical_identity_of`/`acquired_by` now exist in `entity_relationship_types`; the *entity* row pattern was already delivered by WP-02 (see `tests/database/test_entity_names_tbr_gs4_studios_fixture.py`, which still uses `AFFILIATED_WITH` as its documented placeholder edge pending the write path that would let it use the new codes through `EntityRelationshipType`) |
| Project address / legal principal address / HQ / regional or known office / city hall | `entity_addresses` | WP-03 | Deferred |
| Phone / website / domain / email as a contact channel | `entity_communication_methods` | WP-03 | Deferred |
| Key/known contact, with title, at a project or organization | Person entity + `entity_person_organization_affiliations` + project participation | WP-05, WP-04 | **Delivered** — the project-participation half (`entity_project_participations`) was delivered by WP-04; the affiliation/title half (`entity_person_organization_affiliations.job_title`) is delivered by WP-05 |
| Relationship / parent / practice / acquisition lineage / technical-review / seller-developer-SPV / utility-authority edge | `entity_relationship_types` taxonomy (table-backed successor to the CHECK that froze `EntityRelationshipType` at fifteen codes) | WP-06a | **Delivered** — thirty-five codes seeded (the fifteen existing plus twenty new); `entity_relationships.relationship_type` is now a foreign key into this table. `EntityRelationshipType` itself stays at fifteen codes, deliberately not widened — see its own docstring |
| Project role / discipline / scope / stakeholder side / stakeholder tier / role basis / participation state | `entity_project_participations` — named `entity_project_participations` rather than the audit's own `project_entity_participations`; see "Naming deviations" under RI-ENT-WP-04 below | WP-04 | **Delivered** |
| "Confidence" (register label) at any dimension (role/scope/participation/legal-identity) | **Not a scalar confidence field anywhere** — discrete `assertion_status`/`role_basis_code`/`legal_identity_status_code`-family vocabularies, one per dimension, bound to the fact/edge/participation that carries it | WP-02 delivers `legal_identity_status_code`; the rest is WP-07 | Partial — RULING 1 governs all of it, see below |
| Evidence / source type-URI / observation and verification timestamps / assertion author / conflicting evidence / supersession / source-driven correction | Existing `entity_fact_evidence_links`, `entity_observations`, `entity_mutation_events`, `entity_resolution_decisions`, extended to bind the new record families | WP-07 | Deferred; the ledgers exist and are unmodified, but do not yet bind `entity_names`/`entity_organization_profiles` rows |
| Import readiness (READY/FLAG/HOLD/DO NOT IMPORT), canonicalization state distinct from lifecycle | A new, separate state record or nullable FK on `entities` (`canonicalization_state_code`) — explicitly **not** an overload of `entities.status` | Design decision recorded now (`ENTITY-STATE-001`); table not created this increment | Deferred |
| Duplicate/reconciliation state, merge/split ledgers | Existing `entity_merge_records`, `entity_identity_effects`/`entity_identity_previews`/`entity_identity_operations`, `entity_identity_preview_ambiguities`, `entity_identity_ambiguity_settlements` | Existing (RI remediation campaign, PR #164) | Unchanged; `entity_names`/`entity_organization_profiles` and the other four Entity-bound families are **fully wired in as of RI-ENT-WP-06b** — see "Merge/split disposition" |
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
`tests/database/test_person_organization_affiliations_tbr_fixture.py`
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

**"Current" is `state = 'active' AND effective_to IS NULL`, made unambiguous
per person by a partial unique index — a specific product decision, stated explicitly rather
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

## RI-ENT-WP-06a — relationship taxonomy expansion

**Objective** (source audit, decision R.3): replace the frozen
`EntityRelationshipType` CHECK with a table-backed, extensible relationship-
type taxonomy, closing `ENTITY-REL-001` ("closed relationship vocabulary (15
of 22 required codes)"). **Delivered this increment, as PR1 of a two-PR
increment; PR2 (merge/split coordination for the six WP-02/04/05 record
families this document's "Merge/split disposition" section already ledgers)
is separate, later, independent work this PR does not touch.**

### `entity_relationship_types`

Global, Principal-independent reference vocabulary — the same shape
`entity_role_types`/`entity_discipline_types` already established for
RI-ENT-WP-04, reusing the same `TaxonomyEntryStatus`
(`active`/`deprecated`). Seeded with the fifteen pre-existing
`EntityRelationshipType` codes plus twenty new ones the audit's Record
Element Inventory names: `brand_of`, `operates_as`, `dba_of`,
`historical_identity_of`, `parent_of`, `subsidiary_of`, `acquired_by`,
`practice_of`, `contracting_entity_for`, `managed_by`,
`owner_representative_for`, `project_controls_advisor_to`,
`technical_reviewer_of`, `peer_reviewer_of`, `design_coordinates_with`,
`utility_provider_for`, `permitting_authority_for`, `seller_developer_for`,
`sales_marketing_agent_for`, `sequence_interfaces_with`.

`directed` is `true` for all thirty-five (every code in this vocabulary is a
directed edge, seeded and future). `inverse_type_code` is wired for exactly
two pairs self-evident from the code names alone — `parent_of`/
`subsidiary_of` and `manages`/`managed_by` — and left `NULL` everywhere else,
including where the audit's own text names an inverse
(`technical_reviewer_of`'s `reviewed_by`) that is not part of this revision's
required vocabulary (RULING 2: never invent an unauthorized semantic
pairing). `source_entity_type`/`target_entity_type` are nullable, CHECK-
constrained to `person`/`organization`, and populated only for the nine
codes the audit frames unambiguously as organization-to-organization
corporate-identity edges plus two organization-only-source codes
(`utility_provider_for`, `permitting_authority_for`); every other code,
including all fifteen pre-existing ones, is `NULL`/`NULL` rather than
guessed. `allows_project_scope` is `true` for the fifteen new codes the
audit frames as ordinarily exercised within a project's scope (via
`entity_relationships.scope_entity_id`, unchanged) and `false` for the five
pure corporate-lineage codes and all fifteen pre-existing ones.
`cardinality_rule` is left `NULL` for every seeded row — the audit
explicitly warns against assuming a DB-singleton "one active parent" rule
for `parent_of`, which is exactly what an empty column avoids asserting.

### The constraint swap

`9def3c2e63bb`'s `an_entity_relationship_type_is_known` CHECK is dropped and
replaced by a validated (not `NOT VALID`) foreign key,
`an_entity_relationship_type_is_seeded`, from
`entity_relationships.relationship_type` to
`entity_relationship_types.relationship_type_code`. Because the fifteen
pre-existing codes are seeded *before* this swap, the validated `ALTER
TABLE` is itself the proof that every existing `entity_relationships` row
survives: Postgres refuses the `ALTER` outright if any row's value is not
among the seeded codes. `tests/schema/test_entity_relationship_types_migration.py`
proves this against a real server, explicitly for all fifteen pre-existing
codes (one assertion per code) and for each of the twenty new ones.

### `EntityRelationshipType` is not widened, disclosed

`EntityRelationshipType` (the application-facing `StrEnum`) stays at
fifteen codes. It is deeply threaded through the already-shipped
`entity_relationships` write path (`application/commands.py`'s directed-
write validation, `contracts/ports.py`, `infrastructure/persistence/
entity.py`, the HTTP/MCP transport and capability surfaces) in a way none
of the six WP-02/04/05 record families are, so widening it would be a
second, much larger surface change this single-purpose PR does not make.
`entity_relationship_types` is now the authoritative, extensible, DB-level
source of truth for all thirty-five codes; a caller cannot yet write an
`entity_relationships` row through the existing typed command path using
one of the twenty new codes. This is disclosed here, in
`EntityRelationshipType`'s own docstring, and in the `8dc3619891bb`
migration's module docstring — not left implicit — and follows the same
disclosed-deferral pattern this campaign already uses for the six WP-02/04/05
families' merge/split wiring.

### Delivered artifacts

- Migration `8dc3619891bb` (`down_revision = 17149a48fa30`): one new table
  (`entity_relationship_types`, seeded with thirty-five rows), and one
  altered constraint on `entity_relationships.relationship_type` (CHECK
  replaced by foreign key). No other existing table, column, or constraint
  is altered.
- `src/my_pa/domain/relationship/entity.py`: `RelationshipTypeTaxonomyEntry`;
  `EntityRelationshipType`'s docstring updated to disclose the table-backed
  companion and why the enum itself is not widened.
- `src/my_pa/infrastructure/persistence/tables.py`: `entity_relationship_types`
  (Core `Table` definition for runtime access; the migration itself is
  written out in raw DDL per `D-48`/`D-69`); `entity_relationships`'s
  declaration rewritten to match (the old `_one_of(relationship_type,
  EntityRelationshipType, ...)` CHECK replaced by the matching
  `ForeignKeyConstraint`).
- No new `IdKind` member: `entity_relationship_types.relationship_type_code`
  is a stable business code, not a generated id, the same way
  `entity_role_types.role_code`/`entity_discipline_types.discipline_code`
  need none.

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

**Historical decision, as of RI-ENT-WP-05: deferred, not wired in, for all six
Entity-bound families.** The five numbered points and the "Blocking
dependency" paragraph that originally followed this line are superseded by
the RI-ENT-WP-06b update immediately below, which records the wiring's actual
landing rather than its deferral. The five points are kept here in
condensed form (the full reasoning behind each is in `git log` on this file
at the RI-ENT-WP-05 commit) as the record of what was true through
RI-ENT-WP-05 and why the deferral was reasoned rather than an oversight — a
future reader comparing revisions should be able to see the decision change,
not just its current state.

1. No live write path existed yet, for any of the six.
2. The execution machinery is genuinely bespoke per family, not
   config-driven.
3. `entity_person_organization_affiliations` restated the two-reference
   wrinkle a sixth time, with two entity references naming *different kinds*
   of entity.
4. What a merge did, absent wiring: a row stayed bound to the merged-away
   `entity_id`, resolvable through `entities.superseded_by_entity_id` but not
   reachable by querying the survivor's own records.
5. Deferred to `RI-ENT-WP-06`.

## RI-ENT-WP-06b update: the wiring has landed

**All six families now have full merge/split participation.** `RI-ENT-WP-06b`
extended `IdentityEffectFamily` with six new members — `NAME`,
`ORGANIZATION_PROFILE`, `ADDRESS`, `COMMUNICATION_METHOD`,
`PROJECT_PARTICIPATION`, `PERSON_ORGANIZATION_AFFILIATION` — and
`MergeFamily` (the merge preview report's own, separate vocabulary; see that
class's docstring) with the same six, so a merge preview a human operator
reads now names what happens to every one of them rather than staying silent
about six families it can transform. `_DISPOSITIONS_BY_FAMILY` gives all six
`(ASSIGN_TO_ENTITY, LEAVE_UNRESOLVED)` — the same two dispositions `ALIAS`
and `IDENTIFIER` get — on the reasoning that none of the six admits a
`PRESERVE_SHARED` reading: each is a record of one exclusive fact about one
entity (or, for the two dual-reference families, one exclusive fact about one
*pair* of entities), not evidence of what a source said the way an
observation is, and RI v0.2 section 15.4's "preserve shared and ambiguous
evidence" is textually about evidence.

**What full participation means concretely, per family:**

- **`entity_names`, `entity_addresses`, `entity_communication_methods`**
  (`plan_names`/`plan_addresses`/`plan_communication_methods`,
  `src/my_pa/application/identity_correction.py`) mirror `plan_aliases`
  exactly on the value-key collision dimension (same `(type, normalized
  value)` key, same reparent/coalesce/`AMBIGUOUS_DISPOSITION`-conflict
  shape). Each of the three also carries a *second*, independent collision
  the value key cannot see: `an_active_..._has_one_preferred_per_type`, a
  partial unique index admitting at most one active preferred row per
  `(entity, type)`. **Resolution: demotion, not a second operator
  question.** A reparenting row whose `is_preferred` would collide with the
  survivor's own active preferred row of that type has its `is_preferred`
  cleared to `false` before the write, deterministically — not offered as a
  second `ConflictChoice`, because the `choices`/`dispositions` mappings this
  plane's commands carry name one answer per record, not one per collision
  axis a record happens to sit on. Nothing is lost: the row is still active
  and correctly bound to the survivor, and a person can re-mark it preferred
  afterward. This demotion is a real column write alongside the entity
  reparenting, which needed a small, generic extension to the shared write
  path: `_ChildSubject.content_columns`
  (`src/my_pa/infrastructure/persistence/entity.py`) names non-entity-reference
  columns a reparenting also writes, sourced from the effect's own
  `after_state`, empty for every other family. `reparent_entity_reference`
  gained an optional `after_state` parameter to carry it. A coalesced row's
  `is_preferred` is left unchanged (it already falls outside both partial
  indexes once superseded).

- **`entity_organization_profiles`** (`plan_organization_profiles`) is the one
  family that is not alias-shaped: `entity_id` is both the table's primary
  key and its foreign key to `entities` (see
  `EntityOrganizationProfile`'s own docstring), so an organization entity
  carries at most one profile row by construction, with no `state` or
  `superseded_by_*` column for a losing row to retire into. **When only one
  side of a merge carries a profile, that is an unambiguous reparenting** —
  literally a primary-key rewrite, which the generic `reparent_entity_reference`
  substitution already performs correctly for a family whose sole
  `entity_columns` entry doubles as its `id_column`. **When more than one
  profile exists across the whole operation** (the survivor already has one
  and a merged-away entity also does, or — the degenerate case — two or more
  merged-away entities each carry one competing for the same empty primary
  key) **the merge blocks outright**, via a fourth `IdentityConflictKind`
  member, `SINGLETON_RECORD_CONFLICT` (`domain/relationship/identity_correction.py`),
  on the same textual reasoning the existing `IDENTIFIER` conflict already
  blocks rather than asks: "the schema admits either [reparenting or
  coalescing]" is what makes an `ALIAS` conflict an operator's choice, and it
  is false here. No profile's data is ever silently dropped; the merge is
  refused until the ambiguity is resolved by other means (which this
  increment does not itself provide, matching how `ACTIVE_IDENTIFIER_CONFLICT`
  is refused rather than resolved).

  Wiring this family surfaced a genuine, narrower architectural fact worth
  recording precisely: because `entity_id` is simultaneously the row's stable
  identity and the entity reference a merge substitutes, the merge *ledger's*
  `record_id` for an `OWNER_REPARENTED` effect necessarily names the row's
  identity *before* the effect (the value the write has to find the row by,
  while it is still there) — but every later reader asking "does this row
  still look like the ledger says" or "is this row already accounted for" has
  to look for it at the identity the effect *produced*. A new domain-level
  function, `current_record_id` (`domain/relationship/identity_correction.py`),
  is the one place that fact is stated and is used by both the split-side
  read-back checks (`identity_effect_matches_after_state`,
  `restore_identity_effect`) and post-merge-created discovery
  (`_post_merge_created`'s `known` set) — one function, imported by both,
  rather than two independent places that could disagree about it. No other
  family needs it: every other one keeps a surrogate row identifier
  (`alias_id`, `entity_name_id`, `participation_id`, and so on) disjoint from
  the entity references it carries.

- **`entity_project_participations`** (`plan_project_participations`) has two
  independent entity references of the *same kind* — `project_entity_id` and
  `participant_entity_id` — mirroring `plan_relationships`'s from/to shape.
  Both substitute independently in one statement (the generic
  `reparent_entity_reference` already handles this, exactly as it does
  `RELATIONSHIP`'s three endpoints); a row whose project and participant both
  become the survivor in the same multi-entity merge is `SELF_EDGE_SUPERSEDED`
  rather than reparented, because `a_project_participation_project_is_not_the_participant`
  forbids the row any other form. Active-uniqueness collision is per
  `(project, participant, role)`, deduplicating only active rows exactly as
  `ASSIGNMENT`/`RELATIONSHIP` already do — with one wrinkle specific to this
  index: `an_active_project_participation_is_unique_per_project_and_role` has
  no `COALESCE` over `role_code`, so two concurrently active rows that both
  leave `role_code` unset never collide (ordinary PostgreSQL `NULL <> NULL`
  semantics), and the planner never adds a `NULL`-role row to its collision
  index either. A database test proves both columns reparenting
  independently in one multi-entity merge (the project and one of its
  participants both merged away at once).

- **`entity_person_organization_affiliations`** (`plan_person_organization_affiliations`)
  has two entity references of *different* kinds — `person_entity_id` and the
  nullable `organization_entity_id` — both substituting independently, on the
  same terms as the participation family, including the degenerate case of
  both changing on one row at once (a database test proves it). A row that
  becomes self-affiliated after substitution is `SELF_EDGE_SUPERSEDED`, per
  `a_person_affiliation_organization_is_not_the_person`. The family's one
  collision is `an_open_ended_affiliation_is_unique_per_person` — at most one
  row per person may be simultaneously `state = 'active'` and `effective_to
  IS NULL` — which, unlike `ALIAS`'s value-key collision, has no "current
  versus former" asymmetry for an operator to decide between: a closed
  affiliation is outside the partial index and never collides at all, so the
  collision this family can have is always exactly the shape `plan_aliases`
  resolves by auto-coalescing (both sides "current"), never
  `AMBIGUOUS_DISPOSITION`. The incoming (merged-away) row is coalesced into
  the survivor's pre-existing open affiliation, which is left untouched; the
  merged-away entity's own row is preserved as history, superseded rather
  than discarded.

**No new relationship-type taxonomy work, no touch to `EntityRelationshipType`
or `entity.py`'s relationship enum** — that is the concurrent, independent
`ri-ent/wp06-relationship-taxonomy` branch's scope, not this one's.

**One migration was required, and it is genuinely additive.** RULING 2 does
not forbid a migration when one is genuinely needed; investigation found one
is: `entity_identity_effects.record_family`,
`entity_identity_preview_ambiguities.record_family`, and
`entity_identity_ambiguity_settlements.record_family` each carry a `CHECK
(record_family IN (...))` closing the ledger's own family vocabulary at the
twelve values `8e1c4a7b2d90` last widened it to — fewer than
`IdentityEffectFamily`'s eighteen current members. Migration `9a3f6c1e8d24`
was originally authored with `down_revision = 17149a48fa30`, the head this
branch was authored against before the concurrent
`ri-ent/wp06-relationship-taxonomy` branch's own migration (`8dc3619891bb`)
landed; rather than a separate merge revision, `9a3f6c1e8d24` was re-pointed
to chain directly off `8dc3619891bb` (`down_revision = 8dc3619891bb`) and
this branch rebased onto that branch's tip, per the orchestrating session's
sequencing decision recorded when both PRs were found to need a migration off
the same parent. `DROP CONSTRAINT`/`ADD CONSTRAINT`s all three under their
existing names with the six new values
appended, on `8e1c4a7b2d90`'s own precedent for widening this exact
vocabulary the first time. Purely additive: every row written before this
revision is a strict subset of what the widened list admits, so
`downgrade()` is safe wherever no row already names one of the six new
families (true of every disposable test database this increment's own tests
create, since each is dropped at the end of its own test). No other schema
change was needed — none of the six tables themselves gained a column;
`is_preferred` demotion and `SINGLETON_RECORD_CONFLICT` blocking both work
against columns and constraints RI-ENT-WP-02 through WP-05 already shipped.

**Test evidence for the six families' full participation** (all against real
PostgreSQL, `tests/database/test_ri_ent_wp06b_merge_split.py`, 16 tests, plus
`tests/schema/test_widen_identity_family_vocabulary_migration.py`'s 2-test
upgrade/downgrade round trip for the widened `CHECK` constraints; unit
planning coverage in `tests/unit/test_identity_correction_planning.py`, 30
new tests, plus 4 more in `tests/unit/test_identity_correction.py` covering
`current_record_id` and the new dispositions/conflict-kind vocabulary):
unambiguous reparenting for all six; the preferred-per-type demotion for
names, addresses, and communication methods; the
`SINGLETON_RECORD_CONFLICT` block for a profile on both sides of a merge;
both-columns-independent reparenting and role-based deduplication for project
participations; both-columns-independent reparenting and open-affiliation
coalescing for person-organization affiliations; split inversion proven for
names, communication methods, organization profiles, project participations,
and person-organization affiliations; `POST_MERGE_CREATED` ambiguity
discovery proven for names and person-organization affiliations (exercising
`_ATTRIBUTABLE_FAMILIES`'s generic `records_bound_to_entity_outside` walk for
two representative families — the same generic mechanism serves the other
four); and cross-Principal partition isolation for the new read accessors.
Exact commands and pass counts are in the PR description for
`ri-ent/wp06-merge-split-wiring`; the existing merge/split suites
(`tests/database/test_identity_correction_merge.py`, 86 tests;
`tests/database/test_identity_split_ambiguity.py`, 11 tests) and the full
unit suite (`tests/unit/`, 6,903 passed) ran green, measured directly by a
full synchronous run against the final combined tree (`8dc3619891bb` then
`9a3f6c1e8d24`) rather than carried forward from either branch's own,
now-stale pre-combination count -- `ruff check`, `ruff format --check`, and
`mypy` (432 files) are clean over every file this increment touches. The full
`tests/database/` tier (734 passed), `tests/schema/` tier (763 passed), and
`tests/architecture/` tier (4,725 collected, 4,723 passed, 2 known-
environmental-only failures -- see the FAST/Architecture tier rows in
`relationship-intelligence-implementation-plan.md`) were likewise re-measured
serially against the final combined tree, not assumed from either branch's
standalone report.

**Blocking dependency, updated status: LIFTED.** The RI-ENT-WP-05-era rule —
`WP-08` and `WP-11` may not ship a write path for any of the six families
until this wiring lands — no longer applies to any of the six.
`entity_names`, `entity_organization_profiles`, `entity_addresses`,
`entity_communication_methods`, `entity_project_participations`, and
`entity_person_organization_affiliations` all now have merge reparenting,
split inversion, post-merge-created ambiguity discovery, and a
`_DISPOSITIONS_BY_FAMILY` policy. `WP-08` and `WP-11` may proceed to ship
write paths for all six without reintroducing the class of defect
(`RI-P2-BLK-001`) this rule existed to prevent.

This satisfies RULING 2's first branch for all six families: full
participation rather than a documented exclusion. (`entity_role_types` and
`entity_discipline_types` remain the campaign's one standing *exclusion*,
under RULING 2's second branch, for the reason stated above this update: no
`entity_id` column of any kind, so there is no row for a merge to touch.)

## Test evidence

Exact commands, run from the repository root with
`MY_PA_DATABASE_URL='postgresql+psycopg://my_pa@127.0.0.1:5433/my_pa'`
(reused only to *create* disposable test databases; every test below runs
against its own disposable database, never the configured one):

- `.venv/bin/python -m pytest tests/unit/test_entity_name_and_organization_profile_domain.py -q`
- `.venv/bin/python -m pytest tests/schema/test_entity_names_and_organization_profile_migration.py -q`
- `.venv/bin/python -m pytest tests/unit/test_person_organization_affiliation_domain.py -q`
- `.venv/bin/python -m pytest tests/schema/test_person_organization_affiliations_migration.py -q`
- `.venv/bin/python -m pytest tests/database/test_person_organization_affiliations_tbr_fixture.py -q`
- `.venv/bin/python -m pytest tests/unit/test_relationship_type_taxonomy_domain.py -q`
- `.venv/bin/python -m pytest tests/schema/test_entity_relationship_types_migration.py -q`
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
- `src/my_pa/domain/relationship/entity.py` — `EntityName`, `EntityNameState`, `NameTypeCode`, `EntityOrganizationProfile`, `OrganizationKindCode`, `LegalIdentityStatusCode`, `EntityAddress`, `EntityAddressState`, `AddressTypeCode`, `EntityCommunicationMethod`, `EntityCommunicationMethodState`, `CommunicationMethodTypeCode`, `CommunicationUsageContextCode`, `CommunicationVerificationStatusCode`, `EntityProjectParticipation`, `EntityProjectParticipationState`, `RoleBasisCode`, `StakeholderSideCode`, `StakeholderClassCode`, `ParticipationStatusCode`, `PersonOrganizationAffiliation`, `PersonOrganizationAffiliationState`, `AffiliationTypeCode`, `RelationshipTypeTaxonomyEntry`, `EntityRelationshipType`.
- `src/my_pa/infrastructure/persistence/tables.py` — `entity_names`, `entity_organization_profiles`, `entity_addresses`, `entity_communication_methods`, `entity_project_participations`, `entity_role_types`, `entity_discipline_types`, `entity_person_organization_affiliations`, `entity_relationship_types`, `entity_relationships`.
- `migrations/versions/20260830_7e114f822af2_add_entity_names_and_organization_.py` (RI-ENT-WP-02).
- `migrations/versions/20260830_441b071bf37b_add_entity_addresses_and_communication_.py` (RI-ENT-WP-03).
- `migrations/versions/20260830_f5b06925857e_add_entity_project_participations_and_.py` (RI-ENT-WP-04).
- `migrations/versions/20260830_17149a48fa30_add_entity_person_organization_affiliat.py` (RI-ENT-WP-05).
- `migrations/versions/20260831_8dc3619891bb_add_entity_relationship_types.py` (RI-ENT-WP-06a).
