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
* **RECR-AC-006 (MR-R09):** the feed reader's routing reach is keys only --
  of each routed family's child table it names the primary key and the one
  owner column (the partition comes through `partition_criterion`), never a
  value, a narrative column or the whole row.

**Database:** after representative committed writes carrying distinctive
narrative -- an entity with an alias, a memory created and revised, a merge
that moves both -- no committed feed row contains any of that text in any
column, and every committed `changed_fields` token is a name token.

**WP-RE-08 (RE-AC-091):** the capture builders take only ids, versions, enums,
tokens, times and typed non-narrative facts -- never text, a label, a digest or
a key (G-3b-2) -- and a capture created with a sentinel text, label and Project
and revised with a second sentinel text, plus a Task comment with a sentinel
body, commits no sentinel, no digest of either text, no idempotency key and no
request id to any feed column (G-3b-3).
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import inspect
import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text
from tests.database.test_task_record_events import Runtime

from my_pa.application.commands import (
    CreateCapture,
    CreateProject,
    CreateTask,
    CreateTaskComment,
    ReviseCapture,
)
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
from my_pa.domain.record_events import (
    CHANGED_FIELD_PATTERN,
    CaptureVersionFacts,
    RecordEvent,
    RecordEventDraft,
    capture_changed_fields,
    capture_record_event,
    task_comment_record_event,
)
from my_pa.domain.relationship.entity import EntityType
from my_pa.domain.relationship.governance import ActorClass
from my_pa.domain.relationship.memory import MemoryKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.domain.task.lifecycle import TaskOriginKind
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
        # WP-RE-08 (G-3b-1, MR-11): capture text, its digests, and the
        # admission's own request identity are never tokens.
        "content",
        "text",
        "content_sha256",
        "payload_sha256",
        "request_digest",
        "idempotency_key",
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


# ---- FAST: MR-06 extended to the WP-RE-06 feed reader -------------------------

#: The feed reader's OD-8 (i) predicate may name, per memory table, only these
#: columns: the join keys, `current_version_id` and the version `classification`.
READER_MEMORY_COLUMNS_ALLOWED: Final = {
    "relationship_memories": frozenset({"memory_id", "current_version_id"}),
    "relationship_memory_versions": frozenset({"memory_version_id", "classification"}),
}
FEED_READER: Final = PACKAGE / "infrastructure" / "persistence" / "record_events.py"


def _reader_memory_reads(tree: ast.Module) -> dict[str, set[str]]:
    """Every column of a memory table the reader names; a whole-table select is `*`."""
    found: dict[str, set[str]] = {table: set() for table in READER_MEMORY_COLUMNS_ALLOWED}
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "c"
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id in found
        ):
            found[node.value.value.id].add(node.attr)
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr == "c"
            and isinstance(node.value.value, ast.Name)
            and node.value.value.id in found
        ):
            key = node.slice
            named = key.value if isinstance(key, ast.Constant) else "*"
            found[node.value.value.id].add(str(named))
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "select":
            for argument in node.args:
                if isinstance(argument, ast.Name) and argument.id in found:
                    found[argument.id].add("*")
                if isinstance(argument, ast.Starred):
                    for inner in ast.walk(argument.value):
                        if isinstance(inner, ast.Name) and inner.id in found:
                            found[inner.id].add("*")
    return found


def test_the_feed_reader_reads_only_memory_keys_and_the_version_classification() -> None:
    """MR-06, extended (WP-RE-06): the OD-8 predicate's one-column reach."""
    reads = _reader_memory_reads(ast.parse(FEED_READER.read_text(encoding="utf-8")))
    assert "classification" in reads["relationship_memory_versions"]
    assert "current_version_id" in reads["relationship_memories"]
    for table, allowed in READER_MEMORY_COLUMNS_ALLOWED.items():
        assert reads[table] <= allowed, (table, sorted(reads[table]))


@pytest.mark.parametrize(
    "planted",
    [
        "select(relationship_memory_versions.c.statement_text)",
        "select(relationship_memories.c.subject_entity_id)",
        "select(relationship_memory_versions)",
        "select(*(relationship_memories.c[name] for name in NAMES))",
        'relationship_memory_versions.c["statement_text"] == 1',
    ],
)
def test_the_feed_reader_scan_sees_a_wider_read(planted: str) -> None:
    """The control: a statement, another column, or the whole row is reported."""
    reads = _reader_memory_reads(ast.parse(f"def page(self):\n    return {planted}\n"))
    assert any(
        not reads[table] <= allowed for table, allowed in READER_MEMORY_COLUMNS_ALLOWED.items()
    )


# ---- FAST: MR-12, the one-column capture reach of the feed reader --------------

#: WP-RE-08 (OD-W8-4, ratified as MR-12): the reader's capture predicate may name,
#: per capture table, only the join keys and the version `classification` --
#: through the table itself or any alias of it. The partition column is reached
#: through `partition_criterion`, never named here.
READER_CAPTURE_COLUMNS_ALLOWED: Final = {
    "capture_versions": frozenset({"capture_id", "version_number", "classification"}),
    "captures": frozenset({"capture_id"}),
}


def _capture_aliases(tree: ast.Module) -> dict[str, str]:
    """Every name bound to a capture table or to an `.alias(...)` of one."""
    aliases = {table: table for table in READER_CAPTURE_COLUMNS_ALLOWED}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for inner in ast.walk(value):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "alias"
                and isinstance(inner.func.value, ast.Name)
                and inner.func.value.id in READER_CAPTURE_COLUMNS_ALLOWED
            ):
                for target in targets:
                    if isinstance(target, ast.Name):
                        aliases[target.id] = inner.func.value.id
    return aliases


def _reader_capture_reads(tree: ast.Module) -> dict[str, set[str]]:
    """Every column of a capture table the reader names; a whole-table read is `*`."""
    aliases = _capture_aliases(tree)
    found: dict[str, set[str]] = {table: set() for table in READER_CAPTURE_COLUMNS_ALLOWED}

    def table_of(node: ast.AST) -> str | None:
        return aliases.get(node.id) if isinstance(node, ast.Name) else None

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr in {"c", "columns"}
            and (table := table_of(node.value.value)) is not None
        ):
            found[table].add(node.attr)
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr in {"c", "columns"}
            and (table := table_of(node.value.value)) is not None
        ):
            key = node.slice
            found[table].add(str(key.value) if isinstance(key, ast.Constant) else "*")
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "select":
            for argument in node.args:
                if (table := table_of(argument)) is not None:
                    found[table].add("*")
                if isinstance(argument, ast.Starred):
                    for inner in ast.walk(argument.value):
                        if (table := table_of(inner)) is not None:
                            found[table].add("*")
    return found


def test_the_feed_reader_reads_only_capture_keys_and_the_version_classification() -> None:
    """MR-12: the capture predicate's one-column reach, through every alias."""
    reads = _reader_capture_reads(ast.parse(FEED_READER.read_text(encoding="utf-8")))
    assert "classification" in reads["capture_versions"], "the scan found no capture reach"
    for table, allowed in READER_CAPTURE_COLUMNS_ALLOWED.items():
        assert reads[table] <= allowed, (table, sorted(reads[table]))


@pytest.mark.parametrize(
    "planted",
    [
        "def page(self):\n    return select(capture_versions.c.content)\n",
        "def page(self):\n    return select(capture_versions)\n",
        'def page(self):\n    return capture_versions.c["content_sha256"] == 1\n',
        "_A = cast(Table, capture_versions.alias('a'))\n"
        "def page(self):\n    return select(_A.c.content)\n",
        "_A = capture_versions.alias('a')\ndef page(self):\n    return select(*_A.c)\n",
        "_A = capture_versions.alias('a')\ndef page(self):\n    return select(_A)\n",
        "def page(self):\n    return select(captures.c.owner_principal_id)\n",
    ],
)
def test_the_capture_reader_scan_sees_a_wider_read(planted: str) -> None:
    """The control: the text, a digest, another column or a whole row is reported."""
    reads = _reader_capture_reads(ast.parse(planted))
    assert any(
        not reads[table] <= allowed for table, allowed in READER_CAPTURE_COLUMNS_ALLOWED.items()
    )


# ---- RECR-AC-006: the routing reach is keys only (MR-R09) -------------------------

#: Of each routed family's child table, what the feed reader may name: the
#: primary key the event's `record_id` names, the one owner column the routing
#: reference is read from, and the partition column (reached through
#: `partition_criterion`, so normally never named here at all).
READER_ROUTING_COLUMNS_ALLOWED: Final = {
    "task_comments": frozenset({"comment_id", "task_id", "principal_id"}),
    "constraint_categories": frozenset({"category_id", "project_id", "principal_id"}),
    "entity_external_identifiers": frozenset({"identifier_id", "entity_id", "principal_id"}),
    "entity_aliases": frozenset({"alias_id", "entity_id", "principal_id"}),
    "entity_assignments": frozenset({"assignment_id", "entity_id", "principal_id"}),
    "entity_relationships": frozenset({"relationship_id", "from_entity_id", "principal_id"}),
    "entity_observations": frozenset({"observation_id", "entity_id", "principal_id"}),
    "entity_names": frozenset({"entity_name_id", "entity_id", "principal_id"}),
    "entity_addresses": frozenset({"entity_address_id", "entity_id", "principal_id"}),
    "entity_communication_methods": frozenset(
        {"communication_method_id", "entity_id", "principal_id"}
    ),
    "entity_project_participations": frozenset(
        {"participation_id", "participant_entity_id", "principal_id"}
    ),
    "entity_person_organization_affiliations": frozenset(
        {"affiliation_id", "person_entity_id", "principal_id"}
    ),
}


def _reader_routing_reads(tree: ast.Module) -> dict[str, set[str]]:
    """Every column of a routing table the reader names; a whole-table read is `*`.

    Aliases are followed as `_capture_aliases` follows them, so `t = table.alias()`
    cannot hide a wider read.
    """
    aliases = {table: table for table in READER_ROUTING_COLUMNS_ALLOWED}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            targets, value = [node.target], node.value
        else:
            continue
        for inner in ast.walk(value):
            if (
                isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "alias"
                and isinstance(inner.func.value, ast.Name)
                and inner.func.value.id in READER_ROUTING_COLUMNS_ALLOWED
            ):
                for target in targets:
                    if isinstance(target, ast.Name):
                        aliases[target.id] = inner.func.value.id
    found: dict[str, set[str]] = {table: set() for table in READER_ROUTING_COLUMNS_ALLOWED}

    def table_of(node: ast.AST) -> str | None:
        return aliases.get(node.id) if isinstance(node, ast.Name) else None

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr in {"c", "columns"}
            and (table := table_of(node.value.value)) is not None
        ):
            found[table].add(node.attr)
        if (
            isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Attribute)
            and node.value.attr in {"c", "columns"}
            and (table := table_of(node.value.value)) is not None
        ):
            key = node.slice
            found[table].add(str(key.value) if isinstance(key, ast.Constant) else "*")
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "select":
            for argument in node.args:
                if (table := table_of(argument)) is not None:
                    found[table].add("*")
                if isinstance(argument, ast.Starred):
                    for inner in ast.walk(argument.value):
                        if (table := table_of(inner)) is not None:
                            found[table].add("*")
    return found


def test_the_feed_reader_routing_reads_only_keys() -> None:
    """RECR-AC-006: every routing table is reached, and only for its keys."""
    reads = _reader_routing_reads(ast.parse(FEED_READER.read_text(encoding="utf-8")))
    unreached = sorted(table for table, columns in reads.items() if not columns)
    assert not unreached, f"the scan found no routing reach into {unreached}"
    for table, allowed in READER_ROUTING_COLUMNS_ALLOWED.items():
        assert reads[table] <= allowed, (table, sorted(reads[table]))


@pytest.mark.parametrize(
    "planted",
    [
        "def page(self):\n    return select(task_comments.c.body)\n",
        "def page(self):\n    return select(task_comments)\n",
        'def page(self):\n    return entity_names.c["display_value"] == 1\n',
        "def page(self):\n    return select(entity_relationships.c.to_entity_id)\n",
        "def page(self):\n"
        "    return select(entity_person_organization_affiliations.c.organization_entity_id)\n",
        "_A = entity_observations.alias('a')\n"
        "def page(self):\n    return select(_A.c.observed_value)\n",
        "_A = entity_aliases.alias('a')\ndef page(self):\n    return select(*_A.c)\n",
    ],
)
def test_the_routing_reach_scan_sees_a_wider_read(planted: str) -> None:
    """The control: a payload column, another endpoint, or a whole row is reported."""
    reads = _reader_routing_reads(ast.parse(planted))
    assert any(
        not reads[table] <= allowed for table, allowed in READER_ROUTING_COLUMNS_ALLOWED.items()
    )


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


# ---- WP-RE-08 G-3b-2 (FAST): the capture builders take no narrative ------------

#: Every parameter a capture builder may take: identifiers, versions, enums,
#: tokens, times, correlation, and the typed non-narrative version facts. A
#: `text`, `content`, `body`, `display_label`, `*_sha256` or key parameter is
#: outside it by construction.
CAPTURE_BUILDER_PARAMETERS_ALLOWED: Final = frozenset(
    {
        "principal_id",
        "capture_id",
        "event_kind",
        "version_number",
        "changed_fields",
        "capability",
        "classification",
        "occurred_at",
        "receipt_id",
        "correlation_id",
        "prior",
        "written",
        "label_recorded",
        "project_bound",
        # WP-RE-08 8C: the comment builder.
        "comment_id",
        "actor",
    }
)
CAPTURE_FACT_FIELDS_ALLOWED: Final = frozenset(
    {"classification", "processing_policy", "client_created_at", "occurred_at", "character_count"}
)
CAPTURE_BUILDERS: Final = (
    capture_record_event,
    capture_changed_fields,
    task_comment_record_event,
)


def test_the_capture_builders_take_only_allow_listed_parameters() -> None:
    for builder in CAPTURE_BUILDERS:
        parameters = set(inspect.signature(builder).parameters)
        assert parameters <= CAPTURE_BUILDER_PARAMETERS_ALLOWED, (
            builder.__name__,
            sorted(parameters - CAPTURE_BUILDER_PARAMETERS_ALLOWED),
        )
    facts = {field.name for field in dataclasses.fields(CaptureVersionFacts)}
    assert facts == CAPTURE_FACT_FIELDS_ALLOWED


@pytest.mark.parametrize(
    "planted", ["text", "content", "display_label", "content_sha256", "idempotency_key", "body"]
)
def test_the_builder_allow_list_refuses_a_narrative_parameter(planted: str) -> None:
    """The control: each narrative-bearing name is outside the allow-list."""
    assert planted not in CAPTURE_BUILDER_PARAMETERS_ALLOWED
    assert planted not in CAPTURE_FACT_FIELDS_ALLOWED


# ---- WP-RE-08 G-3b-3 (database): the capture sentinel sweep --------------------

CAPTURE_TEXT: Final = "Sentinel wp08 capture text quartzmoth-5521."
CAPTURE_REVISED: Final = "Sentinel wp08 revised text quartzmoth-5522."
CAPTURE_LABEL: Final = "Sentinel label quartzmoth-5523"
CAPTURE_PROJECT: Final = "Sentinel project quartzmoth-5524"
COMMENT_BODY: Final = "Sentinel comment body quartzmoth-5525."


@pytest.mark.database
def test_the_committed_capture_feed_carries_no_text_label_digest_or_key(
    disposable_database: str,
) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    runtime = Runtime(disposable_database)
    try:
        project = runtime.ok(
            CreateProject(name=CAPTURE_PROJECT, idempotency_key="wp08-sweep-project"),
            principal_id=principal,
        )
        created = runtime.ok(
            CreateCapture(
                text=CAPTURE_TEXT,
                idempotency_key="wp08-sweep-create-key",
                project_id=project["project_id"],
                display_label=CAPTURE_LABEL,
            ),
            principal_id=principal,
        )
        revised = runtime.ok(
            ReviseCapture(
                capture_id=created["capture_id"],
                text=CAPTURE_REVISED,
                idempotency_key="wp08-sweep-revise-key",
            ),
            principal_id=principal,
        )
        task = runtime.ok(
            CreateTask(
                title="Synthetic wp08 sweep task",
                idempotency_key="wp08-sweep-task",
                origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
            ),
            principal_id=principal,
        )
        runtime.ok(
            CreateTaskComment(
                task_id=task["task"]["task_id"],
                body=COMMENT_BODY,
                idempotency_key="wp08-sweep-comment-key",
            ),
            principal_id=principal,
        )
        with runtime.work_engine.connect() as connection:
            rows = [
                json.loads(row[0])
                for row in connection.execute(
                    text(
                        "SELECT row_to_json(e)::text FROM knowledge.record_events e "
                        "WHERE principal_id = :p ORDER BY sequence_number"
                    ),
                    {"p": principal},
                )
            ]
            request_ids = list(
                connection.execute(
                    text(
                        "SELECT request_id FROM knowledge.capture_submissions "
                        "WHERE principal_id = :p"
                    ),
                    {"p": principal},
                ).scalars()
            )
    finally:
        runtime.close()
    captures = [row for row in rows if row["record_family"] == "capture"]
    assert [row["event_kind"] for row in captures] == ["created", "updated"]
    comments = [row for row in rows if row["record_family"] == "task_comment"]
    assert len(comments) == 1
    assert len(request_ids) == 2
    serialized = json.dumps(rows).lower()
    forbidden = (
        CAPTURE_TEXT,
        CAPTURE_REVISED,
        CAPTURE_LABEL,
        CAPTURE_PROJECT,
        COMMENT_BODY,
        "wp08-sweep-comment-key",
        "quartzmoth",
        str(created["content_sha256"]),
        str(revised["content_sha256"]),
        hashlib.sha256(CAPTURE_TEXT.encode("utf-8")).hexdigest(),
        hashlib.sha256(CAPTURE_REVISED.encode("utf-8")).hexdigest(),
        "wp08-sweep-create-key",
        "wp08-sweep-revise-key",
        *request_ids,
    )
    for value in forbidden:
        assert value.lower() not in serialized, value
    token = re.compile(CHANGED_FIELD_PATTERN.pattern)
    for row in (*captures, *comments):
        assert set(row) == METADATA_COLUMNS
        assert all(token.fullmatch(name) for name in row["changed_fields"])
        assert not set(row["changed_fields"]) & NARRATIVE_FIELDS


# ---- KLP-WP-03 (KLP-AC-044): Knowledge Assertion events are metadata only ---------

#: Knowledge columns that hold a value, an excerpt or a digest of either. None is
#: ever a token, and none reaches the explicit-create event builder.
KNOWLEDGE_NARRATIVE: Final = frozenset(
    {
        "value_text",
        "value_datetime",
        "qualifier_json",
        "normalized_value_sha256",
        "assertion_fingerprint",
        "excerpt",
        "excerpt_sha256",
        "content_hash",
        "request_digest",
        "idempotency_key",
    }
)
KNOWLEDGE_SENTINEL: Final = "KNOWLEDGE-SENTINEL-VALUE-zq81"


def test_the_knowledge_mapping_tokens_are_names_and_never_narrative() -> None:
    from my_pa.domain.knowledge_assertion.provenance import KNOWLEDGE_MUTATION_EVENTS

    for event in KNOWLEDGE_MUTATION_EVENTS.values():
        for token in event.changed_fields:
            assert CHANGED_FIELD_PATTERN.fullmatch(token), token
            assert token not in NARRATIVE_FIELDS | KNOWLEDGE_NARRATIVE, token


def _knowledge_draft_attributes(source: str) -> set[str]:
    """Every attribute name read inside the module's `RecordEventDraft.issue` calls."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "issue"
        ):
            names.update(inner.attr for inner in ast.walk(node) if isinstance(inner, ast.Attribute))
    return names


def test_the_knowledge_event_builder_reads_no_value_or_excerpt() -> None:
    source = (PACKAGE / "infrastructure" / "persistence" / "knowledge_assertions.py").read_text(
        encoding="utf-8"
    )
    read = _knowledge_draft_attributes(source)
    assert read, "the scan found no Knowledge event builder"
    assert not read & KNOWLEDGE_NARRATIVE, sorted(read & KNOWLEDGE_NARRATIVE)


def test_the_knowledge_builder_scan_sees_a_value_read() -> None:
    """The control: a planted value read inside a draft is reported."""
    planted = "RecordEventDraft.issue(record_id=created.assertion_id, x=request.value_text)\n"
    assert "value_text" in _knowledge_draft_attributes(planted)


@pytest.mark.database
def test_the_committed_knowledge_feed_carries_no_value(disposable_database: str) -> None:
    from tests.database.test_knowledge_assertion_repository import (
        KnowledgeRuntime,
        capture_evidence,
        new_principal,
    )

    runtime = KnowledgeRuntime(disposable_database)
    try:
        principal = new_principal()
        capture_id, digest = runtime.capture(principal, "nopayload")
        created = runtime.create(
            principal,
            "klp03-nopayload",
            value=f"Requirement {KNOWLEDGE_SENTINEL}",
            evidence=(capture_evidence(capture_id, digest),),
        )
        with runtime.engine.connect() as connection:
            rows = [
                str(row)
                for row in connection.execute(
                    text(
                        "SELECT row_to_json(e)::text FROM knowledge.record_events e "
                        "WHERE principal_id = :p AND record_family = 'knowledge_assertion'"
                    ),
                    {"p": principal},
                ).scalars()
            ]
            normalized = connection.execute(
                text(
                    "SELECT normalized_value_sha256, assertion_fingerprint "
                    "FROM knowledge.knowledge_assertions WHERE assertion_id = :a"
                ),
                {"a": created["assertion_id"]},
            ).one()
    finally:
        runtime.close()
    assert len(rows) == 1
    for forbidden in (
        KNOWLEDGE_SENTINEL,
        digest,
        normalized[0],
        normalized[1],
        "klp03-nopayload",
        hashlib.sha256(KNOWLEDGE_SENTINEL.encode()).hexdigest(),
    ):
        assert forbidden not in rows[0]
    event = json.loads(rows[0])
    assert event["changed_fields"] == ["classification", "epistemic_status", "lifecycle", "value"]
    assert event["source_receipt_id"] == created["mutation_id"]
