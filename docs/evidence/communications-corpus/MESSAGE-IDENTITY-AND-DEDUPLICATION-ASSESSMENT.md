# Message identity and deduplication assessment

**Basis:** see the [common basis](README.md#common-basis) (aggregate JSON SHA-256 `82edeee885125a6552a00f7046adbefe0337d5e035905fc08dcceb2261a7945d`, 2026-11-21, Manager-run collection; 31 publications = 29 canonical lean + 2 rich), with the post-validation corrections of 2026-11-21 (contract head `ac0d06ae`). Aggregates only: no identifier value appears here.

## Identity fields

| Field | Observed |
| --- | --- |
| Observations (records) | 4,141 |
| Provider id format | `graph_default_mutable` in 4,141 (the provider's default, **mutable** item id) |
| Immutable-id header | requested `false`, applied evidence `none` in 4,141 |
| `message_id` equals `id` | 4,141 |
| Internet Message-ID state | `provider_returned` in 4,141 (0 missing) |
| Conversation id state | `provider_returned` in 4,141 (0 missing) |
| Mailbox references | 1 |
| Source lane | `mail` in 4,141 |
| `source_folder.folder_id` | null in all 4,141 |
| `parent_folder_id_returned` | null in the 3,944 lean records; returned in the 197 rich records |
| `from` state | `provider_returned` 4,139; `not_returned` 2 (null `from`) |
| Empty subjects | 7 |

## Distinct counts

| Measure | Value |
| --- | ---: |
| Distinct provider ids | 3,527 |
| Distinct `(mailbox, Internet Message-ID)` | **3,461** |
| Distinct producer `dedup_key` | 3,527 (the mailbox reference joined to the provider id, so it counts provider ids) |
| Provider ids seen in more than one publication | 191 groups |
| Internet Message-IDs seen in more than one publication | 188 groups |
| Provider id repeated within one publication | 422 records (421 lane pairs + 1 exact repeat) |
| Internet Message-IDs carried by two distinct provider ids | **66** (50 Inbox+Sent pairs, 16 Inbox+Inbox pairs) |
| Provider id mapping to two Internet Message-IDs | 0 |
| Body SHA-256 changing under one provider id or one Message-ID | 0 |
| Subject changing under one Message-ID | 0 |
| Selected timestamp differing within one Message-ID group | 407 groups (received vs sent time) |

3,527 − 3,461 = 66: the gap between provider ids and canonical identities is exactly the 66 Message-IDs held by two mailbox items. The two provider ids of each such pair share a long common prefix (114 or 115 characters), consistent with two items in one mailbox store.

## Finding 1 — the backfill folder-attribution defect (lane observations)

In 23 backfill publications (2026-10-18 to 2026-11-13, including 2026-11-01 and 2026-11-08) every Sent item **also** appears as an inbox-role record carrying the **same** provider id: 421 such pairs. A provider mailbox item lives in one folder, so the inbox copy is a lane or query artifact of the collector, not a second item. Because `folder_id` and `parent_folder_id_returned` are null in the lean dialect, the folder role is the collection lane's **claim**, not verified folder membership.

The two records of a pair differ in:

- the selected timestamp field (received time on the inbox copy, sent time on the sent copy);
- `bcc` (only the sent copy exposes it);
- in 14 pairs, the `to` or `cc` lists — but **only in display name, raw form and trust metadata**. After normalization the address sets are identical in all 14: **0 address-level disagreements** (correction after contract validation; the earlier "12–14 pairs differ" did not separate metadata from addresses).

`duplicate_observations` is 1 on both records, so the collector did not flag them. Publications 2026-11-16, -17, -18 and -20 do not show the defect.

Contract result: 421 records classified `lane_observation_merged`, 421 multi-lane mailbox items, 421 participant reconciliations, **0 participant disagreements**, `bcc` taken from the sent lane in 421 items.

## Finding 2 — two mailbox items, one message

66 Internet Message-IDs are carried by two distinct provider ids. 50 are an Inbox item plus a Sent item (for example self-addressed mail); 16 are two distinct Inbox items (for example duplicate delivery). Both are genuine separate mailbox items under one canonical message. The contract counted 50 `inbox_sent_identity_pairs` and 0 identity conflicts.

## Finding 3 — cross-publication repeats are identical

191 provider ids recur across publications (weekend windows, the rich files overlapping canonical ones). Every repeat has the identical body SHA-256 and subject. No provider id ever maps to two Message-IDs. The contract counted 0 cross-file identity conflicts.

## Finding 4 — one exact within-file repeat

`20261120-comms.json` holds one record repeated with the same provider id in the same folder role. The contract classified it `duplicate_observation` (diagnostic `duplicate_provider_id`).

## Finding 5 — what is never identity

- **`dedup_key`** is the mailbox reference joined to the provider id: it splits the 66 two-item messages, and it is not stable under a mutable provider id.
- **Body SHA-256**: 35 body-hash groups span distinct identities (short or templated bodies).
- **Subject**: 479 subject groups span distinct identities.
- **Provider id**: mutable (`graph_default_mutable`); it identifies a mailbox item at collection time, and an item moved between folders may get a new id.

## Contract classification totals (all 31 files)

| Classification | Records |
| --- | ---: |
| `accepted` | 3,711 |
| `accepted_degraded` | 8 |
| `lane_observation_merged` | 421 |
| `duplicate_observation` | 1 |
| `out_of_window` | 0 |
| `quarantined` | 0 |
| **Total** | **4,141** |

Mailbox items built within publications: 3,719 (= 4,141 − 421 − 1). Canonical message time basis: received 3,172 items, sent 547 items. Lane verification: 197 `verified` (rich), 3,944 `unverified_lane_claim` (lean).
