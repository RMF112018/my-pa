"""Revision `7c2e9b4a1d80`: continuity authoring names and task acceptance pairing."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from alembic.config import Config
from alembic.script import ScriptDirectory

from my_pa.domain.identity.operation import Capability, NativeSourceCapability
from my_pa.domain.identity.purpose import Purpose

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "7c2e9b4a1d80"
PREVIOUS: Final = "4f6a9c2d8e17"

CAPABILITIES_ADDED: Final[frozenset[str]] = frozenset(
    {
        "continuity.projects.create",
        "continuity.situations.create",
        "continuity.tasks.create",
    }
)
PURPOSES_ADDED: Final[frozenset[str]] = frozenset({"continuity_authoring"})


def _frozen_literals(constant: str) -> frozenset[str]:
    matches = [
        path for path in (ROOT / "migrations" / "versions").glob("*.py") if REVISION in path.name
    ]
    assert len(matches) == 1
    source = matches[0].read_text(encoding="utf-8")
    start = source.index(f"{constant}: Final = (")
    end = source.index("\n)", start)
    return frozenset(re.findall(r"'([^']+)'", source[start:end]))


def test_this_revision_is_in_the_chain() -> None:
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert len(list(script.get_heads())) == 1
    assert REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert len(list((ROOT / "migrations" / "versions").glob("*.py"))) == 50


def test_the_frozen_literals_are_this_revision_s_vocabulary() -> None:
    admitted = _frozen_literals("_CAPABILITIES_AT_THIS_REVISION")
    declared = {member.value for member in Capability} | {
        member.value for member in NativeSourceCapability
    }
    assert admitted <= declared
    purposes = _frozen_literals("_PURPOSES_AT_THIS_REVISION")
    assert purposes <= {member.value for member in Purpose}
    assert admitted - _frozen_literals("_CAPABILITIES_BEFORE_THIS_REVISION") == CAPABILITIES_ADDED
    assert purposes - _frozen_literals("_PURPOSES_BEFORE_THIS_REVISION") == PURPOSES_ADDED


def test_the_revision_reads_no_enum() -> None:
    source = next(
        path for path in (ROOT / "migrations" / "versions").glob("*.py") if REVISION in path.name
    ).read_text(encoding="utf-8")
    assert "my_pa.domain" not in source
    for forbidden in ("Capability", "Purpose"):
        assert f"import {forbidden}" not in source
