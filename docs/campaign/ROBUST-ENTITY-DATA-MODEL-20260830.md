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
  (`knowledge.entity_names`, `knowledge.entity_organization_profiles`).

RI-ENT-WP-03 through RI-ENT-WP-13 (addresses, communication methods, project
participation, person affiliation, relationship-graph expansion, assertion/
provenance binding, repository/service layer beyond WP-02, resolution/search
vNext, MCP rich-read and mutation contracts, legacy migration/backfill, and
the full TBR completeness fixture) are **explicitly out of scope for this
increment** and remain future work, ordered as the source audit orders them
(section P). Nothing in this increment implements them, and nothing in this
increment's schema, domain code, or tests assumes they exist.

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
| `ENTITY-PROJECT-001` | Critical | Incomplete project participation | Not in scope (`RI-ENT-WP-04`) |
| `ENTITY-PROVENANCE-001` | High | No fact-level certainty/verification binding | Partially addressed for organization legal identity only, via `legal_identity_status_code` (not a confidence field — see Ruling 1); full assertion/provenance binding is `RI-ENT-WP-07` |
| `ENTITY-PERSON-001` | High | Incomplete person affiliations | Not in scope (`RI-ENT-WP-05`) |
| `ENTITY-RESOLUTION-001` | Critical | Resolution cannot follow typed names/identity graph | **Unblocked, not closed** — `entity_names` now exists as the structural prerequisite; resolution/search changes are `RI-ENT-WP-09` |
| `ENTITY-STATE-001` | High | No canonicalization/review state distinct from lifecycle | Design decision recorded in RI-ENT-WP-01 below (`canonicalization_state_code`, separate 1:1 record, deferred); not implemented this increment |
| `MCP-CONTRACT-001` | Critical | No rich structured profile read | Not in scope (`RI-ENT-WP-10`) |
| `MCP-CONTRACT-002` | High | No record-family mutation capabilities for the new families | Not in scope (`RI-ENT-WP-11`); RULING 5 (no mass-assignment endpoint) remains binding when it is |
| `COMPAT-001` | High | Additive-vs-breaking policy needed for generated strict schemas | Addressed procedurally in RI-ENT-WP-01 (below); no generated schema exists yet to apply it to |
| `MIGRATION-001` | Critical | Legacy `relationship_people`/`relationship_organizations` coexist; must not infer legal identity from names | Honored: migration `7e114f822af2` is purely additive, backfills nothing, infers nothing |
| `SECURITY-001` | High | New families must preserve Principal partitioning, composite keys, append-only ledgers, operator-only merge/split | Partitioning and composite keys: proven by `tests/schema/test_entity_names_and_organization_profile_migration.py`. Merge/split: **explicitly deferred**, not silently — see "Merge/split disposition" below |
| `TEST-001` | High | No TBR completeness fixture exists | Not in scope (`RI-ENT-WP-13`); this increment adds a synthetic single-case fixture (GS4 Studios) proving the pattern, not the full register |

## The 13 work packages (source audit ordering, section P)

| WP | Title | This increment |
|---|---|---|
| WP-01 | Architecture/contract freeze | **Delivered** — see below |
| WP-02 | Taxonomy and typed-name model | **Delivered (partial)** — `entity_names`, `entity_organization_profiles`; role/discipline/relationship taxonomies deferred to WP-04/06 |
| WP-03 | Address and communication record families | **Delivered** — see below |
| WP-04 | Project participation model | Deferred |
| WP-05 | Person affiliation integration | Deferred |
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
| Key/known contact, with title, at a project or organization | Person entity + `person_organization_affiliations` + project participation | WP-05, WP-04 | Deferred |
| Relationship / parent / practice / acquisition lineage / technical-review / seller-developer-SPV / utility-authority edge | Extensible `entity_relationships` taxonomy (successor to the frozen 15-member `EntityRelationshipType`) | WP-06 | Deferred; `EntityRelationshipType` untouched this increment |
| Project role / discipline / scope / stakeholder side / stakeholder tier / role basis / participation state | `project_entity_participations` | WP-04 | Deferred |
| "Confidence" (register label) at any dimension (role/scope/participation/legal-identity) | **Not a scalar confidence field anywhere** — discrete `assertion_status`/`role_basis_code`/`legal_identity_status_code`-family vocabularies, one per dimension, bound to the fact/edge/participation that carries it | WP-02 delivers `legal_identity_status_code`; the rest is WP-07 | Partial — RULING 1 governs all of it, see below |
| Evidence / source type-URI / observation and verification timestamps / assertion author / conflicting evidence / supersession / source-driven correction | Existing `entity_fact_evidence_links`, `entity_observations`, `entity_mutation_events`, `entity_resolution_decisions`, extended to bind the new record families | WP-07 | Deferred; the ledgers exist and are unmodified, but do not yet bind `entity_names`/`entity_organization_profiles` rows |
| Import readiness (READY/FLAG/HOLD/DO NOT IMPORT), canonicalization state distinct from lifecycle | A new, separate state record or nullable FK on `entities` (`canonicalization_state_code`) — explicitly **not** an overload of `entities.status` | Design decision recorded now (`ENTITY-STATE-001`); table not created this increment | Deferred |
| Duplicate/reconciliation state, merge/split ledgers | Existing `entity_merge_records`, `entity_identity_effects`/`entity_identity_previews`/`entity_identity_operations`, `entity_identity_preview_ambiguities`, `entity_identity_ambiguity_settlements` | Existing (RI remediation campaign, PR #164) | Unchanged; `entity_names`/`entity_organization_profiles` are **not yet wired in** — see "Merge/split disposition" |
| "One organization with aliases/historical legal [names]" (register's own instruction to the reader) | Not a field at all — a mapping/architecture rule | This document (WP-01) | Delivered as this table |
| Independent consultant, no organization FK required | Existing nullable `scope_entity_id`/nullable organization pattern already proven by `Assignment` | WP-04/WP-05 reuse the existing pattern | Deferred (pattern only) |

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

## Merge/split disposition (RULING 2)

`entity_names`, `entity_organization_profiles`, `entity_addresses`, and
`entity_communication_methods` are all Entity-bound record families and are
therefore candidates for the merge/split ambiguity model that landed in
`main@0e24018` (`src/my_pa/domain/relationship/identity_correction.py`'s
`IdentityEffectFamily`/`_DISPOSITIONS_BY_FAMILY`, and
`src/my_pa/application/identity_correction.py`'s reparenting/collision/
ambiguity-discovery machinery).

**Decision: deferred, not wired in, and the reason is recorded here rather
than left implicit — for all four families, as of RI-ENT-WP-03.**

1. **No live write path exists yet, for any of the four.** This increment
   (like WP-02 before it) ships no MCP capability and no application command
   that writes `entity_names`, `entity_organization_profiles`,
   `entity_addresses`, or `entity_communication_methods` in ordinary product
   use — only test fixtures write them directly through the persistence
   layer. A merge executed today cannot encounter a populated row of any of
   the four through any caller a real request could reach.
2. **The execution machinery is genuinely bespoke per family**, not
   config-driven: `application/identity_correction.py` carries dedicated
   reparenting functions (`_reparented_alias`, `_reparented_identifier`) and
   dedicated collision-detection logic specific to each table's uniqueness
   rules, across roughly 3,300 carefully-reasoned lines. Extending it
   correctly for four more families — including working out what a merge of
   two organization entities that each carry a profile should do, since
   `entity_organization_profiles` is a 1:1 record a merge cannot simply
   duplicate, and what a merge should do with two entities that each carry
   an active preferred address or communication method of the same type — is
   substantial, separable work, not a small addition to any one increment.
3. **What a merge does today, absent wiring:** if a future write path
   populates any of the four tables before this wiring lands, a merge that
   redirects the owning entity does not reparent, discover ambiguity for, or
   invert those rows. They remain bound to the merged-away `entity_id`, which
   stays resolvable through `entities.superseded_by_entity_id` but is not
   reachable by querying the survivor's names, profile, addresses, or
   communication methods directly. This is recorded as a known limitation in
   all four classes' docstrings (`src/my_pa/domain/relationship/entity.py`)
   and here.
4. **Deferred to `RI-ENT-WP-06`**, which the source audit's own dependency
   ordering already binds to "coordinate merge/split effects" — not to the
   taxonomy or record-family schema work WP-02 and WP-03 deliver.

**Blocking dependency, stated plainly:** `WP-08` (repositories/domain
services) and `WP-11` (MCP mutation contracts) **may not ship a write path
for any of these four families** — `entity_names`,
`entity_organization_profiles`, `entity_addresses`, or
`entity_communication_methods` — **until the merge/split wiring in `WP-06`
lands.** A write path that outpaces that wiring would let ordinary product
use populate a row a merge cannot reparent, discover ambiguity for, or
invert — silently reintroducing the exact hazard `SECURITY-001` and RULING 2
exist to prevent. This is a hard ordering constraint on the work-package
sequence, not a preference.

This satisfies RULING 2's second branch: a documented, evidenced exclusion
rather than a silent one.

## Test evidence

Exact commands, run from the repository root with
`MY_PA_DATABASE_URL='postgresql+psycopg://my_pa@127.0.0.1:5433/my_pa'`
(reused only to *create* disposable test databases; every test below runs
against its own disposable database, never the configured one):

- `.venv/bin/python -m pytest tests/unit/test_entity_name_and_organization_profile_domain.py -q`
- `.venv/bin/python -m pytest tests/schema/test_entity_names_and_organization_profile_migration.py -q`
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
- `src/my_pa/domain/relationship/entity.py` — `EntityName`, `EntityNameState`, `NameTypeCode`, `EntityOrganizationProfile`, `OrganizationKindCode`, `LegalIdentityStatusCode`, `EntityAddress`, `EntityAddressState`, `AddressTypeCode`, `EntityCommunicationMethod`, `EntityCommunicationMethodState`, `CommunicationMethodTypeCode`, `CommunicationUsageContextCode`, `CommunicationVerificationStatusCode`.
- `src/my_pa/infrastructure/persistence/tables.py` — `entity_names`, `entity_organization_profiles`, `entity_addresses`, `entity_communication_methods`.
- `migrations/versions/20260830_7e114f822af2_add_entity_names_and_organization_.py` (RI-ENT-WP-02).
- `migrations/versions/20260830_441b071bf37b_add_entity_addresses_and_communication_.py` (RI-ENT-WP-03).
