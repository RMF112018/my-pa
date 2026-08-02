"""HTTP in, one `invoke`, an envelope out.

Everything this module does is protocol: match a path, refuse a body it will not
read, decode JSON, hand the pair to `normalize`, call `invoke` once, and encode
what came back. There is no decision in it. The authorization, the disclosure,
the coverage, the error classification, and the transaction all happened behind
`ApplicationService.invoke`, and the response body is the bytes the envelope
serialised itself to — not a shape assembled here from its parts.

**Starlette, not FastAPI** (`D-25`). The parity criterion needs both transports
to build the same `(RequestMetadata, Command)` pair, which is provable while
there is one validation path — `contracts/v1` and `application.commands` — and
merely testable once a framework adds a second one that only HTTP has.

**Synchronous endpoints** (`D-27`). The endpoint below is `def`, so Starlette
runs it in its worker thread pool and the synchronous application, unit of work,
and driver run there rather than on the event loop. Reading a request body is
the one thing that must happen *on* the loop, because ASGI delivers it through
an awaitable; `_Body` is that one bridge, and it is stdlib `asyncio` rather than
a new dependency. The guard inside it is not decoration: calling it from the
loop thread would deadlock the process, and a guard that raises is strictly
better than a server that stops answering.

**Two response shapes, because there are two kinds of answer.** A request the
application answered is returned as its `ResponseEnvelope`, error or not. A
request that never became one — unparseable, oversized, addressed to a
capability that does not exist — has no envelope to return: an envelope requires
the caller's `request_id`, and inventing one would be this module fabricating the
identity of a request it could not read. Those answer with the `ProblemDetail`
alone, built by the same `problem_detail` the application uses, so the error
vocabulary stays single even though the envelope cannot be.

**Status is a function of the code, and of nothing else.** `_STATUS` maps the
eleven public error codes onto HTTP, and the endpoint reads it; there is no
branch that inspects a request and picks a status. So a status can never claim
something the body does not, which is the transport-side reinterpretation
`AC-1` forbids. The two exceptions are HTTP's own: a path that matches no route
is `404` and a method that matches no route is `405`, because those are answers
about the URL rather than about a request, and their bodies still carry a typed
code.

**What is refused before anything is read.** A body without a `content-length`,
one that declares more than `MAX_REQUEST_BYTES`, and one that is not
`application/json`. `module-boundaries.md` section 5.7 puts transport limits
here, and refusing on the declared length is what keeps an oversized body from
being buffered before it is rejected. Requiring the header at all is a bounded
transport rule rather than an HTTP-wide one: this gateway is loopback-only
(`D-30`), its clients are local, and a chunked body cannot be bounded before it
has been read.

**No credential is issued, read, or required** (`D-30`). The acting principal is
supplied by the composition root and is a property of the process, not of the
request; `metadata.principal_id` arrives from the caller and stays what the
contract says it is, correlation input the application does not trust.
`P00-OD-010` is open and selecting an authentication mechanism belongs to the
operator, so this module has no notion of one to select.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any, Final

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect, Request
from starlette.responses import Response
from starlette.routing import Route

from my_pa.adapters.normalization import normalize
from my_pa.application.errors import ApplicationError, InvalidRequestError, problem_detail
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.principal import Principal
from my_pa.domain.source.enrollment import MAX_ENROLLMENT_ITEMS
from my_pa.domain.source.registry import issue_identifier

__all__ = ["MAX_REQUEST_BYTES", "PATH_TEMPLATE", "create_http_app"]

#: Where a capability is addressed. The name is a path segment rather than a
#: field, so that the capability a request is routed to and the capability it is
#: authorized as come from one place. MCP's tool name is the same position.
PATH_TEMPLATE: Final = "/v1/{capability}"

#: The one media type this transport reads and writes.
_JSON: Final = "application/json"

#: An identifier in a JSON array: at most 72 characters, which is the bound
#: `domain.common.identifiers` enforces, plus the two quotes and the comma that
#: carry it. Restated rather than imported because that bound is private to the
#: module that enforces it — and checked rather than trusted, by
#: `test_the_request_ceiling_admits_the_largest_request_the_contract_allows`,
#: which builds identifiers at the real maximum and measures the result.
_IDENTIFIER_JSON_BYTES: Final = 75

#: Everything a request carries that is not `sources.enroll`'s object list. An
#: enrollment may name 32 media types and neither the domain nor the contract
#: bounds one's length, so this is where a media type is bounded, at 128 bytes
#: each. The rest is small and enumerable: a request id and an idempotency key
#: at 128 characters each, a search query and a cursor at 512 characters and at
#: most four UTF-8 bytes per character, and a dozen short scalars. Eight
#: kibibytes covers all of it several times over.
_ENVELOPE_BYTES: Final = 32 * 128 + 8 * 1024

#: Most bytes one request body may carry, derived from the largest request the
#: contract can express rather than chosen as a round number. `sources.enroll`
#: at its domain ceiling is that request: `MAX_ENROLLMENT_ITEMS` object
#: identifiers, and everything else beside them.
#:
#: A caller can exceed this — `RequestMetadata.scope` takes identifier lists the
#: contract does not bound — and exceeding it is refused rather than truncated.
#: The declared scope is correlation input that authorization does not read, so
#: nothing is lost by bounding it here.
MAX_REQUEST_BYTES: Final = MAX_ENROLLMENT_ITEMS * _IDENTIFIER_JSON_BYTES + _ENVELOPE_BYTES

#: The HTTP status each public error code is. Written out as a table rather than
#: derived from a rule, because the eleven codes do not fall into HTTP's classes
#: by any rule that would still be true after the twelfth.
#:
#: `denied` and `not_found` are deliberately different statuses even though
#: `docs/specs` section 10 requires the two answers to be indistinguishable to a
#: prober. What that rule protects is the *inference* that a subject exists, and
#: the application is what protects it: an object identifier that names nothing
#: is answered `denied`, not `not_found`, so the pair a caller could subtract is
#: never produced. Collapsing the statuses here would hide a distinction the
#: application already declines to make.
_STATUS: Mapping[ErrorCode, int] = MappingProxyType(
    {
        # The caller can fix these by sending a different request.
        ErrorCode.INVALID_REQUEST: 400,
        ErrorCode.AMBIGUOUS_REQUEST: 400,
        # Authority, not syntax.
        ErrorCode.DENIED: 403,
        # A policy stop on evidence that exists. `403` rather than `409`: it is a
        # refusal to disclose, and only an operator review lifts it.
        ErrorCode.QUARANTINED: 403,
        ErrorCode.NOT_FOUND: 404,
        # State, at the moment the request was made.
        ErrorCode.CONFLICT: 409,
        ErrorCode.CANCELLED: 409,
        ErrorCode.RATE_LIMITED: 429,
        # This build does not serve it, and no retry changes that.
        ErrorCode.UNSUPPORTED: 501,
        ErrorCode.INTERNAL_ERROR: 500,
        ErrorCode.UNAVAILABLE: 503,
    }
)


class _Body:
    """Reads a request body from a worker thread, on the loop that owns it.

    ASGI delivers a body through an awaitable, and `D-27` puts the endpoint in a
    thread so the synchronous application does not run on the event loop. The
    two facts meet here: the loop is recorded by `_Gateway.__call__`, which runs
    on it, and every read is scheduled back onto it and waited for from the
    worker thread.

    Stdlib `asyncio` rather than `anyio`'s equivalent bridge, because
    `AGENTS.md` section 2 admits a dependency only for a problem the standard
    library cannot reasonably solve, and this is four lines of `asyncio`.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None

    def capture(self) -> None:
        """Record the loop this application is running on."""
        self._loop = asyncio.get_running_loop()

    def read(self, request: Request) -> bytes:
        """The complete body of `request`, read from a worker thread."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            # Scheduling onto a loop from the thread running it waits forever.
            # This cannot happen while the endpoint is `def` — which is the
            # whole of `D-27` — so reaching it means that changed, and a raised
            # error is how that arrives as a failure rather than as a hang.
            raise RuntimeError("the endpoint is running on the event loop, not in a worker thread")
        loop = self._loop
        if loop is None:
            raise RuntimeError("the gateway was asked to read a body before it started")
        return asyncio.run_coroutine_threadsafe(request.body(), loop).result()


class _Gateway(Starlette):
    """Starlette, plus the one fact an ASGI entry point knows and a thread does not.

    An ASGI application is *called* on the event loop and the result is then
    awaited, so the call itself can be an ordinary `def` that returns the
    coroutine Starlette would have returned. That single line is where the loop
    is recorded, and it is why this transport needs neither a lifespan handler
    nor a coroutine of its own to find one: a lifespan is an async context
    manager, and `D-27` says this package writes none. Starlette's `on_startup`
    would also have worked and is deprecated in favour of exactly that lifespan,
    so it would have been a warning in every run in exchange for nothing.

    `markcoroutinefunction` is not a trick played on the server. A server
    decides between ASGI 2 and ASGI 3 by asking whether the application is a
    coroutine function, and this one *is* — `__call__` returns a coroutine, and
    the only reason the question is answered wrongly by default is that the
    coroutine is produced rather than declared. The standard library added this
    marker in 3.12 for precisely that case.
    """

    def __init__(self, body: _Body, **options: Any) -> None:  # noqa: ANN401 - Starlette's own
        super().__init__(**options)
        self._body = body

    def __call__(self, scope: Any, receive: Any, send: Any) -> Any:  # noqa: ANN401 - ASGI
        self._body.capture()
        return super().__call__(scope, receive, send)


inspect.markcoroutinefunction(_Gateway.__call__)


def _problem_response(error: ApplicationError) -> Response:
    """Render a refusal this transport made, in the application's vocabulary.

    A correlation identifier is issued here because the request never reached
    the application and no correlation identifier exists yet. It is what an
    operator correlates the refusal by; nothing else in the response is new.
    """
    problem = problem_detail(error, correlation_id=issue_identifier(IdKind.CORRELATION))
    return Response(
        problem.to_canonical_json(), status_code=_STATUS[problem.code], media_type=_JSON
    )


def _envelope_response(envelope: ResponseEnvelope) -> Response:
    """Return the envelope the application produced, verbatim."""
    status = 200 if envelope.error is None else _STATUS[envelope.error.code]
    return Response(envelope.to_canonical_json(), status_code=status, media_type=_JSON)


def _declared_length(request: Request) -> int:
    """The body length the caller declared, or a refusal."""
    declared = request.headers.get("content-length")
    if declared is None:
        raise InvalidRequestError()
    try:
        length = int(declared)
    except ValueError:
        pass
    else:
        if 0 <= length <= MAX_REQUEST_BYTES:
            return length
    raise InvalidRequestError()


def _check_media_type(request: Request) -> None:
    """Refuse a body this transport does not read."""
    declared = request.headers.get("content-type", "")
    if declared.split(";")[0].strip().lower() != _JSON:
        raise InvalidRequestError()


def _document(body: bytes) -> Mapping[str, Any]:
    """The request document, or a refusal.

    A JSON value that is not an object is refused rather than coerced: the
    arguments of a request are named, and a list or a number names nothing.
    """
    try:
        decoded = json.loads(body)
    except ValueError:
        pass
    else:
        if isinstance(decoded, dict):
            return decoded
    # Outside the handler: a `JSONDecodeError` renders the document around the
    # offending character, which is the caller's content.
    raise InvalidRequestError()


def create_http_app(service: ApplicationService, *, principal: Principal) -> Starlette:
    """The ASGI application serving `service` as the one local `principal`.

    `principal` is the authenticated context the composition root established.
    It is fixed for the life of the process because the process is what the
    trust boundary is: one local operator behind a loopback socket (`D-30`).
    """
    body = _Body()

    def invoke(request: Request) -> Response:
        """One request: map it, run it once, map the answer back."""
        try:
            _check_media_type(request)
            declared = _declared_length(request)
            received = body.read(request)
            if len(received) > declared:
                # The framing disagreed with the declaration. Refused rather
                # than trusted, so the bound above is a bound on what was read
                # and not only on what was promised.
                raise InvalidRequestError()
            metadata, command = normalize(request.path_params["capability"], _document(received))
        except ClientDisconnect:
            # "malformed, incomplete, or contradictory" — the request stopped
            # arriving. Classified rather than left to escape as a server fault
            # for a client that is already gone.
            return _problem_response(InvalidRequestError())
        except ApplicationError as refusal:
            return _problem_response(refusal)
        return _envelope_response(service.invoke(metadata, command, principal=principal))

    def not_a_request(request: Request, exception: Exception) -> Response:
        """A URL that addresses no capability, answered in the same vocabulary.

        The status stays HTTP's own — `404` for a path, `405` for a method —
        because those describe the URL rather than a request the application
        could have refused. The body carries `invalid_request`, which is what it
        is: nothing here was addressed to a capability.
        """
        status = exception.status_code if isinstance(exception, HTTPException) else 400
        problem = problem_detail(
            InvalidRequestError(), correlation_id=issue_identifier(IdKind.CORRELATION)
        )
        return Response(problem.to_canonical_json(), status_code=status, media_type=_JSON)

    return _Gateway(
        body,
        routes=[Route(PATH_TEMPLATE, invoke, methods=["POST"])],
        exception_handlers={HTTPException: not_a_request},
    )
