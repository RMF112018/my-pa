"""`D-27`: async is a property of one package, and it is checked as one.

Before WP-4B2b, `grep -rn "async def|await " src apps tests` answered with
nothing across the whole repository — the MCP SDK's handlers are the first thing
in this system that must be `async def`, and `D-27` admits them as a bounded
edge rather than as the start of an asynchronous application.

"Bounded" is the part a comment cannot hold. These rules parse the tree and say
where a coroutine may exist: **inside `adapters/mcp`, the exact origin OAuth
HTTP adapter, or the isolated GSQS remote-eval Streamable HTTP adapter, and
nowhere else in `src/`**, and nowhere at all in `apps/`, which
is where a composition root would otherwise acquire an event loop of its own.
`serve_stdio` is an ordinary `def` precisely so that no caller ever sees one,
and `test_the_mcp_entry_points_are_synchronous`
is what says so.

The counts are asserted too, and deliberately: two coroutine functions and one
`await` in the handlers is the whole surface, and a rule that only said "some
async lives here" would not notice the day it became ten.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "my_pa"
APPS = ROOT / "apps"

#: The one package a coroutine may live in. `module-boundaries.md` section 5.7
#: puts transport concerns in a transport adapter, and the concurrency the SDK
#: brings is one. The isolated GSQS remote-eval Streamable HTTP adapter is a
#: second MCP SDK edge, not a member of the production `adapters/mcp` package.
ASYNC_SUBTREE = PACKAGE / "adapters" / "mcp"
OAUTH_ADAPTER = PACKAGE / "adapters" / "http" / "oauth.py"
EVAL_MCP_ADAPTER = PACKAGE / "adapters" / "gsqs_remote_eval_mcp.py"

#: Every node that makes a module asynchronous. `AsyncFunctionDef` is the
#: coroutine, and the other three are the statements that can only appear inside
#: one — listed separately so a failure names which of them arrived.
ASYNC_NODES = (ast.AsyncFunctionDef, ast.Await, ast.AsyncFor, ast.AsyncWith)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _async_nodes(path: Path) -> list[str]:
    return [type(node).__name__ for node in ast.walk(_tree(path)) if isinstance(node, ASYNC_NODES)]


def _modules(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def test_there_is_async_to_confine() -> None:
    """Guard every rule below: with no coroutine anywhere they are rules about nothing."""
    found = [node for path in _modules(ASYNC_SUBTREE) for node in _async_nodes(path)]
    assert found, "nothing in adapters/mcp is asynchronous; this file confines nothing"


@pytest.mark.parametrize(
    "path",
    [
        p
        for p in _modules(PACKAGE)
        if not p.is_relative_to(ASYNC_SUBTREE) and p != OAUTH_ADAPTER and p != EVAL_MCP_ADAPTER
    ],
    ids=lambda p: str(p.name),
)
def test_no_module_outside_the_mcp_adapter_is_asynchronous(path: Path) -> None:
    """`D-27`: `domain`, `application`, `infrastructure`, and the other transports.

    Including the existing application HTTP adapter, which bridges the *other* way — it schedules a
    coroutine onto a loop from a worker thread and never declares one — and
    `adapters/normalization`, which is shared by all three and would drag async
    into every transport if it acquired any.
    """
    found = sorted(set(_async_nodes(path)))
    assert not found, (
        f"{path.relative_to(PACKAGE)} contains {found}; `D-27` confines async to "
        "the MCP SDK edge, the exact origin OAuth HTTP adapter, and the isolated "
        "GSQS remote-eval Streamable HTTP adapter"
    )


@pytest.mark.parametrize("path", _modules(APPS), ids=lambda p: str(p.name))
def test_no_composition_root_is_asynchronous(path: Path) -> None:
    """A composition root that awaited would have taken the transport's concern.

    `apps/gateway.py` runs the MCP server by calling `serve_stdio`, which owns
    its loop and returns `None`. An `asyncio.run` here instead would put the
    boundary in the wrong file and make every future entry point inherit it.
    """
    found = sorted(set(_async_nodes(path)))
    assert not found, f"{path.relative_to(ROOT)} contains {found}; async belongs to the adapter"


def test_the_async_surface_remains_confined_and_bounded() -> None:
    """The size of the edge, not only its location.

    The official SDK handlers, stdio connection, Streamable HTTP lifespan and
    bounded remote authentication/request edge account for this deliberately
    frozen total. Another node means the asynchronous boundary changed and must
    be reviewed as a decision rather than accepted as a mechanical edit.
    """
    found: list[str] = []
    for path in _modules(ASYNC_SUBTREE):
        found += _async_nodes(path)
    assert found.count("AsyncFunctionDef") == 8, found
    assert found.count("Await") == 11, found
    assert found.count("AsyncWith") == 3, found
    assert found.count("AsyncFor") == 0, found


def test_the_origin_oauth_async_surface_is_exact_and_bounded() -> None:
    found = _async_nodes(OAUTH_ADAPTER)
    assert found.count("AsyncFunctionDef") == 8, found
    assert found.count("Await") == 13, found
    assert found.count("AsyncWith") == 0, found
    assert found.count("AsyncFor") == 0, found


def test_the_eval_mcp_async_surface_is_exact_and_bounded() -> None:
    found = _async_nodes(EVAL_MCP_ADAPTER)
    assert found.count("AsyncFunctionDef") == 9, found
    assert found.count("Await") == 9, found
    assert found.count("AsyncWith") == 2, found
    assert found.count("AsyncFor") == 0, found


def test_the_mcp_entry_points_are_synchronous() -> None:
    """Everything this package exports is an ordinary function.

    This is what "async does not leak" means to a caller: `serve_stdio` and
    `create_mcp_server` return values, not awaitables, so a composition root
    needs no loop and no runner of its own.
    """
    import inspect

    import my_pa.adapters.mcp as package

    for name in package.__all__:
        exported = getattr(package, name)
        if callable(exported):
            assert not inspect.iscoroutinefunction(exported), f"{name} is a coroutine function"


def test_the_guard_catches_a_planted_coroutine(tmp_path: Path) -> None:
    """Plant each of the four node kinds, so a narrowed rule cannot pass silently."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "async def go(items):\n"
        "    async with items as opened:\n"
        "        async for item in opened:\n"
        "            await item\n",
        encoding="utf-8",
    )
    assert sorted(set(_async_nodes(planted))) == [
        "AsyncFor",
        "AsyncFunctionDef",
        "AsyncWith",
        "Await",
    ]


def test_a_docstring_that_mentions_await_does_not_fire(tmp_path: Path) -> None:
    """The rule reads the syntax, not the prose.

    A text search would have flagged `adapters/mcp/server.py`'s own docstring,
    which explains the boundary at length, and a rule that fires on its own
    documentation is a rule someone deletes.
    """
    planted = tmp_path / "planted.py"
    planted.write_text('"""This module does not await; async def stays at the edge."""\n', "utf-8")
    assert _async_nodes(planted) == []
