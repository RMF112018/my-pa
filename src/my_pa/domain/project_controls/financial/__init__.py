"""Financial controlled source F-1: the pure finance domain (no IO, no clock, no persistence).

Contract: `docs/architecture/financial-source-contract.md` (sections 3-6) under
ADR-018 (Proposed -- not accepted). `money.py` is the Decimal-only money type,
`model.py` the closed vocabularies and immutable records, `equations.py` the
per-Project figures, reconciliation, consolidation and eliminations,
`reportability.py` run admission, version and mapping resolution and the
`NOT_REPORTABLE` evaluator, `canonical.py` the canonical objects and digests.

Nothing is re-exported here (contract F1-D01): the Constraint package surface of
`my_pa.domain.project_controls` is unchanged, and every importer names the
module it uses, which keeps the import graph explicit for the scope guard.
No real finance source is designated (OD-06); every input is synthetic.
"""
