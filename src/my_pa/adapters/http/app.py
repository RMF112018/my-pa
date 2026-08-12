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

**A request is bounded in time as well as in bytes, and it was not.** The first
version of this module bounded only size, and an independent review measured
what that costs: forty-five clients that declared a `content-length` and then
sent nothing pinned every thread in Starlette's pool, the gateway stopped
answering, and it would not shut down. Each cost about 130 bytes and no
credential. That is availability rather than disclosure, and it is still a
defect, because two documents promised otherwise — this docstring said the
request was bounded, and the runbook promised the operator that `SIGTERM`
completes. `BODY_TIMEOUT_SECONDS` is the missing half of the bound.

The cost is a *direct* consequence of `D-27` and is worth naming rather than
hiding: an `async def` endpoint would await the body on the event loop and pin
no thread at all — the reviewer built that control and it answered in
milliseconds with two threads. A synchronous endpoint cannot, so the achievable
guarantee is that the stall is bounded and self-clearing rather than absent, and
the tests assert exactly that and not more.

**Two ways the acting principal arrives, and the transport chooses neither.**
`create_http_app` takes exactly one of `principal` and `authenticate`, and
composing it with both or with neither is a `ValueError` at startup rather than a
default.

* With `principal` this is `D-30` unchanged: the acting principal is supplied by
  the composition root and is a property of the process, not of the request. No
  credential is issued, read, or required.
* With `authenticate` every request must present `Authorization: Bearer <token>`
  and the composition root turns it into a `Principal`. This module does not
  verify a token, does not know what a claim is, and names no `PrincipalKind` —
  it reads one header, hands it over with the request document, and maps a
  refusal onto a status. The decision stays where every other decision is.

Either way `metadata.principal_id` arrives from the caller and stays what the
contract says it is, correlation input the application does not trust, and
`tests/architecture/test_principal_is_never_caller_supplied.py` is what keeps
that a measurement.

**`401` is HTTP's own answer, like `404` and `405` are.** Authentication happens
before a request exists — before `normalize` has built one and therefore before
there is a `request_id` an envelope could be addressed to — so the answer is a
`ProblemDetail` alone, exactly as an unroutable URL is. It carries the `denied`
code, because that is what it is in the application's vocabulary, and the status
is HTTP's answer about a credential rather than the application's about a
request. The body is a fixed refusal: no token, no claim, no header, and no hint
of which of the several ways it failed, since each of those distinctions is an
oracle. `_STATUS` is untouched and still maps every public error code, which is
the invariant `AC-1` needs.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, Final

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import ClientDisconnect, Request
from starlette.responses import Response
from starlette.routing import Route

from my_pa.adapters.normalization import MAX_REQUEST_BYTES, normalize
from my_pa.application.errors import (
    ApplicationError,
    DeniedError,
    InvalidRequestError,
    problem_detail,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.user_account import TokenClaimsError
from my_pa.domain.source.registry import issue_identifier

__all__ = ["PATH_TEMPLATE", "create_http_app"]

#: Where a capability is addressed. The name is a path segment rather than a
#: field, so that the capability a request is routed to and the capability it is
#: authorized as come from one place. MCP's tool name is the same position.
PATH_TEMPLATE: Final = "/v1/{capability}"

#: The one media type this transport reads and writes.
_JSON: Final = "application/json"

#: The header a bearer credential arrives in, and the challenge sent back with a
#: refusal. Both are RFC 6750's; neither is a name this transport invented.
_CREDENTIAL_HEADER: Final = "authorization"
_CHALLENGE: Final = "Bearer"

#: HTTP's answer when a request carried no usable credential. Not in `_STATUS`
#: on purpose: `_STATUS` maps the eleven public *error codes*, and this is not
#: one of them — see the module docstring.
_UNAUTHENTICATED: Final = 401

#: How long a client has to deliver the body it announced, before the request is
#: refused and the worker thread released.
#:
#: Derived rather than chosen: it is uvicorn's `timeout_keep_alive`, which is the
#: number this same process already uses for how long a *connection* may sit idle
#: between requests. A client that goes quiet halfway through a request is in the
#: same state as one that goes quiet between two, and answering "as long as this
#: process already waits for that" is a reason where five seconds on its own is
#: not. It is restated here rather than imported because the package may not
#: import uvicorn — running a server is the composition root's act — and
#: `test_the_body_timeout_is_the_servers_own_idle_bound` reads the real default
#: off `uvicorn.Config` so the restatement is a checked claim.
#:
#: It is generous for the case it exists to bound. On loopback a legitimate body
#: is already in the socket buffer when the endpoint asks for it, and the largest
#: one this transport accepts is under a mebibyte.
BODY_TIMEOUT_SECONDS: Final = 5.0

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
        """The complete body of `request`, read from a worker thread, or a refusal.

        The wait is bounded, and the cancellation matters as much as the bound:
        without it the coroutine would go on waiting on the loop for a client
        that is not sending, so the thread would be released and the task would
        not. `TimeoutError` leaves here for the endpoint to classify, because
        deciding what a failure *is* belongs one level up even when it is this
        obvious.
        """
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
        pending = asyncio.run_coroutine_threadsafe(request.body(), loop)
        try:
            return pending.result(timeout=BODY_TIMEOUT_SECONDS)
        except TimeoutError:
            pending.cancel()
            raise


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


def _unauthenticated_response() -> Response:
    """The one answer every authentication failure gets.

    Built from `DeniedError` so the typed code in the body is the application's
    own `denied` rather than a second vocabulary this transport invented, and
    returned with `401` because the caller's problem is a credential rather than
    an authority — the same reason `not_a_request` returns HTTP's `404` under an
    `invalid_request` body. The challenge header states the scheme and nothing
    else: no `realm`, no `error_description`, and no scope, because each of those
    describes the deployment to whoever asks.
    """
    problem = problem_detail(DeniedError(), correlation_id=issue_identifier(IdKind.CORRELATION))
    return Response(
        problem.to_canonical_json(),
        status_code=_UNAUTHENTICATED,
        media_type=_JSON,
        headers={"www-authenticate": _CHALLENGE},
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


def create_http_app(
    service: ApplicationService,
    *,
    principal: Principal | None = None,
    authenticate: Callable[[str | None, Mapping[str, Any]], Principal] | None = None,
) -> Starlette:
    """The ASGI application serving `service`, in exactly one of two modes.

    `principal` is the authenticated context the composition root established.
    It is fixed for the life of the process because the process is what the
    trust boundary is: one local operator behind a loopback socket (`D-30`).

    `authenticate` is the alternative: the composition root's per-request
    authentication, given the raw `Authorization` header and the request
    document, returning the acting `Principal` or raising `TokenClaimsError`.

    Exactly one, checked here rather than defaulted. Neither would be a
    transport that cannot name a caller; both would be a transport with two
    answers to the same question, and the safe-looking resolution — prefer the
    authenticator, fall back to the fixed principal — is precisely the silent
    permissive fallback this mode exists to remove.
    """
    if (principal is None) == (authenticate is None):
        raise ValueError(
            "compose the transport with exactly one of `principal` (the fixed "
            "local-operator mode) or `authenticate` (the per-request mode)"
        )
    body = _Body()

    def fixed_principal() -> Principal:
        """The composed process principal, in the mode that has one."""
        if principal is None:  # pragma: no cover - the composition check forbids this
            raise ValueError("this transport was composed without a fixed principal")
        return principal

    def invoke(request: Request) -> Response:
        """One request: map it, authenticate it, run it once, map the answer back."""
        try:
            _check_media_type(request)
            declared = _declared_length(request)
            received = body.read(request)
            if len(received) > declared:
                # The framing disagreed with the declaration. Refused rather
                # than trusted, so the bound above is a bound on what was read
                # and not only on what was promised.
                raise InvalidRequestError()
            document = _document(received)
        except (ClientDisconnect, TimeoutError):
            # "malformed, incomplete, or contradictory" — the request stopped
            # arriving, either because the client went away or because it never
            # sent what it said it would. Classified rather than left to escape
            # as a server fault for a caller that is not listening anyway.
            return _problem_response(InvalidRequestError())
        except ApplicationError as refusal:
            return _problem_response(refusal)

        if authenticate is None:
            # `D-30`: no header is read at all, because none is required.
            acting = fixed_principal()
        else:
            # Before `normalize`, so an unauthenticated caller is refused
            # without this process building a command for it.
            try:
                acting = authenticate(request.headers.get(_CREDENTIAL_HEADER), document)
            except TokenClaimsError:
                return _unauthenticated_response()

        try:
            metadata, command = normalize(request.path_params["capability"], document)
        except ApplicationError as refusal:
            return _problem_response(refusal)
        return _envelope_response(service.invoke(metadata, command, principal=acting))

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
