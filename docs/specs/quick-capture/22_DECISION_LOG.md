# Decision Log

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


| ID | Decision | Rationale | Status |
|---|---|---|---|
| QC-D-001 | Use Quick Capture as capability name and Capture as action label | Clear and non-form-like | Proposed |
| QC-D-002 | Two initial launch modes: Quick Note and Conversation Log | Covers general and interaction evidence without taxonomy burden | Proposed |
| QC-D-003 | One free-text field is the only content requirement | Core frictionless contract | Proposed |
| QC-D-004 | Explicit Save commits; autosave protects drafts only | Prevents incomplete evidence while avoiding loss | Proposed |
| QC-D-005 | Persist before processing | Capture speed/reliability cannot depend on AI | Proposed |
| QC-D-006 | Original text is product-owned source-authoritative user evidence | Preserves what user wrote without asserting objective truth |
| QC-D-007 | Edits create immutable versions | Lineage and accepted-state revalidation |
| QC-D-008 | Conversation is a specialized first-class Event | Supports timelines/participants/commitments without duplicating source |
| QC-D-009 | Explicit Conversation Log may create a skeletal Conversation | User selected event class; unknown details remain unknown |
| QC-D-010 | Inferred consequential objects remain proposals | Aligns with review-before-authority |
| QC-D-011 | Quick Capture is global action, not primary nav | Avoids UI noise and preserves current IA |
| QC-D-012 | Library has Captures with Notes/Conversations saved views | Predictable retrieval without silos |
| QC-D-013 | Offline append-only capture belongs in MVP | Core promise must survive connectivity loss |
| QC-D-014 | Foreground/resume sync is authoritative | Background Sync is not universally reliable |
| QC-D-015 | PWA first; native wrappers later by measured need | Broad reach, minimal duplication, current product direction |
| QC-D-016 | Native Apple work required for App Intents/WidgetKit/Share extension | PWA cannot claim those integrations |
| QC-D-017 | Windows PWA shortcuts/share are near-term | Supported platform integration without native client |
| QC-D-018 | Tauri is preferred desktop wrapper evaluation candidate | Reuses web UI and supports global shortcuts/integration |
| QC-D-019 | No audio/call recording in MVP | Request is typed capture; legal/privacy/platform risk |
| QC-D-020 | Private-local, cloud false, training false defaults | Local-first/fail-closed repository posture |
| QC-D-021 | Exact source spans required | Traceability for every derived claim |
| QC-D-022 | Confidence never overrides consequence | High-confidence consequential errors remain harmful |
| QC-D-023 | No notification for ordinary processing completion | Avoid noise/leakage |
| QC-D-024 | No Pulse promotion from raw save/model confidence | Pulse requires accepted consequence and reason |
| QC-D-025 | Reuse modular monolith, PostgreSQL jobs/FTS | Consistent with accepted ADR and repository constraints |
| QC-D-026 | No Redis/Celery/microservice/vector/graph requirement | No demonstrated current need |
| QC-D-027 | Feature is not currently implementation-ready | Missing extraction/transport/frontend and active governance constraints |
| QC-D-028 | Publication grants no implementation authority | Governance boundary |
| QC-D-029 | Formal principle recommended: preserve evidence first, structure afterward | Closes product-thesis gap |
| QC-D-030 | Final operator decisions remain open | Product priority, platform, offline, privacy, retention, native/audio/action scope are operator authority |
