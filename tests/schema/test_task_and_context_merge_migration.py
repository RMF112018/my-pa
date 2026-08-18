"""Revision `b7c4e9a2d518`: merge task-management and context-prepare heads.

Note: This revision is no longer the head. Current head `9def3c2e63bb` revises
`f4c1a8e6b205`. The test remains to verify the merge revision's structure and
frozen literals; it asserts a single unbranched head and this revision's place
on the chain rather than which revision happens to be last.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from alembic.config import Config
from alembic.script import ScriptDirectory

from my_pa.domain.identity.operation import Capability, NativeSourceCapability
from my_pa.domain.identity.purpose import Purpose

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "b7c4e9a2d518"
PARENTS: Final = ("7504585e3ca5", "c6f1a8d3e204")


def _frozen_literals(constant: str) -> frozenset[str]:
    matches = [
        path for path in (ROOT / "migrations" / "versions").glob("*.py") if REVISION in path.name
    ]
    assert len(matches) == 1
    source = matches[0].read_text(encoding="utf-8")
    start = source.index(f"{constant}: Final = (")
    end = source.index("\n)", start)
    return frozenset(re.findall(r"'([^']+)'", source[start:end]))


def test_the_chain_has_one_head_and_this_revision_is_in_the_chain() -> None:
    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert len(list(script.get_heads())) == 1
    assert REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(REVISION).down_revision == PARENTS
    assert len(list((ROOT / "migrations" / "versions").glob("*.py"))) == 60


def test_the_frozen_literals_are_the_domain_at_head() -> None:
    admitted = _frozen_literals("_CAPABILITIES_AT_THIS_REVISION")
    declared = {member.value for member in Capability} | {
        member.value for member in NativeSourceCapability
    }
    assert admitted <= declared
    purposes = _frozen_literals("_PURPOSES_AT_THIS_REVISION")
    assert purposes <= {member.value for member in Purpose}
    source = next(
        path for path in (ROOT / "migrations" / "versions").glob("*.py") if REVISION in path.name
    ).read_text(encoding="utf-8")
    for constant in (
        "_CAPABILITIES_AT_THIS_REVISION",
        "_CAPABILITIES_BEFORE_THIS_REVISION",
        "_PURPOSES_AT_THIS_REVISION",
        "_PURPOSES_BEFORE_THIS_REVISION",
    ):
        start = source.index(f"{constant}: Final = (")
        end = source.index("\n)", start)
        names = re.findall(r"'([^']+)'", source[start:end])
        assert names == sorted(names), f"{constant} is not in sorted order"


def test_the_revision_reads_no_enum_and_no_tables_module() -> None:
    source = next(
        path for path in (ROOT / "migrations" / "versions").glob("*.py") if REVISION in path.name
    ).read_text(encoding="utf-8")
    assert "my_pa.domain" not in source
    assert "infrastructure.persistence.tables" not in source
    for forbidden in ("Capability", "Purpose"):
        assert f"import {forbidden}" not in source
