# Gate B v1 corpus — operator disposition `REJECT_FOR_B0`

coordination_request_id: `REQ-MYPA-GOODNOTES-GATE-B-EVALUATION-20260820-001`

Operator review rejected `gsqs-v1` as the production-relevant Gate B
baseline. Keep it as a **deterministic synthetic regression/canary**
only. Do not freeze it as `MEASURED_B0`.

The current v1 identity (after gold-digest and unreadable-render
corrections) is:

| Field | Value |
| --- | --- |
| Corpus version | `gsqs-v1` |
| Generator | `gsqs-v1-generator-1` |
| Manifest digest | `3c2e0131fbf976a8294753b999c5c1d47572e9252d4fbc50b00732768e144728` |
| Approval status | `REJECT_FOR_B0` |
| `FIXED_LABELED_CORPUS_APPROVED` | false |
| `b0_suitable` | false |

The previously published digest
`971083804db9fc46295db1ea64dcf2288d4aa1feaddd1ac8a26345f3579bb6d3`
is historical. It did not bind full gold truth and is not the current
v1 identity.

## Why it remains in the tree

v1 still exercises the evaluator, freeze path, and CI canary. Replica
siblings (`r1`/`r2`/`r3`) can occupy different partitions; that leakage
is why it is `REJECT_FOR_B0`. Each v1 case now has
`leakage_group_id = case_id`, so the *group-isolation freeze check*
passes without claiming template-family isolation.

Use [`../v2/OPERATOR_REVIEW.md`](../v2/OPERATOR_REVIEW.md) for the
corrected corpus offered for operator review.

## Size (unchanged composition)

97 pages, 93 scoreable, 115 NOTE_UNITs. Partitions A/B/C scoreable
pages: 45 / 24 / 24. Personal data: none.

UNREADABLE gold notes now render scribble strokes rather than the
literal `[UNREADABLE]` placeholder.

## What this package does not do

- establish `MEASURED_B0`
- serve as the production-relevant handwriting baseline
- activate self-improvement or automatic promotion
