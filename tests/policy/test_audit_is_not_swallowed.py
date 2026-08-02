"""A failure to record an audit event is never swallowed by the application.

The durable half of the fail-closed rule is proved in
`tests/schema/test_audit_durability.py`, against a server. This is the other
half, and it is a different claim about a different layer: whatever the sink is,
the application must let its failure out. A sink that raised into a layer which
caught and continued would leave the request succeeding with its audit lost, and
no amount of transaction design in the adapter would fix that.

It runs in the FAST tier because it needs no server — the sink is made to raise
directly — and it covers both call sites, because they sit on different branches
and only one of them is on the authorization path.
"""

from __future__ import annotations

import pytest
from tests.conftest import (
    FakeProviders,
    Scene,
    World,
    build_service,
    metadata_for,
    operator,
)

from my_pa.application.commands import GetCapabilities, ListSources
from my_pa.contracts.ports import EvidenceUnavailableError, PortError, RepositoryFailureError
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (EvidenceUnavailableError("the audit store is unreachable"), "unavailable"),
        (RepositoryFailureError("the audit row was refused"), "internal_error"),
    ],
    ids=["unavailable", "internal_error"],
)
def test_an_allowed_request_fails_closed_when_its_audit_cannot_be_recorded(
    scene: Scene, failure: PortError, expected: str
) -> None:
    """The request must not succeed while its audit is lost.

    The sink refuses, so the decision was reached and its record was not kept.
    The answer is an error, the transaction rolled back, and nothing committed —
    which is `module-boundaries.md` section 5.6 for a request policy allowed.
    """
    scene.world.failures["record"] = failure
    service = build_service(scene.world, scene.providers)

    envelope = service.invoke(
        metadata_for(Capability.SOURCES_LIST, Purpose.SOURCE_INSPECTION, scene.principal),
        ListSources(source_id=scene.source.source_id, parent_object_id=None),
        principal=scene.principal,
    )

    assert envelope.result is None
    assert envelope.error is not None
    assert envelope.error.code.value == expected
    assert scene.world.commits == 0, "the work committed without its audit"
    assert scene.world.rollbacks == 1
    assert scene.world.audit == []
    # And the capability never ran: the refusal precedes the handler.
    assert scene.provider.calls == []


def test_a_capability_mismatch_fails_closed_when_its_audit_cannot_be_recorded(
    scene: Scene,
) -> None:
    """The second call site, which is not on the authorization path.

    A declared capability that disagrees with the payload is refused inside the
    transaction and recorded as `failed`. That branch calls the sink directly
    rather than through `authorize`, so a fix applied to one call site and not
    the other would show up here and nowhere else.
    """
    scene.world.failures["record"] = EvidenceUnavailableError("the audit store is unreachable")
    service = build_service(scene.world, scene.providers)

    envelope = service.invoke(
        metadata_for(Capability.SOURCES_LIST, Purpose.SOURCE_INSPECTION, scene.principal),
        GetCapabilities(),
        principal=scene.principal,
    )

    assert envelope.error is not None
    # `unavailable` rather than the `invalid_request` a recorded mismatch answers
    # with: the audit failure happened first and is what stopped the request.
    assert envelope.error.code.value == "unavailable"
    assert scene.world.commits == 0
    assert scene.world.rollbacks == 1
    assert scene.world.audit == []


def test_a_denial_still_records_and_commits_when_the_sink_works(world: World) -> None:
    """The control. Without it, "nothing was recorded" would be evidence of nothing.

    A principal holding no enrollment is denied, and that denial reaches the sink
    and leaves the transaction normally — which is the behaviour the tests above
    would also produce if the sink had simply stopped being called.
    """
    principal = operator()
    source = world.add_source()
    service = build_service(world, FakeProviders({}))

    envelope = service.invoke(
        metadata_for(Capability.SOURCES_LIST, Purpose.SOURCE_INSPECTION, principal),
        ListSources(source_id=source.source_id, parent_object_id=None),
        principal=principal,
    )

    assert envelope.error is not None
    assert envelope.error.code.value == "denied"
    assert len(world.audit) == 1
    assert world.audit[0].outcome.value == "denied"
    assert world.commits == 1
    assert world.rollbacks == 0
