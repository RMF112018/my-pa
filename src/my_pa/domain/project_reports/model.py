"""Closed vocabularies of the project-reports domain (WP3P design section 3.3).

Every value set here is closed: a later slice mirrors each one as a frozen
literal in its migration, so a new member is a reviewed change in two places.
None of these names carries the export source's or its provider's name, and
none is a capability, purpose, identifier kind or table name.
"""

from __future__ import annotations

from enum import StrEnum
from types import MappingProxyType
from typing import Final

__all__ = [
    "FAMILY_OF_VIEW",
    "IDENTITY_VERSION",
    "UNCLASSIFIED_COUNT_KEY",
    "Additivity",
    "BindingReason",
    "BindingRefusal",
    "BindingState",
    "CompletenessClass",
    "DerivationState",
    "DerivationTrigger",
    "FamilyView",
    "FilterSemantics",
    "IdentityBasis",
    "IdentityState",
    "LineKind",
    "NotReportableReason",
    "ObservationState",
    "QuarantineReason",
    "ReconciliationOutcome",
    "RecordFamily",
    "RejectionCode",
    "ReportQualifier",
    "RowReason",
    "RowRole",
    "StatusClass",
    "TotalScope",
    "ValueKind",
    "VersionPresence",
]


class RowRole(StrEnum):
    """The one role of every data row; only `DETAIL` contributes to a measure."""

    DETAIL = "detail"
    GROUP_HEADER = "group_header"
    GRAND_TOTAL = "grand_total"
    SPACER = "spacer"
    GROUPING_ONLY = "grouping_only"
    MALFORMED = "malformed"


#: The role-count key of a quarantined derivation; never a stored row role.
UNCLASSIFIED_COUNT_KEY: Final = "unclassified"


class RecordFamily(StrEnum):
    MEETING_ITEMS = "meeting_items"
    OBSERVATIONS = "observations"
    COORDINATION_ISSUES = "coordination_issues"
    RFIS = "rfis"
    BUDGET_CHANGES = "budget_changes"
    BUYOUT = "buyout"
    CHANGE_ORDER_RECONCILIATION = "change_order_reconciliation"
    DAILY_LOG = "daily_log"


class FamilyView(StrEnum):
    """One view per registered header signature (15)."""

    OAC = "oac"
    WITH_DATE_CLOSED = "with_date_closed"
    OPEN_BY_VENDOR = "open_by_vendor"
    BY_STATUS = "by_status"
    LINKED_TO_DRAWINGS = "linked_to_drawings"
    OPEN_OUTSTANDING = "open_outstanding"
    RECENTLY_CLOSED = "recently_closed"
    GROUPED_BY_CHANGE = "grouped_by_change"
    BY_CODE = "by_code"
    BUYOUT_SUMMARY = "buyout_summary"
    RECONCILIATION = "reconciliation"
    DELAYS = "delays"
    MANPOWER = "manpower"
    NOTES = "notes"
    WEATHER = "weather"


#: Each view belongs to exactly one family.
FAMILY_OF_VIEW: Final = MappingProxyType(
    {
        FamilyView.OAC: RecordFamily.MEETING_ITEMS,
        FamilyView.WITH_DATE_CLOSED: RecordFamily.OBSERVATIONS,
        FamilyView.OPEN_BY_VENDOR: RecordFamily.OBSERVATIONS,
        FamilyView.BY_STATUS: RecordFamily.COORDINATION_ISSUES,
        FamilyView.LINKED_TO_DRAWINGS: RecordFamily.RFIS,
        FamilyView.OPEN_OUTSTANDING: RecordFamily.RFIS,
        FamilyView.RECENTLY_CLOSED: RecordFamily.RFIS,
        FamilyView.GROUPED_BY_CHANGE: RecordFamily.BUDGET_CHANGES,
        FamilyView.BY_CODE: RecordFamily.BUDGET_CHANGES,
        FamilyView.BUYOUT_SUMMARY: RecordFamily.BUYOUT,
        FamilyView.RECONCILIATION: RecordFamily.CHANGE_ORDER_RECONCILIATION,
        FamilyView.DELAYS: RecordFamily.DAILY_LOG,
        FamilyView.MANPOWER: RecordFamily.DAILY_LOG,
        FamilyView.NOTES: RecordFamily.DAILY_LOG,
        FamilyView.WEATHER: RecordFamily.DAILY_LOG,
    }
)


class CompletenessClass(StrEnum):
    POPULATED = "populated"
    VALID_EMPTY = "valid_empty"
    GROUPING_ONLY = "grouping_only"


class FilterSemantics(StrEnum):
    UNKNOWN = "unknown"
    OPERATOR_DECLARED = "operator_declared"


class StatusClass(StrEnum):
    APPROVED = "approved"
    PENDING = "pending"
    VOID = "void"
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class Additivity(StrEnum):
    ADDITIVE = "additive"
    NON_ADDITIVE = "non_additive"
    UNKNOWN = "unknown"


class ReconciliationOutcome(StrEnum):
    MATCH = "match"
    MISMATCH = "mismatch"
    BOTH_EMPTY = "both_empty"
    NOT_CHECKED = "not_checked"


class TotalScope(StrEnum):
    GROUP = "group"
    GRAND = "grand"


class IdentityBasis(StrEnum):
    EXPORTED_NUMBER = "exported_number"
    EXPORTED_NUMBER_NORMALIZED = "exported_number_normalized"
    EXPORTED_COMPOSITE = "exported_composite"


class IdentityState(StrEnum):
    IDENTIFIED = "identified"
    IDENTITY_MISSING = "identity_missing"
    AMBIGUOUS_IDENTITY = "ambiguous_identity"
    SNAPSHOT_SCOPED = "snapshot_scoped"


#: The version of the per-family identity rules in `identity.py`.
IDENTITY_VERSION: Final = "project_report_identity_v1"


class DerivationState(StrEnum):
    CLASSIFIED = "classified"
    QUARANTINED = "quarantined"


class DerivationTrigger(StrEnum):
    INGEST = "ingest"
    REDERIVE_ADAPTER = "rederive_adapter"
    REDERIVE_BINDING = "rederive_binding"
    REDERIVE_VERSION = "rederive_version"
    OPERATOR_REBUILD = "operator_rebuild"


class LineKind(StrEnum):
    ITEM = "item"
    OBSERVATION = "observation"
    ISSUE = "issue"
    RFI_ROW = "rfi_row"
    RFI_DRAWING_LINK = "rfi_drawing_link"
    BUDGET_CHANGE_LINE = "budget_change_line"
    BUDGET_LINE = "budget_line"
    BUDGET_CHANGE = "budget_change"
    PRIME_CHANGE_ORDER = "prime_change_order"
    COMMITMENT = "commitment"
    COMMITMENT_CHANGE_ORDER = "commitment_change_order"
    VENDOR_ONLY = "vendor_only"
    PRIME_PCO_LINE = "prime_pco_line"
    COMMITMENT_CO_LINE = "commitment_co_line"
    MANPOWER = "manpower"
    WEATHER = "weather"
    DELAY = "delay"
    NOTE = "note"


class ObservationState(StrEnum):
    TYPED = "typed"
    DEGRADED = "degraded"


class ValueKind(StrEnum):
    MONEY = "money"
    NUMBER = "number"
    DATE = "date"
    BOOLEAN = "boolean"
    TEXT = "text"
    IDENTIFIER = "identifier"


class RejectionCode(StrEnum):
    """Snapshot rejection: the whole file is refused (the lifecycle `rejection_code`)."""

    NOT_UTF8 = "not_utf8"
    MALFORMED_CSV = "malformed_csv"
    INVALID_HEADER = "invalid_header"
    NUL_BYTE = "nul_byte"


class QuarantineReason(StrEnum):
    """Derivation quarantine: every raw row is kept, none is classified."""

    UNKNOWN_HEADER_SIGNATURE = "unknown_header_signature"
    MALFORMED_RATIO_EXCEEDED = "malformed_ratio_exceeded"
    BINDING_PROJECT_NUMBER_MISMATCH = "binding_project_number_mismatch"


class RowReason(StrEnum):
    WIDTH_MISMATCH = "width_mismatch"
    TYPE_ERROR = "type_error"
    IDENTITY_MISSING = "identity_missing"
    AMBIGUOUS_IDENTITY = "ambiguous_identity"
    AMBIGUOUS_COMMITMENT_CO = "ambiguous_commitment_co"
    MORE_THAN_4_DECIMALS = "more_than_4_decimals"


class BindingRefusal(StrEnum):
    """Why a bindings file is refused as a whole (nothing is written)."""

    FILE_UNREADABLE = "file_unreadable"
    SCHEMA_INVALID = "schema_invalid"
    UNKNOWN_KEY = "unknown_key"
    DUPLICATE_JSON_KEY = "duplicate_json_key"
    PROJECT_NOT_FOUND = "project_not_found"
    PROJECT_NUMBER_MISMATCH = "project_number_mismatch"
    PROJECT_HAS_NO_NUMBER = "project_has_no_number"
    FOLDER_DUPLICATED = "folder_duplicated"
    #: One binding folder inside another, in either direction (Manager ruling on S1).
    FOLDER_NESTED = "folder_nested"
    PROJECT_DUPLICATED = "project_duplicated"
    FOLDER_OUTSIDE_EXPORT_ROOT = "folder_outside_export_root"
    FOLDER_NOT_FOUND = "folder_not_found"
    CURRENCY_INVALID = "currency_invalid"
    FILTER_DESCRIPTION_INVALID = "filter_description_invalid"
    LOCK_HELD = "lock_held"


class BindingState(StrEnum):
    """A folder's binding to a Project: in force, or retired (rows kept, source disabled)."""

    ACTIVE = "active"
    RETIRED = "retired"


class BindingReason(StrEnum):
    INITIAL = "initial"
    CORRECTION = "correction"
    ADD = "add"
    RETIRE = "retire"
    FILTER_UPDATE = "filter_update"


class NotReportableReason(StrEnum):
    """Why a measure has no value (the OD-08 vocabulary; no zero is substituted)."""

    RECONCILIATION_MISMATCH = "reconciliation_mismatch"
    SOURCE_COLUMN_UNPOPULATED = "source_column_unpopulated"
    STATUS_UNKNOWN_PRESENT = "status_unknown_present"
    SNAPSHOT_QUARANTINED = "snapshot_quarantined"
    BINDING_PROJECT_NUMBER_MISMATCH = "binding_project_number_mismatch"
    NO_SNAPSHOT = "no_snapshot"
    #: WP3P-S1 addition (for a ruling): a detail cell of the measured column
    #: failed its type, so the sum would silently omit it.
    TYPE_ERROR_PRESENT = "type_error_present"
    #: Answer-only (WP4P-R1 ruling R1-09): the two sides of a compare delta are
    #: in different currencies, so no delta is given.
    CURRENCY_MIXED = "currency_mixed"


class ReportQualifier(StrEnum):
    """Attached to an answer, never a refusal."""

    FILTER_SEMANTICS_UNKNOWN = "filter_semantics_unknown"
    #: On a record or row count of a derivation whose stated totals mismatched
    #: (WP4P ruling A2): a mismatch concerns reconciled amounts, not counts, so
    #: the count is answered and qualified, never withheld.
    RECONCILIATION_MISMATCH = "reconciliation_mismatch"


class VersionPresence(StrEnum):
    """Whether a record is in the latest version of its series. Never "closed"."""

    OBSERVED_IN_LATEST = "observed_in_latest"
    NOT_OBSERVED_IN_LATEST = "not_observed_in_latest"
    #: The series' latest version is quarantined (WP4P-R1 ruling R1-01): it has
    #: no lines, so whether the record is in it is unknown and nothing is inferred.
    LATEST_UNREADABLE = "latest_unreadable"
