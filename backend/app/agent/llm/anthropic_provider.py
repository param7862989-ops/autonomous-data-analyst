"""Anthropic (Claude) implementation of the LLM provider interface.

* Tool turns use ``tool_choice=auto`` (forced tool use is rejected by current models); tool
  inputs are validated by the agent with Pydantic before anything runs.
* Structured outputs use ``messages.parse`` with a Pydantic model.
* Thinking is left adaptive and never displayed; assistant content (including thinking blocks)
  is replayed unchanged within a run, as the API requires.
* The server-side refusal fallback beta is enabled by default (``LLM_REFUSAL_FALLBACK``).
* The SDK retries connection errors, 429 and 5xx; failures are mapped to provider-neutral
  errors whose messages never include request content or credentials.
"""

from __future__ import annotations

import logging
from typing import Any, TypeVar

import anthropic
from pydantic import BaseModel, ValidationError

from app.agent.llm.base import (
    AssistantTurn,
    LLMConfigurationError,
    LLMError,
    LLMRateLimitError,
    LLMRefusalError,
    LLMResponseError,
    LLMTimeoutError,
    LLMUnavailableError,
    Message,
    StructuredReply,
    ToolCall,
    ToolResults,
    ToolSpec,
    ToolStep,
    Usage,
    UserText,
)
from app.config import Settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AnthropicProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        effort: str,
        timeout_seconds: float,
        max_retries: int,
        refusal_fallback: bool,
        http_client: Any = None,
    ) -> None:
        # http_client is only injected by tests (a mock transport); production uses the default.
        options: dict[str, Any] = {"http_client": http_client} if http_client is not None else {}
        self._client = anthropic.Anthropic(
            api_key=api_key, timeout=timeout_seconds, max_retries=max_retries, **options
        )
        self._model = model
        self._effort = effort
        self._refusal_fallback = refusal_fallback

    @classmethod
    def from_settings(cls, settings: Settings) -> AnthropicProvider:
        if not settings.analysis_enabled or settings.anthropic_api_key is None:
            raise LLMConfigurationError("No LLM API key is configured on this server.")
        return cls(
            api_key=settings.anthropic_api_key.get_secret_value(),
            model=settings.llm_model,
            effort=settings.llm_effort,
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            refusal_fallback=settings.llm_refusal_fallback,
        )

    @property
    def model_name(self) -> str:
        return self._model

    # --- Requests ----------------------------------------------------------------------------

    def _common(self, system: str, messages: list[Message], max_tokens: int) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self._model,
            "max_tokens": max_tokens,
            # The system prompt (instructions + dataset context) is identical across the calls
            # of a run, so it is cached.
            "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            "messages": _to_anthropic(messages),
            "output_config": {"effort": self._effort},
        }
        if self._refusal_fallback:
            params["betas"] = [FALLBACK_BETA]
            params["fallbacks"] = "default"
        return params

    def tool_step(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        max_tokens: int = 16_000,
    ) -> ToolStep:
        params = self._common(system, messages, max_tokens)
        params["tools"] = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in tools
        ]
        params["tool_choice"] = {"type": "auto"}
        response = self._call(self._client.beta.messages.create, params)
        _check_stop_reason(response)
        text = "".join(block.text for block in response.content if block.type == "text")
        calls = [
            ToolCall(id=block.id, name=block.name, input=dict(block.input))
            for block in response.content
            if block.type == "tool_use"
        ]
        return ToolStep(
            turn=AssistantTurn(text=text, tool_calls=calls, raw=response.content),
            usage=_usage(response),
        )

    def structured(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: type[T],
        max_tokens: int = 16_000,
    ) -> StructuredReply[T]:
        params = self._common(system, messages, max_tokens)
        params["output_format"] = schema
        response = self._call(self._client.beta.messages.parse, params)
        _check_stop_reason(response)
        parsed = response.parsed_output
        if not isinstance(parsed, schema):
            raise LLMResponseError("The model did not return the expected structure.")
        return StructuredReply(value=parsed, usage=_usage(response))

    def _call(self, method: Any, params: dict[str, Any]) -> Any:
        try:
            return method(**params)
        except anthropic.APITimeoutError as exc:
            raise LLMTimeoutError("The language model took too long to respond.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMRateLimitError(
                "The language model is rate limited. Try again shortly."
            ) from exc
        except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as exc:
            logger.error("LLM authentication failed (status %s)", exc.status_code)
            raise LLMConfigurationError(
                "The server's language model credentials were rejected."
            ) from exc
        except anthropic.BadRequestError as exc:
            # A 400 means this request is malformed or too large; retrying will not help.
            logger.error("LLM request rejected (request id %s)", exc.request_id)
            raise LLMResponseError("The language model rejected the request.") from exc
        except anthropic.APIStatusError as exc:
            logger.warning("LLM API error status=%s", exc.status_code)
            raise LLMUnavailableError("The language model service is unavailable.") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailableError("Could not reach the language model service.") from exc
        except ValidationError as exc:
            raise LLMResponseError("The model's output did not match the expected schema.") from exc


def _check_stop_reason(response: Any) -> None:
    if response.stop_reason == "refusal":
        raise LLMRefusalError("The language model declined to answer this request.")
    if response.stop_reason == "max_tokens":
        raise LLMResponseError("The model's response was cut off before it finished.")


def _usage(response: Any) -> Usage:
    usage = getattr(response, "usage", None)
    if usage is None:
        return Usage()
    return Usage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
    )


def _to_anthropic(messages: list[Message]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for message in messages:
        if isinstance(message, UserText):
            converted.append({"role": "user", "content": message.text})
        elif isinstance(message, AssistantTurn):
            if message.raw is not None:
                content: Any = message.raw
            else:
                content = [{"type": "text", "text": message.text or "(no text)"}] + [
                    {"type": "tool_use", "id": c.id, "name": c.name, "input": c.input}
                    for c in message.tool_calls
                ]
            converted.append({"role": "assistant", "content": content})
        elif isinstance(message, ToolResults):
            converted.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": result.tool_call_id,
                            "content": result.content,
                            "is_error": result.is_error,
                        }
                        for result in message.results
                    ],
                }
            )
    return converted


__all__ = ["AnthropicProvider", "LLMError"]
