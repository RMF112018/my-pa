# GoodNotes local source contract

The current candidate has a production composition for a read-only,
manifest-indexed local GoodNotes source. It is inert until an operator supplies
an exact admitted root, relative manifest path, exact local OCR executable and
arguments, OCR provenance name/version, database connection, Principal, and
idempotency key. There is no default root, crawler, `.goodnotes` parser, cloud
model, watcher, or live activation.

The manifest schema identifier is `my-pa.goodnotes-local-source.v1`. Its `pages`
array is bounded to 500 entries. Each admitted entry carries:

- `principal_id`, `source_id`, `source_object_id`, and immutable
  `source_version_id`;
- one-based `page_number` and UTC `observed_at`;
- a root-relative, non-escaping `relative_path`;
- `content_sha256`; and
- `media_type`, one of `application/pdf`, `image/png`, or `image/jpeg`.

The reader does not traverse the root. It refuses links, path escape, missing or
non-regular files, unsupported media, duplicate page identity, digest drift,
over-wide manifests, and representations above 25 MiB. Canonical inventory
order is source-object identity then page number and version.
Manifest, representation and observer reads require a regular file with exactly
one hard link both before and after the bounded read. A link added during the
read is refused; this file rule does not apply to parent directories.

Before OCR starts, every manifest tuple `(source_id, source_object_id,
source_version_id)` must match the canonical registry relation and the invoking
Principal must hold an enrollment for that exact object whose admitted output
types include `text/plain`. Unregistered, mismatched, unenrolled, or differently
owned identities fail closed. This is also what makes a later accepted region
reachable through ordinary enrollment-scoped `knowledge.search`; GoodNotes does
not create a parallel search scope.

The local OCR boundary runs one absolute executable with an explicit argument
vector and no shell. Page bytes go to stdin; stderr is discarded; stdout must be
a bounded JSON document containing normalized region boxes, non-empty bounded
text, and confidence in `[0, 1]`. The command is capped at 60 seconds, 25 MiB of
input, 2 MiB of output, and 250 regions. It receives only a fixed minimal
`PATH`; it selects no engine and downloads nothing.
On supported POSIX systems, each invocation owns a separate process session and
group. Nonblocking pipe handling bounds input, output and command completion;
timeout, overflow, pipe failure or a descendant retaining a pipe after its
parent exits cannot turn partial output into success. Cleanup terminates only
the invocation's process group, closes its pipes and reaps its direct child
within bounded waits. Unsupported process-containment platforms fail closed.

Successful reconciliation derives stable page/version/region identities,
records representation and transcription digests plus extractor name/version,
and writes proposals only. A human Review acceptance or correction determines
the accepted text exposed to lexical search, which returns source version and
page provenance. Replays are idempotent; changed inventory under an existing key
is refused. Stable proposal and Review identifiers include the Principal, and
an idempotent insert is accepted only when the already-stored page, version,
region, and receipt are field-equivalent; a deterministic-ID collision with
different OCR content or provenance is an error.

GoodNotes invokes no model in the current composition. The production model
gate is composed into application readiness as disabled, accepts no content or
provider, and has no executable router. GoodNotes model enrichment remains
explicitly deferred; a future implementation must route proposals durably into
the existing canonical Review plane.

A sibling local observer can settle explicit relative PDF or image paths under
the same admitted root. It does not crawl, refuses links, path escape,
non-regular files, oversize, and unsupported media, and fail-closes on digest
drift or mid-read mutation. Path, size, SHA-256, and `mtime_ns` are observation
metadata; `source_root_id` is an opaque alias. Logical-page identity is matched
from a versioned renderer. The production durable-note profile is
`pdfium-normalized-v1`: a pinned pypdfium2/pdfium raster, grayscale normalize,
and dHash. Raw snapshot SHA-256 and per-page `content_sha256` remain hashes of
admitted bytes and are never used as visual identity. `raw-representation-v1`
and mapped test doubles remain explicit non-default profiles. Live GoodNotes
activation remains deferred.

The observer also exposes an explicit, caller-timed liveness receipt for one
named relative path. A newly missing path is `MISSING`; continued absence past
the caller-supplied last-seen interval is `STALE`. The first successful
observation after either state is `REAPPEARED`, carrying
whether its bytes changed from the last known digest. Only `AVAILABLE` is
eligible by that receipt alone; missing, stale, and reappeared observations do
not silently become ingestion success or reuse prior identity. `REAPPEARED`
persists until a caller explicitly acknowledges the exact reappeared SHA-256;
the acknowledgment clears the state only if a new settled read still has those
exact bytes. The caller owns the staleness interval, so repository code does
not freeze an unsupported operational polling choice.

Live GoodNotes root admission, OCR engine selection/licensing, background
watcher activation, personal-data eligibility, and production database use
remain operator-gated. Repository tests use synthetic vector PDFs (byte-different, visually
equivalent), in-memory fixtures, and a deterministic local test command only.
No live personal GoodNotes pages are admitted.

Additive knowledge-schema tables persist NOTE_UNIT identity, physical
occurrences, append-only revisions, structural note links, and exact per-run
change-state rows. A PDF is not a note and a page is not a note; printed or
typed agenda text is SOURCE_CONTEXT. Logical-page identity requires visual
evidence; sequence and path remain provenance. Occurrence matching first resolves
unique server-verified crops across pages within the same Principal and notebook,
then uses page-local geometry. Duplicate crop candidates remain `AMBIGUOUS`;
transcription and context anchors cannot authorize identity reuse. A verified
cross-page move preserves note and occurrence IDs, appends a revision and a
structural destination-page link, and produces `REVISED` rather than `NEW`.
Occupied destination geometry, including retired occurrences, fails closed
without overwriting canonical history. `GoodNotesOccurrenceReconciler`
reads Principal-bound semantic proposals, re-reads committed occurrence state,
and writes those rows atomically with supplied-as-computed change states.
Uncertainty is `AMBIGUOUS`; identity is never reused from a silent pick.
`GoodNotesNewOnlyDelivery.deliver` then reads committed `NEW` run-note-changes
only, associates ranked GN-04 candidate strings against existing
Principal-partitioned Projects/people/notes or stores unresolved literals, and
writes an immutable delivery receipt. A run with zero NEW changes writes an
internal suppressed receipt and has no user-facing body. Destination is an
explicit string such as `operator-local`; this path does not send to Teams,
email, or Abacus and does not create Projects, people, or Tasks.
The authenticated `goodnotes.complete` path can continue canonical reconciliation
when the existing canonical-write rollout gates permit it. Completion receipts
alone do not authorize canonical writes. The server requires the complete stored
run page set, exact proposal digests, and the latest promoting semantic Review
for every expected page. Missing or unreviewed pages leave canonical promotion
pending, so a partial completion cannot retire another page's notes.

Canonical reconciliation and its immutable per-run promotion receipt commit in
one transaction. The receipt binds expected pages, proposal identities, original
and accepted-result digests, and exact Review decision identities/sequences;
zero-note output still receives a receipt. Replays verify this binding. Caller
promotion-evidence objects cannot authorize canonical writes. A promoting Review
decision remains revisable before promotion; after the promotion receipt, new
Review decisions conflict while exact original request replay remains idempotent.
This follows the existing accepted-Review terminal behavior.

Reconciliation, preview and associations read the same receipt-bound accepted
semantic material. CORRECT_AND_ACCEPT uses the immutable corrected Review
payload, preserving the original proposal as evidence. Completion does not send
a message, invoke OCR/model inference, reread live sources or enable a schedule.

Semantic proposals may carry optional `date_evidence` with separate
`page_candidates`, `event_dates`, and `body_dates` collections, each bounded to
32 entries. Entries preserve canonical ISO dates, original literals and bounded
nonempty evidence references, with optional finite confidence. Multiple distinct
PAGE dates remain ambiguous; evidence for the same date remains preserved.
Omitted or empty date evidence retains historical no-date fingerprint bytes.
Review corrections preserve dates when omitted and remove the accepted claim
when explicitly emptied, while the original proposal remains immutable.

Accepted date evidence stays in existing proposal/Review JSON and promotion
bindings. A date-only change appends a semantic revision even when text and
visual identity are unchanged. Comparison follows the latest revision's exact
snapshot/page provenance to its promoted material; missing, inconsistent or
unpromoted prior provenance fails closed rather than inventing prior dates.
Dates never establish identity, infer scheduling, or come from page ordinal,
file paths, modification time or observation time. No new date columns or
user-facing delivery format are introduced.

Authenticated client pull uses a durable Principal-and-client partition for
assignments, attempts, completion keys and status. Restarting the server or
losing a cursor resumes the same outstanding assignment ID and attempt, ordered
by original assignment time then immutable work identity. Existing cursor
authentication and the stable server-derived client context remain unchanged.
One client's progress does not consume another client's budget; both clients
still require the same authoritative semantic proposal and promoting Review.

`MY_PA_GOODNOTES_PULL_ASSIGNMENT_LEASE_SECONDS` is a non-secret integer setting,
default **900 seconds**, bounded **60–86400 seconds**. It does not enable pull
or activate a source. The policy is persisted immutably with each client
session; changing the configured value for an existing session fails closed
instead of reinterpreting its assignments. Existing sessions receive 900
seconds through the additive migration. Context/key rotation remains outside
this contract.

Discovery resumes unexpired assignments first and fills remaining batch space
with fresh or expired retry-eligible work. Ordinary polling never spends another
attempt. Expiry permits one successor under the same session lock used by
completion: a still-current expired assignment may complete, but a committed
successor makes the old handle stale. Completed work is never retried. Status
counts fresh or expired retry-eligible work as pending, unexpired work as
assigned (including the final attempt), and expired unresolved final attempts
as exhausted. Status reads existing policy without creating a session.

Attempts and completion receipts remain append-only. Migration downgrade
refuses client-key collisions or nondefault lease policies that the preceding
schema cannot represent; it never deletes history to make narrowing succeed.
No scheduler, retry request field, new public capability or source write is
introduced.
