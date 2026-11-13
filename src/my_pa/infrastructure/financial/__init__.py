"""Financial controlled source F-1: the synthetic interchange parser (no IO, no persistence).

Contract: `docs/architecture/financial-source-contract.md` section 7 under
ADR-018 (Proposed -- not accepted). `synthetic_csv.py` parses the invented,
neutral `my-pa-synthetic-finance-v1` format -- modelled on no real ERP,
accounting, project-management or scheduling export -- into a domain
`SourceVersion` or a closed refusal code. No real finance source is designated
(OD-06); nothing here is imported by any application module (the scope guard
pins it). Nothing is re-exported.
"""
