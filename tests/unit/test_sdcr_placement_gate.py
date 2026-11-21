"""Synthetic denial matrix for optional server-side SDCR path admission.

No network, database, live NAS, identities, or production config.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from my_pa.domain.files.sdcc_placement import PlacementDenied, SDCRPlacementGate
from my_pa.infrastructure.file_workspace.sdcc_placement_config import (
    SDCRConfigurationError,
    load_sdcr_gate,
)

HERE = Path(__file__).resolve().parents[2]
CONFIG = HERE / "docs/architecture/sdcc-placement-config.example.json"
OWNED = "SDCR/20-Programs/shared-platform/workstreams/cross-client-publication/work-items/365"


def gate() -> SDCRPlacementGate:
    sample = json.loads(CONFIG.read_text())
    sample["policy"]["status"] = "APPROVED_FOR_QUALIFICATION"
    return SDCRPlacementGate(sample["policy"], sample["registrations"])


def test_correct_typed_session_artifact_and_parents() -> None:
    g = gate()
    path = OWNED + "/sessions/SESSION-X/artifacts/source/ART-1__source.zip"
    assert g.admit_create(path, is_directory=False) == "SESSION_ARTIFACT"
    g.admit_directory_tree(path.rsplit("/", 1)[0])


@pytest.mark.parametrize(
    "path,is_dir",
    [
        ("SDCR/misc", True),
        ("SDCR/REVIEW_PACKAGE.zip", False),
        ("SDCR/99-Temporary", True),
        ("SDCR/20-Programs/unknown", True),
        ("SDCR/20-Programs/shared-platform/workstreams/anything", True),
        (
            "SDCR/20-Programs/shared-platform/workstreams/"
            "cross-client-publication/work-items/999", True,
        ),
        (OWNED + "/sessions/S1/artifacts/nonsense", True),
        (OWNED + "/sessions/S1/artifacts/evidence/foo.log", False),
        (OWNED + "/sessions/S1/artifacts/evidence/ID__foo.log/extra", False),
        ("SDCR/20-Programs/shared-platform/../oops", True),
        ("SDCR/20-Programs/shared-platform//oops", True),
        ("SDCR/00-Control/FAKE.txt", False),
        (OWNED + "/custom", True),
    ],
)
def test_unregistered_or_wrong_placement_fails(path: str, is_dir: bool) -> None:
    with pytest.raises(PlacementDenied):
        gate().admit_create(path, is_directory=is_dir)


def test_registered_owner_cannot_be_renamed_by_caller() -> None:
    g = gate()
    bad = OWNED.replace("shared-platform", "my-pa")
    with pytest.raises(PlacementDenied):
        g.admit_directory_tree(bad + "/sessions/S")


def test_no_root_arbitrary_files() -> None:
    g = gate()
    assert g.admit_create("SDCR/20-Programs", is_directory=True) == "DIRECTORY"
    with pytest.raises(PlacementDenied):
        g.admit_create("SDCR/file.txt", is_directory=False)


def test_mutation_denies_copy_move_trash_and_restore_under_sdcr() -> None:
    g = gate()
    for target, source in [
        (OWNED + "/sessions/S1", None),
        ("OTHER/folder", OWNED),
        (OWNED, "OTHER/folder"),
    ]:
        with pytest.raises(PlacementDenied, match="SDCR_LIFECYCLE_CHANGE_REQUIRES_MIGRATION"):
            g.admit_transition(target, source=source)
    g.admit_transition("OTHER/foo", source="OTHER/bar")


def test_write_existing_artifact_is_immutable() -> None:
    p = OWNED + "/sessions/S1/artifacts/evidence/EID__test.log"
    with pytest.raises(PlacementDenied, match="SDCR_IMMUTABLE_CONTENT"):
        gate().admit_create(p, is_directory=False, expected_version="fv1_example")
    assert (
        gate().admit_create(
            OWNED + "/00_ARTIFACT_INDEX.json",
            is_directory=False,
            expected_version="fv1_example",
        )
        == "WORK_ITEM_CONTROL"
    )


def test_control_plane_content_rejected_from_raw_client() -> None:
    with pytest.raises(PlacementDenied, match="TRUSTED_CONTROL_REQUIRES_OPERATOR_PROVISIONING"):
        gate().admit_create(
            "SDCR/00-Control/12_DIRECTORY_PLACEMENT_POLICY.json", is_directory=False
        )


def test_existing_unrelated_workspace_can_still_work() -> None:
    g = gate()
    assert g.admit_create("reproof/new-file.md", is_directory=False) == "OUTSIDE_SDCR"
    g.admit_directory_tree("reproof/another")


def test_malformed_or_unapproved_config_refuses() -> None:
    src = json.loads(CONFIG.read_text())
    with pytest.raises(ValueError, match="sdcr_policy_not_approved"):
        SDCRPlacementGate(src["policy"], src["registrations"])
    src["policy"]["status"] = "APPROVED_FOR_QUALIFICATION"
    src["registrations"]["365"]["program"] = "unknown"
    with pytest.raises(ValueError, match="sdcr_registration_unrecognized_owner"):
        SDCRPlacementGate(src["policy"], src["registrations"])


def test_config_must_be_outside_workspace_and_not_mutable(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    parent = tmp_path / "config"
    parent.mkdir(mode=0o700)
    config = parent / "policy.json"
    data = json.loads(CONFIG.read_text())
    data["policy"]["status"] = "APPROVED_FOR_QUALIFICATION"
    config.write_text(json.dumps(data))
    config.chmod(0o600)
    policy = load_sdcr_gate(str(config), str(workspace))
    assert policy.registration_count == 2
    config.chmod(0o666)
    with pytest.raises(SDCRConfigurationError, match="permissions_unsafe"):
        load_sdcr_gate(str(config), str(workspace))
    config.chmod(0o600)
    internal = workspace / "policy.json"
    internal.write_text(json.dumps(data))
    with pytest.raises(SDCRConfigurationError, match="outside_workspace"):
        load_sdcr_gate(str(internal), str(workspace))
    config.unlink()
    config.symlink_to(internal)
    with pytest.raises(SDCRConfigurationError, match="outside_workspace"):
        load_sdcr_gate(str(config), str(workspace))


def test_nonconfig_cannot_enable_guard(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(SDCRConfigurationError):
        load_sdcr_gate(str(tmp_path / "missing"), str(workspace))
