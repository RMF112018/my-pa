"""The operator CLI as a program, and specifically as one that is not privileged.

`module-boundaries.md` section 5.7 ends with four words — "CLI is not a
privileged bypass" — and they are the reason this file exists. A CLI is the
transport most able to become one, because it runs on the operator's machine
with the operator's shell, and because it is the one place where "just add a
`--principal` flag" looks like a convenience.

What is asserted here:

* the **authorization path is the same one**: an operator-only capability is
  refused to a principal that is not an operator, and no option can change the
  principal;
* **nothing HTTP would deny is reachable**: driven capability by capability with
  a non-operator principal, the CLI's answers are the HTTP gateway's answers;
* **argparse never speaks**: a bad option, a missing value, an unknown flag —
  each is the same typed refusal, and none of them echoes what the operator
  typed;
* **one document on standard output, nothing on standard error**, so a caller
  redirecting one stream is not discarding the answer;
* the **exit status** follows the envelope and not a second judgement.

`SPEC-AC-001`'s comparisons live in `test_transport_parity.py`; the redaction
claims live in `tests/security`. This is the program.
"""

from __future__ import annotations

import argparse
import io
import json
from collections.abc import Sequence
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy

import apps.cli.invoke as entry_point
import pytest
from tests.conftest import Scene, World, build_service, staged_record
from tests.contract.test_transport_parity import (
    a_forbidden_purpose,
    a_permitted_purpose,
    document,
    payloads_for,
)
from tests.transports import Answer, CliTransport, http_transport

from my_pa.adapters.cli import EXIT_FAILED, EXIT_OK, build_parser, run
from my_pa.adapters.normalization import MAX_REQUEST_BYTES
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, is_operator_only
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.source.registry import issue_identifier


def not_an_operator() -> Principal:
    """An authenticated principal that is not the operator.

    `PrincipalKind.GATEWAY` rather than an unauthenticated one, so what is being
    refused is the *kind* rather than the authentication — which is the case a
    privileged bypass would actually be built for.
    """
    return Principal(
        principal_id=issue_identifier(IdKind.PRINCIPAL),
        kind=PrincipalKind.GATEWAY,
        authenticated=True,
    )


def invoke(
    service: ApplicationService, principal: Principal, argv: Sequence[str]
) -> tuple[int, str, str]:
    """Run the CLI and return its status, standard output, and standard error."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stderr(err):
        status = run(argv, service, principal=principal, out=out)
    return status, out.getvalue(), err.getvalue()


@pytest.fixture
def cli(scene: Scene) -> CliTransport:
    staged_record(scene, text="quarterly revenue review")
    return CliTransport(build_service(scene.world, scene.providers), scene.principal)


# ---- not a privileged bypass -------------------------------------------------


def test_an_operator_only_capability_is_still_operator_only(scene: Scene) -> None:
    """The same capability, the same request, two principals, two answers.

    Both halves matter. The refusal alone would also hold on a CLI that refused
    everything, and the acceptance alone would hold on one that authorized
    nothing.

    Each runs against its own copy of the world, because the capability that is
    operator-only is `sources.enroll` and it writes: sharing one world would
    make the second invocation an idempotent retry of the first, and the answer
    would then be `conflict` for a reason that has nothing to do with authority.
    """
    capability = next(c for c in Capability if is_operator_only(c))
    request = document(
        capability,
        scene.principal.principal_id,
        payloads_for(scene, staged_record(scene, text="x"))[capability],
    )
    argv = CliTransport.argv(capability.value, request)

    def over(principal: Principal) -> Answer:
        service = build_service(deepcopy(scene.world), scene.providers)
        return CliTransport(service, principal).run(argv)

    assert over(scene.principal).failed is False
    denied = over(not_an_operator())
    assert denied.failed is True
    assert denied.document["error"]["code"] == ErrorCode.DENIED.value


def test_no_option_can_change_the_acting_principal() -> None:
    """`--principal-id` exists and is correlation input; there is no option that is not.

    The contract puts `principal_id` in the request metadata as correlation
    input the application does not trust, so the CLI carries it like every other
    envelope field. What must not exist is an option that changes *authority*,
    and the check is over the whole option surface rather than over a name a
    reader thought of.
    """
    parser = build_parser()
    options = {
        option
        for action in parser._actions
        for option in action.option_strings
        if option not in {"-h", "--help"}
    }
    forbidden = ("kind", "operator", "authenticated", "role", "token", "credential", "auth")
    named = sorted(option for option in options if any(word in option for word in forbidden))
    assert not named, f"the CLI offers {named}, which would be an authority option"


def test_a_supplied_principal_id_does_not_become_authority(scene: Scene) -> None:
    """The operator's own identifier, typed by a caller that is not the operator.

    This is the injection the CLI is most exposed to: the acting principal comes
    from the composition root, and `--principal-id` is a field in a document.
    Naming the operator in it changes nothing.
    """
    capability = next(c for c in Capability if is_operator_only(c))
    request = document(
        capability,
        scene.principal.principal_id,
        payloads_for(scene, staged_record(scene, text="x"))[capability],
    )
    service = build_service(scene.world, scene.providers)
    argv = CliTransport.argv(capability.value, request)
    answer = CliTransport(service, not_an_operator()).run(argv)
    assert answer.failed is True
    assert answer.document["error"]["code"] == ErrorCode.DENIED.value


@pytest.mark.parametrize("capability", list(Capability), ids=lambda c: c.value)
def test_the_cli_reaches_nothing_http_would_deny(capability: Capability, scene: Scene) -> None:
    """Capability by capability, the CLI's answer is the gateway's answer.

    Driven with a principal that holds nothing, because that is the state in
    which a bypass would show: a CLI that skipped authorization would succeed
    here while the gateway refused.
    """
    stranger = not_an_operator()
    record = staged_record(scene, text="quarterly revenue review")
    request = document(capability, stranger.principal_id, payloads_for(scene, record)[capability])

    over_cli = CliTransport(build_service(scene.world, scene.providers), stranger).send(
        capability.value, request
    )
    with http_transport(build_service(scene.world, scene.providers), stranger) as gateway:
        over_http = gateway.send(capability.value, request)

    assert over_cli.failed == over_http.failed, capability.value
    cli_error = over_cli.document.get("error") or {}
    http_error = over_http.document.get("error") or {}
    assert cli_error.get("code") == http_error.get("code"), capability.value


# ---- argparse never speaks ---------------------------------------------------


#: Every way a command line can be wrong, and the value each carries that must
#: not come back. The value is distinctive so a substring search is decisive.
MALFORMED = [
    ("an unknown option", ["capabilities.get", "--nope", "MARKERTYPEDVALUE"]),
    ("a missing value", ["capabilities.get", "--request-id"]),
    ("no capability at all", []),
    ("a payload that is not JSON", ["capabilities.get", "--payload", "{MARKERTYPEDVALUE"]),
    ("a payload that is not an object", ["capabilities.get", "--payload", '["MARKERTYPEDVALUE"]']),
    ("a capability that does not exist", ["sources.destroy", "--payload", "{}"]),
    ("an extra positional", ["capabilities.get", "MARKERTYPEDVALUE"]),
]


@pytest.mark.parametrize(("name", "argv"), MALFORMED, ids=lambda value: str(value))
def test_a_malformed_command_line_is_a_typed_error(
    name: str, argv: list[str], scene: Scene
) -> None:
    """`AC-7`: a typed error, never a stack trace, never a usage message.

    And never the value the operator typed. `argparse`'s own message would have
    named it — which is how a `--payload` carrying a query reaches a terminal
    and a shell history — so the assertion is over both streams.
    """
    service = build_service(scene.world, scene.providers)
    status, out, err = invoke(service, scene.principal, argv)
    assert status == EXIT_FAILED, name
    problem = json.loads(out)
    assert problem["code"] == ErrorCode.INVALID_REQUEST.value, name
    assert err == "", f"{name} wrote to standard error: {err!r}"
    for leak in ("MARKERTYPEDVALUE", "Traceback", "usage:", "unrecognized"):
        assert leak not in out, f"{name} disclosed {leak!r} on standard output"
    assert scene.world.audit == [], f"{name} reached the application"


def test_help_still_works() -> None:
    """The refusal replaced `argparse`'s errors, not its help.

    Help is the one thing a usage message is for, it names options rather than
    values, and a transport that could not describe itself would be worse than
    one that occasionally said too much.
    """
    out = io.StringIO()
    with redirect_stdout(out), pytest.raises(SystemExit) as exit_status:
        build_parser().parse_args(["--help"])
    assert exit_status.value.code == 0
    assert "--payload" in out.getvalue()
    assert "capability" in out.getvalue()


def test_an_oversized_payload_is_refused_and_not_echoed(scene: Scene) -> None:
    """The HTTP transport's own ceiling, enforced from a shell."""
    payload = {"source_id": scene.source.source_id, "filler": "x" * (MAX_REQUEST_BYTES + 1)}
    service = build_service(scene.world, scene.providers)
    status, out, err = invoke(
        service,
        scene.principal,
        ["sources.list", "--request-id", "r", "--payload", json.dumps(payload)],
    )
    assert status == EXIT_FAILED
    assert json.loads(out)["code"] == ErrorCode.INVALID_REQUEST.value
    assert "x" * 64 not in out
    assert err == ""


# ---- output and exit status ---------------------------------------------------


def test_a_successful_request_writes_one_envelope_and_exits_zero(cli: CliTransport) -> None:
    answer = cli.send(
        Capability.CAPABILITIES_GET.value,
        document(Capability.CAPABILITIES_GET, issue_identifier(IdKind.PRINCIPAL), {}),
    )
    assert answer.failed is False
    assert answer.document["error"] is None
    assert answer.document["disclosure"] is not None


def test_the_exit_status_follows_the_envelope_and_nothing_else(scene: Scene) -> None:
    """Two requests differing only in purpose, and the status follows the answer."""
    service = build_service(scene.world, scene.providers)
    allowed = document(Capability.CAPABILITIES_GET, scene.principal.principal_id, {})
    denied = document(
        Capability.CAPABILITIES_GET,
        scene.principal.principal_id,
        {},
        purpose=a_forbidden_purpose(Capability.CAPABILITIES_GET),
    )
    ok_status, ok_out, _ = invoke(
        service, scene.principal, CliTransport.argv(Capability.CAPABILITIES_GET.value, allowed)
    )
    bad_status, bad_out, _ = invoke(
        service, scene.principal, CliTransport.argv(Capability.CAPABILITIES_GET.value, denied)
    )
    assert (ok_status, bad_status) == (EXIT_OK, EXIT_FAILED)
    assert json.loads(ok_out)["error"] is None
    assert json.loads(bad_out)["error"]["code"] == ErrorCode.DENIED.value


def test_every_answer_is_one_line_of_json(cli: CliTransport, scene: Scene) -> None:
    """One document per invocation, newline-terminated, parseable by a pipe."""
    for capability in Capability:
        request = document(
            capability,
            scene.principal.principal_id,
            payloads_for(scene, staged_record(scene, text="x"))[capability],
        )
        status, out, err = invoke(
            build_service(scene.world, scene.providers),
            scene.principal,
            CliTransport.argv(capability.value, request),
        )
        assert out.endswith("\n"), capability.value
        assert len(out.strip().splitlines()) == 1, capability.value
        assert json.loads(out), capability.value
        assert err == "", capability.value
        assert status in {EXIT_OK, EXIT_FAILED}


# ---- the entry point ----------------------------------------------------------


def test_the_entry_point_composes_the_same_runtime_the_gateway_does() -> None:
    """`apps/cli/invoke.py` chooses no implementation of its own.

    Read from the source rather than executed, because executing it opens a
    connection pool. What matters is that it asks `bootstrap.gateway` for the
    runtime and hands the principal it was given straight through — a second
    composition here is how the CLI would come to differ from the served
    application without anyone deciding that it should.
    """
    source = entry_point.__doc__ or ""
    assert "build_gateway_runtime" in entry_point.main.__globals__
    assert entry_point.main.__globals__["run"] is run
    assert "principal" in source.lower()
    for chosen in ("SqlAlchemyUnitOfWork", "ApplicationService", "create_database_engine"):
        assert chosen not in entry_point.main.__globals__, f"the entry point composes {chosen}"


def test_the_entry_point_releases_its_runtime_on_every_path() -> None:
    """A CLI that leaked a pool per invocation would exhaust the server one command at a time."""
    import inspect

    source = inspect.getsource(entry_point.main)
    assert "finally:" in source
    assert "runtime.close()" in source


def test_the_other_operator_programs_are_untouched_and_separate() -> None:
    """`apps/cli/` holds four operator programs, and they share no surface.

    Stated as a test because "extend rather than replace" is only checkable if
    something checks that the other programs still exist and still mean what they
    did. A capability name arriving in the migration CLI, a migration phase
    arriving here, or a `--root` reaching the capability transport would be the
    planes merging.

    `sources.py` joined them with `D-42` and `health.py` with `D-62`.
    `sources.py` is the one that most needed pinning: it writes to the same
    database as this transport does and is deliberately not a capability.
    `tests/architecture/test_operator_commands_are_not_capabilities.py` is what
    holds that for both of them; this holds the weaker and more visible half,
    which is that the four do not share an option between them.

    `health.py` offers **no option at all** and that is asserted rather than
    skipped over. A program with an empty option set satisfies every pairwise
    disjointness comparison for free, so the comparisons alone would say nothing
    about it; what carries meaning is the exact equality below, which fails the
    day it grows a flag.
    """
    import apps.cli.health as health
    import apps.cli.migration as migration
    import apps.cli.sources as source_registration

    assert migration.build_parser is not entry_point.main
    assert source_registration.build_parser is not entry_point.main
    assert health.build_parser is not entry_point.main
    assert source_registration.build_parser is not migration.build_parser
    assert health.build_parser is not migration.build_parser
    assert health.build_parser is not source_registration.build_parser

    def options(parser: object) -> set[str]:
        """Every option a program offers, subcommands included.

        Descending into the subparsers is what makes this decide anything: two
        of the four programs put every option behind a subcommand, so a
        comparison of the top-level parsers alone would compare two copies of
        `--help`.
        """
        actions = list(parser._actions)  # type: ignore[attr-defined]
        found: set[str] = set()
        while actions:
            action = actions.pop()
            found.update(action.option_strings)
            if isinstance(action, argparse._SubParsersAction):
                for nested in action.choices.values():
                    actions.extend(nested._actions)
        return found

    migration_options = options(migration.build_parser())
    sources_options = options(source_registration.build_parser())
    health_options = options(health.build_parser())
    cli_options = options(build_parser())
    assert {"--source", "--run-id"} <= migration_options
    assert {"--root", "--provider", "--label", "--classification"} <= sources_options
    assert {"--payload", "--request-id"} <= cli_options
    assert health_options == {"-h", "--help"}
    assert migration_options & cli_options == {"-h", "--help"}
    assert sources_options & cli_options == {"-h", "--help"}
    assert sources_options & migration_options == {"-h", "--help"}
    assert health_options & cli_options == {"-h", "--help"}
    assert health_options & migration_options == {"-h", "--help"}
    assert health_options & sources_options == {"-h", "--help"}


def test_the_world_used_here_is_not_empty(scene: Scene) -> None:
    """Guard the fixtures: an empty world would make the refusals above trivial."""
    assert scene.world.enrollments
    assert isinstance(build_service(World(), scene.providers), ApplicationService)
    assert a_permitted_purpose(Capability.SOURCES_ENROLL)
    assert scene.source.source_id and scene.markdown.source_object_id
