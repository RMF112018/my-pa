"""A query that reads a stored revision may not label the column `head`.

`public.alembic_version` records where a *database* is. It knows nothing about
where the repository's chain *ends*. So a query aliasing `version_num AS head`
turns every transcript of its output into a head claim, and the claim is false
whenever the database is behind — which, for canonical `my_pa`, is always and on
purpose: it sits at `6c4d3ea82f10`, five revisions below the chain.

**Three sites, three cycles, found one at a time.** `ops/runbooks/postgres-
operations.md` corrected the `Rev: … (head)` marker in its `alembic current`
transcript, then the `head` alias on its size query — its own note says "this was
its second site and the sweep that found the first did not reach it" — and the
third survived both sweeps in the **restore-verification** query, which is the
highest-consequence place in this repository for a false head claim: it is what
an operator reads before promoting a restored database. Three human sweeps of one
class is the signature this package has now hit four times, so this is the rule
instead.

**What is checked.** Every *revision-reading query* in repository-authored prose
and SQL: a region that both selects and names `alembic_version` or `version_num`.
Within one, no column may be aliased to a name that asserts the end of the chain.
The alias `revision` is what these queries say instead, and it is what the
runbook now uses.

**Named boundaries, so this rule is not described as closing more than it closes.**

- **Only aliases are read, not headings.** A psql transcript whose column header
  reads `head` because the query aliased it is caught through the query; a table
  of results pasted without its query is not, because nothing distinguishes it
  from prose. The corpus writes the query beside every transcript, which is why
  that costs nothing here and is stated rather than assumed.
- **The regions are exact, not heuristic.** In markdown a region is a fenced
  block; in Python it is a string constant, taken from the parsed module rather
  than by regex, so a docstring sentence and an executed SQL literal are read
  the same way and neither is guessed at. English prose outside those regions is
  not read at all: the plan says "answers exactly as head does" and the gateway
  runbook says "the same as head", and both are correct English about a
  comparison rather than aliases.
- **The implicit-alias branch reads position, not grammar.** It cannot tell a
  select list from a sentence, so a region that is prose *and* qualifies as a
  revision-reading query would have an English clause ending in "… head,"
  reported as an alias. No such region exists — measured, none across the
  searched corpus — and the branch is shaped to need that comma precisely so
  the prose already in the corpus stays out. The same branch reaches a *table*
  alias (`FROM public.alembic_version head`), which names no column and so is
  over-reach; it is kept, because the correction is the same word either way.
- **It does not check that the query is right**, only that its column does not
  claim to be the head. A query reading the wrong table, or reading the right one
  and being transcribed wrongly, is invisible here.
- The byte-faithful mirrors under `docs/specs/` (`D-44`) are excluded: a citation
  or a query inside one of them is not this repository's to correct.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

#: Top-level directories holding repository-authored prose and code. `evidence/`
#: is here for the reason it is in `test_citations_resolve_at_head.py`: an
#: acceptance or closeout document is prose a reviewer reads instead of the code,
#: and a transcript inside one asserting `head` over a database's own revision is
#: the same false claim wherever it is written.
SEARCHED_ROOTS = ("apps", "docs", "evidence", "migrations", "ops", "src", "tests")

#: Repository-root files that carry command transcripts.
SEARCHED_ROOT_FILES = ("AGENTS.md", "CONTRIBUTING.md", "README.md", "SECURITY.md")

#: Mirrored external packages, byte-faithful under `D-44`.
MIRRORED = (
    ROOT / "docs" / "specs" / "canonical-product-definition",
    ROOT / "docs" / "specs" / "quick-capture",
)

SKIPPED_DIRECTORIES = frozenset(
    {".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv", "__pycache__", "node_modules"}
)

#: The relation and the column that hold a database's own revision. `version_num`
#: carries a word boundary so that `version_number` — a capture column, and a
#: different thing entirely — is not read as one.
STORED_REVISION = re.compile(r"alembic_version|\bversion_num\b", re.IGNORECASE)

_SELECT = re.compile(r"\bselect\b", re.IGNORECASE)

#: An alias, in the spellings PostgreSQL accepts for one. `AS name` was the only
#: one this pattern read at first, so `AS "head"` — where the quotes are not
#: `\w` — and a bare implicit `head` each produced a column literally named
#: `head` that this rule passed. Both are widened into the pattern the rule
#: already owns rather than carried as a known hole (`D-88`).
#:
#: **The implicit branch is positional, not an optional `AS`.** Making the
#: keyword optional matches every word in the region, and the regions this rule
#: reads are not all SQL: `database_revisions` in `apps/cli/health.py` qualifies as a
#: revision-reading query while being English prose, because it names the table
#: and the verb. Measured over all 14805 regions the corpus then held, an
#: optional-`AS` branch found one such word — `head` in the prose of
#: `tests/schema/test_head_round_trip.py`, a region one `SELECT` away from being
#: read — and this branch found none. Re-measured over the 74104 regions the
#: corpus holds now, with `evidence/` admitted, neither branch finds one; that
#: makes the loose branch currently unlucky rather than safe, which is why the
#: positional one is still what ships. So an implicit alias is required to sit
#: where an alias sits: after something an expression can end with, and before
#: the comma, the `FROM`, or the end of the select list.
_ALIAS = re.compile(
    r'\bAS\s+"?(?P<name>\w+)"?'
    r'|(?<=[\w")])\s+"?(?P<implicit>\w+)"?\s*(?=,|\bFROM\b|$)',
    re.IGNORECASE,
)

#: Names that assert the end of the chain rather than the state of a database.
#: `revision` and `version_num` are the honest ones and are absent by design.
HEAD_NAMES = frozenset({"head", "chain_head", "current_head", "latest", "latest_revision"})

_FENCE = re.compile(r"^```[^\n]*\n(.*?)^```", re.MULTILINE | re.DOTALL)

#: The fewest revision-reading queries before this rule is deciding anything. A
#: region extractor that silently returned nothing would satisfy the rule below
#: over an empty set, which is the failure mode that let six planted violations
#: through a guard in this campaign. Measured over the same universe this rule
#: walks: **twenty-three**, of which four are the original ones — `apps/cli/
#: health.py`'s docstring, the two `psql` blocks in
#: `ops/runbooks/postgres-operations.md`, and the `SELECT` in
#: `src/my_pa/infrastructure/migration/binding.py` — and the remaining nineteen
#: are the `alembic_version` reads the schema-tier round-trip modules make.
#: `evidence/` contributes none. The floor is left just under the original four
#: rather than raised to the measurement, so a rehearsal query removed by a
#: later package does not redden this rule while losing the extractor still
#: does.
FEWEST_QUERIES = 3


@dataclass(frozen=True)
class Region:
    """One place a query may be written, and where it starts."""

    path: Path
    line: int
    text: str

    @property
    def where(self) -> str:
        return f"{self.path.relative_to(ROOT)}:{self.line}"


def searched_files() -> list[Path]:
    """Every searched file except this one.

    This module is the one file in the sweep whose queries are *data about*
    violations rather than violations: the plants below are written wrong on
    purpose, and reading itself would make every one of them a finding. The same
    exclusion, for the same reason, as the spelled-count guard's own sweep.
    """
    found: list[Path] = []
    for name in SEARCHED_ROOT_FILES:
        candidate = ROOT / name
        if candidate.is_file():
            found.append(candidate)
    for root_name in SEARCHED_ROOTS:
        root = ROOT / root_name
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix not in (".md", ".py", ".sql") or not path.is_file():
                continue
            if SKIPPED_DIRECTORIES & set(path.parts):
                continue
            if any(path.is_relative_to(mirror) for mirror in MIRRORED):
                continue
            if path == Path(__file__).resolve():
                continue
            found.append(path)
    return sorted(set(found))


def regions_in(path: Path) -> list[Region]:
    """Every region of `path` that may hold a query.

    A fenced block in markdown, a string constant in Python — taken from the
    parsed module, so the boundary is the language's and not a regex's — and the
    whole file for `.sql`.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    if path.suffix == ".sql":
        return [Region(path, 1, text)]
    if path.suffix == ".md":
        return [
            Region(path, text[: match.start(1)].count("\n") + 1, match.group(1))
            for match in _FENCE.finditer(text)
        ]
    try:
        tree = ast.parse(text)
    except SyntaxError:  # pragma: no cover - defensive; the tier would not import it either
        return []
    return [
        Region(path, node.lineno, node.value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def revision_queries() -> list[Region]:
    """Every region that both selects and names a stored revision."""
    return [
        region
        for path in searched_files()
        for region in regions_in(path)
        if STORED_REVISION.search(region.text) and _SELECT.search(region.text)
    ]


def head_aliases(text: str) -> list[str]:
    """Every alias in `text` that asserts the end of the chain.

    Split on the statement separator first, so an alias belonging to a query
    that reads something else is not attributed to the one that reads the
    revision. The restore-verification query is exactly this shape: four
    subqueries in one statement, only one of which reads `alembic_version`.
    """
    found: list[str] = []
    for statement in text.split(";"):
        if not STORED_REVISION.search(statement):
            continue
        found.extend(
            match.group(0).strip()
            for match in _ALIAS.finditer(statement)
            if (match["name"] or match["implicit"]).lower() in HEAD_NAMES
        )
    return found


QUERIES = revision_queries()


def test_the_sweep_found_queries_to_decide_over() -> None:
    assert len(QUERIES) >= FEWEST_QUERIES, (
        f"only {len(QUERIES)} revision-reading quer(ies) parsed; every rule here is an "
        "emptiness test over this set"
    )


def test_no_revision_reading_query_aliases_a_column_to_the_chain_head() -> None:
    labelled = sorted(
        f"{region.where} aliases {alias!r}"
        for region in QUERIES
        for alias in head_aliases(region.text)
    )
    assert not labelled, (
        f"{len(labelled)} quer(ies) label a stored revision as the head of the chain. "
        "`alembic_version` records where a database is, not where the chain ends, so a "
        "transcript of that column under the name `head` is a false claim about the "
        f"repository; alias it `revision`: {labelled}"
    )


# ---- the plants ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("statement", "flagged"),
    [
        ("SELECT (SELECT version_num FROM public.alembic_version) AS head, 1 AS fks", True),
        ("SELECT (SELECT version_num FROM public.alembic_version) AS revision, 1 AS fks", False),
        ("select version_num as HEAD from public.alembic_version", True),
        ("SELECT version_num AS revision, pg_database_size('my_pa') AS size", False),
        ("SELECT capture_id AS head FROM knowledge.capture_versions", False),
        ("SELECT version_number AS head FROM knowledge.capture_versions", False),
        ('SELECT (SELECT version_num FROM public.alembic_version) AS "head", 1 AS fks', True),
        ("SELECT (SELECT version_num FROM public.alembic_version) head, 1 AS fks", True),
        ('SELECT version_num AS "revision" FROM public.alembic_version', False),
        ("SELECT av.version_num FROM public.alembic_version av", False),
        ("SELECT version_num FROM public.alembic_version head", True),
    ],
    ids=[
        "the defect, in the shape it shipped in",
        "and the correction, which must stay green",
        "the alias is read in any case",
        "the honest alias beside another alias",
        "a query reading something else is not this rule's business",
        "nor is `version_number`, which is a capture column",
        "the quoted identifier, which `\\w` alone does not reach",
        "the implicit alias, which has no `AS` to key on",
        "quoting the honest alias does not make it a claim",
        "an ordinary table alias is not every word in the region",
        "a table aliased `head` is reached too, which is over-reach and named",
    ],
)
def test_the_rule_separates_a_head_claim_from_an_honest_alias(
    statement: str, flagged: bool
) -> None:
    """Both ends, because a rule that flagged every `AS` would prove nothing.

    The last two are the false-finding end and both are live: `capture_versions`
    carries a `version_number`, which contains `version_num` as a substring and
    is not a schema revision.
    """
    assert bool(head_aliases(statement)) is flagged


def test_the_alias_of_a_neighbouring_subquery_is_not_attributed_to_this_one() -> None:
    """Statement scope, planted at its boundary.

    Two statements, one reading the revision honestly and one aliasing something
    else to `head`. Attributing across the separator would report a finding in
    the query that is correct, which is how a rule earns the reputation that
    gets it deleted.
    """
    planted = (
        "SELECT version_num AS revision FROM public.alembic_version;\n"
        "SELECT count(*) AS head FROM pg_constraint;\n"
    )
    assert head_aliases(planted) == []


def test_a_planted_alias_is_found_through_the_region_extractor(tmp_path: Path) -> None:
    """End to end through a fenced block, which is the form the defect took.

    The green half is in the same fixture: an identical query in the same file
    with the honest alias, so this proves the extractor reads the block rather
    than that it reads the file.
    """
    planted = tmp_path / "planted.md"
    planted.write_text(
        'Verify:\n\n```sh\npsql -c "SELECT (SELECT version_num FROM '
        'public.alembic_version) AS head;"\n```\n\n'
        'Corrected:\n\n```sh\npsql -c "SELECT (SELECT version_num FROM '
        'public.alembic_version) AS revision;"\n```\n',
        encoding="utf-8",
    )

    regions = [
        region
        for region in regions_in(planted)
        if STORED_REVISION.search(region.text) and _SELECT.search(region.text)
    ]
    assert len(regions) == 2, regions
    assert [bool(head_aliases(region.text)) for region in regions] == [True, False]


def test_a_python_string_is_a_region_and_a_comment_is_not(tmp_path: Path) -> None:
    """The `.py` half of the extractor, and the boundary the module docstring names.

    SQL lives in string constants in this repository — `binding.py` holds one —
    and a comment is not a region, because a comment cannot be executed. Both
    halves are asserted so that the parse is shown to be discriminating rather
    than merely non-empty.
    """
    planted = tmp_path / "planted.py"
    planted.write_text(
        "# SELECT version_num FROM public.alembic_version AS head\n"
        'QUERY = "SELECT version_num AS head FROM public.alembic_version"\n',
        encoding="utf-8",
    )

    regions = [region for region in regions_in(planted) if STORED_REVISION.search(region.text)]
    assert len(regions) == 1, regions
    assert head_aliases(regions[0].text) == ["AS head"]
