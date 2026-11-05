"""Reports Modernization WP02/WP03: standalone report refusals on the compact facade.

Spec C section 5 layer 11, negative half. The harness is
`tests/contract/test_reports_compact_facade.py`'s: the real remote MCP app, the
real `RemoteAuthenticator` over the durable grant store on PostgreSQL, the
composition root's `remote_access_context` and a real `ApplicationService`.

Every refusal below happens before any mutation: each asserts the six
standalone report tables (and the `knowledge.intelligence_*` tables) hold
exactly the rows they held before the request. Every identity is synthetic.

WP03 (`chatllm-data-v13`) adds the same refusals for `reports.update`,
`reports.history`, `reports.archive`, `reports.delete` and `reports.restore`,
counting the lifecycle events table too: profile omission, every write gate,
`report_authoring` never standing in for `report_lifecycle` (and a
lifecycle-only client never updating), expiry, revocation, the wrong wrapper,
a foreign report answering exactly as a nonexistent one, and forged server
fields.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text
from tests.conftest import metadata_for, operator
from tests.contract.test_reports_compact_facade import (
    ARCHIVE,
    CLIENT,
    DELETE,
    HISTORY,
    INTELLIGENCE_TABLES,
    LIFECYCLE_MOVES,
    MANAGEMENT,
    MANAGEMENT_WRITES,
    MINIMAL,
    MUTATION_TABLES,
    PLANE_TABLES,
    PUBLISH,
    READ,
    RESTORE,
    UPDATE,
    WHEN,
    Harness,
    build_service,
    counts,
    describe,
    grant_row,
    move_payload,
    ok,
    outcome,
    profile_grants,
    refusal,
    remote_principal,
    update_payload,
    wrapped,
)

from my_pa.adapters.mcp.chatllm_gateway import (
    DESCRIBE_TOOL,
    OPERATOR_TOOL,
    READ_TOOL,
    WRITE_TOOL,
)
from my_pa.adapters.normalization import MAX_REQUEST_BYTES
from my_pa.adapters.remote_request import compose_remote_arguments
from my_pa.application.errors import InvalidRequestError
from my_pa.domain.identity.operation import Capability, is_operator_only
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.reports.content import INLINE_CONTENT_MAX_BYTES

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


def _following(report_id: str, version_ref: str) -> dict[str, Any]:
    return {
        **MINIMAL,
        "associations": [
            {
                "target_kind": "standalone_report",
                "target_ref": report_id,
                "relation": "follows",
                "target_version_ref": version_ref,
            }
        ],
    }


def test_a_version_ref_is_verified_against_the_callers_own_report(harness: Harness) -> None:
    """A foreign or nonexistent `grver_` is refused as not found; never stored `verified`."""
    token = harness.client(CLIENT, profile_grants(harness.service))
    (mine,) = harness.run([(token, wrapped(WRITE_TOOL, PUBLISH, MINIMAL))])
    own = ok(mine)
    stranger = operator()
    foreign = harness.service.invoke(
        metadata_for(PUBLISH, Purpose.REPORT_AUTHORING, stranger),
        _publish_command(stranger.principal_id),
        principal=stranger,
    )
    assert foreign.result is not None, foreign.error
    before = counts(harness.engine, _ALL_TABLES)
    refused = harness.run(
        [
            (token, wrapped(WRITE_TOOL, PUBLISH, _following(own["report_id"], ref)))
            for ref in (foreign.result["version_id"], "grver_00000000nothere0")
        ]
    )
    for answer in refused:
        assert refusal(answer) == ("not_found", ["associations"])
    assert counts(harness.engine, _ALL_TABLES) == before

    (accepted,) = harness.run(
        [(token, wrapped(WRITE_TOOL, PUBLISH, _following(own["report_id"], own["version_id"])))]
    )
    receipt = ok(accepted)
    with harness.engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT target_ref, target_version_ref, verification "
                "FROM knowledge.report_associations WHERE version_id = :v"
            ),
            {"v": receipt["version_id"]},
        ).one()
    assert tuple(stored) == (own["report_id"], own["version_id"], "verified")


def test_an_escape_heavy_body_under_the_inline_limit_can_exceed_the_wire_ceiling(
    harness: Harness,
) -> None:
    """The 524,288-byte limit is decoded bytes; the escaped JSON request has its own ceiling.

    Every `"` costs two bytes on the wire, so a body well under the inline
    limit is refused at the transport, before any handler, with no row written.
    """
    token = harness.client(CLIENT, profile_grants(harness.service))
    body = '"' * 400_000
    assert len(body.encode()) < INLINE_CONTENT_MAX_BYTES
    payload = {**MINIMAL, "content": {"format": "text", "body": body}}
    before = counts(harness.engine, _ALL_TABLES)
    (answer,) = harness.run([(token, wrapped(WRITE_TOOL, PUBLISH, payload))])
    assert answer.request_bytes > MAX_REQUEST_BYTES
    assert answer.status == 413, (answer.status, answer.document)
    assert counts(harness.engine, _ALL_TABLES) == before


# ---- Reports Modernization WP03: update, history, archive, delete, restore -------------

_MUTATION: Final = MUTATION_TABLES + INTELLIGENCE_TABLES
_MISSING: Final = "grpt_00000000nothere0"


def _owned_report(harness: Harness) -> str:
    """One active report of the remote Principal, published on the local canonical path."""
    principal = remote_principal()
    published = harness.service.invoke(
        metadata_for(PUBLISH, Purpose.REPORT_AUTHORING, principal),
        _publish_command(principal.principal_id),
        principal=principal,
    )
    assert published.result is not None, published.error
    return str(published.result["report_id"])


def _payload(capability: Capability, report_id: str) -> dict[str, Any]:
    """A payload that would execute against `report_id` were it admitted."""
    if capability is UPDATE:
        return update_payload(report_id, 1, {"title": "Refused"})
    if capability is HISTORY:
        return {"report_id": report_id, "include_withdrawn": True}
    # Archive and delete are legal at revision 0; restore is refused by the
    # domain later, but these tests stop well before the domain.
    return move_payload(report_id, 0)


def _wrapper(capability: Capability) -> str:
    return READ_TOOL if capability is HISTORY else WRITE_TOOL


def _hidden_and_refused(
    harness: Harness,
    token: str,
    capabilities: tuple[Capability, ...],
    *,
    process_writes: bool = True,
) -> None:
    """Each name is absent from describe, unsupported exactly, unsupported to call; no row."""
    rid = _owned_report(harness)
    before = counts(harness.engine, _MUTATION)
    answers = harness.run(
        [(token, describe(feature="reports", limit=100))]
        + [(token, describe(capability=capability.value)) for capability in capabilities]
        + [
            (token, wrapped(_wrapper(capability), capability, _payload(capability, rid)))
            for capability in capabilities
        ],
        process_writes=process_writes,
    )
    _failed, catalog = outcome(answers[0])
    seen = {item["capability"] for item in catalog["items"]}
    assert not seen & {capability.value for capability in capabilities}
    for answer in answers[1:]:
        assert refusal(answer) == ("unsupported", [])
    assert counts(harness.engine, _MUTATION) == before


@pytest.mark.parametrize("capability", MANAGEMENT, ids=lambda c: c.value)
def test_a_management_name_omitted_from_the_profile_is_hidden_and_refused(
    harness: Harness, capability: Capability
) -> None:
    token = harness.client(CLIENT, _without(capability, harness=harness))
    _hidden_and_refused(harness, token, (capability,))
    # The rest of the reports family is untouched by the omission.
    others = {c.value for c in MANAGEMENT if c is not capability} | {PUBLISH.value, READ.value}
    assert others <= _catalog(harness, token, feature="reports")


@pytest.mark.parametrize(
    ("process", "durable_global", "client"),
    [(False, True, True), (True, False, True), (True, True, False)],
    ids=["process_writes_off", "global_writes_off", "client_writes_off"],
)
def test_any_write_gate_off_hides_and_refuses_every_management_write(
    harness: Harness, process: bool, durable_global: bool, client: bool
) -> None:
    harness.gates(writes=durable_global)
    token = harness.client(CLIENT, profile_grants(harness.service), writes=client)
    _hidden_and_refused(harness, token, MANAGEMENT_WRITES, process_writes=process)
    # History is a read: every write gate leaves it discoverable and executable.
    rid = _owned_report(harness)
    (answer,) = harness.run(
        [(token, wrapped(READ_TOOL, HISTORY, {"report_id": rid}))], process_writes=process
    )
    assert [item["version_number"] for item in ok(answer)["items"]] == [1]


def test_report_authoring_and_read_without_report_lifecycle_cannot_archive_delete_or_restore(
    harness: Harness,
) -> None:
    """Least privilege (RD-14): a publisher/updater holds no lifecycle authority."""
    rows = _without(*LIFECYCLE_MOVES, harness=harness)
    purposes = {row[1] for row in rows}
    assert {Purpose.REPORT_AUTHORING, Purpose.REPORT_READ} <= purposes
    assert Purpose.REPORT_LIFECYCLE not in purposes
    token = harness.client(CLIENT, rows)
    _hidden_and_refused(harness, token, LIFECYCLE_MOVES)
    # The same client still updates: its `report_authoring` grant is exact.
    rid = _owned_report(harness)
    (updated,) = harness.run(
        [(token, wrapped(WRITE_TOOL, UPDATE, update_payload(rid, 1, {"title": "Allowed"})))]
    )
    assert ok(updated)["version_number"] == 2


def test_lifecycle_grants_stamped_report_authoring_are_refused(harness: Harness) -> None:
    """`report_authoring` never stands in for `report_lifecycle`, even on the exact name.

    The grant rows name archive, delete and restore, so describe lists them, but
    `report_authoring` intersects nothing they permit: the remote boundary
    refuses before a Purpose is chosen and before `invoke`.
    """
    rows = (
        *_without(*LIFECYCLE_MOVES, harness=harness),
        *(grant_row(c, purpose=Purpose.REPORT_AUTHORING) for c in LIFECYCLE_MOVES),
    )
    token = harness.client(CLIENT, rows)
    rid = _owned_report(harness)
    before = counts(harness.engine, _MUTATION)
    answers = harness.run(
        [(token, wrapped(WRITE_TOOL, c, _payload(c, rid))) for c in LIFECYCLE_MOVES]
    )
    for answer in answers:
        assert refusal(answer) == ("unsupported", [])
    assert counts(harness.engine, _MUTATION) == before


def test_a_report_lifecycle_only_client_cannot_update(harness: Harness) -> None:
    token = harness.client(CLIENT, [grant_row(c) for c in LIFECYCLE_MOVES])
    _hidden_and_refused(harness, token, (UPDATE, HISTORY))
    assert _catalog(harness, token) == {c.value for c in LIFECYCLE_MOVES}
    # An update grant stamped `report_lifecycle` is refused too.
    rows = [grant_row(c) for c in LIFECYCLE_MOVES] + [
        grant_row(UPDATE, purpose=Purpose.REPORT_LIFECYCLE)
    ]
    other = harness.client("synthetic-reports-lifecycle-only", rows)
    rid = _owned_report(harness)
    before = counts(harness.engine, _MUTATION)
    (refused,) = harness.run([(other, wrapped(WRITE_TOOL, UPDATE, _payload(UPDATE, rid)))])
    assert refusal(refused) == ("unsupported", [])
    assert counts(harness.engine, _MUTATION) == before
    # Positive control: the lifecycle grant itself is exact.
    (archived,) = harness.run([(token, wrapped(WRITE_TOOL, ARCHIVE, move_payload(rid, 0)))])
    assert ok(archived)["lifecycle_state"] == "archived"


@pytest.mark.parametrize("capability", MANAGEMENT, ids=lambda c: c.value)
def test_an_expired_management_grant_is_hidden_and_refused(
    harness: Harness, capability: Capability
) -> None:
    expired = grant_row(capability, expires_at=WHEN - timedelta(seconds=1))
    token = harness.client(CLIENT, (*_without(capability, harness=harness), expired))
    _hidden_and_refused(harness, token, (capability,))


def test_a_revoked_client_is_refused_every_management_name(harness: Harness) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    rid = _owned_report(harness)
    harness.revoke(CLIENT)
    before = counts(harness.engine, _MUTATION)
    answers = harness.run(
        [(token, describe(capability=c.value)) for c in MANAGEMENT]
        + [(token, wrapped(_wrapper(c), c, _payload(c, rid))) for c in MANAGEMENT]
    )
    for answer in answers:
        assert answer.status == 401
        assert answer.document == {"error": "invalid_token"}
    assert counts(harness.engine, _MUTATION) == before


def test_the_wrong_wrapper_is_refused_for_every_management_name(harness: Harness) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    rid = _owned_report(harness)
    before = counts(harness.engine, _MUTATION)
    answers = harness.run(
        [(token, wrapped(READ_TOOL, c, _payload(c, rid))) for c in MANAGEMENT_WRITES]
        + [(token, wrapped(WRITE_TOOL, HISTORY, _payload(HISTORY, rid)))]
        + [(token, wrapped(OPERATOR_TOOL, c, _payload(c, rid))) for c in MANAGEMENT]
    )
    for answer in answers[: len(MANAGEMENT_WRITES) + 1]:
        assert refusal(answer)[0] == "invalid_request"
    # `my_pa.operator` is not published to an ordinary client at all.
    for answer in answers[len(MANAGEMENT_WRITES) + 1 :]:
        assert refusal(answer) == ("unsupported", [])
    assert counts(harness.engine, _MUTATION) == before


@pytest.mark.parametrize("capability", MANAGEMENT, ids=lambda c: c.value)
def test_a_foreign_report_answers_exactly_as_a_nonexistent_one(
    harness: Harness, capability: Capability
) -> None:
    stranger = operator()
    assert stranger.principal_id != remote_principal().principal_id
    foreign = harness.service.invoke(
        metadata_for(PUBLISH, Purpose.REPORT_AUTHORING, stranger),
        _publish_command(stranger.principal_id),
        principal=stranger,
    )
    assert foreign.result is not None, foreign.error
    theirs_id = str(foreign.result["report_id"])
    token = harness.client(CLIENT, profile_grants(harness.service))
    before = counts(harness.engine, _MUTATION)
    theirs, missing = harness.run(
        [
            (token, wrapped(_wrapper(capability), capability, _payload(capability, theirs_id))),
            (token, wrapped(_wrapper(capability), capability, _payload(capability, _MISSING))),
        ]
    )
    _failed, first = outcome(theirs)
    _failed, second = outcome(missing)
    for document in (first, second):
        problem = document["error"]
        assert (problem["code"], problem["safe_details"]) == ("not_found", ["artifact_id"])
    redacted = [
        {key: value for key, value in document["error"].items() if key != "correlation_id"}
        for document in (first, second)
    ]
    assert redacted[0] == redacted[1]
    assert theirs_id not in str(first)
    assert counts(harness.engine, _MUTATION) == before


_MANAGEMENT_SERVER_OWNED: Final = (
    "idempotency_key",
    "principal_id",
    "owner_principal_id",
    "purpose",
    "version_id",
    "version_number",
    "receipt_id",
    "lifecycle_state",
    "lifecycle_revision",
    "event_id",
    "prior_state",
    "resulting_state",
    "recorded_at",
    "issued_at",
    "manifest_sha256",
)


@pytest.mark.parametrize("name", _MANAGEMENT_SERVER_OWNED)
@pytest.mark.parametrize("capability", MANAGEMENT, ids=lambda c: c.value)
def test_a_forged_server_field_on_a_management_payload_is_refused(
    harness: Harness, capability: Capability, name: str
) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    rid = _owned_report(harness)
    before = counts(harness.engine, _MUTATION)
    forged = {**_payload(capability, rid), name: "forged-value"}
    (answer,) = harness.run([(token, wrapped(_wrapper(capability), capability, forged))])
    assert refusal(answer)[0] == "invalid_request"
    assert counts(harness.engine, _MUTATION) == before


@pytest.mark.parametrize("name", ["version_id", "receipt_id", "lifecycle_state", "principal_id"])
def test_a_forged_server_field_inside_the_patch_is_refused(harness: Harness, name: str) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    rid = _owned_report(harness)
    before = counts(harness.engine, _MUTATION)
    forged = update_payload(rid, 1, {"title": "Forged", name: "forged-value"})
    (answer,) = harness.run([(token, wrapped(WRITE_TOOL, UPDATE, forged))])
    assert refusal(answer)[0] == "invalid_request"
    assert counts(harness.engine, _MUTATION) == before


@pytest.mark.parametrize("capability", MANAGEMENT_WRITES, ids=lambda c: c.value)
def test_the_remote_key_is_refused_for_every_management_write(capability: Capability) -> None:
    """`idempotency_key` is remote-owned: refused even with the exact planner grant."""
    purpose = Purpose.REPORT_AUTHORING if capability is UPDATE else Purpose.REPORT_LIFECYCLE
    with pytest.raises(InvalidRequestError):
        compose_remote_arguments(
            capability_name=capability.value,
            arguments={
                "payload": {**_payload(capability, _MISSING), "idempotency_key": "caller-chosen"}
            },
            principal=remote_principal(),
            grants=frozenset({(capability, purpose)}),
            authenticated_client_id=CLIENT,
        )


@pytest.mark.parametrize("capability", MANAGEMENT_WRITES, ids=lambda c: c.value)
def test_the_server_stamps_a_client_bound_key_for_every_management_write(
    capability: Capability,
) -> None:
    purpose = Purpose.REPORT_AUTHORING if capability is UPDATE else Purpose.REPORT_LIFECYCLE
    keys = {
        client: compose_remote_arguments(
            capability_name=capability.value,
            arguments={"payload": _payload(capability, _MISSING)},
            principal=remote_principal(),
            grants=frozenset({(capability, purpose)}),
            authenticated_client_id=client,
        )["payload"]["idempotency_key"]
        for client in (CLIENT, "synthetic-other-client")
    }
    assert all(key.startswith("idk_") for key in keys.values())
    assert keys[CLIENT] != keys["synthetic-other-client"]


def test_a_stale_lifecycle_or_version_refuses_with_zero_mutation(harness: Harness) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    rid = _owned_report(harness)
    before = counts(harness.engine, _MUTATION)
    answers = harness.run(
        [
            (token, wrapped(WRITE_TOOL, UPDATE, update_payload(rid, 2, {"title": "Ahead"}))),
            (token, wrapped(WRITE_TOOL, ARCHIVE, move_payload(rid, 1))),
            (token, wrapped(WRITE_TOOL, DELETE, move_payload(rid, 5))),
            (token, wrapped(WRITE_TOOL, RESTORE, move_payload(rid, 0))),
        ]
    )
    assert refusal(answers[0]) == ("conflict", ["stale_version"])
    assert refusal(answers[1]) == ("conflict", ["expected_lifecycle_revision"])
    assert refusal(answers[2]) == ("conflict", ["expected_lifecycle_revision"])
    # Restore of an active report at the current revision is an illegal move.
    assert refusal(answers[3]) == ("conflict", ["lifecycle_state"])
    assert counts(harness.engine, _MUTATION) == before
