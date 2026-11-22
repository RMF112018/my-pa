"""Meeting sync: the pure, provider-neutral `meeting_sync_v1` domain (WP2).

This package holds what a `meeting_sync_v1` publication means once it has been
parsed: the closed vocabularies and immutable event records (`model.py`),
bounded content-free diagnostics (`diagnostics.py`), and the provider identity
and recurrence resolution rules of the communications-intelligence contract
section 12.2 (`resolution.py`), as pure decisions over already-read state.

The parser that maps publication bytes onto these types is
`my_pa.infrastructure.meeting_sync.parser`; the application service that applies
a resolution inside the caller's unit of work is
`my_pa.application.meeting_provider_sync`. Nothing here does IO, reads a clock,
mints an identifier or names a provider.

Nothing is re-exported: every importer names the module it uses.
"""
