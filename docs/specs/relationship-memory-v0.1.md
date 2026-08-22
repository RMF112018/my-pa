# Relationship Memory — implemented contract v0.1

Status: **implemented**, composed off by default. This file describes what the
repository does, not what a product package proposes. It is repository-native
and derived from the accepted package
`MYPA-RELATIONSHIP-MEMORY-ENTITY-NOTES-20260822-001` (Drive folder
`1QraevD7durAYrSaTcOBN2YFMnRZkHP6c`, artifacts `MYPA-RM-00` through
`MYPA-RM-04`); the package remains the product-intent record and this file
remains the executable truth. Where they disagree, this file and the code it
describes are what runs.

Parent requirements source:
[`relationship-intelligence-v0.2.md`](relationship-intelligence-v0.2.md),
section 9.10 (private observations). Authority class:
[ADR-003](../decisions/ADR-003-product-owned-user-authored-source-records.md),
whose clause 6 bindings a memory version carries in full.

## 1. What a Relationship Memory is

One durable statement about one generalized `Entity`, recorded deliberately by
the owning Principal so a later profile view or briefing can use it without
mistaking a private note for an externally proven fact.

It is a record class of its own. It is **not** an `EntityObservation` (evidence
that a source supplied a value used in resolution), **not** a legacy
`RelationshipEvent(OBSERVATION)` (Person-only, unversioned, different acceptance
model), **not** a Quick Capture (the user's unstructured text, which is a
*source* for a memory rather than the memory), and **not** a JSON column on
`entities` (which would put a narrative body on the identity row and make every
entity read a read of private notes).

## 2. Kind and authority are separate axes

`MemoryKind` says what the information means. `MemoryAuthority` says why the
product may present it and with what epistemic status. They are independent: the
same sentence is a `communication_preference` whether the user typed it or a
reviewer promoted it from an email, and the two differ only in authority.

Kinds (ten, closed): `general_note`, `personal_detail`, `important_date`,
`interest`, `communication_preference`, `working_preference`, `concern`,
`sensitivity`, `follow_up_context`, `user_pinned_context`.

Three are Person-only — `personal_detail`, `important_date`, `interest` — and
`sensitivity` deliberately is not: a caution about a topic can belong to an
organization as easily as to a person, and restricting it would push the same
statement into `general_note` for a vendor, losing its classification floor.

Authorities (four, closed): `user_authored_private_note`,
`user_confirmed_assertion`, `source_backed_assertion`, `public_assertion`.
`model_inference` and `unresolved_claim` are **absent from the enum**, which is
the structural form of "a model may not create active memory": there is no value
a promotion path could write.

## 3. Public capability surface

Eight `relationship_memory.` names, and there is deliberately no ninth:

| Capability | Purpose | Notes |
|---|---|---|
| `relationship_memory.create` | `relationship_memory_authoring` | one direct user-authored memory |
| `relationship_memory.revise` | `relationship_memory_authoring` | appends a successor; requires `expected_version` |
| `relationship_memory.archive` | `relationship_memory_authoring` | reversible; requires `expected_version` |
| `relationship_memory.restore` | `relationship_memory_authoring` | reversible; requires `expected_version` |
| `relationship_memory.get` | `relationship_memory_read` | one named memory |
| `relationship_memory.list` | `relationship_memory_read` | entity-scoped, bounded |
| `relationship_memory.search` | `relationship_memory_read` | Principal-scoped, lexical |
| `relationship_memory.history` | `relationship_memory_read` | immutable versions |

There is no `relationship_memory.delete`. Archive is reversible, history is
retained, hard deletion is unresolved by ADR-003 and reserved to the operator,
and a capability name for it would be the first half of building one.

Every write requires an idempotency key. Every state-dependent write requires
`expected_version`, which is the **aggregate** version counter and not the
version number of a statement.

## 4. Server-owned fields

A caller supplies only what a user could legitimately choose: the subject, the
kind, the words, the optional times, the context, the pin, the idempotency key.
The application layer supplies the Principal, the authority (always
`user_authored_private_note` on the public path), the classification, cloud
eligibility, the actor class, and the receipt time.

The mechanism is **absence, not validation**: the command dataclasses have no
`authority`, `classification`, `cloud_eligible`, `principal_id`, `recorded_at`,
`actor` or `review_state` field, so a payload naming one is refused by the
constructor before any handler runs. Nothing reads such a field and decides to
ignore it, because a field that can be sent is a field a later change can start
honouring.

## 5. Classification and disclosure

`sensitivity` floors at `restricted_local`; every other kind floors at
`private_local`. The floor is a floor and not an assignment — an ordinary note
may be stored restricted, and a sensitivity may never be stored merely private.
`cloud_eligible` is stored, CHECKed false in the schema, and refused in the
domain; no path sets it true.

`relationship_memory.list` discloses restricted memories, because the request
already names one entity the Principal owns and holds the read purpose for it —
the narrow profile view. `relationship_memory.search` never does, and the
exclusion is a SQL predicate rather than a post-filter, so a restricted memory
cannot reach a count, a truncation flag or a cursor. Probing a term that appears
only in a restricted memory returns nothing and says nothing.

## 6. Persistence

Eight tables in schema `knowledge`, created by revision `f1c6b904a2d7`:

- `relationship_memories` — identity, kind, lifecycle, current-version pointer,
  aggregate version, pinned. **No narrative text.**
- `relationship_memory_versions` — the immutable statements. Append-only,
  enforced by a `BEFORE UPDATE OR DELETE` trigger, which is why there is no
  `superseded_at` column: supersession is read from `prior_version_id`.
- `relationship_memory_submissions` — the idempotency mechanism, unique on
  `(principal_id, idempotency_key)`, with a payload digest that separates a
  replay from a conflict.
- `relationship_memory_context_links` — where a memory applies, bound to the
  *version* so a revision cannot retroactively rescope the wording it replaced.
- `relationship_memory_evidence_links` — exactly one evidence target per row.
- `relationship_memory_proposals`, `relationship_memory_proposal_evidence`,
  `relationship_memory_review_decisions` — the proposal plane. A proposal never
  enters `relationship_memories`, which is what makes "a proposal cannot appear
  in an ordinary memory read" a property of the schema rather than a predicate
  every query has to remember. **Nothing in this build writes those three
  tables**; section 11 states what that means and why they exist anyway.

Two version counters, deliberately: `version` is the aggregate's
optimistic-concurrency counter and advances on archive and restore, which write
no statement; `current_version_number` advances only on a revision. Collapsing
them would make `expected_version` on an archive either meaningless or a lie
about the version chain.

Cross-plane context targets carry no foreign key. The identifiers are globally
unique, so an FK would prove a row exists without proving it belongs to the
acting Principal; ownership is proven by the repository before the insert, which
is the only place it can be proven.

## 7. Identity and merges

A write against an Entity in `merged_redirect` state is refused and the
canonical target is returned. It is **not** followed: rebinding would turn a
deliberate annotation about a historical identity into one about the current
person, which is a different statement than the user made. Reads still answer,
and `relationship_memory.get` carries `canonical_subject_entity_id` when the
subject has been merged away. A merge erases no memory and no version.

## 8. What this does not do

No task, reminder, calendar entry, notification or message is created by
recording a memory — `follow_up_context` is context, and an actual obligation
belongs in the Task or Commitment plane. No protected-trait inference, tagging
or normalization exists, and `sensitivity` carries no structured topic
taxonomy on purpose. No hard delete. No multi-user sharing. No second database,
graph store or vector index.

## 9. Composition

Off by default behind `MY_PA_RELATIONSHIP_MEMORY_ENABLED`, which additionally
requires `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED`: a memory's subject is an
Entity and the repository proves ownership of it by reading the entity tables,
so serving memories without the plane that owns their subjects would be serving
writes it cannot validate.

A build without the plane withholds all eight `relationship_memory.` names from `capabilities.get` and
from the MCP tool list, and every handler refuses `unsupported` as a floor under
that — the HTTP transport routes by path segment and consults neither list.

Remote MCP additionally withholds the four writes until remote writes are
enabled, because `relationship_memory_authoring` is a write purpose.

## 10. Deferred, and named rather than implied

- retention and hard deletion (ADR-003 leaves it unresolved);
- multi-user or delegated visibility;
- reminder or attention rules over `important_date`;
- memory redistribution after an identity split;
- any widening of cloud eligibility;
- the frontend experience, which `MYPA-RM-04` describes and which this
  implementation does not build.

## 11. The promotion path has no producer

**Nothing in `src/`, `apps/` or `ops/` writes `relationship_memory_proposals` or
`relationship_memory_proposal_evidence`.** Only test fixtures do. Everything the
promotion path is made of is therefore implemented and tested but unreachable in
any composed build, however the feature flags are set:

- three of the eight tables — `relationship_memory_proposals`,
  `relationship_memory_proposal_evidence` and
  `relationship_memory_review_decisions`;
- the whole of `infrastructure/persistence/relationship_memory_review.py`,
  including the authority rules a promotion applies and the evidence copy that
  makes an accepted memory checkable;
- three domain records — `RelationshipMemoryProposal`,
  `MemoryProposalEvidence` and `RelationshipMemoryReviewCase`;
- the widening of `ReviewRepository.cases` to a three-variant union, and the
  `relationship_memory` branch of the review-case payload.

`review.list` and `review.decide` consequently answer today exactly as they did
before this branch, and for two independent reasons. In a build that composed
the plane, the memory query returns nothing and the decide router's memory
branch never matches, because no producer has written a proposal. In a build
that did not compose it, the query is not issued and the branch is not consulted
at all — the unit of work is constructed with the plane off, so `review.list`
cannot disclose a subject or a proposed kind from a plane the operator never
enabled. This is stated rather than implied because
`AGENTS.md` section 2 requires it: code that runs in no composed build is code a
reader would otherwise take for a working feature, and this specification is the
executable-truth record.

**What a producer would have to be.** Something that writes a row into
`relationship_memory_proposals` with a subject Entity this Principal owns, a
`proposed_kind`, the candidate statement and its digest, a `method` and
`method_version` (and, for `local_model`, a `model_id` and `model_version`), a
classification that meets the kind's floor, and a `review_case_id` — plus, for
anything that claims a source, one `relationship_memory_proposal_evidence` row
per record it rests on. The obvious candidate is a deterministic reader over
Quick Capture text or over extracted knowledge, and it is out of scope: it needs
its own capability, its own grant boundary, its own precision evidence and its
own decision about which statements are worth proposing at all. None of that is
in this objective.

**Why it exists now rather than later.** The contract this plane implements
requires that a model or rule can never create active memory — `RM-AC-005`,
`RM-P-AC-008`, `RM-API-AC-012` — and "never" is a claim about the *only* route
that exists, not about a route nobody has built yet. Deferring the promotion
semantics would leave the authority vocabulary, the separate proposal table, the
`review_promotion` actor class and the evidence-copy rule as prose, and the
first producer admitted would be the change that both invented a route and
decided its epistemics, under the pressure of shipping the producer. Building
the destination first is what makes admitting a producer a bounded change: it
writes proposal rows and nothing else, and every question about what a promoted
statement may claim is already answered and already tested. That is also the
form the refusal takes today — `MemoryAuthority` has no `model_inference`
member, so there is no value a producer could write even if one existed.
