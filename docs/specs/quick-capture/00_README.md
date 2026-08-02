# my-pa Quick Capture Feature Package

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## Disposition

`QUICK_CAPTURE_FEATURE_PACKAGE_READY_FOR_OPERATOR_REVIEW`

This package defines, but does not implement, the proposed **Quick Capture** capability for typed Quick Notes and Conversation Logs. It is a product-definition, UX, data-authority, workflow, logical-data-model, architecture, API-contract, privacy, testing, and implementation-sequencing package.

## Recommendation

Quick Capture should be formed as all three of the following:

1. a **pervasive product action** available wherever the user is working;
2. a **product-owned ingestion source** for user-authored evidence; and
3. a **platform capability** that can be exposed through web, installed PWA, command, shortcut, and later native integrations.

It should not become a sixth primary navigation destination. The visible action should normally be labeled **Capture**; the capability and package name should remain **Quick Capture**. The initial launch modes are **Quick Note** and **Conversation Log**. The minimum interaction contract is one unrestricted text field plus an explicit save action. No structured metadata is required before persistence.

## Governing principle

> **When the user is the source, my-pa preserves the evidence first and structures it afterward.**

Supporting shorthand: **Capture first; structure later.**

## Package map

| File | Purpose |
|---|---|
| `01_EXECUTIVE_FEATURE_DESCRIPTION.md` | Executive definition and product recommendation |
| `02_COMPREHENSIVE_IMPLEMENTATION_SPECIFICATION.md` | Integrated build-oriented specification |
| `03_PRODUCT_PHILOSOPHY_AND_USER_VALUE.md` | Product principle, thesis, and non-goals |
| `04_TERMINOLOGY_AND_CAPTURE_TAXONOMY.md` | Modes, subtypes, labels, and naming |
| `05_END_TO_END_WORKFLOW_INVENTORY.md` | Capture, processing, review, reuse, correction, and failure workflows |
| `06_UX_AND_INTERACTION_SPECIFICATION.md` | One-field interaction contract and behavior |
| `07_DEVICE_AND_PLATFORM_EXPERIENCE_MATRIX.md` | Web/PWA/native feasibility and sequencing |
| `08_INFORMATION_ARCHITECTURE_UPDATE.md` | Global action, Library, timelines, Review, Reveal, and System placement |
| `09_LOGICAL_DATA_MODEL.md` | Minimum correct MVP model and later expansion |
| `10_SOURCE_AUTHORITY_AND_PROVENANCE_MODEL.md` | Authority classes, timestamps, spans, lineage, and receipts |
| `11_EXTRACTION_AND_PROPOSAL_PIPELINE.md` | Durable save, asynchronous processing, extraction, linking, indexing |
| `12_REVIEW_AND_PROMOTION_POLICY.md` | Automatic, proposed, review-required, and prohibited transitions |
| `13_OFFLINE_AND_SYNCHRONIZATION_SPECIFICATION.md` | Append-only offline queue, encryption, sync, conflict, recovery |
| `14_PRIVACY_SECURITY_AND_AUDIO_BOUNDARY.md` | Classification, cloud routing, telemetry, device risk, audio boundary |
| `15_SEARCH_DISPLAY_AND_NOTIFICATION_INTEGRATION.md` | Reveal, Library, timelines, Today, Pulse, and notification rules |
| `16_AI_STRATEGY.md` | Deterministic and model-assisted processing with authority controls |
| `17_TECHNICAL_ARCHITECTURE_RECOMMENDATION.md` | Modular-monolith alignment, gateway/worker/PWA boundary |
| `18_PROPOSED_API_AND_CONTRACT_PACKAGE.md` | Proposed HTTP contracts, examples, errors, idempotency |
| `19_MVP_DEFERRED_CAPABILITIES_AND_ROADMAP.md` | MVP, near-term, later, rejected, prerequisites, sequencing |
| `20_TESTING_EVALUATION_AND_ACCEPTANCE.md` | Test matrix, quality evaluations, measurable acceptance criteria |
| `21_RISKS_MITIGATIONS_AND_OPEN_OPERATOR_DECISIONS.md` | Risk register and decisions reserved to the operator |
| `22_DECISION_LOG.md` | Product-definition decisions and rationale |
| `23_STRUCTURED_WIREFRAMES.md` | Required interaction concepts and wireframes |
| `24_SOURCE_MANIFEST.json` | Source identities, evidence status, and unavailable evidence |
| `COORDINATION-REQUEST-REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081.md` | Governed operator request |
| `COORDINATION-RESPONSE-REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081.md` | Full findings and package response |
| `PUBLICATION-RECEIPT-MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005.json` | Publication inventory and verification |
| `COORDINATION-ROUNDTRIP-RECEIPT-REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081.json` | Request-response-publication binding |

## Current repository reality

The feature is **not ready for immediate implementation**. At the authenticated basis, the repository has PostgreSQL, foundational contracts/domain primitives, source enrollment/jobs, and a hardened read-only fixture provider. It does not yet provide the complete extraction/search plane, public gateway/MCP transport, product frontend, or end-to-end workflows required by Quick Capture. The active MCV remains a bounded read-only vertical slice, and a direct operator instruction holds frontend implementation until lifted.

## Authority boundary

This package is a review and planning input. It does not authorize:

- repository modification;
- implementation or creation of work packages;
- database mutation or schema migration;
- live-source or personal-data access;
- external-model disclosure;
- audio or call recording;
- source mutation or external actions;
- deployment, production activation, risk acceptance, or model promotion.

## Recommended operator sequence

1. Review and decide the open operator decisions in file 21.
2. Decide whether Quick Capture becomes a formal product principle and backlog feature.
3. Reconcile priority against the active MCV objective and the frontend hold.
4. Only after explicit reprioritization, commission a fresh repository-truth implementation plan against the then-current exact head.
