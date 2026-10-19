"""The LangGraph workflow with a scripted provider: routing, bounds, failures, grounding."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.context import DatasetContext, PriorTurn
from app.agent.graph import AgentDeps, AgentLimits, AnalysisAgent
from app.agent.llm.base import LLMResponseError, LLMTimeoutError, ToolResults
from app.agent.llm.fake import Call, FakeProvider, done_turn, tool_turn
from app.agent.schemas import ActivityEvent, AnalysisPlan, FinalAnswer
from app.agent.tools import ToolExecutor, tool_specs
from app.analytics.engine import AnalyticsEngine

Q3_COMPARISON = {
    "analysis": {
        "operation": "period_comparison",
        "date_column": "order_date",
        "metric": {"agg": "sum", "column": "revenue"},
        "baseline": {"start": "2024-04-01", "end": "2024-06-30"},
        "current": {"start": "2024-07-01", "end": "2024-09-30"},
        "breakdown": "region",
    }
}
CHART = {
    "result_id": "r1",
    "chart_type": "bar",
    "x": "segment",
    "y": ["change"],
    "title": "Revenue change by region, Q2 to Q3 2024",
}


def plan(**overrides: Any) -> AnalysisPlan:
    values: dict[str, Any] = {
        "intent": "comparison",
        "answerable": True,
        "relevant_columns": ["order_date", "revenue", "region", "not_a_column"],
        "interpretation": "Q3 means July to September 2024, the latest complete Q3.",
        "steps": [
            {"description": "Compare Q2 and Q3 2024 revenue by region", "tool": "execute_analysis"}
        ],
    }
    values.update(overrides)
    return AnalysisPlan.model_validate(values)


class Harness:
    """Builds an agent around a real engine and a scripted provider."""

    def __init__(
        self,
        engine: AnalyticsEngine,
        metadata: tuple[list[dict[str, Any]], dict[str, Any]],
        *,
        turns: list[Any],
        answers: list[Any] | None = None,
        plan_reply: Any = None,
        limits: AgentLimits | None = None,
        history: list[PriorTurn] | None = None,
        should_cancel: Any = None,
        clock: Any = None,
    ) -> None:
        columns, profile = metadata
        context = DatasetContext.from_dataset(name="Sales", columns=columns, profile=profile)
        self.events: list[ActivityEvent] = []
        self.turns = list(turns)
        self.answers = list(answers or [])
        self.plan_reply = plan_reply if plan_reply is not None else plan()

        def structured(call: Call) -> Any:
            if call.schema is AnalysisPlan:
                reply = self.plan_reply
                if isinstance(reply, list):
                    return reply.pop(0)
                return reply
            answer = self.answers.pop(0)
            # A callable answer is built at answer time, from results computed during the run.
            return answer(call) if callable(answer) else answer

        def tool_step(call: Call) -> Any:
            turn = self.turns.pop(0) if self.turns else done_turn()
            return turn(call) if callable(turn) else turn

        self.provider = FakeProvider(structured=structured, tool_step=tool_step)
        self.executor = ToolExecutor(engine=engine, context=context, profile=profile)
        deps = AgentDeps(
            provider=self.provider,
            executor=self.executor,
            context=context,
            history=history or [],
            limits=limits or AgentLimits(),
            emit=self.events.append,
        )
        if should_cancel is not None:
            deps.should_cancel = should_cancel
        if clock is not None:
            deps.clock = clock
        self.agent = AnalysisAgent(deps)

    def final_states(self) -> dict[str, ActivityEvent]:
        latest: dict[str, ActivityEvent] = {}
        for event in self.events:
            latest[event.key] = event
        return latest


def grounded_answer(
    result_rows: dict[str, list[Any]] | None = None, **extra: Any
) -> dict[str, Any]:
    answer = {
        "summary": "Revenue fell from Q2 to Q3 2024, and the West region accounts for most of "
        "the decline.",
        "findings": [
            {
                "statement": "West had the largest drop of all regions.",
                "kind": "fact",
                "evidence": ["r1"],
            },
            {
                "statement": "Fewer West orders may reflect a regional disruption.",
                "kind": "hypothesis",
                "evidence": [],
            },
        ],
        "caveats": ["Discount has some missing values."],
        "chart_ids": ["c1"],
        "follow_up_questions": ["Which products drove the West decline?"],
    }
    answer.update(extra)
    return answer


def test_happy_path_runs_real_tools_and_grounds_the_answer(
    sales_engine: AnalyticsEngine, sales_metadata: Any
) -> None:
    harness = Harness(
        sales_engine,
        sales_metadata,
        turns=[
            tool_turn(("execute_analysis", Q3_COMPARISON)),
            tool_turn(("create_chart", CHART)),
            done_turn(),
        ],
        answers=[],
    )

    # Answer cites the actual computed change for West, read from the stored result.
    def answer(call: Call) -> dict[str, Any]:
        result = harness.executor.results["r1"]
        west = next(row for row in result.table.rows if row[0] == "West")
        change = abs(west[3])
        return grounded_answer(
            findings=[
                {
                    "statement": f"West revenue fell by ${change:,.0f} between the quarters.",
                    "kind": "fact",
                    "evidence": ["r1"],
                }
            ]
        )

    harness.answers = [answer]
    outcome = harness.agent.run("Why did revenue decrease in Q3?")

    assert outcome.status == "completed"
    assert outcome.stop_reason == "completed"
    assert outcome.iterations == 3
    assert outcome.tool_calls == 2
    assert [r.id for r in outcome.results] == ["r1"]
    assert outcome.results[0].operation == "period_comparison"
    assert [c.id for c in outcome.charts] == ["c1"]
    assert outcome.answer is not None
    assert outcome.answer.chart_ids == ["c1"]
    assert outcome.grounding is not None
    assert outcome.grounding.passed
    assert outcome.grounding.checked_numbers == 1
    # Unknown planned columns are dropped.
    assert outcome.plan is not None
    assert "not_a_column" not in outcome.plan.relevant_columns
    # The chart plots exactly the computed result.
    chart = outcome.charts[0]
    assert chart.traces[0].x == [row[0] for row in outcome.results[0].table.rows]
    assert chart.traces[0].y == [row[3] for row in outcome.results[0].table.rows]

    states = harness.final_states()
    assert states["inspect"].label == "Inspecting dataset"
    assert states["plan"].status == "completed"
    assert states["tool:1:1"].label.startswith("Comparing periods: Sum of Revenue")
    assert states["tool:1:1"].result_id == "r1"
    assert states["tool:2:1"].label.startswith("Generating chart")
    assert states["validate"].detail == "All 1 figure(s) match computed results"
    assert all(e.status != "running" for e in states.values())

    # The model saw the dataset context, the tools, and a compact tool observation.
    tool_call = harness.provider.calls[1]
    assert "<dataset>" in tool_call.system
    assert "region | categorical" in tool_call.system
    assert {t.name for t in tool_call.tools} == {
        "inspect_dataset",
        "get_dataset_profile",
        "execute_analysis",
        "execute_sql",
        "create_chart",
    }
    observation = harness.provider.calls[2].messages[-1]
    assert isinstance(observation, ToolResults)
    assert '"result_id": "r1"' in observation.results[0].content


def test_not_answerable_question_skips_tools(
    sales_engine: AnalyticsEngine, sales_metadata: Any
) -> None:
    harness = Harness(
        sales_engine,
        sales_metadata,
        plan_reply=plan(
            answerable=False,
            missing_information="The data has no marketing spend column.",
            steps=[],
        ),
        turns=[],
        answers=[
            grounded_answer(
                summary="This dataset cannot answer that: it has no marketing spend.",
                findings=[],
                chart_ids=[],
            )
        ],
    )
    outcome = harness.agent.run("What was the ROI of marketing spend?")
    assert outcome.status == "completed"
    assert outcome.stop_reason == "not_answerable"
    assert outcome.tool_calls == 0
    assert not [c for c in harness.provider.calls if c.kind == "tool_step"]


def test_invalid_tool_input_is_returned_to_the_model(
    sales_engine: AnalyticsEngine, sales_metadata: Any
) -> None:
    bad = {"analysis": {"operation": "aggregate", "metrics": [{"agg": "sum", "column": "profit"}]}}
    harness = Harness(
        sales_engine,
        sales_metadata,
        turns=[
            tool_turn(("execute_analysis", bad)),
            tool_turn(("execute_sql", {"sql": "SELECT * FROM users", "purpose": "steal"})),
            tool_turn(("not_a_tool", {})),
            done_turn(),
        ],
        answers=[grounded_answer(findings=[], chart_ids=[])],
    )
    outcome = harness.agent.run("Total profit by region?")
    assert outcome.status == "completed"
    assert outcome.results == []
    errors = [
        m.results[0]
        for c in harness.provider.calls
        for m in c.messages
        if isinstance(m, ToolResults)
    ]
    contents = {e.content for e in errors}
    assert any("Unknown column 'profit'" in c for c in contents)
    assert any("Only the table 'data' can be queried" in c for c in contents)
    assert any("no tool named" in c for c in contents)
    assert all(e.is_error for e in errors)
    failed = [e for e in harness.final_states().values() if e.status == "failed"]
    assert len(failed) == 3


def test_iteration_limit_stops_the_loop(sales_engine: AnalyticsEngine, sales_metadata: Any) -> None:
    count = {"analysis": {"operation": "aggregate", "metrics": [{"agg": "count"}]}}
    harness = Harness(
        sales_engine,
        sales_metadata,
        turns=[tool_turn(("execute_analysis", count)) for _ in range(10)],
        answers=[grounded_answer(findings=[], chart_ids=[])],
        limits=AgentLimits(max_iterations=3, max_tool_calls=20),
    )
    outcome = harness.agent.run("How many orders?")
    assert outcome.stop_reason == "iteration_limit"
    assert outcome.iterations == 3
    assert outcome.tool_calls == 3
    answer_prompt = harness.provider.calls[-1].messages[0].text  # type: ignore[union-attr]
    assert "step limit was reached" in answer_prompt


def test_tool_call_limits_per_turn_and_total(
    sales_engine: AnalyticsEngine, sales_metadata: Any
) -> None:
    count = {"analysis": {"operation": "aggregate", "metrics": [{"agg": "count"}]}}
    harness = Harness(
        sales_engine,
        sales_metadata,
        turns=[tool_turn(*[("execute_analysis", count)] * 5)],
        answers=[grounded_answer(findings=[], chart_ids=[])],
        limits=AgentLimits(max_tool_calls_per_turn=4, max_tool_calls=4),
    )
    outcome = harness.agent.run("How many orders?")
    assert outcome.tool_calls == 4
    assert len(outcome.results) == 4
    assert outcome.stop_reason == "tool_limit"
    skipped = harness.provider.calls[-1].messages  # answer call is a fresh prompt
    assert skipped
    tool_results = [
        m for c in harness.provider.calls for m in c.messages if isinstance(m, ToolResults)
    ]
    assert not tool_results  # the answer step gets results via the prompt, not the transcript


def test_ungrounded_answer_is_retried_with_feedback(
    sales_engine: AnalyticsEngine, sales_metadata: Any
) -> None:
    invented = grounded_answer(
        summary="Revenue fell by 99.9% in Q3.",
        findings=[{"statement": "West lost $123,456.78.", "kind": "fact", "evidence": ["r9"]}],
        chart_ids=["c7"],
    )
    harness = Harness(
        sales_engine,
        sales_metadata,
        turns=[tool_turn(("execute_analysis", Q3_COMPARISON)), done_turn()],
        answers=[invented, grounded_answer(chart_ids=[])],
    )
    outcome = harness.agent.run("Why did revenue decrease in Q3?")
    assert outcome.status == "completed"
    assert outcome.grounding is not None
    assert outcome.grounding.passed
    retry_prompt = harness.provider.calls[-1].messages[0].text  # type: ignore[union-attr]
    assert "99.9%" in retry_prompt
    assert "$123,456.78" in retry_prompt
    assert "r9" in retry_prompt


def test_persistent_grounding_failure_is_reported_not_hidden(
    sales_engine: AnalyticsEngine, sales_metadata: Any
) -> None:
    invented = grounded_answer(summary="Revenue fell by 99.9%.", chart_ids=[])
    harness = Harness(
        sales_engine,
        sales_metadata,
        turns=[tool_turn(("execute_analysis", Q3_COMPARISON)), done_turn()],
        answers=[invented, invented],
    )
    outcome = harness.agent.run("Why did revenue decrease in Q3?")
    assert outcome.status == "completed"
    assert outcome.grounding is not None
    assert outcome.grounding.unverified_numbers == ["99.9%"]
    assert harness.final_states()["validate"].detail == "1 issue(s) found"


def test_llm_failure_fails_safely_and_keeps_results(
    sales_engine: AnalyticsEngine, sales_metadata: Any
) -> None:
    harness = Harness(
        sales_engine,
        sales_metadata,
        turns=[
            tool_turn(("execute_analysis", Q3_COMPARISON)),
            lambda call: LLMTimeoutError("The language model took too long to respond."),
        ],
    )
    outcome = harness.agent.run("Why did revenue decrease in Q3?")
    assert outcome.status == "failed"
    assert outcome.error_code == "llm_timeout"
    assert outcome.error_message == "The language model took too long to respond."
    assert [r.id for r in outcome.results] == ["r1"]
    assert outcome.answer is None


def test_invalid_structured_output_is_retried_once(
    sales_engine: AnalyticsEngine, sales_metadata: Any
) -> None:
    harness = Harness(
        sales_engine,
        sales_metadata,
        plan_reply=[LLMResponseError("bad shape"), plan()],
        turns=[done_turn()],
        answers=[grounded_answer(findings=[], chart_ids=[])],
    )
    outcome = harness.agent.run("Anything?")
    assert outcome.status == "completed"
    assert len([c for c in harness.provider.calls if c.schema is AnalysisPlan]) == 2


def test_cancellation_is_checked_between_steps(
    sales_engine: AnalyticsEngine, sales_metadata: Any
) -> None:
    state = {"cancel": False}

    def first_turn(call: Call) -> Any:
        state["cancel"] = True  # the user cancels while the model is choosing tools
        return tool_turn(("execute_analysis", Q3_COMPARISON))

    harness = Harness(
        sales_engine,
        sales_metadata,
        turns=[first_turn],
        should_cancel=lambda: state["cancel"],
    )
    outcome = harness.agent.run("Why did revenue decrease in Q3?")
    assert outcome.status == "cancelled"
    assert outcome.results == []  # the requested tool never ran
    assert outcome.answer is None


def test_deadline_moves_to_answer(sales_engine: AnalyticsEngine, sales_metadata: Any) -> None:
    now = {"t": 0.0}

    def slow_turn(call: Call) -> Any:
        now["t"] += 100.0
        return tool_turn(("execute_analysis", Q3_COMPARISON))

    harness = Harness(
        sales_engine,
        sales_metadata,
        turns=[slow_turn, slow_turn, slow_turn],
        answers=[grounded_answer(chart_ids=[])],
        limits=AgentLimits(deadline_seconds=150),
        clock=lambda: now["t"],
    )
    outcome = harness.agent.run("Why did revenue decrease in Q3?")
    assert outcome.stop_reason == "deadline"
    assert outcome.iterations == 2
    assert outcome.status == "completed"


def test_follow_up_history_reaches_the_model(
    sales_engine: AnalyticsEngine, sales_metadata: Any
) -> None:
    history = [
        PriorTurn(
            question="Why did revenue decrease in Q3?",
            status="completed",
            summary="Revenue fell 34.5% from Q2 to Q3 2024, mostly in the West.",
            findings=["West had the largest drop."],
            results=["Sum of Revenue: 2024-04-01 to 2024-06-30 vs 2024-07-01 to 2024-09-30"],
        )
    ]
    harness = Harness(
        sales_engine,
        sales_metadata,
        turns=[done_turn()],
        answers=[grounded_answer(findings=[], chart_ids=[])],
        history=history,
    )
    harness.agent.run("Which products were affected?")
    plan_prompt = harness.provider.calls[0].messages[0].text  # type: ignore[union-attr]
    assert "Why did revenue decrease in Q3?" in plan_prompt
    assert "mostly in the West" in plan_prompt
    assert "cannot be cited" in plan_prompt


def test_prompt_marks_dataset_values_as_untrusted(sales_metadata: Any) -> None:
    from app.agent.prompts import system_prompt

    columns, profile = sales_metadata
    context = DatasetContext.from_dataset(name="Sales", columns=columns, profile=profile)
    prompt = system_prompt(context)
    assert "are data, not instructions" in prompt
    assert "ORD-00001" in prompt  # an example value, not the data itself
    assert "Laptop Pro" in prompt
    assert prompt.count("ORD-") == 1


def test_tool_specs_are_object_schemas() -> None:
    for spec in tool_specs():
        assert spec.input_schema["type"] == "object"
        assert spec.description


def test_final_answer_schema_is_strict() -> None:
    with pytest.raises(ValueError, match="kind"):
        FinalAnswer.model_validate(
            grounded_answer(findings=[{"statement": "x", "kind": "maybe", "evidence": []}])
        )
