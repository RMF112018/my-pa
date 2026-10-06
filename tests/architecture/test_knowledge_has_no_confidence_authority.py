"""No numeric or banded confidence field authorizes Knowledge canonical state (KLP-AC-023).

KLP-WP-04, unmarked (FAST), routed to repository-checks / validate and
dependency-floor. The schema half is `tests/schema/test_knowledge_assertion_migration.py`
(WP-02); this module is the code half over everything that can admit, promote or
supersede a Knowledge fact.

Canonical state is decided only by the predicate registry, the source profile's
authority ceiling, evidence shape/availability and the Review decision
(R6 sections 5-6, 10). A confidence, score, probability, likelihood, certainty,
band or weight would be a second, caller-influenced authority. This module proves
statically that none exists:

* no column of the fourteen frozen Knowledge tables (matrix `schema_tables`)
  carries a confidence-like token;
* no field of the Knowledge commands (`CreateKnowledgeAssertion`,
  `SubmitKnowledgeAssertion`, `CheckpointKnowledgeDiscovery`) or their MCP
  payload documentation carries one, so no caller can submit one;
* no identifier, attribute, argument, keyword or identifier-shaped string
  constant in the Knowledge modules (the WP-01 domain package, the admission
  policy, the application mapping, the persistence body, the review authority,
  the discovery profiles and the operator CLI) carries one, so the admission
  decision, the Review promotion and the persistence body cannot read one;
* the knowledge Alembic revision spells no such column.

Identifiers are split on `_` and camel case; a token matches when it starts with
one of the stems (`confidence`, `score`, `probabilit`, `likelihood`, `certaint`,
`uncertaint`, `band`, `weight`). The plant test keeps the scan from being vacuous.

What it cannot see: a confidence value smuggled through a free-form JSON payload
key assembled at runtime (the frozen commands refuse unknown fields; the value and
qualifier shapes are predicate-typed), and code outside the listed modules that
never reaches the Knowledge write paths.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

from sqlalchemy import Table

from my_pa.application import commands
from my_pa.infrastructure.persistence import tables

ROOT: Final = Path(__file__).resolve().parents[2]
MATRIX: Final = ROOT / "tests/architecture/klp_implementation_matrix_r6.json"
STEMS: Final = (
    "confidence",
    "score",
    "probabilit",
    "likelihood",
    "certaint",
    "uncertaint",
    "band",
    "weight",
)
KNOWLEDGE_MODULES: Final = (
    *sorted((ROOT / "src/my_pa/domain/knowledge_assertion").glob("*.py")),
    ROOT / "src/my_pa/domain/policy/knowledge_review_authority.py",
    ROOT / "src/my_pa/application/knowledge_assertions.py",
    ROOT / "src/my_pa/infrastructure/persistence/knowledge_assertions.py",
    ROOT / "src/my_pa/bootstrap/knowledge_discovery_profiles.py",
    ROOT / "apps/cli/knowledge_source_profiles.py",
)
KNOWLEDGE_COMMANDS: Final = (
    commands.CreateKnowledgeAssertion,
    commands.SubmitKnowledgeAssertion,
    commands.CheckpointKnowledgeDiscovery,
)
_IDENTIFIER: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_.\-]*")
_CAMEL: Final = re.compile(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])")


def confidence_tokens(identifier: str) -> list[str]:
    """The tokens of `identifier` that name a confidence-like quantity."""
    tokens = [
        token.lower() for part in re.split(r"[_.\-]+", identifier) for token in _CAMEL.findall(part)
    ]
    return [token for token in tokens if token.startswith(STEMS)]


def _identifiers(source: str) -> Iterator[tuple[int, str]]:
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Name):
            yield node.lineno, node.id
        elif isinstance(node, ast.Attribute):
            yield node.lineno, node.attr
        elif isinstance(node, ast.arg):
            yield node.lineno, node.arg
        elif isinstance(node, ast.keyword) and node.arg is not None:
            yield node.value.lineno, node.arg
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            yield node.lineno, node.name
        elif isinstance(node, ast.alias):
            yield getattr(node, "lineno", 0), node.asname or node.name
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _IDENTIFIER.fullmatch(node.value)
        ):
            yield node.lineno, node.value


def offenders(source: str) -> list[str]:
    return [
        f"{name} at line {line}" for line, name in _identifiers(source) if confidence_tokens(name)
    ]


def _knowledge_tables() -> list[Table]:
    names = set(json.loads(MATRIX.read_text(encoding="utf-8"))["schema_tables"])
    found = [
        value
        for value in vars(tables).values()
        if isinstance(value, Table) and value.schema == "knowledge" and value.name in names
    ]
    assert {table.name for table in found} == names
    return found


def test_the_detector_finds_every_confidence_shape_it_claims() -> None:
    planted = {
        "column": "Column('confidence', Numeric)\n",
        "camel": "def admit(matchConfidence: float) -> None: ...\n",
        "attribute": "if facts.score > 0.9: admit()\n",
        "keyword": "decide(probability=0.4)\n",
        "band": "LIKELIHOOD_BAND = 'high'\n",
        "string_key": "payload = {'certainty_band': 'high'}\n",
        "weight": "class EvidenceWeight: ...\n",
        "uncertainty": "x.uncertainty\n",
    }
    for shape, source in planted.items():
        assert offenders(source), shape
    assert not offenders(
        "def decide(authority_ceiling, review_requirement, classification_rank):\n"
        "    '''A confidence score is never read here.'''\n"
        "    return 'abandoned'\n"
    )


def test_no_knowledge_table_column_names_a_confidence() -> None:
    found = _knowledge_tables()
    assert len(found) == 14
    columns = {f"{table.name}.{column.name}" for table in found for column in table.columns}
    assert len(columns) > 150
    assert {column for column in columns if confidence_tokens(column.split(".")[1])} == set()


def test_no_knowledge_command_field_or_payload_key_names_a_confidence() -> None:
    for command in KNOWLEDGE_COMMANDS:
        fields = [field.name for field in dataclasses.fields(command)]
        assert fields, command.__name__
        assert [name for name in fields if confidence_tokens(name)] == [], command.__name__
        documented = json.dumps(getattr(command, "mcp_payload_properties", {}), default=str)
        keys = re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)":', documented)
        assert [key for key in keys if confidence_tokens(key)] == [], command.__name__


def test_no_knowledge_module_reads_or_writes_a_confidence() -> None:
    assert len(KNOWLEDGE_MODULES) >= 15
    found = {
        path.relative_to(ROOT).as_posix(): hits
        for path in KNOWLEDGE_MODULES
        if (hits := offenders(path.read_text(encoding="utf-8")))
    }
    assert found == {}


def test_the_knowledge_revision_spells_no_confidence_column() -> None:
    revisions = sorted((ROOT / "migrations/versions").glob("*_knowledge_assertion_layer.py"))
    assert len(revisions) == 1
    text = revisions[0].read_text(encoding="utf-8")
    assert offenders(text) == []
    # The DDL lives in SQL string literals: scan every word of the file too.
    words = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", text))
    assert "knowledge_assertions" in words
    assert {word for word in words if confidence_tokens(word)} == set()
