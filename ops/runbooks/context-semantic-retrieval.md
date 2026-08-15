# Context retrieval and the semantic gate

Lexical/structured `context.prepare` is the active retrieval path. WP-KC-07
froze a synthetic semantic-retrieval benchmark on 2026-08-15. The recorded
disposition is `SEMANTIC_GATE_FAIL`. Production semantic retrieval is **not
authorized**. Do not enable `hybrid_semantic`, add a vector schema, or add a
model dependency from this runbook.

The three-part `SemanticRetrievalGate` stays all-false. Internal generative
`ModelRoutePolicy` remains `DISABLED`. WP-KC-08 (production semantic
implementation) runs only after a later evaluation records `SEMANTIC_GATE_PASS`.

## What the gate measured

A frozen synthetic corpus (invented names such as "Project Northwind quarterly
review" and "Capture: buy oat milk"; no personal data) compared:

- the production lexical/structured reason codes and `rank_and_pack`;
- one evaluation-only standard-library overlap candidate (character n-grams and
  token Jaccard), not imported by `src/` retrieval.

PASS required a paraphrase Recall@8 gain of at least +0.10 absolute, no drop in
exact-identifier Recall@8, zero cross-principal leakage, zero
`instruction_authority=true`, and no new dependency. The candidate did not meet
every clause, so the gate failed and lexical retrieval stays in production.

## Re-run the evaluation

From the repository root, with the project virtualenv:

```bash
PYTHONPATH=src .venv/bin/python -m pytest -q -m evaluation tests/evaluation
```

The SPECIALIZED test recomputes the metrics and asserts
`tests/evaluation/SEMANTIC_GATE.md` still matches. Changing the corpus, the
candidate, or the frozen thresholds is a new measurement and must update that
file and `CONTEXT_SEMANTIC_GATE_DISPOSITION` together.

This procedure does not open a database, call a network, or read live sources.
