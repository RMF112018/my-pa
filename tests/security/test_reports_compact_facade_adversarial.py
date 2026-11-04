"""Reports Modernization WP02: `reports.publish` / `reports.read` refusals on the compact facade.

Spec C section 5 layer 11, negative half. The harness is
`tests/contract/test_reports_compact_facade.py`'s: the real remote MCP app, the
real `RemoteAuthenticator` over the durable grant store on PostgreSQL, the
composition root's `remote_access_context` and a real `ApplicationService`.

Every refusal below happens before any mutation: each asserts the six
standalone report tables (and the `knowledge.intelligence_*` tables) hold
exactly the rows they held before the request. Every identity is synthetic.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine
from tests.conftest import metadata_for, operator
from tests.contract.test_reports_compact_facade import (
    CLIENT,
    INTELLIGENCE_TABLES,
    MINIMAL,
    PLANE_TABLES,
    PUBLISH,
    READ,
    WHEN,
    Harness,
    build_service,
    counts,
    describe,
    grant_row,
    outcome,
    profile_grants,
    refusal,
    remote_principal,
    wrapped,
)

from my_pa.adapters.mcp.chatllm_gateway import (
    DESCRIBE_TOOL,
    OPERATOR_TOOL,
    READ_TOOL,
    WRITE_TOOL,
)
from my_pa.adapters.remote_request import compose_remote_arguments
from my_pa.application.errors import InvalidRequestError
from my_pa.domain.identity.operation import Capability, is_operator_only
from my_pa.domain.identity.purpose import Purpose

pytestmark = pytest.mark.database

_ALL_TABLES: Final = PLANE_TABLES + INTELLIGENCE_TABLES


@pytest.fixture
def harness(migrated_engine: Engine) -> Harness:
    built = Harness(migrated_engine, build_service(migrated_engine))
    built.gates()
    return built


def _without(*capabilities: Capability, harness: Harness) -> tuple[Any, ...]:
    return tuple(row for row in profile_grants(harness.service) if row[0] not in capabilities)


def _catalog(harness: Harness, token: str, **filters: Any) -> set[str]:  # noqa: ANN401
    (answer,) = harness.run([(token, describe(limit=100, **filters))])
    _failed, catalog = outcome(answer)
    return {item["capability"] for item in catalog["items"]}


def _publish_is_hidden_and_refused(
    harness: Harness, token: str, *, process_writes: bool = True
) -> None:
    before = counts(harness.engine, _ALL_TABLES)
    listed, exact, written = harness.run(
        [
            (token, describe(feature="reports", limit=100)),
            (token, describe(capability=PUBLISH.value)),
            (token, wrapped(WRITE_TOOL, PUBLISH, MINIMAL)),
        ],
        process_writes=process_writes,
    )
    _failed, catalog = outcome(listed)
    seen = {item["capability"] for item in catalog["items"]}
    assert PUBLISH.value not in seen
    assert READ.value in seen
    assert refusal(exact) == ("unsupported", [])
    assert refusal(written) == ("unsupported", [])
    assert counts(harness.engine, _ALL_TABLES) == before


def test_publish_omitted_from_the_client_profile_is_hidden_and_refused(harness: Harness) -> None:
    token = harness.client(CLIENT, _without(PUBLISH, harness=harness))
    _publish_is_hidden_and_refused(harness, token)


@pytest.mark.parametrize(
    ("process", "durable_global", "client"),
    [(False, True, True), (True, False, True), (True, True, False)],
    ids=["process_writes_off", "global_writes_off", "client_writes_off"],
)
def test_any_write_gate_off_hides_and_refuses_publish(
    harness: Harness, process: bool, durable_global: bool, client: bool
) -> None:
    harness.gates(writes=durable_global)
    token = harness.client(CLIENT, profile_grants(harness.service), writes=client)
    _publish_is_hidden_and_refused(harness, token, process_writes=process)
    # The read side is untouched by every write gate.
    assert READ.value in _catalog(harness, token, feature="reports")


def test_a_mis_flagged_read_publish_grant_still_needs_the_write_gates(harness: Harness) -> None:
    """A `reports.publish` grant stored `is_write = false` survives grant resolution
    with the client write flag off, and the composition root still withholds it:
    the write classification comes from the purpose, never from the grant row."""
    rows = (*_without(PUBLISH, harness=harness), grant_row(PUBLISH, is_write=False))
    token = harness.client(CLIENT, rows, writes=False)
    _publish_is_hidden_and_refused(harness, token)


def test_an_inexact_publish_grant_is_refused(harness: Harness) -> None:
    """Insufficient exact grant: `reports.publish` granted under `report_read`.

    The grant names the capability, so describe lists it, but `report_read`
    intersects nothing `reports.publish` permits: the remote boundary refuses
    before a Purpose is chosen and before `invoke`.
    """
    rows = (*_without(PUBLISH, harness=harness), grant_row(PUBLISH, purpose=Purpose.REPORT_READ))
    token = harness.client(CLIENT, rows)
    before = counts(harness.engine, _ALL_TABLES)
    (written,) = harness.run([(token, wrapped(WRITE_TOOL, PUBLISH, MINIMAL))])
    assert refusal(written) == ("unsupported", [])
    assert counts(harness.engine, _ALL_TABLES) == before


def test_only_a_report_read_grant_reads_but_never_publishes(harness: Harness) -> None:
    token = harness.client(CLIENT, [grant_row(READ)])
    before = counts(harness.engine, _ALL_TABLES)
    tools, listed, exact, written = harness.run(
        [
            (token, {"jsonrpc": "2.0", "id": 9, "method": "tools/list"}),
            (token, describe(limit=100)),
            (token, describe(capability=PUBLISH.value)),
            (token, wrapped(WRITE_TOOL, PUBLISH, MINIMAL)),
        ]
    )
    names = {tool["name"] for tool in tools.document["result"]["tools"]}
    assert names == {DESCRIBE_TOOL, READ_TOOL}
    _failed, catalog = outcome(listed)
    assert [item["capability"] for item in catalog["items"]] == [READ.value]
    assert refusal(exact) == ("unsupported", [])
    assert refusal(written) == ("unsupported", [])
    assert counts(harness.engine, _ALL_TABLES) == before


def test_an_expired_publish_grant_is_hidden_and_refused(harness: Harness) -> None:
    expired = grant_row(PUBLISH, expires_at=WHEN - timedelta(seconds=1))
    token = harness.client(CLIENT, (*_without(PUBLISH, harness=harness), expired))
    _publish_is_hidden_and_refused(harness, token)


def test_a_revoked_client_is_refused_before_any_tool(harness: Harness) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    harness.revoke(CLIENT)
    before = counts(harness.engine, _ALL_TABLES)
    answers = harness.run(
        [
            (token, describe(capability=PUBLISH.value)),
            (token, wrapped(WRITE_TOOL, PUBLISH, MINIMAL)),
            (token, wrapped(READ_TOOL, READ, {"report_id": "grpt_00000000nothere0"})),
        ]
    )
    for answer in answers:
        assert answer.status == 401
        assert answer.document == {"error": "invalid_token"}
    assert counts(harness.engine, _ALL_TABLES) == before


def test_the_wrong_wrapper_is_refused_both_ways(harness: Harness) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    before = counts(harness.engine, _ALL_TABLES)
    publish_as_read, read_as_write, publish_as_operator = harness.run(
        [
            (token, wrapped(READ_TOOL, PUBLISH, MINIMAL)),
            (token, wrapped(WRITE_TOOL, READ, {"report_id": "grpt_00000000nothere0"})),
            (token, wrapped(OPERATOR_TOOL, PUBLISH, MINIMAL)),
        ]
    )
    assert refusal(publish_as_read)[0] == "invalid_request"
    assert refusal(read_as_write)[0] == "invalid_request"
    # `my_pa.operator` is not published to an ordinary client at all.
    assert refusal(publish_as_operator) == ("unsupported", [])
    assert counts(harness.engine, _ALL_TABLES) == before


def test_a_foreign_report_reads_exactly_as_a_nonexistent_one(harness: Harness) -> None:
    stranger = operator()
    assert stranger.principal_id != remote_principal().principal_id
    foreign = harness.service.invoke(
        metadata_for(PUBLISH, Purpose.REPORT_AUTHORING, stranger),
        _publish_command(stranger.principal_id),
        principal=stranger,
    )
    assert foreign.result is not None, foreign.error
    token = harness.client(CLIENT, profile_grants(harness.service))
    theirs, missing, theirs_by_version = harness.run(
        [
            (token, wrapped(READ_TOOL, READ, {"report_id": foreign.result["report_id"]})),
            (token, wrapped(READ_TOOL, READ, {"report_id": "grpt_00000000nothere0"})),
            (
                token,
                wrapped(
                    READ_TOOL,
                    READ,
                    {
                        "report_id": foreign.result["report_id"],
                        "version_id": foreign.result["version_id"],
                        "include_manifest": True,
                    },
                ),
            ),
        ]
    )
    _failed, first = outcome(theirs)
    _failed, second = outcome(missing)
    _failed, third = outcome(theirs_by_version)
    for document in (first, second, third):
        problem = document["error"]
        assert (problem["code"], problem["safe_details"]) == ("not_found", ["artifact_id"])
    redacted = [
        {key: value for key, value in document["error"].items() if key != "correlation_id"}
        for document in (first, second, third)
    ]
    assert redacted[0] == redacted[1] == redacted[2]
    assert foreign.result["report_id"] not in str(first)


def _publish_command(principal_id: str) -> Any:  # noqa: ANN401
    from my_pa.adapters.normalization import normalize

    _metadata, command = normalize(
        PUBLISH.value,
        {
            "request_id": "req-foreign-publish",
            "purpose": Purpose.REPORT_AUTHORING.value,
            "principal_id": principal_id,
            "requested_at": "2026-11-04T12:00:00Z",
            "payload": {**MINIMAL, "idempotency_key": "foreign-publish"},
        },
    )
    return command


_SERVER_OWNED: Final = (
    "principal_id",
    "idempotency_key",
    "purpose",
    "created_at",
    "report_id",
    "version_id",
    "receipt_id",
    "verification",
)


@pytest.mark.parametrize("name", _SERVER_OWNED)
def test_a_forged_server_field_in_the_payload_is_refused(harness: Harness, name: str) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    before = counts(harness.engine, _ALL_TABLES)
    (written,) = harness.run(
        [(token, wrapped(WRITE_TOOL, PUBLISH, {**MINIMAL, name: "forged-value"}))]
    )
    assert refusal(written)[0] == "invalid_request"
    assert counts(harness.engine, _ALL_TABLES) == before


@pytest.mark.parametrize("name", ["principal_id", "purpose", "request_id", "scope"])
def test_a_forged_envelope_field_in_the_nested_arguments_is_refused(
    harness: Harness, name: str
) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    before = counts(harness.engine, _ALL_TABLES)
    document = {
        "capability": PUBLISH.value,
        "arguments": {"payload": MINIMAL, name: "forged-value"},
    }
    from tests.contract.test_reports_compact_facade import call

    (written,) = harness.run([(token, call(WRITE_TOOL, document))])
    assert refusal(written)[0] == "invalid_request"
    assert counts(harness.engine, _ALL_TABLES) == before


@pytest.mark.parametrize("name", ["cycle_run_id", "stage"])
def test_a_pipeline_field_is_refused(harness: Harness, name: str) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    before = counts(harness.engine, _ALL_TABLES)
    (written,) = harness.run(
        [(token, wrapped(WRITE_TOOL, PUBLISH, {**MINIMAL, name: "collector"}))]
    )
    assert refusal(written)[0] == "invalid_request"
    assert counts(harness.engine, _ALL_TABLES) == before


def test_the_remote_key_is_refused_before_purpose_selection() -> None:
    """`idempotency_key` is remote-owned: refused even with an exact publish grant."""
    with pytest.raises(InvalidRequestError):
        compose_remote_arguments(
            capability_name=PUBLISH.value,
            arguments={"payload": {**MINIMAL, "idempotency_key": "caller-chosen"}},
            principal=remote_principal(),
            grants=frozenset({(PUBLISH, Purpose.REPORT_AUTHORING)}),
            authenticated_client_id=CLIENT,
        )


def test_an_operator_capability_is_refused_on_the_ordinary_facade(harness: Harness) -> None:
    """A granted operator-only name is never published to an ordinary compact client."""
    enroll = Capability.SOURCES_ENROLL
    assert is_operator_only(enroll)
    token = harness.client(
        CLIENT, (*profile_grants(harness.service), grant_row(enroll, is_write=True))
    )
    before = counts(harness.engine, _ALL_TABLES)
    tools, listed, exact, as_operator, as_write = harness.run(
        [
            (token, {"jsonrpc": "2.0", "id": 9, "method": "tools/list"}),
            (token, describe(limit=100, kind="operator")),
            (token, describe(capability=enroll.value)),
            (token, wrapped(OPERATOR_TOOL, enroll, {})),
            (token, wrapped(WRITE_TOOL, enroll, {})),
        ]
    )
    assert OPERATOR_TOOL not in {tool["name"] for tool in tools.document["result"]["tools"]}
    _failed, catalog = outcome(listed)
    assert catalog["items"] == []
    for answer in (exact, as_operator, as_write):
        assert refusal(answer) == ("unsupported", [])
    assert counts(harness.engine, _ALL_TABLES) == before
