# End-to-End Workflow Inventory

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## W-01 — In-app Quick Note

1. User invokes Capture from shell, Reveal, command palette, or keyboard.
2. Surface opens with cursor in the text field.
3. Optional launch context appears as a passive chip.
4. Draft is autosaved locally while typing.
5. User presses Save or `Cmd/Ctrl+Enter`.
6. Client generates/uses stable capture ID, version ID, and idempotency key.
7. Server transaction persists capture, version, receipt, audit event, and processing job/outbox.
8. Client receives durable acknowledgment, clears draft, closes surface.
9. Worker processes asynchronously.
10. Search/index and proposal status update through refetch/SSE/polling.
11. User may later find the original in Captures/Notes, Reveal, or linked context.

## W-02 — In-app Conversation Log

1. User launches Conversation Log directly or switches mode.
2. User enters a natural-language summary only.
3. Save follows W-01.
4. System creates a source Capture and, for explicit Conversation mode, a skeletal Conversation event with unresolved fields.
5. Pipeline proposes participants, channel, occurred time, topics, commitments, decisions, follow-ups, risks, and contextual links.
6. Low-risk inferred links remain noncanonical suggestions.
7. Consequential proposals route to Review.
8. Accepted event/link updates Relationship and Project timelines.
9. Original text remains one interaction away.

## W-03 — Contextual capture

Launch from a Situation, Project, Relationship, meeting, Decision, Commitment, or source.

- Client includes a deterministic `launch_context`.
- Server validates the referenced object and access.
- The context link may auto-accept if exact and current.
- If the object version is stale/deleted/unavailable, capture still persists and context link becomes unavailable/proposed.
- Capture does not fail merely because contextual linking fails.

## W-04 — Offline capture

1. PWA detects no reliable server path or request fails before acceptance.
2. Client commits encrypted append-only record to IndexedDB in one local transaction.
3. UI confirms **Saved on this device — sync pending**.
4. Foreground/resume/online events initiate sync; Background Sync is opportunistic only.
5. Sync sends original client IDs, timestamps, content hash, and idempotency key.
6. Server returns existing result for a prior identical key or creates the record once.
7. Client records server receipt and removes encrypted payload only after verified acknowledgment.
8. Conflicting server state is surfaced; original local entry is never silently discarded.

## W-05 — Draft recovery

- Non-empty drafts autosave locally at short intervals.
- Closing without save preserves a draft and provides a subtle “Draft saved” state.
- Next launch offers Restore / Discard.
- Drafts are not search indexed, processed, or treated as evidence until explicit save.
- Draft retention is bounded and user-cleareable.

## W-06 — Processing

Stages:

1. validate persisted input;
2. normalize without modifying source;
3. detect language;
4. segment;
5. extract deterministic patterns;
6. extract entities and candidate event/work objects;
7. resolve identities/context;
8. normalize dates/times;
9. retrieve related records;
10. detect contradictions;
11. generate summary and proposals;
12. persist spans and provenance;
13. index original and eligible derived text;
14. route review;
15. evaluate Today/Pulse eligibility.

Each stage is idempotent and independently retryable where safe.

## W-07 — Review extracted commitment/decision

1. Review case identifies exact capture/version/span.
2. Reviewer sees original text, highlighted span, proposed structured value, candidate identities, model/rule version, risk, and downstream impact.
3. Allowed dispositions: Accept, Correct and Accept, Reject, Defer, Mark Unresolved.
4. Acceptance creates or updates the canonical object in one transaction with receipt/audit.
5. Rejection remains as evidence and may influence evaluation/training only if policy permits.
6. External action remains a separate command and authorization.

## W-08 — Edit source text

1. User opens Capture detail and selects Edit.
2. Saving creates a new CaptureVersion; prior version remains immutable.
3. Current version pointer advances.
4. Processing is queued for the new version.
5. Existing accepted assertions remain bound to their original version and become `revalidation_required` when materially affected.
6. System does not silently rewrite or delete prior accepted objects.
7. Reviewer can reaffirm, supersede, or detach them.

## W-09 — Correct extraction only

- User changes a participant, date, project link, or proposal without changing source text.
- Correction updates/provides the derived record, not the source.
- Original candidate, correction, reviewer, timestamp, and training eligibility are retained.
- Partial correction affects only the selected field and dependent proposals.

## W-10 — Delete/archive

- Default action is Archive, which removes the capture from ordinary views while retaining lineage/audit.
- Hard deletion requires a future operator-approved retention/privacy policy.
- Deleting a capture does not silently delete independently accepted downstream records; impact preview and explicit disposition are required.
- Source text may be cryptographically erased only under defined retention authority and with a tombstone/receipt that does not preserve sensitive content.

## W-11 — Processing failure

- Capture remains saved and searchable by exact original text.
- Status states: pending, processing, complete, partial, failed_retryable, failed_terminal, policy_denied.
- System provides retry only when safe.
- Failures are visible in Capture detail and System > Processing.
- Notifications contain no note content.

## W-12 — Search and reuse

- Exact search finds original text independently of extraction success.
- Results distinguish original Capture, Conversation event, summary, accepted assertion, Task, Commitment, Decision, relationship/project event, and Review proposal.
- Opening a derived result reveals its source span and capture version.
- From a Capture, user may create a Situation, link context, or open related accepted objects.
