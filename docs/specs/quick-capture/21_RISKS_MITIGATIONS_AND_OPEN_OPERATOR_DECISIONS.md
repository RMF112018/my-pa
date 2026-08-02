# Risks, Mitigations, and Open Operator Decisions

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## Risk register

| ID | Risk | Severity | Mitigation |
|---|---|---:|---|
| QC-R-001 | Capture becomes a form | High | One-field acceptance criterion; optional metadata hidden |
| QC-R-002 | Source loss during save/offline | Critical | local transaction, server transaction, receipt, idempotency, recovery tests |
| QC-R-003 | False commitment/decision | Critical | exact spans, high precision evaluation, review-required |
| QC-R-004 | Incorrect identity/project link | High | candidate sets, unresolved state, review for consequential link |
| QC-R-005 | AI overwrites user meaning | High | immutable source, derived labels, version lineage |
| QC-R-006 | Review overload | High | low-risk noncanonical proposals, deduplication, burden metrics |
| QC-R-007 | Sensitive content reaches cloud | Critical | private-local/cloud false default, context manifest, fail-closed policy |
| QC-R-008 | Pasted prompt injection | High | evidence-data boundary, no tools, schema validation |
| QC-R-009 | Offline ciphertext/key compromise | High | app encryption, personal-device policy, disclose browser limitations |
| QC-R-010 | Mobile background sync assumed reliable | High | foreground/resume authoritative; background sync enhancement only |
| QC-R-011 | Native capabilities promised by PWA | High | platform matrix and explicit native boundary |
| QC-R-012 | Notification leakage | High | generic content, previews off, user permission |
| QC-R-013 | Duplicate sync | Medium/High | stable IDs, idempotency, request hash, replay receipt |
| QC-R-014 | Same text deduplicated incorrectly | Medium | never dedupe by text alone |
| QC-R-015 | Source edit invalidates accepted state | High | new version, revalidation state, no silent rewrite |
| QC-R-016 | Improper deletion | Critical | archive default, impact preview, operator retention decision |
| QC-R-017 | Relationship surveillance | High | no scores/sensitive traits/continuous monitoring |
| QC-R-018 | Audio scope creep | High | typed MVP boundary; separate spec/legal review |
| QC-R-019 | Architecture sprawl | High | modular monolith/PostgreSQL/PWA first; measured split gates |
| QC-R-020 | Feature conflicts with active MCV | Critical governance | backlog only until explicit reprioritization |
| QC-R-021 | Frontend implementation begins under current hold | Critical governance | explicit stop; operator must lift hold |
| QC-R-022 | Current repo substrate overstated | High | exact head basis; list missing extraction/transport/frontend |
| QC-R-023 | Source/content appears in operational logs | Critical | redacted structured telemetry and negative tests |
| QC-R-024 | Local storage eviction | High | persistence checks, pending status, export/recovery guidance, native evaluation trigger |
| QC-R-025 | Model-training leakage | Critical | training false by default; separate eligibility lifecycle |

## Open operator decisions

### O-01 Final name

Recommendation: capability **Quick Capture**, action **Capture**, modes **Quick Note** and **Conversation Log**.

Operator decision: accept or select alternate terminology.

### O-02 Formal product principle

Recommendation: adopt “When the user is the source, my-pa preserves the evidence first and structures it afterward.”

### O-03 Priority and active objective

Decide whether Quick Capture is:

- backlog after current MCV;
- next feature after MCV;
- a reprioritization of the current objective.

No agent may decide this silently.

### O-04 Frontend hold

Current repository record states frontend implementation is held until the operator lifts it. Decide whether and when to lift it for Quick Capture.

### O-05 Initial platforms

Recommendation: responsive app + installable PWA on iPhone/iPad/macOS/Windows, with Windows PWA shortcuts/share and Apple deep-link Shortcut guidance. Native integrations deferred.

### O-06 Offline MVP

Recommendation: include encrypted append-only offline capture in MVP. Operator must accept the implementation complexity and browser-storage limitations or explicitly defer it.

### O-07 PWA versus native wrappers

Recommendation: PWA first; evaluate Tauri after measurement. Native Apple target only for App Intents/widgets/controls/share extension.

### O-08 Cloud-model eligibility

Recommendation: no cloud by default. Any approved route must name provider/account/purpose/fields/terms/audit/revocation.

### O-09 Private-note default

Recommendation: `private_local`, no lock-screen content, no training.

### O-10 Retention/deletion

Decide:

- active capture retention;
- archive duration;
- draft expiration;
- offline pending expiration;
- hard-delete authority;
- audit/tombstone retention.

### O-11 Notifications

Recommendation: in-app by default; generic system notifications only for actionable review/sync/failure; no processing-complete spam.

### O-12 Audio/voice scope

Recommendation: OS dictation only in MVP. User-initiated audio memo requires separate feature formation. Recording/interception excluded.

### O-13 Attachment scope

Recommendation: defer attachments from typed MVP. Consider shared text/URL first; files after managed storage and limits.

### O-14 Editing semantics

Recommendation: immutable versions; extraction-only corrections do not alter source; accepted downstream state requires revalidation after material source edits.

### O-15 Auto-link thresholds

Decide whether exact unique context/entity matches may be accepted automatically beyond deterministic launch context. Recommendation: keep inferred links proposed initially.

### O-16 Review thresholds

Accept risk/consequence matrix and initial commitment/decision/financial/date/identity review requirements.

### O-17 External-action boundary

Recommendation: no action authority. Accepted records may later create separate action proposals only.

### O-18 Conversation object behavior

Recommendation: explicit Conversation Log creates skeletal Conversation with unknown fields; inferred conversation from Quick Note remains proposed.

### O-19 Processing preference control

Recommendation: default local-only/private policy and optional “Save without AI processing” in secondary controls. Decide whether the control appears in MVP.

### O-20 Device-local encryption policy

Decide acceptable browser key-management posture and whether restricted classifications may be captured offline in a PWA.

## Operator-only next actions

1. Review these decisions.
2. Accept/revise package.
3. Establish product priority and active-goal effect.
4. Commission an exact-head implementation plan only after the required objective/frontend decisions.
5. Separately authorize any cloud, native, audio, live-data, retention, or external-action work.
