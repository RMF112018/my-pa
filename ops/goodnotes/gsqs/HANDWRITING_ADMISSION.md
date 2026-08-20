# Controlled handwriting admission — operator handoff

`CONTROLLED_HANDWRITING_CORPUS = READY_FOR_OPERATOR_INPUT`

This is not a request to ingest ordinary production GoodNotes, customer
pages, business notes, or any personal content already on a device.

The repository must not receive private handwriting image bytes unless a
later operator decision explicitly permits that exact representation.
Admission is digest-bound and external: the Git tree stores identifiers,
SHA-256 digests, labels, leakage groups, partition assignment, and a
private artifact reference — not the pixels.

## Purpose

Layer 1 (`gsqs-v2` synthetic PDFs) is a deterministic regression/canary
corpus. It uses Helvetica and Times-Italic. That is **not** handwriting
and must not be used alone to establish a production-relevant
transcription `MEASURED_B0`.

Layer 2 is a later, operator-controlled sample set of genuine pen/stylus
handwriting of **synthetic non-personal phrases only**.

## Required classification

Every admitted artifact must be:

- `fixture_classification = SYNTHETIC_NON_PERSONAL_HANDWRITING`
- `source_layer = CONTROLLED_HANDWRITING`
- `label_provenance = OPERATOR_ADJUDICATED` after operator review
- explicit gold labels (geometry, transcription, status, class, tags,
  ranking, confidence as applicable)
- `leakage_group_id` that does not split across A/B/C
- exact `artifact_sha256` (64 hex chars)
- non-empty `external_ref` to the private store
- no automatic ingest from GoodNotes production history

Forbidden classifications (refused by `admit_handwriting`):

- `PRODUCTION_GOODNOTES`
- `LIVE_GOODNOTES`
- `PERSONAL_HANDWRITING`
- `ORDINARY_PRODUCTION_GOODNOTES`

## Requested sample content

Write **only** these (or equally synthetic) phrases. Do not substitute
real names, customers, addresses, or live meeting content.

- Review agenda Monday
- Send crane plan Friday
- Call partner after meeting
- Buy spare markers
- Thank partner for intro

## Requested style coverage

Provide at least one sample in each style, using the phrases above:

- print handwriting
- cursive
- mixed print/cursive
- compact writing
- large writing
- slanted writing
- messy but readable
- uncertain (gold `transcription_status = UNCERTAIN`)
- genuinely unreadable (gold `transcription = ""`,
  `transcription_status = UNREADABLE`; the image must be unreadable marks,
  not the word `UNREADABLE`)

Natural variation across writers/sessions is useful. Do not invent
samples inside the repository agent session.

## Admission record (no pixels)

```text
case_id:
artifact_sha256:
external_ref:
fixture_classification: SYNTHETIC_NON_PERSONAL_HANDWRITING
phrases: [...]
style: print | cursive | mixed-print-cursive | compact | large | slanted
       | messy-readable | uncertain | genuinely-unreadable
leakage_group_id:
review_state: PENDING  # until operator review
partition:             # assigned at group level after review
```

After samples exist and are labeled, the corpus state becomes
`READY_FOR_REVIEW`. Only an explicit operator decision may set
`APPROVED`. That later approval is still distinct from
`MEASURED_B0`.

## Stop

Do not collect live personal handwriting in this assignment.
Do not commit private image bytes to this public repository.
Do not run live B0 from these instructions.
