"""AT-023 (S4, DB): Program reporting discloses nothing across Principals or families.

Record lineage S4 contract sections 6.1, 6.2 and 7.5, against PostgreSQL
through `ApplicationService.invoke` with the Program read pool composed as the
gateway composes it. The resolver rows (worker M2, WP-04A):

* another Principal's Program answers exactly as an absent one;
* a remote reader without a grant on `programs.members.resolve` is
  `unsupported` (the S3 grant re-check, R3-F13);
* a remote reader that does not see both the `entity` and the `project`
  family sees no Program -- `not_found`, never a partial answer;
* with either switch off, every S4 capability answers `unsupported`;
* a Program-read statement cancelled by its timeout answers `unavailable`.

The overview, Commitment v2 and manifest rows of the same section 10 entry are
added by their packages (workers M3, M4 and M5). Every identity is synthetic.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import text
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL
from tests.database.lineage_s3_read_harness import grant
from tests.database.lineage_s4_harness import (
    PROGRAM_STATEMENT_TIMEOUT_MS,
    T0,
    S4Runtime,
)

from my_pa.application.commands import (
    Command,
    ListCommitmentsV2,
    ReadCommitmentV2,
    ReadProgramOverview,
    ReadReportManifest,
    ResolveProgramMembers,
    SearchCommitmentsV2,
    WaitingOnV2,
)
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.program.vocabulary import PROGRAM_REPORTING_CAPABILITIES

pytestmark = pytest.mark.database

#: The 2 families both Program reads need (section 6.2), by one read each.
ROOT_READS: Final = ("entities.get", "continuity.projects")
#: An Entity identifier no row carries.
ABSENT: Final = "ent_programisolabsent01"


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S4Runtime]:
    composed = S4Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _program_with_member(runtime: S4Runtime, *, principal_id: str | None = None) -> str:
    seeds = runtime.seeds
    owner = {} if principal_id is None else {"principal_id": principal_id}
    program = seeds.program("Isolation Program", **owner)
    _project, entity = seeds.project("Isolation member", **owner)
    seeds.edge(entity, program, effective_from=T0, **owner)
    return program


def _document(error: dict[str, Any]) -> dict[str, Any]:
    """The error document without its per-request correlation id."""
    return {key: value for key, value in error.items() if key != "correlation_id"}


def _resolve(program: str) -> ResolveProgramMembers:
    return ResolveProgramMembers(program_entity_ids=(program,))


def _error(runtime: S4Runtime, command: Command, **kwargs: Any) -> tuple[str, list[str]]:  # noqa: ANN401
    error = runtime.refused(command, **kwargs)
    return str(error["code"]), list(error.get("safe_details") or [])


def test_a_foreign_program_answers_like_an_absent_one(runtime: S4Runtime) -> None:
    foreign = _program_with_member(runtime, principal_id=OTHER_PRINCIPAL)
    own = _program_with_member(runtime)
    # The owner sees its Program; the other Principal's id answers exactly as
    # an id no row carries -- the whole error document, not only its code.
    assert runtime.resolve(foreign, principal_id=OTHER_PRINCIPAL)["programs"][0]["members"]
    absent = _document(runtime.refused(_resolve(ABSENT)))
    assert _document(runtime.refused(_resolve(foreign))) == absent
    assert (absent["code"], absent["safe_details"]) == ("not_found", ["program_entity_ids"])
    # Mixed with an own Program, the foreign one still refuses the request.
    mixed = runtime.refused(ResolveProgramMembers(program_entity_ids=(own, foreign)))
    assert _document(mixed) == absent
    # Nothing of the other Principal's graph reaches an own Program's answer.
    answer = runtime.resolve(own)
    assert foreign not in str(answer)


def test_a_remote_read_without_its_grant_is_unsupported(runtime: S4Runtime) -> None:
    program = _program_with_member(runtime)
    # Every family read, but no grant on `programs.members.resolve` itself.
    families_only = grant(*ROOT_READS)
    assert _error(runtime, _resolve(program), grants=families_only) == ("unsupported", [])
    # A grant on it for a purpose it does not permit admits nothing either.
    misgranted = families_only | {(Capability.PROGRAMS_MEMBERS_RESOLVE, Purpose.REPORT_READ)}
    assert _error(runtime, _resolve(program), grants=misgranted) == ("unsupported", [])
    # With the grant, the same caller is answered.
    granted = grant("programs.members.resolve", *ROOT_READS)
    answer = runtime.ok(_resolve(program), grants=granted)
    assert len(answer["programs"][0]["members"]) == 1


@pytest.mark.parametrize(
    "reads",
    [(), ("entities.get",), ("continuity.projects",), ("continuity.projects.read",)],
    ids=["neither", "entity-only", "project-only", "project-read-only"],
)
def test_a_remote_reader_without_entity_and_project_reads_sees_no_program(
    runtime: S4Runtime, reads: tuple[str, ...]
) -> None:
    program = _program_with_member(runtime)
    grants = grant("programs.members.resolve", *reads)
    # Not a partial answer: the Program is invisible, as an absent one is.
    assert _error(runtime, _resolve(program), grants=grants) == (
        "not_found",
        ["program_entity_ids"],
    )
    assert _error(runtime, _resolve(ABSENT), grants=grants) == (
        "not_found",
        ["program_entity_ids"],
    )
    # Either read of each family is enough.
    for entity_read in ("entities.get", "entities.search"):
        for project_read in ("continuity.projects", "continuity.projects.read"):
            seen = grant("programs.members.resolve", entity_read, project_read)
            assert runtime.ok(_resolve(program), grants=seen)["programs"][0]["members"]


def _every_s4_command(program: str) -> list[Command]:
    return [
        ResolveProgramMembers(program_entity_ids=(program,)),
        ReadProgramOverview(program_entity_ids=(program,)),
        ReadCommitmentV2(commitment_id="cmt_programisolation01"),
        ListCommitmentsV2(),
        SearchCommitmentsV2(query="synthetic"),
        WaitingOnV2(),
        ReadReportManifest(report_id="rpt_programisolation01"),
    ]


@pytest.mark.parametrize(
    ("lineage", "program_reporting"),
    [(True, False), (False, True), (False, False)],
    ids=["program-switch-off", "lineage-off", "both-off"],
)
def test_switch_off_answers_unsupported_for_every_s4_capability(
    disposable_database: str, lineage: bool, program_reporting: bool
) -> None:
    off = S4Runtime(
        disposable_database, lineage_enabled=lineage, program_reporting_enabled=program_reporting
    )
    try:
        program = _program_with_member(off)
        commands = _every_s4_command(program)
        assert {command.capability.value for command in commands} == PROGRAM_REPORTING_CAPABILITIES
        for command in commands:
            # Locally and remotely with every grant: the switch decides first.
            assert _error(off, command) == ("unsupported", []), command.capability.value
            everything = grant(command.capability.value, *ROOT_READS)
            assert _error(off, command, grants=everything) == ("unsupported", [])
    finally:
        off.close()


def test_a_program_statement_timeout_answers_unavailable(runtime: S4Runtime) -> None:
    program = _program_with_member(runtime)
    locked = threading.Event()
    release = threading.Event()

    def hold_the_edges() -> None:
        # An `ACCESS EXCLUSIVE` lock is the one thing a read-only snapshot
        # read waits on; the Program engine's statement timeout cancels it.
        with runtime.engine.connect() as connection, connection.begin():
            connection.execute(
                text("LOCK TABLE knowledge.entity_relationships IN ACCESS EXCLUSIVE MODE")
            )
            locked.set()
            release.wait(timeout=30)

    holder = threading.Thread(target=hold_the_edges)
    holder.start()
    try:
        assert locked.wait(timeout=30)
        started = datetime.now(UTC)
        error = runtime.refused(_resolve(program))
        waited = (datetime.now(UTC) - started).total_seconds()
    finally:
        release.set()
        holder.join(timeout=30)
    assert (error["code"], error.get("safe_details") or []) == ("unavailable", [])
    # It waited one statement budget, not forever, and returned its connection.
    assert waited >= PROGRAM_STATEMENT_TIMEOUT_MS / 1000 * 0.9
    assert waited < 15
    assert runtime.program_engine.pool.checkedout() == 0  # type: ignore[attr-defined]
    # Once the lock is gone, the same read is answered.
    assert runtime.resolve(program)["programs"][0]["members"]
