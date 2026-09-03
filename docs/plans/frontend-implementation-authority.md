# MY-PA Frontend Implementation Authority

**Authority package:** `UI-IMP-WP01 — Target, Acceptance, and ADR Alignment`  
**Repository basis:** `main@f4eaa4f950009847eb9bde2836f422d5cd731cbc`, tree `0fb4a0ecc416136e5a2a9e25a5d981e3d8a65ae2`  
**Controlling Drive package:** `MYPA-PRODUCTION-FRONTEND-IMPLEMENTATION-PACKAGE-20260819-001`  
**Controlling execution artifact:** `18_POST_AUDIT_IMPLEMENTATION_EXECUTION_PACKAGE_20260901`  
**Governance classification:** NON-AEOS  
**Status:** `UI_IMP_WP01_AUTHORITY_ESTABLISHED`

This file is the repository-controlled entry point for frontend implementation after the 2026-09-01 post-audit reconciliation. Developers should not reconstruct execution authority from older frontend audit/package artifacts.

## 1. Controlling execution sequence

Execution is organized as `UI-IMP-WP01..WP30`. Older `WP-FE-*` sequencing is historical where it conflicts with the post-audit sequence.

- `UI-IMP-WP01` — Target, Acceptance, and ADR Alignment. **This package establishes architecture and acceptance authority only.**
- `UI-IMP-WP02` — Auth Persistence and Session Topology.
- `UI-IMP-WP03` — WebAuthn Authentication and Credential Lifecycle.
- `UI-IMP-WP04` — Opaque Sessions, Principal Authority, Legacy Auth Retirement.
- `UI-IMP-WP05` — Central Mutation Admission and Browser Security.
- `UI-IMP-WP06` — Typed BFF Success, Error, Receipt, and Degraded Contracts.
- `UI-IMP-WP07` — Shared Rich Content, Overlay, Form, and Status Primitives.
- `UI-IMP-WP08` — Shell, Theme, Responsive Navigation, and Inspector Foundation.
- `UI-IMP-WP09` — Authoritative Task and Commitment Lifecycle.
- `UI-IMP-WP10` — Review and Evidence Correction Integrity.
- `UI-IMP-WP11` — Reports / Morning Intelligence BFF Contract.
- `UI-IMP-WP12` — Morning Brief and Specialist Intelligence UI.
- `UI-IMP-WP13` — Canonical Entity / People BFF Read Plane.
- `UI-IMP-WP14` — People Directory and Relationship Intelligence UI.
- `UI-IMP-WP15` — Canvas Canonical Graph Read Contract.
- `UI-IMP-WP16` — Canvas Directory/Map Read Experience.
- `UI-IMP-WP17` — Canvas Workspace Persistence and Arrange Mode.
- `UI-IMP-WP18` — Canvas Canonical Relationship Editing.
- `UI-IMP-WP19` — Canvas Temporal, Inspector, Provenance, and Changes Semantics.
- `UI-IMP-WP20` — Canvas Accessibility, Responsive Fallback, and Scale.
- `UI-IMP-WP21` — GoodNotes / GSQS Browser Contract — **PROVISIONAL** because the dedicated WP-14 audit is missing.
- `UI-IMP-WP22` — Knowledge / GoodNotes Evidence and Correction UI — **PROVISIONAL** for the same evidence limitation.
- `UI-IMP-WP23` — Federated Search Service and BFF.
- `UI-IMP-WP24` — Global Search / Command UX.
- `UI-IMP-WP25` — System / Health Runtime Truth.
- `UI-IMP-WP26` — PWA / Offline Validation-First Closure — **VALIDATION FIRST** because meaningful implementation already exists while the dedicated WP-08 audit is missing.
- `UI-IMP-WP27` — Cross-Cutting Test Protection Hardening.
- `UI-IMP-WP28` — CI, Browser Matrix, Security, and Performance Gates.
- `UI-IMP-WP29` — Deployment, Rollback, Environment, and Observability Contract.
- `UI-IMP-WP30` — Final Runtime / Acceptance Validation.

WP02 persistence substrate exists (`identity.webauthn_credentials`, `identity.webauthn_challenges`, `identity.recovery_code_sets`, `identity.recovery_codes`, `identity.auth_sessions`; see [frontend-auth-persistence.md](frontend-auth-persistence.md)). The production browser cookie and session registry remain the legacy HMAC + process-local map. WP02 does not activate WebAuthn.

The next executable package is:

`UI-IMP-WP13 — Canonical Entity / People BFF Read Plane`

WP11 Reports/Morning Intelligence BFF on this PR is contract substrate, not WP12 Morning Brief UI, production activation, or `PASS_VERIFIED` of `PFE-AC-048..057`.

## 2. Authentication/session authority

[ADR-011](../decisions/ADR-011-passkey-webauthn-authentication-and-opaque-server-sessions.md) is the controlling production browser authentication/session decision.

Target:

`WebAuthn/passkey → opaque server-side session → session-derived Principal`

Required authority rules:

- the browser never selects the authoritative Principal;
- exact RP ID/origin discipline;
- user verification required;
- no public self-registration;
- server-owned credential lifecycle;
- governed recovery and fresh-auth/step-up for sensitive credential actions;
- opaque browser SID only, with server-owned Principal/session state;
- bounded idle and absolute expiry, rotation, and revocation;
- deployment-coherent challenge/session storage;
- no Entra/MSAL normal production browser sign-in;
- no production browser `local_operator`/shared-secret recovery fallback;
- synthetic remains development/test only.

### Current implementation truth versus target

At the WP02 repository basis the web runtime still supports `synthetic | entra | local_operator`, still contains Entra/MSAL code, still uses a signed session cookie carrying Principal/session data, and still uses a process-local session registry. Durable PostgreSQL stores for credentials, challenges, recovery hashes, and opaque sessions now exist but are not wired to that runtime. These are legacy/current implementation facts, not the target architecture.

`UI-IMP-WP03..WP04` own ceremony and cookie cutover. WP02 does not remove or repair those runtime paths.

### Prior ADR supersession

ADR-011 supersedes only conflicting authentication/session provisions:

- ADR-004's MSAL/Entra production identity target, Entra-shaped production session target, Principal-bearing signed-cookie target, and live-Entra completion consequence;
- ADR-008's Entra pilot/production browser-auth selection and Entra-specific web egress requirement insofar as it is an enduring application-login requirement.

The remaining Next.js/BFF/PWA architecture in ADR-004 and the non-authentication NAS/process/filesystem/ingress/Apple/lifecycle topology in ADR-008 remain valid unless independently superseded.

## 3. Browser-native MossAIc / ChatLLM supersession

`BROWSER_NATIVE_MOSSAIC_CHATLLM_FRONTEND = SUPERSEDED`

MY-PA does not implement browser-native MossAIc / Abacus.AI ChatLLM integration. Do not implement or revive:

- ChatLLM iframe/embed;
- MossAIc utility sidebar;
- browser ChatLLM/provider API client;
- reverse proxy or dedicated browser tunnel for ChatLLM;
- native MY-PA chat surface;
- browser-originated Assistant action channel;
- provider-specific browser answer contract;
- browser manual-handoff requirements unless separately reauthorized.

ChatLLM interaction begins from the ChatLLM UI through separately governed connected-service/MCP capabilities.

Historical package artifacts and design evidence remain provenance. They are not active frontend implementation authority where they conflict with this section.

The explicit superseded acceptance IDs are:

`PFE-AC-089`, `PFE-AC-090`, `PFE-AC-185..190`, `PFE-AC-224`, `PFE-AC-225`.

## 4. Acceptance authority

The repository-controlled ledger is [frontend-acceptance-ledger.md](frontend-acceptance-ledger.md).

The effective acceptance universe is exactly `PFE-AC-001..250`:

- `001..139` — original frontend baseline;
- `140..226` — Relationship Canvas extension;
- `227..240` — Ambient Feedback / centralized Review amendment;
- `241..250` — Phase-3 frontend-foundation continuity.

No ID may disappear, be silently renumbered, or be presumed passing.

Because the final post-workstream WP-02 reconciliation was never published, the ledger defaults non-superseded records to `UNRECONCILED`. Unknown is not pass.

## 5. Evidence limitations that remain closure obligations

These do **not** stop bounded implementation under the post-audit sequence, but they do prohibit implied acceptance and final frontend-completion claims:

- final post-workstream WP-02 acceptance reconciliation: **missing**;
- dedicated WP-08 PWA/offline audit: **missing**;
- dedicated WP-14 Knowledge/Library/GoodNotes audit: **missing**;
- WP-16 exhaustive test-quality/protection audit: **incomplete**.

The published criterion wording and later audit normalization also diverge in part of `PFE-AC-123..139`. Preserve the published IDs/text and keep the mapping `UNRECONCILED`; do not renumber or weaken criteria to repair it. WP28-WP30 separately own the later audit's release-readiness controls.

## 6. Implementation discipline for WP02+

- Current repository/runtime truth controls over historical package assumptions.
- A fixture, scaffold, candidate PR, or browser-only synthetic result cannot conceal a missing authoritative backend contract.
- Browser terminal success must be backed by a capability-specific runtime-valid server result; no synthesized receipt/version/disposition/persistence state.
- Missing or unavailable services degrade explicitly rather than becoming empty success.
- Candidate-only behavior receives no current-main acceptance credit.
- Every state-changing browser capability ultimately uses the centralized mutation/security boundary owned by WP05.
- Overall frontend completion is not permitted while any effective ledger record remains `UNRECONCILED`.

## 7. WP01 scope boundary

WP01 changes repository authority and traceability only. It does **not** implement:

- WebAuthn/passkey runtime behavior;
- credential/challenge/recovery persistence;
- opaque session persistence or cutover;
- Entra/MSAL runtime removal;
- `local_operator` runtime removal;
- CSRF/runtime mutation changes;
- BFF runtime changes;
- Search, Intelligence, People, Canvas, GoodNotes, System, PWA, or other feature behavior;
- deployment or production activation.

Any developer beginning WP02 or later must use ADR-011, this authority document, and the all-250 ledger as the repository-controlled baseline.