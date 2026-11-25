"""`tests/schema/vocabulary_admissions.py` is complete and each row is its revision's.

The table is the one home of the capability families admitted after the files
workspace revision (SCOPE row B4). These tests keep it honest without a
database: the newest revision that spells `_CAPABILITIES_AT_THIS_REVISION`
admits exactly the `SINCE` revision's set plus the union of the rows, and each
row's names are spelled by the revision it names. A new vocabulary revision
without its row, or a row naming the wrong revision, turns one of them red.

Unmarked: FAST. Reads `migrations/versions/` and `tests/pins.json`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

from tests import pins
from tests.schema.vocabulary_admissions import (
    CAPABILITY_ADMISSIONS,
    PURPOSE_ADMISSIONS,
    SINCE,
    capabilities_admitted_after,
    purposes_admitted_after,
)

MIGRATIONS: Final = Path(__file__).resolve().parents[2] / "migrations" / "versions"
_NAME: Final = "_CAPABILITIES_AT_THIS_REVISION"
_PURPOSE_NAME: Final = "_PURPOSES_AT_THIS_REVISION"


def _revision_file(revision: str) -> Path:
    (path,) = MIGRATIONS.glob(f"*_{revision}_*.py")
    return path


def _spelled(revision: str, name: str = _NAME) -> frozenset[str] | None:
    source = _revision_file(revision).read_text(encoding="utf-8")
    found = re.search(rf"^{name}: Final = \(\n(.*?)^\)\n", source, re.S | re.M)
    return None if found is None else frozenset(re.findall(r"'([^']+)'", found.group(1)))


def test_the_newest_vocabulary_revision_admits_since_plus_the_rows() -> None:
    newest = next(
        revision for revision in reversed(pins.ALEMBIC_CHAIN) if _spelled(revision) is not None
    )
    since = _spelled(SINCE)
    assert since is not None
    rows = frozenset().union(*(names for _revision, names in CAPABILITY_ADMISSIONS.values()))
    assert _spelled(newest) == since | rows, (
        f"{newest} admits capabilities that no row of vocabulary_admissions.py records"
    )
    assert not since & rows


def test_each_row_is_admitted_after_since_by_the_revision_it_names() -> None:
    assert CAPABILITY_ADMISSIONS, "an empty table proves nothing below"
    seen: set[str] = set()
    for family, (revision, names) in CAPABILITY_ADMISSIONS.items():
        assert pins.ALEMBIC_CHAIN.index(revision) > pins.ALEMBIC_CHAIN.index(SINCE), family
        spelled = _spelled(revision)
        assert spelled is not None, f"{revision} spells no {_NAME}"
        assert names <= spelled, family
        assert not names & seen, f"{family} repeats another row's name"
        seen |= names


def test_admitted_after_selects_only_the_later_rows() -> None:
    for revision, names in CAPABILITY_ADMISSIONS.values():
        before = pins.ALEMBIC_CHAIN[pins.ALEMBIC_CHAIN.index(revision) - 1]
        assert names <= capabilities_admitted_after(before)
        assert not names & capabilities_admitted_after(revision)
    assert capabilities_admitted_after(pins.ALEMBIC_HEAD) == frozenset()


# ---- purposes (ruling R17) ----------------------------------------------------------


def test_the_newest_purpose_revision_admits_since_plus_the_purpose_rows() -> None:
    newest = next(
        revision
        for revision in reversed(pins.ALEMBIC_CHAIN)
        if _spelled(revision, _PURPOSE_NAME) is not None
    )
    since = _spelled(SINCE, _PURPOSE_NAME)
    assert since is not None
    rows = frozenset().union(*(names for _revision, names in PURPOSE_ADMISSIONS.values()))
    assert _spelled(newest, _PURPOSE_NAME) == since | rows, (
        f"{newest} admits purposes that no row of vocabulary_admissions.py records"
    )
    assert not since & rows


def test_each_purpose_row_is_admitted_after_since_by_the_revision_it_names() -> None:
    assert PURPOSE_ADMISSIONS, "an empty table proves nothing below"
    seen: set[str] = set()
    for family, (revision, names) in PURPOSE_ADMISSIONS.items():
        assert pins.ALEMBIC_CHAIN.index(revision) > pins.ALEMBIC_CHAIN.index(SINCE), family
        spelled = _spelled(revision, _PURPOSE_NAME)
        assert spelled is not None, f"{revision} spells no {_PURPOSE_NAME}"
        assert names <= spelled, family
        assert not names & seen, f"{family} repeats another row's name"
        seen |= names


def test_purposes_admitted_after_selects_only_the_later_rows() -> None:
    for revision, names in PURPOSE_ADMISSIONS.values():
        before = pins.ALEMBIC_CHAIN[pins.ALEMBIC_CHAIN.index(revision) - 1]
        assert names <= purposes_admitted_after(before)
        assert not names & purposes_admitted_after(revision)
    assert purposes_admitted_after(pins.ALEMBIC_HEAD) == frozenset()
