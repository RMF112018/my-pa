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
typed agenda text is SOURCE_CONTEXT. Occurrence identity is aligned visual
geometry plus crop/context anchors, not transcription. `GoodNotesOccurrenceReconciler`
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
