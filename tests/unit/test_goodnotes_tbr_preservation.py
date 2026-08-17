"""Lock TBR Staff Meeting regression expectations without a live bridge.

Synthetic strings only. No live SharePoint, OneDrive, Teams, email, or Task.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from my_pa.application import goodnotes as goodnotes_application
from my_pa.application import goodnotes_corrections, goodnotes_delivery
from my_pa.bootstrap import goodnotes as goodnotes_bootstrap
from my_pa.bootstrap import goodnotes_tbr as tbr
from my_pa.bootstrap.goodnotes_tbr import (
    AMBIGUITY_DISPOSITION,
    ARCHIVE_TBR_ONLY,
    CONTRACT_STATUS,
    CORRECTIONS_SUPERVISED,
    EMAIL_ENABLED,
    EXCLUDED_INK,
    INCLUDED_INK,
    LIVE_BRIDGE_IMPLEMENTED,
    LIVE_TASK_MUTATION,
    ONEDRIVE_MEETING_NOTES,
    OPTIONAL_BRIDGE_AUTHORIZED,
    PART_A_KIND,
    PART_B_KIND,
    STAFF_MEETING_INPUTS,
    TEAMS_ENABLED,
    contract_document,
    leader_line_disposition,
    stroke_disposition,
)

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT = ROOT / "ops" / "goodnotes" / "tbr-staff-meeting-regression.json"
RUNBOOK = ROOT / "ops" / "runbooks" / "goodnotes-tbr-preservation.md"

GENERAL_GOODNOTES = (
    ROOT / "src" / "my_pa" / "application" / "goodnotes.py",
    ROOT / "src" / "my_pa" / "application" / "goodnotes_occurrences.py",
    ROOT / "src" / "my_pa" / "application" / "goodnotes_delivery.py",
    ROOT / "src" / "my_pa" / "application" / "goodnotes_corrections.py",
    ROOT / "src" / "my_pa" / "bootstrap" / "goodnotes.py",
)

TBR_ONLY_MARKERS = (
    "TBR",
    "SharePoint",
    "/Meetings/Meeting Notes",
    "leader_line",
    "preparatory",
    "part_a",
    "review_docx",
)


def test_status_is_external_task_gate_pending() -> None:
    assert CONTRACT_STATUS == "GN-09_EXTERNAL_TASK_GATE_PENDING"
    assert LIVE_TASK_MUTATION is False
    assert LIVE_BRIDGE_IMPLEMENTED is False
    assert OPTIONAL_BRIDGE_AUTHORIZED is False
    document = contract_document()
    assert document["status"] == CONTRACT_STATUS
    assert document["live_task_mutation"] is False
    assert document["live_bridge_implemented"] is False
    existing = document["existing_tbr_task"]
    assert isinstance(existing, dict)
    assert existing["must_not_change"] is True
    assert existing["separate_task_change_authorization"] is False
    bridge = document["optional_bridge"]
    assert isinstance(bridge, dict)
    assert bridge["authorized"] is False
    assert bridge["implemented"] is False
    assert bridge["near_term_default"] == "do_not_change_existing_tbr_task"
    assert bridge["wp_15_activation"] is False


def test_frozen_json_matches_the_python_contract() -> None:
    artifact = json.loads(ARTIFACT.read_text(encoding="utf-8"))
    assert artifact == contract_document()


def test_staff_meeting_inputs_are_sharepoint_and_manual() -> None:
    assert frozenset({"sharepoint", "manual"}) == STAFF_MEETING_INPUTS
    inputs = contract_document()["inputs"]
    assert isinstance(inputs, dict)
    assert inputs["staff_meeting"] == ["manual", "sharepoint"]


def test_red_and_black_handwriting_are_included() -> None:
    assert frozenset({"red", "black"}) == INCLUDED_INK
    assert stroke_disposition("synthetic red handwriting") == "include"
    assert stroke_disposition("synthetic black staff-meeting handwriting") == "include"


def test_blue_preparatory_notes_are_excluded() -> None:
    assert frozenset({"blue"}) == EXCLUDED_INK
    assert tbr.BLUE_PREPARATORY is True
    assert stroke_disposition("synthetic blue preparatory note") == "exclude"
    ink = contract_document()["ink"]
    assert isinstance(ink, dict)
    assert ink["blue_is_preparatory"] is True
    assert ink["excluded"] == ["blue"]


def test_leader_lines_follow_unambiguous_included_ink_else_review() -> None:
    assert leader_line_disposition(ink_color="red", unambiguous=True) == "include"
    assert leader_line_disposition(ink_color="black", unambiguous=True) == "include"
    assert leader_line_disposition(ink_color="red", unambiguous=False) == "human_review"
    assert leader_line_disposition(ink_color="blue", unambiguous=True) == "exclude"
    ink = contract_document()["ink"]
    assert isinstance(ink, dict)
    assert ink["leader_lines"] == "unambiguous_included_ink_follows_target_else_human_review"


def test_ambiguity_goes_to_human_review() -> None:
    assert AMBIGUITY_DISPOSITION == "human_review"
    assert stroke_disposition("synthetic ambiguous red handwriting") == "human_review"
    assert stroke_disposition("synthetic unlabeled stroke") == "human_review"
    ink = contract_document()["ink"]
    assert isinstance(ink, dict)
    assert ink["ambiguity"] == "human_review"


def test_part_a_is_paste_ready_and_part_b_is_review_docx() -> None:
    assert PART_A_KIND == "paste_ready"
    assert PART_B_KIND == "review_docx"
    outputs = contract_document()["outputs"]
    assert isinstance(outputs, dict)
    assert outputs["part_a"] == "paste_ready"
    assert outputs["part_b"] == "review_docx"


def test_onedrive_meeting_notes_is_the_named_destination() -> None:
    assert ONEDRIVE_MEETING_NOTES == "/Meetings/Meeting Notes"
    destinations = contract_document()["destinations"]
    assert isinstance(destinations, dict)
    assert destinations["onedrive_meeting_notes"] == "/Meetings/Meeting Notes"


def test_teams_and_email_remain_disabled() -> None:
    assert TEAMS_ENABLED is False
    assert EMAIL_ENABLED is False
    destinations = contract_document()["destinations"]
    assert isinstance(destinations, dict)
    assert destinations["teams_enabled"] is False
    assert destinations["email_enabled"] is False
    assert destinations["teams_email_require_separate_authorization"] is True


def test_tbr_sharepoint_archive_remains_tbr_only() -> None:
    assert ARCHIVE_TBR_ONLY is True
    archive = contract_document()["archive"]
    assert isinstance(archive, dict)
    assert archive["tbr_sharepoint_archive_tbr_only"] is True
    separation = contract_document()["separation"]
    assert isinstance(separation, dict)
    assert separation["general_goodnotes_must_not_merge_sharepoint_archival"] is True


def test_corrections_remain_supervised_input() -> None:
    assert CORRECTIONS_SUPERVISED is True
    corrections = contract_document()["corrections"]
    assert isinstance(corrections, dict)
    assert corrections["supervised_input_only"] is True
    source = inspect.getsource(goodnotes_corrections)
    assert "operator-correction" in source
    assert "teams" not in source.casefold()
    assert "sharepoint" not in source.casefold()


def test_general_goodnotes_does_not_absorb_tbr_rules() -> None:
    combined = "\n".join(path.read_text(encoding="utf-8") for path in GENERAL_GOODNOTES)
    for marker in TBR_ONLY_MARKERS:
        assert marker not in combined, f"general GoodNotes absorbed TBR marker {marker!r}"
    delivery = inspect.getsource(goodnotes_delivery)
    assert "Does not send to Teams, email, or" in delivery
    assert "operator-local" in delivery
    bootstrap = inspect.getsource(goodnotes_bootstrap)
    application = inspect.getsource(goodnotes_application)
    assert "goodnotes_tbr" not in bootstrap
    assert "goodnotes_tbr" not in application
    assert "/Meetings/Meeting Notes" not in delivery
    separation = contract_document()["separation"]
    assert isinstance(separation, dict)
    assert separation["general_goodnotes_must_not_merge_tbr_ink_rules"] is True
    assert separation["general_goodnotes_must_not_merge_teams_email"] is True


def test_contract_module_does_not_write_live_destinations() -> None:
    source = inspect.getsource(tbr)
    assert "urllib" not in source
    assert "httpx" not in source
    assert "requests" not in source
    assert "graph.microsoft" not in source
    assert "Capability" not in source
    assert "alembic" not in source.casefold()


def test_operator_runbook_forbids_live_task_change() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "GN-09_EXTERNAL_TASK_GATE_PENDING" in text
    assert "Do not change it under" in text
    assert "live_task_mutation" in text
    assert "must not merge" in text or "must not absorb" in text
    assert "optional bridge" in text.casefold()
    assert "not authorized" in text.casefold()
    assert "WP-15" in text
    assert "synthetic red handwriting" in text
