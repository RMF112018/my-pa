"""`apps/cli/health.py` tells three states apart, over a real database.

The criterion this file exists for is **mutual distinguishability**, not exit
status. A probe that answered "something is wrong" for a server that is down and
for a server whose schema is four revisions behind would pass every
`exit != 0` assertion anyone could write and would still leave the operator
exactly where `D-61` found them: told the product is broken when the truth is one
of two different things to do about it. So the last test here compares the three
runs against each other rather than each against a constant.

**Why a downgraded database and not a mocked one.** The condition being probed is
a property of a running PostgreSQL server — what `public.alembic_version` holds
against what this repository's Alembic chain ends at — and the state the canonical
`my_pa` database is actually in on this machine. A fake would test this file's
opinion of that state. Downgrading to the unique predecessor of head produces
the real one, on a disposable database, and puts it back. Relative `-1` is
undefined at a merge revision.

**Nothing here touches the canonical database.** `MY_PA_DATABASE_URL` is
repointed at `my_pa_health_probe_test` for the module's lifetime — the probe
composes its own engine from `load_settings()`, which is the whole reason to run
the command rather than call its functions — and the previous value is restored
in `finally`.
"""

from __future__ import annotations

import io
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import apps.cli.health as probe
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
#: Distinct from every other suite's disposable database, so they cannot collide.
DISPOSABLE_DATABASE: Final = "my_pa_health_probe_test"

#: A port nothing listens on, so the driver fails to connect rather than failing
#: to authenticate. The database name stays the disposable one: what is being
#: measured is that the probe cannot reach it, not that it names it wrongly.
CLOSED_PORT: Final = 5499

#: An Alembic revision identifier as this repository writes them.
REVISION: Final = re.compile(r"^[0-9a-f]{12}$")


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def _revision_immediately_behind_head() -> str:
    """A unique Alembic target one step below the single head.

    Relative `-1` raises `Ambiguous walk` when head is a merge revision.
    Naming the first parent undoes only that merge, leaving both parents in
    `alembic_version` — which is one step behind head. On a linear head the
    named parent is the same revision `-1` would have chosen.
    """
    script = ScriptDirectory.from_config(_config())
    heads = script.get_heads()
    assert len(heads) == 1, f"the Alembic chain reports {len(heads)} heads, not one"
    parent = script.get_revision(heads[0]).down_revision
    if isinstance(parent, tuple):
        return parent[0]
    assert isinstance(parent, str), f"head {heads[0]} has no parent to stand behind"
    return parent


@pytest.fixture(scope="module")
def disposable_database() -> Iterator[str]:
    """An empty database at head, repointed to, and dropped when done."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')
    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = os.environ.get(variable)
    try:
        _administer(maintenance, drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        command.upgrade(_config(), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        _administer(maintenance, drop)
        maintenance.dispose()


def _run(capsys: pytest.CaptureFixture[str]) -> tuple[int, str]:
    """One invocation of the command, exactly as a shell would make it."""
    status = probe.main([])
    return status, capsys.readouterr().out


def _field(printed: str, name: str) -> str | None:
    """The value of one `name   value` line, or `None` when it was not printed.

    `None` rather than an exception, because *which* lines a run prints is part
    of what distinguishes the three states: the unreachable run deliberately
    reports no server version and no revision, and a helper that raised would
    turn that fact into an error instead of an observation.
    """
    for line in printed.splitlines():
        head, _, rest = line.partition(" ")
        if head == name:
            return rest.strip()
    return None


def _point_at(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    """Aim the command at one database, explicitly.

    Every fixture below sets this, including the two that want the value the
    module fixture already installed. Inheriting it would make each fixture
    depend on which other fixture pytest happened to resolve first, and that is
    not hypothetical: the first version of this file left `at_head` inheriting,
    a test requested `unreachable` ahead of it, and `at_head` measured the
    closed port — a control that silently became a second copy of the case it
    was supposed to control for.
    """
    monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)


@pytest.fixture
def at_head(
    disposable_database: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> tuple[int, str]:
    _point_at(monkeypatch, disposable_database)
    return _run(capsys)


@pytest.fixture
def behind_head(
    disposable_database: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> tuple[int, str]:
    """The same database, one unique step back, and put back afterwards."""
    _point_at(monkeypatch, disposable_database)
    command.downgrade(_config(), _revision_immediately_behind_head())
    try:
        return _run(capsys)
    finally:
        command.upgrade(_config(), "head")


@pytest.fixture
def unreachable(
    disposable_database: str, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> tuple[int, str]:
    _point_at(
        monkeypatch,
        make_url(disposable_database).set(port=CLOSED_PORT).render_as_string(hide_password=False),
    )
    return _run(capsys)


def test_the_chain_this_file_measures_against_has_exactly_one_head() -> None:
    """Guard the three tests below: they compare against `migration_heads()`.

    A chain reporting no head would make every comparison below compare two
    empty tuples and pass, which is the emptiness this campaign has shipped
    before.
    """
    heads = probe.migration_heads()
    assert len(heads) == 1, f"the Alembic chain reports {len(heads)} heads, not one"
    assert REVISION.match(heads[0]), f"{heads[0]!r} is not a revision identifier"


def test_a_database_at_head_reports_ready_and_exits_zero(at_head: tuple[int, str]) -> None:
    """The positive end. Every assertion is on a value, not on an absence."""
    status, printed = at_head
    assert status == probe.EXIT_OK, printed
    assert _field(printed, "state") == probe.STATE_READY
    assert _field(printed, "revision") == probe.migration_heads()[0]
    assert _field(printed, "head") == probe.migration_heads()[0]

    version = _field(printed, "server_version")
    assert version and version.startswith("17."), f"server_version was {version!r}"
    extensions = _field(printed, "extensions")
    assert extensions and "plpgsql" in extensions, f"extensions were {extensions!r}"


def test_a_database_one_revision_behind_names_what_it_is_and_what_head_is(
    behind_head: tuple[int, str],
) -> None:
    """The diagnosis `healthcheck` alone could never give.

    Both values are asserted, and asserted to *differ*: a probe that printed the
    head twice would satisfy "names a revision" and would tell an operator
    nothing about the gap they are in.
    """
    status, printed = behind_head
    assert status == probe.EXIT_REFUSED, printed
    assert _field(printed, "state") == probe.STATE_NOT_AT_HEAD

    current, head = _field(printed, "revision"), _field(printed, "head")
    assert current is not None, "revision was missing"
    for part in current.split(","):
        token = part.strip()
        assert REVISION.match(token), f"revision was {current!r}"
    assert head == probe.migration_heads()[0]
    assert current != head, "the probe reported the same revision for the database and for head"

    # The server is reachable, so the reachability half is still reported. This
    # is the isolation: the run reddens on the revision check and on nothing
    # else.
    version = _field(printed, "server_version")
    assert version and version.startswith("17."), f"server_version was {version!r}"


def test_an_unreachable_database_is_reported_as_that_and_not_as_a_schema_gap(
    unreachable: tuple[int, str], at_head: tuple[int, str]
) -> None:
    """The absent fields are the subject, so a control that has them sits beside.

    Asserting only that the unreachable run prints no `revision` would pass
    against a probe that prints no `revision` ever. `at_head` is the same
    command against a reachable database in the same test, and it does print
    one.
    """
    status, printed = unreachable
    assert status == probe.EXIT_REFUSED, printed
    assert _field(printed, "state") == probe.STATE_UNREACHABLE
    assert _field(printed, "revision") is None
    assert _field(printed, "server_version") is None

    _, control = at_head
    assert _field(control, "revision") is not None
    assert _field(control, "server_version") is not None


def test_the_unreachable_report_names_no_host_port_or_database(
    unreachable: tuple[int, str], disposable_database: str
) -> None:
    """The path most likely to leak a target is the one that failed to reach it.

    The driver's own `OperationalError` renders with the host and port, so a
    command that printed the exception would disclose them on exactly the run an
    operator is most likely to paste into an evidence file.
    """
    _, printed = unreachable
    url = make_url(disposable_database)
    for secret in (str(url.host), str(CLOSED_PORT), str(url.port), str(url.database)):
        assert secret not in printed, f"the unreachable report named {secret!r}"


def test_the_three_states_are_mutually_distinguishable(
    at_head: tuple[int, str], behind_head: tuple[int, str], unreachable: tuple[int, str]
) -> None:
    """AC-1's actual criterion: three runs, three answers, pairwise different.

    Compared against each other rather than against three constants. A probe
    that collapsed two states into one message would still match two constants
    and would fail here, which is the direction that matters — this campaign has
    now recorded four properties proven in a shape that could not tell its cases
    apart.
    """
    runs = {"at head": at_head, "behind head": behind_head, "unreachable": unreachable}

    states = {name: _field(printed, "state") for name, (_, printed) in runs.items()}
    assert None not in states.values(), f"a run printed no state line: {states}"
    assert len(set(states.values())) == 3, f"the three runs reported {states}"

    outputs = {name: printed for name, (_, printed) in runs.items()}
    assert len(set(outputs.values())) == 3, "two of the three runs printed identical output"

    statuses = {name: status for name, (status, _) in runs.items()}
    assert statuses["at head"] == probe.EXIT_OK
    assert statuses["behind head"] == probe.EXIT_REFUSED
    assert statuses["unreachable"] == probe.EXIT_REFUSED

    # And each state token belongs to exactly one run, so the vocabulary is not
    # merely three distinct strings that happen to co-occur.
    for token in (probe.STATE_READY, probe.STATE_NOT_AT_HEAD, probe.STATE_UNREACHABLE):
        naming = [
            name for name, printed in outputs.items() if f"state            {token}" in printed
        ]
        assert len(naming) == 1, f"{token!r} was reported by {naming}"
