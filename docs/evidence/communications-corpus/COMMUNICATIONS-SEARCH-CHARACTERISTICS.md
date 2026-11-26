# Communications search characteristics

**Basis:** see the [common basis](README.md#common-basis) (aggregate JSON SHA-256 `82edeee885125a6552a00f7046adbefe0337d5e035905fc08dcceb2261a7945d`, 2026-11-21, Manager-run collection; 31 publications = 29 canonical lean + 2 rich), and the contract CLI result measured at `80208caa` (Manager real-corpus run, 2026-11-21) (derivation `comms_search_text_v1`, extractor `comms_identifiers_v1`; contract head `80208caabe92de03be676a93fae8984d31d2b8c1`, the WP1 head after fix F2). Aggregates only. All counts are over the 4,141 records (observations), so lane duplicates are counted twice.

## Bodies

| Measure | Value |
| --- | --- |
| Content type | html 3,986; text 155 |
| Body bytes p50 / p90 / p99 / max | 15,227 / 82,356 / 237,656 / 595,934 |
| Body state (contract) | present 3,936; empty 160; withheld 44; truncated 1 |
| Has attachments | 703 (attachments are never collected) |
| Quoted reply chain present (analysis heuristic) | 2,143 records (52 %) |
| Quoted-header markers per record p50 / p90 / max | 1 / 9 / 79 |
| Signature or disclaimer markers (analysis heuristic) | 1,056 records |

## Producer derived text

| Measure | Value |
| --- | --- |
| Derivation | `html_to_text_v1` 3,948; `plain_passthrough` 141; none 52 |
| Derived text characters p50 / p90 / p99 / max | 2,421 / 12,098 / 38,236 / 98,142 |
| Empty derived text | 439 |
| Digest-bound (rich only) and verified | 145 |

Lean derived text carries no digest, so the contract does not trust it as the text of this body and derives its own (`body_content` basis).

## Searchable text derived by the contract (`comms_search_text_v1`)

All contract figures in this section and the next were measured at `184ac6ca` (Manager real-corpus run, 2026-11-21), except `disclaimer_removed`, which is measured at `80208caa` (Manager real-corpus run, 2026-11-21). The identity, lane, quarantine and coverage results were re-verified unchanged at `184ac6ca` against the earlier `ac0d06ae` run; only `disclaimer_removed` and the `rfi`, `submittal` and `spec` identifier counts moved. At `80208caa`, after fix F2, every figure here was re-verified unchanged except `disclaimer_removed` (125 → 108), and 0 window bounds were floored.

| Basis | Records |
| --- | ---: |
| `body_content` (contract html→text or passthrough) | 3,563 |
| `unique_body` (rich, provider new-content-only body) | 142 |
| `none` (metadata only) | 436 = 391 empty + 44 withheld + 1 truncated |

| Flag | Records |
| --- | ---: |
| `markup_dropped` | 3,754 |
| `quoted_chain_removed` | 2,011 |
| `quoted_chain_retained` (cut would leave nothing; text kept) | 59 |
| `disclaimer_removed` | 108 |
| `metadata_only` | 436 |
| `withheld` | 44 |
| `truncated` | 1 |

Quoted-chain stripping removed a chain in 2,011 records against 2,143 records the analysis heuristic saw a chain in; signature/disclaimer removal fired in 108 (measured at `80208caa` (Manager real-corpus run, 2026-11-21)) against 1,056 marker hits, because the contract's disclaimer rules are deliberately conservative (it never cuts to empty and needs a paragraph-level marker). Fix F1 (review R1) narrowed the rules so that only an exact RFC 3676 `-- ` delimiter near the end counts and a "this email … confidential" sentence counts only when it starts a trailing paragraph; that took the count from 684 at `ac0d06ae` to 125 measured at `184ac6ca` (Manager real-corpus run, 2026-11-21). Fix F2 (review R2) narrowed the rules again: a signature break counts only in the trailing region, and "if you are not the intended recipient" and "confidentiality notice" count only when they start a trailing paragraph. A marker paragraph directly under a trailing dash rule now counts too. That took the count from 125 at `184ac6ca` to 108 measured at `80208caa` (Manager real-corpus run, 2026-11-21).

**Open WP4 item (Manager ruling 2026-11-21: not fixed in WP1).** Two disclaimer markers are still unanchored: a line starting `Disclaimer` and the "if you have received this … in error" phrase match on any line anywhere in the text, not only on a paragraph-start line in the trailing region as the other markers do, and the "received this … in error" phrase matches anywhere within its line. WP4 must anchor them, with tests; until then they can cut body text that merely mentions a disclaimer.

**Closed in WP4 (`comms_search_text_v2`).** Both markers now count only as a trailing paragraph start, and the v1 text of a message is always a prefix of its v2 text. `disclaimer_removed`: 108 under v1, 89 under v2 (Manager real-corpus run, 2026-11-25).

## Privacy screen (rich dialect only)

| Class | Records |
| --- | ---: |
| `professional_unreviewed` | 153 |
| `flagged_sensitive` | 27 |
| `flagged_personal` | 17 |

The 44 flagged records (27 + 17) match the 44 privacy-withheld bodies in count. A withheld record's body, unique body and derived text are null, and its digests describe content this consumer never sees. They are searchable by metadata only.

## Technical identifiers

Two measurements, not to be confused. The analysis column is a broad regex over full bodies (quoted chains included). The contract column is `extract_identifiers` over subject plus the stripped searchable text, which is what an index would hold.

| Kind | Analysis: records with a match | Contract v1: records | Contract v1: distinct identifiers (sum per record) |
| --- | ---: | ---: | ---: |
| RFI number | 67 | 75 | 94 |
| Change bulletin (`CB #n`) | 11 | 10 | 21 |
| GMP | 518 | 458 | 458 |
| FPL | 263 | 134 | 134 |
| Change order (analysis: CO/PCO/COR-n) | 104 | 0 | 0 |
| Submittal | 128 | 31 | 31 |
| Six-digit spec-section-like number | 1,713 | 5 (cued only) | 5 |

Readings:

- **Six-digit numbers are noise by default.** 1,713 records hold a bare six-digit number shaped like a CSI MasterFormat section; the analysis could not tell sections from other numbers, so a bare six-digit number is not evidence of a section. v1 admits a spec section only after a `Section`/`Spec` cue, and found 5.
- **Change orders.** v1 extracts only upper-case `CO` with a separator and excludes `PCO`/`COR` (letter before), and found none; the analysis pattern included `PCO` and `COR`. Per Manager ruling 2026-11-21 (R5), this low recall is an **open WP4 defect**, to be fixed with tests; WP4 decides whether `pco`/`cor` kinds are added.
- **FPL and submittals** drop most sharply because v1 requires an upper-case acronym (`FPL`) and a number after `Submittal`; the analysis matched words. Recall of v1 against labelled examples is a WP4 acceptance item; per Manager ruling 2026-11-21 (R5), the low FPL and submittal recall is part of the same **open WP4 defect**, to be fixed with tests.
- **Exactness.** `RFI 17` never matches `RFI 174` or `RFI 1740` in v1 (token-bounded, leading zeros dropped for integer kinds), and `RFI 1,740` is not `rfi:1` (a number never continues into `,` followed by a digit, added in fix F1); the unit tests pin it.

## Technical identifiers under `comms_identifiers_v2` (WP4)

Measured with the counts-only identifier measurement entry point (Manager real-corpus run, 2026-11-25; 31 files, 4,141 records; after review fix F6). Records with at least one identifier of the kind:

| Kind | Analysis: records with a match | Contract v1: records | Contract v2: records |
| --- | ---: | ---: | ---: |
| RFI number | 67 | 75 | 74 |
| Change bulletin (`CB #n`) | 11 | 10 | 10 |
| GMP | 518 | 458 | 459 |
| FPL | 263 | 134 | 134 |
| Change order family (`co`, `pco`, `cor`) | 104 | 0 | 91 (`pco` 89, `cor` 2) |
| Submittal | 128 | 31 | 44 |
| Spec section (cued only) | 1,713 (six-digit numbers) | 5 | 5 |

Readings:

- **Change orders and submittals.** The remaining gap against the analysis is mentions without a number, which are not identifiers: mostly the change-order keyword alone (52 records) and 118 submittal mentions with no number. Every gap that has a number is covered; the Manager closed R5.
- **RFI** fell by one record: the 6 values v2 no longer extracts were all v1 false positives (hexadecimal ids and one malformed match), so precision improved.
- **FPL** is unchanged: 94 records mention it only in quoted or tail text, excluded by design, and 10 use a shape v2 does not admit (ruling R5b stays (a)).
- **Stored, after the rederive** (Manager real-corpus database run, 2026-11-25): 3,459 messages rederived, 21 with changed text, 817 v2 identifier rows added, 0 unavailable or failed; v2 adds `pco` in 69 messages (124 rows) and `cor` in 2, and submittals go from 23 to 36 messages.
- **Residuals.** `CO: 25 ppm` reads as `co:25`; `RFI 1 740` reads as `rfi:1`; the prefixed form `RFI CON-132` is recognized by neither version.

## Full-text configuration (WP4, ruling D4-final)

`measure-fts` (Manager real-corpus database run, 2026-11-25): identifier probes, 0 uncovered by the identifier index; name probes, 3,887 present, `english` finds 3,130 and `simple` 3,396; the `english`-only loss is exactly the 267 stop-word names. `english` stays the stored document; a query that `english` reduces (a stop-word name) also matches through `simple` at query time and says so (`text_fallback: "simple_stopwords"`).

## Text size planning

At p99 the derived text is about 38,000 characters and the maximum is about 98,000; the contract caps searchable text at 262,144 characters, which no record reached. With roughly 3,500 distinct messages per 5 weeks, a year of mail is in the tens of thousands of rows — well within PostgreSQL full-text search and `pg_trgm` on one node.
