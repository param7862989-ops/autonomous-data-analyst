"""A deterministic, scriptable LLM provider for tests, evaluation of the harness, and E2E runs.

It never calls a network service. Each call is answered by a handler that receives exactly what
a real provider would see, so tests can assert on prompts, tool definitions and transcripts.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

from pydantic import BaseModel

from app.agent.llm.base import (
    AssistantTurn,
    LLMError,
    Message,
    StructuredReply,
    ToolCall,
    ToolSpec,
    ToolStep,
    Usage,
)

T = TypeVar("T", bound=BaseModel)


@dataclass
class Call:
    kind: str  # "structured" | "tool_step"
    system: str
    messages: list[Message]
    schema: type[BaseModel] | None = None
    tools: list[ToolSpec] = field(default_factory=list)


StructuredHandler = Callable[[Call], BaseModel | dict[str, Any] | LLMError]
ToolHandler = Callable[[Call], AssistantTurn | LLMError]


class FakeProvider:
    def __init__(
        self,
        *,
        structured: StructuredHandler | None = None,
        tool_step: ToolHandler | None = None,
        model_name: str = "fake-model",
    ) -> None:
        self._structured = structured
        self._tool_step = tool_step
        self._model_name = model_name
        self.calls: list[Call] = []

    @property
    def model_name(self) -> str:
        return self._model_name

    def structured(
        self,
        *,
        system: str,
        messages: list[Message],
        schema: type[T],
        max_tokens: int = 16_000,
    ) -> StructuredReply[T]:
        call = Call("structured", system, list(messages), schema=schema)
        self.calls.append(call)
        if self._structured is None:
            raise AssertionError("FakeProvider has no structured handler")
        result = self._structured(call)
        if isinstance(result, LLMError):
            raise result
        value = schema.model_validate(result if isinstance(result, dict) else result.model_dump())
        return StructuredReply(value=value, usage=Usage(10, 10))

    def tool_step(
        self,
        *,
        system: str,
        messages: list[Message],
        tools: list[ToolSpec],
        max_tokens: int = 16_000,
    ) -> ToolStep:
        call = Call("tool_step", system, list(messages), tools=list(tools))
        self.calls.append(call)
        if self._tool_step is None:
            raise AssertionError("FakeProvider has no tool handler")
        result = self._tool_step(call)
        if isinstance(result, LLMError):
            raise result
        return ToolStep(turn=result, usage=Usage(10, 10))


def tool_turn(*calls: tuple[str, dict[str, Any]], text: str = "") -> AssistantTurn:
    """Build an assistant turn requesting the given (tool name, input) calls."""
    return AssistantTurn(
        text=text,
        tool_calls=[ToolCall(id=f"call_{i}", name=n, input=a) for i, (n, a) in enumerate(calls)],
    )


def done_turn(text: str = "Analysis complete.") -> AssistantTurn:
    return AssistantTurn(text=text, tool_calls=[])
