import httpx
import pytest

from app.llm.base import LLMError
from app.llm.openai_compat import OpenAICompatLLM


def _make_llm(transport: httpx.MockTransport, sleep_calls: list | None = None) -> OpenAICompatLLM:
    calls = sleep_calls if sleep_calls is not None else []
    return OpenAICompatLLM(
        base_url="http://gw.local/v1",
        api_key="secret-key",
        model="test-model",
        transport=transport,
        sleep_fn=lambda seconds: calls.append(seconds),
    )


def test_complete_returns_text():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        assert request.headers["authorization"] == "Bearer secret-key"
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hello world"}}]},
        )

    transport = httpx.MockTransport(handler)
    llm = _make_llm(transport)

    result = llm.complete([{"role": "user", "content": "hi"}], system="be nice")

    assert result == "hello world"


def test_complete_sends_expected_payload():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    transport = httpx.MockTransport(handler)
    llm = _make_llm(transport)

    llm.complete([{"role": "user", "content": "hi"}], system="sys prompt", max_tokens=123)

    body = captured["body"]
    assert body["model"] == "test-model"
    assert body["max_tokens"] == 123
    assert body["messages"] == [
        {"role": "system", "content": "sys prompt"},
        {"role": "user", "content": "hi"},
    ]


def test_complete_no_system_message_when_empty():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "ok"}}]}
        )

    transport = httpx.MockTransport(handler)
    llm = _make_llm(transport)

    llm.complete([{"role": "user", "content": "hi"}])

    assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]


def test_retry_on_5xx_then_success():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        if call_count["n"] < 3:
            return httpx.Response(500, text="server error")
        return httpx.Response(
            200, json={"choices": [{"message": {"content": "recovered"}}]}
        )

    transport = httpx.MockTransport(handler)
    sleeps: list = []
    llm = _make_llm(transport, sleeps)

    result = llm.complete([{"role": "user", "content": "hi"}])

    assert result == "recovered"
    assert call_count["n"] == 3
    assert len(sleeps) == 2


def test_auth_error_no_retry():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(401, json={"error": "invalid api key"})

    transport = httpx.MockTransport(handler)
    llm = _make_llm(transport)

    with pytest.raises(LLMError) as exc_info:
        llm.complete([{"role": "user", "content": "hi"}])

    assert exc_info.value.kind == "auth"
    assert call_count["n"] == 1


def test_forbidden_error_no_retry():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"error": "forbidden"})

    transport = httpx.MockTransport(handler)
    llm = _make_llm(transport)

    with pytest.raises(LLMError) as exc_info:
        llm.complete([{"role": "user", "content": "hi"}])

    assert exc_info.value.kind == "auth"


def test_gives_up_after_3_retries():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(500, text="server error")

    transport = httpx.MockTransport(handler)
    sleeps: list = []
    llm = _make_llm(transport, sleeps)

    with pytest.raises(LLMError) as exc_info:
        llm.complete([{"role": "user", "content": "hi"}])

    assert exc_info.value.kind == "network"
    assert call_count["n"] == 3
    assert sleeps == [1, 2]


def test_rate_limit_retries_then_gives_up():
    call_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        call_count["n"] += 1
        return httpx.Response(429, json={"error": "rate limited"})

    transport = httpx.MockTransport(handler)
    sleeps: list = []
    llm = _make_llm(transport, sleeps)

    with pytest.raises(LLMError) as exc_info:
        llm.complete([{"role": "user", "content": "hi"}])

    assert exc_info.value.kind == "rate_limit"
    assert call_count["n"] == 3


def test_bad_response_missing_choices():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    transport = httpx.MockTransport(handler)
    llm = _make_llm(transport)

    with pytest.raises(LLMError) as exc_info:
        llm.complete([{"role": "user", "content": "hi"}])

    assert exc_info.value.kind == "bad_response"


def test_bad_response_invalid_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json")

    transport = httpx.MockTransport(handler)
    llm = _make_llm(transport)

    with pytest.raises(LLMError) as exc_info:
        llm.complete([{"role": "user", "content": "hi"}])

    assert exc_info.value.kind == "bad_response"


def test_connection_error_retries_then_network_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    transport = httpx.MockTransport(handler)
    sleeps: list = []
    llm = _make_llm(transport, sleeps)

    with pytest.raises(LLMError) as exc_info:
        llm.complete([{"role": "user", "content": "hi"}])

    assert exc_info.value.kind == "network"
    assert sleeps == [1, 2]


def test_error_message_does_not_leak_url():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "invalid api key"})

    transport = httpx.MockTransport(handler)
    llm = _make_llm(transport)

    with pytest.raises(LLMError) as exc_info:
        llm.complete([{"role": "user", "content": "hi"}])

    assert "gw.local" not in str(exc_info.value)
    assert "secret-key" not in str(exc_info.value)
