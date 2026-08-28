# Relationship Intelligence — operator runbook

Related: [`docs/plans/relationship-intelligence-implementation-plan.md`](../../docs/plans/relationship-intelligence-implementation-plan.md),
[`docs/specs/relationship-intelligence-v0.2.md`](../../docs/specs/relationship-intelligence-v0.2.md).

## 1. Current identity

| Item | Value |
| --- | --- |
| Plane status | Implemented, **off by default** |
| Process gate | `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED`, default `false` |
| Read capabilities | Eleven. The prior ten plus `entities.identity_history`, a Principal-scoped, keyset-paginated view of the authoritative identity-operation/effect ledger |
| Write capabilities | Twenty-three. The prior twenty-one plus `entities.split.preview` and `entities.split`. Merge and split preview/apply are operator-only, identity-correction-gated writes; a preview persists a bounded control record and is therefore not classified as a read |
| Write gate | `MY_PA_RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED`, default `false`, and it requires the plane gate above. A process that sets it `true` while `MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED` is `false` refuses to start rather than serving a half-configured plane |
| Identity-correction gate | `MY_PA_RELATIONSHIP_IDENTITY_CORRECTION_ENABLED`, default `false`, and it requires the **write** gate above rather than the plane gate. It withholds merge and split preview/apply and nothing else. All four are also operator-only, so the flag is independent of the Principal/remote-profile gate |
| Purposes | Five. `entity_read` covers all eleven reads; `entity_observation_ingest` covers `entities.observe`; `entity_authoring` covers the seventeen Phase A writes; `entity_proposal` covers the producer path; and `entity_identity_correction` covers merge and split preview/apply. Preview and apply intentionally share the correction purpose without collapsing their two-gate protocol |
| Tables | `entities`, `entity_aliases`, `entity_external_identifiers`, `entity_assignments`, `entity_relationships`, `entity_observations`, `entity_proposals`, `entity_merge_records`, `entity_mutation_events`, `entity_fact_evidence_links`, `entity_resolution_decisions`, and Phase B's seven: `entity_proposal_evidence_links`, `entity_proposal_review_decisions`, `entity_identity_previews`, `entity_identity_operations`, the append-only `entity_identity_effects`, `relationship_write_requests`, and its append-only child `relationship_write_request_evidence` |
| Final-completion revision | `8e1c4a7b2d90`, additive on `3d07af4dc513`; it adds the recovery/origin/re-enrichment state and widens frozen audit vocabulary for identity history and split without deriving a historical constraint from the current enum |
| Calibration | [`tests/evaluation/RESOLUTION_CALIBRATION.md`](../../tests/evaluation/RESOLUTION_CALIBRATION.md) |
| Frontend | Not implemented. Held by the operator's `D-09` instruction |

## 2. Turning the plane on

`MY_PA_RELATIONSHIP_INTELLIGENCE_ENABLED=true` makes the entity plane's eleven
reads available to the process, and nothing else: the twenty-three writes need
`MY_PA_RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED` beside it. **The read switch is
one decision with two consequences**, and both should be intended before it is
set:

1. the local MCP `tools/list` and `capabilities.get` begin publishing them;
2. `adapters/mcp/remote.py` derives the ordinary remote profile from the
   capability set. If `MY_PA_REMOTE_MCP_ENABLED` is also true, the reads are
   remotely reachable as reads and `MY_PA_REMOTE_WRITES_ENABLED` does not gate
   them; every write is classified as a write and requires that remote-write
   switch. The four identity-correction writes require more: the server-resolved
   durable capability set must exactly equal the frozen `remote.operator`
   profile. A raw allowlist, subset, superset, reviewer profile, or writes-enabled
   setting alone cannot publish them.

To serve the plane locally and *not* remotely, leave `MY_PA_REMOTE_MCP_ENABLED`
off, or grant no `remote_capability_grants` row for the `entities.` names: in
production a remote client reaches a capability only if an operator inserted a
grant for it.

Turning it off again withholds every `entities.` name immediately, reads and
writes alike. It deletes nothing, and it does not undo a write already made.

**The write half is gated once more, locally as well as remotely.**
`MY_PA_RELATIONSHIP_INTELLIGENCE_WRITES_ENABLED` is a second switch and defaults
to `false`, so a process that enables the plane serves the eleven reads and refuses
every write with `unsupported` until it is set. It is refused on every
transport rather than only where a tool list is published: the writes are
subtracted from `ApplicationService.available_capabilities`, which is what
`capabilities.get` and the MCP tool list read, *and* each write handler asks the
gate again before it does anything, because the HTTP transport routes by path
segment straight into `_HANDLERS` and consults neither. Setting it `true` on a
process that has not enabled the plane is a startup failure rather than a
silently ignored variable.

**Governed merge and split are gated once more, and are operator-only besides.**
`MY_PA_RELATIONSHIP_IDENTITY_CORRECTION_ENABLED` is a third switch, defaults to
`false`, and requires the *write* switch rather than the plane switch — so a
process cannot serve an identity correction while refusing an ordinary entity write, and setting
it without the switch below it is a startup failure. With it off,
`entities.merge.preview`, `entities.merge`, `entities.split.preview`, and
`entities.split` are subtracted from
`available_capabilities` and each handler asks the gate again, for the reason the
write half does: the HTTP transport routes by path segment and reads no manifest.

With it on they are still refused to anything but an authenticated operator.
Both are in `_OPERATOR_ONLY`, which is the first time that set has held a
knowledge-plane name: the test it applies is whether a capability *widens the
scope a later request is evaluated against*. Merge rewrites the canonical reach
of its affected records; split restores the exact inverse of one completed merge.
After a merge every alias,
identifier, assignment, edge, observation, proposal, review case and memory that
named a merged-away entity is reached through the survivor. The ordinary remote
profile still drops both names. They join the remote surface only when global
remote writes are enabled and the server-resolved durable capability set exactly
matches `remote.operator`; the normal allowed-capability intersection, exact
capability/purpose grant, feature gates, Principal check, and application policy
then still apply. No configured profile or grant is created by this code, and all
remote and identity-correction switches remain off by default. The exact
`remote.operator` profile retains its historical name and expands additively;
ordinary local/remote standard, producer, and reviewer profiles do not inherit
identity-correction authority.

**The preview is a write and is gated as one.** It mutates no canonical record
and it does persist a bounded control row carrying a digest, an expiry and a
consumption state, so `entities.merge` can be bound to exactly the world an
operator was shown. Describing it as a read would be an annotation contradicting
the transaction.

Remotely a write is gated twice more. A remote client reaches one only with
`MY_PA_REMOTE_WRITES_ENABLED` *and* a `remote_capability_grants` row:
`adapters/mcp/remote.py` classifies a capability as a write by intersecting its
permitted purposes with `_WRITE_PURPOSES`, and both `entity_authoring` and
`entity_observation_ingest` are in that set. The reads stay reachable with the
write switch off, which is the correct classification and the property
`tests/contract/test_entity_remote_exposure.py` holds in both directions. For
merge or split preview/apply, the complete durable capability set must additionally be
the exact frozen `remote.operator` set; the purpose grant remains independently
required at invocation.

## 2a. What the writes do, and what they refuse

**The identity half** — `create`, `update`, `archive`, `restore`, and the
`identifiers.*` and `aliases.*` transitions — changes what an entity is, which
external addresses resolve to it, and what it may be called.

**The directed half** — assignments and typed edges — takes the same three acts
on each family: `create`, `revise`, `end`.

**The observation half** — `observe` and `unresolved_mentions.resolve` — records
what a source said and decides what one mention refers to. `observe` creates no
entity: section 12.2 is explicit that a source record does not become the
canonical person by itself.

**Nothing is deleted and nothing that carries meaning is edited in place.** An
assignment's subject, type and scope, and an edge's source, type, target and
scope, are the record's identity. A `revise` cannot reach them — the command has
no field for one — so correcting a record recorded against the wrong scope is
`end` followed by a fresh `create`, which is the only shape that records both
what was believed and what replaced it. An `end` keeps the row, stamps
`ended_at`, and requires a bounded reason.

**Direction is first class and no reciprocal edge is ever generated.**
`works_for` does not imply `manages`. If the inverse is also true it is asserted
as its own edge, so it can be withdrawn on its own terms later.

**Every write is guarded by a version and a key.** The record's own
`expected_version`; the `expected_entity_version` of each endpoint a create binds
to; and an idempotency key. An exact retry returns the original receipt and
writes nothing; the same key carrying a different request is refused as a
conflict rather than admitted as a second write.

**A duplicate is refused by the database, not by a convention.** Partial unique
indexes over the *active* row decide it: assignments on
`(principal, entity, type, scope, role, discipline, responsibility class)` with
the three free-text fields folded case- and whitespace-insensitively, edges on
`(principal, from, type, to, scope)`, and the identifier and alias families on
their own active keys. Ending a record frees its key for a replacement, which is
what makes end-and-replace work.

**Each of the eighteen Phase A canonical entity writes appends one row to
`entity_mutation_events`, and that row is what the caller is handed back.** It carries the capability, the record and its
family, the prior and new version, the before and after state, the authority, the
actor class, the request digest, the idempotency key and the audit identifier.
The table is append-only by trigger, and
`UNIQUE (principal_id, capability, idempotency_key)` is the idempotency store.

**`receipt_id` is null in the ledger, and the `receipt_id` a result returns is
that row's own `emut_…`.** The two are one decision made once for those eighteen
Phase A writes. The column exists to point at a separate receipt record and this build
keeps none, so filling it with the row's own primary key would be a
self-reference dressed as a reference and would make `receipt_id IS NOT NULL`
mean nothing to anyone reading the ledger. What the completion contract requires
is that a mutation *result* carry a `receipt_id`; it does, and it names a
durable row an operator can go and read.

The three Phase B entity writes use their dedicated governed ledgers rather
than `entity_mutation_events`. `entities.proposals.create` persists the proposal
and its evidence and uses the Principal-and-capability-scoped
`relationship_write_requests` replay ledger. `entities.merge.preview` persists
the exact-version-bound plan in `entity_identity_previews`; `entities.merge`
records its operation and append-only effects in `entity_identity_operations`
and `entity_identity_effects`.

**Evidence is cited from two record families, and which one depends on the
write.** `entity_fact_evidence_links` admits an entity observation, a capture
span or a knowledge record, one per row. The four directed writes that carry
`evidence_refs` admit `eobs_…` only; the four identifier and alias writes that
carry `evidence` admit `span_…` only; no capability admits a knowledge record,
and `unresolved_mentions.resolve` cites nothing a caller names — its links are
minted server-side to record a refused pairing as counterevidence.

The split is by what the schema can prove rather than by preference. An
observation carries a composite `(observation_id, principal_id)` foreign key, so
a foreign one is refused by the database and nothing rests on an application
check. `capture_spans` carries no Principal column at all, so ownership there is
proven by an application join through `capture_versions` to
`captures.owner_principal_id`. Merging the two fields would either spread the
weaker proof across the whole plane or drop a citation form one capability
already accepts, so the difference is stated and bound instead:
`tests/contract/test_entity_evidence_scope.py` derives which kind each write
admits from the commands themselves, so a later widening reddens there.

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

**Corrected 2026-08-20: it returns neither value the source produced.** The
sentence above described the design before `f3a8c1d7e592` and is kept because
the reason it changed is worth an operator's time. The queue used to publish
`normalized_value`, on the argument that a matchable form is the same class of
datum as a canonical name. It is not: `normalize_name` casefolds and turns
punctuation into spaces and removes **no content**, so a writer deriving it from
raw text published that text with its dots turned into spaces — and the result
is `is_normalized_name`-true, so no check on this plane could have refused it.

The queue now reads `entity_observations.mention_display_name`, a separate
optional column, and `normalized_value` is internal to matching. **A writer that
fills nothing publishes nothing**: the mention is still queued with its source
pointers and carries no text. Disclosure is an affirmative write into a column
whose name says what it is for, so "did anyone mean to publish this?" is a
question with an answer, and an auditor greps one column's writers.

**This paragraph said the queue is empty on every build because nothing in
`src/` writes the table. That stopped being true with WP-RI-A-04.**
`entities.observe` is the first writer of `entity_observations` on any
transport, so the queue now fills from ordinary use rather than only from a
script, and an operator who expected it to be empty should expect rows.

**And the queue can now be worked.**
`entities.unresolved_mentions.resolve` decides one mention: `link_existing`
binds an entity the caller named, `create_new` creates one, and `reject`,
`defer` and `quarantine` record that the caller declined to. Every decision is
appended to `entity_resolution_decisions`, which is append-only by trigger, and
checked against the mention's own `resolution_version` — so two operators
working the queue at once produce one decision and one refusal rather than a
silent overwrite. `entities.observations.list` is the read that carries that
version, which the queue's own view does not.

**A `reject` that names `rejected_entity_id` has a durable effect.** The refused
pairing is written to `entity_fact_evidence_links` with role `counterevidence`,
and every later resolution of that mention withholds the refused entity from its
candidates. Nothing is deleted: the observation, its text and the decision all
remain, which is what section 10.11 requires and what makes the refusal
auditable.

Read `unresolved_mentions` and `open_proposals` first. The first is references
the system knows it has not placed; the second is decisions waiting on a person.
Canonical `review.list` is the transport entry point for Entity and Relationship
Memory cases; section 4 describes the supported dispositions.

The report names proposals by identifier and kind and prints no `proposed_by`:
that column is free text a caller supplies, and one free-text column would end
the guarantee that this report carries no personal data.

## 4. Deciding a proposal and applying a governed merge

Entity and Relationship Memory proposals appear on canonical `review.list` and
are decided through `review.decide`. Supported dispositions are `accept`,
`correct_and_accept`, `reject`, `defer`, `mark_unresolved`, `reprocess`,
`escalate`, and `invalidate`. Ordinary accepted Entity proposals promote through
the canonical Entity authoring services; typed corrections and evidence remain
attached. `reprocess` creates a successor, while `reject` and `invalidate`
create no canonical fact. The authenticated producer cannot decide its own
candidate merely because it produced it.

Accepting an identity-correction proposal does **not** merge identities. It
records the review decision only. The operator must separately call
`entities.merge.preview`, inspect the persisted bounded consequences, and pass
that exact unexpired preview and digest to `entities.merge`. Both capabilities
require the identity-correction feature gate, operator authority, exact versions,
the normal capability/purpose policy, and audit persistence. Remotely they also
require global remote writes and the exact server-resolved `remote.operator`
durable capability set described in section 2.

Apply is atomic, preserves merged-away rows as redirects, records lineage and an
append-only effect ledger, reconciles supported children and affected proposal
state, and hard-deletes nothing. A stale, expired, consumed with different
material, conflicted, or tampered preview is refused.

### 4a. Reading history and applying a governed split

`entities.identity_history` is an `entity_read` capability. It returns only the
authenticated Principal's identity operations and effects, ordered by the
repository's opaque keyset cursor. Callers pass the returned `next_cursor`
unchanged; a malformed cursor is an `invalid_request`, not a request to restart
from an inferred position.

A split is the exact inverse of one completed merge, not a general-purpose
identity editor. The operator supplies the source identity-operation identifier
to `entities.split.preview`, inspects the recorded inverse plan, then supplies
that preview's identifier and digest to `entities.split`. Apply checks the
source operation, exact versions, unexpired/unused preview, digest, Principal,
and effect-ledger integrity. It appends a new identity operation and effects; it
does not erase or edit the merge history. Concurrent, stale, tampered, or replayed
material fails closed. As with merge, accepting a review proposal never invokes
split automatically.

`capabilities.get` and MCP `tools/list` answer different questions and must not
be conflated. The former is the process capability manifest, including names
with an unavailable status and limitation. The latter is the effective tool
view after process composition and, remotely, caller/profile/grant filtering.
The generic HTTP and MCP paths still normalize into the same closed command
schemas and dispatch the same application handlers.

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
- **No live commissioning or canary has been performed.** Repository behavior is
  validated with synthetic fixtures and isolated test databases only. Sections
  8 and 9 are operator-gated procedures, not evidence that any flag, grant,
  OAuth configuration, runtime, connector, or personal-data path was activated.
- **`Entity.canonical_name` normalization is unenforced** at the schema level.
  The domain record now refuses an unnormalized `canonical_name`, alias value or
  identifier value at construction, so nothing routed through `Entity`,
  `EntityAlias` or `ExternalIdentifier` can store one — but a migration, a
  backfill or a direct `INSERT` still can, and such a row is unresolvable or,
  worse, resolves as a neighbouring entity.
- **`record_assignment` and `record_relationship` are refused rather than
  deduplicated on retry.** `2fe4e13fb449` gave each a natural key — a partial
  unique over the active row — so a retry that mints a fresh identifier no
  longer writes a second row; it raises. Neither repository write arbitrates
  that index the way `bind_identifier` and `record_alias` do, so the caller sees
  an integrity error rather than a quiet no-op. Closing that needs an
  idempotency key on the write path, which arrives with the work package that
  has something observed to write.
- **All three Phase A ledgers now have a writer, and only two of the three are
  append-only.** `WP-RI-A-02` made the governed writes the first writer of
  `entity_mutation_events` — one row per accepted change, and the same table is
  the plane's idempotency store through
  `UNIQUE (principal_id, capability, idempotency_key)` — and of
  `entity_fact_evidence_links`, which a write fills only when it cites evidence.
  `entities.unresolved_mentions.resolve` writes
  `entity_resolution_decisions`; Phase B's proposal decisions use their own
  canonical review ledgers rather than this mention-resolution ledger.
  `2fe4e13fb449` names exactly two tables in `_IMMUTABLE_TABLES` —
  `entity_mutation_events` and `entity_resolution_decisions` — and creates one
  `BEFORE UPDATE OR DELETE` trigger on each, so those are append-only at the
  server. `entity_fact_evidence_links` carries **no trigger at all**: what it
  has instead is six `CHECK` constraints, including the pair that make a row
  cite exactly one fact and exactly one record, and six composite foreign keys,
  every one of them `ON DELETE CASCADE`. So a link row can be updated, can be
  deleted, and *is* deleted when the fact or the observation it cites goes —
  which is the opposite of append-only, and is a property to know before this
  table is cited as an audit trail. Corrected 2026-08-23: this bullet said all
  three were append-only by trigger, and a live server shows zero triggers on
  the third.

## 8. WP-08 commissioning procedure — prepared, not executed

This is a fail-closed checklist for a later operator-authorized commissioning.
It grants no authority to perform the steps. Before execution, record the exact
release commit/tree and migration head, operator authorization, target runtime
identity, eligible synthetic or dedicated non-personal dataset, backup/restore
point, and the exact `relationship_standard`, `relationship_producer`,
`relationship_reviewer`, or `relationship_operator` role being commissioned.
Map that role to the local/remote code-level profile; do not edit a grant to
approximate a profile, and preserve the exact `remote.operator` compatibility
name for the remote operator role.

In an approved maintenance window, the operator's runtime owner must:

1. attest clean artifact and migration identity, then validate the schema from
   empty and from the supported preceding revision against an isolated database;
2. inspect `capabilities.get` before changing configuration and preserve the
   result as the process manifest baseline;
3. stage plane, write, and identity-correction switches in dependency order,
   refusing startup if any prerequisite is absent;
4. resolve the intended server-side Principal/profile and compare the effective
   MCP `tools/list` separately with the manifest — standard, producer, and
   reviewer profiles must omit merge/split; only the exact operator profile may
   include them, subject to capability and purpose grants;
5. perform only the separately authorized synthetic checks from section 9, then
   capture redacted audit identifiers, counts, and digests rather than payloads.

Stop immediately on identity drift, multiple Alembic heads, an unexpected tool,
cross-Principal visibility, schema/vocabulary mismatch, stale-preview success,
non-operator correction reachability, or any need for live personal data. The
rollback is configuration-only: restore all three RI switches and remote writes
to their prior values and restart through the governed runtime procedure. Do not
reverse the migration or delete ledger rows as an operational rollback. Preserve
the failed evidence and hand the decision back to the operator.

## 9. WP-09 canary procedure — prepared, not executed

Run only after WP-08 is expressly authorized and its preconditions pass. Use a
new synthetic Principal and synthetic entities with no live connector, NAS
content, contact detail, credential, or production/shared database. Record exact
request and result digests plus opaque identifiers for this bounded sequence:

1. verify `relationship_standard` can read the plane and identity history but
   cannot preview/apply merge or split;
2. verify producer can submit a typed proposal and cannot review or mutate it;
3. verify reviewer can decide an eligible proposal and still cannot execute an
   identity correction;
4. as the exact operator profile, preview then apply one merge, read its history,
   preview the inverse from that source operation, and apply the exact split;
5. prove a stale version, altered digest, second consumption, foreign Principal,
   and non-operator request are each refused without an effect-ledger append;
6. compare the generic HTTP and MCP envelopes after masking minted identifiers,
   and compare `capabilities.get` with effective `tools/list` as distinct planes;
7. turn the commissioned switches back to their recorded pre-canary state and
   verify the tool view and direct-call refusal return to that state.

The canary passes only if the final entity state equals the pre-merge semantic
state, both immutable operations remain visible in history, all negative probes
leave counts/digests unchanged, and no sensitive payload appears in logs or the
evidence package. Any other result is a stop, rollback, and operator escalation;
it is not permission to repair production data in place.
