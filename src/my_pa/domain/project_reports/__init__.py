"""Project reports: the pure, source-neutral domain of exported project reports (WP3P-S1).

An exported project report is read-only original-source evidence: a CSV export
of one saved report of one Project, recognised by its ordered header list and
never by its filename. This package holds what such an export means once its
records have been read:

* the closed vocabularies (`model.py`);
* the header signature and the header checks (`signature.py`);
* the row-role classifier that separates detail rows from group headers,
  totals and spacers (`roles.py`);
* the Decimal-only amount parser, never rounding and never a float (`money.py`);
* the stated-total reconciliation and the cross-report check
  (`reconciliation.py`);
* the per-family record identity keys and the exact RFI matching rule
  (`identity.py`);
* detail-only measures with status separation (`measures.py`);
* the pure validation of the operator's bindings file (`bindings.py`);
* filename labels and the version order (`labels.py`), and the comparison of a
  series' versions that never infers closure from absence (`versions.py`);
* the reads' closed field catalogue and generated measure set
  (`catalogue.py`), their pure rules (series identity, Decimal strings,
  per-version filter semantics, comparison, the measure planner; `reads.py`)
  and their opaque cursor (`cursor.py`).

Nothing here does IO, reads a clock, mints an identifier or names an export
provider's header strings: those live in the infrastructure reader alone.

Nothing is re-exported: every importer names the module it uses.
"""
