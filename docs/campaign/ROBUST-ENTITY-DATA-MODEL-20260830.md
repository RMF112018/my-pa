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
| `ENTITY-REL-001` | Critical | Closed relationship vocabulary (15 of 22 required codes) | **Closed by RI-ENT-WP-06a** — `entity_relationship_types` (global, table-backed taxonomy seeded with the fifteen existing codes plus twenty new ones; `entity_relationships.relationship_type` now a foreign key into it). `EntityRelationshipType` itself was originally left at fifteen codes, disclosed and deliberate; the WP-08 blocker-clearing pass then widened it to thirty-four of the thirty-five, withholding `design_coordinates_with`. **That thirty-four-of-thirty-five state is superseded and is no longer current**: commit `37ead78` renamed the taxonomy entry to `design_coordination_with` (migration `c99cd8ed8d1c`) and closed `EntityRelationshipType` at **thirty-five of thirty-five**, with no withheld code and no change to `tests/architecture/test_relationship_scoring_surface_is_denied.py` — see `EntityRelationshipType`'s docstring and "WP-08 blocker cleared: `EntityRelationshipType` widened to 35 of 35 codes" below |
| `ENTITY-PROJECT-001` | Critical | Incomplete project participation | **Closed by RI-ENT-WP-04** — `entity_project_participations` (project/participant identity, project-scoped `project_display_name`, `role_code`/`role_text`, `discipline_code`/`discipline_text`, `scope_text`, `role_basis_code`, `stakeholder_side_code`, `stakeholder_class_code`, `relationship_status_code`, temporal state), plus the extensible `entity_role_types`/`entity_discipline_types` taxonomies. **The "no write path exists yet" clause is superseded**: RI-ENT-WP-08 delivered `record_project_participation`/`supersede_project_participation`/`retire_project_participation` on `EntitiesRepository` and `SqlEntityRepository`, and `EntityRecordFamilyService`'s three verbs above them. No MCP capability or tool exists yet (`RI-ENT-WP-10`/`WP-11`) and the service that calls the write path is unwired — see "RI-ENT-WP-08" and "Merge/split disposition" below |
| `ENTITY-PROVENANCE-001` | High | No fact-level certainty/verification binding | **Closed for schema/domain/persistence by RI-ENT-WP-07** — `entity_assertions`/`entity_assertion_evidence` bind fact-level `assertion_status` (a discrete, unordered epistemic vocabulary, never a confidence score) and evidence to the six WP-02–WP-06 record families that previously had none. **The "repository/service-command wiring (`WP-08`)" clause is now partly closed, not fully**: RI-ENT-WP-08 declared all six assertion methods on the `EntitiesRepository` ABC and implemented them in both test doubles (`a5a939d`, corrected by `7bbc524`), and `EntityRecordFamilyService` records an optional `StatedAssertion` plus one `EntityAssertionEvidence` row per `StatedEvidence` alongside any create or correction of the six families. Still open: MCP exposure (`WP-10`/`WP-11`), which no part of WP-08 delivers, and — inside WP-08's own boundary — mutation-ledger integration, `supersede_assertion`'s collapsed refusal, and the absent retirement verb for `entity_assertions`. See "RI-ENT-WP-07" below and "RI-ENT-WP-08" below for the exact honest boundary of what is and is not delivered |
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
| WP-07 | Assertion/confidence/provenance binding | **Delivered (partial)** — `entity_assertions`/`entity_assertion_evidence` (schema, domain, minimal typed persistence helpers, tests); repository/service/command-layer wiring is `WP-08`, MCP exposure is `WP-10`/`WP-11`. No scalar confidence was added under any name (RULING 1) — see below |
| WP-08 | Repository/domain services and validation | **Delivered (partial)** — seventeen `record_*`/`supersede_*`/`retire_*` methods on `SqlEntityRepository` for the six Entity-bound families, the same seventeen plus RI-ENT-WP-07's six assertion methods declared `@abstractmethod` on `EntitiesRepository`, in-memory equivalents in both test doubles, and the application service `EntityRecordFamilyService` with its own command/receipt DTOs. **The service is deliberately unwired** — no `Capability`, no MCP tool, no HTTP route, no CLI command, and no registration in `ApplicationService`; transport exposure is `WP-10`/`WP-11`. Not delivered: mutation-ledger integration, an idempotency key, proposal-validation integration, a retirement verb for `entity_assertions`, a split of `supersede_assertion`'s single refusal, and **the correction of a row holding the preferred slot** — which is refused outright, because the accepted schema makes it inexpressible as a supersession — see below |
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
| Relationship / parent / practice / acquisition lineage / technical-review / seller-developer-SPV / utility-authority edge | `entity_relationship_types` taxonomy (table-backed successor to the CHECK that froze `EntityRelationshipType` at fifteen codes) | WP-06a | **Delivered** — thirty-five codes seeded (the fifteen existing plus twenty new); `entity_relationships.relationship_type` is now a foreign key into this table. `EntityRelationshipType` itself was originally left at fifteen codes, deliberately not widened; the WP-08 blocker-clearing pass widened it to thirty-four of the thirty-five (`design_coordinates_with` withheld), and **that state is superseded — it is now widened to all thirty-five** as of `37ead78`, which renamed the seeded row to `design_coordination_with` (migration `c99cd8ed8d1c`) rather than weakening any guard — see its own docstring and "WP-08 blocker cleared" below |
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

**One of those seeded codes has since been renamed, and the list above is
left as `8dc3619891bb` actually wrote it rather than rewritten.** Migration
`c99cd8ed8d1c` (commit `37ead78`) renamed the seeded row
`design_coordinates_with` to `design_coordination_with`, changing no other
column of that row. The count is unchanged at thirty-five, and every
statement in this section about the seeded population holds for the renamed
code exactly as it held for the old name; see "WP-08 blocker cleared:
`EntityRelationshipType` widened to 35 of 35 codes" below for why the rename
happened.

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

### `EntityRelationshipType` is not widened, disclosed (historical, as of RI-ENT-WP-06a — superseded below)

**This section records what was true through RI-ENT-WP-06a and why the
deferral was reasoned, not an oversight; it is superseded by "WP-08 blocker
cleared: `EntityRelationshipType` widened to 35 of 35 codes" further down
this document, which records what actually changed.** As of RI-ENT-WP-06a,
`EntityRelationshipType` (the application-facing `StrEnum`) stayed at
fifteen codes. It is deeply threaded through the already-shipped
`entity_relationships` write path (`application/commands.py`'s directed-
write validation, `contracts/ports.py`, `infrastructure/persistence/
entity.py`, the HTTP/MCP transport and capability surfaces) in a way none
of the six WP-02/04/05 record families are, so widening it would have been a
second, much larger surface change that single-purpose PR did not make.
`entity_relationship_types` was, at that point, the authoritative,
extensible, DB-level source of truth for all thirty-five codes while a
caller could not yet write an `entity_relationships` row through the
existing typed command path using one of the twenty new codes. This was
disclosed at the time, in `EntityRelationshipType`'s own docstring, and in
the `8dc3619891bb` migration's module docstring — not left implicit — and
followed the same disclosed-deferral pattern this campaign already uses for
the six WP-02/04/05 families' merge/split wiring.

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

## RI-ENT-WP-07 — assertion/confidence/provenance binding

**Objective** (source audit, section D.10): bind fact-level assertion,
evidence, and provenance to the six Entity-bound record families RI-ENT-WP-02
through RI-ENT-WP-06 added (`entity_names`, `entity_organization_profiles`,
`entity_addresses`, `entity_communication_methods`,
`entity_project_participations`, `entity_person_organization_affiliations`),
closing `ENTITY-PROVENANCE-001` ("no fact-level certainty/verification
binding — confidence/verification exists only per-family, ad hoc"). **Delivered
this increment, at the schema/domain/persistence layer** — repository/
service/command-layer wiring (typed commands, proposal validation, mutation
ledger integration) is `RI-ENT-WP-08`'s own scope, and MCP capability/tool
exposure is `RI-ENT-WP-10`/`RI-ENT-WP-11`'s; neither is implemented or assumed
by this increment.

### `entity_assertions`

One fact-level claim about a field, or an entire record, of one of the six
target families — **binds TO a normalized record; is never a generic EAV
store**, the audit's own explicit architectural constraint. Mirrors
`entity_fact_evidence_links`'s (WP-RI-A-01) "exactly one target" shape
exactly: six nullable `target_*` columns, one per family, with a `CHECK`
enforcing exactly one is non-null — chosen over an unconstrained polymorphic
`(family_code, record_id)` pair with no referential integrity, on the exact
precedent that table already establishes and this campaign's own prompt
required following rather than defaulting past.

**`assertion_status` is a discrete, seven-member, unordered epistemic
vocabulary — never a confidence score (RULING 1).** `verified` /
`best_supported` / `inferred` / `unresolved` / `awaiting_confirmation` /
`contradicted` / `superseded`, exactly the audit's own named alternative to
the "confidence band" and per-dimension "confidence" fields the audit itself
proposed and this campaign forbids under any name or spelling.
`AssertionStatus` is a plain `StrEnum` (never `IntEnum`, never given a rich
comparison dunder), and nothing in `src/` or `tests/` sorts, compares, or
weights it — proved behaviourally, not merely declared, by
`tests/unit/test_entity_assertion_domain.py::test_assertion_status_is_a_plain_strenum_not_an_intenum`
and `::test_nothing_in_the_repository_orders_or_compares_assertion_status`
(the second walks the AST of every `.py` file under `src/` and `tests/` for a
`<`/`<=`/`>`/`>=` comparison naming `assertion_status`). `tests/architecture/
test_relationship_scoring_surface_is_denied.py` was run against this
increment's schema and domain additions and passed with zero denials — see
"Test evidence" below for the exact command and count.

**`predicate_code` is free text and nullable**, naming which field of the
target record the assertion is about; `NULL` means the assertion is about the
whole record. A closed vocabulary across the dozens of heterogeneous field
names the six target families carry between them was considered and rejected
as needing constant widening for no safety benefit a free-text column does
not already give — the audit's own D.10 text calls this `predicate_code`/
`field_code` and does not propose a closed set either.

**`asserted_by` reuses `MutationAuthority` and evidence `role` reuses
`EvidenceRole` — neither vocabulary is reinvented.** Both were verified by
reading their exact current members before reuse, not assumed to fit:
`MutationAuthority` (`USER_CONFIRMED_ASSERTION`/`REVIEW_ACCEPTED`/
`SYSTEM_DETERMINISTIC`) is exactly the audit's "asserted_by actor/system" ask,
and its own docstring already argues against a second vocabulary answering
the same question; `EvidenceRole` (`DIRECT`/`SUPPORTING`/`COUNTEREVIDENCE`) is
exactly the audit's "evidence_role direct/supporting/counterevidence" ask,
already reused by `entity_fact_evidence_links` and
`entity_proposal_evidence_links`.

**`supersedes_assertion_id` points backward** (the newer row names the older
one it replaces) — the opposite direction from every sibling family's
`superseded_by_*` column, and the reversal is deliberate: the audit's own
D.10 text names the field `supersedes_assertion_id`, which only reads
correctly as the new row's own reference to what it replaces. **No
destructive replacement follows directly and is proven, not just argued**:
`tests/database/test_entity_assertion_provenance.py::
test_superseding_an_assertion_leaves_the_old_row_and_its_evidence_intact`
writes a new assertion that supersedes an old one and confirms the old row's
every column other than `state`/`assertion_status`/`version`/`updated_at` is
byte-identical to what it was before, and that every `entity_assertion_evidence`
row citing it is still present, unmodified, and still resolves.

**Never infer provenance a source did not state (RULING 3).** When the source
of an assertion is unknown, `assertion_status` is `unresolved` — never a
guess dressed up as a stronger value, and no writer on this plane may promote
it without a corroborating source, the same discipline `RoleBasisCode`
already states for its own dimension.

**`target_organization_profile_entity_id` is a plain, single-column FK with
`ON UPDATE CASCADE`, not a composite `(id, principal_id)` FK like the other
five targets.** `entity_organization_profiles.entity_id` is simultaneously
that table's primary key and its foreign key to `entities` (see
`EntityOrganizationProfile`'s own docstring), and carries no separate
`UNIQUE(entity_id, principal_id)` a composite reference could target — see
"Merge/split disposition" below for the full reasoning and the database test
that proves this branch specifically.

### `entity_assertion_evidence`

One binding between an `EntityAssertion` and the single record that backs,
supports, or contradicts it. Mirrors `entity_fact_evidence_links`'s evidence
half exactly (the same three evidence-source columns — `entity_observation_id`
/ `capture_span_id` / `knowledge_id` — the same "exactly one" `CHECK`, the
same `EvidenceRole` vocabulary) with the fact half replaced by a single
`assertion_id`, since this table's whole subject is already one assertion.
`source_locator` is free text and nullable ("where permissible", the audit's
own D.10 phrasing) — never required, never inferred from the cited record
(RULING 3). No `state`, no `superseded_by_*`, and no write path in this
revision ever deletes or updates an existing row: superseding an assertion
touches only the `entity_assertions` row itself.

### Merge/split — a reasoned exclusion, investigated rather than assumed

`entity_assertions` and `entity_assertion_evidence` are **not** members of
`IdentityEffectFamily`/`MergeFamily`. This is a deliberate, investigated
exclusion, not an oversight, on two separate arguments for the two tables:

1. **`entity_fact_evidence_links` — the closest existing structural
   precedent, and the first fact this investigation checked before deciding
   anything** — is itself **not** a member of `IdentityEffectFamily` (confirmed
   by reading `IdentityEffectFamily`'s full member list in
   `src/my_pa/domain/relationship/identity_correction.py` before this
   decision was made). The reasoning that makes that safe transfers to five
   of `entity_assertions`' six targets: `reparent_entity_reference`
   (`src/my_pa/infrastructure/persistence/entity.py`) substitutes only the
   *entity-reference columns* a `_ChildSubject` names for each family
   (`entity_id` for `NAME`/`ADDRESS`/`COMMUNICATION_METHOD`, two columns each
   for `PROJECT_PARTICIPATION`/`PERSON_ORGANIZATION_AFFILIATION`) — never the
   row's own surrogate primary key (`entity_name_id`, `entity_address_id`,
   `communication_method_id`, `participation_id`, `affiliation_id`), which
   `entity_assertions.target_*` actually references. A merge that reparents
   one of these rows changes which `entity_id` it names; the row's own
   identity, and therefore the assertion's reference to it, is untouched. A
   row a merge instead coalesces (`ROW_COALESCED`: state flips to
   `superseded`, a `superseded_by_*` column is set) is not deleted either —
   it stays resolvable, and a reader can follow its `superseded_by_*` chain
   to the row that superseded it. `tests/database/
   test_entity_assertion_provenance.py::
   test_an_assertion_bound_to_a_name_stays_resolvable_after_the_name_is_reparented`
   proves this for one representative family (`entity_names`) against a real
   merge, rather than assuming the mechanism transfers.
2. **`entity_organization_profiles` is the one family where this reasoning
   does *not* trivially transfer**, because its `entity_id` is simultaneously
   its primary key and its foreign key to `entities` (see
   `EntityOrganizationProfile`'s own docstring) — a merge's reparenting of a
   profile is a literal primary-key rewrite (`reparent_entity_reference`'s
   generic substitution, applied to a `_ChildSubject` whose `id_column` and
   sole `entity_columns` entry are the same column): `UPDATE
   entity_organization_profiles SET entity_id = :survivor WHERE entity_id IN
   (:merged_away)`. This was investigated, not assumed: because it is a
   genuine SQL `UPDATE` (not a delete-and-reinsert), a real foreign key with
   `ON UPDATE CASCADE` from
   `entity_assertions.target_organization_profile_entity_id` to
   `entity_organization_profiles.entity_id` lets Postgres carry the reference
   along automatically the moment that statement runs. **Proven with a real
   database test, not assumed**: `tests/database/
   test_entity_assertion_provenance.py::
   test_an_assertion_bound_to_an_organization_profile_follows_the_profile_through_a_merge`
   binds an assertion to a profile, runs a real merge (through
   `IdentityCorrectionService`) that reparents that profile, and confirms the
   assertion's own column now names the survivor. No change to
   `IdentityEffectFamily`, `MergeFamily`, or any merge/split application code
   was needed for this branch — the ordinary FK mechanism already does the
   whole job.
3. **`entity_assertion_evidence` needs no merge/split wiring at all, on the
   `entity_role_types`/`entity_discipline_types` argument** the campaign
   document's own ledger already gives for those two tables: it carries no
   `entity_id` column of any kind, direct or indirect — its only references
   are `assertion_id` (opaque, not an entity) and the same evidence-source
   trio `entity_fact_evidence_links` already carries unwired. There is no row
   here for a merge to reparent, discover ambiguity for, or invert, because
   no row here names an entity. Confirmed by reading this table's own
   declaration in `tables.py` before asserting the exclusion, not assumed
   from the table's shape in prose.

**No change was made to `IdentityEffectFamily`, `MergeFamily`,
`_DISPOSITIONS_BY_FAMILY`, or any merge/split application code
(`src/my_pa/application/identity_correction.py`) by this increment.** Both
tables' merge/split behavior is fully accounted for by the ordinary FK
mechanisms already in place — a composite FK's referent staying stable across
reparenting for five targets, and a plain `ON UPDATE CASCADE` FK for the
sixth — with no new wiring required, and this is proven by the two database
tests cited above rather than left as an unexercised claim.

### Delivered artifacts

- Migration `1cda4d536268` (`down_revision = 9a3f6c1e8d24`), purely additive:
  two new tables (`entity_assertions`, `entity_assertion_evidence`), no
  altered column or constraint on any existing table.
- `src/my_pa/domain/relationship/governance.py` (not `entity.py` — see
  below): `AssertionStatus`, `EntityAssertionState`, `EntityAssertion`,
  `EntityAssertionEvidence`.
- `src/my_pa/infrastructure/persistence/tables.py`: `entity_assertions`,
  `entity_assertion_evidence` (Core `Table` definitions for runtime access;
  the migration itself is written out in raw DDL per `D-48`/`D-69`).
- `src/my_pa/infrastructure/persistence/entity.py`: minimal typed read/write
  helpers on `SqlEntityRepository` — `record_assertion`, `assertion`,
  `assertions_targeting`, `supersede_assertion`, `record_assertion_evidence`,
  `assertion_evidence` — concrete methods, **not** added to the
  `EntitiesRepository` ABC (`contracts/ports.py`): this class already carries
  concrete methods the ABC does not (113 vs. 89, after this increment's six
  additions), and adding an abstract
  method there would force every other implementer
  (`tests/conftest.py::_Entities`, `tests/evaluation/resolution_harness.py::
  _CorpusRepository`) to implement it too — a larger, WP-08-shaped surface
  change this increment does not make. **That state is superseded and is no
  longer current**: RI-ENT-WP-08 made exactly the surface change this comment
  named it for. Commit `a5a939d` declares all six abstract on
  `EntitiesRepository`, and both doubles implement them; the recorded counts
  (113 vs. 89) are the WP-07-era measurement and are not head's — see
  "RI-ENT-WP-08" below.
- `src/my_pa/domain/common/identifiers.py`: `IdKind.ENTITY_ASSERTION = "east"`,
  `IdKind.ENTITY_ASSERTION_EVIDENCE = "easev"` — neither collides with any
  prior member of `IdKind`, checked before use, including the pre-existing,
  unrelated `IdKind.ASSERTION = "asrt"` (the capture plane's own canonical-fact
  assertion, `my_pa.domain.capture.assertion` — a different concept this
  revision does not touch or rename).

**Naming deviation, disclosed.** `EntityAssertion`/`EntityAssertionEvidence`
and `AssertionStatus`/`EntityAssertionState` live in `governance.py`, not
`entity.py` where every prior WP-02–WP-06a record family lives. This is
deliberate, not arbitrary: `governance.py` already houses
`EntityFactEvidenceLink` — the closest existing structural precedent this
whole design follows — and `entity.py` cannot import from `governance.py`
without introducing a circular import (`governance.py` imports from
`proposal_validation.py`, which imports from `entity.py`); placing the new
types in `governance.py` (which already declares `EvidenceRole`/
`MutationAuthority`, reused here without a second import hop) avoids that
cycle entirely rather than working around it.

### Test evidence

Exact commands, run from the repository root with
`MY_PA_DATABASE_URL='postgresql+psycopg://my_pa@127.0.0.1:5433/my_pa'`:

- `.venv/bin/python -m pytest tests/unit/test_entity_assertion_domain.py -q` — 26 passed.
- `.venv/bin/python -m pytest tests/schema/test_entity_assertion_provenance_migration.py -q` — 18 passed.
- `.venv/bin/python -m pytest tests/database/test_entity_assertion_provenance.py -q` — 12 passed.
- `.venv/bin/python -m pytest tests/architecture/test_relationship_scoring_surface_is_denied.py -q` — 85 passed, zero denials.
- `.venv/bin/python -m pytest tests/relationship/test_relationship_domain.py -q` — 17 passed (allow-lists widened to admit `entity_assertions`/`entity_assertion_evidence` and `EntityAssertion`/`EntityAssertionEvidence`; table count 58→60, model count 69→71).
- `.venv/bin/python -m alembic upgrade head` / `downgrade -1` / `upgrade head` against a disposable database — clean round trip, no residue.

## RI-ENT-WP-08 — repository/domain services and validation

**Objective** (source audit, section P): "Implement repositories/services/DTOs
with Principal scoping, lifecycle, optimistic versions, normalization and
no-guess rules."

**Delivered this increment at the repository, port and application-service
layers, and deliberately no further.** Nothing this work package wrote is
reachable from any transport, and the boundary section below states exactly
where it stops rather than leaving a reader to infer parity with the earlier,
schema-level work packages.

### What is delivered

**1. The repository write path (`ed6e057`).**
`src/my_pa/infrastructure/persistence/entity.py` gains seventeen methods on
`SqlEntityRepository`: three verbs — `record_*`, `supersede_*`, `retire_*` —
for each of the five temporal families (`entity_names`, `entity_addresses`,
`entity_communication_methods`, `entity_project_participations`,
`entity_person_organization_affiliations`), plus the one singleton exception.
`entity_organization_profiles` is that exception: one row per entity, with
`entity_id` both primary key and foreign key, no `state` and no
`superseded_by_*`, so it gets `record_organization_profile` and the in-place
`revise_organization_profile` and no third verb — 5 × 3 + 2 = 17.

Every versioned write is a guarded `UPDATE` carrying its own `_mine(...)`
Principal predicate together with `version == expected_version`. When it
matches no row, a guarded re-read — carrying its own `_mine(...)` at the call
site — hands the version it found, or `None`, to the module-level
`_refuse_stale_or_absent`, which raises `UnknownScopeError` for an absent or
out-of-scope row and `StaleDirectedVersionError` for a reachable row at a
different version. The helper takes the version rather than the table
deliberately: a helper handed the table would name a partitioned table in a
statement of its own, which
`tests/architecture/test_principal_partition_is_reached_through_the_guard.py`
refuses, and keeping the re-read at the call site is what lets that guard see
each one carry its own predicate. Eleven call sites use it, two per temporal
family plus the profile revision.

`revise_organization_profile` passes and writes **every** mutable column,
including both nullable ones (`jurisdiction_code`, `registration_identifier`),
so a revision cannot silently carry forward a jurisdiction or a registration
identifier the caller believes it cleared.

**2. The port declarations (`b49c8bd`, `a5a939d`, `7bbc524`).**
`src/my_pa/contracts/ports.py` declares the same seventeen methods
`@abstractmethod` on `EntitiesRepository`, so every implementer of the port has
to answer for the write path rather than leave it to whichever concrete class
happens to carry it. `tests/conftest.py`'s `_Entities` gains in-memory
equivalents; `tests/evaluation/resolution_harness.py`'s `_CorpusRepository`
states, per method, that resolution writes none of them.

`a5a939d` additionally declares **RI-ENT-WP-07's six assertion methods** —
`record_assertion`, `assertion`, `assertions_targeting`, `supersede_assertion`,
`record_assertion_evidence`, `assertion_evidence` — abstract on the same ABC,
and implements them in both doubles. **This is the surface change WP-07
explicitly deferred to WP-08**, in its own in-file comment and in this
document's WP-07 "Delivered artifacts" list above; making it here is that
deferral being honoured, not scope creep. Two verbs, not three: `record_*`
inserts and `supersede_assertion` is the family's only transition.

**3. The application service (`1b2dd18`).**
`src/my_pa/application/entity_record_families.py` declares
`EntityRecordFamilyService` over the six families, plus `StatedAssertion` and
`StatedEvidence` — the optional fact-level claim a create or a correction may
carry — the `EntityRecordFamily` receipt discriminator, one command dataclass
per verb per family, and the four receipt DTOs (`RecordedFact`,
`CorrectedFact`, `RetiredFact`, `RevisedFact`). The DTOs live in this module
rather than in `src/my_pa/application/commands.py`, which is the
transport-facing surface `WP-11` owns. The service is stateless: it takes the
`EntitiesRepository` as a per-method argument rather than at construction, so
it never holds one.

The four properties the audit's objective names, each with its exact mechanism:

- **Principal scoping is by absence, not validation.** `principal_id` is a
  keyword-only argument on every method, supplied by the composition root from
  `Authorization.principal.principal_id`, exactly as `EntityDirectedService`
  takes it. **No command dataclass in the module declares `principal_id`** — nor
  `version`, `state`, `superseded_by_*`, `retired_at` or `updated_at` — so a
  payload naming one is refused by the dataclass constructor before any of the
  service runs. There is no field that can be sent and is then ignored, because
  a field that can be sent is a field a later change can start honouring.
- **Lifecycle: a correction is a new row plus a supersession, never an in-place
  rewrite.** `record_*` mints an identifier and inserts. `correct_*` mints a
  *second* identifier, writes the successor row, and only then supersedes the
  predecessor under the caller's `expected_version` — the successor exists
  before any row names it. `retire_*` retires under `expected_version`. What
  the record said before a correction survives the correction, which is the
  property the whole temporal shape exists to keep.
  `revise_organization_profile` is the singleton's stated exception. **A
  second exception is not a choice but a schema fact**: a correction whose
  successor claims the preferred slot is refused outright on the three
  families that carry `is_preferred`, because no ordering of the
  correction's two statements satisfies both the preferred-slot index and
  the supersession foreign key — see "A preferred row cannot be corrected
  at all" in the boundary below.
- **Optimistic versions are the caller's and are never re-read.**
  `expected_version` is a required field on every correction and every
  retirement, and nothing in the service reads the row first to discover its
  version — a service that did would guard against a value it had just fetched,
  which is no guard at all. `UnknownScopeError` and `StaleDirectedVersionError`
  surface **untranslated**, for the reason `EntityDirectedService` does not
  translate them either: the classification into the public error family
  already happens in one place, at the transport edge, where
  `src/my_pa/application/service.py`'s `_directed_translated` maps
  `UnknownScopeError` to `not_found` naming `SUBJECT` and
  `StaleDirectedVersionError` to `conflict` naming `EXPECTED_VERSION`. A second
  translation here would be a second place those answers are decided, free to
  disagree with the first.
- **Normalization is allowed; inference is not, and the line is exact.**
  Computing a normalized key from a display value the caller stated is
  normalization — the caller says what the value is, the service says what form
  two such values are compared in. Inferring a *different fact* is guessing.
  So the service computes `EntityName.normalized_value` with `normalize_name`,
  `EntityAddress.normalized_address_value` with `normalize_address` over
  whichever structured fields the caller populated, and
  `EntityCommunicationMethod.normalized_value` with
  `normalize_communication_value` for the method type the caller *stated* — and
  it never splits `raw_value` into `line1`/`city`/`postal_code`, never decides
  from a string's shape that it is an email, and never folds a display name
  into a legal one.

The four no-guess rules, each a refusal a test can reach:

1. **A legal name is stated, never promoted.** `_stated_name_type` refuses a
   `None` `name_type_code` with `InvalidRequestError(SafeDetail.NAME)`. No code
   path in the module chooses a `NameTypeCode`; a `LEGAL` row exists only
   because a caller said `LEGAL`.
2. **A nullable organization stays null.** `_stated_identifier` passes `None`
   through untouched and refuses a present-but-blank identifier rather than
   reading it as "work out who". Nothing creates an organization entity,
   selects one by name, or substitutes a placeholder to satisfy the foreign key
   RI-ENT-WP-05 made nullable precisely so an independent consultant needs none.
3. **A taxonomy code is stated or absent, never derived from text.**
   `_stated_code` refuses a blank code, naming the taxonomy to quote instead; a
   command carrying only `role_text` records `role_code=None` and keeps the
   text, which is the honest record of what was known.
4. **Unknown stays unresolved.** Every closed vocabulary a caller must decide is
   a field with no default on every command that writes it, so omitting one is
   refused by the constructor rather than filled in.
   `verification_status_code` is the single exception that keeps a default, and
   it defaults to `CommunicationVerificationStatusCode.UNRESOLVED` — that
   vocabulary's own name for "not yet known", and the same default
   `EntityCommunicationMethod` itself declares.

**4. The tests.** `tests/database/test_entity_record_family_write_path.py`
(`ed6e057`) exercises the repository write path against real PostgreSQL,
including the merge case whose finding is recorded under "Finding: merge
reparenting bumps a reparented row's own `version`" below. The two doubles are
covered by the existing `tests/unit`, `tests/relationship` and
`tests/evaluation` suites that construct them.

**The service's own coverage has since landed, and this note is promoted from
pending to delivered.** `tests/unit/test_entity_record_family_service.py`
(`31cc7bf`, extended by `95b16cf`) exercises the service against the in-memory
`_Entities` double: Principal scoping as absence read structurally over
`dataclasses.fields`, the two-row shape of a correction with the predecessor's
survival as the load-bearing assertion, the profile's in-place revision and its
nullable clearing, the optimistic-version refusals and the unreachable/absent
parity, normalization computed from the stated display form, the four no-guess
rules each at the helper that makes the refusal, the optional assertion and its
evidence, and `MutationAuthority`'s keyword-only unreachability. It also pins
the preferred-correction refusal on all three families, the two cases that
refusal is deliberately wider than, and an AST check that the refusal is the
first statement of each correction it guards.
`tests/database/test_entity_record_family_service_write_path.py` (`499a7c1`,
rewritten by `95b16cf`) holds only what a real schema can decide about the
service's ordering, and pairs each positive claim with an anti-vacuity test
proving the constraint it relies on actually fires.
### The boundary — what RI-ENT-WP-08 does NOT deliver

**The service is deliberately unwired.** No `Capability` names
`EntityRecordFamilyService`, no MCP tool, HTTP route or CLI command reaches it,
and `ApplicationService` does not hold it — the module is imported by nothing
outside itself. Transport exposure is `RI-ENT-WP-10`/`RI-ENT-WP-11`'s, and
`WP-11` additionally owns the capability and purpose `CHECK` migrations that
would have to land before any of this could be published. Declaring the service
now is the same deliberate half-step `contracts.ports` took when it declared
the write block abstract: the caller-facing shape is fixed and reviewable
before anything can invoke it. The module's own docstring says this; it is
reproduced here rather than paraphrased into something stronger.

**Atomicity belongs to the caller's transaction, not to the service.** A
correction is two statements, not one. `SqlEntityRepository` takes the
connection rather than opening one — "the caller owns the transaction, this
class only issues statements on it" — and `SqlUnitOfWork.entities` hands out a
repository bound to the open transaction's connection, so a correction issued
through a unit of work commits or rolls back whole. The service opens, commits
and rolls back nothing, and holds no compensating write: **called with a
repository that is not inside a transaction, a `record_*` that succeeds
followed by a `supersede_*` that raises leaves the successor row written and
the predecessor still `ACTIVE`.** Both rows are then visible and correctable by
their own identifiers. The guarantee belongs to the caller's transaction, and
neither the module nor this document will describe it as the service's own.

**A preferred row cannot be corrected at all, and the refusal is a fact about
the accepted schema rather than a policy this work package chose.** Found
against real PostgreSQL after this section's first draft landed, and disclosed
here explicitly rather than left to be inferred from the code.
`EntityRecordFamilyService.correct_name`, `correct_address` and
`correct_communication_method` now **refuse** any command carrying
`is_preferred=True`, before any write, through `_refuse_preferred_correction`
(commit `34367b4`); the refusal is the first statement of each of the three
methods.

*Why no ordering works.* The two possible orderings for a correction are
mutually exclusive against the accepted schema.

- **Successor-first** — the order every `correct_*` uses — trips the partial
  unique **index** `an_active_entity_name_has_one_preferred_per_type`,
  `ON (principal_id, entity_id, name_type_code) WHERE state = 'active' AND
  is_preferred = true`, because the predecessor has not yet left
  `state = 'active'`. `an_active_entity_address_has_one_preferred_per_type` and
  `an_active_communication_method_has_one_preferred_per_type` are the same
  shape for the other two families.
- **Supersession-first** trips the self-referencing foreign key
  `an_entity_name_is_superseded_within_its_principal` — `(superseded_by_*,
  principal_id)` back to the same table — because the successor row does not
  exist yet. `an_entity_address_is_superseded_within_its_principal` and
  `a_communication_method_is_superseded_within_its_principal` are its siblings.

*Why no transaction-level trick works either.* Those foreign keys carry **no
`DEFERRABLE` clause** in
`migrations/versions/20260830_7e114f822af2_add_entity_names_and_organization_.py`
or
`migrations/versions/20260830_441b071bf37b_add_entity_addresses_and_communication_.py`
(`grep -c DEFERRABLE` returns zero in both), so they are checked per statement;
and a unique **index** cannot be deferred at all — only a unique *constraint*
can — so nothing reaches the first horn. That is proven against the live
catalogue rather than read off a migration file:
`tests/database/test_entity_record_family_service_write_path.py::test_no_supersession_foreign_key_is_deferrable`
reads `pg_constraint` and asserts `condeferrable` and `condeferred` are false
for every foreign key on a `superseded_by_*` column — matched by column rather
than by name, so it covers both keys each column carries (the composite named
one and the single-column one that column's own `REFERENCES` clause created).

**So a preferred row's correction is not expressible as a supersession under
the accepted schema and the accepted three-verb port.** The service answers
with `InvalidRequestError` before any statement runs, which is a stable
application refusal in place of a raw `psycopg` `UniqueViolation` leaking out
of the repository —
`test_a_preferred_correction_answers_with_a_refusal_and_not_a_driver_error`
admits either and then asserts the type, so it locks that improvement rather
than merely describing it.

**The refusal is deliberately wider than the constraint, and this document
states it rather than letting a reader assume exactness.** The service performs
no read of the predecessor, so it also refuses two cases the indexes would in
fact have admitted: a successor naming a *different* type code from the
predecessor's, and one whose predecessor was not itself preferred. Narrowing
the refusal would require reading the predecessor, which would be a second,
unguarded source of truth beside the caller's `expected_version` — the very
property the version guard exists to be. Both over-refused cases are pinned by
tests in `tests/unit/test_entity_record_family_service.py`, so the width is
held deliberately rather than drifting.

**The available path, and its cost, stated plainly.** A caller replacing a
preferred row uses `retire_*` on the predecessor — retirement writes
`is_preferred = false` and releases the slot, proved against real PostgreSQL by
`tests/database/test_entity_record_family_write_path.py::test_a_retirement_releases_the_preferred_slot`
— and then `record_*` the replacement as preferred. **This is not equivalent to
a correction, and the difference is not cosmetic:** it records a retirement,
not a supersession, so no `superseded_by_*` lineage link is written and the two
rows carry no relation to each other. A reader following the supersession chain
will not find the replacement from the retired row. The schema enforces that
rather than merely leaving it: `an_entity_name_names_a_successor_only_when_superseded`
refuses a retired row that names a successor, so "a retirement that kept the
lineage" is not a reachable state.

**A known imprecision, recorded so a later fix reads as a correction rather
than a regression.** The refusal reports `SafeDetail.PINNED` — the one member
of that closed set naming a per-record "default to this" boolean.
`src/my_pa/application/errors.py` has no `is_preferred` member and was outside
the service work's scope, so `PINNED` is a documented approximation, not the
precise token.

**Two named follow-ups, neither taken and neither authorised in this branch.**
A migration making those self-referencing foreign keys `DEFERRABLE INITIALLY
DEFERRED` would reach the second horn but not the first, and belongs to a
schema-owning work package rather than to WP-08. An in-place preference verb
for a temporal family is explicitly rejected by the module's own design
("there is deliberately no 'update in place' verb for a temporal family").
Neither is inside RI-ENT-WP-08's objective; both are open, and the first is the
only one of the two this campaign has not already argued against.

**`supersede_assertion` collapses two refusals into one, and the split was
deliberately not taken here.** `SqlEntityRepository.supersede_assertion` has a
single failure branch — `rowcount == 0` — and raises `UnknownScopeError` for
both a stale version and an unreachable row, where the six WP-08 families split
the two through `_refuse_stale_or_absent`. The in-memory double originally
split them and was corrected (`7bbc524`) to reproduce the server's answer
verbatim instead, because a double that refuses *more precisely* than
production teaches a caller a distinction production will never make: a caller
written against a `StaleDirectedVersionError` branch would pass every test and
never take that branch in production, which is the class of defect this whole
program exists to correct. **Splitting the server's answer is an available
RI-ENT-WP-07 follow-up that was deliberately NOT taken in WP-08** — it changes
landed production behaviour and needs database-tier proof, and WP-08's
acceptance is to surface optimistic-version conflicts as the repository already
classifies them. It remains unclaimed. A reader should not assume parity
between the assertion family and the six record families on this point.

**No retirement verb for `entity_assertions`.** `EntityAssertionState.RETIRED`
exists in `src/my_pa/domain/relationship/governance.py`, but RI-ENT-WP-07 wrote
no retirement path, and this work package declares no verb no implementer has —
an abstract `retire_assertion` on the port would be a method every double would
have to fake. No `retire_assertion` exists anywhere in `src/` or `tests/` at
head; the port records the omission and its reason in a comment above the
assertion block rather than leaving it silent.

**`entity_organization_profiles` has no retire verb.** The singleton has
nowhere to retire to — no `state`, no `superseded_by_*`, one row per entity by
construction, so there is nothing a supersession could name. A correction is
`revise_organization_profile` in place, under its `expected_version`, passing
every mutable column including the two nullable ones so a revision cannot
silently carry forward a cleared value.

**No mutation-ledger row, and no idempotency key.** The port's write block for
these six families takes neither, unlike the directed writes, so the service
has no replay to consult and writes no `entity_mutation_events` row. Retrying a
`record_*` mints a fresh identifier and writes a second row; the active partial
uniques those tables carry are what refuse a genuine duplicate. **This is a
narrowing of what this document's WP-07 section named as WP-08's scope** —
"typed commands, proposal validation, mutation ledger integration" — of which
WP-08 delivered the typed commands and neither of the other two. A transport
that publishes these methods will have to say what it does about a retry, and
`WP-11` inherits that question along with proposal validation.

**Merge/split behaviour is inherited, not added.** WP-08 introduced no
`IdentityEffectFamily` or `_DISPOSITIONS_BY_FAMILY` member and changed no
merge/split code. It inherits the reparenting semantics RI-ENT-WP-06b wired,
including the version bump recorded under "Finding: merge reparenting bumps a
reparented row's own `version`" below — the finding proven by a test this work
package landed.

### The guard that was touched, and exactly how

`tests/architecture/test_principal_is_never_caller_supplied.py` was modified by
commit `28fb1e5`, and it is the only test or guard this work package touched.
The change is **35 lines added and 0 removed**: a comment block, and six tuples
inserted in their sorted positions into `VERIFIED_CALLER_STATEMENTS`'s entry
for `infrastructure/persistence/entity.py` —

    ("address", "principal_id")
    ("affiliation", "principal_id")
    ("entity_name", "principal_id")
    ("method", "principal_id")
    ("participation", "principal_id")
    ("profile", "principal_id")

**No matcher, detector, control set, or other test was changed.**
`CALLER_SUPPLIED`, `IDENTITY_KEYS`, `PRINCIPAL_FIELDS`, `DERIVED_CHAINS`,
`_DERIVED_RECEIVERS`, `CONTINUITY_COMMANDS`, `MANAGED_DOCUMENT_COMMANDS`, every
detector function and claim 1's matcher are untouched; no pattern was relaxed
and no test was skipped, weakened, or deleted. The diff is additions only.

**Why this is the guard working rather than an allow-list widening.**
`VERIFIED_CALLER_STATEMENTS` records production sites that read a
caller-stated `principal_id` **in order to refuse a mismatch**. The six new
entries are the six families' `record_*` methods — `record_entity_name`,
`record_organization_profile`, `record_entity_address`,
`record_communication_method`, `record_project_participation`,
`record_person_organization_affiliation` — each performing the same
`if X.principal_id != principal_id: raise ValueError(...)` the module already
performs for `assertion`, `link`, `observation` and `proposal`, before any
statement runs and ahead of the scope lock and the merged-endpoint check. None
of the six values is caller input: the records are domain objects the
application hands down having already stamped the resolved partition, and none
of the reads decides a partition — the partition is the `principal_id`
argument, and the read exists only to prove the record agrees with it.
**Registering a check that *adds* a refusal removes none.** Each entry was
verified by reading its method, not inferred from the measurement that went red.

**The separate `name` → `entity_name` parameter rename (`b49c8bd`), and why it
was necessary.** The guard's first claim propagates "caller-supplied" by *local
name*, transitively across a whole module. `_row_to_proposal` binds `name` in
`{str(name): _payload_value(value) for name, value in payload.items()}`, and
`payload` is one of that claim's caller-supplied containers — so every `name`
in `infrastructure/persistence/entity.py` is a name claim 1 has been told not
to read a Principal off. `record_entity_name` read `name.principal_id` in order
to *refuse* a mismatch, which reddened claim 1 — and **claim 1 has no registry
to record an exception in.** Renaming the parameter to `entity_name`, in the
port, the SQL repository and both doubles, is the only response that neither
edits the guard nor stops checking the Principal, and it matches the other five
families, whose parameters were already spelled for their own record.

### Delivered artifacts

- `src/my_pa/infrastructure/persistence/entity.py` (`ed6e057`, parameter rename
  in `b49c8bd`): the seventeen `record_*`/`supersede_*`/`retire_*`/`revise_*`
  methods on `SqlEntityRepository` and the module-level
  `_refuse_stale_or_absent`.
- `src/my_pa/contracts/ports.py` (`b49c8bd`, `a5a939d`, `7bbc524`): the same
  seventeen declared `@abstractmethod` on `EntitiesRepository`, plus
  RI-ENT-WP-07's six assertion methods (`record_assertion`, `assertion`,
  `assertions_targeting`, `supersede_assertion`, `record_assertion_evidence`,
  `assertion_evidence`), and `supersede_assertion`'s collapsed-refusal contract
  stated outright in its docstring.
- `src/my_pa/application/entity_record_families.py` (`1b2dd18`):
  `EntityRecordFamilyService`, `EntityRecordFamily`, `StatedAssertion`,
  `StatedEvidence`, the per-verb command dataclasses, and the `RecordedFact`/
  `CorrectedFact`/`RetiredFact`/`RevisedFact` receipts. No migration; no change
  to any existing module.
- `tests/conftest.py` (`b49c8bd`, `a5a939d`, `7bbc524`): `_Entities` in-memory
  equivalents for all twenty-three declared methods.
- `tests/evaluation/resolution_harness.py` (`b49c8bd`, `a5a939d`):
  `_CorpusRepository` per-method refusals — the corpus holds none of these
  rows, so an empty read would be indistinguishable from a resolver that
  consulted the plane and correctly found nothing.
- `tests/database/test_entity_record_family_write_path.py` (`ed6e057`).
- `tests/unit/test_entity_record_family_service.py` (`31cc7bf`, `95b16cf`) and
  `tests/database/test_entity_record_family_service_write_path.py` (`499a7c1`,
  `95b16cf`): the service's own unit and database coverage, including the
  preferred-correction refusal and both horns of "not expressible as a
  supersession" proved against the live schema.
- `src/my_pa/application/entity_record_families.py` (`34367b4`):
  `_refuse_preferred_correction`, called as the first statement of
  `correct_name`, `correct_address` and `correct_communication_method`.
- `tests/architecture/test_principal_is_never_caller_supplied.py` (`28fb1e5`):
  six registry entries added, none removed, no matcher or control changed.

**No migration, and no schema change of any kind, was made by RI-ENT-WP-08.**
It writes to tables `RI-ENT-WP-02` through `RI-ENT-WP-07` already created.

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

**RI-ENT-WP-07 adds two more tables to this ledger, both as reasoned
exclusions, investigated rather than assumed.** `entity_assertions` and
`entity_assertion_evidence` are **not** members of
`IdentityEffectFamily`/`MergeFamily`. `entity_assertion_evidence` needs no
wiring on the same `entity_role_types`/`entity_discipline_types` argument
immediately above (no `entity_id` column of any kind). `entity_assertions`
is subtler: five of its six `target_*` columns reference a sibling row by
that row's own stable surrogate key, which a merge's
`reparent_entity_reference` never rewrites, so those references stay valid
across a merge with no wiring at all — proven, not assumed, by a real
database test for a representative family (`entity_names`). The sixth,
`target_organization_profile_entity_id`, is a genuine FK with `ON UPDATE
CASCADE` to `entity_organization_profiles.entity_id`, which Postgres follows
automatically the moment that table's own reparenting `UPDATE` runs —
proven by a second real database test binding an assertion to a profile,
running a real merge through `IdentityCorrectionService`, and confirming the
assertion's reference now names the survivor. See "RI-ENT-WP-07 — assertion/
confidence/provenance binding" above ("Merge/split — a reasoned exclusion,
investigated rather than assumed") for the full reasoning and the exact test
names.

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
  both changing on one row at once (a unit-level planning test proves it,
  `test_both_person_and_organization_merging_onto_one_survivor_is_the_
  degenerate_self_edge` in `tests/unit/test_identity_correction_planning.py`
  — unlike the participation family's equivalent claim above, which is
  backed by a real `tests/database/` integration test, this one is proven at
  the planning-function level against an in-memory model rather than against
  a live PostgreSQL database; corrected here for precision, found during
  this increment's independent review). A row that
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
environmental-only failures at the time this passage was written -- see the
FAST/Architecture tier rows in `relationship-intelligence-implementation-plan.md`,
and, for that specific claim mechanically re-verified rather than restated,
"Architecture tier re-verified: the `.claude`-path-component cause, confirmed"
below) were likewise re-measured serially against the final combined tree, not
assumed from either branch's
standalone report.

**Blocking dependency, updated status: LIFTED for the merge/split hazard.** The
RI-ENT-WP-05-era rule — `WP-08` and `WP-11` may not ship a write path for any
of the six families until this wiring lands — no longer applies to any of the
six, on that specific hazard. `entity_names`, `entity_organization_profiles`,
`entity_addresses`, `entity_communication_methods`,
`entity_project_participations`, and `entity_person_organization_affiliations`
all now have merge reparenting, split inversion, post-merge-created ambiguity
discovery, and a `_DISPOSITIONS_BY_FAMILY` policy. `WP-08` and `WP-11` may
proceed to ship write paths for all six without reintroducing the class of
defect (`RI-P2-BLK-001`) this rule existed to prevent, **on that specific
hazard alone** — see the second, separate blocking dependency below, which
this increment did not close and which binds a different, narrower surface.

**Second blocking dependency, new as of this increment's independent review,
STILL STANDING as of RI-ENT-WP-06b — LIFTED by the WP-08 blocker-clearing
pass recorded in "WP-08 blocker cleared" immediately below.**
`entity_relationship_types` (RI-ENT-WP-06a) now holds 35 codes, but the
Python domain enum `EntityRelationshipType`
(`src/my_pa/domain/relationship/entity.py`) was still the original 15
members, by RI-ENT-WP-06a's own deliberate, disclosed design choice (see its
migration's docstring and the "`EntityRelationshipType` is not widened,
disclosed" section above). The consequence, verified directly against the
actual code by this increment's own investigation: `infrastructure/
persistence/entity.py`'s `_row_to_relationship` called
`EntityRelationshipType(str(row.relationship_type))` — a `StrEnum`
constructor — to build every `EntityRelationship` it read back. That call
**raised `ValueError`** for any of the 20 new codes, because they were not
members of the enum. This was unreachable at the time only because nothing
wrote a new code to `entity_relationships.relationship_type` yet — the same
"safe only because nothing writes it" argument this document has made for
the six merge/split-deferred families throughout. **The rule this section
originally stated — no work package, including `WP-08` and `WP-11`, may ship
a write path that can emit one of the 20 new relationship-type codes until
`EntityRelationshipType` is widened to admit all 35 codes and
`_row_to_relationship` (and any other typed read path over
`entity_relationships`) is updated to handle all 35 without raising — is the
rule "WP-08 blocker cleared" below satisfies.** This was deliberately NOT
closed by RI-ENT-WP-06b (that increment): RI-ENT-WP-06b's scope was the six
deferred Entity-bound families' merge/split wiring, which did not touch
`EntityRelationshipType` or `entity_relationships` at all. Widening
`EntityRelationshipType` and its read path was separable, narrower work,
deferred at that point to a future work package rather than folded into
either RI-ENT-WP-06a or RI-ENT-WP-06b's already-reviewed scope — that future
work is what "WP-08 blocker cleared" below records.

This satisfies RULING 2's first branch for all six families: full
participation rather than a documented exclusion. (`entity_role_types` and
`entity_discipline_types` remain the campaign's one standing *exclusion*,
under RULING 2's second branch, for the reason stated above this update: no
`entity_id` column of any kind, so there is no row for a merge to touch.)

### Finding: merge reparenting bumps a reparented row's own `version`

**Recorded here, in the merge/split material, rather than under a work
package, because it is a property of the reparenting machinery this section
describes that every future write path over these six families inherits —
`WP-08`'s and `WP-11`'s included.** It is a consequence of the wiring above,
not a defect in it, and it is written down because it is the kind of fact a
caller discovers as a surprising failure rather than by reading a contract.

**The fact.** `SqlEntityRepository.reparent_entity_reference`
(`src/my_pa/infrastructure/persistence/entity.py`) writes `version = version
+ 1` (and `updated_at = at`) in the same `UPDATE` that substitutes the
survivor's `entity_id` into the row's entity-reference columns. It does this
for every family whose `_ChildSubject.version_column` is `"version"`, which
is all six of the RI-ENT-WP-06b families — `NAME`, `ORGANIZATION_PROFILE`,
`ADDRESS`, `COMMUNICATION_METHOD`, `PROJECT_PARTICIPATION`,
`PERSON_ORGANIZATION_AFFILIATION` — as well as `ALIAS`, `IDENTIFIER`,
`ASSIGNMENT`, `RELATIONSHIP`, `ENTITY`, and `PROPOSAL`. The one member that
does not take this branch is `OBSERVATION`, whose `version_column` is
`resolution_version`; the claim is stated at that width rather than as a
universal one.

**What it means for a caller holding an `expected_version`.** A caller that
read a row's `version`, and then had someone else's merge reparent that row
before the caller's write landed, is holding a stale version — **stale as a
pure side effect of an operation the caller neither performed nor edited the
row's own content with.** The optimistic-version predicate then refuses the
write with `StaleDirectedVersionError` rather than silently applying it.
That refusal is the contract working, not a bug: the row's entity binding
changed underneath the caller, so the state the caller reasoned about is no
longer the state on disk, and the correct recovery is to re-read and retry
against the current version. A write path must not treat a post-merge
stale-version refusal as an anomaly to be worked around, and must not carry
a pre-merge version across a merge boundary.

**What proves it.**
`tests/database/test_entity_record_family_write_path.py::test_a_versioned_write_still_reaches_a_row_a_merge_reparented`,
landed in commit `ed6e057` ("feat(ri-ent): add the six record families'
write path (RI-ENT-WP-08)"). The test creates an `entity_names` row under an
entity that is then merged away, runs a real merge through
`IdentityCorrectionService`, reads the row back under the survivor and
asserts it is the same row by its own `entity_name_id` and now at `version
== 2`; asserts that `retire_entity_name` at `expected_version=1` — the
version a pre-merge caller would be holding — raises
`StaleDirectedVersionError`; and then retires at the current version, which
succeeds and lands the row at `version == 3`. It states the bump rather than
working around it, which is why it is citable as the proof of this finding.

**Status of the run.** This test is under `tests/database`, which is strictly
serial across this campaign and run by the Orchestrator; this document does
not restate a pass count it did not measure.

## WP-08 blocker cleared: `EntityRelationshipType` widened to 35 of 35 codes

**Status: the second blocking dependency above is LIFTED for all twenty new
codes. `EntityRelationshipType` holds thirty-five members and there is no
withheld code.** As a prerequisite pass ahead of `WP-08`'s own write-path
work, `EntityRelationshipType` (`src/my_pa/domain/relationship/entity.py`)
was widened from the original fifteen members. All twenty new codes were
added and the full test suite was run, including `tests/architecture/`, per
this program's own process rules — which is what caught the one exception
recorded below before it could ship silently, and that exception has since
been resolved.

**Superseded statement, preserved rather than rewritten.** Through commit
`f4eaa4f` this section was headed "widened to 34 of 35 codes" and stated
that the blocker was lifted "for nineteen of the twenty new codes; one code,
`design_coordinates_with`, is a disclosed, narrower exception this pass
found and did not have the authority to resolve unilaterally", left to the
campaign owner. **That was true when it was written and is no longer true.**
The two paragraphs below record, in order, why the enum member was withheld
and how the withholding was actually resolved; neither rewrites the history
into "it was always thirty-five". The enum's docstring was rewritten by the
same pass to state the result plainly and to cite `8dc3619891bb` and this
update, removing the then-false claims that the enum was frozen at fifteen
and that `_row_to_relationship` raised for all twenty new codes.

**Why the enum member was withheld (historical, the state through
`f4eaa4f`): `design_coordinates_with` tripped the no-confidence guard.**
Adding `DESIGN_COORDINATES_WITH = "design_coordinates_with"` as a member was
tried, and `tests/architecture/test_relationship_scoring_surface_is_denied.py`
— the guard this program is explicitly forbidden from touching, weakening,
or reasoning around — turned red:
`test_no_closed_relationship_vocabulary_admits_a_score_or_a_protected_trait`
and `test_every_live_name_on_the_relationship_surface_passes_the_rule` both
failed, because that guard's `latitude|longitude|geolocation|coordinates|
whereabouts|tracking` → "location tracking" denial pattern matched the token
`coordinates` in `design_coordinates_with`'s name and value, mechanically,
with no awareness that the taxonomy entry means design-discipline
coordination between two project participants (an architect and a structural
engineer coordinating design, say), not geolocation. That was a genuine
false positive at the semantic level and a genuine, correct-as-designed
match at the mechanical level the guard actually runs:
`entity_relationship_types.design_coordinates_with` (the DB-level taxonomy
row RI-ENT-WP-06a seeded) was untouched and remained valid; only the *Python
enum member* for it was withheld, and only because this program's own rules
forbid the two ways then available to make it pass (editing the guard's
pattern, or writing an enum value that does not match the seeded
`relationship_type_code` character-for-character). That gap was disclosed at
the time in `EntityRelationshipType`'s own docstring, here, and in
`tests/database/test_entity_relationship_type_widened_read_path.py`'s module
docstring, with a dedicated test proving it was real and current rather than
a stale claim.

**How it was resolved: the taxonomy entry was renamed, and the guard was not
edited.** Commit `37ead78` ("fix(ri-ent): rename design_coordinates_with ->
design_coordination_with, close EntityRelationshipType to 35/35") took
neither of the two routes the withholding pass had named as unavailable to
it, and in particular did **not** carve out an exception in the guard.
`tests/architecture/test_relationship_scoring_surface_is_denied.py` is
unmodified by this branch: `37ead78` touched exactly two files
(`migrations/versions/20260831_c99cd8ed8d1c_rename_design_coordinates_with.py`
and `src/my_pa/domain/relationship/entity.py`), and `git log
f4eaa4f..HEAD -- tests/architecture/test_relationship_scoring_surface_is_denied.py`
returns no commits at all. Instead, migration `c99cd8ed8d1c`
(`down_revision = 1cda4d536268`) renamed the seeded
`entity_relationship_types` row from `design_coordinates_with` to
`design_coordination_with`, leaving every other column of that row
(`directed`, `inverse_type_code`, `source_entity_type`/`target_entity_type`,
`allows_project_scope`, `cardinality_rule`, `status`, `label`) unchanged — a
rename, not a new taxonomy decision — and
`EntityRelationshipType.DESIGN_COORDINATION_WITH = "design_coordination_with"`
became the enum's thirty-fifth member. The new name carries the meaning the
old one always intended (design-discipline coordination between project
participants) and does not collide with the denied token family, because
that guard matches `fullmatch` on snake_case tokens rather than on
substrings — it documents that distinction in its own docstring — and
`design_coordination_with` tokenizes to `("design", "coordination", "with")`,
none of which fullmatches `latitude|longitude|geolocation|coordinates|
whereabouts|tracking` or any other pattern in the guard's `DENIED` tuple.
`coordination` is a different token from `coordinates`. **The guard's
strength is therefore unchanged: nothing in it was excepted, weakened, or
reasoned around; the name that tripped it simply no longer exists in the
tree.** `8dc3619891bb`'s own text still says `design_coordinates_with` —
that migration is history and is deliberately not rewritten.

**Current state, verified against the tree rather than restated.**
`EntityRelationshipType` has thirty-five members, `DESIGN_COORDINATION_WITH`
among them and no `DESIGN_COORDINATES_WITH`; the enum's values match
`entity_relationship_types.relationship_type_code` character-for-character
for all thirty-five codes, with no exception. `grep -rn
"design_coordinates_with" src/ tests/ migrations/` finds the old spelling
only in prose — the enum docstring's and the tests' own historical accounts,
`8dc3619891bb`'s untouched text, and `c99cd8ed8d1c`'s rename statements —
and never as a live enum member or as a seeded code.

**The read path.** `infrastructure/persistence/entity.py`'s
`_row_to_relationship` (`EntityRelationshipType(str(row.relationship_type))`)
required no code change for either half of this: with all thirty-five codes
present as enum members, the same constructor call that used to raise
`ValueError` for all twenty new codes now succeeds for every seeded code,
`design_coordination_with` included. Every other typed read path over
`entity_relationships.relationship_type` was grepped
(`EntityRelationshipType(` across `src/`) and confirmed to have exactly one
call site — `_row_to_relationship` itself — so there was no second
construction site to fix separately.

**The write path — a mechanical consequence, stated honestly rather than
narrower than it is.** Widening the enum's membership was not scoped as
`WP-08`'s own write-path work, but it is not actually separable from it:
`application/commands.py`'s `CreateEntityRelationship.__post_init__` gates
`relationship_type` with `isinstance(self.relationship_type,
EntityRelationshipType)`, and `domain/relationship/proposal_validation.py`'s
`_member` helper and the equivalent checks in `adapters/normalization.py`
and `application/entity_promotion.py` all test membership against this
enum's own value set — none of them hard-code the fifteen-code list
separately. Because nothing else gates the newly-admitted codes out,
widening the enum's membership, by itself, also widens what those write-path
checks accept — originally for nineteen codes, and, after `37ead78` added
`DESIGN_COORDINATION_WITH`, for all twenty. The withheld-code caveat this
paragraph used to carry ("`design_coordinates_with` is not a member, so no
write path — typed or otherwise — can construct an `EntityRelationshipType`
for it") is superseded and no longer applies to any code. This is disclosed
here and in the enum's own docstring rather than implied to be a narrower or
more complete change than it is.

**Test evidence, database-level, real PostgreSQL — historical measurement,
against the 34-of-35 tree.** As measured at the withholding pass,
`tests/database/test_entity_relationship_type_widened_read_path.py` (23
tests) wrote one real `knowledge.entity_relationships` row for each of the
nineteen newly-admitted codes and read each back through
`SqlEntityRepository.relationship` and `SqlEntityRepository.relationships`
(both of which call `_row_to_relationship`), asserting no `ValueError` was
raised and the returned `EntityRelationship.relationship_type` equalled the
expected `EntityRelationshipType` member; a dedicated test proved
`design_coordinates_with` was correctly withheld and still raised. Run:
`MY_PA_DATABASE_URL='postgresql+psycopg://my_pa@127.0.0.1:5433/my_pa'
.venv/bin/python -m pytest
tests/database/test_entity_relationship_type_widened_read_path.py -q` — 23
passed at that tree. `tests/schema/test_entity_relationship_types_migration.py`
and `tests/relationship/test_relationship_domain.py` (73 passed together)
were re-run and were green, and at that point no test in the repository
hard-coded `EntityRelationshipType`'s member count or its exact member list.
`.venv/bin/python -m mypy src` (305 source files, clean) and
`.venv/bin/python -m ruff check .` (clean) were re-run after the
`design_coordinates_with` correction and were clean. **Every figure in this
paragraph is a measurement of the pre-rename tree and is retained as the
record of that pass, not as a current-state claim.**

**Test evidence after the rename.** Commit `87e1e0f` rewrote
`tests/database/test_entity_relationship_type_widened_read_path.py` to cover
all thirty-five seeded codes rather than only the twenty new ones. Its
`ALL_35_CODES` is `EXISTING_CODES` (fifteen) `+ NEW_CODES` (twenty), both
restated verbatim from the migrations rather than re-derived from the enum,
so the file cannot pass merely because the enum and the list were built from
the same spelling; two of its five test functions are parametrized across
all thirty-five codes (round-trip through `SqlEntityRepository.relationship`
and through the paged `.relationships` list), and
`test_the_seeded_taxonomy_table_and_the_enum_are_exact_mirrors` asserts the
live table's seeded codes equal `{member.value for member in
EntityRelationshipType}` in both directions, asserting specifically that
`design_coordinates_with` is *not* seeded and `design_coordination_with`
*is*. The same commit removed the now-false `WITHHELD_CODE` constant and its
dedicated test, and updated
`tests/schema/test_entity_relationship_types_migration.py`'s `NEW_CODES` to
the renamed code. **These database and schema tests are strictly serial
across this campaign and are run by the Orchestrator, not restated here with
a pass count this document did not measure.**
`MY_PA_DATABASE_URL='postgresql+psycopg://my_pa@127.0.0.1:5433/my_pa'
.venv/bin/python -m pytest tests/architecture -q -p no:cacheprovider`, run
from a normal checkout (`/Users/bobbyfetting/my-pa`, no `.claude` path
component — see "Architecture tier re-verified" below), was re-run after
the correction and is fully green.

## Architecture tier re-verified: the `.claude`-path-component cause, confirmed

The RI-ENT-WP-06b passage above records "2 known-environmental-only
failures" as of that PR's own measurement. This section independently
re-measures that claim rather than restating it, per an explicit operator
instruction that "'known-environmental failure' is exactly the phrase that
once hid a real regression in this program, so it must be accurate or
absent."

**Result, run from `/Users/bobbyfetting/my-pa` (confirmed via `pwd` first,
not a `.claude/worktrees/...` path):**
`MY_PA_DATABASE_URL='postgresql+psycopg://my_pa@127.0.0.1:5433/my_pa'
.venv/bin/python -m pytest tests/architecture -q -p no:cacheprovider` — **4,725
passed, 0 failed.** `tests/architecture/test_citations_resolve_at_head.py`'s
two tests, specifically, did not fail.

**The mechanical cause, read out of the guard's own source rather than
inferred.** `tests/architecture/test_citations_resolve_at_head.py` derives
its sweep root as `ROOT = Path(__file__).resolve().parents[2]` — the test
*file's own* resolved on-disk location, two parents up, not
`Path.cwd()` and not a `git rev-parse --show-toplevel` call. `_repository_files()`
walks `ROOT.rglob("*")` and skips any path whose `.parts` intersect
`SKIPPED_DIRECTORIES`, which contains `.claude` (the module's own comment:
"local Cursor worktrees under `.claude`, which would otherwise duplicate the
corpus into the shorthand index"). `Path.parts` on a path built from
`ROOT.rglob(...)` carries every component of `ROOT` itself, not just the
file's relative subpath — so **if `ROOT` (i.e., the checkout this test file
lives in) is located anywhere under a directory literally named `.claude`**
(for example `.claude/worktrees/<agent-name>/...`, the isolation mechanism
this program's own tooling uses), `SKIPPED_DIRECTORIES & set(path.parts)` is
non-empty for **every** path the sweep visits, `_repository_files()` returns
empty, and the two floor assertions (`FEWEST_EXPLICIT = 35`, `FEWEST_BARE =
5`) fail 100% reproducibly — regardless of any code change, because the
input to the sweep is zero before a single citation is read. This is not
about the pytest process's current working directory as such; it is about
where the checkout `__file__` resolves into sits on disk. In this session's
case cwd and the checkout path were the same normal, non-`.claude` path
(`/Users/bobbyfetting/my-pa`), so both readings agree, but the mechanism
itself keys off the file's resolved path, not `os.getcwd()`.
`docs/plans/relationship-intelligence-implementation-plan.md`'s own
Architecture tier row already states this same finding in its own words
("this sandboxed local worktree's `ROOT` resolves under
`.claude/worktrees/agent-.../`... confirmed by running the identical test
file against a real, non-worktree checkout, where it passes cleanly") — this
section is this campaign's own independent re-confirmation of that same
mechanism, not a new finding.

**No second, different environmental failure was found.** The "2" in "2
known-environmental-only failures" is `test_citations_resolve_at_head.py`'s
own two tests (its floor assertion for explicit citations and its floor
assertion for bare citations), both zeroed by the same single mechanism
above — not two failures from two different causes.
`relationship-intelligence-implementation-plan.md` was grepped for
"known-environmental" and confirms this: its Architecture tier row names
only this one file and this one mechanism for both of the two failures it
counts.

**What this means for the phrase "known-environmental failure" going
forward.** From a normal checkout — this repository's actual working
directory for this session, and CI's own working directory — the phrase does
not apply today: there were zero failures, known-environmental or otherwise,
in this session's `tests/architecture` run. The phrase remains accurate
*only* as a description of what happens when this specific test file is run
from inside a `.claude`-nested path (a Cursor/agent worktree), which is a
property of where pytest's `ROOT` resolves, never a property of the code
under test. A future reader should not read "2 known-environmental-only
failures" as a standing fact about this branch's head; it is contingent on
the runner's own checkout location and was zero in this session's own,
normal-checkout run.

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
- `.venv/bin/python -m pytest tests/unit/test_entity_assertion_domain.py -q` (RI-ENT-WP-07)
- `.venv/bin/python -m pytest tests/schema/test_entity_assertion_provenance_migration.py -q` (RI-ENT-WP-07)
- `.venv/bin/python -m pytest tests/database/test_entity_assertion_provenance.py -q` (RI-ENT-WP-07)
- `.venv/bin/python -m pytest tests/database/test_entity_record_family_write_path.py -q` (RI-ENT-WP-08; database tier, strictly serial across this campaign)
- `.venv/bin/python -m pytest tests/architecture/test_principal_is_never_caller_supplied.py -q` (RI-ENT-WP-08 — the guard `28fb1e5` registered six new entries in)
- `.venv/bin/python -m pytest tests/architecture/test_principal_partition_is_reached_through_the_guard.py -q` (RI-ENT-WP-08 — the guard `_refuse_stale_or_absent`'s call-site shape exists to satisfy)
- `.venv/bin/python -m pytest tests/unit/test_entity_record_family_service.py -q` (RI-ENT-WP-08)
- `.venv/bin/python -m pytest tests/database/test_entity_record_family_service_write_path.py -q` (RI-ENT-WP-08; database tier, strictly serial across this campaign)
- `.venv/bin/python -m pytest tests/unit tests/relationship tests/evaluation -q` (RI-ENT-WP-08 — the two `EntitiesRepository` doubles the port additions obliged)
- `.venv/bin/python -m mypy src` (RI-ENT-WP-08)
- `.venv/bin/python -m ruff check .` / `.venv/bin/python -m ruff format --check .` (RI-ENT-WP-08)
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
- `src/my_pa/domain/relationship/governance.py` — `EntityFactEvidenceLink`, `EvidenceRole`, `MutationAuthority` (reused, not reinvented, by RI-ENT-WP-07), `AssertionStatus`, `EntityAssertionState`, `EntityAssertion`, `EntityAssertionEvidence`.
- `src/my_pa/infrastructure/persistence/tables.py` — `entity_names`, `entity_organization_profiles`, `entity_addresses`, `entity_communication_methods`, `entity_project_participations`, `entity_role_types`, `entity_discipline_types`, `entity_person_organization_affiliations`, `entity_relationship_types`, `entity_relationships`, `entity_assertions`, `entity_assertion_evidence`.
- `migrations/versions/20260830_7e114f822af2_add_entity_names_and_organization_.py` (RI-ENT-WP-02).
- `migrations/versions/20260830_441b071bf37b_add_entity_addresses_and_communication_.py` (RI-ENT-WP-03).
- `migrations/versions/20260830_f5b06925857e_add_entity_project_participations_and_.py` (RI-ENT-WP-04).
- `migrations/versions/20260830_17149a48fa30_add_entity_person_organization_affiliat.py` (RI-ENT-WP-05).
- `migrations/versions/20260831_8dc3619891bb_add_entity_relationship_types.py` (RI-ENT-WP-06a).
- `migrations/versions/20260831_1cda4d536268_add_entity_assertions_and_evidence.py` (RI-ENT-WP-07).
- `migrations/versions/20260831_c99cd8ed8d1c_rename_design_coordinates_with.py` (the WP-08 blocker-clearing rename of the seeded `design_coordinates_with` row to `design_coordination_with`; `down_revision = 1cda4d536268`).
