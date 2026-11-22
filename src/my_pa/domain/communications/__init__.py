"""Communications evidence: the pure, provider-neutral domain (no IO, no clock, no persistence).

This package holds what the `communications_evidence_v2` source contract means
once a publication has been parsed: the closed vocabularies and immutable
records (`model.py`), bounded diagnostics (`diagnostics.py`), per-record
classification and within-publication identity and lane rules (`classification.py`), mailbox
items with reconciled participants (`reconciliation.py`),
content-integrity checks (`integrity.py`), the versioned searchable-text
derivation (`search_text.py`), the versioned technical-identifier extractor
(`identifiers.py`), and cross-publication coverage and identity summaries
(`corpus.py`).

Provider field names (the producer's JSON keys and provider vocabulary) live in
`my_pa.infrastructure.communications.evidence_v2`, the parser that maps a
publication onto these types; nothing here names a provider.

Nothing is re-exported: every importer names the module it uses.
"""
