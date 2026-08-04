"""One normalised request, whichever protocol delivered it.

A driving adapter's whole job is to turn `(capability name, arguments)` into the
`(RequestMetadata, Command)` pair `ApplicationService.invoke` takes. This module
is that turn, and it is shared rather than per-transport because
`SPEC-AC-001` asks for two transports that produce *equal* pairs — a claim that
is proved by construction when both call this function, and only tested by
sampling when each has its own copy.

**There is no validation here, and that is the point.** `D-25` chose Starlette
over FastAPI precisely so that HTTP would not acquire a second validation layer
that MCP has no counterpart for. So every rule a request is held to is already
owned by something else: `RequestMetadata` is a `StrictModel`, which rejects an
unknown field, a bad purpose, a malformed principal identifier, and the wrong
contract version; each command's `__post_init__` rejects a malformed identifier,
a contradictory selector, and a non-positive count. What this module does is
*shape* conversion — a JSON array is not a tuple and a JSON string is not a
`Representation` — plus the one classification that shape conversion needs: a
`TypeError` from a constructor that was handed a field it does not have becomes
`invalid_request` rather than escaping as a crash.

**Failures are raised, never rendered.** Every refusal leaves as
`InvalidRequestError`, which the caller renders through
`application.errors.problem_detail` exactly as the application's own refusals
are rendered. A transport that built its own error body would be a second error
vocabulary, and the point of one validation path is that there is one of those
too.

**Nothing here reads a value into a message.** The refusals below carry no
`safe_details` at all: the field names this layer could report — `request_id`,
`purpose`, `requested_at` — are not members of `application.errors.SafeDetail`,
and that closed set is what keeps a rejected value out of a public error. A
command's own refusal carries its own token, so the details a caller does get
are the ones the application already vouches for.

**The one bound that lives here, and why it is not in a transport.**
`MAX_REQUEST_BYTES` is derived from the largest request the *contract* can
express, not from anything a protocol does, so it is a property of the request
and belongs beside the function that builds one. It was written in
`adapters/http/app.py` when HTTP was the only transport, and WP-4B2b moved it:
three transports importing a ceiling from one transport's module would say that
deleting HTTP breaks MCP, which is false, and a structural claim that is false
misleads the next reader more than a duplicated constant would. Enforcing it is
still each transport's own act — HTTP refuses on the declared `content-length`
before reading, and the other two measure a document the protocol has already
delivered — but the number they enforce is one number.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Any, Final

from my_pa.application.commands import (
    Command,
    CreateCapture,
    DecideReviewCase,
    EnrollSource,
    FetchSource,
    GetCapabilities,
    GetSourceMetadata,
    GetSourceStatus,
    ListCaptures,
    ListReviewCases,
    ListSources,
    ReadCapture,
    ReadKnowledge,
    Representation,
    ReviseCapture,
    SearchCaptures,
    SearchKnowledge,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.domain.capture.review import Disposition
from my_pa.domain.capture.submission import CaptureKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.source.enrollment import MAX_ENROLLMENT_ITEMS

__all__ = ["MAX_REQUEST_BYTES", "PAYLOAD_KEY", "normalize"]

#: Where a request's capability-specific fields live, separated from the common
#: metadata beside them. Separate rather than flat because the two are validated
#: by different owners — the envelope by `RequestMetadata`, the payload by the
#: command — and a flat document would make "which owner rejected this" a
#: question about field names.
PAYLOAD_KEY: Final = "payload"

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

#: Most bytes one request may carry, derived from the largest request the
#: contract can express rather than chosen as a round number. `sources.enroll`
#: at its domain ceiling is that request: `MAX_ENROLLMENT_ITEMS` object
#: identifiers, and everything else beside them.
#:
#: `capture.create` at *its* domain ceiling is the other candidate and is
#: smaller: `MAX_CAPTURE_CHARACTERS` characters escape to at most six JSON bytes
#: each, which is under this bound with the envelope beside it. So the ceiling
#: the domain publishes for a capture is reachable over every transport rather
#: than being silently cut off by this one — which would refuse the largest legal
#: capture with `invalid_request` and no field to name.
#:
#: A caller can exceed this — `RequestMetadata.scope` takes identifier lists the
#: contract does not bound — and exceeding it is refused rather than truncated.
#: The declared scope is correlation input that authorization does not read, so
#: nothing is lost by bounding it here.
#:
#: It lives beside `normalize` rather than in a transport because it is derived
#: from the contract; see the module docstring.
MAX_REQUEST_BYTES: Final = MAX_ENROLLMENT_ITEMS * _IDENTIFIER_JSON_BYTES + _ENVELOPE_BYTES


def _strings(value: object, detail: SafeDetail) -> tuple[str, ...]:
    """A JSON array of strings as the tuple a command declares.

    JSON has no tuple and no way to say "strings only", so this is conversion
    rather than validation. It refuses a non-string entry because the field it
    feeds — an enrollment's media-type allowlist — would otherwise reach the
    domain as a list containing an integer and fail as a `TypeError` from a
    regular expression, which is a crash where a refusal belongs.
    """
    if not isinstance(value, list):
        raise InvalidRequestError(detail)
    items: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise InvalidRequestError(detail)
        items.append(item)
    return tuple(items)


def _get_capabilities(payload: Mapping[str, Any]) -> Command:
    return GetCapabilities(**payload)


def _list_sources(payload: Mapping[str, Any]) -> Command:
    return ListSources(**payload)


def _get_source_metadata(payload: Mapping[str, Any]) -> Command:
    return GetSourceMetadata(**payload)


def _fetch_source(payload: Mapping[str, Any]) -> Command:
    """`sources.fetch`, with the representation resolved to its enum member.

    Resolved here because `FetchSource` refuses anything that is not a
    `Representation`, so a caller's `"raw_bytes"` would otherwise be rejected for
    being a string rather than for naming something. An unresolvable string is
    refused with the same token the command uses, so the two paths report the
    same field.
    """
    named = payload.get("representation")
    if not isinstance(named, str):
        # Left alone: `FetchSource` refuses a non-string representation itself,
        # and an absent one takes the command's own default.
        return FetchSource(**payload)
    try:
        representation = Representation(named)
    except ValueError:
        pass
    else:
        return FetchSource(**{**payload, "representation": representation})
    raise InvalidRequestError(SafeDetail.REPRESENTATION)


def _get_source_status(payload: Mapping[str, Any]) -> Command:
    return GetSourceStatus(**payload)


def _enroll_source(payload: Mapping[str, Any]) -> Command:
    """`sources.enroll`, with its two JSON arrays converted to tuples.

    Converted only when present: `object_ids` is optional, and an absent one
    means the request selects a root instead — a distinction `EnrollmentScope`
    enforces and this must not erase by supplying an empty tuple of its own.
    """
    converted = dict(payload)
    if "media_types" in converted:
        converted["media_types"] = _strings(converted["media_types"], SafeDetail.MEDIA_TYPES)
    if "object_ids" in converted:
        converted["object_ids"] = _strings(converted["object_ids"], SafeDetail.SOURCE_OBJECT_ID)
    return EnrollSource(**converted)


def _search_knowledge(payload: Mapping[str, Any]) -> Command:
    return SearchKnowledge(**payload)


def _read_knowledge(payload: Mapping[str, Any]) -> Command:
    return ReadKnowledge(**payload)


#: The two caller-supplied times a capture may carry, and the token each is
#: refused under. Both are optional and neither is ever defaulted from the other
#: or from the request clock (`QC-AC-012`).
_CAPTURE_MOMENTS: Mapping[str, SafeDetail] = MappingProxyType(
    {
        "client_created_at": SafeDetail.CLIENT_CREATED_AT,
        "occurred_at": SafeDetail.OCCURRED_AT,
    }
)


def _moments(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve a capture's optional times from RFC 3339 strings to datetimes.

    Shape conversion, like `_fetch_source`'s representation: JSON has no
    datetime, and the command refuses anything that is not one, so a caller's
    `"2026-08-03T09:00:00Z"` would otherwise be rejected for being a string
    rather than for naming a moment. `fromisoformat` accepts the `Z` suffix on
    Python 3.11 and later, which is the form the contract publishes.

    A key that is absent stays absent, and a key that is present and `null`
    stays `None`: the command distinguishes "the caller did not say" from "the
    caller said nothing", and both mean the same stored value here — but
    inventing one from the request clock would be the coercion `QC-AC-012`
    exists to prevent, so neither is filled in.
    """
    converted = dict(payload)
    for name, detail in _CAPTURE_MOMENTS.items():
        supplied = converted.get(name)
        if supplied is None:
            continue
        if not isinstance(supplied, str):
            raise InvalidRequestError(detail)
        try:
            converted[name] = datetime.fromisoformat(supplied)
        except ValueError:
            pass
        else:
            continue
        # Outside the handler: the original renders the rejected value.
        raise InvalidRequestError(detail)
    return converted


def _create_capture(payload: Mapping[str, Any]) -> Command:
    converted = _moments(payload)
    named = converted.get("capture_kind")
    if isinstance(named, str):
        try:
            converted["capture_kind"] = CaptureKind(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.CAPTURE_KIND) from None
    return CreateCapture(**converted)


def _revise_capture(payload: Mapping[str, Any]) -> Command:
    return ReviseCapture(**_moments(payload))


def _read_capture(payload: Mapping[str, Any]) -> Command:
    return ReadCapture(**payload)


def _list_captures(payload: Mapping[str, Any]) -> Command:
    return ListCaptures(**payload)


def _search_captures(payload: Mapping[str, Any]) -> Command:
    return SearchCaptures(**payload)


def _list_review_cases(payload: Mapping[str, Any]) -> Command:
    return ListReviewCases(**payload)


def _decide_review_case(payload: Mapping[str, Any]) -> Command:
    converted = dict(payload)
    named = converted.get("disposition")
    if isinstance(named, str):
        try:
            converted["disposition"] = Disposition(named)
        except ValueError:
            raise InvalidRequestError(SafeDetail.DISPOSITION) from None
    return DecideReviewCase(**converted)


#: One builder per capability. A mapping rather than a `match`, so that
#: `test_every_capability_has_exactly_one_builder` can compare its keys against
#: `Capability` and a further capability cannot be unreachable over a transport
#: while the manifest publishes it.
_BUILDERS: Mapping[Capability, Callable[[Mapping[str, Any]], Command]] = MappingProxyType(
    {
        Capability.CAPABILITIES_GET: _get_capabilities,
        Capability.SOURCES_LIST: _list_sources,
        Capability.SOURCES_METADATA: _get_source_metadata,
        Capability.SOURCES_FETCH: _fetch_source,
        Capability.SOURCES_STATUS: _get_source_status,
        Capability.SOURCES_ENROLL: _enroll_source,
        Capability.KNOWLEDGE_SEARCH: _search_knowledge,
        Capability.KNOWLEDGE_READ: _read_knowledge,
        Capability.CAPTURE_CREATE: _create_capture,
        Capability.CAPTURE_REVISE: _revise_capture,
        Capability.CAPTURE_READ: _read_capture,
        Capability.CAPTURE_LIST: _list_captures,
        Capability.CAPTURE_SEARCH: _search_captures,
        Capability.REVIEW_LIST: _list_review_cases,
        Capability.REVIEW_DECIDE: _decide_review_case,
    }
)


def _named(capability: str) -> Capability:
    """The capability this request names, or a refusal.

    An unknown name is `invalid_request` and not `unsupported`: `unsupported`
    says this build does not serve a capability that exists, and a name that is
    not one of the fifteen names nothing.
    """
    try:
        return Capability(capability)
    except ValueError:
        pass
    raise InvalidRequestError()


def _metadata(capability: Capability, arguments: Mapping[str, Any]) -> RequestMetadata:
    """The common envelope, built by the contract model that owns its rules.

    The capability comes from the transport's own routing rather than from the
    document, so the two cannot disagree. A document that names it anyway is
    refused — `RequestMetadata` would receive the argument twice — rather than
    accepted with one of the two winning silently.
    """
    fields = {name: value for name, value in arguments.items() if name != PAYLOAD_KEY}
    try:
        return RequestMetadata(capability=capability, **fields)
    except (TypeError, ValueError):
        # `ValidationError` is a `ValueError`. Caught together because the two
        # say the same thing here: the envelope the caller sent is not one.
        pass
    # Raised outside the handler, as everywhere else in this repository: the
    # original renders the rejected input, and leaving the handler first is what
    # actually clears `__context__`.
    raise InvalidRequestError()


def _command(capability: Capability, payload: Mapping[str, Any]) -> Command:
    """The command for `capability`, built from the caller's payload.

    A `TypeError` is the constructor saying the payload named a field the
    command does not have, or omitted one it requires, or was not an object at
    all. All three are `invalid_request`, and none of them may escape as a crash.
    """
    build = _BUILDERS[capability]
    try:
        return build(payload)
    except TypeError:
        pass
    raise InvalidRequestError()


def normalize(capability: str, arguments: Mapping[str, Any]) -> tuple[RequestMetadata, Command]:
    """Build the request pair `ApplicationService.invoke` takes, or refuse.

    `capability` is the name the transport routed on — an HTTP path segment, an
    MCP tool name. `arguments` is the document beside it: the common metadata
    fields, and the capability's own fields under `payload`.

    Raises `InvalidRequestError` and nothing else. Every other outcome is the
    application's to decide, including whether the request is allowed.
    """
    named = _named(capability)
    payload = arguments.get(PAYLOAD_KEY, {})
    if not isinstance(payload, Mapping):
        raise InvalidRequestError()
    return _metadata(named, arguments), _command(named, payload)
