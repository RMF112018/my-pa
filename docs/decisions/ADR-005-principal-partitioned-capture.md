# ADR-005: Principal-Partitioned Capture with a Durable Local Operator

- **Status:** Accepted
- **Decision ID:** `PKL-MYPA-D-WP03-001`
- **Repository:** `RMF112018/my-pa`
- **Scope:** Capture-plane ownership and authorization. No production deployment,
  live Entra credential, or live personal-data authority.

## Context

Before this decision the capture plane stored an owner and enforced nothing. D-72
recorded that `owner_principal_id` was persisted on every capture but that no read,
list, search, or revise path consulted it; D-67 recorded that every gateway
composition minted a fresh principal, so the "owner" changed on every process
restart and could not be the unit of isolation even in principle. The limitation
was honest — `docs/operations/mcv-limitations.md` named it — but it left the
central product claim unproven: that a capture belongs to exactly one Principal
and is invisible to every other.

WP-01 (merged at `21ff8dc2`) made the identity plane real: durable
`identity.user_accounts` keyed by validated Entra claims `(tid, oid)`, with
fail-closed principal scoping in persistence (`principal_scope.py`). WP-02
(merged at `6461e2a`) built the MossAIc frontend against that identity plane.
The ratified Moss canonical product package v4.0
(`MYPA-MOSS-CANONICAL-PRODUCT-PACKAGE-20260805-008`, SHA256
`60e886e9dd19c6d39929990cd939ab1eb8c9c11eea8b0fb8faffac971516d6a4`) makes R2 —
product-owned capture — the next work package, and its acceptance criteria
require ownership binding at admission, per-Principal idempotency, and
cross-Principal invisibility proven by negative tests.

## Decision

1. **Identity binding is a durable, deterministic derivation.**
   `src/my_pa/domain/identity/binding.py` defines `PRINCIPAL_NAMESPACE`
   (uuid5 of the URL namespace over `https://my-pa.invalid/principals`) and maps
   any valid principal identifier to a durable UUID: an identifier whose suffix
   is exactly thirty-two lowercase hexadecimal characters *is* a UUID and maps
   to itself (the bound form); any other valid identifier maps to the uuid5
   digest of its full text under `PRINCIPAL_NAMESPACE`. Lowercase is required
   for the exact branch because `UUID(hex=...)` accepts mixed case and would
   break injectivity between the two branches.
2. **The local operator is one principal forever.** `local_principal()` in
   `bootstrap/gateway.py` now returns the bound form of `LOCAL_OPERATOR_UUID`
   (uuid5 of `"local-operator"` under `PRINCIPAL_NAMESPACE`) instead of minting
   a fresh identifier per composition. Two runtimes on the same machine are the
   same Principal; a capture admitted before a restart is readable and revisable
   after it. This dissolves D-67's premise rather than working around it.
3. **Every capture operation takes the authenticated Principal.** The
   `CaptureRepository` port and its persistence implementation
   (`infrastructure/persistence/capture.py`, `capture_search.py`) require a
   `PrincipalContext` carrying `capture_principal_id`; read, head, chain,
   version, list, and search statements all carry the partition criterion. A
   capture owned by another Principal is not "forbidden" — it is **nonexistent**:
   reads return nothing, lists and search totals exclude it, and revising it
   raises `UnknownScopeError`, which the application service maps to the same
   `not_found` envelope as a genuinely absent identifier.
4. **Admission verifies, never trusts, the payload principal.** `admit_capture`
   compares the request's `principal_id` to the authenticated context and raises
   `CallerSuppliedPrincipalError` on mismatch (MU-AC-02 discipline): a forged
   owner in the payload is refused fail-closed, not silently rewritten.
5. **Idempotency is a per-Principal contract.** Alembic revision
   `e7f3a9c2d514` replaces the global unique constraint on `idempotency_key`
   with `UNIQUE (principal_id, idempotency_key)` and adds owner-first indexes
   on captures and capture versions. Two Principals may submit the same key and
   each receives their own capture; a replay by the same Principal returns the
   original receipt with `created = false`; the same key with different content
   from the same Principal is a conflict.
6. **Supersession is recorded, not erased.** This ADR supersedes D-72's
   stored-but-unenforced ownership and dissolves D-67; the plan register rows
   stand as history, `docs/operations/mcv-limitations.md` is rewritten to name
   the remaining gap, and QC-AC-013 (ownership binding) is now provable both
   across process restarts and against a foreign Principal —
   `tests/capture/test_owner_is_the_partition.py`,
   `tests/security/test_cross_principal_capture_isolation.py`,
   `tests/unit/test_principal_binding.py`, and
   `tests/schema/test_capture_partition_migration.py` carry the proof.

## Consequences

- All isolation proof runs on synthetic principals (`prn_aaaa0001…`,
  `prn_bbbb0002…`); no live personal data is involved.
- Live multi-principal identity — real Entra tokens resolving to distinct
  Principals at the gateway — remains gated on the open decision P00-OD-010
  and is out of scope here; the partition it will flow into is now real.
- Capture text remains absent from receipts and audit events (QC-AC-041); the
  new negative tests scan the persisted rows to keep that claim honest.

## Supersession

Supersedes the D-72 working default (owner stored, not enforced) and dissolves
the D-67 premise (fresh principal per composition). Superseded in turn only by
a later accepted ADR; wiring live Entra identity to the runtime does not modify
this ADR, it fulfills it.
