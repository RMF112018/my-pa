# Capture withdrawal product contract v0.1

- **Work package:** CRL-WP-02; gap `CRL-CAP-001`; decision `PD-CAP-01`.
- **Status:** Accepted CRL-WP-02 product contract by explicit operator approval
  on 2026-09-30. This document does not describe implemented capabilities or
  authorize CRL-WP-03 runtime implementation.
- **Objective:** Define reversible, owner-scoped withdrawal of a Capture without
  rewriting source evidence, changing independently owned records, or authorizing
  deletion.
- **Repository basis:** `RMF112018/my-pa`, main commit
  `8940e60b75291ba39a725248303c37844a925016`, tree
  `4504fbe596d65b2b3a24585e6c836e03a16d2d20`.
- **Instruction basis:** The operator's 2026-09-30 instruction to implement
  “CRL-WP-02 — Capture withdrawal product contract in full through merge” authorizes
  this repository contract work. The operator subsequently approved the complete
  product meaning recorded in section 2, including then-current processing policy
  on restore. Neither instruction activates the later runtime implementation work
  package.

## 1. Authority, current truth and scope

The originating investigation is
`MYPA-CORE-RECORD-LIFECYCLE-SEMANTICS-GAP-INVESTIGATION-20260930-001`, dated
2026-09-30, published in Drive as `15JkqpFFI9patAIIOopszLr84n63m0L7D` under
Responses parent `1pibV2pqs-Ab4nnjk2SlGWttmZsN3lzUZ`. Its native published text
was retrieved for this contract; that establishes a source identity, not raw-byte
identity, and no source hash is asserted. Sections D1, G1/G2, H and I establish
Capture withdrawal intent and the choices resolved below. Section I separates CRL-WP-02
product-contract decisions from CRL-WP-03 implementation planning. The
investigation's historical `NONE` implementation authority is superseded only
for the present operator-authorized WP-02 documentation work, not runtime
implementation, deployment or risk acceptance.

[ADR-003](../decisions/ADR-003-product-owned-user-authored-source-records.md)
clause 3 already defines withdrawal as archive and forbids application deletion
or in-place rewriting of user-authored text.
[ADR-005](../decisions/ADR-005-principal-partitioned-capture.md) requires the
verified owning Principal for every Capture operation and makes foreign and
absent records indistinguishable. Both remain unchanged.

At the repository basis, Capture roots and content versions are insert-only;
the current content is the greatest version number, with no mutable root head
pointer. The public operations are create, revise, read, list and search.
Archive and restore are absent. Current search selects acknowledged current
versions, and processing stages have no archive awareness. These are current
facts, not evidence that the accepted behavior is already available. Source
anchors are `domain/capture/version.py`, `infrastructure/persistence/capture.py`,
`infrastructure/persistence/capture_search.py` and
`infrastructure/jobs/capture_pipeline.py`.

This contract covers root lifecycle state, owner partition, archive/restore
intent, read/discovery behavior, source-preserving concurrency and replay,
processing disposition, downstream disclosure and synthetic acceptance scenarios.
CRL-WP-03 must separately choose the smallest permitted physical metadata/history
mechanism, additive migration, application commands, policy/audit vocabulary,
MCP generation and tests. `capture.archive` and `capture.restore` below are
candidate contract names, not additions to a capability registry or grants.

Out of scope are hard delete, purge, retention expiry, managed-document writes,
source-provider writes, generic undo or lifecycle frameworks, other record
families, auth replacement, live personal data, runtime grants, frontend
implementation, deployment, production activation and risk acceptance. No schema,
code, tests, migration, ADR or repository policy is changed by this document.

## 2. Accepted product decisions

The operator approved the full Capture withdrawal product contract on 2026-09-30
in the controlling conversation. The ledger below paraphrases that approval; it
is not represented as a verbatim quotation. Appendix A preserves the exact
operator decision, which is the ratification instrument; the earlier investigation
and recommendations are evidence and are not that instrument. This closes `PD-CAP-01` for the
bounded withdrawal/restore product meaning while preserving ADR-003/005 and the
separate retention decision. Approval includes then-current processing policy on
restore, replacing the draft's saved-policy proposal. Runtime implementation,
physical schema and activation remain separately gated.

| Decision | Accepted product meaning | Authority and date |
|---|---|---|
| `CW-PD-01` | Archive is reversible withdrawal, not deletion, content revision, rollback or downstream invalidation. Archived roots leave default active discovery. New revisions are refused; new processing/derivation is paused, unfinished work is suspended and in-flight authoritative publication is fenced. Committed earlier results remain. | Explicit operator approval, 2026-09-30 |
| `CW-PD-02` | Owner restore makes the same root and existing latest content active. Discovery, revision and processing eligibility return under then-current processing policy and eligibility checks, ordinary idempotency, lineage and review rules. Eligible unfinished work can resume; completed durable results are not duplicated. No new source version or erased history results. | Explicit operator approval, 2026-09-30 |
| `CW-PD-03` | Previously accepted/promoted records retain their own identity, authority and lifecycle. Every surface exposing their Capture provenance can disclose current source withdrawal with exact version/span lineage. Archive/restore does not invalidate, delete, close or otherwise cascade into those records; their later disposition is separately authorized. | Explicit operator approval, 2026-09-30 |

Retention is not selected by this bundle. Existing evidence remains retained
under existing controls while the separate retention/privacy decision remains
open. No expiry or purge is introduced, and this is no approval of perpetual
retention. [Data authority section 9](../architecture/data-authority.md#9-deletion-retention-recovery-and-reversibility)
still requires a separately authorized basis for destructive erasure.

## 3. Root lifecycle and content invariants

- `CW-001`: Lifecycle belongs to one owner-scoped Capture root, not a single
  CaptureVersion, extraction, proposal or promoted record. States are `active`
  and `archived`. New and existing roots are logically active at lifecycle revision
  0 until a first lifecycle transition; any physical backfill belongs to CRL-WP-03.
- `CW-002`: The lifecycle revision is monotonic and independent of content version
  numbers and processing states. Each actual archive or restore increments it
  once. A same-state request is a receipted no-op and does not increment it.
  A content revision never resets or consumes the lifecycle revision.
- `CW-003`: Lifecycle metadata/history is append-only. A later restore records an
  inverse transition without removing the earlier withdrawal event. Physical
  tables, counter storage and transaction locks are CRL-WP-03 choices, not selected
  here. The existing insert-only root/content boundary is preserved.
- `CW-004`: Archive and restore append no content version, alter no exact text,
  hash, predecessor, classification, processing policy or evidence span, and never
  move the content head backward. Restore exposes the existing greatest version
  number. Blank text, sentinel text and a fabricated successor are forbidden
  representations of withdrawal.
- `CW-005`: The current archive timestamp denotes the transition into the current
  archived interval. A no-op archive retains it. Restore ends that interval in
  lifecycle history; a later real archive has a new interval timestamp without
  erasing the earlier one.

## 4. Commands, ownership, concurrency and receipts

- `CW-006`: Both candidate commands require a verified owning Principal, Capture
  root identity, expected lifecycle revision, idempotency key and nonblank reason.
  The reason records operator intent rather than fabricated external evidence.
  Authorization uses existing Capture authoring boundaries; no ordinary override,
  cross-owner action or hard-delete grant is introduced. An absent and foreign
  target produce the same not-found result without owner/state disclosure.
  Candidate policy intent is purpose `capture_authoring`, write operation,
  `additive=false` and `destructive_hint=true`; future compact routing is feature
  `capture`, kind `write`, with DATA_REQUIRED eligibility. These are future
  contract constraints, not registry, grant or runtime composition changes.
- `CW-007`: The digest represents normalized caller intent: owning partition,
  operation, root identity, expected lifecycle revision and normalized reason.
  Boundary whitespace is trimmed; a whitespace-only reason is refused; remaining
  Unicode text, including internal whitespace, remains significant without case
  folding or Unicode normalization. The trimmed reason must contain 1–500 Unicode
  code points; out-of-bound values are refused before admission. Generated times,
  event IDs and receipt IDs cannot enter the digest. The idempotency key identifies
  a request and is scoped per Principal; reuse for a different operation, target,
  revision or reason is a conflict. No raw reason or source content is exposed in the digest response.
- `CW-008`: After current ownership and policy checks, a valid same-key/same-intent
  replay returns the original receipt and original outcome, even if a later
  transition has occurred. It creates no event, timestamp, version or work.
  A historical replay receipt must not be presented as current lifecycle state.
  A fresh key requires the current expected lifecycle revision even for a no-op;
  stale requests conflict without effects.
- `CW-009`: Fresh archive(active) and restore(archived) apply one transition.
  Archive(archived) and restore(active), with a current expected revision, return
  an explicit no-op receipt. Receipts bind Principal, root, operation, original
  outcome, expected and resulting lifecycle revisions, relevant lifecycle event,
  server time, correlation and audit reference. No-op outcomes are not fabricated
  mutations, and lifecycle counters are not content version identifiers.
- `CW-010`: State observation, expected-revision validation, transition/no-op
  recording and idempotency receipt commit atomically. No successful outcome or
  APPLIED audit event may escape before that transaction succeeds. Failure rolls
  back every staged successful effect. Separately recorded, redacted denial or failure
  attempt audit events remain permitted and cannot claim a committed transition.
  A concurrent loser conflicts or replays the single committed receipt; it cannot
  append a second transition or fork history.
- `CW-011`: Archive and content revision serialize on
  the same root admission boundary. A revision committed first remains the latest
  immutable version when archive commits; archive committed first refuses revision
  until restore. A client never bypasses this boundary by supplying content-version
  numbers as lifecycle preconditions.

The semantic outcomes are `APPLIED`, `NO_OP`, replay of the original outcome,
`not_found`, invalid intent, policy refusal and conflict. Invalid intent includes
missing or malformed required values and a reason outside the normalized bound;
conflict includes stale expected lifecycle revision or a mismatched reused key.
Revision while archived is a policy refusal; processing/derivation is paused and
unfinished work is suspended rather than falsely reported as a successful no-op
or failed solely because of archive. Failed
operations have no successful transition effects. These are required behavioral
distinctions; CRL-WP-03 maps them to the existing error envelope and selects exact
transport/schema vocabulary without exposing foreign state or raw reason text.
No new concrete error code or public capability is declared here.

## 5. Discovery and targeted history

- `CW-012`: Default Capture list/search is active-only. An explicit lifecycle
  selector accepts `active`, `archived` or `all`; filtering occurs before totals,
  pagination and result ranking so archived or foreign records cannot leak through
  counts or page boundaries. `archived` and `all` opt into root lifecycle history
  visibility, not automatic enumeration of every content version. Existing
  acknowledged-current-content search eligibility still applies independently.
- `CW-013`: Authenticated owner-targeted root, version and chain reads remain
  available for archived Captures. Default targeted root reads resolve the current
  content head and disclose current lifecycle state, revision and archive interval;
  they do not silently omit a known archived root. Explicit historical version
  reads return that exact immutable version with the root's current withdrawal
  disclosure; historical lifecycle events remain distinguishable from current state.
- `CW-014`: Existing citations retain exact version identities, hashes and spans.
  Withdrawal is an additional provenance fact, not a claim that the text never
  existed, a span mismatch or a superseding source version. Consumers must label
  archived Capture provenance when displaying or using retained cited evidence.
  Ordinary discovery must not reintroduce archived roots through a derived search
  shortcut that presents them as active Capture results.

## 6. Processing and independently owned records

The following accepted requirements describe future behavior rather than current
processing and preserve the independently owned records already committed.

- `CW-015` (`CW-PD-01`): New extraction, enrichment, proposal generation, retry,
  promotion and all other derivation from archived source are paused, including
  new updates to an existing record based on that source. Unfinished work is
  suspended, not marked failed or discarded merely because of archive. In-flight
  computation may finish at an internal boundary, but no new authoritative effect
  may commit after archive commits: current root lifecycle eligibility is checked
  atomically at each admission/publication commit boundary. A result committed
  before archive remains recorded, with withdrawal disclosure. Archive is not
  permission to destroy staged work or erase prior attempt evidence.
- `CW-016` (`CW-PD-02`): Restore makes the same Capture identity eligible for
  discovery, revision and processing without a new source version or erased
  history. It does not recreate completed processing, admission receipts, proposals
  or independent records. Eligible unfinished work may resume under then-current
  processing policy and authorization/classification/eligibility checks, preserving
  existing version identity, idempotency, lineage and ordinary review rules. The
  immutable policy recorded on an earlier source version remains historical
  provenance; it does not bypass the then-current policy governing resumed work.
  Restore grants no cloud disclosure, model-training eligibility or automatic
  approval. A safe technical requeue may resume the same unfinished logical work;
  it must preserve provenance and prevent duplicate durable completed results.
  No scheduler, queue or worker design is selected in this contract.
- `CW-017` (`CW-PD-03`): Archive and restore never cascade state changes into
  previously accepted or independently promoted records, their links or histories.
  They remain usable under their own identity, authority and lifecycle contracts
  with source-withdrawal disclosure. Restore does
  not silently validate or reapprove their assertions. Any later disposition is a
  separate authorized operation on the independently owned record. Every surface
  exposing Capture provenance can disclose current withdrawal with exact
  version/span lineage. Withdrawal disclosure is resolved at
  read/projection time as current provenance metadata;
  immutable Report, Memory, source content and citation bytes are never rewritten
  to add it. After restore, current disclosure returns to active while historical
  withdrawal events remain available and distinguishable.

## 7. Audit, privacy and deferred retention

- `CW-018`: Lifecycle events/receipts bind intent and outcome through stable
  identifiers, correlation and audit references. Audit records use bounded,
  redacted metadata and safe outcome/reason categories; they contain neither Capture
  text, contact details nor raw free-text reasons. The digest binds the reason;
  any decision to persist its raw text requires a separately justified protected
  storage design in CRL-WP-03. Error responses disclose no reason from a prior
  request to another Principal.
- `CW-019`: Existing private-local classification, cloud-ineligible default and
  training prohibition remain. Archive is reversible withdrawal from ordinary use,
  not privacy erasure, retention expiry, external-source deletion or permission to
  access live personal data. Restoring preserves those protections.

## 8. Acceptance scenarios for CRL-WP-03

These are required future synthetic proofs, not tests run or supplied by CRL-WP-02.

| ID | Required proof | Requirements |
|---|---|---|
| `CW-AC-01` | Archive and restore retain every content version byte/hash, predecessor, exact citation span and latest version; neither appends a content version. Lifecycle 0 → 1 → 2 has separate history. | CW-001–005, CW-014 |
| `CW-AC-02` | Foreign/absent root reads and mutations are indistinguishable; owner-scoped active/archived/all list/search totals and pagination contain only eligible roots. | CW-006, CW-012–013 |
| `CW-AC-03` | Advancing the server clock changes neither replay digest nor receipt; same-key changed operation/target/revision/reason conflicts; distinct Principals do not share receipts. | CW-007–008 |
| `CW-AC-04` | Fresh same-state requests are honest no-ops without counter/timestamp reset; stale requests conflict; replay after inverse transition returns the original historical receipt without changing current state. | CW-005, CW-008–009 |
| `CW-AC-05` | Contention produces one transition/receipt; induced transaction failure commits no state, successful/APPLIED event or success receipt; separately redacted denial/failure attempt audit remains permitted. Archive/revise races preserve the accepted admission ordering. | CW-010–011 |
| `CW-AC-06` | Active-only default, explicit archived/all selection, targeted historical reads and retained citations disclose withdrawal without rewriting content or leaking foreign counts. | CW-012–014 |
| `CW-AC-07` | Queued/in-flight work cannot publish after an archive commit; earlier committed results remain. Revision while archived is refused; extraction, enrichment, proposal generation, retry, promotion and all derivation are paused. Unfinished work is suspended rather than failed/discarded. Commit/admission fencing covers new updates based on archived source. | CW-011, CW-015 |
| `CW-AC-08` | Restore uses the existing latest version and unfinished processing identity, does not duplicate completed work or autoapprove proposals, and applies then-current processing policy/eligibility with ordinary lineage, idempotency and review rules. Include a policy change during suspension that blocks previously eligible work. | CW-016 |
| `CW-AC-09` | Independently promoted records retain state/history/links through archive/restore and all provenance-exposing surfaces can disclose current withdrawal with exact version/span lineage without rewriting immutable bytes. | CW-017 |
| `CW-AC-10` | Receipts/audit/errors omit source text and raw reasons; archive/restore expose no hard-delete path or new disclosure authority. | CW-018–019 |

CRL-WP-02 acceptance requires this operator-approved contract, unchanged
ADR-003/005 boundaries, visible retention limits, repository documentation
validation and independently reviewed exact-head documentation before merge.
Product decisions are resolved by the recorded operator approval; CRL-WP-03
planning and runtime implementation remain separately authorized work. The future
scenarios above are acceptance obligations, not a claim of implementation or
executed runtime proof.

## Appendix A. Exact operator product decision

**Date:** 2026-09-30. **Context:** Direct operator message in the controlling
CRL-WP-02 conversation, following review of the concrete contract draft. The text
below is preserved verbatim from that message. The temporary coordination copy
used to reproduce it is not a separate authorization artifact. This decision
ratifies product semantics; the initial instruction separately authorizes bounded
WP-02 repository documentation delivery through merge.

<!-- BEGIN EXACT OPERATOR PRODUCT DECISION -->
## CRL-WP-02 Product Decision — Capture Withdrawal Semantics

**Decision:** APPROVED PRODUCT SEMANTICS

A Capture archive is an explicit, reversible withdrawal of that Capture from active use. It is not deletion, content revision, rollback, or retroactive invalidation of records previously derived from the Capture.

### 1. Archived Capture

While a Capture is archived:

- its immutable Capture and CaptureVersion evidence remains retained and retrievable under authorized historical/explicit access;
- it is excluded from normal active/default Capture list and search results;
- new Capture revisions are refused;
- new extraction, enrichment, proposal-generation, retry, promotion, and other derivation processing from that Capture is paused;
- pending unfinished processing is suspended rather than converted into failure or discarded merely because of archive;
- processing that has not yet committed an authoritative output must re-check Capture lifecycle eligibility before committing that output;
- archive does not alter the text, version chain, evidence spans, provenance, classification, or prior receipts.

Archive must not be represented by a sentinel CaptureVersion or by modifying source text.

### 2. Restore

Restore reactivates the **same Capture identity**.

Restore:

- does not create a new CaptureVersion;
- does not rewrite prior archive evidence;
- returns the Capture to normal active/default discovery;
- permits new revisions again;
- permits processing again under the Capture's then-current processing policy;
- resumes only processing that remains eligible and unfinished;
- must not duplicate already-completed proposals, accepted records, or other durable processing results;
- must continue to honor ordinary idempotency, lineage, policy, and review rules.

Restore is a lifecycle transition, not a content correction.

### 3. Previously promoted or accepted records

Archiving a Capture does **not** automatically archive, delete, cancel, void, retract, or otherwise mutate records previously promoted or accepted from that Capture.

Those records retain their own identity, authority, lifecycle, and correction rules.

However:

- their provenance remains bound to the exact CaptureVersion and evidence spans from which they were derived;
- any surface that exposes that provenance must be able to disclose that the source Capture is currently archived/withdrawn;
- an archived Capture cannot silently generate new promotions or updates to those records;
- if an already-promoted record itself needs withdrawal, correction, closure, cancellation, or other lifecycle action, that must occur through the lifecycle contract of that downstream record family.

Capture withdrawal therefore changes the **current usability of the source**, not the historical truth that a downstream record was previously derived or accepted from it.

### 4. Processing already in flight

Archive establishes a lifecycle gate.

Work that is merely queued or awaiting retry becomes suspended.

Work already computing may terminate normally at an internal boundary, but it must not commit a new proposal, promotion, or other authoritative downstream effect after the Capture has become archived unless that durable write was already committed before the archive transition.

The implementation must enforce this through current lifecycle state at the relevant commit/admission boundary rather than relying only on the state observed when processing began.

### 5. Search and historical access

Default Capture discovery represents the active working set and therefore excludes archived Captures.

Archived Captures remain accessible through explicit archived/history-oriented retrieval and direct authorized retrieval by identity. Their immutable versions remain available for lineage and audit.

Archive must not make previously valid evidence spans unverifiable.

### 6. Hard deletion and retention

This decision grants no hard-delete authority and does not resolve retention/privacy erasure.

Permanent destruction remains a separately governed decision.

### 7. Contract boundary

This decision does not create a generic lifecycle framework and does not change lifecycle semantics for Tasks, Commitments, Meetings, Entities, Relationships, Relationship Memory, Reports, or derived records.

It resolves `PD-CAP-01` only to the extent necessary to finalize the Capture archive/restore contract.
<!-- END EXACT OPERATOR PRODUCT DECISION -->
