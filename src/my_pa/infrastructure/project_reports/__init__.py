"""Project reports: the export reader, its signature registry and the file-level aggregate.

`pulse_csv.py` reads one exported CSV report strictly (RFC 4180, UTF-8 only),
plans its raw rows so they reconstruct the file byte-exact, recognises the
report by its header signature and derives a classified or quarantined plan
through one adapter per family view. It is the **only** module that names the
export provider's header strings. `aggregate_cli.py` runs it over files and
prints closed-vocabulary counts only.

Pure apart from the CLI reading the files it is named: no database, network,
environment, clock or logging. Nothing is re-exported.
"""
