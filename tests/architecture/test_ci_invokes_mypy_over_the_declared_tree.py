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
this repository's workflows use, and the list is exact because the gaps in it
were fail-open for four commits:

* **Reads.** Block mappings and block sequences; comments and blank lines; plain
  scalars; simply quoted scalars, unquoted; `|`-family block scalars, joined
  with newlines; `>`-family block scalars, *folded* — line breaks between
  equally indented lines become spaces and a run of blank lines becomes one
  fewer newline, which is what YAML means by `>` and what
  `run: >` over two lines means to the shell.
* **Reads without interpreting.** A flow *sequence* comes back as its own text:
  `branches: [main]` is the string `"[main]"`. That is pinned in the synthetic
  parse below rather than left to be discovered, and it is safe here only
  because a flow sequence in a `steps:` position then fails the `isinstance`
  check in `_steps` rather than parsing to nothing.
* **Raises.** A line that is neither a mapping entry nor a sequence entry; a
  flow *mapping* anywhere (`- {name: Check, run: mypy src}`, whose block reading
  loses every key after the first and yields a step with no `run:`); a quoted
  scalar whose quoting is not simple, meaning it carries an escape or an inner
  quote; and a folded scalar containing a more-indented line, which YAML keeps
  literal under a third joining rule this parser does not implement.
* **Ignores.** Chomping and keep modifiers. `>-`, `>` and `>+` are read alike
  and no trailing newline is reproduced, which cannot change how a command line
  tokenizes and is the one place this parser is deliberately loose.

It raises rather than skipping because a parser that silently skipped would be
exactly the guard that cannot fire — which is what it was. Three of the four
shapes above were **silent** passes, and two of them were demonstrated
end-to-end against the real workflow: a `run: >` holding `python -m mypy` and
`src` on two lines was joined with a newline, so the guard read a bare
invocation and a stray word and went green on `D-64` itself.
`test_the_parser_reads_a_document_it_has_never_seen` exercises the parser on a
synthetic workflow whose expected parse is written out — including a folded
scalar over *several* lines, because a single-line `>-` is the one case where
folding and newline-joining are indistinguishable and a control that cannot
discriminate is not a control.
`test_the_parser_refuses_or_reads_every_step_shape_it_meets` is the fail-closed
table, and `test_the_workflow_parses_into_jobs_that_run_commands` is the
emptiness test over the real file.

**What it does not check.** It does not run `mypy`, so it says nothing about
whether the 140 files pass; that is what CI's own `mypy` step is for. It reads
`.github/workflows/*.yml` and `*.yaml` — both, because GitHub Actions honours
both and a real `.yaml` workflow running `mypy src` sat outside this guard
undetected — so a `mypy` invocation in a Makefile, a
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
#: be read as a plain scalar and swallow a whole script. The `|` family and the
#: `>` family are **not** joined the same way; see `_block_scalar`.
_BLOCK_SCALARS: Final = frozenset({"|", "|-", "|+", ">", ">-", ">+"})

#: The suffixes GitHub Actions reads out of `.github/workflows`. Both of them,
#: because it honours both identically: a real `extra-typecheck.yaml` running
#: `mypy src` was invisible to a `*.yml` glob and read exactly like a file that
#: had been checked.
_WORKFLOW_SUFFIXES: Final = frozenset({".yml", ".yaml"})

#: The quote characters a simply quoted scalar may be wrapped in.
_QUOTES: Final = frozenset({'"', "'"})

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


def _refuse_flow_mapping(value: str, index: int) -> None:
    """A flow mapping is refused, because reading it as a block loses its keys.

    `- {name: Check, run: mypy src}` splits at its first `": "`, which is inside
    the braces, and comes back as `{'{name': 'Check, run: mypy src}'}` — a step
    mapping with no `run:` key, which `_steps` then skips without a word. A
    parser that cannot read a construct must say so; this is where it says so.
    """
    if value.startswith("{"):
        raise ValueError(
            f"line {index + 1} is a flow mapping: {value!r}. Read as a block it loses "
            "every key after the first, so a step written this way is skipped rather "
            "than checked; write it as a block mapping"
        )


def _scalar(value: str, index: int) -> str:
    """A plain scalar unchanged, a simply quoted one unquoted, anything else refused.

    `_split_key` unquotes the key and used to leave the value alone, so
    `run: "python -m mypy src"` came back with its quotes attached: `shlex` saw
    one token whose basename is not `mypy`, **zero** invocations were found, and
    a targeted invocation passed the rule below by being invisible to it.

    Simple quoting only. An escape or an inner quote of the same kind is
    refused rather than approximated, because `"mypy \\"src\\""` and `'it''s'`
    both mean something this parser would otherwise get wrong quietly.
    """
    _refuse_flow_mapping(value, index)
    quote = value[:1]
    if quote not in _QUOTES:
        return value
    if len(value) < 2 or not value.endswith(quote) or quote in value[1:-1] or "\\" in value:
        raise ValueError(
            f"line {index + 1} is a quoted scalar this parser will not unquote: "
            f"{value!r}. Approximating it is how a real invocation comes to read "
            "as a single word that no rule matches"
        )
    return value[1:-1]


def _block_scalar(lines: list[str], index: int, indent: int, folded: bool) -> tuple[str, int]:
    """Every line more indented than `indent`, dedented to its own margin.

    `folded` selects the join, and the two joins are different answers rather
    than different spellings. YAML's `|` keeps every line break; YAML's `>`
    *folds* a break between equally indented lines into a space. So

        run: >
          python -m mypy
          src

    is the single command `python -m mypy src` — `D-64` exactly — and joining it
    with a newline instead reads a bare invocation followed by the word `src`,
    which is the guard returning green on the defect it exists to catch.
    """
    start = index
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
    dedented = [line[margin:] if line.strip() else "" for line in body]
    if not folded:
        return "\n".join(dedented), index
    return _fold(dedented, start), index


def _fold(dedented: list[str], start: int) -> str:
    """YAML folding over the subset this repository writes.

    Breaks between equally indented lines fold to spaces, and a run of *n* blank
    lines becomes *n* - 1 newlines. A **more-indented** line is kept literally by
    YAML under a third rule, which this parser does not implement and therefore
    refuses: guessing that rule wrong is the same class of mistake as reading
    `>` as `|`.
    """
    paragraphs: list[str] = []
    current: list[str] = []
    for offset, line in enumerate(dedented):
        if not line:
            paragraphs.append(" ".join(current))
            current = []
        elif line.startswith(" "):
            raise ValueError(
                f"line {start + offset + 1} is more indented than its folded scalar: "
                f"{line!r}. YAML keeps such a line literal, which is a joining rule "
                "this parser does not read; write the block with `|` instead of `>`"
            )
        else:
            current.append(line)
    paragraphs.append(" ".join(current))
    return "\n".join(paragraphs)


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
        _refuse_flow_mapping(rest, index)
        if _split_key(rest) is None:
            items.append(_scalar(rest, index))
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
            mapping[key], index = _block_scalar(lines, index, indent, rest.startswith(">"))
        elif rest:
            mapping[key] = _scalar(rest, index - 1)
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


def _workflow_files(directory: Path) -> list[Path]:
    """Every file in `directory` GitHub Actions would run.

    Both suffixes. `glob("*.yml")` alone left `.yaml` workflows outside this
    guard entirely, which is not a narrower check but no check at all: the file
    was never opened, so nothing about it could go red.
    """
    return sorted(
        path for path in directory.iterdir() if path.is_file() and path.suffix in _WORKFLOW_SUFFIXES
    )


def _steps_in(name: str, document: str) -> list[tuple[str, str, str]]:
    """Every `(workflow, job, shell script)` one workflow document declares.

    The assertions are the parser's downstream half of failing closed. A `steps:`
    that parsed to a string — a flow sequence, an alias — or a step that parsed
    to something other than a mapping stops here loudly rather than contributing
    nothing to a rule that quantifies over what it returns.
    """
    found: list[tuple[str, str, str]] = []
    workflow = _parse_workflow(document)
    jobs = workflow.get("jobs")
    assert isinstance(jobs, dict), f"{name} declares no jobs mapping"
    for job, definition in jobs.items():
        assert isinstance(definition, dict), f"{name}: job {job} is not a mapping"
        steps = definition.get("steps")
        assert isinstance(steps, list), f"{name}: job {job} declares no steps"
        for step in steps:
            assert isinstance(step, dict), f"{name}: job {job} has a non-mapping step"
            script = step.get("run")
            if isinstance(script, str):
                found.append((name, str(job), script))
    return found


def _steps() -> list[tuple[str, str, str]]:
    """Every `(workflow, job, shell script)` the repository's CI runs."""
    found: list[tuple[str, str, str]] = []
    for path in _workflow_files(WORKFLOWS):
        found.extend(_steps_in(path.name, path.read_text(encoding="utf-8")))
    return found


def test_the_parser_reads_a_document_it_has_never_seen() -> None:
    """The extractor's own control: a synthetic workflow with its parse written out.

    Every construct the real file uses and several it does not — a nested
    mapping, a sequence of mappings, a `|` block scalar holding a `#` line that
    must survive as script text and a blank line that must survive as one, a
    whole-line comment that must not, a `key:` with no value, a quoted scalar, and
    a `host:port` scalar that is not a mapping.
    Without this, a parser that returned an empty mapping would make every rule
    below pass by describing nothing.

    **The folded scalars are written over several lines on purpose.** This test
    exercised `>-` on a single-line value only, which is the one shape where
    folding and newline-joining produce the same string — so it agreed with a
    parser that read `>` as `|`, and the defect that let `run: >` hide a target
    from `D-64` sat underneath a green control. Both a folded `run:` and a folded
    option are spelled out here, blank line included, because a same-shape
    control that cannot discriminate is not a control.
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
            '        id: "checkout"',
            "      - name: Check",
            "        run: |",
            "          # a shell comment, which is script and not YAML",
            "          python -m mypy",
            "",
            "          echo done",
            "      - name: Folded",
            "        run: >",
            "          python -m mypy",
            "          --strict",
            "",
            "          echo done",
            "  second:",
            "    ports:",
            "      - 5432:5432",
            "    empty:",
            "    options: >-",
            "      --health-retries 5",
            "      --health-timeout 5s",
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
        {"name": "Checkout", "uses": "actions/checkout@abc", "id": "checkout"},
        {
            "name": "Check",
            "run": ("# a shell comment, which is script and not YAML\npython -m mypy\n\necho done"),
        },
        # Folded: the two option lines become one command line, and the blank
        # line becomes the break between two. A `|` reading would give three
        # commands, the first of them a bare `python -m mypy`.
        {"name": "Folded", "run": "python -m mypy --strict\necho done"},
    ]
    second = jobs["second"]
    assert isinstance(second, dict)
    assert second["ports"] == ["5432:5432"]
    assert second["empty"] is None
    assert second["options"] == "--health-retries 5 --health-timeout 5s"
    assert second["steps"] == [{"run": "python -m mypy"}]


def _one_job(*step_lines: str) -> str:
    """A minimal workflow whose only job carries the given step lines."""
    return "\n".join(["jobs:", "  only:", "    runs-on: ubuntu-latest", "    steps:", *step_lines])


_STEP = "      - name: Typecheck"

#: `D-64` written the way each construct spells it, and what must happen to it.
#: `None` means the parser must raise or `_steps_in` must assert; a list is the
#: invocation read correctly. Nothing may return `[]` while a target is present,
#: because `[]` is the answer that reads as "this workflow does not invoke mypy"
#: and satisfies every rule in this file by describing nothing. Three of these
#: shapes returned exactly that, and two were demonstrated against the real
#: workflow before the parser was fixed.
_STEP_SHAPES: Final[list[tuple[str, list[tuple[str, ...]] | None]]] = [
    # The folded scalar, which was the live bypass: `>` folds the break to a
    # space, so these two lines are the single command `python -m mypy src`.
    (_one_job(_STEP, "        run: >", "          python -m mypy", "          src"), [("src",)]),
    # Its discriminating control. The same two lines under `|` really are two
    # commands, the first of them bare — which is what `>` used to be read as.
    (_one_job(_STEP, "        run: |", "          python -m mypy", "          src"), [()]),
    # A more-indented line in a folded scalar is YAML's third joining rule.
    (_one_job(_STEP, "        run: >", "          python -m mypy", "            src"), None),
    # The plainly caught control, and the bare form that must stay accepted.
    (_one_job(_STEP, "        run: |", "          python -m mypy src"), [("src",)]),
    (_one_job(_STEP, "        run: |", "          python -m mypy"), [()]),
    # The quoted scalar, which used to yield zero invocations in silence.
    (_one_job(_STEP, '        run: "python -m mypy src"'), [("src",)]),
    (_one_job(_STEP, "        run: 'python -m mypy src'"), [("src",)]),
    (_one_job(_STEP, '        run: "python -m mypy \\"src\\""'), None),
    # The flow-mapping step, which used to parse to a step with no `run:` key.
    (_one_job("      - {name: Typecheck, run: mypy src}"), None),
    # The four the reviewer verified already fail closed, pinned so they stay so.
    ("jobs:\n  only:\n    steps: [{name: T, run: mypy src}]", None),
    ("jobs:\n  a:\n    steps: &s\n      - run: mypy src\n  b:\n    steps: *s", None),
    ("jobs:\n  only:\n\t\tsteps:\n\t\t\t- run: mypy src", None),
    (_one_job("      - run: mypy") + "\n---\njobs:\n  b:\n    steps:\n      - run: mypy src", None),
]


@pytest.mark.parametrize(
    ("document", "expected"),
    _STEP_SHAPES,
    ids=[
        "a folded run folds, so its target is read",
        "the same lines under a literal block are two commands",
        "a folded run with a more-indented line is refused",
        "a literal block naming a target is caught",
        "a literal block naming none is bare",
        "a quoted run is unquoted, so its target is read",
        "a single-quoted run is unquoted too",
        "a quoted run carrying an escape is refused",
        "a flow-mapping step is refused",
        "a flow sequence of steps is refused",
        "an alias in a steps position is refused",
        "tab indentation is refused",
        "a second document is refused",
    ],
)
def test_the_parser_refuses_or_reads_every_step_shape_it_meets(
    document: str, expected: list[tuple[str, ...]] | None
) -> None:
    """The fail-closed table: loud, or right — never silently empty.

    The docstring above claims this parser raises on what it cannot read rather
    than skipping it. Four constructs falsified that, and two of them were
    demonstrated end-to-end by planting `D-64` into the real workflow and
    watching this file return green. Each is a row here beside a control that is
    known to be caught, so the table cannot pass by refusing everything and
    cannot pass by reading everything as bare.
    """
    if expected is None:
        with pytest.raises((ValueError, AssertionError)):
            _steps_in("planted.yml", document)
        return

    found = [
        arguments
        for _, _, script in _steps_in("planted.yml", document)
        for arguments in mypy_arguments(script)
    ]
    assert found == expected


def test_every_workflow_file_github_would_run_is_read(tmp_path: Path) -> None:
    """`.yaml` is not a second-class spelling, and this guard read only `.yml`.

    GitHub Actions runs both suffixes identically. A real
    `.github/workflows/extra-typecheck.yaml` invoking `python -m mypy src` was
    never opened by this file, so `D-64` could be restored in a new workflow with
    every gate green — not a narrower check but no check at all.
    """
    for name in ("a.yml", "b.yaml", "c.txt", "d.yml.bak", "e.YML"):
        (tmp_path / name).write_text("name: x\n", encoding="utf-8")
    (tmp_path / "f.yml").mkdir()

    assert [path.name for path in _workflow_files(tmp_path)] == ["a.yml", "b.yaml"]
    assert _workflow_files(WORKFLOWS), "the real workflow directory reads as empty"


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
        # Spellings a launcher, a variable or a matrix could reach the target
        # through. Each is caught today; each is here so it stays caught.
        ("uv run mypy src", [("src",)]),
        ("mypy $ARGS", [("$ARGS",)]),
        ("mypy ${{ matrix.target }}", [("${{", "matrix.target", "}}")]),
        ("mypy --config-file pyproject.toml", [("--config-file", "pyproject.toml")]),
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
