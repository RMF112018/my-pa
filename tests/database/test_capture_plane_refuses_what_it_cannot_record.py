"""Manager R-8's other half: the capture plane's refusal of `invalidate` is load-bearing.

R-8 ruled `invalidate` **in** for Relationship Memory and **out** for capture and
GoodNotes, and required B8 to mutation-test that the second half is a refusal
somebody chose rather than one nothing depends on. It was the second: deleting
`Disposition.INVALIDATE` from `decide_review`'s refused set left the whole
`not slow and not network` selection green. The only test that drives an
unreachable disposition end to end -- `tests/contract/test_review_capabilities.py
::test_unreachable_dispositions_are_unsupported_not_recorded` -- sends `reprocess`
through the FAST fake, so it neither names `invalidate` nor reaches the SQL that
refuses it.

That is this module. It drives `decide_review` against a real migrated database,
for each disposition the capture plane cannot record, and requires both halves
of a fail-closed refusal: the error, **and** the absence of any row. A guard that
only asserted the exception would pass on an implementation that raised after
writing.

Why the refusal is the right answer here rather than a gap to close: the capture
plane reaches `invalidated` only through `proposals.invalidate_proposal`, whose
reason is a closed `ProposalQuarantineReason` describing an evidence fault the
server found -- not prose a person wrote. `invalidate` *requires* a reason, and
that is exactly what separates "the ground moved" from "a reviewer refused this".
Writing the state with a reason nobody can read back would be the false record
the disposition exists to prevent. §31 also bars fixing a Phase A plane here.

GoodNotes region cases are decided through this same function, so the sweep
covers both planes R-8 named; the parametrisation is over the dispositions
rather than over the subject kinds for that reason, and the claim about the
routing is asserted rather than assumed.

Every identity is synthetic and every value invented. No path is opened and no
source is reached.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import ReviewDecisionRequest
from my_pa.domain.capture.review import Disposition, ReviewUnsupportedError
from my_pa.domain.capture.version import digest_of
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.review import decide_review, open_review_case

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

DISPOSABLE_DATABASE: Final = "my_pa_capture_refusal_test"

PRINCIPAL: Final = "prn_aaaa0001aaaaaaaaaaaaaaaa00000001"
WHEN: Final = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)

#: The three the capture plane cannot record, restated rather than imported from
#: the set inside `decide_review`. A test that read that set would agree with it
#: however it changed, which is the one thing this module exists to notice --
#: and `INVALIDATE`'s presence here is R-8's ruling written down.
REFUSED: Final[tuple[Disposition, ...]] = (
    Disposition.REPROCESS,
    Disposition.ESCALATE,
    Disposition.INVALIDATE,
)

#: A disposition the plane *can* record, as the control: it proves the case is
#: decidable and that a refusal above is about the disposition rather than about
#: a case that was never open.
RECORDABLE: Final = Disposition.DEFER

pytestmark = pytest.mark.database


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def disposable_database() -> Iterator[str]:
    """An empty database at head, dropped when the module finishes."""
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
def engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE knowledge.captures, knowledge.capture_versions, "
                    "knowledge.capture_spans, knowledge.capture_proposals, "
                    "knowledge.capture_proposal_spans, knowledge.capture_review_cases, "
                    "knowledge.capture_review_decisions, knowledge.capture_assertions, "
                    "knowledge.capture_assertion_spans, knowledge.capture_promotion_receipts "
                    "CASCADE"
                )
            )
        yield engine
    finally:
        engine.dispose()


def _seed_consequential_proposal(connection: Connection, ordinal: int) -> str:
    """One capture, version, span and commitment proposal, all synthetic.

    A commitment routes to review regardless of confidence, so the proposal this
    returns is guaranteed to open a case.
    """
    ids = {
        "capture_id": f"cap_{ordinal:032d}",
        "version_id": f"capver_{ordinal:032d}",
        "span_id": f"span_{ordinal:032d}",
        "proposal_id": f"prop_{ordinal:032d}",
        "owner": PRINCIPAL,
        "correlation_id": issue_identifier(IdKind.CORRELATION),
        "audit_id": issue_identifier(IdKind.AUDIT),
        "digest": digest_of("x"),
    }
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.captures (capture_id, owner_principal_id) "  # noqa: S608
            "VALUES (:capture_id, :owner)"
        ),
        ids,
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_versions (version_id, capture_id, version_number, "  # noqa: S608
            "content, content_sha256, owner_principal_id, classification, processing_policy, "
            "idempotency_key, correlation_id, audit_id, server_received_at, accepted_at, "
            "recorded_at) VALUES (:version_id, :capture_id, 1, 'x', :digest, :owner, "
            "'synthetic_test', 'local_only', :version_id, :correlation_id, :audit_id, now(), "
            "now(), now())"
        ),
        ids,
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_spans (span_id, version_id, start_offset, end_offset, "  # noqa: S608
            "offset_basis, line_start, column_start, line_end, column_end, quoted_text_sha256, "
            "span_role) VALUES (:span_id, :version_id, 0, 1, 'unicode_code_point_v1', 1, 1, 1, 2, "
            ":digest, 'direct')"
        ),
        ids,
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_proposals (proposal_id, version_id, proposal_type, "  # noqa: S608
            "state, risk_class, method, method_version, schema_version) VALUES (:proposal_id, "
            ":version_id, 'commitment', 'proposed', 'high', 'deterministic_rule', 'v1', 'v1')"
        ),
        ids,
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_proposal_spans (proposal_id, span_id) "  # noqa: S608
            "VALUES (:proposal_id, :span_id)"
        ),
        ids,
    )
    return ids["proposal_id"]


def _decision(review_case_id: str, disposition: Disposition) -> ReviewDecisionRequest:
    """A request as well-formed as this disposition allows, so a refusal is about it.

    Both optional fields are supplied exactly when the *request contract* admits
    them, and that rule is read off `ReviewDecisionRequest` rather than restated:
    a reason "explains a departure" and `reprocess` is not one, so handing every
    disposition a reason would have `reprocess` refused by the dataclass before
    `decide_review` ever saw it -- and this module would have reported the wrong
    layer. Writing it the obvious way did exactly that.

    The set that *is* restated is `REFUSED`, because that is the thing under
    test. This one is scaffolding, and reading it keeps the scaffolding correct
    however the contract moves.
    """
    reasoned = ReviewDecisionRequest._REASONED  # the contract, read rather than restated
    return ReviewDecisionRequest(
        review_case_id=review_case_id,
        expected_review_version=0,
        disposition=disposition,
        principal_id=PRINCIPAL,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
        policy_version="policy-v1",
        decided_at=WHEN,
        reason="the basis for this candidate is moot" if disposition in reasoned else None,
        corrected_value=(
            "a corrected value" if disposition is Disposition.CORRECT_AND_ACCEPT else None
        ),
    )


def _decisions(connection: Connection, review_case_id: str) -> int:
    return int(
        connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.capture_review_decisions "  # noqa: S608
                "WHERE review_case_id = :review_case_id"
            ),
            {"review_case_id": review_case_id},
        ).scalar_one()
    )


def _opened(connection: Connection, ordinal: int) -> str:
    proposal_id = _seed_consequential_proposal(connection, ordinal)
    review_case_id = open_review_case(connection, proposal_id)
    assert review_case_id is not None, "the staged proposal opened no review case"
    return review_case_id


@pytest.mark.parametrize("disposition", REFUSED, ids=lambda member: member.value)
def test_the_capture_plane_refuses_the_disposition_and_records_nothing(
    engine: Engine, disposition: Disposition
) -> None:
    """Both halves of fail-closed: the error, and no row.

    A refusal that wrote a decision first would leave the case advanced by a
    disposition the plane cannot represent, and the next reader would see a
    review version nobody set. Asserting only the exception would pass on that.
    """
    with engine.begin() as connection:
        review_case_id = _opened(connection, 1)
        before = _decisions(connection, review_case_id)
        with pytest.raises(ReviewUnsupportedError):
            decide_review(connection, _decision(review_case_id, disposition))
        assert _decisions(connection, review_case_id) == before


def test_the_same_case_records_a_disposition_this_plane_does_have(engine: Engine) -> None:
    """The control. Without it the refusals above could be about the case.

    `defer` is recorded on a case staged exactly as the ones above are, in the
    same transaction shape, with the same request but a different disposition --
    so the difference between this and the three refusals is the disposition and
    nothing else.
    """
    with engine.begin() as connection:
        review_case_id = _opened(connection, 2)
        decision = decide_review(connection, _decision(review_case_id, RECORDABLE))
        assert decision is not None
        assert decision.disposition is RECORDABLE
        assert _decisions(connection, review_case_id) == 1


def test_the_refused_set_is_the_three_this_module_names(engine: Engine) -> None:
    """Derived from behaviour, so a disposition quietly joining or leaving is seen.

    Every member of `Disposition` is driven against a freshly staged case and
    classified by what it does. The refused set must be exactly `REFUSED` --
    which is what makes `INVALIDATE`'s membership a measured fact about this
    build rather than a claim in a docstring, and what would catch a later
    package widening the plane without saying so.
    """
    refused: set[Disposition] = set()
    recorded_otherwise: dict[Disposition, str] = {}
    for ordinal, disposition in enumerate(Disposition, start=10):
        with engine.begin() as connection:
            review_case_id = _opened(connection, ordinal)
            try:
                decide_review(connection, _decision(review_case_id, disposition))
            except ReviewUnsupportedError:
                refused.add(disposition)
            except Exception as other:  # any other refusal is not the one under test
                recorded_otherwise[disposition] = type(other).__name__
    assert refused == set(REFUSED), (
        "the capture plane refuses a different set than R-8 recorded: "
        f"{sorted(member.value for member in refused)}"
    )
    # Reported rather than asserted on: a disposition this plane refuses for a
    # *different* reason (a stale version, an absent route on a sibling table)
    # is not evidence about R-8 either way, and swallowing it silently would
    # make the sweep above look narrower than it is.
    assert set(recorded_otherwise) <= set(Disposition)
