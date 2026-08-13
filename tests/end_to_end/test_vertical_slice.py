"""The whole read-only slice, and the one identifier that has to survive it.

The first three tests are acceptance criterion 7's bridge, which is what this
module was built for. `sources.fetch` resolves a `source_object_id` in **provider
memory**; `knowledge.read` resolves one in the **database**. Before WP-4B3 the
two spaces never met, and a mismatch between them is silent: empty coverage,
empty search, no exception anywhere. A test that only proved "nothing raised"
would pass on a build where nothing worked, so **every assertion below is on a
non-empty value**, and **every count that is legitimately zero sits beside a
non-zero produced by the same mechanism in the same test** — the quarantine
count beside three non-zero coverage counts, an empty search inside a named set
beside the identical query answering inside the root grant, a refused
cross-source fetch beside the same identifier served under the source that
issued it.

**The six tests after them close the rest of the slice's seven conditions**:
one registered root and no reach outside it; listing and inspecting one level at
a time; the explicit object set beside the root selector; quarantine named
beside freshness and trust; one stored row answered identically over HTTP and
over MCP; and a request two grants both cover, refused rather than guessed.
Conditions 5 (`knowledge.search` within the enrolled scope) needs nothing new —
the first test already demonstrates it — and condition 7's source-mutation and
unknown-scope rows are proven in `tests/security/` and are deliberately not
rebuilt here.

**The slice is walked, not simulated.** `apps/cli/sources.py register` writes the
`sources` row and observes the root; `sources.enroll` enumerates the root inside
its own transaction and records the object set; `run_worker` claims the queued
job and drives `infrastructure.jobs.extraction.extract_enrollment`;
`knowledge.search` finds the text that executor stored; `knowledge.read` returns
the record and its provenance; `sources.fetch` reads the bytes back through the
provider. Every one of those is the production path — the composition root is
`bootstrap.gateway.build_gateway_runtime`, the same one `apps/gateway.py` and
`apps/cli/invoke.py` are handed, so nothing here is a shortcut around a decision.

**The identifier is traced, not assumed.** `obj` is read out of
`knowledge.enrollment_objects` — the row enumeration wrote — and is then required
to be the identifier `knowledge.search` returns, the identifier
`knowledge.read`'s provenance carries, and the identifier `sources.fetch`
accepts. Four independent resolutions of one value, two of them in the database
and two through the provider.

**The PDF is counted, never skipped.** `P00-OD-003` is open and nothing here
opens it: `handbook.pdf` reaches an `unsupported` row, is counted in the
disclosed coverage, and refuses `normalized_text` by name while still answering
`raw_bytes`. Asserting that is the difference between a defect reported and a
defect laundered.

**Two corpora, both synthetic.** Most tests point at `fixtures/mcv/root`, which
is in-repo and never written to. Two build their own under `tmp_path` — the
nested-roots test, whose subject *is* a containment geometry the committed corpus
cannot express twice over, and the quarantine test, which needs a file whose
bytes contradict its name. Extending the committed corpus instead would have
changed five files across three tiers to add one object; `_tree` says why in
full. `P00-OD-009` is satisfied by both: invented content, no live root.

No live source is reached, no network is used beyond a loopback socket this
process binds, and the database is a disposable one this module creates and
drops.
"""

from __future__ import annotations

import base64
import io
import os
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import apps.cli.sources as registration
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from tests.transports import all_transports

from my_pa.application.commands import (
    Command,
    EnrollSource,
    FetchSource,
    GetSourceMetadata,
    GetSourceStatus,
    ListSources,
    ReadKnowledge,
    Representation,
    SearchKnowledge,
)
from my_pa.bootstrap.gateway import GatewayRuntime, build_gateway_runtime
from my_pa.bootstrap.settings import ENV_PREFIX, Settings, load_settings
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.contracts.v1.status import SourceStatusState
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.provenance import TrustLevel
from my_pa.domain.common.time import format_rfc3339
from my_pa.domain.extraction.coverage import CoverageState
from my_pa.domain.extraction.quarantine import QuarantineReason
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.jobs.extraction import extract_enrollment
from my_pa.infrastructure.jobs.worker import issue_worker_owner, run_worker

ROOT: Final = Path(__file__).resolve().parents[2]

#: The in-repo synthetic corpus. Four files at depth 0 — `notes.md`,
#: `readme.txt`, `handbook.pdf`, `opaque.bin` — plus a `nested/` container that
#: depth 0 descends into and does not count, because a directory holds no
#: extractable content.
MCV_ROOT: Final = ROOT / "fixtures" / "mcv" / "root"

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
DISPOSABLE_DATABASE: Final = "my_pa_vertical_slice_test"

WHEN: Final = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)

#: A term that occurs in `notes.md` and in no other extractable file in the
#: corpus, so a search for it has exactly one answer and that answer identifies
#: the object rather than merely proving the index is not empty.
ONLY_IN_NOTES: Final = "flanges"

#: The same property for `readme.txt`, so that a search bounded to a set which
#: excludes it has a term whose absence is a boundary rather than an empty index.
ONLY_IN_README: Final = "truncation"

#: What depth 0 over `MCV_ROOT` enumerates. Stated as a number so a corpus that
#: grows makes this test fail loudly rather than silently measuring something
#: else.
ELIGIBLE: Final = 4


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def disposable_database() -> Iterator[str]:
    """An empty database at head, dropped when the module finishes.

    `MY_PA_DATABASE_URL` is repointed for the module's lifetime because
    `apps/cli/sources.py` composes its own engine from `load_settings()`, which
    is the whole point of running it rather than calling its writers directly.
    The previous value is restored in `finally`.
    """
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')
    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = os.environ.get(variable)
    try:
        _administer(maintenance, drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        command.upgrade(Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO()), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        _administer(maintenance, drop)
        maintenance.dispose()


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[GatewayRuntime]:
    """The composition every transport is handed, over a disposable database."""
    built = build_gateway_runtime(Settings(database_url=disposable_database))
    try:
        with built.work_engine.begin() as connection:
            connection.execute(text("TRUNCATE knowledge.sources CASCADE"))
            connection.execute(
                text(
                    "TRUNCATE knowledge.native_simulation_receipts, "
                    "knowledge.native_checkpoints, "
                    "knowledge.native_apple_read_grants, "
                    "knowledge.native_admission_authorities, knowledge.audit_events"
                )
            )
        yield built
    finally:
        built.close()


def _invoke(
    runtime: GatewayRuntime, capability: Capability, purpose: Purpose, request: Command, tag: str
) -> ResponseEnvelope:
    """One request through the real application, as a transport would make it."""
    return runtime.service.invoke(
        RequestMetadata(
            request_id=f"req-slice-{tag}",
            capability=capability,
            purpose=purpose,
            principal_id=runtime.principal.principal_id,
            requested_at=WHEN,
        ),
        request,
        principal=runtime.principal,
    )


def _succeeded(envelope: ResponseEnvelope, what: str) -> dict[str, Any]:
    """The result payload, or a failure that names which step refused."""
    assert envelope.error is None, (
        f"{what} refused with {envelope.error.code if envelope.error else None}; "
        "the slice cannot be proven past a step that did not run"
    )
    assert isinstance(envelope.result, dict) and envelope.result, (
        f"{what} succeeded with an empty payload, which is the silent failure "
        "this test exists to catch"
    )
    return envelope.result


def _register(
    capsys: pytest.CaptureFixture[str],
    root: Path = MCV_ROOT,
    label: str = "MCV synthetic corpus",
) -> tuple[str, str]:
    """Run the operator command and read back the two identifiers it issues.

    Parsed from the command's own stdout rather than from a second query,
    because what has to be true is that an operator running this command can
    reach the rest of the product with what it printed.

    `root` is a parameter because two tests below register more than one source
    — one of them registers two roots whose *containment* is the whole subject —
    and the committed corpus is the default because that is what the first three
    tests are about.
    """
    status = registration.main(
        [
            "register",
            "--provider",
            "fixture",
            "--root",
            str(root),
            "--label",
            label,
            "--classification",
            "synthetic_test",
        ]
    )
    printed = capsys.readouterr().out
    assert status == registration.EXIT_OK, f"register refused: {printed}"

    fields = dict(
        line.split(maxsplit=1) for line in printed.splitlines() if len(line.split(maxsplit=1)) == 2
    )
    source_id, root_object_id = fields["source_id"].strip(), fields["root_object_id"].strip()
    validate_identifier(source_id, IdKind.SOURCE)
    validate_identifier(root_object_id, IdKind.SOURCE_OBJECT)

    # The command claims `--root` is never echoed on any path. It is cheap to
    # hold it to that here, where the value is known.
    assert str(root.resolve()) not in printed, "the configured root reached stdout"
    return source_id, root_object_id


def _enroll(
    runtime: GatewayRuntime,
    source_id: str,
    root_object_id: str | None = None,
    *,
    object_ids: tuple[str, ...] = (),
    key: str = "vertical-slice-1",
    depth: int = 0,
    tag: str = "enroll",
) -> dict[str, Any]:
    """One accepted grant. Exactly one of `root_object_id` and `object_ids` is set.

    The selector is the command's own refusal to be given both, so it is not
    re-checked here; what this adds is that a test naming an explicit object set
    reaches the same acceptance path as one naming a root.
    """
    envelope = _invoke(
        runtime,
        Capability.SOURCES_ENROLL,
        Purpose.BOUNDED_ENROLLMENT,
        EnrollSource(
            source_id=source_id,
            media_types=("text/markdown", "text/plain"),
            idempotency_key=key,
            root_object_id=root_object_id,
            object_ids=object_ids,
            depth=depth,
            max_items=100,
            max_bytes=1 << 16,
        ),
        tag,
    )
    return _succeeded(envelope, "sources.enroll")


def _enumerated(runtime: GatewayRuntime, enrollment_id: str) -> tuple[str, ...]:
    """The object identifiers enumeration recorded, straight from the table."""
    with runtime.work_engine.connect() as connection:
        return tuple(
            str(row[0])
            for row in connection.execute(
                text(
                    "SELECT source_object_id FROM knowledge.enrollment_objects "
                    "WHERE enrollment_id = :id ORDER BY source_object_id"
                ),
                {"id": enrollment_id},
            )
        )


def _work(runtime: GatewayRuntime, *, iterations: int = 1) -> tuple[int, int]:
    """Drive the real worker loop. `iterations` because two grants queue two jobs."""
    run = run_worker(
        runtime.work_engine,
        # The Principal this runtime acts as — the same one whose enrollments
        # queued the work. A worker claims its own Principal's queue (WP-04).
        principal_id=runtime.principal.principal_id,
        owner=issue_worker_owner(),
        handler=extract_enrollment,
        stop=threading.Event(),
        max_iterations=iterations,
    )
    return run.claimed, run.completed


def _tree(root: Path, files: dict[str, bytes]) -> Path:
    """Build a synthetic corpus at `root`, creating intermediate containers.

    `tmp_path` rather than an addition to `fixtures/mcv/root`, deliberately.
    Extending the committed corpus to add one object would change
    `tests/provider_conformance/test_fixture_provider.py`'s `CORPUS` and
    `EXPECTED_ROOT_ORDER`, `fixtures/mcv/README.md`'s per-file table,
    `tests/jobs/test_extraction_executor.py`'s "four-file shape" comment, and all
    three existing assertions in this module — including turning a positional
    comparison of refusal codes into an order-dependent one over a randomly
    ordered identifier set. A corpus built here changes none of them and states
    its own shape in the test that asserts it. `P00-OD-009` is satisfied either
    way: synthetic, invented, no live root.
    """
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    return root


def _object_ending(runtime: GatewayRuntime, source_id: str, suffix: str) -> str:
    """The identifier this source issued for the object whose locator ends `suffix`.

    A test that has to name one particular file needs the identifier the store
    issued for it, and the provider discloses no name. Read from
    `knowledge.source_objects` under the stated source, so an identifier issued
    under a *different* source can never be returned by accident — which matters
    in the one test below that registers two overlapping roots.
    """
    with runtime.work_engine.connect() as connection:
        return str(
            connection.execute(
                text(
                    "SELECT source_object_id FROM knowledge.source_objects "
                    "WHERE source_id = :source AND native_locator LIKE :pattern"
                ),
                {"source": source_id, "pattern": f"%{suffix}"},
            ).scalar_one()
        )


def _modified(path: Path) -> str:
    """The file's own modification time, formatted the way the answer carries it.

    Built with the provider's own formula (`providers/fixture.py`,
    `datetime.fromtimestamp(status.st_mtime, UTC)`) so that comparing the two is
    comparing a filesystem fact against what travelled through the provider, the
    `extractions` row, and the response — rather than comparing a value with a
    restatement of itself.
    """
    return format_rfc3339(datetime.fromtimestamp(path.stat().st_mtime, UTC))


@pytest.mark.database
@pytest.mark.e2e
def test_the_identifier_enrollment_issued_is_accepted_by_fetch_and_returned_by_read(
    runtime: GatewayRuntime, capsys: pytest.CaptureFixture[str]
) -> None:
    """Criterion 7, proven from both ends against one identifier.

    End **(a)** is the database: `knowledge.read`'s provenance must carry the
    identifier enumeration issued. End **(b)** is provider memory:
    `sources.fetch` must accept that same identifier and return content for it.
    Both assertions are on non-empty values and neither implies the other —
    an executor built without a durable identity leaves (b) passing while (a)
    has nothing to read, and a fetch that returns an empty body leaves (a)
    passing while (b) returns nothing a caller can use.
    """
    source_id, root_object_id = _register(capsys)

    accepted = _enroll(runtime, source_id, root_object_id)
    assert accepted["created"] is True
    assert accepted["operation_id"] is not None, "no work was queued for an accepted enrollment"
    enrollment_id = accepted["enrollment_id"]

    # The denominator is measured at acceptance, not guessed, and the two tokens
    # this package deleted may not reappear in the envelope that used to carry
    # them.
    enroll_disclosure = _invoke(
        runtime,
        Capability.SOURCES_STATUS,
        Purpose.STATUS_OBSERVATION,
        GetSourceStatus(enrollment_id=enrollment_id),
        "status-accepted",
    ).disclosure
    assert enroll_disclosure is not None
    assert enroll_disclosure.coverage.eligible == ELIGIBLE
    assert not {
        "eligible_total_not_persisted",
        "scope_is_source_wide_not_root_bounded",
    } & set(enroll_disclosure.limitations)

    enumerated = _enumerated(runtime, enrollment_id)
    assert len(enumerated) == ELIGIBLE, (
        "enumeration recorded no object set; every assertion below would then be "
        "about an empty scope"
    )

    assert _work(runtime) == (1, 1), "the queued job was not claimed and completed"

    # What one pass covered, disclosed through the capability rather than read
    # out of the tables. The PDF and the unidentifiable binary are *counted*.
    covered = _invoke(
        runtime,
        Capability.SOURCES_STATUS,
        Purpose.STATUS_OBSERVATION,
        GetSourceStatus(enrollment_id=enrollment_id),
        "status-covered",
    ).disclosure
    assert covered is not None
    assert (
        covered.coverage.eligible,
        covered.coverage.processed,
        covered.coverage.unsupported,
        covered.coverage.quarantined,
    ) == (ELIGIBLE, 2, 2, 0), (
        "the executor did not cover the enumerated set as expected. `processed == 0` "
        "with everything quarantined is the bridge broken on the worker's side: the "
        "identifiers `enrollment_objects` holds are not ones its provider can resolve, "
        "so end (a) has nothing to read even though end (b) still answers"
    )
    assert covered.coverage.state is CoverageState.PARTIALLY_PROCESSED
    assert covered.partial_result is True
    assert "scope_not_fully_extracted" in covered.limitations

    # --- the identifier enters the read side -----------------------------------
    found = _succeeded(
        _invoke(
            runtime,
            Capability.KNOWLEDGE_SEARCH,
            Purpose.KNOWLEDGE_SEARCH,
            SearchKnowledge(enrollment_id=enrollment_id, query=ONLY_IN_NOTES),
            "search",
        ),
        "knowledge.search",
    )
    matches = found["matches"]
    assert len(matches) == 1, (
        f"search for {ONLY_IN_NOTES!r} returned {len(matches)} matches. Zero is the "
        "silent failure: the identifier the executor recorded against is not one "
        "this enrollment authorizes, so the text is stored and unreachable"
    )
    match = matches[0]
    assert match["snippet"], "a match with an empty snippet proves nothing was stored"

    knowledge_id, obj = match["knowledge_id"], match["source_object_id"]
    assert obj in enumerated, (
        "search returned an object identifier that enumeration never issued; the "
        "two identifier spaces have come apart"
    )

    # --- end (a): the database returns the identifier enumeration issued --------
    record = _succeeded(
        _invoke(
            runtime,
            Capability.KNOWLEDGE_READ,
            Purpose.KNOWLEDGE_READ,
            ReadKnowledge(knowledge_id=knowledge_id, enrollment_id=enrollment_id),
            "read",
        ),
        "knowledge.read",
    )
    assert record["text"], "knowledge.read returned a record with no text"
    assert ONLY_IN_NOTES in record["text"]
    assert record["character_count"] > 0
    assert record["provenance"]["source_object_id"] == obj, (
        "end (a) failed: knowledge.read's provenance names "
        f"{record['provenance']['source_object_id']!r}, but enumeration issued {obj!r}"
    )
    assert record["provenance"]["source_id"] == source_id

    # --- end (b): the provider accepts the same identifier ----------------------
    extracted = _succeeded(
        _invoke(
            runtime,
            Capability.SOURCES_FETCH,
            Purpose.CONTENT_EXTRACTION,
            FetchSource(source_id=source_id, source_object_id=obj, enrollment_id=enrollment_id),
            "fetch-text",
        ),
        "sources.fetch (normalized_text)",
    )
    assert extracted["text"], (
        "end (b) failed: sources.fetch accepted the identifier and returned no "
        "text. An empty body is this package's silent failure mode, not a pass"
    )
    assert ONLY_IN_NOTES in extracted["text"]
    assert extracted["character_count"] > 0

    raw = _succeeded(
        _invoke(
            runtime,
            Capability.SOURCES_FETCH,
            Purpose.CONTENT_EXTRACTION,
            FetchSource(
                source_id=source_id,
                source_object_id=obj,
                representation=Representation.RAW_BYTES,
                enrollment_id=enrollment_id,
            ),
            "fetch-bytes",
        ),
        "sources.fetch (raw_bytes)",
    )
    assert raw["byte_count"] > 0
    assert base64.b64decode(raw["content_base64"]), "fetch returned an empty body as base64"

    # One identifier, four resolutions: the enumeration table, the search index,
    # the stored provenance, and the provider. Two in the database, two through
    # provider memory.
    assert {
        obj,
        record["provenance"]["source_object_id"],
        match["source_object_id"],
    } == {obj}


@pytest.mark.database
@pytest.mark.e2e
def test_the_operator_can_list_back_what_the_operator_registered(
    runtime: GatewayRuntime, capsys: pytest.CaptureFixture[str]
) -> None:
    """`register` then `list`, through `registry.all_sources`, disclosing no root.

    The listing is the only reader of the whole source set and it is the reason
    `all_sources` exists: before it, this command selected from the `sources`
    table declaration, which meant the operator-command guard had to admit a
    write surface to permit a read. Asserting on the printed line rather than on
    the function keeps the claim at the level an operator experiences it.

    The assertion is on a non-empty listing that names the identifier just
    issued. A `list` that printed nothing would satisfy "it did not crash" and
    is exactly what this must not accept.
    """
    source_id, _ = _register(capsys)

    assert registration.main(["list"]) == registration.EXIT_OK
    printed = capsys.readouterr().out

    assert source_id in printed, "the registered source is absent from its own listing"
    assert "MCV synthetic corpus" in printed
    assert "synthetic_test" in printed
    assert printed.rstrip().endswith("sources     1")
    assert str(MCV_ROOT.resolve()) not in printed, "the configured root reached stdout"


@pytest.mark.database
@pytest.mark.e2e
def test_every_enumerated_identifier_is_fetchable_and_the_pdf_is_reported_not_skipped(
    runtime: GatewayRuntime, capsys: pytest.CaptureFixture[str]
) -> None:
    """The bridge holds for the whole enumerated set, and the defect stays named.

    The first test proves one identifier crosses. This proves the property is
    not an accident of which object the search happened to return: *every*
    identifier `enrollment_objects` holds is one the provider resolves and
    serves bytes for, including the two the extractor cannot read.

    `handbook.pdf` is the reason the second half exists. `P00-OD-003` is open,
    so a PDF must be **reported** rather than silently skipped: it answers
    `raw_bytes` with real bytes, refuses `normalized_text` with `unsupported`,
    and is counted in the coverage the first test asserts. The zero here — no
    identifier that fails to resolve — is only meaningful because it sits beside
    four non-empty bodies in the same test.
    """
    source_id, root_object_id = _register(capsys)
    accepted = _enroll(runtime, source_id, root_object_id)
    enrollment_id = accepted["enrollment_id"]
    enumerated = _enumerated(runtime, enrollment_id)
    assert len(enumerated) == ELIGIBLE

    bodies: dict[str, int] = {}
    for index, obj in enumerate(enumerated):
        raw = _succeeded(
            _invoke(
                runtime,
                Capability.SOURCES_FETCH,
                Purpose.SOURCE_INSPECTION,
                FetchSource(
                    source_id=source_id,
                    source_object_id=obj,
                    representation=Representation.RAW_BYTES,
                    enrollment_id=enrollment_id,
                ),
                f"fetch-raw-{index}",
            ),
            f"sources.fetch (raw_bytes) for enumerated object {index}",
        )
        bodies[obj] = raw["byte_count"]

    assert len(bodies) == ELIGIBLE
    assert all(count > 0 for count in bodies.values()), (
        f"an enumerated identifier fetched an empty body: {bodies}"
    )

    # The two the extractor will not read still resolve; they refuse the *text*
    # representation, by name, and that refusal is the report.
    refusals = []
    for index, obj in enumerate(enumerated):
        envelope = _invoke(
            runtime,
            Capability.SOURCES_FETCH,
            Purpose.CONTENT_EXTRACTION,
            FetchSource(source_id=source_id, source_object_id=obj, enrollment_id=enrollment_id),
            f"fetch-text-{index}",
        )
        if envelope.error is not None:
            refusals.append(envelope.error.code)
        else:
            assert envelope.result is not None and envelope.result["text"]

    assert refusals == [ErrorCode.UNSUPPORTED, ErrorCode.UNSUPPORTED], (
        f"expected exactly two unsupported refusals over {ELIGIBLE} objects, got {refusals}. "
        "A PDF that fetched as text would mean it had been coerced; one that "
        "resolved to nothing would mean it had been skipped"
    )


# ---- condition 1: one approved root, and no reach outside it -------------------


@pytest.mark.database
@pytest.mark.e2e
def test_an_identifier_issued_under_one_registered_root_is_denied_under_a_nested_one(
    runtime: GatewayRuntime, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """Two registered roots, and an identifier that belongs to exactly one of them.

    `knowledge.source_objects` is **one table across every configured source**
    and `resolve_native_locator` keys on the object alone, so an identifier
    issued under source A would resolve, under source B's provider, to A's
    locator. `RegistryIdentity.locate`'s ownership test
    (`providers/identity.py:230-232`) is what stops that, and its own docstring
    names the defect it prevents: *"one registered root nested inside another
    would then let a provider serve an object it was never given."*

    **Nothing exercises it.** With `EphemeralIdentity` — which is what the whole
    FAST provider-conformance suite runs against — the confusion is structurally
    impossible, because the map is a private dictionary per provider instance.
    The one `database`-marked provider-conformance test registers a single
    source. So this guard has never fired anywhere, at any tier.

    **The geometry is load-bearing and a later reader must not flatten it.**
    B's root is a **subdirectory** of A's. That direction is the only one that
    tests anything. If B's root *contained* A's, the leaked locator would resolve
    *outside* B's root and `resolve_within` would deny it whatever the ownership
    test did — the guard would be untestable and any plant on it vacuous, which
    is precisely the shape `D-55` records. With B nested inside A, the leaked
    locator lands **inside** B's root, `resolve_within` passes it, and the
    ownership test is the only thing standing between B and an object it was
    never given. The containment is asserted below rather than only described.

    **The identifier is reached by listing, not by enrolling.** The effective
    `max_enrollment_depth` is **0** by default (`Settings` in
    `bootstrap/settings.py`) and
    the handler refuses a deeper request outright, so no enrollment this
    composition accepts can reach a grandchild. `sources.list` can: it is bounded
    by the registered root and not by the enrolled object set, which is
    `_sources_list`'s own shape — it resolves `_one_enrollment` for the *source*
    and then asks the provider. Walking one level at a time is therefore the
    production way to reach this object, and it issues the identifier through
    the same `RegistryIdentity` the enrollment would have.

    The control is in this test: the identical identifier, fetched under **A**,
    returns real bytes. Without it a build that denied everything would pass.
    """
    corpus = _tree(
        tmp_path / "corpus",
        {
            "top.md": b"# Top\n\nAt the outer root.\n",
            "inner/inner.md": b"# Inner\n\nAt the inner root.\n",
            "inner/deeper/log.txt": b"a grandchild of the outer root, a child of the inner one\n",
        },
    )
    leaked_path = corpus / "inner" / "deeper" / "log.txt"

    # The geometry, asserted. B inside A, and the object under test inside B.
    assert (corpus / "inner").resolve().is_relative_to(corpus.resolve())
    assert leaked_path.resolve().is_relative_to((corpus / "inner").resolve())

    outer_source, outer_root = _register(capsys, corpus, "Outer synthetic corpus")
    inner_source, inner_root = _register(capsys, corpus / "inner", "Inner synthetic corpus")
    assert outer_source != inner_source, "the two roots were configured as one source"

    outer = _enroll(runtime, outer_source, outer_root, key="two-roots-outer", tag="outer")
    inner = _enroll(runtime, inner_source, inner_root, key="two-roots-inner", tag="inner")
    outer_objects = _enumerated(runtime, outer["enrollment_id"])
    inner_objects = _enumerated(runtime, inner["enrollment_id"])
    assert len(outer_objects) == 1, outer_objects
    assert len(inner_objects) == 1, inner_objects

    # Two listings under the **outer** source, which is what issues the
    # identifier: the inner container, then the container below it. Every
    # identifier here is minted by the outer source's `RegistryIdentity`.
    def _children(parent: str | None, tag: str) -> list[dict[str, Any]]:
        return _succeeded(
            _invoke(
                runtime,
                Capability.SOURCES_LIST,
                Purpose.SOURCE_INSPECTION,
                ListSources(
                    source_id=outer_source,
                    parent_object_id=parent,
                    enrollment_id=outer["enrollment_id"],
                ),
                tag,
            ),
            f"sources.list ({tag})",
        )["objects"]

    at_root = _children(None, "two-roots-list-root")
    inner_container = next(child for child in at_root if child["kind"] == "container")
    below = _children(inner_container["source_object_id"], "two-roots-list-inner")
    deeper_container = next(child for child in below if child["kind"] == "container")
    grandchildren = _children(deeper_container["source_object_id"], "two-roots-list-deeper")
    assert len(grandchildren) == 1, grandchildren
    leaked = grandchildren[0]["source_object_id"]

    assert leaked == _object_ending(runtime, outer_source, "inner/deeper/log.txt"), (
        "the listing and the store disagree about which identifier the outer "
        "source issued for the object under test"
    )
    assert leaked not in inner_objects, "the inner root enumerated the object under test"

    # The escape: the inner source is handed the outer source's identifier, and
    # its own grant. The locator behind it is inside the inner root, so
    # containment alone would let this through.
    refused = _invoke(
        runtime,
        Capability.SOURCES_FETCH,
        Purpose.SOURCE_INSPECTION,
        FetchSource(
            source_id=inner_source,
            source_object_id=leaked,
            representation=Representation.RAW_BYTES,
            enrollment_id=inner["enrollment_id"],
        ),
        "cross-source",
    )
    assert refused.error is not None, (
        "the inner source served an object issued under the outer source. The "
        "locator resolves inside the inner root, so containment cannot have "
        "caught it; the ownership test is what was missing"
    )
    assert refused.error.code == ErrorCode.DENIED
    assert refused.result is None

    # The control, in the same test: the identifier is good, under the source
    # that issued it. A build that denied every fetch would fail here.
    served = _succeeded(
        _invoke(
            runtime,
            Capability.SOURCES_FETCH,
            Purpose.SOURCE_INSPECTION,
            FetchSource(
                source_id=outer_source,
                source_object_id=leaked,
                representation=Representation.RAW_BYTES,
                enrollment_id=outer["enrollment_id"],
            ),
            "own-source",
        ),
        "sources.fetch under the source that issued the identifier",
    )
    assert served["byte_count"] > 0
    assert base64.b64decode(served["content_base64"]) == leaked_path.read_bytes()

    # Nothing about either root reached the caller on either path.
    assert str(corpus.resolve()) not in repr(refused)
    assert str(corpus.resolve()) not in repr(served)


# ---- condition 2: list and inspect, one level at a time ------------------------


@pytest.mark.database
@pytest.mark.e2e
def test_the_operator_can_list_and_inspect_bounded_objects_without_recursing(
    runtime: GatewayRuntime, capsys: pytest.CaptureFixture[str]
) -> None:
    """`sources.list` and `sources.metadata` end to end, and the grandchild that never surfaces.

    `sources.list` and `sources.metadata` are invoked by no end-to-end test at
    this head. Both are proven here against the real store, and the listing does
    double duty: the count of immediate children is deliberately **not** the
    eligible total, because a container is descended and not recorded
    (`service.py::_enumerate`), so asserting both numbers in one test is the
    "no recursive discovery" evidence for condition 1 as well as the listing
    evidence for condition 2.

    The absence — `log.txt` in neither ancestor's listing — sits beside five
    presences and a successful listing of its own parent, so it is a bounded
    walk rather than an empty answer.
    """
    source_id, root_object_id = _register(capsys)
    accepted = _enroll(runtime, source_id, root_object_id)
    enrollment_id = accepted["enrollment_id"]
    enumerated = _enumerated(runtime, enrollment_id)
    assert len(enumerated) == ELIGIBLE

    root_listing = _succeeded(
        _invoke(
            runtime,
            Capability.SOURCES_LIST,
            Purpose.SOURCE_INSPECTION,
            ListSources(source_id=source_id, enrollment_id=enrollment_id),
            "list-root",
        ),
        "sources.list (root)",
    )["objects"]
    assert len(root_listing) == 5, root_listing
    assert len(root_listing) != ELIGIBLE, (
        "the listing and the eligible total came out equal, which would mean the "
        "container was either counted as extractable or not listed at all"
    )
    files = [child for child in root_listing if child["kind"] == "file"]
    containers = [child for child in root_listing if child["kind"] == "container"]
    assert len(containers) == 1
    assert {child["source_object_id"] for child in files} == set(enumerated), (
        "the identifiers `sources.list` discloses are not the identifiers "
        "enumeration recorded; the two readers of one store disagree"
    )

    # One level down. Two children, one of each kind — and the file here is not
    # in the root listing, which is what "immediate children only" means.
    nested = containers[0]["source_object_id"]
    nested_listing = _succeeded(
        _invoke(
            runtime,
            Capability.SOURCES_LIST,
            Purpose.SOURCE_INSPECTION,
            ListSources(source_id=source_id, parent_object_id=nested, enrollment_id=enrollment_id),
            "list-nested",
        ),
        "sources.list (nested)",
    )["objects"]
    assert sorted(child["kind"] for child in nested_listing) == ["container", "file"], (
        nested_listing
    )

    deeper = next(
        child["source_object_id"] for child in nested_listing if child["kind"] == "container"
    )
    deeper_listing = _succeeded(
        _invoke(
            runtime,
            Capability.SOURCES_LIST,
            Purpose.SOURCE_INSPECTION,
            ListSources(source_id=source_id, parent_object_id=deeper, enrollment_id=enrollment_id),
            "list-deeper",
        ),
        "sources.list (deeper)",
    )["objects"]
    assert len(deeper_listing) == 1, deeper_listing
    grandchild = deeper_listing[0]["source_object_id"]
    assert grandchild not in {child["source_object_id"] for child in root_listing}
    assert grandchild not in {child["source_object_id"] for child in nested_listing}
    assert grandchild not in enumerated, (
        "an object two levels below the root entered the enrolled scope; depth 0 "
        "is the named root and its immediate children and nothing else"
    )

    # --- inspection, and the two kind-derived operation sets --------------------
    markdown = next(child for child in files if child["media_type"] == "text/markdown")
    described = _succeeded(
        _invoke(
            runtime,
            Capability.SOURCES_METADATA,
            Purpose.SOURCE_INSPECTION,
            GetSourceMetadata(
                source_id=source_id,
                source_object_id=markdown["source_object_id"],
                enrollment_id=enrollment_id,
            ),
            "metadata-file",
        ),
        "sources.metadata (file)",
    )
    assert described["kind"] == "file"
    assert described["media_type"] == "text/markdown"
    assert described["size_bytes"] > 0
    assert described["supported_operations"] == ["metadata", "fetch"]
    assert described["modified_at"] == _modified(MCV_ROOT / "notes.md")
    assert described["status"] == SourceStatusState.ACCEPTED.value, (
        "an object with no outcome yet reported something other than `accepted`"
    )

    container = _succeeded(
        _invoke(
            runtime,
            Capability.SOURCES_METADATA,
            Purpose.SOURCE_INSPECTION,
            GetSourceMetadata(
                source_id=source_id, source_object_id=nested, enrollment_id=enrollment_id
            ),
            "metadata-container",
        ),
        "sources.metadata (container)",
    )
    assert container["kind"] == "container"
    assert container["supported_operations"] == ["metadata", "list_children"], (
        "the operation set stopped being derived from the object's kind"
    )
    assert container["size_bytes"] is None

    # --- the status field tracks the store, and is not a constant ---------------
    assert _work(runtime) == (1, 1)
    after = _succeeded(
        _invoke(
            runtime,
            Capability.SOURCES_METADATA,
            Purpose.SOURCE_INSPECTION,
            GetSourceMetadata(
                source_id=source_id,
                source_object_id=markdown["source_object_id"],
                enrollment_id=enrollment_id,
            ),
            "metadata-after",
        ),
        "sources.metadata (after the worker ran)",
    )
    assert after["status"] == SourceStatusState.COMPLETE_FOR_SCOPE.value
    assert after["status"] != described["status"], (
        "the status was the same before and after extraction, so it reports a "
        "constant rather than the persisted outcome"
    )


# ---- condition 3: the explicit object set --------------------------------------


@pytest.mark.database
@pytest.mark.e2e
def test_an_enrollment_naming_its_objects_authorizes_those_and_no_others(
    runtime: GatewayRuntime, capsys: pytest.CaptureFixture[str]
) -> None:
    """The `object_ids` selector, end to end, beside a root selector over the same source.

    Condition 3 asks for a bounded subtree **or an explicit object set**, and
    only the subtree half is walked end to end at this head. Both grants are made
    here over one source and one principal, so the comparison is between two
    selectors rather than between two situations.

    **The isolating pair.** A search inside the named set for a term that occurs
    only in an *excluded* object returns nothing, while the same search inside
    the root grant returns one match — a zero that means something because a
    non-zero produced by the same query sits next to it. And the record the root
    grant produced for that excluded object is `not_found` under the named grant,
    while the named grant's own record reads back with its text. Both selectors
    are answered by one membership predicate (`authorized_object`), and this is
    that predicate observed from the outside.
    """
    source_id, root_object_id = _register(capsys)
    whole = _enroll(runtime, source_id, root_object_id)
    enumerated = _enumerated(runtime, whole["enrollment_id"])
    assert len(enumerated) == ELIGIBLE

    kinds = {
        obj: _succeeded(
            _invoke(
                runtime,
                Capability.SOURCES_METADATA,
                Purpose.SOURCE_INSPECTION,
                GetSourceMetadata(
                    source_id=source_id,
                    source_object_id=obj,
                    enrollment_id=whole["enrollment_id"],
                ),
                f"named-metadata-{index}",
            ),
            "sources.metadata",
        )["media_type"]
        for index, obj in enumerate(enumerated)
    }
    markdown = next(obj for obj, media in kinds.items() if media == "text/markdown")
    pdf = next(obj for obj, media in kinds.items() if media == "application/pdf")
    excluded = next(obj for obj, media in kinds.items() if media == "text/plain")
    named_set = tuple(sorted((markdown, pdf)))

    named = _enroll(
        runtime,
        source_id,
        object_ids=named_set,
        key="named-subset",
        tag="named",
    )
    assert named["created"] is True
    assert named["enrollment_id"] != whole["enrollment_id"]
    assert named["selector"] == "object_ids", (
        "the accepted grant reports the selector the request did not use"
    )
    assert _enumerated(runtime, named["enrollment_id"]) == named_set, (
        "`enrollment_objects` does not hold exactly the objects the request named"
    )

    accepted = _invoke(
        runtime,
        Capability.SOURCES_STATUS,
        Purpose.STATUS_OBSERVATION,
        GetSourceStatus(enrollment_id=named["enrollment_id"]),
        "named-status",
    ).disclosure
    assert accepted is not None
    assert accepted.coverage.eligible == 2, (
        "the eligible total of a named set is not the size of the set it named"
    )

    # Two grants, two queued jobs.
    assert _work(runtime, iterations=2) == (2, 2)

    covered = _invoke(
        runtime,
        Capability.SOURCES_STATUS,
        Purpose.STATUS_OBSERVATION,
        GetSourceStatus(enrollment_id=named["enrollment_id"]),
        "named-covered",
    ).disclosure
    assert covered is not None
    assert (
        covered.coverage.eligible,
        covered.coverage.processed,
        covered.coverage.unsupported,
        covered.coverage.quarantined,
    ) == (2, 1, 1, 0), "the worker covered something other than the named set"

    # --- the zero, beside the non-zero that makes it mean something -------------
    inside = _succeeded(
        _invoke(
            runtime,
            Capability.KNOWLEDGE_SEARCH,
            Purpose.KNOWLEDGE_SEARCH,
            SearchKnowledge(enrollment_id=named["enrollment_id"], query=ONLY_IN_NOTES),
            "named-search-included",
        ),
        "knowledge.search inside the named set",
    )["matches"]
    assert len(inside) == 1, inside
    assert inside[0]["source_object_id"] == markdown

    outside = _succeeded(
        _invoke(
            runtime,
            Capability.KNOWLEDGE_SEARCH,
            Purpose.KNOWLEDGE_SEARCH,
            SearchKnowledge(enrollment_id=named["enrollment_id"], query=ONLY_IN_README),
            "named-search-excluded",
        ),
        "knowledge.search for an excluded object",
    )["matches"]
    assert outside == [], (
        "the named set answered for an object it never named. The identical "
        "query inside the root grant is asserted next, so this zero is a "
        "boundary rather than an empty index"
    )

    control = _succeeded(
        _invoke(
            runtime,
            Capability.KNOWLEDGE_SEARCH,
            Purpose.KNOWLEDGE_SEARCH,
            SearchKnowledge(enrollment_id=whole["enrollment_id"], query=ONLY_IN_README),
            "whole-search-excluded",
        ),
        "knowledge.search inside the root grant",
    )["matches"]
    assert len(control) == 1, (
        f"the root grant returned {len(control)} matches for a term the corpus "
        "holds, so the zero above proves nothing"
    )
    assert control[0]["source_object_id"] == excluded

    # --- the same object, read under each grant ---------------------------------
    refused = _invoke(
        runtime,
        Capability.KNOWLEDGE_READ,
        Purpose.KNOWLEDGE_READ,
        ReadKnowledge(
            knowledge_id=control[0]["knowledge_id"], enrollment_id=named["enrollment_id"]
        ),
        "named-read-excluded",
    )
    assert refused.error is not None and refused.error.code == ErrorCode.NOT_FOUND, (
        "a record produced under the root grant was readable under a grant that "
        "never named its object"
    )

    allowed = _succeeded(
        _invoke(
            runtime,
            Capability.KNOWLEDGE_READ,
            Purpose.KNOWLEDGE_READ,
            ReadKnowledge(
                knowledge_id=inside[0]["knowledge_id"], enrollment_id=named["enrollment_id"]
            ),
            "named-read-included",
        ),
        "knowledge.read inside the named set",
    )
    assert ONLY_IN_NOTES in allowed["text"]
    assert allowed["provenance"]["source_object_id"] == markdown


# ---- condition 4: quarantine by name, beside freshness and trust ---------------


@pytest.mark.database
@pytest.mark.e2e
def test_a_failing_object_is_quarantined_by_name_beside_its_freshness_and_trust(
    runtime: GatewayRuntime, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    """The fourth coverage count, and the two disclosure fields nothing asserts.

    `quarantined` is asserted `== 0` by the existing slice and `freshness` and
    `trust` appear in it nowhere. All three are closed here over a corpus that
    contains one deliberate failure, and none of the three is asserted as a bare
    count or a bare constant:

    * the quarantined object is **named** — its identifier is required to be one
      enumeration issued, `quarantine_records` is required to hold exactly one
      row for it, and the reason is required to be the one its bytes imply;
    * **freshness** is asserted at `provenance.observed_at`, which is the
      object's own modification time carried through the provider and the
      `extractions` row — deliberately not the request clock
      (`service.py::_sources_fetch`) — and `disclosure.freshness.observed_at`,
      which *is* a request clock, is asserted to be no earlier;
    * **trust** is asserted to be the level and basis read out of the stored
      provenance, beside a `sources.fetch` in the same test that discloses a
      **different** level from the provider — so neither is whatever the layer
      happens to emit for everything.

    `handbook.pdf` stays `unsupported`, counted and reported. `P00-OD-003` is
    open and this test does not repurpose the PDF as the quarantine case; the
    quarantine is a file whose bytes contradict the media type its name declares,
    which is deterministic and needs no filesystem race.
    """
    corpus = _tree(
        tmp_path / "quarantine-corpus",
        {
            "notes.md": f"# Notes\n\nThe blue widget has three {ONLY_IN_NOTES}.\n".encode(),
            "readme.txt": b"Synthetic plain-text fixture.\n",
            "handbook.pdf": b"%PDF-1.7\nreported, not read, and not the quarantine case\n",
            "opaque.bin": bytes(range(32)),
            "mislabelled.md": b"%PDF-1.7\ncalling itself markdown\n",
        },
    )
    source_id, root_object_id = _register(capsys, corpus, "Quarantine synthetic corpus")
    accepted = _enroll(runtime, source_id, root_object_id, key="quarantine-1", tag="quarantine")
    enrollment_id = accepted["enrollment_id"]
    enumerated = _enumerated(runtime, enrollment_id)
    assert len(enumerated) == 5, enumerated

    assert _work(runtime) == (1, 1)

    covered = _invoke(
        runtime,
        Capability.SOURCES_STATUS,
        Purpose.STATUS_OBSERVATION,
        GetSourceStatus(enrollment_id=enrollment_id),
        "quarantine-status",
    ).disclosure
    assert covered is not None
    assert (
        covered.coverage.eligible,
        covered.coverage.processed,
        covered.coverage.unsupported,
        covered.coverage.quarantined,
    ) == (5, 2, 2, 1), "the one quarantine sits beside two processed and two unsupported"
    assert covered.coverage.state is CoverageState.PARTIALLY_PROCESSED

    # --- the quarantine, named rather than counted ------------------------------
    with runtime.work_engine.connect() as connection:
        quarantined = [
            (str(row[0]), str(row[1]))
            for row in connection.execute(
                text(
                    "SELECT source_object_id, reason FROM knowledge.quarantine_records "
                    "WHERE enrollment_id = :id"
                ),
                {"id": enrollment_id},
            )
        ]
    assert len(quarantined) == 1, quarantined
    stopped, reason = quarantined[0]
    assert stopped in enumerated, "the quarantined object is not one enumeration issued"
    assert reason == QuarantineReason.MEDIA_TYPE_CONFLICTS_WITH_SIGNATURE.value
    assert stopped == _object_ending(runtime, source_id, "mislabelled.md"), (
        "the object that stopped is not the one whose bytes contradict its name"
    )

    # The PDF is a different state and stays one. Reported, counted, not laundered
    # into the quarantine and not silently skipped.
    pdf = _object_ending(runtime, source_id, "handbook.pdf")
    assert pdf != stopped
    refused = _invoke(
        runtime,
        Capability.SOURCES_FETCH,
        Purpose.CONTENT_EXTRACTION,
        FetchSource(source_id=source_id, source_object_id=pdf, enrollment_id=enrollment_id),
        "quarantine-pdf",
    )
    assert refused.error is not None and refused.error.code == ErrorCode.UNSUPPORTED

    # --- freshness and trust, from the record the executor stored ---------------
    match = _succeeded(
        _invoke(
            runtime,
            Capability.KNOWLEDGE_SEARCH,
            Purpose.KNOWLEDGE_SEARCH,
            SearchKnowledge(enrollment_id=enrollment_id, query=ONLY_IN_NOTES),
            "quarantine-search",
        ),
        "knowledge.search",
    )["matches"][0]

    read = _invoke(
        runtime,
        Capability.KNOWLEDGE_READ,
        Purpose.KNOWLEDGE_READ,
        ReadKnowledge(knowledge_id=match["knowledge_id"], enrollment_id=enrollment_id),
        "quarantine-read",
    )
    record = _succeeded(read, "knowledge.read")
    disclosure = read.disclosure
    assert disclosure is not None

    assert record["provenance"]["observed_at"] == _modified(corpus / "notes.md"), (
        "the stored observation is not the object's own modification time. One "
        "filesystem fact is traced here through the provider, the `extractions` "
        "row, and the answer; a request clock in its place would break exactly "
        "this and leave the disclosure's own clock passing"
    )
    freshness_at = format_rfc3339(disclosure.freshness.observed_at)
    assert freshness_at >= record["provenance"]["observed_at"], (
        "the request clock preceded the object's observation, which `Provenance` "
        "refuses to construct"
    )
    assert disclosure.freshness.state.value == "current_for_observed_version"

    # Written out rather than imported, and deliberately not read back off
    # `record`: `assert extractor` — the truthiness check this replaces — held
    # for any non-empty string, and the basis comparison below took its expected
    # value from the very row it was checking. Between them they proved the
    # answer was self-consistent and nothing at all about what was stored. The
    # version is asserted because nothing in the suite asserted it anywhere.
    extractor = record["provenance"]["extractor"]
    assert extractor == "my_pa.text"
    assert record["provenance"]["extractor_version"] == "1"
    assert record["provenance"]["trust_level"] == TrustLevel.SOURCE_BOUND_DERIVED.value
    assert disclosure.trust.level is TrustLevel.SOURCE_BOUND_DERIVED
    assert disclosure.trust.basis == (extractor,), (
        "the disclosed basis is not the extractor the stored row names"
    )

    # The control that makes the trust assertion a measurement rather than a
    # restatement of a constant: the same object, fetched raw, discloses a
    # different level and a different basis in the same test.
    raw = _invoke(
        runtime,
        Capability.SOURCES_FETCH,
        Purpose.SOURCE_INSPECTION,
        FetchSource(
            source_id=source_id,
            source_object_id=record["provenance"]["source_object_id"],
            representation=Representation.RAW_BYTES,
            enrollment_id=enrollment_id,
        ),
        "quarantine-raw",
    )
    assert _succeeded(raw, "sources.fetch (raw_bytes)")["byte_count"] > 0
    assert raw.disclosure is not None
    # Two different levels and two different bases, disclosed for one object in
    # one test. Neither is the constant the layer emits for everything.
    assert raw.disclosure.trust.level is TrustLevel.SOURCE_ORIGINAL
    assert raw.disclosure.trust.basis == ("source_provider",)
    assert raw.disclosure.trust.basis != disclosure.trust.basis


# ---- condition 6: one stored row, two transports -------------------------------


def _wire_document(
    runtime: GatewayRuntime, purpose: Purpose, payload: dict[str, Any], tag: str
) -> dict[str, Any]:
    """One request in the shape every transport carries it."""
    return {
        "request_id": f"req-slice-{tag}",
        "purpose": purpose.value,
        "principal_id": runtime.principal.principal_id,
        "requested_at": "2026-08-03T12:00:00Z",
        "payload": payload,
    }


def _comparable(document: dict[str, Any]) -> dict[str, Any]:
    """The answer with the three fields that vary per request removed, and no others.

    Stated positively — a named list of what varies, with the line that makes it
    vary — rather than as a walk over everything that looks like an identifier.
    `tests/contract/test_transport_parity.py::masked` keeps its own mask for its
    eight-capability sweep over fakes; this is a narrower claim about one
    capability over a real store, and importing that mask would couple an `e2e`
    module to a 924-line FAST contract file.

    * `correlation_id` — minted per request (`service.py::invoke`);
    * `completed_at` — `self._clock()`, read twice per request;
    * `disclosure.freshness.observed_at` — `authorization.at`, the request clock.

    Everything else is compared **literally**, including `request_id`, which the
    request supplied, so a transport answering about a different subject is a
    difference. `result.provenance.observed_at` is compared literally too: it is
    the *object's* modification time and does not vary per request.
    """
    varying = {"correlation_id", "completed_at"}
    body = {key: value for key, value in document.items() if key not in varying}
    disclosure = body.get("disclosure")
    if isinstance(disclosure, dict):
        freshness = disclosure.get("freshness")
        if isinstance(freshness, dict):
            body["disclosure"] = {
                **disclosure,
                "freshness": {
                    key: value for key, value in freshness.items() if key != "observed_at"
                },
            }
    return body


@pytest.mark.database
@pytest.mark.e2e
def test_knowledge_read_answers_identically_over_http_and_mcp_from_one_stored_row(
    runtime: GatewayRuntime, capsys: pytest.CaptureFixture[str]
) -> None:
    """The same stored record, asked for over a real socket and over real JSON-RPC.

    No harness is built. `tests/wire.py::serve` already runs a real uvicorn
    server on a kernel-chosen loopback port, configured from `apps/gateway.py`'s
    own constants, with an `http.client` client so the bytes cross a socket and
    uvicorn's parser both ways; `tests/transports.py::mcp_transport` already runs
    a real JSON-RPC exchange through the SDK's own `ClientSession`. Both take an
    `ApplicationService`, so handing them the disposable-database runtime is what
    turns a fake-backed parity matrix into an end-to-end equivalence over
    PostgreSQL.

    **The preconditions come first, and they are the point.** Two identical
    failures satisfy any equality. So each transport is separately required to
    have answered with the record's real text before the two answers are
    compared at all; the liveness plant for this test is a runtime with no worker
    run, and it must go red *here* rather than on the equality.

    **What this does not prove, at demonstrated capability.** The server runs in
    a thread of this process, not under `apps/gateway.py run`, and the MCP
    session is over memory streams rather than a spawned child. That the
    composition roots serve a *reachable* store is proven separately and against
    a deliberately unreachable one at
    `tests/contract/test_http_gateway_process.py` and
    `tests/contract/test_mcp_transport.py`. The uncovered intersection —
    composition root by reachable store — is named and not closed here.

    Condition 7's `unsupported` and prohibited-disclosure rows ride along,
    because both are about a *transport* and neither needs a second server.
    """
    source_id, root_object_id = _register(capsys)
    accepted = _enroll(runtime, source_id, root_object_id)
    enrollment_id = accepted["enrollment_id"]
    assert _work(runtime) == (1, 1)

    found = _succeeded(
        _invoke(
            runtime,
            Capability.KNOWLEDGE_SEARCH,
            Purpose.KNOWLEDGE_SEARCH,
            SearchKnowledge(enrollment_id=enrollment_id, query=ONLY_IN_NOTES),
            "parity-search",
        ),
        "knowledge.search",
    )["matches"][0]
    markdown = found["source_object_id"]
    pdf = _object_ending(runtime, source_id, "handbook.pdf")

    read_document = _wire_document(
        runtime,
        Purpose.KNOWLEDGE_READ,
        {
            "knowledge_id": found["knowledge_id"],
            "enrollment_id": enrollment_id,
            "metadata_only": False,
        },
        "parity-read",
    )

    with all_transports(runtime.service, runtime.principal) as (http, mcp, cli):
        answers = {
            transport.name: transport.send(Capability.KNOWLEDGE_READ.value, read_document)
            for transport in (http, mcp)
        }

        # --- per transport, before anything is compared -------------------------
        for name, answer in answers.items():
            assert not answer.failed, f"{name} refused the read: {answer.document}"
            assert answer.document["error"] is None, f"{name}: {answer.document['error']}"
            result = answer.document["result"]
            assert result["text"], f"{name} answered with no text"
            assert ONLY_IN_NOTES in result["text"], f"{name} answered about a different record"
            assert result["provenance"]["source_object_id"] == markdown
            assert answer.document["disclosure"] is not None, f"{name} disclosed nothing"

        http_answer, mcp_answer = answers["http"], answers["mcp"]

        # The three excluded fields are asserted to be present and to vary, so the
        # exclusion below is a measurement rather than a convenience.
        assert http_answer.document["correlation_id"] != mcp_answer.document["correlation_id"], (
            "the two requests share a correlation identifier, so nothing was minted per request"
        )
        for answer in (http_answer, mcp_answer):
            assert answer.document["completed_at"]
            assert answer.document["disclosure"]["freshness"]["observed_at"]

        assert _comparable(http_answer.document) == _comparable(mcp_answer.document), (
            "HTTP and MCP disagree about a field neither of them invented"
        )

        # --- condition 7: `unsupported`, over a transport, with its control -----
        for name, transport in (("http", http), ("mcp", mcp), ("cli", cli)):
            refused = transport.send(
                Capability.SOURCES_FETCH.value,
                _wire_document(
                    runtime,
                    Purpose.CONTENT_EXTRACTION,
                    {
                        "source_id": source_id,
                        "source_object_id": pdf,
                        "representation": "normalized_text",
                        "enrollment_id": enrollment_id,
                    },
                    "parity-pdf",
                ),
            )
            assert refused.failed, f"{name} served a PDF as text"
            assert refused.document["error"]["code"] == ErrorCode.UNSUPPORTED.value, (
                f"{name} reported the PDF as {refused.document['error']['code']} "
                "rather than `unsupported`; a coerced empty body would be a "
                "defect laundered into a success"
            )

            served = transport.send(
                Capability.SOURCES_FETCH.value,
                _wire_document(
                    runtime,
                    Purpose.CONTENT_EXTRACTION,
                    {
                        "source_id": source_id,
                        "source_object_id": markdown,
                        "representation": "normalized_text",
                        "enrollment_id": enrollment_id,
                    },
                    "parity-markdown",
                ),
            )
            assert not served.failed, f"{name} refused a file it can read"
            assert ONLY_IN_NOTES in served.document["result"]["text"]

            # --- condition 7: prohibited disclosure, over the real values -------
            # Only a real registration puts the resolved root in play, and only a
            # real store puts the database name and the driver in play. The scan
            # covers the status line and every header for HTTP, the whole
            # `CallToolResult` for MCP, and both streams for the CLI.
            for rendered in (refused.rendered, served.rendered):
                assert str(MCV_ROOT.resolve()) not in rendered, f"{name} disclosed the root"
                assert DISPOSABLE_DATABASE not in rendered, f"{name} disclosed the database"
                assert "psycopg" not in rendered, f"{name} disclosed the driver"


# ---- condition 7: a request two grants both cover ------------------------------


@pytest.mark.database
@pytest.mark.e2e
def test_a_request_covered_by_two_enrollments_is_refused_as_ambiguous(
    runtime: GatewayRuntime, capsys: pytest.CaptureFixture[str]
) -> None:
    """`ambiguous_request`, produced by a request rather than constructed by a test.

    `SafeDetail.MULTIPLE_ENROLLMENTS_COVER_THE_SCOPE` is declared in
    `application/errors.py` and raised in `application/service.py::_one_enrollment`,
    and at this head **no test names it**: `AmbiguousRequestError` appears only
    where `tests/security/test_application_redaction.py` constructs the object
    directly and as a string in a taxonomy list. A declared refusal that has
    never fired is the guard-that-cannot-fire shape this campaign keeps
    recording, and the precondition — two grants over one source held by one
    principal — is persisted state a fake could stage but never has.

    The control is in the same test and is what makes the refusal a *choice*
    rather than a failure: the identical fetch, naming one of the two grants,
    succeeds and returns bytes.
    """
    source_id, root_object_id = _register(capsys)
    first = _enroll(runtime, source_id, root_object_id, key="ambiguous-a", tag="ambiguous-a")
    enumerated = _enumerated(runtime, first["enrollment_id"])
    second = _enroll(
        runtime,
        source_id,
        object_ids=enumerated[:1],
        key="ambiguous-b",
        tag="ambiguous-b",
    )
    assert second["created"] is True
    assert second["enrollment_id"] != first["enrollment_id"], (
        "the second request was answered as a retry of the first, so only one "
        "grant exists and the branch under test cannot be reached"
    )

    refused = _invoke(
        runtime,
        Capability.SOURCES_FETCH,
        Purpose.SOURCE_INSPECTION,
        FetchSource(
            source_id=source_id,
            source_object_id=enumerated[0],
            representation=Representation.RAW_BYTES,
        ),
        "ambiguous",
    )
    assert refused.error is not None, (
        "a request covered by two grants was answered under one of them, which "
        "is the guess `_one_enrollment` exists to refuse"
    )
    assert refused.error.code == ErrorCode.AMBIGUOUS_REQUEST
    assert "multiple_enrollments_cover_the_scope" in refused.error.safe_details

    named = _succeeded(
        _invoke(
            runtime,
            Capability.SOURCES_FETCH,
            Purpose.SOURCE_INSPECTION,
            FetchSource(
                source_id=source_id,
                source_object_id=enumerated[0],
                representation=Representation.RAW_BYTES,
                enrollment_id=second["enrollment_id"],
            ),
            "ambiguous-named",
        ),
        "sources.fetch naming one of the two grants",
    )
    assert named["byte_count"] > 0, (
        "the refusal above is only a boundary if the same request naming a grant is answered"
    )
