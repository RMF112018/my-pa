"""Only the two local operator adapters stamp `operator_surface` (KLP-WP-04, R6 section 3.2).

R6 section 3.2 item 5 (i), KLP-AC-039 (stamping half): no module under
`src/my_pa/adapters/mcp/` and not `apps/cli/gsqs_b0.py` references
`operator_surface` or `OperatorSurface`, and exactly two production call sites
stamp a surface -- `adapters/cli/app.py` with `OperatorSurface.CLI` and the HTTP
gateway's `invoke` route in `adapters/http/app.py` with
`OperatorSurface.HTTP_GATEWAY`. The remote capture route (`submit`) never does.

"Stamp" means a call passing `operator_surface=` anything other than a plain
forward of a variable named `operator_surface` (the service's own
`invoke -> _run -> authorize -> Authorization` plumbing). Measured over the AST of
every production module, so a new stamp anywhere -- under any spelling of the
value -- fails here.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
PRODUCTION: Final = (ROOT / "src", ROOT / "apps")
FORBIDDEN: Final = (
    ROOT / "src" / "my_pa" / "adapters" / "mcp",
    ROOT / "apps" / "cli" / "gsqs_b0.py",
)
EXPECTED_STAMPS: Final = {
    ("src/my_pa/adapters/cli/app.py", "run", "CLI"),
    ("src/my_pa/adapters/http/app.py", "invoke", "HTTP_GATEWAY"),
}


def _modules() -> list[Path]:
    return sorted(path for root in PRODUCTION for path in root.rglob("*.py"))


def _forbidden(path: Path) -> bool:
    return any(path == item or item in path.parents for item in FORBIDDEN)


def _enclosing_functions(tree: ast.AST) -> dict[ast.AST, str]:
    owner: dict[ast.AST, str] = {}

    def visit(node: ast.AST, current: str) -> None:
        for child in ast.iter_child_nodes(node):
            name = (
                child.name if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else current
            )
            owner[child] = name
            visit(child, name)

    visit(tree, "<module>")
    return owner


def _stamps() -> set[tuple[str, str, str]]:
    found: set[tuple[str, str, str]] = set()
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        owner = _enclosing_functions(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "operator_surface":
                    continue
                value = keyword.value
                if isinstance(value, ast.Name) and value.id == "operator_surface":
                    continue  # a forward of the caller's own parameter
                if (
                    isinstance(value, ast.Attribute)
                    and value.attr == "operator_surface"
                    and isinstance(value.value, ast.Name)
                    and value.value.id == "self"
                ):
                    continue  # a forward of the record's own field
                member = (
                    value.attr
                    if isinstance(value, ast.Attribute)
                    and isinstance(value.value, ast.Name)
                    and value.value.id == "OperatorSurface"
                    else ast.unparse(value)
                )
                found.add((path.relative_to(ROOT).as_posix(), owner.get(node, "?"), member))
    return found


def test_no_mcp_module_or_gsqs_b0_references_the_operator_surface() -> None:
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in _modules()
        if _forbidden(path)
        and (
            "operator_surface" in (text := path.read_text(encoding="utf-8"))
            or "OperatorSurface" in text
        )
    ]
    assert offenders == []
    assert any(_forbidden(path) for path in _modules()), "the forbidden set matched no module"


def test_exactly_two_production_call_sites_stamp_a_surface() -> None:
    assert _stamps() == EXPECTED_STAMPS


def test_the_remote_capture_route_never_stamps_a_surface() -> None:
    path = ROOT / "src" / "my_pa" / "adapters" / "http" / "app.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    routes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "submit"
    ]
    assert routes, "the remote capture route was not found"
    for route in routes:
        assert "operator_surface" not in ast.unparse(route)
        assert "OperatorSurface" not in ast.unparse(route)
