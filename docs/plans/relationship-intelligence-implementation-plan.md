# Relationship Intelligence — implementation plan and acceptance ledger

**Objective.** Build the Relationship Intelligence entity plane admitted to MCV
scope by the operator's 2026-08-01 reprioritization (`AGENTS.md` sections 1 and
3), as a sequence of bounded work packages WP-RI-01 … WP-RI-13.

**Specification.** [`docs/specs/relationship-intelligence-v0.2.md`](../specs/relationship-intelligence-v0.2.md).
That document carries `implementation_authority: false` and describes itself as
a proposal; it is the *requirements* source, not the authorization. The
authorization is the operator's scope reprioritization recorded in `AGENTS.md`.
Where this plan departs from the specification, section 4 below says so and
why.

**Out of scope for every work package here**, and a mandatory stop if
approached: production deployment or activation, shared or production database
operations, live personal-data traversal, credential or OAuth mutation, live
Abacus/ChatLLM Task changes, destructive actions, and operator risk acceptance
(`AGENTS.md` sections 5, 8.2 and 9).

---

## 1. Work packages

| WP | Scope | State |
|---|---|---|
| WP-RI-01 | Domain model (`Entity`, `ExternalIdentifier`, `Assignment`, `EntityRelationship`), four identifier prefixes, four tables, Alembic revision `9def3c2e63bb` | **complete** |
| WP-RI-02 | `EntitiesRepository` port, `SqlEntityRepository`, the `UnitOfWork.entities` seat, the in-memory fake, FAST-tier tests | **complete** |
| WP-RI-03 | Exact resolution: alias table, namespace and alias normalization, effective-date filtering, entity-type and scope filtering, conflicting-identifier handling, historical resolution, same-name protection | **complete** |
| WP-RI-04 | Contextual resolution: bounded candidate ranking, calibration, explainable evidence, collision-biased safety, false-resolution evaluation | not started |
| WP-RI-05 | The capability and MCP surface: `Capability` members, `Purpose` registration, the forward `ALTER`, commands, handlers, remote-exposure decision | not started |
| WP-RI-06 | Observation, proposal, review, and merge | not started |
| WP-RI-07 | Context card assembly (the specification's "context packet", section 26.3) | not started |
| WP-RI-08 | Backfill / re-enrichment (the specification's "re-enrichment triggers", section 27.4) | not started |
| WP-RI-09 | Inspection tooling | not started |
| WP-RI-10 | Intelligence-task integration | not started |
| WP-RI-11 | Security and privacy regression | not started |
| WP-RI-12 | Acceptance evidence against the ledger in section 3 | not started |
| WP-RI-13 | Documentation and runbook | not started |

WP-RI-06 … WP-RI-09 are parallelizable once WP-RI-05 lands. WP-RI-03 must
precede WP-RI-04, and both must precede WP-RI-05.

---

## 2. The core safety rule

> **Ambiguity is preferable to a wrong entity match.**

The specification states this five separate times and never as a single named
rule. Section 15.2: *"Ambiguous mentions remain unresolved rather than forced
into the nearest person."* Section 10.3: *"Ambiguous identity matches remain
unresolved."* Section 15.2 again: *"Names alone are insufficient for automatic
merge"* and *"Conflicting immutable identifiers prevent automatic merge."*
`RI-RISK-001` names a false identity merge as contaminating *"profile,
timeline, commitments, and briefings"* and asks for **precision-first
metrics**.

Two consequences bind WP-RI-03 and WP-RI-04:

* Resolution must return a **typed outcome** with ordered alternatives,
  warnings, and explainable evidence. It must never collapse an ambiguous or
  conflicted result into a generic `NotFoundError`, because "I could not find
  them" and "I found four of them" are different answers and only one of them is
  safe to act on. WP-RI-03 delivers this: `EntityResolution.resolved_entity_id`
  is a derived property that exists only for the two resolved outcomes, so an
  `AMBIGUOUS` answer has no identifier for any caller to read. Calibration — a
  numeric a caller can threshold on — is deliberately *not* part of it, for the
  reason `D-RI-02` gives, and is WP-RI-04's to design with its exemption.
* The false-resolution evaluation in WP-RI-04 is **collision-biased**: the
  fixture is built to make wrong joins likely (same surname, shared employer,
  recycled email local-parts), because a corpus of easy cases measures nothing.

---

## 3. Acceptance-criteria ledger — RI-AC-001 … RI-AC-040

The specification declares seventy criteria; this campaign tracks the first
forty. **A note that must not be lost:** a substantial share of RI-AC-001 …
RI-AC-040 are product- and interface-level criteria that cannot be satisfied
while frontend implementation remains held by the operator's `D-09`
instruction (`AGENTS.md` section 3, specification section 2.3). They are
carried here as `BLOCKED_BY_D09` rather than quietly recast as backend
criteria — a backend that makes a criterion *possible* has not satisfied a
criterion about what a user sees.

Status vocabulary: `MET` (evidence exists), `PARTIAL` (some evidence, gap
named), `OPEN` (in a planned work package), `BLOCKED_BY_D09` (needs the held
frontend), `NOT_APPLICABLE_TO_THIS_CAMPAIGN` (belongs to another plane).

| ID | Criterion (abridged) | Status | Where |
|---|---|---|---|
| RI-AC-001 | Public language is Relationships / Relationship Intelligence; PRIE historical only | `OPEN` | WP-RI-13 |
| RI-AC-002 | Integrated into `my-pa`, not a standalone engine | `MET` | No new process, database, or service; `tests/architecture/test_dependency_direction.py` |
| RI-AC-003 | The product states relationships are not scores | `PARTIAL` | Enforced structurally by `tests/architecture/test_relationship_scoring_surface_is_denied.py`, now widened to the entity plane. The *statement* is WP-RI-13 |
| RI-AC-004 | Value without starting a chat | `BLOCKED_BY_D09` | — |
| RI-AC-005 | Contact/source rows stay observations, not automatic canonical people | `OPEN` | WP-RI-06 |
| RI-AC-006 | Unresolved mentions are first-class and searchable | `PARTIAL` | `ResolutionOutcome.AMBIGUOUS`/`NOT_FOUND` are first-class answers carrying their candidates and warnings; a *stored* unresolved mention is WP-RI-06 |
| RI-AC-007 | No identity merge without governed policy | `OPEN` | WP-RI-06 |
| RI-AC-008 | Merge preview shows all materially affected records | `OPEN` | WP-RI-06 |
| RI-AC-009 | Merge and split history preserved and correctable | `PARTIAL` | `entities.superseded_by_entity_id` + the `merged_redirect` biconditional exist; lineage records are WP-RI-06 |
| RI-AC-010 | Negative identity evidence prevents repeated false matches | `OPEN` | WP-RI-04 |
| RI-AC-011 | Every material profile statement links to evidence or is marked | `OPEN` | WP-RI-06 |
| RI-AC-012 | Source facts / notes / assertions / inferences structurally distinct | `OPEN` | WP-RI-06 |
| RI-AC-013 | Coverage, freshness, exclusions appear before synthesis | `OPEN` | WP-RI-07 |
| RI-AC-014 | Stale evidence never presented as current | `PARTIAL` | Resolution answers `HISTORICAL_MATCH` with `ENTITY_IS_NOT_CURRENT`/`ENTITY_HAS_BEEN_MERGED_AWAY`, and filters evidence by effective date under `as_of` (WP-RI-03). Briefing-level staleness is WP-RI-07; presentation is `BLOCKED_BY_D09` |
| RI-AC-015 | Contradictory evidence preserved, not collapsed | `OPEN` | WP-RI-06 |
| RI-AC-016 | Briefings retain evidence scope and model identity | `OPEN` | WP-RI-07 |
| RI-AC-017 | Person profile exposes the full record set | `BLOCKED_BY_D09` | — |
| RI-AC-018 | Timeline distinguishes event / effective / observed / recorded times | `PARTIAL` | `effective_from`/`effective_to` and `created_at`/`updated_at` exist; the four-clock model is WP-RI-06 |
| RI-AC-019 | Profile navigation preserves context and return state | `BLOCKED_BY_D09` | — |
| RI-AC-020 | Organization profiles support time-aware associations | `PARTIAL` | The schema is time-aware; the profile is `BLOCKED_BY_D09` |
| RI-AC-021 | Commitments retain obligor, beneficiary, outcome, source, lifecycle | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | The commitment plane already exists (WP-TM-05) |
| RI-AC-022 | Commitments and tasks remain distinct | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Existing planes |
| RI-AC-023 | Extracted commitments require review initially | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Existing review plane |
| RI-AC-024 | Fulfillment retains evidence or explicit confirmation | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Existing planes |
| RI-AC-025 | Commitments by and to a person separately visible | `OPEN` | WP-RI-10 |
| RI-AC-026 | Follow-ups distinct from commitments | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Existing planes |
| RI-AC-027 | Meeting briefing identifies attendee ambiguity and unavailable evidence | `OPEN` | WP-RI-07 |
| RI-AC-028 | Deterministic meeting context usable when AI is unavailable | `OPEN` | WP-RI-07 |
| RI-AC-029 | Briefing claims navigate to source evidence | `BLOCKED_BY_D09` | — |
| RI-AC-030 | Post-meeting capture creates proposals without changing source events | `OPEN` | WP-RI-06 |
| RI-AC-031 | Quick Note / Call launchable in-app and from device shortcuts | `BLOCKED_BY_D09` | — |
| RI-AC-032 | One general input field required before save | `BLOCKED_BY_D09` | — |
| RI-AC-033 | Original input durably stored before enrichment | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Quick Capture plane (ADR-003) |
| RI-AC-034 | Enrichment failure does not lose or block the capture | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Quick Capture plane |
| RI-AC-035 | Participants, commitments, sensitive facts, dates follow review policy | `OPEN` | WP-RI-06 |
| RI-AC-036 | Repeated processing does not duplicate structured records | `PARTIAL` | `bind_identifier` is idempotent against its natural key; `record_assignment` and `record_relationship` are idempotent only against their own identifier. Closing this needs a write-path idempotency key — WP-RI-06 |
| RI-AC-037 | Capture corrections retain immutable before/after evidence | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Quick Capture plane |
| RI-AC-038 | AI output carries an authority class | `OPEN` | WP-RI-06 |
| RI-AC-039 | Models cannot merge identities or promote inferences autonomously | `OPEN` | WP-RI-06, WP-RI-11 |
| RI-AC-040 | No external action occurs through a relationship knowledge write | `OPEN` | WP-RI-11 |

**Tier discipline.** A criterion requiring MCP, integration, canary, or live
evidence is not satisfied by a FAST-tier unit test. RI-AC-036 in particular is
a database-tier claim about what the server refuses, and is marked `PARTIAL`
here precisely because no such test exists yet.

---

## 4. Decisions taken, and where they depart from the specification

Recorded here because each one is a choice a reviewer would otherwise have to
reconstruct from a diff.

**D-RI-01 — WP-RI-02 registers no capability.** The five `entities.*`
capabilities move to WP-RI-05. `adapters/mcp/remote.py::remote_tool_names`
derives the remote profile from `Capability` directly: any non-operator-only
read with a handler and a command **joins the remote MCP surface
automatically**, and there is no per-capability exclusion list to withhold it.
Registering `entities.resolve` before WP-RI-03 and WP-RI-04 exist would put an
unfinished resolution surface on the remote transport, which is exactly what
the carry-forward gate on this campaign forbids. Registering also costs a
forward `ALTER` on `capability_is_known`/`purpose_is_known` plus roughly thirty
test and prose updates, which would then land a second time when the surface
actually changed. Withholding is achieved through the composition gate
`_MANAGED_CAPABILITIES` already proves end-to-end, and WP-RI-05 owns that
decision.

**D-RI-02 — no `confidence` field on this plane.**
`tests/architecture/test_relationship_scoring_surface_is_denied.py` denies the
token outright as "a model likelihood", and specification section 22.3 admits a
numeric *"only when calibrated and explained"*. Sections 12.5 and 12.15 do ask
for confidence on these records, so this is a real departure — but nothing in
WP-RI-01 or WP-RI-02 produces, calibrates, or explains a confidence value, and
weakening a repository-wide prohibition to admit a field no writer fills is the
wrong trade. The work package that first has an evidential confidence to record
makes the argument, adds the exemption, and tests it.

**D-RI-03 — no `provenance` or `observation_id` yet.** Specification section
22.2 requires provenance on every observed and derived record and section 12.2
requires an observation behind every source-bound claim. Neither is modelled
here because neither has anything to bind to: nothing in these work packages
observes a source. The prior draft typed `provenance` as `str` against a `jsonb`
column, which would have stored a bare JSON scalar and made the column
unqueryable; `observation_id` named a table that does not exist. Both arrive
with the observation record in WP-RI-06, bound to the repository's existing
`Provenance` type.

**D-RI-04 — four identifier prefixes, not eight.** `ent`, `xid`, `asn`, `erel`.
The prefixes for observations, proposals, context packets, and merge lineage are
declared by the work packages that create their tables. A prefix in `IdKind` is
a stability promise, and promising one for a record nothing issues is a promise
about nothing.

**D-RI-05 — the alias table arrived with the code that uses it.** WP-RI-02
removed `AliasType` and the port's alias methods rather than leaving them
raising `NotImplementedError`; WP-RI-03 added `entity_aliases`, `EntityAlias`,
`record_alias`/`aliases`, and the resolution that reads them, together. The
unique constraint is `(entity_id, alias_type, normalized_value)` and
deliberately **not** global on `normalized_value`: two real people share a name,
and a schema that made that a conflict would force one of them to be merged into
the other.

**D-RI-06 — `superseded_by_entity_id` is not unique.** The prior draft declared
it `UNIQUE`, which forbids merging two entities into the same survivor — the
ordinary case. Replaced with two named CHECKs: an entity redirects **exactly**
when its status is `merged_redirect`, and it does not supersede itself.

**D-RI-11 — a lone name match is `AMBIGUOUS`, not resolved.** The single most
consequential call in WP-RI-03. One entity carries a name and no other does, and
that is still not evidence that a reference means that entity: uniqueness is a
fact about the database, not about the person. So `ResolutionOutcome.AMBIGUOUS`
admits one candidate as well as several, and `EntityResolution` refuses by
construction to report `RESOLVED_EXACT` for a candidate whose strongest evidence
is a canonical name. An alias *does* resolve, because an alias is a recorded
fact about the entity rather than an incidental collision.

**D-RI-12 — email local-parts are not rewritten.** Dot and `+tag` folding is one
provider's rule; applying it everywhere merges two distinct mailboxes at every
other provider. The domain is lowercased (DNS is case-insensitive by
specification) and the local-part is lowercased (universal in this product's
reach), and nothing else is touched. Opaque `vendor_system_id` and
`source_participant_id` values are compared exactly, because their issuers' case
rules are unknown and folding could collide two distinct records. Recorded
because the specification defines no normalization algorithm at all.

**D-RI-13 — `Entity.canonical_name` is expected to hold a normalized name, and
nothing yet enforces it.** Resolution compares a normalized query against that
column by equality, so a writer that stored an unnormalized name would make its
entity unresolvable. The invariant is not in the dataclass because
`domain/relationship/entity.py` and `domain/relationship/normalization.py` would
import each other. It belongs on the write path, and the write path arrives in
WP-RI-06. Carried in section 5 as a known gap rather than assumed.

**D-RI-07 — the resolution outcome vocabulary is an addition, not a
requirement.** The specification contains no per-query resolution outcome enum.
It has a record lifecycle state machine (section 13.1: `unresolved_mention`,
`candidate_match`, `provisionally_linked`, `confirmed_person`,
`duplicate_candidate`, `merge_proposed`, `merged`, `split_proposed`, `split`,
`disputed`, `superseded`). A typed outcome such as `RESOLVED_EXACT` /
`RESOLVED_CONTEXTUAL` / `AMBIGUOUS` / `NOT_FOUND` / `CONFLICTED_IDENTIFIER` /
`HISTORICAL_MATCH` is compatible with the specification and required by its
honesty rules (sections 26.4 and 30.4 both list "unresolved identity" as a state
that must be disclosed distinctly), but it is a design decision this campaign
makes rather than one the specification hands down. WP-RI-03 states the final
vocabulary and its relationship to the section 13.1 states.

**D-RI-08 — capability naming is deferred with its surface.** Specification
section 25 proposes a `relationships.*` family and explicitly calls it *"a
proposed future semantic capability family, not an accepted public API"* that
*"must not be forced into those contracts without a versioned decision."* It
contains no read `resolve` capability at all. WP-RI-05 makes and records that
versioned decision.

**D-RI-09 — the scoring and closed-vocabulary guards now reach this plane.**
Both `tests/architecture/test_relationship_scoring_surface_is_denied.py` and
`tests/relationship/test_relationship_domain.py` selected their population by
the `relationship_` table-name prefix, so the four new tables escaped both. A
plane that stores people, organizations, their assignments and their typed edges
is the relationship surface whatever its tables are called; both now scan
`relationship_`, `entities`, and `entity_`.

**D-RI-10 — `updated_at` is carried.** Specification section 12.1 asks for
"created and updated times". Nothing updates an entity yet, so the column has a
server default and no trigger; the work package that first mutates an entity
sets it.

---

## 5. Known gaps carried forward

* **`Entity.canonical_name` normalization is unenforced** (`D-RI-13`). WP-RI-06
  owns it.
* **Contextual resolution is only as good as the scope it is given.** WP-RI-03
  narrows by assignment and by outgoing relationship, and reports
  `NARROWED_BY_SUPPLIED_SCOPE` only when the scope actually excluded someone. It
  does not rank, calibrate, or evaluate — WP-RI-04 owns those, including the
  collision-biased false-resolution evaluation.
* **No MCP or capability surface exists** (`D-RI-01`), so nothing outside the
  process can reach any of this yet. That is deliberate until WP-RI-05.
* **`record_assignment` and `record_relationship` have no natural key**, so a
  retry that mints a fresh identifier writes a second row (RI-AC-036).
* **The specification is silent** on identifier namespaces, the normalization
  algorithm, `effective_from`/`effective_to` null and overlap semantics, as-of
  queries, merge-redirect read behaviour, person lifecycle values, and
  organization resolution. WP-RI-03 and WP-RI-04 must decide each explicitly
  rather than inherit an assumption.
