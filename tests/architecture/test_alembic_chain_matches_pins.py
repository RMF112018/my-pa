"""The Alembic graph, walked from its base, is exactly the reviewed chain.

Phase P2b of SCOPE "pins and counts" (operator decision O2). Every migration
test used to restate the chain from the head down to its own revision, so one
edge was asserted up to thirty times and every new migration edited dozens of
files. This is the one test that asserts the whole graph: each per-migration
test now keeps only its own edge (`down_revision == PREVIOUS`, hand-written,
fixed once its revision merges), and every edge is still asserted here.

The chain is read from `tests.pins` (the committed `tests/pins.json`), which
`test_pins_are_current[alembic]` keeps equal to the repository; this test adds
the shape that snapshot does not state: one base, one head, each revision's
parents exactly the revision before it, and every revision file on the chain.

The graph is not linear from its base: three historical merges joined branches
that predate the single-head rule. Their parents, and the two branch arms whose
parent is not the revision before them in walk order, are frozen below. They
never change; any new merge, fork or re-parenting fails here.

Unmarked: FAST. Reads `migrations/` and `tests/pins.json`; writes nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from alembic.config import Config
from alembic.script import Script, ScriptDirectory
from tests import pins

#: Revisions whose parents are not `(the revision before it in the chain,)`.
HISTORICAL_PARENTS: Final[dict[str, tuple[str, ...]]] = {
    # Branch arm: its parent sits two places back, beyond the other arm.
    "a7c3e8d1f642": ("9d5e2f7b4c61",),
    # Merge of the two arms above.
    "c8f4a2d9e761": ("a7c3e8d1f642", "6b3d9a2f8c14"),
    # Branch arm off `4f6a9c2d8e17`, beside the task-schema arm.
    "7c2e9b4a1d80": ("4f6a9c2d8e17",),
    # Merge of the continuity-authoring and task arms.
    "7504585e3ca5": ("7c2e9b4a1d80", "a1c9e6f2b834"),
    # Merge of that merge and the context arm.
    "b7c4e9a2d518": ("7504585e3ca5", "c6f1a8d3e204"),
}
#: The revisions with more than one child, and those children: the branch
#: points the merges above close. Frozen for the same reason.
HISTORICAL_FORKS: Final[dict[str, list[str]]] = {
    "4f6a9c2d8e17": ["3d7a2a3e8277", "7c2e9b4a1d80"],
    "7c2e9b4a1d80": ["7504585e3ca5", "8a1c4e7b2d90"],
    "9d5e2f7b4c61": ["a7c3e8d1f642", "c4a7e2d81b53"],
}


def _parents(revision: Script) -> tuple[str, ...]:
    down = revision.down_revision
    if down is None:
        return ()
    return (down,) if isinstance(down, str) else tuple(down)


def test_alembic_chain_is_linear_and_matches_pins() -> None:
    script = ScriptDirectory.from_config(Config(str(pins.ROOT / "alembic.ini")))
    chain = pins.ALEMBIC_CHAIN
    walked = tuple(revision.revision for revision in script.walk_revisions())[::-1]
    assert walked == chain, "the graph walked from its base is not the pinned chain"
    assert tuple(script.get_bases()) == (chain[0],), "the chain has more than one base"
    assert tuple(script.get_heads()) == (chain[-1],), "the chain has more than one head"

    children: dict[str, list[str]] = {revision: [] for revision in chain}
    for index, name in enumerate(chain):
        revision = script.get_revision(name)
        assert revision is not None, name
        expected = () if index == 0 else HISTORICAL_PARENTS.get(name, (chain[index - 1],))
        assert _parents(revision) == expected, (
            f"{name} revises {_parents(revision)}, but the chain puts {expected} beneath it"
        )
        for parent in _parents(revision):
            children[parent].append(name)
    forks = {name: sorted(kids) for name, kids in children.items() if len(kids) > 1}
    assert forks == HISTORICAL_FORKS, "a revision gained a second child"
    assert [name for name, kids in children.items() if not kids] == [chain[-1]]

    on_chain = set()
    for name in chain:
        revision = script.get_revision(name)
        assert revision is not None and revision.path is not None, name
        on_chain.add(Path(revision.path).resolve())
    files = {path.resolve() for path in pins.MIGRATIONS.glob("*.py")}
    assert files == on_chain, f"revision files off the chain: {sorted(map(str, files - on_chain))}"
