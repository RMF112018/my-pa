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
| WP-RI-04 | Contextual resolution: bounded candidate ranking, calibration, explainable evidence, collision-biased safety, false-resolution evaluation | **complete** |
| WP-RI-05 | The capability and MCP surface: five `Capability` members, the `entity_read` purpose, the forward `ALTER`, commands, handlers, transport builders, scope policy, the composition gate, and a minimal context card | **complete** |
| WP-RI-06 | Observation, proposal, and governed merge with lineage | **complete** |
| WP-RI-07 | Context card enrichment: coverage, freshness, and generation identity | **complete** |
| WP-RI-08 | Re-enrichment: bounded, idempotent passes after a merge and after an alias | **complete** (two of nine triggers) |
| WP-RI-09 | Read-only operator inspection (`scripts/inspect_entity_plane.py`) | **complete** |
| WP-RI-10 | Dormant intelligence-Task profile, read-only and default-off | **complete** (draft, not activated) |
| WP-RI-11 | Security and privacy regression for the entity plane | **complete** |
| WP-RI-12 | Acceptance evidence against the ledger in section 3 | **complete** |
| WP-RI-13 | Operator runbook (`ops/runbooks/relationship-intelligence.md`) | **complete** |

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
  Delivered as `tests/evaluation/fixtures/resolution_corpus.py` and measured by
  `tests/evaluation/resolution_harness.py`; the frozen result is
  [`tests/evaluation/RESOLUTION_CALIBRATION.md`](../../tests/evaluation/RESOLUTION_CALIBRATION.md).

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
named), `OPEN` (in a work package this campaign has not yet delivered),
`UNMET` (the work package that was to carry it has shipped, and shipped without
it), `BLOCKED_BY_D09` (needs the held frontend),
`NOT_APPLICABLE_TO_THIS_CAMPAIGN` (belongs to another plane).

`UNMET` exists because `OPEN` stopped being true. Nine criteria were routed to
WP-RI-06, WP-RI-07 and WP-RI-10; all three have now landed, and a criterion
still reading "in a planned work package" against a delivered package is a
ledger that quietly converts an unmet criterion into a scheduled one. Each is
restated below against what actually shipped, with the specific missing thing
named rather than a package number. **No criterion moved to `MET` in this
pass**; the change is from a status that was wrong to one that is not.

| ID | Criterion (abridged) | Status | Where |
|---|---|---|---|
| RI-AC-001 | Public language is Relationships / Relationship Intelligence; PRIE historical only | `MET` (backend) | No source, doc or runbook produced here uses "PRIE"; `ops/runbooks/relationship-intelligence.md` and the capability names use the current label. User-facing copy is `BLOCKED_BY_D09` |
| RI-AC-002 | Integrated into `my-pa`, not a standalone engine | `MET` | No new process, database, or service; `tests/architecture/test_dependency_direction.py` |
| RI-AC-003 | The product states relationships are not scores | `PARTIAL` | Enforced structurally by `tests/architecture/test_relationship_scoring_surface_is_denied.py`, widened to the entity plane; no numeric reaches the durable surface (`D-RI-14`). The *statement* is WP-RI-13 |
| RI-AC-004 | Value without starting a chat | `BLOCKED_BY_D09` | — |
| RI-AC-005 | Contact/source rows stay observations, not automatic canonical people | `MET` | `EntityGovernanceService.observe` records an observation and can do nothing else; `tests/unit/test_entity_governance.py` asserts no entity appears |
| RI-AC-006 | Unresolved mentions are first-class and searchable | `MET` (backend) | An unlinked `entity_observations` row *is* the unresolved mention, listable via `unresolved_mentions`; resolution answers `AMBIGUOUS`/`NOT_FOUND` over the wire. Surfacing it to a user is `BLOCKED_BY_D09` |
| RI-AC-007 | No identity merge without governed policy | `MET` | `ReviewRequirement.REQUIRES_OPERATOR` refuses an unauthorised accept; the server refuses a decided proposal with no actor (`tests/database/test_entity_governance.py`) |
| RI-AC-008 | Merge preview shows all materially affected records | `UNMET` | WP-RI-06 shipped the merge *record* and `merge_lineage`, which are post-hoc. Nothing computes a pre-decision preview, and there is no surface on which to show one: `EntityGovernanceService` is composed by nothing (`D-RI-21`, runbook section 4). Needs a decision surface first |
| RI-AC-009 | Merge and split history preserved and correctable | `PARTIAL` | `entity_merge_records` carries actor, reason, moment and both identifiers; the merged entity survives as a redirect. **Split is not implemented** — section 15.4's requirements are unmet and open |
| RI-AC-010 | Negative identity evidence prevents repeated false matches | `UNMET` | WP-RI-06 brought the record it needed — a rejected proposal persists as `EntityProposalState.REJECTED` — but nothing reads it back. `EntityResolutionService` consults entities, aliases and identifiers and never proposals, so a rejected merge does not stop the same pairing being proposed again. The gap is a read, not a table |
| RI-AC-011 | Every material profile statement links to evidence or is marked | `PARTIAL` | The context card carries its observations and per-source `coverage`, and marks what it left out (`ContextCardLimitation`, including `COVERAGE_COUNTED_A_BOUNDED_SAMPLE`). But an alias, an identifier and an assignment on that card carry no link to the observation that evidenced them — no column relates them — so those statements are neither linked nor marked |
| RI-AC-012 | Source facts / notes / assertions / inferences structurally distinct | `PARTIAL` | `ObservationKind` distinguishes kinds of *source record* (contact row, message participant, calendar attendee, document mention, user statement). It does not distinguish a source fact from an assertion or an inference: nothing in this plane records an inference at all, so the distinction is unmade rather than made wrongly |
| RI-AC-013 | Coverage, freshness, exclusions appear before synthesis | `MET` (backend) | The card carries `coverage` per source, `most_recent_observation_at`, `assembled_at`, and `limitations`, ordered before the records. Presentation is `BLOCKED_BY_D09` |
| RI-AC-014 | Stale evidence never presented as current | `PARTIAL` | Resolution answers `HISTORICAL_MATCH` with `ENTITY_IS_NOT_CURRENT`/`ENTITY_HAS_BEEN_MERGED_AWAY`, and filters evidence by effective date under `as_of` (WP-RI-03). Briefing-level staleness is WP-RI-07; presentation is `BLOCKED_BY_D09` |
| RI-AC-015 | Contradictory evidence preserved, not collapsed | `PARTIAL` | Preserved, and one contradiction is surfaced: an identifier claimed by two entities answers `CONFLICTED_IDENTIFIER` rather than picking one (`tests/unit/test_entity_resolution.py`). Nothing is ever deleted or merged away silently. But contradiction *between observations* — two sources disagreeing about a name or an affiliation — is stored and never detected or presented as a contradiction |
| RI-AC-016 | Briefings retain evidence scope and model identity | `PARTIAL` | The context card carries `assembled_at` and per-source `coverage`. No briefing and no model exist to attribute — `NOT_APPLICABLE` until one does |
| RI-AC-017 | Person profile exposes the full record set | `BLOCKED_BY_D09` | — |
| RI-AC-018 | Timeline distinguishes event / effective / observed / recorded times | `PARTIAL` | `effective_from`/`effective_to` and `created_at`/`updated_at` exist; the four-clock model is WP-RI-06 |
| RI-AC-019 | Profile navigation preserves context and return state | `BLOCKED_BY_D09` | — |
| RI-AC-020 | Organization profiles support time-aware associations | `PARTIAL` | The schema is time-aware; the profile is `BLOCKED_BY_D09` |
| RI-AC-021 | Commitments retain obligor, beneficiary, outcome, source, lifecycle | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | The commitment plane already exists (WP-TM-05) |
| RI-AC-022 | Commitments and tasks remain distinct | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Existing planes |
| RI-AC-023 | Extracted commitments require review initially | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Existing review plane |
| RI-AC-024 | Fulfillment retains evidence or explicit confirmation | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Existing planes |
| RI-AC-025 | Commitments by and to a person separately visible | `UNMET` | WP-RI-10 delivered the dormant Task profile and the privacy regression suite; neither touches commitments. No column, query or capability relates an entity to a `commitments` row in either direction. This is a join this campaign did not build |
| RI-AC-026 | Follow-ups distinct from commitments | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Existing planes |
| RI-AC-027 | Meeting briefing identifies attendee ambiguity and unavailable evidence | `UNMET` | WP-RI-07 delivered both halves *as parts*: `entities.resolve` names attendee ambiguity (`AMBIGUOUS`, ranked alternatives, warnings) and the card names unavailable evidence (`NO_SOURCE_HAS_BEEN_OBSERVED` and the other limitations). There is no meeting briefing to assemble them into, and nothing reads a calendar event |
| RI-AC-028 | Deterministic meeting context usable when AI is unavailable | `PARTIAL` | The determinism half holds: `EntityContextService` calls no model, takes its clock as an argument, and returns the same card for the same rows — so the context that exists is fully usable with AI unavailable. The *meeting* half does not exist; the card is assembled per entity, not per event |
| RI-AC-029 | Briefing claims navigate to source evidence | `BLOCKED_BY_D09` | — |
| RI-AC-030 | Post-meeting capture creates proposals without changing source events | `PARTIAL` | The proposal plane exists and writes no source; no capture pipeline feeds it yet |
| RI-AC-031 | Quick Note / Call launchable in-app and from device shortcuts | `BLOCKED_BY_D09` | — |
| RI-AC-032 | One general input field required before save | `BLOCKED_BY_D09` | — |
| RI-AC-033 | Original input durably stored before enrichment | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Quick Capture plane (ADR-003) |
| RI-AC-034 | Enrichment failure does not lose or block the capture | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Quick Capture plane |
| RI-AC-035 | Participants, commitments, sensitive facts, dates follow review policy | `PARTIAL` | Identity proposals require review and merges require an operator; commitments and sensitive facts belong to their own planes |
| RI-AC-036 | Repeated processing does not duplicate structured records | `PARTIAL` | `bind_identifier` and `record_alias` are idempotent against a natural key; re-enrichment passes are idempotent and tested twice-run. `record_assignment`/`record_relationship` remain idempotent only against their own identifier — a retry minting a fresh one still writes a second row |
| RI-AC-037 | Capture corrections retain immutable before/after evidence | `NOT_APPLICABLE_TO_THIS_CAMPAIGN` | Quick Capture plane |
| RI-AC-038 | AI output carries an authority class | `UNMET` | Nothing in this plane produces AI output — every capability is a deterministic read — so there is no output here to class. The criterion becomes live for whatever first generates a statement about an entity, and this campaign built no such generator. Recorded as unmet rather than not-applicable: the plane is what such a generator would read from |
| RI-AC-039 | Models cannot merge identities or promote inferences autonomously | `MET` | `propose` cannot apply; `accept` refuses a merge without declared operator authority; both mutations were mutation-tested |
| RI-AC-040 | No external action occurs through a relationship knowledge write | `MET` | The plane has no write capability at all and no connector; the Task profile grants five reads. `tests/security/test_entity_privacy_regression.py` asserts a name that reads as an instruction reaches no tool description and gains no capability |

**Tier discipline.** A criterion requiring MCP, integration, canary, or live
evidence is not satisfied by a FAST-tier unit test. RI-AC-036 in particular is
a database-tier claim about what the server refuses, and is marked `PARTIAL`
here precisely because no such test exists yet.

---

## 4. Decisions taken, and where they depart from the specification

Recorded here because each one is a choice a reviewer would otherwise have to
reconstruct from a diff.

**D-RI-24 — the intelligence Task profile is read-only and dormant.**
`bootstrap/relationship_intelligence_task.py` states which capabilities a
proposed Task may reach: the five reads and nothing else, `DRAFT_NOT_ACTIVATED`,
and empty until the process gate is on. It creates, edits and enables nothing —
live Abacus/ChatLLM Task changes are out of scope for this campaign by explicit
instruction and reserved by `AGENTS.md` section 8.2 regardless. The profile
exists so the answer to "what would such a Task be allowed" is in the repository
before anyone is in a position to grant it.

**D-RI-25 — two of nine re-enrichment triggers.** Specification section 27.4
lists nine; `WP-RI-08` implements the two that are reachable — a completed merge
(re-point the stranded observations) and a recorded alias (re-offer the
unresolved mentions). The other seven need observations from sources this
product does not read. Listed in the module rather than implied, because a pass
that silently covered two of nine would look like a pass that covered all of
them. The alias pass links only `RESOLVED_EXACT`: a background walk with nobody
watching is the last place a doubtful identity join should be made.

**D-RI-26 — re-enrichment carries a precondition and a constraint, not just a
bound.** Two decisions taken after adversarial review, both of the same kind:
a background pass with nobody watching may not make an identity join a watched
one would have refused.

* `after_merge` requires a **recorded merge in that direction and that
  Principal's partition** before it moves a single observation. Its authority to
  re-point someone's evidence at another person comes from an operator's
  decision (section 8.4) and from nothing else; called with two identifiers no
  decision connects, it performed exactly the false join `RI-RISK-001` names —
  silently, with no proposal, no actor, and no lineage row to find it by.
* `after_alias` carries each mention's kind into resolution as an `entity_type`
  constraint where the kind settles it (`KIND_IMPLIES_ENTITY_TYPE`). A contact
  row, a message participant and a calendar attendee are records *of a person*.
  Without the constraint the pass asked only "who is called this", and a
  calendar attendee linked to a project of the same name. `DOCUMENT_MENTION`
  and `USER_STATEMENT` are deliberately unconstrained — a document can name
  anything, and inventing a constraint there would be this module guessing.

Both are mutation-tested: removing either reddens the suite.

**D-RI-27 — coverage is computed to a stated ceiling, not from the displayed
page and not without limit.** The context card carries at most
`CONTEXT_CARD_COLLECTION_LIMIT` observations and computes `coverage` from up to
`CONTEXT_CARD_COVERAGE_LIMIT` of them. Both halves matter. Computing coverage
from the twenty-five shown would report "one source" for an entity with four,
which is the claim the card exists to make trustworthy. Computing it from all of
them makes a single read pull an unbounded result set, because observations are
the one collection here that grows with every source record that ever mentioned
someone. When the ceiling bites the card says so
(`COVERAGE_COUNTED_A_BOUNDED_SAMPLE`), so a partial count is never presented as
a complete one.

**D-RI-28 — a decision is a one-time act, enforced by the write predicate.**
`decide_proposal` carries `state = 'proposed'` in its own `UPDATE` predicate
rather than checking before writing. `EntityGovernanceService` already refuses a
decided proposal, but that check reads and then writes — two statements, so two
callers can both read "open". Without the predicate, the second write replaced
`decided_by`, `decided_at` and the reason: the record of who decided and why
became whoever called last, and a *rejected* merge could be re-accepted with
nothing left to show it had ever been refused. A merge record's `proposal_id` is
partition-checked for the same reason — a row citing another Principal's
proposal presents their decision as this Principal's own.

**D-RI-21 — WP-RI-06 registers no capability, and that is the gate.** The
governance plane writes: it links observations, decides proposals, and redirects
merged entities. Specification section 21.4 forbids a model merging identities;
`RI-AC-039` says the same; the carry-forward gate on this campaign says write
methods must not become remote before their authorization gate. So observation,
proposal and merge are reachable in-process — by `WP-RI-08`'s re-enrichment and
by a future review surface — and reachable over no transport at all. A write
capability would need a write purpose, which would put it in
`adapters/mcp/remote._WRITE_PURPOSES` and on the remote surface the moment
writes were enabled, and that is a decision for the work package that has a
reviewer to grant it.

**D-RI-22 — `ReviewRequirement`, not a risk band.** Specification section 12.18
asks a review case for a "risk class"; the scoring prohibition refuses the token
`risk` on this surface. Naming the concept for what it *does* —
`MAY_BE_ACCEPTED_AUTOMATICALLY`, `REQUIRES_REVIEW`, `REQUIRES_OPERATOR` — keeps
the guard intact and is more useful besides: "this needs an operator" is
actionable, where "high risk" is a label somebody still has to translate. It is
derived from the proposal kind rather than stored on the proposal, so a proposer
cannot name its own weakest requirement.

**D-RI-23 — a merge redirects; it never deletes.** Accepting a merge sets the
merged-away entity to `merged_redirect`, points it at the survivor, and writes an
`entity_merge_records` row naming the actor, the reason and the moment. It does
not delete the entity, rewrite its identifiers, or move its observations.
Section 15.3 asks a merge to preserve prior identifiers as lineage and to support
a governed correction path, and an entity that still resolves as a
`HISTORICAL_MATCH` is how both are true at once. Re-pointing the records that
referred to it is `WP-RI-08`.

**D-RI-18 — WP-RI-05 registered all five capabilities at once, including
`entities.context`.** Registering one costs a forward `ALTER` on
`capability_is_known`/`purpose_is_known` plus roughly fifty test registries and
prose counts; splitting the family across two work packages would pay that
twice. So WP-RI-05 delivered a minimal-but-real context card — the records
around an entity, bounded per collection, with every bound that bit named — and
WP-RI-07 enriches it without touching the capability registry. The alternative,
registering four now and one later, would have re-run the whole registration
dance for one name.

**D-RI-19 — one purpose, `entity_read`, for all five.** A purpose of its own
rather than a reuse, on the `TASK_READ` argument: no existing purpose reaches
`knowledge.entities`, and a grant issued to search extracted text has no
occasion to also return who a person is. *One* rather than five, on the
`capture.search` argument (`D-91`): all five read the same rows under the same
authority, so a second read purpose would map to exactly one capability and
separate nothing. There is deliberately no write purpose — this plane has no
write capability, and a purpose no capability permits is denied for everything
and reads as a mistake rather than as a decision.

**D-RI-20 — the plane is off by default, and that is the remote-exposure
gate.** `Settings.relationship_intelligence_enabled` defaults `False`, and
`ApplicationService.available_capabilities` subtracts `_ENTITY_CAPABILITIES`
from what the build serves when it is. This is the mechanism `D-RI-01`
promised, and it is the only one that works: `adapters.mcp.remote.remote_tool_names`
derives the remote profile from `Capability` with no per-capability exclusion
list, so "this build serves it" and "a remote client can reach it" are one
decision. `tests/contract/test_mcp_transport.py` proves the withholding against
a real child process; `tests/contract/test_entity_remote_exposure.py` proves it
about the remote profile specifically, which no existing test reached — the
existing remote test asserts membership by name and so could never have noticed
an *addition*.

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

**D-RI-14 — the calibration is a measured table, not a number on a record.**
Specification section 22.3 admits a numeric "only when calibrated and
explained", and `D-RI-02` removed `confidence` from the durable surface because
nothing calibrated it. WP-RI-04 resolves that tension without weakening either
constraint: an answer carries the *basis* it rests on, and
`RESOLUTION_CALIBRATION.md` publishes the observed precision of each
`outcome:basis` pair over the labelled corpus. The number is a counted frequency
rather than a chosen weight, it lives in the evaluation rather than on a record
about a person, and a reader who wants to know what a `RESOLVED_EXACT` on a
verified identifier is worth looks it up. The table is keyed by outcome *and*
basis deliberately: keyed by basis alone it would report `canonical_name: 1.0`,
which would read as though a bare name were sufficient — the exact claim the
plane refuses. `exact_resolutions_on_a_bare_name` is asserted to stay zero.

**D-RI-15 — the safety evaluation runs in the FAST tier, not as a SPECIALIZED
suite.** `tests/evaluation`'s existing harness is `evaluation`-marked, which no
CI job selects. That is right for a suite that exercises a whole retrieval
pipeline and wrong for this one: it is microseconds of pure Python over an
in-memory corpus, and what it protects is the plane's central claim.
`AGENTS.md` section 7 admits a test to the PR gate when it protects a critical
contract at acceptable cost. The frozen record is checked in the same run, so
the published calibration cannot rot.

**D-RI-16 — a recall floor, because "never resolve" would otherwise pass.** Zero
false joins is trivially achievable by answering nothing, so
`resolution_recall` is measured over `MUST_RESOLVE_FAMILIES` and floored at
0.9. Both failure modes are measured, because only measuring both distinguishes
a careful resolver from a useless one. The corpus therefore contains cases that
*must* resolve — a married name, a diacritic variant, a reissued mailbox at two
different moments — and refusing those is as much a failure as joining the two
Alices.

**D-RI-17 — no signal that nothing can reach.** A `SHARES_THE_REFERENCE_IDENTIFIER_DOMAIN`
signal was drafted and removed: contextual signals are computed only on the name
path, which runs only when the identifier lookup found nothing, so a
domain-corroboration signal would have required a person whose *name* is an
email address. Section 15.1 does list "email addresses and domains" as
resolution evidence, and it becomes reachable when observations arrive; it is
not modelled before then. The discriminating/corroborating split went with it,
for the same reason — a classification with one empty half classifies nothing.

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

## 4a. Evidence, as executed

Every figure below was produced by running the command named, on this branch.

| Claim | Evidence |
|---|---|
| FAST tier green | `pytest -m "not slow and not database and not network and not connector and not evaluation and not e2e and not recovery"` — **7881 passed, 0 failed, 933 deselected** |
| Lint and format | `ruff check .` and `ruff format --check .` — clean over 913 files |
| Types | `mypy` (configured targets: `src`, `migrations`, `apps`, `ops`) — clean over 337 files |
| Full database tier green | `pytest -m "database or recovery or e2e"` against a live PostgreSQL 17 — **923 passed, 0 failed, 7891 deselected**. The four schema-suite failures adversarial review surfaced (accumulation sets in the audit, enrollment, capture and entity migration tests, outgrown by this plane's eight tables and five capabilities) are fixed, not deselected |
| Evaluation tier | `pytest -m evaluation` — 2 passed. Selected by no CI job by design; the frozen record is what CI checks |
| Migrations apply and reverse | `tests/schema/test_entity_schema_migration.py` — 54 tests: empty-to-head, head-to-empty, and declaration-to-server constraint, column and partition parity across **all eight** plane tables, against a disposable PostgreSQL 17. The parity groups were parameterized on this revision's four until the governance revision added three the parity checks never reached |
| Partition holds at the server | `tests/database/test_entity_repository.py` — 34 tests: cross-Principal isolation on every read and every write, including the joined resolution lookups, and the redirect refusals (cycle, chain, absent survivor, cross-partition) |
| Governance holds at the server | `tests/database/test_entity_governance.py` — 18 tests: a proposal cannot be accepted without an actor in either direction; a decided proposal cannot be decided again (asserted at the repository, below the service's own check); a merge record cannot cite another Principal's proposal |
| The context card is honest about its own bounds | `tests/unit/test_entity_context.py` — 9 tests: coverage counts past the page the card displays, discloses when the read ceiling bit, holds at the off-by-one, never counts another Principal's observation, and asks the repository for a bounded read. `tests/database/test_entity_governance.py` proves the cap becomes a server-side `LIMIT` rather than a slice of a full result set. Before this the module had no direct test at all |
| MCP surface | `tests/contract/test_mcp_transport.py` — a real child process publishes 53 tools when composed for the plane and withholds all five when not |
| Remote exposure | `tests/contract/test_entity_remote_exposure.py` — none of the five reaches the remote profile with the plane off, under either write setting |
| False-resolution rate | [`tests/evaluation/RESOLUTION_CALIBRATION.md`](../../tests/evaluation/RESOLUTION_CALIBRATION.md) — 0 false resolutions, 0 cross-Principal leaks, 0 forbidden candidates, recall 1.0 over **27** labelled collision-biased cases (12 must-resolve, 15 must-not) |
| The safety rules bite | Mutation-tested: resolving a lone name, choosing a claimant of a conflicted identifier, ignoring effective dates, dropping the partition, dropping the operator gate, letting `propose` apply its own merge, dropping the observation-kind entity-type constraint, dropping the recorded-merge precondition, dropping the still-open predicate, dropping the merge record's proposal partition check — each reddened the suite |

**What no evidence here covers.** Nothing has been run against a shared or
production database; every database figure comes from a disposable database
created and dropped by its own fixture. No connector, source, or live personal
data was touched. **No independent exact-head review has occurred**, so nothing
here is merge-eligible under `AGENTS.md` section 8.1. The adversarial pass
recorded in section 4b was run by this campaign against its own work; it is not
that review and does not substitute for it.

---

## 4b. Adversarial review, and what it found

An adversarial pass was run over the whole branch after WP-RI-13. It raised
thirteen findings. Recording them here because the interesting ones are the
three that were **confirmed by execution rather than accepted on argument** —
each was reproduced as a failing assertion before anything was changed, and each
had made the resolver answer confidently and wrongly.

| # | Severity | What it was | Disposition |
|---|---|---|---|
| 1 | HIGH | The `entity_type` filter ran *before* the conflicted-identifier check, so an identifier claimed by a person and a project answered `RESOLVED_EXACT` — a different entity per caller, with no warning | Fixed: the conflict is computed on the unfiltered effective set |
| 2 | HIGH | One unnormalized `canonical_name` flipped `AMBIGUOUS` to `RESOLVED_EXACT` naming the *neighbouring* entity. The same hole existed, undocumented, on `EntityAlias.normalized_value` and `ExternalIdentifier.normalized_value` | Fixed: `is_normalized_name` / `is_normalized_identifier` are enforced by all three records at construction. `ExternalIdentifierNamespace` moved to `normalization.py` so the dependency runs one way |
| 3 | MED-HIGH | `RESOLVED_CONTEXTUAL` required a rival, so adding a duplicate row *upgraded a refusal into a resolution*. Separately, a scope true of nobody was silent | Fixed: corroboration resolves without a rival; a scope matching no candidate warns |
| 4 | MED | `redirect_entity` permitted a merge cycle and a merge chain, making `superseded_by_entity_id` a pointer that never arrives | Fixed and regression-tested at the SQL layer; the fake carries the same guard so a unit test cannot pass without it |
| 5 | MED | `EntitiesRepository.create` took no `principal_id`, contradicting the port's own universal invariant | Fixed: `create(principal_id, entity)`, 130 call sites updated |
| 6 | MED | `after_merge` moved observations between any two entities named together — no merge record required. `after_alias` discarded the observation's kind, so a calendar attendee could link to a project of the same name | Fixed: a recorded merge in that direction and partition is a precondition; `KIND_IMPLIES_ENTITY_TYPE` constrains the re-offer. Both mutation-tested |
| 7 | MED | The runbook instructed operators to run `EntityGovernanceService` and `EntityReenrichmentService`, which **nothing in `src/` composes** | Corrected, not papered over: runbook section 4 now says plainly that the queue can be read and cannot be worked, and section 7 carries it as a gap |
| 8 | MED | Nine acceptance criteria read `OPEN` — "in a planned work package" — against WP-RI-06/07/10, all of which had shipped | Fixed by re-dispositioning each against what actually shipped, with an `UNMET` status added for exactly this. **None moved to `MET`** |
| 9 | LOW | `cross_principal_leakage` in the calibration record actually counted all forbidden candidates | Fixed: split into two metrics |
| 10 | LOW | The inspection script emitted free-text `proposed_by` while claiming it printed no personal data | Fixed: the column is not selected, and the docstring says why |
| 11 | LOW | The end-to-end scoring scan covered four of the five capabilities | Fixed: `ENTITIES_RELATIONSHIPS` added |
| 12 | LOW | `ports.py` said "no alias table exists yet" — stale since WP-RI-03 | Fixed: the claim (aliases are not searched) is now stated as the decision it is, with the disclosure reason |
| 13 | LOW | Six smaller items: an unbounded observation read in the context card (and, once looked for, the same slice-after-fetch in both re-enrichment passes); `record_merge` not partition-checking `proposal_id`; `decide_proposal` not asserting the proposal was still open; `reached_the_bound` naming; a stale file count; two must-resolve cases filed under a "must not resolve" banner | All fixed. The two persistence ones carry mutation-tested database regressions; the card now reads at a disclosed ceiling and says when it bit |

Four schema-suite failures surfaced alongside these, all of the same kind:
accumulation sets in `test_audit_schema_migration.py`,
`test_enrollment_objects_migration.py`, `test_capture_schema_migration.py` and
`test_entity_schema_migration.py` that name what the revisions above them create,
and which the entity plane's eight tables and five capabilities had outgrown.
Each was corrected as bookkeeping.

---

## 5. Known gaps carried forward

* **`Entity.canonical_name` normalization is unenforced at the schema level**
  (`D-RI-13`). The domain records now refuse an unnormalized canonical name,
  alias value or identifier value at construction, so nothing routed through
  `Entity`, `EntityAlias` or `ExternalIdentifier` can store one — that was
  adversarial finding 2, and it had made a refusal resolve to a *neighbouring*
  entity. A migration, a backfill or a direct `INSERT` still can: the CHECK
  would have to reimplement `normalize_name` in SQL, which would then be a
  second implementation to keep in step with the first.
* **The evaluation measures the service against a double, not against SQL.**
  `_CorpusRepository` subclasses the real port, so the service cannot pass
  against a shape production could not supply — but the production partition,
  the joins, and the constraints are proved in `tests/database` and
  `tests/schema`, not here. Neither suite alone is sufficient.
* **The corpus is small and synthetic.** Twenty-seven labelled cases over twelve
  entities is evidence that the stated refusals hold and that the resolver still
  answers what it should. It is not a population estimate, and no number in
  `RESOLUTION_CALIBRATION.md` should be read as a probability about a real
  person. That limitation is stated in the report itself.
* **Only two contextual signals exist** — assignment to a named scope, and a
  typed relationship reaching it. Section 15.1's calendar attendees, email
  participants, introduction chains, and negative evidence all need the
  observation record. WP-RI-06 has since delivered that record, and the
  resolver still does not read it: `EntityResolutionService` consults entities,
  aliases and identifiers only. `RI-AC-010` is therefore `UNMET` rather than
  `OPEN` — the table it was waiting for exists, and the read was never written.
* **The MCP surface exists and is off by default** (`D-RI-20`). A process that
  has not set `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED` publishes none of the
  five, locally or remotely.
* **`record_assignment` and `record_relationship` have no natural key**, so a
  retry that mints a fresh identifier writes a second row (RI-AC-036).
* **The governance plane has no caller.** `EntityGovernanceService` and
  `EntityReenrichmentService` are composed by nothing in `src/` — no capability
  (`D-RI-21`), no bootstrap wiring, no script, no worker. A proposal can be
  written and read and cannot be decided. This is the single largest gap between
  what the branch implements and what an operator can do with it, and it is
  named in `ops/runbooks/relationship-intelligence.md` section 4 as well, since
  the runbook is where somebody would go looking for the procedure.
* **The context card counts coverage from at most
  `CONTEXT_CARD_COVERAGE_LIMIT` observations**, and says so
  (`COVERAGE_COUNTED_A_BOUNDED_SAMPLE`) when the ceiling bites. Beyond it the
  per-source counts are floors and a source may be missing entirely.
* **The specification is silent** on identifier namespaces, the normalization
  algorithm, `effective_from`/`effective_to` null and overlap semantics, as-of
  queries, merge-redirect read behaviour, person lifecycle values, and
  organization resolution. WP-RI-03 and WP-RI-04 must decide each explicitly
  rather than inherit an assumption.
