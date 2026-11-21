"""Aggregate-only validation of `communications_evidence_v2` publications.

Usage (from an environment where this package is importable, e.g. an install
of this repository; `-I` keeps the environment and working directory out of
the import path)::

    python -I -m my_pa.infrastructure.communications.aggregate_cli FILE [FILE ...]

From a source checkout without an install: ``PYTHONPATH=src python -m ...``.

It parses each file, then prints one JSON document to stdout: per file the
size, file SHA-256, dialect, schema version, status, window bounds and
declared/actual hours, coverage, and counts (records per classification,
reason, folder role, identity state, body state, content type, integrity
outcome, searchable-text basis and flag, identifier kind, diagnostic code);
mailbox-item counts (multi-lane pairs, participant reconciliations and
disagreements, message-time basis); then a cross-file summary (observations,
unique identities and provider ids, cross-file repeats, Inbox+Sent identity
pairs under distinct provider ids, multi-lane items, reconciliations, lane
verification states, null-from records, empty subjects, window rules seen and
DST-flagged windows, identity conflicts, and merged coverage intervals and gaps
-- inclusive ends, windows at most `adjacency_tolerance_seconds` (1 s) apart
merge).

**The output is aggregate-only.** It contains no subject, body, address,
display name, provider id, internet message id, conversation id, source key or
other file-content string -- only counts, validated timestamps and dates,
closed-vocabulary members, and each file's *basename* as given on the command
line. Diagnostics are reported as code counts; their retained entries are not
printed. Identifier extraction reports kinds, never values.

Why here and not under `adapters/cli` or `apps/cli`: this is a validation tool
over the driven parser, invoking no capability and no application use case;
a driving adapter must contain no provider-format logic.

Exit status: `0` when every file was accepted; `1` when any file was rejected
or unreadable (the JSON is still printed); `2` on a usage error.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from my_pa.domain.communications.corpus import ADJACENCY_TOLERANCE_SECONDS, summarize_corpus
from my_pa.domain.communications.diagnostics import PublicationRejection
from my_pa.domain.communications.identifiers import IDENTIFIER_VERSION, extract_identifiers
from my_pa.domain.communications.model import (
    ItemFlag,
    Publication,
    RecordClassification,
    SourceCoverage,
)
from my_pa.domain.communications.search_text import SEARCH_TEXT_VERSION, derive_search_text
from my_pa.infrastructure.communications.evidence_v2 import (
    MAX_PUBLICATION_BYTES,
    PARSER_VERSION,
    PublicationParse,
    PublicationStatus,
    parse_publication,
)

__all__ = ["main", "summarize_files"]

TOOL: Final = "communications_evidence_aggregate"
#: Source keys printed by name; any other key is printed as `other`.
KNOWN_SOURCE_KEYS: Final = frozenset({"inbox", "sent", "procore_rfis"})

type Json = dict[str, object]


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _counts(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def _source(source: SourceCoverage) -> Json:
    return {
        "key_kind": source.key if source.key in KNOWN_SOURCE_KEYS else "other",
        "role": source.role.value,
        "lane": source.lane.value,
        "authorized": source.authorized,
        "coverage": source.state.value,
        "raw_messages": source.raw_messages,
        "pages": source.pages,
        "pages_not_ok": source.pages_not_ok,
        "errors": source.errors,
        "warnings": source.warnings,
    }


def _records(publication: Publication) -> Json:
    c: dict[str, Counter[str]] = {
        name: Counter()
        for name in (
            "by_classification", "by_reason", "by_folder_role", "by_lane_verification",
            "by_identity_state", "by_sent_time_state", "by_from_state",
            "by_body_state", "by_content_type", "body_integrity", "unique_body_integrity",
            "derived_text_integrity", "search_text_basis", "search_text_flags",
            "identifier_kind_messages", "identifier_kind_occurrences",
        )
    }  # fmt: skip
    for record in publication.records:
        c["by_classification"][record.classification.value] += 1
        c["by_reason"].update(reason.value for reason in record.reasons)
        message = record.message
        if message is None:
            continue
        c["by_folder_role"][message.folder_role.value] += 1
        c["by_lane_verification"][message.folder_verification.value] += 1
        c["by_sent_time_state"][message.timestamps.sent_state.value] += 1
        c["by_from_state"][message.participants["from"].state.value] += 1
        c["by_identity_state"][message.identity_state.value] += 1
        c["by_body_state"][message.body.state.value] += 1
        c["by_content_type"][message.body.content_type.value] += 1
        c["body_integrity"][message.body.integrity.value] += 1
        if message.unique_body is not None:
            c["unique_body_integrity"][message.unique_body.integrity.value] += 1
        if message.derived_text is not None:
            c["derived_text_integrity"][message.derived_text.integrity.value] += 1
        if record.classification is RecordClassification.QUARANTINED:
            continue
        search = derive_search_text(message)
        c["search_text_basis"][search.basis.value] += 1
        c["search_text_flags"].update(flag.value for flag in search.flags)
        identifiers = extract_identifiers(f"{message.subject or ''}\n{search.text or ''}")
        kinds = {identifier.kind.value for identifier in identifiers}
        c["identifier_kind_messages"].update(kinds)
        c["identifier_kind_occurrences"].update(identifier.kind.value for identifier in identifiers)
    result: Json = {"total": len(publication.records)}
    result.update({name: _counts(counter) for name, counter in c.items()})
    return result


def _items(publication: Publication) -> Json:
    """Mailbox-item aggregates: lane merges and participant reconciliation (counts only)."""
    flags: Counter[str] = Counter()
    basis: Counter[str] = Counter()
    for item in publication.items:
        flags.update(flag.value for flag in item.flags)
        basis[item.message_time_basis.value] += 1
    return {
        "total": len(publication.items),
        "multi_lane_pairs": flags[ItemFlag.MULTI_LANE.value],
        "participants_reconciled": flags[ItemFlag.PARTICIPANTS_RECONCILED.value],
        "participants_disagreed": flags[ItemFlag.PARTICIPANTS_DISAGREED.value],
        "bcc_from_sent_lane": flags[ItemFlag.BCC_FROM_SENT_LANE.value],
        "message_time_basis": _counts(basis),
    }


def _file_report(name: str, data: bytes | None, parsed: PublicationParse | None) -> Json:
    report: Json = {"file": name}
    if data is None or parsed is None:
        report.update(
            {"status": "rejected", "rejection": PublicationRejection.FILE_UNREADABLE.value}
        )
        return report
    report.update(
        {
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "status": parsed.status.value,
            "rejection": parsed.rejection.value if parsed.rejection is not None else None,
            "diagnostics": {
                "code_counts": dict(parsed.diagnostics.code_counts),
                "retained": len(parsed.diagnostics.entries),
                "overflow": parsed.diagnostics.overflow,
            },
        }
    )
    publication = parsed.publication
    if publication is None:
        return report
    window = publication.window
    report.update(
        {
            "dialect": publication.dialect.value,
            "schema_version": str(publication.schema_version),
            "business_date": publication.business_date.isoformat(),
            "cycle_run_id_present": publication.cycle_run_id_present,
            "window": {
                "start_utc": _iso(window.start_utc),
                "end_utc": _iso(window.end_utc),
                "end_inclusive": True,
                "declared_hours": window.declared_hours,
                "actual_hours": window.actual_hours,
                "actual_seconds": window.actual_seconds,
                "rule": window.rule.value,
                # Printed only once it resolved to a real zone: never a raw input string.
                "tz": window.tz if window.dst_change_computed is not None else None,
                "backfill": window.backfill,
                "dst_change_declared": window.dst_change_declared,
                "dst_change_computed": window.dst_change_computed,
            },
            "coverage": {
                "overall": publication.coverage_overall.value,
                "sources": [_source(source) for source in publication.sources],
            },
            "unknown_keys": {
                "top_level": publication.unknown_top_level_keys,
                "record": publication.unknown_record_keys,
            },
            "records": _records(publication),
            "items": _items(publication),
        }
    )
    return report


def summarize_files(paths: Sequence[Path]) -> tuple[Json, bool]:
    """The aggregate document for `paths`, and whether every file was accepted."""
    files: list[Json] = []
    publications: list[Publication] = []
    all_accepted = True
    for path in paths:
        data: bytes | None
        parsed: PublicationParse | None
        try:
            size = path.stat().st_size
            if size > MAX_PUBLICATION_BYTES:
                all_accepted = False
                files.append(
                    {
                        "file": path.name,
                        "bytes": size,
                        "status": PublicationStatus.REJECTED.value,
                        "rejection": PublicationRejection.FILE_TOO_LARGE.value,
                    }
                )
                continue
            data = path.read_bytes()
            parsed = parse_publication(data)
        except OSError:
            data, parsed = None, None
        except Exception:  # one bad file never aborts the batch
            # Content-free on purpose: neither the exception nor its message is
            # reported, because either could quote file content.
            all_accepted = False
            files.append(
                {
                    "file": path.name,
                    "status": PublicationStatus.REJECTED.value,
                    "rejection": PublicationRejection.INTERNAL_ERROR.value,
                }
            )
            continue
        if parsed is None or parsed.status is not PublicationStatus.ACCEPTED:
            all_accepted = False
        elif parsed.publication is not None:
            publications.append(parsed.publication)
        files.append(_file_report(path.name, data, parsed))

    summary = summarize_corpus(publications)
    document: Json = {
        "tool": TOOL,
        "parser_version": PARSER_VERSION,
        "search_text_version": SEARCH_TEXT_VERSION,
        "identifier_version": IDENTIFIER_VERSION,
        "files": files,
        "summary": {
            "files": len(paths),
            "accepted": len(publications),
            "rejected": len(paths) - len(publications),
            "observations": summary.observations,
            "usable_observations": summary.usable_observations,
            "unique_canonical_identities": summary.unique_canonical_identities,
            "unique_provider_ids": summary.unique_provider_ids,
            "provider_id_cross_file_repeats": summary.provider_id_cross_publication_repeats,
            "identity_cross_file_repeats": summary.identity_cross_publication_repeats,
            "inbox_sent_identity_pairs": summary.inbox_sent_identity_pairs,
            "multi_lane_items": summary.multi_lane_items,
            "participant_reconciliations": summary.participant_reconciliations,
            "participant_disagreements": summary.participant_disagreements,
            "lane_verification": dict(summary.lane_verification),
            "null_from_records": summary.null_from_records,
            "empty_subjects": summary.empty_subjects,
            "window_rules": dict(summary.window_rules),
            "dst_flagged_windows": summary.dst_flagged_windows,
            "within_file_identity_conflict_records": (
                summary.within_publication_identity_conflict_records
            ),
            "cross_file_identity_conflicts": summary.cross_publication_identity_conflicts,
            "coverage": {
                "intervals": [
                    {"start_utc": _iso(i.start), "end_utc": _iso(i.end)}
                    for i in summary.coverage_intervals
                ],
                "gaps": [
                    {
                        "start_utc": _iso(g.start),
                        "end_utc": _iso(g.end),
                        "seconds": g.inclusive_seconds,
                    }
                    for g in summary.coverage_gaps
                ],
                "publications_excluded": summary.publications_excluded_from_coverage,
                "end_inclusive": True,
                "adjacency_tolerance_seconds": ADJACENCY_TOLERANCE_SECONDS,
            },
        },
    }
    return document, all_accepted


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m my_pa.infrastructure.communications.aggregate_cli",
        description="Validate communications_evidence_v2 files; print aggregate-only JSON.",
    )
    parser.add_argument("files", nargs="+", type=Path, metavar="FILE")
    arguments = parser.parse_args(argv)
    document, all_accepted = summarize_files(arguments.files)
    sys.stdout.write(json.dumps(document, indent=1, sort_keys=False) + "\n")
    return 0 if all_accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
