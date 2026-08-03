"""`D-72`, pinned mechanically: the owner is recorded and never authorized on.

`D-67` measured that identity in this build is **process-scoped**: three CLI
invocations mint three principals, one gateway runtime keeps one across three
reads, and a gateway restart mints a new one. The envelope's `principal_id` is
correlation input and nothing authorizes on it, and `apps/cli/invoke.py` refuses
a `--principal` option deliberately. There is no lever a caller can pull to
supply a stable owner.

`ADR-003` clause 6 nonetheless requires every stored version to bind its owning
principal, so the owner is **stored**. `D-72`'s decision is that it is not an
authorization input: `capture.read`, `capture.list` and `capture.revise`
authorize on capability and purpose alone. Under `P00-OD-010`-open, loopback-only,
single-local-principal operation there is exactly one human operator, so
owner-scoped authorization would enforce a distinction the deployment cannot
make — and it would make **`QC-AC-013` unprovable across processes**, because the
predecessor's owner never exists again.

**This module is that decision made mechanical rather than described.** Two
runtimes are composed over one database, which is two principals in the sense
that matters — the same thing a gateway restart does. A capture is created under
the first and revised and read under the second, and the test asserts *both*
that the two `owner_principal_id` values **differ** and that the revise and the
read **succeed**.

It fails the moment someone adds an owner-equality check, which is exactly the
point: that decision then goes back to the operator instead of being made
silently in a patch that looked like a hardening. The consequence — no
owner-scoped access control on captures — is disclosed in
`docs/operations/mcv-limitations.md`, worded as blocking on multi-principal
operation, with `P00-OD-010`'s resolution as its invalidation trigger.

Every value here is synthetic. No source is opened and no path is reached.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

import pytest
from sqlalchemy import text
from tests.capture.conftest import empty, invoke, succeeded

from my_pa.application.commands import CreateCapture, ListCaptures, ReadCapture, ReviseCapture
from my_pa.bootstrap.gateway import GatewayRuntime, build_gateway_runtime
from my_pa.bootstrap.settings import Settings
from my_pa.domain.identity.operation import Capability

FIRST: Final = "written by the process that created the capture"
SECOND: Final = "revised by a process that never wrote the first version"


@pytest.fixture
def two_runtimes(capture_database: str) -> Iterator[tuple[GatewayRuntime, GatewayRuntime]]:
    """Two compositions over one database, which is two principals.

    Composed the same way `apps/gateway.py` composes one. A second composition
    is what a restart is, so this is the situation `D-67` measured rather than a
    situation invented to produce two identifiers.
    """
    first = build_gateway_runtime(Settings(database_url=capture_database))
    second = build_gateway_runtime(Settings(database_url=capture_database))
    try:
        empty(first.work_engine)
        yield first, second
    finally:
        first.close()
        second.close()


@pytest.mark.database
def test_a_capture_created_by_one_runtime_is_revised_and_read_by_another(
    two_runtimes: tuple[GatewayRuntime, GatewayRuntime],
) -> None:
    """The two owners differ, and the second runtime's revise and read succeed.

    The precondition is asserted first and is not decoration: if the two
    compositions minted the same principal, everything below would pass on a
    build that *did* authorize on owner equality, and the test would prove the
    opposite of what it claims.
    """
    author, reviser = two_runtimes
    assert author.principal.principal_id != reviser.principal.principal_id, (
        "the two compositions share a principal, so this test cannot distinguish "
        "a build that authorizes on owner equality from one that does not"
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

    # --- the second runtime revises a capture it did not write ------------------
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
        "the revise under a second principal did not append a version. An "
        "owner-equality check here would make `QC-AC-013` unprovable across two "
        "processes, because the predecessor's owner never exists again"
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
        "version to bind the principal that wrote it, and each version binds the "
        "one that actually did"
    )
    assert len(set(owners)) == 2, "the two versions record one owner, so nothing was distinguished"

    # And the listing, which is the other read path, is not owner-scoped either:
    # the second runtime sees the capture the first one created.
    listed = succeeded(
        invoke(reviser, Capability.CAPTURE_LIST, ListCaptures(), "list"), "capture.list"
    )["captures"]
    assert [entry["capture_id"] for entry in listed] == [capture_id]
    assert listed[0]["version_count"] == 2
    assert listed[0]["owner_principal_id"] == author.principal.principal_id, (
        "the listing reports the capture's owner as whoever asked, so the stored "
        "owner is not being read back at all"
    )
