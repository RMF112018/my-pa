# Semantic retrieval gate

Date: 2026-08-15

Disposition: `SEMANTIC_GATE_FAIL`

Production semantic retrieval is **not authorized**. The active path is lexical/structured `context.prepare`. This file is the frozen WP-KC-07 decision. Re-run the evaluation to recompute; the JSON record below must match the harness exactly.

```json
{
  "baseline": {
    "k16": {
      "cross_principal_leakage": 0,
      "duplicate_rate_after_packing": 0.0,
      "exact_id_recall_at_k": 1.0,
      "instruction_authority_true": 0,
      "missing_required_returns": 0,
      "mrr": 0.4333,
      "paraphrase_recall_at_k": 0.3333,
      "recall_at_k": 0.8
    },
    "k8": {
      "cross_principal_leakage": 0,
      "duplicate_rate_after_packing": 0.0,
      "exact_id_recall_at_k": 1.0,
      "instruction_authority_true": 0,
      "missing_required_returns": 0,
      "mrr": 0.4333,
      "paraphrase_recall_at_k": 0.3333,
      "recall_at_k": 0.8
    }
  },
  "candidate": {
    "k16": {
      "cross_principal_leakage": 0,
      "duplicate_rate_after_packing": 0.0,
      "exact_id_recall_at_k": 1.0,
      "instruction_authority_true": 0,
      "missing_required_returns": 0,
      "mrr": 0.5333,
      "paraphrase_recall_at_k": 0.3333,
      "recall_at_k": 0.8
    },
    "k8": {
      "cross_principal_leakage": 0,
      "duplicate_rate_after_packing": 0.0,
      "exact_id_recall_at_k": 1.0,
      "instruction_authority_true": 0,
      "missing_required_returns": 0,
      "mrr": 0.5333,
      "paraphrase_recall_at_k": 0.3333,
      "recall_at_k": 0.8
    }
  },
  "date": "2026-08-15",
  "disposition": "SEMANTIC_GATE_FAIL",
  "k": [
    8,
    16
  ],
  "new_forbidden_dependency_count": 0,
  "note": "Production semantic retrieval is not authorized. context.prepare remains lexical_structured. WP-KC-08 runs only after SEMANTIC_GATE_PASS.",
  "paraphrase_delta_at_8": 0.0,
  "paraphrase_recall_at_8_min_absolute_delta": 0.1,
  "production_semantic_authorized": false
}
```
