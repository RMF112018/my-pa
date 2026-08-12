"""`apps/cli/` holds operator commands. None of them is a further capability.

The capability set is closed by `domain/identity/operation.py`, and an operator
command that quietly joined it would be the widest hole this package could open:
`audit_events.capability` is constrained to exactly that set, so a new member
would have to be admitted to the contract, the audit table, and the policy
decision at once — or, worse, would run beside them without any of the three.

**No count is written here, and that is deliberate.** This docstring stated the
old size three times, unchanged, through the pull request that widened the set —
in the one module whose entire subject is that closure — and the sentence below
about a prose assertion is exactly why nothing caught it. The size belongs to
`Capability`; where a message below needs it, it is derived from `Capability` at
the point of use.

**The check is mechanical, not asserted.** Every claim below is decided by
reading the command with `ast`, so it holds against what the file says rather
than against what a docstring says about it. A prose assertion in the module
under test cannot fail; this can.

**Two commands, not one.** `sources.py` came first, with `D-42`. `health.py`
joined it with `D-62`, and it is the one a guard written for a single file would
have missed — the pattern this campaign keeps catching is a guarantee proven in
one shape and not in its neighbour. Its permitted persistence set is **empty**,
which is a stronger claim than `sources.py`'s rather than a weaker one: the probe
reads a server's version and its Alembic revision and reaches no product table at
all, so any persistence name arriving in it is a write surface appearing in a
program that has none. `migration.py` is deliberately *not* here: it is the
migration control plane and writes to `migration_runs` by design, so it is
governed by `tests/contract/test_cli_transport.py`'s disjointness rule instead.

**Each rule has a planted violation in this file.** A guard whose set has been
narrowed to nothing keeps reporting success on every module in the tree, which is
a defect this campaign has shipped once already. The three planted fixtures are
read by the *same* functions that read the real module, so narrowing a rule
breaks its plant in the same commit.

What the three rules are for, in the order they matter:

1. *No `my_pa.application`, no `my_pa.adapters`.* Those are the two packages
   through which a capability is invoked. Without a path to either, this command
   cannot invoke one however it is called.
2. *A named subset of the persistence writers.* Registering a source and
   observing its root are the two writes this command exists to perform, and
   reading the `sources` rows is the third thing it does. It must not be able to
   write an enrollment, a job, an extraction, or a quarantine, and the way to
   know that is to enumerate what it may name.
3. *No `Capability`.* The enum is how a capability is identified everywhere in
   this tree. A command that never mentions it cannot be dispatched as one, and
   cannot record an audit event under one either.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from my_pa.domain.identity.operation import Capability

ROOT = Path(__file__).resolve().parents[2]

#: The forbidden packages of rule 1, by import prefix.
FORBIDDEN_PACKAGES = ("my_pa.application", "my_pa.adapters")

#: Every name rule 2 permits `sources.py` to import from persistence.
#:
#: Four readers and writers, and **no table declaration**. This set briefly held
#: `sources`, the `Table` object, because the command's listing selected from it
#: directly and `infrastructure.persistence.registry` had no reader for the whole
#: set — `get_source` answers about one. That was a documented workaround and it
#: is now closed: a `Table` is a *write* surface, since `insert()` and `update()`
#: reach through it exactly as `select()` does, so admitting one to let an
#: operator command perform a read widened this rule by a write it never needed.
#: `registry.all_sources` is the reader that replaced it, and this set is back to
#: naming only functions whose own signatures decide what they may do. Nothing
#: about an enrollment, a job, an extraction, or a quarantine is reachable
#: through any of them.
PERMITTED_PERSISTENCE_NAMES = frozenset(
    {"register_source", "observe_object", "get_source", "all_sources"}
)

#: Every name rule 2 permits `clients.py` to import from persistence.
#:
#: Three writers and readers over the client plane, plus `capture_context`, which
#: is the guard's own constructor rather than a store: this command has to name
#: the Principal it is acting for in order to be scoped by it, and
#: `principal_scope` is where that translation lives. No table declaration, for
#: the reason `sources.py`'s set holds none — a `Table` is a write surface
#: whatever it is used for — and nothing about a capture, a version, a job, an
#: enrollment, or an audit event is reachable through any of the four.
PERMITTED_CLIENT_NAMES = frozenset(
    {"register_client", "revoke_client", "clients_of", "capture_context"}
)

#: The commands these rules govern, and — for rule 2 — exactly what each may name
#: out of `infrastructure.persistence`.
#:
#: `health.py`'s empty set is the whole of its claim. It composes an engine,
#: calls `healthcheck`, and asks Alembic what revision the server is at; it names
#: no table, no reader, and no writer, so this rule is what keeps it that way.
#:
#: `clients.py` (WP-10) is the command that mints credentials, which makes it the
#: one these rules most need to hold: a command that could reach the application
#: while also minting the credentials that authenticate future requests would be
#: the widest hole in the tree. It names four persistence functions and no
#: capability at all.
COMMANDS = {
    "sources.py": PERMITTED_PERSISTENCE_NAMES,
    "health.py": frozenset(),
    "clients.py": PERMITTED_CLIENT_NAMES,
}

#: The identifier rule 3 forbids anywhere in the file.
FORBIDDEN_IDENTIFIER = "Capability"

PERSISTENCE = "my_pa.infrastructure.persistence"


def _command(name: str) -> Path:
    return ROOT / "apps" / "cli" / name


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(path: Path) -> set[str]:
    """Every dotted module a file imports, wherever the import appears.

    `ast.walk` rather than a scan of the module body, so an import inside a
    function counts. The same shape `test_dependency_direction._imported_modules`
    uses, and for the same reason.
    """
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def _persistence_names(path: Path) -> set[str]:
    """Every name a file imports out of `infrastructure.persistence`.

    Keyed on the module the name came *from*, so `from …persistence.registry
    import register_source` contributes `register_source` and
    `import my_pa.infrastructure.persistence.enrollment` contributes the module
    itself — a whole module reached by attribute is not a narrower grant than a
    name reached by `from`, and reporting it as nothing would be the hole.
    """
    names: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module == PERSISTENCE or node.module.startswith(f"{PERSISTENCE}."):
                names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == PERSISTENCE or alias.name.startswith(f"{PERSISTENCE}."):
                    names.add(alias.name)
    return names


def _identifiers(path: Path) -> set[str]:
    """Every identifier a file mentions: names, attributes, and imported aliases.

    Three node kinds rather than one, because `Capability` can arrive as a bare
    name, as `operation.Capability`, or as an alias in an import — and a rule
    that read only `ast.Name` would miss two of the three ways to reach it.
    """
    found: set[str] = set()
    for node in ast.walk(_tree(path)):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.alias):
            found.add(node.name.rsplit(".", 1)[-1])
            if node.asname:
                found.add(node.asname)
    return found


@pytest.mark.parametrize("command", sorted(COMMANDS), ids=lambda value: str(value))
def test_the_command_exists_and_is_read(command: str) -> None:
    """Guard the three rules below: each is an emptiness test on a parsed file.

    A missing or unparsed file would make all three pass without deciding
    anything, so what is asserted here is that the file has real imports and real
    identifiers in it.
    """
    path = _command(command)
    assert path.is_file(), f"{path} is gone; the three rules below decide nothing"
    imported = _imported_modules(path)
    assert len(imported) >= 5, f"only {len(imported)} imports parsed out of {command}"
    assert len(_identifiers(path)) >= 20


def test_the_persistence_rule_decides_something_for_the_command_that_writes() -> None:
    """Rule 2 is a subset test, and a subset test over an empty set is free.

    `health.py`'s permitted set is empty *and* it imports no persistence name, so
    for that command the rule holds trivially — which is exactly the state the
    claim describes. This asserts the other command really does import from
    persistence, so the rule below is deciding something for at least one of
    them rather than passing over two empty sets.
    """
    named = _persistence_names(_command("sources.py"))
    assert named, "sources.py imports no persistence name; the rule below decides nothing"
    assert named <= PERMITTED_PERSISTENCE_NAMES


@pytest.mark.parametrize("command", sorted(COMMANDS), ids=lambda value: str(value))
def test_the_command_reaches_no_capability_path(command: str) -> None:
    """Rule 1: no `my_pa.application` and no `my_pa.adapters`, at any depth."""
    offending = sorted(
        imported
        for imported in _imported_modules(_command(command))
        if any(
            imported == package or imported.startswith(f"{package}.")
            for package in FORBIDDEN_PACKAGES
        )
    )
    assert not offending, (
        f"apps/cli/{command} imports {offending}; an operator command that can "
        "reach the application can invoke a capability, which is what makes it one"
    )


@pytest.mark.parametrize("command", sorted(COMMANDS), ids=lambda value: str(value))
def test_the_command_names_only_the_writers_it_needs(command: str) -> None:
    """Rule 2: the persistence names it imports are inside the permitted set."""
    beyond = sorted(_persistence_names(_command(command)) - COMMANDS[command])
    assert not beyond, (
        f"apps/cli/{command} imports {beyond} from persistence; each command names "
        "only the readers and writers its own job needs, and no others"
    )


@pytest.mark.parametrize("command", sorted(COMMANDS), ids=lambda value: str(value))
def test_the_command_never_names_a_capability(command: str) -> None:
    """Rule 3: the word does not appear, so it cannot become one by accident."""
    assert FORBIDDEN_IDENTIFIER not in _identifiers(_command(command)), (
        f"apps/cli/{command} names `Capability`; the set is closed at {len(Capability)} "
        "and an operator command is configuration rather than a member of it"
    )


# ---- the three plants ---------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "from my_pa.application.service import ApplicationService",
        "import my_pa.adapters.cli",
        "from my_pa.adapters import cli",
    ],
    ids=lambda value: str(value),
)
def test_the_capability_path_rule_catches_a_planted_import(tmp_path: Path, statement: str) -> None:
    """Rule 1 fires on a planted reach into the application or a transport."""
    planted = tmp_path / "planted.py"
    planted.write_text(f"{statement}\n", encoding="utf-8")
    offending = {
        imported
        for imported in _imported_modules(planted)
        if any(
            imported == package or imported.startswith(f"{package}.")
            for package in FORBIDDEN_PACKAGES
        )
    }
    assert offending, f"{statement!r} escaped the capability-path rule"


@pytest.mark.parametrize(
    "statement",
    [
        "from my_pa.infrastructure.persistence.enrollment import accept_enrollment",
        "from my_pa.infrastructure.persistence.jobs import enqueue_job",
        "from my_pa.infrastructure.persistence.extraction import record_outcome",
        "import my_pa.infrastructure.persistence.extraction",
    ],
    ids=lambda value: str(value),
)
def test_the_persistence_rule_catches_a_planted_writer(tmp_path: Path, statement: str) -> None:
    """Rule 2 fires on a planted writer, including one reached as a whole module."""
    planted = tmp_path / "planted.py"
    planted.write_text(f"{statement}\n", encoding="utf-8")
    beyond = _persistence_names(planted) - PERMITTED_PERSISTENCE_NAMES
    assert beyond, f"{statement!r} escaped the permitted-persistence rule"


@pytest.mark.parametrize(
    "source",
    [
        "from my_pa.domain.identity.operation import Capability\n",
        "from my_pa.domain.identity import operation\n\nWHAT = operation.Capability\n",
        "from my_pa.domain.identity.operation import Capability as Op\n",
        "def which(value: object) -> object:\n    return Capability(value)\n",
    ],
    ids=lambda value: str(value)[:40],
)
def test_the_capability_name_rule_catches_a_planted_mention(tmp_path: Path, source: str) -> None:
    """Rule 3 fires on each of the four ways the enum can be named.

    Including the aliased import, which is the one a rule reading only `ast.Name`
    would let through, and the attribute access, which is the one a rule reading
    only imports would.
    """
    planted = tmp_path / "planted.py"
    planted.write_text(source, encoding="utf-8")
    assert FORBIDDEN_IDENTIFIER in _identifiers(planted), f"{source!r} escaped the name rule"
