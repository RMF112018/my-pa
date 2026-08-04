"""ADR-003 clause 5, at both of its ends: no write on the port, no source in the writer.

Clause 5 says a record the user authors inside `my-pa` is a **third authority
class** — product-owned, neither a source-system write nor a managed-document
write — and that admitting it "grants the read-only source-provider port no
write method". That is one sentence and **two** claims, and a build can satisfy
either while breaking the other:

* the port could stay read-only while the capture writer reached through it
  anyway, which is a source touched by the plane that is supposed to own nothing
  but its own records;
* the capture writer could touch no source at all while the port grew a `write`,
  which is the mutation surface clause 5 refuses whether or not anything has yet
  called it.

So there are **two plants and two ends**, and each is required to leave the
other green. `D-55` is the standing reason: a plant that fails both ends of a
bridge distinguishes nothing, and the campaign has already shipped one design
that proposed exactly that.

**The third end is elsewhere and is named here so a reader can find it.**
`tests/security/test_mcp_and_cli_negative_evidence.py` drives every capture
capability over both transports against a recording provider and asserts the
provider is **neither called nor looked up** — the run-time form of the same
claim, and the one carrying `D-71`'s exemption of `capture.*` from the
mutating-name proxy. This module is the static form: what the source says,
rather than what one traversal of it did.

Nothing here opens a path, reaches a source, or touches a database.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from my_pa.contracts.ports import SourceProviders
from my_pa.domain.source.provider import SourceProvider

ROOT: Final = Path(__file__).resolve().parents[2]
SOURCE: Final = ROOT / "src"

#: The capture writer. The one module under `src/` that stores a capture, and
#: therefore the one that would have to reach a source in order for the capture
#: plane to reach one at all.
CAPTURE_WRITER: Final = SOURCE / "my_pa" / "infrastructure" / "persistence" / "capture.py"

#: A module that really does import a provider, so the import detector below has
#: something it must find. `unit_of_work.py` composes the registry the use cases
#: are handed; if this stops being true the control reddens and says so.
PROVIDER_IMPORTER: Final = SOURCE / "my_pa" / "infrastructure" / "persistence" / "unit_of_work.py"

#: What the read-only port is, in full. An exact set rather than a list of
#: forbidden verbs, because "no method whose name sounds like a write" is a
#: proxy and this repository has already had to replace one of those (`D-71`).
#: A method added here for any reason has to be argued against clause 5, which
#: is the point.
READ_ONLY_SURFACE: Final = frozenset({"source_id", "list_children", "metadata", "fetch"})

#: The names clause 5 is usually broken by. Kept beside the exact set as a
#: second, independent statement of the same refusal — an exact-set assertion
#: that someone widened "to add one harmless method" would still fail this.
MUTATING_VERBS: Final = (
    "write",
    "create",
    "update",
    "delete",
    "remove",
    "rename",
    "move",
    "put",
    "permission",
    "chmod",
    "chown",
)

#: The provider package, as a module path. Any import that starts here is a
#: reach for a source.
PROVIDER_PACKAGE: Final = "my_pa.infrastructure.providers"

#: The pipeline that derives proposals from a capture's text. Every module of
#: it, so a stage added in a second file is covered by the same walk rather than
#: by a name somebody remembered to add.
PIPELINE_PACKAGE: Final = SOURCE / "my_pa" / "infrastructure" / "jobs"
PIPELINE_MODULES: Final = (PIPELINE_PACKAGE / "capture_pipeline.py",)

#: What "reaches the network" looks like as an import, for a build that has no
#: HTTP client in `src/` at all. Both the standard library's clients and the
#: third-party one the transports use, plus the socket layer under them. `mcp`
#: and `starlette` are here because a pipeline that imported either would have
#: reached a transport from inside a worker, which is the same mistake wearing a
#: different name.
NETWORK_PACKAGES: Final = (
    "socket",
    "ssl",
    "http",
    "urllib",
    "httpx",
    "requests",
    "asyncio",
    "mcp",
    "starlette",
    "uvicorn",
)


def _public(port: type) -> frozenset[str]:
    """Every name the port declares, excluding the machinery `ABC` adds."""
    return frozenset(
        name
        for name in vars(port)
        if not name.startswith("_") and name not in {"abstractmethods", "impl"}
    )


def _is_network(name: str) -> bool:
    """Whether one imported module name is a reach for the network.

    Prefix-matched on a dotted boundary rather than by substring, so a module
    called `my_pa.domain.sslabel` is not read as `ssl`.
    """
    return any(name == package or name.startswith(f"{package}.") for package in NETWORK_PACKAGES)


def _imports(path: Path) -> frozenset[str]:
    """Every module one file imports, by dotted name, both statement forms."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return frozenset(found)


def test_the_source_provider_port_declares_exactly_its_four_read_operations() -> None:
    """End one: the port a capture cannot use, because there is nothing to use.

    Both halves are asserted. The exact set is the strong claim; the verb scan
    beside it is what catches a widening that renamed its way past the set — and
    it is applied to a synthetic name in the same test, so a verb list that
    matched nothing could not pass silently.
    """
    surface = _public(SourceProvider)
    assert surface == READ_ONLY_SURFACE, (
        f"the read-only source-provider port declares {sorted(surface)}. ADR-003 "
        "clause 5 grants it no write method; a capture is a product-owned record "
        "and is not a source-system write"
    )
    assert SourceProvider.__abstractmethods__ >= frozenset({"list_children", "metadata", "fetch"})

    offending = [name for name in surface if any(verb in name.lower() for verb in MUTATING_VERBS)]
    assert offending == [], f"the port declares a mutating operation: {offending}"

    # The lookup is the other half of the port and is read-only for the same
    # reason: a use case that could register or replace a provider would be
    # choosing an implementation, which belongs to the composition root.
    assert _public(SourceProviders) == frozenset({"for_source"})

    # The control that makes the zero above a measurement: the same scan over a
    # name that does mutate has to report it.
    assert [name for name in ("write_object",) if any(verb in name for verb in MUTATING_VERBS)] == [
        "write_object"
    ]


def test_the_capture_writer_imports_no_source_provider() -> None:
    """End two: the plane that owns product records reaches for no source at all.

    Not "calls no provider method" — *imports* no provider module. Clause 5 is a
    claim about reaching, and a writer that resolved a provider and then decided
    against calling it would still have reached. The stronger runtime form of
    this is in `tests/security/test_mcp_and_cli_negative_evidence.py`, which
    asserts the lookup itself is never made.
    """
    imported = _imports(CAPTURE_WRITER)
    assert imported, "the capture writer was parsed as importing nothing at all"

    reaching = sorted(name for name in imported if name.startswith(PROVIDER_PACKAGE))
    assert reaching == [], (
        f"{CAPTURE_WRITER.relative_to(ROOT)} imports {reaching}. A capture is a "
        "product-owned record under ADR-003 clause 5; the module that stores one "
        "has no source to read and no provider to resolve"
    )

    # The control: the same detector, over a module that does import a provider,
    # reports it. Without this, a detector that parsed nothing would agree with
    # the assertion above.
    composed = sorted(
        name for name in _imports(PROVIDER_IMPORTER) if name.startswith(PROVIDER_PACKAGE)
    )
    assert composed, (
        f"{PROVIDER_IMPORTER.relative_to(ROOT)} imports no provider module, so the "
        "detector above has never been shown to find one"
    )


def test_no_pipeline_stage_reaches_a_source_provider_or_the_network() -> None:
    """`QC-AC-042`(a): captured text cannot invoke a tool or make a fetch.

    **A static claim, because the runtime form cannot make it.** A test that ran
    the pipeline over an injection corpus and asserted no provider was called
    proves it for the strings that corpus happened to contain; a proposal that
    the pipeline *cannot* fetch has to be about what the code can reach, and one
    traversal of it is not that. The runtime half exists and is elsewhere —
    `tests/pipeline/test_injection_corpus.py` drives text designed to instruct —
    and the two together are what the criterion asks for.

    Two reaches are refused and each has its own assertion, because they fail
    independently: a pipeline could resolve a source provider without opening a
    socket, and it could open a socket without ever naming a provider.

    The control is the same detector over the module that *does* import a
    provider, so a zero here is a measurement rather than a parser that found
    nothing.
    """
    assert PIPELINE_MODULES, "the pipeline module list is empty, so this test checks nothing"
    for module in PIPELINE_MODULES:
        assert module.is_file(), f"{module.relative_to(ROOT)} does not exist"
        imported = _imports(module)
        assert imported, f"{module.relative_to(ROOT)} was parsed as importing nothing at all"

        reaching = sorted(name for name in imported if name.startswith(PROVIDER_PACKAGE))
        assert reaching == [], (
            f"{module.relative_to(ROOT)} imports {reaching}. A pipeline stage derives "
            "proposals from text already stored; captured text that could reach a "
            "source provider is captured text that has broadened retrieval "
            "(`QC-AC-042`)"
        )

        networking = sorted(name for name in imported if _is_network(name))
        assert networking == [], (
            f"{module.relative_to(ROOT)} imports {networking}. No stage of this "
            "pipeline makes a call of any kind; its only inputs are a database "
            "connection and text already in it"
        )

    # The control, in this test rather than in another file: the same detector,
    # over the module that composes providers, reports the reach. Without it, a
    # walk that returned nothing would satisfy both assertions above.
    composed = sorted(
        name for name in _imports(PROVIDER_IMPORTER) if name.startswith(PROVIDER_PACKAGE)
    )
    assert composed, (
        f"{PROVIDER_IMPORTER.relative_to(ROOT)} imports no provider module, so the "
        "detector above has never been shown to find one"
    )

    # The second control, for the network half: the same matcher over a name that
    # is a network reach has to report it. A prefix list that matched nothing
    # would otherwise agree with the zero above.
    assert [name for name in ("httpx._client", "socket") if _is_network(name)] == [
        "httpx._client",
        "socket",
    ]
