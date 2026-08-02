"""How the fixture provider classifies a failed open: shortage or refusal.

`docs/plans/mcv-completion-plan.md` section 10 carried this into WP-3. WP-2
established the principle on one errno -- a read timeout is `unavailable`, not
`denied` -- and left `EMFILE`, `ENFILE`, `ENOMEM`, `EIO`, and `ESTALE` in the
blanket handler, where each became a non-retryable refusal. `INV-PKL-007`
forbids converting unavailable evidence into something else, and section 10 puts
`denied` and `unavailable` in different rows with opposite retry guidance, so
the conversion told a caller to stop retrying something that was only slow, or
only out of descriptors.

Two claims are made here and they pull in opposite directions, which is why they
are in one file. The first is that the retryable class is real: descriptor
exhaustion, produced for real by clamping `RLIMIT_NOFILE` rather than simulated,
is not reported as a denial. The second is that widening it opened no existence
oracle -- every denial still reads identically whatever produced it, every
unavailability reads identically too, and an errno nobody enumerated is a
denial. A fix for the first that broke the second would be a worse defect than
the one it fixed.

The errno lists are restated here rather than imported from the module. A test
that imports the set it is checking proves only that a loop ran;
`test_the_unavailable_class_is_exactly_this_set` pins the two against each other
so that widening the class has to be written twice, deliberately.

No database, no marker, no network. This provider reads a directory.
"""

from __future__ import annotations

import errno
import os
import resource
import secrets
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.source.provider import (
    ProviderError,
    SourceObject,
    TraversalDeniedError,
    VersionChangedError,
)
from my_pa.infrastructure.providers import fixture as fixture_module
from my_pa.infrastructure.providers.fixture import FixtureSourceProvider

#: Restated, not imported. Each is a resource shortage or a transient I/O
#: condition: the same call can succeed a moment later, which is what
#: `unavailable`'s conditional retry guidance means. `EBADF` is one of them
#: because `open` takes no descriptor and this platform reports descriptor
#: exhaustion with it; the module constant carries the measurement.
UNAVAILABLE_ERRNO_NAMES = frozenset(
    {"EBADF", "EMFILE", "ENFILE", "ENOMEM", "EIO", "ESTALE", "ETIMEDOUT"}
)

#: What `open` may report when the process is at its descriptor limit. POSIX
#: says `EMFILE`; Darwin was measured saying `EBADF`. Pinned so that a third
#: answer on some later platform fails loudly here rather than quietly turning
#: the exhaustion tests into a denial nobody noticed.
EXHAUSTION_ERRNOS = frozenset({errno.EMFILE, errno.EBADF})

#: Containment, absence, and "not a thing this source has". Retrying any of
#: these without a change of authority or of the filesystem is a loop.
DENIED_ERRNO_NAMES = frozenset(
    {"ENOENT", "ENOTDIR", "EACCES", "EPERM", "ELOOP", "ENAMETOOLONG", "EISDIR", "ENXIO"}
)

#: An errno in neither list. `EXDEV` is a real errno that cannot arise from an
#: `O_RDONLY` open, and 4095 is not an errno at all: both must be denials,
#: because the classification is an allowlist and its failure direction is to
#: refuse rather than to invite an unbounded retry.
UNCLASSIFIED_ERRNOS = (errno.EXDEV, 4095)

#: Low enough that the process is already past it, so exhaustion is immediate
#: rather than a loop that has to consume thousands of descriptors.
DESCRIPTOR_CLAMP = 64

#: Bounds the exhaustion loop. Reaching it means the clamp did not take, which
#: `test_clamping_the_descriptor_limit_really_exhausts_descriptors` reports as a
#: failure rather than letting the classification test pass on an unexhausted
#: process.
MAX_DESCRIPTORS_HELD = 512


def provider(root: Path) -> FixtureSourceProvider:
    return FixtureSourceProvider(root, make_identifier(IdKind.SOURCE, secrets.token_hex(8)))


@pytest.fixture
def sandbox(tmp_path: Path) -> Path:
    (tmp_path / "root").mkdir()
    return tmp_path / "root"


@pytest.fixture
def observed(sandbox: Path) -> tuple[FixtureSourceProvider, SourceObject]:
    """A provider over one real file, already observed so `fetch` reaches its open.

    Observation matters to the argument and not only to the mechanics: `fetch`
    proves containment, issuance, and a prior observation before it opens
    anything, so nothing below is reachable by a caller that has not already
    been told the object exists. That is the first of the three reasons the
    retryable class is not an existence oracle.
    """
    (sandbox / "note.txt").write_bytes(b"present, and readable when the machine allows it")
    source = provider(sandbox)
    return source, next(iter(source.list_children()))


def template(exception: BaseException, object_id: str) -> str:
    """The message with the only part that may legitimately vary removed."""
    return str(exception).replace(object_id, "<object>")


def failing_open(number: int, path: Path) -> Callable[..., int]:
    """An `os.open` that fails with `number`, carrying a path the way a real one does.

    The third argument is what makes this worth constructing: a real `OSError`
    from `open` sets `filename`, and `OSError.__str__` renders it. An
    implementation that let the original into `__context__` would put the path
    into every traceback, which is what the disclosure assertions below check.
    """

    def opener(*arguments: object, **keywords: object) -> int:
        raise OSError(number, "the operating system said something specific", str(path))

    return opener


def capture(call: Callable[[], object]) -> Exception | None:
    """Run `call` and return what it raised.

    Used where the assertion must happen *after* some resource has been
    restored: `pytest.raises` would report inside the region, and reporting a
    failure needs the very descriptors the region has taken away.
    """
    try:
        call()
    except Exception as error:
        return error
    return None


def probe_errno() -> int | None:
    """Open one descriptor and report the errno, or `None` if it succeeded."""
    try:
        descriptor = os.open(os.devnull, os.O_RDONLY)
    except OSError as error:
        return error.errno
    os.close(descriptor)
    return None


@contextmanager
def descriptors_exhausted() -> Iterator[None]:
    """Clamp `RLIMIT_NOFILE` and consume what is left, restoring both afterwards.

    The restoration is in a `finally` because the alternative is a test session
    that cannot open a file again: every later test, and pytest's own failure
    reporting, would fail for a reason having nothing to do with what broke. The
    descriptors are closed before the limit is restored, in that order, so a
    failure between the two still leaves the process able to open something.
    """
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    held: list[int] = []
    try:
        resource.setrlimit(resource.RLIMIT_NOFILE, (DESCRIPTOR_CLAMP, hard))
        while len(held) < MAX_DESCRIPTORS_HELD:
            try:
                held.append(os.open(os.devnull, os.O_RDONLY))
            except OSError as error:
                if error.errno not in EXHAUSTION_ERRNOS:
                    raise
                break
        yield
    finally:
        for descriptor in held:
            os.close(descriptor)
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))


def test_the_unavailable_class_is_exactly_this_set() -> None:
    """Pin the module's allowlist against the one restated here.

    Planted cases alone cannot pin a set: a list that happened to contain the
    six names below would satisfy every parametrised test in this file while
    also containing anything else somebody added. Comparing the sets means a
    widening has to be written in two places, which is what makes it a decision
    rather than a drift.
    """
    named = {errno.errorcode[number] for number in fixture_module._UNAVAILABLE_ERRNOS}
    assert named == set(UNAVAILABLE_ERRNO_NAMES)
    assert not UNAVAILABLE_ERRNO_NAMES & DENIED_ERRNO_NAMES


@pytest.mark.parametrize("name", sorted(UNAVAILABLE_ERRNO_NAMES))
def test_a_shortage_is_reported_as_unavailable_and_not_as_a_denial(
    observed: tuple[FixtureSourceProvider, SourceObject],
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    sandbox: Path,
) -> None:
    source, entry = observed
    monkeypatch.setattr(os, "open", failing_open(getattr(errno, name), sandbox / "note.txt"))

    with pytest.raises(ProviderError) as raised:
        source.fetch(entry.source_object_id, max_bytes=64)

    # The type is the channel a caller classifies on, so it is what is asserted.
    assert not isinstance(raised.value, TraversalDeniedError)
    assert not isinstance(raised.value, VersionChangedError)


@pytest.mark.parametrize("name", sorted(DENIED_ERRNO_NAMES))
def test_a_refusal_is_still_a_denial(
    observed: tuple[FixtureSourceProvider, SourceObject],
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    sandbox: Path,
) -> None:
    """The paired negative. Classifying everything as unavailable would pass the
    test above and would tell a caller to retry a containment refusal forever.
    """
    source, entry = observed
    monkeypatch.setattr(os, "open", failing_open(getattr(errno, name), sandbox / "note.txt"))

    with pytest.raises(TraversalDeniedError):
        source.fetch(entry.source_object_id, max_bytes=64)


@pytest.mark.parametrize("number", UNCLASSIFIED_ERRNOS)
def test_an_errno_nobody_enumerated_is_denied(
    observed: tuple[FixtureSourceProvider, SourceObject],
    monkeypatch: pytest.MonkeyPatch,
    number: int,
    sandbox: Path,
) -> None:
    """Fail closed, which is the property that keeps the allowlist an allowlist."""
    source, entry = observed
    monkeypatch.setattr(os, "open", failing_open(number, sandbox / "note.txt"))

    with pytest.raises(TraversalDeniedError):
        source.fetch(entry.source_object_id, max_bytes=64)


def test_an_operating_system_error_with_no_errno_is_denied(
    observed: tuple[FixtureSourceProvider, SourceObject], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`OSError()` carries `errno is None`, and `None` is in no allowlist."""
    source, entry = observed

    def opener(*arguments: object, **keywords: object) -> int:
        raise OSError

    monkeypatch.setattr(os, "open", opener)
    with pytest.raises(TraversalDeniedError):
        source.fetch(entry.source_object_id, max_bytes=64)


def test_a_timeout_is_unavailable_whatever_errno_its_platform_uses(
    observed: tuple[FixtureSourceProvider, SourceObject], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ETIMEDOUT` is 60 on Darwin and 110 on Linux; `TimeoutError` is neither.

    The classification checks the type as well as the number, so a deadline is
    unavailable on both platforms and on one raised with no errno at all. Without
    the type check this file would pass on the machine it was written on.
    """
    source, entry = observed

    def opener(*arguments: object, **keywords: object) -> int:
        raise TimeoutError

    monkeypatch.setattr(os, "open", opener)
    with pytest.raises(ProviderError) as raised:
        source.fetch(entry.source_object_id, max_bytes=64)
    assert not isinstance(raised.value, TraversalDeniedError)
    assert fixture_module._is_unavailable(TimeoutError()) is True


def test_every_unavailability_reads_the_same_and_every_denial_reads_the_same(
    observed: tuple[FixtureSourceProvider, SourceObject],
    monkeypatch: pytest.MonkeyPatch,
    sandbox: Path,
) -> None:
    """The second reason the widening is not an oracle: one sentence per class.

    A caller that could tell `EIO` -- which is reached only after the kernel has
    looked at the object -- from `EMFILE` -- which is not -- would have learned
    something about the object from an error. Both classes collapse to one
    sentence each, so the message says no more than the type does.
    """
    source, entry = observed
    unavailable, denied = set(), set()
    for name in sorted(UNAVAILABLE_ERRNO_NAMES):
        monkeypatch.setattr(os, "open", failing_open(getattr(errno, name), sandbox / "note.txt"))
        with pytest.raises(ProviderError) as raised:
            source.fetch(entry.source_object_id, max_bytes=64)
        unavailable.add(template(raised.value, entry.source_object_id))
    for name in sorted(DENIED_ERRNO_NAMES):
        monkeypatch.setattr(os, "open", failing_open(getattr(errno, name), sandbox / "note.txt"))
        with pytest.raises(TraversalDeniedError) as raised:
            source.fetch(entry.source_object_id, max_bytes=64)
        denied.add(template(raised.value, entry.source_object_id))

    assert len(unavailable) == 1
    assert len(denied) == 1
    assert unavailable != denied


def test_a_refused_open_reads_exactly_like_a_genuinely_absent_object(
    observed: tuple[FixtureSourceProvider, SourceObject],
    monkeypatch: pytest.MonkeyPatch,
    sandbox: Path,
) -> None:
    """The oracle test proper: the fix must not have moved anything out of the denial.

    An object that was deleted, an identifier that was never issued, and every
    errno that stays denied all have to produce one sentence. If any of them had
    drifted into its own wording, a caller could subtract one outcome from
    another to learn that something exists, which is what section 10's
    `not_found` row forbids.
    """
    source, entry = observed
    messages = set()
    for name in sorted(DENIED_ERRNO_NAMES):
        monkeypatch.setattr(os, "open", failing_open(getattr(errno, name), sandbox / "note.txt"))
        with pytest.raises(TraversalDeniedError) as raised:
            source.fetch(entry.source_object_id, max_bytes=64)
        messages.add(template(raised.value, entry.source_object_id))

    monkeypatch.undo()
    unknown = make_identifier(IdKind.SOURCE_OBJECT, secrets.token_hex(16))
    (sandbox / "note.txt").unlink()
    for object_id in (entry.source_object_id, unknown):
        with pytest.raises(TraversalDeniedError) as raised:
            source.fetch(object_id, max_bytes=64)
        messages.add(template(raised.value, object_id))

    assert len(messages) == 1


@pytest.mark.parametrize(
    "name", sorted(UNAVAILABLE_ERRNO_NAMES | DENIED_ERRNO_NAMES | {"__unclassified__"})
)
def test_no_classified_failure_discloses_the_path_or_chains_the_original(
    observed: tuple[FixtureSourceProvider, SourceObject],
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    sandbox: Path,
) -> None:
    """Both branches raise outside the handler, and both are checked for it.

    `raise ... from None` would not be enough: it clears `__cause__` and leaves
    the `OSError` in `__context__`, where it renders with the filename it
    failed on. The difference between the two spellings is invisible on
    inspection, so it is asserted on every errno rather than argued once.
    """
    source, entry = observed
    target = sandbox / "note.txt"
    number = 4095 if name == "__unclassified__" else getattr(errno, name)
    monkeypatch.setattr(os, "open", failing_open(number, target))

    with pytest.raises(ProviderError) as raised:
        source.fetch(entry.source_object_id, max_bytes=64)

    rendered = f"{raised.value!r} {raised.value.args} {raised.value.__context__}"
    for fragment in (
        str(sandbox),
        str(sandbox.resolve()),
        "note.txt",
        "the operating system said something specific",
        os.sep,
    ):
        assert fragment not in rendered, f"{name} disclosed {fragment!r}"
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is None


def test_clamping_the_descriptor_limit_really_exhausts_descriptors() -> None:
    """Non-vacuity for the test below, and it restores the limit either way.

    Without this, a clamp that silently failed to take would leave the next test
    opening a file successfully and reporting a classification it never
    exercised.
    """
    before = resource.getrlimit(resource.RLIMIT_NOFILE)
    with descriptors_exhausted():
        observed_errno = probe_errno()

    assert observed_errno in EXHAUSTION_ERRNOS, "the clamp did not exhaust descriptors"
    assert resource.getrlimit(resource.RLIMIT_NOFILE) == before
    assert probe_errno() is None, "the limit was not restored"


def test_descriptor_exhaustion_is_not_reported_as_a_denial(
    observed: tuple[FixtureSourceProvider, SourceObject],
) -> None:
    """The reviewer's reproduction, as a test: real `EMFILE`, not a monkeypatch.

    Every assertion is made after the descriptors have been given back, because
    pytest cannot report a failure inside a region where it cannot open a file.
    The limit is restored by the context manager's `finally`, so an exception
    escaping the region restores it too -- otherwise one failure here would
    fail the rest of the session for an unrelated reason.
    """
    source, entry = observed
    before = resource.getrlimit(resource.RLIMIT_NOFILE)

    with descriptors_exhausted():
        observed_errno = probe_errno()
        outcome = capture(lambda: source.fetch(entry.source_object_id, max_bytes=64))

    assert resource.getrlimit(resource.RLIMIT_NOFILE) == before
    assert observed_errno in EXHAUSTION_ERRNOS, (
        "descriptors were not exhausted; this proves nothing"
    )
    assert observed_errno in fixture_module._UNAVAILABLE_ERRNOS, (
        "the errno this platform reports for descriptor exhaustion is not classified"
    )
    assert isinstance(outcome, ProviderError)
    assert not isinstance(outcome, TraversalDeniedError), (
        "descriptor exhaustion told the caller to stop retrying something merely unavailable"
    )
    assert not isinstance(outcome, VersionChangedError)


def test_the_object_is_still_readable_once_descriptors_are_returned(
    observed: tuple[FixtureSourceProvider, SourceObject],
) -> None:
    """The control: the shortage was the machine's, and it was temporary.

    This is what makes `unavailable` the truthful answer rather than a softer
    word for the same refusal -- the identical call succeeds once the condition
    clears, which is exactly what conditional retry guidance promises.
    """
    source, entry = observed
    with descriptors_exhausted():
        outcome = capture(lambda: source.fetch(entry.source_object_id, max_bytes=64))
    assert isinstance(outcome, ProviderError)

    content = source.fetch(entry.source_object_id, max_bytes=64)
    assert content.content == b"present, and readable when the machine allows it"
