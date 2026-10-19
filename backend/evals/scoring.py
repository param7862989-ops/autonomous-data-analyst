"""Scoring helpers: does a text or a result contain a ground-truth figure or entity?"""

from __future__ import annotations

import math
from typing import Any

from app.agent.grounding import extract_numbers
from app.agent.schemas import AgentOutcome, StoredResult


def _close(candidate: float, truth: float, tolerance: float) -> bool:
    return abs(candidate - truth) <= max(tolerance * abs(truth), 1e-9)


def text_states(text: str, truth: float, *, percent: bool, tolerance: float) -> bool:
    """True if ``text`` states the figure, allowing for written rounding and % for ratios."""
    target = abs(truth)
    for token in extract_numbers(text):
        candidates = [target * 100] if percent and token.percent else [target]
        if percent and not token.percent:
            candidates.append(target)
        for value in candidates:
            if _close(token.value, value, tolerance) or abs(token.value - value) <= token.rounding:
                return True
    return False


def result_contains(results: list[StoredResult], truth: float, *, tolerance: float) -> bool:
    """True if any computed result holds the figure (or its magnitude)."""
    target = abs(truth)
    for result in results:
        values = [v for row in result.table.rows for v in row] + list(result.summary.values())
        for value in values:
            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            if math.isfinite(value) and _close(abs(float(value)), target, tolerance):
                return True
    return False


def aliases(entity: Any) -> tuple[str, ...]:
    if isinstance(entity, tuple | list):
        return tuple(str(item) for item in entity)
    return (str(entity),)


def result_mentions(results: list[StoredResult], entity: Any) -> bool:
    needles = {alias.lower() for alias in aliases(entity)}
    return any(
        isinstance(value, str) and value.lower() in needles
        for result in results
        for row in result.table.rows
        for value in row
    )


def text_mentions(text: str, entity: Any) -> bool:
    lowered = text.lower()
    return any(alias.lower() in lowered for alias in aliases(entity))


def answer_text(outcome: AgentOutcome) -> str:
    if outcome.answer is None:
        return ""
    parts = [outcome.answer.summary] + [f.statement for f in outcome.answer.findings]
    return "\n".join(parts)


def columns_used(outcome: AgentOutcome, known_columns: set[str]) -> set[str]:
    """Known column names that appear in the plan or in any tool input (including SQL text)."""
    used: set[str] = set()
    if outcome.plan is not None:
        used |= set(outcome.plan.relevant_columns) & known_columns

    def scan(value: Any) -> None:
        if isinstance(value, str):
            if value in known_columns:
                used.add(value)
            else:
                lowered = value.lower()
                used.update(c for c in known_columns if c in lowered)
        elif isinstance(value, dict):
            for item in value.values():
                scan(item)
        elif isinstance(value, list):
            for item in value:
                scan(item)

    for result in outcome.results:
        scan(result.arguments or {})
    return used


def operations_used(outcome: AgentOutcome) -> set[str]:
    return {result.operation for result in outcome.results}


def charts_consistent(outcome: AgentOutcome) -> bool:
    """Every chart's plotted values come from the result it cites."""
    results = {r.id: r for r in outcome.results}
    for chart in outcome.charts:
        source = results.get(chart.source_result_id)
        if source is None:
            return False
        values = {
            float(v)
            for row in source.table.rows
            for v in row
            if isinstance(v, int | float) and not isinstance(v, bool)
        }
        for trace in chart.traces:
            if any(y is not None and float(y) not in values for y in trace.y):
                return False
        if chart.heatmap is not None:
            cells = [v for row in chart.heatmap.z for v in row if v is not None]
            if any(float(v) not in values for v in cells):
                return False
    return True
