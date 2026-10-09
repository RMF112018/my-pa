"""Operator command: Knowledge discovery source profiles and their maintenance.

    .venv/bin/python apps/cli/knowledge_source_profiles.py apply \\
        --file ops/knowledge-source-profiles/initial.json
    .venv/bin/python apps/cli/knowledge_source_profiles.py list
    .venv/bin/python apps/cli/knowledge_source_profiles.py disable --source-profile-id kdsp_...
    .venv/bin/python apps/cli/knowledge_source_profiles.py classify-evidence \\
        --evidence-ref kaevd_... --classification restricted_local
    .venv/bin/python apps/cli/knowledge_source_profiles.py drain-revalidation
    .venv/bin/python apps/cli/knowledge_source_profiles.py redact-sealed --below-seal 2

**Configuration, not a capability** (KLP-AC-129, R6 section 5.1). Commissioning
a discovery source -- which client, which origin system, which scope, what
authority ceiling, whether it may direct-admit -- and the source-classification
ingress are operator acts. Neither is a `capability`: this command builds no
`ApplicationService`, imports neither `my_pa.application` nor `my_pa.adapters`,
and is registered in `tests/architecture/test_operator_commands_are_not_capabilities.py`
with the persistence names it may use. It writes no audit event (the
`clients.py` precedent): profile versions, mutations and Record Events are its
evidence.

**The profile file** (`apply`, alias `provision`) is JSON
`{"version": 1, "profiles": [...]}`. Each entry names exactly
`authenticated_client_id`, `origin_system`, `authority_ceiling`, one of
`scope` (a native scope identifier, hashed here and never stored or printed) or
`scope_digest` (64 lowercase hex), and optionally `direct_admission_enabled`
(default false) and `read_only_proof_state` (default `unproven`). The Principal
is this process's, never a file field. Refused before anything is written:

* any OneDrive origin -- there is no token for it (WP-14 is blocked), so a
  OneDrive profile is unrepresentable (KLP-AC-065);
* `direct_admission_enabled` without `read_only_proof_state = proven` and an
  `authoritative_source` ceiling, for every origin system and in particular
  `outlook_mail` and `sharepoint_documents` (KLP-AC-063/064; the database CHECK
  `knowledge_profile_direct_admission_needs_proof` backs it);
* a client that is in neither `MY_PA_KNOWLEDGE_DISCOVERY_OAUTH_CLIENT_IDS` nor
  `MY_PA_KNOWLEDGE_MANAGER_OAUTH_CLIENT_IDS` (KLP Step 8: a Knowledge Manager
  submits source-backed assertions too, so it may have a source profile);
* an unknown field, a duplicate binding, a malformed value.

An existing active binding has its mutable controls updated (new
`profile_version`); its authority ceiling is immutable (disable it and provision
a new one). `disable` is terminal: it sets `disabled_at` and clears direct
admission under `FOR NO KEY UPDATE`, and deletes no Knowledge row (KLP-AC-090);
later submissions answer `source_profile_inactive`. Profile commands print the
`allowlist_fingerprint` they evaluated (R6 section 3.4).

**Maintenance** prints `remaining=<n>` and exits 3 while n > 0 (re-run until
it reports 0), 0 when n = 0. `classify-evidence` raises the named evidence row
-- and, for an external object, every sibling row of it -- to
`restricted_local` and redacts its excerpt in one UPDATE, then classifies at most
128 live linked assertions per run (KLP-AC-164, KLP-R6V-201/202).
`drain-revalidation` marks at most 128 assertions of one pending evidence row per
run and clears the flag only once every linked live assertion is marked.
`redact-sealed` redacts every checkpoint-request envelope sealed below the
given seal version (seal rotation, R6 section 7 step 3).

**Nothing is echoed that was not asked for.** Output is identifiers, digests,
tokens of closed vocabularies and counts: never an excerpt, a checkpoint
envelope, a credential or a native scope identifier (KLP-AC-072).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from sqlalchemy import Engine

from my_pa.bootstrap.knowledge_discovery_profiles import (
    KnowledgeAllowlists,
    allowlist_fingerprint,
    knowledge_allowlists,
)
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import KnowledgeEvidenceNotFoundError, TransactionConflictError
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeEvidenceAuthority,
    KnowledgeOriginSystem,
    KnowledgeReadOnlyProofState,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.unit_of_work import knowledge_maintenance_transaction

EXIT_OK: Final = 0
EXIT_REFUSED: Final = 1
#: Maintenance is resumable: exit 3 means "re-run, work remains".
EXIT_REMAINING: Final = 3
#: Transactions `classify-evidence` may restart after a held new sibling (R6V-202).
CLASSIFY_ATTEMPTS: Final = 3

PROFILE_DOCUMENT_VERSION: Final = 1
_DOCUMENT_KEYS: Final = frozenset({"version", "profiles"})
_REQUIRED: Final = frozenset({"authenticated_client_id", "origin_system", "authority_ceiling"})
_OPTIONAL: Final = frozenset(
    {"scope", "scope_digest", "direct_admission_enabled", "read_only_proof_state"}
)
_SHA256_HEX: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f]")
_EVIDENCE_REF: Final = re.compile(r"\Akaevd_[A-Za-z0-9]{8,64}\Z")
_PROFILE_ID: Final = re.compile(r"\Akdsp_[A-Za-z0-9]{8,64}\Z")
MAX_CLIENT_CHARACTERS: Final = 256
MAX_SCOPE_CHARACTERS: Final = 1024


class ProfileRefusalError(ValueError):
    """A profile document or entry this command refuses. Names a field, never a value."""


@dataclass(frozen=True, slots=True)
class ProfileSpec:
    """One validated profile entry. Holds the scope digest only."""

    authenticated_client_id: str
    origin_system: KnowledgeOriginSystem
    scope_digest: str
    authority_ceiling: KnowledgeEvidenceAuthority
    direct_admission_enabled: bool
    read_only_proof_state: KnowledgeReadOnlyProofState


def scope_digest_of(origin_system: KnowledgeOriginSystem, scope: str) -> str:
    """sha256 hex of the canonical JSON of (v, origin_system, native scope)."""
    document = {"origin_system": origin_system.value, "scope": scope, "v": 1}
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _member[EnumT](value: object, enum: Callable[[str], EnumT], field: str) -> EnumT:
    if not isinstance(value, str):
        raise ProfileRefusalError(f"{field} must be a closed token")
    try:
        return enum(value)
    except ValueError:
        raise ProfileRefusalError(f"{field} is not a known token") from None


def _origin(value: object) -> KnowledgeOriginSystem:
    if isinstance(value, str) and "onedrive" in value.lower().replace("_", "").replace("-", ""):
        raise ProfileRefusalError(
            "origin_system: OneDrive is not representable (no origin_system token exists; "
            "KLP-WP-14 is blocked), so no OneDrive profile can be provisioned"
        )
    return _member(value, KnowledgeOriginSystem, "origin_system")


def source_profile_clients(allowlists: KnowledgeAllowlists) -> frozenset[str]:
    """The exact clients a source profile may name: discovery or Knowledge Manager.

    KLP Step 8. Exact membership of the two Settings allowlists; an operator-review
    or ChatLLM-only client is in neither and is refused.
    """
    return allowlists.discovery | allowlists.manager


def parse_profile(entry: object, *, discovery_clients: frozenset[str]) -> ProfileSpec:
    """Validate one entry (KLP-AC-063/064/065). Pure: no database, no settings.

    `discovery_clients` is every client that may submit: since KLP Step 8 the
    union `source_profile_clients` builds (the name is kept for its callers).
    """
    if not isinstance(entry, Mapping):
        raise ProfileRefusalError("each profile must be an object")
    keys = set(entry)
    if not keys >= _REQUIRED or not keys <= _REQUIRED | _OPTIONAL:
        raise ProfileRefusalError(
            "a profile names exactly authenticated_client_id, origin_system, "
            "authority_ceiling, one of scope/scope_digest, and optionally "
            "direct_admission_enabled and read_only_proof_state"
        )
    origin = _origin(entry["origin_system"])
    client = entry["authenticated_client_id"]
    if (
        not isinstance(client, str)
        or not 1 <= len(client) <= MAX_CLIENT_CHARACTERS
        or _CONTROL.search(client)
    ):
        raise ProfileRefusalError("authenticated_client_id must be 1..256 printable characters")
    if client not in discovery_clients:
        raise ProfileRefusalError(
            f"authenticated_client_id is not in {ENV_PREFIX}KNOWLEDGE_DISCOVERY_OAUTH_CLIENT_IDS "
            f"or {ENV_PREFIX}KNOWLEDGE_MANAGER_OAUTH_CLIENT_IDS; only a bound discovery or "
            "Knowledge Manager client can have a source profile"
        )
    if ("scope" in entry) == ("scope_digest" in entry):
        raise ProfileRefusalError("a profile names exactly one of scope and scope_digest")
    if "scope" in entry:
        scope = entry["scope"]
        if not isinstance(scope, str) or not 1 <= len(scope) <= MAX_SCOPE_CHARACTERS:
            raise ProfileRefusalError("scope must be 1..1024 characters")
        digest = scope_digest_of(origin, scope)
    else:
        digest = entry["scope_digest"]
        if not isinstance(digest, str) or not _SHA256_HEX.fullmatch(digest):
            raise ProfileRefusalError("scope_digest must be 64 lowercase hex characters")
    ceiling = _member(entry["authority_ceiling"], KnowledgeEvidenceAuthority, "authority_ceiling")
    proof = _member(
        entry.get("read_only_proof_state", KnowledgeReadOnlyProofState.UNPROVEN.value),
        KnowledgeReadOnlyProofState,
        "read_only_proof_state",
    )
    direct = entry.get("direct_admission_enabled", False)
    if not isinstance(direct, bool):
        raise ProfileRefusalError("direct_admission_enabled must be true or false")
    if direct and (
        proof is not KnowledgeReadOnlyProofState.PROVEN
        or ceiling is not KnowledgeEvidenceAuthority.AUTHORITATIVE_SOURCE
    ):
        raise ProfileRefusalError(
            f"direct_admission_enabled needs read_only_proof_state=proven and "
            f"authority_ceiling=authoritative_source ({origin.value})"
        )
    return ProfileSpec(
        authenticated_client_id=client,
        origin_system=origin,
        scope_digest=digest,
        authority_ceiling=ceiling,
        direct_admission_enabled=direct,
        read_only_proof_state=proof,
    )


def parse_profiles(
    document: object, *, discovery_clients: frozenset[str]
) -> tuple[ProfileSpec, ...]:
    """Validate a whole profile document; refuse it whole on the first defect."""
    if not isinstance(document, Mapping) or set(document) != _DOCUMENT_KEYS:
        raise ProfileRefusalError('the document is exactly {"version": 1, "profiles": [...]}')
    if document["version"] != PROFILE_DOCUMENT_VERSION or isinstance(document["version"], bool):
        raise ProfileRefusalError("version must be 1")
    entries = document["profiles"]
    if not isinstance(entries, list):
        raise ProfileRefusalError("profiles must be a list")
    specs: list[ProfileSpec] = []
    seen: set[tuple[str, str, str]] = set()
    for index, entry in enumerate(entries):
        try:
            spec = parse_profile(entry, discovery_clients=discovery_clients)
        except ProfileRefusalError as refusal:
            raise ProfileRefusalError(f"profiles[{index}]: {refusal}") from None
        binding = (spec.authenticated_client_id, spec.origin_system.value, spec.scope_digest)
        if binding in seen:
            raise ProfileRefusalError(f"profiles[{index}]: the same binding appears twice")
        seen.add(binding)
        specs.append(spec)
    return tuple(specs)


def load_profile_document(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ProfileRefusalError("the profile file could not be read as UTF-8 JSON") from None


# ---- output (identifiers, digests, closed tokens and counts only) -----------------


def profile_line(action: str, profile: Any) -> str:  # noqa: ANN401 - a persistence record
    disabled = "-" if profile.disabled_at is None else profile.disabled_at.isoformat()
    return (
        f"{action:<9s} {profile.source_profile_id}  client={profile.authenticated_client_id}  "
        f"origin={profile.origin_system}  scope_digest={profile.scope_digest}  "
        f"ceiling={profile.authority_ceiling}  "
        f"direct={str(profile.direct_admission_enabled).lower()}  "
        f"proof={profile.read_only_proof_state}  version={profile.profile_version}  "
        f"disabled_at={disabled}"
    )


def maintenance_lines(result: Any) -> list[str]:  # noqa: ANN401 - a persistence result
    return [
        f"evidence_refs     {','.join(result.evidence_ref_ids) or '-'}",
        f"mutated           {len(result.mutated_assertion_ids)}",
        f"pending           {str(result.pending).lower()}",
        f"remaining={result.remaining}",
    ]


# ---- the runtime -------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Runtime:
    """What every subcommand runs against: one engine, one Principal, one clock."""

    engine: Engine
    principal_id: str
    allowlists: KnowledgeAllowlists
    clock: Callable[[], datetime]


def _fingerprint(runtime: Runtime, out: Callable[[str], None]) -> None:
    out(f"allowlist_fingerprint {allowlist_fingerprint(runtime.allowlists)}")


def _apply(args: argparse.Namespace, runtime: Runtime, out: Callable[[str], None]) -> int:
    _fingerprint(runtime, out)
    specs = parse_profiles(
        load_profile_document(Path(args.file)),
        discovery_clients=source_profile_clients(runtime.allowlists),
    )
    at = runtime.clock()
    with knowledge_maintenance_transaction(runtime.engine) as repository:
        changes = [
            repository.apply_source_profile(
                runtime.principal_id,
                authenticated_client_id=spec.authenticated_client_id,
                origin_system=spec.origin_system.value,
                scope_digest=spec.scope_digest,
                authority_ceiling=spec.authority_ceiling.value,
                direct_admission_enabled=spec.direct_admission_enabled,
                read_only_proof_state=spec.read_only_proof_state.value,
                at=at,
            )
            for spec in specs
        ]
    for change in changes:
        out(profile_line(change.action, change.profile))
    out(f"profiles          {len(changes)}")
    return EXIT_OK


def _list(args: argparse.Namespace, runtime: Runtime, out: Callable[[str], None]) -> int:
    _fingerprint(runtime, out)
    with knowledge_maintenance_transaction(runtime.engine) as repository:
        profiles = repository.source_profiles(runtime.principal_id, at=runtime.clock())
    for profile in profiles:
        out(profile_line("profile", profile))
    out(f"profiles          {len(profiles)}")
    return EXIT_OK


def _disable(args: argparse.Namespace, runtime: Runtime, out: Callable[[str], None]) -> int:
    _fingerprint(runtime, out)
    if not isinstance(args.source_profile_id, str) or not _PROFILE_ID.fullmatch(
        args.source_profile_id
    ):
        raise ProfileRefusalError("--source-profile-id is not a kdsp_ identifier")
    with knowledge_maintenance_transaction(runtime.engine) as repository:
        disabled = repository.disable_source_profile(
            runtime.principal_id, args.source_profile_id, at=runtime.clock()
        )
    if disabled is None:
        out("refused           no active source profile of this Principal carries that identifier")
        return EXIT_REFUSED
    out(profile_line("disabled", disabled))
    out("notice            new submissions and checkpoints answer source_profile_inactive")
    return EXIT_OK


def _remaining(result: Any, out: Callable[[str], None]) -> int:  # noqa: ANN401
    for line in maintenance_lines(result):
        out(line)
    return EXIT_REMAINING if result.remaining > 0 else EXIT_OK


def _classify(args: argparse.Namespace, runtime: Runtime, out: Callable[[str], None]) -> int:
    if not isinstance(args.evidence_ref, str) or not _EVIDENCE_REF.fullmatch(args.evidence_ref):
        raise ProfileRefusalError("--evidence-ref is not a kaevd_ identifier")
    for attempt in range(CLASSIFY_ATTEMPTS):
        try:
            with knowledge_maintenance_transaction(runtime.engine) as repository:
                result = repository.classify_evidence_restricted(
                    runtime.principal_id, args.evidence_ref, at=runtime.clock()
                )
        except TransactionConflictError:
            # A sibling appeared and is held by a writer (KLP-R6V-202): restart the
            # transaction, whose first read now carries the larger sibling set.
            if attempt + 1 == CLASSIFY_ATTEMPTS:
                raise
            continue
        return _remaining(result, out)
    raise AssertionError("unreachable")  # pragma: no cover


def _drain(args: argparse.Namespace, runtime: Runtime, out: Callable[[str], None]) -> int:
    with knowledge_maintenance_transaction(runtime.engine) as repository:
        result = repository.drain_availability_revalidation(
            runtime.principal_id, at=runtime.clock()
        )
    return _remaining(result, out)


def _redact(args: argparse.Namespace, runtime: Runtime, out: Callable[[str], None]) -> int:
    below = args.below_seal
    if not 1 <= below <= 32767:
        raise ProfileRefusalError("--below-seal is 1..32767")
    with knowledge_maintenance_transaction(runtime.engine) as repository:
        redacted = repository.redact_sealed_checkpoint_requests(
            runtime.principal_id, below_seal=below, at=runtime.clock()
        )
    out(f"redacted          {redacted}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="knowledge_source_profiles",
        description="Provision Knowledge discovery source profiles and run their maintenance.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("apply", "provision"):
        apply = commands.add_parser(name, help="create or update profiles from a JSON file")
        apply.add_argument("--file", required=True, help="the profile document (JSON)")
    commands.add_parser("list", help="print this Principal's source profiles")
    disable = commands.add_parser("disable", help="disable one source profile (terminal)")
    disable.add_argument("--source-profile-id", required=True)
    classify = commands.add_parser(
        "classify-evidence", help="raise one evidence row (and its siblings) to restricted_local"
    )
    classify.add_argument("--evidence-ref", required=True)
    classify.add_argument("--classification", required=True, choices=["restricted_local"])
    commands.add_parser(
        "drain-revalidation", help="mark the assertions of one availability-pending row"
    )
    redact = commands.add_parser(
        "redact-sealed", help="redact checkpoint envelopes sealed below a seal version"
    )
    redact.add_argument("--below-seal", required=True, type=int)
    return parser


def _dispatch(args: argparse.Namespace, runtime: Runtime, out: Callable[[str], None]) -> int:
    match args.command:
        case "apply" | "provision":
            return _apply(args, runtime, out)
        case "list":
            return _list(args, runtime, out)
        case "disable":
            return _disable(args, runtime, out)
        case "classify-evidence":
            return _classify(args, runtime, out)
        case "drain-revalidation":
            return _drain(args, runtime, out)
        case "redact-sealed":
            return _redact(args, runtime, out)
        case unknown:  # pragma: no cover - argparse rejects an unknown command first
            raise SystemExit(f"unhandled command {unknown!r}")


def run_knowledge_source_profiles(
    argv: Sequence[str],
    runtime: Runtime,
    *,
    out: Callable[[str], None] = print,
) -> int:
    """Parse and dispatch against `runtime`. A refusal is exit 1 and one line."""
    args = build_parser().parse_args(list(argv))
    try:
        return _dispatch(args, runtime, out)
    except ValueError as refusal:
        out(f"refused           {refusal}")
        return EXIT_REFUSED
    except KnowledgeEvidenceNotFoundError:
        out("refused           no evidence row of this Principal carries that identifier")
        return EXIT_REFUSED
    except TransactionConflictError:
        # `classify-evidence` restarted CLASSIFY_ATTEMPTS times and a writer still
        # held a new sibling: nothing committed, so the command is simply re-run.
        out("conflict          evidence rows are held by another writer; re-run")
        return EXIT_REMAINING


def main(argv: list[str] | None = None) -> int:
    """Bind this process's durable Principal, or refuse, then run one subcommand.

    The Principal is `admissible_client_principal_id()` -- the one local-operator
    Principal this process serves (the `clients.py` binding). There is no
    `--principal-id` flag: a profile or a maintenance write never acts for a
    caller-named Principal.
    """
    arguments = sys.argv[1:] if argv is None else argv
    settings = load_settings()
    principal = settings.admissible_client_principal_id()
    if principal is None:
        print(
            f"refused           {ENV_PREFIX}AUTH_MODE authenticates each request and a shell "
            "carries no credential, so there is no Principal to act for. Run this from a "
            "process configured for the local operator"
        )
        return EXIT_REFUSED
    runtime = Runtime(
        engine=create_database_engine(settings.parsed_database_url(), statement_timeout_ms=30_000),
        principal_id=principal,
        allowlists=knowledge_allowlists(settings),
        clock=lambda: datetime.now(UTC),
    )
    try:
        return run_knowledge_source_profiles(arguments, runtime)
    finally:
        runtime.engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
