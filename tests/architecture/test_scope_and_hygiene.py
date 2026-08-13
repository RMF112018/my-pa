"""Scope, neutral naming, and secret hygiene.

These guard the boundaries the work is bounded by: no transport, provider, or
model dependency; one PostgreSQL driver rather than several; neutral naming;
nothing secret-shaped committed.

A guard here is narrowed only when scope legitimately grows, never to make a
change pass. Each narrowing states its reason beside the pattern and is paired
with planted violations, so a relaxed guard cannot silently become a guard that
matches nothing.

Persistence entered scope with the PostgreSQL foundation, so SQLAlchemy,
Alembic, and `psycopg` moved from the prohibited list to the declared set below.
The alternative drivers stay prohibited: two drivers for one database is the
duplicate-library case AGENTS.md section 2 rules out, and it would make the
connection URL's scheme ambiguous.

The HTTP transport entered scope with WP-4B2a, and the two dependencies it
brings are narrowed differently rather than both being deleted from the list,
because they are permitted in different places and "permitted" would be weaker
than the truth in both cases:

* **Starlette is confined**, not admitted. It may be imported by
  `adapters/http`, which is the transport, and nowhere else — an application or
  infrastructure module that imported it would have taken a transport concern,
  and the layer rules in `test_dependency_direction.py` would not catch it,
  because they are about direction rather than about libraries.
* **uvicorn stays prohibited inside the package** and is a declared runtime
  dependency all the same. It is the server that runs the application, which is
  the composition root's business: `apps/gateway.py` imports it and nothing
  under `src/` may. That is why the declared-set check and the import check now
  read two different lists rather than one.

**The MCP SDK entered scope with WP-4B2b and is confined the same way Starlette
is**, not admitted. `mcp` moved off the prohibited list and onto the confined
one, so `adapters/mcp` may import it and nothing else may — an application or
infrastructure module that reached for it would have taken a transport concern,
and the layer rules in `test_dependency_direction.py` are about direction rather
than about libraries. Deleting it from the prohibited list without adding it to
the confined one would have been admitting it package-wide, which is the
difference this file exists to keep.

**The SDK's transitive surface is prohibited, and the list of it is derived
rather than typed.** `mcp` pulls an HTTP client, `cryptography`, `pyjwt`,
`jsonschema`, `sse-starlette`, `python-multipart` and an OpenTelemetry API to
serve the OAuth and streamable-HTTP surfaces `D-30` refuses. `D-26` accepts that
cost *on the grounds that none of them can be imported and a test enforces it*,
so what that test actually covers is the whole of the decision's surviving cost
argument.

It covered none of them. The first version of this guard was a hand-typed list,
and an independent review added `import cryptography`, `import httpx2`,
`import jwt`, `import jsonschema`, `import sse_starlette` and
`from opentelemetry import trace` to `application/service.py` with the entire
FAST tier staying green. Not one root was on the list — and the entry meant to
cover the HTTP client was `httpx`, while `mcp` 2.0 declares **`httpx2`**, so
that entry could never fire at all. Four documents asserted the enforcement:
this docstring, `pyproject.toml`, the `D-26` register row, and the commit
message. All four were false.

`SDK_IMPORT_ROOTS` below is the fix and the reason it is a derivation rather
than a longer list: it walks `mcp`'s declared requirement closure — extras
included, which is how `cryptography` arrives, through `pyjwt[crypto]` — and
maps every distribution in it to the import names it installs. A future SDK
release that adds a package nobody here thought of is prohibited by having been
declared. `httpx` stays typed beside `httpx2` because a later release could
switch back, and a guard that stopped covering the old name would fail silently.

FastAPI stays prohibited. `D-25` chose Starlette precisely so that HTTP would
not acquire a second validation layer that the MCP adapter has no counterpart
for, and a dependency admitted "just for one route" is how that decision would
be reversed without being revisited.
"""

from __future__ import annotations

import ast
import importlib.metadata as metadata
import re
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
PACKAGE = SRC / "my_pa"

#: Dependencies no module under `src/my_pa` may import, by root, named one by
#: one because each is a distinct decision. `uvicorn` is here *and* declared in
#: `pyproject.toml`: running a server is the composition root's act, and
#: `apps/gateway.py` lives outside this tree. `httpx` is here beside the derived
#: `httpx2`; see the module docstring.
NAMED_PROHIBITED_ROOTS = frozenset(
    {
        "fastapi",
        "uvicorn",
        "psycopg2",
        "asyncpg",
        "redis",
        "celery",
        "anthropic",
        "openai",
        "httpx",
        "requests",
        "aiohttp",
        "neo4j",
        "chromadb",
        "pinecone",
        "pypdf",
        "pdfminer",
        "fitz",
        "paramiko",
        "boto3",
        "dotenv",
        "environs",
        "attrs",
        "marshmallow",
        "cerberus",
    }
)

#: The roots this package legitimately imports and which therefore cannot be
#: prohibited by the derivation below. Each is subtracted for a stated reason,
#: and `test_every_exemption_is_actually_used` requires each to be used — an
#: exemption nobody needs is a hole with a comment on it.
#:
#: * `pydantic` — the contract and settings boundary;
#:   `test_pydantic_is_confined_to_contracts_and_settings` is what says where.
#: * `starlette` — confined to `adapters/http` by `CONFINED_IMPORT_ROOTS`.
#: * `uvicorn` — prohibited above by name, which is stricter, so subtracting it
#:   from the derivation changes nothing; it is listed for the reader.
#: * `jwt` — PyJWT stopped being SDK baggage with WP-05 and became a *declared*
#:   direct runtime dependency, because `MY_PA_AUTH_MODE=entra` verifies RS256
#:   bearer tokens and the standard library has no JWS implementation. It is
#:   exempted from the derived prohibition and **confined** by
#:   `CONFINED_IMPORT_ROOTS` to `infrastructure/security`, which is the same
#:   treatment Starlette gets and is stricter than "permitted": one module may
#:   import it and every other module in the tree may not. Deleting it from the
#:   derivation *without* confining it would have admitted a token library
#:   package-wide, which is the difference this file exists to keep.
SDK_EXEMPT_ROOTS = frozenset({"pydantic", "starlette", "uvicorn", "jwt"})


def _distribution_name(specifier: str) -> str:
    """The distribution a requirement specifier names, normalised."""
    return re.split(r"[<>=!~;\[ ]", specifier, maxsplit=1)[0].strip().lower().replace("_", "-")


def _requested_extras(specifier: str) -> frozenset[str]:
    """The extras a requirement asks for, as in `pyjwt[crypto]>=2.10.1`."""
    found = re.search(r"\[([^\]]*)\]", specifier.split(";")[0])
    return frozenset(part.strip() for part in found.group(1).split(",")) if found else frozenset()


def _requirements(distribution: str, extras: frozenset[str]) -> list[str]:
    """What `distribution` declares, keeping only the extras that were asked for."""
    try:
        declared = metadata.distribution(distribution).requires or []
    except metadata.PackageNotFoundError:
        # An extra that is not installed — `mcp`'s `cli` and `rich` groups — can
        # contribute no importable root, so it contributes nothing here either.
        return []
    kept: list[str] = []
    for specifier in declared:
        marker = specifier.split(";", 1)[1] if ";" in specifier else ""
        gated = re.search(r"extra\s*==\s*['\"]([^'\"]+)['\"]", marker)
        if gated and gated.group(1) not in extras:
            continue
        kept.append(specifier)
    return kept


def _dependency_closure(root: str) -> set[str]:
    """Every distribution `root` pulls in, following declared extras."""
    seen: set[tuple[str, frozenset[str]]] = set()
    found: set[str] = set()
    queue: list[tuple[str, frozenset[str]]] = [(root, frozenset())]
    while queue:
        distribution, extras = queue.pop()
        if (distribution, extras) in seen:
            continue
        seen.add((distribution, extras))
        for specifier in _requirements(distribution, extras):
            child = _distribution_name(specifier)
            found.add(child)
            queue.append((child, _requested_extras(specifier)))
    return found


def _import_roots(distributions: set[str]) -> frozenset[str]:
    """The top-level import names those distributions install.

    Read from the installed metadata rather than guessed from the distribution
    name, because the two differ often and silently: `pyjwt` installs `jwt`,
    `opentelemetry-api` installs `opentelemetry`, `python-multipart` installs
    `multipart`. A guard keyed on distribution names would have missed all three.
    """
    owners: dict[str, set[str]] = {}
    for imported, owning in metadata.packages_distributions().items():
        if not imported.isidentifier() or imported.startswith("_"):
            continue
        for distribution in owning:
            owners.setdefault(distribution.lower().replace("_", "-"), set()).add(imported)
    return frozenset(
        root for distribution in distributions for root in owners.get(distribution, ())
    )


#: Everything the MCP SDK drags in, derived from what it declares. See the
#: module docstring: this is `D-26`'s cost argument, and it was a hand-typed
#: list that enforced none of it.
#:
#: The exemptions are subtracted *when the prohibition is formed* rather than
#: here, so this stays what its name says — the closure the SDK resolves to —
#: and the controls below that assert a root is in the closure keep asserting
#: that rather than quietly becoming assertions about the prohibition.
SDK_IMPORT_ROOTS = _import_roots(_dependency_closure("mcp"))

#: Dependencies no module under `src/my_pa` may import, by root.
PROHIBITED_IMPORT_ROOTS = NAMED_PROHIBITED_ROOTS | (SDK_IMPORT_ROOTS - SDK_EXEMPT_ROOTS)

#: What counts as "not third party" when reading the package's own imports.
_STDLIB_ROOTS = frozenset(sys.stdlib_module_names)


def _modules() -> list[Path]:
    return sorted(PACKAGE.rglob("*.py"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


#: Dependencies the package may import in exactly one subtree, and the subtree.
#: See the module docstring: a transport library is not "in scope", it is in the
#: transport.
CONFINED_IMPORT_ROOTS = {
    "starlette": "adapters",
    "mcp": "adapters/mcp",
    # PyJWT. One module verifies bearer tokens; nothing else in the tree may
    # decode, inspect, or re-verify one, which is what keeps "the token was
    # checked here" a fact about the wiring rather than a convention.
    "jwt": "infrastructure/security",
}


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.name))
def test_no_prohibited_dependency_is_imported(path: Path) -> None:
    offending = _imports(path) & PROHIBITED_IMPORT_ROOTS
    assert not offending, f"{path.relative_to(PACKAGE)} imports out-of-scope {sorted(offending)}"


#: The roots an independent review imported into `application/service.py` while
#: the entire FAST tier stayed green. They are named here as *fixtures for the
#: derivation*, not as the rule — the rule is `SDK_IMPORT_ROOTS`, which is
#: derived — so that a derivation which silently stopped resolving anything
#: fails here instead of reporting success over an empty set.
REVIEW_PLANTED_ROOTS = (
    "cryptography",
    "httpx2",
    "jwt",
    "jsonschema",
    "sse_starlette",
    "opentelemetry",
)


@pytest.mark.parametrize("root", REVIEW_PLANTED_ROOTS)
def test_the_derived_prohibition_covers_what_the_sdk_actually_brings(root: str) -> None:
    """Each root the review planted is covered, and by derivation not by name.

    Five are prohibited outright. `jwt` is the sixth and is covered *differently*
    since WP-05: PyJWT became a declared direct dependency, so it is exempt from
    the prohibition and confined to one subtree instead. The third assertion is
    what keeps that from being a hole — a root that left the prohibition without
    arriving in the confinement fails here — and it is stricter than the two
    assertions that preceded it, which said only that the derivation resolved.
    """
    assert root in SDK_IMPORT_ROOTS, (
        f"{root!r} is installed by the MCP SDK's dependency closure and the derivation missed it"
    )
    assert root not in NAMED_PROHIBITED_ROOTS, (
        f"{root!r} is covered by a typed name; the derivation is not what is being tested"
    )
    assert root in PROHIBITED_IMPORT_ROOTS or root in CONFINED_IMPORT_ROOTS, (
        f"{root!r} is neither prohibited nor confined; the SDK's transitive "
        "surface is admitted package-wide"
    )


def test_the_derivation_resolves_a_closure_rather_than_a_direct_list() -> None:
    """`cryptography` is the honest sample: it is nobody's direct requirement.

    It arrives through `pyjwt[crypto]`, which is two hops and an extra away from
    `mcp`. A derivation that read only `mcp`'s own `requires` would miss it, and
    would still pass every other rule in this file.
    """
    direct = {_distribution_name(spec) for spec in _requirements("mcp", frozenset())}
    assert "cryptography" not in direct, "the sample is no longer indirect; pick another"
    assert "pyjwt" in direct
    assert "cryptography" in _dependency_closure("mcp")
    assert len(SDK_IMPORT_ROOTS) >= 20, f"the closure resolved only {sorted(SDK_IMPORT_ROOTS)}"


def test_the_import_root_mapping_is_read_and_not_guessed() -> None:
    """Three distributions whose import name is not their distribution name.

    A guard keyed on distribution names would have prohibited `pyjwt`,
    `opentelemetry-api` and `python-multipart` — none of which is importable
    under those names — and would have caught none of the three real imports.
    """
    for distribution, imported in (
        ("pyjwt", "jwt"),
        ("opentelemetry-api", "opentelemetry"),
        ("python-multipart", "multipart"),
    ):
        assert imported in _import_roots({distribution}), f"{distribution} -> {imported}"
        assert imported in SDK_IMPORT_ROOTS


def test_the_derivation_prohibits_nothing_the_package_legitimately_uses() -> None:
    """An over-broad derivation would be a failing suite, not a silent hole — but say so.

    Every third-party root the package actually imports must be either exempt or
    confined. Without this, a future SDK release that started depending on
    something this repository uses would prohibit it, and the failure would read
    as a scope violation rather than as what it is.
    """
    imported: set[str] = set()
    for path in _modules():
        imported |= _imports(path)
    third_party = {root for root in imported if root != "my_pa" and root not in _STDLIB_ROOTS}
    unaccounted = third_party & PROHIBITED_IMPORT_ROOTS - set(CONFINED_IMPORT_ROOTS)
    assert not unaccounted, (
        f"the package imports {sorted(unaccounted)}, which the derivation prohibits; "
        "either the import is wrong or the root belongs in SDK_EXEMPT_ROOTS with a reason"
    )
    assert third_party == {"jwt", "mcp", "psycopg", "pydantic", "sqlalchemy", "starlette"}, (
        f"the package's third-party surface changed to {sorted(third_party)}"
    )


def test_every_exemption_is_actually_used() -> None:
    """An exemption nobody needs is a hole with a comment on it."""
    imported: set[str] = set()
    for path in _modules():
        imported |= _imports(path)
    unused = sorted(SDK_EXEMPT_ROOTS - imported - {"uvicorn"})
    assert not unused, f"{unused} is exempted from the SDK prohibition and imported by nothing"


@pytest.mark.parametrize("path", _modules(), ids=lambda p: str(p.name))
def test_a_confined_dependency_is_imported_only_where_it_belongs(path: Path) -> None:
    where = path.relative_to(PACKAGE).as_posix()
    for root, subtree in CONFINED_IMPORT_ROOTS.items():
        if root not in _imports(path):
            continue
        assert where.startswith(f"{subtree}/"), (
            f"{where} imports {root!r}, which belongs to {subtree}/ and nowhere else"
        )


def test_every_confined_dependency_is_actually_used_there() -> None:
    """A confinement nothing tests is a rule about an empty set.

    Without this, deleting the transport would leave the rule above passing on
    every module in the tree while confining nothing.
    """
    for root, subtree in CONFINED_IMPORT_ROOTS.items():
        importers = [p for p in _modules() if root in _imports(p)]
        assert importers, f"nothing imports {root!r}; the confinement guards nothing"
        for path in importers:
            assert path.relative_to(PACKAGE).as_posix().startswith(f"{subtree}/")


def test_declared_runtime_dependencies_are_the_agreed_set() -> None:
    """Runtime dependencies are enumerated, not open-ended.

    Adding one has to be a deliberate edit here as well as in `pyproject.toml`,
    which is what keeps "a library for that" from arriving unremarked.
    """
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    runtime = data["project"]["dependencies"]
    roots = {re.split(r"[><=!~\[]", item)[0].strip().lower() for item in runtime}
    assert roots == {
        "pydantic",
        "sqlalchemy",
        "psycopg",
        "alembic",
        "starlette",
        "uvicorn",
        "mcp",
        "pyjwt",
    }


def test_every_runtime_dependency_declares_a_range() -> None:
    # A floor without a ceiling lets a major release land untested; a pin
    # without a floor makes the `dependency-floor` CI job meaningless.
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for item in data["project"]["dependencies"]:
        assert ">=" in item, f"{item} declares no lower bound"
        assert "<" in item.split(">=", 1)[1], f"{item} declares no upper bound"


def test_declared_dev_dependencies_are_the_agreed_set() -> None:
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dev = data["project"]["optional-dependencies"]["dev"]
    roots = {re.split(r"[><=!\[]", item)[0].strip() for item in dev}
    assert roots == {"pytest", "ruff", "mypy"}


def test_no_declared_dependency_is_prohibited() -> None:
    """Nothing out of scope is declared, which is a narrower list than the imports.

    `uvicorn` is subtracted because it is deliberately both: declared, so the
    gateway process can run, and un-importable by the package, so that running a
    server stays the composition root's act. Every other prohibited root is
    prohibited outright and may not be declared either.
    """
    data = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    declared = list(data["project"]["dependencies"])
    for group in data["project"].get("optional-dependencies", {}).values():
        declared.extend(group)
    roots = {re.split(r"[><=!\[]", item)[0].strip().lower() for item in declared}
    assert not (roots & (PROHIBITED_IMPORT_ROOTS - {"uvicorn"}))


def test_the_only_shipped_module_that_runs_a_server_is_the_composition_root() -> None:
    """Across `src/` and `apps/`, `uvicorn` appears in exactly one file.

    The import rule above says the package may not import it. This says where it
    *is* imported, because "nowhere in the package" is also satisfied by a build
    with no gateway at all.

    **The scan is `src/` and `apps/`, and the qualifier is load-bearing.**
    `tests/wire.py` imports uvicorn and runs a server too, deliberately: the
    HTTP tests drive a real one rather than calling an ASGI app in process, and
    it imports `apps.gateway`'s own settings so the two configurations cannot
    drift. What is enforced here is that nothing *shipped* starts a server
    except the composition root, which is the property that matters; a test
    harness is not shipped, and naming this test after the wider claim would
    have made it read as one it does not check.
    """
    shipped = [*_modules(), *sorted((ROOT / "apps").rglob("*.py"))]
    importers = sorted(
        path.relative_to(ROOT).as_posix() for path in shipped if "uvicorn" in _imports(path)
    )
    assert importers == ["apps/gateway.py"]
    assert "uvicorn" in _imports(ROOT / "tests" / "wire.py"), (
        "the harness no longer runs a real server; this test's qualifier is stale"
    )


def test_package_uses_the_neutral_namespace() -> None:
    assert (SRC / "my_pa").is_dir()
    assert not list(SRC.glob("hb_*"))


def test_no_active_former_employer_identifier() -> None:
    pattern = re.compile(r"hb[-_]nas|hb[-_]intel|hbintel|hedrick", re.IGNORECASE)
    for path in [*_modules(), ROOT / "pyproject.toml", ROOT / ".env.example"]:
        text = path.read_text(encoding="utf-8")
        assert not pattern.search(text), f"{path} names a legacy identity"


def test_configuration_prefix_is_neutral() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    declared = re.findall(r"^([A-Z][A-Z0-9_]*)=", example, flags=re.MULTILINE)
    assert declared
    assert all(name.startswith("MY_PA_") for name in declared)


def test_env_example_contains_no_secret_value() -> None:
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    forbidden = re.compile(
        r"(password|secret|api[_-]?key|token|BEGIN [A-Z ]*PRIVATE KEY|postgres://|://[^/\s]+:[^@\s]+@)",
        re.IGNORECASE,
    )
    for line in example.splitlines():
        if line.strip().startswith("#") or not line.strip():
            continue
        assert not forbidden.search(line), f"possible secret in .env.example: {line}"


def test_no_source_file_embeds_a_personal_path_or_credential() -> None:
    forbidden = re.compile(
        r"(/Users/[a-z]|/home/[a-z]|/Volumes/|postgres://|BEGIN [A-Z ]*PRIVATE KEY|ssh\s+\w+-nas)",
        re.IGNORECASE,
    )
    for path in _modules():
        text = path.read_text(encoding="utf-8")
        assert not forbidden.search(text), f"{path} embeds a private value"


def test_repository_has_no_high_confidence_secret_signature() -> None:
    """Scan every text artifact without ever printing a suspected value."""
    signatures = {
        "private_key": re.compile(
            "-----BEGIN " + r"(?:RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY-----"
        ),
        "aws_access_key": re.compile("A" + r"(?:KI|SI)A[0-9A-Z]{16}"),
        "github_token": re.compile("gh" + r"[pousr]_[A-Za-z0-9]{36,}"),
        "github_fine_grained_token": re.compile("github_" + r"pat_[A-Za-z0-9_]{40,}"),
        "slack_token": re.compile("xo" + r"x[baprs]-[A-Za-z0-9-]{20,}"),
        "stripe_live_key": re.compile("sk_" + r"live_[A-Za-z0-9]{20,}"),
        "openai_project_key": re.compile("sk-" + r"proj-[A-Za-z0-9_-]{20,}"),
        "google_api_key": re.compile("AI" + r"za[0-9A-Za-z_-]{35}"),
    }
    roots = (
        ROOT / ".github",
        ROOT / "apps",
        ROOT / "docs",
        ROOT / "migrations",
        ROOT / "ops",
        SRC,
        ROOT / "tests",
        ROOT / "web",
    )
    candidates = [ROOT / ".env.example", ROOT / "pyproject.toml", ROOT / "README.md"]
    candidates.extend(path for root in roots for path in root.rglob("*") if path.is_file())
    for path in candidates:
        if "node_modules" in path.parts or path.stat().st_size > 2_000_000:
            continue
        try:
            document = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for name, signature in signatures.items():
            assert signature.search(document) is None, (
                f"{path.relative_to(ROOT)} matches high-confidence secret signature {name}"
            )


def test_every_package_directory_is_importable() -> None:
    for directory in {p.parent for p in _modules()}:
        assert (directory / "__init__.py").exists(), f"{directory} lacks __init__.py"


#: Module names that mean speculative machinery rather than a domain noun.
#:
#: `registry` was a bare term here until the source registry entered scope.
#: `docs/plans/mcv-completion-plan.md` section 7 names "source registry, bounded
#: enrollment with idempotency keys, job lease/retry, opaque ID issuance" as the
#: WP-2 deliverable, so a registry of sources is a planned product capability
#: rather than an extension point, and banning the word outright would have
#: forced a worse name on a required concept. The speculative sense is what the
#: guard was for, so the compounds carrying that sense stay banned.
#:
#: Two tests hold this pattern in place, and it is worth being exact about what
#: they can and cannot show. The planted violations below prove the pattern is
#: not vacuous; they cannot prove it is general, because any finite list of
#: examples is also satisfied by a pattern that matches only those examples.
#: `test_the_speculative_module_guard_is_exactly_this_pattern` closes that gap
#: structurally: shrinking the pattern to fit its own fixtures fails there.
#:
#: Coverage was genuinely lost, not merely relocated. The old bare term also
#: caught `tool_registry`, `strategy_registry`, `port_registry`, and
#: `registry_factory`; those are named below to recover them. It also caught
#: `source_registry`, which is now deliberately permitted — that name is the
#: legitimate one for this concept.
_SPECULATIVE_MODULE_NAMES = re.compile(
    r"(plugin|factory_factory|abstract_base|extension_point|registry_factory"
    r"|(?:plugin|service|provider|component|handler|adapter|capability|tool"
    r"|strategy|port)_registry)",
    re.I,
)

#: The pattern above, pinned. An edit to the guard has to be an edit here too.
_EXPECTED_SPECULATIVE_PATTERN = (
    r"(plugin|factory_factory|abstract_base|extension_point|registry_factory"
    r"|(?:plugin|service|provider|component|handler|adapter|capability|tool"
    r"|strategy|port)_registry)"
)


def test_no_placeholder_or_speculative_module_was_added() -> None:
    offenders = [
        p.relative_to(PACKAGE) for p in _modules() if _SPECULATIVE_MODULE_NAMES.search(p.name)
    ]
    assert not offenders, f"speculative modules present: {offenders}"


@pytest.mark.parametrize(
    "name",
    [
        "plugin.py",
        "plugin_loader.py",
        "plugin_registry.py",
        "service_registry.py",
        "provider_registry.py",
        "component_registry.py",
        "handler_registry.py",
        "adapter_registry.py",
        "capability_registry.py",
        "factory_factory.py",
        "abstract_base.py",
        "extension_point.py",
    ],
)
def test_the_speculative_module_guard_still_catches_what_it_is_for(name: str) -> None:
    """Planted violations, so narrowing the pattern cannot quietly gut it.

    Without this, a later edit could relax the pattern to the point where it
    matches nothing and the guard above would still pass, reporting a boundary
    it no longer enforces.
    """
    assert _SPECULATIVE_MODULE_NAMES.search(name), f"{name} should be rejected"


@pytest.mark.parametrize(
    "name", ["registry.py", "source_registry.py", "sources.py", "enrollment.py", "jobs.py"]
)
def test_the_speculative_module_guard_permits_domain_nouns(name: str) -> None:
    """The narrowing is deliberate and bounded, not incidental."""
    assert not _SPECULATIVE_MODULE_NAMES.search(name), f"{name} should be permitted"


def test_the_speculative_module_guard_is_exactly_this_pattern() -> None:
    """Pin the pattern, because planted violations alone cannot pin it.

    An anchored alternation of exactly the names listed above would satisfy
    every planted-violation test while catching nothing else. Comparing the
    pattern itself means a narrowing has to be written twice, deliberately,
    rather than arrived at by relaxing a regex until the suite goes green.
    """
    assert _SPECULATIVE_MODULE_NAMES.pattern == _EXPECTED_SPECULATIVE_PATTERN
