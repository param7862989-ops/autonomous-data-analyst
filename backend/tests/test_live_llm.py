"""Opt-in tests against the configured real LLM provider.

They call a paid or rate-limited API, so they run only when asked for:

    RUN_LIVE_LLM_TESTS=1 uv run pytest -m live_llm

The provider, model and key come from the environment or the root .env, as for the app.
"""

from __future__ import annotations

import os
from typing import Any

import pytest

from app.agent import prompts
from app.agent.context import DatasetContext
from app.agent.llm.base import LLMProvider, ToolOutcome, ToolResults, UserText
from app.agent.llm.factory import provider_from_settings
from app.agent.schemas import AnalysisPlan
from app.agent.tools import tool_specs
from app.config import Settings

pytestmark = [
    pytest.mark.live_llm,
    pytest.mark.skipif(
        os.environ.get("RUN_LIVE_LLM_TESTS") != "1",
        reason="set RUN_LIVE_LLM_TESTS=1 to call the real LLM provider",
    ),
]


@pytest.fixture
def provider() -> LLMProvider:
    settings = Settings()
    if not settings.analysis_enabled:
        pytest.fail(f"RUN_LIVE_LLM_TESTS=1 but no API key is set for {settings.llm_provider}")
    return provider_from_settings(settings)


@pytest.fixture
def system(sales_metadata: Any) -> str:
    columns, profile = sales_metadata
    context = DatasetContext.from_dataset(name="Sales", columns=columns, profile=profile)
    return prompts.system_prompt(context)


def test_structured_plan(provider: LLMProvider, system: str) -> None:
    prompt = prompts.plan_prompt("What was total revenue by region in 2024?", [])
    reply = provider.structured(system=system, messages=[UserText(prompt)], schema=AnalysisPlan)
    assert reply.value.answerable
    assert {"region", "revenue"} <= set(reply.value.relevant_columns)
    assert reply.usage.input_tokens > 0


def test_tool_call_round_trip(provider: LLMProvider, system: str) -> None:
    question = UserText("Use a tool to show three example rows of the dataset.")
    specs = tool_specs()
    first = provider.tool_step(system=system, messages=[question], tools=specs)
    calls = first.turn.tool_calls
    assert calls
    assert {call.name for call in calls} <= {spec.name for spec in specs}

    # Replaying the turn exercises what providers are strict about: ids and thought signatures.
    results = ToolResults([ToolOutcome(call.id, '{"rows": [["West", 1200]]}') for call in calls])
    second = provider.tool_step(
        system=system, messages=[question, first.turn, results], tools=specs
    )
    assert second.turn.text or second.turn.tool_calls
