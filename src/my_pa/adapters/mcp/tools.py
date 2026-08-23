"""The tool list, derived from the capability set rather than written down.

An MCP client learns what a server can do from `tools/list`, so that list is a
second statement of the capability set — and a second statement is a second
thing to keep true. Nothing here names a capability, a field, or a schema. The
tools come from `Capability`, each tool's payload shape comes from the command
that capability builds, and the metadata beside the payload comes from
`RequestMetadata`'s own JSON Schema. A new capability with a new command appears
as a new tool with the correct schema, and no one edits this file — which WP-6
exercised: four capabilities were added, and the only change here was a schema
for a field type no earlier command used.

**The schema is assembled here and not owned by one model.** A request is
two documents with two owners: `RequestMetadata` validates the envelope, and the
command validates the payload. That split is `adapters/normalization.py`'s and
it is what makes one validation path possible across three transports. The
consequence is that no single object can render the whole input schema, so this
module joins the two halves in exactly the shape `normalize` reads them: the
envelope's fields at the top level, the capability's own fields under
`PAYLOAD_KEY`. Nested dict contracts the type graph cannot express — a
`tuple[dict[str, object], ...]` whose item shape `__post_init__` already
enforces — may be published on the command as `mcp_payload_properties`. This
module copies those properties without naming a capability.

**`capability` is removed from the envelope half deliberately.** A tool call
names its capability in the tool name, and `normalize` refuses a document that
names it again — `RequestMetadata` would receive the argument twice. Publishing
it as an accepted property would advertise a field every request carrying it is
refused for.

**This publishes safety metadata, not authority.** A tool's description is the
command's own docstring summary. Its read-only annotation is derived from the
domain's capability-to-purpose policy through `is_write_capability`, so the
client-facing classification cannot drift into a second list. Which purposes
may invoke a capability and whether it is operator-only remain decided behind
`invoke`; annotations never grant authority or replace confirmation.

The list is built at import so that a build whose capability set and command set
disagree fails when the process is composed rather than when a client asks. A
protocol handler is the wrong place to discover that the build is inconsistent.
"""

from __future__ import annotations

import dataclasses
import json
from collections.abc import Mapping
from datetime import date, datetime
from enum import StrEnum
from types import MappingProxyType, UnionType
from typing import Any, Final, Union, get_args, get_origin, get_type_hints

from mcp.types import Tool, ToolAnnotations

from my_pa.adapters.normalization import PAYLOAD_KEY
from my_pa.application.commands import Command
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.domain.identity.operation import Capability, is_write_capability

__all__ = ["TOOLS", "input_schema_for", "payload_schema_for"]

#: JSON's scalar types, keyed by the Python type a command field declares.
#: `bool` before `int` is not a concern: these are exact keys, and `bool` is a
#: distinct object from `int` however the subclassing goes.
_SCALARS: Mapping[type, str] = MappingProxyType(
    {bool: "boolean", int: "integer", float: "number", str: "string"}
)

#: Payload-object JSON Schema applicators a command may publish beside field
#: overlays. They are not properties and must not be copied onto `properties`.
_PAYLOAD_SCHEMA_APPLICATORS: Final[frozenset[str]] = frozenset(
    {"allOf", "anyOf", "else", "if", "oneOf", "then"}
)


def _schema_for(annotation: Any) -> dict[str, Any] | None:  # noqa: ANN401 - a type annotation
    """The JSON Schema for one command field, or `None` for a shape not described here.

    `None` rather than a guess. An unrecognised annotation publishes an
    unconstrained property, which is honest — the field exists and this module
    cannot say what it takes — and
    `test_every_command_field_has_a_described_json_type` is what keeps `None`
    from becoming the normal answer as commands grow.
    """
    if annotation in _SCALARS:
        return {"type": _SCALARS[annotation]}
    if annotation is datetime:
        # A command holds a real `datetime` and `adapters.normalization` is what
        # converts a caller's string into one, exactly as it converts a string
        # into a `Representation`. On the wire it is a string, and JSON Schema
        # has a name for which kind, so this publishes the wire shape rather than
        # the Python type.
        return {"type": "string", "format": "date-time"}
    if annotation is date:
        # A work-view date is normalized with `date.fromisoformat`; publish the
        # same exact calendar-date wire shape instead of an unconstrained value.
        return {
            "type": "string",
            "format": "date",
            "pattern": r"^\d{4}-\d{2}-\d{2}$",
        }
    if annotation is bytes:
        # A command holds real `bytes` — a managed document body — and JSON has
        # no byte string, so the wire form is base64 and
        # `adapters.normalization` is what decodes it, exactly as it converts a
        # string into a `datetime`. This publishes the wire shape rather than the
        # Python type, and `contentEncoding` is JSON Schema's own name for which
        # kind of string it is. Nothing here says how large one may be: the
        # request ceiling belongs to `adapters.normalization` and the document
        # ceiling to `domain.documents.managed`, and restating either as a
        # `maxLength` would be a third copy able to disagree with both.
        return {"type": "string", "contentEncoding": "base64"}
    origin = get_origin(annotation)
    if origin is UnionType or origin is Union:
        optional = [member for member in get_args(annotation) if member is not type(None)]
        return _schema_for(optional[0]) if len(optional) == 1 else None
    if origin is tuple:
        # `arguments` is also what a caller's request document is called in
        # `server.py`, and `tests/architecture/test_mcp_is_a_thin_adapter.py`
        # forbids reading a field out of one. That guard follows the *value* — a
        # request taints only the parameters it arrives in and the locals it flows
        # into — so a local this module binds to a tuple of type arguments is not
        # a request whatever it is called. The plain name is kept deliberately: a
        # guard rewritten to match names again would report this line, which is
        # the regression showing up as a failure rather than as a rename.
        arguments = get_args(annotation)
        if len(arguments) == 2 and arguments[1] is Ellipsis:
            item = _schema_for(arguments[0])
            return None if item is None else {"type": "array", "items": item}
        return None
    if origin is dict and get_args(annotation) == (str, object):
        # `dict[str, object]` is a bulk mutation: itself a request document for
        # one of the single-task commands (`CreateTask`, `UpdateTask`,
        # `TransitionTask`), each with its own fields and its own schema
        # published elsewhere in this same module. Restating that shape here
        # would be a second copy able to disagree with the first, so this
        # publishes only what every mutation is regardless of which command it
        # names: a JSON object. A narrower value type, such as `dict[str, int]`,
        # is a different shape this module still does not describe.
        return {"type": "object"}
    if isinstance(annotation, type) and issubclass(annotation, StrEnum):
        return {"type": "string", "enum": [member.value for member in annotation]}
    return None


def payload_schema_for(command: type) -> dict[str, Any]:
    """The schema of one command's own fields, read off the dataclass.

    A field with no default is required, which is the same rule the constructor
    enforces: `__post_init__` never runs for a field the caller had to supply
    and did not, because the constructor refuses first.

    `mcp_payload_properties` overlays nested object contracts the annotation
    `dict[str, object]` cannot describe. The overlay must not invent fields.
    JSON Schema applicators that are not field names (`if`/`then`/`else`,
    `oneOf`, `anyOf`, `allOf`) attach to the payload object so a command can
    discriminate nested variants without this module naming the command.
    """
    hints = get_type_hints(command)
    properties: dict[str, Any] = {}
    required: list[str] = []
    for field in dataclasses.fields(command):
        described = _schema_for(hints[field.name])
        properties[field.name] = {} if described is None else described
        if field.default is dataclasses.MISSING and field.default_factory is dataclasses.MISSING:
            required.append(field.name)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    overlays = vars(command).get("mcp_payload_properties")
    if isinstance(overlays, Mapping):
        for name, value in overlays.items():
            if name in properties and isinstance(value, Mapping):
                # **Merged over the derived property, not substituted for it.**
                # A substitution loses whatever `_schema_for` worked out from the
                # annotation, which is fine for an overlay that restates a whole
                # nested object and silently wrong for one that only adds a
                # `description`: the published field ends up with documentation
                # and no type. Overlay keys win, so an overlay that does describe
                # the whole shape still does.
                properties[name] = {**properties[name], **dict(value)}
            elif name in _PAYLOAD_SCHEMA_APPLICATORS:
                schema[name] = value
    return schema


def _envelope_schema() -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    """`RequestMetadata`'s schema, less the field the tool name already carries."""
    schema = RequestMetadata.model_json_schema()
    properties = {
        name: value for name, value in schema["properties"].items() if name != "capability"
    }
    required = [name for name in schema.get("required", ()) if name != "capability"]
    return properties, required, dict(schema.get("$defs", {}))


def _referenced(definitions: Mapping[str, Any], document: Mapping[str, Any]) -> dict[str, Any]:
    """The definitions `document` actually points at.

    Removing `capability` from the envelope leaves `Capability` defined and
    unreferenced, which is a schema that describes something the tool does not
    accept. Pruning by reference rather than by name keeps that true after the
    next contract change.
    """
    rendered = json.dumps(document)
    return {name: value for name, value in definitions.items() if f'"#/$defs/{name}"' in rendered}


def input_schema_for(command: type) -> dict[str, Any]:
    """The complete input schema for the tool serving `command`.

    The envelope at the top level and the command's own fields under
    `PAYLOAD_KEY`, which is the document `normalize` reads. `payload` is
    required only when the command has a field that is.
    """
    properties, required, definitions = _envelope_schema()
    # `payload` for the reason `arguments` above carries: this is a generated
    # JSON Schema built from a command type, and nothing a caller sent reaches it.
    payload = payload_schema_for(command)
    properties[PAYLOAD_KEY] = payload
    if payload["required"]:
        required.append(PAYLOAD_KEY)
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }
    kept = _referenced(definitions, schema)
    if kept:
        schema["$defs"] = kept
    return schema


def _summary(command: type) -> str | None:
    """The command's first documented line, as the tool's description."""
    documentation = command.__doc__
    return documentation.strip().splitlines()[0].strip() if documentation else None


#: Every command there is, by the capability it serves. Read off the union in
#: `application.commands` and each member's own `capability`, so the mapping
#: cannot disagree with the commands it maps.
_COMMANDS: Mapping[Capability, type] = MappingProxyType(
    {member.capability: member for member in get_args(Command.__value__)}
)


def _tools() -> tuple[Tool, ...]:
    """Publish only commands this transport can normalize and dispatch.

    The global capability vocabulary also includes WP-12C's authenticated
    native-host boundary. Those commands remain deliberately unwired here until
    WP-12G; iterating the Command-derived map preserves that separation and
    prevents an import-time KeyError for an enum-valid unavailable capability.
    """
    return tuple(
        Tool(
            name=capability.value,
            description=_summary(_COMMANDS[capability]),
            input_schema=input_schema_for(_COMMANDS[capability]),
            annotations=ToolAnnotations(
                read_only_hint=not is_write_capability(capability),
                destructive_hint=False,
                open_world_hint=False,
            ),
        )
        for capability in _COMMANDS
    )


#: The tool list this server publishes. Built at import: see the module
#: docstring for why a build whose capability and command sets disagree should
#: fail at composition rather than at the first `tools/list`.
TOOLS: Final[tuple[Tool, ...]] = _tools()
