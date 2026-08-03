"""The whole read-only slice, and the one identifier that has to survive it.

This is acceptance criterion 7, and it is the criterion this package exists to
make provable. `sources.fetch` resolves a `source_object_id` in **provider
memory**; `knowledge.read` resolves one in the **database**. Before this package
the two spaces never met, and a mismatch between them is silent: empty coverage,
empty search, no exception anywhere. A test that only proved "nothing raised"
would pass on a build where nothing worked, so **every assertion below is on a
non-empty value**, and the one count that is legitimately zero (`quarantined`)
sits beside three non-zero counts in the same assertion block.

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

The corpus is `fixtures/mcv/root`, which is synthetic, in-repo, and never
written to. No live source is reached, no network is used, and the database is a
disposable one this module creates and drops.
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

from my_pa.application.commands import (
    Command,
    EnrollSource,
    FetchSource,
    GetSourceStatus,
    ReadKnowledge,
    Representation,
    SearchKnowledge,
)
from my_pa.bootstrap.gateway import GatewayRuntime, build_gateway_runtime
from my_pa.bootstrap.settings import ENV_PREFIX, Settings, load_settings
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.extraction.coverage import CoverageState
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
            connection.execute(text("TRUNCATE knowledge.audit_events"))
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


def _register(capsys: pytest.CaptureFixture[str]) -> tuple[str, str]:
    """Run the operator command and read back the two identifiers it issues.

    Parsed from the command's own stdout rather than from a second query,
    because what has to be true is that an operator running this command can
    reach the rest of the product with what it printed.
    """
    status = registration.main(
        [
            "register",
            "--provider",
            "fixture",
            "--root",
            str(MCV_ROOT),
            "--label",
            "MCV synthetic corpus",
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
    assert str(MCV_ROOT.resolve()) not in printed, "the configured root reached stdout"
    return source_id, root_object_id


def _enroll(runtime: GatewayRuntime, source_id: str, root_object_id: str) -> dict[str, Any]:
    envelope = _invoke(
        runtime,
        Capability.SOURCES_ENROLL,
        Purpose.BOUNDED_ENROLLMENT,
        EnrollSource(
            source_id=source_id,
            media_types=("text/markdown", "text/plain"),
            idempotency_key="vertical-slice-1",
            root_object_id=root_object_id,
            depth=0,
            max_items=100,
            max_bytes=1 << 16,
        ),
        "enroll",
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


def _work(runtime: GatewayRuntime) -> tuple[int, int]:
    run = run_worker(
        runtime.work_engine,
        owner=issue_worker_owner(),
        handler=extract_enrollment,
        stop=threading.Event(),
        max_iterations=1,
    )
    return run.claimed, run.completed


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
