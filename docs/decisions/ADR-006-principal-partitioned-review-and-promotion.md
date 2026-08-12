# ADR-006: Principal-Partitioned Review and Promotion

- **Status:** Accepted
- **Decision ID:** `PKL-MYPA-D-WP05-001`
- **Repository:** `RMF112018/my-pa`
- **Scope:** Review and promotion plane ownership and authorization — review
  cases, assertions, assertion spans, and promotion receipts. No production
  deployment, live Entra credential, or live personal-data authority.

## Context

WP-05 (R4) adapts the existing proposal/review/promotion substrate to Principal
partitioning. The substrate itself predates the campaign: the review and
promotion tables were created at Alembic revision `3c8f1e2a5b74`, before
`principal_id` was a campaign-wide invariant. Those tables stored assertions,
assertion spans, review cases, and promotion receipts keyed only by their
`version_id`/`review_case_id` lineage. Ownership was implied transitively —
an assertion belonged to whoever owned the capture version it derived from —
but nothing on the review plane consulted a principal. A review listing read
every case; a decision looked a case up by id alone. The central product claim
for R4 was therefore unproven at the review tier even though ADR-005 had proven
it at the capture tier: that a proposal, its review, and its promotion belong to
exactly one Principal and are invisible to every other.

ADR-005 (`PKL-MYPA-D-WP03-001`, merged as `646c273`) made capture
principal-partitioned: `owner_principal_id` is bound and verified at admission,
idempotency is per-Principal at revision `e7f3a9c2d514`, and a foreign
Principal's capture is indistinguishable from a nonexistent one on every read
path. WP-05 depends on that capture plane as its proposal input, and on the
WP-01 identity foundation. WP-04 (R3 offline capture) is deferred by operator
decision as a leaf dependency; WP-05 does not depend on it.

The ratified Moss canonical product package v4.0
(`MYPA-MOSS-CANONICAL-PRODUCT-PACKAGE-20260805-008`) makes R4 the active work
package. Its acceptance criteria (WORK-PACKAGE-MAP WP-05) require transactional
promotion with receipts, AI output that stays non-authoritative until a human
review acceptance, cross-Principal review negative tests (MU-AC-04), and
correction/rejection/defer/supersession paths that never act across Principals.

## Decision

1. **The review plane carries its own `principal_id`, derived from the owner.**
   `capture_review_cases`, `capture_assertions`, `capture_assertion_spans`, and
   `capture_promotion_receipts` each gain a mandatory `principal_id`, validated
   as an opaque `PRINCIPAL` identifier and indexed by principal. The value is
   never taken from a caller: `open_review_case` and `promote_proposal` read the
   `owner_principal_id` of the capture version under review and stamp it onto
   every case, assertion, span, and receipt they write. The review principal is
   by construction the capture owner, so the review-plane partition is the same
   partition ADR-005 established — not a parallel one that could drift out of
   alignment (MU-AC-02).

2. **Reads and decisions are principal-scoped, and a foreign case is
   nonexistent.** `review_cases` now requires a `PrincipalContext` and is
   `principal_scoped`, so a listing can only ever return the caller's own cases.
   `decide_review` scopes its case lookup by `request.principal_id`; a decision
   aimed at another Principal's case raises `ReviewNotFoundError` and writes
   nothing, which the application service maps to the same `not_found` envelope
   as a genuinely absent id. Cross-Principal existence is never disclosed — a
   foreign case and an unknown case are indistinguishable.

3. **AI stays non-authoritative until a human disposition.** A proposal is a
   noncanonical interpretation; it becomes a canonical reviewed assertion only
   through an explicit accept or correct-and-accept disposition. There is no
   silent promotion path for the consequential classes R4 routes to Review
   (commitments, decisions, identity merges, sensitive relationship claims,
   managed-document writes, external actions). Correction preserves the original
   proposal and records a separate reviewed value; it does not rewrite
   derivation history.

4. **Promotion is transactional and issues an immutable receipt.**
   `promote_proposal` writes the assertion, its spans, and the promotion receipt
   inside one transaction, each stamped with the owner's `principal_id`. The
   receipt binds Principal, policy version, proposal/decision, evidence version,
   transition, and timestamp — the durable evidence that a promotion occurred
   under a stated authority.

5. **The forward migration is frozen-literal; the pre-campaign revision is
   frozen in place.** Alembic revision `b9a4ecdfac0b` (down-revision
   `e7f3a9c2d514`) adds the `principal_id` columns, `CHECK` constraints, and
   principal indexes to the four review-plane tables. Its CHECK literal and
   constraint name byte-match the live `_is_identifier` emission so the schema
   the migration builds and the schema the table metadata declares are the same.
   Revision `3c8f1e2a5b74` — which predates the campaign — is frozen to keep
   emitting its original pre-`principal_id` shape, because a merged migration
   must never change what it emits (campaign D-48); the new column arrives only
   at `b9a4ecdfac0b`.

6. **The web tier mirrors the partition.** The Review destination is now a
   workbench: `/api/review` lists only the caller's own cases and
   `/api/review/:id/decide` records a disposition against a case the caller
   owns, returning the receipt the promotion issues. A case the caller does not
   own is `not_found`. Cases are principal-scoped synthetic fixtures until the
   Python read models are wired; every response is labeled synthetic.

## Consequences

- All isolation proof runs on synthetic principals (`prn_aaaa0001…`,
  `prn_bbbb0002…`); no live personal data is involved.
  `tests/security/test_cross_principal_review_isolation.py` proves a foreign
  Principal cannot list, decide, or observe another Principal's review and
  promotion records; `tests/schema/test_review_schema_migration.py` round-trips
  the partitioned schema from empty.
- The review principal is a derivation of the capture owner, not an independent
  input, so no review, assertion, span, or receipt can ever be stamped with a
  principal that differs from the evidence it derives from. This is the
  invariant the negative tests defend.
- Response payloads on the review plane do not echo `principal_id`; the session
  (web) and the `PrincipalContext` (Python) are the only identity carriers.
- Live multi-principal identity — real Entra tokens resolving to distinct
  Principals at the gateway — remains gated on P00-OD-010 and is out of scope
  here; the partition it will flow into is now real on the review plane as well
  as the capture plane.

## Supersession

Supersedes the pre-campaign working default in which the review and promotion
tables stored lineage but no principal and no read or decision path consulted
one. Superseded in turn only by a later accepted ADR; wiring live Entra identity
or the live proposal pipeline to the runtime does not modify this ADR, it
fulfills it.
