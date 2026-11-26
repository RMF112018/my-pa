"""Counts-only identifier measurement of `communications_evidence_v2` publications.

Usage (communications WP4 ruling D3; the Manager runs it over the private
corpus, the worker never sees its input)::

    PYTHONPATH=src python -m my_pa.infrastructure.communications.identifier_measure_cli \\
        FILE [FILE ...]

It parses each file with the evidence_v2 parser (the `aggregate_cli`
precedent) and prints one JSON document: the tool and version names, how many
files were given, accepted and rejected, how many usable records were
measured, `disclaimer_removed` per search-text version and, per identifier
kind, the `measure_identifiers` counts (`my_pa.domain.communications.measurement`):
records per version, lost and gained, v2 occurrences, records per form class
and the attribution of the gap to the analysis count.

**The output is counts only.** No subject, body, address, identifier value,
file name, path or rejection detail is printed -- only kinds, closed
form-class names and integers. A file that cannot be read or parsed is counted
as rejected, never described.

Exit status: `0` when every file was accepted; `1` when any was rejected (the
JSON is still printed, over the accepted ones); `2` on a usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from my_pa.domain.communications.identifiers import IDENTIFIER_VERSION_V1, IDENTIFIER_VERSION_V2
from my_pa.domain.communications.measurement import measure_identifiers
from my_pa.domain.communications.model import Publication
from my_pa.domain.communications.search_text import SEARCH_TEXT_VERSION_V1, SEARCH_TEXT_VERSION_V2
from my_pa.infrastructure.communications.evidence_v2 import (
    MAX_PUBLICATION_BYTES,
    PARSER_VERSION,
    PublicationStatus,
    parse_publication,
)

__all__ = ["main", "measure_files"]

TOOL: Final = "communications_identifier_measure"

type Json = dict[str, object]


def _publication(path: Path) -> Publication | None:
    """The accepted publication in `path`, or `None` for any refusal (content-free)."""
    try:
        if path.stat().st_size > MAX_PUBLICATION_BYTES:
            return None
        parsed = parse_publication(path.read_bytes())
    except Exception:  # one bad file never aborts the batch, and is never described
        return None
    if parsed.status is not PublicationStatus.ACCEPTED:
        return None
    return parsed.publication


def measure_files(paths: Sequence[Path]) -> tuple[Json, bool]:
    """The counts-only document for `paths`, and whether every file was accepted."""
    publications = [p for p in (_publication(path) for path in paths) if p is not None]
    measurement = measure_identifiers(publications)
    document: Json = {
        "tool": TOOL,
        "parser_version": PARSER_VERSION,
        "identifier_versions": [IDENTIFIER_VERSION_V1, IDENTIFIER_VERSION_V2],
        "search_text_versions": [SEARCH_TEXT_VERSION_V1, SEARCH_TEXT_VERSION_V2],
        "files": len(paths),
        "accepted": len(publications),
        "rejected": len(paths) - len(publications),
        "records": measurement.records,
        "disclaimer_removed": dict(measurement.disclaimer_removed),
        "kinds": {
            kind: {
                "records_v1": counts.records_v1,
                "records_v2": counts.records_v2,
                "records_v1_only": counts.records_v1_only,
                "records_v2_only": counts.records_v2_only,
                "occurrences_v2": counts.occurrences_v2,
                "by_form_class_v2": dict(counts.by_form_class_v2),
                "gap": {
                    "records_quoted_or_tail_only": counts.records_quoted_or_tail_only,
                    "records_keyword_without_number": counts.records_keyword_without_number,
                    "records_unsupported_shape": counts.records_unsupported_shape,
                },
            }
            for kind, counts in measurement.kinds.items()
        },
    }
    return document, len(publications) == len(paths)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m my_pa.infrastructure.communications.identifier_measure_cli",
        description="Measure identifiers in communications_evidence_v2 files; counts only.",
    )
    parser.add_argument("files", nargs="+", type=Path, metavar="FILE")
    arguments = parser.parse_args(argv)
    document, all_accepted = measure_files(arguments.files)
    sys.stdout.write(json.dumps(document, indent=1, sort_keys=False) + "\n")
    return 0 if all_accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
