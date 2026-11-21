#!/usr/bin/env python3
"""Closed-world SDCR file placement; pure, versioned, no I/O.

Active only when gateway composition loads an independently managed approved
configuration. A caller cannot supply or modify the trusted owner registry.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Any

IDENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
ARTIFACT = re.compile(r"([A-Za-z0-9][A-Za-z0-9._-]{0,127})__([A-Za-z0-9][A-Za-z0-9._-]{0,180})\Z")
YEAR = re.compile(r"20[0-9]{2}\Z")
MONTH = re.compile(r"(?:0[1-9]|1[012])\Z")
SAFE_RESERVED = frozenset({".my-pa", "#recycle", "#snapshot", "@eadir"})
REPORT_FILES = frozenset(
    {
        "INDEPENDENT_REVIEW_REPORT.md",
        "SYNTHETIC_PROOF_AND_CI_LEDGER.md",
        "EVIDENCE_MANIFEST.json",
        "REVIEW_RECEIPT.json",
    }
)
SESSION_FILES = frozenset(
    {
        "SESSION_MANIFEST.json",
        "SESSION_PUBLICATION_RECEIPT.json",
        "SESSION_RECOVERY.json",
        "SESSION_PUBLICATION_FAILURE.json",
        "HANDOFF.md",
    }
)
WORK_FILES = frozenset({"WORK_ITEM.md", "00_ARTIFACT_INDEX.json", "OWNERSHIP.json"})
ROOT_INDEX_FILES = {
    "30-Exchange": "00_ACTIVE_WORK_INDEX.md",
    "40-Publication": "00_SESSION_REGISTRY_INDEX.md",
    "50-Shared-Evidence": "00_INDEX.md",
    "60-Cross-Program-Decisions": "00_INDEX.md",
    "70-Client-Adapters": "00_INDEX.md",
    "80-Templates": "00_INDEX.md",
    "90-Migration": "00_MIGRATION_INDEX.md",
    "99-Legacy-Archive": "00_INDEX.md",
    "10-Governance": "00_GOVERNANCE_INDEX.md",
}


class PlacementDeniedError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _deny(code: str) -> None:
    raise PlacementDeniedError(code)


def _ident(segment: str) -> bool:
    return bool(IDENT.fullmatch(segment)) and segment not in (".", "..")


def _file_name(segment: str) -> bool:
    return bool(ARTIFACT.fullmatch(segment)) and len(segment.encode("utf-8")) <= 255


def _parts(raw: str) -> list[str]:
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > 4096:
        _deny("INVALID_PATH")
    if raw != "SDCR" and not raw.startswith("SDCR/"):
        _deny("OUTSIDE_SDCR_ROOT")
    if "\\" in raw or any(ord(c) < 32 or ord(c) == 127 for c in raw):
        _deny("INVALID_PATH")
    parts = raw.split("/")
    if any(
        not p or p in (".", "..") or p.lower() in SAFE_RESERVED or len(p.encode("utf-8")) > 255
        for p in parts
    ):
        _deny("INVALID_PATH")
    if PurePosixPath(raw).as_posix() != raw:
        _deny("INVALID_PATH")
    return parts


def _yearmonth(p: list[str]) -> bool:
    return len(p) >= 2 and bool(YEAR.fullmatch(p[0])) and bool(MONTH.fullmatch(p[1]))


def _program(
    parts: list[str],
    policy: Mapping[str, Any],
    registrations: Mapping[str, Mapping[str, str]],
    is_dir: bool,
    role: str | None,
) -> str:
    p = parts
    if not p:
        return "DIRECTORY" if is_dir else _deny("NO_ROOT_FILES")
    program = p[0]
    if program not in policy["program_workstreams"]:
        _deny("UNREGISTERED_PROGRAM")
    if len(p) == 1:
        return "PROGRAM_DIRECTORY" if is_dir else _deny("MISPLACED_FILE")
    if p[1] == "00_PROGRAM_INDEX.md" and len(p) == 2 and not is_dir:
        return "PROGRAM_INDEX"
    if p[1] != "workstreams":
        _deny("UNKNOWN_PROGRAM_SUBTREE")
    if len(p) == 2:
        return "DIRECTORY" if is_dir else _deny("MISPLACED_FILE")
    stream = p[2]
    if stream not in policy["program_workstreams"][program]:
        _deny("UNREGISTERED_WORKSTREAM")
    if len(p) == 3:
        return "WORKSTREAM_DIRECTORY" if is_dir else _deny("MISPLACED_FILE")
    if len(p) == 4 and p[3] == "00_WORKSTREAM_INDEX.md" and not is_dir:
        return "WORKSTREAM_INDEX"
    if p[3] != "work-items":
        _deny("UNKNOWN_WORKSTREAM_SUBTREE")
    if len(p) == 4:
        return "DIRECTORY" if is_dir else _deny("MISPLACED_FILE")
    item_id = p[4]
    if not _ident(item_id):
        _deny("INVALID_WORK_ITEM_ID")
    owner = registrations.get(item_id)
    if owner is None or owner.get("program") != program or owner.get("workstream") != stream:
        _deny("WORK_ITEM_NOT_REGISTERED_TO_THIS_OWNER")
    if len(p) == 5:
        return "WORK_ITEM_DIRECTORY" if is_dir else _deny("MISPLACED_FILE")
    rest = p[5:]
    if len(rest) == 1 and rest[0] in WORK_FILES and not is_dir:
        return "WORK_ITEM_CONTROL"
    group = rest[0]
    if group not in {
        "reference-inputs",
        "canonical",
        "sessions",
        "reviews",
        "coordination",
        "follow-ups",
    }:
        _deny("UNKNOWN_WORK_ITEM_SUBTREE")
    if len(rest) == 1:
        return "DIRECTORY" if is_dir else _deny("MISPLACED_FILE")
    if group == "reference-inputs":
        if len(rest) == 2 and not is_dir and _file_name(rest[1]) and role == "input":
            return "REFERENCE_INPUT"
        _deny("BAD_REFERENCE_INPUT_PLACEMENT")
    if group == "canonical":
        if (
            len(rest) == 2
            and not is_dir
            and _ident(rest[1][:-5])
            and rest[1].endswith(".json")
            and role == "canonical_pointer"
        ):
            return "CANONICAL_POINTER"
        _deny("CANONICAL_MUST_BE_POINTER")
    if group == "follow-ups":
        if len(rest) == 2 and not is_dir and rest[1].endswith(".json") and _ident(rest[1][:-5]):
            return "FOLLOW_UP"
        _deny("BAD_FOLLOW_UP_PLACEMENT")
    key = rest[1]
    if not _ident(key):
        _deny("INVALID_SESSION_OR_REVIEW_ID")
    if len(rest) == 2:
        return "CONTROLLED_ID_DIRECTORY" if is_dir else _deny("MISPLACED_FILE")
    tail = rest[2:]
    if group == "sessions":
        if len(tail) == 1 and tail[0] in SESSION_FILES and not is_dir:
            return "SESSION_CONTROL"
        if tail == ["artifacts"] and is_dir:
            return "ARTIFACT_ROOT"
        if len(tail) >= 2 and tail[0] == "artifacts":
            category = tail[1]
            if category not in policy["session_artifact_categories"]:
                _deny("INVALID_ARTIFACT_CATEGORY")
            if len(tail) == 2 and is_dir:
                return "ARTIFACT_CATEGORY_DIRECTORY"
            if len(tail) == 3 and not is_dir and _file_name(tail[2]) and category == role:
                return (
                    "SESSION_ARTIFACT"
                    if category != "unclassified"
                    else "STAGED_UNCLASSIFIED_NOT_READY"
                )
        _deny("INVALID_SESSION_LAYOUT")
    if group == "reviews":
        if len(tail) == 1 and not is_dir and tail[0] in REPORT_FILES:
            return "REVIEW_RECORD"
        if tail == ["artifacts"] and is_dir:
            return "REVIEW_ARTIFACT_ROOT"
        if (
            len(tail) == 2
            and tail[0] == "artifacts"
            and not is_dir
            and _file_name(tail[1])
            and role == "review"
        ):
            return "REVIEW_EVIDENCE"
        _deny("INVALID_REVIEW_LAYOUT")
    if group == "coordination":
        names = {
            f"COORDINATION-REQUEST-{key}.md",
            f"COORDINATION-RESPONSE-{key}.md",
            "DISPATCH_PUBLICATION_RECEIPT.json",
            f"COORDINATION-ROUNDTRIP-RECEIPT-{key}.json",
        }
        if len(tail) == 1 and not is_dir and tail[0] in names:
            return "COORDINATION_RECORD"
        _deny("INVALID_COORDINATION_LAYOUT")
    _deny("INVALID_ITEM_LAYOUT")


def _other_top(
    name: str,
    p: list[str],
    policy: Mapping[str, Any],
    is_dir: bool,
    role: str | None,
) -> str:
    if not p:
        return "ROOT_COLLECTION" if is_dir else _deny("ROOT_FILE_FORBIDDEN")
    if len(p) == 1 and not is_dir and p[0] == ROOT_INDEX_FILES.get(name):
        return "ROOT_INDEX"
    if name == "00-Control":
        if len(p) == 1 and not is_dir and p[0] in policy["control_files"]:
            return "CONTROL_FILE"
        _deny("UNKNOWN_CONTROL_FILE")
    if name == "10-Governance":
        if p[0] not in policy["governance_collections"]:
            _deny("UNKNOWN_GOVERNANCE_COLLECTION")
        if len(p) == 1 and is_dir:
            return "GOVERNANCE_COLLECTION"
        if len(p) == 2 and not is_dir and _file_name(p[1]) and role == "governance":
            return "GOVERNANCE_FILE"
        _deny("UNKNOWN_GOVERNANCE_PATH")
    if name in ("30-Exchange", "50-Shared-Evidence", "60-Cross-Program-Decisions"):
        lookup = {
            "30-Exchange": "client-notices",
            "50-Shared-Evidence": "pointers",
            "60-Cross-Program-Decisions": "pointers",
        }
        child = lookup[name]
        if p[0] != child:
            _deny("UNREGISTERED_COLLECTION_CHILD")
        if len(p) == 1 and is_dir:
            return "CONTROLLED_COLLECTION"
        if name == "30-Exchange":
            if len(p) == 2 and is_dir and p[1] in policy["client_adapter_ids"]:
                return "CLIENT_QUEUE"
            if (
                len(p) == 3
                and not is_dir
                and p[1] in policy["client_adapter_ids"]
                and p[2].endswith(".json")
                and _ident(p[2][:-5])
                and role == "locator"
            ):
                return "CLIENT_POINTER"
        elif (
            len(p) == 2
            and not is_dir
            and p[1].endswith(".json")
            and _ident(p[1][:-5])
            and role == "locator"
        ):
            return "CANONICAL_OWNER_POINTER"
        _deny("INVALID_POINTER_LAYOUT")
    if name == "40-Publication":
        group = p[0]
        if group not in ("sessions", "events", "registry-snapshots", "exceptions"):
            _deny("INVALID_PUBLICATION_GROUP")
        if len(p) == 1 and is_dir:
            return "PUBLICATION_GROUP"
        if group in ("sessions", "events"):
            if len(p) == 2 and is_dir and YEAR.fullmatch(p[1]):
                return "PUBLICATION_YEAR"
            if len(p) == 3 and is_dir and _yearmonth(p[1:]):
                return "PUBLICATION_MONTH"
            if (
                len(p) == 4
                and not is_dir
                and _yearmonth(p[1:3])
                and p[3].endswith(".json")
                and _ident(p[3][:-5])
                and role == "locator"
            ):
                return "PUBLICATION_POINTER"
        elif (
            len(p) == 2
            and not is_dir
            and p[1].endswith(".json")
            and _ident(p[1][:-5])
            and role == "locator"
        ):
            return "PUBLICATION_META"
        _deny("INVALID_PUBLICATION_PATH")
    if name == "70-Client-Adapters":
        if p[0] not in policy["client_adapter_ids"]:
            _deny("INVALID_CLIENT_ADAPTER")
        if len(p) == 1 and is_dir:
            return "CLIENT_ADAPTER_DIRECTORY"
        if len(p) == 2 and not is_dir and p[1] in ("ADAPTER.md", "CAPABILITIES.json"):
            return "CLIENT_ADAPTER_CONTROL"
        _deny("INVALID_CLIENT_ADAPTER_PATH")
    if name == "80-Templates":
        if p[0] not in policy["template_collections"]:
            _deny("INVALID_TEMPLATE_COLLECTION")
        if len(p) == 1 and is_dir:
            return "TEMPLATE_COLLECTION"
        if len(p) == 2 and not is_dir and _file_name(p[1]) and role == "template":
            return "TEMPLATE"
        _deny("INVALID_TEMPLATE_PATH")
    if name == "90-Migration":
        if p[0] not in policy["migration_collections"]:
            _deny("INVALID_MIGRATION_COLLECTION")
        if len(p) == 1 and is_dir:
            return "MIGRATION_COLLECTION"
        if len(p) == 2 and is_dir and _ident(p[1]):
            return "MIGRATION_BATCH"
        if (
            len(p) == 3
            and not is_dir
            and _ident(p[1])
            and p[2] in ("BATCH_MANIFEST.json", "BATCH_RECEIPT.json", "HANDOFF.md")
        ):
            return "MIGRATION_BATCH_CONTROL"
        if len(p) == 3 and is_dir and _ident(p[1]) and p[2] == "artifacts":
            return "MIGRATION_ARTIFACT_DIRECTORY"
        if (
            len(p) == 4
            and not is_dir
            and _ident(p[1])
            and p[2] == "artifacts"
            and _file_name(p[3])
            and role == "migration"
        ):
            return "MIGRATION_ARTIFACT"
        _deny("INVALID_MIGRATION_LAYOUT")
    if name == "99-Legacy-Archive":
        if p[0] != "imports":
            _deny("INVALID_LEGACY_LOCATION")
        if len(p) == 1 and is_dir:
            return "LEGACY_IMPORTS"
        if len(p) == 2 and is_dir and _ident(p[1]):
            return "LEGACY_BATCH"
        if len(p) == 3 and not is_dir and _ident(p[1]) and p[2] == "IMPORT_MANIFEST.json":
            return "LEGACY_MANIFEST"
        if len(p) == 3 and is_dir and _ident(p[1]) and p[2] == "artifacts":
            return "LEGACY_ARTIFACTS"
        if (
            len(p) == 4
            and not is_dir
            and _ident(p[1])
            and p[2] == "artifacts"
            and _file_name(p[3])
            and role == "legacy"
        ):
            return "LEGACY_FILE"
        _deny("INVALID_LEGACY_LAYOUT")
    _deny("UNKNOWN_ROOT_CATEGORY")


def authorize_path(
    policy: Mapping[str, Any],
    registrations: Mapping[str, Mapping[str, str]],
    *,
    path: str,
    is_directory: bool,
    role: str | None = None,
) -> str:
    """Validate one proposed pathname using only immutable policy and registry data.

    In the deployed implementation, role and registered work item MUST come from
    a trusted manifest/owning registry, not from an unchecked client string.
    """
    parts = _parts(path)
    if len(parts) == 1:
        return "SDCR_ROOT" if is_directory else _deny("ROOT_FILE_FORBIDDEN")
    top = parts[1]
    if top not in policy["allowed_root_directories"]:
        _deny("UNKNOWN_ROOT_COLLECTION")
    rest = parts[2:]
    if top == "20-Programs":
        return _program(rest, policy, registrations, is_directory, role)
    return _other_top(top, rest, policy, is_directory, role)




def authorize_mutation(
    policy: Mapping[str, Any],
    registrations: Mapping[str, Mapping[str, str]],
    *,
    capability: str,
    target: str,
    is_directory: bool,
    role: str | None = None,
    source: str | None = None,
    privileged_migration: bool = False,
) -> str:
    """Model one proposed Files mutation; this pure helper does no I/O."""
    listed = policy["bypass_prevention"]["mutations"]
    if capability not in listed:
        _deny("UNKNOWN_MUTATION_CAPABILITY")
    if (
        capability in ("files.move", "files.rename", "files.trash", "files.restore")
        and not privileged_migration
    ):
        _deny("LIFECYCLE_CHANGE_REQUIRES_MIGRATION_AUTHORITY")
    if (
        capability in ("files.copy", "files.move", "files.rename", "files.restore")
        and source is None
    ):
        _deny("SOURCE_IDENTITY_REQUIRED")
    result = authorize_path(
        policy, registrations, path=target, is_directory=is_directory, role=role
    )
    if source is not None:
        authorize_path(
            policy, registrations, path=source, is_directory=is_directory, role=role
        )

        def owned_item(item_path: str) -> str | None:
            seq = _parts(item_path)
            if len(seq) > 6 and seq[1] == "20-Programs":
                return "/".join(seq[:7])
            return None

        if owned_item(source) != owned_item(target) and not privileged_migration:
            _deny("CROSS_OWNER_COPY_REQUIRES_AUTHORITY")
    return result


def route_session_artifact(
    policy: Mapping[str, Any],
    registrations: Mapping[str, Mapping[str, str]],
    *,
    work_item_id: str,
    session_id: str,
    category: str,
    artifact_id: str,
    filename: str,
) -> str:
    """Derive the destination from the trusted work-item owner."""
    owner = registrations.get(work_item_id)
    if owner is None:
        _deny("WORK_ITEM_NOT_REGISTERED")
    if category not in policy["session_artifact_categories"]:
        _deny("INVALID_ARTIFACT_CATEGORY")
    if (
        not _ident(session_id)
        or not _ident(artifact_id)
        or not _ident(filename)
        or len(filename.encode("utf-8")) > 180
    ):
        _deny("INVALID_ARTIFACT_FILENAME")
    path = (
        f"SDCR/20-Programs/{owner['program']}/workstreams/{owner['workstream']}"
        f"/work-items/{work_item_id}/sessions/{session_id}/artifacts/{category}"
        f"/{artifact_id}__{filename}"
    )
    authorize_path(policy, registrations, path=path, is_directory=False, role=category)
    return path


def can_complete(
    expected_artifact_ids: set[str],
    recorded_artifacts: Mapping[str, str],
    *,
    hashes_verified: bool,
    manifest_verified: bool,
    registry_verified: bool,
    receipt_verified: bool,
) -> bool:
    """No handoff on missing, unclassified, withheld or unverifiable artifacts."""
    if not all((hashes_verified, manifest_verified, registry_verified, receipt_verified)):
        return False
    if set(recorded_artifacts) != expected_artifact_ids:
        return False
    return all(
        status
        not in {
            "FAILED_EVIDENCE",
            "PROTECTED_WITHHELD",
            "UNCLASSIFIED",
            "MISSING",
            "UNVERIFIED",
        }
        for status in recorded_artifacts.values()
    )



# The existing public Files contract has no new error code for this extension.
# The storage adapter maps PlacementDeniedError to the existing invalid_path refusal
# without disclosing a private owner registry, path, or artifact payload.


def _in_sdcr(path: str) -> bool:
    return path == "SDCR" or path.startswith("SDCR/")


def _derived_role(path: str) -> str | None:
    """Derive structural category, never trust a `role` supplied by a caller.

    Actual content type/classification remains a separate intake/manifest gate;
    a raw Files API cannot determine semantic correctness from a file name.
    """
    bits = path.split("/")
    if len(bits) >= 2 and bits[1] == "20-Programs":
        if len(bits) >= 12 and bits[9] == "artifacts":
            return bits[10]
        if len(bits) >= 8:
            if bits[7] == "reference-inputs":
                return "input"
            if bits[7] == "canonical":
                return "canonical_pointer"
            if bits[7] == "reviews":
                return "review"
    if len(bits) >= 2:
        return {
            "10-Governance": "governance",
            "30-Exchange": "locator",
            "40-Publication": "locator",
            "50-Shared-Evidence": "locator",
            "60-Cross-Program-Decisions": "locator",
            "80-Templates": "template",
            "90-Migration": "migration",
            "99-Legacy-Archive": "legacy",
        }.get(bits[1])
    return None


class SDCRPlacementGate:
    """Immutable in-process SDCR placement policy with trusted owner binding.

    `registrations` must come from an operator-managed config outside all
    writable MY-PA workspaces. Neither Files metadata nor session caller text
    is an authorized registration source. The gateway validates the config's
    location at startup and composes this object only when explicitly enabled.
    """

    def __init__(
        self,
        policy: Mapping[str, Any],
        registrations: Mapping[str, Mapping[str, str]],
    ) -> None:
        if policy.get("schema_version") != "sdcr.directory-placement.v1":
            raise ValueError("sdcr_policy_schema_invalid")
        if policy.get("workspace_id") != "mcp" or policy.get("relative_root") != "SDCR":
            raise ValueError("sdcr_policy_scope_invalid")
        if policy.get("status") not in {"APPROVED_ACTIVE", "APPROVED_FOR_QUALIFICATION"}:
            raise ValueError("sdcr_policy_not_approved")
        programs = policy.get("program_workstreams")
        if not isinstance(programs, dict) or not programs:
            raise ValueError("sdcr_policy_programs_invalid")
        if not isinstance(registrations, dict) or not registrations:
            raise ValueError("sdcr_registrations_missing")
        verified: dict[str, dict[str, str]] = {}
        for work_id, owner in registrations.items():
            if not isinstance(work_id, str) or not _ident(work_id):
                raise ValueError("sdcr_registration_identity_invalid")
            if not isinstance(owner, dict):
                raise ValueError("sdcr_registration_owner_invalid")
            program, stream = owner.get("program"), owner.get("workstream")
            if not isinstance(program, str) or not isinstance(stream, str):
                raise ValueError("sdcr_registration_owner_invalid")
            if program not in programs or stream not in programs[program]:
                raise ValueError("sdcr_registration_unrecognized_owner")
            verified[work_id] = {"program": program, "workstream": stream}
        # Copies prevent external caller mutation after gate creation.
        self._registrations = verified
        self._policy = copy.deepcopy(policy)

    @property
    def registration_count(self) -> int:
        return len(self._registrations)

    @staticmethod
    def covers(path: str) -> bool:
        return _in_sdcr(path)

    def admit_create(
        self, path: str, *, is_directory: bool, expected_version: str | None = None
    ) -> str:
        """Check a direct create/update before any directory/byte operation.

        Parent auto-creation is checked separately for *every* intermediate
        directory, so `parents=True` cannot open an unapproved path.
        """
        if not self.covers(path):
            return "OUTSIDE_SDCR"
        if expected_version is not None:
            # Only typed owner/global index and canonical pointer paths may be
            # revised in place with the existing CAS/preimage machinery.
            basename = path.rsplit("/", 1)[-1]
            if (
                basename not in {"00_ARTIFACT_INDEX.json"}
                and not (basename.startswith("00_") and basename.endswith("_INDEX.json"))
                and not ("/canonical/" in path and basename.endswith(".json"))
            ):
                _deny("SDCR_IMMUTABLE_CONTENT")
        result = authorize_path(
            self._policy,
            self._registrations,
            path=path,
            is_directory=is_directory,
            role=_derived_role(path),
        )
        # Policy and trusted owner registry are supplied only by deployment,
        # not by mutable `00-Control` content in the Files workspace.
        if path.startswith("SDCR/00-Control/") and not is_directory:
            _deny("TRUSTED_CONTROL_REQUIRES_OPERATOR_PROVISIONING")
        return result

    def admit_directory_tree(self, path: str) -> None:
        if not self.covers(path):
            return
        bits = path.split("/")
        for n in range(1, len(bits) + 1):
            self.admit_create("/".join(bits[:n]), is_directory=True)

    def admit_transition(self, path: str, *, source: str | None = None) -> None:
        """Fail closed on SDCR copy/move/rename/restore/trash.

        A separately approved migration-specific entry point will be needed
        for historical relocation; regular Files calls cannot masquerade as it.
        """
        if self.covers(path) or (source is not None and self.covers(source)):
            _deny("SDCR_LIFECYCLE_CHANGE_REQUIRES_MIGRATION")
