"""KLP-WP-02: the single Knowledge revision `6734f039f7a6` and its frozen DDL inventory.

R6 plan amendment section 11; matrix `schema_contract`, `schema_functions`,
`schema_creation_order`, `existing_table_alters`, `initial_predicates`,
`migration_contract`. This module proves, in two halves:

**FAST (static).** The revision is the sole head directly on `0641c354ca85`
and the only file of its name (AC-076); it imports nothing from `my_pa` and
derives nothing from an enum (AC-077); every CREATE TABLE, index, deferred
foreign key and trigger is the matrix contract rendered verbatim, in creation
order; every closed-set literal equals both the matrix and the WP-01 enum it
mirrors; the eight seeds are the matrix rows; the A1-A5 AT literals are the
matrix after-literals and the BEFORE literals are byte copies of the revisions
that installed them; `tables.py` declares the same names; the schema-ahead
contract module is the matrix gap table; no other revision names a Knowledge
table or a widened CHECK name (AC-131).

**Migration edge (database).** On disposable PostgreSQL databases: an empty
database reaches the head and its `pg_catalog` inventory -- columns, types,
nullability, defaults, every named constraint, index and trigger, the
functions, the seeds and A1-A7 -- equals the matrix exactly (AC-131); the
predecessor holding context items and audit rows upgrades unchanged (N1-N4 are
untouched); `downgrade` refuses with `restrict_violation`, deleting nothing,
while any Knowledge state exists, and otherwise restores the generated context
CHECK names and the exact BEFORE literals and round-trips (AC-078); every named
CHECK is proved red in isolation by a minimal violating INSERT, and every
trigger, the key foreign keys and the partial unique indexes by a minimal
violating INSERT/UPDATE/DELETE (AC-003..AC-150 schema slices, KLP-R6V-201).

The file name routes every `database` node to migration-edge
(`tests/db/fixtures.py`); the unmarked nodes run in FAST. Every value is
synthetic.
"""

from __future__ import annotations

import ast
import importlib.util
import io
import json
import re
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, Table, insert, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from tests.schema import knowledge_schema_ahead_contract as contract

from my_pa.domain.common.classification import Classification
from my_pa.domain.knowledge_assertion import vocabulary as kv
from my_pa.domain.relationship.entity import EntityType
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence import tables as declared

ROOT: Final = Path(__file__).resolve().parents[2]
VERSIONS: Final = ROOT / "migrations" / "versions"
MATRIX_PATH: Final = ROOT / "tests" / "architecture" / "klp_implementation_matrix_r6.json"
SCHEMA: Final = "knowledge"
REVISION: Final = "6734f039f7a6"
PREVIOUS: Final = "0641c354ca85"
MIGRATION: Final = VERSIONS / "20261004_6734f039f7a6_knowledge_assertion_layer.py"
RESTRICT_VIOLATION: Final = "23001"
FOREIGN_KEY_VIOLATION: Final = "23503"
UNIQUE_VIOLATION: Final = "23505"
CHECK_VIOLATION: Final = "23514"
_WHITESPACE: Final = re.compile(r"\s+")
_LITERAL: Final = re.compile(r"'([^']*)'")


@cache
def _matrix() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(MATRIX_PATH.read_text(encoding="utf-8"))
    return loaded


@cache
def _revision() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_knowledge_revision", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _flat(sql: str) -> str:
    """Whitespace-insensitive text: runs collapse, and none survives inside a bracket edge."""
    flat = _WHITESPACE.sub(" ", sql).strip()
    return flat.replace("( ", "(").replace(" )", ")")


def _contract() -> Mapping[str, dict[str, Any]]:
    contract_tables: dict[str, dict[str, Any]] = _matrix()["schema_contract"]
    return contract_tables


def _alters() -> dict[str, dict[str, Any]]:
    return {alter["id"]: alter for alter in _matrix()["existing_table_alters"]}


def _checks(table: str) -> list[dict[str, Any]]:
    return [c for c in _contract()[table]["constraints"] if c["kind"] == "check"]


def _config(buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


# ---- rendering the matrix contract as the DDL it denotes -------------------------------


def _render_constraint(constraint: Mapping[str, Any]) -> str:
    columns = ", ".join(constraint.get("columns", []))
    name = constraint["name"]
    kind = constraint["kind"]
    if kind == "primary_key":
        return f"CONSTRAINT {name} PRIMARY KEY ({columns})"
    if kind == "unique":
        return f"CONSTRAINT {name} UNIQUE ({columns})"
    if kind == "check":
        return f"CONSTRAINT {name} CHECK ({constraint['expression']})"
    assert kind == "foreign_key", constraint
    assert constraint["on_delete"] == "RESTRICT" and constraint["deferrable"] is False
    return (
        f"CONSTRAINT {name} FOREIGN KEY ({columns}) REFERENCES "
        f"knowledge.{constraint['references_table']} "
        f"({', '.join(constraint['references_columns'])}) ON DELETE RESTRICT NOT DEFERRABLE"
    )


def _render_table(table: Mapping[str, Any]) -> str:
    parts = []
    for column in table["columns"]:
        part = f"{column['name']} {column['type']}" + ("" if column["nullable"] else " NOT NULL")
        if column["default"] is not None:
            part += f" DEFAULT {column['default']}"
        parts.append(part)
    parts.extend(
        _render_constraint(constraint)
        for constraint in table["constraints"]
        if not constraint.get("added_after_all_tables", False)
    )
    return f"CREATE TABLE knowledge.{table['name']} (" + ", ".join(parts) + ")"


def _render_index(table: str, index: Mapping[str, Any]) -> str:
    unique = "UNIQUE " if index["unique"] else ""
    where = f" WHERE {index['where']}" if index["where"] else ""
    return (
        f"CREATE {unique}INDEX {index['name']} ON knowledge.{table} "
        f"({', '.join(index['columns'])}){where}"
    )


def _render_trigger(table: str, trigger: Mapping[str, Any]) -> str:
    if trigger["constraint_trigger_deferrable_initially_deferred"]:
        return (
            f"CREATE CONSTRAINT TRIGGER {trigger['name']} {trigger['timing']} "
            f"{trigger['events']} ON knowledge.{table} DEFERRABLE INITIALLY DEFERRED FOR EACH "
            f"{trigger['level']} EXECUTE FUNCTION {trigger['function']}"
        )
    return (
        f"CREATE TRIGGER {trigger['name']} {trigger['timing']} {trigger['events']} ON "
        f"knowledge.{table} FOR EACH {trigger['level']} EXECUTE FUNCTION {trigger['function']}"
    )


# ---- FAST: the graph -------------------------------------------------------------------


def test_the_revision_is_the_single_head_directly_on_0641c354ca85() -> None:
    """AC-076: one current head; the revision was generated from the sole head."""
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert _revision().revision == REVISION
    assert _revision().down_revision == PREVIOUS
    migration_contract = _matrix()["migration_contract"]
    assert migration_contract["current_head"] == PREVIOUS
    files = sorted(VERSIONS.glob("*.py"))
    assert len(files) == migration_contract["expected_post_r6_revision_file_count"] == 112
    assert [path.name for path in VERSIONS.glob("*_knowledge_assertion_layer.py")] == [
        MIGRATION.name
    ]


# ---- FAST: the freeze ------------------------------------------------------------------


def test_revision_imports_no_domain_or_persistence_modules() -> None:
    """AC-077: frozen text; no `my_pa` import, no live declaration, no enum."""
    source = MIGRATION.read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert imported <= {"alembic", "__future__", "typing"}
    assert "my_pa" not in source
    assert "create_all" not in source
    assert "StrEnum" not in source
    assert "sa.Table" not in source


def test_no_other_revision_names_a_knowledge_table_or_a_widened_check() -> None:
    """AC-131: later KLP work packages are schema-code-only; nothing else touches these."""
    names = set(_contract()) | {
        "context_run_item_plane_is_known",
        "context_run_item_authority_is_known",
        "context_run_item_knowledge_assertion_identity",
        "knowledge_assertion_id",
        "a_memory_is_identified_within_its_principal",
    }
    for path in sorted(VERSIONS.glob("*.py")):
        if path == MIGRATION:
            continue
        source = path.read_text(encoding="utf-8")
        for name in names:
            assert not re.search(rf"\b{name}\b", source), (path.name, name)


def test_the_tables_are_created_in_the_matrix_creation_order() -> None:
    assert [table for table, _ddl, _indexes in _revision()._TABLE_DDL] == _matrix()[
        "schema_creation_order"
    ]
    assert list(_contract()) == _matrix()["schema_creation_order"]
    assert len(_contract()) == 14


@pytest.mark.parametrize("table", list(_matrix()["schema_creation_order"]))
def test_each_create_table_is_the_matrix_contract_verbatim(table: str) -> None:
    """Every column, type, nullability, default and inline constraint, in order."""
    ddl = {name: sql for name, sql, _indexes in _revision()._TABLE_DDL}[table]
    assert _flat(ddl) == _flat(_render_table(_contract()[table]))


@pytest.mark.parametrize("table", list(_matrix()["schema_creation_order"]))
def test_each_table_carries_exactly_the_matrix_indexes(table: str) -> None:
    indexes = {name: tuple(sql) for name, _sql, sql in _revision()._TABLE_DDL}[table]
    expected = tuple(_render_index(table, index) for index in _contract()[table]["indexes"])
    assert tuple(_flat(sql) for sql in indexes) == tuple(_flat(sql) for sql in expected)


def test_the_deferred_foreign_keys_are_exactly_the_four_result_keys() -> None:
    expected = [
        (
            constraint["name"],
            f"ALTER TABLE knowledge.{table} ADD {_render_constraint(constraint)}",
        )
        for table, contract_table in _contract().items()
        for constraint in contract_table["constraints"]
        if constraint.get("added_after_all_tables", False)
    ]
    assert len(expected) == 4
    assert [(name, _flat(sql)) for name, sql in _revision()._DEFERRED_FOREIGN_KEYS] == expected


def test_every_foreign_key_restricts_and_is_not_deferrable() -> None:
    flat = _flat(MIGRATION.read_text(encoding="utf-8"))
    references = re.findall(r"REFERENCES knowledge\.\w+ \([^)]*\)([^,)\"]*)", flat)
    expected = sum(
        1
        for table in _contract().values()
        for constraint in table["constraints"]
        if constraint["kind"] == "foreign_key"
    )
    assert len(references) == expected == 33
    for tail in references:
        assert tail.strip() == "ON DELETE RESTRICT NOT DEFERRABLE", tail


def test_the_triggers_are_exactly_the_matrix_triggers() -> None:
    expected = [
        (trigger["name"], table, _render_trigger(table, trigger))
        for table, contract_table in _contract().items()
        for trigger in contract_table["triggers"]
    ]
    assert len(expected) == 19
    assert [(name, table, _flat(sql)) for name, table, sql in _revision()._TRIGGERS] == expected


def test_the_shared_functions_are_the_matrix_schema_functions() -> None:
    functions = dict(_revision()._SHARED_FUNCTIONS)
    assert list(functions) == [
        "knowledge_classification_rank(text)",
        "knowledge_row_is_append_only()",
    ]
    for expected, sql in zip(_matrix()["schema_functions"], functions.values(), strict=True):
        flat = _flat(sql)
        assert f"CREATE FUNCTION {expected['name']}" in flat
        assert f"RETURNS {expected['returns']} LANGUAGE {expected['language']}" in flat
        assert expected["volatility"] in flat
        assert _flat(expected["body"]) in flat


def test_every_trigger_function_is_schema_qualified_plpgsql_with_stated_error_codes() -> None:
    """R6 11.1: plpgsql, `knowledge.`-qualified, `restrict_violation` or `check_violation`."""
    named = {
        trigger["function"].removeprefix("knowledge.").removesuffix("()")
        for table in _contract().values()
        for trigger in table["triggers"]
    } - {"knowledge_row_is_append_only"}
    listed = {
        function.removeprefix("knowledge.").removesuffix("()")
        for table in _contract().values()
        for function in table["trigger_functions"]
    } - {"knowledge_row_is_append_only"}
    functions = dict(_revision()._TRIGGER_FUNCTIONS)
    assert set(functions) == named == listed
    assert len(functions) == 12
    for name, sql in functions.items():
        flat = _flat(sql)
        assert flat.startswith(f"CREATE FUNCTION knowledge.{name}()"), name
        assert "LANGUAGE plpgsql" in flat, name
        for relation in re.findall(r"\b(?:FROM|INTO|JOIN|UPDATE)\s+([a-z_.]+)", flat):
            assert relation.startswith("knowledge.") or relation in {
                "head",
                "p",
                "c",
                "s",
            }, (name, relation)
        assert "knowledge_classification_rank(" not in flat.replace(
            "knowledge.knowledge_classification_rank(", ""
        ), name
        codes = re.findall(r"ERRCODE = '([a-z_]+)'", flat)
        assert codes and set(codes) <= {"restrict_violation", "check_violation"}, name
        assert flat.count("RAISE EXCEPTION") == len(codes), name


# ---- FAST: closed vocabularies equal the matrix and the WP-01 enums ----------------------

#: Each Knowledge closed-set CHECK, with the WP-01 (or reused) value source it mirrors.
#: Frozen literals in the revision; this is where drift in either is caught.
CLOSED_SETS: Final[dict[str, tuple[str, Any]]] = {
    "knowledge_predicate_admission_state_is_known": (
        "admission_state",
        kv.KnowledgePredicateAdmissionState,
    ),
    "knowledge_predicate_value_type_is_known": ("value_type", kv.KnowledgeValueType),
    "knowledge_predicate_cardinality_is_known": ("cardinality", kv.KnowledgeCardinality),
    "knowledge_predicate_temporal_semantics_is_known": (
        "temporal_semantics",
        kv.KnowledgeTemporalSemantics,
    ),
    "knowledge_predicate_qualifier_rule_is_known": ("qualifier_rule", kv.KnowledgeQualifierRule),
    "knowledge_predicate_subject_kinds_are_known": (
        "allowed_subject_kinds",
        kv.KnowledgeSubjectKind,
    ),
    "knowledge_predicate_entity_types_are_known": ("allowed_entity_types", EntityType),
    "knowledge_predicate_canonical_owner_is_known": ("canonical_owner", kv.KnowledgeCanonicalOwner),
    "knowledge_predicate_admission_policy_is_known": (
        "autonomous_admission_policy",
        kv.KnowledgeAutonomousAdmissionPolicy,
    ),
    "knowledge_predicate_review_requirement_is_known": (
        "review_requirement",
        kv.KnowledgeReviewRequirement,
    ),
    "knowledge_predicate_consequential_class_is_known": (
        "consequential_class",
        kv.KnowledgeConsequentialClass,
    ),
    "knowledge_predicate_normalization_rule_is_known": (
        "normalization_rule",
        kv.KnowledgeNormalizationRule,
    ),
    "knowledge_predicate_classification_floor_is_known": (
        "classification_floor",
        kv.KNOWLEDGE_CLASSIFICATION_FLOORS,
    ),
    "knowledge_predicate_conflict_rule_is_known": ("conflict_rule", kv.KnowledgeConflictRule),
    "knowledge_predicate_minimum_authority_is_known": (
        "minimum_evidence_authority",
        kv.KnowledgeEvidenceAuthority,
    ),
    "knowledge_profile_origin_system_is_known": ("origin_system", kv.KnowledgeOriginSystem),
    "knowledge_profile_authority_ceiling_is_known": (
        "authority_ceiling",
        kv.KnowledgeEvidenceAuthority,
    ),
    "knowledge_profile_proof_state_is_known": (
        "read_only_proof_state",
        kv.KnowledgeReadOnlyProofState,
    ),
    "knowledge_submission_origin_is_known": ("origin", kv.KnowledgeSubmissionOrigin),
    "knowledge_submission_subject_kind_is_known": ("subject_kind", kv.KnowledgeSubjectKind),
    "knowledge_submission_state_is_known": ("submission_state", kv.KnowledgeLedgerState),
    "knowledge_submission_outcome_is_known": ("outcome", kv.KnowledgeSubmissionOutcome),
    "knowledge_submission_reason_is_known": ("reason", kv.STORED_SUBMISSION_REASONS),
    "knowledge_submission_result_owner_is_known": (
        "result_canonical_owner",
        kv.KnowledgeCanonicalOwner,
    ),
    "knowledge_evidence_ref_identity_kind_is_known": (
        "identity_kind",
        kv.KnowledgeEvidenceIdentityKind,
    ),
    "knowledge_evidence_ref_content_origin_is_known": (
        "content_origin",
        kv.KnowledgeContentOrigin,
    ),
    "knowledge_evidence_ref_classification_is_known": ("source_classification", Classification),
    "knowledge_evidence_ref_availability_is_known": (
        "availability_state",
        kv.KnowledgeEvidenceAvailability,
    ),
    "knowledge_subject_lock_subject_kind_is_known": ("subject_kind", kv.KnowledgeSubjectKind),
    "knowledge_proposal_subject_kind_is_known": ("subject_kind", kv.KnowledgeSubjectKind),
    "knowledge_proposal_classification_is_known": ("classification", Classification),
    "knowledge_proposal_risk_class_is_known": (
        "risk_class",
        ("low", "moderate", "high", "critical"),
    ),
    "knowledge_proposal_review_requirement_is_known": (
        "review_requirement",
        kv.KnowledgeReviewRequirement,
    ),
    "knowledge_proposal_state_is_known": ("state", kv.KnowledgeProposalState),
    "knowledge_decision_requirement_is_known": (
        "review_requirement",
        kv.KnowledgeReviewRequirement,
    ),
    "knowledge_decision_disposition_is_known": ("disposition", kv.KnowledgeReviewDisposition),
    "knowledge_decision_channel_is_known": ("decision_channel", kv.KnowledgeDecisionChannel),
    "knowledge_decision_authority_class_is_known": (
        "operator_authority_class",
        kv.KnowledgeReviewAuthorityClass,
    ),
    "knowledge_assertion_subject_kind_is_known": ("subject_kind", kv.KnowledgeSubjectKind),
    "knowledge_assertion_epistemic_status_is_known": (
        "epistemic_status",
        kv.KnowledgeEpistemicStatus,
    ),
    "knowledge_assertion_classification_is_known": ("classification", Classification),
    "knowledge_assertion_lifecycle_is_known": ("lifecycle", kv.KnowledgeAssertionLifecycle),
    "knowledge_mutation_kind_is_known": ("mutation_kind", kv.KnowledgeMutationKind),
    "knowledge_evidence_link_role_is_known": ("evidence_role", kv.KnowledgeEvidenceRole),
    "knowledge_submission_evidence_role_is_known": ("evidence_role", kv.KnowledgeEvidenceRole),
    "knowledge_checkpoint_kind_is_known": ("checkpoint_kind", kv.KnowledgeCheckpointKind),
    "knowledge_checkpoint_request_state_is_known": ("state", kv.KnowledgeLedgerState),
    "knowledge_checkpoint_request_outcome_is_known": (
        "result_outcome",
        kv.KnowledgeCheckpointOutcome,
    ),
    "knowledge_checkpoint_request_result_kind_is_known": (
        "result_checkpoint_kind",
        kv.KnowledgeCheckpointKind,
    ),
}


def _values(source: object) -> tuple[str, ...]:
    if isinstance(source, type) and issubclass(source, StrEnum):
        return tuple(member.value for member in source)
    return tuple(str(value) for value in source)


def _expression(name: str) -> str:
    for table in _contract().values():
        for constraint in table["constraints"]:
            if constraint["name"] == name:
                return str(constraint["expression"])
    raise AssertionError(name)


@pytest.mark.parametrize("name", sorted(CLOSED_SETS))
def test_each_closed_set_literal_equals_the_matrix_and_the_wp01_enum(name: str) -> None:
    """The frozen literal, the matrix and the domain agree, in the matrix's order."""
    column, source = CLOSED_SETS[name]
    expression = _expression(name)
    literal = re.search(rf"{column} (?:IN \(|<@ ARRAY\[)([^)\]]*)[)\]]", expression)
    assert literal, (name, expression)
    frozen = tuple(_LITERAL.findall(literal.group(1)))
    assert set(frozen) == set(_values(source)), name
    assert len(frozen) == len(set(frozen)), name
    flat_revision = _flat(MIGRATION.read_text(encoding="utf-8"))
    assert f"CONSTRAINT {name} CHECK ({_flat(expression)})" in flat_revision, name


def test_every_simple_known_check_is_tied_to_a_domain_vocabulary() -> None:
    """A new `*_is_known`/`*_are_known` closed set cannot land without a domain mirror."""
    named = {
        constraint["name"]
        for table in _contract().values()
        for constraint in table["constraints"]
        if constraint["kind"] == "check" and re.search(r"_(?:is|are)_known$", constraint["name"])
    }
    assert named == set(CLOSED_SETS)


def test_the_subject_and_owner_ref_kinds_bind_their_id_kinds() -> None:
    """AC-108/AC-107: each subject kind and owner ref kind names its IdKind prefix."""
    expression = _expression("knowledge_submission_subject_id_matches_kind")
    pairs = dict(re.findall(r"subject_kind = '(\w+)' AND subject_id ~ '\^(\w+)_", expression))
    assert pairs == {
        "principal": "prn",
        "entity": "ent",
        "project": "prj",
        "managed_document": "mdoc",
        "evidence_ref": "kaevd",
    }
    assert set(pairs) == set(_values(kv.KnowledgeSubjectKind))
    owners = dict(
        re.findall(
            r"owner_ref_kind = '(\w+)' AND owner_ref_id ~ '\^(\w+)_",
            _expression("knowledge_submission_owner_ref_is_typed"),
        )
    )
    assert set(owners) == set(_values(kv.KnowledgeOwnerRefKind))


def test_every_new_identifier_check_uses_a_disjoint_dedicated_prefix() -> None:
    """AC-107: kasr/kamut/kasub/kaprp/kaevd/kadec/kdcp/kdcpr/kdsp, never asrt/sub/prop/..."""
    prefixes = set()
    for table in _contract().values():
        for constraint in table["constraints"]:
            if constraint["kind"] == "check":
                prefixes |= set(
                    re.findall(r"'\^([a-z]+)_\[A-Za-z0-9\]\{8,64\}\$'", constraint["expression"])
                )
    new = {"kasr", "kamut", "kasub", "kaprp", "kaevd", "kadec", "kdcp", "kdcpr", "kdsp"}
    assert new <= prefixes
    assert not prefixes & {"asrt", "sub", "prop", "rdec", "east"}
    assert {kind["prefix"] for kind in _matrix()["id_kinds"]} == new


def test_no_knowledge_column_is_a_numeric_or_banded_confidence() -> None:
    """AC-023: nothing in the schema can carry a confidence that authorizes state."""
    for name, table in _contract().items():
        for column in table["columns"]:
            assert not re.search(r"confidence|score|probability|band", column["name"]), (
                name,
                column["name"],
            )


# ---- FAST: seeds, ALTER literals, the gap table ----------------------------------------

_SEED_COLUMNS: Final = (
    "predicate_code",
    "predicate_version",
    "admission_state",
    "value_type",
    "cardinality",
    "temporal_semantics",
    "qualifier_rule",
    "allowed_subject_kinds",
    "allowed_entity_types",
    "canonical_owner",
    "autonomous_admission_policy",
    "review_requirement",
    "consequential_class",
    "normalization_rule",
    "classification_floor",
    "conflict_rule",
    "minimum_evidence_authority",
    "fingerprint_version",
)


def _sql_value(value: object) -> str:
    if isinstance(value, int):
        return str(value)
    if isinstance(value, list):
        if not value:
            return "'{}'::text[]"
        return "ARRAY[" + ", ".join(f"'{item}'" for item in value) + "]::text[]"
    return f"'{value}'"


def test_the_seeds_are_the_eight_matrix_initial_predicates() -> None:
    """AC-004/AC-098/AC-131: S1-S8, every column but `created_at`, as frozen literals."""
    rows = _matrix()["initial_predicates"]
    assert len(rows) == 8
    assert set(_SEED_COLUMNS) | {"created_at"} == {
        column["name"] for column in _contract()["knowledge_assertion_predicates"]["columns"]
    }
    expected = (
        f"INSERT INTO knowledge.knowledge_assertion_predicates ({', '.join(_SEED_COLUMNS)}) "  # noqa: S608
        "VALUES "
        + ", ".join(
            "(" + ", ".join(_sql_value(row[column]) for column in _SEED_COLUMNS) + ")"
            for row in rows
        )
    )
    assert _flat(_revision()._PREDICATE_SEEDS) == _flat(expected)
    payment_terms = rows[0]
    assert payment_terms["predicate_code"] == "organization.payment_terms"
    assert payment_terms["consequential_class"] == "financial_fact"
    assert payment_terms["autonomous_admission_policy"] == "never"


def _in_literal(expression: str) -> tuple[str, ...]:
    return tuple(_LITERAL.findall(expression))


def _source_literal(path: Path, name: str) -> str:
    """A module-level string constant's value, read without importing `path`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        target = node.target if isinstance(node, ast.AnnAssign) else None
        if isinstance(target, ast.Name) and target.id == name and node.value is not None:
            value = ast.literal_eval(node.value)
            assert isinstance(value, str)
            return value
    raise AssertionError((path.name, name))


def test_the_audit_literals_are_the_matrix_after_literals_and_byte_copied_before() -> None:
    """A1/A2 (AC-021): AT = matrix after-literal; BEFORE = `0641c354ca85`'s AT, byte for byte."""
    revision = _revision()
    alters = _alters()
    previous = VERSIONS / "20261001_0641c354ca85_capture_lifecycle.py"
    for column, at_name, before_name, alter_id in (
        (
            "capability",
            "_CAPABILITIES_AT_THIS_REVISION",
            "_CAPABILITIES_BEFORE_THIS_REVISION",
            "A1",
        ),
        ("purpose", "_PURPOSES_AT_THIS_REVISION", "_PURPOSES_BEFORE_THIS_REVISION", "A2"),
    ):
        at = getattr(revision, at_name)
        before = getattr(revision, before_name)
        assert at.startswith(f"{column} IN (")
        assert _in_literal(at) == tuple(alters[alter_id]["after_literal"])
        assert len(_in_literal(at)) == alters[alter_id]["after_count"]
        assert before == _source_literal(previous, at_name.replace("BEFORE", "AT"))
        assert len(_in_literal(before)) == alters[alter_id]["before_count"]
        assert set(_in_literal(at)) == set(_in_literal(before)) | set(
            alters[alter_id]["added_values"]
        )
        assert _in_literal(at) == tuple(sorted(_in_literal(at)))


def test_the_record_family_and_context_literals_are_the_matrix_literals() -> None:
    """A3/A4/A5 (AC-052): BEFORE literals are the installing revisions' sets; AT add one each."""
    revision = _revision()
    alters = _alters()
    record_source = (VERSIONS / "20260929_1d9b248e7f83_record_events.py").read_text("utf-8")
    declared_families = re.search(
        r"a_record_event_family_is_known CHECK \(record_family IN \((.*?)\)\)",
        record_source,
        re.S,
    )
    assert declared_families
    assert _in_literal(revision._RECORD_FAMILIES_BEFORE_THIS_REVISION) == tuple(
        _LITERAL.findall(declared_families.group(1))
    )
    assert _in_literal(revision._RECORD_FAMILIES_AT_THIS_REVISION) == tuple(
        alters["A3"]["after_literal"]
    )
    context_source = (VERSIONS / "20260815_9b2d5f8c3e01_create_context_run_tables.py").read_text(
        "utf-8"
    )
    for column, before, at, alter_id in (
        (
            "plane",
            revision._CONTEXT_PLANES_BEFORE_THIS_REVISION,
            revision._CONTEXT_PLANES_AT_THIS_REVISION,
            "A4",
        ),
        (
            "authority_class",
            revision._CONTEXT_AUTHORITIES_BEFORE_THIS_REVISION,
            revision._CONTEXT_AUTHORITIES_AT_THIS_REVISION,
            "A5",
        ),
    ):
        inline = re.search(
            rf"\b{column} text NOT NULL\s+CHECK \({column} IN \((.*?)\)\)", context_source, re.S
        )
        assert inline, column
        assert _in_literal(before) == tuple(_LITERAL.findall(inline.group(1)))
        assert _in_literal(before) == tuple(alters[alter_id]["before_literal"])
        assert _in_literal(at) == tuple(alters[alter_id]["after_literal"])
        assert alters[alter_id]["existing_name"] == f"context_run_items_{column}_check"
    assert alters["A4"]["existing_name"] == revision._GENERATED_PLANE_CHECK
    assert alters["A5"]["existing_name"] == revision._GENERATED_AUTHORITY_CHECK
    assert alters["A4"]["new_name"] == revision._DECLARED_PLANE_CHECK
    assert alters["A5"]["new_name"] == revision._DECLARED_AUTHORITY_CHECK
    a6 = (
        _flat(revision._CONTEXT_ITEM_KNOWLEDGE_ASSERTION)
        + " "
        + _flat(revision._CONTEXT_ITEM_KNOWLEDGE_ASSERTION_INDEX)
    )
    for part in alters["A6"]["operation"].split("; "):
        part = part.replace(
            "ADD COLUMN knowledge_assertion_id text NULL", "knowledge_assertion_id text NULL"
        )
        assert _flat(part).replace("ADD CONSTRAINT ", "") in a6.replace(
            "ADD CONSTRAINT ", ""
        ).replace("ADD COLUMN ", ""), part


def test_the_downgrade_refusal_names_exactly_the_new_vocabulary() -> None:
    """AC-078: the refusal is keyed on exactly the added vocabulary and the new tokens."""
    refusal = _flat(_revision()._REFUSE_DOWNGRADE)
    alters = _alters()
    for value in alters["A1"]["added_values"] + alters["A2"]["added_values"]:
        assert f"'{value}'" in refusal, value
    for table in _matrix()["schema_creation_order"][1:]:
        assert f"SELECT 1 FROM knowledge.{table})" in refusal, table  # noqa: S608
    assert "knowledge.knowledge_assertion_predicates" not in refusal
    assert "record_family = 'knowledge_assertion'" in refusal
    assert "plane = 'knowledge_assertion'" in refusal
    assert "authority_class = 'product_owned_knowledge_assertion'" in refusal
    assert "knowledge_assertion_id IS NOT NULL" in refusal
    assert "USING ERRCODE = 'restrict_violation'" in refusal


def test_the_schema_ahead_contract_is_the_matrix_gap_table() -> None:
    """AC-109/AC-132: the one home of the gap rows, at `wp02`, empty at `wp06`."""
    module = _matrix()["schema_ahead_contract_module"]
    assert module["path"] == "tests/schema/knowledge_schema_ahead_contract.py"
    assert contract.KNOWLEDGE_WP_HEAD == "wp02"
    assert set(contract.GAP_ROWS) == set(module["rows"])
    assert (
        tuple(_matrix()["migration_contract"]["schema_ahead_gap_families"]) == contract.GAP_FAMILIES
    )
    for head, row in module["rows"].items():
        assert set(contract.GAP_ROWS[head]) == set(row) == set(contract.GAP_FAMILIES)
        for family, values in row.items():
            assert contract.GAP_ROWS[head][family] == frozenset(values), (head, family)
    assert module["rows"] == _matrix()["schema_ahead_gap_ledger"]
    assert all(not values for values in contract.GAP_ROWS["wp06"].values())
    alters = _alters()
    row = contract.current_gap()
    assert row["capability"] == frozenset(alters["A1"]["added_values"])
    assert row["purpose"] == frozenset(alters["A2"]["added_values"])
    assert row["record_event_family"] == frozenset(alters["A3"]["added_values"])
    assert row["context_plane"] == frozenset(alters["A4"]["added_values"])
    assert row["source_authority_class"] == frozenset(alters["A5"]["added_values"])
    source = (ROOT / module["path"]).read_text(encoding="utf-8")
    assert re.search(r'^KNOWLEDGE_WP_HEAD: Final\[KnowledgeWpHead\] = "wp02"$', source, re.M)
    assert 'KnowledgeWpHead = Literal["wp02", "wp03", "wp04", "wp05", "wp06"]' in source


# ---- FAST: tables.py declares the same schema -------------------------------------------

_DECLARED_TYPES: Final = {
    "text": "TEXT",
    "integer": "INTEGER",
    "smallint": "SMALLINT",
    "boolean": "BOOLEAN",
    "timestamptz": "TIMESTAMP WITH TIME ZONE",
    "jsonb": "JSONB",
    "text[]": "TEXT[]",
}


@pytest.mark.parametrize("name", list(_matrix()["schema_creation_order"]))
def test_tables_py_declares_the_matrix_table(name: str) -> None:
    """Identical names, columns, types, nullability, defaults, constraints and indexes."""
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.sql.schema import (
        CheckConstraint,
        ForeignKeyConstraint,
        PrimaryKeyConstraint,
        UniqueConstraint,
    )

    table: Table = declared.METADATA.tables[f"{SCHEMA}.{name}"]
    expected = _contract()[name]
    dialect = postgresql.dialect()
    assert [column.name for column in table.c] == [c["name"] for c in expected["columns"]]
    for column, spec in zip(table.c, expected["columns"], strict=True):
        assert column.type.compile(dialect=dialect) == _DECLARED_TYPES[spec["type"]], column.name
        assert column.nullable is spec["nullable"], column.name
        default = column.server_default
        if spec["default"] is None:
            assert default is None, column.name
        else:
            assert default is not None
            assert str(getattr(default, "arg", default)) == spec["default"], column.name
    kinds = {
        PrimaryKeyConstraint: "primary_key",
        UniqueConstraint: "unique",
        CheckConstraint: "check",
        ForeignKeyConstraint: "foreign_key",
    }
    found: dict[str, tuple[str, object]] = {}
    for constraint in table.constraints:
        kind = kinds[type(constraint)]
        if kind == "check":
            assert isinstance(constraint, CheckConstraint)
            found[str(constraint.name)] = (kind, _flat(str(constraint.sqltext)))
        elif kind == "foreign_key":
            assert isinstance(constraint, ForeignKeyConstraint)
            assert constraint.ondelete == "RESTRICT" and constraint.deferrable is False
            found[str(constraint.name)] = (
                kind,
                (
                    tuple(constraint.column_keys),
                    tuple(element.target_fullname for element in constraint.elements),
                    bool(constraint.use_alter),
                ),
            )
        else:
            found[str(constraint.name)] = (kind, tuple(c.name for c in constraint.columns))
    wanted: dict[str, tuple[str, object]] = {}
    for spec in expected["constraints"]:
        if spec["kind"] == "check":
            wanted[spec["name"]] = ("check", _flat(spec["expression"]))
        elif spec["kind"] == "foreign_key":
            wanted[spec["name"]] = (
                "foreign_key",
                (
                    tuple(spec["columns"]),
                    tuple(
                        f"{SCHEMA}.{spec['references_table']}.{column}"
                        for column in spec["references_columns"]
                    ),
                    bool(spec["added_after_all_tables"]),
                ),
            )
        else:
            wanted[spec["name"]] = (spec["kind"], tuple(spec["columns"]))
    assert found == wanted
    indexes = {
        str(index.name): (
            bool(index.unique),
            tuple(
                str(element) if not hasattr(element, "name") else element.name
                for element in index.expressions
            ),
            str(index.dialect_options["postgresql"]["where"])
            if index.dialect_options["postgresql"]["where"] is not None
            else None,
        )
        for index in table.indexes
    }
    assert indexes == {
        spec["name"]: (
            spec["unique"],
            tuple(column[1:-1] if column.startswith("(") else column for column in spec["columns"]),
            spec["where"],
        )
        for spec in expected["indexes"]
    }


def test_tables_py_declares_the_context_item_knowledge_assertion_identity() -> None:
    """A6 in the live declaration; the plane/authority CHECKs stay enum-derived (gap)."""
    items = declared.context_run_items
    assert "knowledge_assertion_id" in items.c
    assert items.c.knowledge_assertion_id.nullable
    checks = {
        str(constraint.name): _flat(str(getattr(constraint, "sqltext", "")))
        for constraint in items.constraints
    }
    assert checks["context_run_item_knowledge_assertion_is_opaque"] == (
        "knowledge_assertion_id IS NULL OR knowledge_assertion_id ~ '^kasr_[A-Za-z0-9]{8,64}$'"
    )
    a6 = _flat(_revision()._CONTEXT_ITEM_KNOWLEDGE_ASSERTION)
    assert f"CHECK ({checks['context_run_item_knowledge_assertion_identity']})" in a6
    assert "context_run_items_by_knowledge_assertion" in {index.name for index in items.indexes}
    plane = set(_LITERAL.findall(checks["context_run_item_plane_is_known"]))
    authority = set(_LITERAL.findall(checks["context_run_item_authority_is_known"]))
    row = contract.current_gap()
    assert plane | row["context_plane"] == set(_alters()["A4"]["after_literal"])
    assert authority | row["source_authority_class"] == set(_alters()["A5"]["after_literal"])
    assert not plane & row["context_plane"]
    assert "a_memory_is_identified_within_its_principal" not in {
        str(constraint.name) for constraint in declared.relationship_memories.constraints
    }


# ---- FAST: offline SQL -----------------------------------------------------------------


def _offline(target: str, *, down: bool = False) -> str:
    buffer = io.StringIO()
    action = command.downgrade if down else command.upgrade
    action(_config(buffer), target, sql=True)
    return _flat(buffer.getvalue())


def test_the_offline_upgrade_follows_the_r6_upgrade_order() -> None:
    """R6 11.4: functions, A7, tables, deferred keys, triggers, seeds, A1-A6."""
    rendered = _offline(f"{PREVIOUS}:{REVISION}")
    order = [
        "CREATE FUNCTION knowledge.knowledge_classification_rank(",
        "CREATE FUNCTION knowledge.knowledge_row_is_append_only()",
        "ADD CONSTRAINT a_memory_is_identified_within_its_principal UNIQUE "
        "(memory_id, principal_id)",
        *(f"CREATE TABLE knowledge.{table} (" for table in _matrix()["schema_creation_order"]),
        "ADD CONSTRAINT knowledge_submission_result_assertion_is_owned",
        "ADD CONSTRAINT knowledge_submission_result_proposal_case_pair",
        "CREATE FUNCTION knowledge.knowledge_predicate_structure_guard()",
        "CREATE FUNCTION knowledge.knowledge_checkpoint_request_reserved_at_commit()",
        "CREATE TRIGGER knowledge_predicate_is_insert_only",
        "CREATE CONSTRAINT TRIGGER knowledge_checkpoint_request_is_never_left_reserved",
        "INSERT INTO knowledge.knowledge_assertion_predicates",
        "ADD CONSTRAINT capability_is_known CHECK",
        "ADD CONSTRAINT purpose_is_known CHECK",
        "ADD CONSTRAINT a_record_event_family_is_known CHECK",
        "DROP CONSTRAINT context_run_items_plane_check, ADD CONSTRAINT "
        "context_run_item_plane_is_known",
        "DROP CONSTRAINT context_run_items_authority_class_check, ADD CONSTRAINT "
        "context_run_item_authority_is_known",
        "ADD COLUMN knowledge_assertion_id text NULL",
        "CREATE INDEX context_run_items_by_knowledge_assertion",
        f"SET version_num='{REVISION}'",
    ]
    positions = [rendered.index(marker) for marker in order]
    assert positions == sorted(positions)


def test_the_offline_downgrade_refuses_first_and_unwinds_in_reverse() -> None:
    """R6 11.7: refusal, A6..A1, triggers, functions, deferred keys, tables, A7, functions."""
    rendered = _offline(f"{REVISION}:{PREVIOUS}", down=True)
    order = [
        "refusing to downgrade 6734f039f7a6",
        "DROP INDEX knowledge.context_run_items_by_knowledge_assertion",
        "DROP COLUMN knowledge_assertion_id",
        "DROP CONSTRAINT context_run_item_authority_is_known, ADD CONSTRAINT "
        "context_run_items_authority_class_check",
        "DROP CONSTRAINT context_run_item_plane_is_known, ADD CONSTRAINT "
        "context_run_items_plane_check",
        "ADD CONSTRAINT a_record_event_family_is_known CHECK",
        "ADD CONSTRAINT capability_is_known CHECK",
        "DROP TRIGGER knowledge_checkpoint_request_is_never_left_reserved",
        "DROP TRIGGER knowledge_predicate_is_insert_only",
        "DROP FUNCTION knowledge.knowledge_checkpoint_request_reserved_at_commit()",
        "DROP FUNCTION knowledge.knowledge_predicate_structure_guard()",
        "DROP CONSTRAINT knowledge_submission_result_proposal_case_pair",
        "DROP CONSTRAINT knowledge_submission_result_assertion_is_owned",
        *(
            f"DROP TABLE knowledge.{table} RESTRICT"
            for table in reversed(_matrix()["schema_creation_order"])
        ),
        "DROP CONSTRAINT a_memory_is_identified_within_its_principal",
        "DROP FUNCTION knowledge.knowledge_row_is_append_only()",
        "DROP FUNCTION knowledge.knowledge_classification_rank(text)",
        f"SET version_num='{PREVIOUS}'",
    ]
    positions = [rendered.index(marker) for marker in order]
    assert positions == sorted(positions)
    assert "DELETE FROM" not in rendered.upper().replace("ON DELETE", "")


# =========================================================================================
# Migration edge: disposable databases
# =========================================================================================

PRINCIPAL: Final = "prn_kwp02principal1"
OTHER_PRINCIPAL: Final = "prn_kwp02principal2"
ENTITY: Final = "ent_kwp02entity0001"
ENTITY_TWO: Final = "ent_kwp02entity0002"
PROFILE: Final = "kdsp_kwp02profile01"
SUBMISSION: Final = "kasub_kwp02sub00001"
EVIDENCE: Final = "kaevd_kwp02evid0001"
PROPOSAL: Final = "kaprp_kwp02prop0001"
CASE: Final = "rvw_kwp02case00001"
DECISION: Final = "kadec_kwp02dec00001"
ASSERTION: Final = "kasr_kwp02asrt00001"
MUTATION: Final = "kamut_kwp02mut00001"
EVENT: Final = "rcev_kwp02event0001"
MANIFEST: Final = "ctxm_kwp02manifest1"
CLIENT: Final = "client-kwp02"
PAYMENT_TERMS: Final = "organization.payment_terms"
NOW: Final = datetime(2026, 10, 4, 12, tzinfo=UTC)
EARLIER: Final = NOW - timedelta(days=1)
LATER: Final = NOW + timedelta(days=1)
DIGEST: Final = "a" * 64


def _t(name: str) -> Table:
    return declared.METADATA.tables[f"{SCHEMA}.{name}"]


#: The parent graph every prove-red case stands on, in insert order.
GRAPH: Final[tuple[tuple[str, dict[str, Any]], ...]] = (
    (
        "knowledge_discovery_source_profiles",
        {
            "principal_id": PRINCIPAL,
            "source_profile_id": PROFILE,
            "authenticated_client_id": CLIENT,
            "origin_system": "outlook_mail",
            "scope_digest": DIGEST,
            "authority_ceiling": "authoritative_source",
            "direct_admission_enabled": False,
            "read_only_proof_state": "unproven",
            "is_synthetic": False,
            "profile_version": 1,
            "created_at": NOW,
            "updated_at": NOW,
        },
    ),
    (
        "knowledge_assertion_submissions",
        {
            "principal_id": PRINCIPAL,
            "submission_id": SUBMISSION,
            "origin": "explicit_create",
            "idempotency_key": "kwp02-key-1",
            "origin_is_synthetic": False,
            "subject_kind": "entity",
            "subject_id": ENTITY,
            "predicate_code": PAYMENT_TERMS,
            "request_digest": "b" * 64,
            "submission_state": "completed",
            "causal_depth": 0,
            "causal_root_submission_id": SUBMISSION,
            "outcome": "refused",
            "reason": "source_profile_inactive",
            "result_canonical_owner": "knowledge_assertion",
            "result_digest": "c" * 64,
            "created_at": NOW,
            "completed_at": NOW,
        },
    ),
    (
        "knowledge_evidence_refs",
        {
            "principal_id": PRINCIPAL,
            "evidence_ref_id": EVIDENCE,
            "identity_kind": "external_object",
            "source_profile_id": PROFILE,
            "source_is_synthetic": False,
            "external_object_id": "obj-kwp02-1",
            "content_hash": "c" * 64,
            "excerpt": "Net 30 days.",
            "excerpt_sha256": "d" * 64,
            "content_origin": "external_source",
            "source_classification": "private_local",
            "created_at": NOW,
            "updated_at": NOW,
        },
    ),
    (
        "knowledge_assertion_proposals",
        {
            "principal_id": PRINCIPAL,
            "proposal_id": PROPOSAL,
            "review_case_id": CASE,
            "origin_submission_id": SUBMISSION,
            "origin_is_synthetic": False,
            "subject_kind": "entity",
            "subject_id": ENTITY,
            "predicate_code": PAYMENT_TERMS,
            "predicate_version": 1,
            "value_type": "text",
            "cardinality": "single_current",
            "temporal_semantics": "observed_state",
            "qualifier_rule": "none",
            "value_text": "Net 30",
            "normalized_value_sha256": "e" * 64,
            "fingerprint_version": 1,
            "proposal_fingerprint": "f" * 64,
            "classification": "private_local",
            "risk_class": "high",
            "review_requirement": "requires_operator",
            "state": "needs_review",
            "created_at": NOW,
            "updated_at": NOW,
        },
    ),
    (
        "knowledge_assertion_review_decisions",
        {
            "principal_id": PRINCIPAL,
            "decision_id": DECISION,
            "review_case_id": CASE,
            "proposal_id": PROPOSAL,
            "review_requirement": "requires_operator",
            "decision_sequence": 1,
            "disposition": "defer",
            "decision_channel": "local_cli",
            "operator_authority_class": "local_operator",
            "correlation_id": "corr_kwp02corr0001",
            "audit_id": "audit_kwp02audit001",
            "created_at": NOW,
        },
    ),
    (
        "knowledge_assertions",
        {
            "principal_id": PRINCIPAL,
            "assertion_id": ASSERTION,
            "subject_kind": "entity",
            "subject_id": ENTITY,
            "predicate_code": PAYMENT_TERMS,
            "predicate_version": 1,
            "value_type": "text",
            "cardinality": "single_current",
            "temporal_semantics": "observed_state",
            "qualifier_rule": "none",
            "value_text": "Net 30",
            "normalized_value_sha256": "e" * 64,
            "fingerprint_version": 1,
            "assertion_fingerprint": "f" * 64,
            "epistemic_status": "principal_asserted",
            "classification": "private_local",
            "origin_is_synthetic": False,
            "lifecycle": "active",
            "version": 1,
            "origin_submission_id": SUBMISSION,
            "created_at": NOW,
            "updated_at": NOW,
        },
    ),
    (
        "knowledge_assertion_mutations",
        {
            "principal_id": PRINCIPAL,
            "mutation_id": MUTATION,
            "assertion_id": ASSERTION,
            "mutation_kind": "create",
            "prior_version": 0,
            "new_version": 1,
            "submission_id": SUBMISSION,
            "created_at": NOW,
        },
    ),
    (
        "record_events",
        {
            "event_id": EVENT,
            "principal_id": PRINCIPAL,
            "sequence_number": 1,
            "record_family": "knowledge_assertion",
            "record_id": ASSERTION,
            "event_kind": "created",
            "record_version": 1,
            "changed_fields": [],
            "source_capability": "knowledge.assertions.create",
            "actor_class": "principal",
            "classification": "private_local",
            "occurred_at": NOW,
        },
    ),
    (
        "context_runs",
        {
            "context_manifest_id": MANIFEST,
            "principal_id": PRINCIPAL,
            "request_id": "kwp02-request-1",
            "correlation_id": "corr_kwp02corr0002",
            "transport": "local",
            "purpose": "context_preparation",
            "query_fingerprint": DIGEST,
            "retrieval_mode": "lexical_structured",
            "ranking_version": "rank-v1",
            "policy_version": "policy-v1",
            "generated_at": NOW,
            "total_items": 1,
            "total_bytes": 1,
            "outcome": "success",
            "truncated": False,
        },
    ),
)

#: A valid row per table, distinct from the graph, used by the control and by every
#: CHECK case (each case overrides the fewest columns that violate its target).
BASE: Final[dict[str, dict[str, Any]]] = {
    "knowledge_assertion_predicates": {
        "predicate_code": "zz.case",
        "predicate_version": 1,
        "admission_state": "active",
        "value_type": "text",
        "cardinality": "single_current",
        "temporal_semantics": "observed_state",
        "qualifier_rule": "none",
        "allowed_subject_kinds": ["entity"],
        "allowed_entity_types": ["organization"],
        "canonical_owner": "knowledge_assertion",
        "autonomous_admission_policy": "never",
        "review_requirement": "requires_operator",
        "consequential_class": "financial_fact",
        "normalization_rule": "text_nfc_trim_collapse_whitespace",
        "classification_floor": "private_local",
        "conflict_rule": "review_on_difference",
        "minimum_evidence_authority": "observed_source",
        "fingerprint_version": 1,
    },
    "knowledge_discovery_source_profiles": {
        **dict(GRAPH[0][1]),
        "source_profile_id": "kdsp_kwp02profile02",
        "origin_system": "sharepoint_documents",
        "scope_digest": "b" * 64,
        "authority_ceiling": "observed_source",
    },
    "knowledge_assertion_submissions": {
        "principal_id": PRINCIPAL,
        "submission_id": "kasub_kwp02sub00002",
        "origin": "explicit_create",
        "idempotency_key": "kwp02-key-2",
        "origin_is_synthetic": False,
        "subject_kind": "entity",
        "subject_id": ENTITY_TWO,
        "predicate_code": PAYMENT_TERMS,
        "request_digest": "b" * 64,
        "submission_state": "reserved",
        "causal_depth": 0,
        "causal_root_submission_id": "kasub_kwp02sub00002",
        "created_at": NOW,
    },
    "knowledge_evidence_refs": {
        **dict(GRAPH[2][1]),
        "evidence_ref_id": "kaevd_kwp02evid0002",
        "external_object_id": "obj-kwp02-2",
    },
    "knowledge_assertion_subject_locks": {
        "principal_id": PRINCIPAL,
        "subject_kind": "entity",
        "subject_id": ENTITY_TWO,
        "predicate_code": PAYMENT_TERMS,
    },
    "knowledge_assertion_proposals": {
        **dict(GRAPH[3][1]),
        "proposal_id": "kaprp_kwp02prop0002",
        "review_case_id": "rvw_kwp02case00002",
        "subject_id": ENTITY_TWO,
        "proposal_fingerprint": "1" * 64,
    },
    "knowledge_assertion_review_decisions": {
        **dict(GRAPH[4][1]),
        "decision_id": "kadec_kwp02dec00002",
        "decision_sequence": 2,
    },
    "knowledge_assertions": {
        **dict(GRAPH[5][1]),
        "assertion_id": "kasr_kwp02asrt00002",
        "subject_id": ENTITY_TWO,
        "assertion_fingerprint": "2" * 64,
    },
    "knowledge_assertion_mutations": {
        "principal_id": PRINCIPAL,
        "mutation_id": "kamut_kwp02mut00002",
        "assertion_id": ASSERTION,
        "mutation_kind": "classify",
        "prior_version": 1,
        "new_version": 2,
        "created_at": NOW,
    },
    "knowledge_assertion_evidence_links": {
        "principal_id": PRINCIPAL,
        "assertion_id": ASSERTION,
        "evidence_ref_id": EVIDENCE,
        "evidence_role": "direct",
        "linked_by_mutation_id": MUTATION,
        "created_at": NOW,
    },
    "knowledge_submission_evidence": {
        "principal_id": PRINCIPAL,
        "submission_id": SUBMISSION,
        "evidence_ref_id": EVIDENCE,
        "evidence_role": "direct",
        "created_at": NOW,
    },
    "knowledge_submission_trigger_events": {
        "principal_id": PRINCIPAL,
        "submission_id": SUBMISSION,
        "trigger_event_id": EVENT,
        "created_at": NOW,
    },
    "knowledge_discovery_checkpoints": {
        "principal_id": PRINCIPAL,
        "checkpoint_id": "kdcp_kwp02checkpt01",
        "source_profile_id": PROFILE,
        "authenticated_client_id": CLIENT,
        "scope_digest": DIGEST,
        "version": 1,
        "checkpoint_kind": "delta_token",
        "private_envelope": "opaque-envelope",
        "seal_version": 1,
        "envelope_mac": "9" * 64,
        "external_run_id": "run-kwp02-1",
        "created_at": NOW,
        "updated_at": NOW,
    },
    "knowledge_discovery_checkpoint_requests": {
        "principal_id": PRINCIPAL,
        "checkpoint_request_id": "kdcpr_kwp02request1",
        "authenticated_client_id": CLIENT,
        "source_profile_id": PROFILE,
        "scope_digest": DIGEST,
        "external_run_id": "run-kwp02-1",
        "submitted_candidate_count": 0,
        "expected_version": 0,
        "idempotency_key": "kwp02-checkpoint-1",
        "request_digest": "8" * 64,
        "state": "reserved",
        "private_token_redacted": False,
        "created_at": NOW,
    },
    "context_run_items": {
        "context_manifest_id": MANIFEST,
        "position": 0,
        "principal_id": PRINCIPAL,
        "reference_id": "kwp02-ref-1",
        "plane": "knowledge_assertion",
        "authority_class": "product_owned_knowledge_assertion",
        "lifecycle": "accepted",
        "classification": "private_local",
        "excerpt_sha256": DIGEST,
        "reason_codes": "",
        "knowledge_assertion_id": ASSERTION,
    },
}

_P = "knowledge_assertion_predicates"
_PR = "knowledge_discovery_source_profiles"
_S = "knowledge_assertion_submissions"
_E = "knowledge_evidence_refs"
_L = "knowledge_assertion_subject_locks"
_PP = "knowledge_assertion_proposals"
_D = "knowledge_assertion_review_decisions"
_A = "knowledge_assertions"
_M = "knowledge_assertion_mutations"
_EL = "knowledge_assertion_evidence_links"
_SE = "knowledge_submission_evidence"
_TE = "knowledge_submission_trigger_events"
_C = "knowledge_discovery_checkpoints"
_R = "knowledge_discovery_checkpoint_requests"
_CI = "context_run_items"
_CAPTURE_SHAPE: Final = {
    "identity_kind": "capture",
    "capture_id": "cap_kwp02capture01",
    "source_profile_id": None,
    "source_is_synthetic": None,
    "external_object_id": None,
    "content_origin": "capture",
}

#: Every named CHECK of the fourteen tables (and A4-A6 on `context_run_items`), with the
#: minimal override of its table's BASE row that violates it. Each case runs with every
#: *other* CHECK of the table dropped and the table's user triggers disabled, inside a
#: rolled-back savepoint, so a red result is that one constraint and nothing else.
CHECK_CASES: Final[dict[str, tuple[str, dict[str, Any]]]] = {
    "knowledge_predicate_code_is_bounded": (_P, {"predicate_code": "Zz.case"}),
    "knowledge_predicate_version_is_positive": (_P, {"predicate_version": 0}),
    "knowledge_predicate_admission_state_is_known": (_P, {"admission_state": "paused"}),
    "knowledge_predicate_value_type_is_known": (_P, {"value_type": "number"}),
    "knowledge_predicate_cardinality_is_known": (_P, {"cardinality": "many"}),
    "knowledge_predicate_temporal_semantics_is_known": (_P, {"temporal_semantics": "eternal"}),
    "knowledge_predicate_qualifier_rule_is_known": (_P, {"qualifier_rule": "unit"}),
    "knowledge_predicate_subject_kinds_are_known": (
        _P,
        {"allowed_subject_kinds": ["entity", "task"]},
    ),
    "knowledge_predicate_entity_types_are_known": (_P, {"allowed_entity_types": ["team"]}),
    "knowledge_predicate_entity_types_follow_subjects": (_P, {"allowed_entity_types": []}),
    "knowledge_predicate_canonical_owner_is_known": (_P, {"canonical_owner": "documents"}),
    "knowledge_predicate_admission_policy_is_known": (
        _P,
        {"autonomous_admission_policy": "always"},
    ),
    "knowledge_predicate_review_requirement_is_known": (_P, {"review_requirement": "none"}),
    "knowledge_predicate_consequential_class_is_known": (_P, {"consequential_class": "legal"}),
    "knowledge_predicate_normalization_rule_is_known": (_P, {"normalization_rule": "raw"}),
    "knowledge_predicate_classification_floor_is_known": (
        _P,
        {"classification_floor": "synthetic_test"},
    ),
    "knowledge_predicate_conflict_rule_is_known": (_P, {"conflict_rule": "last_wins"}),
    "knowledge_predicate_minimum_authority_is_known": (
        _P,
        {"minimum_evidence_authority": "hearsay"},
    ),
    "knowledge_predicate_fingerprint_version_is_one": (_P, {"fingerprint_version": 2}),
    "knowledge_predicate_single_current_is_unqualified_state": (
        _P,
        {"temporal_semantics": "historical"},
    ),
    "knowledge_predicate_conflict_rule_follows_cardinality": (_P, {"conflict_rule": "coexist"}),
    "knowledge_predicate_normalization_follows_value_type": (
        _P,
        {"normalization_rule": "datetime_utc_microsecond"},
    ),
    "knowledge_predicate_date_kind_is_datetime": (_P, {"qualifier_rule": "date_kind"}),
    "knowledge_predicate_consequential_never_direct_admits": (
        _P,
        {"autonomous_admission_policy": "authoritative_source"},
    ),
    "knowledge_predicate_domain_owned_never_direct_admits": (
        _P,
        {
            "canonical_owner": "relationship_memory",
            "consequential_class": "none",
            "autonomous_admission_policy": "authoritative_source",
        },
    ),
    "knowledge_profile_principal_is_opaque": (_PR, {"principal_id": "principal-1"}),
    "knowledge_profile_id_is_opaque": (_PR, {"source_profile_id": "kdsp_short"}),
    "knowledge_profile_client_is_bounded": (_PR, {"authenticated_client_id": ""}),
    "knowledge_profile_origin_system_is_known": (_PR, {"origin_system": "gmail"}),
    "knowledge_profile_scope_digest_is_sha256": (_PR, {"scope_digest": "ABC"}),
    "knowledge_profile_authority_ceiling_is_known": (_PR, {"authority_ceiling": "absolute"}),
    "knowledge_profile_proof_state_is_known": (_PR, {"read_only_proof_state": "maybe"}),
    "knowledge_profile_synthetic_follows_origin": (_PR, {"is_synthetic": True}),
    "knowledge_profile_direct_admission_needs_proof": (_PR, {"direct_admission_enabled": True}),
    "knowledge_profile_version_is_positive": (_PR, {"profile_version": 0}),
    "knowledge_profile_is_not_updated_before_created": (_PR, {"updated_at": EARLIER}),
    "knowledge_submission_principal_is_opaque": (_S, {"principal_id": "prn_!"}),
    "knowledge_submission_id_is_opaque": (_S, {"submission_id": "sub_kwp02sub00002"}),
    "knowledge_submission_origin_is_known": (_S, {"origin": "import"}),
    "knowledge_submission_client_is_bounded": (_S, {"authenticated_client_id": "x" * 257}),
    "knowledge_submission_key_is_bounded": (_S, {"idempotency_key": "k" * 129}),
    "knowledge_submission_profile_is_opaque": (_S, {"source_profile_id": "profile"}),
    "knowledge_submission_scope_digest_is_sha256": (_S, {"scope_digest": "z"}),
    "knowledge_submission_run_ids_are_bounded": (_S, {"external_run_id": ""}),
    "knowledge_submission_origin_shape": (_S, {"idempotency_key": None}),
    "knowledge_submission_subject_kind_is_known": (_S, {"subject_kind": "task"}),
    "knowledge_submission_subject_id_matches_kind": (_S, {"subject_id": "prj_kwp02project01"}),
    "knowledge_submission_predicate_code_is_bounded": (_S, {"predicate_code": "PAYMENT"}),
    "knowledge_submission_owner_ref_is_typed": (
        _S,
        {"owner_ref_kind": "task", "owner_ref_id": "cmt_kwp02commit001"},
    ),
    "knowledge_submission_request_digest_is_sha256": (_S, {"request_digest": "0"}),
    "knowledge_submission_state_is_known": (_S, {"submission_state": "pending"}),
    "knowledge_submission_depth_is_bounded": (_S, {"causal_depth": 5}),
    "knowledge_submission_root_is_opaque": (_S, {"causal_root_submission_id": "root"}),
    "knowledge_submission_causal_shape": (_S, {"causal_depth": None}),
    "knowledge_submission_root_is_self_at_depth_zero": (
        _S,
        {"causal_root_submission_id": SUBMISSION},
    ),
    "knowledge_submission_explicit_create_is_a_root": (
        _S,
        {"causal_depth": 1, "causal_root_submission_id": SUBMISSION},
    ),
    "knowledge_submission_outcome_is_known": (_S, {"outcome": "maybe"}),
    "knowledge_submission_reason_is_known": (_S, {"reason": "idempotency_conflict"}),
    "knowledge_submission_reason_matches_outcome": (
        _S,
        {"outcome": "direct_created", "reason": "superseded"},
    ),
    "knowledge_submission_result_assertion_is_opaque": (_S, {"result_assertion_id": "asrt_1"}),
    "knowledge_submission_result_version_is_positive": (_S, {"result_assertion_version": 0}),
    "knowledge_submission_result_mutation_is_opaque": (_S, {"result_mutation_id": "m"}),
    "knowledge_submission_result_superseded_is_opaque": (
        _S,
        {"result_superseded_assertion_id": "s"},
    ),
    "knowledge_submission_result_proposal_is_opaque": (_S, {"result_proposal_id": "prop_x"}),
    "knowledge_submission_result_case_is_opaque": (_S, {"result_review_case_id": "case"}),
    "knowledge_submission_result_owner_is_known": (_S, {"result_canonical_owner": "nobody"}),
    "knowledge_submission_routed_record_is_opaque": (_S, {"result_routed_record_id": "Bad_1"}),
    "knowledge_submission_result_digest_is_sha256": (_S, {"result_digest": "x"}),
    "knowledge_submission_reserved_has_no_result": (_S, {"outcome": "refused"}),
    "knowledge_submission_completed_has_outcome": (_S, {"submission_state": "completed"}),
    "knowledge_submission_result_matches_outcome": (_S, {"outcome": "direct_created"}),
    "knowledge_evidence_ref_principal_is_opaque": (_E, {"principal_id": "p"}),
    "knowledge_evidence_ref_id_is_opaque": (_E, {"evidence_ref_id": "evd_kwp02evid0002"}),
    "knowledge_evidence_ref_identity_kind_is_known": (_E, {"identity_kind": "url"}),
    "knowledge_evidence_ref_profile_is_opaque": (_E, {"source_profile_id": "profile"}),
    "knowledge_evidence_ref_capture_is_opaque": (_E, {"capture_id": "capture-1"}),
    "knowledge_evidence_ref_memory_is_opaque": (_E, {"relationship_memory_id": "memory-1"}),
    "knowledge_evidence_ref_external_ids_are_bounded": (
        _E,
        {"external_object_id": "line\nbreak"},
    ),
    "knowledge_evidence_ref_content_hash_is_sha256": (_E, {"content_hash": "C" * 64}),
    "knowledge_evidence_ref_excerpt_is_bounded": (_E, {"excerpt": "x" * 2049}),
    "knowledge_evidence_ref_excerpt_digest_is_sha256": (_E, {"excerpt_sha256": "nope"}),
    "knowledge_evidence_ref_excerpt_has_digest": (_E, {"excerpt_sha256": None}),
    "knowledge_evidence_ref_content_origin_is_known": (_E, {"content_origin": "rumour"}),
    "knowledge_evidence_ref_classification_is_known": (_E, {"source_classification": "public"}),
    "knowledge_evidence_ref_availability_is_known": (_E, {"availability_state": "gone"}),
    "knowledge_evidence_ref_has_one_identity_shape": (
        _E,
        {"capture_id": "cap_kwp02capture01"},
    ),
    "knowledge_evidence_ref_synthetic_origin_follows_profile": (
        _E,
        {"content_origin": "synthetic_source"},
    ),
    "knowledge_evidence_ref_synthetic_class_needs_synthetic_source": (
        _E,
        {"source_classification": "synthetic_test"},
    ),
    "knowledge_evidence_ref_restricted_has_no_excerpt": (
        _E,
        {"source_classification": "restricted_local"},
    ),
    "knowledge_evidence_ref_product_shapes_store_no_availability": (
        _E,
        {**_CAPTURE_SHAPE, "availability_state": "deleted"},
    ),
    "knowledge_evidence_ref_is_not_updated_before_created": (_E, {"updated_at": EARLIER}),
    "knowledge_subject_lock_principal_is_opaque": (_L, {"principal_id": "p"}),
    "knowledge_subject_lock_subject_kind_is_known": (_L, {"subject_kind": "task"}),
    "knowledge_subject_lock_subject_id_matches_kind": (_L, {"subject_id": PRINCIPAL}),
    "knowledge_subject_lock_predicate_code_is_bounded": (_L, {"predicate_code": "x"}),
    "knowledge_proposal_principal_is_opaque": (_PP, {"principal_id": "p"}),
    "knowledge_proposal_id_is_opaque": (_PP, {"proposal_id": "prop_kwp02prop0002"}),
    "knowledge_proposal_case_is_opaque": (_PP, {"review_case_id": "case"}),
    "knowledge_proposal_origin_is_opaque": (_PP, {"origin_submission_id": "sub"}),
    "knowledge_proposal_subject_kind_is_known": (_PP, {"subject_kind": "task"}),
    "knowledge_proposal_subject_id_matches_kind": (_PP, {"subject_id": "x"}),
    "knowledge_proposal_value_follows_type": (_PP, {"value_text": None}),
    "knowledge_proposal_text_is_bounded": (_PP, {"value_text": "x" * 4001}),
    "knowledge_proposal_qualifier_follows_rule": (
        _PP,
        {"qualifier_json": {"date_kind": "deadline"}},
    ),
    "knowledge_proposal_interval_is_ordered": (
        _PP,
        {"effective_from": NOW, "effective_to": EARLIER},
    ),
    "knowledge_proposal_value_digest_is_sha256": (_PP, {"normalized_value_sha256": "x"}),
    "knowledge_proposal_fingerprint_version_is_one": (_PP, {"fingerprint_version": 2}),
    "knowledge_proposal_fingerprint_is_sha256": (_PP, {"proposal_fingerprint": "x"}),
    "knowledge_proposal_classification_is_known": (_PP, {"classification": "public"}),
    "knowledge_proposal_synthetic_needs_synthetic_origin": (
        _PP,
        {"classification": "synthetic_test"},
    ),
    "knowledge_proposal_risk_class_is_known": (_PP, {"risk_class": "extreme"}),
    "knowledge_proposal_review_requirement_is_known": (_PP, {"review_requirement": "none"}),
    "knowledge_proposal_state_is_known": (_PP, {"state": "open"}),
    "knowledge_proposal_is_not_updated_before_created": (_PP, {"updated_at": EARLIER}),
    "knowledge_decision_principal_is_opaque": (_D, {"principal_id": "p"}),
    "knowledge_decision_id_is_opaque": (_D, {"decision_id": "dec"}),
    "knowledge_decision_case_is_opaque": (_D, {"review_case_id": "c"}),
    "knowledge_decision_proposal_is_opaque": (_D, {"proposal_id": "p"}),
    "knowledge_decision_requirement_is_known": (_D, {"review_requirement": "x"}),
    "knowledge_decision_sequence_is_positive": (_D, {"decision_sequence": 0}),
    "knowledge_decision_disposition_is_known": (_D, {"disposition": "approve"}),
    "knowledge_decision_reason_is_bounded": (_D, {"reason": ""}),
    "knowledge_decision_patch_follows_disposition": (
        _D,
        {"correction_patch": {"value_text": "x"}},
    ),
    "knowledge_decision_client_is_bounded": (_D, {"authenticated_client_id": ""}),
    "knowledge_decision_channel_is_known": (_D, {"decision_channel": "email"}),
    "knowledge_decision_authority_class_is_known": (_D, {"operator_authority_class": "admin"}),
    "knowledge_decision_channel_matches_authority": (
        _D,
        {"decision_channel": "remote_interactive"},
    ),
    "knowledge_decision_operator_rule_holds": (
        _D,
        {
            "disposition": "accept",
            "operator_authority_class": "ordinary_reviewer",
            "decision_channel": "local_unattested",
        },
    ),
    "knowledge_decision_feedback_ref_is_sha256": (_D, {"external_feedback_ref_hash": "x"}),
    "knowledge_decision_correlation_is_opaque": (_D, {"correlation_id": "c"}),
    "knowledge_decision_audit_is_opaque": (_D, {"audit_id": "a"}),
    "knowledge_assertion_principal_is_opaque": (_A, {"principal_id": "p"}),
    "knowledge_assertion_id_is_opaque": (_A, {"assertion_id": "asrt_kwp02asrt00002"}),
    "knowledge_assertion_subject_kind_is_known": (_A, {"subject_kind": "task"}),
    "knowledge_assertion_subject_id_matches_kind": (_A, {"subject_id": "x"}),
    "knowledge_assertion_value_follows_type": (_A, {"value_datetime": NOW}),
    "knowledge_assertion_text_is_bounded": (_A, {"value_text": ""}),
    "knowledge_assertion_qualifier_follows_rule": (_A, {"qualifier_rule": "date_kind"}),
    "knowledge_assertion_interval_is_ordered": (
        _A,
        {"effective_from": NOW, "effective_to": NOW},
    ),
    "knowledge_assertion_value_digest_is_sha256": (_A, {"normalized_value_sha256": "x"}),
    "knowledge_assertion_fingerprint_version_is_one": (_A, {"fingerprint_version": 2}),
    "knowledge_assertion_fingerprint_is_sha256": (_A, {"assertion_fingerprint": "x"}),
    "knowledge_assertion_epistemic_status_is_known": (_A, {"epistemic_status": "guess"}),
    "knowledge_assertion_classification_is_known": (_A, {"classification": "public"}),
    "knowledge_assertion_synthetic_needs_synthetic_origin": (
        _A,
        {"classification": "synthetic_test"},
    ),
    "knowledge_assertion_lifecycle_is_known": (_A, {"lifecycle": "deleted"}),
    "knowledge_assertion_version_is_positive": (_A, {"version": 0}),
    "knowledge_assertion_origin_is_opaque": (_A, {"origin_submission_id": "s"}),
    "knowledge_assertion_predecessor_is_another_assertion": (
        _A,
        {"supersedes_assertion_id": "kasr_kwp02asrt00002"},
    ),
    "knowledge_assertion_case_is_opaque": (_A, {"accepted_review_case_id": "x"}),
    "knowledge_assertion_is_not_updated_before_created": (_A, {"updated_at": EARLIER}),
    "knowledge_mutation_principal_is_opaque": (_M, {"principal_id": "p"}),
    "knowledge_mutation_id_is_opaque": (_M, {"mutation_id": "m"}),
    "knowledge_mutation_assertion_is_opaque": (_M, {"assertion_id": "a"}),
    "knowledge_mutation_kind_is_known": (_M, {"mutation_kind": "edit"}),
    "knowledge_mutation_version_is_contiguous": (_M, {"new_version": 3}),
    "knowledge_mutation_creation_starts_at_zero": (_M, {"mutation_kind": "create"}),
    "knowledge_mutation_submission_is_opaque": (_M, {"submission_id": "s"}),
    "knowledge_mutation_proposal_is_opaque": (_M, {"proposal_id": "p"}),
    "knowledge_mutation_case_is_opaque": (_M, {"review_case_id": "c"}),
    "knowledge_mutation_decision_is_opaque": (_M, {"review_decision_id": "d"}),
    "knowledge_mutation_submission_presence": (_M, {"mutation_kind": "evidence_enrich"}),
    "knowledge_mutation_review_fields_travel_together": (_M, {"review_decision_id": DECISION}),
    "knowledge_mutation_review_kinds_cite_a_decision": (_M, {"mutation_kind": "review_accept"}),
    "knowledge_evidence_link_principal_is_opaque": (_EL, {"principal_id": "p"}),
    "knowledge_evidence_link_role_is_known": (_EL, {"evidence_role": "primary"}),
    "knowledge_submission_evidence_principal_is_opaque": (_SE, {"principal_id": "p"}),
    "knowledge_submission_evidence_role_is_known": (_SE, {"evidence_role": "primary"}),
    "knowledge_trigger_event_principal_is_opaque": (_TE, {"principal_id": "p"}),
    "knowledge_trigger_event_id_is_opaque": (_TE, {"trigger_event_id": "evt"}),
    "knowledge_trigger_event_parent_triple_travels_together": (
        _TE,
        {"parent_submission_id": SUBMISSION},
    ),
    "knowledge_trigger_event_parent_depth_is_bounded": (_TE, {"parent_causal_depth": 5}),
    "knowledge_checkpoint_principal_is_opaque": (_C, {"principal_id": "p"}),
    "knowledge_checkpoint_id_is_opaque": (_C, {"checkpoint_id": "chk"}),
    "knowledge_checkpoint_profile_is_opaque": (_C, {"source_profile_id": "p"}),
    "knowledge_checkpoint_client_is_bounded": (_C, {"authenticated_client_id": ""}),
    "knowledge_checkpoint_scope_digest_is_sha256": (_C, {"scope_digest": "s"}),
    "knowledge_checkpoint_version_is_positive": (_C, {"version": 0}),
    "knowledge_checkpoint_kind_is_known": (_C, {"checkpoint_kind": "cursor"}),
    "knowledge_checkpoint_envelope_is_bounded": (_C, {"private_envelope": "e" * 4097}),
    "knowledge_checkpoint_seal_version_is_positive": (_C, {"seal_version": 0}),
    "knowledge_checkpoint_mac_is_hmac_sha256_hex": (_C, {"envelope_mac": "x"}),
    "knowledge_checkpoint_run_is_bounded": (_C, {"external_run_id": ""}),
    "knowledge_checkpoint_is_not_updated_before_created": (_C, {"updated_at": EARLIER}),
    "knowledge_checkpoint_request_principal_is_opaque": (_R, {"principal_id": "p"}),
    "knowledge_checkpoint_request_id_is_opaque": (_R, {"checkpoint_request_id": "r"}),
    "knowledge_checkpoint_request_client_is_bounded": (_R, {"authenticated_client_id": ""}),
    "knowledge_checkpoint_request_profile_is_opaque": (_R, {"source_profile_id": "p"}),
    "knowledge_checkpoint_request_scope_is_sha256": (_R, {"scope_digest": "s"}),
    "knowledge_checkpoint_request_run_is_bounded": (_R, {"external_run_id": "r" * 201}),
    "knowledge_checkpoint_request_count_is_bounded": (_R, {"submitted_candidate_count": -1}),
    "knowledge_checkpoint_request_expected_version_is_valid": (_R, {"expected_version": -1}),
    "knowledge_checkpoint_request_key_is_bounded": (_R, {"idempotency_key": ""}),
    "knowledge_checkpoint_request_digest_is_sha256": (_R, {"request_digest": "d"}),
    "knowledge_checkpoint_request_state_is_known": (_R, {"state": "open"}),
    "knowledge_checkpoint_request_outcome_is_known": (_R, {"result_outcome": "maybe"}),
    "knowledge_checkpoint_request_reason_matches_outcome": (
        _R,
        {"result_outcome": "advanced", "result_reason": "candidate_count_mismatch"},
    ),
    "knowledge_checkpoint_request_result_id_is_opaque": (_R, {"result_checkpoint_id": "c"}),
    "knowledge_checkpoint_request_result_version_is_positive": (
        _R,
        {"result_checkpoint_version": 0},
    ),
    "knowledge_checkpoint_request_result_kind_is_known": (_R, {"result_checkpoint_kind": "x"}),
    "knowledge_checkpoint_request_envelope_is_bounded": (_R, {"result_private_envelope": ""}),
    "knowledge_checkpoint_request_mac_is_hmac_sha256_hex": (_R, {"result_envelope_mac": "x"}),
    "knowledge_checkpoint_request_envelope_travels_with_mac": (
        _R,
        {"result_private_envelope": "env"},
    ),
    "knowledge_checkpoint_request_redacted_has_no_envelope": (
        _R,
        {"private_token_redacted": True, "result_private_envelope": "env"},
    ),
    "knowledge_checkpoint_request_reserved_has_no_result": (_R, {"result_reason": "advanced"}),
    "knowledge_checkpoint_request_completed_has_outcome": (_R, {"state": "completed"}),
    "knowledge_checkpoint_request_advanced_names_checkpoint": (
        _R,
        {"result_outcome": "advanced"},
    ),
    "knowledge_checkpoint_request_refusal_has_no_envelope": (
        _R,
        {"result_outcome": "refused", "result_private_envelope": "env"},
    ),
    "context_run_item_plane_is_known": (_CI, {"plane": "web"}),
    "context_run_item_authority_is_known": (_CI, {"authority_class": "web"}),
    "context_run_item_knowledge_assertion_is_opaque": (_CI, {"knowledge_assertion_id": "asrt"}),
    "context_run_item_knowledge_assertion_identity": (_CI, {"knowledge_assertion_id": None}),
}


def test_every_named_check_has_exactly_one_isolated_prove_red_case() -> None:
    """Coverage of the prove-red table: every matrix CHECK, plus the A4-A6 context CHECKs."""
    expected = {
        constraint["name"]: table
        for table, contract_table in _contract().items()
        for constraint in contract_table["constraints"]
        if constraint["kind"] == "check"
    }
    expected |= {
        "context_run_item_plane_is_known": _CI,
        "context_run_item_authority_is_known": _CI,
        "context_run_item_knowledge_assertion_is_opaque": _CI,
        "context_run_item_knowledge_assertion_identity": _CI,
    }
    assert {name: table for name, (table, _override) in CHECK_CASES.items()} == expected
    assert len(CHECK_CASES) == 212
    for name, (table, override) in CHECK_CASES.items():
        assert set(override) <= {column.name for column in _t(table).c}, name
        assert override, name


# ---- database fixtures and helpers -----------------------------------------------------


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """An empty catalog: this module drives Alembic itself."""
    return empty_database_url


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    built = create_database_engine(disposable_database)
    try:
        yield built
    finally:
        built.dispose()


@pytest.fixture(scope="module")
def head_engine(module_cloned_database_url: str) -> Iterator[Engine]:
    """One current-head clone for the prove-red cases; each case rolls itself back."""
    built = create_database_engine(module_cloned_database_url)
    try:
        yield built
    finally:
        built.dispose()


def _refusal(error: DBAPIError) -> tuple[str | None, str | None]:
    original = error.orig
    diag = getattr(original, "diag", None)
    return getattr(original, "sqlstate", None), getattr(diag, "constraint_name", None)


@cache
def _table_for(name: str) -> Table:
    return _t(name)


def _insert(connection: Connection, table: str, row: Mapping[str, Any]) -> None:
    connection.execute(insert(_table_for(table)).values(**row))


def _build_graph(connection: Connection) -> None:
    for table, row in GRAPH:
        _insert(connection, table, row)
    # Fire the two deferred reserved-at-commit checks now (both graph ledgers are
    # completed), so no trigger event is pending when a case alters a table, then
    # restore the declared deferral for the rest of the case.
    connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
    connection.execute(text("SET CONSTRAINTS ALL DEFERRED"))


def _refused(
    connection: Connection, sql: str | None = None, *, table: str | None = None, **params: object
) -> tuple[str | None, str | None]:
    """Run one statement in a savepoint; return the refusal it raised."""
    savepoint = connection.begin_nested()
    try:
        if table is not None:
            _insert(connection, table, params)
        else:
            assert sql is not None
            connection.execute(text(sql), params)
    except DBAPIError as error:
        savepoint.rollback()
        return _refusal(error)
    savepoint.rollback()
    raise AssertionError(f"accepted: {sql or table}")


def _accepted(connection: Connection, sql: str, **params: object) -> None:
    connection.execute(text(sql), params)


@pytest.fixture
def graph(head_engine: Engine) -> Iterator[Connection]:
    """A connection inside a transaction holding the parent graph; rolled back after."""
    with head_engine.connect() as connection:
        transaction = connection.begin()
        try:
            _build_graph(connection)
            yield connection
        finally:
            transaction.rollback()


# ---- migration edge: inventory ---------------------------------------------------------


def _scalar(engine: Engine, sql: str, **params: object) -> object:
    with engine.connect() as connection:
        return connection.execute(text(sql), params).scalar_one()


def _version(engine: Engine) -> str:
    return str(_scalar(engine, "SELECT version_num FROM alembic_version"))


_CATALOG_TYPES: Final = {
    "text": "text",
    "integer": "integer",
    "smallint": "smallint",
    "boolean": "boolean",
    "timestamptz": "timestamp with time zone",
    "jsonb": "jsonb",
    "text[]": "text[]",
}
_CATALOG_DEFAULTS: Final = {
    "now()": "now()",
    "'{}'::text[]": "'{}'::text[]",
    "false": "false",
    "1": "1",
    "'available'": "'available'::text",
}


def _columns(connection: Connection, table: str) -> list[tuple[str, str, bool, str | None]]:
    rows = connection.execute(
        text(
            "SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, "
            "pg_get_expr(d.adbin, d.adrelid) FROM pg_attribute a "
            "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
            "WHERE a.attrelid = CAST(:table AS regclass) AND a.attnum > 0 "
            "AND NOT a.attisdropped ORDER BY a.attnum"
        ),
        {"table": f"{SCHEMA}.{table}"},
    ).all()
    return [(str(r[0]), str(r[1]), bool(r[2]), None if r[3] is None else str(r[3])) for r in rows]


def _constraints(connection: Connection, table: str) -> dict[str, tuple[str, str]]:
    rows = connection.execute(
        text(
            "SELECT conname, contype, pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = CAST(:table AS regclass)"
        ),
        {"table": f"{SCHEMA}.{table}"},
    ).all()
    return {str(r[0]): (str(r[1]), str(r[2])) for r in rows}


def _canonical_check(connection: Connection, table: str, expression: str) -> str:
    """How the server itself prints `expression` as a CHECK on `table`'s columns."""
    connection.execute(text("SAVEPOINT canonical"))
    connection.execute(
        text(f"CREATE TEMP TABLE kwp02_canonical (LIKE {SCHEMA}.{table}) ON COMMIT DROP")
    )
    connection.execute(
        text(f"ALTER TABLE kwp02_canonical ADD CONSTRAINT kwp02_probe CHECK ({expression})")
    )
    definition = connection.execute(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = 'kwp02_probe' "
            "AND conrelid = CAST('kwp02_canonical' AS regclass)"
        )
    ).scalar_one()
    connection.execute(text("ROLLBACK TO SAVEPOINT canonical"))
    return str(definition)


def _canonical_index(connection: Connection, table: str, index: Mapping[str, Any]) -> str:
    connection.execute(text("SAVEPOINT canonical"))
    connection.execute(
        text(f"CREATE TEMP TABLE kwp02_canonical (LIKE {SCHEMA}.{table}) ON COMMIT DROP")
    )
    unique = "UNIQUE " if index["unique"] else ""
    where = f" WHERE {index['where']}" if index["where"] else ""
    connection.execute(
        text(
            f"CREATE {unique}INDEX kwp02_probe ON kwp02_canonical "
            f"({', '.join(index['columns'])}){where}"
        )
    )
    definition = str(
        connection.execute(
            text("SELECT pg_get_indexdef(CAST('kwp02_probe' AS regclass))")
        ).scalar_one()
    )
    connection.execute(text("ROLLBACK TO SAVEPOINT canonical"))
    definition = re.sub(r"ON pg_temp(?:_\d+)?\.kwp02_canonical", f"ON {SCHEMA}.{table}", definition)
    return definition.replace("INDEX kwp02_probe ", f"INDEX {index['name']} ")


def _indexes(connection: Connection, table: str) -> dict[str, str]:
    rows = connection.execute(
        text(
            "SELECT i.relname, pg_get_indexdef(x.indexrelid) FROM pg_index x "
            "JOIN pg_class i ON i.oid = x.indexrelid "
            "WHERE x.indrelid = CAST(:table AS regclass) AND NOT EXISTS "
            "(SELECT 1 FROM pg_constraint c WHERE c.conindid = x.indexrelid)"
        ),
        {"table": f"{SCHEMA}.{table}"},
    ).all()
    return {str(r[0]): str(r[1]) for r in rows}


def _triggers(connection: Connection, table: str) -> dict[str, tuple[Any, ...]]:
    rows = connection.execute(
        text(
            "SELECT t.tgname, t.tgtype, p.proname, n.nspname, t.tgconstraint <> 0, "
            "t.tgdeferrable, t.tginitdeferred, t.tgenabled FROM pg_trigger t "
            "JOIN pg_proc p ON p.oid = t.tgfoid JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE t.tgrelid = CAST(:table AS regclass) AND NOT t.tgisinternal"
        ),
        {"table": f"{SCHEMA}.{table}"},
    ).all()
    return {str(r[0]): tuple(r[1:]) for r in rows}


def _expected_trigger(trigger: Mapping[str, Any]) -> tuple[Any, ...]:
    # pg_trigger.tgtype bits: ROW 1, BEFORE 2, INSERT 4, DELETE 8, UPDATE 16.
    bits = 1 if trigger["level"] == "ROW" else 0
    bits |= 2 if trigger["timing"] == "BEFORE" else 0
    for event in trigger["events"].split(" OR "):
        bits |= {"INSERT": 4, "DELETE": 8, "UPDATE": 16}[event]
    deferred = bool(trigger["constraint_trigger_deferrable_initially_deferred"])
    function = trigger["function"].removeprefix("knowledge.").removesuffix("()")
    return (bits, function, SCHEMA, deferred, deferred, deferred, "O")


def _assert_inventory(connection: Connection) -> None:
    for name, table in _contract().items():
        columns = _columns(connection, name)
        assert columns == [
            (
                spec["name"],
                _CATALOG_TYPES[spec["type"]],
                not spec["nullable"],
                None if spec["default"] is None else _CATALOG_DEFAULTS[spec["default"]],
            )
            for spec in table["columns"]
        ], name
        constraints = _constraints(connection, name)
        # A constraint trigger also owns a pg_constraint row (contype 't'), named for it.
        assert {n for n, (kind, _definition) in constraints.items() if kind == "t"} == {
            trigger["name"]
            for trigger in table["triggers"]
            if trigger["constraint_trigger_deferrable_initially_deferred"]
        }, name
        constraints = {n: row for n, row in constraints.items() if row[0] != "t"}
        assert set(constraints) == {c["name"] for c in table["constraints"]}, name
        for spec in table["constraints"]:
            kind, definition = constraints[spec["name"]]
            columns_text = ", ".join(spec.get("columns", []))
            if spec["kind"] == "check":
                assert kind == "c"
                assert definition == _canonical_check(connection, name, spec["expression"]), spec[
                    "name"
                ]
            elif spec["kind"] == "primary_key":
                assert (kind, definition) == ("p", f"PRIMARY KEY ({columns_text})")
            elif spec["kind"] == "unique":
                assert (kind, definition) == ("u", f"UNIQUE ({columns_text})")
            else:
                assert kind == "f"
                assert definition == (
                    f"FOREIGN KEY ({columns_text}) REFERENCES "
                    f"{SCHEMA}.{spec['references_table']}"
                    f"({', '.join(spec['references_columns'])}) ON DELETE RESTRICT"
                ), spec["name"]
        flags = connection.execute(
            text(
                "SELECT coalesce(bool_or(condeferrable), false), "
                "coalesce(bool_and(confmatchtype = 's'), true), "
                "coalesce(bool_and(confdeltype = 'r'), true) FROM pg_constraint "
                "WHERE conrelid = CAST(:table AS regclass) AND contype = 'f'"
            ),
            {"table": f"{SCHEMA}.{name}"},
        ).one()
        assert tuple(flags) == (False, True, True), name
        indexes = _indexes(connection, name)
        assert set(indexes) == {index["name"] for index in table["indexes"]}, name
        for index in table["indexes"]:
            assert indexes[index["name"]] == _canonical_index(connection, name, index), index[
                "name"
            ]
        triggers = _triggers(connection, name)
        assert triggers == {
            trigger["name"]: _expected_trigger(trigger) for trigger in table["triggers"]
        }, name


def _functions(connection: Connection) -> dict[str, tuple[Any, ...]]:
    rows = connection.execute(
        text(
            "SELECT p.proname, l.lanname, p.provolatile, p.proisstrict, p.proparallel, "
            "format_type(p.prorettype, NULL), pg_get_function_identity_arguments(p.oid) "
            "FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "JOIN pg_language l ON l.oid = p.prolang "
            "WHERE n.nspname = :schema AND p.proname LIKE 'knowledge\\_%'"
        ),
        {"schema": SCHEMA},
    ).all()
    return {str(r[0]): tuple(r[1:]) for r in rows}


def _assert_functions(connection: Connection) -> None:
    functions = _functions(connection)
    trigger_functions = {name for name, _sql in _revision()._TRIGGER_FUNCTIONS}
    assert (
        set(functions)
        == {
            "knowledge_classification_rank",
            "knowledge_row_is_append_only",
        }
        | trigger_functions
    )
    assert functions["knowledge_classification_rank"] == (
        "sql",
        "i",
        True,
        "s",
        "smallint",
        "classification text",
    )
    assert functions["knowledge_row_is_append_only"][:2] == ("plpgsql", "v")
    for name in trigger_functions:
        assert functions[name][0] == "plpgsql" and functions[name][4] == "trigger", name
    ranks = connection.execute(
        text(
            "SELECT knowledge.knowledge_classification_rank('synthetic_test'), "
            "knowledge.knowledge_classification_rank('private_local'), "
            "knowledge.knowledge_classification_rank('restricted_local'), "
            "knowledge.knowledge_classification_rank('public'), "
            "knowledge.knowledge_classification_rank(NULL)"
        )
    ).one()
    assert tuple(ranks) == (0, 1, 2, None, None)


def _assert_seeds(connection: Connection) -> None:
    rows = [
        dict(row._mapping)
        for row in connection.execute(
            text(
                "SELECT * FROM knowledge.knowledge_assertion_predicates "
                "ORDER BY predicate_code, predicate_version"
            )
        )
    ]
    expected = sorted(_matrix()["initial_predicates"], key=lambda row: row["predicate_code"])
    assert len(rows) == 8
    for row, seed in zip(rows, expected, strict=True):
        assert row.pop("created_at") is not None
        assert row == {column: seed[column] for column in _SEED_COLUMNS}, seed["predicate_code"]


def _admitted(connection: Connection, table: str, constraint: str) -> tuple[str, ...]:
    definition = connection.execute(
        text(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint WHERE conname = :name "
            "AND conrelid = CAST(:table AS regclass)"
        ),
        {"name": constraint, "table": f"{SCHEMA}.{table}"},
    ).scalar_one()
    return tuple(re.findall(r"'([^']+)'::text", str(definition)))


def _assert_alters(connection: Connection) -> None:
    alters = _alters()
    assert _admitted(connection, "audit_events", "capability_is_known") == tuple(
        alters["A1"]["after_literal"]
    )
    assert _admitted(connection, "audit_events", "purpose_is_known") == tuple(
        alters["A2"]["after_literal"]
    )
    assert _admitted(connection, "record_events", "a_record_event_family_is_known") == tuple(
        alters["A3"]["after_literal"]
    )
    items = _constraints(connection, "context_run_items")
    # W3-001: the declared names are present and the generated ones are gone.
    assert "context_run_item_plane_is_known" in items
    assert "context_run_item_authority_is_known" in items
    assert "context_run_items_plane_check" not in items
    assert "context_run_items_authority_class_check" not in items
    assert _admitted(connection, "context_run_items", "context_run_item_plane_is_known") == tuple(
        alters["A4"]["after_literal"]
    )
    assert _admitted(
        connection, "context_run_items", "context_run_item_authority_is_known"
    ) == tuple(alters["A5"]["after_literal"])
    a6 = _revision()
    for name in ("context_run_item_knowledge_assertion_is_opaque",):
        assert items[name][1] == _canonical_check(
            connection,
            "context_run_items",
            "knowledge_assertion_id IS NULL OR knowledge_assertion_id ~ '^kasr_[A-Za-z0-9]{8,64}$'",
        )
    identity = re.search(
        r"context_run_item_knowledge_assertion_identity CHECK \((.*)\)\s*$",
        _flat(a6._CONTEXT_ITEM_KNOWLEDGE_ASSERTION),
    )
    assert identity
    assert items["context_run_item_knowledge_assertion_identity"][1] == _canonical_check(
        connection, "context_run_items", identity.group(1)
    )
    assert ("knowledge_assertion_id", "text", False, None) in _columns(
        connection, "context_run_items"
    )
    assert _indexes(connection, "context_run_items")[
        "context_run_items_by_knowledge_assertion"
    ] == (
        "CREATE INDEX context_run_items_by_knowledge_assertion ON knowledge.context_run_items "
        "USING btree (principal_id, knowledge_assertion_id) WHERE (knowledge_assertion_id IS "
        "NOT NULL)"
    )
    memories = _constraints(connection, "relationship_memories")
    assert memories["a_memory_is_identified_within_its_principal"] == (
        "u",
        "UNIQUE (memory_id, principal_id)",
    )


@pytest.mark.database
def test_an_empty_database_reaches_the_head_with_the_frozen_inventory(engine: Engine) -> None:
    """AC-131 / AC-078 (empty->head): pg_catalog equals the matrix, exactly."""
    command.upgrade(_config(), "head")
    assert _version(engine) == REVISION
    with engine.connect() as connection, connection.begin():
        tables = set(
            connection.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = :schema "
                    "AND tablename LIKE 'knowledge\\_%'"
                ),
                {"schema": SCHEMA},
            ).scalars()
        )
        assert tables == set(_contract())
        _assert_inventory(connection)
        _assert_functions(connection)
        _assert_seeds(connection)
        _assert_alters(connection)


# ---- migration edge: predecessor upgrade, refusal, round trip ---------------------------


def _audit(connection: Connection, audit_id: str, capability: str, purpose: str) -> None:
    connection.execute(
        text(
            "INSERT INTO knowledge.audit_events (audit_id, correlation_id, principal_id, "
            "capability, purpose, outcome, policy_version, recorded_at) VALUES (:audit, "
            "'corr_kwp02corr0009', :principal, :capability, :purpose, 'allowed', 'policy-v1', "
            ":now)"
        ),
        {
            "audit": audit_id,
            "principal": PRINCIPAL,
            "capability": capability,
            "purpose": purpose,
            "now": NOW,
        },
    )


def _context_item(connection: Connection, position: int, **overrides: object) -> None:
    columns = {
        "context_manifest_id": MANIFEST,
        "position": position,
        "principal_id": PRINCIPAL,
        "reference_id": f"kwp02-ref-{position}",
        "plane": "capture",
        "authority_class": "product_owned_capture",
        "lifecycle": "accepted",
        "classification": "private_local",
        "excerpt_sha256": DIGEST,
        "reason_codes": "",
        **overrides,
    }
    names = ", ".join(columns)
    values = ", ".join(f":{name}" for name in columns)
    connection.execute(
        text(f"INSERT INTO knowledge.context_run_items ({names}) VALUES ({values})"),  # noqa: S608
        columns,
    )


def _context_run(connection: Connection) -> None:
    row = dict(GRAPH[-1][1])
    names = ", ".join(row)
    values = ", ".join(f":{name}" for name in row)
    connection.execute(text(f"INSERT INTO knowledge.context_runs ({names}) VALUES ({values})"), row)  # noqa: S608


def _snapshot(connection: Connection, tables: tuple[str, ...]) -> dict[str, Any]:
    return {
        table: (
            _columns(connection, table),
            _constraints(connection, table),
            _indexes(connection, table),
            _triggers(connection, table),
        )
        for table in tables
    }


_EXISTING: Final = (
    "audit_events",
    "record_events",
    "context_run_items",
    "relationship_memories",
    "relationship_write_requests",
    "capture_review_cases",
    "captures",
)


@pytest.mark.database
def test_the_predecessor_with_context_items_and_audit_rows_upgrades_unchanged(
    engine: Engine,
) -> None:
    """AC-078 (0641c354ca85->head); N1-N4: the four untouched tables keep their DDL."""
    command.upgrade(_config(), PREVIOUS)
    with engine.begin() as connection:
        _audit(connection, "audit_kwp02audit010", "capture.create", "capture_authoring")
        _context_run(connection)
        _context_item(connection, 0)
        before = _snapshot(connection, _EXISTING)
    command.upgrade(_config(), REVISION)
    assert _version(engine) == REVISION
    with engine.begin() as connection:
        after = _snapshot(connection, _EXISTING)
        for table in ("relationship_write_requests", "capture_review_cases", "captures"):
            assert after[table] == before[table], table
        assert after["record_events"][0] == before["record_events"][0]
        assert set(after["record_events"][1]) == set(before["record_events"][1])
        item = connection.execute(
            text(
                "SELECT plane, authority_class, knowledge_assertion_id "
                "FROM knowledge.context_run_items"
            )
        ).one()
        assert tuple(item) == ("capture", "product_owned_capture", None)
        assert _scalar(engine, "SELECT count(*) FROM knowledge.audit_events") == 1
        # The new vocabulary is admitted at head (A1-A6 accept what they add).
        _audit(
            connection,
            "audit_kwp02audit011",
            "knowledge.assertions.create",
            "knowledge_assertion_authoring",
        )
        _context_item(
            connection,
            1,
            plane="knowledge_assertion",
            authority_class="product_owned_knowledge_assertion",
            knowledge_assertion_id=ASSERTION,
        )


#: One Knowledge state of each kind the downgrade refusal names.
_STATES: Final = (
    "knowledge_row",
    "subject_lock",
    "capability",
    "purpose",
    "record_event",
    "context",
)


def _plant(connection: Connection, state: str) -> None:
    if state == "knowledge_row":
        _insert(connection, *GRAPH[0])
    elif state == "subject_lock":
        _insert(connection, _L, BASE[_L])
    elif state == "capability":
        _audit(connection, "audit_kwp02audit020", "record_events.provenance", "record_event_read")
    elif state == "purpose":
        _audit(
            connection, "audit_kwp02audit021", "record_events.list", "record_event_provenance_read"
        )
    elif state == "record_event":
        _insert(connection, "record_events", GRAPH[7][1])
    else:
        _context_run(connection)
        _context_item(
            connection,
            0,
            plane="knowledge_assertion",
            authority_class="product_owned_knowledge_assertion",
            knowledge_assertion_id=ASSERTION,
        )


@pytest.mark.database
@pytest.mark.parametrize("state", _STATES)
def test_a_downgrade_refuses_while_knowledge_state_exists(engine: Engine, state: str) -> None:
    """AC-078: restrict_violation, version unchanged, nothing deleted."""
    command.upgrade(_config(), "head")
    with engine.begin() as connection:
        _plant(connection, state)
    with engine.connect() as connection:
        counts_before = _knowledge_counts(connection)
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert _refusal(refused.value)[0] == RESTRICT_VIOLATION
    assert _version(engine) == REVISION
    with engine.connect() as connection:
        assert _knowledge_counts(connection) == counts_before
        assert sum(counts_before.values()) >= 9


def _knowledge_counts(connection: Connection) -> dict[str, int]:
    counts = {}
    for table in (*_contract(), "audit_events", "record_events", "context_run_items"):
        counts[table] = int(
            connection.execute(text(f"SELECT count(*) FROM {SCHEMA}.{table}")).scalar_one()  # noqa: S608
        )
    return counts


@pytest.mark.database
def test_an_empty_downgrade_restores_the_exact_predecessor_and_upgrades_again(
    engine: Engine,
) -> None:
    """AC-078: generated context names and exact BEFORE literals come back; round trip."""
    command.upgrade(_config(), PREVIOUS)
    with engine.connect() as connection:
        before = _snapshot(connection, _EXISTING)
        functions_before = _functions(connection)
    command.upgrade(_config(), "head")
    with engine.connect() as connection:
        assert "context_run_items_plane_check" not in _constraints(connection, "context_run_items")
    command.downgrade(_config(), PREVIOUS)
    assert _version(engine) == PREVIOUS
    with engine.connect() as connection:
        assert _snapshot(connection, _EXISTING) == before
        items = _constraints(connection, "context_run_items")
        assert "context_run_items_plane_check" in items
        assert "context_run_items_authority_class_check" in items
        assert "context_run_item_plane_is_known" not in items
        assert _functions(connection) == functions_before == {}
        remaining = connection.execute(
            text(
                "SELECT count(*) FROM pg_tables WHERE schemaname = :schema "
                "AND tablename LIKE 'knowledge\\_%'"
            ),
            {"schema": SCHEMA},
        ).scalar_one()
        assert remaining == 0
    command.upgrade(_config(), "head")
    assert _version(engine) == REVISION
    with engine.connect() as connection, connection.begin():
        _assert_seeds(connection)
        _assert_alters(connection)


# ---- migration edge: prove-red, one CHECK at a time --------------------------------------


@pytest.mark.database
def test_the_base_rows_are_accepted_with_every_constraint_and_trigger_live(
    graph: Connection,
) -> None:
    """The control for every CHECK case below: the unmodified row is admitted."""
    for table, row in BASE.items():
        savepoint = graph.begin_nested()
        _insert(graph, table, row)
        savepoint.rollback()


@pytest.mark.database
@pytest.mark.parametrize("name", sorted(CHECK_CASES))
def test_each_check_refuses_its_minimal_violation_in_isolation(
    graph: Connection, name: str
) -> None:
    table, override = CHECK_CASES[name]
    savepoint = graph.begin_nested()
    try:
        others = [
            str(other)
            for other in graph.execute(
                text(
                    "SELECT conname FROM pg_constraint WHERE contype = 'c' "
                    "AND conrelid = CAST(:table AS regclass) AND conname <> :name"
                ),
                {"table": f"{SCHEMA}.{table}", "name": name},
            ).scalars()
        ]
        graph.execute(text(f"ALTER TABLE {SCHEMA}.{table} DISABLE TRIGGER USER"))
        if others:
            graph.execute(
                text(
                    f"ALTER TABLE {SCHEMA}.{table} "
                    + ", ".join(f"DROP CONSTRAINT {other}" for other in others)
                )
            )
        assert _refused(graph, table=table, **{**BASE[table], **override}) == (
            CHECK_VIOLATION,
            name,
        )
    finally:
        savepoint.rollback()


# ---- migration edge: triggers ----------------------------------------------------------


def _update(table: str, assignments: str, where: str) -> str:
    return f"UPDATE {SCHEMA}.{table} SET {assignments} WHERE {where}"  # noqa: S608


def _delete(table: str, where: str = "TRUE") -> str:
    return f"DELETE FROM {SCHEMA}.{table} WHERE {where}"  # noqa: S608


@pytest.mark.database
def test_the_predicate_registry_is_insert_only_and_structurally_versioned(
    graph: Connection,
) -> None:
    """AC-004 / AC-150: insert-only; head+1 with identical structure; retired is closed."""
    payment = f"predicate_code = '{PAYMENT_TERMS}'"
    assert _refused(graph, _update(_P, "admission_state = 'retired'", payment))[0] == (
        RESTRICT_VIOLATION
    )
    assert _refused(graph, _delete(_P, payment))[0] == RESTRICT_VIOLATION
    seed = {**BASE[_P], "predicate_code": PAYMENT_TERMS}
    # A structural change within the code, a skipped version, a new code past 1.
    assert _refused(
        graph,
        table=_P,
        **{
            **seed,
            "predicate_version": 2,
            "cardinality": "multi_value",
            "conflict_rule": "coexist",
        },
    ) == (CHECK_VIOLATION, None)
    assert _refused(graph, table=_P, **{**seed, "predicate_version": 3}) == (CHECK_VIOLATION, None)
    assert _refused(graph, table=_P, **{**BASE[_P], "predicate_version": 2}) == (
        CHECK_VIOLATION,
        None,
    )
    # Head + 1 with the same structure is admitted; non-structural fields may differ.
    _insert(graph, _P, {**seed, "predicate_version": 2, "review_requirement": "requires_review"})
    # A retired head closes the code permanently.
    _insert(graph, _P, {**BASE[_P]})
    _insert(graph, _P, {**BASE[_P], "predicate_version": 2, "admission_state": "retired"})
    assert _refused(graph, table=_P, **{**BASE[_P], "predicate_version": 3}) == (
        CHECK_VIOLATION,
        None,
    )


@pytest.mark.database
def test_an_assertion_must_use_the_active_predicate_head(graph: Connection) -> None:
    """AC-150 / race 19: a non-head or a retired head version is refused at INSERT."""
    seed = {**BASE[_P], "predicate_code": PAYMENT_TERMS}
    _insert(graph, _P, {**seed, "predicate_version": 2})
    assert _refused(graph, table=_A, **BASE[_A]) == (CHECK_VIOLATION, None)
    _insert(graph, _A, {**BASE[_A], "predicate_version": 2})
    _insert(graph, _P, {**BASE[_P]})
    _insert(graph, _P, {**BASE[_P], "predicate_version": 2, "admission_state": "retired"})
    retired = {
        **BASE[_A],
        "assertion_id": "kasr_kwp02asrt00003",
        "subject_id": "ent_kwp02entity0003",
        "assertion_fingerprint": "3" * 64,
        "predicate_code": "zz.case",
    }
    assert _refused(graph, table=_A, **{**retired, "predicate_version": 2}) == (
        CHECK_VIOLATION,
        None,
    )
    assert _refused(graph, table=_A, **{**retired, "predicate_version": 1}) == (
        CHECK_VIOLATION,
        None,
    )


@pytest.mark.database
def test_the_registered_structure_binds_assertions_and_proposals(graph: Connection) -> None:
    """AC-003 / AC-130: an unknown (code, version) or a mismatched structure is 23503."""
    mismatched = {
        **BASE[_A],
        "value_type": "datetime",
        "value_text": None,
        "value_datetime": NOW,
    }
    assert _refused(graph, table=_A, **mismatched) == (
        FOREIGN_KEY_VIOLATION,
        "knowledge_assertion_uses_registered_structure",
    )
    assert _refused(graph, table=_PP, **{**BASE[_PP], "predicate_version": 9}) == (
        FOREIGN_KEY_VIOLATION,
        "knowledge_proposal_uses_registered_structure",
    )
    assert _refused(graph, table=_PP, **{**BASE[_PP], "cardinality": "multi_value"}) == (
        FOREIGN_KEY_VIOLATION,
        "knowledge_proposal_uses_registered_structure",
    )


@pytest.mark.database
def test_assertion_facts_are_immutable_and_controls_move_forward_only(
    graph: Connection,
) -> None:
    """AC-006 / AC-007 / AC-095: controls only, version + 1, rank-monotonic, terminal."""
    where = f"assertion_id = '{ASSERTION}'"
    assert _refused(graph, _delete(_A, where))[0] == RESTRICT_VIOLATION
    for assignments in (
        "value_text = 'Net 45', version = 2",
        "subject_id = 'ent_kwp02entity0009', version = 2",
        "predicate_version = 1, origin_submission_id = 'kasub_kwp02sub00009', version = 2",
        "lifecycle = 'revalidation_required'",
        "lifecycle = 'revalidation_required', version = 3",
        "classification = 'synthetic_test', version = 2",
        "version = 2, updated_at = :earlier",
    ):
        assert _refused(graph, _update(_A, assignments, where), earlier=EARLIER)[0] == (
            RESTRICT_VIOLATION
        ), assignments
    _accepted(graph, _update(_A, "classification = 'restricted_local', version = 2", where))
    assert (
        _refused(graph, _update(_A, "classification = 'private_local', version = 3", where))[0]
        == RESTRICT_VIOLATION
    )
    _accepted(graph, _update(_A, "lifecycle = 'archived', version = 3", where))
    assert _refused(graph, _update(_A, "lifecycle = 'active', version = 4", where))[0] == (
        RESTRICT_VIOLATION
    )


@pytest.mark.database
def test_mutation_versions_are_unique_and_contiguous(graph: Connection) -> None:
    """AC-007: a duplicate new_version is 23505; a gap is 23514."""
    duplicate = {
        **BASE[_M],
        "mutation_kind": "create",
        "prior_version": 0,
        "new_version": 1,
        "submission_id": SUBMISSION,
    }
    assert _refused(graph, table=_M, **duplicate) == (
        UNIQUE_VIOLATION,
        "knowledge_mutation_version_is_unique",
    )
    assert _refused(graph, table=_M, **{**BASE[_M], "new_version": 4}) == (
        CHECK_VIOLATION,
        "knowledge_mutation_version_is_contiguous",
    )
    _insert(graph, _M, BASE[_M])


def _successor(**overrides: object) -> dict[str, Any]:
    return {
        **BASE[_A],
        "assertion_id": "kasr_kwp02asrt00005",
        "subject_id": ENTITY,
        "assertion_fingerprint": "5" * 64,
        "supersedes_assertion_id": ASSERTION,
        **overrides,
    }


@pytest.mark.database
def test_supersession_is_demote_then_insert_once_and_never_less_restrictive(
    graph: Connection,
) -> None:
    """AC-008 / AC-092 / AC-095 / AC-116: single slot, one successor, monotone class."""
    where = f"assertion_id = '{ASSERTION}'"
    # The predecessor is still live: the trigger refuses before the slot index does.
    assert _refused(graph, table=_A, **_successor()) == (CHECK_VIOLATION, None)
    # A second live single_current assertion for the same key never coexists.
    rival = {**_successor(), "supersedes_assertion_id": None}
    assert _refused(graph, table=_A, **rival) == (
        UNIQUE_VIOLATION,
        "knowledge_assertion_single_current_slot",
    )
    _accepted(
        graph,
        _update(
            _A, "lifecycle = 'superseded', classification = 'restricted_local', version = 2", where
        ),
    )
    assert _refused(graph, table=_A, **_successor()) == (CHECK_VIOLATION, None)
    _insert(graph, _A, _successor(classification="restricted_local"))
    # One successor per predecessor; a self-reference is a CHECK.
    _accepted(
        graph,
        _update(_A, "lifecycle = 'archived', version = 2", "assertion_id = 'kasr_kwp02asrt00005'"),
    )
    second = _successor(
        assertion_id="kasr_kwp02asrt00006",
        assertion_fingerprint="6" * 64,
        classification="restricted_local",
    )
    assert _refused(graph, table=_A, **second) == (
        UNIQUE_VIOLATION,
        "knowledge_assertion_supersedes_once",
    )


@pytest.mark.database
def test_an_accepted_assertion_is_never_less_restrictive_than_its_proposal(
    graph: Connection,
) -> None:
    """AC-095 / AC-116: the BEFORE INSERT floor trigger, via accepted_review_case_id."""
    _accepted(
        graph,
        _update(
            _PP,
            "classification = 'restricted_local', state = 'accepted'",
            f"proposal_id = '{PROPOSAL}'",
        ),
    )
    accepted = {**BASE[_A], "accepted_review_case_id": CASE}
    assert _refused(graph, table=_A, **accepted) == (CHECK_VIOLATION, None)
    _insert(graph, _A, {**accepted, "classification": "restricted_local"})


@pytest.mark.database
def test_live_fingerprints_are_unique_and_an_a_b_a_sequence_ends_with_one_live_a(
    graph: Connection,
) -> None:
    """AC-009 (schema slice) / AC-117: uniqueness covers live lifecycles only, with v1."""
    multi = {
        **BASE[_A],
        "predicate_code": "project.decision",
        "cardinality": "multi_value",
        "temporal_semantics": "historical",
        "subject_kind": "project",
        "subject_id": "prj_kwp02project01",
        "assertion_fingerprint": "7" * 64,
    }
    _insert(graph, _A, multi)
    again = {**multi, "assertion_id": "kasr_kwp02asrt00008"}
    assert _refused(graph, table=_A, **again) == (
        UNIQUE_VIOLATION,
        "knowledge_assertion_live_fingerprint",
    )
    _accepted(
        graph,
        _update(_A, "lifecycle = 'archived', version = 2", "assertion_id = 'kasr_kwp02asrt00002'"),
    )
    _insert(graph, _A, again)
    open_twin = {**BASE[_PP], "proposal_fingerprint": "f" * 64}
    assert _refused(graph, table=_PP, **open_twin) == (
        UNIQUE_VIOLATION,
        "knowledge_proposal_open_fingerprint",
    )


@pytest.mark.database
def test_evidence_identity_is_canonical_and_same_principal(graph: Connection) -> None:
    """AC-010 / AC-014 / AC-112: one row per identity; composite same-Principal FKs."""
    twin = {**BASE[_E], "external_object_id": "obj-kwp02-1"}
    assert _refused(graph, table=_E, **twin) == (
        UNIQUE_VIOLATION,
        "knowledge_evidence_external_identity",
    )
    _accepted(
        graph,
        "INSERT INTO knowledge.captures (capture_id, owner_principal_id, created_at) "
        "VALUES ('cap_kwp02capture01', :other, :now)",
        other=OTHER_PRINCIPAL,
        now=NOW,
    )
    capture_row = {
        **BASE[_E],
        **_CAPTURE_SHAPE,
        "excerpt": None,
        "excerpt_sha256": None,
    }
    assert _refused(graph, table=_E, **capture_row) == (
        FOREIGN_KEY_VIOLATION,
        "knowledge_evidence_ref_cites_owned_capture",
    )
    memory_row = {
        **capture_row,
        "identity_kind": "relationship_memory",
        "capture_id": None,
        "relationship_memory_id": "mem_kwp02memory001",
        "content_origin": "relationship_memory",
    }
    assert _refused(graph, table=_E, **memory_row) == (
        FOREIGN_KEY_VIOLATION,
        "knowledge_evidence_ref_cites_owned_memory",
    )
    _accepted(
        graph,
        "INSERT INTO knowledge.captures (capture_id, owner_principal_id, created_at) "
        "VALUES ('cap_kwp02capture02', :principal, :now)",
        principal=PRINCIPAL,
        now=NOW,
    )
    own = {**capture_row, "capture_id": "cap_kwp02capture02"}
    _insert(graph, _E, own)
    assert _refused(graph, table=_E, **{**own, "evidence_ref_id": "kaevd_kwp02evid0003"}) == (
        UNIQUE_VIOLATION,
        "knowledge_evidence_capture_identity",
    )
    other_link = {**BASE[_EL], "principal_id": OTHER_PRINCIPAL}
    assert _refused(graph, table=_EL, **other_link)[0] == FOREIGN_KEY_VIOLATION


@pytest.mark.database
def test_an_evidence_link_names_a_mutation_of_the_same_assertion(graph: Connection) -> None:
    """AC-100 / AC-130: NOT DEFERRABLE composite FK to the mutation of that assertion."""
    _insert(graph, _A, BASE[_A])
    foreign = {**BASE[_EL], "assertion_id": "kasr_kwp02asrt00002"}
    assert _refused(graph, table=_EL, **foreign) == (
        FOREIGN_KEY_VIOLATION,
        "knowledge_evidence_link_made_by_mutation_of_assertion",
    )
    _insert(graph, _EL, BASE[_EL])
    for sql in (
        _update(_EL, "evidence_role = 'supporting'", "TRUE"),
        _delete(_EL),
    ):
        assert _refused(graph, sql)[0] == RESTRICT_VIOLATION


@pytest.mark.database
def test_append_only_ledgers_refuse_update_and_delete(graph: Connection) -> None:
    """Decisions, mutations, submission evidence, trigger events, subject locks."""
    _insert(graph, _SE, BASE[_SE])
    _insert(graph, _TE, BASE[_TE])
    _insert(graph, _L, BASE[_L])
    for table in (_D, _M, _SE, _TE, _L):
        assert _refused(graph, _update(table, "principal_id = principal_id", "TRUE"))[0] == (
            RESTRICT_VIOLATION
        ), table
        assert _refused(graph, _delete(table))[0] == RESTRICT_VIOLATION, table


@pytest.mark.database
def test_the_subject_lock_is_keyed_without_predicate_version(graph: Connection) -> None:
    """AC-091: one lock row per (Principal, subject, predicate_code), created idempotently."""
    _insert(graph, _L, BASE[_L])
    assert _refused(graph, table=_L, **BASE[_L]) == (
        UNIQUE_VIOLATION,
        "knowledge_subject_lock_is_identified",
    )
    graph.execute(
        text(
            "INSERT INTO knowledge.knowledge_assertion_subject_locks (principal_id, "
            "subject_kind, subject_id, predicate_code) VALUES (:p, 'entity', :s, :c) "
            "ON CONFLICT (principal_id, subject_kind, subject_id, predicate_code) DO NOTHING"
        ),
        {"p": PRINCIPAL, "s": ENTITY_TWO, "c": PAYMENT_TERMS},
    )


@pytest.mark.database
def test_a_proposal_moves_only_its_controls_and_terminal_states_are_final(
    graph: Connection,
) -> None:
    """AC-034 (case scope) / AC-095: controls only; rank-monotone; terminal is final."""
    where = f"proposal_id = '{PROPOSAL}'"
    assert _refused(graph, _delete(_PP, where))[0] == RESTRICT_VIOLATION
    for assignments in (
        "value_text = 'Net 60'",
        "review_case_id = 'rvw_kwp02case00009'",
        "updated_at = :earlier",
    ):
        assert _refused(graph, _update(_PP, assignments, where), earlier=EARLIER)[0] == (
            RESTRICT_VIOLATION
        ), assignments
    _accepted(graph, _update(_PP, "classification = 'restricted_local', state = 'deferred'", where))
    assert _refused(graph, _update(_PP, "classification = 'private_local'", where))[0] == (
        RESTRICT_VIOLATION
    )
    _accepted(graph, _update(_PP, "state = 'rejected'", where))
    assert _refused(graph, _update(_PP, "state = 'needs_review'", where))[0] == (RESTRICT_VIOLATION)
    duplicate_case = {**BASE[_PP], "review_case_id": CASE}
    assert _refused(graph, table=_PP, **duplicate_case)[0] == UNIQUE_VIOLATION
    cross = {**BASE[_D], "principal_id": OTHER_PRINCIPAL}
    assert _refused(graph, table=_D, **cross) == (
        FOREIGN_KEY_VIOLATION,
        "knowledge_decision_names_proposal_case",
    )


@pytest.mark.database
def test_a_source_profile_mutates_controls_only_and_disable_is_terminal(
    graph: Connection,
) -> None:
    """AC-061 / AC-062 / AC-101: binding immutable; version + 1; one active scope."""
    where = f"source_profile_id = '{PROFILE}'"
    assert _refused(graph, _delete(_PR, where))[0] == RESTRICT_VIOLATION
    for assignments in (
        "scope_digest = :other, profile_version = 2",
        "authority_ceiling = 'observed_source', profile_version = 2",
        "read_only_proof_state = 'proven'",
        "read_only_proof_state = 'proven', profile_version = 2, updated_at = :earlier",
    ):
        assert (
            _refused(graph, _update(_PR, assignments, where), other="b" * 64, earlier=EARLIER)[0]
            == RESTRICT_VIOLATION
        ), assignments
    _accepted(
        graph,
        _update(
            _PR,
            "read_only_proof_state = 'proven', direct_admission_enabled = true, "
            "profile_version = 2",
            where,
        ),
    )
    twin = {**GRAPH[0][1], "source_profile_id": "kdsp_kwp02profile03"}
    assert _refused(graph, table=_PR, **twin) == (
        UNIQUE_VIOLATION,
        "knowledge_profile_one_active_scope",
    )
    _accepted(
        graph,
        _update(
            _PR,
            "disabled_at = :now, direct_admission_enabled = false, profile_version = 3",
            where,
        ),
        now=NOW,
    )
    _insert(graph, _PR, twin)
    assert _refused(graph, _update(_PR, "profile_version = 4", where))[0] == RESTRICT_VIOLATION


@pytest.mark.database
def test_a_submission_completes_once_and_is_never_committed_reserved(
    graph: Connection,
) -> None:
    """AC-050 / AC-051 / AC-093: lifecycle trigger, deferred re-read, idempotency keys."""
    completed = {**BASE[_S], "submission_state": "completed", "outcome": "direct_created"}
    assert _refused(graph, table=_S, **completed) == (CHECK_VIOLATION, None)
    assert _refused(graph, _delete(_S))[0] == RESTRICT_VIOLATION
    graph_where = f"submission_id = '{SUBMISSION}'"
    assert (
        _refused(graph, _update(_S, "reason = 'source_authority_insufficient'", graph_where))[0]
        == RESTRICT_VIOLATION
    )
    duplicate_key = {
        **BASE[_S],
        "submission_id": "kasub_kwp02sub00003",
        "causal_root_submission_id": "kasub_kwp02sub00003",
        "idempotency_key": "kwp02-key-1",
    }
    assert _refused(graph, table=_S, **duplicate_key) == (
        UNIQUE_VIOLATION,
        "knowledge_submission_explicit_key",
    )
    _insert(graph, _S, BASE[_S])
    where = "submission_id = 'kasub_kwp02sub00002'"
    # The deferred constraint trigger re-reads the current row: reserved is refused.
    savepoint = graph.begin_nested()
    with pytest.raises(DBAPIError) as refused:
        graph.execute(
            text("SET CONSTRAINTS knowledge.knowledge_submission_is_never_left_reserved IMMEDIATE")
        )
    assert _refusal(refused.value)[0] == CHECK_VIOLATION
    savepoint.rollback()
    assert (
        _refused(
            graph,
            _update(
                _S,
                "submission_state = 'completed', outcome = 'refused', reason = "
                "'source_profile_inactive', result_digest = :digest, completed_at = :now, "
                "subject_id = 'ent_kwp02entity0009'",
                where,
            ),
            digest=DIGEST,
            now=NOW,
        )[0]
        == RESTRICT_VIOLATION
    )
    _accepted(
        graph,
        _update(
            _S,
            "submission_state = 'completed', outcome = 'refused', reason = "
            "'source_profile_inactive', result_digest = :digest, completed_at = :now",
            where,
        ),
        digest=DIGEST,
        now=NOW,
    )
    graph.execute(
        text("SET CONSTRAINTS knowledge.knowledge_submission_is_never_left_reserved IMMEDIATE")
    )
    graph.execute(
        text("SET CONSTRAINTS knowledge.knowledge_submission_is_never_left_reserved DEFERRED")
    )
    assert _refused(graph, _update(_S, "reason = 'capture_archived'", where))[0] == (
        RESTRICT_VIOLATION
    )
    autonomous = {
        **BASE[_S],
        "submission_id": "kasub_kwp02sub00004",
        "origin": "autonomous_submit",
        "authenticated_client_id": CLIENT,
        "idempotency_key": None,
        "source_profile_id": PROFILE,
        "scope_digest": DIGEST,
        "external_run_id": "run-kwp02-1",
        "external_candidate_id": "candidate-1",
        "causal_root_submission_id": "kasub_kwp02sub00004",
    }
    _insert(graph, _S, autonomous)
    again = {
        **autonomous,
        "submission_id": "kasub_kwp02sub00005",
        "causal_root_submission_id": "kasub_kwp02sub00005",
    }
    assert _refused(graph, table=_S, **again) == (
        UNIQUE_VIOLATION,
        "knowledge_submission_autonomous_candidate",
    )


#: The seven R6V-201 cases, each from a private external row holding an excerpt.
_REDACTIONS: Final[tuple[tuple[str, str, tuple[str, str | None] | None], ...]] = (
    ("raise_and_redact", "source_classification = 'restricted_local', excerpt = NULL", None),
    (
        "raise_without_redacting",
        "source_classification = 'restricted_local'",
        (CHECK_VIOLATION, "knowledge_evidence_ref_restricted_has_no_excerpt"),
    ),
    ("redact_without_raising", "excerpt = NULL", (RESTRICT_VIOLATION, None)),
    ("edit_excerpt", "excerpt = 'Net 45 days.'", (RESTRICT_VIOLATION, None)),
    ("lower_rank", "source_classification = 'synthetic_test'", (RESTRICT_VIOLATION, None)),
    (
        "change_digest",
        "excerpt_sha256 = :other, excerpt = NULL, source_classification = 'restricted_local'",
        (RESTRICT_VIOLATION, None),
    ),
    ("change_content_hash", "content_hash = :other", (RESTRICT_VIOLATION, None)),
)


@pytest.mark.database
@pytest.mark.parametrize(("case", "assignments", "refusal"), _REDACTIONS)
def test_restricted_evidence_never_keeps_an_excerpt(
    graph: Connection, case: str, assignments: str, refusal: tuple[str, str | None] | None
) -> None:
    """AC-013 / KLP-R6V-201: excerpt may become NULL exactly in the raise to restricted."""
    where = f"evidence_ref_id = '{EVIDENCE}'"
    sql = _update(_E, assignments, where)
    if refusal is None:
        _accepted(graph, sql)
        row = graph.execute(
            text(
                "SELECT source_classification, excerpt, excerpt_sha256, content_hash "  # noqa: S608
                f"FROM knowledge.knowledge_evidence_refs WHERE {where}"
            )
        ).one()
        assert tuple(row) == ("restricted_local", None, "d" * 64, "c" * 64)
        # Restricted is terminal for the excerpt: NULL never becomes non-NULL again.
        assert _refused(graph, _update(_E, "excerpt = 'Net 30 days.'", where)) == (
            RESTRICT_VIOLATION,
            None,
        )
    else:
        assert _refused(graph, sql, other="0" * 64) == refusal, case


@pytest.mark.database
@pytest.mark.parametrize("kind", ("external_object", "capture", "relationship_memory"))
def test_born_restricted_evidence_of_any_identity_kind_stores_no_excerpt(
    graph: Connection, kind: str
) -> None:
    """KLP-R6V-201: restricted at INSERT with excerpt NULL succeeds; with excerpt, 23514."""
    row: dict[str, Any] = {
        **BASE[_E],
        "source_classification": "restricted_local",
        "excerpt": None,
        "excerpt_sha256": "d" * 64,
    }
    if kind == "capture":
        _accepted(
            graph,
            "INSERT INTO knowledge.captures (capture_id, owner_principal_id, created_at) "
            "VALUES ('cap_kwp02capture01', :principal, :now)",
            principal=PRINCIPAL,
            now=NOW,
        )
        row |= _CAPTURE_SHAPE
    elif kind == "relationship_memory":
        # The memory's own current-version key is DEFERRABLE INITIALLY DEFERRED and
        # this transaction never commits, so a bare memory row is enough here.
        _accepted(
            graph,
            "INSERT INTO knowledge.relationship_memories (memory_id, principal_id, "
            "subject_entity_id, memory_kind, current_version_id, current_version_number, "
            "created_at, updated_at, origin_subject_entity_id) VALUES ('mem_kwp02memory001', "
            ":principal, :entity, 'communication_preference', 'memver_kwp02version01', 1, "
            ":now, :now, :entity)",
            principal=PRINCIPAL,
            entity=ENTITY,
            now=NOW,
        )
        row |= {
            **_CAPTURE_SHAPE,
            "identity_kind": "relationship_memory",
            "capture_id": None,
            "relationship_memory_id": "mem_kwp02memory001",
            "content_origin": "relationship_memory",
        }
    with_excerpt = {**row, "excerpt": "Net 30 days."}
    assert _refused(graph, table=_E, **with_excerpt) == (
        CHECK_VIOLATION,
        "knowledge_evidence_ref_restricted_has_no_excerpt",
    )
    _insert(graph, _E, row)
    stored = graph.execute(
        text(
            "SELECT source_classification, excerpt, excerpt_sha256 FROM "
            "knowledge.knowledge_evidence_refs WHERE evidence_ref_id = 'kaevd_kwp02evid0002'"
        )
    ).one()
    assert tuple(stored) == ("restricted_local", None, "d" * 64)


@pytest.mark.database
def test_evidence_identity_is_immutable_and_controls_are_governed(graph: Connection) -> None:
    where = f"evidence_ref_id = '{EVIDENCE}'"
    assert _refused(graph, _delete(_E, where))[0] == RESTRICT_VIOLATION
    assert _refused(graph, _update(_E, "external_object_id = 'obj-other'", where))[0] == (
        RESTRICT_VIOLATION
    )
    assert _refused(graph, _update(_E, "updated_at = :earlier", where), earlier=EARLIER)[0] == (
        RESTRICT_VIOLATION
    )
    _accepted(
        graph,
        _update(
            _E,
            "availability_state = 'permission_lost', availability_revalidation_pending = true, "
            "access_last_verified_at = :now, updated_at = :later",
            where,
        ),
        now=NOW,
        later=LATER,
    )


@pytest.mark.database
def test_a_checkpoint_only_advances(graph: Connection) -> None:
    """AC-074 (schema slice): binding immutable; version + 1; seal never decreases."""
    _insert(graph, _C, BASE[_C])
    where = "checkpoint_id = 'kdcp_kwp02checkpt01'"
    assert _refused(graph, _delete(_C))[0] == RESTRICT_VIOLATION
    for assignments in (
        "scope_digest = :other, version = 2",
        "checkpoint_kind = 'page_cursor', version = 2",
        "version = 3",
        "version = 2, seal_version = 0",
        "version = 2, updated_at = :earlier",
    ):
        assert (
            _refused(graph, _update(_C, assignments, where), other="b" * 64, earlier=EARLIER)[0]
            == RESTRICT_VIOLATION
        ), assignments
    _accepted(graph, _update(_C, "version = 2, seal_version = 2, private_envelope = 'next'", where))
    assert _refused(graph, _update(_C, "version = 3, seal_version = 1", where))[0] == (
        RESTRICT_VIOLATION
    )


@pytest.mark.database
def test_a_checkpoint_request_completes_once_and_redacts_once(graph: Connection) -> None:
    """AC-093 / KLP-R6A-W3-008: inserted reserved; completion; one redaction; deferred."""
    reserved_completed = {
        **BASE[_R],
        "state": "completed",
        "result_outcome": "refused",
        "result_reason": "source_profile_inactive",
        "completed_at": NOW,
    }
    assert _refused(graph, table=_R, **reserved_completed) == (RESTRICT_VIOLATION, None)
    _insert(graph, _C, BASE[_C])
    _insert(graph, _R, BASE[_R])
    where = "checkpoint_request_id = 'kdcpr_kwp02request1'"
    savepoint = graph.begin_nested()
    with pytest.raises(DBAPIError) as refused:
        graph.execute(
            text(
                "SET CONSTRAINTS knowledge.knowledge_checkpoint_request_is_never_left_reserved "
                "IMMEDIATE"
            )
        )
    assert _refusal(refused.value)[0] == RESTRICT_VIOLATION
    savepoint.rollback()
    assert _refused(graph, _delete(_R))[0] == RESTRICT_VIOLATION
    complete = (
        "state = 'completed', result_outcome = 'advanced', result_reason = 'advanced', "
        "result_checkpoint_id = 'kdcp_kwp02checkpt01', result_checkpoint_version = 1, "
        "result_checkpoint_kind = 'delta_token', result_private_envelope = 'env', "
        "result_seal_version = 1, result_envelope_mac = :mac, completed_at = :now"
    )
    for extra in (", private_token_redacted = true", ", idempotency_key = 'other-key'"):
        assert _refused(graph, _update(_R, complete + extra, where), mac=DIGEST, now=NOW) == (
            RESTRICT_VIOLATION,
            None,
        ), extra
    _accepted(graph, _update(_R, complete, where), mac=DIGEST, now=NOW)
    graph.execute(
        text(
            "SET CONSTRAINTS knowledge.knowledge_checkpoint_request_is_never_left_reserved "
            "IMMEDIATE"
        )
    )
    assert (
        _refused(graph, _update(_R, "result_reason = 'advanced', result_seal_version = 2", where))[
            0
        ]
        == RESTRICT_VIOLATION
    )
    redact = (
        "result_private_envelope = NULL, result_envelope_mac = NULL, private_token_redacted = true"
    )
    assert (
        _refused(graph, _update(_R, redact + ", result_checkpoint_version = 2", where))[0]
        == RESTRICT_VIOLATION
    )
    _accepted(graph, _update(_R, redact, where))
    assert _refused(graph, _update(_R, "private_token_redacted = true", where))[0] == (
        RESTRICT_VIOLATION
    )
