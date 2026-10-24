"""Record lineage domain, Slice S1 (ADR-015; `docs/architecture/record-lineage-s1-contract.md`).

`vocabulary.py` holds the closed S1 vocabularies, `model.py` the endpoint and
evidence-anchor value objects, and `canonical.py` the canonical encodings
(anchor identity and order, evidence-set digest, passage digest, normalized
link identity, request digest). Pure domain: nothing here persists, mints an
identifier or reads a clock.
"""
