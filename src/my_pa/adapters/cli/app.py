"""An argument vector in, one `invoke`, an envelope out.

The third transport, and the same module again: assemble the arguments, hand
`(capability, arguments)` to `normalize`, call `invoke` once, and write what came
back. `module-boundaries.md` section 5.7 requires that the CLI is **not a
privileged bypass**, and the way that is made true here is structural rather
than careful — there is no path from an argument to the application that does
not go through the one `normalize` the other two transports call, and the
principal is supplied by the composition root exactly as it is for them. An
operator-only capability is operator-only from a shell for the same reason it is
over a socket: nothing in this file knows which capabilities those are.

**Why the envelope is options and the payload is JSON.** The two halves of a
request have two owners. The envelope is one fixed shape — `RequestMetadata`'s
fields, the same for all 142 capabilities — so it is presented as
options, which is what a CLI is for. The payload is capability-specific, so
fifteen sets of hand-written options would be fifteen statements of what
`application.commands` already says, and a 102nd capability would
arrive with none. `--payload` is
JSON for the same reason `adapters/mcp/tools.py` derives its schemas: a second
copy of a shape is a second thing to keep true.

**Nothing here validates.** Every option is optional to `argparse` and every
value is passed through as the string the operator typed. A missing
`--request-id`, a purpose that is not one, a `--requested-at` that is not a
time: each is refused by `RequestMetadata`, which is the same object that
refuses it over HTTP and MCP, reported with the same code and the same message.
An option this file rejected itself would be a second validation path and a
second error vocabulary.

**`argparse` is not allowed to speak.** Its default failure prints a usage
message naming the value it rejected, to standard error, and then exits — which
would put a caller's `--payload` on a terminal and in whatever collects that
stream. `_Parser.error` turns every one of those into the same typed refusal the
rest of this file produces, so there is exactly one thing this transport can
say. `--help` is untouched: it prints option names and no value.

**One document out, on standard output, always.** Success and failure are the
same shape, because they are the same envelope. Standard error stays empty so
that a caller redirecting one stream is not silently discarding the answer, and
so that "this transport disclosed nothing" is a claim about one stream rather
than two. The exit status carries success and nothing more: it is `1` for every
refusal rather than a number per code, because a shell status is five bits of
sign-extended folklore and the envelope already carries the code that matters.
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from typing import IO, Any, Final, NoReturn

from my_pa.adapters.normalization import MAX_REQUEST_BYTES, PAYLOAD_KEY, normalize
from my_pa.application.errors import (
    ApplicationError,
    InternalError,
    InvalidRequestError,
    problem_detail,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.errors import ProblemDetail
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.principal import Principal
from my_pa.domain.source.registry import issue_identifier

__all__ = ["EXIT_FAILED", "EXIT_OK", "build_parser", "run"]

#: The request completed and the envelope carries a result.
EXIT_OK: Final = 0

#: The request was refused. Which refusal is in the envelope, not in the status.
EXIT_FAILED: Final = 1

#: Envelope options, and the `RequestMetadata` field each supplies. Written as a
#: mapping so that assembling the document is one loop over it rather than five
#: assignments, and so `test_the_cli_offers_every_envelope_field` can compare it
#: against the contract model instead of against a reader's memory.
_ENVELOPE_OPTIONS: Mapping[str, str] = {
    "--request-id": "request_id",
    "--purpose": "purpose",
    "--principal-id": "principal_id",
    "--requested-at": "requested_at",
    "--contract-version": "contract_version",
}

#: Repeatable options that build the declared scope. Separate from the scalars
#: because `Scope` is a nested object and a shell has no nesting.
_SCOPE_OPTIONS: Mapping[str, str] = {
    "--scope-source-id": "source_ids",
    "--scope-enrollment-id": "enrollment_ids",
}


class _Parser(argparse.ArgumentParser):
    """`argparse`, with its own error reporting removed. See the module docstring."""

    def error(self, message: str) -> NoReturn:
        raise InvalidRequestError()


def build_parser() -> argparse.ArgumentParser:
    """The operator's command line.

    One positional capability, the envelope as options, and the payload as one
    JSON document. Nothing here declares a choice, a type, or a default: a
    `choices=` list would be a fourth copy of the capability set and a `type=`
    would be a refusal this file made rather than the contract.
    """
    parser = _Parser(
        prog="my-pa",
        description="Invoke one my-pa capability. The answer is a v1 response envelope.",
    )
    parser.add_argument("capability", help="the capability to invoke, for example knowledge.read")
    for option, field in _ENVELOPE_OPTIONS.items():
        parser.add_argument(option, dest=field)
    for option, field in _SCOPE_OPTIONS.items():
        parser.add_argument(option, dest=field, action="append")
    parser.add_argument(
        "--payload",
        help="the capability's own fields, as one JSON object",
    )
    return parser


def _payload(encoded: str | None) -> Mapping[str, Any]:
    """The `--payload` document, or a refusal.

    A JSON value that is not an object is refused rather than coerced, for the
    reason `adapters/http/app.py` refuses one: the fields of a request are
    named, and a list or a number names nothing.
    """
    if encoded is None:
        return {}
    try:
        decoded = json.loads(encoded)
    except ValueError:
        pass
    else:
        if isinstance(decoded, dict):
            return decoded
    # Raised outside the handler: a `JSONDecodeError` renders the document
    # around the offending character, which is the operator's own content.
    raise InvalidRequestError()


def _arguments(parsed: argparse.Namespace) -> Mapping[str, Any]:
    """The request document, assembled from what the operator actually supplied.

    Absent options are absent from the document rather than present and `None`,
    because `RequestMetadata` distinguishes the two: a field that is not there
    takes the contract's default, and one that is there and null is a rejected
    value. Passing `None` would silently turn "I did not say" into "I said
    nothing", which is exactly the coercion `AGENTS.md` section 5 forbids.
    """
    document: dict[str, Any] = {}
    for field in _ENVELOPE_OPTIONS.values():
        supplied = getattr(parsed, field)
        if supplied is not None:
            document[field] = supplied
    scope = {
        field: getattr(parsed, field)
        for field in _SCOPE_OPTIONS.values()
        if getattr(parsed, field) is not None
    }
    if scope:
        document["scope"] = scope
    document[PAYLOAD_KEY] = _payload(parsed.payload)
    return _bounded(document)


def _bounded(document: Mapping[str, Any]) -> Mapping[str, Any]:
    """Refuse a request past the shared ceiling, or return it.

    Imported rather than restated. `MAX_REQUEST_BYTES` lives beside `normalize`
    because it is derived from the largest request the *contract* can express,
    so it belongs to the request rather than to a protocol, and three transports
    enforcing three numbers is the drift `SPEC-AC-001` exists to prevent.

    A shell can exceed it more easily than a socket can — an operator pasting a
    file into `--payload` is one keystroke — so this refuses rather than
    truncates, and the rejected value is not echoed.
    """
    try:
        encoded = json.dumps(document, separators=(",", ":")).encode()
    except (TypeError, ValueError):
        pass
    else:
        if len(encoded) <= MAX_REQUEST_BYTES:
            return document
    raise InvalidRequestError()


def _problem(error: ApplicationError) -> ProblemDetail:
    """Render a refusal this transport made, in the application's vocabulary."""
    return problem_detail(error, correlation_id=issue_identifier(IdKind.CORRELATION))


def run(
    argv: Sequence[str],
    service: ApplicationService,
    *,
    principal: Principal,
    out: IO[str],
) -> int:
    """Invoke one capability and write the answer to `out`. Returns the exit status.

    `principal` is the authenticated context the composition root established.
    It is the same object, established the same way, that the HTTP and MCP
    transports are handed — which is the whole of "the CLI is not a privileged
    bypass": there is no second principal and no flag that could ask for one.

    The terminal catch is the one `adapters/mcp/server.py` documents, for the
    same reason: `ApplicationService.invoke` already refuses to raise, and what
    is left is this module's own rendering. A traceback on a terminal is a
    disclosure, and it is the disclosure a test of response bodies never sees.
    """
    try:
        parsed = build_parser().parse_args(list(argv))
        metadata, command = normalize(parsed.capability, _arguments(parsed))
    except ApplicationError as refusal:
        return _write(out, _problem(refusal).to_canonical_json(), EXIT_FAILED)
    except Exception:
        return _write(out, _problem(InternalError()).to_canonical_json(), EXIT_FAILED)
    try:
        envelope = service.invoke(metadata, command, principal=principal)
    except Exception:
        return _write(out, _problem(InternalError()).to_canonical_json(), EXIT_FAILED)
    status = EXIT_OK if envelope.error is None else EXIT_FAILED
    return _write(out, envelope.to_canonical_json(), status)


def _write(out: IO[str], document: str, status: int) -> int:
    out.write(f"{document}\n")
    out.flush()
    return status
