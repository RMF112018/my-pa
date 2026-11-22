"""Composition of the communications ingestion consumer (WP3a, Manager ruling M5).

The one place the `communications_evidence_v2` parser (infrastructure) meets
its lifecycle handler (application): `communications_handler()` injects
`parse_publication`, `PARSER_VERSION` and `MAX_PUBLICATION_BYTES` into
`CommunicationsEvidenceHandler`. The operator CLI and the cycles-plane poll step
build their `IngestionLifecycle` with this handler.
"""

from __future__ import annotations

from my_pa.application.communications_ingest import (
    CommunicationsEvidenceHandler,
    ParsedPublication,
)
from my_pa.infrastructure.communications.evidence_v2 import (
    MAX_PUBLICATION_BYTES,
    PARSER_VERSION,
    parse_publication,
)

__all__ = ["communications_handler", "parse_for_ingestion"]


def parse_for_ingestion(data: bytes) -> ParsedPublication:
    """`parse_publication`, as the handler's injected parser answer."""
    parsed = parse_publication(data)
    return ParsedPublication(
        publication=parsed.publication,
        rejection=parsed.rejection,
        diagnostic_counts=parsed.diagnostics.code_counts,
    )


def communications_handler() -> CommunicationsEvidenceHandler:
    """The `communications_evidence_v2` handler with the WP1 parser wired in."""
    return CommunicationsEvidenceHandler(
        parse=parse_for_ingestion,
        parser_version=PARSER_VERSION,
        max_bytes=MAX_PUBLICATION_BYTES,
    )
