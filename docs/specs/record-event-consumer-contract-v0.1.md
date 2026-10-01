# Record Event consumer contract v0.1

- **Status:** **Implemented.** This file describes what the repository does for a
  consumer of `record_events.list`. It does not commission the feed: whether any
  persistent database carries it, and whether any client holds its grant, are
  runtime facts no repository evidence establishes (see
  [`../operations/mcv-limitations.md`](../operations/mcv-limitations.md), section 15).
- **Request:** `MYPA-RECORD-EVENT-CONSUMER-READINESS-20261001-001` (RECR-1, RECR-2,
  RECR-3), under the approved RECR plan (SHA-256
  `e1a545c4a7977b29c80d719c0257ad3e5465cec039ff5d5a0d0ee3a2b0bb9d04`, Drive
  `1QfApsSyALgwSgNjvW2ClISNsGyIDzgzu`) and the Manager rulings recorded in
  [`../../.ai/goals/record-event-consumer-readiness/goal.md`](../../.ai/goals/record-event-consumer-readiness/goal.md).
- **Repository basis:** `RMF112018/my-pa`, branched from `origin/main`
  `174876621c880312ee3f4e32f649520fab04aa9d` (PR #297, the Record Event feed).
- **Scope:** how a consumer resolves an event to its record, how it initializes
  without a gap, and how it recovers. Not in scope: the causal-provenance chain
  of a future external write (a separate design record), any writeback plane,
  and any consumer implementation.

## 1. What the feed is

`record_events.list` is an **invalidation feed**. Each event says *that* one
canonical record changed -- its family, its id, its new version, the kind of
change, the changed field names and the operation -- and never what it changed
to. A consumer rereads the record through the existing read for its family.
The feed is metadata only, narrowed to the caller's own grants, ordered by an
internal per-Principal sequence that never leaves the server, and paged by an
opaque cursor bound to the request.

The public item is `RecordEventItemView` in
`src/my_pa/contracts/v1/record_events.py`; the page and its high watermark come
from one SQL statement in
`src/my_pa/infrastructure/persistence/record_events.py` (`SqlRecordEventReader.page`).

## 2. Resolving an event (RECR-1)

**Every listed event is resolvable from the event alone, under the caller's
normal grants.** For most families `record_id` is itself the key of a read. For
the families whose `record_id` is a child row that no read accepts as a key, the
item also carries a **routing reference**:

- `routing_family` -- the kind of record to reread through: `task`, `project` or
  `entity`;
- `routing_record_id` -- that record's opaque id.

Both are metadata: an identifier, never a value, a name or narrative. They exist
only on an item the caller already sees, so they inherit the event's grant
intersection and remote withholding exactly. The table that decides which
families carry routing is `RECORD_EVENT_ROUTING` in
`src/my_pa/domain/record_events.py`.

### 2.1 Routing guide

| Family | Reread with | Read |
|---|---|---|
| `task` | `record_id` | `tasks.read(task_id)` |
| `commitment` | `record_id` | `commitments.read(commitment_id)` |
| `project` | `record_id` | `continuity.projects.read(project_id)` |
| `entity` | `record_id` | `entities.get(entity_id)` |
| `relationship_memory` | `record_id` | `relationship_memory.get(memory_id)` |
| `constraint` | `record_id` | `constraints.read(constraint_id)` |
| `project_controls_settings` | `record_id` (the Project) | `project_controls.status(project_id)` |
| `meeting` | `record_id` | `meetings.read(meeting_id)` |
| `meeting_series` | `record_id` | `meetings.list(meeting_series_id)` |
| `capture` | `record_id` | `capture.read(capture_id)` |
| `task_comment` | `routing_record_id` (Task) | `tasks.comments.list(task_id)` |
| `constraint_category` | `routing_record_id` (Project) | `constraint_categories.list(project_id)` |
| `entity_identifier` | `routing_record_id` (Entity) | `entities.identifiers.list(entity_id)` |
| `entity_alias` | `routing_record_id` (Entity) | `entities.aliases.list(entity_id)` |
| `entity_assignment` | `routing_record_id` (Entity) | `entities.assignments.list(entity_id, active_only=false)` |
| `entity_relationship` | `routing_record_id` (the `from` Entity) | `entities.relationships(entity_id, direction="outgoing")` |
| `entity_observation` | `routing_record_id` (Entity), when resolved | `entities.observations.list(entity_id)`; unresolved: residual R-2 |
| `entity_name` | `routing_record_id` (Entity) | `entities.names.list(entity_id)` or `entities.profile` |
| `entity_address` | `routing_record_id` (Entity) | `entities.addresses.list(entity_id)` or `entities.profile` |
| `entity_communication_method` | `routing_record_id` (Entity) | `entities.communication.list(entity_id)` or `entities.profile` |
| `entity_project_participation` | `routing_record_id` (the participant Entity) | `entities.participations.list(entity_id, perspective="participant")` |
| `person_organization_affiliation` | `routing_record_id` (the **person** Entity) | `entities.profile(entity_id)`, its person-side collection; bounded, residual R-1 |

The read returns the record whose id equals `record_id`, or shows that it is no
longer current. Proved per family, through the production writers and these
exact reads, by
`tests/database/test_record_event_routing.py::test_every_family_resolves_from_the_event_alone`.

### 2.2 Routing names the current owner

The server computes `routing_record_id` **at list time**, inside the same
statement that reads the page and the watermark, from the child row's owner
column. It is never stored on the event. Two consequences a consumer relies on:

- It names the record's **current** owner, which is what "reread the current
  canonical record" needs. After an Entity merge reparents a child, the routing
  of that child's earlier events names the survivor
  (`tests/database/test_record_event_routing.py::test_routing_follows_a_merge_to_the_survivor`).
- The routing of one event can therefore differ between two reads of the feed.
  That is correct for an invalidation feed: routing says where to reread *now*.
  Events written before the routing reference existed are covered too, because
  nothing is backfilled.

### 2.3 Null routing

On a routed family, `routing_family` and `routing_record_id` are both `null`
when the record has no current owner -- an observation that resolved to no
Entity, or a child row that is gone. The contract is: **null routing means "not
currently resolvable"; treat the event as a tombstone** for the record it names
until a later event says otherwise. The item validator admits exactly "both set
or both null" (`tests/contract/test_record_events_list.py::test_routing_fields_are_validated`),
and the orphaned observation is proved by
`tests/database/test_record_event_routing.py::test_an_orphaned_observation_lists_with_null_routing`.

## 3. Bootstrap without a gap (RECR-2)

A new consumer initializes in four steps. **No synthetic historical event is
ever produced**: a record never mutated since the feed existed has no event, and
the snapshot is its only source.

1. **W0.** Call `record_events.list` once with no cursor, using the **same page
   size and the same family narrowing** the consumer will consume with. Keep
   `high_watermark_cursor` as W0 and discard the returned events. The cursor
   binding includes the page size and the requested families, so a W0 taken
   under different ones is `conflict(cursor)` on resume.
2. **Snapshot.** Enumerate the eligible current records through the existing
   reads (section 3.1). Each read may run in its own transaction.
3. **Process.** Apply the snapshot idempotently: upsert keyed by
   `(family, record_id)`.
4. **Delta.** Consume `record_events.list` from W0 until `next_cursor` is null,
   then keep polling from the latest cursor. For each event, reread the record
   through section 2.1 and upsert. **Downstream must stay idempotent**:
   re-applying a record already seen is harmless and expected. Skipping on
   `record_version <= held` is only an optimisation, valid where the read
   exposes the event's version, and never for `entity_observation`, whose feed
   version is not a dedup key.

**Why there is no gap.** Per Principal, sequence order is commit order: the
allocator is one row lock held to COMMIT, so no transaction can commit an event
below one that is still uncommitted. Every write committed before W0's snapshot
has a sequence at or below W0, and the snapshot reads, which run after W0, see
at least that state. Every write committed after it has a sequence above W0, so
the delta delivers it. A write committed between W0 and a snapshot read is seen
twice, which idempotency absorbs. Proved by
`tests/database/test_record_events_consumer_bootstrap.py` (a write in flight at
W0, one committed between W0 and the snapshot, one committed during snapshot
enumeration), on top of the single-snapshot page and watermark of
`tests/database/test_record_events_bootstrap_race.py::test_page_and_watermark_share_one_snapshot`.

### 3.1 Snapshot enumeration

- Direct enumerations: `tasks.list`, `commitments.list`, `continuity.projects`,
  `capture.list`, `meetings.list` (meetings and their series), and
  `entities.observations.list` with no `entity_id`.
- Per Project: `constraints.list`, `constraint_categories.list`,
  `project_controls.status`.
- Per Task: `tasks.comments.list`.
- Per Entity: the Entity sub-family reads and `relationship_memory.list`.

**The Entity plane is reference-driven.** No read enumerates every Entity:
`entities.search` refuses a blank query. Entity bootstrap therefore traverses the
references reachable from the enumerable roots -- projects, tasks, commitments,
constraints, meetings, memories and captures -- and then reads each Entity found
and its sub-families. **Coverage limit:** an Entity that no enumerable root
references, and that has not changed since the feed existed, is not reached by
the bootstrap. Once it changes, its event reaches the consumer like any other.
A complete Entity enumeration needs a new read (section 6).

## 4. Recovery (RECR-3)

A resume token is decoded in a fixed order: its shape, then its binding to this
request, then its anchor event. The anchor must be **an event this request's
page would show**: the caller's own, in the effective families, and -- for a
remote caller -- not withheld as restricted Relationship Memory or Capture. A
hidden anchor is `invalid_request(cursor)`, the same answer as an unknown one,
so it discloses nothing.

On resume, `invalid_request(cursor)` or `conflict(cursor)` means **re-bootstrap
from step 1**. The causes are:

- a change to the caller's grants or to the composed family set
  (`conflict(cursor)`);
- an anchor that became hidden (`invalid_request(cursor)`) -- for a remote
  caller this includes an anchor whose memory or capture's *current* version has
  since become `restricted_local`, even though the token was legitimately issued.

Proved by `tests/database/test_record_events_cursor_visibility.py` and
`tests/security/test_record_events_grant_narrowing.py::test_the_position_is_resolved_under_the_effective_families_and_disclosure`.

## 5. Residuals

- **R-1, affiliations past the profile bound.** Affiliations route to the
  **person** end. Their only read is `entities.profile`, which carries at most 25
  affiliations per collection and issues no cursor, so for a person with more
  than 25 affiliations, the ones past the 25th cannot be reached by any read.
- **R-2, orphaned observations.** An observation with no Entity has null routing
  (section 2.3). It is reachable only through the unkeyed
  `entities.observations.list` scan with `unresolved_only=true`.
- **R-G, the consumer's grants.** A family is visible to a remote caller when
  any one of its mapped reads is granted, but some of those reads cannot take the
  routing key: list reads with no id filter (`tasks.list`, `commitments.list`,
  `continuity.projects`, `capture.list`, `constraints.list`),
  `relationship_memory.list` (keyed by Entity), `meetings.read` for a series, and
  `entities.profile` alone (bounded). **Requirement:** a consumer must hold, for
  each family it consumes, the read named in section 2.1. A grant set that makes
  a family visible only through another read leaves its events visible but not
  directly rereadable.

## 6. Follow-up candidates (not implemented)

- **A paginated affiliation read capability**, which would cure R-1.
- **An entity enumeration read**, which would let the Entity plane bootstrap
  beyond the references reachable from the enumerable roots.

Each would be a new capability with its own purpose, profile and audit
consequences, and needs separate authorization.
