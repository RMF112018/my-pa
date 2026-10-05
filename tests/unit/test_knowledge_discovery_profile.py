"""Knowledge client profiles and the one deny overlay (KLP-WP-04, R6 section 3.4).

FAST. The profile table, the resolver and the gateway's use of it, without a
database (the real remote-identity store half is
`tests/database/test_knowledge_remote_grants.py`).

* **KLP-AC-019.** One resolver in `bootstrap/knowledge_discovery_profiles.py`
  returns the overlaid `(capabilities, capability_purposes)` pair and
  `apps/gateway.py` passes both on: a bound client is intersected with its exact
  profile for tools *and* grants -- a stray `tasks.read` grant yields no task
  family events -- and submit/checkpoint are removed from every unbound client.
* **KLP-AC-040 (overlay half).** A discovery client never receives `review.decide`
  (nor `knowledge.assertions.create`), whatever its grants say.
* **KLP-AC-106 (repository half).** The ordinary ChatLLM profile is
  `chatllm-data-v7` and classifies submit/checkpoint `CONTROL_PLANE_EXCLUDED`.
* **KLP-AC-134 (FAST half).** The same intersections hold for both outputs even
  with conflicting grant pairs.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Final

import pytest
from apps.gateway import remote_access_context

from my_pa.application.record_events import visible_families
from my_pa.bootstrap.knowledge_discovery_profiles import (
    DISCOVERY_PROFILE,
    DISCOVERY_PROFILES,
    KNOWLEDGE_CLIENT_PROFILES,
    KNOWLEDGE_DISCOVERY_V1,
    KNOWLEDGE_DISCOVERY_V2_DEFERRED,
    KNOWLEDGE_OPERATOR_REVIEW_V1,
    resolve_knowledge_client_overlay,
)
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    ChatLLMCapabilityClass,
)
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.record_events import RecordEventFamily

MATRIX: Final = json.loads(
    (Path(__file__).parents[1] / "architecture" / "klp_implementation_matrix_r6.json").read_text(
        encoding="utf-8"
    )
)
DISCOVERY: Final = "synthetic-discovery"
REVIEW: Final = "synthetic-review"
CHAT: Final = "synthetic-chat"
SUBMIT: Final = Capability.KNOWLEDGE_ASSERTIONS_SUBMIT
CHECKPOINT: Final = Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT
SETTINGS: Final = SimpleNamespace(
    knowledge_discovery_oauth_client_id_set=lambda: frozenset({DISCOVERY}),
    knowledge_operator_review_oauth_client_id_set=lambda: frozenset({REVIEW}),
    chatllm_gateway_oauth_client_id_set=lambda: frozenset({CHAT}),
    compact_publication_for_client=lambda _client: False,
)

#: Every capability one over-granted client could hold: the whole discovery and
#: operator-review vocabulary plus the conflicting names the overlay must strip.
CONFLICTING: Final = frozenset(
    {
        SUBMIT,
        CHECKPOINT,
        Capability.KNOWLEDGE_ASSERTIONS_READ,
        Capability.KNOWLEDGE_ASSERTIONS_LIST,
        Capability.KNOWLEDGE_ASSERTIONS_CREATE,
        Capability.RECORD_EVENTS_LIST,
        Capability.REVIEW_LIST,
        Capability.REVIEW_DECIDE,
        Capability.TASKS_READ,
        Capability.TASKS_LIST,
    }
)


def _pairs(capabilities: frozenset[Capability]) -> frozenset[tuple[Capability, Purpose | None]]:
    """Each capability granted for every permitted purpose, plus a capability-wide row."""
    pairs: set[tuple[Capability, Purpose | None]] = set()
    for capability in capabilities:
        pairs.add((capability, None))
        pairs.update((capability, purpose) for purpose in permitted_purposes(capability))
    return frozenset(pairs)


Overlay = tuple[frozenset[Capability], frozenset[tuple[Capability, Purpose | None]]]


def _overlay(client: str | None) -> Overlay:
    return resolve_knowledge_client_overlay(SETTINGS, client, CONFLICTING, _pairs(CONFLICTING))


def test_the_profiles_are_the_matrix_profiles() -> None:
    contract = MATRIX["profile_contract"]
    assert {
        name: frozenset(Capability(member) for member in members)
        for name, members in contract["operator_review_profiles"].items()
    } == {KNOWLEDGE_OPERATOR_REVIEW_V1: KNOWLEDGE_CLIENT_PROFILES[KNOWLEDGE_OPERATOR_REVIEW_V1]}
    assert DISCOVERY_PROFILES[KNOWLEDGE_DISCOVERY_V1] == frozenset(
        Capability(member) for member in contract["discovery_profiles"][KNOWLEDGE_DISCOVERY_V1]
    )


def test_discovery_v2_is_not_representable_until_its_capability_exists() -> None:
    """DEV: `record_events.provenance` is KLP-WP-05's; this build binds v1."""
    v2 = MATRIX["profile_contract"]["discovery_profiles"][KNOWLEDGE_DISCOVERY_V2_DEFERRED]
    missing = {member for member in v2 if member not in {c.value for c in Capability}}
    assert missing == {"record_events.provenance"}
    assert KNOWLEDGE_DISCOVERY_V2_DEFERRED not in DISCOVERY_PROFILES
    assert DISCOVERY_PROFILE == KNOWLEDGE_DISCOVERY_V1


def test_matrix_discovery_membership_agrees_with_the_profile_table() -> None:
    for row in MATRIX["capabilities"]:
        if KNOWLEDGE_DISCOVERY_V1 not in row["discovery_profile"]:
            continue
        assert Capability(row["name"]) in DISCOVERY_PROFILES[KNOWLEDGE_DISCOVERY_V1]


def test_a_discovery_client_is_intersected_with_its_exact_profile() -> None:
    capabilities, purposes = _overlay(DISCOVERY)
    assert capabilities == DISCOVERY_PROFILES[DISCOVERY_PROFILE]
    assert {capability for capability, _ in purposes} == capabilities


@pytest.mark.parametrize(
    "denied",
    [
        Capability.KNOWLEDGE_ASSERTIONS_CREATE,
        Capability.REVIEW_DECIDE,
        Capability.REVIEW_LIST,
        Capability.TASKS_READ,
        Capability.KNOWLEDGE_ASSERTIONS_LIST,
    ],
    ids=str,
)
def test_a_discovery_client_never_receives_a_conflicting_grant(denied: Capability) -> None:
    capabilities, purposes = _overlay(DISCOVERY)
    assert denied in CONFLICTING
    assert denied not in capabilities
    assert not any(capability is denied for capability, _ in purposes)


def test_an_operator_review_client_is_intersected_with_its_profile() -> None:
    capabilities, purposes = _overlay(REVIEW)
    assert capabilities == KNOWLEDGE_CLIENT_PROFILES[KNOWLEDGE_OPERATOR_REVIEW_V1]
    assert capabilities == {
        Capability.REVIEW_LIST,
        Capability.REVIEW_DECIDE,
        Capability.KNOWLEDGE_ASSERTIONS_READ,
    }
    assert {capability for capability, _ in purposes} == capabilities


@pytest.mark.parametrize("client", [CHAT, "synthetic-unbound", None])
def test_every_unbound_client_loses_submit_and_checkpoint_only(client: str | None) -> None:
    capabilities, purposes = _overlay(client)
    assert capabilities == CONFLICTING - {SUBMIT, CHECKPOINT}
    assert {capability for capability, _ in purposes} == capabilities


def test_membership_is_exact_never_a_prefix() -> None:
    capabilities, _ = _overlay(f"{DISCOVERY}-x")
    assert SUBMIT not in capabilities
    assert Capability.TASKS_READ in capabilities


def test_a_stray_tasks_grant_yields_no_task_family_events_for_a_discovery_client() -> None:
    available = frozenset(Capability)
    _, unbound_purposes = _overlay("synthetic-unbound")
    assert RecordEventFamily.TASK in visible_families(available, unbound_purposes)
    _, purposes = _overlay(DISCOVERY)
    families = visible_families(available, purposes)
    assert RecordEventFamily.TASK not in families
    assert RecordEventFamily.KNOWLEDGE_ASSERTION in families


def _authenticated(client: str) -> SimpleNamespace:
    return SimpleNamespace(
        principal=Principal(
            principal_id="prn_klpwp04overlay01", kind=PrincipalKind.OPERATOR, authenticated=True
        ),
        client_id=client,
        capabilities=CONFLICTING,
        capability_purposes=_pairs(CONFLICTING),
        write_allowed=True,
    )


@pytest.mark.parametrize("client", [DISCOVERY, REVIEW, "synthetic-unbound"])
def test_the_gateway_passes_the_overlaid_pair_on(client: str) -> None:
    """`apps/gateway.py` hands the overlay -- not the raw grants -- to the transport."""
    expected_capabilities, expected_purposes = _overlay(client)
    context = remote_access_context(
        SETTINGS,  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        _authenticated(client),  # type: ignore[arg-type]
    )
    assert context.allowed_capabilities == {c.value for c in expected_capabilities}
    assert context.capability_purposes == expected_purposes
    assert context.authenticated_client_id == client


def test_the_ordinary_chatllm_profile_excludes_submit_and_checkpoint() -> None:
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v7"
    assert MATRIX["profile_contract"]["ordinary_chatllm_versions"]["KLP-WP-04"] == (
        CHATLLM_DATA_PROFILE_VERSION
    )
    for capability in (SUBMIT, CHECKPOINT):
        assert (
            CHATLLM_CAPABILITY_POLICY[capability].classification
            is ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED
        )
