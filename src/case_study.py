"""Would the tests have pointed at the ArriveCAN contractors?

Author: Neo Nguyen

The data has no label saying which contracts were a problem, so the tests cannot be scored the usual
way. This is the nearest thing to a check: take contracts the Auditor General later examined and
see whether the tests flag them more often than other contracts, and how high they rank.

Auditor General of Canada, 2024 Report 1, ArriveCAN:
https://www.oag-bvg.gc.ca/internet/English/att__e_44429.html

The case group is CBSA's awards to GC Strategies, Dalian and Coradix from April 2020 to March 2023
(the settings, and why these three firms, are in config.py). Two broad baselines come first: CBSA's
other awards, and every other award. They differ from the case group in size, and amendments and
duplicates are both more common on large contracts, so the fair comparison is like for like: the
case group's service awards of CASE_COMPARABLE_MIN or more against CBSA's other service awards of
that size over the same period. A flag rate says nothing about whether any contract was improper.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import (CASE_COMPARABLE_MIN, CASE_END, CASE_OWNER_ORG, CASE_START, CASE_VENDOR_PATTERN,
                    PROCESSED_DIR)
from db import connect, query

TESTS = {"T1": "t1_splitting", "T2": "t2_near_limit", "T3": "t3_amendment_growth",
         "T4": "t4_duplicate", "T5": "t5_concentration"}


def summarize(scored: pd.DataFrame, groups: dict[str, pd.Series]) -> pd.DataFrame:
    """Flag rates for each named group of awards, in the order given.

    `scored` needs n_flags, risk_score and the five test columns. "Top decile" means among the
    highest-scoring 10% of all awards in `scored`, and flagged at all.
    """
    top = (scored["risk_score"] >= scored["risk_score"].quantile(0.9)) & (scored["risk_score"] > 0)
    rows = {}
    for name, mask in groups.items():
        n = int(mask.sum())
        pct = (lambda s: 100 * s.mean()) if n else (lambda s: np.nan)
        rows[name] = {"n_awards": n, "n_flagged": int((scored.loc[mask, "n_flags"] > 0).sum()),
                      "pct_flagged": pct(scored.loc[mask, "n_flags"] > 0),
                      "pct_top_decile": pct(top[mask]),
                      **{f"pct_{test}": pct(scored.loc[mask, col]) for test, col in TESTS.items()}}
    return pd.DataFrame.from_dict(rows, orient="index")


def main():
    with connect() as con:
        scored = query(con, """
            SELECT f.owner_org, f.contract_key, f.department, f.vendor, f.vendor_id, f.award_date,
                   f.commodity_type, f.solicitation_procedure, f.original_value, f.final_value, f.n_amendments,
                   f.n_flags, f.t1_splitting, f.t2_near_limit, f.t3_amendment_growth, f.t4_duplicate,
                   f.t5_concentration, f.flag_details, r.risk_score, r.risk_rank
            FROM vw_award_flags f JOIN risk_scores r USING (owner_org, contract_key)""")
        vendor_ids = query(con, "SELECT DISTINCT vendor_id FROM vendor_aliases WHERE alias_key ~ %s",
                           [CASE_VENDOR_PATTERN])["vendor_id"]

    cbsa = scored["owner_org"] == CASE_OWNER_ORG
    in_period = scored["award_date"].between(CASE_START, CASE_END)
    in_case = cbsa & scored["vendor_id"].isin(vendor_ids) & in_period
    large_services = (scored["commodity_type"] == "S") & (scored["original_value"] >= CASE_COMPARABLE_MIN)
    summary = summarize(scored, {
        "case awards": in_case,
        "CBSA, other awards": cbsa & ~in_case,
        "all other awards": ~in_case,
        "case awards, large services": in_case & large_services,
        "CBSA, other large services, same period": cbsa & ~in_case & in_period & large_services,
    })

    case = scored[in_case].sort_values("risk_rank")
    case["rank_percentile"] = 100 * case["risk_rank"] / len(scored)       # 1.0 = in the top 1% of all awards
    case.to_csv(PROCESSED_DIR / "case_study_contracts.csv", index=False)
    summary.rename_axis("group").to_csv(PROCESSED_DIR / "case_study_summary.csv")

    print(case.groupby("vendor").agg(n_awards=("contract_key", "size"), n_flagged=("n_flags", lambda s: (s > 0).sum()),
                                     awarded=("original_value", "sum"), current=("final_value", "sum")).to_string())
    print()
    print(summary.round(2).to_string())


if __name__ == "__main__":
    main()
