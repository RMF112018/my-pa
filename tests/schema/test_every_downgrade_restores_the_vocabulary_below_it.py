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

Measured at the head that introduced this module: **six** `CHECK` constraints are
restated by a `downgrade` anywhere in the chain — `extraction_status_is_known` by
`9d4e7a3b1c62`, `capability_is_known` by `3c8f1e2a5b74`, `2b7e9f4c1a83` and
`1a4c9e77b2d5`, and `purpose_is_known` by `3c8f1e2a5b74` and `1a4c9e77b2d5`.
`KNOWN_RESTATED` holds that as a **floor** rather than restating it as a fact, so
a seventh is covered automatically and a drop to five is a failure.

**What was unguarded, stated as a negative result with its universe**, because
"nothing else is broken" is worth something only when the universe is named. Of
those six, the five that are not `9d4e7a3b1c62`'s already emitted the correct
text. But *correct* and *guarded* are different claims, and only two of the five
were guarded: `1a4c9e77b2d5`'s pair is pinned by
`test_capture_schema_migration.py::test_downgrading_this_revision_restores_the_previous_vocabulary`
in the database tier. `2b7e9f4c1a83`'s `capability_is_known` and `3c8f1e2a5b74`'s
pair were pinned by nothing —
`test_review_schema_migration.py::test_downgrading_this_revision_leaves_the_chain_below_it_intact`
downgrades across `3c8f1e2a5b74` but asserts over tables, not vocabularies. So
the reviewer's plant would have gone green in three of the four restating
revisions, not one. This module covers all six.

**Offline, and therefore in FAST.** Nothing here connects: `command.upgrade` and
`command.downgrade` with `sql=True` render the DDL both ways, which is exactly
the artefact the question is about — what a migration *emits*. The database tier
makes the same claim against a server for `9d4e7a3b1c62` and `1a4c9e77b2d5`; this
module makes it for every revision, cheaply enough to run on every commit.
Neither is sufficient alone: this one cannot see anything a server does to the
text it is handed, and the tier only visits the revisions its modules stop at.

**What it does NOT detect**, at demonstrated capability and no higher. Only
constraints a `downgrade` re-adds **by name**. A `downgrade` that drops a
constraint and never restores it emits no `ADD CONSTRAINT`, contributes no row
here, and is not covered. A `downgrade` written as an empty function is invisible
for the same reason — which is why `9d4e7a3b1c62` restates its text explicitly
rather than doing nothing, since doing nothing would reach the same database and
be unreadable. And the landing text is read from the upgrade stream by name, so a
constraint that a later revision dropped without re-adding would be reported as
still in force; no revision in the chain does that today.
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

#: Offline rendering still loads the process settings, and `MY_PA_DATABASE_URL`
#: is required with no default. Nothing is dialled: `sql=True` renders to a
#: buffer. The value is unroutable on purpose, so a render that tried to connect
#: would fail rather than reach something.
UNROUTABLE = "postgresql+psycopg://nobody@nowhere/nothing"

#: The revisions whose `downgrade` restates a `CHECK`, with the constraint each
#: restates, as measured at the head that added this module. A floor, not a
#: description: the subject here is a guard that could be narrowed without anyone
#: noticing, and a floor is what stops that.
KNOWN_RESTATED: Final[frozenset[tuple[str, str]]] = frozenset(
    {
        ("9d4e7a3b1c62", "extraction_status_is_known"),
        ("3c8f1e2a5b74", "capability_is_known"),
        ("3c8f1e2a5b74", "purpose_is_known"),
        ("2b7e9f4c1a83", "capability_is_known"),
        ("1a4c9e77b2d5", "capability_is_known"),
        ("1a4c9e77b2d5", "purpose_is_known"),
    }
)

#: `-- Running upgrade <from> -> <to>` and its downgrade twin, which is how
#: Alembic separates one revision's emitted DDL from the next's in `--sql` mode.
#: Splitting on it is what makes "the text in force at revision X" computable
#: from a single render rather than from one render per revision.
_BOUNDARY = "^-- Running {direction} (?P<source>[0-9a-f]*) -> (?P<target>[0-9a-f]*)"

#: `CONSTRAINT <name> CHECK (` in either shape Alembic emits — quoted from an
#: `op.execute` that writes the `ALTER` itself, unquoted from a `CREATE TABLE`
#: rendered out of a `Table`. Both are read, because a constraint created inline
#: by one revision and restated by an `ALTER` in another is the ordinary case and
#: reading only one shape would make the comparison compare nothing.
_CONSTRAINT = re.compile(r'CONSTRAINT "?(?P<name>\w+)"? CHECK \(')


def _config(buffer: io.StringIO) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


def _checks(body: str) -> list[tuple[str, str]]:
    """Every named `CHECK` in `body`, as `(name, expression)`.

    The expression is taken by matching parentheses rather than by a lazy regex,
    because every vocabulary in this repository is written `column IN ('a', 'b')`
    and a pattern that stopped at the first `)` would truncate every one of them
    to `column IN ('a'` — a silent corruption that would make two different
    vocabularies compare equal whenever their first member agreed.
    """
    found = []
    for match in _CONSTRAINT.finditer(body):
        index, depth = match.end(), 1
        while depth and index < len(body):
            depth += {"(": 1, ")": -1}.get(body[index], 0)
            index += 1
        found.append((match.group("name"), body[match.end() : index - 1].strip()))
    return found


def _blocks(stream: str, direction: str) -> list[tuple[str, str, str]]:
    """`(from, to, ddl)` for each revision in a rendered stream, in applied order."""
    parts = re.split(_BOUNDARY.format(direction=direction) + ".*$", stream, flags=re.M)
    return [(parts[i], parts[i + 1], parts[i + 2]) for i in range(1, len(parts), 3)]


@pytest.fixture
def restated() -> Iterator[list[tuple[str, str, str, str, str | None]]]:
    """Every `CHECK` a `downgrade` re-adds, beside the text in force where it lands.

    One row per `ADD CONSTRAINT ... CHECK` in the downgrade stream: the revision
    being undone, the revision it lands on, the constraint name, the text it
    restores, and the text the same name holds after upgrading from empty to that
    landing revision. The last is `None` when no upgrade block up to that point
    defines the name, which is a failure in its own right and asserted as one.
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

    def in_force(landing: str, name: str) -> str | None:
        held: str | None = None
        for _, target, body in upgrades:
            for emitted, expression in _checks(body):
                if emitted == name:
                    held = expression
            if target == landing:
                break
        return held

    rows = [
        (undone, landing, name, restores, in_force(landing, name))
        for undone, landing, body in _blocks(downward.getvalue(), "downgrade")
        for name, restores in _checks(body)
    ]
    yield sorted(rows)


def test_the_reader_finds_the_restatements_it_is_meant_to_read(
    restated: list[tuple[str, str, str, str, str | None]],
) -> None:
    """The control that makes the comparison below a measurement.

    The claim below quantifies over rows this render produced. A parse that
    matched nothing would produce no rows and the claim would pass vacuously,
    which is the shape of check this repository refuses. So the floor and the
    non-emptiness of every parsed expression are asserted first, against the real
    chain and not a synthetic one.
    """
    found = {(undone, name) for undone, _, name, _, _ in restated}

    assert found >= KNOWN_RESTATED, (
        "a downgrade stopped restating a constraint it used to restate, so the "
        f"claim below covers less than it did: {sorted(KNOWN_RESTATED - found)}"
    )
    for undone, _, name, restores, _ in restated:
        assert restores, f"{undone} restores {name} with an expression that parsed as empty"


def test_every_downgrade_restores_the_text_in_force_where_it_lands(
    restated: list[tuple[str, str, str, str, str | None]],
) -> None:
    """The claim, over every restatement in the chain at once.

    Every row is compared before anything is asserted, and the failure prints the
    whole table. That is deliberate: the five restatements that were already
    correct are the controls for the one that was not, and a failure that showed
    only the first disagreement would hide whether the guard could see the
    others at all.
    """
    table = [
        (undone, landing, name, restores, held, restores == held)
        for undone, landing, name, restores, held in restated
    ]
    report = "\n".join(
        f"  {undone} -> {landing}  {name}\n"
        f"      restores : {restores}\n"
        f"      in force : {held}\n"
        f"      agree    : {agree}"
        for undone, landing, name, restores, held, agree in table
    )

    assert all(agree for *_, agree in table), (
        "a downgrade restores a vocabulary the revision it lands on does not "
        "hold, so two databases at that revision would admit different values:\n"
        f"{report}"
    )
