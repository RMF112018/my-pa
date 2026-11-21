# Communications corpus evidence (sanitized aggregates)

**Status:** evidence for [ADR-021](../../decisions/ADR-021-communications-intelligence.md) (Proposed — accepted-candidate; not ratified) and its implementation spec [`communications-intelligence-contract.md`](../../architecture/communications-intelligence-contract.md). Aggregates only.

These six documents describe the real `communications_evidence_v2` corpus the communications-intelligence design was reconciled against. They hold **counts, distributions, closed-vocabulary values, file basenames and business dates only**: no subject, body, address, display name, provider id, Internet Message-ID, conversation id or mailbox reference value. The private publications themselves are never committed and are not reachable from this repository.

| Document | What it answers |
| --- | --- |
| [`COMMUNICATIONS-CORPUS-INVENTORY.md`](COMMUNICATIONS-CORPUS-INVENTORY.md) | Which publications exist, their sizes, dialects, windows and record counts |
| [`COMMUNICATIONS-COVERAGE-BASELINE.md`](COMMUNICATIONS-COVERAGE-BASELINE.md) | What time the corpus covers, the window rules, DST and the merged interval |
| [`MESSAGE-IDENTITY-AND-DEDUPLICATION-ASSESSMENT.md`](MESSAGE-IDENTITY-AND-DEDUPLICATION-ASSESSMENT.md) | What identifies a message, what repeats, and what is never identity |
| [`SCHEMA-COMPATIBILITY-ASSESSMENT.md`](SCHEMA-COMPATIBILITY-ASSESSMENT.md) | The lean and rich dialects of one schema version and how one parser takes both |
| [`COMMUNICATIONS-SEARCH-CHARACTERISTICS.md`](COMMUNICATIONS-SEARCH-CHARACTERISTICS.md) | Body sizes, derived text, quoted chains, withheld bodies, technical identifiers |
| [`CORPUS-DESIGN-IMPLICATIONS.md`](CORPUS-DESIGN-IMPLICATIONS.md) | Each finding mapped to a design decision and to its ADR/spec section |

## Common basis

- **Aggregate source:** `corpus-analysis-sanitized-v2.json`, SHA-256 `82edeee885125a6552a00f7046adbefe0337d5e035905fc08dcceb2261a7945d`, produced 2026-11-21 (about 12:05Z) by a Manager-run collection over local copies of the publications, each verified byte-exact against the NAS SHA-256 listing. The file lives in the Manager's run directory, outside this repository.
- **Corpus:** 31 publications — 29 canonical lean-dialect files in the communications publication folder (business dates 2026-10-18 to 2026-11-20) plus 2 rich-dialect files published outside it.
- **Corrections:** the "Corrections after real-corpus contract validation" of the Manager's corpus addendum v2, made after the Manager ran the WP1 contract's aggregate CLI (`my_pa.infrastructure.communications.aggregate_cli`) over all 31 files at contract head `ac0d06ae85200c3aa48c66279745a76808684a35`. The Manager re-ran it after fix F1 at contract head `184ac6cadd49be9a19f94fcbf60acda22c35a06c` (2026-11-21); contract figures in these documents are measured at `184ac6ca` (Manager real-corpus run, 2026-11-21). The identity, lane, quarantine and coverage results were re-verified unchanged at `184ac6ca`; only `disclaimer_removed` (684 → 125) and the `rfi`, `submittal` and `spec` identifier counts moved. Where an analysis figure and a contract figure differ, both are given and the difference is explained.
- The earlier v1 baseline (5 publications, 561 observations) is superseded; it is cited only where a change is worth recording.
