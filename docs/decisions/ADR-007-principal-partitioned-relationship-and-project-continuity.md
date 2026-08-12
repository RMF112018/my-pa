# ADR-007: Principal-Partitioned Relationship and Project Continuity

- **Status:** Accepted
- **Decision ID:** `PKL-MYPA-D-WP06-001`
- **Repository:** `RMF112018/my-pa`
- **Scope:** Relationship/project continuity plane ownership and authorization —
  the pre-existing relationship-identity substrate plus the new Situation,
  Frame, Trace, Project, RelationshipEvent, and PulseItem surfaces. No
  production deployment, live Entra credential, or live personal-data authority.

## Context

WP-06 (R5) builds the relationship and project continuity surface: Person and
Organization identity, time/context-aware Relationships, Interactions and
Meetings, reciprocal commitments, private observations, Project and Relationship
workspaces and timelines, briefing, Situations/Frame/Trace, and the Today/Pulse
attention gate — all partitioned per Principal (WORK-PACKAGE-MAP WP-06).

Two things were unaligned with the campaign-wide `principal_id` invariant when
WP-06 opened:

1. **The relationship-identity substrate predates the partition.** The
   relationship people, organizations, identity observations, unresolved
   mentions, duplicate sets and members, identity review cases and decisions,
   resolutions, resolution observations, observation links, aliases,
   affiliations, evidence, evidence observations, and conversation participants
   and observations were created at Alembic revision `7f2a9d6c4e18`, before
   `principal_id` was a campaign-wide invariant. They keyed records by their own
   lineage; nothing on the relationship plane consulted a Principal. A person
   record, an affiliation, or an evidence row was therefore legible without a
   principal predicate — the same gap ADR-005 (capture) and ADR-006 (review)
   closed on their planes.

2. **The continuity surface did not exist yet.** Situations, Frames, Traces,
   Projects, and the Pulse/Today attention items had view-tier contracts but no
   canonical persistence and no principal-scoped read/write path.

ADR-006 (`PKL-MYPA-D-WP05-001`, merged as `a2f5345`) made review and promotion
principal-partitioned and established that a proposal becomes a canonical
reviewed assertion only through an explicit human disposition. WP-06 depends on
those accepted records as the only thing a continuity timeline or a Pulse item
may present as fact, and on the WP-01 identity foundation and WP-02 destinations.

The ratified Moss canonical product package v4.0
(`MYPA-MOSS-CANONICAL-PRODUCT-PACKAGE-20260805-008`) makes R5 the active work
package. Its acceptance criteria require relationship records and timelines to
be Principal-scoped end to end, Today/Pulse to read only accepted records, and
cross-Principal relationship negative tests to pass; its stop condition is any
shared identity record legible across Principals.

## Decision

1. **The relationship-identity substrate is retroactively partitioned.** Alembic
   revision `c1f2d3e4a5b6` (down-revision `b9a4ecdfac0b`) adds a mandatory
   `principal_id` to every table created by `7f2a9d6c4e18` that lacked one, with
   the canonical opaque-identifier `CHECK` constraint
   (`principal_id ~ '^prn_[A-Za-z0-9]{8,64}$'`, named
   `principal_id_is_an_opaque_identifier`) and a principal-first index; the one
   table that already carried the column receives the matching index. All
   seventeen tables of the substrate now carry the partition key, so no person,
   affiliation, or evidence row can be read — or joined — across Principals. The
   pre-campaign revision `7f2a9d6c4e18` is frozen in place; the column arrives
   only at `c1f2d3e4a5b6`, because a merged migration must never change what it
   emits (campaign D-48).

2. **The continuity surface is created principal-partitioned from birth.**
   Alembic revision `d2e3f4a5b6c7` (down-revision `c1f2d3e4a5b6`) creates
   `situations`, `frames`, `traces`, `projects`, `project_situations`,
   `relationship_events`, and `pulse_items`. Every table carries `principal_id`
   with the same `CHECK` and a principal-first index. A Situation references
   objects it does not own (its `object_refs` are opaque references, not foreign
   keys that would confer authority); a Frame belongs to a Situation; a Trace is
   a derived reconstruction, not source evidence; a Project links to Situations
   through `project_situations` with a single-link uniqueness constraint.

3. **Today/Pulse reads only accepted records, enforced in the schema.**
   `pulse_items.accepted_only` carries a `CHECK (accepted_only IS TRUE)`
   constraint named `pulse_reads_only_accepted_records`, so the database itself
   refuses a Pulse row that would surface a non-accepted interpretation. On the
   relationship timeline, `relationship_events.accepted` is the visibility gate:
   `list_accepted_events` filters `accepted IS TRUE`, so a proposed event never
   appears as fact until a human disposition accepts it. This is the structural
   half of the WP-06 acceptance gate; the domain half is a `PulseItem`
   `__post_init__` that rejects `accepted_only` other than `True`.

4. **Reads and writes are principal-scoped, and a foreign record is
   nonexistent.** Every concrete repository in
   `infrastructure/persistence/situation_repository.py` filters every read by
   `principal_id` and stamps it on every insert; a cross-partition reference
   raises `UnknownScopeError`. A `list_situations`, `list_projects`, or
   `list_accepted_events` call can only ever return the caller's own records.
   Cross-Principal existence is never disclosed — a foreign id and an unknown id
   are indistinguishable.

5. **The web tier mirrors the partition.** `/api/situations` and
   `/api/projects` list only the caller's own records; `/api/relationships/:personId/timeline`
   returns the accepted-only slice of a person's events, and a person that does
   not resolve in the caller's partition is `not_found` — a foreign person and
   an unknown person are indistinguishable (MU-AC-05). The `/situations` page
   renders the Situation board and links into the relationship timeline; the
   `/relationships/[personId]` page `notFound()`s a foreign person. Records are
   principal-scoped synthetic fixtures until the Python continuity read models
   are wired; every response is labeled synthetic.

## Consequences

- All isolation proof runs on synthetic principals (`prn_aaaa0001…`,
  `prn_bbbb0002…`); no live personal data is involved.
  `tests/situation/test_cross_principal_situation_isolation.py` proves at the
  application tier that Principal B cannot see Principal A's situations,
  projects, relationship events, or pulse items;
  `tests/database/test_cross_principal_r5_isolation.py` proves the same with
  real row-level SQL; `tests/database/test_situation_schema_migration.py`
  confirms every new table carries `principal_id NOT NULL` and that
  `pulse_items` enforces the accepted-only gate in the schema.
- Because the relationship substrate is now fully partitioned, a person or
  affiliation can no longer be resolved across Principals even through a join —
  closing the WP-06 stop condition (shared identity records legible across
  Principals).
- The Pulse accepted-only invariant is defended in three places: the schema
  `CHECK`, the domain `__post_init__`, and the `generate_pulse` query filter
  (`accepted_only IS TRUE AND dismissed_at IS NULL`). A regression in any one
  is caught by the other two and by the tests.
- Response payloads on the continuity plane do not echo `principal_id`; the
  session (web) and the `PrincipalContext` (Python) are the only identity
  carriers.
- Live multi-principal identity — real Entra tokens resolving to distinct
  Principals at the gateway — remains gated on P00-OD-010 and is out of scope
  here; the partition it will flow into is now real on the continuity plane as
  well as the capture and review planes.

## Supersession

Supersedes the pre-campaign working default in which the relationship-identity
substrate stored lineage but no principal and no read path consulted one, and
in which the continuity surface had no canonical persistence. Superseded in turn
only by a later accepted ADR; wiring live Entra identity or the live continuity
read models to the runtime does not modify this ADR, it fulfills it.
