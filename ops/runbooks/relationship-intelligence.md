# Relationship Intelligence — operator runbook

Related: [`docs/plans/relationship-intelligence-implementation-plan.md`](../../docs/plans/relationship-intelligence-implementation-plan.md),
[`docs/specs/relationship-intelligence-v0.2.md`](../../docs/specs/relationship-intelligence-v0.2.md).

## 1. Current identity

| Item | Value |
| --- | --- |
| Plane status | Implemented, **off by default** |
| Process gate | `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED`, default `false` |
| Capabilities | `entities.search`, `entities.get`, `entities.resolve`, `entities.context`, `entities.relationships` |
| Purpose | `entity_read` — one, read-only |
| Write capabilities | **None.** Observation, proposal and merge are in-process only |
| Tables | `entities`, `entity_aliases`, `entity_external_identifiers`, `entity_assignments`, `entity_relationships`, `entity_observations`, `entity_proposals`, `entity_merge_records` |
| Revisions | `9def3c2e63bb` (entity tables), `b7f4d1a92c36` (aliases), `c1a7e4b93d58` (capabilities and purpose), `e4d7b2f9a316` (governance tables) |
| Calibration | [`tests/evaluation/RESOLUTION_CALIBRATION.md`](../../tests/evaluation/RESOLUTION_CALIBRATION.md) |
| Frontend | Not implemented. Held by the operator's `D-09` instruction |

## 2. Turning the plane on

`MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED=true` makes the entity capabilities
available to the process. **It is one decision with two consequences**, and both
should be intended before it is set:

1. the local MCP `tools/list` and `capabilities.get` begin publishing them;
2. `adapters/mcp/remote.py` derives the remote profile from the capability set
   with no per-capability exclusion list, so if `MY_PA_REMOTE_MCP_ENABLED` is
   also true they become reachable remotely — as **reads**, so
   `MY_PA_REMOTE_WRITES_ENABLED` does not gate them.

To serve the plane locally and *not* remotely, leave `MY_PA_REMOTE_MCP_ENABLED`
off, or grant no `remote_capability_grants` row for the `entities.` names: in
production a remote client reaches a capability only if an operator inserted a
grant for it.

Turning it off again withholds all six immediately. It deletes nothing.

## 3. Inspecting the plane

```sh
MY_PA_DATABASE_URL=... PGPASSWORD=... \
    .venv/bin/python scripts/inspect_entity_plane.py --principal prn_...
```

Read-only, and prints no personal data — counts, closed-set status names, and
opaque identifiers only. `--principal` is required: the plane is partitioned and
a report across all Principals would be the cross-Principal read the partition
exists to prevent.

**`entities.unresolved_mentions` reads the queue over a transport.** Added
2026-08-20 for the frontend package's People landing, which lists unresolved
identity ambiguities as a section: until then the queue existed in
`EntityGovernanceService`, which nothing composes, so it was reachable only by
this script. It returns the *normalized* value — the form resolution compares —
and never `observed_value`, the raw text lifted out of a source. The card omits
both because a card summarises an entity already identified; a queue of things
nobody could place is useless without the thing that could not be placed.

It remains a **read**. Nothing on this plane links a mention to an entity, so
this capability shows the queue and cannot work it. That is section 4's gap,
unchanged.

Read `unresolved_mentions` and `open_proposals` first. The first is references
the system knows it has not placed; the second is decisions waiting on a person
— and, in this build, waiting indefinitely (section 4).

The report names proposals by identifier and kind and prints no `proposed_by`:
that column is free text a caller supplies, and one free-text column would end
the guarantee that this report carries no personal data.

## 4. Deciding a proposal — **not yet operable**

Read this section as a description of the rules, not as a procedure. There is
**no way to decide a proposal in this build.**

- There is no capability for it, deliberately (`D-RI-21`): observe, propose,
  decide and merge exist on no transport, local or remote.
- There is also no operator entry point. `EntityGovernanceService` and
  `EntityReenrichmentService` are composed by **nothing** in `src/` — no
  bootstrap wiring, no script, no worker. They are in-process contracts with a
  test suite and no caller.

So the queue `scripts/inspect_entity_plane.py` reports can be *read* and cannot
be *worked*. An operator who needs a proposal decided today has no supported
action; wiring one is its own work package, with its own authorization gate.

The rules those services encode, for when there is:

- `RECORD_ALIAS`, `RECORD_ASSIGNMENT`, `RECORD_RELATIONSHIP` — may be accepted
  under a configured threshold.
- `CREATE_ENTITY`, `BIND_IDENTIFIER` — require review.
- `MERGE_ENTITIES` — **requires the operator**, and is never eligible for a bulk
  action (specification section 8.4).

Accepting a merge redirects the merged-away entity at the survivor and writes an
`entity_merge_records` row naming the actor, reason and moment. It deletes
nothing: the merged entity still resolves as a `HISTORICAL_MATCH`. The merge
record is also a precondition rather than a formality — `after_merge` refuses to
move any observation between two entities no recorded merge connects, in that
direction, in that Principal's partition. A pass is repeated until
`more_remains` is false.

## 5. Reading a resolution answer

`entities.resolve` returns an `outcome`, and **the outcome is read before the
entity_id**, which is `null` for everything that is not a match:

| outcome | meaning | what to do |
| --- | --- | --- |
| `resolved_exact` | one entity, matched on an identifier or an alias | act on it |
| `resolved_contextual` | one entity, selected by a scope you supplied | act on it, knowing the scope decided it |
| `ambiguous` | candidates found, none chosen | narrow with `scope_entity_id`, `entity_type`, or an identifier |
| `conflicted_identifier` | one identifier is claimed by more than one entity | a data defect; fix the records, do not choose |
| `historical_match` | found, but merged away or not current | follow `superseded_by_entity_id` |
| `not_found` | nothing matched | not an error |

A bare name never yields `resolved_exact`. One entity carrying a name is still
not evidence that a reference means that entity, and `ambiguous` with a single
candidate is the honest answer.

## 6. What this plane will not do

- merge identities without an operator (sections 8.4, 21.4; `RI-AC-039`);
- resolve an ambiguous reference to the nearest candidate (section 15.2);
- store or display a score, rating, confidence or any composite judgement about
  a person (section 16.2; `RI-AC-049`), enforced by
  `tests/architecture/test_relationship_scoring_surface_is_denied.py`;
- reach another Principal's records under any capability;
- read a source. Nothing here traverses personal data — observations are written
  by callers, and no connector writes them yet.

## 7. Known gaps

- **No frontend.** Held by `D-09`. Every user-facing acceptance criterion is
  unmet for that reason and is ledgered as such.
- **No split.** Section 15.4's split requirements are not implemented; only
  merge is.
- **Seven of nine re-enrichment triggers** (section 27.4) are unimplemented,
  because they need observations from sources this product does not read yet.
- **No operator entry point for governance.** See section 4: the review plane is
  implemented and composed by nothing. Reading the queue works; working it does
  not.
- **`Entity.canonical_name` normalization is unenforced** at the schema level.
  The domain record now refuses an unnormalized `canonical_name`, alias value or
  identifier value at construction, so nothing routed through `Entity`,
  `EntityAlias` or `ExternalIdentifier` can store one — but a migration, a
  backfill or a direct `INSERT` still can, and such a row is unresolvable or,
  worse, resolves as a neighbouring entity.
- **`record_assignment` and `record_relationship` have no natural key**, so a
  retry that mints a fresh identifier writes a second row.
