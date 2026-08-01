"""Root containment for the fixture source provider, proved non-vacuously.

A containment test that passes because nothing in the fixture actually escapes
is worse than no test at all: it reports a guarantee nobody checked. So every
case here is built in `tmp_path` at test time and then *verified to be a real
escape before it is denied* -- the candidate is read with a plain `open` and has
to return the marker that lives outside the root. If the escape stops working,
`test_every_escape_case_really_escapes` fails, rather than the denial tests
quietly passing on inert fixtures.

The escapes are built rather than committed. A symlink pointing out of the
repository is a hazard to carry in a checkout, and not every checkout, archive,
or export preserves one; a case that silently arrived as a plain file would be a
denial test with nothing to deny.

Two controls sit alongside the denials, because "deny everything" would satisfy
every assertion in a file that only tested denial: a contained path must
resolve, and a symlink that stays inside the root must be followed and read.

No database, no marker, no network.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Callable
from pathlib import Path

import pytest

from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.source.provider import ObjectKind, TraversalDeniedError
from my_pa.infrastructure.providers.fixture import FixtureSourceProvider, resolve_within

#: What lives outside the root. Any appearance of this in a result or a message
#: is a containment failure.
MARKER = b"OUTSIDE-THE-ROOT: the provider must never return these bytes"

#: The five escapes this work package is required to deny, plus a chained
#: symlink, which is the same class of defect one indirection further out.
EXPECTED_CASES = frozenset(
    {
        "parent_traversal",
        "absolute_path",
        "symlink_to_relative_target",
        "symlink_to_absolute_target",
        "directory_symlink",
        "symlink_chain",
    }
)


def anonymous() -> str:
    """An object identifier for a path no identifier was ever issued for."""
    return make_identifier(IdKind.SOURCE_OBJECT, secrets.token_hex(16))


def provider(root: Path) -> FixtureSourceProvider:
    return FixtureSourceProvider(root, make_identifier(IdKind.SOURCE, secrets.token_hex(8)))


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """A configured root with a sibling directory holding the marker."""
    (tmp_path / "root").mkdir()
    (tmp_path / "outside").mkdir()
    (tmp_path / "outside" / "secret.txt").write_bytes(MARKER)
    (tmp_path / "root" / "contained.txt").write_bytes(b"inside the root, and allowed")
    return tmp_path / "root"


def escape_cases(root: Path) -> dict[str, Path]:
    """Build every escape and return the candidate path each one produces.

    Each candidate is a path a caller might hand in or an identifier might
    still point at. All of them reach the same file outside the root, which is
    what makes the single guard below sufficient for all of them.
    """
    outside = root.parent / "outside"

    (root / "link-relative.txt").symlink_to(Path("..") / "outside" / "secret.txt")
    (root / "link-absolute.txt").symlink_to(outside / "secret.txt")
    (root / "link-dir").symlink_to(outside, target_is_directory=True)
    (root / "link-chain.txt").symlink_to(Path("link-relative.txt"))

    return {
        "parent_traversal": root / ".." / "outside" / "secret.txt",
        "absolute_path": outside / "secret.txt",
        "symlink_to_relative_target": root / "link-relative.txt",
        "symlink_to_absolute_target": root / "link-absolute.txt",
        "directory_symlink": root / "link-dir" / "secret.txt",
        "symlink_chain": root / "link-chain.txt",
    }


def test_the_escape_cases_are_all_present(root: Path) -> None:
    """The guard that keeps a deleted case from silently shrinking the suite.

    Parametrising over a dict that lost an entry would report fewer passing
    tests, not a failure, and nobody counts passing tests.
    """
    assert set(escape_cases(root)) == set(EXPECTED_CASES)


@pytest.mark.parametrize("case", sorted(EXPECTED_CASES))
def test_every_escape_case_really_escapes(root: Path, case: str) -> None:
    """Non-vacuity, case by case, before anything is asserted about denial.

    Three things have to hold for the corresponding denial test to mean
    anything: the candidate resolves outside the root, the file it reaches
    exists, and an implementation without a containment check would return the
    marker. The last is not argued, it is performed.
    """
    candidate = escape_cases(root)[case]
    resolved = candidate.resolve()
    assert not resolved.is_relative_to(root.resolve()), "case does not leave the root"
    assert resolved.is_file(), "case reaches nothing, so denying it proves nothing"
    assert candidate.read_bytes() == MARKER, "the escape is inert; the denial would be vacuous"


@pytest.mark.parametrize("case", sorted(EXPECTED_CASES))
def test_every_escape_case_is_denied(root: Path, case: str) -> None:
    candidate = escape_cases(root)[case]
    object_id = anonymous()
    with pytest.raises(TraversalDeniedError) as raised:
        resolve_within(root.resolve(), candidate, object_id)
    assert str(raised.value) == f"{object_id} cannot be served from the configured source"


def test_a_contained_path_resolves(root: Path) -> None:
    """The control. A check that denied everything would pass every test above."""
    resolved = root.resolve()
    assert resolve_within(resolved, root / "contained.txt", anonymous()) == (
        resolved / "contained.txt"
    )
    assert resolve_within(resolved, resolved, anonymous()) == resolved
    assert resolve_within(resolved, root / "." / "contained.txt", anonymous()) == (
        resolved / "contained.txt"
    )


def test_a_symlink_that_stays_inside_the_root_is_followed(root: Path) -> None:
    """The second control: containment is about where a link lands, not that it is one.

    A provider that refused every symlink would also deny every escape, and the
    denial tests could not tell the difference.
    """
    (root / "alias.txt").symlink_to(Path("contained.txt"))
    resolved = root.resolve()
    assert resolve_within(resolved, root / "alias.txt", anonymous()) == resolved / "contained.txt"

    source = provider(root)
    listed = list(source.list_children())
    assert len(listed) == 2
    # Two names, one object: identity here is the resolved object, so the alias
    # and its target carry the same identifier rather than two for one file.
    assert listed[0] == listed[1]
    content = source.fetch(listed[0].source_object_id, max_bytes=64)
    assert content.content == b"inside the root, and allowed"


def test_a_sibling_directory_sharing_the_root_s_name_is_outside(tmp_path: Path) -> None:
    """`/x/rootlike` is not inside `/x/root`, which a string prefix test would allow."""
    (tmp_path / "root").mkdir()
    (tmp_path / "rootlike").mkdir()
    (tmp_path / "rootlike" / "secret.txt").write_bytes(MARKER)
    with pytest.raises(TraversalDeniedError):
        resolve_within(tmp_path / "root", tmp_path / "rootlike" / "secret.txt", anonymous())


def test_an_escaping_symlink_is_never_listed(root: Path) -> None:
    """A listing omits what it cannot prove contained, and says nothing about why."""
    escape_cases(root)
    source = provider(root)
    listed = list(source.list_children())

    assert len(listed) == 1, "an escaping entry reached the listing"
    assert listed[0].size_bytes == len(b"inside the root, and allowed")
    for entry in listed:
        assert MARKER not in source.fetch(entry.source_object_id, max_bytes=4096).content


def test_a_file_swapped_for_an_escaping_symlink_after_issue_is_denied(root: Path) -> None:
    """The case the port's docstring names: the swap lands between issue and open.

    Containment was true when the identifier was minted. It is re-proved on
    every call, so the identifier is worth nothing once the path underneath it
    points somewhere else.
    """
    target = root / "contained.txt"
    source = provider(root)
    observed = next(entry for entry in source.list_children() if entry.kind is ObjectKind.FILE)
    assert source.fetch(observed.source_object_id, max_bytes=64).content != MARKER

    target.unlink()
    target.symlink_to(root.parent / "outside" / "secret.txt")
    assert target.read_bytes() == MARKER, "the swap did not take; the test would be vacuous"

    with pytest.raises(TraversalDeniedError):
        source.metadata(observed.source_object_id)
    with pytest.raises(TraversalDeniedError) as raised:
        source.fetch(observed.source_object_id, max_bytes=4096)
    assert str(raised.value) == (
        f"{observed.source_object_id} cannot be served from the configured source"
    )


def test_a_container_swapped_for_an_escaping_directory_symlink_is_denied(root: Path) -> None:
    """The swap that an `O_NOFOLLOW` open alone does not catch.

    The escaping symlink is an *intermediate* directory, and the file at the end
    of the path is a real regular file with the name the identifier was minted
    for. `O_NOFOLLOW` inspects the last component only, so the open succeeds:
    nothing but re-resolving the whole path before the open refuses this. That
    is why the outside directory is given a same-named decoy -- without it, the
    open would fail with "no such file" and the test would pass on an
    implementation that had stopped revalidating containment entirely.
    """
    decoy = root.parent / "outside" / "nested"
    decoy.mkdir()
    (decoy / "note.txt").write_bytes(MARKER)

    nested = root / "nested"
    nested.mkdir()
    (nested / "note.txt").write_bytes(b"inside the root, in a subdirectory")
    source = provider(root)
    container = next(
        entry for entry in source.list_children() if entry.kind is ObjectKind.CONTAINER
    )
    child = next(iter(source.list_children(container.source_object_id)))
    assert source.fetch(child.source_object_id, max_bytes=4096).content != MARKER

    (nested / "note.txt").unlink()
    nested.rmdir()
    nested.symlink_to(decoy, target_is_directory=True)
    assert (nested / "note.txt").read_bytes() == MARKER, "the swap did not take"
    assert not (root / "nested" / "note.txt").is_symlink(), (
        "the decoy must be a real file, or O_NOFOLLOW would refuse the open "
        "and this test would pass without any containment check at all"
    )

    with pytest.raises(TraversalDeniedError):
        source.list_children(container.source_object_id)
    with pytest.raises(TraversalDeniedError):
        source.metadata(container.source_object_id)
    with pytest.raises(TraversalDeniedError):
        source.metadata(child.source_object_id)
    # The child identifier was minted under the old directory; the path it holds
    # now resolves through the replaced parent and out of the root.
    with pytest.raises(TraversalDeniedError):
        source.fetch(child.source_object_id, max_bytes=4096)


def test_a_denial_never_names_the_path_the_marker_or_the_root(root: Path) -> None:
    """Section 10: an error may not disclose a location, and must not leak by chaining.

    Every denial this suite can produce is rendered with its arguments and its
    exception chain, and checked against the root, the outside directory, the
    marker, and the path separator itself.
    """
    cases = escape_cases(root)
    source = provider(root)
    observed = next(iter(source.list_children()))
    (root / "contained.txt").unlink()
    (root / "contained.txt").symlink_to(root.parent / "outside" / "secret.txt")

    failures: list[tuple[str, BaseException]] = []
    calls: list[tuple[str, Callable[[str], object]]] = [
        ("metadata", source.metadata),
        ("fetch", lambda oid: source.fetch(oid, max_bytes=4096)),
        ("list_children", source.list_children),
    ]
    for name, call in calls:
        with pytest.raises(TraversalDeniedError) as raised:
            call(observed.source_object_id)
        failures.append((name, raised.value))
    for case in sorted(EXPECTED_CASES):
        with pytest.raises(TraversalDeniedError) as raised:
            resolve_within(root.resolve(), cases[case], anonymous())
        failures.append((case, raised.value))

    assert len(failures) == 3 + len(EXPECTED_CASES)
    for name, failure in failures:
        rendered = f"{failure!r} {failure.args} {failure.__cause__} {failure.__context__}"
        for fragment in (
            str(root),
            str(root.resolve()),
            str(root.parent / "outside"),
            "secret",
            "contained",
            MARKER.decode(),
            os.sep,
        ):
            assert fragment not in rendered, f"{name} disclosed {fragment!r}"
        assert failure.__cause__ is None
        assert failure.__context__ is None


def test_the_denials_are_indistinguishable_from_one_another(root: Path) -> None:
    """An escape, an absence, and an identifier that was never issued read alike.

    If they did not, the difference would be a probe: a caller could learn that
    something exists outside the root by the shape of the refusal it got.
    """
    source = provider(root)
    observed = next(iter(source.list_children()))
    messages = set()

    def record(object_id: str) -> None:
        with pytest.raises(TraversalDeniedError) as raised:
            source.metadata(object_id)
        messages.add(str(raised.value).replace(object_id, "<object>"))

    # In this order, because the same object has to be absent before it can be
    # replaced by something that escapes.
    (root / "contained.txt").unlink()
    record(observed.source_object_id)
    (root / "contained.txt").symlink_to(root.parent / "outside" / "secret.txt")
    assert (root / "contained.txt").read_bytes() == MARKER
    record(observed.source_object_id)
    record(anonymous())

    assert len(messages) == 1
