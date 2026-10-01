"""CRL-WP-03: the lifecycle of one Capture root -- archive and restore.

`docs/specs/capture-withdrawal-v0.1.md` (CW-001..CW-019) is the product
contract; this module is its pure domain half. Nothing here reads or writes a
row, takes a lock or talks to a clock: persistence, the use case and the
pipeline fences arrive in later checkpoints and call into these rules rather
than restating them.

**Lifecycle is a fact about the root, held beside it.** `version.Capture`
still carries no lifecycle state (that module's docstring explains why an
identity row cannot be updated). The current state is a *projection* of an
append-only event history, exactly as the current content is a projection of
the version chain: a root with no lifecycle event is `active` at revision 0
(CW-001), and every event increments the revision by one (CW-002).

**Alternation is arithmetic, so it can be declared.** Starting from active/0,
the only legal transitions alternate archive, restore, archive... So an odd
revision is always the result of an archive and an even one of a restore, and
the state at revision `n` is `archived` exactly when `n` is odd. The planned
table CHECKs restate the same two rules (`(lifecycle_revision % 2 = 1) =
(operation = 'archive')` and `(operation = 'archive') = (resulting_state =
'archived')`); `state_at_revision` and `operation_for_revision` are the rule in
one place so the CHECK and this code can be compared rather than assumed equal.

**The intent digest binds what the caller asked for and nothing the server
chose** (CW-007, CW-AC-03). Its material is the owning Principal, the
operation, the root, the expected lifecycle revision and the normalized
reason -- and a domain-separation tag. A generated event id, receipt id,
timestamp or correlation id has no parameter to arrive through, so advancing
the clock or reissuing an id cannot change it. The reason enters the digest
and nowhere else in this module's public output: `CaptureLifecycleIntent`
holds it `repr=False`, and no error carries it.

**Reason normalization is deliberately minimal.** Boundary whitespace is
trimmed, a whitespace-only reason is refused, and the trimmed text must hold
1..500 Unicode code points. Nothing else changes: internal whitespace, case and
the Unicode normalization form all remain significant, so `"Done"` and
`"done"`, or an NFC and an NFD spelling, are different intents. A string that
cannot be encoded as UTF-8 (a lone surrogate) is refused as malformed rather
than silently replaced.

**Eligibility is an interface, not a setting.** Restore resumes work under
*then-current* processing policy (CW-016, MR-C12). No capture-processing
enablement setting exists in this build, so the seam is a resolver protocol
the worker composes; `pause_cause_for` combines its answer with the root's
lifecycle state into the one pause token a job row may carry.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final, Protocol

from my_pa.domain.capture.errors import CaptureError
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "INITIAL_LIFECYCLE_REVISION",
    "INTENT_DIGEST_SCHEME",
    "MAX_LIFECYCLE_REASON_CHARACTERS",
    "MAX_LIFECYCLE_REVISION",
    "CaptureLifecycleDecision",
    "CaptureLifecycleError",
    "CaptureLifecycleEvent",
    "CaptureLifecycleHistoryError",
    "CaptureLifecycleIntent",
    "CaptureLifecycleOperation",
    "CaptureLifecycleOutcome",
    "CaptureLifecycleProjection",
    "CaptureLifecycleReasonError",
    "CaptureLifecycleReceipt",
    "CaptureLifecycleRevisionError",
    "CaptureLifecycleState",
    "CapturePauseCause",
    "CaptureProcessingEligibility",
    "CaptureProcessingEligibilityResolver",
    "CaptureProcessingSubject",
    "CaptureReasonCategory",
    "StaleCaptureLifecycleRevisionError",
    "decide_transition",
    "intent_digest",
    "normalize_reason",
    "operation_for_revision",
    "pause_cause_for",
    "project_history",
    "state_at_revision",
    "target_state",
    "validate_expected_revision",
]

#: The revision of a root that has never transitioned (CW-001).
INITIAL_LIFECYCLE_REVISION: Final = 0

#: The largest revision a root may reach: the planned `INTEGER` columns'
#: bound. Stated so an out-of-range caller value is refused as invalid here
#: rather than surfacing later as a database overflow.
MAX_LIFECYCLE_REVISION: Final = 2_147_483_647

#: The trimmed reason holds 1..this many Unicode code points (CW-007).
MAX_LIFECYCLE_REASON_CHARACTERS: Final = 500

#: The domain-separation tag inside the digest material. A later change to the
#: material is a new scheme, never a silent reinterpretation of stored digests.
INTENT_DIGEST_SCHEME: Final = "capture-lifecycle-intent-v1"


class CaptureLifecycleState(StrEnum):
    """The two states a Capture root can be in (CW-001)."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class CaptureLifecycleOperation(StrEnum):
    """The two lifecycle operations. No delete, purge or undo alias exists."""

    ARCHIVE = "archive"
    RESTORE = "restore"


class CaptureLifecycleOutcome(StrEnum):
    """What a receipted request did (CW-009).

    A replay is not an outcome: it returns the original receipt, whose outcome
    is one of these two.
    """

    APPLIED = "applied"
    NO_OP = "no_op"


class CaptureReasonCategory(StrEnum):
    """The bounded, redacted reason category an event records (MR-C10).

    One member: the command has no category input, so the only honest category
    is that the owner stated a reason. The raw reason is bound by the digest
    and never stored here (CW-018).
    """

    OWNER_STATED = "owner_stated"


class CapturePauseCause(StrEnum):
    """Why a queued capture job is not claimable (plan (e.3), (f)).

    `CAPTURE_WITHDRAWN` is set by archive and cleared or converted by restore;
    `CURRENT_POLICY_INELIGIBLE` is set when then-current eligibility refuses
    work on an active root, and is re-evaluated after bounded backoff (MR-C16).
    """

    CAPTURE_WITHDRAWN = "capture_withdrawn"
    CURRENT_POLICY_INELIGIBLE = "current_policy_ineligible"


class CaptureProcessingEligibility(StrEnum):
    """A resolver's answer about then-current processing eligibility."""

    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"


# --- refusals ------------------------------------------------------------------


class CaptureLifecycleError(CaptureError):
    """A lifecycle value or rule refused. Never carries the refused value."""


class CaptureLifecycleReasonError(CaptureLifecycleError):
    """The reason was not a string, was blank, was out of bound, or was not UTF-8.

    Invalid intent (`invalid_request` naming `reason`). The message names the
    rule only: a reason is operator free text and must not reach an error.
    """


class CaptureLifecycleRevisionError(CaptureLifecycleError):
    """An expected lifecycle revision was malformed: not an int, a bool, or out of range.

    Invalid intent (`invalid_request` naming `expected_lifecycle_revision`).
    """


class StaleCaptureLifecycleRevisionError(CaptureLifecycleError):
    """A well-formed expected revision is not the root's current one (CW-008).

    `conflict` naming `expected_lifecycle_revision`. Raised even when the root is
    already in the requested state: a fresh key must name the current revision
    for a no-op too. Carries neither revision, so a caller learns nothing about
    a root beyond the fact that its own precondition no longer holds.
    """


class CaptureLifecycleHistoryError(CaptureLifecycleError):
    """Stored lifecycle facts break contiguity, alternation or root binding.

    An internal fault, never a caller's: the planned table constraints make
    such a history unrepresentable, so reading one means the store is broken.
    """


# --- the rules -------------------------------------------------------------------


def validate_expected_revision(value: object) -> int:
    """Return `value` as a lifecycle revision, or raise `CaptureLifecycleRevisionError`.

    Strict: an `int` that is not a `bool`, in `0..MAX_LIFECYCLE_REVISION`. A
    `True` is refused rather than read as 1 (plan (g), CRL-AC-D6).
    """
    if isinstance(value, bool) or not isinstance(value, int):
        raise CaptureLifecycleRevisionError("an expected lifecycle revision must be an integer")
    if value < INITIAL_LIFECYCLE_REVISION or value > MAX_LIFECYCLE_REVISION:
        raise CaptureLifecycleRevisionError("an expected lifecycle revision is out of range")
    return value


def normalize_reason(value: object) -> str:
    """Trim boundary whitespace and enforce 1..500 code points (CW-007).

    No case folding, no Unicode normalization, no internal whitespace change.
    Idempotent: normalizing a normalized reason returns it unchanged.
    """
    if not isinstance(value, str):
        raise CaptureLifecycleReasonError("a lifecycle reason must be a string")
    trimmed = value.strip()
    if not trimmed:
        raise CaptureLifecycleReasonError("a lifecycle reason must not be blank")
    if len(trimmed) > MAX_LIFECYCLE_REASON_CHARACTERS:
        raise CaptureLifecycleReasonError(
            f"a lifecycle reason holds at most {MAX_LIFECYCLE_REASON_CHARACTERS} code points"
        )
    try:
        trimmed.encode("utf-8")
    except UnicodeEncodeError:
        raise CaptureLifecycleReasonError("a lifecycle reason must be valid Unicode") from None
    return trimmed


def target_state(operation: CaptureLifecycleOperation) -> CaptureLifecycleState:
    """The state an operation asks the root to be in."""
    if operation is CaptureLifecycleOperation.ARCHIVE:
        return CaptureLifecycleState.ARCHIVED
    return CaptureLifecycleState.ACTIVE


def state_at_revision(revision: int) -> CaptureLifecycleState:
    """The state a root is in at `revision` under strict alternation from active/0."""
    validate_expected_revision(revision)
    if revision % 2 == 1:
        return CaptureLifecycleState.ARCHIVED
    return CaptureLifecycleState.ACTIVE


def operation_for_revision(revision: int) -> CaptureLifecycleOperation:
    """The only operation whose event may carry `revision` (>= 1)."""
    validate_expected_revision(revision)
    if revision < 1:
        raise CaptureLifecycleRevisionError("revision 0 is reached by no operation")
    if revision % 2 == 1:
        return CaptureLifecycleOperation.ARCHIVE
    return CaptureLifecycleOperation.RESTORE


def intent_digest(
    *,
    owner_principal_id: str,
    operation: CaptureLifecycleOperation,
    capture_id: str,
    expected_lifecycle_revision: int,
    reason: str,
) -> str:
    """The SHA-256 of one normalized caller intent, lowercase hexadecimal (CW-007).

    The material is a canonical JSON object -- sorted keys, no padding, ASCII
    escapes -- of the scheme tag and the five intent fields, with the reason
    normalized first. There is no parameter for a time or a generated id, so
    neither can enter it (CW-AC-03).
    """
    validate_identifier(owner_principal_id, IdKind.PRINCIPAL)
    validate_identifier(capture_id, IdKind.CAPTURE)
    material = {
        "capture_id": capture_id,
        "expected_lifecycle_revision": validate_expected_revision(expected_lifecycle_revision),
        "operation": CaptureLifecycleOperation(operation).value,
        "owner_principal_id": owner_principal_id,
        "reason": normalize_reason(reason),
        "scheme": INTENT_DIGEST_SCHEME,
    }
    canonical = json.dumps(material, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptureLifecycleIntent:
    """One normalized archive or restore request, and its digest.

    `reason` is normalized on construction and is `repr=False`: it is the one
    piece of operator free text this plane carries, and a dataclass `repr`
    reaches tracebacks and log records without anyone deciding it should.
    """

    owner_principal_id: str
    capture_id: str
    operation: CaptureLifecycleOperation
    expected_lifecycle_revision: int
    reason: str = field(repr=False)

    def __post_init__(self) -> None:
        validate_identifier(self.owner_principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        object.__setattr__(self, "operation", CaptureLifecycleOperation(self.operation))
        validate_expected_revision(self.expected_lifecycle_revision)
        object.__setattr__(self, "reason", normalize_reason(self.reason))

    @property
    def digest(self) -> str:
        """The intent digest; see `intent_digest`."""
        return intent_digest(
            owner_principal_id=self.owner_principal_id,
            operation=self.operation,
            capture_id=self.capture_id,
            expected_lifecycle_revision=self.expected_lifecycle_revision,
            reason=self.reason,
        )


def _digest_shape(value: object) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise CaptureLifecycleHistoryError("an intent digest is 64 lowercase hex characters")
    return value


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptureLifecycleEvent:
    """One append-only lifecycle transition (plan (e.1)).

    Every invariant the planned table declares is checked here too, so a row
    that could not be inserted cannot be built, and a row read back that breaks
    one is refused as a broken store.
    """

    event_id: str
    owner_principal_id: str
    capture_id: str
    lifecycle_revision: int
    operation: CaptureLifecycleOperation
    resulting_state: CaptureLifecycleState
    predecessor_event_id: str | None
    predecessor_revision: int | None
    transitioned_at: datetime
    intent_digest: str
    correlation_id: str
    audit_id: str
    reason_category: CaptureReasonCategory = CaptureReasonCategory.OWNER_STATED

    def __post_init__(self) -> None:
        validate_identifier(self.event_id, IdKind.CAPTURE_LIFECYCLE_EVENT)
        validate_identifier(self.owner_principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        validate_identifier(self.audit_id, IdKind.AUDIT)
        ensure_utc(self.transitioned_at)
        _digest_shape(self.intent_digest)
        object.__setattr__(self, "operation", CaptureLifecycleOperation(self.operation))
        object.__setattr__(self, "resulting_state", CaptureLifecycleState(self.resulting_state))
        object.__setattr__(self, "reason_category", CaptureReasonCategory(self.reason_category))
        # Typed `object`: a dataclass enforces no annotation at runtime, so the
        # type check is real and must not read as dead code to a type checker.
        stored: object = self.lifecycle_revision
        if isinstance(stored, bool) or not isinstance(stored, int) or stored < 1:
            raise CaptureLifecycleHistoryError("an event's lifecycle revision is at least one")
        revision = validate_expected_revision(stored)
        if self.operation is not operation_for_revision(revision):
            raise CaptureLifecycleHistoryError("odd revisions archive and even revisions restore")
        if self.resulting_state is not target_state(self.operation):
            raise CaptureLifecycleHistoryError("archive results in archived, restore in active")
        if (self.predecessor_event_id is None) != (self.predecessor_revision is None):
            # Both halves or neither. The planned composite self-reference is
            # MATCH SIMPLE, so a half-null predecessor would escape it; the
            # table needs this CHECK too, not only the revision-1 rule.
            raise CaptureLifecycleHistoryError("a predecessor names both its event and revision")
        first = revision == 1
        if first != (self.predecessor_event_id is None):
            raise CaptureLifecycleHistoryError(
                "the first event has no predecessor and every later one has exactly one"
            )
        if self.predecessor_event_id is not None:
            validate_identifier(self.predecessor_event_id, IdKind.CAPTURE_LIFECYCLE_EVENT)
        if self.predecessor_revision is not None and self.predecessor_revision != revision - 1:
            raise CaptureLifecycleHistoryError("a predecessor is the immediately prior revision")

    @classmethod
    def following(
        cls,
        projection: CaptureLifecycleProjection,
        decision: CaptureLifecycleDecision,
        *,
        event_id: str,
        transitioned_at: datetime,
        intent_digest: str,
        correlation_id: str,
        audit_id: str,
    ) -> CaptureLifecycleEvent:
        """The event an APPLIED decision appends after `projection`'s latest event."""
        if decision.outcome is not CaptureLifecycleOutcome.APPLIED:
            raise CaptureLifecycleHistoryError("only an applied decision appends an event")
        if (
            decision.owner_principal_id != projection.owner_principal_id
            or decision.capture_id != projection.capture_id
            or decision.expected_lifecycle_revision != projection.revision
        ):
            raise CaptureLifecycleHistoryError("a decision follows the projection it was made on")
        first = projection.revision == INITIAL_LIFECYCLE_REVISION
        return cls(
            event_id=event_id,
            owner_principal_id=projection.owner_principal_id,
            capture_id=projection.capture_id,
            lifecycle_revision=decision.resulting_lifecycle_revision,
            operation=decision.operation,
            resulting_state=decision.resulting_state,
            predecessor_event_id=None if first else projection.latest_event_id,
            predecessor_revision=None if first else projection.revision,
            transitioned_at=transitioned_at,
            intent_digest=intent_digest,
            correlation_id=correlation_id,
            audit_id=audit_id,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptureLifecycleProjection:
    """A root's current lifecycle: state, revision, archive interval start.

    `archived_at` is the transition time of the event that opened the current
    archived interval, and `None` while active (CW-005). `latest_event_id` is
    the event a following transition names as its predecessor, `None` at
    revision 0. The public read fields are `lifecycle_state`,
    `lifecycle_revision` and `archived_at` (`CAPTURE_LIFECYCLE_FIELDS`).
    """

    owner_principal_id: str
    capture_id: str
    state: CaptureLifecycleState
    revision: int
    archived_at: datetime | None
    latest_event_id: str | None

    def __post_init__(self) -> None:
        validate_identifier(self.owner_principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        object.__setattr__(self, "state", CaptureLifecycleState(self.state))
        validate_expected_revision(self.revision)
        if self.state is not state_at_revision(self.revision):
            raise CaptureLifecycleHistoryError("a projection's state follows its revision")
        if (self.state is CaptureLifecycleState.ARCHIVED) != (self.archived_at is not None):
            raise CaptureLifecycleHistoryError("only an archived root has an archive time")
        if self.archived_at is not None:
            ensure_utc(self.archived_at)
        if (self.revision == INITIAL_LIFECYCLE_REVISION) != (self.latest_event_id is None):
            raise CaptureLifecycleHistoryError("only a never-transitioned root has no event")
        if self.latest_event_id is not None:
            validate_identifier(self.latest_event_id, IdKind.CAPTURE_LIFECYCLE_EVENT)

    @classmethod
    def initial(cls, *, owner_principal_id: str, capture_id: str) -> CaptureLifecycleProjection:
        """A root with no lifecycle event: active at revision 0 (CW-001)."""
        return cls(
            owner_principal_id=owner_principal_id,
            capture_id=capture_id,
            state=CaptureLifecycleState.ACTIVE,
            revision=INITIAL_LIFECYCLE_REVISION,
            archived_at=None,
            latest_event_id=None,
        )

    @classmethod
    def from_latest(
        cls,
        *,
        owner_principal_id: str,
        capture_id: str,
        latest: CaptureLifecycleEvent | None,
    ) -> CaptureLifecycleProjection:
        """The projection from the latest event alone (the persistence read path).

        Sufficient because the latest event's revision fixes the state, and an
        archived root's latest event is the archive that opened its interval.
        """
        if latest is None:
            return cls.initial(owner_principal_id=owner_principal_id, capture_id=capture_id)
        if latest.owner_principal_id != owner_principal_id or latest.capture_id != capture_id:
            raise CaptureLifecycleHistoryError("an event belongs to its own root and owner")
        archived = latest.resulting_state is CaptureLifecycleState.ARCHIVED
        return cls(
            owner_principal_id=owner_principal_id,
            capture_id=capture_id,
            state=latest.resulting_state,
            revision=latest.lifecycle_revision,
            archived_at=latest.transitioned_at if archived else None,
            latest_event_id=latest.event_id,
        )


def project_history(
    *,
    owner_principal_id: str,
    capture_id: str,
    events: Sequence[CaptureLifecycleEvent],
) -> CaptureLifecycleProjection:
    """Fold a complete ordered history into the current projection (CW-AC-01).

    Refuses a history that is not exactly revisions 1..n of one root, each
    naming its immediate predecessor: a gap, a fork, a foreign event or a
    mislinked predecessor is a broken store, not a state to guess at.
    """
    previous: CaptureLifecycleEvent | None = None
    for expected_revision, event in enumerate(events, start=1):
        if event.owner_principal_id != owner_principal_id or event.capture_id != capture_id:
            raise CaptureLifecycleHistoryError("an event belongs to its own root and owner")
        if event.lifecycle_revision != expected_revision:
            raise CaptureLifecycleHistoryError("a lifecycle history is contiguous from one")
        if previous is not None and event.predecessor_event_id != previous.event_id:
            raise CaptureLifecycleHistoryError("each event names its immediate predecessor")
        previous = event
    return CaptureLifecycleProjection.from_latest(
        owner_principal_id=owner_principal_id, capture_id=capture_id, latest=previous
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptureLifecycleDecision:
    """What a fresh (non-replay) request does to a root (CW-008, CW-009)."""

    owner_principal_id: str
    capture_id: str
    operation: CaptureLifecycleOperation
    outcome: CaptureLifecycleOutcome
    expected_lifecycle_revision: int
    resulting_lifecycle_revision: int
    resulting_state: CaptureLifecycleState


def decide_transition(
    projection: CaptureLifecycleProjection,
    operation: CaptureLifecycleOperation,
    expected_lifecycle_revision: int,
) -> CaptureLifecycleDecision:
    """Decide APPLIED or NO_OP for a fresh request, or refuse a stale one.

    Replay is not decided here: an exact same-key, same-intent request returns
    its stored receipt before this is consulted (CW-008). A stale expected
    revision conflicts even when the root is already in the requested state.
    A same-state request with the current revision is an honest NO_OP: no
    revision increment and no archive-time reset (CW-005, CW-009).
    """
    expected = validate_expected_revision(expected_lifecycle_revision)
    operation = CaptureLifecycleOperation(operation)
    if expected != projection.revision:
        raise StaleCaptureLifecycleRevisionError("the expected lifecycle revision is not current")
    wanted = target_state(operation)
    if projection.state is wanted:
        return CaptureLifecycleDecision(
            owner_principal_id=projection.owner_principal_id,
            capture_id=projection.capture_id,
            operation=operation,
            outcome=CaptureLifecycleOutcome.NO_OP,
            expected_lifecycle_revision=expected,
            resulting_lifecycle_revision=expected,
            resulting_state=wanted,
        )
    # The projection ties its state to its revision's parity, so moving out of
    # it always lands on the parity `operation_for_revision` assigns to
    # `operation`; no second alternation check is needed here (or reachable).
    resulting = validate_expected_revision(expected + 1)
    return CaptureLifecycleDecision(
        owner_principal_id=projection.owner_principal_id,
        capture_id=projection.capture_id,
        operation=operation,
        outcome=CaptureLifecycleOutcome.APPLIED,
        expected_lifecycle_revision=expected,
        resulting_lifecycle_revision=resulting,
        resulting_state=wanted,
    )


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptureLifecycleReceipt:
    """One idempotency receipt: the original outcome of one key (plan (e.2)).

    Holds no reason and no text. The honest-outcome rules the planned table
    declares are checked here: APPLIED moves the revision by exactly one and
    names an event; NO_OP moves nothing, and names the latest event of its own
    operation except at revision 0, where none exists.
    """

    receipt_id: str
    owner_principal_id: str
    idempotency_key: str = field(repr=False)
    capture_id: str
    operation: CaptureLifecycleOperation
    intent_digest: str
    expected_lifecycle_revision: int
    resulting_lifecycle_revision: int
    outcome: CaptureLifecycleOutcome
    event_id: str | None
    issued_at: datetime
    correlation_id: str
    audit_id: str

    def __post_init__(self) -> None:
        validate_identifier(self.receipt_id, IdKind.CAPTURE_LIFECYCLE_RECEIPT)
        validate_identifier(self.owner_principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        validate_identifier(self.audit_id, IdKind.AUDIT)
        key: object = self.idempotency_key
        if not isinstance(key, str) or not key:
            raise CaptureLifecycleHistoryError("a receipt records the key that admitted it")
        _digest_shape(self.intent_digest)
        ensure_utc(self.issued_at)
        object.__setattr__(self, "operation", CaptureLifecycleOperation(self.operation))
        object.__setattr__(self, "outcome", CaptureLifecycleOutcome(self.outcome))
        expected = validate_expected_revision(self.expected_lifecycle_revision)
        resulting = validate_expected_revision(self.resulting_lifecycle_revision)
        if self.event_id is not None:
            validate_identifier(self.event_id, IdKind.CAPTURE_LIFECYCLE_EVENT)
        if self.outcome is CaptureLifecycleOutcome.APPLIED:
            if resulting != expected + 1 or self.event_id is None:
                raise CaptureLifecycleHistoryError(
                    "an applied receipt moves the revision by one and names its event"
                )
        elif resulting != expected or ((expected == 0) != (self.event_id is None)):
            raise CaptureLifecycleHistoryError(
                "a no-op receipt moves nothing and names an event except at revision zero"
            )


# --- then-current processing eligibility -----------------------------------------


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptureProcessingSubject:
    """What an eligibility resolver is asked about: one version of one owned root.

    `processing_policy` is the immutable ceiling saved on the version (D-95);
    the resolver answers whether *then-current* policy still permits work
    within it (CW-016). No text is carried.
    """

    owner_principal_id: str
    capture_id: str
    version_id: str
    processing_policy: str
    classification: Classification

    def __post_init__(self) -> None:
        validate_identifier(self.owner_principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)


class CaptureProcessingEligibilityResolver(Protocol):
    """The seam through which then-current processing policy is consulted.

    Implementations must be pure with respect to the request: no write, no
    disclosure, and the same answer for the same subject and policy state. The
    worker composes one; tests inject one that refuses to prove CW-AC-08.
    """

    def eligibility(self, subject: CaptureProcessingSubject) -> CaptureProcessingEligibility:
        """Whether then-current policy permits processing `subject`."""
        ...


def pause_cause_for(
    state: CaptureLifecycleState,
    eligibility: CaptureProcessingEligibility,
) -> CapturePauseCause | None:
    """The pause token a queued job of a root in `state` must carry, or `None`.

    Archive dominates: an archived root's work is withdrawn whatever policy
    says, so restoring the root is what re-exposes the policy question
    (MR-C12). An active root's work is paused only when then-current policy
    refuses it.
    """
    state = CaptureLifecycleState(state)
    eligibility = CaptureProcessingEligibility(eligibility)
    if state is CaptureLifecycleState.ARCHIVED:
        return CapturePauseCause.CAPTURE_WITHDRAWN
    if eligibility is CaptureProcessingEligibility.INELIGIBLE:
        return CapturePauseCause.CURRENT_POLICY_INELIGIBLE
    return None
