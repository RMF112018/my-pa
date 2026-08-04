"""The fixture personal-source adapter is replayable, contained, and read-only."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.relationship.provider import PersonalSourceBatch, PersonalSourceProvider
from my_pa.domain.source.provider import ProviderError
from my_pa.infrastructure.providers.fixture import FixtureSourceProvider
from my_pa.infrastructure.providers.personal_fixture import FixturePersonalSourceProvider


def _write_fixture(root: Path, name: str = "contact.json") -> None:
    (root / name).write_text(
        json.dumps(
            {
                "domain": "contacts",
                "observed_at": "2026-08-04T12:00:00Z",
                "display_name": "Synthetic Person",
            }
        ),
        encoding="utf-8",
    )


def test_fresh_adapter_instances_replay_the_same_observation_identity(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    source = FixtureSourceProvider(tmp_path, make_identifier(IdKind.SOURCE, "0000000000000001"))
    first = FixturePersonalSourceProvider(source).observations()
    second = FixturePersonalSourceProvider(source).observations()
    first_ids = tuple(row.observation_id for batch in first for row in batch.observations)
    second_ids = tuple(row.observation_id for batch in second for row in batch.observations)
    assert first_ids
    assert first_ids == second_ids


def test_changed_source_version_gets_a_new_observation_identity(tmp_path: Path) -> None:
    _write_fixture(tmp_path)
    source = FixtureSourceProvider(tmp_path, make_identifier(IdKind.SOURCE, "0000000000000004"))
    adapter = FixturePersonalSourceProvider(source)
    first = tuple(
        row.observation_id for batch in adapter.observations() for row in batch.observations
    )
    payload = json.loads((tmp_path / "contact.json").read_text(encoding="utf-8"))
    payload["display_name"] = "Changed Synthetic Person"
    (tmp_path / "contact.json").write_text(json.dumps(payload), encoding="utf-8")
    second = tuple(
        row.observation_id for batch in adapter.observations() for row in batch.observations
    )
    assert first and second
    assert first != second


@pytest.mark.parametrize(
    "payload",
    [
        {"domain": "contacts", "state": "stale", "observed_at": "2026-08-04T12:00:00Z"},
        {
            "domain": "contacts",
            "observed_at": "2026-08-04T12:00:00Z",
            "display_name": 42,
        },
    ],
)
def test_fixture_refuses_unsupported_state_and_non_string_name(
    tmp_path: Path, payload: dict[str, object]
) -> None:
    (tmp_path / "row.json").write_text(json.dumps(payload), encoding="utf-8")
    source = FixtureSourceProvider(tmp_path, make_identifier(IdKind.SOURCE, "0000000000000005"))
    with pytest.raises(ProviderError):
        FixturePersonalSourceProvider(source).observations()


def test_personal_source_batch_enforces_processed_and_unavailable_shapes() -> None:
    with pytest.raises(ValueError, match="contains observations"):
        PersonalSourceBatch(domain="contacts", state=CoverageState.PROCESSED, observations=())
    with pytest.raises(ValueError, match="contains no rows"):
        PersonalSourceBatch(
            domain="contacts",
            state=CoverageState.UNAVAILABLE,
            observations=(),
            limitation=None,
        )
    with pytest.raises(ValueError, match="processed or unavailable"):
        PersonalSourceBatch(domain="contacts", state=CoverageState.STALE, observations=())


def test_personal_source_port_and_adapter_expose_no_mutation_method() -> None:
    forbidden = {"write", "update", "delete", "move", "rename", "merge"}
    assert not forbidden & set(PersonalSourceProvider.__dict__)
    assert not forbidden & set(FixturePersonalSourceProvider.__dict__)
    assert "observations" in PersonalSourceProvider.__dict__


def test_escaping_symlink_fixture_is_not_observed(tmp_path: Path) -> None:
    outside = tmp_path.parent / "synthetic-personal-outside.json"
    outside.write_text("{}", encoding="utf-8")
    (tmp_path / "escape.json").symlink_to(outside)
    source = FixtureSourceProvider(tmp_path, make_identifier(IdKind.SOURCE, "0000000000000002"))
    assert not [
        row
        for batch in FixturePersonalSourceProvider(source).observations()
        for row in batch.observations
    ]


def test_hard_link_fixture_is_not_observed(tmp_path: Path) -> None:
    outside = tmp_path.parent / "synthetic-personal-hardlink.json"
    _write_fixture(tmp_path, "inside.json")
    outside.write_text((tmp_path / "inside.json").read_text(encoding="utf-8"), encoding="utf-8")
    hardlink = tmp_path / "hardlink.json"
    os.link(outside, hardlink)
    source = FixtureSourceProvider(tmp_path, make_identifier(IdKind.SOURCE, "0000000000000003"))
    batches = FixturePersonalSourceProvider(source).observations()
    assert sum(len(batch.observations) for batch in batches) == 1


def test_parent_traversal_is_not_an_adapter_operation() -> None:
    # The structured port takes no locator at all; the WP-2 boundary remains the
    # only component that can resolve a fixture path.
    parameters = PersonalSourceProvider.observations.__annotations__
    assert set(parameters) == {"return"}
