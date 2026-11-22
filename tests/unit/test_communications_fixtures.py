"""The committed communications fixtures are exactly what their builders produce, and synthetic."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.fixtures.communications_evidence import synthetic as s

ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+)")


@pytest.mark.parametrize("name", sorted(s.COMMITTED))
def test_committed_fixture_matches_its_builder(name: str) -> None:
    assert (s.HERE / name).read_bytes() == s.encode(s.COMMITTED[name]())


@pytest.mark.parametrize("path", sorted(s.HERE.glob("*.json")), ids=lambda p: p.name)
def test_fixtures_are_small_and_use_only_invalid_domains(path: Path) -> None:
    data = path.read_bytes()
    assert len(data) < 64 * 1024
    domains = set(ADDRESS.findall(data.decode("utf-8")))
    assert domains <= {"example.invalid"}, domains
