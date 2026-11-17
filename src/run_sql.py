"""Build the PostgreSQL schema, load the cleaned data, run the checks, and print the first summaries.

Author: Neo Nguyen

The SQL files are plain text so they can also be run by hand in psql. This script runs them in
order inside one transaction: create tables, load the CSVs from data/processed, write the config
settings into params, create views, run the checks. If a hard check fails, the transaction is
rolled back and the database keeps its last good version.
"""
from __future__ import annotations

import re

import config
from db import connect, ensure_database, load_csv, query

# Table <- CSV written by clean.py. Order matters: contract_reports points at the two lookups.
LOADS = {
    "departments": "departments.csv",
    "vendors": "vendors.csv",
    "vendor_aliases": "vendor_aliases.csv",
    "contract_reports": "contract_reports.csv",
    "dq_python": "dq_python.csv",
}

# Settings the views and checks read, so SQL never repeats a number from config.py
PARAMS = {
    "load_start": config.LOAD_START,
    "analysis_start": config.ANALYSIS_START,
    "s6b_limit_G": config.S6B_LIMIT["G"],
    "s6b_limit_S": config.S6B_LIMIT["S"],
    "s6b_limit_C": config.S6B_LIMIT["C"],
    "near_limit_band": config.NEAR_LIMIT_BAND,
    "split_window_days": config.SPLIT_WINDOW_DAYS,
    "amendment_growth_flag": config.AMENDMENT_GROWTH_FLAG,
    "amendment_count_flag": config.AMENDMENT_COUNT_FLAG,
    "min_original_for_growth": config.MIN_ORIGINAL_FOR_GROWTH,
    "duplicate_window_days": config.DUPLICATE_WINDOW_DAYS,
    "concentration_share": config.CONCENTRATION_SHARE,
    "concentration_min_spend": config.CONCENTRATION_MIN_SPEND,
    **{f"weight_{test}": weight for test, weight in config.RISK_WEIGHTS.items()},
}

SQL_FILES = ["01_tables.sql", "02_views.sql", "03_audit_tests.sql", "05_tableau_views.sql"]
CHECKS_FILE = "04_checks.sql"


def missing_params(sql_text: str, params: dict) -> set[str]:
    """Settings the SQL reads with param('name') that PARAMS does not write. A missing one would read
    as NULL inside the views, and a test would quietly flag nothing."""
    return set(re.findall(r"param\(\s*'(\w+)'\s*\)", sql_text)) - set(params)


def main():
    ensure_database()
    sql = lambda f: (config.ROOT / "sql" / f).read_text()
    missing = missing_params("\n".join(sql(f) for f in SQL_FILES + [CHECKS_FILE]), PARAMS)
    if missing:
        raise SystemExit(f"Settings read by the SQL but not written from config.py: {sorted(missing)}")
    with connect() as con:                       # one transaction: commit on success, roll back on error
        con.execute(sql("01_tables.sql"))
        for table, csv in LOADS.items():
            n = load_csv(con, table, config.PROCESSED_DIR / csv)
            print(f"  loaded {n:>9,} rows into {table}")
        con.cursor().executemany("INSERT INTO params (name, value) VALUES (%s, %s)",
                                 [(k, str(v)) for k, v in PARAMS.items()])
        for f in SQL_FILES[1:]:
            con.execute(sql(f))

        checks = query(con, sql(CHECKS_FILE))
        checks["passed"] = checks["actual"] == checks["expected"]
        checks.to_csv(config.PROCESSED_DIR / "sql_checks.csv", index=False)     # the report lists these
        print()
        print(checks.to_string(index=False))
        failed = checks[(checks["severity"] == "hard") & ~checks["passed"]]
        if len(failed):
            raise SystemExit(f"\n{len(failed)} hard check(s) FAILED: rebuild rolled back")

        print()
        print(query(con, "SELECT * FROM vw_spend_by_fiscal_year").to_string(index=False))
        print()
        print(query(con, "SELECT * FROM vw_test_summary").to_string(index=False))


if __name__ == "__main__":
    main()
