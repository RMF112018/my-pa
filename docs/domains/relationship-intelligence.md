# Relationship Intelligence

Relationship Intelligence (RI) is MY-PA's Principal-scoped entity, relationship, memory, review and continuity plane.

## Current implementation

The repository implements:

- governed Entity identity and multiple record families;
- names, addresses, communication methods, participations, identifiers, aliases and assignments;
- directed relationships/graph reads and writes;
- observations and unresolved mentions;
- profile/context assembly;
- identity history;
- governed merge/split preview/apply paths;
- Relationship Memory with immutable/versioned authoring lifecycle;
- review/proposal integration;
- continuity projections for relationship/project/situation views;
- deterministic re-enrichment work after identity changes.

The exact capability set is defined by current code and composition.

## Feature gates

RI is composition/feature-gated. Reads, ordinary writes, identity correction and remote writes have distinct controls. A feature switch is not authority by itself; normal capability/purpose/policy/Principal gates still apply.

Do not collapse “RI enabled” into “every RI write is allowed.”

## Principal isolation

RI records are Principal-partitioned. Ownership is derived server-side. Every new record family/read/write must preserve same-Principal isolation and add database/security tests when a cross-Principal path could exist.

## Identity correction

Merge/split are governed correction operations, not ordinary CRUD:

- preview/apply are distinct;
- ambiguity/conflict state is explicit;
- operator-only remote behavior requires stronger server-resolved authorization;
- history/provenance must remain intelligible after correction.

Do not hide identity correction inside a generic entity update.

## Relationship Memory

Relationship Memory binds a memory to an Entity subject and maintains lifecycle/version history. It has its own read/authoring purposes and is gated separately from the entity plane.

A memory is product-owned derived/user-authored knowledge under existing authority classes; it is not a source record overwrite.

## Re-enrichment

Identity changes can register durable re-enrichment work. The re-enrichment worker re-reads version inputs and settles stale/partial/failure explicitly rather than pretending every invalidation succeeded.

New derived RI material should define what invalidates it and how currency is proven.

## Product intent

Drive remains canonical for accepted Relationship Intelligence product intent. Current router:

- Relationship Intelligence lane: Drive folder `15Ekm96HISWd8sEQ6m8v-9QhHW88VreD6`
- current supporting Relationship Memory context and stakeholder-entity product package are indexed there.

Repository code/tests govern what is implemented.

## Extension checklist

For a new entity record family or RI capability:

1. define domain vocabulary/invariants;
2. define evidence/provenance/authority;
3. add persistence + Principal ownership;
4. define merge/split/history effects if identity correction touches it;
5. add application command/capability and policy;
6. classify remote write/operator requirements;
7. add MCP/HTTP/BFF decoding;
8. add partition/conflict/idempotency tests;
9. define re-enrichment invalidation where derived material depends on it;
10. update docs and Drive intent linkage as appropriate.

Detailed operational gating remains in `ops/runbooks/relationship-intelligence.md`.
