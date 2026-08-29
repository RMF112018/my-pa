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

Nine `relationship_memory.` names:

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
| `relationship_memory.propose` | `relationship_memory_proposal` | records a candidate for governed review; never creates active memory |

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
  every query has to remember. `relationship_memory.propose` writes the first
  two, and `review.decide` appends the decision and promotes an accepted proposal
  in the same transaction.

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

A direct write against an Entity already in `merged_redirect` state is refused
and the canonical target is returned. Governed identity correction is the only
redistribution path: merge reparents memory subjects, proposal subjects and
proposal/canonical Entity context links to the survivor while retaining immutable
origin bindings in both canonical rows and the effect ledger. Split consumes
that ledger to restore the historical bindings. Neither direction erases a
memory or a memory version, and the aggregate concurrency token advances on
both merge and split rather than returning to an earlier value.

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

A build without the plane withholds all nine `relationship_memory.` names from `capabilities.get` and
from the MCP tool list, and every handler refuses `unsupported` as a floor under
that — the HTTP transport routes by path segment and consults neither list.

Remote MCP additionally withholds the five write-capable names until remote
writes are enabled, because both Relationship Memory authoring and proposal
purposes are write purposes.

## 10. Deferred, and named rather than implied

- retention and hard deletion (ADR-003 leaves it unresolved);
- multi-user or delegated visibility;
- reminder or attention rules over `important_date`;
- any widening of cloud eligibility;
- the frontend experience, which `MYPA-RM-04` describes and which this
  implementation does not build.

## 11. Governed proposal and promotion path

`relationship_memory.propose` is the production producer. It validates a
Principal-owned subject and evidence, resolves immutable rule/model provenance
from the authenticated Principal's registration, and writes a candidate plus
its evidence without writing active memory. Equivalent open candidates dedupe
to the existing proposal, and the response deliberately excludes statement
text.

The proposal's `review_case_id` puts it on the composed `review.list` surface.
`review.decide` routes the case to
`infrastructure/persistence/relationship_memory_review.py`; acceptance creates
the canonical memory, version, context and evidence rows and appends the review
decision atomically. The non-accepting dispositions — reject, defer,
mark-unresolved, reprocess, escalate and invalidate — do not create active
memory. Corrected acceptance follows the acceptance path. When the plane is not
composed, neither listing nor decision routing probes its rows, preserving the
same not-found behavior as an unknown case.

The epistemic boundary remains structural: a rule or local model can propose,
but cannot create active memory directly. Promotion uses the closed accepted
authority vocabulary and the `review_promotion` actor class, copies exact
evidence, and records the review case that admitted the version.
