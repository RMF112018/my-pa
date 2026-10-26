"""Part D: the lineage plane in the catalog and the compact facade (S3.1 contract 7.13).

FAST. Worker N1's half of section 7.13 -- the kinds, the catalog entries and the
annotations -- and the client-bound remote key of section 4.9:

* every S1-S4 lineage-plane capability and every S3.1 one (41 names) has a
  `TOOLS` entry with a summary and a feature other than `other`;
* each name's facade kind is the section 7.13 table's, kind by kind: the 14
  open writes stay `write`, Issue close and reopen and the 3 confirms are
  `operator` (D-16), the backfill pair stays `operator`, every read is `read`;
* every lineage write tool is annotated idempotent, and no other tool's
  annotations move (D-17);
* the attested lineage writes are never published to a remote client;
* the derived remote key of the 14 open writes binds the OAuth client, and no
  other capability's derivation changes.

The facade end-to-end rows of section 7.13 are worker N3's
(`tests/integration/test_lineage_s31_compact_facade.py`). Every value is
synthetic.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Final

from tests.conftest import Scene, build_service

from my_pa.adapters.mcp.chatllm_gateway import facade_kind, facade_tool_names, feature_label
from my_pa.adapters.mcp.remote import remote_tool_names
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.remote_request import (
    _CLIENT_BOUND_KEY_CAPABILITIES,
    _IDEMPOTENT_REMOTE_CAPABILITIES,
    compose_remote_arguments,
    is_remote_idempotent,
    is_server_replay_capability,
)
from my_pa.application.service import _LINEAGE_CAPABILITIES
from my_pa.domain.identity.operation import Capability, is_operator_only
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.lineage.vocabulary import (
    ATTESTED_LINEAGE_WRITE_CAPABILITIES,
    LINEAGE_BACKFILL_CAPABILITIES,
    LINEAGE_WRITE_CAPABILITIES,
    OPEN_LINEAGE_WRITE_CAPABILITIES,
)
from my_pa.domain.program.vocabulary import PROGRAM_REPORTING_CAPABILITIES

#: Section 7.13's capability table: `name -> (feature, new kind)`.
_TABLE: Final[dict[str, tuple[str, str]]] = {
    "issues.create": ("lineage", "write"),
    "issues.update": ("lineage", "write"),
    "issues.read": ("lineage", "read"),
    "issues.list": ("lineage", "read"),
    "issues.history": ("lineage", "read"),
    "issues.timeline": ("lineage", "read"),
    "issues.closure_readiness": ("lineage", "read"),
    "issues.close": ("lineage", "operator"),
    "issues.reopen": ("lineage", "operator"),
    "issues.project_links.add": ("lineage", "write"),
    "issues.project_links.end": ("lineage", "write"),
    "issues.project_links.confirm": ("lineage", "operator"),
    "issues.memberships.add": ("lineage", "write"),
    "issues.memberships.end": ("lineage", "write"),
    "issues.memberships.correct": ("lineage", "write"),
    "issues.memberships.confirm": ("lineage", "operator"),
    "issues.handoffs.record": ("lineage", "write"),
    "issues.handoffs.correct": ("lineage", "write"),
    "issues.handoffs.list": ("lineage", "read"),
    "issues.work.create_task": ("lineage", "write"),
    "issues.work.create_commitment": ("lineage", "write"),
    "records.associations.assert": ("lineage", "write"),
    "records.associations.correct": ("lineage", "write"),
    "records.associations.end": ("lineage", "write"),
    "records.associations.contest": ("lineage", "write"),
    "records.associations.reinstate": ("lineage", "write"),
    "records.associations.confirm": ("lineage", "operator"),
    "records.associations.history": ("lineage", "read"),
    "records.lineage": ("lineage", "read"),
    "records.lineage.related": ("lineage", "read"),
    "records.backfill.plan": ("lineage", "operator"),
    "records.backfill.report": ("lineage", "operator"),
    "meetings.notes.versions": ("meetings", "read"),
    "meetings.notes.read_version": ("meetings", "read"),
    "programs.members.resolve": ("programs", "read"),
    "programs.overview": ("programs", "read"),
    "commitments.v2.read": ("work", "read"),
    "commitments.v2.list": ("work", "read"),
    "commitments.v2.search": ("work", "read"),
    "commitments.v2.waiting_on": ("work", "read"),
    "reports.manifest": ("reports", "read"),
}
#: The non-lineage tools' annotations, `(name, readOnly, destructive, idempotent,
#: openWorld)` sorted, canonical JSON -- measured at the S4 basis `9bfd7d47`.
_NON_LINEAGE_ANNOTATIONS_SHA256: Final = (
    "8e4bc723e750445610a53945f7a4fd5fb746a08106acaa486518ec22c961bba9"
)
_PRINCIPAL: Final = Principal(
    principal_id="prn_lineages31parta001", kind=PrincipalKind.OPERATOR, authenticated=True
)
_FROZEN: Final = datetime(2026, 10, 25, 12, tzinfo=UTC)


def _lineage_plane() -> frozenset[str]:
    return frozenset(c.value for c in _LINEAGE_CAPABILITIES) | PROGRAM_REPORTING_CAPABILITIES


def _tools() -> dict[str, Any]:
    return {tool.name: tool for tool in TOOLS}


def test_every_lineage_capability_has_a_catalog_entry() -> None:
    plane = _lineage_plane()
    assert plane == frozenset(_TABLE)
    assert len(plane) == 41
    tools = _tools()
    for name in sorted(plane):
        assert name in tools, name
        assert tools[name].description, f"{name} has no catalog summary"
        assert feature_label(name) != "other", name
        assert feature_label(name) == _TABLE[name][0], name


def test_lineage_facade_kinds_are_deliberate() -> None:
    for name, (_feature, kind) in sorted(_TABLE.items()):
        capability = Capability(name)
        assert facade_kind(capability) == kind, name
        assert is_operator_only(capability) is (kind == "operator"), name
    # The sets the table is made of: the open writes `write`, the attested ones
    # and the backfill pair `operator`.
    for name in OPEN_LINEAGE_WRITE_CAPABILITIES:
        assert facade_kind(Capability(name)) == "write", name
    for name in ATTESTED_LINEAGE_WRITE_CAPABILITIES | LINEAGE_BACKFILL_CAPABILITIES:
        assert facade_kind(Capability(name)) == "operator", name
    # `issues.update` stays `write`: only its closed-Issue correction is attested.
    assert facade_kind(Capability.ISSUES_UPDATE) == "write"
    # The facade publishes `my_pa.operator` only for an eligible operator name.
    assert facade_tool_names(frozenset({"issues.close"})) == {"my_pa.describe", "my_pa.operator"}
    assert facade_tool_names(frozenset({"records.associations.assert"})) == {
        "my_pa.describe",
        "my_pa.write",
    }


def test_lineage_write_tools_are_annotated_idempotent() -> None:
    tools = _tools()
    assert len(LINEAGE_WRITE_CAPABILITIES) == 22
    for name in sorted(_lineage_plane()):
        annotations = tools[name].annotations
        writes = name in LINEAGE_WRITE_CAPABILITIES
        assert annotations.idempotent_hint is writes, name
        assert is_remote_idempotent(Capability(name)) is writes, name


def _annotation_rows(names: frozenset[str]) -> list[list[object]]:
    tools = _tools()
    return sorted(
        [
            name,
            tools[name].annotations.read_only_hint,
            tools[name].annotations.destructive_hint,
            tools[name].annotations.idempotent_hint,
            tools[name].annotations.open_world_hint,
        ]
        for name in names
    )


def test_non_lineage_tool_annotations_are_unchanged() -> None:
    plane = _lineage_plane()
    others = frozenset(_tools()) - plane
    assert len(others) == 192
    for name in sorted(others):
        capability = Capability(name)
        # D-17: the hint is the server-replay registry's alone outside lineage.
        assert _tools()[name].annotations.idempotent_hint is is_server_replay_capability(
            capability
        ), name
    # Non-vacuous: keyed non-lineage writes exist, and none is annotated idempotent.
    keyed = {c.value for c in _IDEMPOTENT_REMOTE_CAPABILITIES} - plane
    assert keyed
    assert not any(_tools()[name].annotations.idempotent_hint for name in keyed)
    rows = _annotation_rows(others)
    digest = hashlib.sha256(
        json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert digest == _NON_LINEAGE_ANNOTATIONS_SHA256


def test_attested_lineage_writes_are_never_published_remotely(scene: Scene) -> None:
    service = build_service(
        scene.world, scene.providers, lineage_enabled=True, lineage_backfill_enabled=True
    )
    never = ATTESTED_LINEAGE_WRITE_CAPABILITIES | LINEAGE_BACKFILL_CAPABILITIES
    for compact in (False, True):
        published = remote_tool_names(
            service, writes_enabled=True, compact_operator_publication=compact
        )
        assert not published & never, sorted(published & never)
        # The open writes are published while remote writes are on.
        assert published >= OPEN_LINEAGE_WRITE_CAPABILITIES
        assert published >= {"records.lineage.related", "issues.update"}
    # Remote writes off: no lineage write at all, the reads still.
    reads_only = remote_tool_names(service, writes_enabled=False)
    assert not reads_only & LINEAGE_WRITE_CAPABILITIES
    assert "records.lineage.related" in reads_only


def _key(capability: Capability, client: str | None, payload: dict[str, object]) -> str:
    composed = compose_remote_arguments(
        capability_name=capability.value,
        arguments={"payload": payload},
        principal=_PRINCIPAL,
        grants=None,
        clock=lambda: _FROZEN,
        authenticated_client_id=client,
    )
    return str(composed["payload"]["idempotency_key"])


def test_the_remote_key_binds_the_client_for_open_writes_only() -> None:
    assert {c.value for c in _CLIENT_BOUND_KEY_CAPABILITIES} == OPEN_LINEAGE_WRITE_CAPABILITIES
    end = {
        "link_id": "irl_lineages31parta01",
        "expected_revision": 1,
        "reason": "Ended.",
    }
    first = _key(Capability.RECORDS_ASSOCIATIONS_END, "client-a", end)
    # A client's own retry derives its own key again (and so replays) ...
    assert _key(Capability.RECORDS_ASSOCIATIONS_END, "client-a", end) == first
    # ... while another client sending the same payload derives another key.
    assert _key(Capability.RECORDS_ASSOCIATIONS_END, "client-b", end) != first
    # The key is the section 4.9 document's digest, the client in it.
    digest = hashlib.sha256(
        json.dumps(
            {
                "capability": "records.associations.end",
                "principal_id": _PRINCIPAL.principal_id,
                "payload": end,
                "client": "client-a",
            },
            sort_keys=True,
            default=str,
        ).encode()
    ).hexdigest()
    assert first == f"idk_{digest[:32]}"
    # Every other keyed capability's derivation is unchanged and client-blind.
    issue = {"title": "Synthetic", "description": None}
    for capability, payload in (
        (Capability.ISSUES_CREATE, issue),
        (Capability.ISSUES_CLOSE, {"issue_id": "sit_lineages31parta01"}),
        (Capability.RECORDS_ASSOCIATIONS_CONFIRM, {"link_id": "irl_lineages31parta01"}),
    ):
        assert capability in _IDEMPOTENT_REMOTE_CAPABILITIES
        assert capability not in _CLIENT_BOUND_KEY_CAPABILITIES
        blind = _key(capability, "client-a", payload)
        assert _key(capability, "client-b", payload) == blind == _key(capability, None, payload)
        legacy = hashlib.sha256(
            json.dumps(
                {
                    "capability": capability.value,
                    "principal_id": _PRINCIPAL.principal_id,
                    "payload": payload,
                },
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        assert blind == f"idk_{legacy[:32]}"
