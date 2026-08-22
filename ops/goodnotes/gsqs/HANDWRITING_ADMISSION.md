# Controlled handwriting admission

`CONTROLLED_HANDWRITING_CORPUS = APPROVED`

Two complementary Gate B layers exist:

1. **Synthetic regression** (`gsqs-v2`) — Helvetica / Times-Italic PDFs.
   Valid for evaluator, schema, tags, ranking, critical errors, and CI.
   Not genuine handwriting. `b0_suitable = false` on that layer alone.
2. **Controlled real handwriting** (`gsqs-hw-combined-v1`) — complete eligible
   census from the three operator-authorized GoodNotes roots (Moss, Kast,
   Altman). Historical Moss-only tranche `gsqs-hw-moss-v1` is preserved and
   is not independently B0-suitable.

The former 75–150 page / 125–250 NOTE_UNIT floors are statistical
limitations, not automatic rejection. Principle:
`COMPLETE_AVAILABLE_AUTHORIZED_EVIDENCE > ARTIFICIAL_SAMPLE_QUOTA`.

The repository must not receive private handwriting image bytes or gold
transcriptions. Git stores identifiers, SHA-256 digests, classification,
source cohort, leakage groups, partition assignment, redacted counts, and
a private artifact reference.

## Allowed classifications

`admit_handwriting` accepts only:

- `SYNTHETIC_NON_PERSONAL_HANDWRITING` — optional later phrase samples
- `PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING` — operator-authorized
  Moss / Kast / Altman roots only, via digest-bound private gold

Forbidden (still refused):

- `PRODUCTION_GOODNOTES`
- `LIVE_GOODNOTES`
- `PERSONAL_HANDWRITING`
- `ORDINARY_PRODUCTION_GOODNOTES`

Uncontrolled personal or production ingest is not authorized by the
existence of the authorized-root exception.

## Synthetic phrase path (still available)

If the operator later supplies non-personal written phrases, use only
these (or equally synthetic) phrases:

- Review agenda Monday
- Send crane plan Friday
- Call partner after meeting
- Buy spare markers
- Thank partner for intro

Requested style coverage for that path remains: print, cursive,
mixed-print-cursive, compact, large, slanted, messy-readable, uncertain,
genuinely-unreadable.

## Real-handwriting path (current)

Operator review packages:

- [`hw-combined-v1/OPERATOR_REVIEW.md`](hw-combined-v1/OPERATOR_REVIEW.md)
  — current combined census; admitted labels `APPROVED` /
  `OPERATOR_ADJUDICATED` after the 2026-08-21 operator decision bound to
  the pre-rebind digest; B0 still requires a separate disclosure
  authorization
- [`hw-moss-v1/OPERATOR_REVIEW.md`](hw-moss-v1/OPERATOR_REVIEW.md) —
  historical Moss-only tranche (`INSUFFICIENT_EVIDENCE`, `PENDING`)

Rules for the combined layer:

- source PDFs are read-only evidence
- gold transcriptions stay in the private store
- each case digest binds raster digest + private label digest
- page-level `primary_class` and `transcription_status` are independent
  public descriptors, not unique region aggregates; GSQS scores per
  region; v2 admission checks NOTE_UNIT counts only
- A/B/C partitioning is group-level; no leakage group may split
- scoreable cases require `review_state = APPROVED` and
  `label_provenance = OPERATOR_ADJUDICATED`
- `PENDING` and `AMBIGUOUS_EXCLUDE` are not scoreable
- missing real-world UNREADABLE is a documented limitation, not automatic
  corpus rejection; synthetic `gsqs-v2` still tests fabricated-unreadable
  traps
- B0, if later authorized, measures this authorized corpus only — not
  universal handwriting accuracy
- Corpus C is a holdout and must not be shown to a future optimizer
- external model scoring requires a separate private-data disclosure
  authorization

## Stop

Do not commit private image bytes or transcriptions to this public
repository. Do not run live B0 from these instructions. Do not send
handwriting page content to ChatLLM, Abacus, or another external model.
