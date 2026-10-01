"""T-20 (WP-RE-04; T-001): every identity-correction write site is enumerated.

The Record Event emitters for merge and split (WP-RE-04 Phase 4B) stage one
event per materially changed canonical record. That is only complete if the set
of writes an identity correction performs is the set the plan enumerated
(Gate-1 plan WP-RE-04 and PATH-SYMBOL §6: M-L, M1-M10, S-L, S1-S9). A write
that appears without being enumerated would change canonical state with no
event -- stop N20 -- so this module pins the set by parsing the source.

Two claims:

1. **Inside `IdentityCorrectionService`**, every repository call
   (`self._entities.*`, `self._memories.*`) is either a named read or one of the
   enumerated writes, in the method the enumeration names. Any other callee --
   a new write, or a read nobody has classified -- fails here.
2. **The two handlers** (`ApplicationService._entities_merge` and
   `_entities_split`) add exactly one write of their own: the re-enrichment
   registration (M10, S9), which is control and has no event.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
SERVICE: Final = ROOT / "src" / "my_pa" / "application" / "identity_correction.py"
HANDLERS: Final = ROOT / "src" / "my_pa" / "application" / "service.py"
CLASS: Final = "IdentityCorrectionService"
PORTS: Final = frozenset({"_entities", "_memories"})

#: `(method, port, callee) -> enumeration id`. The preview-only writes are
#: listed because they exist, and marked as outside every apply path.
ENUMERATED_WRITES: Final[dict[tuple[str, str, str], str]] = {
    ("apply", "_entities", "serialize_identifier_entity_scopes"): "M-L (advisory lock)",
    ("apply", "_entities", "serialize_identifier_claim_keys"): "M-L (advisory lock)",
    ("_perform", "_entities", "consume_identity_preview"): "M1",
    ("_perform", "_entities", "record_identity_operation"): "M2",
    ("_write", "_entities", "redirect_entity"): "M3",
    ("_write", "_entities", "invalidate_proposal"): "M4",
    ("_write", "_memories", "apply_identity_effect"): "M5",
    ("_write", "_entities", "reparent_entity_reference"): "M6",
    ("_write", "_entities", "supersede_child_record"): "M7",
    ("_perform", "_entities", "record_identity_effects"): "M8",
    ("_perform", "_entities", "complete_identity_operation"): "M9",
    ("split_apply", "_entities", "serialize_identifier_entity_scopes"): "S-L (advisory lock)",
    ("split_apply", "_entities", "consume_identity_preview"): "S1",
    ("split_apply", "_entities", "record_identity_operation"): "S2",
    ("split_apply", "_memories", "restore_identity_effect"): "S3",
    ("split_apply", "_entities", "restore_identity_effect"): "S4",
    ("split_apply", "_entities", "reparent_entity_reference"): "S5",
    ("split_apply", "_entities", "record_ambiguity_settlements"): "S6",
    ("split_apply", "_entities", "record_identity_effects"): "S7",
    ("split_apply", "_entities", "complete_identity_operation"): "S8",
    ("preview", "_entities", "record_identity_preview"): "preview only (excluded)",
    ("split_preview", "_entities", "record_identity_preview"): "preview only (excluded)",
    ("split_preview", "_entities", "record_preview_ambiguities"): "preview only (excluded)",
}

#: Every repository callee the service may call that writes nothing.
READS: Final = frozenset(
    {
        "addresses",
        "aliases",
        "assignment",
        "assignments",
        "assignments_scoped_by",
        "communication_methods",
        # WP-RE-04 Phase 4B: the owning-memory and memory-facts reads the
        # merge/split Record Events are built from (OD-2 (b), OD-8).
        "context_link_owner",
        "entity_proposal_review_snapshot",
        "external_identifiers",
        "fact_evidence_links_naming",
        "get",
        "identity_effect_matches_after_state",
        "identity_effects",
        "identity_operation",
        "identity_operation_for_key",
        "identity_preview",
        "memory_feed_facts",
        "names",
        "observation",
        "observations",
        "organization_profile",
        "person_organization_affiliations_as_organization",
        "person_organization_affiliations_as_person",
        "plan_identity_merge",
        "preview_ambiguities",
        "project_participations_as_participant",
        "project_participations_as_project",
        "proposals",
        "records_bound_to_entity_outside",
        "relationship",
        "relationships",
        "relationships_scoped_by",
        "resolution_decisions_naming",
        "split_for_source_operation",
    }
)

#: The handlers' own writes: the re-enrichment registration only (M10, S9).
HANDLER_WRITES: Final[dict[str, frozenset[str]]] = {
    "_entities_merge": frozenset({"self._register_reenrichment"}),
    "_entities_split": frozenset({"self._register_reenrichment"}),
}


def _repository_calls(tree: ast.Module) -> set[tuple[str, str, str]]:
    calls: set[tuple[str, str, str]] = set()
    for node in tree.body:
        if not (isinstance(node, ast.ClassDef) and node.name == CLASS):
            continue
        for method in node.body:
            if not isinstance(method, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for inner in ast.walk(method):
                if (
                    isinstance(inner, ast.Call)
                    and isinstance(inner.func, ast.Attribute)
                    and isinstance(inner.func.value, ast.Attribute)
                    and isinstance(inner.func.value.value, ast.Name)
                    and inner.func.value.value.id == "self"
                    and inner.func.value.attr in PORTS
                ):
                    calls.add((method.name, inner.func.value.attr, inner.func.attr))
    return calls


def _writes(calls: set[tuple[str, str, str]]) -> set[tuple[str, str, str]]:
    return {call for call in calls if call[2] not in READS}


def test_the_service_performs_exactly_the_enumerated_writes() -> None:
    writes = _writes(_repository_calls(ast.parse(SERVICE.read_text(encoding="utf-8"))))
    unlisted = writes - set(ENUMERATED_WRITES)
    missing = set(ENUMERATED_WRITES) - writes
    assert not unlisted, f"STOP N20: unenumerated identity-correction writes {sorted(unlisted)}"
    assert not missing, f"the enumeration names writes the code no longer makes: {sorted(missing)}"


def test_the_scan_sees_a_planted_write() -> None:
    """The control: a new callee on either port is reported, not ignored."""
    planted = ast.parse(
        "class IdentityCorrectionService:\n"
        "    def _write(self):\n"
        "        self._entities.rewrite_everything()\n"
        "        self._entities.get()\n"
    )
    assert _writes(_repository_calls(planted)) == {("_write", "_entities", "rewrite_everything")}


def _handler_calls(name: str) -> set[str]:
    tree = ast.parse(HANDLERS.read_text(encoding="utf-8"))
    (handler,) = (
        node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name
    )
    names: set[str] = set()
    for inner in ast.walk(handler):
        if isinstance(inner, ast.Call):
            parts: list[str] = []
            func: ast.expr = inner.func
            while isinstance(func, ast.Attribute):
                parts.append(func.attr)
                func = func.value
            if isinstance(func, ast.Name):
                parts.append(func.id)
            names.add(".".join(reversed(parts)))
    return names


def test_the_handlers_add_only_the_reenrichment_registration() -> None:
    for handler, expected in HANDLER_WRITES.items():
        calls = _handler_calls(handler)
        registrations = {call for call in calls if call.startswith("self._register")}
        assert registrations == expected, (handler, registrations)
        assert not {call for call in calls if call.startswith("unit_of_work.")}, handler
