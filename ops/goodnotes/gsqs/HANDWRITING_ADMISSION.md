# Controlled handwriting admission

`CONTROLLED_HANDWRITING_CORPUS = INSUFFICIENT_EVIDENCE`

Two complementary Gate B layers exist:

1. **Synthetic regression** (`gsqs-v2`) — Helvetica / Times-Italic PDFs.
   Valid for evaluator, schema, tags, ranking, critical errors, and CI.
   Not genuine handwriting. `b0_suitable = false` on that layer alone.
2. **Controlled real handwriting** (`gsqs-hw-moss-v1`) — operator-authorized
   local construction from the exact Moss inbox root named in
   `REQ-MYPA-GOODNOTES-GATE-B-HANDWRITING-CORPUS-20260820-001`.
   First-pass labels are private, digest-bound, and `PENDING`.
   Population/diversity is below the B0 floor.

The repository must not receive private handwriting image bytes or gold
transcriptions. Git stores identifiers, SHA-256 digests, classification,
leakage groups, partition assignment, redacted counts, and a private
artifact reference.

## Allowed classifications

`admit_handwriting` accepts only:

- `SYNTHETIC_NON_PERSONAL_HANDWRITING` — optional later phrase samples
- `PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING` — the 2026-08-20 Moss
  root only, via digest-bound private gold

Forbidden (still refused):

- `PRODUCTION_GOODNOTES`
- `LIVE_GOODNOTES`
- `PERSONAL_HANDWRITING`
- `ORDINARY_PRODUCTION_GOODNOTES`

Uncontrolled personal or production ingest is not authorized by the
existence of the Moss exception.

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

Operator review package:
[`hw-moss-v1/OPERATOR_REVIEW.md`](hw-moss-v1/OPERATOR_REVIEW.md).

Rules for that layer:

- source PDFs are read-only evidence
- gold transcriptions stay in the private store
- each case digest binds raster digest + private label digest
- A/B/C partitioning is group-level; no leakage group may split
- review_state stays `PENDING` until the operator adjudicates
- `b0_suitable` stays false while population, UNREADABLE coverage, or
  pending labels fail the B0 criteria
- Corpus C is a holdout and must not be shown to a future optimizer
- external model scoring requires a separate disclosure authorization

## Stop

Do not commit private image bytes or transcriptions to this public
repository. Do not run live B0 from these instructions. Do not send
Moss page content to ChatLLM, Abacus, or another external model.
