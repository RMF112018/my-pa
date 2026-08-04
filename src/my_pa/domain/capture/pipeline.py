"""The processing pipeline's stages, its aggregate state, and its replay key.

**Nine stages, and the nine are a subset stated rather than assumed.**
`docs/specs/quick-capture/11_EXTRACTION_AND_PROPOSAL_PIPELINE.md` names eighteen.
This build runs `P-01`, `P-02`, `P-03`, `P-04`, `P-05`, `P-08`, `P-09`, `P-15`
and `P-16`. The other nine are excluded because each needs a resolver, a
generator, or a review surface this repository has not built and `P00-OD-006` is
open — which is a checkable reason, unlike "model-assisted", which `11` says of
`P-14` alone.

**One processing-state vocabulary, and which instrument it came from.** Two
disagree: `11_…:224-234` gives nine aggregate states and
`docs/specs/canonical-product-definition/09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md:98`
gives seven, differently named. The canonical seven are used here, on the same
ruling `docs/plans/mcv-completion-plan.md:920` makes for the proposal states —
canonical governs where the two disagree — and because `D-19` ratified that
document. Implementing both would give one fact two vocabularies and no way to
tell which a stored row meant.

**`ProcessingState` is deliberately not `JobState`.** A job is `queued`,
`running`, `succeeded` or `failed` because that is what a worker needs to claim
work and let a crashed lease expire (`persistence.tables.JobState`). A
*processing* state says how far the pipeline got and whether what it produced is
whole — `partial` and `policy_denied` have no job meaning at all, and a job that
is `succeeded` can carry a `partial` result. Mapping one onto the other would
also cost two already-merged constraint texts, one still derived and one frozen
(`D-91`).

**The replay key is the specification's own** (`11_…:209`):
`sha256(capture_version_id | stage | pipeline_version | stage_config_hash)`. It
is what makes "a completed stage with the same key returns the prior output"
(`11_…:212`) decidable without comparing outputs, and it is what a changed
pipeline version breaks on purpose, so a re-run under new configuration is a new
attempt rather than a silent overwrite.
"""

from __future__ import annotations

import hashlib
import re
from enum import StrEnum
from typing import Final

from my_pa.domain.capture.errors import CaptureError
from my_pa.domain.common.identifiers import IdKind, validate_identifier

__all__ = [
    "MAX_PIPELINE_VERSION_CHARACTERS",
    "PIPELINE_VERSION",
    "PipelineError",
    "PipelineStage",
    "ProcessingState",
    "stage_config_digest",
    "stage_identity",
]

#: Bounded, and constrained to a shape, for the reason every caller-facing token
#: in this schema is: an unbounded free-text column is a payload channel.
MAX_PIPELINE_VERSION_CHARACTERS: Final = 32

#: The shape a pipeline or configuration version must take.
_VERSION_PATTERN: Final = re.compile(r"\A[a-z0-9][a-z0-9._-]{0,31}\Z")

#: This build's pipeline version. Bumping it makes every stage's replay key
#: change, which is `11_…:212`'s "a changed pipeline/config creates a new
#: attempt" rather than a migration of stored rows.
PIPELINE_VERSION: Final = "capture-pipeline-v1"

_DIGEST_PATTERN: Final = re.compile(r"\A[0-9a-f]{64}\Z")


class PipelineError(CaptureError):
    """A stage identity could not be built from the values given.

    Names the field and never the value, like every other refusal in this
    package.
    """


class PipelineStage(StrEnum):
    """The stages this build runs, declared in the specification's `P-` order.

    Named for what each does rather than by its `P-` number, because the numbers
    are the specification's index and a stored row outlives a renumbering. The
    mapping is in this module's docstring and in each member's comment.

    **Declaration order is not run order**, and the difference is deliberate
    rather than an oversight. `INDEX_CAPTURE_TEXT` is `P-16` and is declared
    last, but it runs *before* `PERSIST_PROPOSALS`, because `11_…:191` indexes
    the original capture text "immediately" and `QC-AC-050` requires it to be
    searchable "independently of enrichment success" — an act sequenced after
    proposal persistence is an act that never happens for the one capture the
    criterion is about. The order the pipeline actually runs is
    `infrastructure.jobs.capture_pipeline.PIPELINE_ORDER`, which is the single
    statement of it; this enum is the vocabulary, and a vocabulary that also
    claimed to be a schedule would be two facts in one place.
    """

    #: `P-01`. Confirms the version, verifies its stored hash, applies the
    #: bounds, and loads the processing-policy snapshot recorded at save —
    #: `D-95`'s obligation, and the reason a policy added later is honoured for
    #: captures saved after it rather than for every capture retroactively.
    VALIDATE = "validate"
    #: `P-02`. Conservative processing text plus the reversible offset mapping
    #: back to the original. The original is never rewritten.
    NORMALIZE = "normalize"
    #: `P-03`. Deterministic detection, `unknown` permitted, nothing translated.
    DETECT_LANGUAGE = "detect_language"
    #: `P-04`. Paragraphs, sentences, bullets, and quoted or pasted regions —
    #: the last is what makes captured markup recognisable as data rather than
    #: as instruction (`QC-AC-042`).
    SEGMENT = "segment"
    #: `P-05`. Dates, amounts, identifiers, URLs, and explicit commitment cues,
    #: each with a span and an authority classification (`11_…:81`).
    DETERMINISTIC_EXTRACTION = "deterministic_extraction"
    #: `P-08`. Raw phrase preserved, precision and ambiguity recorded, and
    #: recorded, occurred and due time kept apart.
    DATETIME_NORMALIZATION = "datetime_normalization"
    #: `P-09`. Typed work-object proposals from deterministic cues only, each
    #: naming the required fields it could not fill.
    WORK_OBJECT_EXTRACTION = "work_object_extraction"
    #: `P-15`. Proposals and spans written transactionally; nothing that fails
    #: validation is stored as an accepted-looking record.
    PERSIST_PROPOSALS = "persist_proposals"
    #: `P-16`. The original capture text, searchable. Outside `P-15`'s
    #: transaction and before it, because `11_…:191` says "immediately" and
    #: `QC-AC-050` says "independently of enrichment success".
    INDEX_CAPTURE_TEXT = "index_capture_text"


class ProcessingState(StrEnum):
    """How far processing got, and whether what it produced is whole.

    The canonical seven. `partial` is the member that stops this being a
    success/failure flag: a pipeline that extracted three proposals and then
    failed `P-09` produced something real and something incomplete, and
    reporting either "complete" or "failed" for it would be a claim the run does
    not support.
    """

    WAITING = "waiting"
    RUNNING = "running"
    PARTIAL = "partial"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"
    POLICY_DENIED = "policy_denied"
    COMPLETE = "complete"


def _validated_version_token(value: str, *, field: str) -> str:
    if not isinstance(value, str):
        raise PipelineError(f"{field} must be a bounded lowercase token")
    if not _VERSION_PATTERN.fullmatch(value):
        raise PipelineError(f"{field} must be a bounded lowercase token")
    return value


def stage_config_digest(*parts: str) -> str:
    """A stage's configuration, as one digest over its ordered parts.

    Joined by a character the parts cannot contain, so two different
    configurations cannot produce one digest by running together — the same
    reason `stage_identity` uses `|`.
    """
    if not parts:
        raise PipelineError("a stage configuration has at least one part")
    for part in parts:
        if not isinstance(part, str):
            raise PipelineError("a stage configuration part is text without a null")
        if "\x00" in part:
            raise PipelineError("a stage configuration part is text without a null")
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


def stage_identity(
    *,
    version_id: str,
    stage: PipelineStage,
    pipeline_version: str = PIPELINE_VERSION,
    stage_config_hash: str,
) -> str:
    """The replay key `11_…:209` recommends, built exactly as it is written.

    `sha256(capture_version_id | stage | pipeline_version | stage_config_hash)`,
    with `|` as the separator the specification shows. Every part is validated
    first: an identity built from an unvalidated version identifier would key a
    stored row to a value nothing else in the schema would match, and the
    failure of that is an empty replay rather than an error.
    """
    validate_identifier(version_id, IdKind.CAPTURE_VERSION)
    if not isinstance(stage, PipelineStage):
        raise PipelineError("a stage identity names one pipeline stage")
    _validated_version_token(pipeline_version, field="pipeline version")
    if not isinstance(stage_config_hash, str):
        raise PipelineError("a stage configuration hash is a sha-256 digest")
    if not _DIGEST_PATTERN.fullmatch(stage_config_hash):
        raise PipelineError("a stage configuration hash is a sha-256 digest")
    material = "|".join((version_id, stage.value, pipeline_version, stage_config_hash))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
