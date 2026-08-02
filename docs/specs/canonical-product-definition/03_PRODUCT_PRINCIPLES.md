---
title: my-pa — Product Principles
artifact_id: PRINCIPLES-MYPA-CANONICAL-002
artifact_type: Product principles
package_id: MYPA-CANONICAL-PRODUCT-DEFINITION-20260802-006
coordination_request_id: REQ-MYPA-CANONICAL-PRODUCT-MCP-INTEGRATION-20260802T095600Z
version: 2.1
status: CURRENT_CANONICAL_PRODUCT_DEFINITION
date: 2026-08-02
repository: RMF112018/my-pa
repository_head: 9096fa4fbe64ff1cdabc07e53a3e68c52efc8575
repository_tree: UNAVAILABLE_FROM_AUTHENTICATED_CONNECTOR
canonical_parent_folder_id: 1Ss71vau8phz7dvXduy7ChIwtxcU3K8Rz
package_folder_id: 1Z8Aug1_3v6ILgvopY8XpjiNMBySZOCCq
implementation_authority: NOT_GRANTED
repository_mutation: NOT_PERFORMED
revision_action: REVISE
prior_version: 2.0
feature_package_id: MYPA-FRONTIER-NAS-MCP-CONNECTOR-FEATURE-PACKAGE-20260802-086
feature_package_folder_id: 1McYcZODHhUb2k-vOQJnkHVQyqHbWRuVa
---

# Product Principles

1. **Evidence before fluency.** Material outputs expose source, coverage, freshness, contradiction, uncertainty, and unavailable evidence.
2. **Attention before volume.** Pulse ranks by consequence and explains why.
3. **Continuity before transactions.** Current state stays connected to people, projects, conversations, decisions, commitments, and sources.
4. **Preserve before structure.** User-authored evidence is committed before enrichment.
5. **Proposal before promotion.** Rules/models create candidates; authority creates canonical state.
6. **Consequence outranks confidence.** High-confidence high-consequence content still requires Review.
7. **Shared records, multiple lenses.** Projects, people, meetings, captures, commitments, and decisions reference shared records.
8. **Unresolved is valid.** Unknown identity, time, project, or meaning is represented, not guessed.
9. **Original evidence remains reachable.** Every derived record links to exact version and span/region.
10. **Corrections add history.** Versions, reversals, rejections, and supersession remain visible.
11. **Offline is bounded.** MVP permits encrypted append-only Capture, not broad canonical mutation.
12. **External action is separate authority.** Knowledge acceptance is not execution permission.
13. **Privacy is default.** Captures and sensitive observations start local/private/cloud-false/training-false.
14. **Useful without chat.** Essential workflows have navigable visual paths.
15. **System limits are visible.** Degraded capability, stale index, denied policy, and unavailable source are explicit.
16. **Architecture follows measured need.** Modular monolith, PostgreSQL, PWA, and shared planes precede specialized infrastructure.
17. **No relationship surveillance.** No hidden sentiment, loyalty, protected-trait, compatibility, or composite score.
18. **No false native promise.** PWA limits and platform capabilities are represented honestly.
19. **No source mutation by default.** External sources remain read-only; managed writes use separate authority.
20. **The human closes consequential loops.** Review, risk, merge, deployment, production, and external action remain explicit boundaries.

## Decision test

A feature must improve attention, continuity, evidence quality, or closure; preserve exact source/authority; avoid capture friction; keep consequential promotion reviewable; expose failure; fit the smallest coherent model; avoid a new silo without measured need; and have bounded privacy/recovery/audit.

## Tension order

Safety/privacy/source preservation; explicit human authority; source fidelity; minimal capture friction; transparent unresolved state; repository architecture for implementation; operator-only decisions remain open.

15. **One capability plane.** First-party surfaces and frontier clients invoke the same application use cases, policy, evidence, lifecycle, and audit semantics.
16. **Transport neutrality.** MCP, HTTP, CLI, worker, and UI adapters translate transport concerns; they do not become independent products or business-logic planes.
17. **Client request is not application authority.** A client or model may ask; authenticated identity, grants, policy, purpose, classification, scope, and side-effect class decide.
18. **Local control with selective external reasoning.** NAS-backed evidence remains locally governed; external disclosure is explicit, classified, bounded, and attributable.
19. **Semantic parity, not provider imitation.** Reproduce useful capability semantics without copying Google-specific storage, collaboration, permissions, or office-document models.
20. **Read and write are separate grants.** Source reads remain read-only; product-managed writes require a distinct store, lifecycle, authorization, and receipt.
21. **Compatibility is evidence.** A client is supported only after exact-profile conformance, not because it claims protocol support.

