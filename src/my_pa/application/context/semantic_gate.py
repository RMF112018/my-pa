"""Frozen semantic-retrieval gate for context preparation.

WP-KC-07 records a lexical/structured baseline and one standard-library
candidate against a frozen synthetic set. Production `context.prepare` stays on
`lexical_structured` until this module records `SEMANTIC_GATE_PASS`. The
three-part `SemanticRetrievalGate` on the model boundary remains all-false
regardless of this disposition; a later work package is not authorized by a
comment or a ranking reason code.

Decision rule, frozen before harness numbers are consulted. PASS requires every
clause below; otherwise FAIL:

1. Paraphrase Recall@8 rises by at least `PARAPHRASE_RECALL_AT_8_MIN_ABSOLUTE_DELTA`
   versus the lexical/structured path.
2. Exact-identifier Recall@8 does not fall versus lexical.
3. Cross-principal leakage is zero on both paths.
4. `instruction_authority` remains false on every packed item.
5. No new runtime or development dependency is introduced.

These thresholds exist so a private overlap candidate cannot open production
semantic retrieval unless it shows a material paraphrase gain without dropping
exact-identifier retrieval, weakening Principal isolation, or treating retrieved
text as instructions. Anything less leaves lexical/structured retrieval as the
production path. WP-KC-08 runs only after PASS.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "CONTEXT_SEMANTIC_GATE_DISPOSITION",
    "K_RECALL",
    "PARAPHRASE_RECALL_AT_8_MIN_ABSOLUTE_DELTA",
    "SEMANTIC_GATE_FAIL",
    "SEMANTIC_GATE_PASS",
]

SEMANTIC_GATE_PASS: Final = "SEMANTIC_GATE_PASS"  # noqa: S105
SEMANTIC_GATE_FAIL: Final = "SEMANTIC_GATE_FAIL"

PARAPHRASE_RECALL_AT_8_MIN_ABSOLUTE_DELTA: Final = 0.10
K_RECALL: Final = (8, 16)

#: Frozen after the WP-KC-07 harness ran on 2026-08-15. Recompute with
#: `PYTHONPATH=src .venv/bin/python -m pytest -q -m evaluation tests/evaluation`
#: before changing this token.
CONTEXT_SEMANTIC_GATE_DISPOSITION: Final = SEMANTIC_GATE_FAIL
