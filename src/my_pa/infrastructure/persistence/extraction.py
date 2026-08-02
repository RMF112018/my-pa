"""Persisting extraction outcomes, quarantines, and aggregate limitations.

Every function takes a `Connection` and the caller owns the transaction, as
everywhere else in this package: these are the statements, not the unit of work,
so an enrollment's whole pass commits together rather than once per object.

**No outcome can be dropped on the way in.** `record_outcome` accepts any
`ExtractionOutcome` and routes it — extracted and unsupported become a row in
`extractions`, quarantined becomes a row in `quarantine_records`. A caller
therefore cannot persist a batch of outcomes and silently lose the quarantines by
filtering for the ones that have text, which is the shape the section 12 rule
against silent skipping is guarding against.

**The payload never reaches the quarantine path.** `quarantine_object` takes
identifiers, a reason, and nothing else; it has no parameter that content could
be passed in, and the table it writes has no column content could be stored in.
The two together are why "quarantine stores IDs and safe reason codes, not
payloads" is a property of the code rather than a promise about how it is called.

**An enrollment authorizes in two dimensions, and both are enforced.** Section
9.6 makes an enrollment request a selector *and* a content-type allowlist, so
"what this enrollment authorizes" is two stored facts and not one:
`enrollments.object_ids` with `enrollments.source_id`, and
`enrollments.media_types`. `authorized_object` is the whole of the first and
`authorized_media_type` is the whole of the second. Neither is a definition of
the other, and this module said for five review rounds that the first was the
only one, which is how the second went unenforced everywhere.

**The object dimension.** Filtering by `enrollment_id` alone is not an
authorization boundary: nothing in the schema ties an outcome's
`source_object_id` to the objects its enrollment named, so a row written for any
object at all would be counted and returned as if it were in scope.
`authorized_object` is an object of the enrollment's own source, and, where the
enrollment named its objects, one of those. It is applied by every count in
`coverage_for` and by the search predicate that reads the same rows. The write
path refuses the same objects through `UnauthorizedObjectError`.

**The content dimension, and exactly how far it reaches.** The allowlist governs
*extracted text*: which content types this enrollment authorizes being read out
of an object and stored. So `authorized_media_type` restricts the `processed`
count and `persistence.search`'s match predicate, and `record_outcome` refuses an
extracted outcome whose media type the enrollment did not allow.

It deliberately does not restrict the `unsupported` count, the `quarantined`
count, or `quarantine_object`, and each of those is a decision with a reason
rather than a place it was forgotten:

* An `unsupported` row stores no text — the check constraint tying `text` to
  `status` makes that a property of the table — and it is precisely the
  section 12 report that an object's media type is one this extractor does not
  read. Through `extract_text` such a row's media type is always outside
  `SUPPORTED_MEDIA_TYPES`, so gating this count by the allowlist would erase the
  report for exactly the objects it exists to report, and would leave an
  operator having to allowlist `application/pdf` — authorizing its content — in
  order to be told that PDFs are there.
* A quarantine stores no media type at all: `quarantine_records` has no such
  column and `quarantine_object` has no such parameter, so there is nothing to
  compare. Supplying one from the outcome would be worse than having none. The
  case where a media type is most relevant to a quarantine is
  `MEDIA_TYPE_CONFLICTS_WITH_SIGNATURE`, where the declared type is the fact in
  dispute, and gating on it would let a mislabelled object suppress the record
  that it was mislabelled.

What that costs, stated rather than left to be found: `unsupported` and
`quarantined` can count an object whose content type the enrollment never
allowed. Neither count discloses content, both are counts of objects section
9.2 permits, and a caller whose enumeration filtered by the allowlist while its
writer did not can hand `coverage_for` a denominator its rows no longer fit
inside — which raises, in the direction that fails rather than overclaims.

For an enrollment that named its objects that makes the inconsistent state
impossible to create rather than merely unreported: the set is stored, so both
sides can restrict to it. For an enrollment that named a root it does not. There
is no stored object set for a root, so both sides admit every object of the
enrollment's source, including objects of that source outside the root — the
write path accepts them and the read path counts and returns them. That is a
limit of what the schema knows and not a check that was forgotten;
`authorized_object` says what would close it, and `persistence.search` discloses
it in the envelope rather than leaving a caller to infer it.

The two halves are not redundant. The read side has to hold against rows already
stored, written by hand, or written before the write side existed; the write side
is what stops new ones. Neither would be enough alone.

**Two rules about conditions, stated once and applied to every condition in this
module and in `persistence.search`.** The branch has been blocked repeatedly for
applying a principle at one site and not at its neighbours, so both rules are
written here rather than argued at each occurrence.

*A condition that restricts rows or branches on derived state, and that no
arrangement of rows can make decide anything, is removed.* It is not defence in
depth; it is a claim nothing checks, and this package has now been wrong in that
direction more than once. The rule is why the boundary is absent from the two
precedence subqueries in `coverage_for`, why `persistence.search` no longer tests
`eligible > 0` before claiming complete coverage, and why `match_statement` no
longer filters on `status`. The single exception is a condition the type checker
requires in order to narrow a value: `record_outcome`'s missing-reason check is
one, and it is written as the narrowing it is and says so where it stands.

*Every identifier crossing a public boundary of this module is validated at that
boundary, before anything else, whether or not a callee would reject it too.*
Two of those calls are behaviourally undecidable, and they are the two that
`authorized_object` reaches: it validates the enrollment identifier that
`record_outcome` and `quarantine_object` have already validated, so deleting
either raises the identical error from a few lines further in. They are kept
anyway, because the rule above is about conditions that decide *rows* and this
one is about a function's precondition. Removing the duplicates would make each
function's precondition a property of which callee it happens to reach, which
is the opposite of a checkable claim; keeping them uniformly means a reader never
has to trace one. Which of the two rules a condition falls under is decided by
what the condition is for, not by whether a test happens to reach it.

**Coverage is read for a stated enrollment and snapshot.** `coverage_for` counts
what this schema stores and requires the caller to state what it does not: the
eligible total, and any queued or unavailable counts. That asymmetry is
deliberate. Only the layer that enumerated the scope knows how many objects were
eligible, and deriving the denominator from the rows that happen to exist would
report complete coverage of a scope nobody measured — exactly the global
inference section 12 forbids.

A caller that never enumerated the scope says so, with `eligible=None`, and the
total is then derived from what was accounted for. That is the same arithmetic
the paragraph above rejects, and it is admissible only because it is *stated*:
`None` is a caller declaring the denominator unmeasured, where an integer is a
caller asserting one. What the two must not share is a coverage *state*, and
`None` is the fact a caller needs to hold the state below any that would claim
the whole scope reached an outcome. The alternative — making a caller invent a
plausible integer and then repair the counts afterwards — is what produced two
defects here already: an invented ceiling can disagree with the stored rows and
crash the read, and a repaired total leaves no record that it was repaired.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Connection, Text, any_, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc, utc_now
from my_pa.domain.extraction.coverage import (
    AggregateLimitation,
    CoverageCounts,
    LimitationReason,
    SnapshotState,
)
from my_pa.domain.extraction.quarantine import (
    QuarantineReason,
    QuarantineRecord,
    QuarantineReviewState,
)
from my_pa.domain.extraction.text import ExtractionOutcome, ExtractionStatus
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence import conflicting_row
from my_pa.infrastructure.persistence.tables import (
    coverage_limitations,
    enrollments,
    extractions,
    quarantine_records,
    source_objects,
)

__all__ = [
    "UnauthorizedObjectError",
    "authorized_media_type",
    "authorized_object",
    "coverage_for",
    "quarantine_object",
    "record_limitation",
    "record_outcome",
]


class UnauthorizedObjectError(Exception):
    """An outcome was offered for an object its enrollment does not authorize.

    Added because nothing else in this module's vocabulary fits. A `ValueError`
    would say the arguments are malformed, and they are not — both identifiers
    passed `validate_identifier` before this was reached. `IsolationLevelError`
    is about a row that vanished. What happened is that the write was refused on
    authorization grounds, and that has to be distinguishable by type, because a
    caller may reasonably quarantine-and-continue on a malformed outcome and must
    not do the same with one it was never entitled to record.

    Carries the two identifiers, and that is a decision rather than a default,
    because this message may reach a log. Both values were supplied by the caller
    in the call being refused, so the message discloses nothing the caller did not
    already hold; both are opaque `enr_…` and `obj_…` identifiers rather than
    locators, names, or media types, so a log line carrying them says which grant
    refused which object and nothing about what either contains. They are also
    the only thing that makes the refusal actionable: a caller persisting a batch
    of outcomes has to know which one was refused, and an error naming neither
    would leave it re-deriving that from the batch.

    The message says which of the two dimensions refused — the object, or its
    content type — and never the media type itself. Which dimension is as
    actionable as which outcome: a caller told only "unauthorized" would not know
    whether to fix the scope it enumerated or the types it extracted. The *value*
    is a different thing and stays out, so the message says no more about the
    enrollment's allowlist than that the type offered was not in it.

    That is the opposite decision from `persistence.search`'s errors, which carry
    nothing at all, and the difference is who receives them. Those cross back to
    whoever asked the question and are classified by section 10; this one goes to
    the writer that already holds both values.

    There is no reason code and no content: this is not a quarantine.
    `test_a_refused_object_names_the_two_identifiers_its_caller_supplied` asserts
    the message rather than leaving this paragraph to be believed.
    """


def authorized_object(
    source_object_id: ColumnElement[Any], *, enrollment_id: str
) -> ColumnElement[bool]:
    """Whether `enrollment_id` authorizes the object `source_object_id` names.

    The one definition of an enrollment's authorized object set, written once and
    used by every read and every write that touches an outcome. Two conditions,
    and each is a fact the schema already stores:

    * The object belongs to the enrollment's own source. True of both selectors.
      A root selector names an object of that source and depth walks within it,
      so no object of another source can be under it; an enrollment naming
      objects is accepted without anything checking they are that source's, which
      is why this is enforced here rather than assumed.
    * Where the enrollment named its objects, the object is one of them.
      `enrollments.object_ids` *is* the authorization for that selector, and
      `enrollment_names_exactly_one_selector` guarantees it is non-empty exactly
      when `root_object_id` is null.

    A root-selector enrollment stores no object set, so there is nothing to
    restrict against and this deliberately does not invent one. What that costs
    is stated plainly because it is larger than it sounds: such an enrollment
    authorizes *its whole source*, root or no root. An object of the same source
    sitting outside the root — a sibling directory, anything the depth walk would
    never have reached — passes this predicate, so it can be written under the
    enrollment, is counted by `coverage_for`, and is returned by a search.

    Containment is not implemented rather than being implemented badly, and the
    reason is that the fact it needs is not stored. `source_objects` holds a
    `native_locator` and a `source_id` and no parent link, so a subtree test
    could only be a prefix comparison over locators, and no provider promises
    that a locator prefix means containment. The object set under a root was
    known to the enumeration that walked it and nothing persists it; there is no
    worker yet that could.

    **What WP-4 should do, once, rather than twice.** Persist the enumerated
    object set at enrollment time. It is one missing fact — which objects are
    under this root — and it closes two things that are currently carried
    separately: this containment gap, because membership would then apply to a
    root selector exactly as it applies to a named one, and the unmeasured
    denominator in `persistence.search`, because the size of that set is the
    eligible total search has no honest number for. Fixing either alone would
    mean building the same persistence twice.

    `correlate_except` rather than SQLAlchemy's automatic correlation, and what
    it buys is stated as narrowly as it is measured. This predicate takes the
    object column as an argument, so its two tables have to be resolved inside
    the subquery whatever the enclosing statement's `FROM` happens to hold.
    Without it SQLAlchemy correlates `source_objects` to an enclosing statement
    that selects from it, and the condition `source_objects.source_object_id ==
    source_object_id` then constrains the *enclosing* row instead of looking the
    argument up — the predicate stops answering about its argument. For
    `match_statement`'s statement in particular the two forms happen to agree,
    because it joins `source_objects` on exactly that equality, so no result
    there can distinguish them; the difference is real for any other enclosing
    statement, and
    `test_the_authorization_predicate_answers_about_its_argument_and_not_the_enclosing_row`
    measures it against one.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    return (
        select(literal(1))
        .where(
            enrollments.c.enrollment_id == enrollment_id,
            source_objects.c.source_object_id == source_object_id,
            source_objects.c.source_id == enrollments.c.source_id,
            or_(
                enrollments.c.root_object_id.is_not(None),
                source_object_id == any_(enrollments.c.object_ids),
            ),
        )
        .correlate_except(enrollments, source_objects)
        .exists()
    )


def authorized_media_type(
    media_type: ColumnElement[Any], *, enrollment_id: str
) -> ColumnElement[bool]:
    """Whether `enrollment_id` allows extracted text of the type `media_type` names.

    The whole of the content dimension, written once and used by the one count
    and the one statement that read stored text. `enrollments.media_types` *is*
    that allowlist: it is `NOT NULL`, `enrollment_allows_some_content_type`
    keeps it non-empty, and `domain.source.enrollment` normalizes every entry to
    a bare lower-case `type/subtype` before it is stored, so the comparison is a
    set membership and not a parse.

    Fails closed in both of the ways it can be asked something it has no answer
    to. A `NULL` media type is not a member of any array — `NULL = ANY(…)` is
    `NULL`, the subquery returns no row, and the predicate is false — so an
    outcome whose type nothing identified is not authorized rather than
    generously admitted. An allowlist naming a type this extractor cannot read
    authorizes no extracted text at all: an extracted row's media type is
    confined to `SUPPORTED_MEDIA_TYPES` by
    `only_a_supported_media_type_is_extracted`, so an enrollment allowing only
    `application/pdf` matches nothing here, and that is the honest answer while
    `P00-OD-003` is open rather than a case to special-case.

    **No `correlate_except`, and that is measured rather than an oversight.**
    `authorized_object` needs one and says why at length: it names two tables, so
    an enclosing statement that selects from either can capture it and the
    predicate stops answering about its argument. This names one. SQLAlchemy will
    not correlate away a subquery's only `FROM` element — it would leave the
    subquery with nothing to select from — so `enrollments` is resolved here
    whatever encloses this, and adding the call changes not one character of the
    compiled SQL. It was compiled both ways against an enclosing statement over
    `enrollments`, which is the case that could distinguish them, and the two are
    byte-identical;
    `test_the_content_type_predicate_resolves_its_own_table_whatever_encloses_it`
    asserts the property the call would have bought. Writing the call anyway
    would be a claim nothing checks, which is the rule this module states once.
    A second table in this predicate would change that, and would need it.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    return (
        select(literal(1))
        .where(
            enrollments.c.enrollment_id == enrollment_id,
            media_type == any_(enrollments.c.media_types),
        )
        .exists()
    )


def _refuse_an_unauthorized_object(
    connection: Connection, *, enrollment_id: str, source_object_id: str
) -> None:
    """Raise unless `enrollment_id` authorizes `source_object_id`.

    One round trip before the write, which is the price of the state being
    impossible rather than merely unreported. The alternative — a foreign key or
    a check constraint — cannot be written: the authorized set for the named
    selector is an array column on another table, and PostgreSQL has no
    constraint that reaches it.
    """
    authorized = connection.execute(
        select(authorized_object(literal(source_object_id, Text), enrollment_id=enrollment_id))
    ).scalar_one()
    if not authorized:
        raise UnauthorizedObjectError(
            f"enrollment {enrollment_id} does not authorize object {source_object_id}"
        )


def _refuse_an_unauthorized_media_type(
    connection: Connection, *, enrollment_id: str, source_object_id: str, media_type: str | None
) -> None:
    """Raise unless `enrollment_id` allows extracted text of type `media_type`.

    A second round trip rather than a second column on the first, so that the
    two dimensions stay two statements a reader can delete one of and watch fail
    separately. The object is checked first because it is the wider refusal: a
    caller told its content type was wrong for an object it was never entitled
    to touch would fix the wrong thing.

    Called only where an outcome would store extracted text. The module
    docstring says why an unsupported row and a quarantine are not its business.
    """
    authorized = connection.execute(
        select(authorized_media_type(literal(media_type, Text), enrollment_id=enrollment_id))
    ).scalar_one()
    if not authorized:
        raise UnauthorizedObjectError(
            f"enrollment {enrollment_id} does not authorize the content type of "
            f"object {source_object_id}"
        )


def record_outcome(
    connection: Connection,
    *,
    enrollment_id: str,
    outcome: ExtractionOutcome,
) -> str:
    """Persist one extraction outcome and return the identifier of its row.

    Idempotent per (enrollment, observed version): re-extracting an unchanged
    object returns the identifier issued the first time rather than accumulating
    rows, because a retry is not new evidence. A changed object has a new
    `ver_…` and therefore a new row, which is what keeps stored text
    attributable to the bytes it came from.

    A quarantined outcome is written to `quarantine_records` instead, and its
    `kn_…` is returned. It is not idempotent there — section 12 makes
    reprocessing an explicit new operation, so a second quarantine is a second
    event.

    Raises `UnauthorizedObjectError` for an object the enrollment does not
    authorize, before anything is written. The check is `authorized_object`'s,
    so an enrollment that named its objects admits only those; one that named a
    root has no stored object set and is restricted by its source alone.

    Raises it again, naming the content type rather than the object, for an
    *extracted* outcome whose media type the enrollment's allowlist does not
    hold. Only for an extracted one: that is the outcome that stores text, which
    is what the allowlist governs, and the module docstring gives the reasons the
    unsupported and quarantined paths are not gated by it.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    provenance = outcome.provenance

    if outcome.status is ExtractionStatus.QUARANTINED:
        reason = outcome.quarantine_reason
        if reason is None:
            # The narrowing `quarantine_object`'s signature requires, and the one
            # exception to this module's rule about unreachable conditions:
            # `ExtractionOutcome` refuses to exist in this state, so no arrangement
            # of arguments reaches the raise, but `quarantine_reason` is
            # `QuarantineReason | None` and the call below takes `QuarantineReason`.
            # A `raise` rather than an `assert` because a quarantine written without
            # its reason would be a record that cannot be reviewed, and because
            # `assert` is not a check under `-O`.
            raise ValueError("a quarantined outcome carries a reason")
        return quarantine_object(
            connection,
            enrollment_id=enrollment_id,
            source_object_id=provenance.source_object_id,
            version_id=provenance.version_id,
            reason=reason,
        ).quarantine_id

    # Checked here rather than at the top of the function so the quarantine path
    # is checked exactly once, by `quarantine_object` itself: it is reachable
    # both through this routing and directly.
    _refuse_an_unauthorized_object(
        connection,
        enrollment_id=enrollment_id,
        source_object_id=provenance.source_object_id,
    )
    if outcome.status is ExtractionStatus.EXTRACTED:
        _refuse_an_unauthorized_media_type(
            connection,
            enrollment_id=enrollment_id,
            source_object_id=provenance.source_object_id,
            media_type=outcome.media_type,
        )

    statement = (
        pg_insert(extractions)
        .values(
            extraction_id=issue_identifier(IdKind.KNOWLEDGE),
            enrollment_id=enrollment_id,
            source_object_id=provenance.source_object_id,
            version_id=provenance.version_id,
            status=outcome.status.value,
            media_type=outcome.media_type,
            extractor=provenance.extractor,
            extractor_version=provenance.extractor_version,
            trust_level=provenance.trust_level.value,
            text=outcome.text,
            is_truncated=outcome.is_truncated,
            observed_at=provenance.observed_at,
            processed_at=provenance.processed_at,
        )
        .on_conflict_do_nothing(constraint="one_extraction_per_version_per_enrollment")
        .returning(extractions.c.extraction_id)
    )
    inserted = connection.execute(statement).scalar_one_or_none()
    if inserted is not None:
        # A round trip saved, not a check, and it is worth saying which: the read
        # below would find this transaction's own row and return the same
        # identifier, so deleting these two lines changes nothing but the cost.
        # Nothing pins it and nothing should — there is no wrong answer to catch.
        return str(inserted)

    # The insert conflicted, so the row exists and was committed by someone
    # else. Reading it here depends on READ COMMITTED taking a fresh snapshot
    # per statement; the package docstring records what a higher isolation level
    # does instead. `conflicting_row` keeps the remaining case — the row deleted
    # between the two statements — from looking like an absent extraction.
    existing = connection.execute(
        select(extractions.c.extraction_id).where(
            extractions.c.enrollment_id == enrollment_id,
            extractions.c.version_id == provenance.version_id,
        )
    ).scalar_one_or_none()
    return str(conflicting_row(existing, "knowledge.extractions"))


def quarantine_object(
    connection: Connection,
    *,
    enrollment_id: str,
    source_object_id: str,
    version_id: str | None,
    reason: QuarantineReason,
) -> QuarantineRecord:
    """Record that processing of one object stopped, and why.

    Takes no content parameter, by design. The only things it can be given are
    opaque identifiers and a closed reason code, so there is nothing a caller
    could hand it that would end up stored, logged, or echoed.

    `version_id` may be `None` when the trigger fired before any version was
    proven — a containment failure at listing time, for instance. Recording a
    version that was never observed would attribute the quarantine to bytes
    nobody saw.

    Raises `UnauthorizedObjectError` for an object outside what the enrollment
    authorizes, and identifier syntax is no longer the whole of what is checked.
    A quarantine for an object the enrollment never named used to be storable,
    and the row it left was counted as coverage of that enrollment's scope. For
    an enrollment that named a root there is no stored object set to check
    against, so only its source is checked; `authorized_object` records why.

    The object is the only dimension checked here, and that is stated rather than
    left implied. A quarantine carries no media type — this function has no such
    parameter and `quarantine_records` has no such column — so there is nothing
    for `authorized_media_type` to compare. Taking one from the caller instead
    would be worse than having none: the quarantine whose media type is most
    load-bearing is `MEDIA_TYPE_CONFLICTS_WITH_SIGNATURE`, where the declared
    type is exactly the fact under dispute, and refusing the record on the
    strength of it would let a mislabelled object suppress the record that it was
    mislabelled.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    validate_identifier(source_object_id, IdKind.SOURCE_OBJECT)
    if version_id is not None:
        validate_identifier(version_id, IdKind.VERSION)
    _refuse_an_unauthorized_object(
        connection, enrollment_id=enrollment_id, source_object_id=source_object_id
    )

    quarantined_at = utc_now()
    quarantine_id = issue_identifier(IdKind.KNOWLEDGE)
    connection.execute(
        quarantine_records.insert().values(
            quarantine_id=quarantine_id,
            enrollment_id=enrollment_id,
            source_object_id=source_object_id,
            version_id=version_id,
            reason=reason.value,
            review_state=QuarantineReviewState.PENDING_REVIEW.value,
            quarantined_at=quarantined_at,
        )
    )
    return QuarantineRecord(
        quarantine_id=quarantine_id,
        enrollment_id=enrollment_id,
        source_object_id=source_object_id,
        version_id=version_id,
        reason=reason,
        review_state=QuarantineReviewState.PENDING_REVIEW,
        quarantined_at=quarantined_at,
    )


def record_limitation(
    connection: Connection,
    *,
    enrollment_id: str,
    observed_at: datetime,
    reason: LimitationReason,
    affected_count: int,
) -> AggregateLimitation:
    """Add `affected_count` objects to one enrollment's limitation for a snapshot.

    Accumulates rather than replaces, and returns the running total. A listing
    that is paginated reports the objects it could not account for page by page,
    and the enrollment's limitation for that pass is the sum of them; a writer
    that overwrote would report only the last page's omissions.

    The count is all that is stored. There is no parameter for which objects were
    affected, because `docs/specs` section 9.2 permits the aggregate in the same
    sentence that forbids the per-object side channel.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    if affected_count < 1:
        raise ValueError("a limitation affects at least one object")
    snapshot = ensure_utc(observed_at)

    statement = (
        pg_insert(coverage_limitations)
        .values(
            limitation_id=issue_identifier(IdKind.KNOWLEDGE),
            enrollment_id=enrollment_id,
            observed_at=snapshot,
            reason=reason.value,
            affected_count=affected_count,
        )
        .on_conflict_do_update(
            constraint="one_limitation_per_reason_per_snapshot",
            set_={
                "affected_count": coverage_limitations.c.affected_count + affected_count,
            },
        )
        .returning(coverage_limitations.c.affected_count)
    )
    total = connection.execute(statement).scalar_one()
    return AggregateLimitation(reason=reason, affected_count=int(total))


def coverage_for(
    connection: Connection,
    enrollment_id: str,
    *,
    observed_at: datetime,
    eligible: int | None,
    queued: int = 0,
    unavailable: int = 0,
    snapshot: SnapshotState = SnapshotState.CURRENT,
) -> CoverageCounts:
    """Report coverage of `enrollment_id` for the snapshot `observed_at` names.

    Outcomes are counted for the whole enrollment and for nothing the enrollment
    does not authorize. That is not the same as "nothing beyond it", and the
    difference is the root selector: `authorized_object` restricts a root-selector
    enrollment to its source and no further, so an object of that source outside
    the root is authorized, and its outcomes are counted here. The counts are then
    of a scope wider than the enrollment's root. `authorized_object` records why
    that cannot be narrowed with what the schema stores and what would close it;
    `persistence.search` discloses it to a caller.

    "For the enrollment" is `authorized_object` and not `enrollment_id` alone:
    an outcome stored against this enrollment for an object it does not
    authorize is not coverage of its scope, and counting it converted a partial
    result into a complete one — with a named-objects enrollment the stray
    outcomes fitted inside the denominator and the read reported
    `processed == eligible` while authorized objects had reached no outcome at
    all. Objects that are authorized and have no outcome stay uncounted, which
    is what leaves the result partial, and that is the direction this must fail
    in.

    `processed` carries the content dimension as well, and only `processed`
    does. It is the count of objects whose *text* was read and stored, so an
    extracted row of a media type the enrollment's allowlist does not hold is not
    coverage of that enrollment either, and it is not counted — it stays
    uncounted rather than moving to another count, which leaves the result
    partial in the same safe direction. `unsupported` and `quarantined` count
    objects whose content was never stored and are deliberately not restricted
    this way; the module docstring gives the reason for each, and
    `test_an_unsupported_object_is_counted_and_not_searchable` and
    `test_an_object_quarantined_and_recorded_unsupported_is_counted_once` are
    what would fail if either acquired the restriction.

    Counted for the whole enrollment rather than for one pass, because that is
    the scope the grant defines and an outcome does not stop being true when the
    next pass starts. Limitations are matched to the snapshot exactly: a
    limitation is a property of one enumeration pass rather than a running total,
    and summing two passes over the same tree would report each omission twice.

    Deliberately not filtered by time. An extraction records when the version it
    read was observed and a quarantine records when processing stopped, which are
    facts about different clocks; comparing either against a snapshot timestamp
    would look like an as-of query and answer a different question depending on
    which table it hit. Where the stored outcomes predate the source's current
    state, that is what `SnapshotState.STALE` is for, and the caller states it
    because only the caller can compare the source against the snapshot.

    Every outcome is counted by distinct object, and the three sets are
    disjoint. Both tables record events rather than states — the quarantine
    ledger is append-only, and `extractions` holds one row per observed version —
    so an object quarantined twice is two rows and one uncovered object, and an
    object with a quarantine on one version and an extraction on another is two
    rows and one object with one outcome. Counting rows would report more
    outcomes than there are objects, and `eligible` is a count of objects, so
    every count beside it has to be one too.

    The precedence is quarantine, then unsupported, then extracted, and it runs
    in that direction because it is the one that cannot overclaim. An object
    with any quarantine row is quarantined and is *not* processed: a later
    success must never hide a quarantine behind it, which is what `INV-PKL-007`
    and threat-model `ABUSE-PKL-008` forbid. For the same reason an object with
    an unsupported row is unsupported even where another version of it was
    extracted. The cost is disclosed rather than hidden: an object quarantined at
    one version and successfully extracted at a later one keeps reporting as
    quarantined, because nothing in these counts orders versions or reads the
    quarantine's review state. That understates coverage, which is the direction
    this can afford; the reverse would be a false claim that the object is
    covered.

    `eligible` is the enumerated total, or `None` from a caller that has no
    enumeration to quote. `None` is not a default and not a convenience: it is
    the caller stating that the denominator was never measured, and the total is
    then the objects this schema can account for — the outcomes counted here plus
    whatever queued and unavailable work the caller declared. A caller passing
    `None` gets a total it must not present as a measured scope; the whole-scope
    coverage states are the claim it has to withhold, because a denominator taken
    from the numerator divides out to all of it whichever outcome dominates.

    Raises `ValueError` — through `CoverageCounts` — when the counts do not fit
    inside an `eligible` the caller supplied. That is the right failure: a scope
    smaller than what was processed within it means the caller's denominator is
    wrong, and reporting coverage from it would be a number that cannot be true.
    It cannot arise from `None`, which is derived to fit exactly.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    moment = ensure_utc(observed_at)

    # The authorization boundary, evaluated per object and applied to every
    # count below. Each is built separately because each restricts a different
    # table's `source_object_id`.
    quarantine_is_authorized = authorized_object(
        quarantine_records.c.source_object_id, enrollment_id=enrollment_id
    )
    extraction_is_authorized = authorized_object(
        extractions.c.source_object_id, enrollment_id=enrollment_id
    )
    # The content dimension, applied to the one count that counts stored text.
    text_is_authorized = authorized_media_type(
        extractions.c.media_type, enrollment_id=enrollment_id
    )

    # The two subqueries are the precedence, written once and subtracted from
    # the counts that rank below them. Neither is executed on its own; each
    # becomes a `NOT IN (SELECT …)` inside a count that has to exclude it.
    #
    # Deliberately without the boundary, which they carried until it was shown to
    # be unreachable. Both are only ever subtracted from a count that already
    # applies `extraction_is_authorized` to `extractions.source_object_id` — the
    # same column the exclusion compares — so the only objects the exclusion can
    # decide anything about are authorized ones, and `authorized_object` is a
    # function of the object and the enrollment alone. An object authorized for
    # the extraction is therefore authorized for its quarantine too, and the case
    # the boundary here was written for — an unauthorized quarantine suppressing
    # an authorized extraction of the same object — cannot exist. Both columns
    # are `NOT NULL`, so `NOT IN` cannot go three-valued and swallow the count
    # either. A predicate no arrangement of rows can exercise is not defence in
    # depth; it is a claim nothing checks, and this module has now been wrong in
    # that direction more than once.
    quarantined_objects = select(quarantine_records.c.source_object_id).where(
        quarantine_records.c.enrollment_id == enrollment_id,
    )
    unsupported_objects = select(extractions.c.source_object_id).where(
        extractions.c.enrollment_id == enrollment_id,
        extractions.c.status == ExtractionStatus.UNSUPPORTED.value,
    )

    quarantined = connection.execute(
        select(func.count(func.distinct(quarantine_records.c.source_object_id))).where(
            quarantine_records.c.enrollment_id == enrollment_id,
            quarantine_is_authorized,
        )
    ).scalar_one()
    unsupported = connection.execute(
        select(func.count(func.distinct(extractions.c.source_object_id))).where(
            extractions.c.enrollment_id == enrollment_id,
            extractions.c.status == ExtractionStatus.UNSUPPORTED.value,
            extraction_is_authorized,
            extractions.c.source_object_id.not_in(quarantined_objects),
        )
    ).scalar_one()
    processed = connection.execute(
        select(func.count(func.distinct(extractions.c.source_object_id))).where(
            extractions.c.enrollment_id == enrollment_id,
            extractions.c.status == ExtractionStatus.EXTRACTED.value,
            extraction_is_authorized,
            text_is_authorized,
            extractions.c.source_object_id.not_in(quarantined_objects),
            extractions.c.source_object_id.not_in(unsupported_objects),
        )
    ).scalar_one()
    limitations = tuple(
        AggregateLimitation(reason=LimitationReason(row[0]), affected_count=int(row[1]))
        for row in connection.execute(
            select(coverage_limitations.c.reason, coverage_limitations.c.affected_count).where(
                coverage_limitations.c.enrollment_id == enrollment_id,
                coverage_limitations.c.observed_at == moment,
            )
        )
    )

    if eligible is None:
        # The caller has no enumeration, so the total is what is accounted for
        # and nothing is invented on top of it. `queued` and `unavailable` are
        # included because they are objects the caller already knows about:
        # leaving them out would build a total smaller than the counts beside it
        # and raise from `CoverageCounts`, which is the crash this branch exists
        # to remove rather than relocate.
        eligible = int(processed) + int(quarantined) + int(unsupported) + unavailable + queued

    return CoverageCounts(
        observed_at=moment,
        enrollment_id=enrollment_id,
        eligible=eligible,
        queued=queued,
        processed=int(processed),
        quarantined=int(quarantined),
        unsupported=int(unsupported),
        unavailable=unavailable,
        limitations=limitations,
        snapshot=snapshot,
    )
