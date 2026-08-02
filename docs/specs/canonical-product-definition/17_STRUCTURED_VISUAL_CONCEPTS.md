---
title: my-pa — Reconciled Structured Visual Concepts
artifact_id: VISUAL-CONCEPTS-MYPA-CANONICAL-002
artifact_type: Structured wireframes
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

# Reconciled Structured Visual Concepts

Implementation-neutral structures defining hierarchy, state, authority, and workflow.

## 1. Canonical shell

```text
┌──────────────┬───────────────────────────────────────┬──────────────┐
│ Today        │ Today                         Reveal⌕ │ Evidence     │
│ Situations   │                               Capture+│ Coverage     │
│ Review   3   │ Pulse                                  │ Sources      │
│ Library      │ 1. Steel lead-time commitment at risk │ Unknowns     │
│ System       │ 2. Relationship follow-up due         │              │
│              │ 3. Capture sync conflict              │              │
└──────────────┴───────────────────────────────────────┴──────────────┘
```

## 2. Desktop Quick Note

```text
┌──────────────────────────────────────────────────┐
│ Quick Note                                  [×]  │
│ [Project: Riverfront Tower ×]                    │
│ ┌──────────────────────────────────────────────┐ │
│ │ Water visible at north stair after storm.   │ │
│ │ Ask waterproofing contractor to inspect.    │ │
│ └──────────────────────────────────────────────┘ │
│ Private · Local processing       [Save Note]    │
└──────────────────────────────────────────────────┘
```

## 3. Mobile Conversation Log

```text
┌──────────────────────────────┐
│ Conversation Log       [×]   │
│ ┌──────────────────────────┐ │
│ │ Called Jordan. I will    │ │
│ │ send revised buyout Fri. │ │
│ │ Jordan will confirm      │ │
│ │ steel lead time.         │ │
│ └──────────────────────────┘ │
│ Private · Draft protected    │
│ [        Save Log         ]  │
└──────────────────────────────┘
```

## 4. Offline saved

```text
✓ Saved on this device
Sync pending
Encrypted local capture. Reopen after connecting.
[Close] [Retry]
```

No server receipt is claimed.

## 5. Sync conflict

```text
Sync needs review
Local version and server version differ
[Open local] [Open server]
[Keep unresolved] [Create new version]
```

No last-write-wins.

## 6. Capture detail

```text
Library/Captures | Conversation Log · Saved | Authority
Original text v1                           | User-authored
Suggestions: Jordan [identity?]            | Receipt/hash
2 commitments [review]                     | Processing/policy
1 decision [review]                        | Receipt
[Review] [New version]
```

## 7. Conversation detail

```text
Conversation · Aug 1 · Phone? · Riverfront Tower
Jordan Lee (?)
Summary — inferred
You → Send revised buyout · Fri · Needs review
Jordan → Confirm steel lead time · Needs review
[Original capture] [Review]
```

## 8. Library

```text
Captures / Notes
[Search][Project][Relationship][Status][Privacy]
4:31 Water at north stair…  Project suggested
3:10 Simplify weekly…       Ready

Captures / Conversations
[Search][Person][Project][Channel][Review]
Aug 1 Jordan Lee (?) Phone? 2 commitments need review
```

## 9. Relationship workspace

```text
Jordan Lee · Turner Steel
[Capture conversation]
You owe: Revised buyout · Fri
Owed to you: Confirm steel lead time
Timeline: Aug 1 Conversation; Jul 28 Meeting
Private observation [user-authored]
Evidence/Coverage/Contradictions
```

No score or sentiment meter.

## 10. Identity Review

```text
Source “Called Jordan…” | Candidates | Impact
Capture v1              | Jordan Lee | Relationship
                        | Jordan Smith| Commitments
                        | Create new  | Project timeline
                        | Unresolved  |
[Reject][Defer][Accept]
```

## 11. Project Trace

```text
Aug 1 4:05 · Conversation
Steel lead-time confirmation requested
Source: user-authored Conversation Log
Commitments: pending review
[Evidence][Conversation]
```

## 12. Relationship timeline

```text
Aug 1 · Conversation · accepted
You owe revised buyout; Jordan owes lead-time confirmation
[Evidence][Open conversation]
Pending concern/preference [Review]
```

## 13. Commitment Review

```text
Original evidence | Proposed Commitment | Impact
“…I will send…”  | Obligor: You         | Today
highlighted       | Counterparty: Jordan?| Relationship
Capture v1        | Due: Aug 7           | Project
[Reject][Defer][Correct][Accept]
```

## 14. Decision Review

```text
Evidence/counterevidence | Proposed Decision | Impact
exact spans/versions     | Alternatives       | Schedule/Cost
unavailable sources      | Effective date ?   | Project Trace
[Reject][Defer][Correct][Accept]
```

## 15. System processing

```text
Capture queue 2 waiting · 1 retryable
Offline sync 1 pending · 1 auth blocked
Search current through 4:31 PM
Model local only · Cloud disabled
Review 3 high consequence · 6 low priority
[Open failure][Retry][Policy]
```

## Responsive/accessibility

Desktop may use three panes; tablet one canvas plus drawers; mobile full-height Capture and focused Review. Focus returns to invoking control after save. High contrast/reduced motion preserve semantics. No content appears in telemetry.

## 16. Connected Clients

```text
System / Connected Clients
[Safe mode: off] [Read: enabled] [Write: disabled] [Global: enabled]
Client                  Profile status   Authorization   Health      Last activity
ChatGPT                 Unverified       None            —           —
Claude                   Unverified       None            —           —
Grok                     Unverified       None            —           —
Synthetic reference     Verified/local   Read fixture    Ready       10:42
```

## 17. Client Grant Detail

```text
Client: Synthetic reference / profile hash ...
Actor: owning principal
Purposes: source_inspection, knowledge_retrieval
Capabilities: sources.list, sources.fetch, knowledge.search, knowledge.read
Side effects: read_only
Source scopes: fixture enrollment enr_...
Managed roots: none
Classifications: [eligible synthetic]
Expires / revoke / reauthorize
[Save narrower grant] [Revoke]
```

## 18. Invocation Trace

```text
Invocation inv_...  RESULT: partial
Actor / Client / Session reference
Capability + semantic version + schema hash
Purpose / scope / policy version + decision
Evidence disclosure: coverage, freshness, authority, unavailable items, limitations
Audit event audit_...
Receipt: none (read)
[Open source lineage] [Open System health]
```

## 19. Managed Mutation Receipt

```text
Receipt rcpt_...  managed.files.update@1
Actor / client / purpose / policy
Document mdoc_...  expected mver_7 -> created mver_8
SHA-256 / bytes / classification / lineage
Prior version recoverable: yes
Idempotency result: original request
Audit event audit_...
[Open document] [View versions] [Archive]
```

## 20. Revocation and Safe Mode

```text
Connected client degraded: refresh revoked
Capabilities withdrawn: all
No in-flight mutation committed after revocation boundary
[Reauthorize] [Keep disabled]

Safe mode
Read [on/off]  Write [on/off]  Global [on/off]
Consequence preview + required reason
[Activate] -> policy version + audit event
```

All concepts preserve first-party authority, keyboard/accessibility requirements, redacted identifiers, no raw tokens or physical paths, and explicit distinctions among source read, managed write, and product-owned Capture.

