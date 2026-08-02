# Source Authority and Provenance Model

Package: `MYPA-QUICK-CAPTURE-FEATURE-PACKAGE-20260801-005`
Coordination request: `REQ-MYPA-QUICK-CAPTURE-FEATURE-DEFINITION-20260801-081`
Date: 2026-08-01
Repository basis: `RMF112018/my-pa@40391b784ba7df2aa37f99fed86b0d4ac4723034`
Status: `PROPOSED_FOR_OPERATOR_REVIEW`
Implementation authority: `NOT_GRANTED`
Repository mutation: `NOT_PERFORMED`


## Authority classification

A saved Quick Capture is both:

- a **product-owned source record**; and
- **source-authoritative user evidence** for the exact text the user committed.

It is not automatically an authoritative statement that every described fact occurred. It authoritatively records what the user wrote, when the server received it, and the available client/launch metadata.

## Authority matrix

| Element | Authority state | Meaning |
|---|---|---|
| Original capture text | `source_authoritative` | Exact user-authored evidence |
| Capture/version identity | `canonical` | Product-owned identity |
| Server receipt timestamp | `canonical_observed` | Server’s durable acceptance time |
| Client/device timestamp | `observed` | Device-reported; may be wrong |
| Launch mode supplied by route | `observed/deterministic` | Exact client action, server-validated |
| Launch context | `deterministic` if valid | Context supplied by invoking object |
| User correction of source | new `source_authoritative` version | Does not erase prior version |
| User correction of extraction | `canonical` for corrected derived field after governed transition | Does not change source text |
| Inferred capture subtype | `inferred/proposed` | Noncanonical |
| AI summary | `derived/inferred` | Never replaces source |
| Extracted person/project/topic | `proposed` or `accepted assertion` | Based on spans and policy |
| Extracted commitment/decision | `proposed`, review-required | Consequential |
| Conversation channel/time | deterministic, proposed, or accepted | Must expose basis |
| Accepted assertion | `canonical` within product lifecycle | Retains source spans |
| Timeline event | `canonical` only after applicable transition | Retains capture link |
| Search index | `derived/cached` | Rebuildable |
| Pulse/notification selection | `derived` | Attention decision, not evidence authority |

## Time model

Maintain distinct timestamps:

- `client_created_at`: when device reports capture occurred;
- `server_received_at`: when durable server transaction accepted it;
- `recorded_at`: product event representing capture recording;
- `occurred_at`: when described conversation/event occurred;
- `processed_at`: when a processing stage ran;
- `proposed_at`: when a proposal was created;
- `accepted_at`: when a governed transition occurred;
- `indexed_at`: when search became available.

Do not substitute one for another. `occurred_at` may be unknown.

## Provenance envelope

Every derived/proposed/accepted item includes:

- capture ID and exact version ID;
- source text hash;
- one or more evidence spans;
- processing-text version and offset mapping when used;
- method type and exact rule/model/version;
- schema version;
- prompt hash where a model was used;
- context manifest and retrieval inputs;
- processing timestamp;
- policy decision/version and processing destination;
- calibrated confidence where meaningful;
- limitations, unresolved identities, and conflicting evidence;
- review/acceptance identity and receipt;
- supersession/invalidation lineage.

## Span contract

### Canonical basis

- Source text is decoded as UTF-8 by the API contract.
- Offsets use Unicode code points under `unicode_code_point_v1`.
- End offsets are exclusive.
- Spans also include line/column and a quoted-text hash.
- Server validates quoted text against the immutable source version.

### Normalization

Processing may create a separate normalized representation but must retain a mapping to original offsets. No proposal may cite only normalized text.

### Multiple spans

A proposal may use:

- one direct span;
- multiple discontinuous direct spans;
- contextual spans;
- counterevidence spans.

Example: a commitment may require the promise phrase, person mention, and due-date phrase.

## Versioning and supersession

- Editing creates a new capture version.
- Old proposals remain bound to old versions.
- New processing does not overwrite old attempts.
- Accepted downstream records supported by superseded text enter `revalidation_required` when the relevant span materially changed.
- Reaffirmation creates a new support link/receipt.
- Rejection or withdrawal does not erase historical evidence.

## Receipts

### Capture receipt

Generated in the save transaction and records:

- capture and version IDs;
- idempotency key hash;
- source text hash;
- server receipt time;
- classification and processing policy;
- initial context link results;
- processing job/outbox ID;
- correlation ID.

It does not copy the note body.

### Promotion receipt

Records:

- proposal and exact source identity;
- prior and resulting object versions;
- reviewer/authority;
- disposition;
- downstream effects;
- audit references.

## Trust presentation

User-visible labels:

- Original capture
- User-authored private note
- Device-reported time
- System receipt time
- Inferred
- Proposed
- Accepted
- Corrected
- Contradicted
- Stale
- Unavailable
- Superseded

Confidence does not replace these authority labels.
