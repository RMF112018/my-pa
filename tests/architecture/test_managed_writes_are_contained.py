"""Every filesystem write in this repository is one module's, or is registered.

WP-27 adds the first plane in this product that writes bytes to a filesystem.
The guarantee that matters is not "the managed store is careful" — it is that
**the managed store is the only thing that writes at all**, so a future package
asked to "save this file somewhere" cannot quietly acquire a second write path
that no containment check covers.

That guarantee is measured here rather than asserted, and the measurement is a
registry in the shape `test_user_owned_tables_are_partitioned.py` and
`test_principal_partition_is_reached_through_the_guard.py` already use: every
write call site in the tree is either the managed byte store's or is named below
with the reason it is not. Exact set equality in both directions, so a new writer
reddens and a registered writer that disappears reddens too.

**Four things this campaign's last four packages got wrong, and what is done
about each here.**

* *WP-17 exempted directories until the guard was hollow.* There is no directory
  exemption below. Every Python file under `src/`, `apps/`, `scripts/`, `ops/`
  and `migrations/` is walked, and the registry names **call sites**, not
  directories.
* *WP-18's leading block comment hid whole lines from a text guard.* The Python
  detector is `ast`-based, so a comment, a string, a line continuation, or an
  unusual spelling changes nothing about what it sees. The `.sql` detector is
  necessarily textual — SQL is not parsed here — so it is written to survive
  comments: it strips `--` and `/* */` before matching, and
  `test_the_sql_detector_sees_through_a_comment` plants exactly the WP-18 shape.
* *WP-23's guard could not see `.sql` files or migrations at all.* Both are in
  the universe here, and the universe is asserted non-empty and asserted to
  contain the 24,000-line target-schema corpus and the migration that installs
  the managed plane. A guard that walked nothing would fail before it reported
  zero.
* *A guard you author is not a guard you are subject to.* Every rule below has a
  planted control run through the **same** function that reads the real tree, so
  narrowing a rule breaks its control in the same commit.

**What this does not close, stated because an overclaimed control is the defect
this campaign keeps finding.** It reads static call sites. A write performed
through `getattr(os, "renam" + "e")`, through a C extension, or by a subprocess
this repository launches is outside it. Nothing in the tree does any of those,
which is a fact about today rather than a property of the detector.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

ROOT: Final = Path(__file__).resolve().parents[2]

#: Every tree a shipped or operational Python file can live in. `migrations/` and
#: `ops/` are here because WP-23 found 24,419 lines of `.sql` that no guard had
#: ever opened, and a filesystem write executed from a migration is a write.
PYTHON_ROOTS: Final = ("src", "apps", "scripts", "ops", "migrations")

#: The trees whose `.sql` is read. Same reasoning.
SQL_ROOTS: Final = ("migrations", "ops", "scripts", "src")

SKIPPED_DIRECTORIES: Final = frozenset(
    {"__pycache__", ".ruff_cache", ".mypy_cache", "node_modules"}
)

#: The one module allowed to write bytes to a filesystem.
MANAGED_STORE: Final = "src/my_pa/infrastructure/managed_document_stores/filesystem/store.py"

#: Modules other than the managed byte store that call a filesystem-write API,
#: with what each writes and why it is not the managed plane.
#:
#: **Not an exemption list.** An entry is a claim that this call site writes to a
#: location its *caller* named explicitly on a command line, that the location is
#: a build or review artifact rather than user content, and that no managed root
#: and no source root can reach it. A module added here is a decision someone has
#: to write down.
REGISTERED_WRITERS: Final[dict[str, str]] = {
    "ops/nas/remote/render-cloudflared-config.py": (
        "writes a non-secret tunnel configuration to an explicit operator output path and "
        "refuses overwrite; it is deployment configuration, not user or managed content."
    ),
    "src/my_pa/infrastructure/apple_transport_agent.py": (
        "writes only NAS-issued grant metadata and its content digest receipt into an "
        "absolute, existing, owner-only Mac journal; the constructor rejects symlinks "
        "and group/other access, and the journal contains no Apple payload bytes."
    ),
    "src/my_pa/infrastructure/apple_source_host.py": (
        "writes bounded configuration, grant, and checkpoint JSON only inside a "
        "fresh process-private temporary directory for one Apple host invocation; "
        "the directory is not caller-selected and cannot be a managed or source root."
    ),
    "src/my_pa/infrastructure/migration/sql_files.py": (
        "writes the rendered target-schema DDL to a path the caller supplies. A "
        "review artifact for `scripts/migration/generate_target_schema.py`; it "
        "holds no user content, reads no managed root, and is never reached from "
        "a request path."
    ),
    "scripts/migration/generate_target_schema.py": (
        "the operator script that renders that DDL, writing under an explicit `--output` directory."
    ),
    "scripts/migration/build_disposition_registry.py": (
        "writes the migration disposition registry to an explicit output path."
    ),
    "scripts/migration/profile_source.py": (
        "writes a source profile to an explicit output path. Migration tooling, "
        "run by an operator against a legacy corpus."
    ),
    "scripts/migration/reconcile.py": (
        "writes a reconciliation report to an explicit output path."
    ),
    "ops/nas/write-candidate-manifest.py": (
        "writes only a non-deployable image manifest into the operator-selected "
        "candidate artifact directory; it never reads or writes personal or managed bytes."
    ),
    "ops/nas/write-image-metadata.py": (
        "writes only Docker image identity metadata into the operator-selected "
        "candidate artifact directory; it never reads or writes personal or managed bytes."
    ),
    "ops/nas/write-operator-candidate.py": (
        "writes only non-admitted operator-image identity evidence into the explicit "
        "candidate artifact directory; it never reads or writes personal or managed bytes."
    ),
    "ops/nas/admit-operator-runtime.py": (
        "writes only a new root-controlled operator-runtime admission to an explicit "
        "operator path; it contains tool, image, repository, and engine identities only."
    ),
    "ops/nas/generate-postgres-resources.py": (
        "writes only engine-bound PostgreSQL admission evidence to an explicit, new "
        "owner-only operator path; it never reads or writes personal or managed bytes."
    ),
    "ops/nas/generate-runtime-admission.py": (
        "writes only engine-bound runtime identity evidence to an explicit, new "
        "owner-only operator path; it never reads or writes personal or managed bytes."
    ),
    "ops/nas/generate-postgres-bootstrap-admission.py": (
        "writes only engine-bound PostgreSQL bootstrap identity evidence to an explicit, new "
        "root-controlled operator path; it contains no database password or personal bytes."
    ),
    "ops/nas/run_synthetic_acceptance.py": (
        "writes only synthetic pytest receipt digests into an explicit fresh evidence "
        "directory; it neither reads nor records personal or managed-document bytes."
    ),
    "ops/nas/nas10_acceptance_gate.py": (
        "writes only an unsigned acceptance candidate to an explicit new output path; "
        "the artifact contains repository/runtime digests and no personal or managed bytes."
    ),
    "src/my_pa/application/goodnotes_gsqs_live_b0.py": (
        "writes only public GSQS B0 control JSON (identities, digests, measurement "
        "records without gold) into an explicit caller-supplied evidence directory; "
        "it never writes private transcriptions or managed-document bytes."
    ),
}

#: Attribute names that are a filesystem write whatever they are called on,
#: because no builtin or standard container has a method of that name. Matching
#: these on the receiver alone would be the false-positive problem that made an
#: earlier draft of this guard report `str.replace` and `list.remove`.
_UNAMBIGUOUS_WRITE_METHODS: Final = frozenset(
    {
        "write_bytes",
        "write_text",
        "mkdir",
        "makedirs",
        "touch",
        "symlink_to",
        "hardlink_to",
        "rmdir",
        "rmtree",
        "copytree",
        "copyfile",
    }
)

#: Names that are a filesystem write only when the receiver is a filesystem
#: object. `replace`, `remove`, `rename` and `copy` are also `str`, `list`, `set`
#: and `dict` methods, and this tree really does call all four of those.
_QUALIFIED_WRITE_METHODS: Final = frozenset(
    {"replace", "remove", "rename", "unlink", "copy", "copy2", "move", "truncate", "fsync", "write"}
)

#: Module-level functions that are a filesystem write when reached through their
#: own module. `os.open` is handled separately, because it is a write only when
#: its flags say so.
_MODULE_WRITE_FUNCTIONS: Final = {
    "os": frozenset(
        {
            "rename",
            "replace",
            "remove",
            "unlink",
            "rmdir",
            "mkdir",
            "makedirs",
            "removedirs",
            "truncate",
            "ftruncate",
            "symlink",
            "link",
            "write",
            "fsync",
            "fdatasync",
            "mkfifo",
            "mknod",
        }
    ),
    "shutil": frozenset(
        {
            "copy",
            "copy2",
            "copyfile",
            "copytree",
            "move",
            "rmtree",
            "make_archive",
            "unpack_archive",
        }
    ),
}

#: Open modes that write. `open(path)` and `open(path, "rb")` are reads.
_WRITING_MODES: Final = re.compile(r"[waxu+]")

#: `os.open` flags that mean a write.
_WRITE_FLAGS: Final = frozenset(
    {"O_WRONLY", "O_RDWR", "O_CREAT", "O_APPEND", "O_TRUNC", "O_EXCL", "O_TMPFILE"}
)

#: Server-side SQL that reaches a filesystem. A managed write executed from a
#: migration rather than from application code has to be caught here, because no
#: Python detector can see it.
#: `COPY … TO` requires a quoted destination or `TO PROGRAM`, because the bare
#: keyword pair appears in English prose — "a copy … to the shared declaration" —
#: and an earlier draft of this pattern reported three migration docstrings. What
#: it must still catch is the real statement, in every spelling
#: `test_the_sql_detector_sees_through_a_comment` plants.
_SQL_FILESYSTEM: Final = re.compile(
    r"\bCOPY\s+[^;]{1,300}?\bTO\s+(?:PROGRAM\s+)?'"
    r"|\b(?:lo_export|lo_import|pg_read_file|pg_read_binary_file"
    r"|pg_write_file|pg_ls_dir|pg_stat_file|pg_file_write)\b",
    re.IGNORECASE,
)

#: `--` to end of line, and `/* … */` including the leading-block form that
#: hid whole lines from every text guard in WP-18.
_SQL_COMMENT: Final = re.compile(r"--[^\n]*|/\*.*?\*/", re.DOTALL)


def _python_files() -> Iterator[Path]:
    for root in PYTHON_ROOTS:
        base = ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.py")):
            if SKIPPED_DIRECTORIES & set(path.parts):
                continue
            yield path


def _sql_files() -> Iterator[Path]:
    for root in SQL_ROOTS:
        base = ROOT / root
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*.sql")):
            if SKIPPED_DIRECTORIES & set(path.parts):
                continue
            yield path


def _receiver_is_filesystem(node: ast.expr) -> bool:
    """Whether `<node>.<method>()` is being called on a filesystem object.

    Three shapes, and each is one the tree really uses: a bare `os`/`shutil`
    module, a `Path(...)` expression, and a name whose spelling says it is a
    path. The last is the loose one and it is loose on purpose — a false positive
    here costs one registry entry, and a false negative costs the whole guard.
    """
    rendered = ast.unparse(node)
    if rendered in {"os", "os.path", "shutil", "pathlib"}:
        return True
    if rendered.startswith(("Path(", "pathlib.Path(")):
        return True
    tail = rendered.rsplit(".", 1)[-1].removesuffix("()")
    return bool(
        re.search(r"(?:^|_)(?:path|dir|directory|root|file|target|destination|temporary)s?$", tail)
    )


def _module_constants(tree: ast.AST) -> dict[str, str]:
    """Module-level `NAME = <expr>` assignments, rendered.

    `os.open(path, _OPEN_FLAGS)` is the shape both the read-only source provider
    and the managed store use, and a detector that could not follow the constant
    would have to call every one of them a write. Resolving one level is enough
    for this tree and is deliberately not more: a flag expression built at
    runtime is unreadable, and `_opens_for_writing` counts an unreadable one as a
    write.
    """
    constants: dict[str, str] = {}
    if isinstance(tree, ast.Module):
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.value is not None:
                    constants[node.target.id] = ast.unparse(node.value)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = ast.unparse(node.value)
    return constants


def write_calls(tree: ast.AST) -> list[str]:
    """Every filesystem-write call one parsed module makes, as rendered source.

    Public, because the controls below run it over planted modules — the same
    function that reads the real tree, so a narrowing breaks its own control.
    """
    constants = _module_constants(tree)
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Name):
            if function.id == "open" and _opens_for_writing(node, constants):
                found.append(ast.unparse(node)[:120])
            continue
        if not isinstance(function, ast.Attribute):
            continue
        receiver = ast.unparse(function.value)
        if (
            receiver in _MODULE_WRITE_FUNCTIONS
            and function.attr in _MODULE_WRITE_FUNCTIONS[receiver]
        ):
            found.append(ast.unparse(node)[:120])
            continue
        if receiver in {"os", "shutil"} and function.attr == "open":
            if _opens_for_writing(node, constants):
                found.append(ast.unparse(node)[:120])
            continue
        if function.attr in _UNAMBIGUOUS_WRITE_METHODS:
            found.append(ast.unparse(node)[:120])
            continue
        if function.attr == "open" and _receiver_is_filesystem(function.value):
            if _opens_for_writing(node, constants):
                found.append(ast.unparse(node)[:120])
            continue
        if function.attr in _QUALIFIED_WRITE_METHODS and _receiver_is_filesystem(function.value):
            found.append(ast.unparse(node)[:120])
    return found


def _opens_for_writing(node: ast.Call, constants: dict[str, str]) -> bool:
    """Whether an `open`-shaped call asks for a writable descriptor.

    A mode literal is read for `w`, `a`, `x`, `u` or `+`; an `os.open` flag
    expression is read for any of the write flags. **An unreadable mode or flag
    expression counts as a write**, which is the fail-closed direction: a guard
    that assumed a computed mode was a read would be a guard an author defeats by
    computing one.
    """
    arguments = list(node.args) + [keyword.value for keyword in node.keywords]
    if len(arguments) < 2:
        # `open(path)` is a text read; `os.open(path)` does not exist without
        # flags, so a one-argument call here is the builtin's read form.
        return False
    expression = arguments[1]
    if isinstance(expression, ast.Constant) and isinstance(expression.value, str):
        return bool(_WRITING_MODES.search(expression.value))
    rendered = ast.unparse(expression)
    rendered = constants.get(rendered, rendered)
    if any(flag in rendered for flag in _WRITE_FLAGS):
        return True
    read_only = r"[\w.|\s]*O_(?:RDONLY|NOFOLLOW|NONBLOCK|DIRECTORY|CLOEXEC)[\w.|\s]*"
    return not re.fullmatch(read_only, rendered)


def _relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _writers() -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for path in _python_files():
        calls = write_calls(ast.parse(path.read_text(encoding="utf-8"), filename=str(path)))
        if calls:
            found[_relative(path)] = calls
    return found


# --- the universe -----------------------------------------------------------


def test_the_walk_reaches_every_tree_it_claims_to() -> None:
    """A guard that walked nothing would report zero and mean nothing.

    Both universes are stated: WP-23's finding was a guard whose subject was
    `.sql` and which had never opened a `.sql` file, so the corpus is named and
    its size asserted rather than trusted.
    """
    python = {_relative(path) for path in _python_files()}
    assert len(python) > 140, f"the Python walk found {len(python)} files"
    assert MANAGED_STORE in python
    assert "migrations/versions/20260811_4c7b2e91d8a5_create_the_managed_document_tables.py" in (
        python
    ), "the revision that installs the managed plane is not in the walk"
    assert any(name.startswith("scripts/") for name in python)
    assert any(name.startswith("ops/") or name.startswith("apps/") for name in python)

    sql = {_relative(path) for path in _sql_files()}
    assert sql, "no .sql file was walked; the SQL rules below would prove nothing"
    lines = sum(len((ROOT / name).read_text(encoding="utf-8").splitlines()) for name in sorted(sql))
    assert lines > 20_000, (
        f"the .sql walk read {lines} lines; the target-schema corpus is over "
        "24,000 and its absence is exactly what WP-23 found"
    )


# --- rule 1: only the managed byte store writes -----------------------------


def test_every_filesystem_write_is_the_managed_store_or_is_registered() -> None:
    """Exact accounting, in both directions.

    A new writer anywhere under the five roots fails here rather than in review,
    and a registered writer that no longer writes fails too — a registry that
    outlives what it describes has stopped being a measurement.
    """
    measured = _writers()
    assert MANAGED_STORE in measured, (
        "the managed byte store performs no filesystem write the detector can "
        "see; every zero below is then a zero about the detector"
    )

    unaccounted = sorted(set(measured) - {MANAGED_STORE} - set(REGISTERED_WRITERS))
    assert unaccounted == [], (
        f"{unaccounted} call a filesystem-write API and are neither the managed "
        f"byte store nor registered. Managed bytes are written in one place, "
        "behind one containment check; a second write path is a second place a "
        "traversal or a source-root write can happen. Route it through the store, "
        "or register it here with what it writes and why"
    )

    stale = sorted(set(REGISTERED_WRITERS) - set(measured))
    assert stale == [], (
        f"{stale} are registered as filesystem writers but no longer write. "
        "Remove the entry rather than leaving a registry that describes the old tree"
    )


def test_the_python_detector_finds_each_write_shape_it_claims_to() -> None:
    """The control for rule 1, over the same function that reads the tree.

    Every shape the registry's accuracy depends on, planted at once. If this
    reddens, the zero above is a zero about the detector rather than about the
    tree.
    """
    planted = ast.parse(
        "import os, shutil\n"
        "from pathlib import Path\n"
        "def a(p): return Path(p).write_bytes(b'x')\n"
        "def b(p): return Path(p).write_text('x')\n"
        "def c(p): os.rename(p, p)\n"
        "def d(p): os.replace(p, p)\n"
        "def e(p): os.remove(p)\n"
        "def f(p): os.makedirs(p)\n"
        "def g(p): shutil.copy(p, p)\n"
        "def h(p): shutil.rmtree(p)\n"
        "def i(p): shutil.move(p, p)\n"
        "def j(p): open(p, 'w').close()\n"
        "def k(p): open(p, 'ab').close()\n"
        "def l(p): os.open(p, os.O_WRONLY | os.O_CREAT)\n"
        "def m(target): target.unlink()\n"
        "def n(path): path.mkdir()\n"
        "def o(p): Path(p).touch()\n"
        "def q(destination): destination.replace('x')\n"
    )
    found = write_calls(planted)
    assert len(found) == 16, f"the detector found {len(found)} of 16 planted writes: {found}"


def test_the_python_detector_does_not_report_a_read_or_a_container_method() -> None:
    """The other half of the control: a detector that reported everything would
    make the registry meaningless and would be indistinguishable from a broken one.

    Every line here is a shape this tree really contains — `str.replace`,
    `list.remove`, a read-only `os.open`, a binary read — and none is a write.
    """
    planted = ast.parse(
        "import os\n"
        "from pathlib import Path\n"
        "def a(text): return text.replace('a', 'b')\n"
        "def b(columns): columns.remove('x')\n"
        "def c(constraints): constraints.discard('x')\n"
        "def d(p): return open(p, 'rb').read()\n"
        "def e(p): return open(p).read()\n"
        "def f(p): return Path(p).read_text()\n"
        "def g(p): return os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)\n"
        "def h(cursor, statement): return cursor.copy(statement)\n"
        "def i(p): return p.stat()\n"
    )
    assert write_calls(planted) == []


# --- rule 2: no source root reaches a write API -----------------------------


def _names_the_source_root_column(tree: ast.AST) -> bool:
    """Whether a module names `native_root` as a column, a keyword, or in SQL.

    Read from the parse rather than from the text, so a paragraph *about* the
    column — `bootstrap/settings.py` has one — is not a reader of it. That
    distinction is the difference between a registry that measures the tree and
    one that measures its prose.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "native_root":
            return True
        if isinstance(node, ast.keyword) and node.arg == "native_root":
            return True
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and re.search(r"\bnative_root\b", node.value)
            and "\n" not in node.value
        ):
            return True
    return False


def test_no_module_passes_a_configured_source_root_to_a_write_api() -> None:
    """The source-root half of the boundary, read out of the source.

    `sources.native_root` is the column that holds a configured read-only source
    root, and exactly two modules read it: the provider lookup that builds a
    read-only adapter over it, and the reader that hands the set to the managed
    store's *refusal*. A third reader, or either of those two acquiring a
    filesystem write, is how a source root becomes writable.
    """
    readers = sorted(
        _relative(path)
        for path in _python_files()
        if _names_the_source_root_column(
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        )
        and _relative(path) != "src/my_pa/infrastructure/persistence/tables.py"
    )
    assert readers == [
        # The operator command that *registers* a source, which is where a root
        # enters the system at all. It performs no filesystem write.
        "apps/cli/sources.py",
        # The reader that hands the set to the managed store's refusal.
        "src/my_pa/infrastructure/persistence/registry.py",
        # The lookup that builds a read-only adapter over one.
        "src/my_pa/infrastructure/providers/registered.py",
    ], (
        f"{readers} name the configured source root column. Registering a fourth "
        "means a fourth thing can learn where a read-only source lives; confirm "
        "it cannot write there"
    )

    writers = _writers()
    for reader in readers:
        assert reader not in writers, (
            f"{reader} both reads a configured source root and calls a "
            "filesystem-write API. That is the one combination this package "
            "exists to make impossible"
        )


# --- rule 3: no SQL reaches a filesystem ------------------------------------


def strip_sql_comments(text: str) -> str:
    """SQL with its comments removed, so a guard cannot be commented past.

    Public, because the control below runs it. WP-18's fail-open was a leading
    block comment that hid whole lines from every text guard in four packages;
    this is the specific answer to it.
    """
    return _SQL_COMMENT.sub(" ", text)


def test_no_sql_file_reaches_a_filesystem() -> None:
    """`COPY … TO`, large-object export, and the `pg_*_file` family, in `.sql`.

    A managed write executed by the *server* is a write no Python detector can
    see, and 24,419 lines of this repository's `.sql` had never been opened by
    any guard before this package.
    """
    offending = {
        _relative(path): sorted(
            set(_SQL_FILESYSTEM.findall(strip_sql_comments(path.read_text(encoding="utf-8"))))
        )
        for path in _sql_files()
    }
    found = {name: hits for name, hits in offending.items() if hits}
    assert found == {}, (
        f"{found} reach a filesystem from SQL. The managed plane is where this "
        "product writes bytes, and it writes them from one Python module behind "
        "one containment check — not from a statement the server executes with "
        "the database server's own filesystem privileges"
    )


def test_no_migration_reaches_a_filesystem_from_raw_sql() -> None:
    """The same rule over the SQL a migration *emits*, which is not in a `.sql` file.

    `9d4e7a3b1c62` does all of its work in `op.execute` with no `Table` at all,
    so a rule that only read `.sql` files and Python call sites would miss a
    migration that wrote a file through a statement string.
    """
    offending: dict[str, list[str]] = {}
    for path in sorted((ROOT / "migrations").rglob("*.py")):
        if SKIPPED_DIRECTORIES & set(path.parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits = sorted(
            {
                match
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant) and isinstance(node.value, str)
                for match in _SQL_FILESYSTEM.findall(strip_sql_comments(node.value))
            }
        )
        if hits:
            offending[_relative(path)] = hits
    assert offending == {}, f"{offending} emit SQL that reaches a filesystem"


def test_the_sql_detector_sees_through_a_comment() -> None:
    """WP-18's exact fail-open, planted.

    A leading block comment hid whole lines from every text guard in four
    packages. Each plant here is a real reach into a filesystem wearing a comment
    that a naive line-based reader would have skipped.
    """
    for planted in (
        "/* a leading block comment\n */ COPY knowledge.captures TO '/tmp/out.csv';",
        "-- harmless\nCOPY knowledge.captures TO PROGRAM 'cat > /tmp/out';",
        "SELECT lo_export(1234, '/tmp/out');",
        "SELECT pg_read_file('/etc/passwd');",
        "/*\nCOPY x TO 'a';\n*/ SELECT pg_write_file('/tmp/x', 'y');",
    ):
        assert _SQL_FILESYSTEM.search(strip_sql_comments(planted)), planted

    # And it distinguishes: an ordinary `COPY … FROM STDIN`, which the migration
    # loader really uses, is not a filesystem write.
    for benign in (
        "COPY knowledge.captures FROM STDIN",
        "CREATE TABLE knowledge.copy_of_things (id text)",
        "-- COPY knowledge.captures TO '/tmp/out.csv';",
        "/* COPY knowledge.captures TO '/tmp/out.csv'; */",
    ):
        assert not _SQL_FILESYSTEM.search(strip_sql_comments(benign)), benign


# --- rule 4: the version table has no update path ---------------------------


MANAGED_APPEND_ONLY_TABLES: Final = (
    "managed_document_versions",
    "managed_document_lifecycle_events",
)

MUTATING_BUILDERS: Final = frozenset({"update", "delete"})

_RAW_MANAGED_SQL: Final = re.compile(
    r"\b(?:UPDATE|DELETE\s+FROM)\s+(?:\w+\.)?managed_document_(?:versions|lifecycle_events)\b",
    re.IGNORECASE,
)


def statements_against(tree: ast.AST, table: str) -> list[str]:
    """Every statement builder one module applies to one named table.

    Both call shapes SQLAlchemy accepts — `table.update()` and `update(table)` —
    because a guard that knew only one is a guard a writer evades by preferring
    the other without ever intending to. The same shape
    `test_capture_has_no_update_path.py` uses, deliberately: this is the managed
    plane's half of a rule that plane already holds for captures.
    """
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        if isinstance(function, ast.Attribute) and _names(function.value) == table:
            found.append(function.attr)
        elif isinstance(function, ast.Name) and any(
            _names(argument) == table for argument in node.args
        ):
            found.append(function.id)
    return found


def _names(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def test_no_module_updates_or_deletes_a_managed_version_or_lifecycle_row() -> None:
    """Immutability read out of the source, beside the trigger that enforces it.

    Two independent halves, and neither implies the other: a build that dropped
    the trigger would still pass here, and a build that grew an `update()` would
    still pass against the server. `tests/database/test_managed_documents.py`
    holds the other half.
    """
    offending: dict[str, list[str]] = {}
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        hits = sorted(
            {
                builder
                for table in MANAGED_APPEND_ONLY_TABLES
                for builder in statements_against(tree, table)
            }
            & MUTATING_BUILDERS
        ) + [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and _RAW_MANAGED_SQL.search(node.value)
        ]
        if hits:
            offending[_relative(path)] = hits
    assert offending == {}, (
        f"{offending} build a statement that changes or removes a stored managed "
        "version or lifecycle row. A correction is a new version and a restore is "
        "a new transition; the predecessor stays exactly as it was written"
    )


def test_the_immutability_detector_resolves_this_plane_and_fires_on_a_plant() -> None:
    """Two controls: it finds the real appends, and it reports a planted mutation."""
    writer = ROOT / "src" / "my_pa" / "infrastructure" / "persistence" / "managed_documents.py"
    tree = ast.parse(writer.read_text(encoding="utf-8"), filename=str(writer))
    assert "insert" in statements_against(tree, "managed_document_versions"), (
        "the detector cannot resolve the table name in the module that really "
        "writes it; every zero above is then about name resolution"
    )
    assert "insert" in statements_against(tree, "managed_document_lifecycle_events")

    planted = ast.parse(
        "from sqlalchemy import delete, update\n"
        "from my_pa.infrastructure.persistence.tables import (\n"
        "    managed_document_lifecycle_events, managed_document_versions)\n"
        "def a(connection):\n"
        "    connection.execute(managed_document_versions.update().values(title='x'))\n"
        "def b(connection):\n"
        "    connection.execute(delete(managed_document_lifecycle_events))\n"
        "def c(connection):\n"
        "    connection.execute(\n"
        "        text('UPDATE knowledge.managed_document_versions SET title = :t'))\n"
    )
    assert set(statements_against(planted, "managed_document_versions")) & MUTATING_BUILDERS == {
        "update"
    }
    assert set(
        statements_against(planted, "managed_document_lifecycle_events")
    ) & MUTATING_BUILDERS == {"delete"}
    assert _RAW_MANAGED_SQL.search("UPDATE knowledge.managed_document_versions SET title = :t")


# --- rule 5: one Alembic head -----------------------------------------------


def test_the_migration_chain_still_has_exactly_one_head() -> None:
    """A second head is a schema nobody can name, and this package adds a revision.

    Derived from the revision files rather than from a stored number, so it says
    what the chain is today and cannot go stale.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    script = ScriptDirectory.from_config(Config(str(ROOT / "alembic.ini")))
    assert len(script.get_heads()) == 1, f"the chain has heads: {script.get_heads()}"
    revision = script.get_revision("4c7b2e91d8a5")
    assert revision is not None, "this package's revision is not in the chain"
    assert revision.down_revision == "2d9f4a7c1e58"


# --- rule 6: the managed root is never a source root ------------------------


def test_the_managed_root_setting_is_its_own_and_reaches_only_the_store() -> None:
    """The configuration seam, read out of the source.

    The managed root is process configuration; a source root is a database row an
    operator registered. Two channels, so there is no single value that could be
    read as both — and the setting reaches exactly one constructor.
    """
    from my_pa.bootstrap.settings import Settings

    assert "managed_document_root" in Settings.model_fields
    assert Settings.model_fields["managed_document_root"].default == "", (
        "the managed root now has a default location. An unconfigured process "
        "would then acquire a write plane by forgetting something"
    )

    readers = sorted(
        _relative(path)
        for path in _python_files()
        if "managed_document_root" in path.read_text(encoding="utf-8")
    )
    # WP-28 added the third and last of these. `bootstrap/gateway.py` is the
    # composition root, and giving the managed plane a capability seat meant the
    # served process had to build a store rather than only the operator CLI. It
    # is held to the same rule as the other two and meets it: `managed_byte_store`
    # reads the setting, refuses an empty one by composing nothing, and constructs
    # `FilesystemManagedByteStore` with the configured source roots — so the
    # containment resolution and the source-root refusal both run there.
    assert readers == [
        "apps/cli/managed_documents.py",
        "src/my_pa/bootstrap/gateway.py",
        "src/my_pa/bootstrap/settings.py",
    ], (
        f"{readers} read the managed root setting. Every reader is a place a "
        "managed root can be pointed somewhere; each has to construct the store, "
        "which is where the containment and the source-root refusal live"
    )
    composition = (ROOT / "src/my_pa/bootstrap/gateway.py").read_text(encoding="utf-8")
    assert "FilesystemManagedByteStore(" in composition, (
        "the composition root reads the managed root setting without building the "
        "store from it, which is the one thing every reader of this setting must do"
    )
    assert "source_roots=" in composition, (
        "the composition root builds the managed store without giving it the "
        "configured source roots, so the source-root overlap refusal compares "
        "against nothing"
    )
