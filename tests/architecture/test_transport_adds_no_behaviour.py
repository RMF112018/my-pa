"""A transport maps. It does not decide, store, fetch, or disclose.

`module-boundaries.md` section 5.7 says the transport adapters "contain no
business or authorization logic beyond invoking application contracts". That is
the kind of sentence a reviewer can only check by reading, and reading does not
scale to the next adapter. These rules check it by parsing, so `adapters/mcp`
and `adapters/cli` are covered by them the day they exist rather than the day
someone remembers.

Four things a transport could grow, and one guard each:

* **an authorization** — naming `authorize`, `evaluate`, a `PolicyRequest`, or a
  `DenialReason` means a decision is being made or read outside the one place
  `application.authorization` keeps it;
* **a disclosure** — assembling a `Disclosure`, a `Coverage`, or a `Trust` means
  the envelope is being built here rather than returned;
* **a store or a provider** — importing `infrastructure`, SQLAlchemy, a driver,
  or a parser means the transport reached past the application;
* **a composition** — naming a concrete implementation means the transport chose
  one, which only a composition root may do.

Each guard is paired with a planted violation, because a guard whose pattern has
been narrowed to nothing still passes.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "my_pa"
ADAPTERS = PACKAGE / "adapters"


def _adapter_modules() -> list[Path]:
    return sorted(ADAPTERS.rglob("*.py"))


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imports(path: Path) -> set[str]:
    """Every dotted import target in `path`, wherever it appears."""
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def _named(path: Path) -> set[str]:
    """Every bare name and attribute name a module mentions.

    Attributes as well as names, so `policy.evaluate(...)` counts even though
    `evaluate` was never imported.
    """
    tree = _tree(path)
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    names |= {
        alias.asname or alias.name.split(".")[-1]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    return names


def _string_literals(path: Path) -> list[str]:
    return [
        node.value
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def _called_attributes(path: Path) -> set[str]:
    return {
        node.func.attr
        for node in ast.walk(_tree(path))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


#: Packages a transport may not reach into. `domain.policy` is named separately
#: from `infrastructure` because the two would be different mistakes: one is a
#: transport that decides, the other is a transport that stores.
FORBIDDEN_PACKAGES = (
    "my_pa.infrastructure",
    "my_pa.bootstrap",
    "my_pa.domain.policy",
    "my_pa.domain.audit",
)

#: Third-party roots that would mean a transport is talking to a store, a
#: provider, or a parser rather than to the application.
FORBIDDEN_ROOTS = frozenset(
    {
        "alembic",
        "asyncpg",
        "boto3",
        "fitz",
        "paramiko",
        "pdfminer",
        "psycopg",
        "psycopg2",
        "pypdf",
        "smbclient",
        "sqlalchemy",
        "sqlmodel",
    }
)

#: Names that mean a decision, a disclosure, or a composition is happening here.
#: `Principal` is deliberately absent: the transport is *handed* one and
#: annotates it, which is the opposite of choosing one. `PrincipalKind` is
#: present, because choosing a kind is choosing an authority.
FORBIDDEN_NAMES = frozenset(
    {
        # a decision
        "authorize",
        "evaluate",
        "PolicyRequest",
        "PolicyDecision",
        "DenialReason",
        "Authorization",
        "PrincipalKind",
        # an audit
        "AuditEvent",
        "AuditOutcome",
        "audit_event_for",
        # a disclosure
        "Disclosure",
        "Coverage",
        "Trust",
        "Freshness",
        "Truncation",
        "disclosure_for",
        "unenrolled_disclosure",
        # `eligible_total` stood here until WP-4B3 deleted the function. A guard
        # naming something that does not exist can never fire, which is a defect
        # this campaign shipped once and caught only in re-review, so the entry
        # goes with the function rather than after it.
        # a composition
        "SqlAlchemyUnitOfWork",
        "SqlAlchemyAuditSink",
        "create_database_engine",
        "create_engine",
        "FixtureSourceProvider",
        # the application's own internals
        "_HANDLERS",
        "_Result",
        "_run",
        "_effective_limits",
    }
)

#: SQL, as a word rather than as a substring, so `select` in prose does not fire.
SQL = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE TABLE|DROP TABLE)\b")


def test_there_are_adapters_to_guard() -> None:
    """Every rule below parametrises over this list; an empty one passes them all.

    Named module by module rather than counted, because a count is satisfied by
    three files in one transport. Each of the three transports has to be here:
    the rules are about what a transport may contain, and a transport the scan
    never opened is a transport no rule below applies to.
    """
    modules = _adapter_modules()
    assert len(modules) >= 3, f"only {len(modules)} adapter modules were found"
    for expected in (
        ADAPTERS / "normalization.py",
        ADAPTERS / "http" / "app.py",
        ADAPTERS / "mcp" / "server.py",
        ADAPTERS / "mcp" / "tools.py",
        ADAPTERS / "cli" / "app.py",
    ):
        assert expected in modules, f"{expected.relative_to(ADAPTERS)} is not being scanned"
    # And every package `__init__` too, which is where the same hole was found
    # twice this campaign: one import in a package initialiser evaded 624
    # architecture tests because nothing enumerated the file it was in.
    for subtree in ("http", "mcp", "cli"):
        assert (ADAPTERS / subtree / "__init__.py") in modules


@pytest.mark.parametrize("path", _adapter_modules(), ids=lambda p: str(p.name))
def test_a_transport_imports_no_store_policy_or_composition_package(path: Path) -> None:
    offending = sorted(
        imported
        for imported in _imports(path)
        if any(imported == name or imported.startswith(f"{name}.") for name in FORBIDDEN_PACKAGES)
    )
    assert not offending, (
        f"{path.relative_to(PACKAGE)} is transport code and imports {offending}; "
        "a transport reaches the application and nothing behind it"
    )


@pytest.mark.parametrize("path", _adapter_modules(), ids=lambda p: str(p.name))
def test_a_transport_imports_no_driver_orm_or_parser(path: Path) -> None:
    offending = sorted({name.split(".")[0] for name in _imports(path)} & FORBIDDEN_ROOTS)
    assert not offending, (
        f"{path.relative_to(PACKAGE)} is transport code and imports {offending}; "
        "SQL, drivers, and parsers live behind the ports"
    )


@pytest.mark.parametrize("path", _adapter_modules(), ids=lambda p: str(p.name))
def test_a_transport_names_no_decision_disclosure_or_implementation(path: Path) -> None:
    offending = sorted(_named(path) & FORBIDDEN_NAMES)
    assert not offending, (
        f"{path.relative_to(PACKAGE)} is transport code and names {offending}; "
        "authorization, disclosure, and composition happen behind `invoke`"
    )


@pytest.mark.parametrize("path", _adapter_modules(), ids=lambda p: str(p.name))
def test_a_transport_contains_no_sql(path: Path) -> None:
    offending = [
        text
        for text in _string_literals(path)
        if SQL.search(text) and not (path.name == "remote.py" and text == "DELETE")
    ]
    assert not offending, f"{path.relative_to(PACKAGE)} contains SQL"


def test_the_application_is_reached_through_invoke_and_only_invoke() -> None:
    """The positive half: a transport that called nothing would pass every rule above.

    `ApplicationService` has exactly one public method — `tests/policy` asserts
    that — so the check that matters is that the transport calls it, and that it
    reaches no private one.
    """
    called: set[str] = set()
    for path in _adapter_modules():
        called |= _called_attributes(path)
    assert "invoke" in called, "no adapter calls the application at all"
    assert not called & {"_run", "_capabilities_get", "_sources_list"}


# ---- planted violations ------------------------------------------------------


PLANTED = [
    ("from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink", "package"),
    ("import my_pa.bootstrap.settings", "package"),
    ("from my_pa.domain.policy.decision import evaluate", "package"),
    ("import sqlalchemy", "root"),
    ("from psycopg import connect", "root"),
    ("import pypdf", "root"),
]


@pytest.mark.parametrize(("statement", "guard"), PLANTED, ids=lambda v: str(v))
def test_the_import_guards_catch_a_planted_import(
    tmp_path: Path, statement: str, guard: str
) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text(f"{statement}\n", encoding="utf-8")
    imported = _imports(planted)
    if guard == "package":
        assert any(
            name == forbidden or name.startswith(f"{forbidden}.")
            for name in imported
            for forbidden in FORBIDDEN_PACKAGES
        ), f"{statement!r} escaped the package guard"
    else:
        assert {name.split(".")[0] for name in imported} & FORBIDDEN_ROOTS, (
            f"{statement!r} escaped the dependency guard"
        )


@pytest.mark.parametrize(
    "source",
    [
        "from my_pa.application.authorization import authorize\n",
        "def go(policy: object) -> object:\n    return policy.evaluate(1)\n",
        "def go() -> object:\n    from my_pa.contracts.v1.disclosure import Coverage\n\n"
        "    return Coverage\n",
        "def wire(engine: object) -> object:\n    return SqlAlchemyUnitOfWork(engine)\n",
    ],
    ids=["imported", "called-as-attribute", "imported-inside-a-function", "instantiated"],
)
def test_the_behaviour_guard_catches_a_planted_decision(tmp_path: Path, source: str) -> None:
    """Each of the four ways a decision could arrive, planted."""
    planted = tmp_path / "planted.py"
    planted.write_text(source, encoding="utf-8")
    assert _named(planted) & FORBIDDEN_NAMES, f"a planted decision escaped:\n{source}"


def test_the_sql_guard_catches_a_planted_statement(tmp_path: Path) -> None:
    planted = tmp_path / "planted.py"
    planted.write_text('QUERY = "SELECT text FROM knowledge.extractions"\n', encoding="utf-8")
    assert [text for text in _string_literals(planted) if SQL.search(text)]


def test_the_sql_guard_does_not_fire_on_prose(tmp_path: Path) -> None:
    """The narrowing is deliberate: a guard that flagged a docstring would be turned off."""
    planted = tmp_path / "planted.py"
    planted.write_text('"""The caller can select a representation."""\n', encoding="utf-8")
    assert not [text for text in _string_literals(planted) if SQL.search(text)]
