"""Frozen limits and the closed refusal vocabulary of the file workspace plane.

Every figure is the files-workspace contract's section 8 (Manager-approved);
the reason tokens are its section 7. Changing one here without changing the
contract first is a contract violation, not a tuning.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = [
    "BYTE_ROUTE_CONCURRENCY",
    "DISK_RESERVE_BYTES",
    "MAX_COMPONENT_BYTES",
    "MAX_PATH_BYTES",
    "MAX_PREVIEW_BYTES",
    "MAX_SEARCH_QUERY_CHARACTERS",
    "MAX_UPLOAD_BYTES",
    "MAX_UPLOAD_CHUNK_BYTES",
    "MAX_WRITE_TEXT_BYTES",
    "PAGE_SIZE",
    "RESERVED_NAMES",
    "SEARCH_WALK_MAX_DEPTH",
    "SEARCH_WALK_MAX_ENTRIES",
    "TICKET_TTL_DEFAULT_SECONDS",
    "TICKET_TTL_MAX_SECONDS",
    "TICKET_TTL_MIN_SECONDS",
    "FilesReason",
]

_KIB: Final = 1024
_MIB: Final = 1024 * _KIB
_GIB: Final = 1024 * _MIB

#: Section 8: the default per-upload ceiling (`MY_PA_FILES_MAX_UPLOAD_BYTES`).
MAX_UPLOAD_BYTES: Final = 10 * _GIB
#: Section 8: the default free-space reserve (`MY_PA_FILES_DISK_RESERVE_BYTES`).
DISK_RESERVE_BYTES: Final = 20 * _GIB
#: Section 8: one PATCH body, under the tunnel's 100 MB request cap.
MAX_UPLOAD_CHUNK_BYTES: Final = 32 * _MIB
#: Section 8: one `files.preview` call.
MAX_PREVIEW_BYTES: Final = 256 * _KIB
#: Section 8: the UTF-8 encoding of one `files.write_text` text (trim T13).
#:
#: The largest whole-KiB value whose worst-case `ensure_ascii` JSON encoding
#: still fits `adapters.normalization.MAX_REQUEST_BYTES` (762,288) on every
#: transport, so the advertised limit is reachable and a larger text is refused
#: by the command naming `text`, never by an unnamed transport refusal. The text
#: admits C0 controls, each one UTF-8 byte that escapes to six (`\u0000`), so
#: the worst case is 6 JSON bytes per text byte (2-4 byte characters escape to
#: at most 3 per byte). Everything beside it, at its own bound:
#:   path            4,096 bytes x 3 (C0 and `\` refused)       = 12,288
#:   workspace_id    64 chars x 12 (astral surrogate pair)      =    768
#:   idempotency_key 128 chars x 12                             =  1,536
#:   request_id      128 chars x 12                             =  1,536
#:   expected_version 68, principal_id 72                       =    140
#:   keys, purpose, timestamp, JSON-RPC/facade framing reserve  =  4,096
#:   total beside the text                                      = 20,364
#: (762,288 - 20,364) / 6 = 123,654 bytes, so 120 KiB = 122,880 (6x = 737,280;
#: with the rest 757,644 <= 762,288). 121 KiB (123,904) would not fit.
MAX_WRITE_TEXT_BYTES: Final = 120 * _KIB
#: Section 8: list, search and history pages (also the default page size).
PAGE_SIZE: Final = 200
#: Section 8: the bounded name walk of `files.search` and a directory copy.
SEARCH_WALK_MAX_ENTRIES: Final = 20_000
SEARCH_WALK_MAX_DEPTH: Final = 32
#: Section 6: a search query is 1-255 characters.
MAX_SEARCH_QUERY_CHARACTERS: Final = 255
#: Section 8: ticket lifetime. The contract states the default and the maximum
#: only; the minimum is the `reports.transfer` precedent (300 s), the
#: conservative reading recorded in the WP2 handoff.
TICKET_TTL_DEFAULT_SECONDS: Final = 3600
TICKET_TTL_MIN_SECONDS: Final = 300
TICKET_TTL_MAX_SECONDS: Final = 86400
#: Section 8: the byte routes' own per-process concurrency cap (default).
BYTE_ROUTE_CONCURRENCY: Final = 4

#: Section 3 rule 4.
MAX_COMPONENT_BYTES: Final = 255
MAX_PATH_BYTES: Final = 4096

#: Section 3 rule 5, already ASCII-case-folded: compared against a folded name.
RESERVED_NAMES: Final = frozenset({".my-pa", "@eadir", "#recycle", "#snapshot"})


class FilesReason(StrEnum):
    """Section 7: the closed set of files refusal reason tokens.

    A token names a condition; it never carries a path, a name or content.
    """

    INVALID_PATH = "invalid_path"
    NOT_FOUND = "not_found"
    EXISTS = "exists"
    VERSION_CONFLICT = "version_conflict"
    EXTERNAL_CHANGE_DETECTED = "external_change_detected"
    UNSUPPORTED_ENTRY = "unsupported_entry"
    TOO_LARGE = "too_large"
    QUOTA = "quota"
    DIGEST_MISMATCH = "digest_mismatch"
    OFFSET_MISMATCH = "offset_mismatch"
    TICKET_INVALID = "ticket_invalid"
