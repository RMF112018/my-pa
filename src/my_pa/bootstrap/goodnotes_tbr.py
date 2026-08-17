"""Dormant TBR Staff Meeting regression contract (GN-09 / WP-13).

Repository-side freeze of the existing TBR Task's Staff Meeting expectations
and of an optional later bridge. There is no TBR runtime in this repository.
This module does not create, edit, enable, or disable a live Task, does not
implement a live bridge, and does not write SharePoint, OneDrive, Teams, or
email.

Near-term default: do not change the existing TBR Task. General GoodNotes
reconciliation must not absorb TBR red/black/blue ink rules, TBR SharePoint
archival, or Teams/email. After this design is encoded, status is
`GN-09_EXTERNAL_TASK_GATE_PENDING`; Task-change authorization is not granted.
"""

from __future__ import annotations

from typing import Final, Literal

__all__ = [
    "AMBIGUITY_DISPOSITION",
    "ARCHIVE_TBR_ONLY",
    "BLUE_PREPARATORY",
    "CONTRACT_STATUS",
    "CORRECTIONS_SUPERVISED",
    "EMAIL_ENABLED",
    "EXCLUDED_INK",
    "INCLUDED_INK",
    "LIVE_BRIDGE_IMPLEMENTED",
    "LIVE_TASK_MUTATION",
    "ONEDRIVE_MEETING_NOTES",
    "OPTIONAL_BRIDGE_AUTHORIZED",
    "PART_A_KIND",
    "PART_B_KIND",
    "STAFF_MEETING_INPUTS",
    "TEAMS_ENABLED",
    "WORK_ITEM",
    "contract_document",
    "leader_line_disposition",
    "stroke_disposition",
]

WORK_ITEM: Final = "GN-09"
CAMPAIGN_PACKAGE: Final = "WP-13"
CONTRACT_STATUS: Final = "GN-09_EXTERNAL_TASK_GATE_PENDING"
LIVE_TASK_MUTATION: Final = False
LIVE_BRIDGE_IMPLEMENTED: Final = False
OPTIONAL_BRIDGE_AUTHORIZED: Final = False
EXISTING_TBR_TASK_MUST_NOT_CHANGE: Final = True

STAFF_MEETING_INPUTS: Final[frozenset[str]] = frozenset({"sharepoint", "manual"})
INCLUDED_INK: Final[frozenset[str]] = frozenset({"red", "black"})
EXCLUDED_INK: Final[frozenset[str]] = frozenset({"blue"})
BLUE_PREPARATORY: Final = True
AMBIGUITY_DISPOSITION: Final = "human_review"
PART_A_KIND: Final = "paste_ready"
PART_B_KIND: Final = "review_docx"
ONEDRIVE_MEETING_NOTES: Final = "/Meetings/Meeting Notes"
TEAMS_ENABLED: Final = False
EMAIL_ENABLED: Final = False
ARCHIVE_TBR_ONLY: Final = True
CORRECTIONS_SUPERVISED: Final = True

Disposition = Literal["include", "exclude", "human_review"]

_INCLUDE: Final = "include"
_EXCLUDE: Final = "exclude"
_REVIEW: Final = "human_review"


def stroke_disposition(synthetic_label: str) -> Disposition:
    """Classify a synthetic stroke label. Not a live ink detector."""
    lowered = synthetic_label.casefold()
    if "blue" in lowered:
        return _EXCLUDE
    if "ambiguous" in lowered:
        return _REVIEW
    if "red" in lowered or "black" in lowered:
        return _INCLUDE
    return _REVIEW


def leader_line_disposition(*, ink_color: str, unambiguous: bool) -> Disposition:
    """Leader-line handling for a synthetic stroke. Ambiguity goes to review."""
    color = ink_color.casefold()
    if color in EXCLUDED_INK:
        return _EXCLUDE
    if color not in INCLUDED_INK:
        return _REVIEW
    if not unambiguous:
        return _REVIEW
    return _INCLUDE


def contract_document() -> dict[str, object]:
    """Frozen artifact shape. Must match the ops JSON byte-for-byte in tests."""
    return {
        "work_item": WORK_ITEM,
        "campaign_package": CAMPAIGN_PACKAGE,
        "kind": "tbr_staff_meeting_regression_and_optional_bridge_design",
        "status": CONTRACT_STATUS,
        "live_task_mutation": LIVE_TASK_MUTATION,
        "live_bridge_implemented": LIVE_BRIDGE_IMPLEMENTED,
        "existing_tbr_task": {
            "must_not_change": EXISTING_TBR_TASK_MUST_NOT_CHANGE,
            "separate_task_change_authorization": False,
        },
        "inputs": {
            "staff_meeting": sorted(STAFF_MEETING_INPUTS),
        },
        "ink": {
            "included": sorted(INCLUDED_INK),
            "excluded": sorted(EXCLUDED_INK),
            "blue_is_preparatory": BLUE_PREPARATORY,
            "leader_lines": "unambiguous_included_ink_follows_target_else_human_review",
            "ambiguity": AMBIGUITY_DISPOSITION,
        },
        "outputs": {
            "part_a": PART_A_KIND,
            "part_b": PART_B_KIND,
        },
        "destinations": {
            "onedrive_meeting_notes": ONEDRIVE_MEETING_NOTES,
            "teams_enabled": TEAMS_ENABLED,
            "email_enabled": EMAIL_ENABLED,
            "teams_email_require_separate_authorization": True,
        },
        "archive": {
            "tbr_sharepoint_archive_tbr_only": ARCHIVE_TBR_ONLY,
        },
        "corrections": {
            "supervised_input_only": CORRECTIONS_SUPERVISED,
        },
        "separation": {
            "general_goodnotes_must_not_merge_tbr_ink_rules": True,
            "general_goodnotes_must_not_merge_sharepoint_archival": True,
            "general_goodnotes_must_not_merge_teams_email": True,
        },
        "optional_bridge": {
            "authorized": OPTIONAL_BRIDGE_AUTHORIZED,
            "implemented": LIVE_BRIDGE_IMPLEMENTED,
            "near_term_default": "do_not_change_existing_tbr_task",
            "requires_separate_task_change_authorization": True,
            "wp_15_activation": False,
        },
    }
