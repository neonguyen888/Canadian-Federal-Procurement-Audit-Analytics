"""PostgreSQL helpers shared by run_sql.py and the analysis scripts.

Author: Neo Nguyen

Connection settings come from config.PG_DSN (override with PROCUREMENT_PG_DSN). Everything lives in
the `procurement` schema. The CSV loader uses COPY, which loads the 800,000 contract rows in about 20 seconds; row-by-row
inserts would take many minutes.
"""
from __future__ import annotations

import io

import pandas as pd
import psycopg
from psycopg.conninfo import conninfo_to_dict

from config import PG_DSN, PG_SCHEMA

# PostgreSQL type ids, used to give query results the right pandas types
INT_TYPES = {20, 21, 23}          # bigint, smallint, integer
NUMERIC, DATE, BOOL = 1700, 1082, 16


def ensure_database() -> None:
    """Create the database on first run, so the pipeline needs nothing but a running server."""
    params = conninfo_to_dict(PG_DSN)
    name = params.get("dbname", "procurement_audit")
    try:
        with psycopg.connect(**{**params, "dbname": "postgres"}, autocommit=True) as con:
            if not con.execute("SELECT 1 FROM pg_database WHERE datname = %s", [name]).fetchone():
                con.execute(f'CREATE DATABASE "{name}"')
    except psycopg.OperationalError as e:
        raise SystemExit(f"Can't reach PostgreSQL ({PG_DSN}). Start Postgres.app, or set PROCUREMENT_PG_DSN, "
                         f"and run again.\n{e}") from None


def connect() -> psycopg.Connection:
    return psycopg.connect(PG_DSN, options=f"-c search_path={PG_SCHEMA}")


def query(con: psycopg.Connection, sql: str, params=None) -> pd.DataFrame:
    """Run a SELECT and return a DataFrame: dates as datetime64, numeric as float, integers as Int64."""
    cur = con.execute(sql, params)
    df = pd.DataFrame(cur.fetchall(), columns=[d.name for d in cur.description])
    for d in cur.description:
        if d.type_code == NUMERIC:
            df[d.name] = df[d.name].astype(float)
        elif d.type_code == DATE:
            df[d.name] = pd.to_datetime(df[d.name])
        elif d.type_code in INT_TYPES:
            df[d.name] = df[d.name].astype("Int64")
    return df


def load_csv(con: psycopg.Connection, table: str, path) -> int:
    """COPY a CSV into a table. Only the table's own columns are loaded, matched by name."""
    cols = con.execute(
        "SELECT column_name, data_type FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position", [PG_SCHEMA, table]).fetchall()
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [c for c, _ in cols if c not in df.columns]
    if missing:
        raise ValueError(f"{path.name} has no column(s) {missing} for table {table}")
    df = df[[c for c, _ in cols]]
    for c, t in cols:
        # pandas writes whole numbers with gaps as "3.0"; integer columns need "3"
        if t in ("integer", "bigint", "smallint"):
            df[c] = df[c].map(lambda s: s if s == "" else str(int(float(s))))
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False)
    with con.cursor().copy(f"COPY {table} ({', '.join(c for c, _ in cols)}) FROM STDIN WITH (FORMAT csv)") as cp:
        cp.write(buf.getvalue())
    return len(df)


def read_awards(con: psycopg.Connection) -> pd.DataFrame:
    """Every award in the analysis window, with the columns the pandas tests and the charts need."""
    return query(con, """
        SELECT owner_org, contract_key, vendor_id, department, vendor, commodity_type, award_date,
               fiscal_year, fiscal_quarter, original_value, final_value, n_amendments, growth_ratio,
               is_competitive, s6b_limit, is_within_limit, contracting_entity, standing_offer_number
        FROM awards
        ORDER BY owner_org, contract_key COLLATE "C"
    """)
