"""What the model is told about the dataset and the conversation so far.

Only metadata, short value summaries from the stored profile, and earlier computed results are
included. The dataset itself is never sent; the model reads data only through tools.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.analytics.operations import ColumnSpec, DatasetSchema

_MAX_VALUE_CHARS = 40
_TOP_VALUES = 6
MAX_HISTORY_TURNS = 5


def _short(value: Any) -> str:
    text = str(value)
    return text if len(text) <= _MAX_VALUE_CHARS else text[: _MAX_VALUE_CHARS - 1] + "…"


def _number(value: Any) -> str:
    if value is None:
        return "?"
    number = float(value)
    return f"{number:,.0f}" if abs(number) >= 100 else f"{number:,.4g}"


@dataclass(frozen=True)
class ColumnContext:
    name: str
    original_name: str
    semantic_type: str
    missing_share: float
    unique_count: int
    summary: str


@dataclass(frozen=True)
class DatasetContext:
    name: str
    row_count: int
    columns: list[ColumnContext]
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def from_dataset(
        cls, *, name: str, columns: list[dict[str, Any]], profile: dict[str, Any]
    ) -> DatasetContext:
        by_name = {c["name"]: c for c in profile.get("columns", [])}
        contexts = []
        for column in columns:
            stats = by_name.get(column["name"], {})
            contexts.append(
                ColumnContext(
                    name=column["name"],
                    original_name=column["original_name"],
                    semantic_type=column["semantic_type"],
                    missing_share=float(stats.get("missing_share", 0.0)),
                    unique_count=int(stats.get("unique_count", 0)),
                    summary=_column_summary(column["semantic_type"], stats),
                )
            )
        warnings = [
            (f"{w['column']}: " if w.get("column") else "") + w["message"]
            for w in profile.get("warnings", [])
        ]
        return cls(
            name=name,
            row_count=int(profile.get("row_count", 0)),
            columns=contexts,
            warnings=warnings,
        )

    def schema(self) -> DatasetSchema:
        return DatasetSchema(
            [ColumnSpec(c.name, c.semantic_type, c.original_name) for c in self.columns]  # type: ignore[arg-type]
        )

    def render(self) -> str:
        lines = [
            f"Dataset: {_short(self.name)}",
            f"Rows: {self.row_count:,}",
            "Table name for SQL: data",
            "Columns (name | type | original header | missing | distinct | summary):",
        ]
        for c in self.columns:
            lines.append(
                f"- {c.name} | {c.semantic_type} | {json.dumps(c.original_name)} | "
                f"{c.missing_share:.1%} | {c.unique_count:,} | {c.summary}"
            )
        if self.warnings:
            lines.append("Data-quality warnings:")
            lines.extend(f"- {w}" for w in self.warnings[:20])
        return "\n".join(lines)


def _column_summary(semantic_type: str, stats: dict[str, Any]) -> str:
    if semantic_type == "numeric" and stats.get("numeric"):
        n = stats["numeric"]
        low, high, mean = (_number(n.get(k)) for k in ("min", "max", "mean"))
        return f"min {low}, max {high}, mean {mean}"
    if semantic_type == "datetime" and stats.get("datetime"):
        d = stats["datetime"]
        return f"from {str(d.get('min'))[:10]} to {str(d.get('max'))[:10]}"
    top = stats.get("top_values") or []
    if semantic_type == "text" and top:
        return f"free text, e.g. {json.dumps(_short(top[0]['value']))}"
    if top:
        values = ", ".join(
            f"{json.dumps(_short(v['value']))} ({v['count']:,})" for v in top[:_TOP_VALUES]
        )
        more = " …" if len(top) > _TOP_VALUES else ""
        return f"values {values}{more}"
    return "no values"


@dataclass(frozen=True)
class PriorTurn:
    """A compact record of an earlier question in the same conversation."""

    question: str
    status: str
    summary: str | None = None
    findings: list[str] = field(default_factory=list)
    results: list[str] = field(default_factory=list)


def render_history(turns: list[PriorTurn]) -> str:
    if not turns:
        return "This is the first question in the conversation."
    lines = ["Earlier in this conversation (oldest first):"]
    for index, turn in enumerate(turns[-MAX_HISTORY_TURNS:], start=1):
        lines.append(f"{index}. Question: {json.dumps(turn.question)}")
        if turn.status != "completed":
            lines.append(f"   Outcome: the analysis {turn.status}.")
            continue
        if turn.summary:
            lines.append(f"   Answer: {turn.summary}")
        for finding in turn.findings[:5]:
            lines.append(f"   Finding: {finding}")
        for result in turn.results[:6]:
            lines.append(f"   Computed: {result}")
    lines.append(
        "Earlier result ids cannot be cited or charted in this turn; recompute anything you need."
    )
    return "\n".join(lines)
