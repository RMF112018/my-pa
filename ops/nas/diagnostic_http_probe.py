#!/usr/bin/env python3
"""Bounded, credential-safe proof of the browser/BFF and machine-route split."""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_BODY = 1024 * 1024
SESSION_TOKEN = re.compile(r"[A-Za-z0-9._~-]{16,4096}\Z")
DNS_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z")


class _Response(Protocol):
    status: int
    headers: Any

    def read(self, amount: int = -1) -> bytes: ...

    def close(self) -> None: ...


class _RefuseRedirects(HTTPRedirectHandler):
    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:  # noqa: ANN401
        return None


_NO_REDIRECT_OPENER = build_opener(_RefuseRedirects())


def _open_no_redirect(request: Request, *, timeout: int) -> _Response:
    return cast(_Response, _NO_REDIRECT_OPENER.open(request, timeout=timeout))


def _tailnet_origin(value: str) -> tuple[str, str] | None:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    hostname = parsed.hostname or ""
    labels = hostname.split(".")
    if not (
        parsed.scheme == "https"
        and len(hostname) <= 253
        and len(labels) >= 3
        and labels[-2:] == ["ts", "net"]
        and all(DNS_LABEL.fullmatch(label) for label in labels)
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and parsed.path in ("", "/")
        and not parsed.query
        and not parsed.fragment
    ):
        return None
    return value.rstrip("/"), hostname


def _trusted_credential(path: Path, owner_uid: int) -> str | None:
    try:
        metadata = path.lstat()
        if not (
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_uid == owner_uid
            and stat.S_IMODE(metadata.st_mode) == 0o400
            and metadata.st_nlink == 1
            and path.resolve(strict=True) == path
        ):
            return None
        token = path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError):
        return None
    return token if SESSION_TOKEN.fullmatch(token) else None


def _request(request: Request, opener: Callable[..., _Response]) -> tuple[int, Any, bytes] | None:
    response: _Response | None = None
    try:
        response = opener(request, timeout=10)
        body = response.read(MAX_BODY + 1)
        return response.status, response.headers, body
    except HTTPError as error:
        body = error.read(MAX_BODY + 1)
        result = error.code, error.headers, body
        error.close()
        return result
    except (OSError, URLError):
        return None
    finally:
        if response is not None:
            response.close()


def verify(
    endpoint: str,
    credential_path: Path,
    tailnet_host: str,
    verified_origin: str,
    *,
    owner_uid: int | None = None,
    opener: Callable[..., _Response] = _open_no_redirect,
) -> list[str]:
    errors: list[str] = []
    owner_uid = os.geteuid() if owner_uid is None else owner_uid
    trusted_origin = _tailnet_origin(verified_origin)
    if trusted_origin is None or tailnet_host != trusted_origin[1]:
        return ["diagnostic_origin_binding"]
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        return ["diagnostic_endpoint"]
    if not (
        parsed.scheme == "https"
        and parsed.hostname == tailnet_host
        and urlunsplit((parsed.scheme, parsed.netloc, "", "", "")) == trusted_origin[0]
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and parsed.path == "/api/system"
        and not parsed.query
        and not parsed.fragment
    ):
        return ["diagnostic_endpoint"]
    token = _trusted_credential(credential_path, owner_uid)
    if token is None:
        return ["diagnostic_credential"]
    browser = _request(
        Request(  # noqa: S310 - endpoint is constrained to exact private HTTPS origin above
            endpoint, headers={"Cookie": f"mypa_session={token}"}
        ),
        opener,
    )
    if browser is None or len(browser[2]) > MAX_BODY:
        errors.append("browser_bff_probe")
    else:
        try:
            document = json.loads(browser[2])
        except (UnicodeDecodeError, json.JSONDecodeError):
            document = None
        backend = document.get("backend") if isinstance(document, dict) else None
        if (
            browser[0] != 200
            or not isinstance(document, dict)
            or document.get("dataProvider") != "backend"
            or not isinstance(backend, dict)
            or not {"manifest", "readiness", "workerPlanes"} <= set(backend)
        ):
            errors.append("browser_bff_gateway_probe")
    remote_url = urlunsplit((parsed.scheme, parsed.netloc, "/remote/v1/capture.create", "", ""))
    remote = _request(
        Request(remote_url, method="GET"),  # noqa: S310 - same validated HTTPS origin
        opener,
    )
    if (
        remote is None
        or len(remote[2]) > MAX_BODY
        or remote[0] != 405
        or remote[1].get("X-My-PA-Route") != "gateway-only"
    ):
        errors.append("remote_capture_route_probe")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("endpoint")
    parser.add_argument("credential", type=Path)
    parser.add_argument("tailnet_host")
    parser.add_argument("verified_origin")
    args = parser.parse_args()
    errors = verify(args.endpoint, args.credential, args.tailnet_host, args.verified_origin)
    if errors:
        print("NAS HTTP diagnostics refused: " + ", ".join(errors))
        return 1
    print("Authenticated browser/BFF-to-gateway and gateway-only route probes passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
