"""Google Gemini implementation of the LLM provider interface (``google-genai`` SDK).

* Tool turns declare functions with their JSON Schemas and ``mode=AUTO``; automatic function
  calling in the SDK is disabled, because the agent validates and runs every tool itself.
* Structured outputs request JSON constrained by the Pydantic model's JSON Schema; the reply is
  validated with Pydantic again before it is trusted.
* The model's own content (including thought signatures, which Gemini requires back on the
  next turn of a function-calling exchange) is replayed unchanged within a run.
* Thinking text is never returned to the agent or shown to users.
* The SDK retries 408/429/5xx. If the model is still overloaded or out of quota (429/503/504)
  and a fallback model is configured, the provider switches to it for the rest of the run
  (checked live: a model accepts another Gemini model's signed turns).
* Failures are mapped to provider-neutral errors whose messages never include request content
  or credentials.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, TypeVar

from google import genai
from google.genai import errors as genai_errors
from google.genai import types
from pydantic import BaseModel, ValidationError

from app.agent.llm.base import (
    AssistantTurn,
    LLMConfigurationError,
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
from app.config import DEFAULT_MODELS, Settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Ids invented for function calls the model sent without one. They are never sent back to the
# API (Gemini then pairs responses with calls by order and name).
LOCAL_ID_PREFIX = "gemini-local-"

# Gemini 3 rejects a function call without a thought signature (400). Turns rebuilt from text
# and tool calls (not replayed from the model) carry this placeholder, which Google documents
# for function calls the model did not produce (checked live).
PLACEHOLDER_SIGNATURE = b"skip_thought_signature_validator"

# Overloaded (503), timed out at Google (504) or out of quota for this model (429).
_FALLBACK_STATUSES = {429, 503, 504}
_RETRY_STATUSES = [408, 429, 500, 502, 503, 504]
_RETRY_STATUSES_WITH_FALLBACK = sorted(set(_RETRY_STATUSES) - _FALLBACK_STATUSES)

_REFUSAL_REASONS = {
    "SAFETY",
    "PROHIBITED_CONTENT",
    "BLOCKLIST",
    "SPII",
    "RECITATION",
    "MODEL_ARMOR",
}


def _http_errors() -> tuple[tuple[type[Exception], ...], tuple[type[Exception], ...]]:
    """Timeout and connection error classes of whichever HTTP library the SDK uses."""
    timeouts: list[type[Exception]] = []
    connections: list[type[Exception]] = []
    for name in ("httpx", "httpx2"):
        try:
            module = __import__(name)
        except ImportError:
            continue
        timeouts.append(module.TimeoutException)
        connections.append(module.TransportError)
    return tuple(timeouts), tuple(connections)


_TIMEOUT_ERRORS, _CONNECTION_ERRORS = _http_errors()


class GeminiProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        timeout_seconds: float,
        max_retries: int,
        fallback_model: str | None = None,
        http_client: Any = None,
    ) -> None:
        self._fallback = fallback_model if fallback_model and fallback_model != model else None

        # http_client is only injected by tests (a mock transport); production uses the default.
        def client(retry_statuses: list[int]) -> genai.Client:
            options = types.HttpOptions(
                timeout=int(timeout_seconds * 1000),
                retry_options=types.HttpRetryOptions(
                    attempts=max_retries + 1, http_status_codes=retry_statuses
                ),
                httpx_client=http_client,
            )
            return genai.Client(api_key=api_key, http_options=options)

        # With a fallback, overload errors are not retried on the main model: each 504 can take
        # the whole request timeout, and retrying it used up the run's deadline (seen live).
        self._client = client(_RETRY_STATUSES_WITH_FALLBACK if self._fallback else _RETRY_STATUSES)
        self._fallback_client = client(_RETRY_STATUSES) if self._fallback else None
        self._model = model

    @classmethod
    def from_settings(cls, settings: Settings) -> GeminiProvider:
        key = settings.gemini_api_key
        if key is None or not key.get_secret_value().strip():
            raise LLMConfigurationError("No LLM API key is configured on this server.")
        return cls(
            api_key=key.get_secret_value(),
            model=settings.llm_model or DEFAULT_MODELS["gemini"],
            timeout_seconds=settings.llm_timeout_seconds,
            max_retries=settings.llm_max_retries,
            fallback_model=settings.gemini_fallback_model,
        )

    @property
    def model_name(self) -> str:
        """The model in use; after a fallback, the fallback model."""
        return self._model

    # --- Requests ----------------------------------------------------------------------------

    def tool_step(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        max_tokens: int = 16_000,
    ) -> ToolStep:
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t.name,
                            description=t.description,
                            parameters_json_schema=t.input_schema,
                        )
                        for t in tools
                    ]
                )
            ],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="AUTO")
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = self._call(messages, config)
        content = _checked_content(response)
        parts = content.parts or []
        calls = [
            ToolCall(
                id=part.function_call.id or f"{LOCAL_ID_PREFIX}{uuid.uuid4().hex}",
                name=part.function_call.name or "",
                input=dict(part.function_call.args or {}),
            )
            for part in parts
            if part.function_call is not None
        ]
        return ToolStep(
            turn=AssistantTurn(text=_text(parts), tool_calls=calls, raw=content),
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
        config = types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            response_mime_type="application/json",
            response_json_schema=schema.model_json_schema(),
        )
        response = self._call(messages, config)
        content = _checked_content(response)
        text = _text(content.parts or [])
        try:
            value = schema.model_validate_json(text)
        except ValidationError as exc:
            raise LLMResponseError("The model's output did not match the expected schema.") from exc
        return StructuredReply(value=value, usage=_usage(response))

    def _call(
        self, messages: list[Message], config: types.GenerateContentConfig
    ) -> types.GenerateContentResponse:
        contents = _to_gemini(messages)
        try:
            try:
                return self._client.models.generate_content(
                    model=self._model, contents=contents, config=config
                )
            except genai_errors.APIError as exc:
                if (
                    self._fallback is None
                    or self._fallback_client is None
                    or exc.code not in _FALLBACK_STATUSES
                ):
                    raise
                logger.warning(
                    "LLM model %s unavailable (status %s); using fallback model %s for this run",
                    self._model,
                    exc.code,
                    self._fallback,
                )
                self._model, self._fallback = self._fallback, None
                self._client, self._fallback_client = self._fallback_client, None
                return self._client.models.generate_content(
                    model=self._model, contents=contents, config=config
                )
        except genai_errors.ClientError as exc:
            code = exc.code
            if code == 429:
                raise LLMRateLimitError(
                    "The language model is rate limited. Try again shortly."
                ) from exc
            if code in (401, 403):
                logger.error("LLM authentication failed (status %s)", code)
                raise LLMConfigurationError(
                    "The server's language model credentials were rejected."
                ) from exc
            if code == 404:
                # Google's message names the replacement for a retired model; it holds no secrets.
                logger.error("LLM model not found: %s (%s)", self._model, exc.message)
                raise LLMConfigurationError(
                    "The configured language model does not exist or is not available."
                ) from exc
            if code == 408:
                raise LLMTimeoutError("The language model took too long to respond.") from exc
            # Other 4xx: this request is malformed or too large; retrying will not help. The
            # Gemini API reports an invalid or expired API key as 400 INVALID_ARGUMENT.
            if "API key" in str(exc.message or ""):
                logger.error("LLM authentication failed (status %s)", code)
                raise LLMConfigurationError(
                    "The server's language model credentials were rejected."
                ) from exc
            logger.error("LLM request rejected status=%s status_text=%s", code, exc.status)
            raise LLMResponseError("The language model rejected the request.") from exc
        except genai_errors.APIError as exc:
            logger.warning("LLM API error status=%s", exc.code)
            raise LLMUnavailableError("The language model service is unavailable.") from exc
        except _TIMEOUT_ERRORS as exc:
            raise LLMTimeoutError("The language model took too long to respond.") from exc
        except _CONNECTION_ERRORS as exc:
            raise LLMUnavailableError("Could not reach the language model service.") from exc


def _checked_content(response: types.GenerateContentResponse) -> types.Content:
    feedback = response.prompt_feedback
    if feedback is not None and feedback.block_reason is not None:
        raise LLMRefusalError("The language model declined to answer this request.")
    if not response.candidates:
        raise LLMResponseError("The language model returned no answer.")
    candidate = response.candidates[0]
    reason = candidate.finish_reason.name if candidate.finish_reason is not None else "STOP"
    if reason in _REFUSAL_REASONS:
        raise LLMRefusalError("The language model declined to answer this request.")
    if reason == "MAX_TOKENS":
        raise LLMResponseError("The model's response was cut off before it finished.")
    if reason not in ("STOP", "FINISH_REASON_UNSPECIFIED"):
        logger.warning("Unusable LLM finish reason: %s", reason)
        raise LLMResponseError("The model did not return a usable response.")
    if candidate.content is None:
        raise LLMResponseError("The language model returned no answer.")
    return candidate.content


def _text(parts: list[types.Part]) -> str:
    # Thought parts are the model's reasoning summary; they are never used or shown.
    return "".join(part.text for part in parts if part.text and not part.thought)


def _usage(response: types.GenerateContentResponse) -> Usage:
    meta = response.usage_metadata
    if meta is None:
        return Usage()
    return Usage(
        input_tokens=int(meta.prompt_token_count or 0),
        output_tokens=int(meta.candidates_token_count or 0) + int(meta.thoughts_token_count or 0),
    )


def _to_gemini(messages: list[Message]) -> list[types.Content]:
    names: dict[str, str] = {}
    converted: list[types.Content] = []
    for message in messages:
        if isinstance(message, UserText):
            converted.append(types.Content(role="user", parts=[types.Part(text=message.text)]))
        elif isinstance(message, AssistantTurn):
            for call in message.tool_calls:
                names[call.id] = call.name
            if isinstance(message.raw, types.Content):
                converted.append(message.raw)
                continue
            parts: list[types.Part] = []
            if message.text:
                parts.append(types.Part(text=message.text))
            parts.extend(
                types.Part(
                    function_call=types.FunctionCall(
                        id=_api_id(call.id), name=call.name, args=call.input
                    ),
                    thought_signature=PLACEHOLDER_SIGNATURE,
                )
                for call in message.tool_calls
            )
            converted.append(
                types.Content(role="model", parts=parts or [types.Part(text="(no text)")])
            )
        elif isinstance(message, ToolResults):
            converted.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=_api_id(result.tool_call_id),
                                name=names.get(result.tool_call_id, "tool"),
                                response=(
                                    {"error": result.content}
                                    if result.is_error
                                    else {"output": result.content}
                                ),
                            )
                        )
                        for result in message.results
                    ],
                )
            )
    return converted


def _api_id(call_id: str) -> str | None:
    return None if call_id.startswith(LOCAL_ID_PREFIX) else call_id


__all__ = ["GeminiProvider"]
