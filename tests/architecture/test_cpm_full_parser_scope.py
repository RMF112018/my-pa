"""CPM Workbench S5a: the Full-Schedule parser plane stays inside its slice.

Contract `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`
sections 1.2, 3.1, 7, 9 and 10.1. FAST guards over the committed tree:

* **Generic extraction is unchanged.** `SUPPORTED_MEDIA_TYPES` is still exactly
  Markdown and plain text; `application/pdf` stays unsupported there (R2-AC-005).
* **Neutral naming.** No schedule source module, the fixture generator, any
  generated fixture or golden file carries a denylisted research-corpus token.
  The denylist is held as SHA-256 digests of lowercased word tokens, so this
  guard carries no proprietary string itself.
* **Import allowlist.** `domain/schedule` is standard-library only plus itself;
  `infrastructure/schedule` reaches the domain package, itself and (through
  `pdf.py` alone, enforced by `test_scope_and_hygiene.py`) `pypdfium2`; neither
  imports persistence, application, adapters, bootstrap or contracts.
* **No logging, printing, file or environment access** in either package.
* **The fixture generator is standard-library only** at module level (no
  `math`, no `random`, no clock), and **only the generator names
  `write_goldens`**, so no test can silently regenerate a golden.

* **The crosswalk is real.** Every test the contract's section 10.2-10.4
  crosswalk names exists as a top-level test function in the module it names,
  every name is still in the contract, and every section 10.3 gate name is an
  assertion key inside `test_quality_gates_hold_over_every_case`.

What it cannot prove: that a named test is collected and passes (the tiers
run them).
"""

from __future__ import annotations

import ast
import hashlib
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from tests.fixtures import schedule_full_pdf

from my_pa.domain.extraction.text import SUPPORTED_MEDIA_TYPES

ROOT: Final = Path(__file__).resolve().parents[2]
DOMAIN: Final = ROOT / "src" / "my_pa" / "domain" / "schedule"
INFRASTRUCTURE: Final = ROOT / "src" / "my_pa" / "infrastructure" / "schedule"
GENERATOR: Final = ROOT / "tests" / "fixtures" / "schedule_full_pdf.py"
GOLDENS: Final = ROOT / "tests" / "fixtures" / "schedule_full_goldens"
CONTRACT: Final = ROOT / "docs" / "architecture" / "cpm-workbench-p6-full-v1-parser-contract.md"

#: SHA-256 of lowercased `[A-Za-z0-9]+` tokens that must never appear (contract 10.1).
DENYLIST_SHA256: Final = frozenset(
    {
        "26049e25810bd7c6d59e3a8192e93d98c7b398f37061b36b64b58f795fc3d555",
        "7d8a34ddb21729dc73215f8125fcd0d58e32dc938e91978c5f6f6bdb1f88831d",
        "08bf7134d662b64c5241c42be9e9deb9a7644b35af95cce700e71503403a0e35",
        "d037ceb3377a6d6d9f9dbb49f1fa467f9ca87dfae3579542304a02b38280bf62",
    }
)
_TOKEN: Final = re.compile(rb"[A-Za-z0-9]+")

#: Package roots neither schedule package may import (contract 3.1).
FORBIDDEN_PREFIXES: Final = (
    "my_pa.infrastructure.persistence",
    "my_pa.application",
    "my_pa.adapters",
    "my_pa.bootstrap",
    "my_pa.contracts",
)


def _modules(package: Path) -> list[Path]:
    return sorted(package.rglob("*.py"))


def _imported_modules(tree: ast.AST) -> Iterator[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            yield from (alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            yield node.module


def _denylisted(data: bytes) -> set[str]:
    return {
        token.decode("ascii")
        for token in set(_TOKEN.findall(data))
        if hashlib.sha256(token.lower()).hexdigest() in DENYLIST_SHA256
    }


def _neutrality_targets() -> list[Path]:
    targets = [*_modules(DOMAIN), *_modules(INFRASTRUCTURE), GENERATOR]
    if GOLDENS.exists():
        targets += sorted(path for path in GOLDENS.rglob("*") if path.is_file())
    return targets


def test_generic_extraction_still_excludes_pdf() -> None:
    assert frozenset({"text/markdown", "text/plain"}) == SUPPORTED_MEDIA_TYPES
    assert "application/pdf" not in SUPPORTED_MEDIA_TYPES


def test_schedule_files_carry_no_denylisted_token() -> None:
    offending = {
        str(path.relative_to(ROOT)): sorted(found)
        for path in _neutrality_targets()
        if (found := _denylisted(path.read_bytes()))
    }
    assert DOMAIN.is_dir()
    assert INFRASTRUCTURE.is_dir()
    assert not offending, f"denylisted research-corpus tokens: {offending}"


def test_generated_fixtures_carry_no_denylisted_token() -> None:
    offending = {
        f"{family}__{variant}": sorted(found)
        for family, variant in schedule_full_pdf.CASES
        if (found := _denylisted(schedule_full_pdf.build(family, variant).pdf))
    }
    assert not offending, f"denylisted research-corpus tokens: {offending}"


def test_schedule_import_allowlist() -> None:
    stdlib = sys.stdlib_module_names
    wrong: list[str] = []
    for package, allowed in (
        (DOMAIN, ("my_pa.domain.schedule",)),
        (INFRASTRUCTURE, ("my_pa.domain.schedule", "my_pa.infrastructure.schedule", "pypdfium2")),
    ):
        for path in _modules(package):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for name in _imported_modules(tree):
                root = name.split(".")[0]
                if root in stdlib or root == "__future__":
                    continue
                if not any(name == a or name.startswith(f"{a}.") for a in allowed):
                    wrong.append(f"{path.relative_to(ROOT)} imports {name}")
                if name.startswith(FORBIDDEN_PREFIXES):
                    wrong.append(f"{path.relative_to(ROOT)} imports forbidden {name}")
    assert not wrong, wrong


def test_schedule_modules_neither_log_nor_print() -> None:
    wrong: list[str] = []
    for path in [*_modules(DOMAIN), *_modules(INFRASTRUCTURE)]:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for name in _imported_modules(tree):
            if name.split(".")[0] in {"logging", "os", "pathlib", "io", "shutil", "tempfile"}:
                wrong.append(f"{path.relative_to(ROOT)} imports {name}")
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in {"print", "open", "input", "breakpoint"}
            ):
                wrong.append(f"{path.relative_to(ROOT)}:{node.lineno} calls {node.func.id}")
    assert not wrong, wrong


def test_fixture_generator_is_standard_library_only() -> None:
    tree = ast.parse(GENERATOR.read_text(encoding="utf-8"), filename=str(GENERATOR))
    top_level = [
        name
        for node in tree.body
        if isinstance(node, ast.Import | ast.ImportFrom)
        for name in _imported_modules(node)
    ]
    assert top_level, "the generator imports nothing at module level?"
    for name in top_level:
        root = name.split(".")[0]
        assert root in sys.stdlib_module_names or root == "__future__", name
        assert root not in {"math", "random", "time", "secrets", "uuid"}, name
    # The only non-stdlib reach is the lazy parser import inside the golden writer.
    lazy = [
        (node.lineno, name)
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node not in tree.body
        for name in _imported_modules(node)
    ]
    assert {name for _, name in lazy} <= {
        "my_pa.domain.schedule",
        "my_pa.infrastructure.schedule.full_profile",
    }


def test_only_the_generator_references_write_goldens() -> None:
    wrong: list[str] = []
    for path in sorted((ROOT / "tests").rglob("*.py")):
        if path == GENERATOR:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            named = (isinstance(node, ast.Name) and node.id == "write_goldens") or (
                isinstance(node, ast.Attribute) and node.attr == "write_goldens"
            )
            imported = isinstance(node, ast.ImportFrom) and any(
                alias.name == "write_goldens" for alias in node.names
            )
            if named or imported:
                wrong.append(f"{path.relative_to(ROOT)}:{getattr(node, 'lineno', '?')}")
    assert not wrong, wrong


#: Contract sections 10.2-10.4: module -> the test functions the crosswalk names.
CROSSWALK: Final[dict[str, tuple[str, ...]]] = {
    "tests/unit/test_schedule_full_goldens.py": (
        "test_every_case_matches_its_golden",
        "test_linkage_is_eligible_only_for_complete_or_partial",
        "test_merged_summary_label_is_never_an_activity_id",
        "test_vertical_offset_summary_is_one_row",
        "test_occluded_od_header_parses_and_only_warns",
        "test_missing_id_row_invents_nothing_and_links_nothing",
        "test_duration_date_tokens_stay_in_their_cells",
        "test_chart_duplicates_contribute_zero_fragments",
        "test_watermark_contributes_zero_fragments",
        "test_exact_duplicate_collapses_and_overlap_is_ambiguous",
        "test_quality_gates_hold_over_every_case",
        "test_86_page_equivalent_reproduces_the_measured_corpus",
        "test_generated_pdfs_are_deterministic_and_pinned",
        "test_golden_files_are_pinned_by_digest",
        "test_golden_directory_holds_exactly_the_registered_cases",
        "test_86_page_equivalent_parse_time_is_reported",
    ),
    "tests/unit/test_schedule_full_pdf.py": (
        "test_byte_cap_is_checked_before_pdfium_opens",
        "test_page_cap_is_checked_before_any_page_loads",
        "test_object_and_char_caps_stop_before_the_next_page",
        "test_corrupt_encrypted_and_image_only_fail_closed",
        "test_budget_refuses_at_first_and_mid_extraction_checkpoints",
        "test_refusals_carry_codes_only",
        "test_handles_are_closed_on_every_exit",
        "test_extraction_is_identical_across_runs",
        "test_form_xobject_text_is_unsupported_layout",
        "test_object_text_is_attributed_non_generated_characters",
        "test_no_generated_character_enters_evidence",
        "test_suppressed_objects_resolve_deterministically",
        "test_unmapped_characters_make_the_cell_ambiguous",
        "test_unknown_character_handle_is_parser_exception",
        "test_fixture_text_state_is_reset_in_every_block",
        "test_zero_height_own_row_is_placed_by_the_seed_key",
        "test_unknown_text_fragment_does_not_decide_the_row_case",
        "test_security_error_and_unknown_filter_are_encrypted",
        "test_page_origin_is_validated",
        "test_engine_provenance_is_outside_the_digest",
        "test_a_suppressed_copy_in_another_cell_is_ambiguous",
        "test_budget_checkpoints_every_1000_objects",
        "test_budget_checkpoints_every_1000_characters",
        "test_form_objects_join_the_cap_before_their_children_are_read",
        "test_metadata_ignores_unmapped_objects",
        "test_overlapping_title_pieces_never_publish_a_doubled_title",
        "test_a_stale_pdfium_error_never_decides_the_refusal",
    ),
    "tests/unit/test_schedule_full_profile.py": (
        "test_production_limits_are_the_r2_bounds",
        "test_limits_can_only_be_tightened",
        "test_profile_constants_are_frozen",
        "test_rows_group_by_seed_overlap_not_centre_distance",
        "test_grouping_compares_to_the_fixed_seed",
        "test_overlap_ratio_boundary_is_one_half",
        "test_cell_band_boundaries_on_every_grid_line",
        "test_classification_precedence",
        "test_row_wrap_requires_pitch_below_10pt",
        "test_hierarchy_clusters_and_stack",
        "test_hierarchy_ambiguity_propagates",
        "test_watermark_signature_and_ordinary_draft",
        "test_missing_and_duplicate_ids_force_review_required",
        "test_od_occlusion_admits_replaced_and_overlay_only",
        "test_wrap_detects_bold_label_continuations",
        "test_summary_requires_a_value_cell",
        "test_level_gap_is_hierarchy_ambiguous",
        "test_watermark_rotation_uses_decimal_tangents",
    ),
    "tests/unit/test_schedule_model.py": (
        "test_activity_id_normalization_is_nfc_and_trim_only",
        "test_cell_value_is_present_iff_published_value",
        "test_cell_evidence_shape_is_cpm_full_cells_v1",
        "test_closed_enums_have_exactly_the_r2_members",
        "test_issue_severity_is_total",
        "test_canonical_bytes_are_sorted_ascii_and_stable",
        "test_canonical_numbers_are_fixed_decimal_strings",
        "test_outcome_derivation_table",
    ),
    "tests/architecture/test_cpm_full_parser_scope.py": (
        "test_schedule_files_carry_no_denylisted_token",
        "test_generic_extraction_still_excludes_pdf",
        "test_schedule_modules_neither_log_nor_print",
    ),
    "tests/architecture/test_scope_and_hygiene.py": (
        "test_a_confined_dependency_is_imported_only_where_it_belongs",
        "test_every_confined_dependency_is_actually_used_there",
    ),
}

#: Contract section 10.3: one assertion key per R2 section 39 gate.
QUALITY_GATES: Final = (
    "id_precision",
    "id_recall",
    "id_exact",
    "stable_false_merge",
    "spurious_link",
    "dropped_id_rows",
    "summary_promotion",
    "name_exact",
    "date_accuracy",
    "duration_accuracy",
    "coerced_invalid",
    "row_type_accuracy",
    "hierarchy_accuracy",
    "hierarchy_ambiguity_explicit",
    "chart_admitted",
    "watermark_admitted",
    "wrap_concatenated",
    "bad_identity_linked",
    "provenance_match",
    "review_required_links",
)


def _test_functions(path: Path) -> dict[str, ast.FunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name: node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")
    }


def test_the_contract_crosswalk_names_tests_that_exist() -> None:
    contract = CONTRACT.read_text(encoding="utf-8")
    missing: list[str] = []
    for module, names in CROSSWALK.items():
        defined = _test_functions(ROOT / module)
        for name in names:
            if name not in defined:
                missing.append(f"{module}::{name} is not defined")
            if name not in contract:
                missing.append(f"{name} is no longer named by the contract")
    assert not missing, missing


def test_every_quality_gate_is_an_assertion_of_the_gate_test() -> None:
    contract = CONTRACT.read_text(encoding="utf-8")
    goldens = ROOT / "tests" / "unit" / "test_schedule_full_goldens.py"
    gate_test = _test_functions(goldens)["test_quality_gates_hold_over_every_case"]
    asserted = {
        node.slice.value
        for statement in gate_test.body
        if isinstance(statement, ast.Assert)
        for node in ast.walk(statement.test)
        if isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    }
    assert asserted == set(QUALITY_GATES)
    for gate in QUALITY_GATES:
        assert f"`{gate}`" in contract, gate
