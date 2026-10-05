"""KLP-WP-04: discovery source profiles through the guarded operator command (DB).

KLP-AC-061, KLP-AC-062 and KLP-AC-090 (repository half). Marked `database`
(auto `database_clone`), routed to `database-current-head`.

Every profile here is written by `apps/cli/knowledge_source_profiles.py`
(`run` against a test runtime: this database, a fresh synthetic Principal, a
fixed clock and an explicit discovery allowlist). Direct SQL appears only for
the refused writes themselves (CHECK / trigger proofs) and for the Knowledge
rows WP-04 slice B1 has no writer for (external evidence and its links).

* KLP-AC-061: a profile binds the Principal (this process's, never a file
  field), the client, the origin system, the *hashed* scope -- the native
  scope identifier is stored nowhere and printed nowhere -- and the authority
  ceiling; re-applying is idempotent, a control change bumps the version, the
  ceiling is immutable, and one active profile exists per binding.
* KLP-AC-062: CHECK `knowledge_profile_direct_admission_needs_proof` refuses
  direct admission without proof, an authoritative ceiling and an enabled
  profile; the policy the server applies to a stored profile row never
  direct-admits for a disabled or non-proven one.
* KLP-AC-090: `disable` is terminal (trigger), clears direct admission, and
  deletes and rewrites no Knowledge row; the next submission is refused
  `source_profile_inactive` by the policy (the submit handler is slice B2).

Every identity here is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from apps.cli.knowledge_source_profiles import (
    EXIT_OK,
    EXIT_REFUSED,
    Runtime,
    run_knowledge_source_profiles,
    scope_digest_of,
)
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError

from my_pa.bootstrap.knowledge_discovery_profiles import KnowledgeAllowlists, allowlist_fingerprint
from my_pa.domain.knowledge_assertion.admission import (
    AdmissionEvidence,
    AdmissionPath,
    DirectAdmissionFacts,
    SourceProfileFacts,
    SubjectResolution,
    decide_direct_admission,
)
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeEvidenceAuthority,
    KnowledgeEvidenceIdentityKind,
    KnowledgeEvidenceRole,
    KnowledgeOriginSystem,
    KnowledgeReadOnlyProofState,
    KnowledgeSubmissionReason,
)
from my_pa.infrastructure.persistence.tables import knowledge_discovery_source_profiles
from tests.database.test_knowledge_assertion_repository import (
    KnowledgeRuntime,
    counts,
    new_principal,
)
from tests.security.test_knowledge_assertion_disclosure import link, seed_external
from tests.unit.test_knowledge_assertion_domain import SEEDS, _predicate_from_seed

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

WHEN: Final = datetime(2026, 10, 5, 12, tzinfo=UTC)
CLIENT: Final = "klp04-synthetic-discovery-client"
OTHER_CLIENT: Final = "klp04-synthetic-discovery-client-2"
#: A native scope identifier: hashed by the command, stored and printed nowhere.
NATIVE_SCOPE: Final = "synthetic-mailbox:ops-team/Inbox/Vendors"


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[KnowledgeRuntime]:
    composed = KnowledgeRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def cli_runtime(
    engine: Engine, principal: str, *, discovery: frozenset[str] | None = None
) -> Runtime:
    return Runtime(
        engine=engine,
        principal_id=principal,
        allowlists=KnowledgeAllowlists(
            discovery=frozenset({CLIENT, OTHER_CLIENT}) if discovery is None else discovery,
            operator_review=frozenset(),
            chatllm_gateway=frozenset(),
        ),
        clock=lambda: WHEN,
    )


def run_cli(engine: Engine, principal: str, *argv: str) -> tuple[int, list[str]]:
    lines: list[str] = []
    code = run_knowledge_source_profiles(
        list(argv), cli_runtime(engine, principal), out=lines.append
    )
    return code, lines


def profile_file(tmp_path: Path, *profiles: dict[str, object]) -> str:
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({"version": 1, "profiles": list(profiles)}), encoding="utf-8")
    return str(path)


def entry(**changes: object) -> dict[str, object]:
    base: dict[str, object] = {
        "authenticated_client_id": CLIENT,
        "origin_system": "outlook_mail",
        "scope": NATIVE_SCOPE,
        "authority_ceiling": "observed_source",
    }
    base.update(changes)
    return {key: value for key, value in base.items() if value is not None}


def provision(engine: Engine, principal: str, tmp_path: Path, **changes: object) -> str:
    code, lines = run_cli(
        engine, principal, "apply", "--file", profile_file(tmp_path, entry(**changes))
    )
    assert code == EXIT_OK, lines
    return next(word for line in lines for word in line.split() if word.startswith("kdsp_"))


def _rows(engine: Engine, principal: str) -> list[dict[str, Any]]:
    p = knowledge_discovery_source_profiles
    with engine.connect() as connection:
        return [
            dict(row._mapping)
            for row in connection.execute(
                select(p).where(p.c.principal_id == principal).order_by(p.c.created_at)
            )
        ]


def _profile_facts(row: dict[str, Any]) -> SourceProfileFacts:
    return SourceProfileFacts(
        source_profile_id=row["source_profile_id"],
        origin_system=KnowledgeOriginSystem(row["origin_system"]),
        authority_ceiling=KnowledgeEvidenceAuthority(row["authority_ceiling"]),
        direct_admission_enabled=row["direct_admission_enabled"],
        read_only_proof_state=KnowledgeReadOnlyProofState(row["read_only_proof_state"]),
        is_synthetic=row["is_synthetic"],
        disabled=row["disabled_at"] is not None,
    )


def _decide(row: dict[str, Any]) -> AdmissionPath:
    """The policy applied to a stored profile row, with every other fact admitting."""
    return decide_direct_admission(
        DirectAdmissionFacts(
            predicate=_predicate_from_seed(SEEDS["organization.operating_requirement"]),
            profile=_profile_facts(row),
            subject=SubjectResolution.CANONICAL,
            evidence=(
                AdmissionEvidence(
                    identity_kind=KnowledgeEvidenceIdentityKind.EXTERNAL_OBJECT,
                    role=KnowledgeEvidenceRole.DIRECT,
                    content_hash="a" * 64,
                    source_profile_id=row["source_profile_id"],
                    origin_system=KnowledgeOriginSystem(row["origin_system"]),
                    external_object_id="synthetic-object",
                    external_version_id="v1",
                ),
            ),
            candidate_effective_from=None,
            now=WHEN,
        )
    ).path


# ---- KLP-AC-061 -----------------------------------------------------------------------


def test_a_profile_binds_principal_client_origin_hashed_scope_and_ceiling(
    runtime: KnowledgeRuntime, tmp_path: Path
) -> None:
    principal = new_principal()
    code, lines = run_cli(
        runtime.engine, principal, "apply", "--file", profile_file(tmp_path, entry())
    )
    assert code == EXIT_OK, lines
    (row,) = _rows(runtime.engine, principal)
    assert row["principal_id"] == principal
    assert row["authenticated_client_id"] == CLIENT
    assert row["origin_system"] == "outlook_mail"
    assert row["scope_digest"] == scope_digest_of(KnowledgeOriginSystem.OUTLOOK_MAIL, NATIVE_SCOPE)
    assert row["authority_ceiling"] == "observed_source"
    assert (row["direct_admission_enabled"], row["read_only_proof_state"]) == (False, "unproven")
    assert (row["is_synthetic"], row["profile_version"], row["disabled_at"]) == (False, 1, None)
    # The native scope identifier is stored in no column and printed on no line.
    assert all(NATIVE_SCOPE not in str(value) for value in row.values())
    assert all(NATIVE_SCOPE not in line for line in lines)
    fingerprint = allowlist_fingerprint(cli_runtime(runtime.engine, principal).allowlists)
    assert lines[0] == f"allowlist_fingerprint {fingerprint}"
    assert any(line.startswith("created") for line in lines)


def test_a_synthetic_origin_is_a_synthetic_profile(
    runtime: KnowledgeRuntime, tmp_path: Path
) -> None:
    principal = new_principal()
    provision(runtime.engine, principal, tmp_path, origin_system="synthetic")
    (row,) = _rows(runtime.engine, principal)
    assert row["is_synthetic"] is True


def test_reapplying_is_idempotent_and_a_control_change_bumps_the_version(
    runtime: KnowledgeRuntime, tmp_path: Path
) -> None:
    principal = new_principal()
    engine = runtime.engine
    first = provision(engine, principal, tmp_path, authority_ceiling="authoritative_source")
    code, lines = run_cli(
        engine,
        principal,
        "apply",
        "--file",
        profile_file(tmp_path, entry(authority_ceiling="authoritative_source")),
    )
    assert code == EXIT_OK
    assert any(line.startswith("unchanged") for line in lines)
    code, lines = run_cli(
        engine,
        principal,
        "provision",
        "--file",
        profile_file(
            tmp_path,
            entry(
                authority_ceiling="authoritative_source",
                read_only_proof_state="proven",
                direct_admission_enabled=True,
            ),
        ),
    )
    assert code == EXIT_OK, lines
    (row,) = _rows(engine, principal)
    assert row["source_profile_id"] == first
    assert (row["profile_version"], row["direct_admission_enabled"]) == (2, True)
    assert row["read_only_proof_state"] == "proven"
    assert row["updated_at"] >= row["created_at"]


def test_the_authority_ceiling_of_an_active_profile_is_immutable(
    runtime: KnowledgeRuntime, tmp_path: Path
) -> None:
    principal = new_principal()
    provision(runtime.engine, principal, tmp_path)
    before = _rows(runtime.engine, principal)
    code, lines = run_cli(
        runtime.engine,
        principal,
        "apply",
        "--file",
        profile_file(tmp_path, entry(authority_ceiling="authoritative_source")),
    )
    assert code == EXIT_REFUSED
    assert "immutable" in lines[-1]
    assert _rows(runtime.engine, principal) == before
    with pytest.raises(DBAPIError), runtime.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE knowledge.knowledge_discovery_source_profiles SET "
                "authority_ceiling = 'authoritative_source', profile_version = profile_version + 1 "
                "WHERE principal_id = :p"
            ),
            {"p": principal},
        )


def test_a_refused_document_writes_nothing(runtime: KnowledgeRuntime, tmp_path: Path) -> None:
    """One bad entry refuses the whole file before any row is written."""
    principal = new_principal()
    code, lines = run_cli(
        runtime.engine,
        principal,
        "apply",
        "--file",
        profile_file(tmp_path, entry(), entry(authenticated_client_id="klp04-unbound-client")),
    )
    assert code == EXIT_REFUSED
    assert "KNOWLEDGE_DISCOVERY_OAUTH_CLIENT_IDS" in lines[-1]
    assert _rows(runtime.engine, principal) == []


def test_one_active_profile_per_binding_and_principal_isolation(
    runtime: KnowledgeRuntime, tmp_path: Path
) -> None:
    principal, other = new_principal(), new_principal()
    profile = provision(runtime.engine, principal, tmp_path)
    provision(runtime.engine, other, tmp_path)
    (row,) = _rows(runtime.engine, principal)
    with (
        pytest.raises(DBAPIError, match="knowledge_profile_one_active_scope"),
        runtime.engine.begin() as c,
    ):
        c.execute(
            text(
                "INSERT INTO knowledge.knowledge_discovery_source_profiles (principal_id, "
                "source_profile_id, authenticated_client_id, origin_system, scope_digest, "
                "authority_ceiling, read_only_proof_state, is_synthetic, created_at, updated_at) "
                "VALUES (:p, 'kdsp_SyntheticDuplicate1', :c, 'outlook_mail', :d, "
                "'observed_source', 'unproven', false, now(), now())"
            ),
            {"p": principal, "c": CLIENT, "d": row["scope_digest"]},
        )
    code, lines = run_cli(runtime.engine, principal, "list")
    assert code == EXIT_OK
    listed = [line for line in lines if line.startswith("profile ")]
    assert len(listed) == 1
    assert profile in listed[0]
    # Another Principal's profile is invisible to and undisableable by this one.
    (foreign,) = _rows(runtime.engine, other)
    code, _ = run_cli(
        runtime.engine, principal, "disable", "--source-profile-id", foreign["source_profile_id"]
    )
    assert code == EXIT_REFUSED
    assert _rows(runtime.engine, other)[0]["disabled_at"] is None


# ---- KLP-AC-062 -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("proof", "ceiling"),
    [
        ("unproven", "authoritative_source"),
        ("revoked", "authoritative_source"),
        ("proven", "observed_source"),
    ],
)
def test_the_check_refuses_direct_admission_without_proof_and_ceiling(
    runtime: KnowledgeRuntime, proof: str, ceiling: str
) -> None:
    principal = new_principal()
    with (
        pytest.raises(DBAPIError, match="knowledge_profile_direct_admission_needs_proof"),
        runtime.engine.begin() as connection,
    ):
        connection.execute(
            text(
                "INSERT INTO knowledge.knowledge_discovery_source_profiles (principal_id, "
                "source_profile_id, authenticated_client_id, origin_system, scope_digest, "
                "authority_ceiling, direct_admission_enabled, read_only_proof_state, "
                "is_synthetic, created_at, updated_at) VALUES (:p, 'kdsp_SyntheticNoProof1', "
                ":c, 'sharepoint_documents', :d, :ceiling, true, :proof, false, now(), now())"
            ),
            {"p": principal, "c": CLIENT, "d": "e" * 64, "ceiling": ceiling, "proof": proof},
        )


def test_a_proven_profile_cannot_lose_its_proof_while_admitting_directly(
    runtime: KnowledgeRuntime, tmp_path: Path
) -> None:
    principal = new_principal()
    provision(
        runtime.engine,
        principal,
        tmp_path,
        origin_system="sharepoint_documents",
        authority_ceiling="authoritative_source",
        read_only_proof_state="proven",
        direct_admission_enabled=True,
    )
    with (
        pytest.raises(DBAPIError, match="knowledge_profile_direct_admission_needs_proof"),
        runtime.engine.begin() as connection,
    ):
        connection.execute(
            text(
                "UPDATE knowledge.knowledge_discovery_source_profiles SET "
                "read_only_proof_state = 'revoked', profile_version = profile_version + 1 "
                "WHERE principal_id = :p"
            ),
            {"p": principal},
        )


def test_only_an_enabled_proven_authoritative_stored_profile_direct_admits(
    runtime: KnowledgeRuntime, tmp_path: Path
) -> None:
    principal = new_principal()
    engine = runtime.engine
    provision(engine, principal, tmp_path, origin_system="sharepoint_documents")
    (unproven,) = _rows(engine, principal)
    assert _decide(unproven) is AdmissionPath.REVIEW
    code, lines = run_cli(
        engine,
        principal,
        "apply",
        "--file",
        profile_file(
            tmp_path,
            entry(
                origin_system="sharepoint_documents",
                scope="synthetic-site:projects/library",
                authority_ceiling="authoritative_source",
                read_only_proof_state="proven",
                direct_admission_enabled=True,
            ),
        ),
    )
    assert code == EXIT_OK, lines
    proven = next(row for row in _rows(engine, principal) if row["direct_admission_enabled"])
    assert _decide(proven) is AdmissionPath.DIRECT_CREATE
    code, _ = run_cli(
        engine, principal, "disable", "--source-profile-id", proven["source_profile_id"]
    )
    assert code == EXIT_OK
    disabled = next(
        row
        for row in _rows(engine, principal)
        if row["source_profile_id"] == proven["source_profile_id"]
    )
    assert disabled["direct_admission_enabled"] is False
    assert _decide(disabled) is AdmissionPath.REFUSE


# ---- KLP-AC-090 -----------------------------------------------------------------------


def test_disable_is_terminal_and_deletes_or_rewrites_no_knowledge_row(
    runtime: KnowledgeRuntime, tmp_path: Path
) -> None:
    principal = new_principal()
    engine = runtime.engine
    profile = provision(engine, principal, tmp_path)
    created = runtime.create(principal, "klp04-disable-kept")
    evidence = seed_external(engine, principal, profile, object_id="synthetic-kept-object")
    link(engine, principal, created, evidence)
    before = counts(engine, principal)
    with engine.connect() as connection:
        snapshot = connection.execute(
            text(
                "SELECT a.version, a.lifecycle, a.classification, e.source_classification, "
                "e.availability_state FROM knowledge.knowledge_assertions a, "
                "knowledge.knowledge_evidence_refs e WHERE a.assertion_id = :a "
                "AND e.evidence_ref_id = :e"
            ),
            {"a": created["assertion_id"], "e": evidence},
        ).one()

    code, lines = run_cli(engine, principal, "disable", "--source-profile-id", profile)
    assert code == EXIT_OK, lines
    assert any("source_profile_inactive" in line for line in lines)
    (row,) = _rows(engine, principal)
    assert row["disabled_at"] == WHEN
    assert (row["direct_admission_enabled"], row["profile_version"]) == (False, 2)
    assert counts(engine, principal) == before
    with engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT a.version, a.lifecycle, a.classification, e.source_classification, "
                    "e.availability_state FROM knowledge.knowledge_assertions a, "
                    "knowledge.knowledge_evidence_refs e WHERE a.assertion_id = :a "
                    "AND e.evidence_ref_id = :e"
                ),
                {"a": created["assertion_id"], "e": evidence},
            ).one()
            == snapshot
        )
    # Terminal: a second disable changes nothing; the row cannot be re-enabled or deleted.
    code, _ = run_cli(engine, principal, "disable", "--source-profile-id", profile)
    assert code == EXIT_REFUSED
    for statement in (
        "UPDATE knowledge.knowledge_discovery_source_profiles SET disabled_at = NULL, "
        "profile_version = profile_version + 1 WHERE source_profile_id = :s",
        "DELETE FROM knowledge.knowledge_discovery_source_profiles WHERE source_profile_id = :s",
    ):
        with pytest.raises(DBAPIError), engine.begin() as connection:
            connection.execute(text(statement), {"s": profile})
    # Submissions on it are refused `source_profile_inactive` by the policy.
    decision = decide_direct_admission(
        DirectAdmissionFacts(
            predicate=_predicate_from_seed(SEEDS["policy.requirement"]),
            profile=_profile_facts(_rows(engine, principal)[0]),
            subject=SubjectResolution.CANONICAL,
            evidence=(),
            candidate_effective_from=None,
            now=WHEN,
        )
    )
    assert decision.reason is KnowledgeSubmissionReason.SOURCE_PROFILE_INACTIVE
    # Re-enabling means provisioning a new profile row for the same binding.
    renewed = provision(engine, principal, tmp_path)
    assert renewed != profile
    # Both rows share the fixed clock, so their listing order is by random id:
    # compare the set of states, not their order (slice B2 de-flake).
    states = {
        row["source_profile_id"]: row["disabled_at"] is None for row in _rows(engine, principal)
    }
    assert states == {profile: False, renewed: True}


# ---- seal rotation: redact-sealed (R6 section 7 step 3; end to end in slice B3) ------


def _seal_request(
    engine: Engine, principal: str, profile: str, *, seal: int, key: str, envelope: str
) -> str:
    """Setup only: one completed, advanced checkpoint request sealed at `seal`.

    The checkpoint handler is slice B3; the ledger row is written the only way
    the lifecycle trigger admits -- reserved, then completed -- in one
    transaction.
    """
    row = next(r for r in _rows(engine, principal) if r["source_profile_id"] == profile)
    request = f"kdcpr_Synthetic{key}"
    checkpoint = f"kdcp_Synthetic{key}"
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.knowledge_discovery_checkpoints (principal_id, "
                "checkpoint_id, source_profile_id, authenticated_client_id, scope_digest, "
                "version, checkpoint_kind, private_envelope, seal_version, envelope_mac, "
                "external_run_id, created_at, updated_at) VALUES (:p, :cp, :s, :c, :d, 1, "
                "'delta_token', :env, :seal, :mac, 'synthetic-run', now(), now())"
            ),
            {
                "p": principal,
                "cp": checkpoint,
                "s": profile,
                "c": row["authenticated_client_id"],
                "d": row["scope_digest"],
                "env": envelope,
                "seal": seal,
                "mac": "c" * 64,
            },
        )
        connection.execute(
            text(
                "INSERT INTO knowledge.knowledge_discovery_checkpoint_requests (principal_id, "
                "checkpoint_request_id, authenticated_client_id, source_profile_id, "
                "scope_digest, external_run_id, submitted_candidate_count, expected_version, "
                "idempotency_key, request_digest, state, created_at) VALUES (:p, :r, :c, :s, "
                ":d, 'synthetic-run', 0, 0, :k, :rd, 'reserved', now())"
            ),
            {
                "p": principal,
                "r": request,
                "c": row["authenticated_client_id"],
                "s": profile,
                "d": row["scope_digest"],
                "k": f"synthetic-key-{key}",
                "rd": "d" * 64,
            },
        )
        connection.execute(
            text(
                "UPDATE knowledge.knowledge_discovery_checkpoint_requests SET state = "
                "'completed', result_outcome = 'advanced', result_reason = 'advanced', "
                "result_checkpoint_id = :cp, result_checkpoint_version = 1, "
                "result_checkpoint_kind = 'delta_token', result_private_envelope = :env, "
                "result_seal_version = :seal, result_envelope_mac = :mac, completed_at = now() "
                "WHERE checkpoint_request_id = :r"
            ),
            {"cp": checkpoint, "env": envelope, "seal": seal, "mac": "e" * 64, "r": request},
        )
    return request


def _request(engine: Engine, request: str) -> tuple[Any, ...]:
    with engine.connect() as connection:
        return tuple(
            connection.execute(
                text(
                    "SELECT result_private_envelope, result_envelope_mac, private_token_redacted, "
                    "result_seal_version, result_outcome FROM "
                    "knowledge.knowledge_discovery_checkpoint_requests "
                    "WHERE checkpoint_request_id = :r"
                ),
                {"r": request},
            ).one()
        )


def test_redact_sealed_redacts_every_envelope_below_the_seal_and_only_those(
    runtime: KnowledgeRuntime, tmp_path: Path
) -> None:
    principal, other = new_principal(), new_principal()
    engine = runtime.engine
    old_profile = provision(engine, principal, tmp_path, scope="synthetic-scope:old")
    new_profile = provision(engine, principal, tmp_path, scope="synthetic-scope:new")
    foreign_profile = provision(engine, other, tmp_path, scope="synthetic-scope:foreign")
    old = _seal_request(
        engine, principal, old_profile, seal=1, key="Old00001", envelope="synthetic-token-old"
    )
    current = _seal_request(
        engine, principal, new_profile, seal=2, key="New00001", envelope="synthetic-token-new"
    )
    foreign = _seal_request(
        engine, other, foreign_profile, seal=1, key="Foreign1", envelope="synthetic-token-other"
    )

    code, lines = run_cli(engine, principal, "redact-sealed", "--below-seal", "2")
    assert (code, lines) == (EXIT_OK, ["redacted          1"])
    assert _request(engine, old) == (None, None, True, 1, "advanced")
    assert _request(engine, current) == ("synthetic-token-new", "e" * 64, False, 2, "advanced")
    assert _request(engine, foreign)[0] == "synthetic-token-other"
    # Idempotent, and it never prints a token.
    code, lines = run_cli(engine, principal, "redact-sealed", "--below-seal", "2")
    assert (code, lines) == (EXIT_OK, ["redacted          0"])
    code, lines = run_cli(engine, principal, "redact-sealed", "--below-seal", "0")
    assert code == EXIT_REFUSED
