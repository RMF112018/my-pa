"""What a `downgrade` puts back, measured against what the revision below emits.

**The defect this replaces was found by a reviewer's plant and was invisible to
every tier.** `9d4e7a3b1c62`'s `downgrade` restored a three-value
`extraction_status_is_known` while `8b3f5c17d904` — which builds `extractions`
from the *live* declaration — had been narrowed to two. So a database that went
up to head and back down to `7f2a9d6c4e18` admitted `quarantined` and a freshly
built one at the same revision did not: two databases, one revision, two schemas.
Measured that way against PostgreSQL 17.10 before this module existed, not
inferred. The reviewer's paired plant is the sharper statement of why nothing
caught it: `zz_reviewer_probe` in the *upgrade* constant reddened the FAST tier,
and the identical plant in the *downgrade* constant left it green. One direction
was pinned and the other was guarded by nothing.

**The class, not the case.** The subject is not one revision. It is the property
every revision's `downgrade` has to have: *the constraint text it restores is the
text in force at the revision it downgrades to*. Stated that way it is checkable
for the whole chain at once, and the chain is walked rather than listed — the
revisions, the constraint names and the vocabularies all come out of the SQL
Alembic renders, so a revision added tomorrow is covered with no edit here.

**The universe, named rather than counted.** Every `CHECK` a `downgrade` restates
anywhere in the chain, measured at the head that introduced this module:
`extraction_status_is_known` by `9d4e7a3b1c62`; `capability_is_known` by
`3c8f1e2a5b74`, `2b7e9f4c1a83` and `1a4c9e77b2d5`; `purpose_is_known` by
`3c8f1e2a5b74` and `1a4c9e77b2d5`. `KNOWN_RESTATED` holds that list as a
**floor** rather than as a description, so a restatement added later is covered
automatically and one that disappears is a failure. It is a list and not a
spelled figure on purpose: a written-down count of a current set is the defect
`D-108` had to correct twice, once inside the guard whose subject it is.

**What was unguarded, stated as a negative result over that universe**, because
"nothing else is broken" is worth something only when the universe is named.
Every restatement that is not `9d4e7a3b1c62`'s already emitted the correct text.
But *correct* and *guarded* are different claims, and most of them were not
guarded. `1a4c9e77b2d5`'s pair is pinned by
`test_capture_schema_migration.py::test_downgrading_this_revision_restores_the_previous_vocabulary`
in the database tier — that is the whole of the prior coverage.
`2b7e9f4c1a83`'s `capability_is_known` and `3c8f1e2a5b74`'s pair were pinned by
nothing:
`test_review_schema_migration.py::test_downgrading_this_revision_leaves_the_chain_below_it_intact`
downgrades across `3c8f1e2a5b74` but asserts over tables, not vocabularies. So
the reviewer's plant would have gone green in every restating revision except
`1a4c9e77b2d5`'s — not only in the one it was aimed at. Planted rather than
argued: `zz_reviewer_probe` added to `2b7e9f4c1a83`'s
`_CAPABILITIES_BEFORE_THIS_REVISION` and to `3c8f1e2a5b74`'s
`_PURPOSES_BEFORE_THIS_REVISION`, each run twice — with this module deselected
the whole FAST tier is **2995 passed, green**, and with it selected the same tree
is **1 failed, 2996 passed**. Deselected rather than deleted: deleting the file
reddens the repository's own test-module count instead, which is a different
signal and would have made this control read the wrong way. This module covers
the whole list.

**Offline, and therefore in FAST.** Nothing here connects: `command.upgrade` and
`command.downgrade` with `sql=True` render the DDL both ways, which is exactly
the artefact the question is about — what a migration *emits*. The database tier
makes the same claim against a server for `9d4e7a3b1c62` and `1a4c9e77b2d5`; this
module makes it for every revision, cheaply enough to run on every commit.
Neither is sufficient alone: this one cannot see anything a server does to the
text it is handed, and the tier only visits the revisions its modules stop at.

**Keyed by `(table, constraint)` and not by constraint name, because a name alone
does not identify a constraint here.** Measured over the rendered chain: seven
names sit on more than one table — `state_is_known` on both
`knowledge.jobs` (`failed, queued, running, succeeded`) and
`migration_control.table_progress` (`RUNNING, COMPLETED, FAILED`),
`status_is_known` on two `migration_control` tables, and five
`*_is_an_opaque_identifier` names across the capture and audit tables. **A first
version of this module looked the landing text up by name alone, and an
independent reviewer broke it with a plant**: a `downgrade` restoring
`migration_control.table_progress.state_is_known` with `knowledge.jobs`'
vocabulary left this module green at 2 passed while two real databases at
`7f2a9d6c4e18` diverged exactly as described above. The table comes from the
enclosing `CREATE TABLE` or the `ALTER TABLE` that carries the statement, so
`(table, name)` is the key on both sides of every comparison. That plant now
reddens.

**What it does NOT detect**, at demonstrated capability and no higher.

* **`CHECK` constraints only.** `_CONSTRAINT` matches `CONSTRAINT <name> CHECK
  (`, so a `UNIQUE`, `FOREIGN KEY`, `PRIMARY KEY` or `EXCLUDE` constraint that a
  `downgrade` re-adds over different columns contributes no row here and is not
  covered. "Vocabulary" in this module means the literals inside a `CHECK`, not
  any other thing a constraint can constrain.
* **Only what a `downgrade` re-adds.** A `downgrade` that drops a constraint and
  never restores it emits no `ADD CONSTRAINT` and is not covered, and one written
  as an empty function is invisible for the same reason — which is why
  `9d4e7a3b1c62` restates its text explicitly rather than doing nothing, since
  doing nothing would reach the same database unreadably.
* **Only `CHECK` text, not the rest of the schema.** Two databases at one
  revision can still differ in a column type, an index, or a trigger, and nothing
  here would say so. `test_head_round_trip.py` makes the whole-database
  comparison, and only at `base`.

The landing text is accumulated from the upgrade stream up to the revision the
downgrade lands on, so a constraint dropped by a later revision and never re-added
would still be reported as in force at that landing. No revision in the chain does
that — every `DROP CONSTRAINT` in the upgrade stream is paired with an `ADD` — and
that is a measurement rather than an assumption, but it is not asserted here.
Landing on `base` is handled rather than left latent: nothing is in force at
`base`, so a `downgrade` that re-added a `CHECK` on the way there fails outright.
"""

from __future__ import annotations

import io
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config

from my_pa.bootstrap.settings import ENV_PREFIX

ROOT = Path(__file__).resolve().parents[2]

#: `(revision undone, revision landed on, table, constraint, text restored,
#: text in force where it lands)`. The landing text is `None` when nothing
#: holds that `(table, constraint)` there, which the claim refuses.
Restatement = tuple[str, str, str, str, str, str | None]

#: Offline rendering still loads the process settings, and `MY_PA_DATABASE_URL`
#: is required with no default. Nothing is dialled: `sql=True` renders to a
#: buffer. The value is unroutable on purpose, so a render that tried to connect
#: would fail rather than reach something.
UNROUTABLE = "postgresql+psycopg://nobody@nowhere/nothing"

#: Every `(revision, table, constraint)` whose `downgrade` restates a `CHECK`,
#: as rendered at the head that added this module.
#:
#: **Asserted as an equality, not as a floor.** A floor was the first version and
#: an independent reviewer showed it was worth nothing: deleting a row from it
#: left the whole FAST tier green, because the claim below quantifies over
#: rendered rows and never notices that the list describing them got shorter. An
#: equality reddens both ways — a restatement added to the chain and a row
#: deleted from here — which is what "widening or narrowing this guard requires
#: editing this file" has to mean to be true. No count is spelled anywhere,
#: because the set is the assertion.
KNOWN_RESTATED: Final[frozenset[tuple[str, str, str]]] = frozenset(
    {
        ("9d4e7a3b1c62", "knowledge.extractions", "extraction_status_is_known"),
        ("3c8f1e2a5b74", "knowledge.audit_events", "capability_is_known"),
        ("3c8f1e2a5b74", "knowledge.audit_events", "purpose_is_known"),
        ("2b7e9f4c1a83", "knowledge.audit_events", "capability_is_known"),
        ("1a4c9e77b2d5", "knowledge.audit_events", "capability_is_known"),
        ("1a4c9e77b2d5", "knowledge.audit_events", "purpose_is_known"),
    }
)

#: `-- Running upgrade <from> -> <to>` and its downgrade twin, which is how
#: Alembic separates one revision's emitted DDL from the next's in `--sql` mode.
#: Splitting on it is what makes "the text in force at revision X" computable
#: from a single render rather than from one render per revision.
_BOUNDARY = "^-- Running {direction} (?P<source>[0-9a-f]*) -> (?P<target>[0-9a-f]*)"

#: Either the statement that names a table, or a named `CHECK` inside one.
#:
#: Scanned as **one** pattern rather than two passes so that the matches arrive
#: in source order, which is what lets a `CHECK` be attributed to the table whose
#: statement encloses it. `CREATE TABLE` covers the inline shape a `Table`
#: renders to and `ALTER TABLE` the shape an `op.execute` writes; the constraint
#: name is quoted in the second and bare in the first, so both are accepted.
#: Reading only one shape would make the comparison compare nothing, since a
#: constraint created inline by one revision and restated by an `ALTER` in
#: another is the ordinary case here.
_TOKEN = re.compile(
    r"\b(?:CREATE|ALTER) TABLE\s+(?:IF NOT EXISTS\s+)?(?P<table>[\w.\"]+)"
    r'|CONSTRAINT "?(?P<name>\w+)"? CHECK \('
)


def _config(buffer: io.StringIO) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


def _checks(body: str) -> list[tuple[str, str, str]]:
    """Every named `CHECK` in `body`, as `(table, name, expression)`.

    The table is the one most recently named by a `CREATE TABLE` or `ALTER TABLE`
    ahead of the constraint, which is where the statement puts it in both shapes.
    Carrying it is not decoration: seven constraint names in this chain sit on
    more than one table, so a `(name, expression)` pair does not identify
    anything and a comparison keyed on it silently compares two different
    constraints.

    The expression is taken by matching parentheses rather than by a lazy regex,
    because every vocabulary in this repository is written `column IN ('a', 'b')`
    and a pattern that stopped at the first `)` would truncate every one of them
    to `column IN ('a'` — a silent corruption that would make two different
    vocabularies compare equal whenever their first member agreed.
    """
    found = []
    table = "<no table named before this constraint>"
    for match in _TOKEN.finditer(body):
        if match.group("table") is not None:
            table = match.group("table").replace('"', "").lower()
            continue
        index, depth = match.end(), 1
        while depth and index < len(body):
            depth += {"(": 1, ")": -1}.get(body[index], 0)
            index += 1
        found.append((table, match.group("name"), body[match.end() : index - 1].strip()))
    return found


def _blocks(stream: str, direction: str) -> list[tuple[str, str, str]]:
    """`(from, to, ddl)` for each revision in a rendered stream, in applied order."""
    parts = re.split(_BOUNDARY.format(direction=direction) + ".*$", stream, flags=re.M)
    return [(parts[i], parts[i + 1], parts[i + 2]) for i in range(1, len(parts), 3)]


@pytest.fixture
def restated() -> Iterator[list[Restatement]]:
    """Every `CHECK` a `downgrade` re-adds, beside the text in force where it lands.

    One row per `ADD CONSTRAINT ... CHECK` in the downgrade stream: the revision
    being undone, the revision it lands on, the qualified table, the constraint
    name, the text it restores, and the text that same `(table, constraint)`
    holds after upgrading from empty to that landing revision. The last is `None`
    when no upgrade block up to that point defines it — including when the
    landing is `base`, where nothing is in force at all — which is a failure in
    its own right and asserted as one.
    """
    previous = os.environ.get(f"{ENV_PREFIX}DATABASE_URL")
    os.environ[f"{ENV_PREFIX}DATABASE_URL"] = UNROUTABLE
    try:
        upward, downward = io.StringIO(), io.StringIO()
        command.upgrade(_config(upward), "head", sql=True)
        command.downgrade(_config(downward), "head:base", sql=True)
    finally:
        if previous is None:
            os.environ.pop(f"{ENV_PREFIX}DATABASE_URL", None)
        else:
            os.environ[f"{ENV_PREFIX}DATABASE_URL"] = previous

    upgrades = _blocks(upward.getvalue(), "upgrade")

    def in_force(landing: str, table: str, name: str) -> str | None:
        """The text `(table, name)` holds after `upgrade base:landing`.

        `landing` is empty for the block that lands on `base`, which no upgrade
        block's target ever equals — so the loop below runs to the end and would
        return the head-most text for a database that holds nothing at all.
        Refused explicitly instead: at `base` there is no constraint in force,
        and a downgrade re-adding one there is a defect rather than a comparison.
        """
        if not landing:
            return None
        held: str | None = None
        for _, target, body in upgrades:
            for emitted_table, emitted, expression in _checks(body):
                if (emitted_table, emitted) == (table, name):
                    held = expression
            if target == landing:
                break
        return held

    rows = [
        (undone, landing, table, name, restores, in_force(landing, table, name))
        for undone, landing, body in _blocks(downward.getvalue(), "downgrade")
        for table, name, restores in _checks(body)
    ]
    yield sorted(rows)


def test_the_reader_finds_the_restatements_it_is_meant_to_read(
    restated: list[Restatement],
) -> None:
    """The control that makes the comparison below a measurement.

    The claim below quantifies over rows this render produced. A parse that
    matched nothing would produce no rows and the claim would pass vacuously,
    which is the shape of check this repository refuses. So the set of rows is
    asserted equal to `KNOWN_RESTATED`, and every parsed expression asserted
    non-empty, against the real chain and not a synthetic one.

    Equality in both directions, and the two failures mean different things. A
    row this render no longer produces means a downgrade stopped restating
    something, so the claim below covers less than it did. A row this render
    produces that is not listed means a restatement entered the chain without
    anyone editing this file — which is the only thing that makes "widening this
    guard requires editing it" true rather than said.
    """
    found = {(undone, table, name) for undone, _, table, name, _, _ in restated}

    assert found == KNOWN_RESTATED, (
        "the set of restated constraints moved. Gone from the chain: "
        f"{sorted(KNOWN_RESTATED - found)}; new and unlisted: {sorted(found - KNOWN_RESTATED)}"
    )
    for undone, _, table, name, restores, _ in restated:
        assert restores, f"{undone} restores {table}.{name} with an expression that parsed as empty"


def test_every_downgrade_restores_the_text_in_force_where_it_lands(
    restated: list[Restatement],
) -> None:
    """The claim, over every restatement in the chain at once.

    Every row is compared before anything is asserted, and the failure prints the
    whole table. That is deliberate: the restatements that are already correct
    are the controls for any that is not, and a failure that showed only the
    first disagreement would hide whether the guard could see the others at all.
    """
    compared = [
        (undone, landing, table, name, restores, held, restores == held)
        for undone, landing, table, name, restores, held in restated
    ]
    report = "\n".join(
        f"  {undone} -> {landing or 'base'}  {table}.{name}\n"
        f"      restores : {restores}\n"
        f"      in force : {held}\n"
        f"      agree    : {agree}"
        for undone, landing, table, name, restores, held, agree in compared
    )

    assert all(agree for *_, agree in compared), (
        "a downgrade restores a vocabulary the revision it lands on does not "
        "hold, so two databases at that revision would admit different values:\n"
        f"{report}"
    )
