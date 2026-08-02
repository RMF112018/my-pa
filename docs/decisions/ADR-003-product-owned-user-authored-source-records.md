# ADR-003: Product-Owned User-Authored Source Records

- **Status:** Accepted
- **Decision ID:** `PKL-MYPA-D-004`
- **Repository:** `RMF112018/my-pa`
- **Scope:** Data-authority boundary. No implementation, schema, transport, or frontend authority.

## Context

`AGENTS.md` section 4 states two boundaries that between them describe every
record `my-pa` has needed so far:

> Original source systems are authoritative and read-only by default.
>
> Managed-document writes occur only in designated managed storage.

The authority matrix in [`../architecture/data-authority.md`](../architecture/data-authority.md)
section 3 implements that split. Original source bytes are
`source_authoritative` with mutation authority "Source owner only; `my-pa`
none". Managed document bytes are `canonical` in a separate store and are
marked `Excluded` from the MCV.

The operator has reprioritized two features into scope. One of them, Quick
Capture, creates a record that neither row describes: a note the user types
into `my-pa` itself. There is no external source system that owns those bytes,
so the first row does not apply. It is also not a managed document — no separate
store, no filesystem root, no byte-level versioning of an opaque artifact, no
restore workflow — so the second row does not apply either.

The available shortcut is to lift the managed-write exclusion so that "write"
becomes generally permitted. That is the wrong instrument. Managed documents in
this repository carry a specific and heavy contract: a separate store and
credentials, expected-version preconditions, immutable versions, reversible
archive, retention, backup and restore tests, rollback, and no reuse of
source-provider handles (`data-authority.md` section 10, `threat-model.md`
section 10.13). Quick Capture needs none of it. Lifting the exclusion to
accommodate a text field would authorize a far larger surface than the feature
requires, and would erase the boundary that keeps a source provider from ever
acquiring a write method.

## Decision

Add a third authority class, distinct from both existing ones: the
**product-owned user-authored source record**.

The class is not Quick-Capture-specific. Quick Capture is the first feature to
need it, but the Relationship Intelligence specification's private observations
(section 9.10) are the same thing — user-authored text that `my-pa` owns, that
must stay visually distinct from source facts, and that must never silently
become a source-backed fact about another person. Both are governed by the
clauses below.

1. **Authority.** The stored text is `source_authoritative` for what the user
   wrote. It is evidence of the user's own statement, not evidence that the
   statement is true. Anything derived from it — entities, commitments,
   summaries, conversation events — remains `derived`, `proposed`, or
   `inferred` under the rules already in `data-authority.md` sections 4 and 7.

2. **System of record.** PostgreSQL, in the same logical database `my_pa`
   established by ADR-002. Not a managed document store, not a filesystem
   root, not a new database.

3. **Mutation authority.** The authenticated owning principal, through an
   application command, and only by appending a new immutable version. Stored
   text is never updated in place and never deleted by the application. An
   edit creates a successor version and supersedes its predecessor; the
   predecessor remains retrievable. Withdrawal is an archive state, not a
   delete.

4. **This is not a managed-document write.** The managed-document boundary in
   `AGENTS.md` section 4, `data-authority.md`, `module-boundaries.md` section
   9, `system-context.md` section 9, and `threat-model.md` section 10.13
   remains closed and excluded. A user-authored capture is not routed through a
   managed write port, does not use a managed store, and does not acquire the
   managed-document lifecycle.

5. **This grants the source-provider port nothing.** The read-only source
   provider contract is unchanged. It gains no write, create, rename, move,
   delete, or permission method. A capture never travels through a source
   provider. `MB-AC-003` and the negative tests behind it stand unmodified.

6. **Required binding.** Every stored version binds the owning principal, an
   opaque capture and version identity, a monotonic version number, the exact
   committed text, a hash of that text, server receipt time, classification,
   processing policy, the idempotency key that admitted it, and a correlation
   and audit reference. A version that cannot bind these is rejected, not
   stored partially.

7. **Classification.** `private_local` by default, `cloud_eligible=false`,
   never eligible for model training. Location inside `my-pa` does not make
   content disclosable. `P00-OD-006` continues to govern cloud disclosure and
   remains open.

8. **Derived records cite exact spans.** A proposal derived from capture text
   carries evidence spans into an immutable version and is re-validated against
   that version. A span that no longer matches quarantines the proposal rather
   than presenting it against text that has changed.

## What this ADR does not decide

- It does not authorize a frontend. The operator's hold recorded as `D-09` in
  [`../plans/mcv-completion-plan.md`](../plans/mcv-completion-plan.md) stands.
- It does not authorize personal-data connector access. Contacts, email, and
  calendar remain unauthorized regardless of this class.
- It does not resolve retention or deletion. Hard delete requires the separate
  basis already stated in `data-authority.md` section 9.
- It does not select capability names, schemas, tables, or transports. Those
  belong to an implementing work package and its pull request.
- It does not accept risk, authorize deployment, or activate production.

## Consequences

- The authority matrix gains one row rather than a promoted managed-document
  row, so the excluded surface stays excluded.
- Append-only versioning makes the record class safe by construction: there is
  no code path that overwrites user evidence, so no test has to prove that one
  is never reached.
- The job, policy, audit, provenance, and coverage planes built for source-bound
  extraction are reused rather than duplicated. A capture version is an input to
  extraction in the same way a source object version is.
- `INV-PKL-001` ("original source bytes remain authoritative and read-only")
  needs a companion invariant rather than an exception, because a capture has no
  original source bytes to protect.
- A future feature wanting to write to an external system still faces the full
  managed-document gate. This ADR cannot be cited as precedent for it.

## Supersession

Superseded only by a later accepted ADR. Material change to ADR-001, ADR-002,
the source/managed-write separation, the canonical database identity, or the
disclosure posture invalidates this decision and requires reassessment.
