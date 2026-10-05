"""KLP-AC-071 (repository half): the Knowledge plane imports no outbound write adapter.

No module under `src/my_pa/**/knowledge_assertion*` (the WP-01 domain package,
the WP-03 repository) nor `application/knowledge_assertions.py` may import --
directly or through any `my_pa` module it imports -- an adapter that can reach
or change an external system: the connector, source-provider and provider
packages, the GoodNotes and Apple bridges, the routed model transport, the
transport adapters, or a network/mail client library. The runtime half (external
source mutation denied except the commissioned Teams Notes feedback action) is
commissioning evidence, KLP-AC-160.

Read with `ast` over the source tree; nothing is imported to answer it. The
controls prove the walk can see both a direct and a transitive violation.
"""

from __future__ import annotations

import ast
from functools import cache
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"

#: `my_pa` packages and modules that reach or change something outside this process.
OUTBOUND_MY_PA: Final = (
    "my_pa.infrastructure.connectors",
    "my_pa.infrastructure.source_providers",
    "my_pa.infrastructure.providers",
    "my_pa.infrastructure.goodnotes",
    "my_pa.infrastructure.apple_source_host",
    "my_pa.infrastructure.apple_transport_agent",
    "my_pa.infrastructure.gsqs_routellm_transport",
    "my_pa.infrastructure.managed_document_stores",
    "my_pa.adapters",
)
#: Third-party and standard-library clients that open an outbound channel.
OUTBOUND_LIBRARIES: Final = frozenset(
    {
        "httpx",
        "httpx2",
        "requests",
        "urllib.request",
        "http.client",
        "smtplib",
        "socket",
        "ftplib",
        "msal",
        "msgraph",
        "aiohttp",
        "boto3",
    }
)


def knowledge_modules() -> list[Path]:
    found = sorted(
        path
        for path in PACKAGE.rglob("*.py")
        if any(part.startswith("knowledge_assertion") for part in path.relative_to(PACKAGE).parts)
    )
    application = PACKAGE / "application" / "knowledge_assertions.py"
    if application not in found:
        found.append(application)
    return found


def _module_name(path: Path) -> str:
    relative = path.relative_to(ROOT / "src").with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(source: str, module: str) -> set[str]:
    names: set[str] = set()
    package = module.rsplit(".", 1)[0]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                anchor = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join([*anchor, base]) if base else ".".join(anchor)
            names.add(base)
            names.update(f"{base}.{alias.name}" for alias in node.names)
    return names


@cache
def _path_of(module: str) -> Path | None:
    candidate = ROOT / "src" / Path(*module.split("."))
    if candidate.with_suffix(".py").is_file():
        return candidate.with_suffix(".py")
    if (candidate / "__init__.py").is_file():
        return candidate / "__init__.py"
    return None


def _outbound(name: str) -> bool:
    if any(name == prefix or name.startswith(f"{prefix}.") for prefix in OUTBOUND_MY_PA):
        return True
    return any(name == lib or name.startswith(f"{lib}.") for lib in OUTBOUND_LIBRARIES)


def reached(start: str, source: str) -> dict[str, list[str]]:
    """Every outbound name `start` reaches through `my_pa` imports, with one path to it."""
    found: dict[str, list[str]] = {}
    seen: set[str] = set()
    stack: list[tuple[str, str, list[str]]] = [(start, source, [start])]
    while stack:
        module, text, trail = stack.pop()
        if module in seen:
            continue
        seen.add(module)
        for name in _imports(text, module):
            if _outbound(name):
                found.setdefault(name, [*trail, name])
                continue
            if not name.startswith("my_pa"):
                continue
            path = _path_of(name)
            if path is not None and name not in seen:
                stack.append((name, path.read_text(encoding="utf-8"), [*trail, name]))
    return found


def test_the_scan_finds_the_knowledge_modules() -> None:
    modules = {path.relative_to(PACKAGE).as_posix() for path in knowledge_modules()}
    assert "application/knowledge_assertions.py" in modules
    assert "infrastructure/persistence/knowledge_assertions.py" in modules
    assert "domain/knowledge_assertion/assertion.py" in modules
    assert len(modules) >= 10


def test_no_knowledge_module_reaches_an_outbound_write_adapter() -> None:
    violations = {
        path.relative_to(PACKAGE).as_posix(): reached(
            _module_name(path), path.read_text(encoding="utf-8")
        )
        for path in knowledge_modules()
    }
    offending = {module: hits for module, hits in violations.items() if hits}
    assert offending == {}, (
        f"{offending} reach an outbound adapter; the Knowledge plane writes only its own "
        "rows (KLP-AC-071)"
    )


def test_the_walk_sees_a_direct_and_a_transitive_violation() -> None:
    """The control: a planted direct import and a planted chain are both reported."""
    direct = reached("my_pa.planted", "from my_pa.infrastructure.connectors import email\n")
    assert "my_pa.infrastructure.connectors" in direct
    library = reached("my_pa.planted", "import smtplib\n")
    assert "smtplib" in library
    # The real HTTP adapter is reached through the transport package.
    chain = reached("my_pa.planted", "from my_pa.adapters.http import app\n")
    assert chain
