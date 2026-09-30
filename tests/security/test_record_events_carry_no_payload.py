"""WP-RE-04 Phase 4C: a Record Event carries no payload (RE-AC-004, 044, 051).

A Record Event says *that* a record changed. It must never say what the record
says. Two halves:

**FAST (source and schema):**

* the stored row and both carriers are the seventeen metadata columns/fields
  -- no narrative, value, body, snapshot or before/after column;
* every static `changed_fields` set an emitter declares (`field_set(...)`
  literals across `src/`) is lower-snake name tokens, and none names a
  narrative field (a memory's statement or structured value, an
  observation's observed text, a ledger's before/after photograph);
* **MR-06:** the Relationship Memory reads an identity correction uses
  (`memory_feed_facts`, `context_link_owner`) select from
  `relationship_memory_versions` only its `classification` and key columns --
  never the statement or the whole row.

**Database:** after representative committed writes carrying distinctive
narrative -- an entity with an alias, a memory created and revised, a merge
that moves both -- no committed feed row contains any of that text in any
column, and every committed `changed_fields` token is a name token.
"""

from __future__ import annotations

import ast
import dataclasses
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text

from my_pa.application.entity_authoring import EntityAuthoringService, NamedValue
from my_pa.application.identity_correction import (
    IdentityCorrectionService,
    MergeCommand,
    MergePreviewCommand,
)
from my_pa.application.relationship_memory import (
    CreateMemoryCommand,
    RelationshipMemoryService,
    ReviseMemoryCommand,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.record_events import CHANGED_FIELD_PATTERN, RecordEvent, RecordEventDraft
from my_pa.domain.relationship.entity import EntityType
from my_pa.domain.relationship.governance import ActorClass
from my_pa.domain.relationship.memory import MemoryKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.tables import record_events
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"
MEMORY_PERSISTENCE: Final = PACKAGE / "infrastructure" / "persistence" / "relationship_memory.py"

METADATA_COLUMNS: Final = frozenset(
    {
        "event_id",
        "principal_id",
        "sequence_number",
        "record_family",
        "record_id",
        "event_kind",
        "record_version",
        "changed_fields",
        "source_capability",
        "source_receipt_id",
        "actor_class",
        "authority",
        "classification",
        "correlation_id",
        "causation_event_id",
        "occurred_at",
        "recorded_at",
    }
)

#: Field names whose *values* are narrative. A `changed_fields` token naming one
#: would announce that the narrative moved -- which a new version id already
#: says -- and invite a consumer to expect it on the event.
NARRATIVE_FIELDS: Final = frozenset(
    {
        "statement",
        "statement_text",
        "structured_value",
        "observed_value",
        "correction_reason",
        "reason",
        "before_state",
        "after_state",
        "payload",
        "body",
    }
)

#: MR-06: what an identity correction may select from `relationship_memory_versions`.
MEMORY_VERSION_COLUMNS_ALLOWED: Final = frozenset(
    {"classification", "memory_version_id", "memory_id"}
)
MEMORY_FEED_READS: Final = ("memory_feed_facts", "context_link_owner")


# ---- FAST: schema and carriers ------------------------------------------------


def test_the_stored_row_is_metadata_only() -> None:
    assert {column.name for column in record_events.columns} == METADATA_COLUMNS


def test_both_carriers_are_metadata_only() -> None:
    assert {field.name for field in dataclasses.fields(RecordEvent)} == METADATA_COLUMNS
    assert {field.name for field in dataclasses.fields(RecordEventDraft)} == (
        METADATA_COLUMNS - {"sequence_number", "recorded_at"}
    )


# ---- FAST: every declared changed_fields set is name tokens --------------------


def _declared_field_sets() -> list[tuple[str, int, tuple[str, ...]]]:
    found: list[tuple[str, int, tuple[str, ...]]] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "field_set"
            ):
                tokens = tuple(
                    arg.value
                    for arg in node.args
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str)
                )
                found.append((path.relative_to(PACKAGE).as_posix(), node.lineno, tokens))
    return found


def test_every_declared_changed_field_is_a_name_token_and_never_narrative() -> None:
    declared = _declared_field_sets()
    assert len(declared) >= 20, "the scan found too few emitter field sets to prove anything"
    bad = [
        (where, line, token)
        for where, line, tokens in declared
        for token in tokens
        if not CHANGED_FIELD_PATTERN.fullmatch(token) or token in NARRATIVE_FIELDS
    ]
    assert not bad, bad


def test_the_field_set_scan_sees_a_narrative_token() -> None:
    """The control: a planted narrative token is reported."""
    planted = ast.parse('field_set("current_version_id", "statement_text")')
    (call,) = (node for node in ast.walk(planted) if isinstance(node, ast.Call))
    tokens = tuple(arg.value for arg in call.args if isinstance(arg, ast.Constant))
    assert set(tokens) & NARRATIVE_FIELDS == {"statement_text"}


# ---- FAST: MR-06, the one-column memory-version read ---------------------------


def _memory_version_reads(tree: ast.Module) -> list[str]:
    """Every way the two feed reads touch `relationship_memory_versions`.

    A column reference is reported as its column name; the table used whole --
    selected, or starred through a column tuple -- is reported as `*`.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name in MEMORY_FEED_READS):
            continue
        for inner in ast.walk(node):
            if (
                isinstance(inner, ast.Attribute)
                and isinstance(inner.value, ast.Attribute)
                and inner.value.attr == "c"
                and isinstance(inner.value.value, ast.Name)
                and inner.value.value.id == "relationship_memory_versions"
            ):
                found.append(inner.attr)
            if isinstance(inner, ast.Call) and getattr(inner.func, "id", None) == "select":
                for argument in inner.args:
                    if isinstance(argument, ast.Starred) or (
                        isinstance(argument, ast.Name)
                        and argument.id == "relationship_memory_versions"
                    ):
                        found.append("*")
    return found


def test_identity_correction_reads_only_the_version_classification() -> None:
    """MR-06 (2): `classification` plus the join keys, and nothing else."""
    reads = _memory_version_reads(ast.parse(MEMORY_PERSISTENCE.read_text(encoding="utf-8")))
    assert "classification" in reads
    assert set(reads) <= MEMORY_VERSION_COLUMNS_ALLOWED, sorted(set(reads))


@pytest.mark.parametrize(
    "planted",
    [
        "select(relationship_memory_versions.c.statement_text)",
        "select(relationship_memory_versions)",
        "select(*_VERSION_COLUMNS)",
    ],
)
def test_the_memory_version_scan_sees_a_wider_read(planted: str) -> None:
    """The control: the statement, or the whole row, is reported."""
    tree = ast.parse(f"def memory_feed_facts(self):\n    return {planted}\n")
    assert not set(_memory_version_reads(tree)) <= MEMORY_VERSION_COLUMNS_ALLOWED


# ---- database: the committed feed holds none of the narrative ------------------

PRINCIPAL: Final = "prn_rcevnopayload0001"
WHEN: Final = datetime(2026, 9, 29, 12, tzinfo=UTC)
SURVIVOR_NAME: Final = "Quillon Narrativewright"
DUPLICATE_NAME: Final = "Quillon Narrativewright Second"
ALIAS_TEXT: Final = "Quilly Secretname"
STATEMENT: Final = "Quillon confided the private detail zephyr-narrative-7731."
REVISED: Final = "Quillon later confided zephyr-narrative-7732 as well."
NARRATIVE: Final = (SURVIVOR_NAME, DUPLICATE_NAME, ALIAS_TEXT, STATEMENT, REVISED, "zephyr")


@contextmanager
def _unit(engine: Engine) -> Iterator[SqlAlchemyUnitOfWork]:
    with SqlAlchemyUnitOfWork(
        engine, audit=SqlAlchemyAuditSink(engine), relationship_memory_enabled=True
    ) as uow:
        yield uow  # type: ignore[misc]


def _context() -> dict[str, Any]:
    return {
        "principal_id": PRINCIPAL,
        "correlation_id": issue_identifier(IdKind.CORRELATION),
        "audit_id": issue_identifier(IdKind.AUDIT),
        "at": WHEN,
    }


def _create_entity(engine: Engine, name: str, key: str, alias: str | None = None) -> str:
    with _unit(engine) as uow:
        admitted = EntityAuthoringService().create(
            uow.entities,
            entity_type=EntityType.PERSON,
            display_name=name,
            aliases=(NamedValue("nickname", alias),) if alias else (),
            identifiers=(),
            reason=None,
            idempotency_key=key,
            **_context(),
        )
    return admitted.receipt.entity_id


def _committed_rows(engine: Engine) -> list[dict[str, Any]]:
    with engine.connect() as connection:
        return [
            json.loads(row[0])
            for row in connection.execute(
                text(
                    "SELECT row_to_json(e)::text FROM knowledge.record_events e "
                    "WHERE principal_id = :p ORDER BY sequence_number"
                ),
                {"p": PRINCIPAL},
            )
        ]


@pytest.mark.database
def test_the_committed_feed_carries_none_of_the_narrative(migrated_engine: Engine) -> None:
    engine = migrated_engine
    survivor = _create_entity(engine, SURVIVOR_NAME, "nopayload-survivor")
    duplicate = _create_entity(engine, DUPLICATE_NAME, "nopayload-duplicate", alias=ALIAS_TEXT)
    service = RelationshipMemoryService()
    with _unit(engine) as uow:
        memory = service.create(
            uow.relationship_memory,
            CreateMemoryCommand(
                principal_id=PRINCIPAL,
                subject_entity_id=duplicate,
                memory_kind=MemoryKind.GENERAL_NOTE,
                statement=STATEMENT,
                structured_value=None,
                context_links=(),
                pinned=False,
                observed_at=None,
                effective_from=None,
                effective_to=None,
                idempotency_key="nopayload-memory",
            ),
            at=WHEN,
        ).receipt.memory_id
    with _unit(engine) as uow:
        service.revise(
            uow.relationship_memory,
            ReviseMemoryCommand(
                principal_id=PRINCIPAL,
                memory_id=memory,
                expected_version=1,
                statement=REVISED,
                memory_kind=None,
                structured_value=None,
                context_links=(),
                pinned=None,
                observed_at=None,
                effective_from=None,
                effective_to=None,
                correction_reason="zephyr reworded",
                idempotency_key="nopayload-revise",
            ),
            at=WHEN,
            current_kind=MemoryKind.GENERAL_NOTE,
        )
    with _unit(engine) as uow:
        identity = IdentityCorrectionService(
            uow.entities, uow.relationship_memory, stager=uow.record_events
        )
        report = identity.preview(
            MergePreviewCommand(
                principal_id=PRINCIPAL,
                survivor_entity_id=survivor,
                expected_survivor_version=1,
                merged_away=((duplicate, 1),),
                reason="two synthetic records describe one synthetic person",
            ),
            at=WHEN,
            requested_by=PRINCIPAL,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    with _unit(engine) as uow:
        IdentityCorrectionService(
            uow.entities, uow.relationship_memory, stager=uow.record_events
        ).apply(
            MergeCommand(
                principal_id=PRINCIPAL,
                preview_id=report.preview.preview_id,
                preview_digest=report.preview.preview_digest,
                idempotency_key="nopayload-merge",
                reason="two synthetic records describe one synthetic person",
            ),
            at=WHEN,
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=issue_identifier(IdKind.AUDIT),
            performed_by=PRINCIPAL,
            actor_class=ActorClass.USER,
            has_operator_authority=True,
        )
    rows = _committed_rows(engine)
    families = {row["record_family"] for row in rows}
    assert {"entity", "entity_alias", "relationship_memory"} <= families
    serialized = json.dumps(rows).lower()
    for narrative in NARRATIVE:
        assert narrative.lower() not in serialized, narrative
    token = re.compile(CHANGED_FIELD_PATTERN.pattern)
    for row in rows:
        assert set(row) == METADATA_COLUMNS
        assert all(token.fullmatch(name) for name in row["changed_fields"])
        assert not set(row["changed_fields"]) & NARRATIVE_FIELDS
