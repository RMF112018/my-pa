"""The CP-CRL-05 census delta is the lifecycle authority, not a new sink.

At the campaign base the capture census was 56 modules. The three modules added
by CRL-WP-03 are the lifecycle command, its domain vocabulary, and its
repository. None of them is a downstream publication consumer. The repository
is where `require_active_capture_roots` lives.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DELTA = (
    "src/my_pa/application/capture_lifecycle.py",
    "src/my_pa/domain/capture/lifecycle.py",
    "src/my_pa/infrastructure/persistence/capture_lifecycle.py",
)


def test_the_lifecycle_modules_are_the_census_delta_and_not_sinks() -> None:
    repository = (ROOT / DELTA[2]).read_text(encoding="utf-8")
    domain = (ROOT / DELTA[1]).read_text(encoding="utf-8")
    command = (ROOT / DELTA[0]).read_text(encoding="utf-8")
    assert "def require_active_capture_roots(" in repository
    assert "sqlalchemy" not in domain
    assert "def transition_capture(" in command
    for relative in DELTA:
        assert (ROOT / relative).is_file()


def test_the_capture_census_at_this_head_is_the_three_lifecycle_modules() -> None:
    """Re-run of the section (c) census.

    Base was 56 modules. The three lifecycle modules made 59. This head is 61:
    `adapters/remote_request.py` names `capture_id` in its idempotency-stamp
    comment, and RE-DBH-01 `infrastructure/database/record_event_roles.py`
    names `capture_versions` in its bounded runtime read inventory. Neither
    module calls the publication fence. KLP-WP-01 makes it 62:
    `domain/knowledge_assertion/evidence.py` declares the `capture_id` of a
    capture-shaped Knowledge evidence identity (a pure value object; it reads
    no Capture row and calls no fence). KLP-WP-03 makes it 64:
    `application/knowledge_assertions.py` maps a create's cited `capture_id`
    into the repository request (it reads no Capture row), and
    `infrastructure/persistence/knowledge_assertions.py` is a publication
    consumer: an explicit create links capture evidence, so it calls the fence
    exactly once (R6 8.1 C4c) and withholds an archived root remotely.
    """
    import re

    pattern = re.compile(
        r"capture_versions|capture_spans|capture_proposals|\bcaptures\b|"
        r"capture_span_id|capture_id|src_productownedcapture"
    )
    hits = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "src").rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    )
    assert len(hits) == 64
    assert set(DELTA) <= set(hits)
    assert "src/my_pa/adapters/remote_request.py" in hits
    assert "src/my_pa/infrastructure/database/record_event_roles.py" in hits
    assert "src/my_pa/domain/knowledge_assertion/evidence.py" in hits
    roles = (ROOT / "src/my_pa/infrastructure/database/record_event_roles.py").read_text(
        encoding="utf-8"
    )
    assert "require_active_capture_roots" not in roles
    remote = (ROOT / "src/my_pa/adapters/remote_request.py").read_text(encoding="utf-8")
    assert "require_active_capture_roots" not in remote
    knowledge = (ROOT / "src/my_pa/application/knowledge_assertions.py").read_text(encoding="utf-8")
    assert "require_active_capture_roots" not in knowledge
    persistence = (ROOT / "src/my_pa/infrastructure/persistence/knowledge_assertions.py").read_text(
        encoding="utf-8"
    )
    assert persistence.count("require_active_capture_roots(") == 1


def test_class_3_paths_do_not_call_the_publication_fence() -> None:
    """C-19, C-20, C-22 and C-23 stay exemptions. C-19 has no new derivation reader."""
    exempt = (
        "src/my_pa/infrastructure/jobs/reenrichment.py",
        "src/my_pa/infrastructure/persistence/entity_reenrichment.py",
        "src/my_pa/application/entity_reenrichment.py",
        "src/my_pa/application/identity_correction.py",
        "src/my_pa/application/context/service.py",
    )
    for relative in exempt:
        assert "require_active_capture_roots" not in (ROOT / relative).read_text(encoding="utf-8")
    service = (ROOT / "src/my_pa/application/service.py").read_text(encoding="utf-8")
    feedback = service.split("def _context_feedback(", 1)[1].split("\n    def ", 1)[0]
    assert "require_active_capture_roots" not in feedback
    readers = {
        str(path.relative_to(ROOT))
        for path in (ROOT / "src").rglob("*.py")
        if "context_runs" in path.read_text(encoding="utf-8")
    }
    # The writer, its port, the schema, and the re-enrichment docstring. None of
    # these reads a stored run back as input to a new derivation (C-19).
    assert readers == {
        "src/my_pa/application/context/service.py",
        "src/my_pa/contracts/ports.py",
        "src/my_pa/infrastructure/gsqs_b0_evaluation.py",
        "src/my_pa/infrastructure/jobs/reenrichment.py",
        "src/my_pa/infrastructure/persistence/context_runs.py",
        "src/my_pa/infrastructure/persistence/tables.py",
        "src/my_pa/infrastructure/persistence/unit_of_work.py",
    }
    reenrichment = (ROOT / "src/my_pa/infrastructure/jobs/reenrichment.py").read_text(
        encoding="utf-8"
    )
    assert "context_runs" in reenrichment.split("def ", 1)[0]
    assert "context_runs" not in reenrichment.split("def ", 1)[1]


def test_span_evidence_has_no_public_read_model() -> None:
    """P-8 and P-9: capture_span_id stays off public read contracts.

    The entity-proposal receipt still names the span (P-7) and is not overlaid.
    Memory proposal answers publish a count, not the span.
    """
    offenders = sorted(
        str(path.relative_to(ROOT))
        for path in (ROOT / "src/my_pa/contracts/v1").rglob("*.py")
        if "capture_span_id" in path.read_text(encoding="utf-8")
    )
    assert offenders == []
    service = (ROOT / "src/my_pa/application/service.py").read_text(encoding="utf-8")
    proposal = service.split("def _entities_proposals_create(", 1)[1].split("\n    def ", 1)[0]
    memory = service.split("def _relationship_memory_propose(", 1)[1].split("\n    def ", 1)[0]
    assert "capture_span_id" in proposal
    assert "capture_lifecycle_state" not in proposal
    assert '"capture_span_id":' not in memory
    repository = (ROOT / "src/my_pa/infrastructure/persistence/capture_lifecycle.py").read_text(
        encoding="utf-8"
    )
    assert "def capture_lifecycle_states(" in repository
    assert "Absent and foreign ids are omitted" in repository
