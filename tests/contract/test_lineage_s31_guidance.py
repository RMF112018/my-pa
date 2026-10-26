"""Record lineage S3.1: the client guidance page and the open commands' rule (FAST).

S3.1 contract section 7.12 (worker N3, R31-F05, RR1-F06). The docs page
`docs/operations/record-lineage-client-guidance.md` writes every example as a
fenced `json` block of lines, each the params of one MCP `tools/call`: every
line is parsed, a `my_pa.describe` document is validated against the describe
schema, and a `my_pa.read` / `my_pa.write` document against the wrapper schema
and its inner `arguments` against `remote_tool_schema` of the named
capability's published tool -- with the wrapper matching the capability's
facade kind and the payload accepted by the command's own checks. The 14 open
commands' docstrings state the S3.1 rule instead of "Local operator only.".
"""

from __future__ import annotations

import dataclasses
import inspect
import json
import re
from pathlib import Path
from typing import Any, Final

from jsonschema import Draft202012Validator

from my_pa.adapters.mcp.chatllm_gateway import (
    DESCRIBE_TOOL,
    READ_TOOL,
    WRITE_TOOL,
    compact_tools,
    facade_kind,
)
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.remote_request import remote_tool_schema
from my_pa.application import commands
from my_pa.domain.identity.operation import Capability
from my_pa.domain.lineage.vocabulary import OPEN_LINEAGE_WRITE_CAPABILITIES

_ROOT: Final = Path(__file__).resolve().parents[2]
_GUIDANCE: Final = _ROOT / "docs" / "operations" / "record-lineage-client-guidance.md"
_BLOCK: Final = re.compile(r"```json\n(.*?)```", re.S)
_WRAPPERS: Final = {READ_TOOL: "read", WRITE_TOOL: "write"}

#: S3.1 section 7.12: what every open command's docstring body states.
_RULE_PHRASES: Final = (
    "Open to any admitted caller (S3.1)",
    "`client_identified`",
    "never accepted-grade",
    "rate bounds",
)


def _tool_schemas() -> dict[str, dict[str, Any]]:
    published = compact_tools(frozenset({DESCRIBE_TOOL, READ_TOOL, WRITE_TOOL}))
    return {tool.name: dict(tool.input_schema) for tool in published}


def _calls(text: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for block in _BLOCK.findall(text):
        for line in block.splitlines():
            if line.strip():
                call = json.loads(line)
                assert set(call) == {"name", "arguments"}, line
                calls.append(call)
    return calls


def _command_class(capability: str) -> type[Any]:
    for value in vars(commands).values():
        if (
            inspect.isclass(value)
            and dataclasses.is_dataclass(value)
            and getattr(value, "capability", None) == Capability(capability)
        ):
            return value
    raise AssertionError(capability)


def _accepted_by_the_command(capability: str, payload: dict[str, Any]) -> None:
    """The payload passes the command's own checks (the boundary's tuples for arrays)."""
    command = _command_class(capability)
    fields = {field.name for field in dataclasses.fields(command)}
    document = {
        name: tuple(value) if isinstance(value, list) else value for name, value in payload.items()
    }
    if "idempotency_key" in fields and "idempotency_key" not in document:
        document["idempotency_key"] = "idk_0123456789abcdef0123456789abcdef"
    command(**document)


def test_the_guidance_examples_validate_against_the_remote_schemas() -> None:
    text = _GUIDANCE.read_text(encoding="utf-8")
    calls = _calls(text)
    wrappers = _tool_schemas()
    tools = {tool.name: tool for tool in TOOLS}
    seen: set[tuple[str, str | None]] = set()
    for call in calls:
        name, arguments = call["name"], call["arguments"]
        Draft202012Validator(wrappers[name]).validate(arguments)
        if name == DESCRIBE_TOOL:
            seen.add((name, arguments.get("capability")))
            continue
        capability = arguments["capability"]
        # The wrapper is the one the capability's facade kind publishes.
        assert facade_kind(Capability(capability)) == _WRAPPERS[name], capability
        schema = remote_tool_schema(tools[capability].input_schema)
        Draft202012Validator(schema).validate(arguments["arguments"])
        payload = arguments["arguments"]["payload"]
        assert "idempotency_key" not in payload
        _accepted_by_the_command(capability, payload)
        seen.add((name, capability))
    # The 2 worked examples of section 7.12, and the describe calls before them.
    assert {
        (DESCRIBE_TOOL, None),
        (DESCRIBE_TOOL, "records.associations.assert"),
        (WRITE_TOOL, "records.associations.assert"),
        (READ_TOOL, "tasks.search"),
        (READ_TOOL, "records.lineage.related"),
    } <= seen
    # The page states the call shape and what the client never sends.
    for phrase in (
        '{"capability": <name>, "arguments": <document>}',
        "**no** `idempotency_key`",
        "similarity is not causation",
        "`user_directed_claim: true`",
        "Only the operator confirms",
    ):
        assert phrase.casefold() in " ".join(text.split()).casefold(), phrase


def _open_commands() -> dict[str, type[Any]]:
    return {name: _command_class(name) for name in sorted(OPEN_LINEAGE_WRITE_CAPABILITIES)}


def test_open_command_docstrings_state_the_s31_rule() -> None:
    open_commands = _open_commands()
    assert len(open_commands) == 14
    descriptions = {tool.name: tool.description for tool in TOOLS}
    for name, command in open_commands.items():
        docstring = inspect.getdoc(command) or ""
        summary, _, body = docstring.partition("\n\n")
        assert "Local operator only" not in docstring, name
        for phrase in _RULE_PHRASES:
            assert phrase in " ".join(body.split()), (name, phrase)
        # The tool description is the summary, and it says what the server records.
        assert descriptions[name] == summary, name
        assert "client-identified" in summary, name
    # What stays attested still says so.
    for name in (
        "issues.close",
        "issues.reopen",
        "records.associations.confirm",
        "issues.memberships.confirm",
        "issues.project_links.confirm",
    ):
        assert descriptions[name].startswith("Operator only:"), name
