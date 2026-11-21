# Schema compatibility assessment

**Basis:** see the [common basis](README.md#common-basis) (aggregate JSON SHA-256 `82edeee885125a6552a00f7046adbefe0337d5e035905fc08dcceb2261a7945d`, 2026-11-21, Manager-run collection; 31 publications = 29 canonical lean + 2 rich), and the contract CLI result measured at `184ac6ca` (Manager real-corpus run, 2026-11-21); the identity, lane, quarantine and coverage results were re-verified unchanged at `184ac6ca` against the earlier `ac0d06ae` run. Aggregates only; field names are schema vocabulary, not content.

## One schema version, two dialects

All 31 publications declare `schema = communications_evidence_v2` and `schema_version = 2.0.0`, yet they come in two shapes.

| | Lean | Rich |
| --- | --- | --- |
| Publications | 29 (the canonical folder) | 2 (outside it) |
| Records | 3,944 | 197 |
| Top-level keys | 9: `business_date`, `coverage`, `cycle_run_id`, `id_header`, `mailbox_ref`, `messages`, `schema`, `schema_version`, `window` | 14: the 9 plus `candidates`, `counts`, `provenance`, `threads`, `transport` |
| Window rules | weekday/weekend/Friday local-day rules | `explicit_utc_bounds` |
| Folder verification | `folder_id` and `parent_folder_id_returned` null: role is a lane claim | `parent_folder_id_returned` returned: role verified |
| Per-record `importance` | present (3,944) | absent |
| Per-record privacy screen (`privacy.class`, `privacy.screen`, `privacy.flags`, `privacy.policy_withheld`) | absent | present (197) |
| `unique_body` (provider's new-content-only body, with SHA-256 and byte count) | absent | present (197; content withheld in 44) |
| Producer derived text SHA-256 | absent (text not digest-bound) | present on 145 |
| `links` (web link, fallback link), `fetch_state`, `fetch_error`, `in_window`, `provenance.*`, `flags`, `body_preview` | absent | present |
| `shares_internet_message_id_with` | absent | present on 14 records |
| Withheld body (`body.content` null, `content_withheld = policy_withheld_privacy_screen`) | never | 44 records |

The union of record-level `field path:type` combinations over the corpus is 160. The only type differences are values that are null in some records and populated in others (`parent_folder_id_returned` by dialect; `body.content` when withheld; `body_derived_plain_text`; `from` and `sender` in the 2 null-`from` records; one null `sent_raw`).

Fields constant across the whole corpus (a single value in every record): `body.hash_scope` (SHA-256 over the UTF-8 bytes of `body.content` as stored), `body.body_origin = hydration`, `id_format = graph_default_mutable`, `source_lane = mail`, `timestamps.selected_raw_offset = Z`, and `attachments_note` (attachments are never collected).

## Integrity of declared digests

| Check | Result |
| --- | --- |
| `body.sha256` matches stored content | 4,097 verified; 44 not verifiable (withheld: the digest describes the original) |
| `body.utf8_bytes` matches stored content | 4,097 match; 44 withheld |
| `unique_body.sha256` (rich) | 153 verified; 44 withheld |
| Producer derived text digest | 145 verified (rich); 3,944 not declared (lean); 42 withheld |
| Body completeness | `graph_full_body` 4,140; `truncated_unknown` 1 |

No digest mismatch exists in the corpus.

## Compatibility rules the contract implements

These are what `parse_publication` in `my_pa.infrastructure.communications.evidence_v2` does; the spec section "Validation and compatibility" restates them.

1. **Dialect detection by marker keys.** None of `candidates`, `counts`, `provenance`, `threads`, `transport` → lean; any → rich; some but not all → rich with diagnostic `dialect_markers_incomplete`. Records are parsed field-driven, so a rich field is understood wherever it appears.
2. **Major version gate.** Only major `2` is accepted; any other major rejects the publication (`unsupported_major_version`). A newer minor is accepted with diagnostic `schema_minor_newer`; unknown keys are counted, never fatal.
3. **Envelope rejection vs record quarantine.** Only envelope faults reject a publication (size, encoding, malformed JSON, duplicate JSON keys, unknown schema, invalid version, missing required key, invalid window). One bad record is quarantined with reason codes and never rejects its publication.
4. **Inert content.** Bodies are data. HTML is reduced to text nodes only; no attribute, script or style content reaches derived text.

Contract result: 31 of 31 accepted, 0 rejected, 0 unknown top-level keys, 0 unknown record keys, 0 quarantined records, 0 `dialect_markers_incomplete`.

## Drift risks

- **Silent dialect convergence.** Nothing in the envelope distinguishes the dialects except the marker keys; a producer that adds `counts` to lean files would turn them rich. The parser is field-driven, so this changes counts and verification states, not acceptance.
- **Lean folder-role ambiguity.** Until the lean dialect returns a folder id, the role of every lean record stays an unverified lane claim (see the identity assessment). This is a collector-side improvement for the operator to request; the consumer must not assume it.
- **Version discipline.** The producer has kept `2.0.0` across two shapes. A real incompatible change must bump the major; the consumer cannot detect an incompatible change made under the same major other than by quarantine and diagnostic counts.
