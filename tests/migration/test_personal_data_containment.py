"""The personal-data claim, enforced rather than asserted.

`redaction.py` detects machine-shaped identifiers -- mail addresses, telephone
numbers, home-directory paths, the local account name -- and says plainly that a
free-text personal name is not pattern-detectable. Until now the rest of the
claim rested on a sentence about construction: "no query in the harness reads a
row value into its output". That sentence is true, and it was checked by nobody.

Two mechanisms replace it, and they work in opposite directions.

*A closed vocabulary over the machine-readable evidence.* Every string in
`reconciliation.json` has to be a member of a vocabulary derived from the
disposition registry, the generated target DDL, the control plane's own
declaration, and the literals in the generator's source -- or else match one of
a few tightly specified shapes (digest, UUID, Alembic revision, ISO timestamp,
repo-relative path, identity sequence name). This is a whitelist, and that is
the point: a blacklist cannot recognise a personal name, but a whitelist does
not need to, because a leaked value simply will not be in the vocabulary. A
failure names the JSON path and the offending string's *shape*, never the string
itself, so the failure does not commit the disclosure it is reporting.

*A schema-level proof that the control plane cannot hold content.* Every column
of `migration_control` is classified into identifier, hash, count, timestamp,
flag, enum-like code, or object name. A column that fits none of those fails.
`quarantine_records` records a refused row by table, column, code, and key hash
and has no column for the value at all; the test is what keeps that true when
somebody later reaches for a `sample_value` or an `error_detail`.

**The markdown report is generated from the same record**, and that is checked
rather than said. `scripts/migration/reconcile.py` builds one `Reconciliation`
and renders it twice: `reconciliation.as_dict` for the JSON and
`reconciliation_report.render` for `RECONCILIATION.md`. `as_dict` is
`dataclasses.asdict`, so the JSON is a total encoding of the record's fields;
rebuilding the record from the committed JSON and re-rendering reproduces the
committed markdown byte-for-byte. So the vocabulary guarantee reaches the
human-readable artefact too, and what it does not cover there is the fixed
English prose the renderer emits from its own source.

Residual gaps, stated rather than papered over:

- The legacy file's *sibling* names are admitted by prefix. They are names on
  the owner's disk, not repository facts, so the rule is "starts with the bound
  source file name, then filename-safe characters". A personal name inside a
  backup file name would pass.
- The prose in the criteria statements and in `RECONCILIATION.md` is admitted
  because it is a literal in the generator's source. It is covered by code
  review, not by this test.
- The vocabulary is large (thousands of legacy column names), so a leaked value
  that happens to equal a schema identifier would be admitted.
- Non-string JSON scalars are not checked. A count cannot carry a name.
- The control-plane classification is about column *roles*: it catches a new
  column that could hold content, not a future misuse of an existing one.
"""

from __future__ import annotations

import ast
import json
import re
import sys
import types
import typing
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from pathlib import Path
from typing import Any, cast

import pytest
from sqlalchemy import Engine, text

from my_pa.infrastructure.migration import (
    control_plane,
    reconciliation,
    reconciliation_report,
    redaction,
)
from my_pa.infrastructure.migration.generator import (
    PROVENANCE_COLUMNS,
    SOURCE_ROW_HASH_COLUMN,
    SURROGATE_KEY_COLUMN,
)
from my_pa.infrastructure.migration.identifiers import target_name

ROOT = Path(__file__).resolve().parents[2]

EVIDENCE = ROOT / "evidence" / "migration" / "phase-10-reconciliation" / "reconciliation.json"
REGISTRY = ROOT / "migrations" / "data" / "disposition_registry.json"
IDENTIFIER_MAP = ROOT / "migrations" / "data" / "identifier_map.json"
TARGET_TABLES = ROOT / "migrations" / "sql" / "target_tables.up.sql"
SOURCE_IDENTITY = ROOT / "docs" / "migration" / "governance" / "source-read-only-identity.json"
VERSIONS = ROOT / "migrations" / "versions"

#: The generated DDL, one quoted identifier per line, is where the target's
#: table and column names come from. Reading the applied SQL rather than the
#: live catalogue keeps this in the FAST tier and keeps it true in CI, whose
#: PostgreSQL service is empty.
_CREATE_TABLE = re.compile(r'^CREATE TABLE "([^"]+)"\."([^"]+)"', re.MULTILINE)
_COLUMN = re.compile(r'^    "([^"]+)"', re.MULTILINE)
_REVISION = re.compile(r'^revision(?:: str)? = "([0-9a-f]+)"', re.MULTILINE)

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\+00:00|Z)$")
_DECISION = re.compile(r"^(?:OD|OP|P10)-[A-Z0-9-]+$")

#: A path long enough to be a value rather than a name is never asked of the
#: filesystem: `Path.exists` on arbitrary text is a syscall, not a match.
_MAX_PATH_LENGTH = 200


def _read(path: Path) -> dict[str, Any]:
    document: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return document


def _literals_and_templates(*functions: str) -> tuple[set[str], list[re.Pattern[str]]]:
    """The string literals a generator function emits, and its f-string shapes.

    A criterion's `statement` is a plain literal and its `detail` is an f-string
    interpolating counts, so both are derivable from the source of
    `reconciliation.evaluate` instead of restated here. Deriving them is what
    makes this a whitelist of what the *generator* can say rather than a list of
    what somebody remembered it saying. Docstrings are skipped: they are prose
    about the function, not output.
    """
    module = ast.parse(
        Path(reconciliation.__file__).read_text(encoding="utf-8"),
        filename=reconciliation.__file__,
    )
    literals: set[str] = set()
    templates: list[re.Pattern[str]] = []
    for name in functions:
        function = next(
            node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == name
        )
        body = function.body
        if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        for statement in body:
            for node in ast.walk(statement):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    literals.add(node.value)
                elif isinstance(node, ast.JoinedStr):
                    templates.append(_template(node))
    return literals, templates


def _template(node: ast.JoinedStr) -> re.Pattern[str]:
    """An f-string as a regex, with every interpolation required to be a count.

    Deliberately narrow. If a future criterion interpolates something that is
    not an integer, the template stops matching and the change has to be
    acknowledged rather than absorbed.
    """
    parts = []
    for value in node.values:
        if isinstance(value, ast.Constant):
            parts.append(re.escape(str(value.value)))
        else:
            parts.append(r"[\d,]+")
    return re.compile("^" + "".join(parts) + "$")


class Vocabulary:
    """Every string the reconciliation evidence is allowed to contain."""

    def __init__(self) -> None:
        registry = _read(REGISTRY)
        identifiers = _read(IDENTIFIER_MAP)
        ddl = TARGET_TABLES.read_text(encoding="utf-8")

        self.schemas = set(reconciliation.ALL_SCHEMAS)
        self.objects: set[str] = {table.name for table in control_plane.METADATA.tables.values()}
        self.columns: set[str] = {
            column.name
            for table in control_plane.METADATA.tables.values()
            for column in table.columns
        }
        self.codes: set[str] = set()

        for entry in (*registry["entries"], *registry["absent_from_source"]):
            self.objects.add(entry["legacy_object"])
            self.objects.add(target_name(entry["legacy_object"]))
            self.codes.add(entry["planning_disposition"])
            if "target_schema" in entry:
                self.schemas.add(entry["target_schema"])
                self.codes.add(entry["object_type"])
                self.codes.add(entry["target_treatment"])
                # `<phase_id>:<primary_domain>`; the prefix is what the report prints.
                self.codes.add(entry["ordering_group"].split(":", 1)[0])

        for schema, table in _CREATE_TABLE.findall(ddl):
            self.schemas.add(schema)
            self.objects.add(table)
        self.columns.update(_COLUMN.findall(ddl))
        self.columns.update(name for name, _ in PROVENANCE_COLUMNS)
        self.columns.update({SOURCE_ROW_HASH_COLUMN, SURROGATE_KEY_COLUMN})

        for rename in identifiers["renames"]:
            # A renamed identifier may be a column, an index, or a constraint;
            # the report prints the legacy name beside the target one, and the
            # quarantine ledger names source columns the DDL renamed away.
            self.columns.add(rename["original"])
            self.columns.add(rename["shortened"])
            self.objects.add(rename["owner"])
            self.codes.add(rename["object_kind"])

        for enumeration in (
            control_plane.RunStatus,
            control_plane.PhaseStatus,
            control_plane.TableState,
            control_plane.QuarantineCode,
            control_plane.AuditEvent,
        ):
            self.codes.update(member.value for member in enumeration)
        self.codes.update(name for name, _ in redaction.patterns())
        self.codes.update(reconciliation.DEPARTURE_DECISION.values())
        self.codes.update(reconciliation.WAIVED_QUARANTINE_CODES.values())
        self.codes.update(
            {
                reconciliation.PASSED,
                reconciliation.FAILED,
                reconciliation.WAIVED,
                reconciliation.UNEVALUATED,
                reconciliation.PASSED_WITH_WAIVERS,
            }
        )

        self.labels, self.templates = _literals_and_templates("evaluate", "as_dict")
        self.labels.update(reconciliation.NOT_CREATED_REASONS.values())
        self.labels.update(reconciliation.ASSERTED_EMPTY_TREATMENTS.values())
        self.labels.update(reconciliation.OD_008_TREATMENT.values())

        sources = "\n".join(p.read_text(encoding="utf-8") for p in VERSIONS.glob("*.py"))
        self.revisions = set(_REVISION.findall(sources))
        self.decisions = {value for value in self.labels | self.codes if _DECISION.match(value)}
        self.source_file = str(_read(SOURCE_IDENTITY)["legacy_source"]["historical_filename"])
        self.sibling = re.compile(re.escape(self.source_file) + r"[A-Za-z0-9._-]*$")

        self.names = self.schemas | self.objects | self.columns | self.codes

    def __len__(self) -> int:
        return len(self.names | self.labels | self.revisions)

    def _is_sequence(self, tail: str) -> bool:
        """`<table>_<column>_seq`: what PostgreSQL names an identity sequence."""
        if not tail.endswith("_seq"):
            return False
        base = tail[: -len("_seq")]
        return any(
            base.startswith(f"{table}_") and base[len(table) + 1 :] in self.columns
            for table in self.objects
        )

    def _is_repository_path(self, value: str) -> bool:
        if not value or len(value) > _MAX_PATH_LENGTH or value.startswith("/") or ".." in value:
            return False
        # `ROOT / ""` is `ROOT`, so the empty string would otherwise be a path.
        return (ROOT / value).exists()

    def classify(self, value: str) -> str | None:
        """Return why `value` is admitted, or `None` if nothing admits it."""
        if value in self.names:
            return "NAME"
        if value in self.labels:
            return "GENERATOR_LABEL"
        if value in self.revisions:
            return "ALEMBIC_REVISION"
        if _SHA256.match(value):
            return "SHA256"
        if _UUID.match(value):
            return "UUID"
        if _TIMESTAMP.match(value):
            return "TIMESTAMP"
        if self.sibling.match(value):
            return "SOURCE_FILE_NAME"
        schema, separator, tail = value.partition(".")
        if separator and schema in self.schemas:
            if tail in self.objects:
                return "QUALIFIED_NAME"
            if self._is_sequence(tail):
                return "IDENTITY_SEQUENCE"
        if value and all(part in self.decisions for part in value.split(", ")):
            return "DECISION"
        if any(template.match(value) for template in self.templates):
            return "MEASURED_DETAIL"
        if self._is_repository_path(value):
            return "REPOSITORY_PATH"
        return None


@pytest.fixture(scope="module")
def vocabulary() -> Vocabulary:
    return Vocabulary()


def _shape(value: str) -> str:
    """Describe a string without quoting it.

    A failure message that printed the offending value would put the suspected
    disclosure into the test output, which is the mistake this whole module
    exists to prevent.
    """
    categories = sorted({unicodedata.category(character) for character in value})
    return f"length {len(value)}, unicode categories {categories}"


def _strings(node: object, path: str = "$") -> list[tuple[str, str]]:
    """Every string value in the document, with the JSON path that holds it."""
    if isinstance(node, dict):
        return [item for key, value in node.items() for item in _strings(value, f"{path}.{key}")]
    if isinstance(node, list):
        return [item for value in node for item in _strings(value, f"{path}[]")]
    if isinstance(node, str):
        return [(path, node)]
    return []


def _keys(node: object) -> list[str]:
    if isinstance(node, dict):
        return list(node) + [key for value in node.values() for key in _keys(value)]
    if isinstance(node, list):
        return [k for value in node for k in _keys(value)]
    return []


@pytest.fixture(scope="module")
def evidence() -> dict[str, Any]:
    assert EVIDENCE.is_file(), f"{EVIDENCE.relative_to(ROOT)} is the artefact under test"
    return _read(EVIDENCE)


def test_the_evidence_has_enough_strings_to_be_worth_checking(
    evidence: dict[str, Any],
) -> None:
    # A walker that visited nothing would report every rule below as passing.
    found = _strings(evidence)
    assert len(found) > 3000
    assert len({path for path, _ in found}) > 50


def test_every_string_in_the_machine_readable_evidence_is_in_the_vocabulary(
    evidence: dict[str, Any], vocabulary: Vocabulary
) -> None:
    """OD-004. Nothing in the evidence may be a value read out of a row."""
    unexplained = [
        f"{path}: {_shape(value)}"
        for path, value in _strings(evidence)
        if vocabulary.classify(value) is None
    ]
    assert not unexplained, (
        f"{len(unexplained)} strings in {EVIDENCE.relative_to(ROOT)} are outside the "
        "closed vocabulary; each is reported by path and shape rather than by value:\n"
        + "\n".join(sorted(set(unexplained)))
    )


def test_every_object_key_is_a_field_name(evidence: dict[str, Any]) -> None:
    # Keys come from dataclass fields and literals in `as_dict`, never from data.
    offending = [key for key in _keys(evidence) if not re.fullmatch(r"[a-z][a-z0-9_]*", key)]
    assert not offending, f"{len(offending)} keys are not identifier-shaped"


def test_the_vocabulary_admits_only_what_it_can_account_for(vocabulary: Vocabulary) -> None:
    """The whitelist is not vacuous: unremarkable free text is refused."""
    assert vocabulary.classify("Zzz Qqq") is None
    assert vocabulary.classify("a sentence no generator in this repository emits") is None
    assert vocabulary.classify("not_a_column_that_exists_anywhere_xyz") is None
    assert vocabulary.classify("") is None
    # And it is not empty, which would refuse everything and prove nothing.
    assert len(vocabulary) > 1000


def test_the_admitted_shapes_are_the_ones_the_evidence_needs(
    evidence: dict[str, Any], vocabulary: Vocabulary
) -> None:
    # Every rule earns its place. A rule matching nothing is a rule nobody
    # checked, and it would widen the whitelist for free.
    used = {vocabulary.classify(value) for _, value in _strings(evidence)}
    assert used == {
        "NAME",
        "GENERATOR_LABEL",
        "ALEMBIC_REVISION",
        "SHA256",
        "UUID",
        "TIMESTAMP",
        "SOURCE_FILE_NAME",
        "IDENTITY_SEQUENCE",
        "MEASURED_DETAIL",
        "REPOSITORY_PATH",
    }


def _rebuild(cls: type, data: Mapping[str, object]) -> object:
    """Rebuild a dataclass from what `dataclasses.asdict` produced for it.

    `asdict` flattens nested records to dicts and tuples to lists, so the inverse
    needs the field types to put them back. Reflective rather than hand-written
    per record: a new field on `Reconciliation` must round-trip too, and a
    hand-written rebuilder would quietly stop covering it.
    """
    hints = typing.get_type_hints(cls, vars(sys.modules[cls.__module__]))
    values = {field.name: _coerce(hints[field.name], data[field.name]) for field in fields(cls)}
    return cls(**values)


def _coerce(hint: object, value: object) -> object:
    origin = typing.get_origin(hint)
    if origin in (types.UnionType, typing.Union):
        inner = [arg for arg in typing.get_args(hint) if arg is not type(None)]
        return None if value is None else _coerce(inner[0], value)
    if origin is tuple:
        item = typing.get_args(hint)[0]
        return tuple(_coerce(item, entry) for entry in cast(Sequence[object], value))
    if is_dataclass(hint):
        return _rebuild(cast(type, hint), cast(Mapping[str, object], value))
    return value


def test_the_markdown_report_is_generated_from_the_machine_readable_record(
    evidence: dict[str, Any],
) -> None:
    """The closed vocabulary reaches `RECONCILIATION.md` because of this.

    `reconcile.py` renders both artefacts from one `Reconciliation`. Rebuilding
    that record from the committed JSON and re-rendering has to reproduce the
    committed markdown exactly; if it does not, the markdown carries something
    the JSON does not, and the vocabulary check no longer covers it.
    """
    report = _rebuild(reconciliation.Reconciliation, evidence)
    markdown = EVIDENCE.with_name("RECONCILIATION.md")
    assert reconciliation_report.render(report) == markdown.read_text(encoding="utf-8")
    assert json.dumps(reconciliation.as_dict(report), indent=2, sort_keys=False) + "\n" == (
        EVIDENCE.read_text(encoding="utf-8")
    )


#: Columns naming a row's identity rather than its content. `resource_key` and
#: `target_key` are opaque keys; `batch_key` is an ordinal.
IDENTIFIER_COLUMNS = frozenset({"batch_key", "resource_key", "target_key"})

#: Columns that hold a digest. A hash of a natural key is what lets a refused
#: row be found again without the ledger holding the key itself (OD-011).
HASH_COLUMNS = frozenset({"natural_key_hash", "source_sha256"})

#: Sizes, versions, and tallies. Enumerated rather than "any integer column", so
#: a numeric column with a new meaning has to be classified deliberately.
COUNT_COLUMNS = frozenset(
    {
        "loaded_row_count",
        "quarantined_row_count",
        "row_count",
        "rows_failed",
        "rows_ok",
        "rows_quarantined",
        "source_bytes",
        "source_row_count",
        "source_schema_version",
        "tables_completed",
        "tables_total",
        "watermark",
    }
)

#: Text columns holding the name of something in the schema or in the code: a
#: legacy table, a column, a phase, an identifier the DDL renamed, an exception
#: *class*, an Alembic revision, or a lease owner. Never a value out of a row.
NAME_COLUMNS = frozenset(
    {
        "code",
        "column_name",
        "error_class",
        "legacy_table",
        "object_kind",
        "original",
        "owner",
        "owning_table",
        "phase",
        "shortened",
        "target_alembic_revision",
    }
)

_NUMERIC_TYPES = frozenset({"integer", "bigint"})


def _classify_column(name: str, data_type: str, identity: str, enum_like: bool) -> str | None:
    """Say what role a control-plane column plays, or `None` if it has none.

    `None` is the failure. A column that is not an identifier, a hash, a count,
    a timestamp, a flag, an enum-like code, or the name of a schema object is a
    column that could hold a row's content, and the control plane does not get
    to have one.
    """
    if data_type.startswith("timestamp"):
        return "TIMESTAMP"
    if data_type == "boolean":
        return "FLAG"
    if data_type == "uuid" or identity in ("a", "d") or name in IDENTIFIER_COLUMNS:
        return "IDENTIFIER"
    if name in HASH_COLUMNS and data_type == "text":
        return "HASH"
    if name in COUNT_COLUMNS and data_type in _NUMERIC_TYPES:
        return "COUNT"
    if enum_like and data_type == "text":
        return "ENUM_LIKE"
    if name in NAME_COLUMNS and data_type == "text":
        return "OBJECT_NAME"
    return None


_COLUMNS = """
SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attidentity
  FROM pg_attribute a
  JOIN pg_class c ON c.oid = a.attrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = :schema AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
 ORDER BY c.relname, a.attname
"""

_VALUE_CHECKS = """
SELECT c.relname, a.attname
  FROM pg_constraint con
  JOIN pg_class c ON c.oid = con.conrelid
  JOIN pg_namespace n ON n.oid = c.relnamespace
  JOIN unnest(con.conkey) AS k(attnum) ON true
  JOIN pg_attribute a ON a.attrelid = con.conrelid AND a.attnum = k.attnum
 WHERE con.contype = 'c' AND n.nspname = :schema
   AND pg_get_constraintdef(con.oid) LIKE '%ANY (ARRAY[%'
"""


@pytest.fixture
def control_plane_only(target: Engine) -> Engine:
    """The control plane alone, on a disposable database.

    The Alembic revision creates these tables with `METADATA.create_all`, so
    what PostgreSQL materialises from that declaration is what the revision
    applies. The canonical `my_pa` database is never touched by a test.
    """
    with target.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{control_plane.SCHEMA}"'))
        control_plane.METADATA.create_all(connection)
    return target


@pytest.mark.database
def test_no_control_plane_column_can_hold_a_row_value(control_plane_only: Engine) -> None:
    """OD-004, structurally. Leakage here is impossible, not merely avoided.

    `quarantine_records` names a refused row by table, column, error code, and a
    hash of its key, and has no column for the value; `audit_events` carries
    event types, codes, and counts. This is what breaks if somebody later adds a
    `sample_value` or an `error_detail` to make a defect easier to debug.
    """
    with control_plane_only.connect() as connection:
        columns = connection.execute(text(_COLUMNS), {"schema": control_plane.SCHEMA}).all()
        enum_like = {
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                text(_VALUE_CHECKS), {"schema": control_plane.SCHEMA}
            ).all()
        }

    assert {table for table, *_ in columns} == {
        table.name for table in control_plane.METADATA.tables.values()
    }
    unclassified = [
        f"{table}.{column} ({data_type})"
        for table, column, data_type, identity in columns
        if _classify_column(
            str(column), str(data_type), str(identity), (str(table), str(column)) in enum_like
        )
        is None
    ]
    assert not unclassified, (
        f"{len(unclassified)} columns in {control_plane.SCHEMA} are neither an identifier, "
        "a hash, a count, a timestamp, a flag, an enum-like code, nor the name of a schema "
        f"object, so each could hold a row value: {unclassified}"
    )


@pytest.mark.database
def test_the_two_ledgers_written_per_row_carry_no_free_text(
    control_plane_only: Engine,
) -> None:
    """The specific claim the reconciliation report makes, checked by name.

    `quarantine_records` and `audit_events` are the only control tables the
    loader writes a row into per refused or notable row, so they are where a
    content column would do the most damage.
    """
    with control_plane_only.connect() as connection:
        columns = connection.execute(text(_COLUMNS), {"schema": control_plane.SCHEMA}).all()
    written = {
        str(table): {str(column) for candidate, column, _, _ in columns if candidate == table}
        for table in ("quarantine_records", "audit_events")
    }
    assert written["quarantine_records"] == {
        "quarantine_id",
        "run_id",
        "phase",
        "legacy_table",
        "column_name",
        "natural_key_hash",
        "error_code",
        "error_class",
        "recorded_at",
    }
    assert written["audit_events"] == {
        "event_id",
        "run_id",
        "phase",
        "legacy_table",
        "event_type",
        "code",
        "row_count",
        "recorded_at",
    }
