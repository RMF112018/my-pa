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
   so an eighteenth fails the build. The comparison is matched off an arbitrary
   attribute chain, not off a bare name: `plane.table.c.principal_id == …` was
   invisible to the first version of the matcher, and an independent review
   substituted exactly that for `partition_criterion(...)` in
   `reap_abandoned_jobs` with all 140 tests still green.
5. **A guarded module is checked statement by statement, or is registered as
   only checked as a whole.** Claim 1 asks whether a module calls the guard
   *anywhere*, and `jobs.py` answered yes on the strength of `claim_job` and
   `enqueue_job` while `job_for` and `job_state` read the plane with nothing but
   an operation id — visible to neither the guarded set nor `QUARANTINED`. Two
   modules now account for every statement; the rest say so.

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
        # WP-10's client plane. Three of its four statements reach the partition
        # — the insert through `principal_bound_values`, the revoke through
        # `partition_criterion`, the listing through `principal_scoped`. The
        # fourth is `authenticate_client`, which is registered below for the
        # reason `jobs.job_principal` is: it *derives* the Principal.
        "infrastructure/persistence/capture_clients.py",
        "infrastructure/persistence/capture_search.py",
        # Both job queues gained `principal_id` at revision `4f1a8b6d92e3`; the
        # dequeue and the reap carry the partition and the enqueue stamps it
        # from the subject's stored owner. It also names `enrollments` and
        # `capture_versions` — to *read* that owner, which is where the
        # partition comes from and so cannot itself be scoped by one.
        "infrastructure/persistence/jobs.py",
        # WP-23's corpus coverage read, and the only statement in this module that
        # names a partitioned table at all: every other read here is scoped by an
        # enrollment identifier the authorization path already confined to the
        # caller's own grants. `corpus_coverage` has no enrollment to be confined
        # by — its whole subject is "every enrollment this Principal holds" — so
        # the partition is the query's own, through `partition_criterion`.
        "infrastructure/persistence/knowledge.py",
        "infrastructure/persistence/relationships.py",
        # The evidence traversal. Every one of its six statements is rooted at a
        # partitioned table — `captures`, `capture_versions`, `capture_assertions`
        # or `capture_assertion_spans` — and constrained through `principal_scoped`
        # before its joins are built, which is how `capture_spans`,
        # `capture_proposals` and `capture_proposal_spans` are reached at all:
        # none of the three carries a partition column, so the guard would refuse
        # a statement rooted at one.
        "infrastructure/persistence/reveal.py",
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
        "scopes all eleven R5/WP-11 continuity tables by hand-written "
        "`principal_id` comparisons, registered in HAND_WRITTEN_COMPARISONS "
        "below. Three of the eleven — Situations, Projects and the Pulse — are "
        "now reached by a capability (WP-11); the continuity *write* path is "
        "still driven only by `SituationService`, outside `invoke`."
    ),
}

#: The guarded modules whose *statements* are checked one by one, rather than
#: only the module as a whole.
#:
#: Claim 1 asks whether a module calls the guard anywhere, and that is a weak
#: question: `jobs.py` qualified because `claim_job` and `enqueue_job` call it,
#: which made `job_for` and `job_state` — two unpartitioned reads — invisible to
#: both the guarded set and `QUARANTINED` at once. A module here has to account
#: for every statement it builds over a partitioned table.
STATEMENT_LEVEL: Final = frozenset(
    {
        "infrastructure/persistence/jobs.py",
        "infrastructure/persistence/knowledge.py",
        "infrastructure/persistence/relationships.py",
        "infrastructure/persistence/reveal.py",
    }
)

#: The guarded modules that are still only checked as a whole, and why each one
#: is not statement-level yet. Registered rather than left implicit: "this module
#: uses the guard somewhere" is a different claim from "every statement in it
#: does", and a reader is entitled to know which one they are being given.
#:
#: These counts are what a statement-level scan measures today, and they are the
#: work each entry represents rather than a hidden hole: every one of these
#: modules is reached only through an application path that has already resolved
#: the Principal, which is the same argument the `QUARANTINED` entries make.
PER_MODULE_ONLY: Final = {
    "infrastructure/jobs/capture_pipeline.py": (
        "derives a `PrincipalContext` from the stored owner of the version it is "
        "processing and hands it to the modules that query. Its own two "
        "statements read `capture_versions` by `version_id` to find that owner, "
        "so they are the derivation the partition comes from rather than uses."
    ),
    "infrastructure/persistence/capture.py": (
        "three statements of eight — the receipt read, the submission upsert, and "
        "the max-version-number subquery — carry the partition through an "
        "idempotency key or a version identifier instead of `principal_scoped`. "
        "Converting them is capture-plane work, not WP-04's."
    ),
    "infrastructure/persistence/capture_clients.py": (
        "one statement of four — `authenticate_client`'s lookup by `client_id` — "
        "carries no partition predicate, because it is the read that *derives* "
        "the Principal a remote submission runs as and a predicate there would "
        "need the answer to ask the question. The same shape as "
        "`jobs.job_principal`, and it fails closed: an unknown client, a wrong "
        "secret and a revoked client are one `None`."
    ),
    "infrastructure/persistence/capture_search.py": (
        "two statements of three build fragments over `capture_versions` that the "
        "scoped statement composes; the composed statement carries "
        "`partition_criterion`."
    ),
    "infrastructure/persistence/review.py": (
        "twelve statements of thirteen scope the review plane by "
        "`review_case_id`/`proposal_id`/`version_id` rather than by Principal, "
        "relying on the one `principal_scoped` read that resolves the case. That "
        "is the review plane's own chain and repairing it is WP-06's."
    ),
}

#: Statements in `jobs.py` that build a query over a partitioned job table
#: *without* reaching the partition, as `function -> (statement count, reason)`.
#:
#: Exact, and counted, so a second unpartitioned statement inside an already
#: registered function reddens as loudly as a new function does. This is the
#: legible residual of C-3: the four sites below are not reached by a Principal
#: predicate, and each one says what holds it instead.
UNPARTITIONED_JOB_STATEMENTS: Final = {
    "job_principal": (
        1,
        "reads the subject's own row by its primary key to find the Principal a "
        "queued job belongs to. It *is* the derivation the partition comes from, "
        "so a partition predicate here would be circular; it fails closed with "
        "`UnownedJobSubjectError` when there is no such row.",
    ),
    "hold_lease": (
        1,
        "matches `operation_id` and `lease_owner` together and holds the row "
        "`FOR UPDATE`. The lease owner is a token this worker was issued, not "
        "something a request carries, and the answer is a boolean about a lease "
        "rather than any of the job's content.",
    ),
    "complete_job": (
        1,
        "same three-way match as `hold_lease` on the write path: a worker that "
        "does not hold the lease updates no row. Adding the Principal means "
        "giving the worker loop one to state, which is WP-05's lane.",
    ),
    "release_job": (
        1,
        "the failure counterpart of `complete_job`, matched on the same lease "
        "owner and state, and unpartitioned for the same reason.",
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
    # WP-11 grew this entry from fourteen comparisons to thirty-four, and every
    # new one is the same shape as the fourteen that were here: a
    # `<table>.c.principal_id == principal_id` predicate written into the
    # statement. Three of them read `table.c.principal_id` through the closed
    # `_OBJECT_TABLE` map rather than through a table variable, which the scanner
    # sees as the literal name `table`; the map holds only partitioned tables and
    # is private to the module, so the predicate is on a partitioned table in
    # every branch. `capture_review_decisions` is the acceptance gate: `accept`
    # resolves the review decision inside the caller's partition, so a decision
    # belonging to another Principal cannot promote this Principal's proposal.
    "infrastructure/persistence/situation_repository.py": (
        ("capture_review_decisions", "principal_id"),
        ("commitments", "principal_id"),
        ("commitments", "principal_id"),
        ("commitments", "principal_id"),
        ("continuity_lifecycle_events", "principal_id"),
        ("decisions", "principal_id"),
        ("decisions", "principal_id"),
        ("decisions", "principal_id"),
        ("frames", "principal_id"),
        ("frames", "principal_id"),
        ("frames", "principal_id"),
        ("projects", "principal_id"),
        ("projects", "principal_id"),
        ("projects", "principal_id"),
        ("projects", "principal_id"),
        ("pulse_items", "principal_id"),
        ("pulse_items", "principal_id"),
        ("pulse_items", "principal_id"),
        ("relationship_events", "principal_id"),
        ("relationship_events", "principal_id"),
        ("situations", "principal_id"),
        ("situations", "principal_id"),
        ("situations", "principal_id"),
        ("situations", "principal_id"),
        ("situations", "principal_id"),
        ("situations", "principal_id"),
        ("situations", "principal_id"),
        ("table", "principal_id"),
        ("table", "principal_id"),
        ("table", "principal_id"),
        ("tasks", "principal_id"),
        ("tasks", "principal_id"),
        ("tasks", "principal_id"),
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


def partition_column_reference(node: ast.expr) -> tuple[str, str] | None:
    """`<anything>.c.<partition column>` as `(what it was read off, column)`, or `None`.

    The receiver is rendered rather than required to be a bare `ast.Name`, and
    that is the whole of the fix this function carries. The first version
    matched only `<Name>.c.<column>`, so `plane.table.c.principal_id == …` — a
    partition predicate written by hand off an attribute chain — was invisible
    to it. An independent review replaced `partition_criterion(...)` in
    `reap_abandoned_jobs` with exactly that expression and all 140 tests in this
    module stayed green.

    The subscript spelling of a column is read too, because `table.c["principal_id"]`
    is the same access with different punctuation.

    Public: a control below runs it over the expression that got through.
    """
    if isinstance(node, ast.Attribute):
        column, accessor = node.attr, node.value
    elif (
        isinstance(node, ast.Subscript)
        and isinstance(node.slice, ast.Constant)
        and isinstance(node.slice.value, str)
    ):
        column, accessor = node.slice.value, node.value
    else:
        return None
    if column not in PARTITION_COLUMNS:
        return None
    if not isinstance(accessor, ast.Attribute) or accessor.attr != "c":
        return None
    return ast.unparse(accessor.value), column


def _hand_written_comparisons(path: Path) -> tuple[tuple[str, str], ...]:
    """Every `<table>.c.<partition column> == …` written at a call site.

    Both sides of the comparison, because `principal_id == table.c.principal_id`
    is the same predicate typed backwards and SQLAlchemy builds the same clause
    from it.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare):
            continue
        for operand in (node.left, *node.comparators):
            reference = partition_column_reference(operand)
            if reference is not None:
                found.append(reference)
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

    # The control: the detector finds a comparison when there is one to find,
    # in each shape that is one. The attribute-chain case is here because it was
    # a reachable bypass — `plane.table.c.principal_id == principal_id`
    # substituted for `partition_criterion(...)` in `reap_abandoned_jobs` left
    # every test in this module green.
    for source, expected in (
        ("captures.c.owner_principal_id", ("captures", "owner_principal_id")),
        ("plane.table.c.principal_id", ("plane.table", "principal_id")),
        ("self._plane.table.c.principal_id", ("self._plane.table", "principal_id")),
        ("table.c['principal_id']", ("table", "principal_id")),
    ):
        parsed = ast.parse(source, mode="eval").body
        assert partition_column_reference(parsed) == expected, source

    # And it distinguishes: a non-partition column is not a partition predicate,
    # and a column read off something that is not a `.c` collection is not one
    # either. A detector that answered yes to everything would report the whole
    # tree and the registry would stop meaning anything.
    for ignored in ("jobs.c.state", "row.principal_id", "plane.table.principal_id"):
        assert partition_column_reference(ast.parse(ignored, mode="eval").body) is None, ignored


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


#: Statements in `reveal.py` that name a partitioned table without carrying the
#: predicate themselves, as `function -> (statement count, reason)`.
#:
#: Exact and counted, the way `_UNPARTITIONED_JOB_STATEMENTS` is, so a second
#: unscoped statement inside an already registered function reddens as loudly as
#: a new function does. **Neither entry is a hole**: each is a fragment that only
#: ever becomes a query inside a `principal_scoped(...)` call, and the test below
#: asserts that composition rather than accepting the claim.
_REVEAL_FRAGMENTS: Final[dict[str, tuple[int, str]]] = {
    "_proposals": (
        1,
        "the correlated `latest_disposition` subquery over `capture_review_cases`, "
        "composed into the scoped statement in the same function. Correlated to "
        "the outer case, so it carries the partition its consumer imposes.",
    ),
    "_assertion_selection": (
        1,
        "the assertion column and join list, which is not a query: both callers "
        "wrap it in `principal_scoped(..., capture_assertions, context)` before "
        "it is executed.",
    ),
}


def test_every_reveal_statement_reaches_the_partition() -> None:
    """The evidence traversal, statement by statement.

    Claim 1 says `reveal.py` uses `principal_scope` somewhere; this says every
    statement in it does — which is the claim the capability's isolation actually
    rests on, because a reveal walks eight tables and only five of them carry a
    partition column at all.

    **The three that do not are the point.** `capture_spans`,
    `capture_proposals` and `capture_proposal_spans` have no `principal_id`, so
    `principal_scoped` refuses a statement rooted at one — it raises
    `UnpartitionedTableError` — and the only way to read them is to root the
    statement at `capture_versions` and join outward. A statement here therefore
    passes not by naming a partitioned table plus a filter, but by handing
    `principal_scoped` a table that *can* carry the predicate. That makes "the
    scope is at the query" a property of the shape rather than of a comparison
    somebody remembered to write.

    The unit is one top-level statement inside a function, the same unit
    `test_every_relationship_statement_reaches_the_partition` uses, and the
    non-zero floor below is what stops this passing over a module the walk
    failed to parse.
    """
    path = PACKAGE / "infrastructure" / "persistence" / "reveal.py"
    partitioned = set(_partitioned_tables())
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    checked = 0
    offending: list[str] = []
    fragments: dict[str, int] = {}
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for statement in ast.walk(function):
            if not isinstance(statement, ast.Expr | ast.Assign | ast.Return):
                continue
            rendered = ast.unparse(statement)
            if not any(f"{table}.c" in rendered for table in partitioned):
                continue
            checked += 1
            if "principal_scoped(" in rendered:
                continue
            if function.name in _REVEAL_FRAGMENTS:
                fragments[function.name] = fragments.get(function.name, 0) + 1
                continue
            offending.append(f"{function.name}:{statement.lineno}")

    assert checked >= 8, (
        f"only {checked} reveal statements were examined; the walk is not "
        "reaching the module's queries"
    )
    assert offending == [], (
        f"{offending} build a statement over a principal-partitioned capture "
        "table without reaching the partition through `principal_scope`"
    )
    assert fragments == {name: count for name, (count, _) in _REVEAL_FRAGMENTS.items()}, (
        f"{fragments} unscoped statements were found where "
        f"{ {name: count for name, (count, _) in _REVEAL_FRAGMENTS.items()} } are "
        "registered; a fragment gained or lost a statement"
    )
    # And the registered fragments really are composed under the guard, rather
    # than merely asserted to be. Without this the registry above would be an
    # exemption list that could name anything.
    bodies = {
        node.name: ast.unparse(node) for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    for name in _REVEAL_FRAGMENTS:
        composed_by_a_caller = re.search(rf"principal_scoped\(\s*{re.escape(name)}\(", source)
        composed_in_place = "principal_scoped(" in bodies.get(name, "")
        assert composed_by_a_caller or composed_in_place, (
            f"{name} is registered as a fragment whose consumer imposes the "
            "partition, but nothing composes it under principal_scoped"
        )
    # The control, and it is what makes the assertion above mean something: the
    # module does read the three unpartitioned evidence tables, so "every
    # statement is scoped" is a statement about a traversal that genuinely
    # leaves the partitioned tables rather than one that never does.
    for unscoped in ("capture_spans", "capture_proposals", "capture_proposal_spans"):
        assert unscoped not in partitioned, f"{unscoped} now carries a partition column"
        assert f"{unscoped}.c." in source, f"{unscoped} is no longer traversed here"


def test_every_corpus_coverage_statement_reaches_the_partition() -> None:
    """WP-23's corpus read, statement by statement.

    Claim 1 says `knowledge.py` uses `principal_scope` somewhere; this says every
    statement in it that names a partitioned table does. That is the claim the
    corpus capability's isolation rests on, and it is a stronger claim here than
    elsewhere in this module because `corpus_coverage` is the one read in the
    extraction plane with no enrollment identifier to be narrowed by: the
    authorization path confines every *other* read here to the caller's own
    enrollments before it runs, and confines this one to nothing at all, because
    its subject is every enrollment at once.

    The unit is one top-level statement inside a function, the same unit
    `test_every_relationship_statement_reaches_the_partition` uses. The floor is
    what stops this passing over a module the walk failed to parse, and the
    control below is what stops it passing over a module that simply never names
    the partitioned table.
    """
    path = PACKAGE / "infrastructure" / "persistence" / "knowledge.py"
    partitioned = set(_partitioned_tables())
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))

    checked = 0
    offending: list[str] = []
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        for statement in ast.walk(function):
            if not isinstance(statement, ast.Expr | ast.Assign | ast.Return):
                continue
            rendered = ast.unparse(statement)
            if not any(f"{table}.c" in rendered for table in partitioned):
                continue
            checked += 1
            if "partition_criterion(" not in rendered:
                offending.append(f"{function.name}:{statement.lineno}")

    assert checked >= 5, (
        f"only {checked} corpus statements were examined; the walk is not reaching "
        "the module's queries"
    )
    assert offending == [], (
        f"{offending} build a statement over `enrollments` without reaching the "
        "partition through `principal_scope`. A corpus answer is bounded by the "
        "acting Principal and by nothing else, so a statement here that lost its "
        "predicate would return another Principal's enrollments under this "
        "Principal's name"
    )
    # The control, and it is what makes the count above a measurement: this
    # module really does read unpartitioned tables beside the partitioned one, so
    # "every statement is scoped" is a claim about a module that queries more
    # than `enrollments` rather than one that barely queries it.
    for unpartitioned in ("enrollment_objects", "source_objects", "extractions"):
        assert unpartitioned not in partitioned, f"{unpartitioned} gained a partition column"
        assert f"{unpartitioned}.c." in source, f"{unpartitioned} is no longer read here"


#: The names `jobs.py` reaches a partitioned table through. It never names a
#: declaration: every statement is built against `plane.table`, so a scan that
#: looked for `jobs.c` — the way the relationship scan looks for its
#: declarations — would examine nothing and report zero offenders.
_PLANE_TABLES: Final = ("plane.table", "plane.owner_table")

#: What makes a statement a query rather than a fragment. `_abandoned`'s `and_`,
#: `release_job`'s `exhausted`, and `job_for`'s `reported` are predicate and
#: value pieces that the statements below compose; each is checked where it is
#: used, and counting them separately would ask a `case()` expression to carry a
#: partition it has nowhere to put.
_QUERY_MARKERS: Final = ("connection.execute(", "select(", ".update()", ".insert()")


def _named_assignments(function: ast.FunctionDef) -> tuple[tuple[str, ast.expr], ...]:
    bindings: list[tuple[str, ast.expr]] = []
    for node in ast.walk(function):
        if isinstance(node, ast.Assign):
            bindings.extend(
                (target.id, node.value) for target in node.targets if isinstance(target, ast.Name)
            )
        elif (
            isinstance(node, ast.AnnAssign)
            and node.value is not None
            and isinstance(node.target, ast.Name)
        ):
            bindings.append((node.target.id, node.value))
    return tuple(bindings)


def _to_a_fixed_point(
    bindings: tuple[tuple[str, ast.expr], ...], seed: frozenset[str], qualifies: object
) -> frozenset[str]:
    names = set(seed)
    changed = True
    while changed:
        changed = False
        for name, value in bindings:
            if name in names:
                continue
            if qualifies(value, frozenset(names)):  # type: ignore[operator]
                names.add(name)
                changed = True
    return frozenset(names)


def _plane_table_aliases(function: ast.FunctionDef) -> frozenset[str]:
    """Local names bound to a job plane's table — `table = plane.table`, and so on."""

    def qualifies(value: ast.expr, known: frozenset[str]) -> bool:
        rendered = ast.unparse(value)
        return rendered in _PLANE_TABLES or rendered in known

    return _to_a_fixed_point(_named_assignments(function), frozenset(), qualifies)


def _partition_predicate_names(function: ast.FunctionDef) -> frozenset[str]:
    """Local names holding a predicate or a value set the guard built.

    `claim_job` binds `mine = partition_criterion(...)` once and uses it in two
    statements, which is the right way to write it and would otherwise look to a
    text scan like two statements with no guard in them.

    Bound from a *direct* guard call, or from such a name alone. Not from
    anything that merely mentions one: `row = connection.execute(statement)`
    would then be "guarded" because `statement` was, and the rule would launder
    every following statement in the function.
    """

    def qualifies(value: ast.expr, known: frozenset[str]) -> bool:
        rendered = ast.unparse(value)
        return any(f"{call}(" in rendered for call in GUARD_CALLS) or rendered in known

    return _to_a_fixed_point(_named_assignments(function), frozenset(), qualifies)


def unpartitioned_job_statements() -> dict[str, int]:
    """`jobs.py`'s query statements that do not reach the partition, by function.

    Public, because a control below runs it against a `jobs.py` whose partition
    predicates have been read out of the file, so the small number it reports for
    the real module is a measurement rather than a scan that matched nothing.
    """
    path = PACKAGE / "infrastructure" / "persistence" / "jobs.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return _unpartitioned_statements_in(tree)


def _unpartitioned_statements_in(tree: ast.Module) -> dict[str, int]:
    offending: dict[str, int] = {}
    for function in ast.walk(tree):
        if not isinstance(function, ast.FunctionDef):
            continue
        aliases = _plane_table_aliases(function)
        predicates = _partition_predicate_names(function)
        for statement in ast.walk(function):
            if not isinstance(statement, ast.Expr | ast.Assign | ast.AnnAssign | ast.Return):
                continue
            rendered = ast.unparse(statement)
            if not any(marker in rendered for marker in _QUERY_MARKERS):
                continue
            used = {node.id for node in ast.walk(statement) if isinstance(node, ast.Name)}
            chains = {
                ast.unparse(node) for node in ast.walk(statement) if isinstance(node, ast.Attribute)
            }
            if not (used & aliases) and not (chains & set(_PLANE_TABLES)):
                continue
            reaches = any(f"{call}(" in rendered for call in GUARD_CALLS) or bool(used & predicates)
            if not reaches:
                offending[function.name] = offending.get(function.name, 0) + 1
    return offending


def test_every_job_statement_reaches_the_partition_or_is_registered() -> None:
    """C-3: the job plane, statement by statement rather than module by module.

    `jobs.py` was "reached through the guard" because two of its nine functions
    call `principal_scope`. That is how `job_for` and `job_state` came to read
    the whole table with only an operation id and be visible to neither this
    module's guarded set nor its `QUARANTINED` registry — a module-level
    accounting cannot see inside a module it has already accounted for.

    Exact equality against `UNPARTITIONED_JOB_STATEMENTS`, with counts, so a new
    unpartitioned statement reddens whether it is written in a new function or
    beside one that is already registered.
    """
    measured = unpartitioned_job_statements()
    registered = {name: count for name, (count, _) in UNPARTITIONED_JOB_STATEMENTS.items()}
    assert measured == registered, (
        f"the unpartitioned statements in `jobs.py` are now {measured} and the "
        f"registry says {registered}. Scope the statement through "
        "`principal_scope` — a required `principal_id` and a "
        "`partition_criterion`, the way `claim_job` and `job_for` take it — or "
        "register the function here with what holds the partition instead"
    )


def test_the_job_statement_scan_reports_a_statement_that_really_is_unscoped() -> None:
    """The control for C-3, on the exact regression the guard was blind to.

    `job_for` reading the plane with only an operation id is the defect this
    scan exists to catch, and it is reconstructed here by deleting the partition
    predicate from a parsed copy of the real module rather than by writing a
    synthetic function that resembles one.
    """
    path = PACKAGE / "infrastructure" / "persistence" / "jobs.py"
    source = path.read_text(encoding="utf-8")
    assert "partition_criterion(table, capture_context(principal_id))," in source, (
        "`job_for` no longer states its partition the way this control removes it"
    )
    unscoped = ast.parse(
        source.replace("partition_criterion(table, capture_context(principal_id)),", "")
    )
    measured = _unpartitioned_statements_in(unscoped)
    assert measured.get("job_for") == 1, (
        "the scan did not report `job_for` once its partition predicate was "
        f"removed; it reported {measured}, so the small number it reports for the "
        "real module means nothing"
    )

    # And the scan is looking at the real module's queries rather than at a
    # handful of them: the guarded statements outnumber the registered residual.
    guarded = len(
        [
            name
            for name in ("enqueue_job", "reap_abandoned_jobs", "claim_job", "job_for")
            if name not in unpartitioned_job_statements()
        ]
    )
    assert guarded == 4


def test_every_guarded_module_is_checked_per_statement_or_registered_as_not() -> None:
    """The other half of C-3: which guarded modules got the stronger check.

    Exact set equality against `REACHED_THROUGH_THE_GUARD`, so a module joining
    the guarded set has to be classified rather than inheriting the weaker
    per-module claim silently — which is the exact way `jobs.py` came to hold two
    unpartitioned reads that nothing in this file could see.
    """
    classified = STATEMENT_LEVEL | set(PER_MODULE_ONLY)
    assert classified == REACHED_THROUGH_THE_GUARD, (
        f"{sorted(classified ^ REACHED_THROUGH_THE_GUARD)} are guarded but not "
        "classified, or classified but not guarded. Say whether every statement "
        "in the module reaches the partition (STATEMENT_LEVEL) or only the module "
        "as a whole does (PER_MODULE_ONLY), with the reason"
    )
    overlap = sorted(STATEMENT_LEVEL & set(PER_MODULE_ONLY))
    assert overlap == [], f"{overlap} are both statement-level and per-module; one is wrong"

    # Each statement-level module has a test above that actually does it, and
    # the two are named here so removing one of those tests without removing the
    # claim reddens.
    assert (
        frozenset(
            {
                "infrastructure/persistence/jobs.py",
                "infrastructure/persistence/knowledge.py",
                "infrastructure/persistence/relationships.py",
                "infrastructure/persistence/reveal.py",
            }
        )
        == STATEMENT_LEVEL
    ), (
        "a module was added to STATEMENT_LEVEL without a statement-level test; "
        "`test_every_relationship_statement_reaches_the_partition`, "
        "`test_every_job_statement_reaches_the_partition_or_is_registered`, "
        "`test_every_reveal_statement_reaches_the_partition` and "
        "`test_every_corpus_coverage_statement_reaches_the_partition` are the "
        "four that exist"
    )
