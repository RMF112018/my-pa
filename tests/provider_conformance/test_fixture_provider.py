"""Conformance of the fixture provider to the read-only source port.

Two roots are used and they are used for different things. The committed tree
under `fixtures/mcv/root` is the stable corpus: shape, ordering, media types,
and bounded reads are asserted against it, and a guard at the top of this module
fails if that tree is not what these tests assume, so a fixture deleted by
accident cannot turn the rest of the file into a set of vacuous passes. Anything
that has to *change* an object -- a rewrite, a deletion -- happens in `tmp_path`,
because a test that mutated the committed corpus would leave the repository
dirty and the next test looking at a different tree.

No database, no marker, no network. This provider reads a directory.
"""

from __future__ import annotations

import hashlib
import os
import secrets
from pathlib import Path

import pytest

from my_pa.domain.common.identifiers import (
    IdKind,
    InvalidIdentifierError,
    make_identifier,
    parse_identifier,
    validate_identifier,
)
from my_pa.domain.source.provider import (
    ObjectKind,
    SourceObject,
    TraversalDeniedError,
    VersionChangedError,
)
from my_pa.infrastructure.providers.fixture import FixtureSourceProvider

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / "fixtures" / "mcv" / "root"

#: Every path in the committed corpus, relative to it. Stated here rather than
#: derived from the tree, so that a missing fixture is a failure instead of a
#: smaller expectation.
EXPECTED_TREE = frozenset(
    {
        "handbook.pdf",
        "nested",
        "nested/deeper",
        "nested/deeper/log.txt",
        "nested/meeting-notes.md",
        "notes.md",
        "opaque.bin",
        "readme.txt",
    }
)

#: The immediate children of the corpus root, in the order the provider
#: documents: ascending by the code points of the entry name.
EXPECTED_ROOT_ORDER = ("handbook.pdf", "nested", "notes.md", "opaque.bin", "readme.txt")


def provider(root: Path) -> FixtureSourceProvider:
    """A provider over `root` with a freshly issued source identity."""
    return FixtureSourceProvider(root, make_identifier(IdKind.SOURCE, secrets.token_hex(8)))


def by_name(objects: list[SourceObject], root: Path) -> dict[str, SourceObject]:
    """Index listed objects by file name, for tests that assert per-file facts.

    The provider discloses no name, by design. What it does promise is an order:
    ascending by entry name. Zipping the listing against the directory's names
    in that same order is how a test names a file the provider will not, and it
    fails loudly if the promised order is not kept.
    """
    listed = sorted(entry.name for entry in root.iterdir())
    assert len(listed) == len(objects)
    return dict(zip(listed, objects, strict=True))


@pytest.fixture
def corpus() -> FixtureSourceProvider:
    return provider(CORPUS)


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    """A writable copy-shaped root for tests that must change an object."""
    (tmp_path / "root").mkdir()
    return tmp_path / "root"


def test_the_committed_corpus_is_the_tree_these_tests_assume() -> None:
    # Guards every assertion below. A test that listed an empty directory and
    # found nothing wrong would pass while proving nothing.
    assert CORPUS.is_dir()
    found = {str(path.relative_to(CORPUS)) for path in CORPUS.rglob("*")}
    assert found == set(EXPECTED_TREE)
    assert (CORPUS / "handbook.pdf").read_bytes().startswith(b"%PDF-")
    with pytest.raises(UnicodeDecodeError):
        # The unsupported fixture is genuinely undecodable, so "never coerce"
        # is a claim with something behind it.
        (CORPUS / "opaque.bin").read_bytes().decode("utf-8")


def test_no_committed_fixture_is_a_symlink() -> None:
    """The corpus carries no symlink, escaping or otherwise.

    `fixtures/mcv/README.md` says the escape cases are built at test time. This
    is that sentence as a check, so a symlink cannot arrive here unremarked.
    """
    assert not [path for path in CORPUS.rglob("*") if path.is_symlink()]


def test_the_source_identity_is_the_configured_one() -> None:
    source_id = make_identifier(IdKind.SOURCE, secrets.token_hex(8))
    assert FixtureSourceProvider(CORPUS, source_id).source_id == source_id


def test_a_source_identity_of_the_wrong_kind_is_refused() -> None:
    with pytest.raises(InvalidIdentifierError):
        FixtureSourceProvider(CORPUS, make_identifier(IdKind.SOURCE_OBJECT, secrets.token_hex(8)))


def test_a_root_that_is_not_a_directory_is_a_configuration_error(sandbox: Path) -> None:
    for candidate in (sandbox / "absent", CORPUS / "notes.md"):
        with pytest.raises(ValueError, match="root"):
            provider(candidate)


def test_list_children_yields_immediate_children_in_the_documented_order(
    corpus: FixtureSourceProvider,
) -> None:
    listed = list(corpus.list_children())
    assert [entry.kind for entry in listed] == [
        ObjectKind.FILE,
        ObjectKind.CONTAINER,
        ObjectKind.FILE,
        ObjectKind.FILE,
        ObjectKind.FILE,
    ]
    assert [entry.size_bytes for entry in listed] == [
        (CORPUS / name).stat().st_size if (CORPUS / name).is_file() else None
        for name in EXPECTED_ROOT_ORDER
    ]


def test_list_children_never_recurses(corpus: FixtureSourceProvider) -> None:
    """A root listing must not contain anything from a subdirectory.

    Sizes are the check: `nested/deeper/log.txt` and `nested/meeting-notes.md`
    have sizes no root-level file shares, so a recursive implementation would
    show up as extra entries carrying those sizes.
    """
    listed = list(corpus.list_children())
    assert len(listed) == len(EXPECTED_ROOT_ORDER)
    buried = {
        (CORPUS / "nested" / "meeting-notes.md").stat().st_size,
        (CORPUS / "nested" / "deeper" / "log.txt").stat().st_size,
    }
    assert not buried & {entry.size_bytes for entry in listed if entry.size_bytes is not None}


def test_list_children_of_a_container_returns_that_container_s_children(
    corpus: FixtureSourceProvider,
) -> None:
    nested = next(entry for entry in corpus.list_children() if entry.kind is ObjectKind.CONTAINER)
    inner = list(corpus.list_children(nested.source_object_id))
    assert [entry.kind for entry in inner] == [ObjectKind.CONTAINER, ObjectKind.FILE]
    assert inner[1].media_type == "text/markdown"
    assert inner[1].size_bytes == (CORPUS / "nested" / "meeting-notes.md").stat().st_size
    deepest = list(corpus.list_children(inner[0].source_object_id))
    assert [entry.media_type for entry in deepest] == ["text/plain"]


def test_list_children_of_a_file_is_denied(corpus: FixtureSourceProvider) -> None:
    listed = by_name(list(corpus.list_children()), CORPUS)
    with pytest.raises(TraversalDeniedError):
        list(corpus.list_children(listed["notes.md"].source_object_id))


def test_list_children_denies_before_the_iterator_is_consumed(
    corpus: FixtureSourceProvider,
) -> None:
    """The denial arrives on the call, not on the first `next`.

    A generator would defer it, and a caller that never iterated would never
    learn it had been refused.
    """
    unknown = make_identifier(IdKind.SOURCE_OBJECT, secrets.token_hex(16))
    with pytest.raises(TraversalDeniedError):
        corpus.list_children(unknown)


def test_every_issued_identifier_is_a_well_formed_opaque_identifier(
    corpus: FixtureSourceProvider,
) -> None:
    for entry in corpus.list_children():
        assert validate_identifier(entry.source_object_id, IdKind.SOURCE_OBJECT)
        assert validate_identifier(entry.version_id, IdKind.VERSION)
        assert validate_identifier(entry.source_id, IdKind.SOURCE)


def _encodings_of(path: Path) -> set[str]:
    """Every plausible way a suffix could have been derived from a path.

    `INV-PKL-005` forbids an identifier that encodes a path, and
    `domain/common/identifiers.py` says in as many words that its shape check
    cannot detect one. This is the part that can: the literal spellings, and
    digests of them, which is what an implementation reaching for "stable ids
    without state" would use.
    """
    literals = {
        str(path),
        str(path).lower(),
        path.name,
        path.stem,
        path.suffix,
        str(path.relative_to(CORPUS)) if path.is_relative_to(CORPUS) else path.name,
    }
    encodings = set(literals)
    for literal in literals:
        raw = literal.encode("utf-8")
        encodings.add(hashlib.sha256(raw).hexdigest())
        encodings.add(hashlib.sha512(raw).hexdigest())
        encodings.add(hashlib.blake2b(raw).hexdigest())
        encodings.add(raw.hex())
    return encodings


def test_an_identifier_suffix_encodes_neither_a_path_nor_a_digest_of_one(
    corpus: FixtureSourceProvider,
) -> None:
    paths = sorted(CORPUS.iterdir())
    assert paths, "no path to check against"
    suffixes = [parse_identifier(entry.source_object_id)[1] for entry in corpus.list_children()]
    assert len(suffixes) == len(paths)
    for path in paths:
        encodings = _encodings_of(path)
        # The digests are longer than the suffix, so equality alone would miss a
        # truncated digest; a prefix test catches that too.
        assert not [s for s in suffixes if s in encodings]
        assert not [s for s in suffixes if any(e.startswith(s) for e in encodings)]
        assert not [s for s in suffixes if path.name.lower() in s.lower()]


def test_identifiers_are_stable_for_the_lifetime_of_one_provider(
    corpus: FixtureSourceProvider,
) -> None:
    first = [entry.source_object_id for entry in corpus.list_children()]
    second = [entry.source_object_id for entry in corpus.list_children()]
    assert first == second
    assert corpus.metadata(first[0]).source_object_id == first[0]


def test_identifiers_do_not_survive_a_second_provider_over_the_same_root() -> None:
    """The lifetime the module docstring claims, asserted rather than assumed.

    This is not a desirable property; it is an honest one. Identifiers are
    per-instance, nothing persists them, and a test that pretended otherwise
    would be the place a caller learned to rely on what is not true.
    """
    first = [entry.source_object_id for entry in provider(CORPUS).list_children()]
    other = provider(CORPUS)
    assert not set(first) & {entry.source_object_id for entry in other.list_children()}
    with pytest.raises(TraversalDeniedError):
        other.metadata(first[0])


def test_versions_are_stable_while_the_object_is_not_touched(
    corpus: FixtureSourceProvider,
) -> None:
    listed = by_name(list(corpus.list_children()), CORPUS)
    notes = listed["notes.md"]
    assert corpus.metadata(notes.source_object_id).version_id == notes.version_id
    assert corpus.fetch(notes.source_object_id, max_bytes=4096).version_id == notes.version_id


@pytest.mark.parametrize(
    ("name", "media_type"),
    [
        ("readme.txt", "text/plain"),
        ("notes.md", "text/markdown"),
        ("handbook.pdf", "application/pdf"),
        ("opaque.bin", None),
    ],
)
def test_media_type_is_reported_for_each_kind_of_fixture(
    corpus: FixtureSourceProvider, name: str, media_type: str | None
) -> None:
    listed = by_name(list(corpus.list_children()), CORPUS)
    assert listed[name].media_type == media_type
    assert corpus.metadata(listed[name].source_object_id).media_type == media_type


def test_a_container_reports_no_size_and_no_media_type(corpus: FixtureSourceProvider) -> None:
    nested = next(entry for entry in corpus.list_children() if entry.kind is ObjectKind.CONTAINER)
    assert nested.size_bytes is None
    assert nested.media_type is None


def test_a_pdf_is_reported_as_a_pdf_and_returned_unextracted(
    corpus: FixtureSourceProvider,
) -> None:
    """`P00-OD-003` is open, so this provider carries the type and no more.

    Extraction is a later work package. What must not happen here is a PDF
    reported as text, or reported as nothing.
    """
    handbook = by_name(list(corpus.list_children()), CORPUS)["handbook.pdf"]
    content = corpus.fetch(handbook.source_object_id, max_bytes=4096)
    assert content.media_type == "application/pdf"
    assert content.content == (CORPUS / "handbook.pdf").read_bytes()


def test_an_unsupported_type_is_neither_skipped_nor_coerced(
    corpus: FixtureSourceProvider,
) -> None:
    opaque = by_name(list(corpus.list_children()), CORPUS)["opaque.bin"]
    assert opaque.media_type is None
    assert opaque.size_bytes == (CORPUS / "opaque.bin").stat().st_size
    content = corpus.fetch(opaque.source_object_id, max_bytes=4096)
    assert content.media_type is None
    assert content.content == (CORPUS / "opaque.bin").read_bytes()
    assert not content.is_truncated


def test_fetch_returns_the_whole_object_when_the_ceiling_allows(
    corpus: FixtureSourceProvider,
) -> None:
    readme = by_name(list(corpus.list_children()), CORPUS)["readme.txt"]
    assert readme.size_bytes is not None
    content = corpus.fetch(readme.source_object_id, max_bytes=readme.size_bytes)
    assert content.content == (CORPUS / "readme.txt").read_bytes()
    assert not content.is_truncated
    assert content.source_object_id == readme.source_object_id


def test_max_bytes_is_a_hard_ceiling_and_truncation_is_reported(
    corpus: FixtureSourceProvider,
) -> None:
    readme = by_name(list(corpus.list_children()), CORPUS)["readme.txt"]
    assert readme.size_bytes is not None and readme.size_bytes > 64
    content = corpus.fetch(readme.source_object_id, max_bytes=64)
    assert len(content.content) == 64
    assert content.content == (CORPUS / "readme.txt").read_bytes()[:64]
    assert content.is_truncated


def test_a_ceiling_of_zero_reads_nothing_and_says_so(corpus: FixtureSourceProvider) -> None:
    readme = by_name(list(corpus.list_children()), CORPUS)["readme.txt"]
    content = corpus.fetch(readme.source_object_id, max_bytes=0)
    assert content.content == b""
    assert content.is_truncated


def test_an_empty_object_is_not_reported_as_truncated(sandbox: Path) -> None:
    (sandbox / "empty.txt").write_bytes(b"")
    source = provider(sandbox)
    empty = next(iter(source.list_children()))
    assert not source.fetch(empty.source_object_id, max_bytes=16).is_truncated


def test_a_negative_ceiling_is_a_caller_error(corpus: FixtureSourceProvider) -> None:
    readme = by_name(list(corpus.list_children()), CORPUS)["readme.txt"]
    with pytest.raises(ValueError, match="max_bytes"):
        corpus.fetch(readme.source_object_id, max_bytes=-1)


def test_fetch_of_a_container_is_denied(corpus: FixtureSourceProvider) -> None:
    nested = next(entry for entry in corpus.list_children() if entry.kind is ObjectKind.CONTAINER)
    with pytest.raises(TraversalDeniedError):
        corpus.fetch(nested.source_object_id, max_bytes=16)


def test_a_malformed_identifier_is_a_client_error_not_a_denial(
    corpus: FixtureSourceProvider,
) -> None:
    # Shape is wrong whatever exists, so saying so discloses nothing.
    for bad in ("", "obj", "obj_", "obj_../etc", "ver_" + secrets.token_hex(16), "not an id"):
        with pytest.raises(InvalidIdentifierError):
            corpus.metadata(bad)


def _rewrite(path: Path, content: bytes) -> None:
    """Rewrite `path` and force its timestamps forward.

    Filesystem timestamp granularity varies, and a rewrite inside the same tick
    would make the assertion that follows depend on how fast the test ran. The
    explicit `utime` removes the timing from the test; the honest limitation it
    papers over is stated in `_fingerprint`.
    """
    path.write_bytes(content)
    status = path.stat()
    os.utime(path, ns=(status.st_atime_ns, status.st_mtime_ns + 2_000_000_000))


def test_a_changed_object_is_a_conflict_and_not_stale_bytes(sandbox: Path) -> None:
    target = sandbox / "report.txt"
    target.write_bytes(b"first observation")
    source = provider(sandbox)
    observed = next(iter(source.list_children()))

    _rewrite(target, b"second observation, a different length entirely")
    with pytest.raises(VersionChangedError):
        source.fetch(observed.source_object_id, max_bytes=4096)

    # And the conflict persists until the caller re-observes, rather than the
    # provider quietly adopting the new version on the next attempt.
    with pytest.raises(VersionChangedError):
        source.fetch(observed.source_object_id, max_bytes=4096)

    refreshed = source.metadata(observed.source_object_id)
    assert refreshed.version_id != observed.version_id
    content = source.fetch(observed.source_object_id, max_bytes=4096)
    assert content.version_id == refreshed.version_id
    assert content.content == b"second observation, a different length entirely"


def test_a_rewrite_of_identical_length_still_changes_the_version(sandbox: Path) -> None:
    """Size alone would not notice this one."""
    target = sandbox / "report.txt"
    target.write_bytes(b"aaaaaaaaaaaaaaaa")
    source = provider(sandbox)
    observed = next(iter(source.list_children()))

    _rewrite(target, b"bbbbbbbbbbbbbbbb")
    assert target.stat().st_size == 16
    with pytest.raises(VersionChangedError):
        source.fetch(observed.source_object_id, max_bytes=4096)
    assert source.metadata(observed.source_object_id).version_id != observed.version_id


def test_a_replacement_by_rename_changes_the_version(sandbox: Path) -> None:
    """The atomic-swap case: same name, same bytes even, different inode."""
    target = sandbox / "report.txt"
    target.write_bytes(b"identical bytes")
    source = provider(sandbox)
    observed = next(iter(source.list_children()))

    replacement = sandbox / ".staged"
    replacement.write_bytes(b"identical bytes")
    os.utime(replacement, ns=(target.stat().st_atime_ns, target.stat().st_mtime_ns))
    replacement.replace(target)

    with pytest.raises(VersionChangedError):
        source.fetch(observed.source_object_id, max_bytes=4096)


def test_a_deleted_object_is_denied(sandbox: Path) -> None:
    (sandbox / "transient.txt").write_bytes(b"here for now")
    source = provider(sandbox)
    observed = next(iter(source.list_children()))
    (sandbox / "transient.txt").unlink()

    with pytest.raises(TraversalDeniedError):
        source.metadata(observed.source_object_id)
    with pytest.raises(TraversalDeniedError):
        source.fetch(observed.source_object_id, max_bytes=16)


def template(exception: BaseException, object_id: str) -> str:
    """The denial message with the only part that may legitimately vary removed."""
    return str(exception).replace(object_id, "<object>")


def test_absent_and_unknown_are_denied_in_exactly_the_same_words(sandbox: Path) -> None:
    """`docs/specs` section 10: denial must not distinguish, so a caller cannot probe.

    Three outcomes that a caller might hope to tell apart -- an object that was
    deleted, an identifier that was never issued, and an object that is not a
    file -- have to produce the same sentence. The escape cases are held to the
    same sentence in `tests/security/test_containment_denial.py`.
    """
    (sandbox / "transient.txt").write_bytes(b"here for now")
    (sandbox / "folder").mkdir()
    source = provider(sandbox)
    listed = list(source.list_children())
    deleted, folder = listed[1], listed[0]
    (sandbox / "transient.txt").unlink()
    unknown = make_identifier(IdKind.SOURCE_OBJECT, secrets.token_hex(16))

    messages = set()
    for object_id, call in (
        (deleted.source_object_id, source.metadata),
        (unknown, source.metadata),
        (folder.source_object_id, lambda oid: source.fetch(oid, max_bytes=8)),
        (deleted.source_object_id, lambda oid: source.fetch(oid, max_bytes=8)),
    ):
        with pytest.raises(TraversalDeniedError) as raised:
            call(object_id)
        messages.add(template(raised.value, object_id))
    assert len(messages) == 1


def test_no_denial_carries_a_path_a_root_or_a_chained_operating_system_error(
    sandbox: Path,
) -> None:
    """A message, or a `__cause__`, that named the file would undo the denial.

    `OSError` is the specific hazard: it carries `filename`, so chaining one
    would put the path into every traceback that renders the exception.
    """
    (sandbox / "transient.txt").write_bytes(b"here for now")
    source = provider(sandbox)
    observed = next(iter(source.list_children()))
    (sandbox / "transient.txt").unlink()

    with pytest.raises(TraversalDeniedError) as raised:
        source.metadata(observed.source_object_id)

    rendered = f"{raised.value!r} {raised.value.args}"
    for fragment in (str(sandbox), str(sandbox.resolve()), "transient", str(ROOT), os.sep):
        assert fragment not in rendered
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None
