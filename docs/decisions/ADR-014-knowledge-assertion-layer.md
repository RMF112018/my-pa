# ADR-014: Knowledge Assertion layer

- **Status:** Accepted
- **Decision date:** 2026-10-04
- **Repository basis:** `main@3f575c02570c8fa733ecdc7bf0284fedc3c1d980`, tree `3667e3b7e1fd6a8d419deb57ebc2beaa2541789b`
- **Authority:** Operator authorization of the Knowledge Layer readiness plan R5 as amended by R6 (`MYPA_KNOWLEDGE_LAYER_R6_PLAN_AMENDMENT_20261004.md`) and its machine contract, committed byte-exact as [`tests/architecture/klp_implementation_matrix_r6.json`](../../tests/architecture/klp_implementation_matrix_r6.json) (SHA-256 `ee2f2f8fc81a3e5e3f73e618a18fbf296ecd2a752d50499bf2e725e21e60de6a`). Where R6 differs from R5, R6 controls.
- **Scope:** A product-owned plane of canonical, evidence-backed Knowledge Assertions; its closed predicate registry; Review and operator authority derivation; classification rank and monotonicity; the frozen request digest and fingerprint; and the causal provenance bound.

## Context

MY-PA already holds extraction knowledge (`knowledge.search/read/reveal/coverage`), Capture review and promotion (ADR-006), Relationship Memory, Entities and continuity records. None of them is a home for a small, typed, reviewable fact such as "this organization's payment terms are Net 30" that is observed in a source, cited with evidence, and either admitted directly or routed to human Review. Without a dedicated plane such facts end up as free-form attribute rows, as model output treated as truth, or duplicated across planes with no single owner.

A discovery client (a remote LLM integration) will propose such facts. Every remote OAuth client authenticates as the operator Principal ([ADR-013](ADR-013-fixed-local-principal-and-operator-auth-grants.md)), so `principal.is_operator` cannot tell the human operator from a client. Facts must also never become less restricted than the evidence behind them, and a client reacting to its own writes must not loop.

## Decision

1. **Product-owned canonical assertions with evidence.** A Knowledge Assertion is a Principal-partitioned canonical record (`kasr_`) of one subject (principal, entity, project, managed document or evidence ref), one registered predicate and exactly one typed value branch (text or datetime), with an optional closed qualifier and effective interval. Evidence is one canonical row per source identity (`kaevd_`): an external object under a source profile, a Capture, or a Relationship Memory, linked with role `direct`, `supporting` or `counterevidence`. Every change is an append-only mutation receipt (`kamut_`) tied to a submission (`kasub_`). The layer is additive: extraction knowledge keeps its capabilities and identifiers, and neither reveal surface resolves the other's identifiers.

2. **Closed predicate registry, no EAV.** Assertions name a `predicate_code` from a migration-seeded, insert-only registry. A code's structure (value type, cardinality, temporal semantics, qualifier rule, allowed subjects and entity types, canonical owner, normalization and fingerprint version) is immutable across versions; a structural change requires a new code, and a retired head closes its code. Consequential and domain-owned predicates never admit directly. Predicates owned by another plane (continuity decisions, tasks, commitments, constraints, meetings, Relationship Memory) route to that owner or yield `domain_owned_no_intake`; the Knowledge layer never shadows them. All closed vocabularies are defined once in `src/my_pa/domain/knowledge_assertion/vocabulary.py` and restated as frozen literals by the schema revision.

3. **Review and operator authority are derived, never claimed (R6 section 3).** One pure function derives `(review authority class, decision channel)` from server-stamped inputs only; no payload field reaches it.
   - `local_operator` requires an explicitly stamped `OperatorSurface` (`cli` or `http_gateway`, set only by the CLI adapter and the HTTP gateway `invoke` route), `LOCAL` transport, an operator Principal and no authenticated client. The channel is `local_cli` or `local_web`.
   - Setting `operator_surface` together with `REMOTE_CLIENT` transport, an authenticated client id, **or** `capability_grants` raises `ValueError`. A grant-ceilinged caller is never `local_operator`.
   - `remote_operator_attested` requires `REMOTE_CLIENT` and a client in the exact operator-review allowlist (`remote_operator_review` channel). Any other client is `ordinary_reviewer` / `remote_interactive`; every other local caller, including stdio MCP and an unset surface, is `ordinary_reviewer` / `local_unattested`. `REMOTE_CLIENT` with no client is refused for Knowledge `review.decide`.
   - An ordinary reviewer can never accept or correct a `requires_operator` case; the database backs this with CHECKs on the stored decision.
   - The discovery, operator-review and ChatLLM client allowlists are pairwise disjoint exact client ids; discovery clients never receive create or `review.decide`.

4. **Who counts as remote.** Everywhere in this layer a caller is remote when `transport is REMOTE_CLIENT` **or** `capability_grants is not None`. This is the existing fail-closed predicate of Record Event memory disclosure and context plane admission: any composition with a grant ceiling is remote even over local transport.

5. **Classification rank and monotonicity.** The rank is `synthetic_test (0) < private_local (1) < restricted_local (2)`, public as `CLASSIFICATION_RANK` / `classification_max()` in `src/my_pa/domain/common/classification.py`, restated once in SQL as an IMMUTABLE rank function. Stored classes only rise. An assertion's effective class is the rank-max over its own class, its predecessor's, and every linked evidence row, including every same-origin external sibling and every Capture or Relationship Memory version. The observed class of external evidence on submit is rank-max(source-profile floor, sibling max across **all** profiles of the same `origin_system` for the same external object), so a new version or an overlapping profile cannot launder a restriction. `synthetic_test` is legal only on rows whose source profile is synthetic. Restricted, unavailable or archived-capture-backed rows are withheld from every remote surface before pagination. `Classification.is_cloud_eligible` is unchanged.

6. **Frozen request digest and fingerprint v1.** Replay and duplicate detection use two frozen objects encoded one way: NFC strings, `json.dumps(sort_keys=True, separators=(",", ":"), ensure_ascii=False)`, UTF-8, SHA-256 hex, nulls present. The request digest covers the factual payload, owner ref, source profile and scope, sorted de-duplicated trigger events and canonically ordered evidence; it excludes retrieval timestamps, transport keys, raw excerpts and caller hints. The fingerprint covers subject, predicate, value type, normalized value, qualifier, temporal semantics and effective interval; it excludes predicate version, owner ref, evidence and classification, and a proposal's fingerprint equals the assertion fingerprint of the same candidate. Text normalizes by NFC, strip and whitespace collapse with no case folding; datetimes by UTC conversion to `YYYY-MM-DDTHH:MM:SS.ffffffZ`. Golden vectors pin both. A different formula needs a new version and a new schema revision.

7. **Bounded causal provenance.** Each submission stores a causal root and a depth of at most 4, the only ceiling. No Knowledge-parent trigger starts a root; one distinct root is inherited at depth 1 + max; more than one root, depth above 4, or a repeated (client, subject, predicate) anywhere in the ancestor lineage is refused. Explicit create is always a root, and Review promotion inherits its proposal's origin, so review does not reset depth. A soft per-client, per-run rate bound limits loops that cite no trigger. Every Knowledge Record Event names its mutation as `source_receipt_id`, and the Record Event mapping is frozen: actor `assistant` / `principal` / `review_promotion` / `system` and authority `source_backed_assertion` / `user_confirmed_assertion` / `review_accepted` / `system_deterministic`. Same-transaction `causation_event_id` keeps its meaning; cross-run provenance is a separate metadata read (see [`record-event-causal-provenance-v0.1.md`](../specs/record-event-causal-provenance-v0.1.md), section 10).

## Out of scope

- OneDrive discovery: the origin-system vocabulary has no OneDrive token, so a OneDrive profile is unrepresentable until a separately authorized revision adds one.
- Semantic inference that blocks or routes work; model output never authorizes anything, and epistemic status is derived server-side.
- Encryption of checkpoint envelopes, a stdio MCP operator opt-in, a typed correction editor in the web UI, and settling the local-gateway operator boundary for co-located agents (R6 residual R-2).
- Any runtime, connector, credential, grant, deployment or production activation. Those remain operator-gated work packages (KLP-WP-00, WP-08 to WP-14).

## Consequences

- One plane owns small typed facts; other planes keep their own records and receive routed facts through their own writers.
- Operator authority for consequential facts is bound to a human-operator surface or an explicitly allowlisted client, never to the Principal kind alone.
- The schema can be checked against Python vocabularies and against the committed matrix in FAST, before any persistence exists.

## Supersession

This ADR supersedes nothing. ADR-006 Capture review and promotion, ADR-013's single production Principal, and the existing extraction knowledge plane are unchanged. A future change to the digest, fingerprint, vocabularies or authority derivation needs an amendment to this ADR.

## Implementation status

**Not implemented.** KLP-WP-01 lands only the architecture contract: the closed vocabularies, identifier kinds, classification rank, value objects, canonical digest functions with golden vectors, the committed matrix and its FAST traceability and lane lints, and this record. There is no schema, capability, persistence or runtime behaviour. The schema is KLP-WP-02, read/create KLP-WP-03, submit/checkpoint/Review KLP-WP-04, cross-run provenance KLP-WP-05 and the context plane KLP-WP-06. Where the committed matrix still carries stale wording on these rules (R6 verification finding KLP-R6V-203), this ADR's wording in decisions 3 to 5 is authoritative.
