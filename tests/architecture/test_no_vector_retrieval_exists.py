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
2. **No revision installs a vector extension, an ANN index, or a vector
   operator.** Every revision file's SQL strings, plus the extension list the
   foundation revision declares.
3. **No module imports an embedding or model provider.** Every `import` in
   `src/` and `apps/`, read as a syntax tree, matched against a closed list of
   distributions — and against the declared dependencies, so a provider that
   arrived as a dependency without an import yet still reddens.
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


def _modules() -> tuple[Path, ...]:
    return tuple(sorted(PACKAGE.rglob("*.py"))) + tuple(sorted(APPS.rglob("*.py")))


def _revision_files() -> tuple[Path, ...]:
    return tuple(sorted(REVISIONS.glob("*.py")))


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
    assert len(PROVIDER_DISTRIBUTIONS) == 23
    assert len(SQL_FRAGMENTS) == 14
    assert len(INSTALLED_EXTENSIONS) == 2
    assert len(PROVIDER_NEUTRAL_LAYERS) == 3


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


def test_no_provider_is_a_declared_dependency() -> None:
    """Property 3's other half: a provider can arrive before anything imports it."""
    declared = PYPROJECT.read_text(encoding="utf-8")
    start = declared.index("\ndependencies = [")
    # Terminated on a line that is exactly `]`, not on the first `]`: an extra
    # such as `psycopg[binary]` carries one inside a requirement string, and
    # stopping there read two of the eight declarations and called it the block.
    end = declared.index("\n]", start)
    block = declared[start : end + 2]
    assert "SQLAlchemy" in block and "mcp" in block, "the dependency block was not located"
    offending = sorted(
        name
        for name in PROVIDER_DISTRIBUTIONS
        if re.search(rf'"{re.escape(name)}[><=\[",]', block, re.IGNORECASE)
    )
    assert offending == [], (
        f"{offending} are declared runtime dependencies. A provider in the "
        "dependency list is vector infrastructure one import away"
    )


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
