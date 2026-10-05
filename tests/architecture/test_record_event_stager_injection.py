"""WP-RE-04: every writing Entity / Memory repository in `src/` carries a stager.

`SqlEntityRepository` and `SqlRelationshipMemoryRepository` stage their Record
Events (seams S-A, S-B, S-C and the memory admit) into the buffer they were
built with. Built without one they stage into a private buffer that nothing
flushes -- correct for a test fixture, and silently event-less for production.
So every construction in `src/` must pass `stager=`, except a construction
whose only use is one lock call made on the spot, which writes nothing.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"
REPOSITORIES: Final = frozenset(
    {
        "SqlEntityRepository",
        "SqlRelationshipMemoryRepository",
        # KLP-WP-03 (KLP-AC-123): the Knowledge Assertion repository stages the
        # explicit create's event into the buffer it was built with.
        "SqlKnowledgeAssertionRepository",
    }
)
#: A construction used for exactly one of these calls, inline, writes nothing.
LOCK_ONLY_CALLS: Final = frozenset(
    {"serialize_entity_proposal_scope", "serialize_entity_proposals_scope"}
)


def _constructions(tree: ast.Module) -> list[tuple[int, bool, bool]]:
    """`(line, passes a stager, used inline for one lock call only)` per construction."""
    lock_only: set[int] = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in LOCK_ONLY_CALLS
            and isinstance(node.func.value, ast.Call)
        ):
            lock_only.add(id(node.func.value))
    found: list[tuple[int, bool, bool]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in REPOSITORIES
        ):
            stager = any(keyword.arg == "stager" for keyword in node.keywords)
            found.append((node.lineno, stager, id(node) in lock_only))
    return found


def test_every_writing_construction_in_src_passes_a_stager() -> None:
    unstaged: list[str] = []
    seen = 0
    for path in sorted(PACKAGE.rglob("*.py")):
        for line, stager, lock_only in _constructions(ast.parse(path.read_text("utf-8"))):
            seen += 1
            if not stager and not lock_only:
                unstaged.append(f"{path.relative_to(ROOT)}:{line}")
    assert seen, "the scan found no construction at all, so it proves nothing"
    assert not unstaged, (
        f"{unstaged} build an Entity/Memory repository with no Record Event stager; "
        "its writes would stage into a buffer nothing flushes"
    )


def test_the_scan_tells_a_writer_from_a_lock_only_call() -> None:
    """The control: an unstaged writer is reported; a stager or a lock-only use is not."""
    tree = ast.parse(
        "SqlEntityRepository(connection)\n"
        "SqlEntityRepository(connection, stager=buffer)\n"
        "SqlEntityRepository(connection).serialize_entity_proposal_scope(p, q)\n"
        "SqlRelationshipMemoryRepository(connection).admit(request)\n"
    )
    assert [(stager, lock_only) for _, stager, lock_only in _constructions(tree)] == [
        (False, False),
        (True, False),
        (False, True),
        (False, False),
    ]


def test_every_identity_correction_service_in_src_is_given_the_units_stager() -> None:
    """WP-RE-04 Phase 4B: the four handler constructions pass `stager=` explicitly.

    `IdentityCorrectionService` falls back to its entity repository's buffer,
    which inside a unit of work is the same buffer -- so this, and not the
    fallback, is what holds the handlers to naming the unit of work's stager.
    """
    found: list[tuple[str, bool]] = []
    for path in sorted(PACKAGE.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text("utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "IdentityCorrectionService"
            ):
                found.append(
                    (
                        f"{path.relative_to(ROOT)}:{node.lineno}",
                        any(keyword.arg == "stager" for keyword in node.keywords),
                    )
                )
    assert len(found) == 4, found
    assert all(staged for _, staged in found), found


def test_the_knowledge_repository_cannot_be_built_without_a_stager() -> None:
    """KLP-AC-123: `stager` is keyword-only and has no default, so the type itself refuses."""
    import inspect

    from my_pa.infrastructure.persistence.knowledge_assertions import (
        SqlKnowledgeAssertionRepository,
    )

    parameter = inspect.signature(SqlKnowledgeAssertionRepository).parameters["stager"]
    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is inspect.Parameter.empty


def test_every_knowledge_repository_construction_in_src_is_counted() -> None:
    """The scan above sees the one production construction (the unit of work's)."""
    found = [
        (path.relative_to(ROOT).as_posix(), stager)
        for path in sorted(PACKAGE.rglob("*.py"))
        for node in ast.walk(ast.parse(path.read_text("utf-8")))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "SqlKnowledgeAssertionRepository"
        for stager in [any(keyword.arg == "stager" for keyword in node.keywords)]
    ]
    assert found == [("src/my_pa/infrastructure/persistence/unit_of_work.py", True)]
