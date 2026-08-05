"""`PKL-MYPA-D-WP03-001`, pinned mechanically: the owner is the partition.

This module replaces `test_owner_is_not_authorization.py`, which pinned `D-72`
— capability and purpose alone, no owner condition anywhere. That decision
rested on `D-67`'s measurement that identity was **process-scoped**: three CLI
invocations minted three principals, so an owner-equality check would have made
a capture unrevisable by anything but the process that wrote it and `QC-AC-013`
unprovable across two processes. The ratified campaign supersedes both halves at
once, and they have to be superseded together:

* `local_principal` now derives the local operator's identifier from a fixed
  UUID namespace (`my_pa.domain.identity.binding`), so two compositions over one
  database present **one** principal. `D-67`'s premise is dissolved rather than
  overruled — there is no longer a per-run identity for an owner check to
  strand.
* With the premise gone, the capture store partitions every read, list, search,
  and revise-head lookup by the caller's `principal_id`. A foreign capture is
  indistinguishable from an absent one and surfaces as `not_found`, never as a
  `forbidden` that would confirm the identifier exists.

**Both directions are asserted.** The first test is the restart story `D-72`
protected, still green: a capture created by one composition is revised and read
by another, because the two compositions are the same principal. The second is
the isolation `D-72` could not have: a principal that did not write a capture
cannot revise it, read it, or see it listed. A build that lost either property
reddens here.

Every value here is synthetic. No source is opened and no path is reached.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

import pytest
from sqlalchemy import text
from tests.capture.conftest import CAPTURE_PURPOSE, WHEN, empty, invoke, succeeded

from my_pa.application.commands import (
    Command,
    CreateCapture,
    ListCaptures,
    ReadCapture,
    ReviseCapture,
)
from my_pa.bootstrap.gateway import GatewayRuntime, build_gateway_runtime
from my_pa.bootstrap.settings import Settings
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind

FIRST: Final = "written by the process that created the capture"
SECOND: Final = "revised by a process that never wrote the first version"

#: A synthetic principal that never wrote anything. Authenticated and an
#: operator, so every refusal below is scope and never capability — a
#: `GATEWAY` kind here would redden on capability and prove nothing about
#: ownership.
STRANGER: Final = Principal(
    principal_id="prn_bbbb0002bbbbbbbbbbbbbbbb00000002",
    kind=PrincipalKind.OPERATOR,
    authenticated=True,
)


@pytest.fixture
def two_runtimes(capture_database: str) -> Iterator[tuple[GatewayRuntime, GatewayRuntime]]:
    """Two compositions over one database, which is what a restart is.

    Composed the same way `apps/gateway.py` composes one. Under `D-67` this was
    two principals; under the durable binding it is one principal twice, which
    is the whole difference this module measures.
    """
    first = build_gateway_runtime(Settings(database_url=capture_database))
    second = build_gateway_runtime(Settings(database_url=capture_database))
    try:
        empty(first.work_engine)
        yield first, second
    finally:
        first.close()
        second.close()


def invoke_as(
    runtime: GatewayRuntime,
    principal: Principal,
    capability: Capability,
    request: Command,
    tag: str,
) -> ResponseEnvelope:
    """One request through the real application, under a caller-chosen principal.

    `tests/capture/conftest.py`'s `invoke` always acts as the runtime's own
    principal; the isolation half of this module needs the same request under a
    different one, which is what a second authenticated session would present.
    """
    return runtime.service.invoke(
        RequestMetadata(
            request_id=f"req-capture-{tag}",
            capability=capability,
            purpose=CAPTURE_PURPOSE[capability],
            principal_id=principal.principal_id,
            requested_at=WHEN,
        ),
        request,
        principal=principal,
    )


def refused_not_found(envelope: ResponseEnvelope, what: str) -> None:
    """The envelope refused with `not_found`, and nothing else.

    `not_found` rather than `forbidden`, deliberately: a `forbidden` would
    confirm to the stranger that the identifier exists, which is itself a
    disclosure about another principal's data.
    """
    assert envelope.error is not None, (
        f"{what} succeeded for a principal that does not own the capture, so the "
        "partition is not being applied on this path"
    )
    assert envelope.error.code == "not_found", (
        f"{what} refused with {envelope.error.code!r} rather than `not_found`. A "
        "distinguishable refusal confirms the identifier exists, which is a "
        "disclosure about another principal's captures"
    )


@pytest.mark.database
def test_a_capture_created_by_one_runtime_is_revised_and_read_by_another(
    two_runtimes: tuple[GatewayRuntime, GatewayRuntime],
) -> None:
    """The restart story, still green — because two compositions are one principal.

    The precondition is asserted first and is not decoration: if the two
    compositions minted different principals, the successes below would be
    proving the absence of an owner check rather than the durability of the
    binding, and the isolation test beside this one would be unprovable.
    """
    author, reviser = two_runtimes
    assert author.principal.principal_id == reviser.principal.principal_id, (
        "two compositions minted two principals, so the durable local-operator "
        "binding is not in force and every stored capture is stranded behind a "
        "principal that dies with its process"
    )

    created = succeeded(
        invoke(
            author,
            Capability.CAPTURE_CREATE,
            CreateCapture(text=FIRST, idempotency_key="owner-1"),
            "create",
        ),
        "capture.create under the first runtime",
    )
    capture_id = created["capture_id"]

    # --- the second composition revises a capture the first one wrote -----------
    revised = succeeded(
        invoke(
            reviser,
            Capability.CAPTURE_REVISE,
            ReviseCapture(capture_id=capture_id, text=SECOND, idempotency_key="owner-2"),
            "revise",
        ),
        "capture.revise under the second runtime",
    )
    assert revised["capture_id"] == capture_id
    assert revised["version_number"] == 2, (
        "the revise under a second composition did not append a version, so "
        "`QC-AC-013` is unprovable across a restart and the durable binding "
        "bought nothing"
    )

    # --- and reads both versions, including the one it did not write ------------
    original = succeeded(
        invoke(
            reviser,
            Capability.CAPTURE_READ,
            ReadCapture(capture_id=capture_id, version_id=created["version_id"]),
            "read-first",
        ),
        "capture.read of the first runtime's version",
    )
    assert original["text"] == FIRST
    assert original["owner_principal_id"] == author.principal.principal_id

    current = succeeded(
        invoke(
            reviser, Capability.CAPTURE_READ, ReadCapture(capture_id=capture_id), "read-current"
        ),
        "capture.read of the current version",
    )
    assert current["text"] == SECOND
    assert current["owner_principal_id"] == reviser.principal.principal_id

    # --- the stored owners, out of the table ------------------------------------
    with author.work_engine.connect() as connection:
        owners = [
            str(row[0])
            for row in connection.execute(
                text(
                    "SELECT owner_principal_id FROM knowledge.capture_versions "
                    "WHERE capture_id = :id ORDER BY version_number"
                ),
                {"id": capture_id},
            )
        ]
    assert owners == [author.principal.principal_id, reviser.principal.principal_id], (
        f"the stored owners are {owners}. `ADR-003` clause 6 requires every "
        "version to bind the principal that wrote it"
    )
    assert len(set(owners)) == 1, (
        "the two versions record two owners, so the durable binding is not what "
        "wrote them and the successes above prove the wrong thing"
    )

    # And the listing under the second composition sees the capture, because it
    # is the same principal's partition.
    listed = succeeded(
        invoke(reviser, Capability.CAPTURE_LIST, ListCaptures(), "list"), "capture.list"
    )["captures"]
    assert [entry["capture_id"] for entry in listed] == [capture_id]
    assert listed[0]["version_count"] == 2
    assert listed[0]["owner_principal_id"] == author.principal.principal_id


@pytest.mark.database
def test_a_principal_that_did_not_write_a_capture_cannot_reach_it(
    two_runtimes: tuple[GatewayRuntime, GatewayRuntime],
) -> None:
    """The isolation half: a stranger's revise, read, and list find nothing.

    The stranger is authenticated and an operator, so every refusal here is the
    partition and never a capability denial — the control right beside each
    refusal is the owner performing the same operation and succeeding.
    """
    author, _ = two_runtimes
    assert STRANGER.principal_id != author.principal.principal_id

    created = succeeded(
        invoke(
            author,
            Capability.CAPTURE_CREATE,
            CreateCapture(text=FIRST, idempotency_key="isolation-1"),
            "create",
        ),
        "capture.create under the owner",
    )
    capture_id = created["capture_id"]

    refused_not_found(
        invoke_as(
            author,
            STRANGER,
            Capability.CAPTURE_REVISE,
            ReviseCapture(capture_id=capture_id, text=SECOND, idempotency_key="isolation-2"),
            "stranger-revise",
        ),
        "capture.revise by a principal that did not write the capture",
    )
    refused_not_found(
        invoke_as(
            author,
            STRANGER,
            Capability.CAPTURE_READ,
            ReadCapture(capture_id=capture_id),
            "stranger-read",
        ),
        "capture.read by a principal that did not write the capture",
    )
    listed = succeeded(
        invoke_as(author, STRANGER, Capability.CAPTURE_LIST, ListCaptures(), "stranger-list"),
        "capture.list under the stranger",
    )["captures"]
    assert listed == [], (
        f"the stranger's listing carries {len(listed)} captures it never wrote, so "
        "the listing path is not partitioned"
    )

    # The controls: the owner still reaches everything the stranger could not.
    owner_read = succeeded(
        invoke(author, Capability.CAPTURE_READ, ReadCapture(capture_id=capture_id), "owner-read"),
        "capture.read by the owner",
    )
    assert owner_read["text"] == FIRST
    owner_listed = succeeded(
        invoke(author, Capability.CAPTURE_LIST, ListCaptures(), "owner-list"), "capture.list"
    )["captures"]
    assert [entry["capture_id"] for entry in owner_listed] == [capture_id], (
        "the owner's own listing is empty, so the refusals above are a broken "
        "plane rather than a partition"
    )
