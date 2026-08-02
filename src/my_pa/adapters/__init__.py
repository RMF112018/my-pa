"""Driving adapters: the ways a request reaches the application.

`D-23` splits the adapters by direction rather than by name. An adapter that
*drives* the application — HTTP, MCP, the operator CLI — lives here. An adapter
the application *drives* — persistence, source providers, extraction, the
migration plane — stays under `my_pa.infrastructure`, which is where all of them
already were. The split is one rule instead of a list, and it moves no module.

Everything here maps a protocol onto
`my_pa.application.service.ApplicationService.invoke` and maps its answer back.
Nothing here decides anything: no authorization, no policy, no disclosure, no
SQL, no provider access. `tests/architecture/test_transport_adds_no_behaviour.py`
is what makes that a property rather than a promise.

`normalization` is deliberately here and not inside `http`. `SPEC-AC-001` asks
that two transports produce byte-equivalent normalised requests, which is
provable when both build their `(RequestMetadata, Command)` pair with the same
function rather than with two functions that agree today.
"""

from __future__ import annotations

__all__: list[str] = []
