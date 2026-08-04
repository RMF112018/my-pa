"""The nine stages this build runs over one stored capture version.

The handler `apps/worker.py` gives `run_worker(plane=CAPTURE_JOBS)`. One claimed
job is one capture version — `LeasedJob.subject_id` is the `capver_…` itself, so
nothing here has to look up which capture it is working on before it starts.

**Every stage is a pure derivation followed by a write, and the split is the
whole `QC-AC-035` argument.** `capture_stage_results` stores no output blob: it
stores a digest of what the stage produced and how many rows it wrote. "A
completed stage with the same key returns the prior output" (`11_…:212`) is
therefore only true if the stage can be *re-derived*, so every derivation below
is a function of the immutable version's text and the recorded pipeline version
and of nothing else — no clock, no random value, no row this pipeline wrote, and
no configuration read at run time. `replay_stage` is the check, and
`tests/pipeline/test_stage_replay.py` runs it for all nine.

The one place that rule was in real danger is `P-08`. A date normalizer that
resolved "by Friday" against the wall clock would be correct-looking, useful,
and **not re-derivable** — a replay a day later would produce a different answer
for the same immutable text. So relative phrases are recorded as ambiguous with
the raw phrase preserved (`11_…:113`, `11_…:115`) and are never resolved. That is
a smaller `P-08` than the specification's, and it is a smaller one on purpose.

**Identifiers are minted, so a digest is never taken over one.** `issue_identifier`
is random, so a digest of a proposal row would differ on every run and would make
every replay report a mismatch. Each stage's digest is taken over its
*deterministic content* — offsets, labels, types, enumerated values, bounded
tokens — which is what a replay can reproduce and what a reader means by "the
same output".

**The pipeline commits per stage, not per job** (`D-45`(e)'s shape). `P-16` has
to survive `P-05` failing, because `QC-AC-050` says original text is searchable
"independently of enrichment success" and one transaction over nine stages would
discard it. `hold_lease` is the **first statement** in every one of those
transactions, exactly as `jobs/extraction.py` does it, so a worker whose lease
was taken finds out before it writes and its transaction rolls back having
written nothing.

**`P-16` writes no index row, and that is stronger than the design that called
for one.** `knowledge.capture_versions` carries a functional GIN index over
`to_tsvector('simple', content)`, created by revision `2b7e9f4c1a83`, so a
version is searchable because it was *saved*, not because this pipeline indexed
it. The stage's act is therefore a **confirmation**: it asks the plane's own
predicate whether the version this job is about is findable, and records the
answer. That is not a formality — `tables.py` records that a configuration
mismatch between the index and the predicate breaks **silently**, falling back to
a sequential scan, and a stop-word-only capture under the wrong configuration
becomes unfindable with no exception anywhere. The consequence for `QC-AC-002` is
named rather than absorbed: the save's committed set contains no index row
because no such row exists to contain, so that half of the criterion is
structurally true rather than measured. See
`tests/pipeline/test_save_does_not_wait.py`.

**Nothing here reaches a source, a network, or a model.** The only inputs are a
`Connection` and text already in the database.
`tests/architecture/test_capture_reaches_no_source.py` is the structural form of
that claim, and it names this module.

**Captured text is data and never instruction** (`QC-AC-042`). Every record this
module writes takes its `version_id` from the job's subject and never from
anything a match produced, so a proposal cannot escape the capture it was derived
from; every label, type, state, and reason is an enum member chosen by a rule,
never a string lifted out of the text; and the only content-derived free value
that reaches a column is `normalized_value`, which is bounded by
`domain.capture.proposal`. Quoted and pasted regions are segmented as such
(`11_…:55`, `11_…:69`), which is what makes captured markup recognisable as data
in the first place.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from sqlalchemy import Engine, select
from sqlalchemy.engine import Connection

from my_pa.contracts.ports import CaptureSearchRequest
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.classification import (
    CLASSIFICATION_SCHEME,
    CLASSIFICATION_SCHEME_VERSION,
    CaptureClassification,
    CaptureEntityMention,
    CaptureLabel,
    EntityType,
)
from my_pa.domain.capture.pipeline import (
    PIPELINE_VERSION,
    PipelineStage,
    ProcessingState,
    stage_config_digest,
    stage_identity,
)
from my_pa.domain.capture.proposal import (
    MAX_NORMALIZED_VALUE_CHARACTERS,
    Proposal,
    ProposalField,
    ProposalMethod,
    ProposalState,
    ProposalType,
    RiskClass,
    missing_required_fields,
)
from my_pa.domain.capture.span import SourceSpan, SpanRole
from my_pa.domain.capture.version import ProcessingPolicy, digest_of
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.search.query import SearchQuery
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.jobs.worker import JobExecutionError, LeaseLostError
from my_pa.infrastructure.persistence.capture_search import CAPTURE_VERSIONS, match_statement
from my_pa.infrastructure.persistence.jobs import CAPTURE_JOBS, LeasedJob, hold_lease
from my_pa.infrastructure.persistence.proposals import (
    OffsetMapping,
    StageOutcome,
    record_classification,
    record_entity_mention,
    record_processing_text,
    record_proposal,
    record_span,
    record_stage_result,
    stage_result_for,
)
from my_pa.infrastructure.persistence.review import open_review_case
from my_pa.infrastructure.persistence.tables import capture_versions

__all__ = [
    "METHOD_VERSION",
    "NORMALIZATION_VERSION",
    "PIPELINE_ORDER",
    "SCHEMA_VERSION",
    "Derivation",
    "ProposalDraft",
    "Segment",
    "SegmentKind",
    "TextMatch",
    "commitment_cues",
    "derive",
    "detect_language",
    "normalize_text",
    "normalized_moments",
    "process_capture_version",
    "replay_stage",
    "segment_text",
    "text_matches",
    "work_object_drafts",
]

#: The order the stages run in. **`INDEX_CAPTURE_TEXT` precedes
#: `PERSIST_PROPOSALS`**, which is the reverse of the specification's `P-` numbers
#: and is required by two sentences that agree: `11_…:191` indexes the original
#: capture text "immediately", and `QC-AC-050` makes it searchable "independently
#: of enrichment success". A confirmation recorded after proposal persistence
#: would be a confirmation that never runs for the capture whose extraction
#: failed, which is the only capture the criterion is about.
PIPELINE_ORDER: Final[tuple[PipelineStage, ...]] = (
    PipelineStage.VALIDATE,
    PipelineStage.NORMALIZE,
    PipelineStage.DETECT_LANGUAGE,
    PipelineStage.SEGMENT,
    PipelineStage.DETERMINISTIC_EXTRACTION,
    PipelineStage.DATETIME_NORMALIZATION,
    PipelineStage.INDEX_CAPTURE_TEXT,
    PipelineStage.WORK_OBJECT_EXTRACTION,
    PipelineStage.PERSIST_PROPOSALS,
)

#: Which `P-02` normalization produced a processing text. Bumping it makes the
#: `P-02` stage a new attempt rather than an overwrite, and a span measured
#: against the old text names the old token.
NORMALIZATION_VERSION: Final = "conservative-v1"

#: Which rule set produced a proposal, and which shape the proposal takes.
#: Separate tokens because a rule can change without the record changing.
METHOD_VERSION: Final = "cues-v1"
SCHEMA_VERSION: Final = "v1"

#: The processing policies this pipeline runs under. An allowlist rather than a
#: comparison against the one member `ProcessingPolicy` currently has: an `is
#: not` test against a single-member enum is statically constant, and a build
#: that grows a second policy would then process it through a branch nobody
#: wrote. Fail-closed is the direction that costs nothing here — a policy this
#: build has no branch for stops at `P-01` as `policy_denied`, which is the
#: state that exists for exactly that.
_PROCESSABLE_POLICIES: Final[frozenset[ProcessingPolicy]] = frozenset({ProcessingPolicy.LOCAL_ONLY})

#: The rule name recorded beside every deterministic label, and its version.
_RULE: Final = "deterministic_cue_match"
_RULE_VERSION: Final = "v1"

#: The prefixes that name a project rather than a document. A closed set, so a
#: mention's entity type comes from a rule and never from the text's own shape —
#: an identifier this build has no rule for is a document, which is the weaker
#: claim of the two and the honest default.
_PROJECT_PREFIXES: Final = frozenset({"PRJ", "PROJ", "JOB"})

#: `P-05`'s deterministic matchers. Bounded on both ends: every pattern has an
#: upper repetition bound, because an unbounded quantifier over attacker-supplied
#: text is a denial of service with a regular expression on it, and capture text
#: is untrusted data.
_AMOUNT: Final = re.compile(r"\$\s?\d{1,3}(?:,\d{3}){0,6}(?:\.\d{2})?")
_ISO_DATE: Final = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_MONTH_DATE: Final = re.compile(
    r"\b(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},\s+\d{4}\b"
)
_IDENTIFIER: Final = re.compile(r"\b[A-Z]{2,6}-\d{2,8}\b")
_URL: Final = re.compile(r"\bhttps?://[^\s<>\"']{1,300}")

#: The commitment cues `11_…:79` calls explicit. A closed tuple rather than a
#: pattern over verbs: "explicit" is the specification's word, and a general verb
#: matcher would propose a commitment out of a sentence describing one.
_COMMITMENT_CUES: Final[tuple[str, ...]] = (
    "i will",
    "we will",
    "i'll",
    "we'll",
    "action item",
    "follow up",
    "follow-up",
    "next step",
    "to do",
    "todo",
)

#: Relative time phrases. Recognised so that ambiguity can be *recorded*, and
#: deliberately never resolved: resolving one against a clock would make the
#: stage's output depend on when it ran, which is the property the replay proof
#: rests on.
_RELATIVE_MOMENT: Final = re.compile(
    r"\b(?:today|tomorrow|yesterday|tonight|next week|last week|this week|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|eod|eow)\b",
    re.IGNORECASE,
)

#: The month names, in the order a calendar puts them, for `P-08`'s only
#: resolution. Indexed rather than parsed with a locale-aware library, because a
#: locale is process state and this derivation may read none.
_MONTHS: Final[tuple[str, ...]] = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)

#: Characters `P-02` folds to one space. Line separators are handled separately
#: because collapsing them would destroy the line structure a span's line and
#: column values are counted in. The non-breaking, figure, and narrow no-break
#: spaces are written as escapes rather than as themselves: a literal one in a
#: character class is indistinguishable from an ordinary space to a reader, and
#: a reader who deleted it by accident would silently narrow the class.
_HORIZONTAL_SPACE: Final = re.compile("[ \\t\u00a0\u2007\u202f]{1,4096}")


class SegmentKind(StrEnum):
    """What `P-04` decided one run of text is.

    Not persisted, and therefore not a closed set anything constrains: segments
    are an input to the stages after them, and a segment table would be a fourth
    place capture content sits for no reader. The member that earns its keep is
    `QUOTED` — marking a pasted or quoted region is what makes captured markup
    recognisable as *data*, and it is the structural half of `QC-AC-042`
    (`11_…:55`, `11_…:69`).
    """

    PARAGRAPH = "paragraph"
    BULLET = "bullet"
    QUOTED = "quoted"


@dataclass(frozen=True, slots=True)
class Segment:
    """One run of the original text, and what `P-04` decided it is."""

    kind: SegmentKind
    start_offset: int
    end_offset: int


@dataclass(frozen=True, slots=True)
class TextMatch:
    """One deterministic `P-05` match, as offsets into the original text.

    `normalized_value` is what the match resolved to where a rule could resolve
    it — an ISO date, a decimal amount — and `None` where none could. It is never
    the matched text repeated back: a value that was only ever a copy of the
    span would be a second place the capture's content sits, and the span already
    points at it.
    """

    label: CaptureLabel
    start_offset: int
    end_offset: int
    normalized_value: str | None = None


@dataclass(frozen=True, slots=True)
class ProposalDraft:
    """One `P-09` work-object proposal, before it has an identifier.

    Offsets rather than a span identifier, because the draft is the
    deterministic part and the identifier is not. `P-15` mints the identifiers
    and `P-09`'s digest is taken over these fields, so a replay compares what the
    rules produced rather than what `secrets` produced.
    """

    proposal_type: ProposalType
    risk_class: RiskClass
    missing_fields: tuple[ProposalField, ...]
    normalized_value: str | None
    start_offset: int
    end_offset: int


@dataclass(frozen=True, slots=True)
class Derivation:
    """Everything the nine stages derive from one version's text.

    Computed once, outside every transaction, because it reads nothing but the
    text and holding a lease while running regular expressions would spend the
    lease on arithmetic. Each stage then persists its own slice of this, which is
    what makes a stage's write and a stage's derivation two separable things —
    and separable is what `replay_stage` needs.
    """

    content: str
    normalized_text: str
    mapping: OffsetMapping
    language: str
    segments: tuple[Segment, ...]
    matches: tuple[TextMatch, ...]
    moments: tuple[TextMatch, ...]
    drafts: tuple[ProposalDraft, ...]


# ---- the pure derivations ---------------------------------------------------


def normalize_text(content: str) -> tuple[str, OffsetMapping]:
    """`P-02`: conservative processing text, and the mapping back to the original.

    Two transformations and no more: horizontal whitespace runs collapse to one
    space, and `\\r\\n` and `\\r` become `\\n`. Case is untouched, punctuation is
    untouched, and nothing is transliterated — `11_…:61` forbids translating
    source text silently, and a normalizer that lowercased would make every span
    measured against processing text fail to re-derive against the original.

    **The mapping is reversible and is stored as runs**, not as one pair per
    character. Both transformations are piecewise affine — a run of characters
    shifts by a constant — so three parallel arrays describe them exactly, and
    `OffsetMapping.original_offset_of` is the inverse. `10_…:89` is why it is not
    optional decoration: no proposal may cite only normalized text, so the way
    back has to exist.
    """
    normalized: list[str] = []
    normalized_starts: list[int] = []
    original_starts: list[int] = []
    lengths: list[int] = []

    index = 0
    while index < len(content):
        character = content[index]
        if character == "\r":
            width = 2 if content[index : index + 2] == "\r\n" else 1
            _extend(normalized, normalized_starts, original_starts, lengths, "\n", index, width)
            index += width
            continue
        run = _HORIZONTAL_SPACE.match(content, index)
        if run is not None:
            _extend(
                normalized,
                normalized_starts,
                original_starts,
                lengths,
                " ",
                index,
                run.end() - index,
            )
            index = run.end()
            continue
        _extend(normalized, normalized_starts, original_starts, lengths, character, index, 1)
        index += 1

    text = "".join(normalized)
    if not lengths:
        # Unreachable through the pipeline: `a_capture_version_carries_text`
        # refuses an empty version and `OffsetMapping` refuses an empty mapping.
        # It is a refusal rather than a fabricated single run, because inventing
        # a run over text that is not there is the laundering the policy forbids.
        raise ValueError("a processing text covers at least one run")
    return text, OffsetMapping(
        normalized_starts=tuple(normalized_starts),
        original_starts=tuple(original_starts),
        lengths=tuple(lengths),
    )


def _extend(
    normalized: list[str],
    normalized_starts: list[int],
    original_starts: list[int],
    lengths: list[int],
    emitted: str,
    origin: int,
    consumed: int,
) -> None:
    """Append one emitted character and record where it came from.

    A run is extended rather than started whenever the previous one is still
    affine — same shift, contiguous on both sides — so the stored mapping is as
    short as the transformation actually is.
    """
    position = len(normalized)
    normalized.append(emitted)
    if normalized_starts:
        previous = len(normalized_starts) - 1
        shift = original_starts[previous] - normalized_starts[previous]
        contiguous = normalized_starts[previous] + lengths[previous] == position
        if contiguous and consumed == 1 and origin - position == shift:
            lengths[previous] += 1
            return
    normalized_starts.append(position)
    original_starts.append(origin)
    lengths.append(1)


def detect_language(text: str) -> str:
    """`P-03`: a deterministic guess, with `unknown` as a real answer.

    A closed stop-word vote and nothing more. `11_…:59` requires `unknown` to be
    available, and this build reaches it often — which is correct: a two-word
    note carries no evidence of a language, and reporting one would be a claim
    the text does not support. Nothing is translated (`11_…:61`); this stage
    labels and never rewrites.
    """
    words = {word.strip(".,;:!?\"'()[]").lower() for word in text.split()}
    english = words & {"the", "and", "with", "that", "for", "this", "will", "have", "from"}
    return "en" if len(english) >= 2 else "unknown"


def segment_text(content: str) -> tuple[Segment, ...]:
    """`P-04`: paragraphs, bullets, and quoted or pasted regions.

    A quoted region is a line beginning with `>` or a run of lines inside a
    fenced block, which are the two shapes pasted material arrives in. Marking
    them is the point of the stage for `QC-AC-042`: a proposal derived from a
    quoted region is derived from something the user pasted rather than wrote,
    and a later package cannot make that distinction if it was never recorded.

    Sentences are deliberately absent. `11_…:65` lists them, and a sentence
    splitter that is correct for one language and wrong for another would be the
    silent translation `11_…:61` refuses; paragraphs and bullets are decidable
    from layout alone.
    """
    segments: list[Segment] = []
    offset = 0
    fenced = False
    for line in content.splitlines(keepends=True):
        stripped = line.strip()
        end = offset + len(line.rstrip("\r\n"))
        if stripped.startswith("```"):
            fenced = not fenced
            if end > offset:
                segments.append(Segment(SegmentKind.QUOTED, offset, end))
            offset += len(line)
            continue
        if end > offset:
            if fenced or stripped.startswith(">"):
                kind = SegmentKind.QUOTED
            elif stripped.startswith(("-", "*", "•")) or re.match(r"\d{1,3}[.)]\s", stripped):
                kind = SegmentKind.BULLET
            else:
                kind = SegmentKind.PARAGRAPH
            segments.append(Segment(kind, offset, end))
        offset += len(line)
    return tuple(segments)


def text_matches(content: str) -> tuple[TextMatch, ...]:
    """`P-05`: dates, amounts, identifiers, URLs, and commitment cues.

    Each carries a label, which is `11_…:81`'s "deterministic matches still
    require authority classification": a match with no statement of what kind of
    fact it is, is a fact nobody can act on. Overlaps are resolved by keeping the
    earlier and then the longer, so two rules cannot both claim one run of text
    and produce two labels for it.

    **Known aliases and phone- or email-like strings are absent, and their
    absence is a decision.** `11_…:76` lists aliases, and an alias needs an alias
    table that does not exist. `11_…:78` permits phone- and email-like strings
    "where policy permits", and the only policy this build stores is
    `local_only`, which says nothing about contact detail — so recognising one
    would be this module deciding a policy question, and a recognised contact
    detail would then sit in `normalized_value`, which `AGENTS.md` section 5
    keeps out of everything a log or an audit can reach.
    """
    found: list[TextMatch] = []
    for pattern, label in (
        (_ISO_DATE, CaptureLabel.DATE_MENTION),
        (_MONTH_DATE, CaptureLabel.DATE_MENTION),
        (_AMOUNT, CaptureLabel.FINANCIAL_MENTION),
        (_URL, CaptureLabel.EXTERNAL_REFERENCE),
        (_IDENTIFIER, CaptureLabel.IDENTIFIER_MENTION),
    ):
        for match in pattern.finditer(content):
            found.append(
                TextMatch(
                    label=label,
                    start_offset=match.start(),
                    end_offset=match.end(),
                    normalized_value=_normalized_value(label, match.group(0)),
                )
            )
    found.extend(commitment_cues(content))
    return _without_overlaps(found)


def commitment_cues(content: str) -> tuple[TextMatch, ...]:
    """Every explicit commitment cue in `content`, as offsets.

    Case-insensitive on the cue and never on the text: the comparison folds a
    copy, and the offsets are into the original, so a span measured from one
    re-derives against the version.
    """
    folded = content.lower()
    found: list[TextMatch] = []
    for cue in _COMMITMENT_CUES:
        start = folded.find(cue)
        while start != -1:
            found.append(
                TextMatch(
                    label=CaptureLabel.COMMITMENT_MENTION,
                    start_offset=start,
                    end_offset=start + len(cue),
                )
            )
            start = folded.find(cue, start + len(cue))
    return tuple(found)


def _normalized_value(label: CaptureLabel, text: str) -> str | None:
    """What a match resolves to, or `None` where no rule can resolve it."""
    if label is CaptureLabel.FINANCIAL_MENTION:
        digits = text.replace("$", "").replace(",", "").strip()
        return digits if digits else None
    if label is CaptureLabel.DATE_MENTION:
        return _iso_date(text)
    if label is CaptureLabel.IDENTIFIER_MENTION:
        return text
    if label is CaptureLabel.EXTERNAL_REFERENCE:
        return text[:MAX_NORMALIZED_VALUE_CHARACTERS]
    return None


def _iso_date(text: str) -> str | None:
    """One written date as `YYYY-MM-DD`, or `None`.

    Only the two unambiguous forms. `03/04/2026` is deliberately unrecognised:
    it is March the fourth in one convention and the third of April in another,
    and choosing between them without a stated locale would be inventing a fact
    — which is exactly what `11_…:113`'s "identify ambiguity" says to record
    instead.
    """
    if _ISO_DATE.fullmatch(text):
        return text
    parts = text.replace(",", "").split()
    if len(parts) != 3:
        return None
    name, day, year = parts
    if name.lower() not in _MONTHS:
        return None
    month = _MONTHS.index(name.lower()) + 1
    return f"{int(year):04d}-{month:02d}-{int(day):02d}"


def normalized_moments(content: str, matches: Sequence[TextMatch]) -> tuple[TextMatch, ...]:
    """`P-08`: the date mentions, plus the relative phrases left unresolved.

    **The raw phrase is preserved and nothing relative is resolved.** A
    normalizer that turned "Friday" into a date would need a clock, and a stage
    that reads a clock cannot be replayed — the same immutable text would
    produce a different answer tomorrow, and `QC-AC-035`'s "returns the prior
    output" would be false for every capture that mentioned a weekday. So a
    relative phrase is recorded as a date mention with **no** normalized value,
    which is `11_…:113`'s ambiguity identification: the span says where the
    phrase is, and the empty value says the build could not resolve it.

    **Recorded, occurred, and due time stay apart** (`11_…:117`). This stage
    produces neither a recorded nor an occurred time: both are columns
    `capture_versions` already holds, written by the save from three separate
    origins, and a stage that recomputed either would give one moment two
    sources. What it produces is candidate *due* evidence, and it produces it as
    a span rather than as a timestamp, because a due condition this build cannot
    resolve is not a due date.
    """
    resolved = tuple(match for match in matches if match.label is CaptureLabel.DATE_MENTION)
    relative = tuple(
        TextMatch(
            label=CaptureLabel.DATE_MENTION,
            start_offset=match.start(),
            end_offset=match.end(),
            normalized_value=None,
        )
        for match in _RELATIVE_MOMENT.finditer(content)
    )
    return _without_overlaps([*resolved, *relative])


def work_object_drafts(
    matches: Sequence[TextMatch], segments: Sequence[Segment], moments: Sequence[TextMatch]
) -> tuple[ProposalDraft, ...]:
    """`P-09`: typed work-object proposals from deterministic cues only.

    One draft per commitment cue, typed by the segment it sits in: a cue inside a
    quoted or pasted region is a `FOLLOW_UP` rather than a `COMMITMENT`, because
    a commitment somebody else wrote and the user pasted is not the user's
    commitment. That is the `QC-AC-042` thread arriving where it matters — the
    structural distinction `P-04` recorded is what stops pasted text being read
    as the user's own instruction to the product.

    **Missing required fields are recorded, never filled in** (`11_…:131`). The
    cue is the action, and a date near it is a due condition; the actor, the
    counterparty, and the status need a resolver this build does not have, so all
    three are reported absent. A proposal that claimed them would be an invented
    complete record where an honest partial one belongs.

    `risk_class` is a rule and not a judgement: a cue whose segment also carries
    a financial mention is `MODERATE`, and everything else is `LOW`. `HIGH` and
    `CRITICAL` are unreachable here and are declared rather than omitted, for the
    reason `domain.capture.proposal` gives about the state set.
    """
    drafts: list[ProposalDraft] = []
    for match in matches:
        if match.label is not CaptureLabel.COMMITMENT_MENTION:
            continue
        segment = _segment_of(segments, match.start_offset)
        quoted = segment is not None and segment.kind is SegmentKind.QUOTED
        present = {ProposalField.ACTION}
        if segment is not None and any(
            segment.start_offset <= moment.start_offset < segment.end_offset for moment in moments
        ):
            present.add(ProposalField.DUE_CONDITION)
        financial = segment is not None and any(
            other.label is CaptureLabel.FINANCIAL_MENTION
            and segment.start_offset <= other.start_offset < segment.end_offset
            for other in matches
        )
        proposal_type = ProposalType.FOLLOW_UP if quoted else ProposalType.COMMITMENT
        drafts.append(
            ProposalDraft(
                proposal_type=proposal_type,
                risk_class=RiskClass.MODERATE if financial else RiskClass.LOW,
                missing_fields=missing_required_fields(proposal_type, frozenset(present)),
                normalized_value=None,
                start_offset=match.start_offset,
                end_offset=match.end_offset,
            )
        )
    return tuple(drafts)


def _segment_of(segments: Sequence[Segment], offset: int) -> Segment | None:
    return next(
        (
            segment
            for segment in segments
            if segment.start_offset <= offset < max(segment.end_offset, segment.start_offset + 1)
        ),
        None,
    )


def _without_overlaps(matches: Sequence[TextMatch]) -> tuple[TextMatch, ...]:
    """Keep the earliest match, and the longest where two start together.

    Ordered so that two runs over the same text produce the same tuple in the
    same order — which is what makes a digest over it a stable identity rather
    than an artefact of dictionary iteration.
    """
    ordered = sorted(
        matches, key=lambda m: (m.start_offset, -(m.end_offset - m.start_offset), m.label.value)
    )
    kept: list[TextMatch] = []
    for match in ordered:
        if kept and match.start_offset < kept[-1].end_offset:
            continue
        kept.append(match)
    return tuple(kept)


def derive(content: str) -> Derivation:
    """Everything the nine stages need, from the version's text alone.

    The single entry point for the pure half of this module, and the reason it is
    single: a stage that derived its own inputs could disagree with the stage
    before it about what the text says, and two stages disagreeing about one
    immutable string is a defect nothing would report.
    """
    normalized, mapping = normalize_text(content)
    segments = segment_text(content)
    matches = text_matches(content)
    moments = normalized_moments(content, matches)
    return Derivation(
        content=content,
        normalized_text=normalized,
        mapping=mapping,
        language=detect_language(content),
        segments=segments,
        matches=matches,
        moments=moments,
        drafts=work_object_drafts(matches, segments, moments),
    )


# ---- the stage digests ------------------------------------------------------


def _validate_digest(content_sha256: str, policy: ProcessingPolicy) -> str:
    return stage_config_digest(content_sha256, policy.value)


def _normalize_digest(derivation: Derivation) -> str:
    return stage_config_digest(
        digest_of(derivation.normalized_text),
        NORMALIZATION_VERSION,
        ",".join(str(value) for value in derivation.mapping.normalized_starts),
        ",".join(str(value) for value in derivation.mapping.original_starts),
        ",".join(str(value) for value in derivation.mapping.lengths),
    )


def _language_digest(derivation: Derivation) -> str:
    return stage_config_digest(derivation.language)


def _segment_digest(derivation: Derivation) -> str:
    parts = tuple(
        f"{segment.kind.value}:{segment.start_offset}:{segment.end_offset}"
        for segment in derivation.segments
    )
    # A stated absence rather than no parts at all. `stage_config_digest` refuses
    # an empty call, and a digest over nothing would in any case be the same
    # digest for every empty stage of every kind — which would make two different
    # emptinesses indistinguishable in a replay comparison.
    return stage_config_digest(*(parts or ("no-segments",)))


def _match_digest(matches: Sequence[TextMatch]) -> str:
    parts = tuple(
        f"{match.label.value}:{match.start_offset}:{match.end_offset}:"
        f"{match.normalized_value or ''}"
        for match in matches
    )
    return stage_config_digest(*(parts or ("no-matches",)))


def _draft_digest(drafts: Sequence[ProposalDraft]) -> str:
    parts = tuple(
        f"{draft.proposal_type.value}:{draft.risk_class.value}:"
        f"{','.join(field.value for field in draft.missing_fields)}:"
        f"{draft.start_offset}:{draft.end_offset}"
        for draft in drafts
    )
    return stage_config_digest(*(parts or ("no-drafts",)))


def _index_digest(content_sha256: str, *, searchable: bool) -> str:
    return stage_config_digest(content_sha256, CAPTURE_VERSIONS.configuration, str(searchable))


# ---- the runner -------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Version:
    """The version row this job is about, as the pipeline reads it."""

    version_id: str
    content: str
    content_sha256: str
    processing_policy: ProcessingPolicy


def _read_version(connection: Connection, version_id: str) -> _Version | None:
    row = connection.execute(
        select(
            capture_versions.c.content,
            capture_versions.c.content_sha256,
            capture_versions.c.processing_policy,
        ).where(capture_versions.c.version_id == version_id)
    ).one_or_none()
    if row is None:
        return None
    return _Version(
        version_id=version_id,
        content=str(row.content),
        content_sha256=str(row.content_sha256),
        processing_policy=ProcessingPolicy(row.processing_policy),
    )


def _stage_key(version_id: str, stage: PipelineStage, config: str) -> str:
    return stage_identity(
        version_id=version_id,
        stage=stage,
        pipeline_version=PIPELINE_VERSION,
        stage_config_hash=config,
    )


def _stage_config(stage: PipelineStage) -> str:
    """The configuration digest for one stage.

    Every value in it is a module constant, so the key is a function of the
    version, the stage, the pipeline version, and this build's configuration —
    and of nothing that could differ between two runs of the same build.
    """
    match stage:
        case PipelineStage.NORMALIZE:
            return stage_config_digest(stage.value, NORMALIZATION_VERSION)
        case PipelineStage.WORK_OBJECT_EXTRACTION | PipelineStage.PERSIST_PROPOSALS:
            return stage_config_digest(stage.value, METHOD_VERSION, SCHEMA_VERSION)
        case PipelineStage.DETERMINISTIC_EXTRACTION:
            return stage_config_digest(stage.value, _RULE, _RULE_VERSION)
        case PipelineStage.INDEX_CAPTURE_TEXT:
            return stage_config_digest(stage.value, CAPTURE_VERSIONS.configuration)
        case _:
            return stage_config_digest(stage.value)


def _is_searchable(connection: Connection, version: _Version) -> bool:
    """Whether the capture plane can find this version by a word of its own text.

    The confirmation `P-16` records. A word is taken from the version's own text
    rather than supplied, so the question is "is this version findable" and not
    "does some query match something". A version whose text yields no queryable
    term at all answers `False` rather than raising, and the stage records
    `PARTIAL` for it — which is the disclosed residue rather than a silent empty.
    """
    for word in version.content.split():
        candidate = word.strip(".,;:!?\"'()[]<>")
        if not candidate:
            continue
        try:
            request = CaptureSearchRequest(query=SearchQuery(candidate), limit=1)
        except ValueError:
            continue
        rows = connection.execute(match_statement(request)).all()
        if any(str(row.version_id) == version.version_id for row in rows):
            return True
    return False


def process_capture_version(engine: Engine, job: LeasedJob, owner: str) -> None:
    """Run the nine stages over one claimed capture version.

    The `JobHandler` `apps/worker.py` installs for `CAPTURE_JOBS`. It takes the
    engine rather than a connection because it opens one transaction per stage,
    and it takes the owner because each of those transactions asserts the lease
    itself — `hold_lease` first, every time, so a worker whose lease was taken
    writes nothing and says so by raising.

    A stage already completed under its key is **not re-run**: its stored result
    is the answer, which is `11_…:212`. The derivation still happens, because the
    stages after it need its output and re-deriving is what the whole design
    rests on being able to do; what does not happen is a second write.
    """
    with engine.begin() as connection:
        if not hold_lease(connection, job.operation_id, owner=owner, plane=CAPTURE_JOBS):
            raise LeaseLostError(job.operation_id)
        version = _read_version(connection, job.subject_id)
        if version is None:
            # The job names a version the store does not hold. A broken store
            # rather than a partial result: `capture_jobs.version_id` is a
            # foreign key, so the row cannot have gone without the job going too.
            raise JobExecutionError(ErrorCode.NOT_FOUND)
        if digest_of(version.content) != version.content_sha256:
            # `P-01`'s verification, and it fails the attempt rather than
            # continuing over text whose stored identity does not hold. Every
            # span this pipeline would write cites that digest.
            raise JobExecutionError(ErrorCode.QUARANTINED)
        if version.processing_policy not in _PROCESSABLE_POLICIES:
            # `D-95`'s obligation: the policy recorded **at save** is what
            # governs, not the policy current at processing time, so a policy
            # added later is honoured for captures saved after it rather than
            # retroactively. One member exists today and this branch is what a
            # second one arrives into.
            _record(
                connection,
                job,
                version,
                stage=PipelineStage.VALIDATE,
                state=ProcessingState.POLICY_DENIED,
                digest=_validate_digest(version.content_sha256, version.processing_policy),
                rows=0,
            )
            return
        _record(
            connection,
            job,
            version,
            stage=PipelineStage.VALIDATE,
            state=ProcessingState.COMPLETE,
            digest=_validate_digest(version.content_sha256, version.processing_policy),
            rows=0,
        )

    derivation = derive(version.content)
    processing_text_id: str | None = None

    for stage in PIPELINE_ORDER[1:]:
        with engine.begin() as connection:
            if not hold_lease(connection, job.operation_id, owner=owner, plane=CAPTURE_JOBS):
                raise LeaseLostError(job.operation_id)
            written = _run_stage(
                connection,
                job,
                version,
                derivation,
                stage=stage,
                processing_text_id=processing_text_id,
            )
            if stage is PipelineStage.NORMALIZE and written is not None:
                processing_text_id = written


def _run_stage(
    connection: Connection,
    job: LeasedJob,
    version: _Version,
    derivation: Derivation,
    *,
    stage: PipelineStage,
    processing_text_id: str | None,
) -> str | None:
    """Persist one stage's slice, unless its key says it already ran.

    Returns the processing-text identifier `P-02` wrote, and `None` for every
    other stage and for a `P-02` that was replayed rather than re-run. A replayed
    `P-02` leaves the spans that follow it citing no processing text, which is
    permitted: `capture_spans.processing_text_id` is nullable and `10_…:89` only
    forbids a proposal citing normalized text *alone*.
    """
    key = _stage_key(version.version_id, stage, _stage_config(stage))
    if stage_result_for(connection, key) is not None:
        return None

    rows = 0
    written: str | None = None
    state = ProcessingState.COMPLETE
    match stage:
        case PipelineStage.NORMALIZE:
            written = record_processing_text(
                connection,
                version_id=version.version_id,
                normalized_text=derivation.normalized_text,
                normalization_version=NORMALIZATION_VERSION,
                mapping=derivation.mapping,
                language=None,
            )
            rows = 1
            digest = _normalize_digest(derivation)
        case PipelineStage.DETECT_LANGUAGE:
            digest = _language_digest(derivation)
        case PipelineStage.SEGMENT:
            digest = _segment_digest(derivation)
        case PipelineStage.DETERMINISTIC_EXTRACTION:
            rows = _write_matches(connection, version, derivation, processing_text_id)
            digest = _match_digest(derivation.matches)
        case PipelineStage.DATETIME_NORMALIZATION:
            digest = _match_digest(derivation.moments)
            if any(moment.normalized_value is None for moment in derivation.moments):
                # Something in the text names a moment this build cannot resolve
                # without a clock. `partial` is the honest state for that: the
                # stage produced something real and something incomplete, and
                # reporting `complete` would claim the ambiguity was settled.
                state = ProcessingState.PARTIAL
        case PipelineStage.INDEX_CAPTURE_TEXT:
            searchable = _is_searchable(connection, version)
            digest = _index_digest(version.content_sha256, searchable=searchable)
            if not searchable:
                state = ProcessingState.PARTIAL
        case PipelineStage.WORK_OBJECT_EXTRACTION:
            digest = _draft_digest(derivation.drafts)
        case PipelineStage.PERSIST_PROPOSALS:
            rows = _write_proposals(connection, version, derivation, processing_text_id)
            digest = _draft_digest(derivation.drafts)
        case PipelineStage.VALIDATE:  # pragma: no cover - run before the loop
            digest = _validate_digest(version.content_sha256, version.processing_policy)

    _record(connection, job, version, stage=stage, state=state, digest=digest, rows=rows)
    return written


def _write_matches(
    connection: Connection,
    version: _Version,
    derivation: Derivation,
    processing_text_id: str | None,
) -> int:
    """One classification per match, and a mention for the ones that name a thing.

    Every span is measured against the **original** text, so it re-derives
    against `capture_versions.content` — the immutable column the validation in
    `persistence.proposals.span_faults` recomputes from. A span measured against
    processing text would need its mapping to be carried back before it could be
    checked, and `10_…:89` is what makes that the wrong default.
    """
    written = 0
    for match in derivation.matches:
        span = SourceSpan.over(
            derivation.content,
            version_id=version.version_id,
            start_offset=match.start_offset,
            end_offset=match.end_offset,
            span_role=SpanRole.DIRECT,
        )
        span_id = record_span(connection, span, processing_text_id=processing_text_id)
        record_classification(
            connection,
            CaptureClassification(
                classification_id=issue_identifier(IdKind.CAPTURE_CLASSIFICATION),
                version_id=version.version_id,
                span_id=span_id,
                scheme=CLASSIFICATION_SCHEME,
                scheme_version=CLASSIFICATION_SCHEME_VERSION,
                label=match.label,
                rule=_RULE,
                rule_version=_RULE_VERSION,
            ),
        )
        written += 1
        entity_type = _entity_type(match, derivation.content)
        if entity_type is not None:
            record_entity_mention(
                connection,
                CaptureEntityMention(
                    mention_id=issue_identifier(IdKind.CAPTURE_ENTITY_MENTION),
                    version_id=version.version_id,
                    span_id=span_id,
                    entity_type=entity_type,
                ),
            )
            written += 1
    return written


def _entity_type(match: TextMatch, content: str) -> EntityType | None:
    """Which entity a match names, or `None` where it names none.

    `D-93`'s deterministic subset and no more. People and organisations need an
    alias table that does not exist, so a mention of one is not produced at all
    rather than produced with a guessed type — a wrong type is worse than a
    missing row, because a later resolver would take it as evidence.
    """
    if match.label is CaptureLabel.EXTERNAL_REFERENCE:
        return EntityType.URL
    if match.label is not CaptureLabel.IDENTIFIER_MENTION:
        return None
    prefix = content[match.start_offset : match.end_offset].split("-", 1)[0]
    return EntityType.PROJECT if prefix in _PROJECT_PREFIXES else EntityType.DOCUMENT


def _write_proposals(
    connection: Connection,
    version: _Version,
    derivation: Derivation,
    processing_text_id: str | None,
) -> int:
    """`P-15`: every draft as a proposal citing at least one span.

    The span is written first because the link table's foreign key requires it,
    and the cardinality is enforced at commit by a deferred constraint trigger
    (`D-98`) — so a proposal with no span is refused by the server whether or not
    it went through `record_proposal`.

    **`version_id` comes from the job's subject on every row here.** Not from a
    match, not from a draft, and not from anything the text said. That is
    `QC-AC-042`(b) as a property of this function rather than as a convention:
    there is no value a capture could contain that would put a proposal on
    another capture's version.
    """
    written = 0
    for draft in derivation.drafts:
        span = SourceSpan.over(
            derivation.content,
            version_id=version.version_id,
            start_offset=draft.start_offset,
            end_offset=draft.end_offset,
            span_role=SpanRole.DIRECT,
        )
        span_id = record_span(connection, span, processing_text_id=processing_text_id)
        proposal_id = record_proposal(
            connection,
            Proposal(
                proposal_id=issue_identifier(IdKind.PROPOSAL),
                version_id=version.version_id,
                proposal_type=draft.proposal_type,
                state=ProposalState.PROPOSED,
                risk_class=draft.risk_class,
                method=ProposalMethod.DETERMINISTIC_RULE,
                method_version=METHOD_VERSION,
                schema_version=SCHEMA_VERSION,
                missing_fields=draft.missing_fields,
                normalized_value=draft.normalized_value,
            ),
            (span_id,),
        )
        open_review_case(connection, proposal_id)
        written += 1
    return written


def _record(
    connection: Connection,
    job: LeasedJob,
    version: _Version,
    *,
    stage: PipelineStage,
    state: ProcessingState,
    digest: str,
    rows: int,
) -> StageOutcome:
    return record_stage_result(
        connection,
        version_id=version.version_id,
        operation_id=job.operation_id,
        stage=stage,
        pipeline_version=PIPELINE_VERSION,
        stage_config_sha256=_stage_config(stage),
        idempotency_key=_stage_key(version.version_id, stage, _stage_config(stage)),
        processing_state=state,
        output_sha256=digest,
        output_row_count=rows,
    )


def replay_stage(
    connection: Connection, *, version_id: str, stage: PipelineStage
) -> tuple[str, str]:
    """The digest one stage stored, beside the digest re-deriving it produces now.

    **This is the whole of `QC-AC-035`'s "returns the prior output".**
    `capture_stage_results` holds no output blob, so the claim can only be true
    if the stage is a function of the immutable version plus the recorded
    pipeline version — and the way to know whether it is, is to run it again and
    compare. Equal digests mean the prior output *is* the current output and
    replaying returns it; unequal digests mean the stage read something the
    version does not carry, and the pipeline's idempotency would then be a claim
    about a row rather than about a result.

    Raises rather than returning a sentinel for a stage that never ran or a
    version that does not exist: an absent comparison that answered "equal" would
    be the vacuous pass this check exists to make impossible.
    """
    version = _read_version(connection, version_id)
    if version is None:
        raise ValueError("the version this replay names is not stored")
    stored = stage_result_for(connection, _stage_key(version_id, stage, _stage_config(stage)))
    if stored is None or stored.output_sha256 is None:
        raise ValueError("that stage recorded no output for this version")

    derivation = derive(version.content)
    match stage:
        case PipelineStage.VALIDATE:
            rederived = _validate_digest(version.content_sha256, version.processing_policy)
        case PipelineStage.NORMALIZE:
            rederived = _normalize_digest(derivation)
        case PipelineStage.DETECT_LANGUAGE:
            rederived = _language_digest(derivation)
        case PipelineStage.SEGMENT:
            rederived = _segment_digest(derivation)
        case PipelineStage.DETERMINISTIC_EXTRACTION:
            rederived = _match_digest(derivation.matches)
        case PipelineStage.DATETIME_NORMALIZATION:
            rederived = _match_digest(derivation.moments)
        case PipelineStage.INDEX_CAPTURE_TEXT:
            rederived = _index_digest(
                version.content_sha256, searchable=_is_searchable(connection, version)
            )
        case PipelineStage.WORK_OBJECT_EXTRACTION | PipelineStage.PERSIST_PROPOSALS:
            rederived = _draft_digest(derivation.drafts)
    return stored.output_sha256, rederived
