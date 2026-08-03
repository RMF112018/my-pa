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
`knowledge.enrollment_objects` with `enrollments.source_id`, and
`enrollments.media_types`. `authorized_object` is the whole of the first and
`authorized_media_type` is the whole of the second. Neither is a definition of
the other, and this module said for five review rounds that the first was the
only one, which is how the second went unenforced everywhere.

**The object dimension.** Filtering by `enrollment_id` alone is not an
authorization boundary: nothing in `extractions` ties an outcome's
`source_object_id` to the objects its enrollment holds, so a row written for any
object at all would be counted and returned as if it were in scope.
`authorized_object` is a row of `enrollment_objects` for this enrollment, whose
object belongs to the enrollment's own source. It is applied by every count in
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

That makes the inconsistent state impossible to create rather than merely
unreported, and it is now true of both selectors rather than of one:
`enrollment_objects` stores the set for a root exactly as it stores the set for
a named list, so both sides restrict to it. The gap this paragraph used to
record — a root selector authorizing its whole source, including objects
outside the root — is closed by that one stored fact, and nothing here
discloses it any more because there is nothing left to disclose.

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
direction more than once. The rule is why the boundary is absent from
`_quarantined_objects` and `_unsupported_objects`, why `persistence.search` no
longer tests `eligible > 0` before claiming complete coverage, and why it no
longer tests that a truncated page is non-empty before issuing a cursor. It is
about a condition written at a site to decide there, which is why the `status`
test inside `extracted_text_in_scope` is not one: that list is written once and
used twice, `status` decides at one of the two uses, and dropping it from the
other would mean two lists again. The single exception is a condition the type checker
requires in order to narrow a value: `record_outcome`'s missing-reason check is
one, and it is written as the narrowing it is and says so where it stands.

*Every identifier crossing a public boundary of this module is validated at that
boundary, before anything else, whether or not a callee would reject it too.*
Three of those calls are behaviourally undecidable, and they are the three that
`authorized_object` reaches: it validates the enrollment identifier that
`record_outcome`, `quarantine_object`, and `extracted_text_in_scope` have already
validated, so deleting any raises the identical error from a few lines further
in. They are kept anyway, because the rule above is about conditions that decide
*rows* and this one is about a function's precondition. Removing the duplicates
would make each function's precondition a property of which callee it happens to
reach, which is the opposite of a checkable claim; keeping them uniformly means
a reader never has to trace one. Which of the two rules a condition falls under
is decided by what the condition is for, not by whether a test happens to reach
it.

**Coverage is read for a stated enrollment and snapshot, denominator included.**
`coverage_for` takes no `eligible` argument. It reads the denominator from
`enrollment_objects` in the same function, from the same schema, on the same
connection as the numerator, because the enumeration that measured the scope now
persists what it found. That is not the global inference section 12 forbids: the
total is a stored count of *this* enrollment's objects, measured once at
acceptance, and not an arithmetic identity derived from whichever outcomes
happen to exist.

The parameter was removed rather than defaulted. It used to accept `None` from a
caller with no enumeration to quote, and the total was then derived from what had
been accounted for — a number every whole-scope state divides out of, which is
why two disclosure tokens and a state clamp existed in two layers to stop it
being read as a measurement. `record_scope` refuses an empty set and rolls the
accepting transaction back with it, so an accepted enrollment holds at least one
object and there is no instant at which the denominator is unmeasured. Leaving
`eligible: int | None = None` in place with the new meaning would have changed
what `None` asserts without changing a call site, which is the same class of
defect as the one being removed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Connection, Select, Text, any_, func, literal, select
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
from my_pa.infrastructure.persistence.enrollment import enrolled_object_count
from my_pa.infrastructure.persistence.tables import (
    coverage_limitations,
    enrollment_objects,
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
    "extracted_text_in_scope",
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
    and each is a fact the schema stores:

    * The object is in this enrollment's enumerated set —
      `knowledge.enrollment_objects` holds a row for the pair. **This applies to
      a root selector exactly as it applies to a named one**, which is the whole
      of what the new table bought. The enumeration that walked the root at
      acceptance recorded what it found, and `record_scope` refuses an empty set,
      so every accepted enrollment has a set to be a member of.
    * The object belongs to the enrollment's own source.

    The second is not implied by the first, and that is why it is still written.
    `enrollment_objects.source_object_id` references `source_objects` and
    `enrollments.source_id` references `sources`, and no constraint in the schema
    relates the two, so a row inserted by hand can name an object of another
    source. `record_scope` refuses to write one — but the read side has to hold
    against rows already stored, written by hand, or written before that writer
    existed, which is the division this module's docstring states.

    What this predicate used to say, and no longer has to: that a root-selector
    enrollment authorized its *whole source*, because nothing persisted the
    object set under a root. An object of the same source outside the root passed
    it, was counted by `coverage_for`, and was returned by a search, and
    `persistence.search` carried two disclosure tokens describing it. There is
    now one membership test for both selectors, so there is no wider scope to
    disclose and no clamp to hold a state down.

    `correlate_except` rather than SQLAlchemy's automatic correlation, and what
    it buys is stated as narrowly as it is measured. This predicate takes the
    object column as an argument, so its tables have to be resolved inside the
    subquery whatever the enclosing statement's `FROM` happens to hold. Without
    it SQLAlchemy correlates `source_objects` — or `extractions`, through the
    column it is handed — to an enclosing statement that selects from the same
    table, and the condition then constrains the *enclosing* row instead of
    looking the argument up, so the predicate stops answering about its argument.
    For `match_statement`'s statement in particular the two forms happen to
    agree, because it joins `source_objects` on exactly that equality, so no
    result there can distinguish them; the difference is real for any other
    enclosing statement, and
    `test_the_authorization_predicate_answers_about_its_argument_and_not_the_enclosing_row`
    measures it against one.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    return (
        select(literal(1))
        .where(
            enrollment_objects.c.enrollment_id == enrollment_id,
            enrollment_objects.c.source_object_id == source_object_id,
            enrollments.c.enrollment_id == enrollment_objects.c.enrollment_id,
            source_objects.c.source_object_id == enrollment_objects.c.source_object_id,
            source_objects.c.source_id == enrollments.c.source_id,
        )
        .correlate_except(enrollment_objects, enrollments, source_objects)
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

    `correlate_except`, for the same reason `authorized_object` has one, and the
    argument is why. This subquery writes one table, but the column handed to it
    brings another: both read call sites pass `extractions.media_type`, so the
    subquery's `FROM` is `enrollments` and `extractions`, and correlating the
    second away to the enclosing statement is what makes the predicate answer
    about the row being counted or returned. The one that must *not* be
    correlated away is `enrollments`, and whether SQLAlchemy does it depends on
    what encloses the predicate rather than on how many tables it names. Compiled
    in all four combinations of argument and enclosing statement:

    * a literal argument, or `extractions.media_type` inside a statement that
      selects from `extractions` — which is `coverage_for`'s shape and
      `match_statement`'s — and the SQL is identical with the call and without
      it, so neither shipped call site can distinguish them today;
    * `extractions.media_type` inside a statement that selects from
      `enrollments` and not from `extractions`, and the two differ. Without the
      call SQLAlchemy correlates `enrollments` away, leaving `FROM
      knowledge.extractions` alone, and `enrollments.enrollment_id = …` then
      binds the *enclosing* row — the predicate stops answering about the
      enrollment it was given, exactly as `authorized_object`'s docstring warns.

    So this is the case the call is for, and it is what
    `test_the_content_type_predicate_answers_about_its_argument_and_not_the_enclosing_row`
    builds, with rows rather than with compiled text: uncorrelated the predicate
    is a constant for the whole statement and every enrollment of the source is
    returned; correlated it collapses to the one the argument names. The claim
    that stood here before — that this predicate names one table, that
    SQLAlchemy will not correlate away a subquery's only `FROM`, and that adding
    the call changes not one character — was true of the argument form the test
    passed and false of the form both call sites pass.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    return (
        select(literal(1))
        .where(
            enrollments.c.enrollment_id == enrollment_id,
            media_type == any_(enrollments.c.media_types),
        )
        .correlate_except(enrollments)
        .exists()
    )


def _quarantined_objects(enrollment_id: str) -> Select[Any]:
    """The objects `enrollment_id` holds a quarantine for, as a subquery.

    Never executed on its own; it becomes a `NOT IN (SELECT …)` inside a count or
    a page that has to exclude what a quarantine outranks.

    Deliberately without the authorization boundary, which it carried until that
    was shown to be unreachable. Every statement that subtracts it already applies
    `authorized_object` to `extractions.source_object_id` — the same column the
    exclusion compares — so the only objects it can decide anything about are
    authorized ones, and `authorized_object` is a function of the object and the
    enrollment alone. An object authorized for the extraction is therefore
    authorized for its quarantine too, and the case the boundary here was written
    for — an unauthorized quarantine suppressing an authorized extraction of the
    same object — cannot exist. Both columns are `NOT NULL`, so `NOT IN` cannot go
    three-valued and swallow the caller either.
    """
    return select(quarantine_records.c.source_object_id).where(
        quarantine_records.c.enrollment_id == enrollment_id,
    )


def _unsupported_objects(enrollment_id: str) -> Select[Any]:
    """The objects `enrollment_id` recorded an unsupported outcome for, as a subquery.

    The second half of the precedence, on the same terms as `_quarantined_objects`
    and without the boundary for the same reason.
    """
    return select(extractions.c.source_object_id).where(
        extractions.c.enrollment_id == enrollment_id,
        extractions.c.status == ExtractionStatus.UNSUPPORTED.value,
    )


def extracted_text_in_scope(enrollment_id: str) -> tuple[ColumnElement[bool], ...]:
    """Which rows of `extractions` hold text that `enrollment_id`'s grant covers.

    One list, used by `coverage_for`'s `processed` count and by
    `persistence.search`'s `match_statement`. When evaluated against one
    statement snapshot, the two apply the same predicate set because they are
    built from this call and not because two predicate lists were compared and
    found to agree. That comparison stood here for six review rounds and was
    false for two of the six conditions. A page of text beside a coverage report
    that says the scope
    holds none of it is the exact contradiction section 9.7 makes this system's
    reason for existing; differing predicates are one way to reach it, and the
    separate-snapshot window described below is another.

    The six, and what each decides:

    * `enrollment_id`, which is not authorization — it says which grant a row was
      written under — and is not removable either, because two enrollments over
      one source can authorize the same object and neither should read the
      other's rows;
      `test_a_search_returns_only_the_rows_its_own_enrollment_wrote` holds all of
      that constant except the enrollment.
    * `status`, which decides in the count and cannot decide in the page:
      `text_exists_exactly_when_something_was_extracted` makes `text` null for
      every other status, `to_tsvector` of null is null, and `null @@ query` is
      null, so `match_statement`'s match predicate already excludes those rows.
      It stays because this is one list rather than two asserted to be equal, and
      dropping a condition from one side is precisely the divergence this exists
      to prevent. That is the edge of this module's rule about conditions nothing
      can exercise: the rule is about a condition written at a site to decide
      there, and this one is written once, where it decides —
      `test_a_row_filed_in_extractions_as_quarantined_is_not_counted_as_processed`
      is what fails if it goes.
    * `authorized_object` and `authorized_media_type`, the two dimensions of what
      the enrollment authorizes, applied to the object and to the stored text.
    * the two precedence exclusions. An object with any quarantine row is
      quarantined and an object with an unsupported row is unsupported, and
      neither is processed however successfully another version of it was read —
      `INV-PKL-007` and `ABUSE-PKL-008` are why a later success must never hide a
      quarantine. Applying them here rather than only to the count is what stops
      a search from returning the text of an object the coverage beside it
      reports as stopped.

    The cost is `coverage_for`'s and is unchanged by sharing it: an object
    quarantined at one version and extracted at a later one is reported
    quarantined and its text is not returned, because nothing in these counts
    orders versions or reads the quarantine's review state. That understates
    coverage, which is the direction this can afford.

    What is *not* shared, and cannot be: `coverage_for` counts distinct objects
    and a search returns rows, so an object with two authorized extracted
    versions is one processed object and two matches. Within one statement
    snapshot, the two agree about which rows are in scope. Search's page and
    coverage reads use separate READ COMMITTED snapshots, so a quarantine
    committed between them can still make the later coverage contradict the
    page; that cross-statement window is carried to WP-4. The two statements do
    not agree about how many things that is, and no arithmetic here claims they
    do.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    return (
        extractions.c.enrollment_id == enrollment_id,
        extractions.c.status == ExtractionStatus.EXTRACTED.value,
        authorized_object(extractions.c.source_object_id, enrollment_id=enrollment_id),
        authorized_media_type(extractions.c.media_type, enrollment_id=enrollment_id),
        extractions.c.source_object_id.not_in(_quarantined_objects(enrollment_id)),
        extractions.c.source_object_id.not_in(_unsupported_objects(enrollment_id)),
    )


def _refuse_an_unauthorized_object(
    connection: Connection, *, enrollment_id: str, source_object_id: str
) -> None:
    """Raise unless `enrollment_id` authorizes `source_object_id`.

    One round trip before the write, which is the price of the state being
    impossible rather than merely unreported. The alternative — a foreign key
    from `extractions` to `enrollment_objects` — would need `(enrollment_id,
    source_object_id)` to reference that table's composite primary key, and it
    would make an outcome undeletable-in-place rather than refused: the
    constraint fires at insert with a driver message rather than with the typed
    refusal a caller persisting a batch has to act on, and `quarantine_records`
    would need the same pair for the same reason. It is one statement here
    against two constraints and a translation there.
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
    so an enrollment admits exactly the objects its enumeration recorded —
    whichever selector it named.

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
    A quarantine for an object the enrollment never held used to be storable, and
    the row it left was counted as coverage of that enrollment's scope. The check
    is `authorized_object`'s and applies to both selectors alike.

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
    queued: int = 0,
    unavailable: int = 0,
    snapshot: SnapshotState = SnapshotState.CURRENT,
) -> CoverageCounts:
    """Report coverage of `enrollment_id` for the snapshot `observed_at` names.

    Outcomes are counted for the whole enrollment and for nothing the enrollment
    does not authorize, and that now *is* the same as "nothing beyond it".
    `authorized_object` is membership of `enrollment_objects`, which the
    enumeration wrote for a root selector exactly as for a named one, so an
    object of the same source outside the root is not authorized and its outcomes
    are not counted. The scope these counts describe is the enrollment's scope.

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
    does — it is `extracted_text_in_scope`, which is also what a search matches
    within. When evaluated against one statement snapshot, the two describe one
    set of rows. It is the count of objects whose *text* was read and stored, so
    an extracted row of a media type the
    enrollment's allowlist does not hold is not coverage of that enrollment
    either, and it is not counted — it stays uncounted rather than moving to
    another count, which leaves the result partial in the same safe direction.

    `unsupported` and `quarantined` count objects whose content was never stored
    and are deliberately not restricted this way, and the two halves of that are
    not the same kind of decision. `unsupported` *could* carry the restriction
    and must not: `test_an_unsupported_object_is_counted_and_not_searchable`
    fails if it acquires one, because the count would erase the report of exactly
    the media types the allowlist excludes. `quarantined` cannot carry it at all
    — a quarantine stores no media type, so there is nothing to compare, as this
    module's docstring says and `quarantine_object` says again. No test proves
    that half, because the change it would guard against cannot be written; the
    schema is what holds it.

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

    **The denominator is read, not stated.** `eligible` is
    `enrolled_object_count` — `count(*)` over this enrollment's rows in
    `enrollment_objects` — taken on the caller's own connection, from the same
    schema, beside the three numerators. No caller supplies it and no caller can:
    the parameter was removed rather than defaulted, because a `None` that used
    to mean "nobody measured this" and now meant "read it yourself" would have
    changed what every existing call asserts without changing a call site.

    Every count here is restricted by `authorized_object`, which is membership of
    the very rows this total counts, so `accounted` cannot exceed `eligible` and
    the arithmetic guard in `CoverageCounts` cannot be tripped by the outcomes.
    It can still be tripped by `queued` and `unavailable`, which remain the
    caller's to declare, and the failure is the right one: work claimed against a
    scope smaller than it is a number that cannot be true, and raising is better
    than reporting it.
    """
    validate_identifier(enrollment_id, IdKind.ENROLLMENT)
    moment = ensure_utc(observed_at)
    # The one denominator, read where the numerators are read. It is
    # `persistence.enrollment`'s function rather than a fourth `count(*)` written
    # out here, because two statements over `enrollment_objects` that had to
    # agree would be the divergence this package keeps being blocked for.
    eligible = enrolled_object_count(connection, enrollment_id)

    quarantined = connection.execute(
        select(func.count(func.distinct(quarantine_records.c.source_object_id))).where(
            quarantine_records.c.enrollment_id == enrollment_id,
            # The object dimension of the boundary, on the quarantine ledger's own
            # column. There is no content dimension here and there cannot be: a
            # quarantine stores no media type.
            authorized_object(quarantine_records.c.source_object_id, enrollment_id=enrollment_id),
        )
    ).scalar_one()
    unsupported = connection.execute(
        select(func.count(func.distinct(extractions.c.source_object_id))).where(
            extractions.c.enrollment_id == enrollment_id,
            extractions.c.status == ExtractionStatus.UNSUPPORTED.value,
            authorized_object(extractions.c.source_object_id, enrollment_id=enrollment_id),
            extractions.c.source_object_id.not_in(_quarantined_objects(enrollment_id)),
        )
    ).scalar_one()
    # The one count of stored text, and the one place its scope is defined.
    # `extracted_text_in_scope` is that definition and `persistence.search` uses
    # the same call, so both statements apply one predicate set within their own
    # snapshots. Their cross-statement READ COMMITTED window is documented at
    # the search entry point.
    processed = connection.execute(
        select(func.count(func.distinct(extractions.c.source_object_id))).where(
            *extracted_text_in_scope(enrollment_id)
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
