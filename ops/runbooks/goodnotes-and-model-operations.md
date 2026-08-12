# Bounded GoodNotes and model operations

This candidate implements a synthetic-only GoodNotes page-to-region-to-review
slice and an optional model proposal boundary. It does **not** authorize or
configure a live GoodNotes/NAS root, OCR engine, model process, network request,
or cloud disclosure.

## Safe acceptance path

The acceptance fixtures construct `FixtureGoodNotesSource` in memory. Its only
operation is `inventory(principal_id)`; it cannot mutate, rename, move, or delete
a source. `FixturePageTranscriber` treats UTF-8 fixture bytes as one normalized
page region. This proves contracts, identity, provenance, idempotency, review,
correction, lexical search, and Principal partitioning—not handwriting quality.

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

`BoundedModelGate` starts with `ModelRoutePolicy.DISABLED`. Enabling the local
proposal route still grants no durable write: a provider receives a structured
`ContextManifest`, exact evidence references, and content explicitly marked as
having no instruction authority. Provider failures collapse to
`model_unavailable`; prompt text and provider error bodies are not returned.

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

Before any live pilot use, the operator must separately establish the exact
read-only source root and access mechanism, source settling/integrity policy,
eligible OCR runtime and model, privacy/disclosure decision, process lifecycle,
and bounded live canary. None is inferred from environment state.
