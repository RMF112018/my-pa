# Capture lifecycle implementation plan — CRL-WP-03

- **Status:** Planning deliverable, 2026-09-30; runtime work is not authorized by this plan.
- **Objective:** Plan one complete, reversible Capture withdrawal slice implementing
  the accepted [Capture withdrawal contract](../specs/capture-withdrawal-v0.1.md),
  `CW-001`–`CW-019` and `CW-AC-01`–`CW-AC-10`, without changing content evidence or
  independently owned records.
- **Repository:** `RMF112018/my-pa`, planning base
  `fa07ac064561fbbd397da5a796015519ee312ce7`, tree
  `1ac2bac19d45346d479005451d49abfe9b83d335`; branch
  `bf/capture-lifecycle-plan`.
- **Authority:** The operator authorized CRL-WP-03 implementation planning after
  approving `PD-CAP-01` and merging the CRL-WP-02 contract. Planning selects the
  bounded design and verification obligations below; it grants no runtime,
  migration execution, capability activation, grant, deployment or data authority.

## 1. Planning acceptance and boundary

A complete planning deliverable must identify current source behavior, the selected
persistence and concurrency design, all known publication and disclosure seams,
transport/policy contracts, an implementation dependency graph, and a requirement
matrix with synthetic proofs. It must distinguish inspected facts from proposed
behavior and unperformed tests. Independent exact-head review and applicable
repository document checks are required for this planning change.

The future implementation slice includes domain lifecycle values, two additive
PostgreSQL tables, one Alembic revision, Capture archive/restore commands, lifecycle
read metadata and discovery selectors, current eligibility resolution, nonfailure
job suspension, every Capture-derived admission/publication fence, provenance read
projections, and their synthetic tests. No public lifecycle capability may be
exposed while a known publication sink or provenance surface remains unclassified
or uncovered. Internal phases may be integrated together behind the existing
composition boundary; partial integration is not acceptance of a usable slice.

Out of scope: generic lifecycle frameworks; new services, queues, databases or
dependencies; frontend work; policy editors; cloud processing; source-system
mutation; credentials or grants; deployment or production; existing/shared database
access; personal data; retention or hard deletion; and lifecycle changes to Tasks,
Commitments, Meetings, Entities, Relationships, Memory, Reports or derived records.
Independent downstream correction remains governed by its existing contract.

The contract's exact operator decision remains authoritative, particularly restore
under **then-current processing policy**. No new CaptureVersion, sentinel text,
backfill or mutation of source evidence is an acceptable lifecycle representation.

## 2. Source basis and current-versus-proposed inventory

Paths below are relative to the repository. Line numbers are inspection anchors
at the stated base, not promised stable interfaces. Source paths are beneath
`src/my_pa`; shorthand `persistence/` means `infrastructure/persistence/` and
`jobs/` means `infrastructure/jobs/`. Migration paths are repository-relative. They must be refreshed before
implementation. This bounded investigation is not a claim of runtime closure.

| Current seam | Verified current behavior | Proposed change |
| --- | --- | --- |
| `infrastructure/persistence/tables.py:1034`, `capture.py:320,460,486` | Root plus immutable version chain; latest version derived by maximum version number; no root lifecycle state. Revision does not lock the root. | Append-only lifecycle history; absent history means active revision 0. Serialize revise and lifecycle writes on owner root. |
| `capture.py:557,599`, `capture_search.py:226,501,546` | Owner-targeted reads, list, search eligibility/page/totals exist. | Active default and explicit archived/all selectors applied before totals, ranking, pagination and coverage. |
| `contracts/v1/capture.py`, `application/commands.py:1178–1349` | Version/content receipts and Capture list/version DTOs; no lifecycle commands/receipt. | Separate lifecycle command/receipt types and current-state read overlays. |
| `adapters/normalization.py:516–540,2401`, `adapters/mcp/tools.py:152,218,258` | Canonical/compact normalization and schema generation use existing Capture shapes. | Strict archive/restore mapping; no arbitrary operation or delete vocabulary. |
| `application/service.py:4556–4740,11480–11581,13144` | Capture handlers, admission and dispatch exist. | Lifecycle use case, receipt replay and consistent safe translation; revise admission fence. |
| `domain/identity/operation.py:74–87,1030`, `domain/identity/chatllm_capability_policy.py:53–57` | Capture authoring purpose and DATA_REQUIRED boundary exist. | Register lifecycle writes with same boundaries; no runtime grant activation. |
| `infrastructure/jobs/capture_pipeline.py:879–952,1089` | Nine stages commit separately, assert job lease before writing, use saved local-only policy; completed stage identities are reused. | Root lock before lease; current eligibility at every stage commit and completion. |
| `persistence/jobs.py:262,345,494,524`, `jobs/worker.py:225–275` | Four stored job states; normal handler return succeeds, error release spends retry budget and can fail. | Capture-only suspension overlay plus neutral interruption, never normal success or failure for withdrawal. |
| `domain/capture/version.py:68`, `application/service.py:11523` | Saved policy has LOCAL_ONLY ceiling; no then-current eligibility resolver. | Resolve immutable ceiling intersected with current authorization and runtime configuration at each admission. |
| `migrations/versions/20260927_7d9a450dfd07_meeting_records.py` | Sole inspected migration head `7d9a450dfd07`, predecessor `6f6ead27d122`. | Generate next revision only after current-head authentication; freeze revision-local DDL. |

Existing Capture immutability trigger is in revision `1a4c9e77b2d5`; append-only
labels are in `c1a8e4d70b29`. Preserve both. Do not rewrite historical migrations
or import live tables/enums into their frozen DDL. Add owner-root composite
uniqueness if necessary for new same-owner foreign keys without changing root
identity or existing version contents.

PR #297 was an open draft at planning inspection, head `953695a…`; it carries
unlanded event/changefeed work. This plan does not depend on it. Authenticate its
full head and main again before execution; if it merges, refresh admission/audit
seams rather than assuming this plan authorizes a rebase with changed contracts.

## 3. Selected minimal persistence design

Create `knowledge.capture_lifecycle_events` and
`knowledge.capture_lifecycle_receipts`. No mutable lifecycle column, lifecycle
version of source text, third job table or backfill is required. The new revision also adds the Capture-only lease-generation
and bounded pause-diagnostic columns required in section 5; initialize existing rows to generation 0 without
changing content or their processing result identities.

Events contain an event identifier, owner Principal, root Capture ID, positive
lifecycle revision, operation (`archive` or `restore`), resulting state, predecessor
event/revision, server transition time, normalized intent digest, correlation ID,
audit reference and bounded reason category. Persist no raw free-text reason.
The latest event yields current state/revision; no events yields active/0 with
null archive timestamp. The current archived timestamp is the most recent archive
transition time while currently archived, and null when active. Older transition
times remain historical evidence.

Receipts contain receipt identifier, Principal-scoped idempotency key, root,
operation, intent digest, expected and resulting lifecycle revisions, original
`APPLIED` or `NO_OP` outcome, relevant event reference (nullable at active/0),
original server issue time, correlation and audit reference. A replay marker is
response metadata; the original outcome and receipt identity/time remain unchanged.
A no-op records a receipt, not a lifecycle event, counter increment or reset time.
A receipt must never be used to derive the current lifecycle state.

Database requirements:

1. Unique `(owner_principal_id, capture_id, lifecycle_revision)` on events and
   `(principal_id, idempotency_key)` on receipts. Keys bind exact owner/root and
   valid identifier shapes, not transport-provided alternate ownership.
2. Composite same-owner root and event references; event predecessor binds the
   same root/owner. Positive event revisions; operation/state consistency;
   revision 1 archives active/0; later events are contiguous and alternate state.
3. Deferred consistency checking, or equivalent trigger-enforced insertion
   invariant, verifies predecessor revision and alternation against committed
   history. Root serialization is required even with these constraints.
4. Append-only UPDATE/DELETE refusal triggers on both new tables, including
   direct SQL tests. Receipts require honest outcome/event/revision consistency.
5. Index latest owner/root revision and receipt lookup. Use existing identifier,
   digest, timestamp, redacted audit and principal-scope conventions.
6. Do not cascade lifecycle transitions into content, labels, spans, receipts,
   accepted records or immutable outputs. Foreign-key definitions must not create
   an ordinary deletion path for retained lifecycle evidence.

Migration tests must prove empty-to-head and predecessor-to-new-head upgrades,
including existing synthetic roots with no events remaining active/0. Exercise
constraint violations, foreign owner/root/event references, append-only triggers,
and both operation/no-op receipt shapes. Preserve earlier chain reproducibility.
The downgrade must **refuse to drop populated append-only lifecycle evidence**.
An empty-schema downgrade can remove the new objects in reverse dependency order.
Application rollback retains evidence; disabling entry points alone is insufficient.
A future activation requires operator-gated drain/quiescence and runtime identity
proof that all writers/workers enforce lifecycle and lease generation. Rollback
must use a forward-compatible corrective build and must not restore an old writer that bypasses lifecycle fences against archived roots.
Destructive populated downgrade requires separate operator authority and is not a
recovery mechanism authorized here.

## 4. Transaction protocol and lock order

Every operation resolves ownership from persisted roots/versions under current
verified Principal and policy. Do not disclose foreign existence or lifecycle.
Shared lock order for affected paths is:

`owner-scoped Capture roots sorted by Capture ID FOR UPDATE`
→ entity/relationship scope locks → review/proposal/work rows → job rows.
Receipt insertion follows the acquired lock set and atomic effect staging.

Each stage transaction first resolves its complete Capture root and downstream
scope set. It locks sorted roots, then any entity/relationship scopes and
review/proposal/work rows, then calls `hold_lease` at the final job-lock tier before
writes. A stage without downstream scopes uses roots → job directly. Never take
a job lock and later request an entity or review lock. Claim, completion, neutral
pause, release and reaping follow the same total order for the Capture plane;
claim/reap use roots → jobs and acquire no later downstream scope locks. Batch claim/reap first discovers bounded candidate roots,
locks them in sorted order, then locks jobs and revalidates the candidate set;
changed roots cause rollback/restart. Do not hold a job row and then request a root held by archive.
The existing enrollment plane keeps its behavior.

For multiple evidence inputs, discover the owner-scoped Capture root set without
locking, acquire sorted roots, then acquire existing downstream locks and revalidate
that the source/evidence set is unchanged. A newly discovered earlier root forces
rollback and bounded restart; never extend the lock set out of order. Multi-owner
or unresolved input fails closed. Computation occurs outside long transactions;
actual effect transactions re-resolve input roots and eligibility.

Lifecycle transaction sequence:

1. Perform current request policy/write/purpose checks and owner-root lookup.
2. Lock the root and resolve latest lifecycle event.
3. Look up Principal/key receipt and compare canonical intent. Valid replay returns
   the historical original receipt **before** fresh expected-revision checks,
   after current authorization. Mismatched intent conflicts without effects.
4. For a fresh key, require the current expected lifecycle revision even for a
   no-op. Archive(active) or restore(archived) appends one event; a same-state
   request appends no event. Generate times and identifiers only for durable work.
5. Stage transition, neutral job interruption if applicable, receipt and successful
   audit evidence in the same unit of work. No APPLIED event escapes before commit.
6. Insert receipt with PostgreSQL `ON CONFLICT DO NOTHING RETURNING`. Different
   roots can compete for one Principal/key despite root locks. On collision read
   the committed winner, compare intent, and rollback losing transition, audit and
   job effects before replay/conflict response. Do not catch an IntegrityError and
   continue in an aborted transaction. A same-root loser replays or conflicts.
7. Commit together; injected failure leaves no successful event, receipt, job
   adjustment or APPLIED audit. Redacted failure-attempt audit may be separate.

Digest canonicalization binds Principal, operation, root, expected revision and
reason trimmed only at boundaries. Preserve internal whitespace, case and Unicode
code points; 1–500 trimmed code points required. Generated clock values and IDs
never enter the digest. Select exact encoding: UTF-8 bytes of
`json.dumps(intent, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)`,
then SHA-256 lowercase hexadecimal. The intent mapping has exactly
`principal_id`, `operation`, `capture_id`, `expected_lifecycle_revision` and
`reason` keys, with validated typed string/integer values and the boundary-trimmed
reason. It excludes idempotency key, generated timestamps and identifiers. Perform
no Unicode normalization. Freeze exact digest test vectors. The raw reason is `repr=False`, consumed for
digest validation, then discarded; neither error details nor receipts reveal it.

Revision uses the same root lock. If revision commits first, archive preserves the
new latest version; if archive commits first, fresh revision is refused until
restore. Lifecycle revision is never accepted as a content version number.
Existing exact content-write replay retains its historical receipt under current
authorization; it does not admit new content while archived.

## 5. Durable nonfailure suspension and current policy

Select a **Capture-only lifecycle overlay on the existing capture_jobs rows**.
No new stored global JobState or scheduler is needed. Add a Capture-only
`lease_generation` bigint column to `capture_jobs`, initially 0, monotonically
incremented on every claim and revocation. Carry it in each leased Capture job
and compare it on every stage/publication admission, hold, completion and release.
Existing owner-only checks are insufficient: restore may reclaim under the same
owner and refunded attempt number. Generation is independent of retry budget and
receipt identity; enrollment behavior remains unchanged. The lifecycle event is the
durable suspension cause, and existing operation/version/stage identities remain.

On an APPLIED archive, within the same root-locked transaction, lock that root's
unfinished Capture jobs. Queued/retry rows retain their identity, due time, attempt
budget and diagnostics. Running rows have their lease revoked (generation increments), become queued, and
have the interrupted claim's attempt count reduced once (never below zero).
Preserve completed stage results, retry schedule and prior genuine errors. Preserve any immutable attempt evidence; a bounded interruption category and
generation distinguish the interrupted claim from earlier genuine failures. The
refund neutralizes withdrawal's interruption; it does not refund earlier failures.
Already succeeded/failed jobs are unchanged. A same-state no-op neither revokes
again nor refunds again. An old generation cannot publish, complete or release a newer generation even
when the worker owner and refunded attempt count are identical. A worker whose
publication committed before archive keeps
that result; its remaining unfinished work is suspended.

Owner status projection reports effective `suspended` for current-ineligible
unfinished work (including active-root policy pause), and with bounded cause
`capture_withdrawn` for unfinished archived work before lease-expiry/abandoned
failure derivation. Claim and reap exclude archived roots, including a final-attempt
running job. Capture claim must root-lock and revalidate eligibility before taking
the job lock/incrementing attempts. The archive transaction's queued reset also
makes a crash during suspension safe: there is no live lease or spent final attempt
that restore will accidentally reap as archive-caused failure.

Introduce a small Capture-specific paused control result/exception recognized by
the existing worker loop. It must not fall through normal completion or generic
failure release. Each stage commit resolves and locks its complete source and
downstream scope set in section 4 order, checks current eligibility, and verifies
owned generation/lease at the final job-lock tier before writing. Final job
completion uses root → job and the same generation check. A revoked lease
produces no write. An
actual policy pause uses an idempotent neutral pause under owned root/job locks,
with the same bounded interruption refund and distinct safe cause. Add a nullable,
Capture-only bounded `pause_cause` diagnostic column (`capture_withdrawn` or
`current_policy_ineligible`) to `capture_jobs`, distinct from `last_error_code`.
The root remains active on current-policy pause; claim still resolves current
eligibility and skips it until eligible. Preserve pause evidence until a successful
new eligible claim clears current diagnostic state, without erasing prior attempt
evidence. Do not write a failure error or dead-letter timestamp for policy pause. No spinning
claims, unrestricted retry or false succeeded outcome is acceptable.

Current eligibility is a bounded function in existing application/persistence
composition, not a policy framework. It combines:

- current lifecycle active state;
- immutable version classification and saved processing-policy ceiling;
- current owner authorization and ordinary purpose/write/model eligibility;
- current runtime local-processing enablement and available supported configuration;
- existing lineage, lease, review and stage idempotency requirements.

There is only LOCAL_ONLY today. A saved local-only permission never implies cloud
eligibility, and restore adds no cloud/training authority. Read then-current
configuration at admission/publication, without editing saved policy bytes.
Update the conflicting current-state comment at `capture_pipeline.py:902`: saved
policy remains immutable ceiling/provenance, while the accepted successor contract
also requires then-current eligibility. Preserve historical D-95 decision text;
append a contract-bound successor interpretation where necessary. If an
immutable ceiling and current policy disagree, deny/pause the new effect safely.
No policy editor or cloud implementation is in scope. A synthetic controlled
configuration/authorization change during suspension proves the intersection.

Restore appends the event and makes the same unfinished queued operations eligible
for the existing bounded claimant. It does not blindly create jobs, replace
operation IDs, resurrect terminal failures, replay completed stages, autoaccept
proposals or duplicate completed outputs. Current-ineligible unfinished work stays
paused with a distinguishable current-policy cause. Stored retry times still apply.
If policy changes later, normal eligible claiming resumes the same unfinished job;
completed unique stage/result identities remain the duplicate-prevention boundary.

## 6. Publication closure ledger

Before capability exposure, implementation must census every Capture foreign key,
version/span reference, encoded origin and source-reference triple in current
metadata and code. Trace each to authoritative sinks and provenance read surfaces.
Every entry needs either a tested commit/admission fence or a tested classification
as independent correction, historical read, or separate source. A search hit or
this planning inventory alone is not a proof of closure.

| Path / source reference | New-effect treatment and required proof |
| --- | --- |
| `persistence/capture.py:320,460` admission, chain, root/version/labels/context/receipt outbox | Revision locks root and requires active. New Capture creation remains ordinary admission; supplied related context references must not bypass direct archived-source derivation rules. Content replay is historical. |
| `jobs/capture_pipeline.py:879,952,1089` processing text, matches, spans, classifications, mentions, proposals, review cases, stage results | Root-first eligibility and lease fence on validation and every stage effect transaction; no authoritative processing output after archive commits. Completed prior stage keys survive. |
| `persistence/review.py:222,323,365` assertion/span/receipt/proposal state | Accept/promotion and new derived update resolve proposal version/span root and fence in same transaction. Historical rejection/defer bookkeeping is independently classified and must generate no derived promotion. |
| `application/entity_governance.py:433,471,587,784,961,1396` | Proposal, offered evidence, acceptance, ingestion and promotion resolve all direct/transitive Capture sources; gate new effects before authoritative commit. |
| `persistence/entity.py:3806,4147,4569,4876,4982` | Observations, facts, proposals and evidence copy/merge sinks covered by actual source inputs; preserve independent records. |
| `infrastructure/persistence/entity_authoring.py:1107,1141` | New offered span/version evidence is fenced; ordinary correction using unchanged historical evidence is separately tested as independent. |
| `domain/relationship/governance.py:298` encoded `src_productownedcapture` and reprefixed root/version suffixes | Resolve origin triples, not only SQL foreign keys; detect malformed/foreign unresolved references fail closed. |
| `application/relationship_memory.py:585`, `persistence/relationship_memory_proposals.py:112,160–198` | Proposal observations/spans/external refs include transitive Capture origins; gate new proposal or update based on withdrawn source. |
| `persistence/relationship_memory_review.py:483,534,673,806` | Review promotion, reprocessing and copied evidence lock source roots before entity/proposal locks; new-effect fence covers authoritative Memory output. |
| `application/context/providers.py:414,433–503`, `context/service.py:151`, `persistence/context_runs.py:27,69` | Active-only selection plus locked revalidation before publishing a new context manifest carrying direct Capture text/version input. |
| Retained/frozen context manifest used as input to a NEW result | Resolve embedded direct Capture inputs and fence new derivation. Freezing earlier context does not freeze future source eligibility. Existing context/report artifact remains historical and readable. |
| `infrastructure/jobs/reenrichment.py:411,429`, `persistence/entity_reenrichment.py:227–320`, `application/entity_reenrichment.py:418` | Existing observation `entity_id` / resolution-version rebinding to merged-entity survivor is independent lineage correction, not new Capture extraction. Test exemption and byte/span preservation. Any text-consuming new callback must fence its actual write inputs. |
| Task/Commitment or other accepted record carrying Capture provenance | Archive does not mutate record state/history/links. Existing downstream correction/lifecycle remains independent; attaching new archived-source evidence or generating a new derived effect must fence. |
| `application/goodnotes_gsqs_remote_eval.py:310,357–386` | Filesystem evaluation `CaptureEntry` is a separate synthetic evaluation source, not `knowledge.captures`; test/classify excluded. No evaluation redesign. |
| `persistence/native_sources.py:289,750,768,922` | Native source envelopes/versions are separate source authority, not Product Capture. Exclude with source-identity proof; do not change native lifecycle. |

A source set carrying only historical provenance on an independently accepted
record does not make ordinary correction unusable. Conversely, a retained source
text/version reused to produce a new assertion is current derivation regardless
of whether it arrived through a manifest or accepted record. Tests must distinguish
these cases at actual commit sinks. No broad invalidation of old outputs is allowed.

## 7. Discovery and provenance disclosure closure

Use a typed selector `active | archived | all`, default `active`, on Capture list
and search. Apply owner partition and lifecycle eligibility before total counts,
ranking, page boundaries and coverage. Search can retain immutable index rows;
withdrawal changes eligible rows, not source bytes. Cursor binding includes owner
and selector and rejects mismatched reuse without foreign counts.

Direct authorized reads by Capture identity, version and chain remain available
in any state. Explicit archived/all search/list does not weaken purpose or privacy
requirements. Return current lifecycle state, revision and archive timestamp as
read metadata; targeted history additionally returns ordered lifecycle events.
A lifecycle receipt's historical outcome is clearly distinct from current state.

Implement current provenance overlays on all actual provenance-exposing surfaces:

| Surface census seed | Read obligation |
| --- | --- |
| `contracts/v1/capture.py` version/list and search/processing DTO projections | Current root state and lifecycle revision; explicit history remains retrievable. |
| `persistence/reveal.py:104,160`, `contracts/v1/reveal.py:67` | Reveal span/proposal/assertion/receipt exact lineage plus current withdrawal. |
| Capture proposal and review case reads | Exact CaptureVersion/evidence and current lifecycle, including archived pending proposals. |
| `persistence/entity.py:6670,6715,6729` | Evidence/fact/assertion/proposal source references disclose current withdrawal. |
| Memory proposal/review/version evidence projections | Preserve immutable Memory bytes, add current source metadata outside them. |
| Context providers, prepared/run projections, persisted manifests | Retained manifest citations disclose current withdrawal without rewriting frozen manifest bytes. |
| Implemented Report, Memory and citation projections exposing Capture refs | Resolve each owner-authorized Capture root at read/projection time; no immutable body rewrite. |
| Downstream Work record origin/provenance views | Current withdrawal disclosure where Capture provenance is exposed; record state unchanged. |

Refresh this surface census from serializers/contracts/handlers, not table names
alone. A response exposing no provenance needs no fabricated source payload.
Unresolvable or unauthorized references expose safe unavailable metadata rather
than foreign state. Batched owner-scoped resolution prevents per-item broad reads.
Current disclosure becomes active on restore while prior lifecycle events remain
historical. Span IDs, offsets, hashes, original text and version predecessors stay
verifiable throughout archive and restore.

## 8. Public transport, policy, errors and audit proposal

Select canonical capabilities `capture.archive` and `capture.restore`; separate
strict `ArchiveCapture` / `RestoreCapture` commands contain `capture_id`,
`expected_lifecycle_revision` (strict integer >=0, explicitly rejecting booleans
in both DTO validation and public schema), `idempotency_key` and `reason`.
Owner identity is verified session context, never a caller field. No text or
content-version fields are accepted. Reason normalization/bounds follow section 4.

Compact routing selects feature `capture`, kind `write`, operation `archive` or
`restore` and the same fields. Canonical MCP schema generation derives the exact
strict shapes; canonical/compact normalization must produce identical command
intent and policy flags. Unknown properties and delete-like aliases are refused.
Transport schemas do not by themselves activate a capability or grant.

Both operations use purpose `capture_authoring`, write semantics,
`additive=false`, `destructive_hint=true`, DATA_REQUIRED eligibility, ordinary
verified-session/grant checks and existing privacy guards. Read/history selectors
retain existing Capture read purposes. Add to registry/dispatch/remote/compact
catalog and schema consistency tests only after full slice closure. No external
source-provider write method, grant activation or production composition change.

Lifecycle response DTO contains receipt ID, Capture ID, operation, original
outcome, expected/resulting revisions, event reference, original issue time,
correlation/audit reference and replay indicator. Current state is a separate
read-derived projection. `APPLIED` and `NO_OP` are success outcomes; suspended
processing is neither one. Never expose raw reason or Capture text in a receipt.

Use existing `ProblemDetail`, eleven existing `ErrorCode` values and existing
retry mapping. Add bounded safe-detail vocabulary only where needed:

| Condition | Public code / safe detail | Required behavior |
| --- | --- | --- |
| Missing/malformed ID, revision, key, blank/out-of-bound reason, selector | `invalid_request` / rejected field token | Refuse before effects; no value interpolation. |
| Absent or foreign Capture | `not_found` / `capture_id` | Identical response and no state/owner/count disclosure. |
| Stale lifecycle revision | `conflict` / `expected_lifecycle_revision` | Refresh guidance; no effects. |
| Same key changed operation/root/revision/reason | `conflict` / `idempotency_key` | No earlier raw intent/foreign disclosure. |
| Archived fresh revision/new derivation | `denied` / `capture_withdrawn` | Policy refusal at direct command; worker uses internal nonfailure pause. |
| Current authoring/purpose/grant/privacy refusal | `denied` / existing policy category | Current checks precede receipt replay; preserve existing retry semantics. |
| Current local-processing unavailable | Existing `unavailable` / bounded processing category | Internal unfinished work pauses safely; no claim of completed processing. |
| Unclassified transaction/storage failure | `internal_error` | Rollback success effects; no SQL, stack, reason or text disclosure. |

Do not add a `suspended` public error code. Processing-status `suspended` is an
honest state projection. Audit uses existing bounded event shape with lifecycle
operation, stable root/event/receipt IDs, correlation and category. Add vocabulary
and frozen migration checks if required; APPLIED success is committed atomically.
NO_OP audit is distinguishable from mutation. Denial/failure audits cannot claim a
transition. PR #297's unlanded staging cannot be assumed present or duplicated.

## 9. Requirement and acceptance proof matrix

The following tests are **required future evidence, not executed results**.
Unit/contract proofs use fakes and synthetic fixtures; concurrency and trigger
proofs use a newly attested isolated disposable PostgreSQL target.

| Requirement | Acceptance | Required proof |
| --- | --- | --- |
| CW-001 | CW-AC-01 | Multi-version root archive/restore; same root and latest-version identity. |
| CW-002 | CW-AC-01,04 | Active/0 → archived/1 → active/2; content version numbers unchanged. |
| CW-003 | CW-AC-01,05 | Ordered immutable events; direct UPDATE/DELETE refused; contiguous alternating constraints. |
| CW-004 | CW-AC-01 | Byte/hash/predecessor/span/classification/provenance/content-receipt snapshot unchanged. |
| CW-005 | CW-AC-04 | Advancing clock plus fresh same-state key preserves counter/current archive time; restore nulls current time only. |
| CW-006 | CW-AC-02,10 | All canonical/compact purpose/write/DATA_REQUIRED guards; boolean expected revision refused in DTO/schema; absent/foreign identical; no override/delete. |
| CW-007 | CW-AC-03,10 | Pinned digest; boundary trim, Unicode/internal whitespace significance, 0/501 code point refusal; no clock/ID input. |
| CW-008 | CW-AC-03,04 | Replay after inverse transition; original receipt/outcome/time, no side effects; changed intent conflict; current auth refusal. |
| CW-009 | CW-AC-04 | Fresh stale request conflicts even when desired state already true; honest NO_OP receipt only. |
| CW-010 | CW-AC-05 | Same-root contention; same-key different-root collision; rollback after event/audit/job staging; one winner receipt. |
| CW-011 | CW-AC-05,07 | Archive/revise two ordered barriers; archive/promotion/stage/context and completion root-lock barriers. |
| CW-012 | CW-AC-02,06 | Active/archived/all counts/page/rank/coverage before pagination; selector-bound cursor; cross-owner isolation. |
| CW-013 | CW-AC-02,06 | Owner root/version/chain/history reads retained; foreign reads indistinguishable. |
| CW-014 | CW-AC-01,06 | Exact archived citation/span verification and current metadata; no rewritten immutable output. |
| CW-015 | CW-AC-07 | Queue/retry/each stage/new proposal/promotion/update/context/worker completion blocked after archive commit; suspend final attempt without failure. |
| CW-016 | CW-AC-08 | Same unfinished operation/stage IDs resume, no duplicate completed results; then-current local configuration/auth change blocks resume. |
| CW-017 | CW-AC-09 | Accepted Task/Commitment/Entity/Memory/Report state and histories unchanged; read overlays complete; independent lineage rebinding still allowed. |
| CW-018 | CW-AC-03,05,10 | Redacted receipt/audit/error/repr snapshots; raw reason absent, atomic APPLIED evidence, failure event honest. |
| CW-019 | CW-AC-10 | Cloud/training/deletion paths denied or absent; no classification changes, private-local protections retained. |

Acceptance execution must include all ten scenarios, including combined cases:

- CW-AC-01 retains multiple content versions, citations and previous receipts through
  archive/restore and separate lifecycle revision/history.
- CW-AC-02 and CW-AC-06 exercise two Principals, absent/foreign roots, every selector,
  totals, cursor/ranking/coverage, direct historical reads and current disclosure.
- CW-AC-03 and CW-AC-04 exercise advanced clocks, replay after inverse transition,
  mismatched target/operation/reason/revision, fresh no-ops and stale no-ops.
- CW-AC-05 uses deterministic barriers, not sleeps: same/different roots with one
  idempotency key; revise ordering; injected commit failure; no orphan APPLIED audit.
- CW-AC-07 covers every ledger sink, including transitive encoded origins, copied
  evidence and frozen-context direct Capture input. Archive commit is the ordered
  boundary; earlier committed outputs survive. Lost/stale worker leases cannot
  publish or report success. Withdrawal never consumes final retry as failure. Test final-attempt interruption
  before/after completion, expired/reaped lease races, and archive → restore →
  same-owner reclaim → old-generation publication/completion/release refusal.
- CW-AC-08 changes eligibility during suspension, then restores; ineligible work
  stays paused, eligible same operation resumes, completed stages/results are
  unique. Restore cannot autoaccept review or resurrect terminal failures.
- CW-AC-09 snapshots independent downstream state/links/history and immutable output
  bytes; all actual provenance surfaces disclose current withdrawal/restoration;
  independent correction/rebinding exemption is proved separately from new effect.
- CW-AC-10 tests bounded errors/audits/receipts and no source/reason leakage, existing
  purpose/privacy guards and absence of delete/cloud/grant expansion.

Existing test seeds include `schema_capture_immutability`,
`architecture_capture_has_no_update_path`, cross-Principal Capture tests,
`pipeline_recovery`, reveal, Entity/Memory review, context and re-enrichment
regressions. Update an architecture assertion that forbids any Capture lifecycle
path only to distinguish immutable content from additive lifecycle metadata; do
not weaken source immutability. Select actual package-local test commands from
current configuration at implementation time, recording exit codes and durations.

## 10. Execution phases, ownership and release gate

Manager retains intent/accountability; one dedicated Orchestrator reauthenticates
base and integration head, assigns workers, owns shared-file integration and
commissions a fresh independent reviewer with authority to block.

| Phase / worker | Exclusive write ownership | Dependencies and exit evidence |
| --- | --- | --- |
| P0 source-closure analyst | Read-only current metadata/code census and ledger evidence | Fresh base, contract, migration tip and PR #297 identity; classify every source/sink/surface. |
| P1 persistence worker | New lifecycle repository module, new migration, persistence tests | P0 lock protocol/owner references settled; P2 shared domain/port definitions and P6 early matching tables.py integration must land before P1 implementation/tests; empty/edge migration, constraints, rollback and receipt races. |
| P2 domain/command worker | Capture lifecycle domain values, command/contract DTO sections, unit tests | Establish shared domain/port definitions first from this accepted plan, before P1; then finalize DTO/use-case tests against P1 without circular prerequisites; exact normalization/digest/no-op/replay contracts. |
| P3 processing worker | Capture pipeline, Capture branch of jobs/worker, processing tests | P1 lock helpers and P2 pause semantics; all stage/completion fences, neutral suspension/recovery/current-policy proof. |
| P4 publication worker | Review, Entity governance/authoring, Memory promotion and context publication paths/tests | P0 closure census, P1 lock helpers, P3 eligibility; each new-effect sink fenced, exemptions tested. |
| P5 read-projection worker | Capture list/search/reveal and downstream provenance converters/tests | P1 lifecycle projection, P4 source-resolution census; all selectors and disclosure surfaces complete. |
| P6 integration owner (Orchestrator delegates bounded shared edits) | `tables.py`, shared `service.py`, normalization/registry/dispatch/catalog, audit vocabulary, test fixtures and authoritative docs | Serially land shared table/interface definitions as P1–P5 need them, then integrate final P1–P5 seams; no competing shared-file edits. |
| P7 validation worker | Read-only test execution/evidence; bounded corrective tests assigned separately | Frozen integrated head, all CW proofs plus applicable FAST/PR/FULL affected tiers. |
| P8 independent reviewer | Read-only fresh exact-head review, no authored changes | Head/tree/base, ledger closure, test evidence, authority to BLOCK; later commit invalidates verdict. |

Workers may run concurrently only with satisfied dependencies and non-overlapping
explicit path ownership. A row naming several existing files is not permission
for competing writers; Orchestrator splits/serializes ownership before dispatch.
Use isolated worker worktrees where supported. Shared migration chain and
registry/dispatcher have one integration owner. Each worker handoff reports exact
base/result commit and tree, changed paths, CW/AC IDs, commands/results, limitations,
assumptions and unperformed work; no worker merges/deploys or widens scope.

Before runtime capability exposure, integration owner must close the source/sink
and disclosure census with test references; run Ruff/format and affected typing,
unit/domain/contracts, synthetic policy/security tests, isolated persistence and
race tests, migration empty/predecessor paths, and affected end-to-end/recovery
slices. Run the applicable repository PR gates and broader FULL coverage where
changed persistence/job/publication boundaries require it. Do not invent pass
counts from collection. Required current-head independent review and all mandatory
checks must pass before delegated squash merge under AGENTS section 8.1.

## 11. Stop, recovery and evidence disposition

Stop for repository/base drift, changed contract meaning, unknown owner/source,
unbounded lock graph, incomplete publication/provenance closure, migration-tip
conflict, need for new infrastructure, live/shared database, credentials, personal
data, destructive downgrade, deployment, or reserved risk acceptance. Resolve
routine bounded corrections within authorized implementation scope; material
product conflicts return to the Manager/operator.

If the implementation cannot make suspension/current eligibility honest using
the chosen overlay, surface the measured contradiction before changing architecture
or broad JobState semantics. Do not silently ship partial fences or convert pause
to success/failure. Failed test attempts and corrective review findings remain
in evidence; later passes do not erase them. Roll back incomplete application
entry points without deleting durable content/lifecycle history.

This planning package has inspected source and selected future obligations only.
It has not executed migrations, PostgreSQL concurrency tests, runtime proofs,
model calls, policy mutations, lifecycle commands or deployment. Planning document
checks and independent review are reported separately in the delivery handoff.
Runtime implementation requires its own explicit authorization and refreshed
repository identity. Retention/privacy erasure remains unresolved and separately
governed; CRL-WP-03 planning closes no hard-delete decision.
