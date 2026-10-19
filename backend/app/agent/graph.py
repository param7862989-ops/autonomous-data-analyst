"""The analysis workflow as an explicit LangGraph state machine.

    inspect -> plan -> act <-> tools -> answer -> validate -> (answer once more) -> end

Bounds: a maximum number of act turns, of tool calls in total and per turn, and a wall-clock
deadline; LangGraph's recursion limit is a final backstop. Cancellation is checked before every
step. Model failures end the run with a safe error, keeping any results already computed.
Activity events are emitted for real operations only, and no model reasoning is exposed.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, TypedDict

from langgraph.graph import END, START, StateGraph

from app.agent import prompts
from app.agent.context import DatasetContext, PriorTurn
from app.agent.grounding import check_answer, feedback_for
from app.agent.llm.base import (
    LLMError,
    LLMProvider,
    LLMResponseError,
    Message,
    ToolOutcome,
    ToolResults,
    Usage,
    UserText,
)
from app.agent.schemas import (
    ActivityEvent,
    AgentOutcome,
    AnalysisPlan,
    EventStatus,
    FinalAnswer,
    GroundingReport,
    StopReason,
)
from app.agent.tools import ToolExecutor, tool_specs

logger = logging.getLogger(__name__)

MAX_ANSWER_ATTEMPTS = 2
MAX_CHARTS_SHOWN = 4


@dataclass(frozen=True)
class AgentLimits:
    max_iterations: int = 6
    max_tool_calls: int = 12
    max_tool_calls_per_turn: int = 4
    deadline_seconds: float = 240.0


@dataclass
class AgentDeps:
    provider: LLMProvider
    executor: ToolExecutor
    context: DatasetContext
    history: list[PriorTurn] = field(default_factory=list)
    limits: AgentLimits = field(default_factory=AgentLimits)
    emit: Callable[[ActivityEvent], None] = lambda event: None
    should_cancel: Callable[[], bool] = lambda: False
    clock: Callable[[], float] = time.monotonic


Status = Literal["running", "completed", "failed", "cancelled"]


class AgentState(TypedDict, total=False):
    question: str
    status: Status
    stop_reason: StopReason | None
    plan: AnalysisPlan | None
    transcript: list[Message]
    iterations: int
    tool_calls: int
    answer: FinalAnswer | None
    grounding: GroundingReport | None
    answer_attempts: int
    answer_feedback: str | None
    error_code: str | None
    error_message: str | None


class AnalysisAgent:
    def __init__(self, deps: AgentDeps) -> None:
        self.deps = deps
        self.usage = Usage()
        self._system = prompts.system_prompt(deps.context)
        self._tools = tool_specs()
        self._deadline = 0.0
        self.graph = self._build()

    # --- Graph -------------------------------------------------------------------------------

    def _build(self) -> Any:
        graph = StateGraph(AgentState)
        graph.add_node("inspect", self._inspect)
        graph.add_node("plan", self._plan)
        graph.add_node("act", self._act)
        graph.add_node("tools", self._run_tools)
        graph.add_node("answer", self._answer)
        graph.add_node("validate", self._validate)
        graph.add_edge(START, "inspect")
        graph.add_conditional_edges("inspect", self._after_inspect, {"plan": "plan", "end": END})
        graph.add_conditional_edges(
            "plan", self._after_plan, {"act": "act", "answer": "answer", "end": END}
        )
        graph.add_conditional_edges(
            "act", self._after_act, {"tools": "tools", "answer": "answer", "end": END}
        )
        graph.add_conditional_edges(
            "tools", self._after_tools, {"act": "act", "answer": "answer", "end": END}
        )
        graph.add_conditional_edges(
            "answer", self._after_answer, {"validate": "validate", "end": END}
        )
        graph.add_conditional_edges(
            "validate", self._after_validate, {"answer": "answer", "end": END}
        )
        return graph.compile()

    def run(self, question: str) -> AgentOutcome:
        self._deadline = self.deps.clock() + self.deps.limits.deadline_seconds
        limits = self.deps.limits
        # Each act/tools round is two graph steps; the rest is a fixed overhead.
        recursion_limit = 2 * limits.max_iterations + 2 * MAX_ANSWER_ATTEMPTS + 8
        initial: AgentState = {
            "question": question,
            "status": "running",
            "stop_reason": None,
            "plan": None,
            "transcript": [],
            "iterations": 0,
            "tool_calls": 0,
            "answer": None,
            "grounding": None,
            "answer_attempts": 0,
            "answer_feedback": None,
            "error_code": None,
            "error_message": None,
        }
        final: AgentState = self.graph.invoke(initial, config={"recursion_limit": recursion_limit})
        return self._outcome(final)

    def _outcome(self, state: AgentState) -> AgentOutcome:
        status = state.get("status", "failed")
        if status == "running":
            status = "failed"
        executor = self.deps.executor
        answer = state.get("answer")
        charts = list(executor.charts.values())
        if answer is not None:
            chosen = [c for c in answer.chart_ids if c in executor.charts]
            if not chosen:
                chosen = list(executor.charts)[:MAX_CHARTS_SHOWN]
            answer = answer.model_copy(update={"chart_ids": chosen[:MAX_CHARTS_SHOWN]})
        return AgentOutcome(
            status=status,
            stop_reason=state.get("stop_reason")
            or ("completed" if status == "completed" else "error"),
            plan=state.get("plan"),
            answer=answer,
            results=list(executor.results.values()),
            charts=charts,
            grounding=state.get("grounding"),
            error_code=state.get("error_code"),
            error_message=state.get("error_message"),
            iterations=state.get("iterations", 0),
            tool_calls=state.get("tool_calls", 0),
            usage={
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
                "model": self.deps.provider.model_name,
            },
        )

    # --- Helpers -----------------------------------------------------------------------------

    def _emit(self, key: str, label: str, status: EventStatus, detail: str | None = None) -> None:
        self.deps.emit(
            ActivityEvent(kind="step", key=key, label=label, status=status, detail=detail)
        )

    def _cancelled(self) -> AgentState | None:
        if self.deps.should_cancel():
            self._emit("cancel", "Analysis cancelled", "completed")
            return {"status": "cancelled", "stop_reason": "cancelled"}
        return None

    def _failed(self, key: str, label: str, error: LLMError) -> AgentState:
        logger.warning("Agent step %s failed: %s", key, error.code)
        self._emit(key, label, "failed", error.message)
        return {
            "status": "failed",
            "stop_reason": "error",
            "error_code": error.code,
            "error_message": error.message,
        }

    def _structured[S: (AnalysisPlan, FinalAnswer)](self, prompt: str, schema: type[S]) -> S:
        """One structured call, retried once if the output does not validate."""
        messages: list[Message] = [UserText(prompt)]
        try:
            reply = self.deps.provider.structured(
                system=self._system, messages=messages, schema=schema
            )
        except LLMResponseError:
            reply = self.deps.provider.structured(
                system=self._system, messages=messages, schema=schema
            )
        self.usage.add(reply.usage)
        return reply.value

    # --- Nodes -------------------------------------------------------------------------------

    def _inspect(self, state: AgentState) -> AgentState:
        if cancelled := self._cancelled():
            return cancelled
        context = self.deps.context
        self._emit(
            "inspect",
            "Inspecting dataset",
            "completed",
            f"{context.row_count:,} rows, {len(context.columns)} columns",
        )
        return {}

    def _plan(self, state: AgentState) -> AgentState:
        if cancelled := self._cancelled():
            return cancelled
        self._emit("plan", "Planning analysis", "running")
        try:
            plan = self._structured(
                prompts.plan_prompt(state["question"], self.deps.history), AnalysisPlan
            )
        except LLMError as error:
            return self._failed("plan", "Planning analysis", error)
        known = {c.name for c in self.deps.context.columns}
        plan = plan.model_copy(
            update={
                "relevant_columns": [c for c in plan.relevant_columns if c in known],
                "steps": plan.steps[:6],
            }
        )
        detail = (
            f"{len(plan.steps)} step(s)"
            if plan.answerable
            else "The dataset does not contain what this question needs"
        )
        self._emit("plan", "Planning analysis", "completed", detail)
        update: AgentState = {
            "plan": plan,
            "transcript": [
                UserText(
                    prompts.act_prompt(
                        state["question"],
                        self.deps.history,
                        plan,
                        max_tool_calls=self.deps.limits.max_tool_calls,
                        max_iterations=self.deps.limits.max_iterations,
                    )
                )
            ],
        }
        if not plan.answerable:
            update["stop_reason"] = "not_answerable"
        return update

    def _act(self, state: AgentState) -> AgentState:
        if cancelled := self._cancelled():
            return cancelled
        if self.deps.clock() >= self._deadline:
            return {"stop_reason": "deadline"}
        iteration = state.get("iterations", 0) + 1
        key = f"act:{iteration}"
        self._emit(key, "Choosing the next analysis step", "running")
        try:
            step = self.deps.provider.tool_step(
                system=self._system, messages=state["transcript"], tools=self._tools
            )
        except LLMError as error:
            return self._failed(key, "Choosing the next analysis step", error)
        self.usage.add(step.usage)
        calls = len(step.turn.tool_calls)
        self._emit(
            key,
            "Choosing the next analysis step",
            "completed",
            f"{calls} tool call(s)" if calls else "Enough evidence gathered",
        )
        update: AgentState = {
            "transcript": [*state["transcript"], step.turn],
            "iterations": iteration,
        }
        if not calls:
            update["stop_reason"] = "completed"
        return update

    def _run_tools(self, state: AgentState) -> AgentState:
        turn = state["transcript"][-1]
        assert not isinstance(turn, UserText | ToolResults)
        limits = self.deps.limits
        used = state.get("tool_calls", 0)
        outcomes: list[ToolOutcome] = []
        executed = 0
        iteration = state.get("iterations", 0)
        for index, call in enumerate(turn.tool_calls, start=1):
            # Keys are owned by the graph (unique per turn and position), not by provider ids.
            key = f"tool:{iteration}:{index}"
            if self.deps.should_cancel():
                outcomes.append(ToolOutcome(call.id, "Error: the analysis was cancelled.", True))
                continue
            if (
                executed >= limits.max_tool_calls_per_turn
                or used + executed >= limits.max_tool_calls
            ):
                outcomes.append(
                    ToolOutcome(
                        call.id,
                        "Error: tool call limit reached; this call was not run.",
                        is_error=True,
                    )
                )
                continue
            executed += 1
            self.deps.emit(_running_event(key, call.name))
            execution = self.deps.executor.execute(call)
            self.deps.emit(execution.event.model_copy(update={"key": key}))
            outcomes.append(execution.outcome)
        total = used + executed
        update: AgentState = {
            "transcript": [*state["transcript"], ToolResults(outcomes)],
            "tool_calls": total,
        }
        if self.deps.should_cancel():
            update.update({"status": "cancelled", "stop_reason": "cancelled"})
        elif total >= limits.max_tool_calls:
            update["stop_reason"] = "tool_limit"
        elif state.get("iterations", 0) >= limits.max_iterations:
            update["stop_reason"] = "iteration_limit"
        elif self.deps.clock() >= self._deadline:
            update["stop_reason"] = "deadline"
        return update

    def _answer(self, state: AgentState) -> AgentState:
        if cancelled := self._cancelled():
            return cancelled
        attempt = state.get("answer_attempts", 0) + 1
        self._emit("answer", "Preparing answer", "running")
        executor = self.deps.executor
        prompt = prompts.answer_prompt(
            state["question"],
            self.deps.history,
            state.get("plan"),
            list(executor.results.values()),
            list(executor.charts.values()),
            stop_note=_stop_note(state.get("stop_reason")),
            feedback=state.get("answer_feedback"),
        )
        try:
            answer = self._structured(prompt, FinalAnswer)
        except LLMError as error:
            return self._failed("answer", "Preparing answer", error)
        self._emit("answer", "Preparing answer", "completed")
        return {"answer": answer, "answer_attempts": attempt}

    def _validate(self, state: AgentState) -> AgentState:
        answer = state["answer"]
        assert answer is not None
        executor = self.deps.executor
        report = check_answer(
            answer, list(executor.results.values()), list(executor.charts.values())
        )
        if report.passed:
            detail = f"All {report.checked_numbers} figure(s) match computed results"
        else:
            problems = (
                len(report.unverified_numbers)
                + len(report.invalid_references)
                + len(report.unsupported_facts)
            )
            detail = f"{problems} issue(s) found"
        self._emit("validate", "Validating results", "completed", detail)
        update: AgentState = {"grounding": report}
        if not report.passed and state.get("answer_attempts", 0) < MAX_ANSWER_ATTEMPTS:
            update["answer_feedback"] = feedback_for(report)
        else:
            update["status"] = "completed"
            update["answer_feedback"] = None
            if state.get("stop_reason") is None:
                update["stop_reason"] = "completed"
        return update

    # --- Routing -----------------------------------------------------------------------------

    @staticmethod
    def _halted(state: AgentState) -> bool:
        return state.get("status") in {"failed", "cancelled"}

    def _after_inspect(self, state: AgentState) -> str:
        return "end" if self._halted(state) else "plan"

    def _after_plan(self, state: AgentState) -> str:
        if self._halted(state):
            return "end"
        return "answer" if state.get("stop_reason") == "not_answerable" else "act"

    def _after_act(self, state: AgentState) -> str:
        if self._halted(state):
            return "end"
        if state.get("stop_reason") in {"completed", "deadline"}:
            return "answer"
        return "tools"

    def _after_tools(self, state: AgentState) -> str:
        if self._halted(state):
            return "end"
        return "answer" if state.get("stop_reason") else "act"

    def _after_answer(self, state: AgentState) -> str:
        return "end" if self._halted(state) else "validate"

    def _after_validate(self, state: AgentState) -> str:
        return "end" if state.get("status") == "completed" else "answer"


def _running_event(key: str, tool: str) -> ActivityEvent:
    labels = {
        "inspect_dataset": "Reading sample rows",
        "get_dataset_profile": "Reviewing column profiles",
        "execute_analysis": "Running analysis",
        "execute_sql": "Running a validated SQL query",
        "create_chart": "Generating chart",
    }
    return ActivityEvent(
        kind="tool", key=key, label=labels.get(tool, "Running tool"), status="running"
    )


def _stop_note(reason: StopReason | None) -> str | None:
    return {
        "not_answerable": "The plan concluded this dataset cannot answer the question.",
        "iteration_limit": "The step limit was reached; answer from the evidence gathered and "
        "say what remains unverified.",
        "tool_limit": "The tool-call limit was reached; answer from the evidence gathered and "
        "say what remains unverified.",
        "deadline": "The time limit was reached; answer from the evidence gathered and say what "
        "remains unverified.",
    }.get(reason or "")
