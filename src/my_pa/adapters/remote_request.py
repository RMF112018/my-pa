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
    "remote_tool_schema",
    "resolve_remote_purpose",
]

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
    composed.update(
        {
            "contract_version": CONTRACT_VERSION,
            "request_id": issue_id(IdKind.CORRELATION),
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
