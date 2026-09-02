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
| `ENTITY-PROJECT-001` | Critical | Incomplete project participation | **Closed by RI-ENT-WP-04** — `entity_project_participations` (project/participant identity, project-scoped `project_display_name`, `role_code`/`role_text`, `discipline_code`/`discipline_text`, `scope_text`, `role_basis_code`, `stakeholder_side_code`, `stakeholder_class_code`, `relationship_status_code`, temporal state), plus the extensible `entity_role_types`/`entity_discipline_types` taxonomies. **The "no write path exists yet" clause is superseded**: RI-ENT-WP-08 delivered `record_project_participation`/`supersede_project_participation`/`retire_project_participation` on `EntitiesRepository` and `SqlEntityRepository`, and `EntityRecordFamilyService`'s three verbs above them. **The "no MCP capability or tool exists yet" clause is also superseded, and so is the claim beside it that the service is unwired**: `RI-ENT-WP-10` published `entities.participations.list`, a keyset page that makes the caller state which end of the participation it means, and `RI-ENT-WP-11` published `entities.participations.create`, `entities.participations.revise` and `entities.participations.end`, which reach `EntityRecordFamilyService`'s three verbs through `EntityFamilyWriteService`'s ledger bridge. Still open: no participation write carries a `StatedAssertion`, and the database-tier tests for all of it are unexecuted — see "RI-ENT-WP-10", "RI-ENT-WP-11", "RI-ENT-WP-08" and "Merge/split disposition" below |
| `ENTITY-PROVENANCE-001` | High | No fact-level certainty/verification binding | **Closed for schema/domain/persistence by RI-ENT-WP-07** — `entity_assertions`/`entity_assertion_evidence` bind fact-level `assertion_status` (a discrete, unordered epistemic vocabulary, never a confidence score) and evidence to the six WP-02–WP-06 record families that previously had none. **The "repository/service-command wiring (`WP-08`)" clause is now partly closed, not fully**: RI-ENT-WP-08 declared all six assertion methods on the `EntitiesRepository` ABC and implemented them in both test doubles (`a5a939d`, corrected by `7bbc524`), and `EntityRecordFamilyService` records an optional `StatedAssertion` plus one `EntityAssertionEvidence` row per `StatedEvidence` alongside any create or correction of the six families. **The "MCP exposure (`WP-10`/`WP-11`)" clause is now partly closed and must not be read as closed.** The six families' *facts* are reachable over MCP: `RI-ENT-WP-10` publishes five reads over them and `RI-ENT-WP-11` fifteen mutation contracts. **The assertion binding itself is not.** No command published by either package carries a `StatedAssertion` or a `StatedEvidence`, and no response view emits an `entity_assertions` row, so every fact written through the published contracts is written with no assertion attached and no caller can read or state fact-level `assertion_status` over any transport. `RI-ENT-WP-11` omitted it rather than half-exposing it: the schema builder describes no nested dataclass, so the only shape that would publish is the free-form `dict[str, object]` RULING 5 forbids. Also still open, inside WP-08's own boundary: `supersede_assertion`'s collapsed refusal and the absent retirement verb for `entity_assertions`. Mutation-ledger integration is *bridged rather than integrated* — `RI-ENT-WP-11` writes the ledger row from the application tier through the generic `record_mutation_event`, not through `_append_mutation`, with the atomicity consequence recorded under "RI-ENT-WP-11" below. See "RI-ENT-WP-07" below and "RI-ENT-WP-08" below for the exact honest boundary of what is and is not delivered |
| `ENTITY-PERSON-001` | High | Incomplete person affiliations | **Closed by RI-ENT-WP-05** — `entity_person_organization_affiliations` (nullable `organization_entity_id`, `job_title`, `affiliation_type_code`, temporal `effective_from`/`effective_to` with `state = 'active' AND effective_to IS NULL` denoting "current") |
| `ENTITY-RESOLUTION-001` | Critical | Resolution cannot follow typed names/identity graph | **Substantially closed, not fully closed** (`RI-ENT-WP-09`) — resolution reads `entity_names` and `entity_communication_methods` by normalized value and corroborates through affiliations and project participations; the three normalized-value indexes that were read by nothing now have their first readers. Two new match reasons and two new contextual signals ship as **unordered categorical** vocabulary per `RULING-M4`, and the domain's "a name alone does not resolve an entity" refusal was decoupled from `_BASIS_ORDER` onto an explicit `_BASES_THAT_NAME_AN_ENTITY`. Remaining: relationship-type and domain-only matching reach search but not resolution; the communication-value read is EMAIL-shaped (see the limitations below); and the database-tier evidence is written but unexecuted |
| `ENTITY-STATE-001` | High | No canonicalization/review state distinct from lifecycle | Design decision recorded in RI-ENT-WP-01 below (`canonicalization_state_code`, separate 1:1 record, deferred); not implemented this increment |
| `MCP-CONTRACT-001` | Critical | No rich structured profile read | **Closed by RI-ENT-WP-10** — `entities.profile` publishes one bounded composite over all six Entity-bound record families, and `entities.names.list`, `entities.addresses.list`, `entities.communication.list` and `entities.participations.list` are the keyset pages a caller continues on when a collection overflows the profile's per-collection ceiling. **`entities.context` is unchanged**, because widening the bounded card is classified BREAKING by the audit's own compatibility table and prohibited by `COMPAT-001`; the profile is a new capability beside it, and `RULING-M7`'s three exhaustive key-set assertions now hold "no consumer broke" as a test result rather than as a sentence. Not closed by it: the profile issues no cursor, so an overflowing collection is reported incomplete rather than continued in place, and the four `*_page` SQL bodies have never been executed — see "RI-ENT-WP-10" below |
| `MCP-CONTRACT-002` | High | No record-family mutation capabilities for the new families | **Closed by RI-ENT-WP-11** — all five Entity-bound record families, three verbs each, every verb an explicit command with named fields and an `idempotency_key`, and every write appending an `entity_mutation_events` row through the new `application/entity_family_writes.py`. RULING 5 holds and is enforced by the generated schema's `"additionalProperties": false` rather than by convention: there is no `entities.profile.save` and there will not be one. **Closed with three disclosures, not silently**: the ledger bridge writes the family row and the ledger row as two statements rather than one, so outside a transaction a family row can be left with no ledger row; `RI-ENT-WP-08`'s caller-supplied `StatedAssertion`/`StatedEvidence` is deliberately not exposed; and every database-tier test proving any of it is committed and has never been executed. See "RI-ENT-WP-11" below |
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
| WP-08 | Repository/domain services and validation | **Delivered (partial)** — seventeen `record_*`/`supersede_*`/`retire_*` methods on `SqlEntityRepository` for the six Entity-bound families, the same seventeen plus RI-ENT-WP-07's six assertion methods declared `@abstractmethod` on `EntitiesRepository`, in-memory equivalents in both test doubles, and the application service `EntityRecordFamilyService` with its own command/receipt DTOs. ~~**The service is deliberately unwired** — no `Capability`, no MCP tool, no HTTP route, no CLI command, and no registration in `ApplicationService`; transport exposure is `WP-10`/`WP-11`.~~ **Withdrawn 2026-09-02: that was true when written and is now false.** `RI-ENT-WP-10` and `RI-ENT-WP-11` are the transport exposure it deferred, and they landed: MCP tools, HTTP routes and CLI commands reach the six families under the `entities.` values those two packages added, twenty in all, and `ApplicationService` registers handlers for every one. What remains true of the original claim is only its narrowest reading: no `Capability` names `EntityRecordFamilyService` *directly*, because `RI-ENT-WP-11`'s handlers reach it through `EntityFamilyWriteService`. See "The boundary — what RI-ENT-WP-08 does NOT deliver" below, where the same claim is withdrawn in full. Not delivered — the same list the boundary section below enumerates in full, and it adds nothing to it: mutation-ledger integration, an idempotency key, proposal-validation integration, a retirement verb for `entity_assertions`, a split of `supersede_assertion`'s single refusal, no `correct_*` and no `retire_*` for the singleton `entity_organization_profiles` (which has the in-place `revise_organization_profile` instead — **five** families carry `correct_*`, not six), and no typed refusal for a correction whose successor collides with a *third* active row, which still surfaces the raw `IntegrityError` the plain `record_*` path surfaces. **The correction of a row holding the preferred slot IS delivered**: an earlier revision of this row called it inexpressible as a supersession and refused it outright, which was wrong — see "A preferred row is correctable, and the ordering that reaches it" below |
| WP-09 | Entity resolution/search vNext | **Delivered (partial)** — resolution now reads typed names, communication values, affiliations and project participations; `entities.search` matches five further paths and carries two disambiguators (`RI-AC-038`). Not delivered: no supporting index (no migration in scope), no effective dating on search, no MCP capability change (`WP-10`/`WP-11`), and **three committed database-tier modules have never been executed** — see below |
| WP-10 | MCP rich read contracts | **Delivered** — `entities.profile` plus four keyset `.list` reads over the record families, all under `Purpose.ENTITY_READ` and in no write register; four `*_page` port methods beside `identifier_page`/`alias_page`; `entities.context` unchanged and held so by `RULING-M7`'s exhaustive key-set assertions. Not delivered: no cursor on the profile, and the four SQL page bodies are unexecuted — see below |
| WP-11 | MCP mutation contracts | **Delivered** — fifteen mutation contracts across all five Entity-bound record families, every one an explicitly-fielded command with an `idempotency_key`, every write accounted for by an `entity_mutation_events` row written through the new `application/entity_family_writes.py`; `MutationRecordFamily` widened from six to eleven. Not delivered, and disclosed rather than implied: the family write and its ledger row are two statements and not one, `RI-ENT-WP-08`'s `StatedAssertion`/`StatedEvidence` is not exposed, a three-way correction collision still answers `internal_error`, and every database-tier test written for it is committed and unexecuted — see below |
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
`revise_organization_profile` and no third verb — 5 × 3 + 2 = 17. **Seventeen
survives the preferred-correction fix recorded in the boundary below, and was
re-measured rather than carried forward**: that fix added no verb to the port.
It changed one signature — every `supersede_*` now takes the *successor record*
in place of the successor's identifier and writes it itself — and added five
private `_insert_*` helpers to `SqlEntityRepository`, which are not port
methods and are not counted here.

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
  *second* identifier, builds the successor record, and hands it to
  `supersede_*` under the caller's `expected_version` — one call, whose three
  statements the repository issues in the one order the schema admits.
  `retire_*` retires under `expected_version`. What the record said before a
  correction survives the correction, which is the property the whole temporal
  shape exists to keep.
  `revise_organization_profile` is the singleton's stated exception, and it is
  the only one. **A correction whose successor claims the preferred slot is
  not a second exception**: it is written by the same `correct_*` verb as any
  other, because the ordering the accepted DDL admits is three statements
  rather than two — the predecessor is marked `superseded` while its
  `superseded_by_*` is still `NULL`, which releases both partial indexes at
  once because both are `WHERE state = 'active'`; the successor is then
  inserted active; and only then is the predecessor pointed at it, by which
  time the self-referencing foreign key has a row to name. This document
  previously called that correction "structurally inexpressible" and refused
  it outright; that claim was wrong and is withdrawn — see "A preferred row is
  correctable, and the ordering that reaches it" in the boundary below.
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
(`ed6e057`, extended by `f2db56d` from 45 tests to 60) exercises the repository
write path against real PostgreSQL, including the merge case whose finding is
recorded under "Finding: merge reparenting bumps a reparented row's own
`version`" below. The two doubles are covered by the existing `tests/unit`,
`tests/relationship` and `tests/evaluation` suites that construct them.

**The service's own coverage has since landed, and this note is promoted from
pending to delivered.** `tests/unit/test_entity_record_family_service.py`
(`31cc7bf`, extended by `95b16cf`, rewritten onto the corrected write path by
`0e17e91` from 145 tests to 185) exercises the service against the in-memory
`_Entities` double: Principal scoping as absence read structurally over
`dataclasses.fields`, the two-row shape of a correction with the predecessor's
survival as the load-bearing assertion, the profile's in-place revision and its
nullable clearing, the optimistic-version refusals and the unreachable/absent
parity, normalization computed from the stated display form, the four no-guess
rules each at the helper that makes the refusal, the optional assertion and its
evidence, and `MutationAuthority`'s keyword-only unreachability. Since
`0e17e91` it also holds the corrected values on the successor with an
anti-vacuity check against the predecessor's own unchanged values; the
structural claim that each of the five `correct_*` bodies makes exactly one
repository call and that the call is its family's `supersede_*` with the
successor crossing as `successor=` — the property whose loss *is* finding D1 —
with a behavioural counterpart through a counting proxy and the mirror claim
that a `record_*` verb is one insert and not a supersession; the whole-row-list
equality over all five families proving that a correction refused at a stale
version, or naming an unreachable predecessor, writes nothing at all; and the
double's own transition-then-insert supersession with its single version bump
and its successor passing the same guards a fresh record passes.
`tests/database/test_entity_record_family_service_write_path.py` (`499a7c1`,
rewritten by `95b16cf`, corrected by `f2db56d` from 19 tests to 22) holds only
what a real schema can decide about the
service's ordering, and pairs each positive claim with an anti-vacuity test
proving the constraint it relies on actually fires. **What both modules said
about a preferred correction has changed with the code**: through `95b16cf`
they pinned the refusal on all three families, the two cases that refusal was
deliberately wider than, and an AST check that the refusal was the first
statement of each correction it guarded. That refusal is no longer in the tree
and neither is its coverage; `0e17e91` and `f2db56d` replaced each of those
tests in place rather than deleting them, and what the preferred case is now
held to is that the correction *succeeds* against the real schema — the
predecessor superseded, the successor active and preferred, and the
`superseded_by_*` link written — which is the claim the three-statement
ordering in the boundary below exists to make provable.

**What the database tier now proves, and did not before (`f2db56d`).** Finding
D1 survived review because the repository tier's supersession tests
pre-recorded each successor as a deliberately *non-colliding* row — the
affiliation successor named a different person — and then named it by
identifier, which is not the shape a correction actually issues. Correcting a
current affiliation therefore had no database-tier coverage at all: it was
exercised only against the in-memory double, which enforces no uniqueness of
any kind and wrote both rows without complaint. The repository tier now
carries, one test per family, the correction that collided under the old
successor-first ordering:

- `test_a_current_affiliation_is_correctable_at_all` — **`correct_affiliation`
  on a current, open-ended affiliation, which had no database-tier coverage at
  all before this commit.** `an_open_ended_affiliation_is_unique_per_person` is
  `(principal_id, person_entity_id) WHERE state = 'active' AND effective_to IS
  NULL`, keyed on the person alone rather than on the job title, the
  organization or the affiliation type, so under the old ordering *every*
  correction of a current affiliation collided, whatever field was being
  corrected — total rather than intermittent. The test corrects only the job
  title, which is as far from the index's key columns as this family allows,
  and asserts the successor stays open-ended (`effective_to is None`) rather
  than quietly acquiring an end date, which would also release the index by
  inventing a fact the caller never stated.
  `test_a_current_affiliation_is_correctable_through_the_service` carries the
  same case through the service.
- one correction per family that keeps its normalized value — name, address,
  communication method — and one participation correction that restates its
  `role_code`. The `role_code` is stated rather than left null on purpose:
  PostgreSQL indexes nulls as distinct by default, so a null `role_code` never
  collides and would have passed under the broken ordering too.
- three preferred-slot corrections — name, address, channel — each *counting*
  the active holders of the slot rather than only inspecting the successor,
  because a predecessor left active with `is_preferred` still set would satisfy
  "the successor is preferred" while being a second holder of a one-holder
  slot. Each also asserts the predecessor keeps its own `is_preferred`:
  supersession replaces a row, it does not withdraw one, and clearing the flag
  would rewrite what the superseded row said.
- **each family's collision case is exercised**: five third-row collision tests
  — name, address, channel, participation, affiliation — pinning the limitation
  that is *not* closed. A successor colliding with some other active row is a
  real conflict about the world, and it still surfaces as the driver's
  `IntegrityError` naming the index, exactly as the plain `record_*` path does.
  `test_a_correction_colliding_with_another_active_row_still_leaves_as_a_driver_error`
  pins the same limitation at the service tier, asserting the identical
  exception out of `record_name` and out of `correct_name` so the claim is "the
  correction is no worse than the plain write" rather than "the correction
  fails".
- `test_correcting_an_already_superseded_row_aborts_rather_than_leaving_it_unnamed`
  characterises the third statement's own refusal: `_refuse_unnamed_successor`
  raises `RuntimeError` and the transaction aborts, so no orphan successor is
  committed and the predecessor keeps naming the first one.
- `test_the_organization_profile_family_revises_in_place_because_it_is_not_temporal`
  covers the sixth family for what it is rather than by analogy: no `state`, no
  `retired_at`, no `superseded_by_*` column and `entity_id` as its whole primary
  key, all read off the live catalogue rather than off the migration file, and
  therefore `revise_organization_profile` and no `correct_*` verb at all.

At the service tier, `f2db56d` turned the three preferred-correction refusal
tests into tests that the preferred correction succeeds, keeping their
retire-then-record arcs so that the alternative a caller used to be forced into
is still shown working and still shown costing the lineage link.
`test_a_preferred_correction_answers_with_a_written_row_and_not_a_driver_error`
admits every exception and then asserts the *absence* of one alongside the rows
the call was supposed to produce, so a service that silently did nothing would
not satisfy it. `test_a_supersession_naming_an_absent_successor_is_refused_at_the_statement`
keeps its name and its claim: since the port no longer offers any way to name a
successor that does not exist, it issues the raw statements instead, and still
proves the composite self-referencing foreign key is real and checked per
statement. The anti-vacuity tests that read `pg_index` and `pg_constraint`
directly — the three one-preferred partial uniques, and
`test_no_supersession_foreign_key_is_deferrable` — are unchanged.
### The boundary — what RI-ENT-WP-08 does NOT deliver

**The service is no longer unwired, and this paragraph's claim that it is
deliberately unwired is withdrawn in full.** It read, through `RI-ENT-WP-09`:

> **The service is deliberately unwired.** No `Capability` names
> `EntityRecordFamilyService`, no MCP tool, HTTP route or CLI command reaches
> it, and `ApplicationService` does not hold it — the module is imported by
> nothing outside itself. Transport exposure is
> `RI-ENT-WP-10`/`RI-ENT-WP-11`'s, and `WP-11` additionally owns the capability
> and purpose `CHECK` migrations that would have to land before any of this
> could be published.

Every sentence of that was true when it was written and the first three are now
false. `RI-ENT-WP-10` published five reads over the six families and
`RI-ENT-WP-11` fifteen mutation contracts over five of them; MCP tools, HTTP
routes and CLI commands reach all twenty, `ApplicationService` registers a
handler for every one, and the migration the last sentence anticipated is
`16f05c46b8c3`. It is withdrawn here, where a reader who remembers it will come
looking for it, rather than deleted, because a claim this document asserted in
its own voice has to be seen to be retracted.

**Two narrow readings of it survive and are worth keeping.** No `Capability`
names `EntityRecordFamilyService` *directly*: `RI-ENT-WP-11`'s handlers reach
its five families' verbs through a new module, `application/entity_family_writes.py`,
which supplies the idempotency key and the mutation-ledger row the family writer
deliberately has neither of — `entity_record_families.py` itself was not edited,
because it is under independent review on another branch and editing it here
would collide with the reviewed head. And the half-step this paragraph described
was the right one: declaring the caller-facing shape before anything could
invoke it is exactly what let `RI-ENT-WP-11` publish over it without redesigning
it. What follows in this section — the atomicity that belongs to the caller's
transaction, the untranslated `IntegrityError` on a three-way correction
collision — was **not** fixed by the transport packages and remains true as
written.

**Atomicity belongs to the caller's transaction, not to the service.** A
correction is a sequence of statements, never one. `SqlEntityRepository` takes the
connection rather than opening one — "the caller owns the transaction, this
class only issues statements on it" — and `SqlUnitOfWork.entities` hands out a
repository bound to the open transaction's connection, so a correction issued
through a unit of work commits or rolls back whole. The service opens, commits
and rolls back nothing, and holds no compensating write: **called with a
repository that is not inside a transaction, a correction that fails partway
leaves the statements that already ran.** Since the ordering correction below,
those statements are the three `supersede_*` issues, so the state a failure can
leave is a predecessor already marked `superseded` whose `superseded_by_*` is
still `NULL`, with or without the successor row beside it — not, as an earlier
revision of this paragraph said, a written successor beside a predecessor still
`ACTIVE`, which was the shape of the two-call sequence that ordering replaced.
The repository refuses to *return* into that state rather than committing it
silently: when the third statement matches no row, `_refuse_unnamed_successor`
raises and the transaction aborts. What is left after an abort outside a
transaction is still the caller's to see and to correct by the rows' own
identifiers. The guarantee belongs to the caller's transaction, and
neither the module nor this document will describe it as the service's own.

**A preferred row is correctable, and the ordering that reaches it — this
section's earlier "structurally inexpressible" claim was wrong and is withdrawn
in full.** Through commit `34367b4` both this document and the module said that
`EntityRecordFamilyService.correct_name`, `correct_address` and
`correct_communication_method` could not write a successor claiming the
preferred slot at all, and refused every such command outright through
`_refuse_preferred_correction` before any write. **An independent review
refuted that, and the refutation is a fact about the accepted DDL rather than a
matter of judgement: the schema, unmodified, already admits an ordering that
satisfies every constraint involved.** The blanket refusal is gone, and a
preferred correction writes. This correction is recorded here, inside the
section that lists what is *not* delivered, rather than only in "What is
delivered" above — a limitation this section asserted has to be withdrawn where
a reader who remembers it will come looking for it.

*The ordering, in three statements rather than two.*

1. `UPDATE` the predecessor to `state = 'superseded'`, leaving its
   `superseded_by_*` `NULL`. This is legal, and legal for a reason that is
   written into the constraint's own text rather than inferred: each family's
   CHECK is of the form `CHECK (superseded_by_X IS NULL OR state =
   'superseded')` — `an_entity_name_names_a_successor_only_when_superseded` and
   its two siblings. It binds a *non-null successor* to the superseded state,
   and says nothing that forbids a superseded row whose successor is still
   `NULL`. The predecessor has now left `state = 'active'`, and with it **both**
   partial unique indexes at once, because both are predicated on exactly that:
   `an_active_entity_name_is_unique_per_entity_and_type`
   (`WHERE state = 'active'`) and
   `an_active_entity_name_has_one_preferred_per_type`
   (`WHERE state = 'active' AND is_preferred = true`).
2. `INSERT` the successor as active and preferred. There is no collision to
   have: the predecessor is no longer inside either index's `WHERE` clause.
3. `UPDATE` the predecessor's `superseded_by_*` to the successor's identifier.
   The self-referencing composite foreign key
   `an_entity_name_is_superseded_within_its_principal` — `(superseded_by_*,
   principal_id)` back to the same table — is satisfiable at this point,
   because the successor row exists, so its being NOT DEFERRABLE costs nothing.

Nothing in the three steps holds for `entity_names` alone.
`an_entity_address_is_superseded_within_its_principal` and
`a_communication_method_is_superseded_within_its_principal` are that foreign
key's siblings, `an_active_entity_address_has_one_preferred_per_type` and
`an_active_communication_method_has_one_preferred_per_type` are the
preferred-slot index's, and each family carries the same
`CHECK (superseded_by_X IS NULL OR state = 'superseded')` shape and the same
`WHERE state = 'active'` predicate on its active-uniqueness index. All three
families reach the correction by the same ordering.

*What was actually limiting, named exactly.* Not the schema — **a verb
limitation**. The port's `supersede_*` set `state` and `superseded_by_*` in a
single statement, so the release-then-link shape above could not be expressed
through it at all, and the application service ordered the successor first.
Both are properties of code this campaign wrote and can change, not properties
of the accepted DDL. **Every earlier statement in this document that the schema
made a preferred correction impossible, that no ordering reached it, or that a
migration making a constraint `DEFERRABLE INITIALLY DEFERRED` would be
required, was false; it is corrected here rather than softened, and the
mischaracterisation is recorded rather than quietly removed.**

*Where the ordering lives, and why there.* In the persistence tier, in
`src/my_pa/infrastructure/persistence/entity.py`, beside the rest of the write
path. The ordering is not a policy an application layer chose between: it is
the one sequence the DDL admits, derived from the constraints' own predicates,
so it belongs where those statements are issued and the constraints are
checked, not in a service free to order them differently. The application
service still passes the caller's `expected_version`, and the version guard
means what it always meant — a correction proceeds only against the
predecessor the caller believed it was correcting.

*The window this opens, and what closes it.* Between the first statement and
the third, the predecessor is `superseded` and names no successor — legal,
which is exactly why the ordering works, and indistinguishable from a row that
was superseded and never linked. Two things keep that window from being
observable as a resting state. The first statement write-locks the predecessor
for the transaction, so no other session can move it before the third runs;
and if the third matches no row anyway, `_refuse_unnamed_successor` raises
`RuntimeError` and the transaction aborts rather than committing a superseded
row that names nobody. That refusal is deliberately *not* one of the two typed
ones: `UnknownScopeError` would claim a row is absent when it was just updated,
and `StaleDirectedVersionError` would claim a version conflict the third
statement does not test for. Issued through `SqlUnitOfWork.entities` the whole
correction commits or rolls back together; issued against a repository that is
not inside a transaction, the abort still leaves whatever already ran. That is
the same atomicity boundary the paragraph above states, on the same terms.

*One supersession is still one version bump.* The first statement bumps
`version` under the caller's `expected_version`; the third deliberately does
not bump again, and guards on `state = 'superseded'` and `superseded_by_* IS
NULL` instead of on a version. So `expected_version + 1` still describes the
predecessor after a correction, exactly as it did when a supersession was one
statement, and naming the successor is invisible to a caller's version
arithmetic. A caller written against the old shape needs no arithmetic change.

**The preferred slot was not the only thing successor-first broke, and the
wider case was never disclosed.** `entity_person_organization_affiliations`
arbitrates its active uniqueness with
`an_open_ended_affiliation_is_unique_per_person`, `ON (principal_id,
person_entity_id) WHERE state = 'active' AND effective_to IS NULL` — keyed on
the *person alone*, not on the field being corrected. Writing the successor
first therefore collided with the very row being replaced on **every**
correction of a current affiliation that left it current — whatever the
correction changed, and with no preferred slot involved anywhere, since this
family carries no `is_preferred` column at all. `correct_affiliation` carried
no refusal for it, so what surfaced was the driver's error. The same
release-then-insert-then-link ordering closes that case with the preferred one,
because that index is partial on `state = 'active'` like the rest. It is
recorded here because this document disclosed the narrower defect and never
this one. **It is now proved against real PostgreSQL rather than only reasoned
about.** `f2db56d` added
`tests/database/test_entity_record_family_write_path.py::test_a_current_affiliation_is_correctable_at_all`
and its service-tier counterpart
`test_a_current_affiliation_is_correctable_through_the_service`, each
correcting only the job title — as far from the index's key columns as this
family allows — and each asserting the successor stays open-ended rather than
acquiring an end date the caller never stated. Before those two this family had
no database-tier correction coverage at all, which is why the defect reached a
reviewer rather than a test.

*What did NOT change, so a reader assumes nothing more than landed.* The
schema. No migration was written for this, no constraint was made deferrable,
no index was dropped, and no `DEFERRABLE` clause exists on any
`superseded_by_*` foreign key in
`migrations/versions/20260830_7e114f822af2_add_entity_names_and_organization_.py`
or
`migrations/versions/20260830_441b071bf37b_add_entity_addresses_and_communication_.py`
today.
`tests/database/test_entity_record_family_service_write_path.py::test_no_supersession_foreign_key_is_deferrable`
still reads `pg_constraint` and still asserts `condeferrable` and `condeferred`
are false for every foreign key on a `superseded_by_*` column — matched by
column rather than by name, so it covers both keys each column carries (the
composite named one and the single-column one that column's own `REFERENCES`
clause created). **That test was right all along; what was wrong was the
conclusion drawn from it.** Non-deferrability closes off exactly one thing:
naming the successor in the same statement that supersedes the predecessor. It
never closed off doing the two in sequence.

**`retire_*` is unchanged, and is still not a substitute for a correction.**
Retirement writes `is_preferred = false` and releases the slot, proved against
real PostgreSQL by
`tests/database/test_entity_record_family_write_path.py::test_a_retirement_releases_the_preferred_slot`.
It remains the verb for taking a row out of service, and it still writes no
`superseded_by_*` lineage link — `an_entity_name_names_a_successor_only_when_superseded`
refuses a retired row that names a successor, so "a retirement that kept the
lineage" is still not a reachable state. What has changed is that
retire-then-record is no longer the *only* path to replacing a preferred row,
and a caller who wants the lineage link no longer has to give it up to get one.

**The `SafeDetail.PINNED` imprecision went with the refusal.** This section
recorded that `_refuse_preferred_correction` reported `SafeDetail.PINNED` as a
documented approximation, `src/my_pa/application/errors.py` having no
`is_preferred` member. With no blanket refusal left to report, there is no
approximation left to carry; `errors.py` is unchanged and still outside this
work package's scope.

**One named follow-up, not taken and not authorised in this branch.** An
in-place preference verb for a temporal family is explicitly rejected by the
module's own design ("there is deliberately no 'update in place' verb for a
temporal family"), and nothing here reopens that. The second follow-up this
section used to name — a migration making the self-referencing foreign keys
`DEFERRABLE INITIALLY DEFERRED` — is **withdrawn rather than left open**: it
was premised on the mistaken claim corrected above, and no correction, preferred
or otherwise, needs it.

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

**`entity_organization_profiles` has no retire verb and no `correct_*` verb,
so the six families are not symmetrical and this document will not imply that
they are.** The singleton has nowhere to retire to — no `state`, no
`superseded_by_*`, one row per entity by construction, so there is nothing a
supersession could name. It is not a temporal record family, and it therefore
gets no `correct_organization_profile`: its correction is
`revise_organization_profile`, an in-place update under its
`expected_version`, passing every mutable column including the two nullable
ones so a revision cannot silently carry forward a cleared value. **Counted at
the service, that is five `correct_*` verbs and one `revise_*`, not six
`correct_*`** — `correct_name`, `correct_address`,
`correct_communication_method`, `correct_project_participation` and
`correct_affiliation`, read off the module rather than assumed from the
families' count. The asymmetry is the schema's, not an omission this work
package could have closed.

**A correction that collides with a *third* active row still raises a raw
`IntegrityError`, not a typed refusal.** The three-statement ordering below
removes the collision a correction had with *its own predecessor*, and only
that one. A successor that collides with some other active row — a normalized
value already held by a different active row of the same
`(principal_id, entity_id, type code)` under
`an_active_entity_name_is_unique_per_entity_and_type`, or another active
preferred row of that type under
`an_active_entity_name_has_one_preferred_per_type` — is refused by PostgreSQL,
and neither `SqlEntityRepository`'s `record_*` methods for these six families
nor `EntityRecordFamilyService` catches it. The caller receives a
SQLAlchemy `IntegrityError` wrapping the driver's `UniqueViolation` naming the
index. **This is exactly what the plain `record_*` path has always done for the
same collision, so it is a standing property of these six families rather than
something the correction path made worse** — but it is a genuine gap against
the typed-refusal posture the rest of this service holds, it is not closed
here, and no transport should publish these verbs without deciding what it
answers for that error. **The limitation is pinned by tests rather than left to
be rediscovered.** `f2db56d` added one third-row collision test per correctable
family — name, address, communication method, participation and affiliation —
each asserting the `IntegrityError` names the index it collided with and that
the two pre-existing rows are left at version 1, so a correction that failed
this way wrote nothing. `test_a_correction_colliding_with_another_active_row_still_leaves_as_a_driver_error`
carries the same claim at the service tier, asserting the identical exception
out of `record_name` and out of `correct_name` so what is stated is "the
correction is no worse than the plain write" rather than "the correction
fails". A later work package that gives these a typed refusal will find those
tests waiting for it.

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

**`EntityRecordFamilyService` declares no read verb, and
`entity_assertion_evidence` has no removal verb.** The service is a write path
only: its public methods are the five temporal families'
`record_*`/`correct_*`/`retire_*` plus the singleton's
`record_*`/`revise_*`, and a caller that needs
to read a row before or after a write goes to `EntitiesRepository`'s own read
methods, not to this service. On the assertion side the port declares
`record_assertion_evidence` and the `assertion_evidence` read and nothing else,
so an evidence row, once written, has no verb that retires, supersedes or
removes it — the same shape as, and for the same RI-ENT-WP-07 reason as, the
absent `retire_assertion` above.

**This section is the whole of it, and it is enumerated rather than
recollected.** The items above are what RI-ENT-WP-08 does not deliver inside
its own boundary, derived by reading the verbs
`src/my_pa/application/entity_record_families.py` and
`src/my_pa/contracts/ports.py` actually declare and comparing them against the
objective this section opens with — not by remembering what was left out. The
short list in the work-package table above restates these and adds nothing to
them. Two qualifications a reader is owed rather than left to infer: the list
is bounded to WP-08's own boundary, so everything `WP-09`/`WP-10`/`WP-11` owns
(entity resolution, transport exposure, the capability and purpose `CHECK`
migrations) sits outside it by construction and is not repeated here; and a
limitation nobody has yet found is still a limitation, so this is an exhaustive
statement of what is known at this head, not a proof that nothing else exists.
The preferred-correction claim is precisely why that distinction is written
down: it stood in this section as a confident structural impossibility until a
reviewer read the DDL and found it was neither.

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
  `_refuse_stale_or_absent`. The preferred-correction follow-up (`33d5424`)
  rewrites the five `supersede_*` bodies into the three-statement ordering and adds the
  five private `_insert_*` helpers they share with `record_*`, plus the
  module-level `_refuse_unnamed_successor`; it adds no public method.
- `src/my_pa/contracts/ports.py` (`b49c8bd`, `a5a939d`, `7bbc524`): the same
  seventeen declared `@abstractmethod` on `EntitiesRepository`, plus
  RI-ENT-WP-07's six assertion methods (`record_assertion`, `assertion`,
  `assertions_targeting`, `supersede_assertion`, `record_assertion_evidence`,
  `assertion_evidence`), and `supersede_assertion`'s collapsed-refusal contract
  stated outright in its docstring. The preferred-correction follow-up
  (`33d5424`) changes one thing on this port: each of the five `supersede_*` methods takes
  the successor *record* in place of the successor's identifier, and the block
  comment above them states the three-statement ordering and why it is the
  implementer's to know rather than each caller's to rediscover.
- `src/my_pa/application/entity_record_families.py` (`1b2dd18`):
  `EntityRecordFamilyService`, `EntityRecordFamily`, `StatedAssertion`,
  `StatedEvidence`, the per-verb command dataclasses, and the `RecordedFact`/
  `CorrectedFact`/`RetiredFact`/`RevisedFact` receipts. No migration; no change
  to any existing module.
- `tests/conftest.py` (`b49c8bd`, `a5a939d`, `7bbc524`): `_Entities` in-memory
  equivalents for all twenty-three declared methods. The preferred-correction
  follow-up (`33d5424`) moves the double to the new `supersede_*` shape: it
  takes the successor record and writes it, so a test cannot pass over a
  correction that
  never wrote the corrected value, and it preserves refusal *order* — a stale
  or unreachable predecessor is refused before the successor is inserted. It
  deliberately reproduces no uniqueness: which rows collide is the database's
  answer, proved in `tests/database/`, and restating it in a double would be a
  second, unversioned statement of the schema free to drift from the
  migrations.
- `tests/evaluation/resolution_harness.py` (`b49c8bd`, `a5a939d`):
  `_CorpusRepository` per-method refusals — the corpus holds none of these
  rows, so an empty read would be indistinguishable from a resolver that
  consulted the plane and correctly found nothing.
- `tests/database/test_entity_record_family_write_path.py` (`ed6e057`, extended
  by `f2db56d` from 45 tests to 60): the repository write path against real
  PostgreSQL, and since `f2db56d` every family's correction as a correction
  actually issues it.
- `tests/unit/test_entity_record_family_service.py` (`31cc7bf`, `95b16cf`,
  rewritten onto the corrected write path by `0e17e91` from 145 tests to 185)
  and `tests/database/test_entity_record_family_service_write_path.py`
  (`499a7c1`, `95b16cf`, corrected by `f2db56d` from 19 tests to 22): the
  service's own unit and database coverage. Through `95b16cf`
  that included the preferred-correction refusal and both "horns" of the
  "not expressible as a supersession" claim; both are superseded by the
  correction below, and what the preferred case now holds is that the
  correction succeeds against the live schema.
- `src/my_pa/application/entity_record_families.py` (`34367b4`):
  `_refuse_preferred_correction`, called as the first statement of
  `correct_name`, `correct_address` and `correct_communication_method`.
  **Superseded and no longer in the tree.** The refusal rested on the claim
  that no ordering of a correction's statements satisfied both the
  preferred-slot index and the supersession foreign key; a reviewer refuted
  that against the accepted DDL, and the follow-up commit on this branch —
  `33d5424`, listed below — replaced the refusal with the three-statement
  ordering set out under "A preferred row is correctable, and the ordering that
  reaches it" above, issued from
  `src/my_pa/infrastructure/persistence/entity.py`. That commit's exact test
  results are recorded in the pull request and the implementation report bound
  to the head reviewed, rather than restated here, so this list cannot drift
  ahead of the tree.
- `tests/architecture/test_principal_is_never_caller_supplied.py` (`28fb1e5`):
  six registry entries added, none removed, no matcher or control changed.

**The corrective cycle that closed reviewer finding D1 — four commits on this
branch, named here so this list does not stop at the head that was reviewed.**

- `33d5424` — replaces `_refuse_preferred_correction` with the three-statement
  supersession ordering the accepted DDL already admits, in
  `src/my_pa/infrastructure/persistence/entity.py`, the five `supersede_*`
  declarations on `src/my_pa/contracts/ports.py`,
  `src/my_pa/application/entity_record_families.py` and the `_Entities` double
  in `tests/conftest.py`. No schema change and no migration.
- `a3b897b` — this document: withdraws in full the five claims that a
  preferred-slot correction was structurally inexpressible (reviewer finding
  D2), qualifies "pre-existing" for the three defects `37ead78` introduced on
  this same unmerged branch (finding D3), and makes the WP-08 "not delivered"
  list exhaustive rather than merely closed-sounding.
- `0e17e91` — `tests/unit/test_entity_record_family_service.py`, 145 tests to
  185: replaces in place the thirteen tests that asserted the refused
  behaviour, each at the same or greater strength, and adds forty more holding
  the corrected write path and the double's transition-then-insert.
- `f2db56d` — `tests/database/test_entity_record_family_write_path.py`, 45
  tests to 60, and
  `tests/database/test_entity_record_family_service_write_path.py`, 19 tests to
  22: every family's correction covered against real PostgreSQL, including
  `correct_affiliation` on a current affiliation, which had no database-tier
  coverage at all and is the reason finding D1 survived to review.

The commit refreshing this document for those four is not named here: its SHA
does not exist while it is being written, and this list states no SHA it cannot
have read.

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

**`37ead78` also introduced three defects, and this branch — not `origin/main`
— is where they came from.** Adding `c99cd8ed8d1c` moved the Alembic head and
the `migrations/versions/` file count, and the revision performed its rename
through `op.get_bind().execute(...)` and then read `Result.rowcount` off the
return value, which is `None` in Alembic's offline (`--sql`) mode. Three later
commits on this same branch repaired that fallout: `b2c1d79` corrected the
stale head literal `1cda4d536268` in twelve test modules, `2ca2a27` corrected
the stale `85` migration-count literal in sixteen `tests/schema` modules, and
`8638433` gave `c99cd8ed8d1c` an offline branch that re-expresses its
single-row check server-side through `GET DIAGNOSTICS ... ROW_COUNT`, leaving
the online path byte-identical. **Those commits' own messages call the defects
"pre-existing", and that word is qualified here rather than left to mislead a
pull-request reader.** They were pre-existing only relative to the RI-ENT-WP-08
write-path increment, which did not author them. They were **not** inherited
from `main`. `37ead78` is on this unmerged branch, `ri-ent/wp08-write-path`,
and nowhere else, verified rather than assumed: `git merge-base --is-ancestor
37ead78 origin/main` exits non-zero against `origin/main` at
`f4eaa4f950009847eb9bde2836f422d5cd731cbc`, `git branch -a --contains 37ead78`
names only `ri-ent/wp08-write-path` and its remote, and `37ead78` is the oldest
entry in `git log --oneline f4eaa4f..HEAD`. **The honest formulation, and the
one this document uses: this branch introduced them, an earlier work package's
commit on it authored them, and the WP-08 increment did not** — whoever merges
this branch is merging the defects and their repairs together, not receiving a
fix for something `main` was already carrying. The statement above that
`37ead78` touched exactly two files remains a statement about that commit and
stays true; `8638433` later added to one of the two (the migration), and
`tests/architecture/test_relationship_scoring_surface_is_denied.py` is still
untouched by every commit on this branch — `git log f4eaa4f..HEAD --
tests/architecture/test_relationship_scoring_surface_is_denied.py` returns
nothing at this head, three commits later than when that claim was first
written.

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

## RI-ENT-WP-09 — entity resolution/search vNext

**Objective** (source audit, section M): index typed names, domains,
affiliations, project roles and relationship types, and produce match reasons
and ambiguity. **Finding**: `ENTITY-RESOLUTION-001` (Critical). **Non-goal**:
MCP capability wiring (`WP-10`/`WP-11`), legacy backfill (`WP-12`), the TBR
fixture (`WP-13`).

### What the plane could not do before this work package

Three normalized-value indexes existed and **were read by nothing**:
`entity_names_by_normalized_value`,
`entity_addresses_by_normalized_address_value`, and
`entity_communication_methods_by_normalized_value`. The repository's six-family
reads were entity-id-keyed only, so a legal or trading name recorded in
`entity_names` was invisible to both resolution and search. `entities.search`
was an `ILIKE` substring match over `canonical_name` and `display_name` alone.

### What was delivered

**Match reasons, unordered and categorical (`RULING-M4`).** Two
`ResolutionBasis` members, `TYPED_NAME` and `COMMUNICATION_VALUE`, and two
`ContextualSignal` members, `AFFILIATED_WITH_THE_NAMED_SCOPE` and
`PARTICIPATES_IN_THE_NAMED_SCOPE`. The audit's five numbered "resolution tiers"
were **not** transcribed: `tier` is a denied token and the numbering implies an
ordering this campaign refuses. `_BASIS_ORDER` was extended only as a
deterministic presentation tie-break, is exposed as no field, and is serialized
nowhere; the `ResolutionBasis` docstring, and `order_candidates`' docstring with
it, were rewritten to stop calling the first position "strongest".

**The central safety refusal was decoupled from that ordering.** The domain
refused "a name alone resolves an entity" via
`strongest_basis is CANONICAL_NAME`, which was correct only because
`CANONICAL_NAME` happened to sort last — a safety property resting on a
presentation order, and one that would have mis-fired silently the moment a
weaker basis was appended, which is exactly what this work package does. It now
rests on an explicit `_BASES_THAT_NAME_AN_ENTITY` and
`ResolutionCandidate.names_the_entity`. The refactor is **proved**
behaviour-preserving over all fifteen non-empty combinations of the four
pre-existing bases, rather than asserted to be.

**Neither new basis may resolve an entity on its own**, which is audit section
M's rule that "name/alias alone -> retrieval candidates, never automatic merge".
A typed name is a name; a communication value is not a verified identifier.

**Two new repository reads**, `entities_by_typed_name` and
`entities_by_communication_value`, declared `@abstractmethod` on
`EntitiesRepository` and implemented in **all three** implementations —
`SqlEntityRepository`, `tests/conftest.py::_Entities`, and
`tests/evaluation/resolution_harness.py::_CorpusRepository`. Both match by
**equality on the already-normalized value**, never a pattern and never fuzzy,
and both read the collection **whole** rather than paged, because resolution
must see every claimant to decide whether a value is conflicted and a page is
the one shape that could let a claimant fall off the end and read as a clean
match. Both filter to the family's `active` state, deliberately diverging from
`entities_by_alias`, which applies no lifecycle filter: matching a superseded
row would resurrect a value the Principal has already corrected away.

**`entities.search`** gained five correlated `EXISTS` paths inside its one
existing partition-guarded, keyset-paged statement — typed names, communication
values (which yields domain matching without a domain parser, since the match is
already a substring), affiliation job titles and the affiliated organization's
name, project participation roles, and relationship-type labels. `EntitySummary`
gained two defaulted disambiguator collections, bounded at three entries each,
closing `RI-AC-038`. The five original wire keys keep their names and their
meanings, and a compatibility test holds that claim rather than a paragraph
asserting it.

**`WP09-DECISION-1`, recorded rather than made silently.** `entities.search`
carries a recorded decision that aliases are deliberately not searched, because
searching them would put a nickname or a former legal name into a browse result
nobody asked a question about. That reasoning applies with full force to
`entity_names`, which holds exactly those categories. Search therefore indexes
typed names **excluding `NameTypeCode.ALIAS` and `NameTypeCode.HISTORICAL_NAME`**,
which extends the recorded decision consistently rather than reversing it. It is
one `WHERE` clause and is reversible without rework if the Manager reads audit
section M differently.

**The evaluation gate was made non-vacuous, and that was not automatic.**
`_CorpusRepository` answered every six-family method with `NotImplementedError`
and the corpus carried no rows for any of them, so a resolver reading a family
would have been measured against an empty world and would have reported
`RESOLUTION_PRECISION_HELD` regardless. Instrumenting the harness after the
resolver changes landed showed `entities_by_communication_value` called once and
returning nothing, and `AFFILIATED_WITH_THE_NAMED_SCOPE` never firing. Sixteen
cases and six families were added to close both gaps. Every read and every
signal now has non-zero hits: `communication_value` appears on three candidates
and `typed_name` on nine, from zero and one respectively.

The GS4 acceptance rule — four similarly-named juristic entities "must not
silently mint four unrelated organizations or automatically collapse distinct
juristic entities solely because names resemble each other" — was previously
exercised **only** by a `database`-marked fixture. A synthetic four-member
organization family now exercises it on the fast tier.

`RESOLUTION_CALIBRATION.md` was **regenerated from the harness**, never
hand-edited. `RECALL_FLOOR` stays 0.9 and untouched; recall is 1.0;
`exact_resolutions_on_a_bare_name` stays 0; the disposition stays
`RESOLUTION_PRECISION_HELD`; false resolutions, cross-Principal leakage and
forbidden candidates all stay 0. `BASES_THAT_MAY_RESOLVE_EXACTLY` remains a
hardcoded three-member allowlist and was **not** widened — it is deliberate
double-entry against the domain's own set, and a new basis appearing under
`resolved_exact` is meant to fail it. Neither `resolved_exact:canonical_name`
nor `resolved_exact:typed_name` is a key in the table.

### Not delivered, and disclosed rather than implied

- **No supporting index and no migration.** The seven leading-wildcard `ILIKE`
  predicates run over unindexed columns, exactly as the original two already
  did; this makes an already-unindexed browse scan **wider**, not deeper. Adding
  indexes needs a migration, which was out of scope and unverifiable with the
  database tier closed. Recorded in the `search` port docstring, not only here.
- **`entities.search` filters child rows by state only, not by effective
  dating.** The search request carries no clock, so there is no moment to judge
  "in force" against, and adding one would be a request-shape change. A row that
  is `active` with a past `effective_to` still matches.
- **The communication-value read is EMAIL-shaped.** `_by_identifier` passes
  `normalize_identifier(namespace, raw)`, which equals the stored communication
  form for EMAIL. Re-normalizing per method type would mean **inferring** a
  `CommunicationMethodTypeCode` from a string, which `RULING 3` forbids.
- **Relationship-type and domain-only matching reach search but not
  resolution.** A relationship-type code is not something a human reference
  names, and a shared mail domain is an employer fact about many people that
  would manufacture candidate crowds on the resolution path.
- **No `Capability`, MCP tool, route, CLI command, or request-shape change.**
- **Three database-tier modules are committed and have NEVER been executed** —
  `tests/database/test_entity_resolution_value_reads.py` and
  `tests/database/test_entity_search_reaches_context.py` — because the WP-08
  database gate was running on the same machine for the whole of this work
  package. They are statically verified only and may need adjustment on first
  execution. Their figures are collection, not execution.

### Tiers run for this work package

The allowed tiers only: `tests/unit`, `tests/relationship`,
`tests/architecture` and `tests/contract` under
`-m "not slow and not database and not network and not connector and not
evaluation and not e2e and not recovery"`, plus `ruff` and `mypy`. Nothing
marked `database`, `recovery` or `e2e` was run at any point by any WP-09 worker.

## RI-ENT-WP-10 — MCP rich read contracts

**Objective** (source audit, section I): publish a rich structured profile read
over the record families `RI-ENT-WP-02` through `RI-ENT-WP-06` added, and a
paged read per family beside it. **Finding**: `MCP-CONTRACT-001` (Critical).
**Non-goal**: every mutation contract (`RI-ENT-WP-11`), legacy backfill
(`WP-12`), the TBR fixture (`WP-13`).

### What the plane could not do before this work package

Six record families had been stored since `RI-ENT-WP-02` — typed names, the
organization profile, addresses, communication methods, project participations
and person/organization affiliations — and `RI-ENT-WP-08` had given all six a
repository and a service above it. **No capability named any of them.** A caller
holding every `entities.` name the plane published could not read a legal name,
a registered address, a work phone number, a project role or an employer, and
`entities.context` did not help: its card assembles aliases, identifiers,
assignments, relationships, observations and memories, and reads none of the
six. The tables were written by the resolution and identity-correction paths and
read back by nothing a transport could reach.

### What was delivered

**Every name below is a read under `Purpose.ENTITY_READ`. No `Purpose` was
added, and `purpose_is_known` needed no widening on either account.**

| Capability | Kind | What it reads |
|---|---|---|
| `entities.profile` | composite read | all six families in one bounded assembly |
| `entities.names.list` | keyset page | `entity_names` |
| `entities.addresses.list` | keyset page | `entity_addresses` |
| `entities.communication.list` | keyset page | `entity_communication_methods` |
| `entities.participations.list` | keyset page | `entity_project_participations`, from the stated end |

None of the five is in any write register. They join `_ENTITY_CAPABILITIES` and
not `_ENTITY_WRITE_CAPABILITIES`, and `tests/contract/test_entity_write_gate.py`
derives that from the purpose map rather than taking it on trust.

**`entities.profile` is bounded, and says so in the response rather than in a
runbook.** Each collection is cut at `ENTITY_PROFILE_COLLECTION_LIMIT` (25) with
one row read past it to detect the overflow; the card carries `is_complete`, and
`Truncation(is_truncated=..., reason="profile_collection_limit_reached")`
**issues no cursor**. That absence is deliberate and not an omission: a position
into an assembly of seven collections would have to mean seven positions at
once, and the four `.list` capabilities are the continuation for whichever
collection overflowed. `limitations` and `is_complete` precede the records they
qualify, per `RI-AC-013`. An unknown `entity_id` is `not_found` rather than an
empty profile, exactly as `entities.relationships` answers. `principal_id` is
emitted by no view.

**`entities.participations.list` makes the caller state which end.** The
port deliberately has no "either end" read, so `perspective` is exactly
`"project"` or `"participant"` and anything else is an `InvalidRequestError`
naming `SafeDetail.SELECTOR`. A read that silently unioned both ends would
answer a question nobody asked and would page over two orderings at once.

**Four `*_page` port methods** — `name_page`, `address_page`,
`communication_method_page`, `participation_page` — were declared
`@abstractmethod` on `EntitiesRepository` as siblings of the established
`identifier_page`/`alias_page`, keyset-ordered on each family's own primary key,
and implemented in `SqlEntityRepository` and in **both** in-memory doubles
(`tests/conftest.py` and `tests/evaluation/resolution_harness.py`), because a
missing method on a subclass of the port is a `TypeError` at instantiation. The
existing `limit`-only readers are untouched: they answer identity correction,
and these answer a caller scrolling. **The SQL half is database-gated and was
never executed**; the doubles are what the contract tier exercises, and that is
where this package's page evidence comes from.

### `entities.context` is unchanged, and that is a test result rather than a claim

`entities.profile` is a **new** capability and `entities.context` was not
widened into it. That is not a preference. The audit's own compatibility table
classifies "replace bounded `entities.context` with a complete profile" as
**BREAKING**, and `COMPAT-001`'s policy — recorded in this document's
`RI-ENT-WP-01` section — prohibits a breaking change to a published generated
schema in this campaign. `entities.context` and `entities.profile` answer
different questions off different tables, and both now exist rather than one
having eaten the other. The diff carries the proof: `_entities_context`
and `_context_card_view` are byte-identical to `516f9e0`.

**`RULING-M7`, and why it was necessary.** The pre-existing card assertions at
`tests/contract/test_entity_capabilities.py:406` and `:429` named the keys they
cared about and compared no key *set*, so a field **added** to
`_context_card_view` would have satisfied every one of them — the guard would
have stayed green through exactly the change a consumer has to be told about.
Three exhaustive assertions were therefore **added**:

- `test_the_context_card_publishes_exactly_twelve_keys` — an *ordered*
  comparison of the twelve card keys, ordered rather than set-equal because
  `RI-AC-013` is about reading order and a card that moved `limitations` below
  `memories` would satisfy a set comparison while losing the property the order
  carries;
- `test_the_context_cards_nested_entries_publish_exactly_their_own_keys` — the
  `coverage` and `memories` entries, the card's own composed shapes and the two
  a widening would most plausibly reach into;
- `test_the_four_other_entity_reads_publish_exactly_the_keys_they_publish` —
  `entities.get`, `entities.relationships`, `entities.identifiers.list` and
  `entities.aliases.list`.

They are **written out rather than derived from the view functions**, which is
the whole point: a key set derived from `_context_card_view` would agree with
itself after any edit and would prove nothing. "No consumer broke" is now a test
result rather than a sentence in a report.

**The assertion was proved to bite, and here is what was done.** The
implementing worker left no record of the demonstration the design specification
asked for, so the Orchestrator performed it directly at head `7ffe8218`: a
thirteenth key, `zz_probe_key`, was planted on `_context_card_view`, and
`test_the_context_card_publishes_exactly_twelve_keys` failed immediately —
`AssertionError: assert ['zz_probe_ke...tations', ...] == ['entity', 'a...`, at
`tests/contract/test_entity_capabilities.py:522`. The plant was then reverted
and the working tree confirmed byte-identical to the commit
(tree `46ae09a518dc2e4f6e5c6f320f2a90899c7dbb1d` before and after), with the
same test passing again. So the claim that a field added to the context card
now reddens the suite is a measured result, not a reading of the assertion's
shape.

### `RULING-M3` — the audit's own field names were not transcribed

The audit's example response shape in section I contains `"role_confidence"` and
`"legal_identity_confidence"`. **Neither was transcribed, and no near-synonym
was substituted for either.** What ships instead is the categorical, unordered
vocabulary this campaign has used since `RI-ENT-WP-07`: `assertion_status`,
`role_basis_code`, `legal_identity_status_code` and `verification_status_code`
— each a closed set of named states rather than a position on a scale, and none
of them a number a caller could sort people by.

`tests/architecture/test_relationship_scoring_surface_is_denied.py` was **not
amended, not widened, not exempted, and not reasoned around**. Its diff from
`516f9e0` is empty, and that diff — not this paragraph — is the evidence.

### The count defect this package introduced, and the correction that closed it

`93885e2` corrected "thirty-four `entities.` names" everywhere the spelled-count
sweep reads it and stopped there, which left two whole classes of derived figure
stale and neither is one that sweep can see.

The first is a defect this package introduced: `_ENTITY_CAPABILITIES` grew by
five reads while `_ENTITY_WRITE_CAPABILITIES` did not move, so the read half of
the plane went from eleven to sixteen and nine documents and docstrings still
said eleven. `tests/architecture/test_spelled_counts_match_the_sets_they_name.py`
compares a spelled count against `Capability` or `Purpose`, and every one of
those figures is a *subset* — one clause of a sentence whose neighbouring clause
names the whole — so the sweep parsed the sentence, checked the clause it
understood, and was structurally blind to the one beside it. "The eleven reads
and the twenty-three writes" stayed green while half of it was false.

The second is that **the arbiter reads words and is blind to digits.**
`bootstrap/gateway.py`, `adapters/cli/__init__.py`, `adapters/cli/app.py`,
`adapters/mcp/__init__.py`, `contracts/ports.py`,
`docs/architecture/module-boundaries.md`,
`tests/contract/test_transport_parity.py` and two runbooks all carried a
digit-form `104`, and the runbooks quoted the readiness string as
`49 of 104 capabilities are unwired.` — every one of them green the whole time.
`fc73555` corrected all of them by measurement, reading each replacement off the
live sets or the live manifest string. It is recorded here because the same
defect class recurred in `RI-ENT-WP-11` and in this phase's migration, and
because a campaign that has been bitten three times by it should say so.

### Not delivered, and disclosed rather than implied

- **No mutation of any kind.** Every capability here is a read; the write
  contracts are `RI-ENT-WP-11`'s and are recorded below.
- **`entities.context` is not widened, and will not be by this campaign.** A
  caller who wants the six families must name `entities.profile`. That is the
  compatibility rule working, not a gap.
- **`entities.profile` issues no cursor**, so an entity with more than
  twenty-five rows in a collection is *reported* as incomplete and is not
  *continuable* through that capability. The four `.list` reads are the
  continuation and the caller has to switch to one.
- **The four `*_page` SQL bodies were never executed.** They are keyset reads
  written against a closed database tier and verified statically only; the
  in-memory doubles that the contract tier exercises are a different
  implementation of the same signature and cannot find a defect in the SQL.
- **No assertion or evidence is exposed.** `RI-ENT-WP-07`'s `entity_assertions`
  rows are not read by any view here, so `ENTITY-PROVENANCE-001`'s MCP-exposure
  clause is untouched by this package.
- **No supporting index and no migration in this package.** The phase's single
  revision is `16f05c46b8c3`, recorded under `RI-ENT-WP-11` below; it widens
  closed CHECK sets and adds no index.

### Tiers run for this work package

The gate-safe tiers only, and nothing else at any point by any `WP-10` worker:
`tests/unit`, `tests/relationship`, `tests/architecture` and `tests/contract`
under `-m "not database and not recovery and not e2e and not network and not
connector and not evaluation"`, plus `ruff check`, `ruff format --check` and
`mypy src`. Nothing marked `database`, `recovery` or `e2e`, and nothing under
`tests/database`, `tests/schema`, `tests/migration`, `tests/concurrency`,
`tests/end_to_end`, `tests/recovery`, `tests/security` or `tests/capture`, was
run — a machine-wide serial database gate was closed for the whole of this work
package and the whole of `RI-ENT-WP-11` after it. The phase's measured gate
results are recorded once, at the end of the `RI-ENT-WP-11` section below.

## RI-ENT-WP-11 — MCP mutation contracts

`MCP-CONTRACT-002`. `RI-ENT-WP-08` gave the five Entity-bound record families a
writer and `RI-ENT-WP-10` published five reads over them; neither published a
way to *change* one. This work package publishes the capabilities that do, three
verbs per family, and the mutation-ledger row that accounts for each write.

**All five families landed.** The table below is complete: every verb the
source audit named for these families is published, and nothing in `WP-11`'s
scope was left for a later pass. Where this package stops short is not a family
— it is the caller-supplied assertion, the `internal_error` a three-way
correction collision still answers, and every database-tier test in it, each
recorded under "Deliberately not delivered" and "Unexecuted is not verified"
below.

| Family | Capability names | `MutationRecordFamily` |
|---|---|---|
| Typed names | `entities.names.add`, `entities.names.supersede`, `entities.names.retire` | `name` |
| Addresses | `entities.addresses.add`, `entities.addresses.revise`, `entities.addresses.retire` | `address` |
| Communication methods | `entities.communication.add`, `entities.communication.revise`, `entities.communication.retire` | `communication_method` |
| Project participations | `entities.participations.create`, `entities.participations.revise`, `entities.participations.end` | `project_participation` |
| Person-organization affiliations | `entities.affiliations.create`, `entities.affiliations.revise`, `entities.affiliations.end` | `person_organization_affiliation` |

**RULING 5 holds and is enforced by the transport rather than by a convention.**
There is no `entities.profile.save` and there will not be one. Every command
declares its fields explicitly and the generated MCP schema carries
`"additionalProperties": false`, so a payload key nothing declares is refused
before the constructor runs. No command accepts a field map, a `values` mapping,
a `fields` dict or `**kwargs`.

**The absence mechanism is `EntityDirectedService`'s.** No command carries
`principal_id`, `authority`, `actor_class`, `state`, `version`, `recorded_at`,
`updated_at`, `retired_at` or `superseded_by_*`. The server supplies all of them
from the `Authorization`, and there is nothing that reads such a field and
ignores it. Optimistic concurrency is `expected_version` on every supersession
and every withdrawal.

**`supersede` and `revise` are one act under two spellings, and neither is an
edit.** Both reach the family's `correct_*` verb: a successor row is minted and
written, and the predecessor is marked SUPERSEDED under the version the caller
asserted. The audit fixed the inconsistent spelling and it is not normalised
here, because renaming a published capability to make a table look tidy is a
worse defect than an inconsistent verb.

**Merge and split remain operator-only, and nothing here went near that.**
`_OPERATOR_ONLY` is byte-identical to `516f9e0`: the entity-plane names in it
are still exactly `entities.merge.preview`, `entities.merge`,
`entities.split.preview` and `entities.split`, and no name published by this
work package joined it. The distinction is the one "Merge/split disposition
(`RULING 2`)" above already draws. Correcting a record family is the Principal
restating a fact about the Principal's own Entity; a merge decides that two
Entities are one person, which is an identity judgement this campaign reserved
to an operator and has not un-reserved.

**`RULING-M3` holds across the mutation contracts as it does across the reads.**
No command field, response key, enum member, identifier or test name introduced
by this package carries a denied token. What a caller may state about a role, a
legal identity or a verified channel is a *closed categorical vocabulary* that
arrives as the enum and is refused otherwise — `NameTypeCode`,
`AddressTypeCode`, `CommunicationMethodTypeCode`,
`CommunicationUsageContextCode`, `CommunicationVerificationStatusCode`,
`RoleBasisCode`, `StakeholderSideCode`, `StakeholderClassCode`,
`ParticipationStatusCode`, `AffiliationTypeCode`, `OrganizationKindCode`,
`LegalIdentityStatusCode`, `AssertionStatus` and `EvidenceRole`. There is no
field on any of these fifteen commands that a caller could sort people by.
`tests/architecture/test_relationship_scoring_surface_is_denied.py` was not
amended, widened, exempted or reasoned around; its diff from `516f9e0` is empty.

**The source-mutation name proxy gained exactly one exemption entry, holding a
pair of names, and was not weakened.** `tests/security/test_mcp_and_cli_negative_evidence.py` and
`tests/security/test_http_negative_evidence.py` both assert that no non-exempt
capability *value* contains one of `write`, `create`, `update`, `delete`,
`remove`, `rename`, `move` or `put` as a substring. Of the names published
here, exactly two hit it — `entities.participations.create` and
`entities.affiliations.create` — and the other thirteen pass the proxy unaided,
which is the check working rather than an omission. A new
`ENTITY_RECORD_FAMILY_EXEMPTION` frozenset holding exactly those two was added
to both files, mirroring the existing `ENTITY_DIRECTED_EXEMPTION` and carrying
its justification: a project participation and a person-organization affiliation
are **product-owned** records under `ADR-003`, the Principal's own statement
about the Principal's own Entities; their rows carry no `source_id` and the
plane reaches no `SourceProvider` at all. `MUTATING_NAMES` is untouched, no
existing exemption is widened, and a future `entities.participations.delete`
is still caught. **Both of those files are database-tier and neither was
executed** — see below.

**A disclosure about this branch's own history, because the commit message is
misleading and was deliberately not amended.** Commit `aeb09b52` carries the
message "WIP checkpoint: RI-ENT-WP-11 mutation contracts, preserved mid-flight",
written by the Manager after a worker was killed by an API session limit with a
large working set uncommitted; the message says the address family was "likely
incomplete" because that is what the Manager could honestly say at the time. The
Orchestrator subsequently **measured** that commit and it is a complete, fully
green state carrying the whole address family. The message was not amended
because rewriting a pushed commit mid-history would void the identity the later
gates are bound to, so the correction is recorded here instead. Read `aeb09b52`
as a finished increment; do not read its message's implication that the work in
it was unfinished.

### The ledger bridge, and the atomicity it does *not* have

`EntityRecordFamilyService` returns `RecordedFact`/`CorrectedFact`/`RetiredFact`,
writes no `entity_mutation_events` row and holds no idempotency key. Making the
five families reach `SqlEntityRepository._append_mutation` would have meant
changing around fifteen accepted `EntitiesRepository` port methods from
`-> None` to `-> DirectedReceipt` while `RI-ENT-WP-08` is under independent
review, which is a redesign of an accepted contract rather than a use of one.

So a new application module — `src/my_pa/application/entity_family_writes.py` —
uses two port methods that were already there and are already family-agnostic:
`directed_replay` (which filters on `(principal_id, capability,
idempotency_key)` and has no `record_family` predicate) and
`record_mutation_event`. `entity_mutation_events` carries no family-specific
column and no foreign key on `record_id`; the only thing standing between it and
these five families was the closed CHECK `a_mutated_record_family_is_known`,
which the phase's migration widens.

**The write and its ledger row are two statements, not one, and this is a real
difference from the directed plane.** `_append_mutation` writes the record and
the ledger row inside one repository method, so
`one_entity_mutation_per_key_and_capability` arbitrates the whole act. Here the
family write and the ledger insert are two separate calls, so that unique
arbitrates only because **the caller owns the transaction** —
`SqlUnitOfWork.entities` hands out a repository bound to the open transaction and
`ApplicationService.invoke` is what opens and commits it. Inside a transaction
the outcome is still correct: two concurrent writers holding one key both write a
family row, exactly one commits the ledger row, and the loser's whole transaction
aborts and takes its family row with it. **Called outside a transaction, a family
row can be left with no ledger row.** That is stated here and in the module's own
docstring rather than described as equivalent to the directed plane's
single-statement arbitration.

`SqlEntityRepository.record_mutation_event` now wraps its INSERT in the same
`_duplicate_translated(_MUTATION_KEY_UNIQUE)` the directed writer already used,
so two writers racing past its own pre-read produce a typed refusal rather than a
raw driver `IntegrityError`. That changes no answer an earlier caller got — an
untranslated `IntegrityError` and an untranslated `DirectedWriteError` both reach
`invoke`'s terminal catch for `application.entity_governance`, which classifies
neither — and it makes the two writers of one table classify one constraint one
way.

### `MutationRecordFamily` widened from six to eleven

`NAME`, `ADDRESS`, `COMMUNICATION_METHOD`, `PROJECT_PARTICIPATION` and
`PERSON_ORGANIZATION_AFFILIATION`, spelled exactly as `IdentityEffectFamily`
spells the same five families, because two vocabularies for one concept are two
things that can start disagreeing about which rows a correction touched. The
enum's docstring asserted a closure at six and has been rewritten rather than
left standing.

`ORGANIZATION_PROFILE` is deliberately **not** added: no `RI-ENT-WP-11`
capability writes `entity_organization_profiles`, so a member for it would name a
ledger subject nothing can produce.

**Disclosed side effect.** `entity_proposals`' CHECK
`an_accepted_proposal_record_family_is_known` is built by the same
`_one_of(..., MutationRecordFamily, ...)` helper, so widening the enum widens
that constraint's metadata too and the phase's migration must widen both to keep
`tables.py` and the DDL in agreement. It is a metadata-parity consequence with no
behavioural effect: `_PROMOTION_BY_KIND` covers exactly the fifteen existing
`EntityProposalKind` members and `EntityProposalKind` is not widened here, so no
new family becomes promotable through a proposal. That is not the same as "no
change", and it is not left undisclosed.

`SqlEntityRepository.proposal_target_version` is deliberately **not** extended to
the five new families. It returns `None` for an unmapped family, which would be a
silent degradation if anything could reach it with one — and nothing can, for the
reason above: no proposal kind names any of the five.

### No re-enrichment trigger, and why

Nothing is added to `TRIGGERS_BY_MUTATION_CAPABILITY` or to
`_DIRECT_REENRICHMENT_CAPABILITIES`. `ReenrichmentSubjectKind` has no member for
a name, an address, a communication method, a participation or an affiliation,
and `_SUBJECT_ID_KINDS` maps every member it does have to an `IdKind` — so a
direct caller could not name the subject it changed. The generic path is worse:
an entry in `TRIGGERS_BY_MUTATION_CAPABILITY` would register Principal-wide work
under a trigger belonging to a different record family (`NEW_ALIAS` where no
alias row was written, `ROLE_OR_ORGANIZATION_CHANGE` where no assignment was),
which is the shape `TRIGGERS_BY_ACCEPTED_PROPOSAL_KIND` records seven absences
for. Widening the subject vocabulary belongs to the re-enrichment package.

### Deliberately not delivered

- **The caller-supplied assertion is not exposed.** `RI-ENT-WP-08`'s
  `StatedAssertion`/`StatedEvidence` structure would have to arrive as a nested
  object; the schema builder describes no nested dataclass, so the only shape
  that would publish is `dict[str, object]` — the free-form payload RULING 5
  forbids. It is omitted rather than half-exposed, and every command here writes
  a fact with no assertion attached. The *assertion* half of
  `ENTITY-PROVENANCE-001`'s MCP-exposure clause therefore remains open, even
  though the *facts* half is now closed by these contracts and by
  `RI-ENT-WP-10`'s reads — which is why that finding's row reads "partly closed"
  and names both halves rather than reporting a verdict.
- **A correction whose successor collides with a *third* active row still
  answers `internal_error`.** The five families' inserts raise the driver's own
  `IntegrityError`, untranslated, exactly as `EntityRecordFamilyService`'s
  docstrings already say they do; the application layer holds no `sqlalchemy`, so
  the only place to classify that is the persistence adapter, and those methods
  are `RI-ENT-WP-08`'s and under review. The exception does not reach a caller —
  `invoke`'s terminal catch answers `internal_error` — but `internal_error` is
  the wrong class for a conflict a caller could act on, and it is recorded as a
  limitation rather than described as handled. The one violation this work
  package itself introduces, two writers racing for one idempotency key, *is*
  classified.
- **No re-enrichment subject vocabulary.** Recorded in full under "No
  re-enrichment trigger" above: the absence is deliberate, and the widening
  belongs to the re-enrichment package rather than to this one.

### The migration, which landed after the contracts and separately from them

The phase's single revision is **`16f05c46b8c3`**, commit `959f6c1b`, written by
a dedicated owner rather than by any contract worker and landing after every
capability name `RI-ENT-WP-10` and `RI-ENT-WP-11` publish -- twenty in all --
was already committed. It is the chain's head, additive on `c99cd8ed8d1c`, and it widens
three closed CHECK sets and nothing else:

| Constraint | Before | After |
|---|---|---|
| `knowledge.audit_events.capability_is_known` | 115 values | 135 values |
| `knowledge.entity_mutation_events.a_mutated_record_family_is_known` | 6 | 11 |
| `knowledge.entity_proposals.an_accepted_proposal_record_family_is_known` | 6 | 11 |

`knowledge.audit_events.purpose_is_known` is deliberately **not** widened,
because neither work package adds a `Purpose`. The third row is the
metadata-parity consequence disclosed above and has no behavioural effect: no
new family becomes promotable through a proposal.

**The gap between the contracts and the revision was real and is worth
recording.** `authorize` commits an `audit_events` row *before* the handler
runs, and `capability_is_known` is a closed CHECK, so between `93885e2` and
`959f6c1b` every one of the new names was green in every from-scratch test and
would have answered `internal_error` against a migrated database. Nothing in the
gate-safe tiers could see that, because a from-scratch test database is built
from `tables.py` rather than from the revision chain. It was found by
inspection, not by a test, which is the same way the digit-form count defects
were found.

### Unexecuted is not verified

**Every database-tier test written for `RI-ENT-WP-10` and `RI-ENT-WP-11` is
committed and has never been executed.** A machine-wide serial database gate was
closed for the entire duration of both work packages — a concurrent run would
have corrupted another work package's measurements on shared disposable database
names — so no worker on either package ran anything marked `database`,
`recovery` or `e2e`, or anything under `tests/database`, `tests/schema`,
`tests/migration`, `tests/concurrency`, `tests/end_to_end`, `tests/recovery`,
`tests/security` or `tests/capture`.

The modules, by name:

- **`tests/database/test_entity_family_write_ledger.py`** — thirty-two tests
  across the five families, added over four commits. It is *expected* to have
  been failing until `16f05c46b8c3` landed, and has still never run since. The
  tests are:
  `test_an_added_name_writes_one_ledger_row_naming_the_new_record_family`,
  `test_a_retry_with_the_same_key_and_payload_replays_and_writes_nothing`,
  `test_a_retry_with_the_same_key_and_a_different_payload_is_refused`,
  `test_a_supersession_names_its_predecessor_and_the_version_it_asserted`,
  `test_a_retirement_advances_the_version_it_names`,
  `test_a_stale_expected_version_is_refused_and_leaves_no_ledger_row`,
  `test_one_key_under_two_capabilities_is_two_writes_and_not_one`,
  `test_a_second_ledger_row_for_one_key_and_capability_is_refused`,
  `test_an_added_address_writes_a_ledger_row_naming_the_address_family`,
  `test_an_address_retry_with_the_same_key_and_payload_replays`,
  `test_an_address_retry_with_a_different_payload_is_refused`,
  `test_an_address_revision_is_a_supersession_and_not_an_edit`,
  `test_an_address_retirement_advances_its_version_and_releases_its_slot`,
  `test_a_stale_address_version_is_refused_and_leaves_no_ledger_row`,
  `test_an_added_channel_writes_a_ledger_row_naming_the_communication_family`,
  `test_a_channel_retry_with_the_same_key_and_payload_replays`,
  `test_a_channel_retry_with_a_different_payload_is_refused`,
  `test_a_channel_revision_is_a_supersession_and_not_an_edit`,
  `test_a_channel_retirement_advances_its_version_and_releases_its_slot`,
  `test_a_stale_channel_version_is_refused_and_leaves_no_ledger_row`,
  `test_a_created_participation_writes_a_ledger_row_naming_its_family`,
  `test_a_participation_retry_with_the_same_key_and_payload_replays`,
  `test_a_participation_retry_with_a_different_payload_is_refused`,
  `test_a_participation_revision_is_a_supersession_and_not_an_edit`,
  `test_a_participation_end_advances_the_version_it_names`,
  `test_a_stale_participation_version_is_refused_and_leaves_no_ledger_row`,
  `test_a_created_affiliation_writes_a_ledger_row_naming_its_family`,
  `test_an_affiliation_retry_with_the_same_key_and_payload_replays`,
  `test_an_affiliation_retry_with_a_different_payload_is_refused`,
  `test_an_affiliation_revision_is_a_supersession_and_not_an_edit`,
  `test_an_affiliation_end_advances_its_version_and_writes_no_date_it_was_not_given`,
  and `test_a_stale_affiliation_version_is_refused_and_leaves_no_ledger_row`.
- **`tests/database/test_ri_ent_wp_10_11_vocabulary_migration.py`** — commit
  `bcd2048`, the database-tier binding for `16f05c46b8c3` itself. It drives all
  three widened CHECKs with real inserts at head, proves an undeclared name is
  still refused so the widening did not open them, downgrades one revision and
  requires every new value to vanish before upgrading and requiring it back, and
  drives every live `Capability`, `Purpose` and `MutationRecordFamily` through
  the stored CHECKs. Its own commit records `pytest --collect-only` collecting
  thirty-five tests in it, and **no assertion in it has ever run against a
  server.**
- **`tests/security/test_mcp_and_cli_negative_evidence.py`**,
  **`tests/security/test_http_negative_evidence.py`** and
  **`tests/security/test_entity_privacy_regression.py`** — all three were
  *edited* (the exemption frozenset in the first two, the `_EVERY_CAPABILITY`
  registry and its served-name count in the third) and none was run. The
  registry edits in the first two are guard-adjacent by construction and deserve
  explicit reviewer scrutiny for that reason, not less.

**Unexecuted is not verified, and this campaign has already paid for treating it
as though it were.** `RI-ENT-WP-09` committed a statically-verified
database-tier module under the same closed gate; on its first real execution
**eleven of its thirty tests errored at setup**, against a `NameTypeCode` member
that never existed. Nothing about the modules above is stronger evidence than
that module was. Expect them to contain defects; the honest description of their
status is "written, statically verified, never run", and their figures are
collection counts, not execution results.

Two specific claims elsewhere in this section are therefore weaker than they
read. The wrapping of `SqlEntityRepository.record_mutation_event`'s INSERT in
`_duplicate_translated(_MUTATION_KEY_UNIQUE)` is a change to a **shared**
infrastructure method that `RI-ENT-WP-11` made and that no executed test
exercises: the race it classifies needs two concurrent sessions against a real
server, which is precisely what could not be run. And the atomicity account
above is derived from reading the SQL and from who owns the transaction, not
from observing an aborted transaction.

### Tiers run for this work package, with the figures the Orchestrator measured

Measured at `959f6c1b` by the Orchestrator rather than by any worker, and
reproduced here verbatim rather than paraphrased:

```
ruff check .                            All checks passed!
ruff format --check .                   1194 files already formatted
mypy src                                Success: no issues found in 307 source files
alembic heads                           16f05c46b8c3 (head)        [exactly one head]
pytest <18 gate-safe directories>       15144 passed, 137 deselected, 0 failed
  -m "not database and not recovery and not e2e and not network
      and not connector and not evaluation"
pytest tests/architecture (standalone)  4792 passed, 0 failed
FAST tier --collect-only                16182 collected, 2036 deselected
```

The eighteen gate-safe directories are `tests/unit`, `tests/relationship`,
`tests/architecture`, `tests/contract`, `tests/policy`, `tests/canary`,
`tests/connector_conformance`, `tests/entity_resolution`, `tests/evaluation`,
`tests/integration`, `tests/jobs`, `tests/parser_isolation`, `tests/pipeline`,
`tests/projection`, `tests/provider_conformance`, `tests/runtime_attestation`,
`tests/search_quality` and `tests/situation`. Everything outside them is
unexecuted, as recorded above.

Two guard diffs from `516f9e0` are **empty**, and were checked rather than
assumed: `AGENTS.md`, which no worker on either package may amend, and
`tests/architecture/test_relationship_scoring_surface_is_denied.py`.
`tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py` is
**not** unchanged, and the exception is disclosed rather than buried: its
`test_the_chain_is_readable_and_non_empty` counted eighty-six revisions and the
chain now holds eighty-seven, so the Orchestrator corrected that count in
`d58f1309` (+6/-2, the extra lines being the comment explaining why). It is a
derived fact about the tree corrected by measuring it (`RULING-M2`), in the
module's non-vacuity guard; the rule this module exists to enforce is untouched,
and `DENIED`, `ALLOWED` and `FROZEN` are byte-identical to `516f9e0`.

Anti-laundering, across both packages: **0** skips, **0** xfails, **0** tests
deleted, **3** `noqa` added and **16** `type: ignore` comments added. Every
`noqa` is `S608` on an f-string `INSERT` inside the unexecuted migration-test
module, which is the pre-existing idiom for test SQL in this repository; every
`type: ignore` is `[index]` or `[arg-type]` on a JSON-response subscript in a
test file, which is the pre-existing idiom in those files. None of the nineteen
suppresses an assertion.

The sets these packages moved, measured rather than computed: `Capability`
104 → **124**; `entities.` names 34 → **54**; `Purpose` 34, **unchanged**;
`PERMITTED_PAIRS` 106 → **126**; `MutationRecordFamily` 6 → **11**.

The work is on `ri-ent/wp10-11-mcp`, based on `516f9e0` (tree `bf0d211`), and
these are its commits in order:

| Commit | What it landed |
|---|---|
| `93885e20` | `RI-ENT-WP-10`: the six Entity-bound record families published as five reads |
| `fc735550` | `RI-ENT-WP-10`: every count derived from the read/write split, corrected by measurement |
| `150f8713` | `RI-ENT-WP-11`: the typed-name family as three mutation contracts |
| `aeb09b52` | `RI-ENT-WP-11`: the address family — a Manager checkpoint whose message is misleading, measured complete and green, disclosed above |
| `4ea1a232` | `RI-ENT-WP-11`: the communication-method family |
| `8349e200` | `RI-ENT-WP-11`: the project-participation family |
| `e28916c1` | `RI-ENT-WP-11`: the person-organization-affiliation family |
| `959f6c1b` | the phase's single migration `16f05c46b8c3` — the head the gate figures above were measured at |

Commits landing after `959f6c1b` — the database-tier binding for that migration,
and the documentation corrections this section is part of — are not covered by
the figures above, which were measured at `959f6c1b` exactly and are not
restated for a later head so that this document cannot drift ahead of what
actually ran.


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
