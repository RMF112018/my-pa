---
title: my-pa — Reconciled Frontend Architecture
artifact_id: ARCH-MYPA-CANONICAL-FRONTEND-002
artifact_type: Frontend architecture
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

# Reconciled Frontend Architecture

## Recommendation

One responsive client-rendered web application with installable PWA behavior. Recommended, subject to ADR/authorization: React, TypeScript, Vite, type-safe router, generated API client, server-state cache, SSE with polling fallback, minimal UI-only state, same-origin protected deployment.

No frontend toolchain is implemented at the authenticated repository basis.

## Modules

`app`, `shell`, domain modules for Today/Situations/Review/Library/Captures/Conversations/Projects/Relationships/Organizations/Commitments/Decisions/Tasks/Knowledge/Sources/GoodNotes/System; features for Reveal, Quick Capture, evidence rail, source preview, provenance, identity resolution, review, impact, receipts, saved views, offline sync; generated API; event invalidation; security/accessibility/observability/design system/tests.

## Authority

Backend owns policy, identity, lifecycle, canonical mutation, and receipts. Commands bind idempotency, exact object/version, transition, evidence, authority, and correlation. Events invalidate; clients refetch. Optimism is limited to reversible UI preference. No raw database/filesystem/provider SDK/MCP/model tool. Untrusted source text has no instruction/tool authority.

## Responsive shell

- Desktop: navigation rail, context header, canvas, optional evidence/impact rail, Reveal, Capture, command palette.
- Tablet: compact navigation, one canvas, drawers/sheets, centered/full-height Capture.
- Mobile: task-focused navigation, Capture always reachable, full-height modes, stacked detail/evidence drawer.

## Capture UI

Global action, command palette, focused-app keyboard shortcut, mode routes, contextual launch, mobile/tablet/desktop surfaces, draft recovery, online/offline acknowledgment, sync/processing/review/failure state, Capture detail/version history, Conversation detail, Notes/Conversations Library.

Minimal field set: mode label, one unrestricted field, Save, Close, passive privacy/connection state, optional removable context chip. No required title, participants, project, date, channel, tag, or task form.

## Relationship UI

Identity/affiliation disclosure; interactions; reciprocal commitments; project involvement; private observations; contradictions/stale assertions; meeting briefing; contextual Capture; evidence/provenance. No score, sentiment meter, loyalty indicator, or sales pipeline.

## Review UI

Three coordinated areas: source evidence; proposed transition/correction; impact/authority. Keyboard operable; exact spans/regions; identities/counterevidence; downstream impact; disposition; receipt; conflicts.

## PWA/offline

Installable manifest; supported shortcuts; service worker shell; encrypted IndexedDB append-only queue; client opaque IDs/idempotency; foreground/resume sync required; Background Sync opportunistic; account/session binding; explicit conflicts; no broad offline mutation.

## Performance targets

Warm in-app Capture p75 ≤150 ms/p95 ≤300 ms; installed shortcut to cursor p75 ≤1.5 s/p95 ≤2.5 s; keypress paint p95 ≤50 ms; local draft p95 ≤100 ms after debounce; offline acknowledgment p95 ≤200 ms; online durable acknowledgment p95 ≤750 ms on target LAN; indexed search p95 ≤500 ms backend-to-render; review commit p95 ≤1 s excluding background work.

## Accessibility/security

WCAG 2.2 AA; keyboard; screen-reader landmarks/announcements; focus restoration; touch targets; 400% reflow; text scaling; reduced motion; high contrast; no color-only status.

Secure session; CSRF protection; reauthentication for high impact; server-side field/capability enforcement; no content in analytics/URLs/notifications/logs; context manifest; lock/logout/cache clearing; XSS/prompt-injection/link/path/authorization/offline-account-switch/data-leak tests.

## Deferred technology

No Electron/Tauri, native shell, SSR Node server, microfrontends, GraphQL, Redux by default, WebSockets, or dedicated vector/graph client until measured need.

## Connected-client control surface

The first-party frontend is the authoritative control and recovery surface for frontier-client access. It must expose connection status, verified client profile, grants/scopes, capability availability, authorization expiry/revocation, degraded ingress, origin health, read/write/global kill switches, safe mode, denials, invocation traces, audit events, managed-document activity, conflicts, and receipts.

The UI must distinguish:

- edge connectivity from origin authorization and application readiness;
- actor identity from client identity and model metadata;
- source reads from managed-document writes and product-owned Capture records;
- protocol success from application-policy approval;
- client compatibility verified, conditionally supported, degraded, and unverified;
- reversible archive from hard deletion.

A dedicated MCP chat interface is not part of the architecture. External clients provide their own conversation surfaces; the first-party application provides continuity, Reveal, Capture, Library, Review, System, and recovery. Any future embedded client experience requires separate product justification and cannot bypass the same capability plane.

