from __future__ import annotations

import pytest

from app.analytics.sql_guard import MAX_SQL_LENGTH, SQLValidationError, validate_sql

ALLOWED = [
    "SELECT * FROM data",
    "SELECT region, SUM(revenue) AS total FROM data GROUP BY region ORDER BY total DESC LIMIT 5",
    "select count(*) from data where revenue > 100 and region in ('West', 'East')",
    "SELECT DATE_TRUNC('quarter', order_date) AS q, SUM(revenue) FROM data GROUP BY 1 ORDER BY 1",
    "SELECT STRFTIME(order_date, '%Y-%m') AS m, AVG(units) FROM data GROUP BY m",
    "SELECT YEAR(order_date), QUARTER(order_date), EXTRACT(month FROM order_date) FROM data",
    "WITH q AS (SELECT region, SUM(revenue) r FROM data GROUP BY region) "
    "SELECT region, r, r / SUM(r) OVER () AS share FROM q",
    "SELECT product, RANK() OVER (ORDER BY SUM(revenue) DESC) FROM data GROUP BY product",
    "SELECT region, LAG(SUM(revenue)) OVER (PARTITION BY region ORDER BY MIN(order_date)) "
    "FROM data GROUP BY region",
    "SELECT CASE WHEN revenue > 1000 THEN 'big' ELSE 'small' END AS size, COUNT(*) "
    "FROM data GROUP BY size",
    "SELECT COALESCE(sales_channel, 'unknown'), ROUND(AVG(discount), 3) FROM data GROUP BY 1",
    "SELECT CORR(units, revenue), MEDIAN(revenue), QUANTILE_CONT(revenue, 0.9) FROM data",
    "SELECT region FROM data WHERE product = 'Laptop Pro' UNION SELECT region FROM data",
    "SELECT * FROM (SELECT region, revenue FROM data) AS sub WHERE revenue > 10",
    "SELECT LOWER(region), LENGTH(product), CAST(units AS DOUBLE) FROM data",
    "SELECT * FROM data;",
    "SELECT 'DROP TABLE data' AS harmless_text FROM data",
    "SELECT COUNT(*) FILTER (WHERE region = 'West') FROM data",
]

REJECTED = {
    "empty": "",
    "two statements": "SELECT 1 FROM data; SELECT 2 FROM data",
    "drop": "DROP TABLE data",
    "delete": "DELETE FROM data",
    "update": "UPDATE data SET revenue = 0",
    "insert": "INSERT INTO data VALUES (1)",
    "create": "CREATE TABLE x AS SELECT * FROM data",
    "piggyback": "SELECT * FROM data; DROP TABLE data",
    "copy": "COPY data TO '/tmp/out.csv'",
    "attach": "ATTACH '/tmp/other.db'",
    "install": "INSTALL httpfs",
    "load": "LOAD httpfs",
    "set": "SET enable_external_access = true",
    "pragma": "PRAGMA database_list",
    "call": "CALL pragma_version()",
    "export": "EXPORT DATABASE '/tmp/x'",
    "read_csv": "SELECT * FROM read_csv('/etc/passwd')",
    "read_csv_auto": "SELECT * FROM read_csv_auto('/etc/passwd')",
    "read_parquet": "SELECT * FROM read_parquet('/srv/storage/datasets/x.parquet')",
    "read_text": "SELECT read_text('/etc/passwd')",
    "file as table": "SELECT * FROM '/etc/passwd'",
    "glob": "SELECT * FROM glob('/srv/*')",
    "range": "SELECT * FROM range(1000000000)",
    "duckdb_settings": "SELECT * FROM duckdb_settings()",
    "duckdb_tables": "SELECT * FROM duckdb_tables()",
    "information_schema": "SELECT * FROM information_schema.tables",
    "qualified data": "SELECT * FROM main.data",
    "catalog qualified": "SELECT * FROM memory.main.data",
    "other table": "SELECT * FROM users",
    "join other table": "SELECT * FROM data JOIN sessions ON true",
    "subquery other table": "SELECT * FROM data WHERE region IN (SELECT email FROM users)",
    "getenv": "SELECT getenv('HOME') FROM data",
    "current_setting": "SELECT current_setting('home_directory')",
    "pragma function": "SELECT * FROM pragma_database_list()",
    "query function": "SELECT * FROM query('SELECT 1')",
    "query_table": "SELECT * FROM query_table('data')",
    "recursive cte": "WITH RECURSIVE t(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM t) "
    "SELECT * FROM t",
    "select into": "SELECT * INTO new_table FROM data",
    "parameter": "SELECT * FROM data WHERE region = ?",
    "summarize": "SUMMARIZE data",
    "describe": "DESCRIBE data",
    "pivot": "PIVOT data ON region USING SUM(revenue)",
    "unparseable": "SELECT FROM WHERE ((",
    "comment smuggling": "SELECT * FROM data /* ; */ ; DROP TABLE data",
}


@pytest.mark.parametrize("sql", ALLOWED)
def test_allowed_queries(sql: str) -> None:
    normalized = validate_sql(sql)
    assert normalized
    assert ";" not in normalized.rstrip(";")[-1:]


@pytest.mark.parametrize(("name", "sql"), list(REJECTED.items()), ids=list(REJECTED))
def test_rejected_queries(name: str, sql: str) -> None:
    with pytest.raises(SQLValidationError):
        validate_sql(sql)


def test_overlong_query_rejected() -> None:
    sql = "SELECT " + ", ".join(["revenue"] * MAX_SQL_LENGTH) + " FROM data"
    with pytest.raises(SQLValidationError, match="longer than"):
        validate_sql(sql)


def test_cte_names_do_not_open_other_tables() -> None:
    # A CTE can be referenced, but naming one after a real table does not grant access to it:
    # the CTE body itself may only read `data`.
    validate_sql("WITH users AS (SELECT * FROM data) SELECT * FROM users")
    with pytest.raises(SQLValidationError):
        validate_sql("WITH x AS (SELECT * FROM users) SELECT * FROM x")


def test_rejection_messages_explain_the_rule() -> None:
    with pytest.raises(SQLValidationError) as excinfo:
        validate_sql("SELECT * FROM read_csv('x')")
    assert "table functions" in excinfo.value.message
    with pytest.raises(SQLValidationError) as excinfo:
        validate_sql("SELECT getenv('x') FROM data")
    assert "GETENV" in excinfo.value.message
