"""Server-owned request metadata for the remote MCP boundary.

A third-party MCP client supplies domain arguments. This module builds the
canonical envelope `normalize` already accepts: contract version, request
identity, request time, Principal, Purpose, and an empty declared scope.
Authorization still happens only in `ApplicationService.invoke`.

Caller-supplied copies of those fields are refused rather than merged. A
natural-language `purpose` is not a Purpose, and accepting one would turn a
misunderstanding into authority.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final

from my_pa.application.errors import InvalidRequestError, UnsupportedError
from my_pa.contracts.v1.base import CONTRACT_VERSION
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import format_rfc3339, utc_now
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "CANONICAL_REMOTE_PURPOSES",
    "REMOTE_OWNED_PAYLOAD_FIELDS",
    "SERVER_OWNED_REMOTE_FIELDS",
    "compose_remote_arguments",
    "is_server_replay_capability",
    "remote_tool_schema",
    "resolve_remote_purpose",
]

#: Writes whose canonical application handler persists a Principal-scoped
#: request receipt.  Unlike `_IDEMPOTENT_REMOTE_CAPABILITIES`, these commands
#: intentionally have no caller-shaped idempotency field: the remote boundary
#: derives the correlation identity itself and the same registry drives MCP's
#: `idempotentHint`.
_SERVER_REPLAY_REMOTE_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.ENTITIES_PROPOSALS_CREATE,
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
        Capability.REVIEW_DECIDE,
    }
)


def is_server_replay_capability(capability: Capability) -> bool:
    """Whether remote retries are backed by the canonical request ledger."""
    return capability in _SERVER_REPLAY_REMOTE_CAPABILITIES


#: Envelope fields a remote MCP caller may not state. `capability` is already
#: removed from published schemas because the tool name carries it; it is listed
#: here so a caller who sends it anyway is refused the same way.
SERVER_OWNED_REMOTE_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "capability",
        "contract_version",
        "principal_id",
        "purpose",
        "request_id",
        "requested_at",
        "scope",
    }
)

#: Payload fields a remote MCP caller may not state. Replay safety is a server
#: concern: a model inventing `idempotency_key` is the same class of defect as
#: inventing `request_id`.
REMOTE_OWNED_PAYLOAD_FIELDS: Final[frozenset[str]] = frozenset({"idempotency_key"})

_IDEMPOTENT_REMOTE_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {
        Capability.CAPTURE_CREATE,
        Capability.CAPTURE_REVISE,
        Capability.SOURCES_ENROLL,
        Capability.DOCUMENTS_CREATE,
        Capability.DOCUMENTS_REVISE,
        Capability.CONTINUITY_PROJECTS_CREATE,
        Capability.CONTINUITY_SITUATIONS_CREATE,
        Capability.CONTINUITY_TASKS_CREATE,
        Capability.TASKS_CREATE,
        Capability.TASKS_UPDATE,
        Capability.TASKS_TRANSITION,
        Capability.TASKS_BULK_PREVIEW,
        Capability.TASKS_BULK_CONFIRM,
        Capability.COMMITMENTS_CREATE,
        Capability.COMMITMENTS_UPDATE,
        Capability.COMMITMENTS_CLOSE,
        Capability.CONTEXT_FEEDBACK,
        Capability.GOODNOTES_PROPOSE,
        # Domain write published on the read-only remote profile so ChatLLM can
        # initiate synthetic B0 without `remote_writes_enabled`. The command
        # still requires `idempotency_key`; the server stamps it because the
        # caller must not.
        Capability.GSQS_START,
        # The entity plane's eighteen keyed writes (Phase A). Every one of them
        # carries an `idempotency_key` its command validates and its repository
        # arbitrates against
        # `entity_mutation_events (principal_id, capability, idempotency_key)`,
        # so a remote caller that never supplies one still gets a replay rather
        # than a second write when its response is lost. `entities.observe` is
        # here with the rest: an ingest path is the caller most likely to retry.
        Capability.ENTITIES_CREATE,
        Capability.ENTITIES_UPDATE,
        Capability.ENTITIES_ARCHIVE,
        Capability.ENTITIES_RESTORE,
        Capability.ENTITIES_IDENTIFIERS_BIND,
        Capability.ENTITIES_IDENTIFIERS_RETIRE,
        Capability.ENTITIES_IDENTIFIERS_SUPERSEDE,
        Capability.ENTITIES_ALIASES_ADD,
        Capability.ENTITIES_ALIASES_RETIRE,
        Capability.ENTITIES_ALIASES_SUPERSEDE,
        Capability.ENTITIES_ASSIGNMENTS_CREATE,
        Capability.ENTITIES_ASSIGNMENTS_REVISE,
        Capability.ENTITIES_ASSIGNMENTS_END,
        Capability.ENTITIES_RELATIONSHIPS_CREATE,
        Capability.ENTITIES_RELATIONSHIPS_REVISE,
        Capability.ENTITIES_RELATIONSHIPS_END,
        Capability.ENTITIES_OBSERVE,
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE,
        # `RI-ENT-WP-11`'s record-family writes, here on the identical argument
        # and with nothing new to say: every one carries an `idempotency_key`
        # its command validates, and every one is arbitrated against the same
        # `entity_mutation_events (principal_id, capability, idempotency_key)`
        # -- reached through `record_mutation_event` rather than
        # `_append_mutation`, which is a difference in *which* writer touches the
        # unique and not in what the unique decides. So a remote caller that
        # never supplies a key still gets a replay rather than a second recorded
        # name when its response is lost.
        Capability.ENTITIES_NAMES_ADD,
        Capability.ENTITIES_NAMES_SUPERSEDE,
        Capability.ENTITIES_NAMES_RETIRE,
        Capability.ENTITIES_ADDRESSES_ADD,
        Capability.ENTITIES_ADDRESSES_REVISE,
        Capability.ENTITIES_ADDRESSES_RETIRE,
        # **No keyless proposal or identity-correction write is here, and the reason is this set's
        # mechanism rather than a judgement about how replayable they are.**
        # Membership makes `compose_remote_arguments` derive a key and *insert it
        # into the payload*, so a capability here must have an
        # `idempotency_key` field on its command. None of the six does, and
        # that absence is itself the contract:
        #
        # * `entities.proposals.create` and `relationship_memory.propose` use
        #   the canonical Principal-scoped request ledger. The remote boundary
        #   gives an identical request a deterministic request ID, so the
        #   application handler replays its persisted result without inserting
        #   a caller-shaped field into either proposal command.
        # * `entities.merge` and `entities.split` are arbitrated by
        #   `UNIQUE (principal_id, idempotency_key)` on
        #   `entity_identity_operations`, and each key is derived by the handler
        #   from the preview it consumes — so an identical retry replays and a
        #   materially different request against the same preview conflicts, on
        #   local MCP, remote MCP and HTTP alike. Deriving it here would give the
        #   guarantee to one transport out of three.
        # * `entities.merge.preview` and `entities.split.preview` mint a fresh
        #   preview on every call and have no replay identity to key on at all.
        #
        # `REMOTE_OWNED_PAYLOAD_FIELDS` still refuses a caller-supplied
        # `idempotency_key` on every one of these paths, which is what operator §23's "do not
        # accept caller-selected remote idempotency keys" actually needs.
    }
)

#: When more than one permitted purpose remains after grant intersection, the
#: remote boundary picks this one rather than asking the model. Only the
#: capabilities that actually have more than one permitted purpose belong here.
#:
#: `capabilities.get` — a ChatLLM read is status observation of the interface.
#: `security_validation` remains available to a client granted only that purpose.
#:
#: `sources.fetch` — a ChatLLM fetch is inspection of one object. Extraction is
#: a different act and stays available when it is the only granted purpose.
#:
#: **Phase B adds nothing here, and the emptiness is derived rather than
#: overlooked.** `resolve_remote_purpose` consults this mapping only when the
#: grant intersection leaves more than one purpose. Each of `entities.proposals.create`,
#: `relationship_memory.propose`, `entities.merge.preview` and `entities.merge`
#: permits exactly one purpose, so an entry for any of them could never be read
#: — it would be a statement that looks like policy and decides nothing.
CANONICAL_REMOTE_PURPOSES: Final[Mapping[Capability, Purpose]] = MappingProxyType(
    {
        Capability.CAPABILITIES_GET: Purpose.STATUS_OBSERVATION,
        Capability.SOURCES_FETCH: Purpose.SOURCE_INSPECTION,
    }
)

IdentifierIssuer = Callable[[IdKind], str]
Clock = Callable[[], datetime]


def resolve_remote_purpose(
    capability: Capability,
    grants: frozenset[tuple[Capability, Purpose | None]] | None,
) -> Purpose:
    """The one Purpose the remote boundary will stamp for `capability`.

    `grants is None` means the transport did not attach a grant ceiling — the
    same unrestricted remote test access that already skips the grant check
    after `normalize`. That is treated as a capability-wide grant.

    An empty grant set, a grant that does not mention `capability`, or an
    intersection that leaves no permitted purpose, is a refusal. Multiple
    remaining purposes use `CANONICAL_REMOTE_PURPOSES` when that value is in
    the intersection; otherwise the request fails closed.
    """
    permitted = permitted_purposes(capability)
    if not permitted:
        raise UnsupportedError()
    if grants is None or (capability, None) in grants:
        effective = permitted
    else:
        effective = frozenset(purpose for purpose in permitted if (capability, purpose) in grants)
    if not effective:
        raise UnsupportedError()
    if len(effective) == 1:
        return next(iter(effective))
    canonical = CANONICAL_REMOTE_PURPOSES.get(capability)
    if canonical is not None and canonical in effective:
        return canonical
    raise UnsupportedError()


def compose_remote_arguments(
    *,
    capability_name: str,
    arguments: Mapping[str, Any],
    principal: Principal,
    grants: frozenset[tuple[Capability, Purpose | None]] | None,
    clock: Clock = utc_now,
    issue_id: IdentifierIssuer = issue_identifier,
) -> dict[str, Any]:
    """Build the document `normalize` reads, or refuse.

    The caller's mapping is copied only for the keys it is allowed to own.
    Server-owned fields are generated here. A caller that sent one is refused
    before a Purpose is chosen, so a forged purpose never wins.
    """
    if SERVER_OWNED_REMOTE_FIELDS.intersection(arguments):
        raise InvalidRequestError()
    payload = arguments.get("payload")
    if isinstance(payload, Mapping) and REMOTE_OWNED_PAYLOAD_FIELDS.intersection(payload):
        raise InvalidRequestError()
    try:
        capability = Capability(capability_name)
    except ValueError:
        raise InvalidRequestError() from None
    purpose = resolve_remote_purpose(capability, grants)
    composed = dict(arguments)
    if capability in _IDEMPOTENT_REMOTE_CAPABILITIES:
        domain = dict(payload) if isinstance(payload, Mapping) else {}
        digest = hashlib.sha256(
            json.dumps(
                {
                    "capability": capability.value,
                    "principal_id": principal.principal_id,
                    "payload": domain,
                },
                sort_keys=True,
                default=str,
            ).encode()
        ).hexdigest()
        composed["payload"] = {**domain, "idempotency_key": f"idk_{digest[:32]}"}
    if is_server_replay_capability(capability):
        request_digest = hashlib.sha256(
            json.dumps(
                {
                    "capability": capability.value,
                    "principal_id": principal.principal_id,
                    "arguments": composed,
                },
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode()
        ).hexdigest()
        request_id = f"corr_{request_digest[:32]}"
    else:
        request_id = issue_id(IdKind.CORRELATION)
    composed.update(
        {
            "contract_version": CONTRACT_VERSION,
            "request_id": request_id,
            "requested_at": format_rfc3339(clock()),
            "principal_id": principal.principal_id,
            "purpose": purpose.value,
            "scope": {"source_ids": [], "enrollment_ids": []},
        }
    )
    return composed


def remote_tool_schema(schema: Mapping[str, Any]) -> dict[str, Any]:
    """The published remote input schema: domain arguments only."""
    view = dict(schema)
    properties = {
        name: value
        for name, value in dict(view.get("properties", {})).items()
        if name not in SERVER_OWNED_REMOTE_FIELDS
    }
    view["properties"] = properties
    view["required"] = [
        name for name in view.get("required", []) if name not in SERVER_OWNED_REMOTE_FIELDS
    ]
    payload_schema = properties.get("payload")
    if isinstance(payload_schema, dict):
        payload_view = dict(payload_schema)
        payload_properties = {
            name: value
            for name, value in dict(payload_view.get("properties", {})).items()
            if name not in REMOTE_OWNED_PAYLOAD_FIELDS
        }
        payload_view["properties"] = payload_properties
        payload_view["required"] = [
            name
            for name in payload_view.get("required", [])
            if name not in REMOTE_OWNED_PAYLOAD_FIELDS
        ]
        properties["payload"] = payload_view
        view["properties"] = properties
    definitions = view.get("$defs")
    if not definitions:
        return view
    rendered = json.dumps(view)
    kept = {name: value for name, value in definitions.items() if f'"#/$defs/{name}"' in rendered}
    if kept:
        view["$defs"] = kept
    else:
        view.pop("$defs", None)
    return view
