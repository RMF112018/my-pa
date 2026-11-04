"""Frozen bounds and enumerations of the general report plane.

Every value here is also a database literal: the WP01 migration restates these
bounds in CHECK constraints, so changing one is a schema change, never a
silent reinterpretation of stored rows.
"""

from __future__ import annotations

import re
from datetime import timedelta
from enum import StrEnum
from typing import Final

__all__ = [
    "MANIFEST_SCHEMA",
    "MAX_ASSOCIATIONS_PER_VERSION",
    "MAX_ASSOCIATION_REF_CHARACTERS",
    "MAX_DECODED_CONTENT_BYTES",
    "MAX_MANIFEST_BYTES",
    "MAX_METADATA_BYTES",
    "MAX_METADATA_DEPTH",
    "MAX_METADATA_FLOAT_MAGNITUDE",
    "MAX_METADATA_KEYS",
    "MAX_METADATA_KEY_CHARACTERS",
    "MAX_ORIGINAL_CONTENT_BYTES",
    "MAX_REASON_CHARACTERS",
    "MAX_SUMMARY_CHARACTERS",
    "MAX_TERMS",
    "MAX_TERM_CHARACTERS",
    "MAX_TITLE_CHARACTERS",
    "MIN_METADATA_FLOAT_MAGNITUDE",
    "RESERVED_METADATA_KEY_PREFIXES",
    "RESERVED_TYPE_PREFIXES",
    "TRANSFER_CHUNK_MAX_BYTES",
    "TRANSFER_MAX_TTL",
    "TYPE_TOKEN_PATTERN",
    "AssociationTargetKind",
    "AssociationVerification",
    "ChangeKind",
    "ContentEncoding",
    "ContentFormat",
    "LifecycleOperation",
    "LifecycleState",
    "ReceiptOperation",
    "ReceiptOutcome",
    "StorageKind",
    "TransferState",
]

#: A report type and an association relation token (`^[a-z][a-z0-9_]{0,63}$`).
TYPE_TOKEN_PATTERN: Final = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z")
#: Type namespaces the product keeps for itself; a caller type may not use one.
RESERVED_TYPE_PREFIXES: Final = ("my_pa_", "system_", "internal_")

#: Code points after NFC.
MAX_TITLE_CHARACTERS: Final = 256
MAX_SUMMARY_CHARACTERS: Final = 2000
MAX_REASON_CHARACTERS: Final = 500

#: Topics and tags are separate tuples bounded alike.
MAX_TERMS: Final = 24
MAX_TERM_CHARACTERS: Final = 64

MAX_METADATA_KEYS: Final = 32
#: The top-level object is depth 1; every nested object or array adds one.
MAX_METADATA_DEPTH: Final = 4
#: Canonical UTF-8 serialization: sorted keys, `(",", ":")`, `ensure_ascii=False`.
MAX_METADATA_BYTES: Final = 16384
MAX_METADATA_KEY_CHARACTERS: Final = 64
#: A non-zero metadata float has `MIN <= abs(x) < MAX`. In that range Python's
#: shortest `repr` has no exponent, and PostgreSQL's jsonb text prints the same
#: digits; outside it, jsonb text spells `1e308` with 309 digits, so a
#: canonically small object could exceed the stored text bound (32768).
MIN_METADATA_FLOAT_MAGNITUDE: Final = 1e-4
MAX_METADATA_FLOAT_MAGNITUDE: Final = 1e16
RESERVED_METADATA_KEY_PREFIXES: Final = ("_", "my_pa", "system")

MAX_DECODED_CONTENT_BYTES: Final = 16_777_216
MAX_ORIGINAL_CONTENT_BYTES: Final = 16_777_216

MANIFEST_SCHEMA: Final = "report_version_manifest_v1"
MAX_MANIFEST_BYTES: Final = 65536

MAX_ASSOCIATIONS_PER_VERSION: Final = 64
#: Bound on an association's `target_ref` and `target_version_ref`.
MAX_ASSOCIATION_REF_CHARACTERS: Final = 512

TRANSFER_CHUNK_MAX_BYTES: Final = 262144
TRANSFER_MAX_TTL: Final = timedelta(hours=24)


class ContentFormat(StrEnum):
    MARKDOWN = "markdown"
    TEXT = "text"
    JSON = "json"
    MIXED = "mixed"


class ContentEncoding(StrEnum):
    IDENTITY = "identity"
    GZIP_BASE64 = "gzip+base64"


class StorageKind(StrEnum):
    INLINE = "inline"
    MANAGED_BLOB = "managed_blob"


class LifecycleState(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"
    TRASHED = "trashed"


class LifecycleOperation(StrEnum):
    ARCHIVE = "archive"
    DELETE = "delete"
    RESTORE = "restore"


class ChangeKind(StrEnum):
    INITIAL = "initial"
    CONTENT = "content"
    METADATA = "metadata"


class ReceiptOperation(StrEnum):
    PUBLISH = "publish"
    UPDATE = "update"
    ARCHIVE = "archive"
    DELETE = "delete"
    RESTORE = "restore"


class ReceiptOutcome(StrEnum):
    APPLIED = "applied"
    NO_OP = "no_op"


class AssociationTargetKind(StrEnum):
    PROJECT = "project"
    ENTITY = "entity"
    STANDALONE_REPORT = "standalone_report"
    INTELLIGENCE_REPORT = "intelligence_report"
    EXTERNAL_SOURCE = "external_source"


class AssociationVerification(StrEnum):
    ASSERTED = "asserted"
    VERIFIED = "verified"


class TransferState(StrEnum):
    OPEN = "open"
    FINALIZED = "finalized"
    CONSUMED = "consumed"
    ABORTED = "aborted"
    EXPIRED = "expired"
