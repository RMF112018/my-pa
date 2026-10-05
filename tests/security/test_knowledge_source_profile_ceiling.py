"""KLP-WP-04: source-profile ceilings and the no-leak rule of profile maintenance (FAST).

Unmarked (FAST). KLP-AC-062 (ceiling half), KLP-AC-072 and the no-leak part of
KLP-AC-126.

* **KLP-AC-062** -- over the whole grid of profile controls, the server's
  admission policy direct-admits only for an enabled, read-only-proven,
  authoritative, non-disabled profile; a disabled profile is refused
  `source_profile_inactive`, every other posture is queued for Review.
* **KLP-AC-072** -- what profile maintenance can emit is identifiers, digests,
  closed tokens and counts: the operator command's output lines, the
  persistence records it prints, the Record Events maintenance stages
  (`changed_fields` tokens only, metadata only) and the refused audit path.
  Neither the command nor the maintenance code logs or reaches telemetry, and a
  native scope identifier, an excerpt or a checkpoint envelope never appears in
  any of them -- only their hashes.
* **KLP-AC-126 (no-leak part)** -- the discovery commands never render an
  excerpt, an envelope or an idempotency key in their `repr` (the shape logs and
  tracebacks take).

Every identity here is synthetic.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
import inspect
import itertools
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from apps.cli.knowledge_source_profiles import (
    maintenance_lines,
    parse_profile,
    profile_line,
    scope_digest_of,
)
from tests.unit.test_knowledge_assertion_domain import SEEDS, _predicate_from_seed

from my_pa.application.commands import CheckpointKnowledgeDiscovery, SubmitKnowledgeAssertion
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.knowledge_assertion.admission import (
    AdmissionEvidence,
    AdmissionPath,
    DirectAdmissionFacts,
    SourceProfileFacts,
    SubjectResolution,
    decide_direct_admission,
)
from my_pa.domain.knowledge_assertion.provenance import KNOWLEDGE_MUTATION_EVENTS
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeEvidenceAuthority,
    KnowledgeEvidenceIdentityKind,
    KnowledgeEvidenceRole,
    KnowledgeMutationKind,
    KnowledgeOriginSystem,
    KnowledgeReadOnlyProofState,
    KnowledgeSubmissionReason,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence import knowledge_assertions as persistence
from my_pa.infrastructure.persistence.knowledge_assertions import (
    KnowledgeMaintenanceResult,
    KnowledgeSourceProfileRecord,
)
from my_pa.infrastructure.persistence.unit_of_work import _MaintenanceWritesNoAudit

ROOT: Final = Path(__file__).resolve().parents[2]
COMMAND: Final = ROOT / "apps" / "cli" / "knowledge_source_profiles.py"
PERSISTENCE: Final = (
    ROOT / "src" / "my_pa" / "infrastructure" / "persistence" / "knowledge_assertions.py"
)
WHEN: Final = datetime(2026, 10, 5, 12, tzinfo=UTC)
PROFILE: Final = "kdsp_SyntheticCeiling01"
NATIVE_SCOPE: Final = "synthetic-site:finance/board-papers"
EXCERPT: Final = "Synthetic excerpt that must never be echoed."
ENVELOPE: Final = "synthetic-delta-token-abcdef0123456789"


def _facts(profile: SourceProfileFacts) -> DirectAdmissionFacts:
    return DirectAdmissionFacts(
        predicate=_predicate_from_seed(SEEDS["organization.operating_requirement"]),
        profile=profile,
        subject=SubjectResolution.CANONICAL,
        evidence=(
            AdmissionEvidence(
                identity_kind=KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT,
                role=KnowledgeEvidenceRole.DIRECT,
                content_hash="b" * 64,
                source_profile_id=PROFILE,
                origin_system=KnowledgeOriginSystem.SHAREPOINT_DOCUMENTS,
                external_object_id="synthetic-ceiling-doc",
                external_version_id="v1",
            ),
        ),
        candidate_effective_from=None,
        now=WHEN,
    )


# ---- KLP-AC-062: the ceiling grid --------------------------------------------------


@pytest.mark.parametrize(
    ("enabled", "proof", "ceiling", "disabled"),
    list(
        itertools.product(
            (False, True),
            list(KnowledgeReadOnlyProofState),
            list(KnowledgeEvidenceAuthority),
            (False, True),
        )
    ),
)
def test_only_an_enabled_proven_authoritative_live_profile_direct_admits(
    enabled: bool,
    proof: KnowledgeReadOnlyProofState,
    ceiling: KnowledgeEvidenceAuthority,
    disabled: bool,
) -> None:
    decision = decide_direct_admission(
        _facts(
            SourceProfileFacts(
                source_profile_id=PROFILE,
                origin_system=KnowledgeOriginSystem.SHAREPOINT_DOCUMENTS,
                authority_ceiling=ceiling,
                direct_admission_enabled=enabled,
                read_only_proof_state=proof,
                is_synthetic=False,
                disabled=disabled,
            )
        )
    )
    admits = (
        enabled
        and proof is KnowledgeReadOnlyProofState.PROVEN
        and ceiling is KnowledgeEvidenceAuthority.AUTHORITATIVE_SOURCE
        and not disabled
    )
    if disabled:
        assert decision.reason is KnowledgeSubmissionReason.SOURCE_PROFILE_INACTIVE
    elif admits:
        assert decision.path is AdmissionPath.DIRECT_CREATE
    else:
        assert decision.path is AdmissionPath.REVIEW
    assert (decision.path is AdmissionPath.DIRECT_CREATE) == admits


# ---- KLP-AC-072: nothing but hashes, ids, tokens and counts ------------------------


def _record(**changes: object) -> KnowledgeSourceProfileRecord:
    spec = parse_profile(
        {
            "authenticated_client_id": "klp04-synthetic-discovery-client",
            "origin_system": "sharepoint_documents",
            "scope": NATIVE_SCOPE,
            "authority_ceiling": "observed_source",
        },
        discovery_clients=frozenset({"klp04-synthetic-discovery-client"}),
    )
    base = KnowledgeSourceProfileRecord(
        source_profile_id=PROFILE,
        authenticated_client_id=spec.authenticated_client_id,
        origin_system=spec.origin_system.value,
        scope_digest=spec.scope_digest,
        authority_ceiling=spec.authority_ceiling.value,
        direct_admission_enabled=spec.direct_admission_enabled,
        read_only_proof_state=spec.read_only_proof_state.value,
        is_synthetic=False,
        profile_version=1,
        disabled_at=None,
    )
    return dataclasses.replace(base, **changes)  # type: ignore[arg-type]


def test_a_profile_record_and_its_line_hold_the_scope_digest_only() -> None:
    record = _record()
    assert "scope" not in {field.name for field in dataclasses.fields(record)}
    assert record.scope_digest == scope_digest_of(
        KnowledgeOriginSystem.SHAREPOINT_DOCUMENTS, NATIVE_SCOPE
    )
    for action in ("created", "updated", "unchanged", "disabled", "profile"):
        line = profile_line(action, record)
        assert NATIVE_SCOPE not in line
        assert record.scope_digest in line


def test_a_maintenance_result_and_its_lines_hold_ids_and_counts_only() -> None:
    names = {field.name for field in dataclasses.fields(KnowledgeMaintenanceResult)}
    assert names == {"evidence_ref_ids", "mutated_assertion_ids", "remaining", "pending"}
    result = KnowledgeMaintenanceResult(
        evidence_ref_ids=(issue_identifier(IdKind.KNOWLEDGE_EVIDENCE_REF),),
        mutated_assertion_ids=(issue_identifier(IdKind.KNOWLEDGE_ASSERTION),),
        remaining=0,
    )
    lines = maintenance_lines(result)
    assert lines[-1] == "remaining=0"
    assert all(EXCERPT not in line and ENVELOPE not in line for line in lines)


@pytest.mark.parametrize(
    "kind",
    [
        KnowledgeMutationKind.CLASSIFY,
        KnowledgeMutationKind.REVALIDATION_REQUIRED,
        KnowledgeMutationKind.REVALIDATION_CLEARED,
    ],
)
def test_maintenance_events_name_field_tokens_never_content(kind: KnowledgeMutationKind) -> None:
    mapped = KNOWLEDGE_MUTATION_EVENTS[kind]
    assert set(mapped.changed_fields) <= {"classification", "lifecycle"}
    parameters = set(inspect.signature(persistence._stage_knowledge_event).parameters)
    assert parameters.isdisjoint({"excerpt", "value", "text", "envelope", "scope", "content"})


def test_the_maintenance_source_is_a_bounded_internal_token() -> None:
    assert persistence.KNOWLEDGE_MAINTENANCE_SOURCE == "knowledge.source_profiles.maintenance"


def test_maintenance_writes_no_audit_row() -> None:
    with pytest.raises(RuntimeError, match="writes no audit"):
        _MaintenanceWritesNoAudit().record(object())  # type: ignore[arg-type]


@pytest.mark.parametrize("path", [COMMAND, PERSISTENCE], ids=["command", "persistence"])
def test_neither_the_command_nor_the_maintenance_code_logs_or_reaches_telemetry(path: Path) -> None:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    called: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Call):
            func = node.func
            called.add(func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", ""))
    assert not any(
        name.split(".")[0] in {"logging", "structlog", "opentelemetry"} or "telemetry" in name
        for name in imported
    )
    assert called.isdisjoint({"getLogger", "debug", "info", "warning", "exception", "log"})


def test_the_command_prints_only_from_its_line_builders() -> None:
    """Every printed line is built from ids, digests, tokens and counts."""
    source = COMMAND.read_text(encoding="utf-8")
    for forbidden in ("excerpt=", ".excerpt", "private_envelope", "NATIVE_SCOPE", "args.scope"):
        assert forbidden not in source


# ---- KLP-AC-126 (no-leak part) -----------------------------------------------------


def test_discovery_commands_never_render_excerpts_envelopes_or_keys() -> None:
    submit = SubmitKnowledgeAssertion(
        source_profile_id=PROFILE,
        external_run_id="synthetic-run",
        external_candidate_id="synthetic-candidate",
        subject_kind="entity",  # type: ignore[arg-type]
        subject_id="ent_SyntheticOrg0001",
        predicate_code="organization.operating_requirement",
        value="Synthetic value",
        evidence=(
            {
                "identity_kind": "external_object",
                "external_object_id": "synthetic-doc",
                "content_hash": hashlib.sha256(b"x").hexdigest(),
                "excerpt": EXCERPT,
                "role": "direct",
            },
        ),
    )
    checkpoint = CheckpointKnowledgeDiscovery(
        source_profile_id=PROFILE,
        expected_version=0,
        external_run_id="synthetic-run",
        submitted_candidate_count=1,
        checkpoint_kind="delta_token",  # type: ignore[arg-type]
        private_envelope=ENVELOPE,
        idempotency_key="synthetic-checkpoint-key",
    )
    assert EXCERPT not in repr(submit)
    assert ENVELOPE not in repr(checkpoint)
    assert "synthetic-checkpoint-key" not in repr(checkpoint)
