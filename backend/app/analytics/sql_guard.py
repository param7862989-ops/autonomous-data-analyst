"""Validation of model-written SQL before it reaches the analytical engine.

The check is an allowlist over the parsed syntax tree, not a text pattern:

* exactly one statement, and it must be a query (SELECT / UNION / INTERSECT / EXCEPT);
* the only table that can be referenced is ``data`` (plus CTEs defined in the query), never with
  a schema/catalog qualifier, and never a table function such as ``read_csv`` or ``glob``;
* table names are resolved per scope, so a CTE only counts where it is visible (a CTE cannot be
  used to smuggle a catalog table such as ``duckdb_tables`` into another part of the query);
* every function must be on an allowlist of pure analytical functions; functions that can
  multiply string sizes (REPLACE, REGEXP_REPLACE, LPAD, RPAD, REPEAT) are excluded, and
  concatenations are capped, because DuckDB's memory limit does not bound scalar string results;
* no DDL/DML, SET, PRAGMA, COPY, ATTACH, recursive CTEs, SELECT INTO or bind parameters.

The statement that runs is regenerated from the validated tree, so what was checked is what
executes. The engine sandbox is a second, independent layer.
"""

from __future__ import annotations

import sqlglot
from sqlglot import exp
from sqlglot.errors import OptimizeError, ParseError, TokenError
from sqlglot.optimizer.scope import traverse_scope

from app.analytics.engine import TABLE_NAME, AnalyticsError

MAX_SQL_LENGTH = 5_000
# Upper bound on string concatenations (|| and CONCAT arguments) in one query.
MAX_CONCATENATIONS = 20

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
        "CONCAT_WS", "STR_POSITION", "CONTAINS", "STARTS_WITH", "ENDS_WITH",
        "REGEXP_LIKE", "REGEXP_EXTRACT", "SPLIT_PART", "LEFT", "RIGHT", "INITCAP",
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

    concatenations = 0
    for node in tree.walk():
        if isinstance(node, _FORBIDDEN_NODES):
            raise SQLValidationError(
                f"{type(node).__name__.upper()} is not allowed; only read-only queries can run."
            )
        if isinstance(node, exp.Table):
            _check_table_shape(node)
        elif isinstance(node, exp.Func):
            name = _function_name(node)
            if name not in ALLOWED_FUNCTIONS:
                raise SQLValidationError(f"The function {name} is not allowed.")
            if name in {"CONCAT", "CONCAT_WS"}:
                concatenations += len(node.expressions) + 1
        if isinstance(node, exp.DPipe):
            concatenations += 1
    if concatenations > MAX_CONCATENATIONS:
        raise SQLValidationError(
            f"The query concatenates strings more than {MAX_CONCATENATIONS} times."
        )
    _check_table_scopes(tree)
    return tree.sql(dialect="duckdb")


def _check_table_shape(node: exp.Table) -> None:
    if not isinstance(node.this, exp.Identifier):
        raise SQLValidationError(
            f"Only the table '{TABLE_NAME}' can be queried; table functions are not allowed."
        )
    if node.args.get("db") or node.args.get("catalog"):
        raise SQLValidationError(
            f"Only the table '{TABLE_NAME}' can be queried, without a schema or database prefix."
        )


def _check_table_scopes(tree: exp.Expression) -> None:
    """Every table reference must be ``data`` or a CTE visible in its own scope."""
    try:
        scopes = traverse_scope(tree)
    except OptimizeError as exc:
        raise SQLValidationError("The query's table references could not be analysed.") from exc
    checked: set[int] = set()
    for scope in scopes:
        for table in scope.tables:
            checked.add(id(table))
            name = table.name
            if name in scope.cte_sources:
                continue
            if name.lower() != TABLE_NAME:
                raise SQLValidationError(
                    f"Only the table '{TABLE_NAME}' can be queried; '{name}' is not available."
                )
    # Fail closed: a table reference the scope analysis did not visit is not trusted.
    for table in tree.find_all(exp.Table):
        if id(table) not in checked:
            raise SQLValidationError("The query's table references could not be analysed.")
