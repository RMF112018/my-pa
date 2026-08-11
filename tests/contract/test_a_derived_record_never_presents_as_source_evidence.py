"""Model and extractor output proposes; it never presents itself as source evidence.

WP-23 P4, `docs/specs` section 24, `INV-PKL-003`. The rule is that a derived
contribution must be distinguishable from source evidence **at every layer**, so
that no reader — a caller, a reviewer, a later writer, or a second
implementation — can mistake something this system computed for something the
source said.

**Four layers, and each refuses on its own.** That is the property worth
asserting, because a discriminator held at one layer is a discriminator the next
layer's writer can forget:

1. **The domain refuses.** `ExtractionOutcome.__post_init__` rejects any trust
   level but `source_bound_derived`, so an outcome that claims to be source
   original cannot be constructed at all.
2. **The storage refuses.** `knowledge.extractions` carries
   `derived_text_is_never_source_original`, a `CHECK` over the same value, plus a
   server default of the derived level so a writer that forgets the column still
   writes the truthful one. The constraint is read off `METADATA` here; that
   PostgreSQL actually enforces it is
   `tests/schema/test_extraction_schema_migration.py::test_the_schema_refuses_extracted_text_filed_as_source_original`,
   which inserts the row and watches the server refuse.
3. **The envelope carries it.** `Trust.level` is a required field of the
   mandatory disclosure, so no successful result can omit it.
4. **Every extraction-plane capability states the derived level.** Asserted by
   *running* each one over in-memory fakes and reading the envelope, against an
   exact mapping — not by scanning for a constant, which would pass over a code
   path that never executed.

**`knowledge.reveal` is in the mapping and is `source_original`, deliberately.**
It reads the capture plane, where the content is what a person typed, and
`ADR-003` makes a user-authored record an authority in its own right rather than
something derived from one. Putting it in the same table as the three extraction
reads is the point: the mapping is a decision about each capability rather than a
blanket rule that would either mislabel a capture or let an extraction slip
through.

**And nothing on this plane writes.** The read module builds no `insert`,
`update` or `delete`, so a derived record cannot promote itself on the way out —
which is the failure section 24 names, and which
`tests/architecture/test_derivation_proposes_and_never_promotes.py` holds for the
continuity plane on the same terms.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

import pytest
from tests.conftest import WHEN as SOME_MOMENT
from tests.conftest import (
    Scene,
    build_service,
    metadata_for,
    staged_capture,
    staged_record,
    staged_search,
)

from my_pa.application.commands import (
    Command,
    GetCorpusCoverage,
    ReadKnowledge,
    RevealSubject,
    SearchKnowledge,
)
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.common.provenance import Provenance, TrustLevel
from my_pa.domain.extraction.quarantine import QuarantineReason
from my_pa.domain.extraction.text import ExtractionOutcome, ExtractionStatus
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.persistence.tables import extractions

ROOT: Final = Path(__file__).resolve().parents[2]
READS: Final = ROOT / "src" / "my_pa" / "infrastructure" / "persistence" / "knowledge.py"

#: The trust level each `knowledge.*` capability's envelope must carry, and the
#: reason it is that one. An exact mapping over the family rather than a blanket
#: rule: three of the four read the extraction plane, where every record is
#: computed from bytes and must say so, and the fourth reads the capture plane,
#: where the content is what a person wrote.
EXPECTED_TRUST: Final[dict[Capability, TrustLevel]] = {
    Capability.KNOWLEDGE_SEARCH: TrustLevel.SOURCE_BOUND_DERIVED,
    Capability.KNOWLEDGE_READ: TrustLevel.SOURCE_BOUND_DERIVED,
    Capability.KNOWLEDGE_COVERAGE: TrustLevel.SOURCE_BOUND_DERIVED,
    Capability.KNOWLEDGE_REVEAL: TrustLevel.SOURCE_ORIGINAL,
}

#: The purpose each of them is invoked under.
PURPOSES: Final[dict[Capability, Purpose]] = {
    Capability.KNOWLEDGE_SEARCH: Purpose.KNOWLEDGE_SEARCH,
    Capability.KNOWLEDGE_READ: Purpose.KNOWLEDGE_READ,
    Capability.KNOWLEDGE_COVERAGE: Purpose.STATUS_OBSERVATION,
    Capability.KNOWLEDGE_REVEAL: Purpose.CAPTURE_REVIEW,
}

#: Statement builders that write. The same five
#: `test_derivation_proposes_and_never_promotes.py` names, for the same reason:
#: "does this expression write" is not decidable in general, and these are what
#: this repository's persistence layer uses.
WRITERS: Final = frozenset({"insert", "update", "delete", "pg_insert"})


def test_the_family_this_guard_covers_is_the_domains_own() -> None:
    """The mapping covers every `knowledge.*` capability, not a chosen subset.

    Derived from `Capability` rather than written out, so a new member of the
    `knowledge.` family arrives here as a failing row instead of being silently
    unexamined — which is how one comes to return an unlabelled derived record.
    """
    family = {capability for capability in Capability if capability.value.startswith("knowledge.")}
    assert set(EXPECTED_TRUST) == family
    assert set(PURPOSES) == family
    assert len(family) == 4


def command_for(capability: Capability, scene: Scene) -> Command:
    """One executable request per capability, over a world staged for it."""
    match capability:
        case Capability.KNOWLEDGE_SEARCH:
            scene.world.searches[scene.enrollment.enrollment_id] = staged_search(scene)
            return SearchKnowledge(
                enrollment_id=scene.enrollment.enrollment_id, query="the alpha report"
            )
        case Capability.KNOWLEDGE_READ:
            record = staged_record(scene, text="the alpha report, by subject-alpha")
            return ReadKnowledge(
                enrollment_id=scene.enrollment.enrollment_id, knowledge_id=record.knowledge_id
            )
        case Capability.KNOWLEDGE_COVERAGE:
            return GetCorpusCoverage()
        case _:
            capture = staged_capture(scene, text="a synthetic note by subject-alpha")
            return RevealSubject(subject_id=capture.capture_id)


def run(scene: Scene, capability: Capability) -> ResponseEnvelope:
    service = build_service(scene.world, scene.providers)
    return service.invoke(
        metadata_for(capability, PURPOSES[capability], scene.principal),
        command_for(capability, scene),
        principal=scene.principal,
    )


@pytest.mark.parametrize("capability", sorted(EXPECTED_TRUST), ids=lambda c: c.value)
def test_every_knowledge_capability_states_the_trust_level_its_content_carries(
    scene: Scene, capability: Capability
) -> None:
    """Layer 4, by execution rather than by reading the source for a constant.

    A scan for `TrustLevel.SOURCE_BOUND_DERIVED` would pass over a branch that
    never runs. This drives the real `ApplicationService` over in-memory
    repositories and reads the envelope it produced.
    """
    envelope = run(scene, capability)
    assert envelope.error is None, envelope.error
    assert envelope.disclosure is not None
    assert envelope.disclosure.trust.level is EXPECTED_TRUST[capability]
    assert envelope.disclosure.trust.basis, (
        "a trust level with no basis says how much to believe an answer without "
        "saying why, which is the assertion this envelope exists to replace"
    )


def test_a_stored_extraction_read_back_still_carries_its_derived_provenance(
    scene: Scene,
) -> None:
    """The record itself, not only the envelope beside it.

    `knowledge.read` returns provenance in the payload, and that is where a
    caller storing the answer would take the discriminator from. A disclosure a
    consumer discards must not be the only place the record says what it is.
    """
    record = staged_record(scene, text="the alpha report, by subject-alpha")
    service = build_service(scene.world, scene.providers)
    envelope = service.invoke(
        metadata_for(Capability.KNOWLEDGE_READ, Purpose.KNOWLEDGE_READ, scene.principal),
        ReadKnowledge(
            enrollment_id=scene.enrollment.enrollment_id, knowledge_id=record.knowledge_id
        ),
        principal=scene.principal,
    )
    assert envelope.result is not None
    provenance = envelope.result["provenance"]
    assert isinstance(provenance, dict)
    assert provenance["trust_level"] == TrustLevel.SOURCE_BOUND_DERIVED.value
    assert provenance["extractor"] and provenance["extractor_version"]


@pytest.mark.parametrize(
    "level",
    [TrustLevel.SOURCE_ORIGINAL, TrustLevel.MODEL_PROPOSED],
    ids=lambda level: level.value,
)
def test_the_domain_refuses_an_extraction_outcome_that_is_not_derived(
    level: TrustLevel,
) -> None:
    """Layer 1, over both wrong answers rather than the obvious one.

    `model_proposed` is the case that matters for section 24: model output is a
    *proposal*, and an extraction outcome carrying it would be a model
    contribution filed where the extraction plane keeps source-bound text.
    """
    with pytest.raises(ValueError, match="never source original"):
        ExtractionOutcome(
            status=ExtractionStatus.QUARANTINED,
            provenance=Provenance(
                source_id="src_alpha0000001",
                source_object_id="obj_alpha0000001",
                version_id="ver_alpha0000001",
                extractor="my_pa.text",
                extractor_version="1",
                observed_at=SOME_MOMENT,
                processed_at=SOME_MOMENT,
                trust_level=level,
            ),
            media_type=None,
            quarantine_reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )


def test_the_storage_refuses_it_too_and_defaults_to_the_truthful_value() -> None:
    """Layer 2, read off the live declaration rather than off `tables.py` as text."""
    constraints = {
        constraint.name: str(getattr(constraint, "sqltext", ""))
        for constraint in extractions.constraints
        if constraint.name
    }
    assert "derived_text_is_never_source_original" in constraints, (
        "the extraction table no longer refuses a source-original trust level at the "
        "server. Section 24's discriminator would then be held by application code "
        "alone, which is the layer a second writer does not run through"
    )
    assert constraints["derived_text_is_never_source_original"] == (
        f"trust_level = '{TrustLevel.SOURCE_BOUND_DERIVED.value}'"
    )
    default = extractions.c.trust_level.server_default
    assert default is not None, (
        "a writer that omits `trust_level` must still write the derived value; with "
        "no default the column would simply refuse, which is safe, but the default "
        "is what makes forgetting it harmless rather than an outage"
    )
    assert TrustLevel.SOURCE_BOUND_DERIVED.value in str(default.arg)
    assert extractions.c.trust_level.nullable is False


def test_the_read_module_builds_no_write_at_all() -> None:
    """Nothing on this plane can promote its own output on the way out.

    Section 24's failure is a derivation writing its output back as established
    fact, and it is easy to open by accident because it looks like a read. Held
    structurally: the module every knowledge-plane read goes through builds none
    of the five statement kinds that write.
    """
    tree = ast.parse(READS.read_text(encoding="utf-8"), filename=str(READS))
    called = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    } | {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "select" in called, "the guard is not reading a module that queries anything"
    writes = sorted(called & WRITERS)
    assert writes == [], (
        f"{READS.name} builds {writes}. Every capability that reads the extraction "
        "plane goes through this module; a write here is a read path that can change "
        "state, which is the shape section 24 forbids"
    )
