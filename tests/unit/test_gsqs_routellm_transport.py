"""RouteLLM stdlib HTTPS: origin lock, no POST retry, no redirects."""

from __future__ import annotations

from urllib.error import URLError

import pytest

from my_pa.infrastructure import gsqs_routellm_transport as transport


class _FakeResponse:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.status = status
        self._body = body

    def read(self, _n: int) -> bytes:
        return self._body

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


class _CountingOpener:
    def __init__(self, handler: object) -> None:
        self.handler = handler
        self.calls = 0

    def open(self, request: object, timeout: float = 0) -> _FakeResponse:
        del request, timeout
        self.calls += 1
        return self.handler()  # type: ignore[no-untyped-call,operator]


def test_post_is_single_attempt(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    def handler() -> _FakeResponse:
        calls["n"] += 1
        raise URLError("dns")

    opener = _CountingOpener(handler)

    def fake_opener(_tls: object) -> _CountingOpener:
        return opener

    monkeypatch.setattr(transport, "_opener", fake_opener)
    with pytest.raises(transport.RouteLLMTransportError, match="transport error"):
        transport.post_chat_completion(
            origin="https://route.example",
            api_key="k",
            body={"model": "route-llm"},
        )
    assert calls["n"] == 1
    assert opener.calls == 1
    assert transport.IMAGE_POST_RETRY_MAX == 0


def test_post_transport_error_is_indeterminate(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler() -> _FakeResponse:
        raise URLError("dns")

    monkeypatch.setattr(transport, "_opener", lambda _tls: _CountingOpener(handler))
    with pytest.raises(transport.RouteLLMTransportError) as raised:
        transport.post_chat_completion(
            origin="https://route.example",
            api_key="k",
            body={"model": "route-llm"},
        )
    assert raised.value.http_status is None
    assert raised.value.disclosed is None
    assert raised.value.error_class == "URL_ERROR"


def test_probe_retries_transport_errors_only(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    calls = {"n": 0}

    def handler() -> _FakeResponse:
        calls["n"] += 1
        if calls["n"] < 3:
            raise URLError("dns")
        return _FakeResponse(b'{"data":[]}')

    monkeypatch.setattr(transport, "_opener", lambda _tls: _CountingOpener(handler))
    result = transport.get_models_with_retry(
        origin="https://route.example",
        api_key="k",
        sleep=sleeps.append,
    )
    assert result.status == 200
    assert calls["n"] == 3
    assert sleeps == [0.5, 1.5]


def test_probe_http_error_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    from email.message import Message
    from io import BytesIO
    from urllib.error import HTTPError

    calls = {"n": 0}

    def handler() -> _FakeResponse:
        calls["n"] += 1
        raise HTTPError("https://route.example/v1/models", 401, "no", Message(), BytesIO())

    monkeypatch.setattr(transport, "_opener", lambda _tls: _CountingOpener(handler))
    with pytest.raises(transport.RouteLLMTransportError) as raised:
        transport.get_models_with_retry(
            origin="https://route.example",
            api_key="k",
            sleep=lambda _delay: None,
        )
    assert calls["n"] == 1
    assert raised.value.http_status == 401
    assert raised.value.error_class == "HTTP_401"


def test_post_timeout_is_indeterminate(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler() -> _FakeResponse:
        raise TimeoutError("read")

    monkeypatch.setattr(transport, "_opener", lambda _tls: _CountingOpener(handler))
    with pytest.raises(transport.RouteLLMTransportError) as raised:
        transport.post_chat_completion(
            origin="https://route.example",
            api_key="k",
            body={"model": "route-llm"},
        )
    assert raised.value.http_status is None
    assert raised.value.disclosed is None
    assert raised.value.error_class == "TIMEOUT"


def test_models_probe_requires_data_list() -> None:
    transport.validate_route_llm_models_probe(
        transport.RouteLLMHttpResult(status=200, payload={"data": []})
    )
    with pytest.raises(ValueError, match="malformed payload"):
        transport.validate_route_llm_models_probe(
            transport.RouteLLMHttpResult(status=200, payload={})
        )
    with pytest.raises(ValueError, match="malformed payload"):
        transport.validate_route_llm_models_probe(
            transport.RouteLLMHttpResult(status=200, payload={"data": "not-a-list"})
        )


def test_origin_mismatch_and_redirect(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(ValueError, match="exact credential-free HTTPS origin"):
        transport.parse_https_origin("http://route.example")
    with pytest.raises(ValueError, match="exact credential-free HTTPS origin"):
        transport.parse_https_origin("https://user:pass@route.example")
    with pytest.raises(ValueError, match="exact credential-free HTTPS origin"):
        transport.parse_https_origin("https://route.example/v1")
    assert transport.origins_equal("https://Route.Example", "https://route.example/")
    assert not transport.origins_equal("https://a.example", "https://b.example")

    def handler() -> _FakeResponse:
        raise transport.RouteLLMTransportError(
            "redirect refused", error_class="REDIRECT", disclosed=True
        )

    monkeypatch.setattr(transport, "_opener", lambda _tls: _CountingOpener(handler))
    with pytest.raises(transport.RouteLLMTransportError, match="redirect refused"):
        transport.post_chat_completion(
            origin="https://route.example",
            api_key="k",
            body={"model": "route-llm"},
        )
