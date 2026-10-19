"""Provider-neutral LLM interface used by the agent.

The agent only depends on this module. Provider SDKs (Anthropic today) live behind it, and
tests use a fake implementation, so the standard test suite never calls a paid API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


# --- Conversation ----------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class UserText:
    text: str


@dataclass(frozen=True)
class AssistantTurn:
    text: str
    tool_calls: list[ToolCall]
    # Provider-native content (e.g. Anthropic content blocks, including thinking blocks), replayed
    # unchanged on the next request. Other providers may ignore it.
    raw: Any = None


@dataclass(frozen=True)
class ToolOutcome:
    tool_call_id: str
    content: str
    is_error: bool = False


@dataclass(frozen=True)
class ToolResults:
    results: list[ToolOutcome]


Message = UserText | AssistantTurn | ToolResults


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0

    def add(self, other: Usage) -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens


@dataclass
class ToolStep:
    turn: AssistantTurn
    usage: Usage = field(default_factory=Usage)


@dataclass
class StructuredReply[S: BaseModel]:
    value: S
    usage: Usage = field(default_factory=Usage)


# --- Errors ----------------------------------------------------------------------------------


class LLMError(Exception):
    """A provider failure. ``message`` is safe to store and show; it never includes secrets."""

    code = "llm_error"
    retryable = False

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class LLMTimeoutError(LLMError):
    code = "llm_timeout"
    retryable = True


class LLMRateLimitError(LLMError):
    code = "llm_rate_limited"
    retryable = True


class LLMUnavailableError(LLMError):
    code = "llm_unavailable"
    retryable = True


class LLMConfigurationError(LLMError):
    code = "llm_not_configured"


class LLMRefusalError(LLMError):
    code = "llm_refused"


class LLMResponseError(LLMError):
    """The model answered, but not in a usable shape (invalid structure, cut off)."""

    code = "llm_bad_response"


# --- Provider --------------------------------------------------------------------------------


class LLMProvider(Protocol):
    @property
    def model_name(self) -> str: ...

    def structured(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: type[T],
        max_tokens: int = 16_000,
    ) -> StructuredReply[T]:
        """Return a response validated against ``schema``."""
        ...

    def tool_step(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        max_tokens: int = 16_000,
    ) -> ToolStep:
        """One model turn that may request tool calls (tool choice is automatic)."""
        ...
