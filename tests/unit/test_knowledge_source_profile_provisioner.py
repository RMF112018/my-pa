"""KLP-WP-04: the source-profile provisioner refuses before it writes (FAST, unmarked).

KLP-AC-063, KLP-AC-064 and KLP-AC-065 (repository halves; the runtime halves are
KLP-AC-158/159/163). The profile document is validated by the pure
`parse_profiles` of `apps/cli/knowledge_source_profiles.py`, which runs before
any database connection is opened, so every refusal below writes nothing.

* KLP-AC-063 / 064: `outlook_mail` and `sharepoint_documents` profiles (and
  every other origin) cannot be `direct_admission_enabled` unless
  `read_only_proof_state = proven` -- and the ceiling is authoritative, as the
  CHECK `knowledge_profile_direct_admission_needs_proof` (also asserted here
  against the committed matrix DDL text) requires.
* KLP-AC-065: the committed `ops/knowledge-source-profiles/initial.json`
  contains no OneDrive profile, `origin_system` has no OneDrive token, and the
  provisioner refuses any OneDrive spelling.

Every identity here is synthetic.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Final

import pytest
from apps.cli.knowledge_source_profiles import (
    ProfileRefusalError,
    ProfileSpec,
    parse_profile,
    parse_profiles,
    scope_digest_of,
)

from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeEvidenceAuthority,
    KnowledgeOriginSystem,
    KnowledgeReadOnlyProofState,
)

ROOT: Final = Path(__file__).resolve().parents[2]
INITIAL: Final = ROOT / "ops" / "knowledge-source-profiles" / "initial.json"
(KNOWLEDGE_REVISION,) = sorted(
    (ROOT / "migrations" / "versions").glob("*_knowledge_assertion_layer.py")
)
CLIENT: Final = "klp04-synthetic-discovery-client"
CLIENTS: Final = frozenset({CLIENT})


def _entry(**changes: object) -> dict[str, Any]:
    base: dict[str, Any] = {
        "authenticated_client_id": CLIENT,
        "origin_system": "outlook_mail",
        "scope": "synthetic-mailbox:team/Inbox",
        "authority_ceiling": "authoritative_source",
    }
    base.update(changes)
    return {key: value for key, value in base.items() if value is not None}


# ---- KLP-AC-063 / KLP-AC-064 ------------------------------------------------------------


@pytest.mark.parametrize("origin", ["outlook_mail", "sharepoint_documents"])
@pytest.mark.parametrize("proof", [None, "unproven", "revoked"])
def test_direct_admission_without_proof_is_refused(origin: str, proof: str | None) -> None:
    with pytest.raises(ProfileRefusalError, match="read_only_proof_state=proven"):
        parse_profile(
            _entry(
                origin_system=origin,
                read_only_proof_state=proof,
                direct_admission_enabled=True,
            ),
            discovery_clients=CLIENTS,
        )


@pytest.mark.parametrize("origin", [member.value for member in KnowledgeOriginSystem])
def test_direct_admission_needs_an_authoritative_ceiling_on_every_origin(origin: str) -> None:
    with pytest.raises(ProfileRefusalError, match="authoritative_source"):
        parse_profile(
            _entry(
                origin_system=origin,
                authority_ceiling="observed_source",
                read_only_proof_state="proven",
                direct_admission_enabled=True,
            ),
            discovery_clients=CLIENTS,
        )


@pytest.mark.parametrize("origin", ["outlook_mail", "sharepoint_documents"])
def test_a_proven_authoritative_profile_may_direct_admit(origin: str) -> None:
    spec = parse_profile(
        _entry(origin_system=origin, read_only_proof_state="proven", direct_admission_enabled=True),
        discovery_clients=CLIENTS,
    )
    assert spec == ProfileSpec(
        authenticated_client_id=CLIENT,
        origin_system=KnowledgeOriginSystem(origin),
        scope_digest=scope_digest_of(KnowledgeOriginSystem(origin), "synthetic-mailbox:team/Inbox"),
        authority_ceiling=KnowledgeEvidenceAuthority.AUTHORITATIVE_SOURCE,
        direct_admission_enabled=True,
        read_only_proof_state=KnowledgeReadOnlyProofState.PROVEN,
    )


def test_an_unproven_profile_defaults_to_no_direct_admission() -> None:
    spec = parse_profile(_entry(authority_ceiling="observed_source"), discovery_clients=CLIENTS)
    assert spec.direct_admission_enabled is False
    assert spec.read_only_proof_state is KnowledgeReadOnlyProofState.UNPROVEN


def test_the_database_check_states_the_same_rule() -> None:
    """The provisioner mirrors the frozen CHECK in the Knowledge revision (the backstop)."""
    frozen = " ".join(KNOWLEDGE_REVISION.read_text(encoding="utf-8").split())
    assert (
        "knowledge_profile_direct_admission_needs_proof CHECK (NOT direct_admission_enabled OR "
        "(read_only_proof_state = 'proven' AND authority_ceiling = 'authoritative_source' "
        "AND disabled_at IS NULL))"
    ) in frozen


# ---- KLP-AC-065 ---------------------------------------------------------------------


def test_the_committed_initial_profiles_contain_no_onedrive_profile() -> None:
    document = json.loads(INITIAL.read_text(encoding="utf-8"))
    assert set(document) == {"version", "profiles"}
    assert "onedrive" not in INITIAL.read_text(encoding="utf-8").lower()
    origins = {entry["origin_system"] for entry in document["profiles"]}
    assert origins <= {member.value for member in KnowledgeOriginSystem}
    # It parses under the provisioner's own rules with an allowlist naming every
    # client it mentions (it names none today: provisioning nothing is the default).
    clients = frozenset(entry["authenticated_client_id"] for entry in document["profiles"])
    assert parse_profiles(document, discovery_clients=clients) is not None


def test_origin_system_has_no_onedrive_token() -> None:
    values = {member.value for member in KnowledgeOriginSystem}
    assert not any("onedrive" in value.replace("_", "") for value in values)


@pytest.mark.parametrize(
    "spelling", ["onedrive", "OneDrive", "onedrive_files", "one_drive", "one-drive-business"]
)
def test_any_onedrive_spelling_is_refused_as_unrepresentable(spelling: str) -> None:
    with pytest.raises(ProfileRefusalError, match="OneDrive is not representable"):
        parse_profile(_entry(origin_system=spelling), discovery_clients=CLIENTS)


# ---- the rest of the document contract ---------------------------------------------


@pytest.mark.parametrize(
    "entry",
    [
        _entry(origin_system="dropbox"),
        _entry(authenticated_client_id="klp04-unbound-client"),
        _entry(authenticated_client_id=""),
        _entry(authenticated_client_id="bad\nclient"),
        _entry(scope=None),
        _entry(scope_digest="a" * 64),
        _entry(scope=None, scope_digest="NOT-A-DIGEST"),
        _entry(scope=""),
        _entry(authority_ceiling="supreme"),
        _entry(read_only_proof_state="assumed"),
        _entry(direct_admission_enabled="yes"),
        _entry(principal_id="prn_SyntheticOther01"),
        _entry(source_profile_id="kdsp_SyntheticChosen1"),
        _entry(is_synthetic=True),
        _entry(classification="synthetic_test"),
        "not an object",
    ],
    ids=[
        "unknown-origin",
        "unbound-client",
        "empty-client",
        "control-client",
        "no-scope",
        "both-scopes",
        "bad-digest",
        "empty-scope",
        "unknown-ceiling",
        "unknown-proof",
        "non-bool-direct",
        "principal-field",
        "profile-id-field",
        "synthetic-field",
        "classification-field",
        "not-an-object",
    ],
)
def test_a_malformed_entry_is_refused(entry: object) -> None:
    with pytest.raises(ProfileRefusalError):
        parse_profile(entry, discovery_clients=CLIENTS)


def test_a_refusal_never_echoes_the_scope() -> None:
    native_scope = "synthetic-mailbox:ceo-private/Board"
    with pytest.raises(ProfileRefusalError) as refused:
        parse_profiles(
            {
                "version": 1,
                "profiles": [_entry(scope=native_scope, authority_ceiling="supreme")],
            },
            discovery_clients=CLIENTS,
        )
    assert native_scope not in str(refused.value)


@pytest.mark.parametrize(
    "document",
    [
        {"profiles": []},
        {"version": 2, "profiles": []},
        {"version": True, "profiles": []},
        {"version": 1, "profiles": {}},
        {"version": 1, "profiles": [], "principal_id": "prn_SyntheticOther01"},
        {"version": 1, "profiles": [_entry(), _entry()]},
    ],
    ids=["no-version", "version-2", "bool-version", "profiles-object", "extra-key", "duplicate"],
)
def test_a_malformed_document_is_refused_whole(document: object) -> None:
    with pytest.raises(ProfileRefusalError):
        parse_profiles(document, discovery_clients=CLIENTS)


def test_the_scope_digest_is_origin_bound_and_never_the_scope() -> None:
    outlook = scope_digest_of(KnowledgeOriginSystem.OUTLOOK_MAIL, "synthetic-scope")
    sharepoint = scope_digest_of(KnowledgeOriginSystem.SHAREPOINT_DOCUMENTS, "synthetic-scope")
    assert outlook != sharepoint
    assert len(outlook) == 64
    assert "synthetic-scope" not in outlook
