"""The Gemini provider, exercised through the real google-genai SDK with a mock HTTP transport.

No network calls are made: requests are captured and answered by a local handler.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel

from app.agent.llm.base import (
    AssistantTurn,
    LLMConfigurationError,
    LLMRateLimitError,
    LLMRefusalError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
    ToolCall,
    ToolOutcome,
    ToolResults,
    ToolSpec,
    UserText,
)
from app.agent.llm.factory import provider_from_settings
from app.agent.llm.gemini_provider import LOCAL_ID_PREFIX, GeminiProvider
from app.config import Settings

API_KEY = "gemini-test-not-a-real-key"
MODEL = "gemini-test-model"
TOOL = ToolSpec(
    name="execute_sql",
    description="Run SQL",
    input_schema={"type": "object", "properties": {"sql": {"type": "string"}}},
)


def reply(parts: list[dict[str, Any]], finish_reason: str = "STOP") -> dict[str, Any]:
    return {
        "candidates": [
            {"content": {"role": "model", "parts": parts}, "finishReason": finish_reason}
        ],
        "usageMetadata": {
            "promptTokenCount": 12,
            "candidatesTokenCount": 7,
            "thoughtsTokenCount": 3,
        },
    }


def provider(handler: Callable[[httpx2.Request], httpx2.Response]) -> GeminiProvider:
    return GeminiProvider(
        api_key=API_KEY,
        model=MODEL,
        timeout_seconds=5,
        max_retries=0,
        http_client=httpx2.Client(transport=httpx2.MockTransport(handler)),
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
            reply(
                [
                    {"text": "Thinking about it.", "thought": True},
                    {"text": "Checking."},
                    {
                        "functionCall": {
                            "id": "call_1",
                            "name": "execute_sql",
                            "args": {"sql": "SELECT 1"},
                        },
                        "thoughtSignature": "c2lnbmF0dXJl",
                    },
                ]
            )
        ]
    )
    step = provider(captured).tool_step(
        system="You are an analyst.", messages=[UserText("How many rows?")], tools=[TOOL]
    )

    assert step.turn.text == "Checking."  # thoughts are never returned
    assert step.turn.tool_calls == [ToolCall("call_1", "execute_sql", {"sql": "SELECT 1"})]
    assert step.usage.input_tokens == 12
    assert step.usage.output_tokens == 10

    request = captured.requests[0]
    assert MODEL in request.url.path
    assert request.headers["x-goog-api-key"] == API_KEY
    body = captured.body()
    assert body["systemInstruction"]["parts"][0]["text"] == "You are an analyst."
    assert body["contents"] == [{"role": "user", "parts": [{"text": "How many rows?"}]}]
    declaration = body["tools"][0]["functionDeclarations"][0]
    assert declaration["name"] == "execute_sql"
    # The SDK serializes this field in snake_case; the API accepts both spellings.
    schema = declaration.get("parametersJsonSchema", declaration.get("parameters_json_schema"))
    assert schema == TOOL.input_schema
    assert body["toolConfig"]["functionCallingConfig"]["mode"] == "AUTO"


def test_model_content_is_replayed_with_tool_results() -> None:
    first = reply(
        [
            {
                "functionCall": {"id": "call_1", "name": "execute_sql", "args": {"sql": "x"}},
                "thoughtSignature": "c2lnbmF0dXJl",
            }
        ]
    )
    captured = Captured([first, reply([{"text": "Done."}])])
    llm = provider(captured)
    step = llm.tool_step(system="s", messages=[UserText("q")], tools=[TOOL])
    llm.tool_step(
        system="s",
        messages=[
            UserText("q"),
            step.turn,
            ToolResults([ToolOutcome("call_1", "bad column", is_error=True)]),
        ],
        tools=[TOOL],
    )

    contents = captured.body(1)["contents"]
    assert contents[1]["role"] == "model"
    # The thought signature must be sent back unchanged.
    assert contents[1]["parts"][0]["thoughtSignature"] == "c2lnbmF0dXJl"
    response = contents[2]["parts"][0]["functionResponse"]
    assert response == {"id": "call_1", "name": "execute_sql", "response": {"error": "bad column"}}


def test_calls_without_ids_get_local_ids_that_are_not_sent_back() -> None:
    captured = Captured(
        [
            reply([{"functionCall": {"name": "execute_sql", "args": {}}}]),
            reply([{"text": "ok"}]),
        ]
    )
    llm = provider(captured)
    step = llm.tool_step(system="s", messages=[UserText("q")], tools=[TOOL])
    call = step.turn.tool_calls[0]
    assert call.id.startswith(LOCAL_ID_PREFIX)
    llm.tool_step(
        system="s",
        messages=[UserText("q"), step.turn, ToolResults([ToolOutcome(call.id, "1 row")])],
        tools=[TOOL],
    )
    response = captured.body(1)["contents"][2]["parts"][0]["functionResponse"]
    assert "id" not in response
    assert response["response"] == {"output": "1 row"}


def test_turns_without_raw_content_are_rebuilt() -> None:
    captured = Captured([reply([{"text": "ok"}])])
    turn = AssistantTurn(text="", tool_calls=[ToolCall("c9", "execute_sql", {"sql": "y"})])
    provider(captured).tool_step(
        system="s",
        messages=[UserText("q"), turn, ToolResults([ToolOutcome("c9", "done")])],
        tools=[TOOL],
    )
    contents = captured.body()["contents"]
    assert contents[1]["parts"] == [
        {"functionCall": {"id": "c9", "name": "execute_sql", "args": {"sql": "y"}}}
    ]


class Verdict(BaseModel):
    answer: str
    confidence: float


def test_structured_output_is_requested_and_validated() -> None:
    captured = Captured([reply([{"text": '{"answer": "yes", "confidence": 0.9}'}])])
    result = provider(captured).structured(system="s", messages=[UserText("q")], schema=Verdict)
    assert result.value == Verdict(answer="yes", confidence=0.9)
    config = captured.body()["generationConfig"]
    assert config["responseMimeType"] == "application/json"
    assert config["responseJsonSchema"]["properties"]["answer"]["type"] == "string"


def test_schema_mismatch_is_a_response_error() -> None:
    captured = Captured([reply([{"text": '{"answer": "yes"}'}])])
    with pytest.raises(LLMResponseError):
        provider(captured).structured(system="s", messages=[UserText("q")], schema=Verdict)


@pytest.mark.parametrize(
    ("finish_reason", "error"),
    [
        ("SAFETY", LLMRefusalError),
        ("PROHIBITED_CONTENT", LLMRefusalError),
        ("MAX_TOKENS", LLMResponseError),
        ("MALFORMED_FUNCTION_CALL", LLMResponseError),
    ],
)
def test_unusable_finish_reasons(finish_reason: str, error: type[Exception]) -> None:
    captured = Captured([reply([{"text": "partial"}], finish_reason=finish_reason)])
    with pytest.raises(error):
        provider(captured).tool_step(system="s", messages=[UserText("q")], tools=[TOOL])


def test_blocked_prompt_is_a_refusal() -> None:
    captured = Captured([{"promptFeedback": {"blockReason": "SAFETY"}}])
    with pytest.raises(LLMRefusalError):
        provider(captured).tool_step(system="s", messages=[UserText("q")], tools=[TOOL])


def error_handler(
    status: int, message: str = "nope"
) -> Callable[[httpx2.Request], httpx2.Response]:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            status, json={"error": {"code": status, "message": message, "status": "X"}}
        )

    return handler


@pytest.mark.parametrize(
    ("status", "message", "error"),
    [
        (400, "Invalid argument", LLMResponseError),
        (400, "API key not valid. Please pass a valid API key.", LLMConfigurationError),
        (401, "nope", LLMConfigurationError),
        (403, "nope", LLMConfigurationError),
        (404, "model not found", LLMConfigurationError),
        (429, "quota", LLMRateLimitError),
        (500, "boom", LLMUnavailableError),
        (503, "overloaded", LLMUnavailableError),
    ],
)
def test_http_errors_are_mapped(status: int, message: str, error: type[Exception]) -> None:
    with pytest.raises(error) as info:
        provider(error_handler(status, message)).tool_step(
            system="s", messages=[UserText("q")], tools=[TOOL]
        )
    assert API_KEY not in str(info.value)


def test_timeouts_and_connection_failures() -> None:
    def timeout(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("slow", request=request)

    def unreachable(request: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("refused", request=request)

    with pytest.raises(LLMTimeoutError):
        provider(timeout).tool_step(system="s", messages=[UserText("q")], tools=[TOOL])
    with pytest.raises((LLMUnavailableError, LLMTimeoutError)):
        provider(unreachable).tool_step(system="s", messages=[UserText("q")], tools=[TOOL])


def test_from_settings_requires_a_key() -> None:
    with pytest.raises(LLMConfigurationError):
        GeminiProvider.from_settings(Settings(_env_file=None, gemini_api_key=None))  # type: ignore[call-arg]
    with pytest.raises(LLMConfigurationError):
        GeminiProvider.from_settings(Settings(_env_file=None, gemini_api_key="  "))  # type: ignore[call-arg]


def test_factory_selects_the_configured_provider() -> None:
    gemini = provider_from_settings(
        Settings(_env_file=None, llm_provider="gemini", gemini_api_key="k")  # type: ignore[call-arg]
    )
    assert isinstance(gemini, GeminiProvider)
    assert gemini.model_name == "gemini-flash-latest"

    from app.agent.llm.anthropic_provider import AnthropicProvider

    claude = provider_from_settings(
        Settings(  # type: ignore[call-arg]
            _env_file=None, llm_provider="anthropic", anthropic_api_key="k", llm_model="m"
        )
    )
    assert isinstance(claude, AnthropicProvider)
    assert claude.model_name == "m"


def test_analysis_is_enabled_only_by_the_selected_providers_key() -> None:
    assert not Settings(_env_file=None, anthropic_api_key="k").analysis_enabled  # type: ignore[call-arg]
    assert Settings(_env_file=None, gemini_api_key="k").analysis_enabled  # type: ignore[call-arg]
    assert Settings(  # type: ignore[call-arg]
        _env_file=None, llm_provider="anthropic", anthropic_api_key="k"
    ).analysis_enabled
    assert Settings(_env_file=None, llm_model="").resolved_llm_model == "gemini-flash-latest"  # type: ignore[call-arg]
