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
is refused.

Live GoodNotes root admission, OCR engine selection/licensing, background
watcher activation, personal-data eligibility, and production database use
remain operator-gated. Repository tests use synthetic temporary PDF-shaped
bytes and a deterministic local test command only.
