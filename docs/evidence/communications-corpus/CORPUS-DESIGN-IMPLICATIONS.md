# Corpus design implications

**Basis:** see the [common basis](README.md#common-basis) (aggregate JSON SHA-256 `82edeee885125a6552a00f7046adbefe0337d5e035905fc08dcceb2261a7945d`, 2026-11-21, Manager-run collection; 31 publications = 29 canonical lean + 2 rich), with the post-validation corrections at contract head `ac0d06ae` and the contract figures measured at `184ac6ca` (Manager real-corpus run, 2026-11-21); the identity, lane, quarantine and coverage results were re-verified unchanged at `184ac6ca` against the earlier `ac0d06ae` run. Aggregates only.

Each row maps a measured finding to the design decision it forces and to where that decision is recorded: "D*n*" is a decision of [ADR-021](../../decisions/ADR-021-communications-intelligence.md); "§*n*" is a section of [`communications-intelligence-contract.md`](../../architecture/communications-intelligence-contract.md).

| # | Finding (evidence document) | Design decision | ADR / spec |
| --- | --- | --- | --- |
| 1 | One schema version `2.0.0`, two dialects: lean (29 files, 9 keys) and rich (2 files, 14 keys) ([schema](SCHEMA-COMPATIBILITY-ASSESSMENT.md)) | One field-driven parser with dialect detection by marker keys; no per-dialect parser | D3; §2 |
| 2 | Producer kept the same version across two shapes ([schema](SCHEMA-COMPATIBILITY-ASSESSMENT.md)) | Reject unknown majors; tolerate newer minors and unknown keys with counted diagnostics | D3; §2 |
| 3 | 31/31 publications valid; record faults possible but absent ([inventory](COMMUNICATIONS-CORPUS-INVENTORY.md)) | Envelope faults reject; record faults quarantine; one bad record never rejects a publication | D3; §2, §4.3, §18 |
| 4 | Internet Message-ID present in 4,141/4,141; 3,461 distinct ([identity](MESSAGE-IDENTITY-AND-DEDUPLICATION-ASSESSMENT.md)) | Canonical key `(principal, mailbox_ref, internet_message_id)`; `provider_id_only` fallback kept as a separate key space | D4; §3 |
| 5 | Every provider id `graph_default_mutable`; immutable-id header never applied ([identity](MESSAGE-IDENTITY-AND-DEDUPLICATION-ASSESSMENT.md)) | Provider id is mailbox-item identity at collection time only; never message identity | D4, D5; §3 |
| 6 | 421 backfill pairs: same provider id in sent and inbox lanes ([identity](MESSAGE-IDENTITY-AND-DEDUPLICATION-ASSESSMENT.md)) | One item, several lane observations (`lane_observation_merged`); nothing dropped | D5; §4 |
| 7 | Lean records return no folder id ([schema](SCHEMA-COMPATIBILITY-ASSESSMENT.md)) | Folder role is `unverified_lane_claim` unless a folder id is returned (197 verified) | D6; §4, §5.2 |
| 8 | 14 pairs differ in to/cc metadata only; 0 address disagreements; bcc only on sent copies ([identity](MESSAGE-IDENTITY-AND-DEDUPLICATION-ASSESSMENT.md)) | Per-observation participant evidence kept; canonical union by address with provenance; bcc from sent lane; reconciliation flags | D7; §4.2, §5.2 |
| 9 | Pair copies differ in selected time (received vs sent); 407 Message-ID groups vary in selected time ([identity](MESSAGE-IDENTITY-AND-DEDUPLICATION-ASSESSMENT.md)) | Keep both raw times per observation; canonical time by primary lane with recorded basis | D7; §4.2, §5.1 |
| 10 | 66 messages held by two items (50 Inbox+Sent, 16 Inbox+Inbox) ([identity](MESSAGE-IDENTITY-AND-DEDUPLICATION-ASSESSMENT.md)) | Two mailbox items under one message; not a conflict | D5; §3, §5.2 |
| 11 | `dedup_key` counts provider ids; 35 body-hash and 479 subject groups span distinct messages ([identity](MESSAGE-IDENTITY-AND-DEDUPLICATION-ASSESSMENT.md)) | None of them is identity | D8; §3 |
| 12 | 191 cross-publication repeats, all identical; 0 conflicts ([identity](MESSAGE-IDENTITY-AND-DEDUPLICATION-ASSESSMENT.md)) | Repeats add observations; a cross-publication disagreement quarantines and flags, never rewrites | D4; §3, §11 |
| 13 | 1 exact within-file repeat ([identity](MESSAGE-IDENTITY-AND-DEDUPLICATION-ASSESSMENT.md)) | `duplicate_observation`, stored flagged so totals reconcile | D5; §4.3 |
| 14 | 44 bodies withheld by the privacy screen (rich) ([search](COMMUNICATIONS-SEARCH-CHARACTERISTICS.md)) | Metadata-only; no text, never reconstructed or returned; digest not presented as verified | D9; §6, §17 |
| 15 | Body p99 238 KB, max 596 KB; html 96 % ([search](COMMUNICATIONS-SEARCH-CHARACTERISTICS.md)) | Store derived text, digest and source pointer; raw HTML stays in the publication | D10; §5.1 |
| 16 | 52 % of records carry quoted chains; up to 79 quoted headers ([search](COMMUNICATIONS-SEARCH-CHARACTERISTICS.md)) | Versioned quoted-chain and disclaimer stripping before indexing; conversation collapse in results | D11; §6, §14 |
| 17 | Lean derived text has no digest; rich derived text verified on 145 ([search](COMMUNICATIONS-SEARCH-CHARACTERISTICS.md)) | Trust producer text only when digest-verified; otherwise derive from the body | D11; §6 |
| 18 | 160 empty bodies, 439 empty derived texts ([search](COMMUNICATIONS-SEARCH-CHARACTERISTICS.md)) | Empty → metadata-only, flagged; never a search hit on text | D11; §6 |
| 19 | Construction identifiers frequent (GMP 518, FPL 263, RFI 67 records by analysis) ([search](COMMUNICATIONS-SEARCH-CHARACTERISTICS.md)) | Exact identifier index beside FTS; exact-match tiers rank first | D12; §7, §14 |
| 20 | Six-digit spec-like numbers in 1,713 records ([search](COMMUNICATIONS-SEARCH-CHARACTERISTICS.md)) | Spec sections need a cue by default; bare numbers never | D12; §7 |
| 21 | Analysis CO/PCO/COR 104 vs v1 `co` 0; FPL (134 vs 263) and submittal (31 vs 128, measured at `184ac6ca` (Manager real-corpus run, 2026-11-21)) recall far below analysis ([search](COMMUNICATIONS-SEARCH-CHARACTERISTICS.md)) | Extractor versioned; WP4 measures recall and decides new kinds; low recall is an open WP4 defect (Manager ruling 2026-11-21, R5) | D12; §7, §20.4 |
| 22 | Corpus fits tens of thousands of rows a year ([search](COMMUNICATIONS-SEARCH-CHARACTERISTICS.md)) | PostgreSQL FTS + `pg_trgm` only; no semantic index or engine | D12; §6 |
| 23 | Friday window 33.2 h labelled 24 ([coverage](COMMUNICATIONS-COVERAGE-BASELINE.md)) | Coverage from bounds only; `hours` is a label | D13; §9 |
| 24 | Inclusive end; backfill windows 1 s apart ([coverage](COMMUNICATIONS-COVERAGE-BASELINE.md)) | Inclusive containment; merge when ≤ 1 s apart | D13; §9 |
| 25 | Business-date meaning differs by rule ([coverage](COMMUNICATIONS-COVERAGE-BASELINE.md)) | Business date is a label; never a coverage claim | D13; §9 |
| 26 | 49 h fall-back weekend, UTC anchor 04:00Z → 05:00Z ([coverage](COMMUNICATIONS-COVERAGE-BASELINE.md)) | Windows taken as declared in UTC; DST flag cross-checked; real 49 h shape tested | D13; §9, §20.1 |
| 27 | One continuous interval, no gaps; v1 gap closed by a later backfill ([coverage](COMMUNICATIONS-COVERAGE-BASELINE.md)) | Gaps reported with bounds; reads state coverage of the queried range | D13; §9, §13 |
| 28 | `procore_rfis` lane `not_authorized` everywhere ([inventory](COMMUNICATIONS-CORPUS-INVENTORY.md)) | Lane states reported separately; `not_authorized` never reads as "no messages" | D13; §9 |
| 29 | Rich files overlap canonical windows ([coverage](COMMUNICATIONS-COVERAGE-BASELINE.md)) | Overlap is repeat observations; the 2 rich files are admitted to backfill as explicitly registered sources (Manager ruling 2026-11-21, R2) | D2; §10, §11 |
| 30 | Publications are files in a client-writable workspace (ADR-019 decision 3), identified in this analysis by SHA-256 ([inventory](COMMUNICATIONS-CORPUS-INVENTORY.md)) | Snapshot identity = file SHA-256; idempotency by `(source, sha256)`; shared with PULSE | D2; §1 |
| 31 | No calendar identity in the corpus; meetings carry no provider columns ([inventory](COMMUNICATIONS-CORPUS-INVENTORY.md)) | Meeting provider bindings keyed by iCalendar UID and original start; WP2, synthetic fixtures | D14; §12 |
| 32 | 703 records flag attachments that are never collected ([search](COMMUNICATIONS-SEARCH-CHARACTERISTICS.md)) | Attachments out of scope; `has_attachments` stored as an attribute | D10; §5.1 |
| 33 | 2 null-`from` records, 7 empty subjects ([identity](MESSAGE-IDENTITY-AND-DEDUPLICATION-ASSESSMENT.md)) | Degrade, never quarantine, for missing sender or subject | D3; §2 |

## Not decided by the corpus

- Whether the collector should return folder ids in the lean dialect (would turn 3,944 lane claims into verified roles) — an operator request to the collector, WP5 directive.
- External-model eligibility of mail text returned to connected clients — operator decision (spec §17).
- Manager rulings 2026-11-21 on the spec's open items (R1–R5 and the WP2 meeting-sync deferral) are in spec §21; ADR-021 stays Proposed.
- Spring-forward DST, a schema major bump, record-level faults and identity conflicts do not occur in the corpus; they are covered by synthetic fixtures only.
