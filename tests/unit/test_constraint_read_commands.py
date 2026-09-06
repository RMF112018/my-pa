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
import re
from datetime import UTC, date, datetime
from typing import Any, Final, get_args

import pytest

from my_pa.application.commands import (
    Command,
    ListConstraintCategories,
    ListConstraints,
    ReadConstraint,
    ReadConstraintHistory,
    ReadConstraintOverview,
    SearchConstraints,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.application.service import _HANDLERS, ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.project_controls.read_models import (
    MAX_CURSOR_CHARACTERS,
    MAX_LIST_LIMIT,
    MAX_SEARCH_CHARACTERS,
    ConstraintCategoryState,
    ConstraintGrouping,
    ConstraintListScope,
    ConstraintSort,
    SortDirection,
)
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


@pytest.mark.parametrize("capability", sorted(EXPECTED, key=lambda c: c.value))
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


@pytest.mark.parametrize("capability", sorted(EXPECTED, key=lambda c: c.value))
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
    for capability in EXPECTED:
        body = _handler_source(capability)
        assert "date(" not in body
        assert "datetime(" not in body
        assert str(UTC) not in body or "self._clock()" in body
    assert date is not None and datetime is not None
