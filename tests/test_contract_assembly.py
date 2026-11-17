"""Tests for how sql/02_views.sql joins an award to its amendments. Author: Neo Nguyen

These run the real SQL on a few hand-made rows, in a separate database (procurement_audit_test), so
the analysis database is never touched. They are skipped when PostgreSQL is not running.
"""
import os
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[1]
TEST_DSN = os.environ.get("PROCUREMENT_TEST_PG_DSN", "host=localhost port=5432 dbname=procurement_audit_test")
PARAMS = {"load_start": "2017-04-01", "analysis_start": "2019-06-10",
          "s6b_limit_G": "25000", "s6b_limit_S": "40000", "s6b_limit_C": "40000"}

# (contract, reference number, row type, date, total value, original value, reporting period)
ROWS = [
    # X: amended three times, twice in the same quarter; the higher total of those two is current
    ("X", "X-1", "C", "2021-05-03", 30_000, 30_000, "2021-2022-Q1"),
    ("X", "X-2", "A", "2021-05-03", 45_000, 30_000, "2021-2022-Q2"),
    ("X", "X-4", "A", "2021-05-03", 60_000, 30_000, "2021-2022-Q3"),
    ("X", "X-5", "A", "2021-05-03", 50_000, 30_000, "2021-2022-Q3"),
    # Y: a $0 award and a second 'C' row under the same number on the same day; the second is not its value
    ("Y", "Y-1", "C", "2021-06-01", 0, 0, "2021-2022-Q1"),
    ("Y", "Y-2", "C", "2021-06-01", 90_000_000, 90_000_000, "2021-2022-Q1"),
    # Z: amended in the same quarter it was awarded; the amendment is the current value
    ("Z", "Z-2", "C", "2021-07-05", 20_000, 20_000, "2021-2022-Q2"),
    ("Z", "Z-1", "A", "2021-07-05", 35_000, 20_000, "2021-2022-Q2"),
    # W: sole-sourced at $39,000, then amended to $41,000
    ("W", "W-1", "C", "2021-08-09", 39_000, 39_000, "2021-2022-Q2"),
    ("W", "W-2", "A", "2021-08-09", 41_000, 39_000, "2021-2022-Q3"),
    # V: one amendment filed twice, word for word, under two reference numbers
    ("V", "V-1", "C", "2021-09-01", 50_000, 50_000, "2021-2022-Q2"),
    ("V", "V-2", "A", "2021-09-01", 60_000, 50_000, "2021-2022-Q3"),
    ("V", "V-3", "A", "2021-09-01", 60_000, 50_000, "2021-2022-Q3"),
]


@pytest.fixture(scope="module")
def con():
    params = conninfo_to_dict(TEST_DSN)
    try:
        with psycopg.connect(**{**params, "dbname": "postgres"}, autocommit=True, connect_timeout=3) as admin:
            if not admin.execute("SELECT 1 FROM pg_database WHERE datname = %s", [params["dbname"]]).fetchone():
                admin.execute(f'CREATE DATABASE "{params["dbname"]}"')
        c = psycopg.connect(TEST_DSN, options="-c search_path=procurement", connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL is not running")

    # Build the schema, load the hand-made rows, then build contracts and awards from them
    c.execute((ROOT / "sql" / "01_tables.sql").read_text())
    c.execute("INSERT INTO departments VALUES ('dept', 'A department', 'Un ministere')")
    c.execute("INSERT INTO vendors VALUES (1, 'ACME', 'Acme Inc.', 1, 1, 10)")
    cur = c.cursor()
    cur.executemany("INSERT INTO params VALUES (%s, %s)", list(PARAMS.items()))
    cur.executemany("""
        INSERT INTO contract_reports (owner_org, reference_number, procurement_id, vendor_id, vendor_name_raw,
                                      contract_date, contract_value, original_value, instrument_type,
                                      commodity_type, solicitation_procedure, reporting_period, fiscal_year, fiscal_quarter)
        VALUES ('dept', %s, %s, 1, 'Acme Inc.', %s, %s, %s, %s, 'S', 'TN', %s, '2021-2022', 'Q1')""",
        [(ref, key, date, value, original, kind, period) for key, ref, kind, date, value, original, period in ROWS])
    c.execute((ROOT / "sql" / "02_views.sql").read_text())
    yield c
    c.rollback()                                  # nothing is kept in the test database
    c.close()


def contract(con, key):
    return con.execute("SELECT original_value, final_value, n_amendments FROM contracts WHERE contract_key = %s",
                       [key]).fetchone()


def test_the_higher_total_wins_when_two_amendments_share_the_latest_quarter(con):
    assert contract(con, "X") == (30_000, 60_000, 3)


def test_a_second_award_row_under_the_same_number_does_not_set_the_value(con):
    assert contract(con, "Y") == (0, 0, 0)


def test_an_amendment_beats_the_award_row_in_the_same_quarter(con):
    assert contract(con, "Z") == (20_000, 35_000, 1)


def test_amended_past_limit_needs_a_positive_award_and_an_amendment(con):
    keys = {k for (k,) in con.execute("SELECT contract_key FROM vw_amended_past_limit")}
    assert keys == {"X", "W"}


def test_an_amendment_filed_twice_word_for_word_counts_once(con):
    assert contract(con, "V") == (50_000, 60_000, 1)
