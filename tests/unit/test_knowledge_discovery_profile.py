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
  `chatllm-data-v8` (KLP-WP-05; v7 at KLP-WP-04) and classifies submit/checkpoint
  `CONTROL_PLANE_EXCLUDED`. KLP-WP-05: discovery clients are bound to
  `knowledge-discovery-v2` = v1 + `record_events.provenance`, exactly the
  matrix set, and never create, `review.decide`, list, search, history or
  reveal; an unbound client never submit or checkpoint (v1 stays defined as
  history).
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
    KNOWLEDGE_DISCOVERY_V2,
    KNOWLEDGE_MANAGER_V1,
    KNOWLEDGE_OPERATOR_REVIEW_V1,
    KnowledgeAllowlists,
    KnowledgeClientRole,
    is_knowledge_manager,
    knowledge_client_role,
    profile_for_role,
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
#: KLP Step 8: a Knowledge Manager is also a ChatLLM gateway client (allowed overlap).
MANAGER: Final = "synthetic-manager"
SUBMIT: Final = Capability.KNOWLEDGE_ASSERTIONS_SUBMIT
CHECKPOINT: Final = Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT
SETTINGS: Final = SimpleNamespace(
    knowledge_discovery_oauth_client_id_set=lambda: frozenset({DISCOVERY}),
    knowledge_operator_review_oauth_client_id_set=lambda: frozenset({REVIEW}),
    chatllm_gateway_oauth_client_id_set=lambda: frozenset({CHAT, MANAGER}),
    knowledge_manager_oauth_client_id_set=lambda: frozenset({MANAGER}),
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
        Capability.RECORD_EVENTS_PROVENANCE,
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
    assert {
        name: frozenset(Capability(member) for member in members)
        for name, members in contract["discovery_profiles"].items()
    } == dict(DISCOVERY_PROFILES)


def test_discovery_v2_is_not_representable_until_its_capability_exists() -> None:
    """WP-04 DEV-02 closed by KLP-WP-05: v2's capability exists, so v2 is bound.

    The node id is kept from KLP-WP-04 (KLP-AC-080). At the WP-04 head v2 named
    the one undeclared capability `record_events.provenance`; KLP-WP-05 declares
    it, so every v2 member is a Capability, v2 is in the table and every
    discovery client is bound to it.
    """
    v2 = MATRIX["profile_contract"]["discovery_profiles"][KNOWLEDGE_DISCOVERY_V2]
    missing = {member for member in v2 if member not in {c.value for c in Capability}}
    assert missing == set()
    assert "record_events.provenance" in v2
    assert KNOWLEDGE_DISCOVERY_V2 in DISCOVERY_PROFILES
    assert DISCOVERY_PROFILE == KNOWLEDGE_DISCOVERY_V2


def test_matrix_discovery_membership_agrees_with_the_profile_table() -> None:
    for name in (KNOWLEDGE_DISCOVERY_V1, KNOWLEDGE_DISCOVERY_V2):
        named = {
            Capability(row["name"])
            for row in MATRIX["capabilities"]
            if name in row["discovery_profile"]
        }
        # Every matrix row naming the profile is in it; v1/v2 also carry the
        # pre-KLP `record_events.list`, which the KLP capability table omits.
        assert named <= DISCOVERY_PROFILES[name]
        assert DISCOVERY_PROFILES[name] - named == {Capability.RECORD_EVENTS_LIST}


# ---- KLP-AC-106 (KLP-WP-05): knowledge-discovery-v2 ---------------------------------


def test_discovery_v2_is_exactly_v1_plus_provenance() -> None:
    assert DISCOVERY_PROFILES[KNOWLEDGE_DISCOVERY_V2] == frozenset(
        {
            Capability.KNOWLEDGE_ASSERTIONS_SUBMIT,
            Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT,
            Capability.KNOWLEDGE_ASSERTIONS_READ,
            Capability.RECORD_EVENTS_LIST,
            Capability.RECORD_EVENTS_PROVENANCE,
        }
    )
    assert DISCOVERY_PROFILES[KNOWLEDGE_DISCOVERY_V2] - DISCOVERY_PROFILES[
        KNOWLEDGE_DISCOVERY_V1
    ] == {Capability.RECORD_EVENTS_PROVENANCE}
    assert set(DISCOVERY_PROFILES) == {KNOWLEDGE_DISCOVERY_V1, KNOWLEDGE_DISCOVERY_V2}


@pytest.mark.parametrize(
    "never",
    [
        Capability.KNOWLEDGE_ASSERTIONS_CREATE,
        Capability.REVIEW_DECIDE,
        Capability.KNOWLEDGE_ASSERTIONS_LIST,
        Capability.KNOWLEDGE_ASSERTIONS_SEARCH,
        Capability.KNOWLEDGE_ASSERTIONS_HISTORY,
        Capability.KNOWLEDGE_ASSERTIONS_REVEAL,
    ],
    ids=str,
)
def test_no_discovery_profile_ever_names_create_review_decide_or_the_wide_reads(
    never: Capability,
) -> None:
    for profile in DISCOVERY_PROFILES.values():
        assert never not in profile
    granted = frozenset(Capability)
    capabilities, purposes = resolve_knowledge_client_overlay(
        SETTINGS, DISCOVERY, granted, _pairs(granted)
    )
    assert never not in capabilities
    assert not any(capability is never for capability, _ in purposes)


def test_a_fully_granted_discovery_client_holds_exactly_v2() -> None:
    granted = frozenset(Capability)
    capabilities, purposes = resolve_knowledge_client_overlay(
        SETTINGS, DISCOVERY, granted, _pairs(granted)
    )
    assert capabilities == DISCOVERY_PROFILES[KNOWLEDGE_DISCOVERY_V2]
    assert (Capability.RECORD_EVENTS_PROVENANCE, Purpose.RECORD_EVENT_PROVENANCE_READ) in purposes


@pytest.mark.parametrize("client", [CHAT, REVIEW, "synthetic-unbound", None])
def test_no_unbound_or_review_client_ever_holds_submit_or_checkpoint(client: str | None) -> None:
    granted = frozenset(Capability)
    capabilities, purposes = resolve_knowledge_client_overlay(
        SETTINGS, client, granted, _pairs(granted)
    )
    assert not {SUBMIT, CHECKPOINT} & capabilities
    assert not any(capability in {SUBMIT, CHECKPOINT} for capability, _ in purposes)


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


@pytest.mark.parametrize("client", [DISCOVERY, REVIEW, MANAGER, "synthetic-unbound"])
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
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v8"
    assert MATRIX["profile_contract"]["ordinary_chatllm_versions"]["KLP-WP-05"] == (
        CHATLLM_DATA_PROFILE_VERSION
    )
    assert (
        CHATLLM_CAPABILITY_POLICY[Capability.RECORD_EVENTS_PROVENANCE].classification
        is ChatLLMCapabilityClass.DATA_CONDITIONAL
    )
    for capability in (SUBMIT, CHECKPOINT):
        assert (
            CHATLLM_CAPABILITY_POLICY[capability].classification
            is ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED
        )


# ---- KLP Step 8: the Knowledge Manager overlay (additive) ---------------------------

#: A large synthetic broad ChatLLM grant set: Knowledge reads and create, Review,
#: Record Events, context, and the broad data planes a manager must keep.
BROAD: Final = frozenset(
    {
        Capability.KNOWLEDGE_ASSERTIONS_READ,
        Capability.KNOWLEDGE_ASSERTIONS_LIST,
        Capability.KNOWLEDGE_ASSERTIONS_SEARCH,
        Capability.KNOWLEDGE_ASSERTIONS_HISTORY,
        Capability.KNOWLEDGE_ASSERTIONS_REVEAL,
        Capability.KNOWLEDGE_ASSERTIONS_CREATE,
        Capability.REVIEW_LIST,
        Capability.REVIEW_DECIDE,
        Capability.RECORD_EVENTS_LIST,
        Capability.RECORD_EVENTS_PROVENANCE,
        Capability.CONTEXT_PREPARE,
        Capability.TASKS_READ,
        Capability.TASKS_LIST,
        *(capability for capability in Capability if capability.value.startswith("entities.")),
        *(capability for capability in Capability if capability.value.startswith("constraints.")),
        *(capability for capability in Capability if capability.value.startswith("meetings.")),
        *(capability for capability in Capability if capability.value.startswith("reports.")),
    }
)


def _overlay_of(client: str | None, granted: frozenset[Capability]) -> Overlay:
    return resolve_knowledge_client_overlay(SETTINGS, client, granted, _pairs(granted))


def test_the_manager_overlay_is_named_but_is_not_a_narrowing_profile() -> None:
    assert KNOWLEDGE_MANAGER_V1 == "knowledge-manager-v1"
    assert KNOWLEDGE_MANAGER_V1 not in KNOWLEDGE_CLIENT_PROFILES
    assert KnowledgeClientRole.MANAGER == "manager"
    assert profile_for_role(KnowledgeClientRole.MANAGER) is None


def test_the_broad_set_is_actually_broad() -> None:
    """Guards the fixture: a narrow set would make the manager tests vacuous."""
    assert len(BROAD) > 30
    assert not BROAD & {SUBMIT, CHECKPOINT}
    assert any(capability.value.startswith("entities.") for capability in BROAD)


def test_a_manager_keeps_its_full_broad_grant_set() -> None:
    capabilities, purposes = _overlay_of(MANAGER, BROAD)
    assert capabilities == BROAD
    assert purposes == _pairs(BROAD)


def test_a_manager_gains_submit_and_checkpoint_only_when_granted() -> None:
    granted = BROAD | {SUBMIT, CHECKPOINT}
    capabilities, purposes = _overlay_of(MANAGER, granted)
    assert capabilities == granted
    assert {SUBMIT, CHECKPOINT} <= capabilities
    assert (SUBMIT, Purpose.KNOWLEDGE_ASSERTION_OBSERVATION) in purposes
    assert (CHECKPOINT, Purpose.KNOWLEDGE_ASSERTION_OBSERVATION) in purposes
    assert purposes == _pairs(granted)


@pytest.mark.parametrize("held", [frozenset(), frozenset({SUBMIT}), frozenset({CHECKPOINT})])
def test_a_manager_never_gains_an_ungranted_submit_or_checkpoint(
    held: frozenset[Capability],
) -> None:
    capabilities, purposes = _overlay_of(MANAGER, BROAD | held)
    assert capabilities & {SUBMIT, CHECKPOINT} == held
    assert {capability for capability, _ in purposes} == capabilities


@pytest.mark.parametrize("client", [CHAT, "synthetic-unbound", None])
def test_an_ordinary_client_still_loses_submit_and_checkpoint_from_a_broad_grant(
    client: str | None,
) -> None:
    granted = BROAD | {SUBMIT, CHECKPOINT}
    capabilities, purposes = _overlay_of(client, granted)
    assert capabilities == BROAD
    assert not any(capability in {SUBMIT, CHECKPOINT} for capability, _ in purposes)


def test_discovery_and_operator_review_overlays_are_unchanged_by_a_manager_list() -> None:
    """The narrow overlays are identical whether or not a manager list is configured."""
    without_manager = SimpleNamespace(
        knowledge_discovery_oauth_client_id_set=lambda: frozenset({DISCOVERY}),
        knowledge_operator_review_oauth_client_id_set=lambda: frozenset({REVIEW}),
        chatllm_gateway_oauth_client_id_set=lambda: frozenset({CHAT}),
        knowledge_manager_oauth_client_id_set=frozenset,
    )
    granted = BROAD | {SUBMIT, CHECKPOINT}
    for client in (DISCOVERY, REVIEW):
        assert _overlay_of(client, granted) == resolve_knowledge_client_overlay(
            without_manager, client, granted, _pairs(granted)
        )
    assert _overlay_of(DISCOVERY, granted)[0] == DISCOVERY_PROFILES[DISCOVERY_PROFILE]
    assert (
        _overlay_of(REVIEW, granted)[0] == KNOWLEDGE_CLIENT_PROFILES[KNOWLEDGE_OPERATOR_REVIEW_V1]
    )


def test_manager_membership_is_exact_never_a_prefix() -> None:
    capabilities, _ = _overlay_of(f"{MANAGER}-x", BROAD | {SUBMIT, CHECKPOINT})
    assert not capabilities & {SUBMIT, CHECKPOINT}


def test_role_order_is_narrowest_first_so_a_hand_built_overlap_fails_closed() -> None:
    overlap = KnowledgeAllowlists(
        discovery=frozenset({"both-d"}),
        operator_review=frozenset({"both-r"}),
        chatllm_gateway=frozenset({MANAGER}),
        manager=frozenset({"both-d", "both-r", MANAGER}),
    )
    assert knowledge_client_role(overlap, "both-d") == KnowledgeClientRole.DISCOVERY
    assert knowledge_client_role(overlap, "both-r") == KnowledgeClientRole.OPERATOR_REVIEW
    assert knowledge_client_role(overlap, MANAGER) == KnowledgeClientRole.MANAGER
    assert knowledge_client_role(overlap, None) == KnowledgeClientRole.UNBOUND
    assert is_knowledge_manager(overlap, MANAGER)
    assert not is_knowledge_manager(overlap, "both-d")
    assert not is_knowledge_manager(overlap, None)
