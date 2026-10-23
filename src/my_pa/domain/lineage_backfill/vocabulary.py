"""Closed vocabularies of the record lineage S3 backfill dry run (S3 contract section 3).

Each enum holds exactly what the S3 revision's `lineage_backfill_runs` and
`lineage_backfill_items` CHECKs admit; the revision restates each as a frozen
literal and imports nothing from here (`D-48`, `D-69`). The apply states
(`applying`, `applied`) and the `source_backed_verified` acceptance basis are the
deferred apply package's (S3 contract section 11).

Pure data: this module persists nothing and grants nothing.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

__all__ = [
    "BACKFILL_VALIDATOR_VERSION",
    "BackfillClass",
    "BackfillReason",
    "BackfillRunState",
    "BackfillSourceKind",
]

#: S3 section 8.3: the version of the backfill classification rules a run binds.
BACKFILL_VALIDATOR_VERSION: Final = 1


class BackfillClass(StrEnum):
    """S3 section 8.3: the one class every backfill item is classified into."""

    NATIVE_VIRTUAL_PROVEN = "native_virtual_proven"
    SOURCE_BACKED_ACCEPTED = "source_backed_accepted"
    REVIEW_CANDIDATE = "review_candidate"
    UNRESOLVED = "unresolved"
    REFUSED = "refused"


class BackfillSourceKind(StrEnum):
    """S3 section 8.3: the native shape one backfill item was enumerated from."""

    TASK_FOLLOW_UP = "task_follow_up"
    CONSTRAINT_FOLLOW_UP = "constraint_follow_up"
    MEETING_SERIES = "meeting_series"
    PROJECT_SITUATION = "project_situation"
    WORK_ORIGIN_ASSERTION = "work_origin_assertion"
    WORK_ORIGIN_CAPTURE_ROOT = "work_origin_capture_root"
    WORK_ORIGIN_OTHER = "work_origin_other"
    SITUATION_OBJECT_REF = "situation_object_ref"


class BackfillReason(StrEnum):
    """S3 section 8.3: why an item has its class (the classification table's reasons)."""

    NATIVE_FOLLOW_UP = "native_follow_up"
    NATIVE_CONSTRAINT_FOLLOW_UP = "native_constraint_follow_up"
    NATIVE_MEETING_SERIES = "native_meeting_series"
    NATIVE_PROJECT_SITUATION = "native_project_situation"
    PROJECT_SITUATION_INCONSISTENT = "project_situation_inconsistent"
    EXACT_ORIGINAL_SPAN = "exact_original_span"
    PASSAGE_UNPROVEN = "passage_unproven"
    ASSERTION_NOT_CURRENT = "assertion_not_current"
    SOURCE_WITHDRAWN = "source_withdrawn"
    SOURCE_RESTRICTED = "source_restricted"
    REFERENCE_UNRESOLVABLE = "reference_unresolvable"
    NO_EXACT_VERSION = "no_exact_version"
    ORIGIN_REF_UNSUPPORTED = "origin_ref_unsupported"
    OBJECT_REF_UNPROVEN = "object_ref_unproven"
    SOURCE_CHANGED = "source_changed"


class BackfillRunState(StrEnum):
    """S3 section 8.3: a dry run is enumerated, then classified. The apply states are later."""

    ENUMERATED = "enumerated"
    CLASSIFIED = "classified"
