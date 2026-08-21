"""Stdlib HTTPS helper for RouteLLM. POST is single-attempt. No application types."""

from __future__ import annotations

import json
import ssl
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Never
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, OpenerDirector, Request, build_opener

CHAT_COMPLETIONS_PATH = "/v1/chat/completions"
MODELS_PATH = "/v1/models"
CONNECT_TIMEOUT_S = 10.0
READ_TIMEOUT_S = 120.0
OVERALL_TIMEOUT_S = 130.0
TIMEOUT_CLAMP = (1.0, 180.0)
PROBE_RETRY_MAX_ADDITIONAL = 2
PROBE_RETRY_BACKOFF_S = (0.5, 1.5)
IMAGE_POST_RETRY_MAX = 0
_MAXIMUM_RESPONSE_BYTES = 2_000_000


class RouteLLMTransportError(ValueError):
    """A RouteLLM HTTP call failed closed. Message contains no secrets or bodies."""

    def __init__(
        self,
        message: str,
        *,
        http_status: int | None = None,
        error_class: str,
        disclosed: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.http_status = http_status
        self.error_class = error_class
        self.disclosed = disclosed


class RouteLLMPostResponseError(RouteLLMTransportError):
    """The POST returned HTTP evidence; later local parse/envelope failed."""

    def __init__(self, message: str, *, http_status: int, error_class: str) -> None:
        super().__init__(
            message,
            http_status=http_status,
            error_class=error_class,
            disclosed=True,
        )


class _RefuseRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: object,
        fp: object,
        code: object,
        msg: object,
        headers: object,
        newurl: object,
    ) -> Never:
        del req, fp, code, msg, headers, newurl
        raise RouteLLMTransportError(
            "redirect refused",
            error_class="REDIRECT",
            disclosed=True,
        )


@dataclass(frozen=True, slots=True)
class RouteLLMHttpResult:
    status: int
    payload: dict[str, object]


def parse_https_origin(origin: str) -> str:
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("RouteLLM origin must be an exact credential-free HTTPS origin")
    host = parsed.hostname.lower()
    if parsed.port:
        return f"https://{host}:{parsed.port}"
    return f"https://{host}"


def origins_equal(authorized: str, runtime: str) -> bool:
    return parse_https_origin(authorized) == parse_https_origin(runtime)


def _timeout(value: float) -> float:
    low, high = TIMEOUT_CLAMP
    if not low <= value <= high:
        raise ValueError("RouteLLM timeout is outside its bound")
    return value


def _opener(tls: ssl.SSLContext) -> OpenerDirector:
    return build_opener(_RefuseRedirect, HTTPSHandler(context=tls))


def _request(
    *,
    origin: str,
    path: str,
    method: str,
    api_key: str,
    body: bytes | None,
    timeout_s: float,
) -> RouteLLMHttpResult:
    if path not in {CHAT_COMPLETIONS_PATH, MODELS_PATH}:
        raise ValueError("RouteLLM path is not in the allowed family")
    if not api_key or api_key.strip() != api_key:
        raise ValueError("RouteLLM API key is missing")
    parsed_origin = parse_https_origin(origin)
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    data = body
    if body is not None:
        headers["Content-Length"] = str(len(body))
        headers["Content-Type"] = "application/json"
    request = Request(  # noqa: S310 - constructor receives a validated exact HTTPS origin
        parsed_origin + path,
        data=data,
        method=method,
        headers=headers,
    )
    tls = ssl.create_default_context()
    opener = _opener(tls)
    try:
        with opener.open(request, timeout=_timeout(timeout_s)) as response:
            status = int(getattr(response, "status", 200) or 200)
            received = response.read(_MAXIMUM_RESPONSE_BYTES + 1)
    except RouteLLMTransportError:
        raise
    except HTTPError as error:
        raise RouteLLMTransportError(
            f"routellm request failed: HTTP {error.code}",
            http_status=int(error.code),
            error_class=f"HTTP_{error.code}",
            disclosed=method == "POST",
        ) from error
    except TimeoutError as error:
        raise RouteLLMTransportError(
            "routellm request failed: timeout",
            error_class="TIMEOUT",
            disclosed=None if method == "POST" else False,
        ) from error
    except URLError as error:
        raise RouteLLMTransportError(
            "routellm request failed: transport error",
            error_class="URL_ERROR",
            disclosed=None if method == "POST" else False,
        ) from error
    if len(received) > _MAXIMUM_RESPONSE_BYTES:
        raise RouteLLMTransportError(
            "routellm response exceeded its bound",
            http_status=status,
            error_class="RESPONSE_TOO_LARGE",
            disclosed=True,
        )
    try:
        value = json.loads(received)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RouteLLMTransportError(
            "routellm request failed: malformed JSON",
            http_status=status,
            error_class="MALFORMED_JSON",
            disclosed=True,
        ) from error
    if not isinstance(value, dict):
        raise RouteLLMTransportError(
            "routellm request failed: malformed JSON",
            http_status=status,
            error_class="MALFORMED_JSON",
            disclosed=True,
        )
    return RouteLLMHttpResult(status=status, payload=value)


def post_chat_completion(
    *,
    origin: str,
    api_key: str,
    body: Mapping[str, Any],
    timeout_s: float = OVERALL_TIMEOUT_S,
) -> RouteLLMHttpResult:
    if IMAGE_POST_RETRY_MAX != 0:
        raise RouteLLMTransportError(
            "image POST retry is forbidden",
            error_class="RETRY_FORBIDDEN",
            disclosed=False,
        )
    encoded = json.dumps(dict(body), separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return _request(
        origin=origin,
        path=CHAT_COMPLETIONS_PATH,
        method="POST",
        api_key=api_key,
        body=encoded,
        timeout_s=timeout_s,
    )


def get_models(
    *,
    origin: str,
    api_key: str,
    timeout_s: float = CONNECT_TIMEOUT_S,
) -> RouteLLMHttpResult:
    return _request(
        origin=origin,
        path=MODELS_PATH,
        method="GET",
        api_key=api_key,
        body=None,
        timeout_s=timeout_s,
    )


def get_models_with_retry(
    *,
    origin: str,
    api_key: str,
    sleep: Callable[[float], None] = time.sleep,
) -> RouteLLMHttpResult:
    attempts = 1 + PROBE_RETRY_MAX_ADDITIONAL
    for index in range(attempts):
        try:
            return get_models(origin=origin, api_key=api_key)
        except RouteLLMTransportError as error:
            retryable = error.error_class in {"TIMEOUT", "URL_ERROR"} and error.http_status is None
            if not retryable or index >= attempts - 1:
                raise
            sleep(PROBE_RETRY_BACKOFF_S[index])
    raise RouteLLMTransportError(
        "routellm request failed: transport error",
        error_class="URL_ERROR",
        disclosed=False,
    )


def validate_route_llm_models_probe(result: RouteLLMHttpResult) -> None:
    if not isinstance(result.payload.get("data"), list):
        raise ValueError("RouteLLM models probe returned malformed payload")
