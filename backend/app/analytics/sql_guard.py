"""Validation of model-written SQL before it reaches the analytical engine.

The check is an allowlist over the parsed syntax tree, not a text pattern:

* exactly one statement, and it must be a query (SELECT / UNION / INTERSECT / EXCEPT);
* the only table that can be referenced is ``data`` (plus CTEs defined in the query), never with
  a schema/catalog qualifier, and never a table function such as ``read_csv`` or ``glob``;
* every function must be on an allowlist of pure analytical functions;
* no DDL/DML, SET, PRAGMA, COPY, ATTACH, recursive CTEs, SELECT INTO or bind parameters.

The statement that runs is regenerated from the validated tree, so what was checked is what
executes. The engine sandbox is a second, independent layer.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from app.analytics.engine import TABLE_NAME, AnalyticsError

MAX_SQL_LENGTH = 5_000

ALLOWED_FUNCTIONS = frozenset(
    {
        # Aggregates
        "SUM", "AVG", "COUNT", "COUNT_IF", "MIN", "MAX", "MEDIAN", "MODE",
        "STDDEV", "STDDEV_SAMP", "STDDEV_POP", "VARIANCE", "VARIANCE_POP",
        "PERCENTILE_CONT", "PERCENTILE_DISC", "APPROX_QUANTILE", "APPROX_DISTINCT",
        "CORR", "COVAR_POP", "COVAR_SAMP", "ANY_VALUE", "ARG_MAX", "ARG_MIN", "FIRST", "LAST",
        "GROUP_CONCAT", "ARRAY_AGG", "LOGICAL_AND", "LOGICAL_OR", "KURTOSIS", "SKEWNESS",
        "REGR_SLOPE", "REGR_INTERCEPT", "REGR_R2",
        # Window functions
        "ROW_NUMBER", "RANK", "DENSE_RANK", "PERCENT_RANK", "CUME_DIST", "NTILE",
        "LAG", "LEAD", "FIRST_VALUE", "LAST_VALUE", "NTH_VALUE",
        # Dates and times
        "TIMESTAMP_TRUNC", "DATE_TRUNC", "DATETRUNC", "EXTRACT", "DATE_PART", "YEAR", "QUARTER",
        "MONTH", "WEEK", "WEEK_OF_YEAR", "DAY", "DAY_OF_WEEK", "DAY_OF_WEEK_ISO",
        "DAY_OF_MONTH", "DAY_OF_YEAR", "HOUR", "MINUTE", "SECOND", "MONTHNAME", "DAYNAME",
        "TIME_TO_STR", "STR_TO_TIME", "STR_TO_DATE", "DATEDIFF", "DATE_DIFF", "DATE_ADD",
        "DATE_SUB", "DATE_FROM_PARTS", "LAST_DAY", "CURRENT_DATE", "CURRENT_TIMESTAMP", "NOW",
        "TIME_TO_UNIX", "TS_OR_DS_TO_DATE", "DATE", "AGE",
        # Numbers
        "ABS", "ROUND", "FLOOR", "CEIL", "SQRT", "POW", "POWER", "LN", "LOG", "LOG2", "LOG10",
        "EXP", "SIGN", "GREATEST", "LEAST", "IS_NAN", "IS_INF", "MOD",
        # Conditionals and casts
        "CASE", "IF", "COALESCE", "NULLIF", "IFNULL", "CAST", "TRY_CAST",
        # Text
        "LOWER", "UPPER", "TRIM", "LTRIM", "RTRIM", "LENGTH", "SUBSTRING", "CONCAT",
        "CONCAT_WS", "REPLACE", "STR_POSITION", "CONTAINS", "STARTS_WITH", "ENDS_WITH",
        "REGEXP_LIKE", "REGEXP_EXTRACT", "REGEXP_REPLACE", "SPLIT_PART", "LEFT", "RIGHT",
        "LPAD", "RPAD", "INITCAP",
        # Operators and literals that sqlglot represents as function nodes
        "AND", "OR", "EXISTS", "ARRAY", "STRUCT",
        # Column selection helper (SELECT COLUMNS('pattern'))
        "COLUMNS",
    }
)  # fmt: skip

_QUERY_ROOTS = (exp.Select, exp.Union, exp.Intersect, exp.Except)
_FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = (
    exp.Insert,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Create,
    exp.Drop,
    exp.Alter,
    exp.Command,
    exp.Pragma,
    exp.Set,
    exp.Copy,
    exp.Attach,
    exp.Detach,
    exp.Use,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
    exp.Into,
    exp.Placeholder,
    exp.Parameter,
    exp.LoadData,
    exp.Describe,
    exp.Show,
)


class SQLValidationError(AnalyticsError):
    def __init__(self, message: str) -> None:
        super().__init__(message, code="sql_rejected")


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).upper()
    return node.sql_name().upper()


def _cte_names(tree: exp.Expression) -> set[str]:
    names: set[str] = set()
    for cte in tree.find_all(exp.CTE):
        alias = cte.alias
        if alias:
            names.add(alias.lower())
    return names


def validate_sql(sql: str) -> str:
    """Return the normalized SQL to execute, or raise ``SQLValidationError``."""
    text = sql.strip().rstrip(";").strip()
    if not text:
        raise SQLValidationError("The query is empty.")
    if len(text) > MAX_SQL_LENGTH:
        raise SQLValidationError(f"The query is longer than {MAX_SQL_LENGTH} characters.")
    try:
        statements = [s for s in sqlglot.parse(text, dialect="duckdb") if s is not None]
    except (ParseError, TokenError) as exc:
        raise SQLValidationError("The query could not be parsed as SQL.") from exc
    if len(statements) != 1:
        raise SQLValidationError("Exactly one SQL statement is allowed.")
    tree = statements[0]
    if not isinstance(tree, _QUERY_ROOTS):
        raise SQLValidationError("Only SELECT queries are allowed.")

    for with_clause in tree.find_all(exp.With):
        if with_clause.args.get("recursive"):
            raise SQLValidationError("Recursive queries are not allowed.")

    allowed_tables = {TABLE_NAME} | _cte_names(tree)
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SQLValidationError(
                f"{type(node).__name__.upper()} is not allowed; only read-only queries can run."
            )
        if isinstance(node, exp.Table):
            _check_table(node, allowed_tables)
        elif isinstance(node, exp.Func):
            name = _function_name(node)
            if name not in ALLOWED_FUNCTIONS:
                raise SQLValidationError(f"The function {name} is not allowed.")
    return tree.sql(dialect="duckdb")


def _check_table(node: exp.Table, allowed_tables: set[str]) -> None:
    if not isinstance(node.this, exp.Identifier):
        raise SQLValidationError(
            f"Only the table '{TABLE_NAME}' can be queried; table functions are not allowed."
        )
    if node.args.get("db") or node.args.get("catalog"):
        raise SQLValidationError(
            f"Only the table '{TABLE_NAME}' can be queried, without a schema or database prefix."
        )
    if node.name.lower() not in allowed_tables:
        raise SQLValidationError(
            f"Only the table '{TABLE_NAME}' can be queried; '{node.name}' is not available."
        )
