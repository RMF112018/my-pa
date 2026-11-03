"""Schedule Scenarios S6-1: pure scenario domain and the deterministic CPM engine.

Contract: `docs/architecture/schedule-scenarios-contract.md` sections 2-4 and 9.1.
Pure and standard-library only (plus `my_pa.domain.schedule` and the opaque
identifier validator): no database, IO, network, clock, randomness,
environment or `float`. Callers import the submodules; this package holds no
logic.
"""
