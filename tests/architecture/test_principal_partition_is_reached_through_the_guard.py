"""A principal-partitioned table is reached through `principal_scope`, or it is registered.

WP-04. The governing invariant is that every durable user-owned record is scoped
to the authenticated Principal. `infrastructure.persistence.principal_scope` is
the mechanism: it fails closed on a missing context, refuses a table that has no
partition column at all, and recognises both partition vocabularies in one
place. What it could not do, until this module existed, is notice a call site
that simply did not use it.

That is not hypothetical. `SqlRelationshipRepository` stamped `principal_id` on
every INSERT and then issued seven UPDATEs and most of its SELECTs with no
partition predicate at all, for the whole of WP-09 and WP-06, with no test that
would have said so. Three of its reads *did* carry the partition — written by
hand, as `relationship_people.c.principal_id == self._principal_id` — which is
the shape of the defect rather than a defence against it: a predicate written at
the call site is one a neighbouring call site can forget.

Four claims, separated because they fail for different reasons:

1. **Every production module that names a partitioned table is accounted for.**
   Either it reaches the partition through `principal_scope`, or it is in
   `QUARANTINED` with a reason. Exact set equality, so a module that starts
   naming a partitioned table has to be argued about here rather than merged
   quietly.
2. **A module registered as guarded actually calls the guard**, rather than
   importing it and then not using it.
3. **Raw SQL carries the partition on every table reference it makes.** The
   expression language is where `principal_scope` can intervene; a `text()`
   block is where it cannot, so each `FROM`/`JOIN`/`UPDATE` naming a partitioned
   table must constrain that alias's partition column against a bound
   parameter.
4. **A hand-written partition comparison is registered or refused.** Seventeen
   exist today, all in planes this package did not repair; the registry is exact,
   so an eighteenth fails the build.

Nothing here opens a connection, reaches a source, or touches a database. It
parses the source tree, so a violation is caught even when nothing executes the
offending module.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Table

from my_pa.infrastructure.persistence import tables as declarations

ROOT: Final = Path(__file__).resolve().parents[2]
SOURCE: Final = ROOT / "src"
PACKAGE: Final = SOURCE / "my_pa"

#: The module every partition predicate has to come from.
GUARD_MODULE: Final = "my_pa.infrastructure.persistence.principal_scope"

#: The names that module publishes which *reach* a partition. `PrincipalContext`
#: is deliberately absent: carrying the context is not using it.
GUARD_CALLS: Final = frozenset(
    {"partition_criterion", "principal_scoped", "principal_bound_values", "capture_context"}
)

#: The two partition vocabularies, as column names. Kept here rather than
#: imported from `principal_scope` so this module measures the schema
#: independently of the code it is checking.
PARTITION_COLUMNS: Final = ("principal_id", "owner_principal_id")

#: Where a table declaration lives. Excluded from every module scan below,
#: because declaring a partitioned table is not querying one.
DECLARATIONS: Final = PACKAGE / "infrastructure" / "persistence" / "tables.py"

#: Modules that reach a partitioned table through `principal_scope`.
#:
#: `capture_pipeline.py` is here because it derives a `PrincipalContext` from the
#: *stored* owner of the version it is processing and hands it to the modules
#: that query — it names `capture_versions` to read that owner and nothing else.
REACHED_THROUGH_THE_GUARD: Final = frozenset(
    {
        "infrastructure/jobs/capture_pipeline.py",
        "infrastructure/persistence/capture.py",
        "infrastructure/persistence/capture_search.py",
        "infrastructure/persistence/relationships.py",
        "infrastructure/persistence/review.py",
    }
)

#: Modules that name a partitioned table without reaching it through the guard,
#: with the reason each is not closed by WP-04. Every entry is a residual, not an
#: exemption: the reason says what holds the partition instead, and what would
#: have to change for the entry to leave this registry.
#:
#: This is the legible half of the package's scope boundary. WP-04 repaired the
#: relationship plane and registered the rest; a module added to this dict is a
#: decision someone has to write down.
QUARANTINED: Final = {
    "infrastructure/jobs/extraction.py": (
        "reads `enrollments` to resolve the enrollment a job names. Ownership is "
        "the enrollment's `principal_id`, checked by `application.authorization` "
        "before the job is queued rather than by this reader."
    ),
    "infrastructure/persistence/audit.py": (
        "writes `audit_events`, whose `principal_id` comes from the domain event "
        "the policy decision produced. An audit sink that filtered by Principal "
        "would be an audit trail the subject could shape; reads are operator-only."
    ),
    "infrastructure/persistence/enrollment.py": (
        "scopes `enrollments` by a hand-written `principal_id` comparison "
        "registered in HAND_WRITTEN_COMPARISONS below. Not a hole, but not the "
        "guard either — converting it is WP-05's, since the enrollment plane's "
        "identity vocabulary changes there."
    ),
    "infrastructure/persistence/extraction.py": (
        "joins `enrollments` to attribute extraction outcomes. Same enrollment "
        "ownership chain as `jobs/extraction.py`."
    ),
    "infrastructure/persistence/native_sources.py": (
        "writes `audit_events` only; the twenty-three `native_*`/`source*` tables "
        "it owns carry no principal column at all and are registered as an "
        "unpartitioned plane in `test_user_owned_tables_are_partitioned.py`. "
        "Partitioning that plane is explicitly out of WP-04's scope."
    ),
    "infrastructure/persistence/proposals.py": (
        "`version_content` returns a capture version's text given only a "
        "`version_id`, with no partition predicate. Registered rather than "
        "repaired: its one caller is the pipeline, which already resolved the "
        "owner, and closing it properly means giving the function a context, "
        "which changes the pipeline's signature."
    ),
    "infrastructure/persistence/search.py": (
        "scopes the extraction plane by `enrollment_id`, relying on "
        "`application.authorization._scope_of_enrollment` resolving enrollment "
        "identifiers only within the caller's own enrollments. Asserted "
        "behaviourally in "
        "`tests/security/test_cross_principal_search_isolation.py`."
    ),
    "infrastructure/persistence/situation_repository.py": (
        "scopes all seven R5 continuity tables by hand-written `principal_id` "
        "comparisons, registered in HAND_WRITTEN_COMPARISONS below. The "
        "continuity commands that would drive it are unwired (WP-06)."
    ),
}

#: Every hand-written partition comparison in the tree, as
#: `module -> ((table, column), ...)` sorted with multiplicity.
#:
#: A registry rather than a ban, because seventeen exist and removing them is
#: other packages' work. What the registry buys is that an eighteenth cannot
#: appear silently — which is exactly how the relationship plane ended up with
#: three hand-written predicates and twenty-odd statements with none.
HAND_WRITTEN_COMPARISONS: Final = {
    "infrastructure/persistence/enrollment.py": (
        ("enrollments", "principal_id"),
        ("enrollments", "principal_id"),
    ),
    "infrastructure/persistence/review.py": (("capture_review_cases", "principal_id"),),
    "infrastructure/persistence/situation_repository.py": (
        ("frames", "principal_id"),
        ("projects", "principal_id"),
        ("projects", "principal_id"),
        ("projects", "principal_id"),
        ("pulse_items", "principal_id"),
        ("pulse_items", "principal_id"),
        ("relationship_events", "principal_id"),
        ("relationship_events", "principal_id"),
        ("situations", "principal_id"),
        ("situations", "principal_id"),
        ("situations", "principal_id"),
        ("situations", "principal_id"),
        ("situations", "principal_id"),
        ("traces", "principal_id"),
    ),
}

#: A `FROM`, `JOIN`, `UPDATE`, or `INTO` naming a schema-qualified table, with
#: the alias that follows it when there is one. The negative lookahead keeps a
#: keyword from being read as an alias.
_TABLE_REFERENCE: Final = re.compile(
    r"\b(?:FROM|JOIN|UPDATE|INTO)\s+(?:knowledge|identity)\.(\w+)"
    r"(?:\s+(?!ON\b|WHERE\b|SET\b|VALUES\b|LEFT\b|RIGHT\b|INNER\b|JOIN\b|USING\b"
    r"|GROUP\b|ORDER\b|LIMIT\b|EXCEPT\b|UNION\b|AND\b|OR\b)(\w+))?",
    re.IGNORECASE,
)


def _partitioned_tables() -> dict[str, str]:
    """Every declared table carrying a partition column, as `variable -> name`."""
    return {
        name: str(table.name)
        for name, table in vars(declarations).items()
        if isinstance(table, Table) and any(column in table.c for column in PARTITION_COLUMNS)
    }


def _modules() -> list[Path]:
    return [path for path in sorted(PACKAGE.rglob("*.py")) if path != DECLARATIONS]


def _relative(path: Path) -> str:
    return str(path.relative_to(PACKAGE))


def _imported_from(tree: ast.Module, module: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            names.update(alias.asname or alias.name for alias in node.names)
    return names


def _modules_naming_a_partitioned_table() -> dict[str, frozenset[str]]:
    """Measured, not listed: which module imports which partitioned declaration."""
    partitioned = _partitioned_tables()
    found: dict[str, frozenset[str]] = {}
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        imported = _imported_from(tree, "my_pa.infrastructure.persistence.tables")
        named = imported & set(partitioned)
        if named:
            found[_relative(path)] = frozenset(named)
    return found


def _calls_the_guard(path: Path) -> frozenset[str]:
    """The `principal_scope` names a module both imports and calls."""
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    imported = _imported_from(tree, GUARD_MODULE) & GUARD_CALLS
    called: set[str] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in imported
        ):
            called.add(node.func.id)
    return frozenset(called)


def _hand_written_comparisons(path: Path) -> tuple[tuple[str, str], ...]:
    """Every `<table>.c.<partition column> == …` written at a call site."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or not isinstance(node.left, ast.Attribute):
            continue
        column = node.left.attr
        if column not in PARTITION_COLUMNS:
            continue
        accessor = node.left.value
        if not isinstance(accessor, ast.Attribute) or accessor.attr != "c":
            continue
        if isinstance(accessor.value, ast.Name):
            found.append((accessor.value.id, column))
    return tuple(sorted(found))


def unscoped_table_references(statement: str, partitioned: frozenset[str]) -> tuple[str, ...]:
    """Which partitioned tables one SQL string names without constraining their partition.

    Public, and used by this module's own control: the same detector is run over
    a statement that really is unscoped, so a zero from the production scan is a
    measurement rather than a regex that matched nothing.
    """
    unscoped: list[str] = []
    for match in _TABLE_REFERENCE.finditer(statement):
        table, alias = match.group(1), match.group(2)
        if table not in partitioned:
            continue
        qualifier = alias or table
        if not any(
            re.search(rf"\b{re.escape(qualifier)}\.{column}\s*=\s*:", statement)
            for column in PARTITION_COLUMNS
        ):
            unscoped.append(f"{table} AS {qualifier}" if alias else table)
    return tuple(unscoped)


def _sql_literals(path: Path) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def test_the_scan_finds_a_partitioned_schema_and_a_source_tree() -> None:
    """Guards every test below against passing because nothing was parsed."""
    partitioned = _partitioned_tables()
    assert len(partitioned) >= 30, (
        f"only {len(partitioned)} partitioned tables were derived from the live "
        "declaration; the schema scan is not measuring the schema"
    )
    assert "relationship_people" in partitioned.values()
    assert "captures" in partitioned.values()
    assert len(_modules()) >= 100
    assert _modules_naming_a_partitioned_table(), "no module names a partitioned table at all"


def test_every_module_naming_a_partitioned_table_is_guarded_or_registered() -> None:
    """Claim 1: exact accounting. A new unscoped reader fails here, not in review."""
    measured = set(_modules_naming_a_partitioned_table())
    accounted = REACHED_THROUGH_THE_GUARD | set(QUARANTINED)

    unaccounted = sorted(measured - accounted)
    assert unaccounted == [], (
        f"{unaccounted} name a principal-partitioned table without reaching it "
        f"through {GUARD_MODULE} and without a registered reason. Scope the "
        "statements through `principal_scope`, or register the module in "
        "QUARANTINED with what holds the partition instead"
    )

    stale = sorted(accounted - measured)
    assert stale == [], (
        f"{stale} are registered here but no longer name a partitioned table. A "
        "registry that outlives what it describes stops being a measurement"
    )

    overlap = sorted(REACHED_THROUGH_THE_GUARD & set(QUARANTINED))
    assert overlap == [], f"{overlap} are both guarded and quarantined; one is wrong"


def test_a_module_registered_as_guarded_actually_calls_the_guard() -> None:
    """Claim 2: importing `principal_scope` is not using it."""
    for relative in sorted(REACHED_THROUGH_THE_GUARD):
        path = PACKAGE / relative
        assert path.is_file(), f"{relative} is registered as guarded but does not exist"
        called = _calls_the_guard(path)
        assert called, (
            f"{relative} is registered as reaching the partition through "
            f"{GUARD_MODULE}, but calls none of {sorted(GUARD_CALLS)}"
        )

    # The control: a module that is *not* registered as guarded calls none of
    # them, so the detector above distinguishes rather than always answering yes.
    unguarded = PACKAGE / "infrastructure" / "persistence" / "situation_repository.py"
    assert _calls_the_guard(unguarded) == frozenset()


@pytest.mark.parametrize("path", _modules(), ids=_relative)
def test_raw_sql_carries_the_partition_on_every_table_reference(path: Path) -> None:
    """Claim 3: the one place `principal_scope` cannot intervene states it itself."""
    partitioned = frozenset(_partitioned_tables().values())
    for lineno, statement in _sql_literals(path):
        unscoped = unscoped_table_references(statement, partitioned)
        assert unscoped == (), (
            f"{_relative(path)}:{lineno} names {list(unscoped)} in raw SQL with no "
            "principal predicate on that reference. A `text()` block is where the "
            "expression-language guard cannot reach, so the partition has to be "
            "written into the statement — including inside a JOIN condition, where "
            "omitting it lets another Principal's row decide the answer"
        )


def test_the_raw_sql_detector_reports_a_statement_that_really_is_unscoped() -> None:
    """The control for claim 3. Without it, a regex matching nothing would pass."""
    partitioned = frozenset(_partitioned_tables().values())

    bypass = "SELECT display_name FROM knowledge.relationship_people WHERE person_id = :person_id"
    assert unscoped_table_references(bypass, partitioned) == ("relationship_people",)

    aliased = (
        "SELECT 1 FROM knowledge.relationship_observation_links link "
        "JOIN knowledge.relationship_identity_resolutions receipt "
        "ON receipt.resolution_id = link.resolution_id "
        "WHERE link.principal_id = :principal_id"
    )
    assert unscoped_table_references(aliased, partitioned) == (
        "relationship_identity_resolutions AS receipt",
    )

    scoped = (
        "SELECT 1 FROM knowledge.relationship_people person "
        "WHERE person.principal_id = :principal_id AND person.person_id = :person_id"
    )
    assert unscoped_table_references(scoped, partitioned) == ()

    # An unpartitioned table is not this control's business and must not be
    # reported, or the production scan above would fail for the wrong reason.
    unpartitioned = "SELECT 1 FROM knowledge.sources WHERE source_id = :source_id"
    assert unscoped_table_references(unpartitioned, partitioned) == ()


def test_hand_written_partition_comparisons_match_their_registry_exactly() -> None:
    """Claim 4: the drift that caused the defect cannot grow without being named."""
    measured = {
        _relative(path): comparisons
        for path in _modules()
        if (comparisons := _hand_written_comparisons(path))
    }
    assert measured == HAND_WRITTEN_COMPARISONS, (
        "the hand-written partition comparisons in the tree no longer match their "
        "registry. A predicate written at a call site is one a neighbouring call "
        "site can forget — which is how the relationship plane acquired three "
        "hand-written comparisons and twenty-odd statements with none. Reach the "
        "partition through `principal_scope`, or add the site here with a reason"
    )

    # The control: the detector finds a comparison when there is one to find.
    synthetic = ast.parse("x = captures.c.owner_principal_id == other")
    found = [
        (node.left.value.value.id, node.left.attr)
        for node in ast.walk(synthetic)
        if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Attribute)
        and isinstance(node.left.value, ast.Attribute)
    ]
    assert found == [("captures", "owner_principal_id")]


def test_every_relationship_statement_reaches_the_partition() -> None:
    """The module WP-04 repaired, statement by statement.

    Claim 1 says the module uses `principal_scope` somewhere; this says every
    statement in it does. The unit is one top-level statement inside a method,
    because that is how a query is built here: one `select`/`update`/`insert`
    chain per statement. A statement naming a partitioned declaration must also
    name `_mine` (the read and update predicate) or `_bound` (the insert
    stamp) — or be the one `text()` block, which claim 3 covers instead.
    """
    path = PACKAGE / "infrastructure" / "persistence" / "relationships.py"
    partitioned = set(_partitioned_tables())
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    checked = 0
    offending: list[str] = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for statement in ast.walk(function):
            if not isinstance(statement, ast.Expr | ast.Assign | ast.Return):
                continue
            rendered = ast.unparse(statement)
            if not any(
                f"{table}.c" in rendered or f"({table}," in rendered for table in partitioned
            ):
                continue
            if "text(" in rendered:
                continue
            checked += 1
            if "self._mine(" not in rendered and "self._bound(" not in rendered:
                offending.append(f"{function.name}:{statement.lineno}")

    assert checked >= 25, (
        f"only {checked} relationship statements were examined; the walk is not "
        "reaching the module's queries"
    )
    assert offending == [], (
        f"{offending} build a statement over a principal-partitioned relationship "
        "table without reaching the partition through `principal_scope`. Every "
        "read and update predicate goes through `_mine`; every insert goes "
        "through `_bound`"
    )
