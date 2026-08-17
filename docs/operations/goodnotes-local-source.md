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
from a versioned renderer (default `raw-representation-v1` hashes admitted page
bytes) rather than page number or transcription. PDF visual rasterization and
live GoodNotes activation remain deferred.

Live GoodNotes root admission, OCR engine selection/licensing, background
watcher activation, personal-data eligibility, and production database use
remain operator-gated. Repository tests use synthetic temporary PDF-shaped
bytes and a deterministic local test command only.

Additive knowledge-schema tables persist NOTE_UNIT identity, physical
occurrences, append-only revisions, structural note links, and exact per-run
change-state rows. A PDF is not a note and a page is not a note; printed or
typed agenda text is SOURCE_CONTEXT. Occurrence identity is aligned visual
geometry plus crop/context anchors, not transcription. `GoodNotesOccurrenceReconciler`
reads Principal-bound semantic proposals, re-reads committed occurrence state,
and writes those rows atomically with supplied-as-computed change states.
Uncertainty is `AMBIGUOUS`; identity is never reused from a silent pick.
The service does not build a user-facing NEW-only summary and does not deliver.
Agent and MCP exposure of reconciliation remain later slices.
