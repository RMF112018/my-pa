"""GoodNotes draft/composition/publication/grant boundaries, without I/O."""

from __future__ import annotations

from my_pa.bootstrap.goodnotes_durable_note import ALLOWED_CAPABILITIES, capability_states
from my_pa.bootstrap.settings import Settings
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose

DSN = "postgresql+psycopg://my_pa@localhost:5433/my_pa_capability_state_probe"
GOODNOTES_NAMES = frozenset(capability.value for capability in ALLOWED_CAPABILITIES)


def _settings(*, composed: bool) -> Settings:
    return Settings(
        database_url=DSN,
        goodnotes_durable_note_intelligence_enabled=composed,
    )


def test_source_definition_does_not_imply_composition_or_publication() -> None:
    states = capability_states(
        _settings(composed=False),
        runtime_published=GOODNOTES_NAMES,
        allowed_tools=GOODNOTES_NAMES,
        grants=frozenset({(capability, None) for capability in ALLOWED_CAPABILITIES}),
    )

    assert states.source_defined == ALLOWED_CAPABILITIES
    assert states.composed == frozenset()
    assert states.runtime_published == frozenset()
    assert states.grant_visible == frozenset()


def test_composition_publication_and_grant_visibility_are_distinct() -> None:
    runtime_published = frozenset(
        {
            Capability.GOODNOTES_WORK.value,
            Capability.GOODNOTES_CONTENT.value,
            Capability.SOURCES_ENROLL.value,
        }
    )
    states = capability_states(
        _settings(composed=True),
        runtime_published=runtime_published,
        allowed_tools=frozenset(
            {
                Capability.GOODNOTES_CONTENT.value,
                Capability.SOURCES_ENROLL.value,
            }
        ),
        grants=frozenset(
            {
                (Capability.GOODNOTES_CONTENT, Purpose.GOODNOTES_CONTENT),
                (Capability.SOURCES_ENROLL, None),
            }
        ),
    )

    assert states.source_defined == ALLOWED_CAPABILITIES
    assert states.composed == ALLOWED_CAPABILITIES
    assert states.runtime_published == frozenset(
        {Capability.GOODNOTES_WORK, Capability.GOODNOTES_CONTENT}
    )
    assert states.grant_visible == frozenset({Capability.GOODNOTES_CONTENT})
    assert Capability.SOURCES_ENROLL not in states.source_defined
    assert Capability.SOURCES_ENROLL not in states.grant_visible


def test_wrong_purpose_and_name_only_grants_fail_closed() -> None:
    wrong_purpose = capability_states(
        _settings(composed=True),
        runtime_published=GOODNOTES_NAMES,
        allowed_tools=GOODNOTES_NAMES,
        grants=frozenset(
            {
                (Capability.GOODNOTES_WORK, Purpose.GOODNOTES_CONTENT),
                (Capability.GOODNOTES_CONTENT, Purpose.GOODNOTES_WORK),
            }
        ),
    )
    name_only = capability_states(
        _settings(composed=True),
        runtime_published=GOODNOTES_NAMES,
        allowed_tools=GOODNOTES_NAMES,
        grants=frozenset(),
    )

    assert wrong_purpose.grant_visible == frozenset()
    assert name_only.grant_visible == frozenset()
