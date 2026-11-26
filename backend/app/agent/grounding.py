"""Deterministic grounding check of a final answer against the computed results.

Checks that:
* every cited result id and chart id exists;
* every "fact" cites at least one result;
* every figure stated in the summary and findings matches a number in the computed results,
  allowing only for the rounding implied by how it is written (34.5% vs -0.34488, $63k vs
  63,359, $280,000 vs 280,355.87) and for ratios shown as percentages. Trailing zeros count as
  rounding down to two significant figures, so "$280,000" passes for 280,355.87 but "$281,000"
  and "$280,355.86" do not.

It is a heuristic, not a proof: it cannot tell whether a correct number is attributed to the
right thing, or whether words such as "rose" match the direction of a change. Years, dates,
quarter labels and small integers (likely counts or ordinals) are not checked, and neither are
digits inside a name that appears in the results ("Monitor 27in").
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from app.agent.schemas import FinalAnswer, GroundingReport, StoredResult
from app.analytics.charts import ChartSpec

_STRIP = [
    re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?\b"),  # dates / timestamps
    re.compile(r"\b\d{4}-(?:\d{2}|Q[1-4]|W\d{2})\b"),  # 2024-07, 2024-Q3, 2024-W05
    re.compile(r"\bQ[1-4]\b", re.IGNORECASE),
    re.compile(r"\b[rc]\d+\b"),  # result and chart ids
]
_NUMBER = re.compile(
    r"(?<![\w.])(?P<sign>[-\u2212])?(?P<currency>[$€£₹])?"
    r"(?P<int>\d{1,3}(?:,\d{3})+|\d+)(?P<dec>\.\d+)?"
    r"(?:\s?(?P<suffix>%|percent\b|k\b|K\b|M\b|B\b|bn\b|million\b|billion\b|thousand\b))?"
)
_MULTIPLIER = {
    "k": 1e3, "K": 1e3, "thousand": 1e3, "M": 1e6, "million": 1e6,
    "B": 1e9, "bn": 1e9, "billion": 1e9,
}  # fmt: skip
# Room for floating-point noise only, never for a wrong digit.
_FLOAT_NOISE = 1e-9


@dataclass(frozen=True)
class NumberToken:
    text: str
    value: float  # absolute value, scaled by any suffix
    rounding: float  # half a unit in the last significant written digit, scaled
    percent: bool


def names_with_digits(results: list[StoredResult]) -> list[str]:
    """Text cells that are names containing digits, longest first.

    They must start with a letter, so a cell such as "5,000,000" or "$5M" cannot be used to
    get a figure past the check.
    """
    names = {
        value
        for result in results
        for row in result.table.rows
        for value in row
        if isinstance(value, str) and value[:1].isalpha() and any(c.isdigit() for c in value)
    }
    return sorted(names, key=lambda name: (-len(name), name))


def extract_numbers(text: str, names: list[str] | None = None) -> list[NumberToken]:
    for name in names or []:
        text = re.sub(rf"(?<!\w){re.escape(name)}(?!\w)", " ", text)
    for pattern in _STRIP:
        text = pattern.sub(" ", text)
    tokens: list[NumberToken] = []
    for match in _NUMBER.finditer(text):
        integer, decimals = match["int"], match["dec"] or ""
        suffix = match["suffix"] or ""
        percent = suffix in {"%", "percent"}
        multiplier = _MULTIPLIER.get(suffix, 1.0)
        value = float(integer.replace(",", "") + decimals) * multiplier
        plain = not (decimals or suffix or match["currency"])
        if plain and (value <= 10 or (1900 <= value <= 2100 and "," not in integer)):
            continue  # counts, ordinals and years are not checked
        rounding = 0.5 * 10 ** (-_places(integer, decimals)) * multiplier
        tokens.append(NumberToken(match.group(0).strip(), value, rounding, percent))
    return tokens


def _places(integer: str, decimals: str) -> int:
    """Decimal places of the last significant written digit (negative for tens, hundreds...).

    "280,000" may be 280,355 rounded to the thousand, but "30" is not 34 rounded to the ten:
    trailing zeros count as rounding only while two significant figures remain.
    """
    if decimals:
        return len(decimals) - 1
    digits = integer.replace(",", "")
    zeros = len(digits) - len(digits.rstrip("0"))
    return -min(zeros, max(len(digits) - 2, 0))


def _candidates(results: list[StoredResult]) -> tuple[list[float], list[float]]:
    """(plain values, percent forms of ratios) from every numeric cell and summary value."""
    plain: list[float] = []
    for result in results:
        values = [v for row in result.table.rows for v in row]
        values += list(result.summary.values())
        for value in values:
            if isinstance(value, bool) or not isinstance(value, int | float):
                continue
            if math.isfinite(value):
                plain.append(abs(float(value)))
    ratios = [v * 100 for v in plain if v <= 10]
    return plain, ratios


def _matches(token: NumberToken, plain: list[float], ratios: list[float]) -> bool:
    pools = [ratios, plain] if token.percent else [plain]
    for pool in pools:
        for candidate in pool:
            tolerance = token.rounding + _FLOAT_NOISE * max(candidate, 1.0)
            if abs(token.value - candidate) <= tolerance:
                return True
    return False


def check_answer(
    answer: FinalAnswer, results: list[StoredResult], charts: list[ChartSpec]
) -> GroundingReport:
    report = GroundingReport()
    known_results = {r.id for r in results}
    known_charts = {c.id for c in charts}
    plain, ratios = _candidates(results)

    for chart_id in answer.chart_ids:
        if chart_id not in known_charts:
            report.invalid_references.append(chart_id)

    statements = [answer.summary]
    for finding in answer.findings:
        statements.append(finding.statement)
        bad = [e for e in finding.evidence if e not in known_results]
        report.invalid_references.extend(bad)
        if finding.kind == "fact" and not [e for e in finding.evidence if e in known_results]:
            report.unsupported_facts.append(finding.statement)

    names = names_with_digits(results)
    for statement in statements:
        for token in extract_numbers(statement, names):
            report.checked_numbers += 1
            if not _matches(token, plain, ratios):
                report.unverified_numbers.append(token.text)
    report.invalid_references = sorted(set(report.invalid_references))
    return report


def feedback_for(report: GroundingReport) -> str:
    lines = []
    if report.unverified_numbers:
        lines.append(
            "These figures do not match any computed result: "
            + ", ".join(report.unverified_numbers)
            + ". Use only numbers from the results (or compute them with a tool next time)."
        )
    if report.invalid_references:
        lines.append("These ids do not exist: " + ", ".join(report.invalid_references) + ".")
    if report.unsupported_facts:
        lines.append(
            "These facts cite no result; cite the result ids or label them hypotheses: "
            + " | ".join(report.unsupported_facts)
        )
    return "\n".join(lines)
