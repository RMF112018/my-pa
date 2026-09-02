"""A project-scoped name and a global identity never derive from one another.

`20260830_f5b06925857e` writes the rule into the DDL text of the column itself:

    -- The name this participant is known by ON THIS PROJECT --
    -- project-scoped fact, never global identity. Nothing may ever
    -- write this value to entities.display_name or
    -- entities.canonical_name, and nothing may read either of those
    -- columns into this one.

That revision's docstring calls it *"the single most important semantic boundary
in this work package"*; `persistence.tables` restates it above the column and
`my_pa.domain.relationship.entity.EntityProjectParticipation` states it
canonically. **Until this module existed all four statements were prose.** A
rule left as prose in a merged migration is `D-81`, and
`test_no_revision_derives_a_closed_set_from_an_enum.py` is the guard that exists
because of the last one; this closes the same class for this boundary.

The prohibition is **bidirectional** and names **exactly two** counterpart
columns: `knowledge.entities.display_name` and `knowledge.entities.canonical_name`.
It does not name the legacy `entity_assignments` table, and neither does this
module: that table has no name-bearing column at all, so a rule about it would
quantify over nothing.

## What was and was not already checked

`tests/unit/test_project_entity_participation_domain.py` proves the *dataclass*
carries no field, property or attribute named for a global identity. That is a
statement about the **shape** of `EntityProjectParticipation` and it is a good
one, but a shape says nothing about where a value came from:
`project_display_name=entity.display_name` satisfies it exactly.
`tests/database/test_project_entity_participation_isolation.py` proves the
column survives a merge, but it writes its own raw SQL and so never exercises
the production writer, and it checks one direction only. Neither would redden if
production code populated `project_display_name` from `entities.display_name`,
and nothing anywhere would redden for the reverse direction.

## Three rules, at expression granularity, because module granularity is useless

`infrastructure/persistence/entity.py` is six and a half thousand lines, owns
both participation write sites, and names `display_name` or `canonical_name` on
thirty-eight of its lines in the course of doing its unrelated job; `tables.py`
and the domain module do the same. A rule of the form "no module mentions both" would
fire on every module that matters and would have to be weakened until it fired
on nothing. So every rule here reads a **single bound expression** or a **single
executed statement**.

1. **Provenance of the project-scoped name.** Every binding of
   `project_display_name` — a keyword argument at any call, or a string key in
   any dict literal — is read as an expression, and no `Name`, `Attribute`,
   `Subscript` key or string constant inside it may contain `display_name` or
   `canonical_name` other than `project_display_name` itself. The binding
   universe is deliberately wider than "`EntityProjectParticipation(...)` and
   `insert(entity_project_participations).values(...)`": the persistence write
   site does not pass the keyword to `values()` at all, it passes it to a
   `_bound(...)` helper *inside* `values()`, and a rule shaped around the two
   constructs named in the prose would have walked straight past it.
2. **The reverse direction**, which today is guarded by nothing at all, not even
   the raw-SQL database test. Every binding of `display_name` or
   `canonical_name` — which is every `Entity(...)` construction, every
   `insert`/`update` on `entities`, and fifty-odd other bindings besides — is
   read the same way, and no expression bound to one may derive from a name
   containing `project_display_name`.
3. **Executed SQL text**, which is the direction an expression rule structurally
   cannot see: a bulk backfill is a single string, and no `Attribute` node in
   this process ever represents the columns it names. Every string literal and
   every assembled string in every file that can hand a statement to the server,
   plus every statement of the six `migrations/sql/*.sql` files three revisions
   execute, is read for a statement that names the participation column or table
   *and* a bare global-identity column.

**Rule 4 is the anti-vacuity rule** and it is stated as equalities, not floors:
the write-site and read-site populations are frozen as exact sets, so a fourth
write site or a fourth reader reddens here and has to be argued against this
boundary rather than merged past it. `D-26`, `D-44` and `D-80` are three
vacuous guards this repository has already had to find; each rule below is
therefore paired with a plant that asserts it fires, and with a negative control
that asserts it does not fire on the constructs the live surface really uses.

## Two false positives are registered by name rather than matched around

* **`core.daily_brief_change_events`** — a table ported from the legacy SQLite
  database by `1e6c0a94f3b7`, declared in `migrations/sql/target_tables.up.sql`,
  carrying a `project_display_name` column of its own that has nothing to do
  with `knowledge.entity_project_participations`. It is registered in
  `PORTED_LEGACY_PROJECT_NAME_TABLES` and measured by
  `test_the_ported_legacy_project_name_column_is_the_one_registered`, which also
  records that the statement declaring it carries no bare global-identity column
  — so the exemption costs nothing rather than being taken on trust.
* **`a_project_participation_display_name_is_not_blank`** — the CHECK constraint
  the boundary revision names after the column it constrains. A substring rule
  on `display_name` reports it forever. `global_identity_tokens` therefore
  matches `display_name` and `canonical_name` only as **whole identifiers**,
  which is also the faithful reading of a prohibition that names two columns:
  a statement that reads `knowledge.entities.display_name` spells that token
  exactly. `test_the_statement_rule_does_not_fire_on_the_declaration_that_states_it`
  asserts the constraint name is not matched.

SQL comments are stripped before any statement is read, and **that is
load-bearing in this module in a way it is not in most**: the six lines quoted
at the top of this docstring live inside the executed `CREATE TABLE` text, so an
unstripped scan reports the declaration of the rule as a violation of it. The
same test asserts both halves of that — the tokens are present before stripping
and absent after — so the stripping is measured rather than assumed.

## What this guard does NOT close

Stated plainly, because a guard that is later cited as closing the whole class
would be worse than no guard. Every rule here reads one expression or one
string. It therefore does **not** catch:

* **a value laundered through a local variable** — `name = entity.display_name`
  on one line and `project_display_name=name` on the next is green here. Rule 1
  reads the binding, not the definition that reaches it; this module performs no
  reaching-definitions analysis and does not claim to.
* **a `**kwargs` splat**, or a dict assembled anywhere other than the literal
  that binds the key. `EntityProjectParticipation(**payload)` binds no keyword
  this module can see.
* **a mapping built elsewhere** — a row adapter, a `dataclasses.replace`, a
  `model_dump()` fed into a constructor, or any helper that copies fields by
  name.
* **SQL assembled at runtime** from values that are not string constants.
  `folded` reconstructs concatenation, f-string constant parts and
  `str.join` over literals, and drops substituted values rather than guessing
  them, so a table or column name arriving through a parameter is not
  reconstructed and a token split across a substitution is not rejoined.
* **anything under `tests/`**, which is not swept: the fixtures legitimately
  write both columns with raw SQL, and sweeping them would force the rule to be
  weakened until it stopped saying anything about `src/`.

What it does close is the whole of the surface as it is written today — every
write site, every reader, and every executed statement — and it makes a fourth
one impossible to add silently. The residual above is the honest boundary of a
syntactic rule, and closing it would take a dataflow analysis this repository
does not have.

Nothing here opens a connection, imports the persistence layer, or touches a
database. It parses source and reads text.

The `ast` machinery below — `_docstring_nodes`, `_string_literals`, `folded`,
`_assembled_strings`, `_statement_texts` — is the same approach
`test_no_vector_retrieval_exists.py` uses for the same problem, re-stated here
rather than imported: no guard in `tests/architecture/` imports from another,
and each is readable on its own.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Final

import pytest

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"
APPS: Final = ROOT / "apps"
MIGRATIONS: Final = ROOT / "migrations"
REVISIONS: Final = MIGRATIONS / "versions"
SQL_DIRECTORY: Final = MIGRATIONS / "sql"

#: The revision that declares the column and states the boundary in its DDL.
#: Named so the control that reads the declaration reads the real one.
BOUNDARY_REVISION: Final = (
    REVISIONS / "20260830_f5b06925857e_add_entity_project_participations_and_.py"
)

#: The project-scoped column. Project fact, never global identity.
PROJECT_SCOPED_COLUMN: Final = "project_display_name"

#: The table it belongs to.
PARTICIPATION_TABLE: Final = "entity_project_participations"

#: The two counterpart columns the prohibition names, and the only two. Not
#: `mention_display_name`, which is `entity_mentions`' own observed-text column
#: and a different question; not `entity_assignments`, which has no name-bearing
#: column to confuse with either. A rule wider than the prose would be a rule
#: nobody wrote down.
GLOBAL_IDENTITY_COLUMNS: Final = ("display_name", "canonical_name")

#: Tables outside `knowledge` that carry a `project_display_name` column of
#: their own, as an exact registry.
#:
#: `core.daily_brief_change_events` is ported from the legacy SQLite database by
#: `1e6c0a94f3b7` and its DDL lives in `migrations/sql/target_tables.up.sql`
#: among three and a half thousand statements. Its `project_display_name` is
#: legacy data shape, unrelated to `knowledge.entity_project_participations`,
#: and any text sweep over that directory meets it. It is written down rather
#: than matched around, and
#: `test_the_ported_legacy_project_name_column_is_the_one_registered` measures
#: the claim: the statement declaring it names no bare global-identity column,
#: so nothing crosses the boundary there whether or not it is exempt.
PORTED_LEGACY_PROJECT_NAME_TABLES: Final = ("core.daily_brief_change_events",)

#: The SQL identifier the boundary revision names its CHECK constraint. It ends
#: in `display_name` and is not a reference to `entities.display_name`; it is
#: the reason `global_identity_tokens` matches whole identifiers only, and it is
#: asserted directly rather than left as an unexplained narrowing.
PARTICIPATION_CHECK_CONSTRAINT: Final = "a_project_participation_display_name_is_not_blank"

#: Every place in `src/`, `apps/` and `migrations/` that binds a value to
#: `project_display_name`, as an exact set.
#:
#: **This is the population rule 1 quantifies over, and it is frozen so that a
#: fourth write site reddens here rather than arriving unread.** Three sites,
#: and each is a straight copy of the field it is named after: the use case
#: copies the command, the writer copies the domain record, the row adapter
#: copies the column. None of the three has any business reading a global
#: identity, which is exactly why a fourth needs an argument.
PARTICIPATION_WRITE_SITES: Final = (
    "src/my_pa/application/entity_record_families.py: "
    "project_display_name=command.project_display_name",
    "src/my_pa/infrastructure/persistence/entity.py: "
    "project_display_name=participation.project_display_name",
    "src/my_pa/infrastructure/persistence/entity.py: "
    "project_display_name=str(row.project_display_name)",
)

#: Every place that reads the column by name, as an exact set with multiplicity.
#:
#: Frozen for the same reason and against a different failure: a *reader* is how
#: the value escapes its project scope. The three `.c.` reads are the search
#: predicate and the two halves of the browse projection, which flow only into
#: `EntitySummary.project_roles`; `ports.py` composes that string and takes the
#: name as a parameter; `self.project_display_name` is the domain record's own
#: blank check. Written as unparsed expressions rather than line numbers, so an
#: edit elsewhere in a six-thousand-line module does not redden this.
PARTICIPATION_READ_SITES: Final = (
    "src/my_pa/application/entity_record_families.py: command.project_display_name",
    "src/my_pa/contracts/ports.py: (parameter) project_display_name",
    "src/my_pa/contracts/ports.py: project_display_name",
    "src/my_pa/contracts/ports.py: project_display_name",
    "src/my_pa/domain/relationship/entity.py: self.project_display_name",
    "src/my_pa/infrastructure/persistence/entity.py: "
    "entity_project_participations.c.project_display_name",
    "src/my_pa/infrastructure/persistence/entity.py: "
    "entity_project_participations.c.project_display_name",
    "src/my_pa/infrastructure/persistence/entity.py: "
    "entity_project_participations.c.project_display_name",
    "src/my_pa/infrastructure/persistence/entity.py: participation.project_display_name",
    "src/my_pa/infrastructure/persistence/entity.py: row.project_display_name",
)

#: A SQL comment, in both forms PostgreSQL accepts. Stripped before any
#: statement is read for identifiers, because the boundary revision states the
#: prohibition *inside* the `CREATE TABLE` text it executes and an unstripped
#: scan reports that declaration as a violation of itself. Textual, and it would
#: also strip a `--` that appeared inside a quoted SQL string; no statement in
#: this tree contains one, and the alternative is a SQL parser.
SQL_COMMENT: Final = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)

#: `display_name` or `canonical_name` as a **whole** SQL identifier: not
#: preceded or followed by an identifier character, so `project_display_name`,
#: `mention_display_name`, `actor_display_name` and the CHECK constraint named
#: after the column are all different tokens rather than near-misses that have
#: to be excused one at a time. `entities.display_name` and `e.display_name`
#: both match, because `.` is not an identifier character.
GLOBAL_IDENTITY_TOKEN: Final = re.compile(
    r"(?<![A-Za-z0-9_])(display_name|canonical_name)(?![A-Za-z0-9_])"
)


def _modules() -> tuple[Path, ...]:
    """Every module of the product, the apps, and the migration chain.

    Wider than `src/` on purpose: `migrations/env.py` and the revisions are
    executable code that can construct a domain record or bind a column exactly
    as a runtime module can, and `apps/` is where the operator CLI lives.
    """
    return (
        *sorted(PACKAGE.rglob("*.py")),
        *sorted(APPS.rglob("*.py")),
        *sorted(MIGRATIONS.rglob("*.py")),
    )


def _revision_files() -> tuple[Path, ...]:
    return tuple(sorted(REVISIONS.glob("*.py")))


def _sql_files() -> tuple[Path, ...]:
    """The `.sql` files three revisions read and execute statement by statement."""
    return tuple(sorted(SQL_DIRECTORY.glob("*.sql")))


def _ddl_bearing_files() -> tuple[Path, ...]:
    """Every file in this repository that can hand a statement to the server.

    The revisions and their environment, and every module of `src/` and
    `apps/`: a backfill issued from a runtime module writes the same rows as one
    issued from a migration, and a rule that read only the directory the plant
    was written in would be a rule against the plant.
    """
    return _modules()


def relative(path: Path) -> str:
    """One path as this repository names it, for a message a reader can act on."""
    return str(path.relative_to(ROOT))


def terminal_identifiers(expression: ast.expr) -> tuple[str, ...]:
    """Every name a bound expression reaches for, at the granularity that matters.

    The `id` of each `Name`, the `attr` of each `Attribute`, the key of each
    constant-subscript, and every string constant — so `entity.display_name`,
    `row["display_name"]` and `mapping.get("canonical_name")` are all read as
    naming the column, and `command.project_display_name` is read as naming its
    own.

    Public, because the plants below run it over expressions that really do
    reach for a global identity, which is what makes a zero from the live tree a
    measurement rather than a matcher that matches nothing.
    """
    found: list[str] = []
    for node in ast.walk(expression):
        if isinstance(node, ast.Name):
            found.append(node.id)
        elif isinstance(node, ast.Attribute):
            found.append(node.attr)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append(node.value)
    return tuple(found)


def global_identity_sources(expression: ast.expr) -> tuple[str, ...]:
    """Which names in one expression reach for a global identity.

    Substring containment, so `entity_display_name` and `display_name_of` are
    the same decision as `display_name` — and `project_display_name` is excluded
    by exact equality rather than by a substring rule, because it is the one
    name that legitimately contains the forbidden one.
    """
    return tuple(
        sorted(
            {
                name
                for name in terminal_identifiers(expression)
                if any(column in name for column in GLOBAL_IDENTITY_COLUMNS)
                and name != PROJECT_SCOPED_COLUMN
            }
        )
    )


def project_name_sources(expression: ast.expr) -> tuple[str, ...]:
    """Which names in one expression reach for the project-scoped name."""
    return tuple(
        sorted({name for name in terminal_identifiers(expression) if PROJECT_SCOPED_COLUMN in name})
    )


def _bindings(path: Path, names: frozenset[str]) -> list[tuple[int, str, ast.expr]]:
    """Every expression one module binds to one of `names`, however it is bound.

    A keyword argument at any call — which covers a dataclass construction, a
    Core `values()`, and the `_bound(...)` helper the participation writer calls
    *inside* `values()` — and a string key in any dict literal, which covers a
    payload handed to `execute` or to a mapping-shaped writer.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, str, ast.expr]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg in names:
            found.append((node.value.lineno, node.arg, node.value))
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value in names:
                    found.append((key.lineno, str(key.value), value))
    return found


def _participation_bindings() -> list[tuple[Path, int, ast.expr]]:
    return [
        (path, lineno, value)
        for path in _modules()
        for lineno, _, value in _bindings(path, frozenset({PROJECT_SCOPED_COLUMN}))
    ]


def _global_identity_bindings() -> list[tuple[Path, int, str, ast.expr]]:
    return [
        (path, lineno, name, value)
        for path in _modules()
        for lineno, name, value in _bindings(path, frozenset(GLOBAL_IDENTITY_COLUMNS))
    ]


def _participation_reads() -> list[str]:
    """Every place the project-scoped column is read or accepted by name."""
    found: list[str] = []
    for path in _modules():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute) and node.attr == PROJECT_SCOPED_COLUMN) or (
                isinstance(node, ast.Name)
                and node.id == PROJECT_SCOPED_COLUMN
                and isinstance(node.ctx, ast.Load)
            ):
                found.append(f"{relative(path)}: {ast.unparse(node)}")
            elif isinstance(node, ast.arg) and node.arg == PROJECT_SCOPED_COLUMN:
                found.append(f"{relative(path)}: (parameter) {node.arg}")
    return sorted(found)


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """Every string constant that is a docstring, by identity."""
    found: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            continue
        first = node.body[0] if node.body else None
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            found.add(id(first.value))
    return found


def _string_literals(path: Path, *, executable_only: bool = False) -> list[tuple[int, str]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    docstrings = _docstring_nodes(tree) if executable_only else set()
    return [
        (node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and id(node) not in docstrings
    ]


def folded(node: ast.expr) -> str | None:
    """The string one expression is known to produce, or `None` if it is not one.

    Adjacent literals need nothing here — CPython's parser joins them before
    this file sees them. Concatenation stays a `BinOp`, an f-string stays a
    `JoinedStr` whose constant parts are separate nodes, and `"".join((...))`
    stays a `Call` over literals that are each innocent; all three are how a
    statement gets written without any one literal spelling it.

    A substituted value is dropped rather than guessed at, which makes the fold
    an under-approximation and is one of the residuals this module's docstring
    states: `f"SELECT {column} FROM t"` folds to `SELECT  FROM t`.
    """
    if isinstance(node, ast.Constant):
        return node.value if isinstance(node.value, str) else None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        left, right = folded(node.left), folded(node.right)
        return None if left is None or right is None else left + right
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value
            for part in node.values
            if isinstance(part, ast.Constant) and isinstance(part.value, str)
        )
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "join"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.List | ast.Tuple)
    ):
        separator = folded(node.func.value)
        parts = [folded(item) for item in node.args[0].elts]
        if separator is not None and all(part is not None for part in parts):
            return separator.join(part for part in parts if part is not None)
    return None


def _assembled_strings(path: Path) -> list[tuple[int, str]]:
    """Every string a module builds, including the ones no single literal spells."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assembled: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp | ast.JoinedStr):
            text = folded(node)
            if text:
                assembled.append((node.lineno, text))
    return assembled


def _statement_texts(path: Path) -> list[tuple[int, str]]:
    """Every string one file could execute, per literal and per assembly.

    Docstrings are excluded, and here the exclusion is not a convenience: the
    boundary revision's own docstring states the prohibition in English, naming
    both forbidden columns beside the participation table. A sweep that read
    prose would report the paragraph that states the rule, and the vocabulary
    would have to be narrowed until it survived — which is how a guard loses the
    words that matter. A docstring executes nothing.
    """
    return [*_string_literals(path, executable_only=True), *_assembled_strings(path)]


def global_identity_tokens(text: str) -> tuple[str, ...]:
    """Which global-identity columns one block of SQL names, comments removed.

    Public, because the plants run it over statements that really do cross the
    boundary and the controls run it over the declaration that states the rule.
    """
    return tuple(sorted(set(GLOBAL_IDENTITY_TOKEN.findall(SQL_COMMENT.sub(" ", text.lower())))))


def crosses_the_boundary(text: str) -> tuple[str, ...]:
    """Which global-identity columns one statement names alongside the project one.

    One symmetric condition covering both directions, because a statement that
    moves a value between the two surfaces has to name both ends of the move:
    a backfill *into* the participation column names
    `entity_project_participations`, and a backfill *out of* it names
    `project_display_name` in its `SELECT`. Empty when the statement is about
    only one of the two surfaces, which is every statement this tree executes.
    """
    stripped = SQL_COMMENT.sub(" ", text.lower())
    subjects = (PARTICIPATION_TABLE, PROJECT_SCOPED_COLUMN)
    if not any(subject in stripped for subject in subjects):
        return ()
    return tuple(sorted(set(GLOBAL_IDENTITY_TOKEN.findall(stripped))))


def _sql_statements(text: str) -> list[str]:
    """One `.sql` file, as the statements the chain executes one at a time."""
    return [statement for statement in text.split(";") if statement.strip()]


def _exempt_legacy_statement(statement: str) -> bool:
    """Whether one `.sql` statement is a registered legacy table and nothing else.

    Narrow on purpose: a statement is excused only if it names a table in
    `PORTED_LEGACY_PROJECT_NAME_TABLES` and does *not* name the participation
    table, so a future statement that touched both would be read rather than
    excused.
    """
    lowered = SQL_COMMENT.sub(" ", statement.lower())
    if PARTICIPATION_TABLE in lowered:
        return False
    return any(
        table.split(".")[-1] in lowered for table in PORTED_LEGACY_PROJECT_NAME_TABLES
    ) and any(table.split(".")[0] in lowered for table in PORTED_LEGACY_PROJECT_NAME_TABLES)


def test_the_universes_this_guard_quantifies_over_are_not_empty() -> None:
    """Guards every rule below: an empty sweep satisfies all of them."""
    assert len(_modules()) >= 100, "the module scan is not reading the tree"
    assert len(_revision_files()) >= 25, "the revision scan is not reading the chain"
    assert len(_sql_files()) == 6, "the ported-DDL scan is not reading the six files"
    assert BOUNDARY_REVISION.is_file(), f"{relative(BOUNDARY_REVISION)} does not exist"
    assert len(_ddl_bearing_files()) >= 100, "the statement scan is not reading the tree"

    statements = [
        statement
        for path in _sql_files()
        for statement in _sql_statements(path.read_text(encoding="utf-8"))
    ]
    assert len(statements) >= 3000, f"only {len(statements)} ported statements were read"

    assert _participation_bindings(), "rule 1 quantifies over nothing"
    assert _global_identity_bindings(), "rule 2 quantifies over nothing"
    assert _participation_reads(), "the read surface was measured as empty"


def test_the_vocabularies_are_closed_at_the_sizes_they_declare() -> None:
    """A vocabulary with no floor passes when it is emptied.

    Exact equalities rather than floors, so growing one is a decision recorded
    here and shrinking one reddens.
    """
    assert len(GLOBAL_IDENTITY_COLUMNS) == 2
    assert len(PORTED_LEGACY_PROJECT_NAME_TABLES) == 1
    assert len(PARTICIPATION_WRITE_SITES) == 3
    assert len(PARTICIPATION_READ_SITES) == 10


def test_the_surface_this_boundary_covers_is_exactly_the_sites_recorded() -> None:
    """Rule 4. A fourth write site or a fourth reader reddens here.

    Stated as equalities over unparsed expressions rather than as floors or line
    numbers: a floor passes when the population grows, and a line number reddens
    when an unrelated edit moves it. The point is that arriving at this boundary
    is a reviewed act — the three writers each copy the field they are named
    after, and every reader flows into `EntitySummary.project_roles` or into the
    domain record's own validation.

    The reverse direction's population is deliberately *not* frozen: it is every
    binding of `display_name` or `canonical_name` in the tree, which grows with
    ordinary identity work that has nothing to do with this boundary. A floor is
    the honest assertion there, and rule 2 reads every one of them anyway.
    """
    written = sorted(
        f"{relative(path)}: {PROJECT_SCOPED_COLUMN}={ast.unparse(value)}"
        for path, _, value in _participation_bindings()
    )
    assert tuple(written) == tuple(sorted(PARTICIPATION_WRITE_SITES)), (
        f"the sites that bind {PROJECT_SCOPED_COLUMN} are {written}. Each one is a "
        "place a project-scoped name is written; a new one has to be argued "
        "against the boundary `20260830_f5b06925857e` declares, not merged past it"
    )

    read = _participation_reads()
    assert tuple(read) == tuple(sorted(PARTICIPATION_READ_SITES)), (
        f"the sites that read {PROJECT_SCOPED_COLUMN} are {read}. A reader is how a "
        "project-scoped fact escapes its project; the recorded ones flow only into "
        "`EntitySummary.project_roles` and the domain record's own blank check"
    )

    assert len(_global_identity_bindings()) >= 40, (
        "the reverse direction is quantified over fewer bindings than the tree has; "
        "rule 2 is reading less than it claims"
    )


def test_no_project_scoped_name_is_bound_from_a_global_identity() -> None:
    """Rule 1: nothing reads `entities.display_name`/`canonical_name` into this column."""
    offending: list[str] = []
    for path, lineno, value in _participation_bindings():
        sources = global_identity_sources(value)
        if sources:
            offending.append(
                f"{relative(path)}:{lineno} {PROJECT_SCOPED_COLUMN}="
                f"{ast.unparse(value)} reaches for {list(sources)}"
            )
    assert offending == [], (
        f"{offending}. `{PROJECT_SCOPED_COLUMN}` is the name a participant is known "
        "by ON THIS PROJECT -- project-scoped fact, never global identity. "
        "`20260830_f5b06925857e` writes that into the column's own DDL and calls it "
        "the single most important semantic boundary in the work package"
    )


def test_no_global_identity_is_bound_from_a_project_scoped_name() -> None:
    """Rule 2: the reverse direction, which nothing else in this tree checks.

    Not the mirror of rule 1 in strength only — in coverage. The raw-SQL
    database test checks one direction; the domain test checks a dataclass
    shape. A use case that promoted a project-scoped name into
    `Entity.canonical_name` would be green everywhere else in this repository.
    """
    offending: list[str] = []
    for path, lineno, name, value in _global_identity_bindings():
        sources = project_name_sources(value)
        if sources:
            offending.append(
                f"{relative(path)}:{lineno} {name}={ast.unparse(value)} reaches for {list(sources)}"
            )
    assert offending == [], (
        f"{offending}. `entities.display_name` and `entities.canonical_name` are "
        "global identity; a name a participant happens to be known by on one project "
        "is not, and promoting one to the other is the half of this boundary no "
        "other test in this tree reads"
    )


def test_no_executed_statement_crosses_the_boundary() -> None:
    """Rule 3: the direction an expression rule structurally cannot see.

    A bulk backfill is one string. No `Attribute` node in this process ever
    represents the columns it names, so rules 1 and 2 are blind to
    `INSERT INTO knowledge.entity_project_participations (project_display_name)
    SELECT display_name FROM knowledge.entities` no matter how carefully they
    read expressions. This reads the statement.
    """
    offending: list[str] = []
    for path in _ddl_bearing_files():
        for lineno, text in _statement_texts(path):
            crossing = crosses_the_boundary(text)
            if crossing:
                offending.append(f"{relative(path)}:{lineno} names {list(crossing)}")
    assert offending == [], (
        f"{offending} name a global-identity column in the same statement as the "
        "project-scoped participation surface. Nothing may write "
        f"`{PROJECT_SCOPED_COLUMN}` into `entities.display_name` or "
        "`entities.canonical_name`, and nothing may read either into it"
    )


def test_no_ported_sql_statement_crosses_the_boundary() -> None:
    """Rule 3's other half: the twenty-four thousand lines three revisions execute.

    `1e6c0a94f3b7` and the two revisions after it write no DDL literal at all;
    they read `migrations/sql/*.sql` and execute it statement by statement, so a
    scan of Python literals reads none of it. The one registered legacy
    exception is excused by name and measured separately.
    """
    offending: list[str] = []
    for path in _sql_files():
        for index, statement in enumerate(_sql_statements(path.read_text(encoding="utf-8"))):
            if _exempt_legacy_statement(statement):
                continue
            crossing = crosses_the_boundary(statement)
            if crossing:
                offending.append(f"{path.name} statement {index} names {list(crossing)}")
    assert offending == [], (
        f"{offending} name a global-identity column in the same ported statement as "
        f"the `{PROJECT_SCOPED_COLUMN}` surface"
    )


def test_the_ported_legacy_project_name_column_is_the_one_registered() -> None:
    """The registered exception, measured rather than trusted.

    Two claims. That `core.daily_brief_change_events` really is the only
    statement in the ported DDL naming a `project_display_name`, so the registry
    is exact; and that the statement declaring it names no bare global-identity
    column, so excusing it costs nothing — the exemption removes a false
    positive rather than a rule.
    """
    declaring: list[str] = []
    for path in _sql_files():
        for statement in _sql_statements(path.read_text(encoding="utf-8")):
            lowered = SQL_COMMENT.sub(" ", statement.lower())
            if PROJECT_SCOPED_COLUMN in lowered:
                declaring.append(f"{path.name}: {lowered.strip()[:60]}")
                assert global_identity_tokens(statement) == (), (
                    f"the ported statement in {path.name} that declares a "
                    f"`{PROJECT_SCOPED_COLUMN}` also names a global-identity column, "
                    "so the registry is excusing a statement that crosses the boundary"
                )
    assert len(declaring) == 1, (
        f"{declaring} declare a `{PROJECT_SCOPED_COLUMN}` in the ported DDL. "
        f"`{PORTED_LEGACY_PROJECT_NAME_TABLES}` records one; a second is a table "
        "somebody has to look at rather than a registry entry to widen"
    )
    assert "daily_brief_change_events" in declaring[0]

    # And the exemption is narrow: naming the legacy table does not excuse a
    # statement that also names the participation surface, which is the only way
    # a registry entry could become a hole.
    assert _exempt_legacy_statement(
        'CREATE TABLE "core"."daily_brief_change_events" ("project_display_name" text)'
    )
    assert not _exempt_legacy_statement(
        "INSERT INTO knowledge.entity_project_participations (project_display_name) "
        "SELECT display_name FROM core.daily_brief_change_events"
    )


@pytest.mark.parametrize(
    "planted",
    [
        "project_display_name=entity.display_name",
        "project_display_name=entity.canonical_name",
        'project_display_name=row["display_name"]',
        "project_display_name=str(entity.display_name)",
        "project_display_name=summary.display_name or command.project_display_name",
        'project_display_name=payload.get("canonical_name", "")',
        "project_display_name=entity_display_name",
    ],
)
def test_the_provenance_rule_fires_on_a_planted_global_identity(planted: str) -> None:
    """The control for rule 1, over the shapes a violation would really be written in.

    The first is the one an author who is not hiding anything would write. The
    rest are the ones a rule that read only `Attribute` nodes, or only the outer
    call, would walk past: a subscript, a wrapper call, a fallback expression, a
    mapping lookup by string, and a local whose *name* carries the column.
    """
    node = ast.parse(f"EntityProjectParticipation({planted})", mode="eval").body
    binding = next(
        keyword for keyword in getattr(node, "keywords", []) if keyword.arg == PROJECT_SCOPED_COLUMN
    )
    assert global_identity_sources(binding.value), planted


def test_the_provenance_rule_does_not_fire_on_the_bindings_the_surface_uses() -> None:
    """The negative control for rule 1: the three live shapes stay green.

    Without this the rule above could be satisfied by a matcher that fired on
    everything, which reddens the tree rather than guarding it — and a guard
    that has to be reverted is worth less than none.
    """
    for legitimate in (
        "project_display_name=command.project_display_name",
        "project_display_name=participation.project_display_name",
        "project_display_name=str(row.project_display_name)",
        'project_display_name=values["project_display_name"]',
    ):
        node = ast.parse(f"EntityProjectParticipation({legitimate})", mode="eval").body
        binding = next(
            keyword
            for keyword in getattr(node, "keywords", [])
            if keyword.arg == PROJECT_SCOPED_COLUMN
        )
        assert global_identity_sources(binding.value) == (), legitimate

    # The dict-literal half of the binding universe, over a real payload shape,
    # because the keyword half would not exercise it.
    payload = ast.parse('{"project_display_name": entity.display_name}', mode="eval").body
    assert isinstance(payload, ast.Dict)
    assert global_identity_sources(payload.values[0]) == ("display_name",)


@pytest.mark.parametrize(
    "planted",
    [
        "display_name=participation.project_display_name",
        "canonical_name=participation.project_display_name",
        "canonical_name=normalize_name(participation.project_display_name)",
        'display_name=row["project_display_name"]',
        "display_name=project_display_name",
    ],
)
def test_the_reverse_rule_fires_on_a_planted_project_scoped_source(planted: str) -> None:
    """The control for rule 2, in the direction nothing else in this tree reads."""
    node = ast.parse(f"Entity({planted})", mode="eval").body
    binding = next(
        keyword
        for keyword in getattr(node, "keywords", [])
        if keyword.arg in GLOBAL_IDENTITY_COLUMNS
    )
    assert project_name_sources(binding.value), planted


def test_the_reverse_rule_does_not_fire_on_the_bindings_the_surface_uses() -> None:
    """The negative control for rule 2, over live identity shapes."""
    for legitimate in (
        "display_name=command.display_name",
        "canonical_name=normalize_name(command.canonical_name)",
        "display_name=str(row.display_name)",
        "canonical_name=normalized",
        "display_name=command.display_name or command.canonical_name",
    ):
        node = ast.parse(f"Entity({legitimate})", mode="eval").body
        binding = next(
            keyword
            for keyword in getattr(node, "keywords", [])
            if keyword.arg in GLOBAL_IDENTITY_COLUMNS
        )
        assert project_name_sources(binding.value) == (), legitimate


def test_the_statement_rule_fires_on_a_planted_backfill(tmp_path: Path) -> None:
    """The control for rule 3, in both directions and over a real file.

    Run over files rather than over strings, because "the sweep opens the file
    and reads what is executed" is the part a string plant would not exercise.
    A revision that assembles its DDL is planted too: a single literal is the
    shape an honest author writes, and the assembled shapes are the ones a
    per-literal sweep reports two innocent halves of.
    """
    revision = tmp_path / "20260901_planted_backfill.py"
    revision.write_text(
        "def upgrade() -> None:\n"
        '    """A docstring naming entities.display_name, which must be ignored."""\n'
        "    op.execute(\n"
        '        "INSERT INTO knowledge.entity_project_participations "\n'
        '        "(participation_id, project_display_name) "\n'
        '        "SELECT entity_id, display_name FROM knowledge.entities"\n'
        "    )\n",
        encoding="utf-8",
    )
    reported = [
        (lineno, crosses_the_boundary(text))
        for lineno, text in _statement_texts(revision)
        if crosses_the_boundary(text)
    ]
    assert reported, "the planted backfill into the participation column was not reported"
    assert reported[0][1] == ("display_name",)

    reverse = tmp_path / "20260901_planted_promotion.py"
    reverse.write_text(
        "def upgrade() -> None:\n"
        "    op.execute(\n"
        '        "UPDATE knowledge.entities SET canonical_name = p.project_display_name "\n'
        '        "FROM knowledge.entity_project_participations p"\n'
        "    )\n",
        encoding="utf-8",
    )
    promoted = [
        crosses_the_boundary(text)
        for _, text in _statement_texts(reverse)
        if crosses_the_boundary(text)
    ]
    assert promoted, "the planted promotion out of the participation column was not reported"
    assert promoted[0] == ("canonical_name",)

    # The assembled shapes, so a statement no single literal spells is read too.
    for source in (
        '"SELECT display_name FROM knowledge.entities INTO " + "entity_project_participations"',
        'f"INSERT INTO knowledge.{table} (project_display_name) SELECT display_name"',
        '" ".join(["INSERT INTO entity_project_participations", "SELECT display_name"])',
    ):
        text = folded(ast.parse(source, mode="eval").body)
        assert text is not None, source
        assert crosses_the_boundary(text) == ("display_name",), source

    # And a planted `.sql` file, because the ported DDL is read by a different
    # sweep that splits on statements rather than on literals.
    planted_sql = tmp_path / "target_backfill.up.sql"
    planted_sql.write_text(
        'CREATE TABLE "core"."documents" ("document_id" text);\n'
        "INSERT INTO knowledge.entity_project_participations (project_display_name) "
        "SELECT canonical_name FROM knowledge.entities;\n",
        encoding="utf-8",
    )
    statements = _sql_statements(planted_sql.read_text(encoding="utf-8"))
    assert len(statements) == 2
    assert crosses_the_boundary(statements[0]) == ()
    assert crosses_the_boundary(statements[1]) == ("canonical_name",)
    assert not _exempt_legacy_statement(statements[1]), (
        "the legacy registry excused a planted backfill; the exemption is not narrow"
    )


def test_the_statement_rule_does_not_fire_on_the_declaration_that_states_it() -> None:
    """The negative control for rule 3, on the statement most likely to break it.

    The boundary revision states the prohibition in SQL comments *inside* the
    `CREATE TABLE` text it executes, and names its CHECK constraint after the
    column. Both halves are measured here rather than assumed:

    * before comment stripping the executed text really does name both forbidden
      columns, so the stripping is load-bearing and not decoration;
    * after stripping it names neither, and the constraint name — which ends in
      `display_name` — is not matched, because the rule matches whole
      identifiers and a substring rule would report it forever.
    """
    executed = [text for _, text in _statement_texts(BOUNDARY_REVISION)]
    assert executed, f"{relative(BOUNDARY_REVISION)} was read as executing nothing"

    unstripped = [
        text
        for text in executed
        if PARTICIPATION_TABLE in text.lower() and GLOBAL_IDENTITY_TOKEN.search(text.lower())
    ]
    assert unstripped, (
        "the boundary revision no longer names both forbidden columns in its "
        "executed DDL, so this control no longer proves comment stripping is "
        "load-bearing -- and the prose that states the rule may have been deleted"
    )

    assert [text for text in executed if crosses_the_boundary(text)] == []

    declaring = [text for text in executed if PARTICIPATION_CHECK_CONSTRAINT in text]
    assert declaring, f"{PARTICIPATION_CHECK_CONSTRAINT} is no longer declared"
    for text in declaring:
        assert global_identity_tokens(text) == (), (
            f"the CHECK constraint `{PARTICIPATION_CHECK_CONSTRAINT}` is being read as "
            "a reference to a global-identity column; it is the constraint on the "
            "project-scoped column and the rule matches whole identifiers for this reason"
        )

    # The same distinction, stated over the near-miss identifiers directly.
    for near_miss in (
        "SELECT project_display_name FROM knowledge.entity_project_participations",
        "SELECT mention_display_name FROM knowledge.entity_mentions",
        'CREATE TABLE "core"."daily_brief_change_events" ("actor_display_name" text)',
        f"CONSTRAINT {PARTICIPATION_CHECK_CONSTRAINT} CHECK (true)",
    ):
        assert global_identity_tokens(near_miss) == (), near_miss

    # And the matcher does fire on the two columns the prohibition names, in the
    # forms a statement writes them, so the zeros above are measurements.
    for named in (
        "SELECT display_name FROM knowledge.entities",
        "SELECT e.canonical_name FROM knowledge.entities e",
        "UPDATE knowledge.entities SET display_name = 'x'",
    ):
        assert global_identity_tokens(named), named
