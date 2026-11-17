"""Check that SQL and pandas flag the same awards and score them the same.

Author: Neo Nguyen

The five tests exist twice: sql/03_audit_tests.sql and src/flags.py, each written from the same
definition. This script compares them award by award. For every test it counts the awards flagged
on each side, adds up their value, and counts awards flagged by one side only. It does the same for
the risk score and the top 100 of the review queue. Any difference stops the pipeline: it means one
of the two has a bug, and the numbers in the report cannot be trusted until it is found.
"""
from __future__ import annotations

import pandas as pd

from config import PROCESSED_DIR
from db import connect, query, read_awards
from flags import all_flags, risk_score

TOP_N = 100


def main():
    with connect() as con:
        a = read_awards(con)
        sql_flags = query(con, "SELECT owner_org || '|' || contract_key AS key, test_id FROM audit_flags")
        sql_scores = query(con, "SELECT owner_org || '|' || contract_key AS key, risk_score, risk_rank FROM risk_scores")

    a.index = a["owner_org"] + "|" + a["contract_key"]
    f = all_flags(a)
    value = a["original_value"]
    rows = []                                    # (check, sql value, python value, match)

    # ---- Flags, test by test -------------------------------------------------------------
    for test in ("T1", "T2", "T3", "T4", "T5"):
        in_sql = set(sql_flags.loc[sql_flags["test_id"] == test, "key"])
        in_py = set(f.index[f[test.lower()]])
        v_sql, v_py = value[list(in_sql)].sum(), value[list(in_py)].sum()
        rows += [
            (f"{test}: awards flagged", len(in_sql), len(in_py), len(in_sql) == len(in_py)),
            (f"{test}: awarded value flagged", round(v_sql, 2), round(v_py, 2), abs(v_sql - v_py) < 0.01),
            (f"{test}: flagged by one side only", len(in_sql - in_py), len(in_py - in_sql), in_sql == in_py),
        ]

    # ---- Risk score and the top of the review queue ----------------------------------------
    score = risk_score(f, value)["risk_score"]
    sql_score = sql_scores.set_index("key")["risk_score"].reindex(a.index)
    gap = (score - sql_score).abs().max()
    rows.append(("risk score: largest difference", 0.0, round(float(gap), 9), gap < 1e-9))
    top_sql = set(sql_scores.loc[sql_scores["risk_rank"] <= TOP_N, "key"])
    ranked = (pd.DataFrame({"score": score, "value": value, "org": a["owner_org"], "key": a["contract_key"]})
              .sort_values(["score", "value", "org", "key"], ascending=[False, False, True, True]))
    top_py = set(ranked.index[:TOP_N])
    rows.append((f"review queue: top {TOP_N} in common", TOP_N, len(top_sql & top_py), top_sql == top_py))

    out = pd.DataFrame(rows, columns=["check", "sql_value", "python_value", "match"])
    out.to_csv(PROCESSED_DIR / "reconciliation.csv", index=False)
    print(out.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
    if not out["match"].all():
        raise SystemExit("\nSQL and pandas DISAGREE: find the cause before using any number downstream")
    print(f"\nSQL and pandas agree on all {len(out)} checks")


if __name__ == "__main__":
    main()
