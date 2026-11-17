"""Collect every number the report quotes into one file.

Author: Neo Nguyen

README.md and reports/report.md only use figures that appear in data/processed/results.json, so a
number in the text can always be traced to the run that produced it. This script reads the database
and the CSVs the analysis scripts wrote; it computes nothing new beyond counts and shares.
"""
from __future__ import annotations

import json

import pandas as pd

import config
from db import connect, query

P = config.PROCESSED_DIR


def records(df: pd.DataFrame) -> list[dict]:
    return json.loads(df.to_json(orient="records", date_format="iso"))


def main():
    with connect() as con:
        window = query(con, """
            SELECT count(*) AS n_awards, count(DISTINCT owner_org) AS n_departments,
                   count(DISTINCT vendor_id) AS n_vendors, sum(original_value) AS awarded_value,
                   sum(final_value) AS current_value, min(award_date) AS first_award, max(award_date) AS last_award,
                   100.0 * count(*) FILTER (WHERE NOT is_competitive) / count(*) AS pct_non_competitive,
                   count(*) FILTER (WHERE n_amendments > 0) AS n_amended
            FROM awards""")
        flagged = query(con, """
            SELECT count(*) FILTER (WHERE n_flags > 0) AS n_flagged,
                   100.0 * count(*) FILTER (WHERE n_flags > 0) / count(*) AS pct_flagged,
                   count(*) FILTER (WHERE n_flags >= 2) AS n_with_two_or_more,
                   sum(original_value) FILTER (WHERE n_flags > 0) AS awarded_value_flagged
            FROM vw_award_flags""")
        counts = query(con, """
            SELECT (SELECT count(*) FROM contract_reports) AS n_report_rows,
                   (SELECT count(*) FROM contracts) AS n_contracts,
                   (SELECT count(*) FROM vendors) AS n_vendors_all,
                   (SELECT count(*) FROM departments) AS n_departments_all""")
        # Sole-sourced within the limit, then amended past it (rule in sql/02_views.sql), and the
        # s.6 exception each one recorded: '2' is the dollar limit itself
        past_limit = query(con, """
            SELECT count(*) AS n_awards, sum(original_value) AS awarded_value, sum(final_value) AS current_value,
                   count(*) FILTER (WHERE final_value > 2 * s6b_limit) AS n_over_double_the_limit,
                   count(*) FILTER (WHERE article_6_exceptions = '2') AS n_citing_the_dollar_limit,
                   count(*) FILTER (WHERE standing_offer_number IS NOT NULL) AS n_standing_offer_call_ups,
                   (SELECT count(*) FROM awards WHERE NOT is_competitive AND is_within_limit AND original_value > 0)
                       AS n_sole_source_within_limit
            FROM vw_amended_past_limit""")
        # Service awards around the $40,000 limit: who gets them, and how sharp the pile-up is
        # (w = the bunching window, b = one bin, both from config.py)
        near_limit = query(con, """
            WITH s AS (SELECT original_value - s6b_limit AS d, is_competitive FROM awards WHERE commodity_type = 'S')
            SELECT 100.0 * count(*) FILTER (WHERE NOT is_competitive AND d > -%(w)s AND d <= 0)
                         / count(*) FILTER (WHERE d > -%(w)s AND d <= 0)       AS pct_non_competitive_last_5000,
                   100.0 * count(*) FILTER (WHERE NOT is_competitive AND d > 0 AND d <= %(w)s)
                         / count(*) FILTER (WHERE d > 0 AND d <= %(w)s)        AS pct_non_competitive_next_5000,
                   count(*) FILTER (WHERE d > -%(b)s AND d <= 0)               AS n_last_1000,
                   count(*) FILTER (WHERE d > -%(w)s AND d <= -%(b)s)::numeric
                       / ((%(w)s - %(b)s) / %(b)s)                             AS n_per_1000_before_that,
                   count(*) FILTER (WHERE d = 0)                               AS n_exactly_at_limit
            FROM s""", {"w": config.BUNCH_WINDOW, "b": config.BUNCH_BIN_WIDTH})
        # Non-competitive awards priced exactly at their limit: within it, because the rule says "does not exceed"
        at_limit = query(con, "SELECT count(*) AS n FROM awards WHERE NOT is_competitive AND original_value = s6b_limit")["n"].iloc[0]
        # Non-competitive awards with no s.6 exception, by fiscal year. The field is optional in the
        # publication standard, so the early years mostly show a field nobody filled in.
        no_reason = query(con, """
            SELECT fiscal_year, count(*) AS n_non_competitive,
                   count(*) FILTER (WHERE coalesce(article_6_exceptions, '0') IN ('0', '?')) AS n_no_s6_exception,
                   count(*) FILTER (WHERE coalesce(article_6_exceptions, '0') IN ('0', '?')
                                      AND coalesce(limited_tendering_reason, '00') NOT IN ('', '00')) AS n_with_other_reason
            FROM awards WHERE solicitation_procedure = 'TN'
            GROUP BY fiscal_year ORDER BY fiscal_year""")
        no_reason["pct_no_s6_exception"] = (100 * no_reason["n_no_s6_exception"] / no_reason["n_non_competitive"]).round(1)
        # Every row CBSA filed for the first ArriveCAN contract the audit names (paragraph 1.38)
        first_contract_rows = query(con, """
            SELECT reference_number, instrument_type, solicitation_procedure, limited_tendering_reason,
                   contract_value, reporting_period
            FROM contract_reports
            WHERE (owner_org, procurement_id) IN (SELECT owner_org, procurement_id FROM awards
                                                  WHERE owner_org = %(owner_org)s AND award_date = %(award_date)s
                                                    AND original_value = %(original_value)s)
            ORDER BY reporting_period, reference_number COLLATE "C"
        """, config.AUDIT_FIRST_CONTRACT)
        # T3 flags where the award row itself already reports a total above its original value
        t3_without_amendment = query(con, """
            SELECT count(*) AS n FROM audit_flags f JOIN awards a USING (owner_org, contract_key)
            WHERE f.test_id = 'T3' AND a.n_amendments = 0""")["n"].iloc[0]
        tests = query(con, "SELECT * FROM vw_test_summary")
        years = query(con, "SELECT * FROM vw_spend_by_fiscal_year")
        # The head of the review queue, without vendor names: the report shows what the top of the
        # queue looks like. The names stay in the risk_scores and audit_flags tables for the reviewer.
        queue = query(con, """
            SELECT r.risk_rank, f.department, f.commodity_type, f.fiscal_year, f.original_value, f.final_value,
                   f.n_amendments, f.n_flags, r.flag_points, round(r.risk_score::numeric, 1) AS risk_score
            FROM risk_scores r JOIN vw_award_flags f USING (owner_org, contract_key)
            WHERE r.risk_rank <= 10 ORDER BY r.risk_rank""")

    dq = pd.read_csv(P / "dq_python.csv").set_index("check_name")["value"]
    checks = pd.read_csv(P / "sql_checks.csv")
    reconciliation = pd.read_csv(P / "reconciliation.csv")
    case = pd.read_csv(P / "case_study_contracts.csv")
    by_department = pd.read_csv(P / "bunching_by_department.csv")
    services = by_department[by_department["commodity_type"] == "S"]

    results = {
        "source": json.loads((P / "source_metadata.json").read_text()),
        "settings": {
            "load_start": config.LOAD_START, "analysis_start": config.ANALYSIS_START,
            "s6b_limit": config.S6B_LIMIT, "near_limit_band": config.NEAR_LIMIT_BAND,
            "split_window_days": config.SPLIT_WINDOW_DAYS, "amendment_growth_flag": config.AMENDMENT_GROWTH_FLAG,
            "amendment_count_flag": config.AMENDMENT_COUNT_FLAG, "duplicate_window_days": config.DUPLICATE_WINDOW_DAYS,
            "concentration_share": config.CONCENTRATION_SHARE, "risk_weights": config.RISK_WEIGHTS,
            "fuzzy_threshold": config.FUZZY_THRESHOLD, "placebo_limits": config.PLACEBO_LIMITS,
        },
        "cleaning": dq.to_dict(),
        "database": records(counts)[0],
        "window": records(window)[0],
        "by_fiscal_year": records(years),
        "sql_checks": {"n_hard": int((checks.severity == "hard").sum()),
                       "n_hard_passed": int(((checks.severity == "hard") & checks.passed).sum()),
                       "info": checks[checks.severity == "info"].set_index("check_name")["actual"].to_dict()},
        "tests": records(tests),
        "flagged": records(flagged)[0],
        "t3_flags_with_no_amendment_row": int(t3_without_amendment),
        "amended_past_limit": records(past_limit)[0],
        "services_near_limit": records(near_limit.round(1))[0],
        "non_competitive_awards_at_exactly_the_limit": int(at_limit),
        "non_competitive_without_s6_exception_by_year": records(no_reason),
        "reconciliation": {"n_checks": len(reconciliation), "n_matching": int(reconciliation["match"].sum())},
        "bunching": records(pd.read_csv(P / "bunching_summary.csv").round(3)),
        "bunching_by_department": records(by_department.round(3)),
        "departments_services": {
            "n_estimated": int((by_department["commodity_type"] == "S").sum()),
            "n_with_own_placebo": int(services["placebo_hi"].notna().sum()),
            "n_interval_above_own_placebo": int((services["ci_lo"] > services["placebo_hi"]).sum()),
            "n_point_above_own_placebo": int((services["ratio"] > services["placebo_hi"]).sum()),
        },
        "sensitivity": records(pd.read_csv(P / "sensitivity.csv")),
        "case_study": {
            "summary": records(pd.read_csv(P / "case_study_summary.csv").round(2)),
            "by_vendor": records(case.groupby("vendor").agg(
                n_awards=("contract_key", "size"), n_flagged=("n_flags", lambda s: int((s > 0).sum())),
                awarded_value=("original_value", "sum"), current_value=("final_value", "sum")).reset_index()),
            "highest_ranked": records(case.head(5)[["vendor", "award_date", "original_value", "final_value",
                                                    "n_amendments", "n_flags", "risk_rank", "rank_percentile"]].round(3)),
            # The audit (paragraph 1.38) names the first ArriveCAN contract: GC Strategies, $2.35M, April 2020
            "first_contract_named_in_audit": records(case[(case["award_date"] == config.AUDIT_FIRST_CONTRACT["award_date"])
                                                          & (case["original_value"] == config.AUDIT_FIRST_CONTRACT["original_value"])][
                ["vendor", "award_date", "original_value", "final_value", "n_amendments", "solicitation_procedure",
                 "n_flags", "flag_details", "risk_rank", "rank_percentile"]].round(3)),
            "first_contract_all_rows": records(first_contract_rows),
        },
        "review_queue_top_10": records(queue),
    }
    (P / "results.json").write_text(json.dumps(results, indent=2))
    print(json.dumps({k: results[k] for k in ("database", "window", "flagged", "reconciliation")}, indent=2))


if __name__ == "__main__":
    main()
