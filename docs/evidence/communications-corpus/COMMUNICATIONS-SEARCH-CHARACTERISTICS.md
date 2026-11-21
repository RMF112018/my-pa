# Communications search characteristics

**Basis:** see the [common basis](README.md#common-basis) (aggregate JSON SHA-256 `82edeee885125a6552a00f7046adbefe0337d5e035905fc08dcceb2261a7945d`, 2026-11-21, Manager-run collection; 31 publications = 29 canonical lean + 2 rich), and the contract CLI result at `ac0d06ae` (derivation `comms_search_text_v1`, extractor `comms_identifiers_v1`). Aggregates only. All counts are over the 4,141 records (observations), so lane duplicates are counted twice.

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
| `disclaimer_removed` | 684 |
| `metadata_only` | 436 |
| `withheld` | 44 |
| `truncated` | 1 |

Quoted-chain stripping removed a chain in 2,011 records against 2,143 records the analysis heuristic saw a chain in; signature/disclaimer removal fired in 684 against 1,056 marker hits, because the contract's disclaimer rules are deliberately conservative (it never cuts to empty and needs a paragraph-level marker).

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
| RFI number | 67 | 51 | 70 |
| Change bulletin (`CB #n`) | 11 | 10 | 21 |
| GMP | 518 | 458 | 458 |
| FPL | 263 | 134 | 134 |
| Change order (analysis: CO/PCO/COR-n) | 104 | 0 | 0 |
| Submittal | 128 | 28 | 28 |
| Six-digit spec-section-like number | 1,713 | 1 (cued only) | 1 |

Readings:

- **Six-digit numbers are noise by default.** 1,713 records hold a bare six-digit number shaped like a CSI MasterFormat section; the analysis could not tell sections from other numbers, so a bare six-digit number is not evidence of a section. v1 admits a spec section only after a `Section`/`Spec` cue, and found 1.
- **Change orders.** v1 extracts only upper-case `CO` with a separator and excludes `PCO`/`COR` (letter before), and found none; the analysis pattern included `PCO` and `COR`. Adding `pco`/`cor` kinds is a measured WP4 decision, not a v1 defect.
- **FPL and submittals** drop most sharply because v1 requires an upper-case acronym (`FPL`) and a number after `Submittal`; the analysis matched words. Recall of v1 against labelled examples is a WP4 acceptance item.
- **Exactness.** `RFI 17` never matches `RFI 174` or `RFI 1740` in v1 (token-bounded, leading zeros dropped for integer kinds); the unit tests pin it.

## Text size planning

At p99 the derived text is about 38,000 characters and the maximum is about 98,000; the contract caps searchable text at 262,144 characters, which no record reached. With roughly 3,500 distinct messages per 5 weeks, a year of mail is in the tens of thousands of rows — well within PostgreSQL full-text search and `pg_trgm` on one node.
