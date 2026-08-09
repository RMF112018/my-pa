"""`D-64`'s invariant, enforced instead of commented three times.

`D-64` is the finding that both CI jobs ran `mypy src` while `[tool.mypy] files`
named `src`, `migrations` and `apps` — and that **an explicit path argument
overrides that list**, so CI checked 93 files where a bare `mypy` checked 109
and the 16 in `apps/` and `migrations/` were type-checked by nothing. The fix
was to make every invocation bare. What held the fix in place was three prose
comments: one in `pyproject.toml` and one in each of the two workflow jobs.
Nothing structural. A third job written with `mypy src`, or a `files` list
narrowed back to `src`, would restore the original defect with every gate green,
which is the shape this campaign has caught repeatedly.

**Why this is not a text search.** The four lines of prose in the workflow that
*describe* the defect contain the literal `mypy src` — twice in each job. A
`grep` for that string reports the comments explaining why it must not be
written, and reports nothing about a real invocation written as
`python  -m  mypy   src` or `mypy \\\n  src`. So the workflow is parsed into
jobs, steps and shell scripts, the shell scripts are read as command lines with
continuations joined and comments dropped, and the rule is applied to the
tokens of a command rather than to the bytes of a file.

**Why the parser is written here.** No YAML library is a declared dependency of
this package, and this test must run in the FAST tier on an ordinary install, so
it cannot import one. `_parse_workflow` is a parser for the block subset of YAML
this repository's workflows use: mappings, sequences, block scalars, comments
and plain scalars. It **raises** on a construct it does not understand rather
than skipping it, because a parser that silently skipped would be exactly the
guard that cannot fire. Flow collections are the one construct it reads without
interpreting — `branches: [main]` comes back as the string `"[main]"` — which is
pinned in the synthetic parse below rather than left to be discovered, and which
costs nothing here because no `run:` is written in flow style.
`test_the_parser_reads_a_document_it_has_never_seen`
exercises it on a synthetic workflow whose expected parse is written out, and
`test_the_workflow_parses_into_jobs_that_run_commands` is the emptiness test
over the real file.

**What it does not check.** It does not run `mypy`, so it says nothing about
whether the 140 files pass; that is what CI's own `mypy` step is for. It reads
`.github/workflows/*.yml` only, so a `mypy` invocation in a Makefile, a
pre-commit hook or a script is outside it. And the argument rule is *stricter*
than `D-64` needs: any token after `mypy` that does not begin with `-` is
refused, so `--config-file pyproject.toml` written with a space would be refused
along with `src`. Modelling mypy's option grammar in a test is the alternative,
and it would be a second thing to keep true; the restriction is written down
here instead. `--config-file=pyproject.toml` passes.

Nothing here opens a connection, runs a subprocess, or reads outside the
repository.
"""

from __future__ import annotations

import re
import shlex
import tomllib
from collections.abc import Iterator
from pathlib import Path, PurePosixPath
from typing import Final

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
PYPROJECT = ROOT / "pyproject.toml"

#: The block-scalar indicators. Chomping and keep modifiers are accepted because
#: the workflow uses `>-`, and a header this parser did not know would otherwise
#: be read as a plain scalar and swallow a whole script.
_BLOCK_SCALARS: Final = frozenset({"|", "|-", "|+", ">", ">-", ">+"})

#: Shell control operators, so `a && mypy src` is two commands and not one.
_OPERATORS: Final = frozenset({"&&", "||", ";", "|", "&"})

#: `python`, `python3`, `python3.12` — the launchers `python -m mypy` is spelled
#: with. Matched against a token, never against a file's text.
_INTERPRETER: Final = re.compile(r"^python(3(\.\d+)?)?$")

#: Top-level directories that hold `.py` files and are deliberately absent from
#: `[tool.mypy] files`. This records the current classification; it does not
#: argue that any of the three *should* be unchecked. Its job is that a **new**
#: Python root cannot appear without someone deciding which side it is on, which
#: is the half of `D-64` that a bare-invocation rule alone does not cover.
UNCHECKED_ROOTS: Final = frozenset({"tests", "docs", "scripts"})


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _content(lines: list[str], index: int) -> int:
    """The next line that is neither blank nor a whole-line comment."""
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped and not stripped.startswith("#"):
            return index
        index += 1
    return index


def _split_key(line: str) -> tuple[str, str] | None:
    """`key` and the rest, on YAML's rule: a key ends at `": "` or a final `":"`.

    The rule matters. `- 5432:5432` is a scalar and not a mapping, and
    `MY_PA_DATABASE_URL: postgresql+psycopg://my_pa@localhost:5432/my_pa_ci`
    splits at the first `": "` rather than at the port.
    """
    if line.endswith(":"):
        return line[:-1].strip().strip("\"'"), ""
    head, separator, rest = line.partition(": ")
    if not separator:
        return None
    return head.strip().strip("\"'"), rest.strip()


def _block_scalar(lines: list[str], index: int, indent: int) -> tuple[str, int]:
    """Every line more indented than `indent`, dedented to its own margin."""
    body: list[str] = []
    while index < len(lines):
        line = lines[index]
        if line.strip() and _indent(line) <= indent:
            break
        body.append(line)
        index += 1
    while body and not body[-1].strip():
        body.pop()
    if not body:
        return "", index
    margin = min(_indent(line) for line in body if line.strip())
    return "\n".join(line[margin:] if line.strip() else "" for line in body), index


def _parse_block(lines: list[str], index: int, indent: int) -> tuple[object, int]:
    if lines[index].lstrip().startswith("- "):
        return _parse_sequence(lines, index, indent)
    return _parse_mapping(lines, index, indent)


def _parse_sequence(lines: list[str], index: int, indent: int) -> tuple[list[object], int]:
    items: list[object] = []
    while True:
        index = _content(lines, index)
        if index >= len(lines) or _indent(lines[index]) != indent:
            return items, index
        entry = lines[index].lstrip()
        if not entry.startswith("- "):
            return items, index
        rest = entry[2:]
        if _split_key(rest) is None:
            items.append(rest)
            index += 1
            continue
        # A mapping opening on the dash line. Rewriting the line as if the dash
        # were spaces is what lets the mapping parser see a normal entry; the
        # caller's list is a copy, so nothing outside this parse is touched.
        lines[index] = " " * (indent + 2) + rest
        value, index = _parse_mapping(lines, index, indent + 2)
        items.append(value)


def _parse_mapping(lines: list[str], index: int, indent: int) -> tuple[dict[str, object], int]:
    mapping: dict[str, object] = {}
    while True:
        index = _content(lines, index)
        if index >= len(lines) or _indent(lines[index]) != indent:
            return mapping, index
        entry = lines[index].lstrip()
        if entry.startswith("- "):
            return mapping, index
        split = _split_key(entry)
        if split is None:
            raise ValueError(
                f"line {index + 1} is neither a mapping nor a sequence entry: {entry!r}"
            )
        key, rest = split
        index += 1
        if rest in _BLOCK_SCALARS:
            mapping[key], index = _block_scalar(lines, index, indent)
        elif rest:
            mapping[key] = rest
        else:
            nested = _content(lines, index)
            if nested < len(lines) and _indent(lines[nested]) > indent:
                mapping[key], index = _parse_block(lines, nested, _indent(lines[nested]))
            else:
                mapping[key] = None


def _parse_workflow(document: str) -> dict[str, object]:
    lines = document.splitlines()
    start = _content(lines, 0)
    if start >= len(lines):
        return {}
    parsed, _ = _parse_mapping(lines, start, _indent(lines[start]))
    return parsed


def _command_lines(script: str) -> list[str]:
    """One logical shell command per entry: continuations joined, comments gone."""
    commands: list[str] = []
    pending = ""
    for raw in script.splitlines():
        stripped = raw.strip()
        if not pending and (not stripped or stripped.startswith("#")):
            continue
        pending = f"{pending} {stripped}" if pending else stripped
        if pending.endswith("\\"):
            pending = pending[:-1].rstrip()
            continue
        commands.append(pending)
        pending = ""
    if pending:
        commands.append(pending)
    return commands


def _segments(tokens: list[str]) -> Iterator[list[str]]:
    segment: list[str] = []
    for token in tokens:
        if token in _OPERATORS:
            if segment:
                yield segment
            segment = []
        else:
            segment.append(token)
    if segment:
        yield segment


def mypy_arguments(script: str) -> list[tuple[str, ...]]:
    """The arguments of every `mypy` invocation in one shell script.

    One entry per invocation, so a script with none returns `[]` and a script
    with a bare one returns `[()]` — the two are different answers and the
    tests below depend on telling them apart.

    A token is an invocation when its basename is `mypy`, which reads `mypy`,
    `/usr/local/bin/mypy` and the `python -m mypy` form alike without a special
    case for each. `mypy` is prefiltered as a substring only to avoid tokenizing
    every line of embedded Python in the workflow's heredocs; a command that
    invokes mypy necessarily contains the string, so the prefilter cannot hide
    one.
    """
    invocations: list[tuple[str, ...]] = []
    for command in _command_lines(script):
        if "mypy" not in command:
            continue
        for segment in _segments(shlex.split(command, comments=True)):
            for position, token in enumerate(segment):
                if PurePosixPath(token).name == "mypy" and not (
                    position >= 2
                    and segment[position - 1] == "-m"
                    and not _INTERPRETER.match(PurePosixPath(segment[position - 2]).name)
                ):
                    invocations.append(tuple(segment[position + 1 :]))
                    break
    return invocations


def _steps() -> list[tuple[str, str, str]]:
    """Every `(workflow, job, shell script)` the repository's CI runs."""
    found: list[tuple[str, str, str]] = []
    for path in sorted(WORKFLOWS.glob("*.yml")):
        workflow = _parse_workflow(path.read_text(encoding="utf-8"))
        jobs = workflow.get("jobs")
        assert isinstance(jobs, dict), f"{path.name} declares no jobs mapping"
        for job, definition in jobs.items():
            assert isinstance(definition, dict), f"{path.name}: job {job} is not a mapping"
            steps = definition.get("steps")
            assert isinstance(steps, list), f"{path.name}: job {job} declares no steps"
            for step in steps:
                assert isinstance(step, dict), f"{path.name}: job {job} has a non-mapping step"
                script = step.get("run")
                if isinstance(script, str):
                    found.append((path.name, str(job), script))
    return found


def test_the_parser_reads_a_document_it_has_never_seen() -> None:
    """The extractor's own control: a synthetic workflow with its parse written out.

    Every construct the real file uses and one it does not — a nested mapping, a
    sequence of mappings, a `|` block scalar holding a `#` line that must survive
    as script text, a `>-` folded scalar, a whole-line comment that must not,
    a `key:` with no value, and a `host:port` scalar that is not a mapping.
    Without this, a parser that returned an empty mapping would make every rule
    below pass by describing nothing.
    """
    document = "\n".join(
        [
            "name: synthetic",
            "# a comment that is not data",
            "on:",
            "  push:",
            "    branches: [main]",
            "jobs:",
            "  first:",
            "    runs-on: ubuntu-latest",
            "    steps:",
            "      - name: Checkout",
            "        uses: actions/checkout@abc",
            "      - name: Check",
            "        run: |",
            "          # a shell comment, which is script and not YAML",
            "          python -m mypy",
            "",
            "          echo done",
            "  second:",
            "    ports:",
            "      - 5432:5432",
            "    empty:",
            "    options: >-",
            "      --health-retries 5",
            "    steps:",
            "      - run: python -m mypy",
        ]
    )

    parsed = _parse_workflow(document)

    assert parsed["name"] == "synthetic"
    assert parsed["on"] == {"push": {"branches": "[main]"}}
    jobs = parsed["jobs"]
    assert isinstance(jobs, dict)
    assert list(jobs) == ["first", "second"]
    first = jobs["first"]
    assert isinstance(first, dict)
    assert first["runs-on"] == "ubuntu-latest"
    assert first["steps"] == [
        {"name": "Checkout", "uses": "actions/checkout@abc"},
        {
            "name": "Check",
            "run": ("# a shell comment, which is script and not YAML\npython -m mypy\n\necho done"),
        },
    ]
    second = jobs["second"]
    assert isinstance(second, dict)
    assert second["ports"] == ["5432:5432"]
    assert second["empty"] is None
    assert second["options"] == "--health-retries 5"
    assert second["steps"] == [{"run": "python -m mypy"}]


def test_the_workflow_parses_into_jobs_that_run_commands() -> None:
    """The emptiness test over the real parse.

    Every rule below quantifies over `_steps()`, so a parse that found no step
    would satisfy all of them. The job names are asserted as a subset: a fourth
    job must be covered without an edit here, which is the property `D-64` wants
    and the reason a name list would be the wrong shape.
    """
    steps = _steps()
    assert len(steps) >= 5
    assert {job for _, job, _ in steps} >= {"validate", "dependency-floor", "database-tier"}
    assert all(script.strip() for _, _, script in steps)


def test_ci_invokes_mypy_and_every_invocation_is_bare() -> None:
    """`D-64`, as a check rather than as three comments.

    Both halves in one test on purpose. "No invocation carries a target" is
    satisfied by a repository that never invokes `mypy` at all, so the count of
    invocations is asserted beside the rule that constrains them: `mypy` is run,
    in more than one job, and no run of it names a path.
    """
    invocations = [
        (job, arguments) for _, job, script in _steps() for arguments in mypy_arguments(script)
    ]

    assert len(invocations) >= 2
    assert len({job for job, _ in invocations}) >= 2
    for job, arguments in invocations:
        targets = [argument for argument in arguments if not argument.startswith("-")]
        assert not targets, (
            f"job {job} invokes mypy with {targets}; an explicit target overrides "
            "[tool.mypy] files in pyproject.toml, which is D-64. Invoke it bare, and "
            "write any option that takes a value as --option=value"
        )


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        # The forms CI uses today, which must stay accepted.
        ("python -m mypy", [()]),
        ("mypy", [()]),
        ("python -m mypy --strict", [("--strict",)]),
        ("python -m mypy --config-file=pyproject.toml", [("--config-file=pyproject.toml",)]),
        # `D-64` itself, in the spellings a text search misses.
        ("python -m mypy src", [("src",)]),
        ("mypy  src   apps", [("src", "apps")]),
        ("python -m mypy \\\n  src", [("src",)]),
        ("python -m mypy -p my_pa", [("-p", "my_pa")]),
        ("ruff check . && python -m mypy src", [("src",)]),
        # A comment naming the defect is not the defect. Four such lines are in
        # the workflow, which is why `grep 'mypy src'` cannot be the rule.
        ("# never write `mypy src`\npython -m mypy", [()]),
        # No invocation at all, so a script with none is distinguishable from a
        # script with a bare one.
        ("python -m pytest -q", []),
        ("python -m pip install mypy", [()]),
    ],
)
def test_the_reader_tells_a_bare_invocation_from_a_targeted_one(
    script: str, expected: list[tuple[str, ...]]
) -> None:
    """The rule's own control, with both answers in one table.

    A reader that saw every command as bare would pass
    `test_ci_invokes_mypy_and_every_invocation_is_bare` while checking nothing,
    and one that saw none at all would fail its count. The rows above pin both
    directions on the same function the real workflow goes through.
    """
    assert mypy_arguments(script) == expected


def test_every_python_root_is_type_checked_or_named() -> None:
    """The other half of `D-64`: `files` narrowed is the same defect as `mypy src`.

    Derived from the tree rather than restated: every top-level directory that
    holds a `.py` file is either in `[tool.mypy] files` or in `UNCHECKED_ROOTS`,
    and the two sets together are exactly that set. So narrowing `files` to
    `["src"]` reddens, and a new Python root — a `services/`, a second `apps/` —
    reddens until someone puts it on one side or the other. That the equality
    rots when a root is added is the point of it.
    """
    configured = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["tool"]["mypy"]["files"]
    checked = {str(entry) for entry in configured}
    # Untracked roots are excluded by reading `.gitignore`'s own top-level
    # directory patterns rather than by a list here, so a developer's `venv/`
    # does not turn this rule red and no name has to be remembered.
    ignored = {
        entry
        for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        if (entry := line.strip().rstrip("/")) and not entry.startswith("#") and "/" not in entry
    }
    roots = {
        root
        for path in ROOT.glob("*/**/*.py")
        if "__pycache__" not in path.parts
        and (root := path.relative_to(ROOT).parts[0]) not in ignored
        and not root.startswith(".")
    }

    assert roots, "no Python root was found, so this rule is describing nothing"
    assert checked | UNCHECKED_ROOTS == roots
    assert not checked & UNCHECKED_ROOTS
