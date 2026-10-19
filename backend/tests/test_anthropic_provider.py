"""The Anthropic provider, exercised through the real SDK with a mock HTTP transport.

No network calls are made: requests are captured and answered by a local handler.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import anthropic
import httpx2
import pytest
from pydantic import BaseModel

from app.agent.llm.anthropic_provider import FALLBACK_BETA, AnthropicProvider
from app.agent.llm.base import (
    LLMConfigurationError,
    LLMRateLimitError,
    LLMRefusalError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
    ToolOutcome,
    ToolResults,
    ToolSpec,
    UserText,
)
from app.config import Settings

API_KEY = "sk-ant-test-not-a-real-key"
TOOL = ToolSpec(
    name="execute_sql",
    description="Run SQL",
    input_schema={"type": "object", "properties": {"sql": {"type": "string"}}},
)


def message(content: list[dict[str, Any]], stop_reason: str = "end_turn") -> dict[str, Any]:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-5-5",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 12, "output_tokens": 7},
    }


def provider(
    handler: Callable[[httpx2.Request], httpx2.Response], *, fallback: bool = True
) -> AnthropicProvider:
    client = anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    return AnthropicProvider(
        api_key=API_KEY,
        model="claude-opus-5-5",
        effort="medium",
        timeout_seconds=5,
        max_retries=0,
        refusal_fallback=fallback,
        http_client=client,
    )


class Captured:
    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self.responses = responses
        self.requests: list[httpx2.Request] = []

    def __call__(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return httpx2.Response(200, json=self.responses[len(self.requests) - 1])

    def body(self, index: int = 0) -> dict[str, Any]:
        return json.loads(self.requests[index].content)


def test_tool_step_request_shape_and_parsing() -> None:
    captured = Captured(
        [
            message(
                [
                    {"type": "text", "text": "Checking."},
                    {
                        "type": "tool_use",
                        "id": "toolu_1",
                        "name": "execute_sql",
                        "input": {"sql": "SELECT 1"},
                    },
                ],
                stop_reason="tool_use",
            )
        ]
    )
    step = provider(captured).tool_step(
        system="You are an analyst.", messages=[UserText("Hi")], tools=[TOOL]
    )
    assert step.turn.text == "Checking."
    assert [(c.id, c.name, c.input) for c in step.turn.tool_calls] == [
        ("toolu_1", "execute_sql", {"sql": "SELECT 1"})
    ]
    assert (step.usage.input_tokens, step.usage.output_tokens) == (12, 7)

    request = captured.requests[0]
    assert request.headers["x-api-key"] == API_KEY
    assert FALLBACK_BETA in request.headers["anthropic-beta"]
    body = captured.body()
    assert body["model"] == "claude-opus-5-5"
    assert body["tool_choice"] == {"type": "auto"}
    assert body["tools"][0]["name"] == "execute_sql"
    assert body["output_config"] == {"effort": "medium"}
    assert body["fallbacks"] == "default"
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert "thinking" not in body  # adaptive by default, never displayed


def test_assistant_content_is_replayed_with_tool_results() -> None:
    first = message(
        [{"type": "tool_use", "id": "toolu_1", "name": "execute_sql", "input": {"sql": "x"}}],
        stop_reason="tool_use",
    )
    captured = Captured([first, message([{"type": "text", "text": "Done"}])])
    llm = provider(captured)
    step = llm.tool_step(system="s", messages=[UserText("q")], tools=[TOOL])
    llm.tool_step(
        system="s",
        messages=[
            UserText("q"),
            step.turn,
            ToolResults([ToolOutcome("toolu_1", '{"rows": []}', is_error=False)]),
        ],
        tools=[TOOL],
    )
    replay = captured.body(1)["messages"]
    assert replay[1]["role"] == "assistant"
    assert replay[1]["content"][0]["type"] == "tool_use"
    assert replay[2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "toolu_1",
        "content": '{"rows": []}',
        "is_error": False,
    }


class Verdict(BaseModel):
    answer: str
    confidence: float


def test_structured_output_is_parsed_and_validated() -> None:
    captured = Captured(
        [message([{"type": "text", "text": '{"answer": "yes", "confidence": 0.9}'}])]
    )
    reply = provider(captured).structured(system="s", messages=[UserText("q")], schema=Verdict)
    assert reply.value == Verdict(answer="yes", confidence=0.9)
    assert captured.body()["output_config"]["format"]["type"] == "json_schema"


def test_fallback_can_be_disabled() -> None:
    captured = Captured([message([{"type": "text", "text": "ok"}])])
    provider(captured, fallback=False).tool_step(system="s", messages=[UserText("q")], tools=[])
    assert (
        "anthropic-beta" not in captured.requests[0].headers
        or FALLBACK_BETA not in (captured.requests[0].headers["anthropic-beta"])
    )
    assert "fallbacks" not in captured.body()


@pytest.mark.parametrize(
    ("stop_reason", "error"),
    [("refusal", LLMRefusalError), ("max_tokens", LLMResponseError)],
)
def test_unusable_stop_reasons(stop_reason: str, error: type[Exception]) -> None:
    captured = Captured([message([{"type": "text", "text": "..."}], stop_reason=stop_reason)])
    with pytest.raises(error):
        provider(captured).tool_step(system="s", messages=[UserText("q")], tools=[])


def error_response(status: int, kind: str) -> Callable[[httpx2.Request], httpx2.Response]:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status, json={"type": "error", "error": {"type": kind, "message": "nope"}}
        )

    return handler


@pytest.mark.parametrize(
    ("handler", "error"),
    [
        (error_response(429, "rate_limit_error"), LLMRateLimitError),
        (error_response(500, "api_error"), LLMUnavailableError),
        (error_response(529, "overloaded_error"), LLMUnavailableError),
        (error_response(401, "authentication_error"), LLMConfigurationError),
        (error_response(400, "invalid_request_error"), LLMResponseError),
    ],
)
def test_http_errors_are_mapped(
    handler: Callable[[httpx2.Request], httpx2.Response], error: type[Exception]
) -> None:
    with pytest.raises(error) as excinfo:
        provider(handler).tool_step(system="s", messages=[UserText("q")], tools=[])
    assert API_KEY not in str(excinfo.value)


def test_timeouts_and_connection_failures() -> None:
    def timeout(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("timed out", request=request)

    def refused(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(LLMTimeoutError):
        provider(timeout).tool_step(system="s", messages=[UserText("q")], tools=[])
    with pytest.raises(LLMUnavailableError):
        provider(refused).tool_step(system="s", messages=[UserText("q")], tools=[])


def test_schema_mismatch_is_a_response_error() -> None:
    captured = Captured([message([{"type": "text", "text": '{"answer": "yes"}'}])])
    with pytest.raises(LLMResponseError):
        provider(captured).structured(system="s", messages=[UserText("q")], schema=Verdict)


def test_from_settings_requires_a_key() -> None:
    with pytest.raises(LLMConfigurationError):
        AnthropicProvider.from_settings(Settings(_env_file=None, anthropic_api_key=None))  # type: ignore[call-arg]
    with pytest.raises(LLMConfigurationError):
        AnthropicProvider.from_settings(Settings(_env_file=None, anthropic_api_key="  "))  # type: ignore[call-arg]
