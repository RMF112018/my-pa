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

**A second address, a second credential plane, and the same application**
(WP-10). `REMOTE_CAPTURE_PATH` is where an authenticated remote client submits a
capture. What it shares with `PATH_TEMPLATE` is everything that matters: the same
`normalize`, the same `service.invoke`, the same envelope, the same body bounds
and the same timeout, read through the same `_Body`. What differs is three
things, and each is narrower rather than wider:

* the credential is `Authorization: ClientCredential …` rather than `Bearer …`,
  and the composition root parses it. The two schemes are mutually refused, so a
  person's token cannot submit here and a device's secret cannot invoke a
  capability there;
* the capability is a constant, not a path segment, so a remote client addresses
  `capture.create` and has no way to name anything else;
* the caller may not state `principal_id` anywhere, and this transport supplies
  the one the credential resolved to. Elsewhere a stated identity is accepted and
  ignored; here it is refused.

**The ingress is off unless an operator turned it on**, and the route is mounted
either way. `remote_client=None` is the off state and the handler answers `501`
before reading a credential or a body, so "disabled" is a refusal a request meets
rather than an address that is not there. That is deliberate: a vanishing route
can only be tested by inspecting the routing table, and a test that inspects the
routing table proves nothing about the handler that would run if it were mounted
for any other reason.

**A query string is refused outright on the ingress**, which is stronger than
ignoring one. `QC-AC-041` names URL parameters as a sink for capture text, and a
caller that put a note in `?text=` and received `200` would have been told it was
fine. Nothing on this path reads the URL beyond matching it.

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

from my_pa.adapters.normalization import MAX_REQUEST_BYTES, PAYLOAD_KEY, normalize
from my_pa.application.apple_machine import (
    AppleBridgeIdentity,
    AppleMachineControl,
    AppleMachineCredentialError,
)
from my_pa.application.errors import (
    ApplicationError,
    DeniedError,
    InternalError,
    InvalidRequestError,
    UnsupportedError,
    problem_detail,
)
from my_pa.application.native_sources import AdmissionDeniedError
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.user_account import TokenClaimsError
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "APPLE_ADMIT_PATH",
    "APPLE_POLL_PATH",
    "PATH_TEMPLATE",
    "REMOTE_CAPTURE_CAPABILITY",
    "REMOTE_CAPTURE_PATH",
    "WEBAUTHN_PATH",
    "create_http_app",
]

#: Where a capability is addressed. The name is a path segment rather than a
#: field, so that the capability a request is routed to and the capability it is
#: authorized as come from one place. MCP's tool name is the same position.
PATH_TEMPLATE: Final = "/v1/{capability}"

#: Where an authenticated remote client submits a capture (WP-10).
#:
#: **A literal path with no placeholder at all**, which is a narrower address
#: than `PATH_TEMPLATE`'s and deliberately so: a remote client addresses one
#: capability and there is no segment through which it could name another. A
#: template here would have made "a remote credential cannot invoke
#: `sources.enroll`" a rule somebody has to enforce; a constant makes it a fact
#: about the routing table.
#:
#: It carries the capability's own name so that a reader of an access log — or
#: of a reverse-proxy rule an operator writes — can see which capability the
#: path reaches without consulting this file.
REMOTE_CAPTURE_PATH: Final = "/remote/v1/capture.create"

#: The capability `REMOTE_CAPTURE_PATH` routes to. A string rather than an import
#: of `Capability`, because this module names no member of that enum anywhere
#: else and `normalize` takes the name a transport routed on — the same string an
#: HTTP path segment or an MCP tool name supplies.
REMOTE_CAPTURE_CAPABILITY: Final = "capture.create"

APPLE_POLL_PATH: Final = "/apple/v1/grant.poll"
APPLE_ADMIT_PATH: Final = "/apple/v1/envelope.admit"
WEBAUTHN_PATH: Final = "/webauthn/v1/{action:path}"

#: The one media type this transport reads and writes.
_JSON: Final = "application/json"

#: The header a bearer credential arrives in, and the challenge sent back with a
#: refusal. Both are RFC 6750's; neither is a name this transport invented.
_CREDENTIAL_HEADER: Final = "authorization"
_CHALLENGE: Final = "Bearer"

#: The challenge the remote ingress sends back instead. A different scheme, so a
#: client that presents the wrong kind of credential is told which kind this
#: address takes — and so the two planes are visibly disjoint from outside the
#: process as well as inside it. The composition root is what parses it; this
#: module only names it in a refusal.
_CLIENT_CHALLENGE: Final = "ClientCredential"

#: The envelope field a remote caller may not state. Named here rather than
#: written twice inside the check, so the refusal and the substitution cannot
#: come to disagree about which field they are about.
_IDENTITY_FIELD: Final = "principal_id"

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
# The Swift host's bounded one-mebibyte payload is represented as JSON integer
# arrays on this exact machine route. Five bytes per input byte covers `255,`
# plus the bounded envelope fields without widening any public capability route.
APPLE_MACHINE_MAX_REQUEST_BYTES: Final = 5 * 1_048_576

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


def _unauthenticated_response(challenge: str = _CHALLENGE) -> Response:
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
        headers={"www-authenticate": challenge},
    )


def _envelope_response(envelope: ResponseEnvelope) -> Response:
    """Return the envelope the application produced, verbatim."""
    status = 200 if envelope.error is None else _STATUS[envelope.error.code]
    return Response(envelope.to_canonical_json(), status_code=status, media_type=_JSON)


def _declared_length(request: Request, *, maximum: int = MAX_REQUEST_BYTES) -> int:
    """The body length the caller declared, or a refusal."""
    declared = request.headers.get("content-length")
    if declared is None:
        raise InvalidRequestError()
    try:
        length = int(declared)
    except ValueError:
        pass
    else:
        if 0 <= length <= maximum:
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


def _without_caller_identity(
    document: Mapping[str, Any], principal: Principal
) -> Mapping[str, Any]:
    """The document with the authenticated identity supplied, or a refusal.

    Takes the `Principal` rather than its identifier, so the value substituted in
    is read off the object the composition root resolved and cannot have come
    from anywhere else — which is what
    `tests/architecture/test_principal_is_never_caller_supplied.py` measures
    rather than assumes.

    Refuses `principal_id` in the envelope **and** in the payload, then puts the
    authenticated one in the envelope, where `RequestMetadata` requires it. The
    payload check is not redundant with `entra_authenticator`'s: that one is on
    the other plane, and a rule proved in one shape and not in its neighbour is
    the failure this campaign keeps finding.

    Building a new mapping rather than mutating: the caller's document is not
    this function's to edit, and a copy makes it impossible for the refusal above
    to have been bypassed by a key inserted after the check.
    """
    payload = document.get(PAYLOAD_KEY)
    named_in_payload = isinstance(payload, Mapping) and _IDENTITY_FIELD in payload
    if _IDENTITY_FIELD in document or named_in_payload:
        raise InvalidRequestError()
    return {**document, _IDENTITY_FIELD: principal.principal_id}


def create_http_app(
    service: ApplicationService,
    *,
    principal: Principal | None = None,
    authenticate: Callable[[str | None, Mapping[str, Any]], Principal] | None = None,
    remote_client: Callable[[str | None], Principal] | None = None,
    apple_authenticate: Callable[[str | None], AppleBridgeIdentity] | None = None,
    apple_control: AppleMachineControl | None = None,
    webauthn: Callable[[Request, Mapping[str, Any]], Response] | None = None,
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

    `remote_client` is a **third**, independent thing rather than a third mode:
    the composition root's authentication for a registered capture client, or
    `None`. It is orthogonal to the two above because the ingress is a separate
    credential plane — either mode may run with it or without it — and `None`
    is what every process that has not turned it on receives.

    **The ingress route is mounted whether or not `remote_client` is composed**,
    and the refusal lives in the handler. A route that vanished when the switch
    was off would make "disabled" indistinguishable from "this build has no such
    address", which reads as the stronger property and is the weaker one: it can
    only ever be tested by asking the routing table, and a future change that
    mounted the route for some other reason would silently serve. Mounting it
    always means the disabled state is something a real request meets and a test
    can drive.
    """
    if (principal is None) == (authenticate is None):
        raise ValueError(
            "compose the transport with exactly one of `principal` (the fixed "
            "local-operator mode) or `authenticate` (the per-request mode)"
        )
    if (apple_authenticate is None) != (apple_control is None):
        raise ValueError("Apple machine authentication and control must be composed together")
    body = _Body()

    def fixed_principal() -> Principal:
        """The composed process principal, in the mode that has one."""
        if principal is None:  # pragma: no cover - the composition check forbids this
            raise ValueError("this transport was composed without a fixed principal")
        return principal

    def read_document(request: Request, *, maximum: int = MAX_REQUEST_BYTES) -> Mapping[str, Any]:
        """The request document, or a refusal, with every transport bound applied.

        Factored out because the ingress route below reads a body under exactly
        the same rules — media type, declared length, the ceiling, the timeout,
        and the framing check — and two copies of a bound is how two transports
        come to enforce two numbers.
        """
        _check_media_type(request)
        declared = _declared_length(request, maximum=maximum)
        received = body.read(request)
        if len(received) > declared:
            # The framing disagreed with the declaration. Refused rather than
            # trusted, so the bound above is a bound on what was read and not
            # only on what was promised.
            raise InvalidRequestError()
        return _document(received)

    def invoke(request: Request) -> Response:
        """One request: map it, authenticate it, run it once, map the answer back."""
        try:
            document = read_document(request)
        except (ClientDisconnect, TimeoutError):
            # "malformed, incomplete, or contradictory" — the request stopped
            # arriving, either because the client went away or because it never
            # sent what it said it would. Classified rather than left to escape
            # as a server fault for a caller that is not listening anyway.
            return _problem_response(InvalidRequestError())
        except ApplicationError as refusal:
            return _problem_response(refusal)
        except Exception:
            # The body-read block's own terminal catch. It was missing here
            # while `submit`'s equivalent block had one, so the asymmetry a
            # previous commit claimed to have closed was merely inverted: this
            # route answered a bare `500` for a fault in `read_document` while
            # the other answered an envelope. The rule is per route, so it is
            # applied to every block of both.
            return _problem_response(InternalError())

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
        except Exception:
            # The terminal catch the CLI and MCP transports both carry, and this
            # one did not. `normalize` promises `InvalidRequestError` and nothing
            # else, but a command that reads a caller-supplied field without
            # first checking its type raises `AttributeError` instead, which is
            # not an `ApplicationError` and so escaped to Starlette as a bare
            # `500` with no envelope and no correlation identifier. Catching the
            # class here means a single command's missing type check can no
            # longer decide whether this transport answers in its own vocabulary.
            return _problem_response(InternalError())
        try:
            envelope = service.invoke(metadata, command, principal=acting)
        except Exception:
            # `invoke` has its own terminal catch, so reaching this is a fault in
            # the mapping between them rather than in a handler. Answered the
            # same way for the same reason: the envelope is the contract.
            return _problem_response(InternalError())
        return _envelope_response(envelope)

    def submit(request: Request) -> Response:
        """One remote capture: refuse unless everything about it is right.

        The order below is the order the refusals have to happen in.

        1. **The switch.** `remote_client is None` is the ingress being disabled,
           and it is answered `501` — "this build does not serve it, and no retry
           changes that", which is exactly true — before a credential is read, a
           body is read, or a connection is taken. Nothing about the request can
           make this branch not happen.
        2. **The query string.** A remote submission carries its note in a body
           and *only* in a body, so any query string at all is refused rather
           than ignored. Ignoring one is the usual answer and it is the wrong
           one here: a caller that put the note in `?text=` and got a `200` would
           have written it into a request line, a reverse-proxy log and a device
           history, and a success would tell them it was fine to keep doing it.
           This is `QC-AC-041`'s URL sink closed at the transport rather than
           inferred from the body being empty.
        3. **The credential**, before the body is read, so an unauthenticated
           caller never gets this process to parse a document for it.
        4. **A caller-supplied identity**, refused wherever it appears. The
           envelope's `principal_id` is required by the contract and is
           correlation input nothing reads (`D-13`/`D-14`); on this plane the
           caller may not state it *at all* and the transport supplies the one it
           authenticated. That is strictly narrower than the other transports —
           there, a caller may state an identity that is then ignored; here it
           cannot state one — and the narrowing is worth the asymmetry because
           this is the one plane where the caller is not the operator's own
           process.

        Everything after that is `invoke`'s own path: one `normalize`, one
        `service.invoke`, one envelope out. The capability is the route's
        constant, so a remote client cannot address a second one, and the
        transport it declares is provenance the composition root vouches for.
        """
        if remote_client is None:
            return _problem_response(UnsupportedError())
        if request.url.query:
            return _problem_response(InvalidRequestError())
        try:
            acting = remote_client(request.headers.get(_CREDENTIAL_HEADER))
        except TokenClaimsError:
            return _unauthenticated_response(_CLIENT_CHALLENGE)
        try:
            submitted = read_document(request)
            document = _without_caller_identity(submitted, acting)
            metadata, command = normalize(REMOTE_CAPTURE_CAPABILITY, document)
        except (ClientDisconnect, TimeoutError):
            return _problem_response(InvalidRequestError())
        except ApplicationError as refusal:
            return _problem_response(refusal)
        except Exception:
            # The terminal catch `invoke` carries, on the same grounds. It
            # reached `invoke` alone when it was added, while the claim made was
            # about "the transport" -- so the rule went to the route a reviewer
            # had pointed at and not to its sibling here, which is the shape
            # this branch keeps paying for. Then it reached this block and not
            # `invoke`'s body-read block, which inverted the asymmetry rather
            # than closing it; both now carry it.
            return _problem_response(InternalError())
        try:
            envelope = service.invoke(
                metadata, command, principal=acting, transport=CaptureTransport.REMOTE_CLIENT
            )
        except Exception:
            return _problem_response(InternalError())
        return _envelope_response(envelope)

    def apple_request(request: Request) -> Response:
        """Serve only the two credentialed, off-by-default Apple machine paths."""
        if apple_authenticate is None or apple_control is None:
            return _problem_response(UnsupportedError())
        if request.url.query:
            return _problem_response(InvalidRequestError())
        try:
            identity = apple_authenticate(request.headers.get(_CREDENTIAL_HEADER))
        except AppleMachineCredentialError:
            return _unauthenticated_response("AppleBridgeCredential")
        try:
            document = read_document(request, maximum=APPLE_MACHINE_MAX_REQUEST_BYTES)
        except (ClientDisconnect, TimeoutError):
            return _problem_response(InvalidRequestError())
        except ApplicationError as refusal:
            return _problem_response(refusal)
        if "principal_id" in document or "principalID" in document or "bridgeID" in document:
            return _problem_response(InvalidRequestError())
        try:
            result = (
                apple_control.poll(identity)
                if request.url.path == APPLE_POLL_PATH
                else apple_control.admit(identity, document)
            )
        except AppleMachineCredentialError:
            return _unauthenticated_response("AppleBridgeCredential")
        except (AdmissionDeniedError, ValueError, LookupError):
            return _problem_response(DeniedError())
        if result is None:
            return Response(status_code=204)
        return Response(
            json.dumps(result, separators=(",", ":"), sort_keys=True),
            status_code=200,
            media_type=_JSON,
        )

    def webauthn_request(request: Request) -> Response:
        """Ceremony routes: same body bounds as invoke, then the WebAuthn handler."""
        if webauthn is None:
            problem = problem_detail(
                InvalidRequestError(), correlation_id=issue_identifier(IdKind.CORRELATION)
            )
            return Response(problem.to_canonical_json(), status_code=503, media_type=_JSON)
        try:
            document = read_document(request)
        except (ClientDisconnect, TimeoutError):
            return _problem_response(InvalidRequestError())
        except ApplicationError as refusal:
            return _problem_response(refusal)
        except Exception:
            return _problem_response(InternalError())
        return webauthn(request, document)

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
        routes=[
            # The literal route is declared first so that it is matched as
            # itself. Starlette matches in order and `/v1/{capability}` cannot
            # match `/remote/v1/...` in any case, but ordering the specific
            # address ahead of the templated one keeps that a property of the
            # list rather than of the two paths happening not to overlap.
            Route(REMOTE_CAPTURE_PATH, submit, methods=["POST"]),
            Route(APPLE_POLL_PATH, apple_request, methods=["POST"]),
            Route(APPLE_ADMIT_PATH, apple_request, methods=["POST"]),
            Route(WEBAUTHN_PATH, webauthn_request, methods=["POST"]),
            Route(PATH_TEMPLATE, invoke, methods=["POST"]),
        ],
        exception_handlers={HTTPException: not_a_request},
    )
