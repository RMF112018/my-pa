"""Retrieval is lexical, and there is no vector machinery anywhere to make it otherwise.

`docs/specs` section 23: *"Semantic/vector retrieval remains benchmark/security
gated. Do not implement vector infrastructure merely because it is technically
available."* This is the guard that makes the sentence checkable, and it is the
evidence an independent reviewer is entitled to demand for it.

**Written to be hard to satisfy vacuously**, because the shape of the claim
invites it: "no embeddings exist" is trivially true of a tree nobody looked at.
Six properties, each quantified over a *derived* universe rather than over a list
of files somebody remembered, and each with a control that plants the thing it is
looking for and asserts the detector finds it.

1. **No column, table or index in the live schema is vector machinery.** Read off
   `METADATA` — every table, every column, every column type, every index — not
   off `tables.py` as text, so a declaration built by a helper is examined the
   same as one written out.
2. **No revision installs a vector extension, an ANN index, a vector operator,
   or a column or index *named* for one.** Every revision file's SQL strings,
   read with the operator vocabulary *and* the schema-name vocabulary, plus the
   extension list the foundation revision declares. The name half is what rule 1
   structurally cannot supply: `op.execute("ALTER TABLE ... ADD COLUMN
   note_embedding real[]")` installs a column no `Table` object in this process
   has ever heard of, so `METADATA` reports nothing and the migration is the
   whole of the evidence there is. Three revisions write no DDL literal at all
   and execute `migrations/sql/*.sql` instead; those twenty-four thousand lines
   are swept too, and the two ported legacy tables named for embeddings and
   similarity are registered by name in `PORTED_VECTOR_NAMES` rather than left
   for a reader to discover.
3. **No module imports an embedding or model provider.** Every `import` in
   `src/` and `apps/`, read as a syntax tree, matched against a closed list of
   distributions — and against every requirement in every dependency block of
   `pyproject.toml`, runtime, extra or group alike, so a provider that arrived as
   a dependency without an import yet still reddens.
4. **No similarity operator or similarity function is written anywhere.**
   `pg_trgm` *is* installed, and `persistence.search` records that it is
   deliberately unused because similarity is a different question from lexical
   match. That paragraph is a promise; this is the check. The `<->`, `<=>` and
   `<#>` distance operators are refused in the same sweep — they are pgvector's,
   and `<->` is also `pg_trgm`'s distance operator, so one rule covers both.
5. **The knowledge application contract binds to no provider.** The public
   contract, the domain and the application layer are searched for provider
   names, so "provider-neutral" is a property of the interface rather than of
   which adapter happens to be installed.
6. **The vocabularies this guard uses are pinned as exact equalities**, so
   emptying one reddens instead of quietly making every rule above pass.

**What this does not claim.** It does not claim the product could never do
semantic retrieval; it claims that today no part of it can, that nothing is
staged for it, and that turning it on would be a visible change rather than the
flip of a flag. That is exactly the gate section 23 asks for, and WP-24's
`OD-COMP-007` is where it is decided.

Nothing here opens a connection. It reads `METADATA`, parses source, and reads
migration text.
"""

from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Index, Table

from my_pa.infrastructure.persistence import tables as declarations

ROOT: Final = Path(__file__).resolve().parents[2]
PACKAGE: Final = ROOT / "src" / "my_pa"
APPS: Final = ROOT / "apps"
REVISIONS: Final = ROOT / "migrations" / "versions"
PYPROJECT: Final = ROOT / "pyproject.toml"

#: Layers whose *contract* must name no model or embedding provider. The public
#: contract, the domain, and the use cases: the three that a caller, a reviewer
#: or a second implementation would read to know what this system promises.
PROVIDER_NEUTRAL_LAYERS: Final = ("contracts", "domain", "application")

#: Words that name vector-retrieval machinery in a schema object's name. Matched
#: as substrings against lower-cased table, column and index names, because a
#: column called `note_embedding` and one called `embedding_of_note` are the same
#: decision.
#:
#: `vector` is deliberately absent and its absence is the interesting one: the
#: word appears in `tsvector`, which is exactly the lexical machinery this system
#: *does* use, so a substring rule on it would forbid full-text search. Vector
#: *types* are caught by rule 1's type check and vector *operators* by rule 4,
#: neither of which can be confused by a tsvector.
SCHEMA_WORDS: Final = frozenset(
    {
        "embedding",
        "embed_",
        "hnsw",
        "ivfflat",
        "faiss",
        "cosine",
        "centroid",
        "nearest_neighbour",
        "nearest_neighbor",
        "knn",
        "ann_index",
        "semantic_index",
        "similarity",
    }
)

#: Distributions that provide an embedding model, a model API client, or a vector
#: store. An import of any of these is a binding to a provider, which the
#: knowledge contract must not have; a declaration of any of them is the same
#: binding one step earlier.
PROVIDER_DISTRIBUTIONS: Final = frozenset(
    {
        "openai",
        "anthropic",
        "cohere",
        "voyageai",
        "mistralai",
        "google.generativeai",
        "sentence_transformers",
        "transformers",
        "torch",
        "tensorflow",
        "onnxruntime",
        "faiss",
        "pgvector",
        "chromadb",
        "pinecone",
        "qdrant_client",
        "weaviate",
        "lancedb",
        "milvus",
        "llama_index",
        "langchain",
        "haystack",
        "ollama",
        "litellm",
        "huggingface_hub",
        "sklearn",
    }
)

#: SQL fragments that install, index, or query a vector or similarity space.
#: Matched case-insensitively against every string literal in every revision and
#: every module, because a statement is a string wherever it is written.
#:
#: `<=>` and `<#>` are pgvector's cosine and inner-product operators and mean
#: nothing else in PostgreSQL, so they are swept over every literal including
#: prose. `<->` is not here and has its own rule below, for a reason worth
#: stating rather than quietly dropping it. `similarity(` and `word_similarity(`
#: are `pg_trgm`'s functions: the extension is installed and
#: `persistence.search` states that it is deliberately unused, and this is what
#: turns that statement into a checked claim.
SQL_FRAGMENTS: Final = frozenset(
    {
        'create extension if not exists "vector"',
        "create extension vector",
        "using ivfflat",
        "using hnsw",
        "vector_cosine_ops",
        "vector_l2_ops",
        "vector_ip_ops",
        "gin_trgm_ops",
        "gist_trgm_ops",
        "similarity(",
        "word_similarity(",
        "<=>",
        "<#>",
        "::vector",
    }
)

#: The distance operator that is *not* unambiguous, swept separately.
#:
#: `<->` is pgvector's L2 distance and `pg_trgm`'s distance, and it is also
#: PostgreSQL's own `tsquery` phrase-adjacency operator — `foo <-> bar` means
#: "followed by". `persistence.search`'s module docstring writes exactly that,
#: while explaining that `websearch_to_tsquery` reduces it to an ordinary `AND`,
#: which is a paragraph about lexical search and not a distance query. Banning
#: the three characters everywhere would therefore forbid the documentation of
#: the lexical machinery this system does use. So it is swept over *executable*
#: string literals only — every constant that is not a docstring — which is where
#: a statement lives and where prose does not. The narrowing is stated here
#: rather than left as an unexplained absence, because an unexplained absence is
#: how a guard acquires a hole.
DISTANCE_OPERATOR: Final = "<->"

#: The extensions the foundation revision installs. An exact equality, so a
#: fourth arriving is a decision rather than a diff — which is the whole of how
#: `vector` would arrive.
INSTALLED_EXTENSIONS: Final = ("pg_trgm", "unaccent")

#: Every object in the ported target schema whose *name* carries one of
#: `SCHEMA_WORDS`, as an exact registry.
#:
#: **These are not this system's retrieval machinery and they are not nothing
#: either, so they are written down.** `1e6c0a94f3b7` and the two revisions after
#: it create 484 tables ported from the legacy SQLite database, and the DDL lives
#: in `migrations/sql/*.sql` rather than in a Python literal — twenty-four
#: thousand lines that no rule in this file read until the registry below existed.
#: Two of those tables are named for embeddings and similarity: `content_embeddings`
#: is the legacy system's own embedding ledger and `candidate_similarity_edges` is
#: its clustering output, and everything else here is a constraint, index, key or
#: column of one of them.
#:
#: What makes them not a hole is the rule beside this one:
#: `test_no_sql_file_the_chain_executes_installs_a_vector_space` reads the same
#: files for `SQL_FRAGMENTS` and for `<->` and finds none, so there is no vector
#: type, no ANN access method, no distance operator and no extension anywhere in
#: them. A ported table with a `similarity_score` column that nothing computes
#: and nothing queries is inherited data shape, not staged infrastructure. The
#: registry is exact so that a twenty-eighth name is a decision someone writes
#: down rather than a diff nobody reads.
PORTED_VECTOR_NAMES: Final = (
    "candidate_similarity_edges",
    "candidate_similarity_edges_calendar_mutation_performed_ck13",
    "candidate_similarity_edges_download_url_persisted_ck8",
    "candidate_similarity_edges_email_send_performed_ck12",
    "candidate_similarity_edges_external_writeback_performed_ck9",
    "candidate_similarity_edges_graph_writeback_performed_ck10",
    "candidate_similarity_edges_pkey",
    "candidate_similarity_edges_procore_writeback_performed_ck11",
    "candidate_similarity_edges_raw_calendar_payload_persisted_ck3",
    "candidate_similarity_edges_raw_document_text_persisted_ck2",
    "candidate_similarity_edges_raw_email_body_persisted_ck1",
    "candidate_similarity_edges_raw_procore_payload_persisted_ck4",
    "candidate_similarity_edges_raw_prompt_persisted_ck5",
    "candidate_similarity_edges_raw_response_persisted_ck6",
    "candidate_similarity_edges_signed_url_persisted_ck7",
    "content_embeddings",
    "content_embeddings_fk0",
    "content_embeddings_pkey",
    "content_embeddings_uq1",
    "ix_candidate_similarity_edges_a",
    "ix_candidate_similarity_edges_b",
    "ix_candidate_similarity_edges_cluster",
    "ix_candidate_similarity_edges_date",
    "name_similarity",
    "similarity_edge_id",
    "similarity_method",
    "similarity_score",
)


def _modules() -> tuple[Path, ...]:
    return tuple(sorted(PACKAGE.rglob("*.py"))) + tuple(sorted(APPS.rglob("*.py")))


def _revision_files() -> tuple[Path, ...]:
    return tuple(sorted(REVISIONS.glob("*.py")))


def _sql_files() -> tuple[Path, ...]:
    """The `.sql` files three revisions read and execute statement by statement."""
    return tuple(sorted((REVISIONS.parent / "sql").glob("*.sql")))


def quoted_identifiers(text: str) -> frozenset[str]:
    """Every double-quoted identifier in a block of SQL.

    Public, because the registry below is measured with it. The generated target
    DDL quotes every identifier it writes, which is what makes the set readable
    without parsing SQL.
    """
    return frozenset(re.findall(r'"([A-Za-z0-9_]+)"', text))


def _tables() -> tuple[Table, ...]:
    return tuple(declarations.METADATA.tables.values())


def _indexes() -> tuple[Index, ...]:
    return tuple(index for table in _tables() for index in table.indexes)


def schema_words_in(name: str) -> tuple[str, ...]:
    """Which vector-machinery words a schema object's name contains.

    Public: the controls below run it over names that really are vector
    machinery, so a zero from the live schema is a measurement rather than a
    matcher that matches nothing.
    """
    lowered = name.lower()
    return tuple(sorted(word for word in SCHEMA_WORDS if word in lowered))


def sql_fragments_in(text: str) -> tuple[str, ...]:
    """Which vector or similarity SQL fragments one string contains."""
    lowered = text.lower()
    return tuple(sorted(fragment for fragment in SQL_FRAGMENTS if fragment in lowered))


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def _docstring_nodes(tree: ast.Module) -> set[int]:
    """Every string constant that is a docstring, by identity.

    A docstring is the first statement of a module, class or function, which is
    exactly what `ast.get_docstring` decides; collecting the node identities is
    what lets one sweep read every literal and another read only the executable
    ones.
    """
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

    Public, because a control below folds each shape and asserts the result, so
    the sweep that uses it is measured rather than assumed.

    Adjacent literals — `"note_" "embedding"` — need nothing here: CPython's own
    parser joins them into a single constant before this file ever sees them.
    What does need folding is the three shapes that survive parsing. `"note_" +
    "embedding"` stays a `BinOp`, so a per-literal sweep reads two harmless
    halves. An f-string stays a `JoinedStr` whose constant parts are separate
    nodes, so DDL assembled around a substituted name is read the same way.
    `"".join(("embed", "ding"))` stays a `Call` over two literals that are each
    innocent. All three are how a statement gets written without any one literal
    spelling it, and the third is the one this file's own first fix still let
    through.

    A substituted value is dropped rather than guessed at, which makes the fold
    an under-approximation: `f"USING {method}"` folds to `USING `, and a word
    split *across* a substitution is not reconstructed. That is the fail-open
    residual of this helper and it is stated rather than left to be found —
    `test_the_universes_this_guard_quantifies_over_are_not_empty` and the
    per-literal sweep still read every constant part on its own.
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


def _ddl_bearing_files() -> tuple[Path, ...]:
    """Every file in this repository that can hand a statement to the server.

    The revisions, the Alembic environment beside them, and every module of
    `src/` and `apps/`. Derived rather than listed, and wider than "the
    revisions" on purpose: `migrations/env.py` is a sibling of the chain that no
    `versions/*.py` glob reaches, and a `CREATE INDEX` issued from a runtime
    module is the same index as one issued from a migration. A rule that read
    only the directory where the plant was found would be a rule against that
    plant rather than against the thing it is an instance of.
    """
    support = tuple(sorted(REVISIONS.parent.glob("*.py")))
    return (*_revision_files(), *support, *_modules())


def _statement_texts(path: Path) -> list[tuple[int, str]]:
    """Every string one file could execute, per literal and per assembly.

    Docstrings are excluded, and the exclusion is load-bearing in one direction
    only: a revision's prose explains what it does, and
    `2b7e9f4c1a83` uses the word *embedding* in the ordinary English sense while
    describing a literal it declines to hoist into a constant. A sweep that read
    prose would report that paragraph and the vocabulary would have to be
    narrowed to survive it, which is how a guard loses the word that matters. A
    docstring executes nothing, so nothing is lost by not reading them here.
    """
    return [*_string_literals(path, executable_only=True), *_assembled_strings(path)]


def test_the_universes_this_guard_quantifies_over_are_not_empty() -> None:
    """Guards every rule below: an empty sweep satisfies all of them."""
    assert len(_tables()) >= 40, "the schema scan is not reading the schema"
    assert len(_indexes()) >= 20, "no index was read; rule 1's index half proves nothing"
    assert len(_modules()) >= 100, "the module scan is not reading the tree"
    assert len(_revision_files()) >= 25, "the revision scan is not reading the chain"
    columns = [column for table in _tables() for column in table.columns]
    assert len(columns) >= 300, f"only {len(columns)} columns were read"


def test_the_vocabularies_are_closed_at_the_sizes_they_declare() -> None:
    """A vocabulary with no floor passes when it is emptied.

    Exact equalities rather than floors, so growing one is a decision recorded
    here and shrinking one reddens — which is the failure mode three consecutive
    packages found in guards of their own.
    """
    assert len(SCHEMA_WORDS) == 13
    assert len(PROVIDER_DISTRIBUTIONS) == 26
    assert len(_NORMALISED_PROVIDERS) == 26, (
        "two providers normalise to one name, so the set the dependency scan "
        "compares against is smaller than the set this file declares"
    )
    assert len(SQL_FRAGMENTS) == 14
    assert len(INSTALLED_EXTENSIONS) == 2
    assert len(PROVIDER_NEUTRAL_LAYERS) == 3
    assert len(PORTED_VECTOR_NAMES) == 27


def test_no_table_column_or_index_in_the_live_schema_is_vector_machinery() -> None:
    """Property 1, read off `METADATA` rather than off the text that builds it."""
    offending: list[str] = []
    for table in _tables():
        offending.extend(
            f"table {table.name} ({', '.join(schema_words_in(table.name))})"
            for _ in schema_words_in(table.name)[:1]
        )
        for column in table.columns:
            words = schema_words_in(column.name)
            if words:
                offending.append(f"{table.name}.{column.name} ({', '.join(words)})")
            rendered = type(column.type).__name__.lower()
            if "vector" in rendered or "embedding" in rendered:
                offending.append(f"{table.name}.{column.name} has type {rendered}")
    for index in _indexes():
        words = schema_words_in(index.name or "")
        if words:
            offending.append(f"index {index.name} ({', '.join(words)})")
    assert offending == [], (
        f"{offending} are vector-retrieval machinery in the live schema. Section 23 "
        "gates semantic retrieval behind a benchmark and a security review; a column "
        "or index staged for it is that gate opened quietly"
    )


def test_the_schema_scan_finds_the_machinery_when_there_is_some_to_find() -> None:
    """The control for property 1. Without it the rule above is a matcher of nothing."""
    for planted in ("note_embeddings", "embedding", "captures_by_cosine", "hnsw_index"):
        assert schema_words_in(planted), planted
    # And it distinguishes: the lexical machinery this system does use is not
    # vector machinery, which is the whole reason `vector` is not a schema word.
    for allowed in ("extractions_full_text", "to_tsvector", "text", "search_config"):
        assert schema_words_in(allowed) == (), allowed


def test_no_revision_installs_a_vector_extension_or_an_ann_index() -> None:
    """Property 2, over every string literal in every revision in the chain."""
    offending: list[str] = []
    for path in _revision_files():
        for lineno, literal in _string_literals(path):
            found = sql_fragments_in(literal)
            if found:
                offending.append(f"{path.name}:{lineno} {list(found)}")
    assert offending == [], (
        f"{offending} install or query a vector or similarity space. `pg_trgm` is "
        "installed and `persistence.search` records that it is deliberately unused; "
        "pgvector is not installed at all, and section 23 is why"
    )


def test_no_executed_statement_names_vector_machinery() -> None:
    """Property 2's other half, and it is the half `METADATA` cannot supply.

    Rule 1 reads the live declaration, which is the right place to look for a
    column `tables.py` declares and the *only* place a column declared there can
    hide. It is also blind by construction to DDL a revision executes as text:
    `op.execute("ALTER TABLE ... ADD COLUMN note_embedding real[]")` installs a
    column that no `Table` object in this process has ever heard of, and an
    `extractions_semantic_index` beside it is an ANN index in everything but the
    access method it happens to name.

    Rule 2 as first written was blind to both, because it matched only
    `SQL_FRAGMENTS` — a list of *access methods and operators* — against revision
    text, and never `SCHEMA_WORDS`, the list of names. A reviewer planted exactly
    the two statements above, unobfuscated, and the whole of `tests/architecture`
    and `tests/schema` stayed green. This is that hole closed: the full
    vocabulary, over every string anything in this repository executes,
    including the strings no single literal spells.

    **Wider than the plant, deliberately.** The sweep is over every revision,
    over `migrations/env.py` beside them, and over every module of `src/` and
    `apps/` — because `versions/*.py` is where the reviewer put it and not where
    the property lives. A `CREATE INDEX ... USING hnsw` issued from a runtime
    module installs the same index as one issued from a migration, and a guard
    written to the directory the plant was found in is a guard against that
    plant. Docstrings are excluded and the exclusion is measured rather than
    assumed: `2b7e9f4c1a83` uses *embedding* in the ordinary English sense while
    describing a literal it declines to hoist, and `persistence.search` explains
    at length why `pg_trgm`'s *similarity* stays unused. Prose that explains why
    a thing is absent must not be the reason the guard cannot name it.

    Section 23 forbids staging vector infrastructure at all, so the rule is on
    the *name* and not on the type: `real[]` is a perfectly ordinary PostgreSQL
    array and a column called `note_embedding` holding one is a vector store with
    the label filed off.
    """
    scanned = _ddl_bearing_files()
    assert len(scanned) >= 130, f"only {len(scanned)} statement-bearing files were read"
    offending: list[str] = []
    for path in scanned:
        for lineno, statement in _statement_texts(path):
            found = schema_words_in(statement)
            if found:
                offending.append(f"{path.relative_to(ROOT)}:{lineno} {list(found)}")
    assert offending == [], (
        f"{offending} name vector-retrieval machinery in DDL a revision executes. A "
        "column or index installed by a migration is invisible to the `METADATA` "
        "scan above, which is what makes this the load-bearing half: section 23 "
        "gates semantic retrieval behind a benchmark and a security review, and a "
        "migration is how that gate gets opened without a declaration to notice"
    )


def test_the_revision_ddl_scan_finds_each_shape_a_statement_can_be_written_in() -> None:
    """The control for the rule above, over the shapes that defeat a naive sweep.

    Four plants, and the last three exist because the first one is the only shape
    an author who is not hiding anything would use. A guard that read only whole
    literals would pass every one of the others.
    """
    for planted in (
        "ALTER TABLE knowledge.extractions ADD COLUMN note_embedding real[]",
        "CREATE INDEX extractions_semantic_index ON knowledge.extractions (note_embedding)",
        "CREATE INDEX notes_ann ON knowledge.notes USING hnsw (v)",
    ):
        assert schema_words_in(planted), planted

    # Assembly, one shape per node kind the fold understands. The implicit
    # concatenation is here to record that the *parser* closes it, not this file.
    for source, expected in (
        ('"note_" "embedding"', "note_embedding"),
        ('"note_" + "embedding"', "note_embedding"),
        ('f"ADD COLUMN {name}_embedding real[]"', "ADD COLUMN _embedding real[]"),
        ('"ALTER TABLE t " + f"ADD COLUMN {name}_embedding real[]"', None),
        ('"".join(("embed", "ding"))', "embedding"),
        ('"_".join(["note", "embedding"])', "note_embedding"),
    ):
        node = ast.parse(source, mode="eval").body
        assembled = folded(node)
        assert assembled is not None, source
        assert expected is None or assembled == expected, (source, assembled)
        assert schema_words_in(assembled), source

    # And it distinguishes: the DDL the chain really does execute is not vector
    # machinery, or the rule above would be reporting the whole chain to itself.
    for allowed in (
        'ALTER TABLE knowledge.audit_events DROP CONSTRAINT "capability_is_known"',
        "CREATE INDEX extractions_full_text ON knowledge.extractions USING gin "
        "(to_tsvector('english', text))",
        "CREATE EXTENSION IF NOT EXISTS pg_trgm",
    ):
        assert schema_words_in(allowed) == (), allowed

    # The fold is an under-approximation and says so; this is where that is
    # recorded as a measurement rather than a claim. A word split across a
    # substitution is not reconstructed, and the per-literal sweep is what still
    # reads each half.
    split = ast.parse('f"note_{prefix}embedding"', mode="eval").body
    assert folded(split) == "note_embedding"
    assert folded(ast.parse('f"embed{x}ding"', mode="eval").body) == "embedding"
    assert folded(ast.parse("value + other", mode="eval").body) is None


def test_no_sql_file_the_chain_executes_installs_a_vector_space() -> None:
    """Property 2 over the DDL that is not written in Python at all.

    `1e6c0a94f3b7`, `2f7d1ba05c48` and `3a8e2cb16d59` do not write their
    statements as literals: they read `migrations/sql/*.sql` and execute what is
    in them. That is twenty-four thousand lines of DDL the chain runs against a
    real database, and until this rule existed every sweep in this file walked
    past it, because none of them opens a file that is not Python.

    This is the *whole* vocabulary — the access methods, the operator forms, and
    `<->` — over the whole of those files. Prose is not a concern here: a `.sql`
    file is executable by definition, so nothing is excluded and nothing needs to
    be.
    """
    files = _sql_files()
    assert len(files) == 6, f"{len(files)} SQL files were found; the chain reads six"
    lines = sum(len(path.read_text(encoding="utf-8").splitlines()) for path in files)
    assert lines >= 20000, f"only {lines} lines of DDL were read"

    offending: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        found = [*sql_fragments_in(text)]
        if DISTANCE_OPERATOR in text:
            found.append(DISTANCE_OPERATOR)
        if found:
            offending.append(f"{path.name} {found}")
    assert offending == [], (
        f"{offending} install or query a vector or similarity space in DDL the "
        "chain executes from a file. The ported target schema carries two tables "
        "named for embeddings and similarity — `PORTED_VECTOR_NAMES` records them "
        "— and what makes those inherited data shape rather than staged "
        "infrastructure is precisely that this list is empty"
    )


def test_the_ported_schema_names_vector_machinery_only_where_it_is_registered() -> None:
    """The other half: the names, against an exact registry rather than a ban.

    A ban would be false — `content_embeddings` and `candidate_similarity_edges`
    are in the legacy database and the port carries them — and silence would be
    worse, because a reader of this file would conclude that no object anywhere
    in this repository is named for an embedding. So the twenty-seven names are
    written out, and a twenty-eighth reddens.
    """
    found: set[str] = set()
    for path in _sql_files():
        found |= {
            identifier
            for identifier in quoted_identifiers(path.read_text(encoding="utf-8"))
            if schema_words_in(identifier)
        }
    assert tuple(sorted(found)) == PORTED_VECTOR_NAMES, (
        f"{sorted(found ^ set(PORTED_VECTOR_NAMES))} is named for vector machinery "
        "in the ported target schema and is not registered, or is registered and "
        "is gone. Section 23 gates semantic retrieval; a new object named for it "
        "arriving through the port is that gate opened by inheritance"
    )
    # And the registry is two tables and their parts, not an open list: every
    # registered name belongs to one of them, so "twenty-seven" cannot quietly
    # become a third subject.
    roots = ("content_embeddings", "candidate_similarity_edges", "similarity_", "name_similarity")
    unaccounted = [name for name in PORTED_VECTOR_NAMES if not any(root in name for root in roots)]
    assert unaccounted == [], unaccounted
    assert len(PORTED_VECTOR_NAMES) == 27


def test_the_sql_file_scan_reads_a_file_that_really_names_one(tmp_path: Path) -> None:
    """The control for the two rules above, in both halves.

    Run over a file rather than a string, because "the sweep opens the file" is
    the part that was missing and the part a string plant would not exercise.
    """
    planted = tmp_path / "target_indexes.up.sql"
    planted.write_text(
        'CREATE INDEX "notes_ann" ON "core"."notes" USING hnsw ("note_embedding" '
        'vector_cosine_ops);\nCREATE TABLE "core"."semantic_index_probe" ();\n',
        encoding="utf-8",
    )
    text = planted.read_text(encoding="utf-8")
    assert sql_fragments_in(text)
    assert {name for name in quoted_identifiers(text) if schema_words_in(name)} == {
        "note_embedding",
        "semantic_index_probe",
    }

    # And it distinguishes: ordinary ported DDL is neither.
    ordinary = tmp_path / "target_tables.up.sql"
    ordinary.write_text(
        'CREATE TABLE "core"."documents" ("document_id" text PRIMARY KEY);\n', encoding="utf-8"
    )
    plain = ordinary.read_text(encoding="utf-8")
    assert sql_fragments_in(plain) == ()
    assert {name for name in quoted_identifiers(plain) if schema_words_in(name)} == set()


def test_the_installed_extensions_are_the_two_the_foundation_declares() -> None:
    """The list itself, so a third arriving is visible rather than inferred.

    Read out of the revision that installs them rather than restated, because the
    claim is about what the chain does and not about what this file remembers.
    """
    foundation = next(
        path for path in _revision_files() if "create_target_schemas_and_extensions" in path.name
    )
    tree = ast.parse(foundation.read_text(encoding="utf-8"), filename=str(foundation))
    declared = next(
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "EXTENSIONS"
    )
    installed = tuple(ast.literal_eval(declared))
    assert installed == INSTALLED_EXTENSIONS, (
        f"the chain installs {installed}. A vector extension arriving here is how "
        "vector retrieval becomes technically available, which section 23 names "
        "specifically as not being a reason to implement it"
    )


def test_no_module_imports_an_embedding_or_model_provider() -> None:
    """Property 3, over every import in `src/` and `apps/`."""
    offending: list[str] = []
    for path in _modules():
        for name in _imported_names(path):
            root = name.split(".")[0]
            if root in PROVIDER_DISTRIBUTIONS or name in PROVIDER_DISTRIBUTIONS:
                offending.append(f"{path.relative_to(ROOT)} imports {name}")
    assert offending == [], (
        f"{offending} bind this build to a model or embedding provider. The knowledge "
        "contract is provider-neutral, and an import is the strongest form of a "
        "binding there is"
    )


def distribution_named(requirement: str) -> str:
    """The normalised distribution name one requirement string declares.

    PEP 503's normalisation, because the packaging ecosystem treats `-`, `_` and
    `.` as the same character and this rule must too: `sentence-transformers` is
    the distribution and `sentence_transformers` is the import, and a comparison
    that read one spelling would miss a declaration of the other. Extras and
    version specifiers are cut, so `psycopg[binary]>=3.2,<4` is `psycopg`.
    """
    head = re.split(r"[\[<>=!~;\s]", requirement.strip(), maxsplit=1)[0]
    return re.sub(r"[-_.]+", "_", head).lower()


#: `PROVIDER_DISTRIBUTIONS` under the same normalisation, so the two sides of
#: every comparison are spelled the same way.
_NORMALISED_PROVIDERS: Final = frozenset(
    distribution_named(name) for name in PROVIDER_DISTRIBUTIONS
)


def declared_requirements(document: object, *, within: bool = False) -> tuple[str, ...]:
    """Every requirement string the project declares, from every block that declares one.

    Public, because a control below runs it over a document that declares a
    provider in each of the shapes a real `pyproject.toml` has.

    Derived by walking the parsed document for *any* list of strings reached
    through a key that names dependencies, rather than by slicing the one block
    somebody remembered. The first version of this rule read
    `[project.dependencies]` and nothing else, and a reviewer put `openai` and
    `pgvector` under `[project.optional-dependencies]` — where `pip install
    .[retrieval]` would resolve them — and left all fifteen rules of this file
    green. An extra is a dependency; so is a dependency group; so is whatever
    the next packaging standard calls one. Quantifying over the shape of the
    value instead of over the names of the blocks is what makes the next one
    arrive already covered.
    """
    found: list[str] = []
    if isinstance(document, dict):
        for name, value in document.items():
            named = "depend" in str(name) or "requires" in str(name)
            # Sticky, because the key that names dependencies is rarely the key
            # the list hangs off: an extra is `optional-dependencies.retrieval`
            # and a group is `dependency-groups.ml`, and a walk that only looked
            # at the *immediate* key would read neither.
            found.extend(declared_requirements(value, within=within or named))
    elif isinstance(document, list):
        if within:
            found.extend(item for item in document if isinstance(item, str))
        else:
            for item in document:
                found.extend(declared_requirements(item))
    return tuple(found)


def test_no_provider_is_a_declared_dependency() -> None:
    """Property 3's other half: a provider can arrive before anything imports it."""
    document = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    requirements = declared_requirements(document)
    # The floor and the two named requirements together are what stop this
    # passing over a document the walk failed to read: an empty sweep offends
    # nobody.
    assert len(requirements) >= 12, f"only {len(requirements)} requirements were read"
    assert {"sqlalchemy", "mcp"} <= {distribution_named(name) for name in requirements}, (
        "the dependency blocks were not located"
    )
    offending = sorted(
        requirement
        for requirement in requirements
        if distribution_named(requirement) in _NORMALISED_PROVIDERS
    )
    assert offending == [], (
        f"{offending} are declared dependencies. A provider in any dependency "
        "block — runtime, extra, or group — is vector infrastructure one import "
        "away, and an extra is the shape that installs on a real machine while "
        "looking optional in the file"
    )


def test_the_dependency_scan_reads_every_block_a_provider_could_arrive_in() -> None:
    """The control for the rule above, one plant per block shape.

    The extra is the case that was open, so it is written out here rather than
    covered by a loop, and the group beside it is the block this project does
    not use today and would be read the same way if it did.
    """
    planted = tomllib.loads(
        "[project]\n"
        'dependencies = ["SQLAlchemy>=2.0.20,<3"]\n'
        "[project.optional-dependencies]\n"
        'retrieval = ["openai>=1.40", "pgvector>=0.3"]\n'
        "[dependency-groups]\n"
        'ml = ["sentence-transformers>=3"]\n'
        "[build-system]\n"
        'requires = ["setuptools>=77"]\n'
    )
    requirements = declared_requirements(planted)
    assert set(requirements) == {
        "SQLAlchemy>=2.0.20,<3",
        "openai>=1.40",
        "pgvector>=0.3",
        "sentence-transformers>=3",
        "setuptools>=77",
    }
    named = {
        distribution_named(requirement)
        for requirement in requirements
        if distribution_named(requirement) in _NORMALISED_PROVIDERS
    }
    # `sentence-transformers` is the plant that matters most here: the import
    # name is `sentence_transformers` and the *distribution* name is spelled
    # with a hyphen, so a comparison that did not normalise the separator would
    # read the declaration and not recognise it.
    assert named == {"openai", "pgvector", "sentence_transformers"}

    # And it distinguishes, in the direction that matters: a requirement whose
    # name merely *starts* with a provider's is not that provider, or the rule
    # would report a dependency for the letters it shares.
    for innocent in ("openai-compatible-nothing", "torchless", "faiss-stub-typing", "mcp>=2.0,<3"):
        assert distribution_named(innocent) not in _NORMALISED_PROVIDERS, innocent


def test_no_similarity_operator_or_function_is_written_in_the_tree() -> None:
    """Property 4. `pg_trgm` is installed and this is what keeps it unused.

    Similarity is a different retrieval question from lexical match — fuzzy and
    misspelled input — and `persistence.search` records that adding it would
    introduce a second relevance signal with no benchmark to weigh it against the
    first. That paragraph is prose; the sweep below is the rule.
    """
    offending: list[str] = []
    for path in _modules():
        for lineno, literal in _string_literals(path):
            found = sql_fragments_in(literal)
            if found:
                offending.append(f"{path.relative_to(ROOT)}:{lineno} {list(found)}")
    assert offending == [], (
        f"{offending} write a similarity or vector-distance expression. Retrieval "
        "here is lexical; `pg_trgm` stays installed and unused, and pgvector is not "
        "installed at all"
    )


def test_no_executable_statement_writes_a_distance_operator() -> None:
    """Property 4's narrowed half, and the narrowing is the interesting part.

    `<->` is pgvector's L2 distance, `pg_trgm`'s distance, *and* `tsquery`'s
    phrase-adjacency operator. `persistence.search` writes it in prose while
    explaining that `websearch_to_tsquery` reduces `foo <-> bar` to an ordinary
    `AND`, so a sweep that read docstrings would forbid documenting the lexical
    machinery this system does use. Executable literals only, therefore — every
    string constant that is not a module, class or function docstring — which is
    where a statement lives.
    """
    offending: list[str] = []
    for path in (*_modules(), *_revision_files()):
        for lineno, literal in _string_literals(path, executable_only=True):
            if DISTANCE_OPERATOR in literal:
                offending.append(f"{path.relative_to(ROOT)}:{lineno}")
    assert offending == [], (
        f"{offending} write a `<->` distance expression in an executable string. "
        "Inside a tsquery that is phrase adjacency and inside a vector or trigram "
        "expression it is a distance query; a statement that needs one is a "
        "retrieval decision section 23 gates"
    )
    # The control, in both directions: the narrowing must still find a planted
    # statement, and the docstring it excludes must still be there to exclude —
    # otherwise "executable only" would be a filter over an empty set.
    module = PACKAGE / "infrastructure" / "persistence" / "search.py"
    assert DISTANCE_OPERATOR in module.read_text(encoding="utf-8"), (
        "the tsquery paragraph this narrowing exists for is gone; either the "
        "narrowing or this test is now describing something that is not there"
    )
    assert not [
        literal
        for _lineno, literal in _string_literals(module, executable_only=True)
        if DISTANCE_OPERATOR in literal
    ]


def test_the_sql_scan_finds_a_planted_statement_of_each_shape() -> None:
    """The control for properties 2 and 4, one plant per shape the rule reads."""
    for planted in (
        'CREATE EXTENSION IF NOT EXISTS "vector"',
        "CREATE INDEX notes_ann ON knowledge.notes USING hnsw (embedding vector_cosine_ops)",
        "CREATE INDEX notes_trgm ON knowledge.notes USING gin (text gin_trgm_ops)",
        "SELECT similarity(text, :query) FROM knowledge.extractions",
        "SELECT embedding <=> :probe FROM knowledge.notes ORDER BY 1",
        "SELECT :probe::vector",
    ):
        assert sql_fragments_in(planted), planted
    # `<->` is the one fragment this list does not hold, and the reason is at
    # `DISTANCE_OPERATOR`. Asserted here so the absence reads as a decision
    # rather than as an omission a reader has to notice.
    assert sql_fragments_in("SELECT embedding <-> :probe FROM knowledge.notes") == ()
    # And it distinguishes: the statements this system really does build are not
    # similarity statements, or the production sweep above would be reporting the
    # search module to itself.
    for allowed in (
        "to_tsvector('english', text)",
        "websearch_to_tsquery",
        "ts_rank_cd",
        "CREATE INDEX extractions_full_text ON knowledge.extractions USING gin "
        "(to_tsvector('english', text))",
    ):
        assert sql_fragments_in(allowed) == (), allowed


@pytest.mark.parametrize("layer", PROVIDER_NEUTRAL_LAYERS)
def test_the_knowledge_contract_names_no_model_or_embedding_provider(layer: str) -> None:
    """Property 5. Neutrality is a property of the interface, not of the adapter set.

    Every module of the layer is read as text rather than as imports, because a
    provider named in a type, a constant, a docstring's promise or a settings key
    is a binding a caller would read as one even with nothing importing it.
    """
    root = PACKAGE / layer
    assert root.is_dir(), f"{layer} is not a package; this rule is reading nothing"
    modules = tuple(sorted(root.rglob("*.py")))
    assert modules, f"{layer} holds no modules"
    offending: list[str] = []
    for path in modules:
        lowered = path.read_text(encoding="utf-8").lower()
        offending.extend(
            f"{path.relative_to(ROOT)} names {name}"
            for name in PROVIDER_DISTRIBUTIONS
            if re.search(rf"\b{re.escape(name)}\b", lowered)
        )
    assert offending == [], (
        f"{offending} name a model or embedding provider inside the "
        f"provider-neutral `{layer}` layer. What this build retrieves with is a "
        "decision the contract must not have already made"
    )


def test_the_provider_scan_reads_a_module_that_names_one(tmp_path: Path) -> None:
    """The control for properties 3 and 5, in both shapes they read."""
    planted = tmp_path / "planted.py"
    planted.write_text(
        "from sentence_transformers import SentenceTransformer\nimport faiss\n", encoding="utf-8"
    )
    imported = {name.split(".")[0] for name in _imported_names(planted)}
    assert imported & PROVIDER_DISTRIBUTIONS == {"sentence_transformers", "faiss"}

    prose = "the embedding is produced by openai and stored in pgvector"
    named = {name for name in PROVIDER_DISTRIBUTIONS if re.search(rf"\b{name}\b", prose)}
    assert named == {"openai", "pgvector"}

    # And it distinguishes: the modules this build really does import are not
    # providers, or every rule above would be reporting the whole tree.
    ordinary = tmp_path / "ordinary.py"
    ordinary.write_text("import sqlalchemy\nfrom pydantic import BaseModel\n", encoding="utf-8")
    assert {n.split(".")[0] for n in _imported_names(ordinary)} & PROVIDER_DISTRIBUTIONS == set()
