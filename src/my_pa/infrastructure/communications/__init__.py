"""Communications evidence: the `communications_evidence_v2` parser and its aggregate CLI.

`evidence_v2.py` maps a producer publication (JSON bytes, either dialect) onto
the provider-neutral types of `my_pa.domain.communications`; it is the only
place the producer's field names and provider vocabulary appear.
`aggregate_cli.py` validates files and prints aggregate-only JSON.

Pure apart from the CLI reading the files it is named: no database, network,
environment, clock or logging. Nothing is re-exported.
"""
