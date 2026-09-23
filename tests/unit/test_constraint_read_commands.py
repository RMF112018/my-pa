"""The six Constraint reads reach WP03's service and add nothing on the way.

`PC-CM-IMP-WP04` exposes a read plane that already exists. The risk it carries is
not that a read is wrong — `tests/database` proves the reads against a real
server — but that the *exposure* quietly becomes a second implementation: a
handler that filtered a page, recomputed a flag, or read the Principal out of the
payload would answer plausibly and disagree with the plane it claims to publish.

So three claims, and they are different in kind.

**Dispatch.** Every read capability has a handler, every handler is registered
under the capability its command declares, and every command is in the union the
MCP tool set is generated from. A command omitted from that union is *silently*
excluded from the published tools, which is the failure this file exists to make
loud.

**Delegation.** Each handler calls exactly one method of `ConstraintReadService`,
with the Principal taken from the authorization and never from the command, and
returns what came back. Measured by a recording repository rather than by reading
the source: what matters is which call happened, not which line was written.

**Non-recomputation.** The handler bodies are read as source and asserted to name
no date arithmetic, no business-day helper, no party comparison and no
aggregation. This is the one claim a behavioural test cannot make, because a
handler that recomputed a flag *correctly* would return the same answer today and
drift the first time the read plane changed.
"""

from __future__ import annotations

import ast
import inspect
import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, Final, get_args

import pytest

from my_pa.adapters.mcp import TOOLS
from my_pa.adapters.mcp.tools import input_schema_for
from my_pa.adapters.normalization import _BUILDERS, PAYLOAD_KEY, normalize
from my_pa.application.commands import (
    Command,
    ListConstraintCategories,
    ListConstraints,
    ListPortfolioConstraints,
    ReadConstraint,
    ReadConstraintHistory,
    ReadConstraintOverview,
    ReadPortfolioConstraintOverview,
    SearchConstraints,
    SearchPortfolioConstraints,
)
from my_pa.application.disclosure import Limitation
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.application.service import _HANDLERS, MAX_PORTFOLIO_PROJECTS, ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.project_controls.constraint import ConstraintOrigin, ConstraintRecordQuality
from my_pa.domain.project_controls.read_models import (
    MAX_CURSOR_CHARACTERS,
    MAX_LIST_LIMIT,
    MAX_SEARCH_CHARACTERS,
    ConstraintCategoryState,
    ConstraintGrouping,
    ConstraintLifecycleState,
    ConstraintListCursor,
    ConstraintListQuery,
    ConstraintListScope,
    ConstraintSort,
    PersistedConstraintRecord,
    SortDirection,
)
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.domain.source.registry import issue_identifier
from tests.conftest import (
    DEFAULT_LIMITS,
    WHEN,
    FakeConstraintManagementUnitOfWork,
    FakeUnitOfWork,
    Scene,
    metadata_for,
)

#: Capability -> the command class that serves it and the read-service method the
#: handler must reach. Written out, because "the handler calls something" is not
#: the claim: `constraints.search` and `constraints.list` share a method on
#: purpose (a search *is* a Register request with a search predicate) and a table
#: derived from the code could not say that was intended.
EXPECTED: Final[dict[Capability, tuple[type, str]]] = {
    Capability.CONSTRAINTS_READ: (ReadConstraint, "read_constraint"),
    Capability.CONSTRAINTS_LIST: (ListConstraints, "list_constraints"),
    Capability.CONSTRAINTS_SEARCH: (SearchConstraints, "list_constraints"),
    Capability.CONSTRAINTS_HISTORY: (ReadConstraintHistory, "read_history"),
    Capability.CONSTRAINTS_OVERVIEW: (ReadConstraintOverview, "read_overview"),
    Capability.CONSTRAINT_CATEGORIES_LIST: (ListConstraintCategories, "list_categories"),
}

PORTFOLIO_EXPECTED: Final[dict[Capability, tuple[type, str]]] = {
    Capability.CONSTRAINTS_PORTFOLIO_LIST: (
        ListPortfolioConstraints,
        "list_portfolio_constraints",
    ),
    Capability.CONSTRAINTS_PORTFOLIO_SEARCH: (
        SearchPortfolioConstraints,
        "list_portfolio_constraints",
    ),
    Capability.CONSTRAINTS_PORTFOLIO_OVERVIEW: (
        ReadPortfolioConstraintOverview,
        "read_portfolio_overview",
    ),
}


#: Both tables at once, for the claims that are about every Constraint read
#: rather than about one family: a handler that recomputed a derived answer is
#: the same defect whether it names one Project or all of them.
ALL_READS: Final[dict[Capability, tuple[type, str]]] = {**EXPECTED, **PORTFOLIO_EXPECTED}

#: Names whose presence in a handler body would mean the exposure had started
#: deciding something. Derivation vocabulary (`overdue`, `due_soon`, `my_court`,
#: `business_day`) and the arithmetic that produces it.
FORBIDDEN_IN_A_HANDLER: Final[tuple[str, ...]] = (
    "business_day",
    "due_soon_through",
    "timedelta",
    "_project_today",
    "_is_overdue",
    "_is_due_soon",
    "_days_elapsed",
    "_group_keys",
    "_sort_key",
    "sum",
    "len",
)


class _Recorder:
    """A `ConstraintReadService` that records the one call it was asked to make."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def _record(self, name: str) -> Any:  # noqa: ANN401 - a spy returns what it is given
        def call(_repository: object, **keywords: Any) -> Any:  # noqa: ANN401 - see above
            self.calls.append((name, keywords))
            return _ANSWERS[name]

        return call

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401 - see above
        if name not in _ANSWERS:
            raise AttributeError(name)
        return self._record(name)


class _Page:
    """The shape the paging handlers read off a page, and nothing else."""

    entries: tuple[object, ...] = ()
    is_truncated = False
    next_cursor: str | None = None


#: What the spy answers with. JSON containers, because the handler renders what
#: it is given into the envelope and a bare sentinel is not a document.
_ANSWERS: Final[dict[str, Any]] = {
    "read_constraint": (),
    "list_constraints": _Page(),
    "read_history": _Page(),
    "read_overview": (),
    "list_categories": (),
}


def _service(scene: Scene, recorder: _Recorder | None = None) -> ApplicationService:
    scene.world.providers = scene.providers
    service = ApplicationService(
        unit_of_work=lambda: FakeUnitOfWork(scene.world),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        constraint_management_unit_of_work=lambda: FakeConstraintManagementUnitOfWork(scene.world),
    )
    if recorder is not None:
        service._constraint_reads = recorder  # type: ignore[assignment]
    return service


def _run(service: ApplicationService, scene: Scene, command: object) -> ResponseEnvelope:
    capability = command.capability  # type: ignore[attr-defined]
    return service.invoke(
        metadata_for(capability, Purpose.CONSTRAINT_READ, scene.principal),
        command,  # type: ignore[arg-type] - the union is exercised member by member
        principal=scene.principal,
    )


def _command_for(capability: Capability, scene: Scene) -> object:
    if capability is Capability.CONSTRAINTS_READ:
        return ReadConstraint(constraint_id=scene.constraint_id)
    if capability is Capability.CONSTRAINTS_LIST:
        return ListConstraints(project_id=scene.constraint_project_id)
    if capability is Capability.CONSTRAINTS_SEARCH:
        return SearchConstraints(project_id=scene.constraint_project_id, query="synthetic")
    if capability is Capability.CONSTRAINTS_HISTORY:
        return ReadConstraintHistory(constraint_id=scene.constraint_id)
    if capability is Capability.CONSTRAINTS_OVERVIEW:
        return ReadConstraintOverview(project_id=scene.constraint_project_id)
    return ListConstraintCategories(project_id=scene.constraint_project_id)


# ---- dispatch ---------------------------------------------------------------


@pytest.mark.parametrize("capability", sorted(EXPECTED, key=lambda c: c.value))
def test_every_constraint_read_capability_has_a_handler(capability: Capability) -> None:
    assert capability in _HANDLERS


@pytest.mark.parametrize("capability", sorted(EXPECTED, key=lambda c: c.value))
def test_every_constraint_read_command_declares_its_own_capability(
    capability: Capability,
) -> None:
    command, _method = EXPECTED[capability]
    assert command.capability is capability  # type: ignore[attr-defined]


@pytest.mark.parametrize("capability", sorted(EXPECTED, key=lambda c: c.value))
def test_every_constraint_read_command_is_in_the_command_union(
    capability: Capability,
) -> None:
    """Union membership is what publishes the MCP tool, so it is asserted by name.

    `adapters.mcp.tools._COMMANDS` is built from `get_args(Command.__value__)`. A
    command that exists, validates and dispatches but is missing from the union
    produces no tool and no error anywhere.
    """
    command, _method = EXPECTED[capability]
    assert command in get_args(Command.__value__)


# ---- delegation -------------------------------------------------------------


@pytest.mark.parametrize("capability", sorted(EXPECTED, key=lambda c: c.value))
def test_each_handler_makes_exactly_one_canonical_read_call(
    capability: Capability, scene: Scene
) -> None:
    recorder = _Recorder()
    envelope = _run(_service(scene, recorder), scene, _command_for(capability, scene))
    assert envelope.error is None, envelope.error
    _command, method = EXPECTED[capability]
    assert [name for name, _keywords in recorder.calls] == [method]


@pytest.mark.parametrize("capability", sorted(EXPECTED, key=lambda c: c.value))
def test_each_handler_passes_the_authenticated_principal_and_never_a_payload_field(
    capability: Capability, scene: Scene
) -> None:
    """The Principal comes from the authorization; no command carries one.

    Both halves are asserted, because either alone is satisfiable by accident: a
    handler could read a payload field that happens to hold the right value, and
    a command could omit the field while the handler passed something else.
    """
    recorder = _Recorder()
    command = _command_for(capability, scene)
    assert not [field for field in vars(type(command)).get("__slots__", ()) if "principal" in field]
    _run(_service(scene, recorder), scene, command)
    (_name, keywords) = recorder.calls[0]
    assert keywords["principal_id"] == scene.principal.principal_id


@pytest.mark.parametrize("capability", sorted(EXPECTED, key=lambda c: c.value))
def test_each_handler_answers_against_the_real_read_service(
    capability: Capability, scene: Scene
) -> None:
    """The same six, without the spy, so the wiring is proved end to end."""
    envelope = _run(_service(scene), scene, _command_for(capability, scene))
    assert envelope.error is None, envelope.error
    assert envelope.result is not None


def test_a_foreign_principals_constraint_is_answered_as_an_absent_one(
    scene: Scene,
) -> None:
    """`CM-BE-AC-078` at this layer: not-found and not-yours are one answer.

    The identifier is well formed and names nothing in this partition, which is
    the same thing a Constraint another Principal owns is to this Principal: the
    repository's lookup key includes `principal_id`, so there is no branch here
    that could distinguish them even by accident.
    """
    envelope = _run(
        _service(scene),
        scene,
        ReadConstraint(constraint_id=issue_identifier(IdKind.PROJECT_CONSTRAINT)),
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.NOT_FOUND
    assert not envelope.error.safe_details


def test_an_unconfigured_project_calendar_is_unavailable_rather_than_empty(
    scene: Scene,
) -> None:
    """The read plane's own fail-closed answer, carried through unchanged.

    A count of zero overdue Constraints is a claim the read service refuses to
    make without a Project calendar, and the exposure must not soften that into
    an empty page.
    """
    envelope = _run(
        _service(scene),
        scene,
        ReadConstraintOverview(project_id=issue_identifier(IdKind.PROJECT)),
    )
    assert envelope.error is not None
    assert envelope.error.code is ErrorCode.UNAVAILABLE


# ---- malformed requests -----------------------------------------------------


def test_a_malformed_constraint_identifier_is_an_invalid_request() -> None:
    with pytest.raises(InvalidRequestError) as refusal:
        ReadConstraint(constraint_id="not-an-identifier")
    assert refusal.value.safe_details == (SafeDetail.CONSTRAINT_ID,)


def test_a_non_string_identifier_is_refused_before_it_is_read() -> None:
    """`123` is not a string, and the refusal must be classified rather than raised."""
    with pytest.raises(InvalidRequestError):
        ReadConstraint(constraint_id=123)  # type: ignore[arg-type]


@pytest.mark.parametrize("limit", [0, -1, MAX_LIST_LIMIT + 1, True])
def test_a_page_limit_outside_the_domains_bound_is_an_invalid_request(limit: object) -> None:
    with pytest.raises(InvalidRequestError) as refusal:
        ListConstraints(project_id=issue_identifier(IdKind.PROJECT), limit=limit)  # type: ignore[arg-type]
    assert refusal.value.safe_details == (SafeDetail.LIMIT,)


def test_an_oversized_cursor_is_refused_before_it_is_decoded() -> None:
    with pytest.raises(InvalidRequestError) as refusal:
        ListConstraints(
            project_id=issue_identifier(IdKind.PROJECT),
            cursor="x" * (MAX_CURSOR_CHARACTERS + 1),
        )
    assert refusal.value.safe_details == (SafeDetail.CURSOR,)


def test_an_oversized_search_term_is_refused() -> None:
    with pytest.raises(InvalidRequestError) as refusal:
        SearchConstraints(
            project_id=issue_identifier(IdKind.PROJECT),
            query="x" * (MAX_SEARCH_CHARACTERS + 1),
        )
    assert refusal.value.safe_details == (SafeDetail.QUERY,)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scope", "open"),
        ("sort", "code"),
        ("sort_order", "asc"),
        ("grouping", "category"),
    ],
)
def test_a_closed_vocabulary_field_refuses_a_bare_string(field: str, value: str) -> None:
    """The wire form is converted by `adapters.normalization`, never here.

    A command that accepted the string would make the enum advisory, and the
    published schema's `enum` would stop describing what is enforced.
    """
    with pytest.raises(InvalidRequestError):
        ListConstraints(project_id=issue_identifier(IdKind.PROJECT), **{field: value})


def test_a_filter_family_refuses_a_member_of_another_vocabulary() -> None:
    with pytest.raises(InvalidRequestError):
        ListConstraintCategories(
            project_id=issue_identifier(IdKind.PROJECT),
            states=(ConstraintListScope.OPEN,),  # type: ignore[arg-type]
        )


def test_the_well_formed_shapes_this_file_asserts_against_are_accepted() -> None:
    """The green half, so the refusals above are not the only thing measured."""
    project_id = issue_identifier(IdKind.PROJECT)
    ListConstraints(
        project_id=project_id,
        scope=ConstraintListScope.ALL,
        sort=ConstraintSort.DUE_DATE,
        sort_order=SortDirection.DESC,
        grouping=ConstraintGrouping.NONE,
        limit=MAX_LIST_LIMIT,
    )
    ListConstraintCategories(project_id=project_id, states=(ConstraintCategoryState.ACTIVE,))
    SearchConstraints(project_id=project_id, query="a bounded term")


# ---- no semantic recomputation ----------------------------------------------


def _handler_source(capability: Capability) -> str:
    return inspect.getsource(_HANDLERS[capability])


@pytest.mark.parametrize("capability", sorted(ALL_READS, key=lambda c: c.value))
@pytest.mark.parametrize("forbidden", FORBIDDEN_IN_A_HANDLER)
def test_no_handler_body_recomputes_a_derived_answer(
    capability: Capability, forbidden: str
) -> None:
    """Read as source, because a correct recomputation passes every other test.

    Overdue, Due Soon, In My Court, the recent windows, the attention fields, the
    grouping, the cursor semantics and the overview formulas are decided in
    `application.constraints`. A second decision here would agree today and drift
    the first time that plane changed, which is the failure no behavioural
    assertion can see.
    """
    body = _handler_source(capability)
    assert not re.search(rf"\b{re.escape(forbidden)}\b", body), (
        f"the {capability.value} handler names `{forbidden}`. Every derived flag, "
        "count, group and cursor belongs to `application.constraints`; the handler "
        "opens a transaction, calls one read and renders what came back"
    )


@pytest.mark.parametrize("capability", sorted(ALL_READS, key=lambda c: c.value))
def test_no_handler_body_compares_two_dates_or_two_parties(capability: Capability) -> None:
    """No comparison operator at all in a handler body.

    Overdue is a date comparison and In My Court is a party comparison; a handler
    with neither cannot have made either. The `is None` tests a handler legitimately
    needs are `ast.Is`, not `ast.Compare` operators of the ordering kind.
    """
    tree = ast.parse(inspect.getsource(_HANDLERS[capability]).lstrip())
    ordering = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Compare)
        and any(
            isinstance(operator, ast.Lt | ast.LtE | ast.Gt | ast.GtE | ast.Eq | ast.NotEq)
            for operator in node.ops
        )
    ]
    assert ordering == []


def test_no_handler_imports_a_date_or_a_calendar() -> None:
    """Neither the clock nor the calendar is reasoned about at this layer.

    `self._clock()` is passed to the read service, which resolves the Project's
    own calendar; a handler that constructed a `date` would be resolving one of
    its own.
    """
    for capability in ALL_READS:
        body = _handler_source(capability)
        assert "date(" not in body
        assert "datetime(" not in body
        assert str(UTC) not in body or "self._clock()" in body
    assert date is not None and datetime is not None


# ---- the three cross-Project reads (PC-CM-RUN01-WP06) -----------------------
#
# Held apart from the six above rather than folded into `EXPECTED`, and the
# separation is the claim rather than a convenience. The exact-Project six are
# driven end to end against `tests/conftest`'s shared `_ConstraintReads` fake,
# which carries WP03's eleven read methods and none of WP06's five set-based
# ones; a portfolio read reaching it would raise rather than answer. So the
# three are exercised against the spy for delegation and against a local
# portfolio repository for behaviour, exactly as `test_constraint_portfolio_
# reads.py` exercises the read service itself.
#
# The Project set is the other reason. These three name no Project at all, so
# `_command_for` above has nothing to build them from and the scene's seeded
# Constraint Project is not what they read: they read whatever the canonical
# `ProjectRepository` says this Principal owns, which is the seam the fixtures
# below stand in for.


@dataclass(frozen=True)
class _PortfolioPage:
    """What the two paging portfolio handlers read off the read service's answer.

    The Register page, plus the count of owned Projects that could not
    contribute — the shape `ConstraintPortfolioPage` publishes. A handler that
    stopped reading the count would still pass every delegation assertion, so
    the disclosure tests below read it off the envelope rather than off this.
    """

    page: _Page = field(default_factory=_Page)
    omitted_projects: int = 0


@dataclass(frozen=True)
class _PortfolioOverview:
    """The overview's answer, reduced to the one field the handler reads."""

    omitted_projects: int = 0


_ANSWERS["list_portfolio_constraints"] = _PortfolioPage()
_ANSWERS["read_portfolio_overview"] = _PortfolioOverview()


def _portfolio_command(capability: Capability) -> object:
    if capability is Capability.CONSTRAINTS_PORTFOLIO_LIST:
        return ListPortfolioConstraints()
    if capability is Capability.CONSTRAINTS_PORTFOLIO_SEARCH:
        return SearchPortfolioConstraints(query="synthetic")
    return ReadPortfolioConstraintOverview()


class _OwnedProjects:
    """The canonical Project seam, holding exactly the Projects it was handed.

    Only `list_projects` is implemented, and that is the assertion rather than a
    shortcut: a portfolio handler that reached `get_project` — one call per
    Project — would raise here rather than pass, which is the per-Project
    degradation this package exists to prevent.
    """

    def __init__(self, project_ids: tuple[str, ...]) -> None:
        self.project_ids = project_ids
        self.calls: list[int | None] = []

    def list_projects(
        self,
        principal_id: str,
        **keywords: Any,  # noqa: ANN401 - the port's own signature
    ) -> tuple[Any, ...]:
        del principal_id
        self.calls.append(keywords.get("limit"))
        limit = keywords.get("limit")
        found = tuple(SimpleNamespace(project_id=identifier) for identifier in self.project_ids)
        return found if limit is None else found[:limit]


class _PortfolioWork:
    """A Constraint unit of work whose Project seam is `_OwnedProjects`."""

    def __init__(self, projects: _OwnedProjects, constraints: object) -> None:
        self.projects = projects
        self.constraints = constraints

    def __enter__(self) -> _PortfolioWork:
        return self

    def __exit__(self, *_exception: object) -> None:
        return None


def _portfolio_service(
    scene: Scene, owned: _OwnedProjects, recorder: _Recorder | None = None
) -> ApplicationService:
    scene.world.providers = scene.providers
    service = ApplicationService(
        unit_of_work=lambda: FakeUnitOfWork(scene.world),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        constraint_management_unit_of_work=lambda: _PortfolioWork(owned, object()),  # type: ignore[arg-type]
    )
    service._constraint_reads = recorder if recorder is not None else _Recorder()  # type: ignore[assignment]
    return service


def _synthetic_projects(count: int) -> tuple[str, ...]:
    return tuple(issue_identifier(IdKind.PROJECT) for _ in range(count))


# ---- dispatch ---------------------------------------------------------------


@pytest.mark.parametrize("capability", sorted(PORTFOLIO_EXPECTED, key=lambda c: c.value))
def test_every_portfolio_read_capability_has_a_handler(capability: Capability) -> None:
    assert capability in _HANDLERS


@pytest.mark.parametrize("capability", sorted(PORTFOLIO_EXPECTED, key=lambda c: c.value))
def test_every_portfolio_read_command_declares_its_own_capability(
    capability: Capability,
) -> None:
    command, _method = PORTFOLIO_EXPECTED[capability]
    assert command.capability is capability  # type: ignore[attr-defined]


@pytest.mark.parametrize("capability", sorted(PORTFOLIO_EXPECTED, key=lambda c: c.value))
def test_every_portfolio_read_command_is_in_the_command_union(capability: Capability) -> None:
    """Union membership is what publishes the MCP tool, for the reason above."""
    command, _method = PORTFOLIO_EXPECTED[capability]
    assert command in get_args(Command.__value__)


@pytest.mark.parametrize("capability", sorted(PORTFOLIO_EXPECTED, key=lambda c: c.value))
def test_every_portfolio_read_has_a_normalization_builder(capability: Capability) -> None:
    """A capability with no builder normalises to nothing and is refused at the wire.

    The builder table is what turns a JSON payload into the command the handler
    takes, so a capability wired into `_HANDLERS` and left out of `_BUILDERS`
    dispatches over no transport at all.
    """
    command, _method = PORTFOLIO_EXPECTED[capability]
    assert capability in _BUILDERS
    assert isinstance(
        _BUILDERS[capability]({})
        if command is not SearchPortfolioConstraints
        else _BUILDERS[capability]({"query": "synthetic"}),
        command,
    )


def test_the_portfolio_builders_convert_the_closed_vocabularies() -> None:
    """The wire's strings become enum members, exactly as the exact-Project pair do.

    Asserted on the built command rather than on the builder, because what
    matters is that the frozen dataclass accepted it: a builder that passed the
    raw string through would be refused by `__post_init__`, and a builder that
    converted the wrong field would build a command whose vocabulary is
    advisory.
    """
    built = _BUILDERS[Capability.CONSTRAINTS_PORTFOLIO_LIST](
        {
            "scope": "all",
            "sort": "due_date",
            "sort_order": "desc",
            "grouping": "none",
            "statuses": ["in_progress"],
        }
    )
    assert isinstance(built, ListPortfolioConstraints)
    assert built.scope is ConstraintListScope.ALL
    assert built.sort is ConstraintSort.DUE_DATE
    assert built.sort_order is SortDirection.DESC
    assert built.grouping is ConstraintGrouping.NONE
    assert built.statuses == (ConstraintLifecycleState.IN_PROGRESS,)


# ---- delegation and the Project seam ----------------------------------------


@pytest.mark.parametrize("capability", sorted(PORTFOLIO_EXPECTED, key=lambda c: c.value))
def test_each_portfolio_handler_makes_exactly_one_canonical_read_call(
    capability: Capability, scene: Scene
) -> None:
    recorder = _Recorder()
    owned = _OwnedProjects(_synthetic_projects(3))
    envelope = _run(
        _portfolio_service(scene, owned, recorder), scene, _portfolio_command(capability)
    )
    assert envelope.error is None, envelope.error
    _command, method = PORTFOLIO_EXPECTED[capability]
    assert [name for name, _keywords in recorder.calls] == [method]


@pytest.mark.parametrize("capability", sorted(PORTFOLIO_EXPECTED, key=lambda c: c.value))
def test_each_portfolio_handler_enumerates_projects_in_exactly_one_bounded_statement(
    capability: Capability, scene: Scene
) -> None:
    """The defining bound of this package, measured rather than asserted in prose.

    One call to `list_projects` per request, whatever the Register does
    afterwards, and that call states a limit. A handler that asked the Project
    seam once per Project would show as many calls here, and a handler that
    asked for every Project the Principal owns would show `None`.
    """
    owned = _OwnedProjects(_synthetic_projects(4))
    _run(_portfolio_service(scene, owned), scene, _portfolio_command(capability))
    assert owned.calls == [MAX_PORTFOLIO_PROJECTS + 1]


@pytest.mark.parametrize("capability", sorted(PORTFOLIO_EXPECTED, key=lambda c: c.value))
def test_each_portfolio_handler_passes_the_owned_set_and_never_a_payload_field(
    capability: Capability, scene: Scene
) -> None:
    """The Project set reaches the read service from the repository, not the request.

    Both halves again: the command carries no Project field of any spelling, and
    what the handler passed is exactly what the canonical repository returned.
    A caller-supplied Project set would make this surface an existence oracle,
    so the absence of the field is asserted by name.
    """
    recorder = _Recorder()
    project_ids = _synthetic_projects(3)
    owned = _OwnedProjects(project_ids)
    command = _portfolio_command(capability)
    slots = vars(type(command)).get("__slots__", ())
    assert not [field for field in slots if "project" in field or "principal" in field]
    _run(_portfolio_service(scene, owned, recorder), scene, command)
    (_name, keywords) = recorder.calls[0]
    assert keywords["principal_id"] == scene.principal.principal_id
    assert set(keywords["project_ids"]) == set(project_ids)


# ---- the Project-set bound and its disclosure -------------------------------


@pytest.mark.parametrize("capability", sorted(PORTFOLIO_EXPECTED, key=lambda c: c.value))
def test_a_portfolio_within_the_cap_discloses_no_truncation(
    capability: Capability, scene: Scene
) -> None:
    owned = _OwnedProjects(_synthetic_projects(MAX_PORTFOLIO_PROJECTS))
    envelope = _run(_portfolio_service(scene, owned), scene, _portfolio_command(capability))
    assert envelope.result is not None
    assert envelope.disclosure is not None
    truncation = envelope.disclosure.truncation
    assert truncation is None or truncation.is_truncated is False


@pytest.mark.parametrize("capability", sorted(PORTFOLIO_EXPECTED, key=lambda c: c.value))
def test_a_portfolio_beyond_the_cap_says_so_rather_than_answering_for_a_subset(
    capability: Capability, scene: Scene
) -> None:
    """A silently-truncated portfolio presented as the portfolio is a false answer.

    The cap is real and a Principal can exceed it, so the only honest outcomes
    are to refuse or to disclose. This surface discloses: the reason names the
    Project bound rather than the page bound, and — because this arrangement's
    page also fits, so no cursor is issued — the limitation says the truncation
    cannot be paged past. The both-bounds arrangement, where a cursor *is*
    issued, is a different answer and is measured against real rows below.
    """
    owned = _OwnedProjects(_synthetic_projects(MAX_PORTFOLIO_PROJECTS + 1))
    envelope = _run(_portfolio_service(scene, owned), scene, _portfolio_command(capability))
    assert envelope.result is not None
    assert envelope.disclosure is not None
    truncation = envelope.disclosure.truncation
    assert truncation is not None and truncation.is_truncated is True
    assert truncation.reason == "portfolio_project_limit_reached"
    assert truncation.next_cursor is None
    assert Limitation.LISTING_HAS_NO_CONTINUATION.value in envelope.disclosure.limitations


@pytest.mark.parametrize("capability", sorted(PORTFOLIO_EXPECTED, key=lambda c: c.value))
def test_the_project_bound_never_states_a_count_of_projects(
    capability: Capability, scene: Scene
) -> None:
    """The disclosure says *that* the cap was reached, never how many were owned.

    A portfolio surface is an easy place to leak existence, and a truncation
    field carrying "112 of your Projects" would be a count this Principal did
    not ask for and a shape a probe could read. The reason is a constant string
    and the limitation is a closed enum member; neither varies with the data.
    """
    owned = _OwnedProjects(_synthetic_projects(MAX_PORTFOLIO_PROJECTS + 7))
    envelope = _run(_portfolio_service(scene, owned), scene, _portfolio_command(capability))
    assert envelope.result is not None
    rendered = json.dumps(envelope.model_dump(mode="json", exclude={"correlation_id"}))
    assert str(MAX_PORTFOLIO_PROJECTS + 7) not in rendered
    for project_id in owned.project_ids:
        assert project_id not in rendered


# ---- both bounds at once, over real rows ------------------------------------
#
# The arrangements below deliberately use no spy. `_Recorder` answers every
# paging read with a page that neither truncates nor issues a cursor, so it
# cannot express the one combination this section exists for: a Principal over
# the Project cap *and* a page that filled. What the handler composes there is a
# property of the backend, so the real `ConstraintReadService` runs over stored
# rows and the cursor in the answer is one it actually issued.


def _capped_world(scene: Scene, *, rows: int) -> tuple[str, ...]:
    """`MAX_PORTFOLIO_PROJECTS + 1` owned Projects, `rows` of them in the first.

    Settings are seeded only for the Projects inside the cap, which is the shape
    the read is given: a Project the enumeration never reached contributes no
    calendar and no rows either way.
    """
    project_ids = _synthetic_projects(MAX_PORTFOLIO_PROJECTS + 1)
    for project_id in project_ids[:MAX_PORTFOLIO_PROJECTS]:
        scene.world.constraint_settings[(scene.principal.principal_id, project_id)] = (
            ConstraintProjectSettings(
                principal_id=scene.principal.principal_id,
                project_id=project_id,
                timezone_name="UTC",
                version=1,
                created_at=WHEN,
                updated_at=WHEN,
            )
        )
    for ordinal in range(rows):
        constraint_id = issue_identifier(IdKind.PROJECT_CONSTRAINT)
        scene.world.project_constraints[(scene.principal.principal_id, constraint_id)] = (
            PersistedConstraintRecord(
                constraint_id=constraint_id,
                principal_id=scene.principal.principal_id,
                lifecycle_state=ConstraintLifecycleState.IDENTIFIED,
                record_quality=ConstraintRecordQuality.NORMAL,
                origin=ConstraintOrigin.PRODUCT,
                version=1,
                created_at=WHEN,
                updated_at=WHEN,
                project_id=project_ids[0],
                constraint_code=f"CAP-{ordinal:03d}",
                description="A synthetic Project control.",
                date_identified=WHEN.date(),
                due_date=WHEN.date(),
                published_at=WHEN,
            )
        )
    return project_ids


def _backed_portfolio_service(scene: Scene, project_ids: tuple[str, ...]) -> ApplicationService:
    """`_portfolio_service` with the real read service instead of the spy."""
    scene.world.providers = scene.providers
    return ApplicationService(
        unit_of_work=lambda: FakeUnitOfWork(scene.world),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        constraint_management_unit_of_work=lambda: _PortfolioWork(  # type: ignore[arg-type]
            _OwnedProjects(project_ids),
            FakeConstraintManagementUnitOfWork(scene.world).constraints,
        ),
    )


@pytest.mark.parametrize(
    "capability",
    [Capability.CONSTRAINTS_PORTFOLIO_LIST, Capability.CONSTRAINTS_PORTFOLIO_SEARCH],
)
def test_a_page_that_fills_beyond_the_project_cap_keeps_its_cursor_and_drops_the_limitation(
    capability: Capability, scene: Scene
) -> None:
    """The combination the two bounds make, and the contradiction it used to be.

    More owned Projects than the cap **and** a page that filled. The answer used
    to carry `listing_has_no_continuation_cursor` beside a real, usable cursor —
    a response that contradicted itself, because that member is documented as
    "a listing stopped at the page size and this build issues no cursor" and
    every other emission site in the repository pairs it with a truncation
    carrying none. A client that honoured it would stop paging here and silently
    lose rows inside the Projects that *were* read.

    The cursor is kept, because it reaches rows the caller is entitled to, and
    the limitation is dropped, because with a cursor present it is simply false.
    Nothing about the Project cap is lost: the reason still names it.
    """
    project_ids = _capped_world(scene, rows=4)
    command = (
        ListPortfolioConstraints(limit=2)
        if capability is Capability.CONSTRAINTS_PORTFOLIO_LIST
        else SearchPortfolioConstraints(query="synthetic", limit=2)
    )
    envelope = _run(_backed_portfolio_service(scene, project_ids), scene, command)
    assert envelope.error is None, envelope.error
    assert envelope.disclosure is not None
    truncation = envelope.disclosure.truncation
    assert truncation is not None and truncation.is_truncated is True
    assert truncation.reason == "portfolio_project_limit_reached"
    assert truncation.next_cursor is not None
    assert Limitation.LISTING_HAS_NO_CONTINUATION.value not in envelope.disclosure.limitations


def test_the_cursor_issued_beyond_the_project_cap_is_one_the_read_service_will_take_back(
    scene: Scene,
) -> None:
    """The kept cursor is usable, which is why keeping it is the honest answer.

    A cursor that could not be replayed would be as misleading as the limitation
    was. This one is bound to the *capped* Project set the handler actually read
    — not to the Principal's whole owned set — and the same capability accepts it
    back rather than refusing it as a foreign scope. That the rows it continues
    from are the right ones is a property of real SQL and is proved in
    `tests/database/test_constraint_portfolio_reads.py`.
    """
    project_ids = _capped_world(scene, rows=5)
    service = _backed_portfolio_service(scene, project_ids)
    first = _run(service, scene, ListPortfolioConstraints(limit=2))
    assert first.disclosure is not None and first.disclosure.truncation is not None
    cursor = first.disclosure.truncation.next_cursor
    assert cursor is not None
    decoded = ConstraintListCursor.decode(cursor)
    assert decoded.binding == ConstraintListQuery(limit=2).portfolio_binding(
        principal_id=scene.principal.principal_id,
        project_ids=tuple(sorted(project_ids[:MAX_PORTFOLIO_PROJECTS])),
    )
    replayed = _run(service, scene, ListPortfolioConstraints(limit=2, cursor=cursor))
    assert replayed.error is None, replayed.error


def test_the_last_page_of_a_capped_portfolio_still_says_the_cap_was_reached(
    scene: Scene,
) -> None:
    """The fact the limitation used to carry survives without it, on every page.

    This is what makes dropping the limitation safe rather than a second way of
    misleading a caller. The Project cap drives `is_truncated` on its own, so a
    capped listing stays truncated after the rows run out — and on that last
    page there is no cursor, so `listing_has_no_continuation_cursor` is true
    again and is emitted again. A caller that pages to exhaustion is never told
    it has seen the whole portfolio.
    """
    project_ids = _capped_world(scene, rows=2)
    envelope = _run(
        _backed_portfolio_service(scene, project_ids), scene, ListPortfolioConstraints(limit=50)
    )
    assert envelope.error is None, envelope.error
    assert envelope.disclosure is not None
    truncation = envelope.disclosure.truncation
    assert truncation is not None and truncation.is_truncated is True
    assert truncation.reason == "portfolio_project_limit_reached"
    assert truncation.next_cursor is None
    assert Limitation.LISTING_HAS_NO_CONTINUATION.value in envelope.disclosure.limitations
    assert envelope.disclosure.partial_result is True


def test_a_page_that_fills_inside_the_cap_is_an_ordinary_page_size_truncation(
    scene: Scene,
) -> None:
    """The control: the same filled page under the cap names the page bound."""
    project_ids = _capped_world(scene, rows=4)[:MAX_PORTFOLIO_PROJECTS]
    envelope = _run(
        _backed_portfolio_service(scene, project_ids), scene, ListPortfolioConstraints(limit=2)
    )
    assert envelope.error is None, envelope.error
    assert envelope.disclosure is not None
    truncation = envelope.disclosure.truncation
    assert truncation is not None and truncation.is_truncated is True
    assert truncation.reason == "page_size_reached"
    assert truncation.next_cursor is not None
    assert Limitation.LISTING_HAS_NO_CONTINUATION.value not in envelope.disclosure.limitations


# ---- the Project that cannot contribute, and the precedence of three bounds --
#
# The operator's ruling (PC-CM-RUN01-WP06, third corrective cycle): an owned
# Project that cannot contribute — no settings row, or a stored zone that will
# not load — is omitted, not fatal, and **disclosed**, by a count and never by
# an identity. Three partialities can now hold at once, so what is pinned below
# is the precedence over the single `reason` slot *and* the fact that filling
# that slot masks nothing: each partiality has its own channel.


def _omitting_world(
    scene: Scene,
    *,
    owned: int,
    configured: int,
    broken: int = 0,
    rows: int = 0,
) -> tuple[str, ...]:
    """`owned` Projects, of which `configured` have a calendar and `broken` a bad one.

    The remainder have no settings row at all. Both of those are the "cannot
    contribute" class; the rows all sit in the first configured Project.
    """

    def _settings(project_id: str, zone: str) -> ConstraintProjectSettings:
        return ConstraintProjectSettings(
            principal_id=scene.principal.principal_id,
            project_id=project_id,
            timezone_name=zone,
            version=1,
            created_at=WHEN,
            updated_at=WHEN,
        )

    project_ids = _synthetic_projects(owned)
    for project_id in project_ids[:configured]:
        scene.world.constraint_settings[(scene.principal.principal_id, project_id)] = _settings(
            project_id, "UTC"
        )
    for project_id in project_ids[configured : configured + broken]:
        scene.world.constraint_settings[(scene.principal.principal_id, project_id)] = _settings(
            project_id, "Mars/Olympus_Mons"
        )
    for ordinal in range(rows):
        constraint_id = issue_identifier(IdKind.PROJECT_CONSTRAINT)
        scene.world.project_constraints[(scene.principal.principal_id, constraint_id)] = (
            PersistedConstraintRecord(
                constraint_id=constraint_id,
                principal_id=scene.principal.principal_id,
                lifecycle_state=ConstraintLifecycleState.IDENTIFIED,
                record_quality=ConstraintRecordQuality.NORMAL,
                origin=ConstraintOrigin.PRODUCT,
                version=1,
                created_at=WHEN,
                updated_at=WHEN,
                project_id=project_ids[0],
                constraint_code=f"OMT-{ordinal:03d}",
                description="A synthetic Project control.",
                date_identified=WHEN.date(),
                due_date=WHEN.date(),
                published_at=WHEN,
            )
        )
    return project_ids


def _result(envelope: ResponseEnvelope) -> dict[str, Any]:
    assert envelope.error is None, envelope.error
    assert envelope.result is not None
    return json.loads(json.dumps(envelope.model_dump(mode="json")))["result"]


@pytest.mark.parametrize(
    "capability",
    [Capability.CONSTRAINTS_PORTFOLIO_LIST, Capability.CONSTRAINTS_PORTFOLIO_SEARCH],
)
def test_an_owned_project_that_cannot_contribute_is_omitted_and_disclosed(
    capability: Capability, scene: Scene
) -> None:
    """Omitted rather than fatal, and stated rather than silent.

    Three owned Projects: one with a calendar, one never enrolled, one enrolled
    against a zone that will not load. The old build answered this three
    different ways — the unconfigured one vanished undisclosed, the broken one
    failed the entire read with an anonymous refusal that took the healthy
    Project down with it. Now both are the same class, both are omitted, and the
    answer says how many.
    """
    project_ids = _omitting_world(scene, owned=3, configured=1, broken=1, rows=1)
    command = (
        ListPortfolioConstraints()
        if capability is Capability.CONSTRAINTS_PORTFOLIO_LIST
        else SearchPortfolioConstraints(query="synthetic")
    )
    envelope = _run(_backed_portfolio_service(scene, project_ids), scene, command)
    assert envelope.error is None, envelope.error
    assert envelope.disclosure is not None
    truncation = envelope.disclosure.truncation
    assert truncation is not None and truncation.is_truncated is True
    assert truncation.reason == "portfolio_projects_omitted"
    assert truncation.next_cursor is None
    assert Limitation.LISTING_HAS_NO_CONTINUATION.value in envelope.disclosure.limitations
    assert _result(envelope)["omitted_projects"] == 2


def test_an_overview_omitting_a_project_discloses_it_the_same_way(scene: Scene) -> None:
    """The overview has no paging, but it has the same two omission members."""
    project_ids = _omitting_world(scene, owned=3, configured=1, broken=1)
    envelope = _run(
        _backed_portfolio_service(scene, project_ids), scene, ReadPortfolioConstraintOverview()
    )
    assert envelope.error is None, envelope.error
    assert envelope.disclosure is not None
    truncation = envelope.disclosure.truncation
    assert truncation is not None and truncation.is_truncated is True
    assert truncation.reason == "portfolio_projects_omitted"
    assert truncation.next_cursor is None
    assert Limitation.LISTING_HAS_NO_CONTINUATION.value in envelope.disclosure.limitations
    assert _result(envelope)["overview"]["omitted_projects"] == 2


@pytest.mark.parametrize(
    "capability",
    [Capability.CONSTRAINTS_PORTFOLIO_LIST, Capability.CONSTRAINTS_PORTFOLIO_SEARCH],
)
def test_a_portfolio_that_omits_nothing_says_zero_rather_than_saying_nothing(
    capability: Capability, scene: Scene
) -> None:
    """The control, and the reason the count is not optional.

    A field present only when it is non-zero would make "complete" and "this
    build does not publish the field" the same document. It is always published,
    and an untruncated answer publishes it as zero.
    """
    project_ids = _omitting_world(scene, owned=2, configured=2, rows=1)
    command = (
        ListPortfolioConstraints()
        if capability is Capability.CONSTRAINTS_PORTFOLIO_LIST
        else SearchPortfolioConstraints(query="synthetic")
    )
    envelope = _run(_backed_portfolio_service(scene, project_ids), scene, command)
    assert envelope.error is None, envelope.error
    assert envelope.disclosure is not None
    truncation = envelope.disclosure.truncation
    assert truncation is None or truncation.is_truncated is False
    assert _result(envelope)["omitted_projects"] == 0


def test_an_omission_and_a_filled_page_are_both_reachable_from_one_answer(
    scene: Scene,
) -> None:
    """Two partialities, one `reason` slot, and nothing masked.

    The omission takes the slot, because a filled page has its own channel: the
    cursor. A caller reads "some of your Projects could not be included" off
    `reason` and the count, and "there are more rows" off `next_cursor`, from the
    same answer. `LISTING_HAS_NO_CONTINUATION` is absent because a continuation
    was genuinely issued — the invariant the previous cycle established, which a
    new `reason` must not disturb.
    """
    project_ids = _omitting_world(scene, owned=3, configured=1, broken=1, rows=4)
    envelope = _run(
        _backed_portfolio_service(scene, project_ids), scene, ListPortfolioConstraints(limit=2)
    )
    assert envelope.error is None, envelope.error
    assert envelope.disclosure is not None
    truncation = envelope.disclosure.truncation
    assert truncation is not None and truncation.is_truncated is True
    assert truncation.reason == "portfolio_projects_omitted"
    assert truncation.next_cursor is not None
    assert Limitation.LISTING_HAS_NO_CONTINUATION.value not in envelope.disclosure.limitations
    assert _result(envelope)["omitted_projects"] == 2


def test_the_project_cap_outranks_an_omission_and_the_omission_is_still_readable(
    scene: Scene,
) -> None:
    """The precedence, at the one arrangement where it decides something.

    Cap and omission both hold. The cap takes `reason`, because `reason` is the
    *only* channel the cap has — so `portfolio_project_limit_reached` means the
    cap was reached, always. The omission loses the slot and loses nothing: its
    count is published either way. A build that ordered these the other way
    would make "the cap was reached" unsayable whenever anything was omitted.
    """
    project_ids = _omitting_world(
        scene,
        owned=MAX_PORTFOLIO_PROJECTS + 1,
        configured=MAX_PORTFOLIO_PROJECTS - 2,
        broken=1,
        rows=1,
    )
    envelope = _run(
        _backed_portfolio_service(scene, project_ids), scene, ListPortfolioConstraints()
    )
    assert envelope.error is None, envelope.error
    assert envelope.disclosure is not None
    truncation = envelope.disclosure.truncation
    assert truncation is not None and truncation.is_truncated is True
    assert truncation.reason == "portfolio_project_limit_reached"
    # The omission is not masked: it has its own channel and still says two —
    # the unenrolled Project inside the cap and the one with the broken zone.
    # The Project beyond the cap is the cap's business and is not counted here.
    assert _result(envelope)["omitted_projects"] == 2


def test_all_three_partialities_at_once_are_each_reachable(scene: Scene) -> None:
    """Cap, omission and a filled page together. Each has a channel; none is lost."""
    project_ids = _omitting_world(
        scene,
        owned=MAX_PORTFOLIO_PROJECTS + 1,
        configured=MAX_PORTFOLIO_PROJECTS - 2,
        broken=1,
        rows=4,
    )
    envelope = _run(
        _backed_portfolio_service(scene, project_ids), scene, ListPortfolioConstraints(limit=2)
    )
    assert envelope.error is None, envelope.error
    assert envelope.disclosure is not None
    truncation = envelope.disclosure.truncation
    assert truncation is not None and truncation.is_truncated is True
    assert truncation.reason == "portfolio_project_limit_reached"  # the cap
    assert truncation.next_cursor is not None  # the filled page
    assert _result(envelope)["omitted_projects"] == 2  # the omission
    assert Limitation.LISTING_HAS_NO_CONTINUATION.value not in envelope.disclosure.limitations


def test_the_omission_disclosure_names_no_project_and_carries_no_zone(
    scene: Scene,
) -> None:
    """The §14 proof: a count, and nothing an identity could be read out of.

    Neither the omitted Projects' identifiers nor the stored zone that failed to
    load appears anywhere in the rendered envelope, and the count is the only
    number that moved. The Projects that *did* contribute are named, which is
    what makes the absence of the others meaningful rather than vacuous.
    """
    project_ids = _omitting_world(scene, owned=4, configured=1, broken=2, rows=1)
    envelope = _run(
        _backed_portfolio_service(scene, project_ids), scene, ListPortfolioConstraints()
    )
    assert envelope.error is None, envelope.error
    rendered = json.dumps(envelope.model_dump(mode="json"))
    assert project_ids[0] in rendered
    for project_id in project_ids[1:]:
        assert project_id not in rendered
    assert "Mars/Olympus_Mons" not in rendered
    assert _result(envelope)["omitted_projects"] == 3


def test_a_portfolio_whose_projects_all_fail_is_empty_and_disclosed_not_refused(
    scene: Scene,
) -> None:
    """The whole-surface case the ruling exists for.

    Every owned Project cannot contribute. The old build's unloadable zone made
    this an anonymous 503; the old build's missing settings row made it an
    unqualified empty page. It is now one answer: empty, truncated, and counted.
    """
    project_ids = _omitting_world(scene, owned=3, configured=0, broken=2)
    envelope = _run(
        _backed_portfolio_service(scene, project_ids), scene, ListPortfolioConstraints()
    )
    assert envelope.error is None, envelope.error
    assert envelope.disclosure is not None
    truncation = envelope.disclosure.truncation
    assert truncation is not None and truncation.is_truncated is True
    assert truncation.reason == "portfolio_projects_omitted"
    assert _result(envelope)["constraints"] == []
    assert _result(envelope)["omitted_projects"] == 3


def test_a_principal_owning_no_projects_gets_an_empty_portfolio_not_a_refusal(
    scene: Scene,
) -> None:
    """Nothing owned is an empty answer, because the alternative discloses something.

    A refusal here would tell a caller that the emptiness was special, and an
    error shape that differed from the populated one would be a branch a probe
    could time. The answer is the same envelope with nothing in it.
    """
    owned = _OwnedProjects(())
    envelope = _run(_portfolio_service(scene, owned), scene, ListPortfolioConstraints())
    assert envelope.error is None, envelope.error
    assert envelope.disclosure is not None
    truncation = envelope.disclosure.truncation
    assert truncation is None or truncation.is_truncated is False


# ---- the cursor binding across a changed owned set --------------------------


def test_a_cursor_issued_over_one_owned_set_fails_closed_over_another() -> None:
    """The portfolio cursor binds the Project set, so a changed portfolio refuses.

    Asserted at the binding rather than through a page, because the binding is
    what the read service compares: a cursor carries the digest it was issued
    under, and `list_portfolio_constraints` decodes against the digest of the
    set it was *just* handed. Two different owned sets therefore produce two
    different bindings, and a cursor from the first cannot validate against the
    second — which is what makes a portfolio that gained or lost a Project
    between pages a refusal rather than a silently different portfolio.
    """
    query = ConstraintListQuery()
    principal_id = issue_identifier(IdKind.PRINCIPAL)
    first = _synthetic_projects(3)
    binding = query.portfolio_binding(principal_id=principal_id, project_ids=first)
    assert binding == query.portfolio_binding(principal_id=principal_id, project_ids=first)
    assert binding != query.portfolio_binding(
        principal_id=principal_id, project_ids=(*first, issue_identifier(IdKind.PROJECT))
    )
    assert binding != query.portfolio_binding(principal_id=principal_id, project_ids=first[:2])
    # And the set is the *only* thing that changed: a different Principal over
    # the same Projects is also a different binding, so neither half is carrying
    # the other.
    assert binding != query.portfolio_binding(
        principal_id=issue_identifier(IdKind.PRINCIPAL), project_ids=first
    )


# ---- malformed portfolio requests -------------------------------------------


def test_a_portfolio_command_refuses_a_caller_supplied_project() -> None:
    """The one refusal this surface exists for, stated for all three commands.

    `project_id` is not a field these commands have, so it arrives as an
    unexpected keyword and the frozen dataclass refuses it. That is the same
    refusal any other unknown key gets, and it is deliberate: a caller must not
    be able to tell "that is not a field here" from "that Project is not yours".
    """
    for command in (
        ListPortfolioConstraints,
        SearchPortfolioConstraints,
        ReadPortfolioConstraintOverview,
    ):
        with pytest.raises(TypeError):
            command(project_id=issue_identifier(IdKind.PROJECT))  # type: ignore[call-arg]


def test_a_portfolio_command_refuses_a_caller_supplied_project_set() -> None:
    """A collection of Projects is refused for the same reason a single one is.

    Naming a set rather than one identifier would be the existence oracle in its
    most direct form: a caller could vary the set and read which identifiers
    changed the answer.
    """
    with pytest.raises(TypeError):
        ListPortfolioConstraints(project_ids=_synthetic_projects(2))  # type: ignore[call-arg]


def test_a_portfolio_command_refuses_an_unknown_field() -> None:
    with pytest.raises(TypeError):
        ListPortfolioConstraints(unknown_selector="anything")  # type: ignore[call-arg]


@pytest.mark.parametrize("limit", [0, -1, MAX_LIST_LIMIT + 1, True])
def test_a_portfolio_page_limit_outside_the_domains_bound_is_an_invalid_request(
    limit: object,
) -> None:
    with pytest.raises(InvalidRequestError) as listing:
        ListPortfolioConstraints(limit=limit)  # type: ignore[arg-type]
    assert listing.value.safe_details == (SafeDetail.LIMIT,)
    with pytest.raises(InvalidRequestError) as searching:
        SearchPortfolioConstraints(query="synthetic", limit=limit)  # type: ignore[arg-type]
    assert searching.value.safe_details == (SafeDetail.LIMIT,)


def test_an_oversized_portfolio_cursor_is_refused_before_it_is_decoded() -> None:
    with pytest.raises(InvalidRequestError) as refusal:
        ListPortfolioConstraints(cursor="x" * (MAX_CURSOR_CHARACTERS + 1))
    assert refusal.value.safe_details == (SafeDetail.CURSOR,)


def test_an_oversized_portfolio_search_term_is_refused() -> None:
    with pytest.raises(InvalidRequestError) as refusal:
        SearchPortfolioConstraints(query="x" * (MAX_SEARCH_CHARACTERS + 1))
    assert refusal.value.safe_details == (SafeDetail.QUERY,)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scope", "open"),
        ("sort", "code"),
        ("sort_order", "asc"),
        ("grouping", "category"),
    ],
)
def test_a_portfolio_vocabulary_field_refuses_a_bare_string(field: str, value: str) -> None:
    with pytest.raises(InvalidRequestError):
        ListPortfolioConstraints(**{field: value})


def test_a_portfolio_filter_family_refuses_a_member_of_another_vocabulary() -> None:
    with pytest.raises(InvalidRequestError):
        ListPortfolioConstraints(statuses=(ConstraintListScope.OPEN,))  # type: ignore[arg-type]


def test_the_well_formed_portfolio_shapes_are_accepted() -> None:
    """The green half, so the refusals above are not the only thing measured."""
    ListPortfolioConstraints(
        scope=ConstraintListScope.ALL,
        sort=ConstraintSort.DUE_DATE,
        sort_order=SortDirection.DESC,
        grouping=ConstraintGrouping.NONE,
        limit=MAX_LIST_LIMIT,
    )
    SearchPortfolioConstraints(query="a bounded term")
    ReadPortfolioConstraintOverview()


def test_the_overview_command_carries_no_field_at_all() -> None:
    """A zero-field command is well formed here, and `GetCapabilities` is the precedent.

    It matters at the wire: `adapters.mcp.tools.input_schema_for` makes
    `payload` required only when the command has a required field, so this tool
    publishes a payload a caller may omit entirely. A field added here later
    would silently change that.
    """
    assert list(vars(ReadPortfolioConstraintOverview).get("__slots__", ())) == []
    assert ReadPortfolioConstraintOverview() == ReadPortfolioConstraintOverview()


def test_the_overview_tool_accepts_an_absent_payload_and_an_empty_one(scene: Scene) -> None:
    """A command with no field must round-trip with no `payload` key at all.

    Asserted in both wire spellings, because they are different documents and a
    browser will send whichever its client library produces. `payload` is
    *absent* in the first and an *empty object* in the second, and
    `input_schema_for` publishes the tool with `payload` outside its top-level
    `required` list — so a caller that omits it is sending a valid request
    rather than one this build happens to tolerate. A field added to this
    command later would move `payload` into `required` and silently break the
    first form.
    """
    capability = Capability.CONSTRAINTS_PORTFOLIO_OVERVIEW
    with_payload = {
        "request_id": "req-portfolio-overview",
        "purpose": Purpose.CONSTRAINT_READ.value,
        "principal_id": scene.principal.principal_id,
        "requested_at": "2026-08-02T12:00:00Z",
        PAYLOAD_KEY: {},
    }
    without_payload = {name: value for name, value in with_payload.items() if name != PAYLOAD_KEY}
    for document in (without_payload, with_payload):
        _metadata, command = normalize(capability.value, document)
        assert command == ReadPortfolioConstraintOverview()

    schema = input_schema_for(ReadPortfolioConstraintOverview)
    assert PAYLOAD_KEY not in schema["required"]
    assert schema["properties"][PAYLOAD_KEY]["required"] == []
    assert schema["properties"][PAYLOAD_KEY]["additionalProperties"] is False


@pytest.mark.parametrize("capability", sorted(PORTFOLIO_EXPECTED, key=lambda c: c.value))
def test_every_portfolio_tool_is_published_and_marked_read_only(capability: Capability) -> None:
    """The MCP tool follows from the union, and its hint follows from the command.

    `read_only_hint` is derived rather than declared, so this asserts the
    derivation landed the right way round: all three are reads, and a portfolio
    surface advertised as a mutation would be a false statement to any client
    that gates on the hint.
    """
    published = {tool.name: tool for tool in TOOLS}
    assert capability.value in published
    assert published[capability.value].annotations.read_only_hint is True
