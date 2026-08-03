"""A capture's stable identity, its immutable content, and the chain of edits.

**`Capture` holds no current-version pointer and no lifecycle state.** Either
would have to be written by a revise, and an `UPDATE` on the identity row is a
mutation path on a chain whose whole point is that it has none. The current
version of a capture is the greatest `version_number` it holds, which is a read
rather than a stored fact that could disagree with the rows it summarises.
Withdrawal and archive (ADR-003 clause 3) are out of scope here and are absent
rather than declared and unreachable.

**Five timestamps, none derived from another.**
`docs/specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:191` requires
device, server, occurred, processed, and accepted times to remain distinct. Two
of them are nullable — a transport may supply no device clock, and a note about
no particular moment has no occurrence — and a nullable column here
is honest absence. Defaulting `occurred_at` from `server_received_at` would
invent a fact about the world from a fact about this process, which is the
laundering `AGENTS.md` section 5 forbids; the difference between "the user did
not say when" and "the user said now" is exactly what the criterion protects.

**The content is preserved exactly.** `CaptureContent` refuses an empty or
whitespace-only value and refuses one past the bound, and does nothing else to
it: no strip, no normalisation, no truncation. The digest is over the UTF-8
bytes of the text as stored, so it identifies what was kept rather than what was
sent through a normaliser first.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.capture.errors import (
    CaptureBoundsError,
    EmptyCaptureError,
    SupersessionError,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "DIGEST_PATTERN",
    "MAX_CAPTURE_CHARACTERS",
    "Capture",
    "CaptureContent",
    "CaptureVersion",
    "ProcessingPolicy",
    "digest_of",
]

#: Longest one capture may be. A bound is required — an unbounded text column is
#: an unbounded request — and this one is derived from what a person types in one
#: sitting rather than from a storage limit. A longer note is not truncated; it
#: is refused, and the caller is told which field and which bound.
MAX_CAPTURE_CHARACTERS: Final = 100_000

#: The shape a stored digest must take, restated where the value object enforces
#: it so that the table constraint and this rule can be compared rather than
#: assumed equal.
DIGEST_PATTERN: Final = re.compile(r"\A[0-9a-f]{64}\Z")


class ProcessingPolicy(StrEnum):
    """What may be done with a stored capture.

    One member, and that is deliberate rather than an unfinished enumeration —
    the same shape and the same argument as `extractions.trust_level`, which also
    permits exactly one value. `P00-OD-006` is open, so this build makes no model
    call and routes nothing anywhere; a policy value naming an eligible route
    would be a column nothing could ever honour. With one member, no writer, no
    hand-run statement, and no later revision can file a capture as routable
    without changing this enum and the frozen literal in the migration that
    mirrors it, which is a visible change rather than a silent one.

    `QC-AC-040` requires the default to be private-local with cloud and training
    false. `classification` carries the first half; this carries the second.
    """

    LOCAL_ONLY = "local_only"


def digest_of(text: str) -> str:
    """Return the SHA-256 of `text`'s UTF-8 bytes, lowercase hexadecimal.

    Over the text as stored, not over a normalised form of it. A digest computed
    after normalisation would identify something the store does not hold, and
    `QC-AC-031`'s "byte-identical payload" would then be a claim about a
    transformation rather than about the bytes.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CaptureContent:
    """One capture's text, bounded and non-empty, and its digest.

    `text` is `repr=False` for the reason `SearchKnowledge.query` is: it is the
    one sensitive string this plane carries, and a dataclass `repr` reaches a
    traceback, a log record, and an assertion message without anyone deciding it
    should.
    """

    text: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            # Domain models are plain dataclasses with no runtime type
            # enforcement, matching the guard in `validate_identifier`.
            raise EmptyCaptureError("capture text must be a string")
        if not self.text.strip():
            raise EmptyCaptureError("a capture must carry text")
        if len(self.text) > MAX_CAPTURE_CHARACTERS:
            raise CaptureBoundsError(
                f"a capture may carry at most {MAX_CAPTURE_CHARACTERS} characters"
            )

    @property
    def digest(self) -> str:
        """The SHA-256 of the stored text."""
        return digest_of(self.text)

    @property
    def character_count(self) -> int:
        """How many characters were stored. A count, never the content."""
        return len(self.text)


@dataclass(frozen=True, slots=True)
class Capture:
    """The stable identity of one user-authored record.

    Three fields, and the two that are not here are the design: no
    `current_version_id` and no `lifecycle_state`. See the module docstring.
    """

    capture_id: str
    owner_principal_id: str
    created_at: datetime

    def __post_init__(self) -> None:
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        validate_identifier(self.owner_principal_id, IdKind.PRINCIPAL)
        ensure_utc(self.created_at)


@dataclass(frozen=True, slots=True)
class CaptureVersion:
    """One immutable version of one capture, and everything bound to it.

    `owner_principal_id` is stored on every version because ADR-003 clause 6
    requires it, and it is stored *and not authorized on* because `D-72` says so:
    identity in this build survives only as long as the serving process, so owner
    equality would make `QC-AC-013` unprovable across two of them. The column is
    an honest record of who wrote the version, whatever that identity's lifetime.

    `audit_id` is a *reference* to an audit event that has already committed on
    its own connection (`D-34`). It is not a foreign key: `audit_events` commits
    before the work it describes, so a reference constraint would make the
    audit's durability depend on the durability of the thing it exists to
    outlive.
    """

    version_id: str
    capture_id: str
    version_number: int
    supersedes_version_id: str | None
    content: CaptureContent
    owner_principal_id: str
    classification: Classification
    processing_policy: ProcessingPolicy
    idempotency_key: str
    correlation_id: str
    audit_id: str
    server_received_at: datetime
    accepted_at: datetime
    recorded_at: datetime
    client_created_at: datetime | None = None
    occurred_at: datetime | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.version_id, IdKind.CAPTURE_VERSION)
        validate_identifier(self.capture_id, IdKind.CAPTURE)
        validate_identifier(self.owner_principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        validate_identifier(self.audit_id, IdKind.AUDIT)
        if isinstance(self.version_number, bool) or not isinstance(self.version_number, int):
            raise SupersessionError("a version number must be an integer")
        if self.version_number < 1:
            raise SupersessionError("version numbers start at one")
        if self.supersedes_version_id is not None:
            validate_identifier(self.supersedes_version_id, IdKind.CAPTURE_VERSION)
        # The chain rule, stated where the value is built as well as in the
        # table. A first version that supersedes something joins a chain it is
        # not the head of; a later version that supersedes nothing starts a
        # second chain inside one capture. Neither is representable.
        if (self.version_number == 1) is not (self.supersedes_version_id is None):
            raise SupersessionError(
                "the first version supersedes nothing and every later one supersedes a predecessor"
            )
        if not isinstance(self.content, CaptureContent):
            raise EmptyCaptureError("a capture version must carry content")
        if not isinstance(self.idempotency_key, str):
            raise SupersessionError("a capture version records the key that admitted it")
        if not self.idempotency_key:
            raise SupersessionError("a capture version records the key that admitted it")
        for moment in (self.server_received_at, self.accepted_at, self.recorded_at):
            ensure_utc(moment)
        for optional in (self.client_created_at, self.occurred_at):
            if optional is not None:
                ensure_utc(optional)
