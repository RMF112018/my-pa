# Bounded GoodNotes and model operations

This candidate implements a production-shaped, local GoodNotes
page-to-region-to-review composition and an explicitly disabled model boundary.
`ManifestGoodNotesSource` can read digest-bound page representations from one
explicitly admitted local root, and `BoundedLocalOCRTranscriber` can invoke one
explicitly configured local OCR executable without a shell. Both routes are
disabled until their exact root, manifest, executable, provenance, and runtime
settings are configured and authorized. The candidate does **not** authorize a
live GoodNotes/NAS root, select or install an OCR engine, start a model process,
make a network request, or permit cloud disclosure.

## Synthetic validation path

Most acceptance fixtures construct `FixtureGoodNotesSource` in memory. Its only
operation is `inventory(principal_id)`; it cannot mutate, rename, move, or delete
a source. `FixturePageTranscriber` treats UTF-8 fixture bytes as one normalized
page region. Focused unit tests also instantiate the production-shaped manifest
source and bounded OCR adapter against temporary synthetic files and an inert
synthetic local executable. These tests prove admission bounds and composition
contracts as well as identity, provenance, idempotency, review, correction,
lexical search, and Principal partitioning. They do not prove a live-root
configuration, an installed OCR engine, handwriting quality, or operational
readiness.

Run the database-free acceptance evidence:

```bash
.venv/bin/python -m pytest -q \
  tests/unit/test_goodnotes.py \
  tests/unit/test_model_gate.py
```

Run the PostgreSQL evidence only with `MY_PA_DATABASE_URL` pointed at a verified
local PostgreSQL maintenance server. The test creates and drops only the fixed
disposable database `my_pa_goodnotes_test`:

```bash
.venv/bin/python -m pytest -q tests/database/test_goodnotes_ingestion.py
```

Never point the test at an unknown physical server. It uses no source path and
contains only visibly synthetic text.

## Model boundary

`BoundedModelGate` has only `ModelRoutePolicy.DISABLED`. It accepts no content,
provider, router, or persistence port and returns `model_route_deferred`.
Structured context/proposal contracts remain non-executable domain shapes for a
future separately authorized route into canonical Review.

External providers are denied unless the manifest carries a separately made
disclosure-eligibility decision. No code in this slice makes that decision.
Semantic/vector retrieval remains disabled unless benchmark, security-review,
and privacy-review gates all pass. There is no vector schema, dependency, index,
or query implementation.

## GoodNotes lifecycle

Reconciliation derives stable opaque page, page-version, and region identities
from source object/version identity, page number, and content digest. A consumed
idempotency key replays the stored receipt; binding the same key to changed
inventory is refused. Page versions and OCR region proposals are append-only.

OCR text is a noncanonical proposal and does not enter GoodNotes lexical search
until the owning Principal accepts or corrects it. Correction is a separate
review decision; it does not overwrite the source-bound transcription. Search
returns exact page/source-version provenance and is always filtered by
`principal_id`.

## Operator-only prerequisites

Before any live pilot use, the operator must separately establish and authorize
the exact read-only source root and manifest, access mechanism, source
settling/integrity policy, exact eligible OCR executable and provenance, model
route (if any), privacy/disclosure decision, process lifecycle, and bounded live
canary. Until then the production-shaped composition remains unconfigured and
disabled; none of those decisions is inferred from environment state.
