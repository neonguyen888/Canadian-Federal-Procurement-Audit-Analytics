"""Write the files the Tableau dashboard reads.

Author: Neo Nguyen

Tableau Public cannot connect to PostgreSQL, so the dashboard reads CSV files from data/tableau/:

  awards.csv                 one row per award, with flags and risk score (sql/05_tableau_views.sql)
  value_bins.csv             awards per $1,000 of value by commodity, with the fitted trend
  bunching_summary.csv       the excess at each limit and placebo value, for the cards on page 2
  bunching_by_department.csv each department's excess and its own placebo range
  headline.csv               single numbers the dashboard quotes but cannot compute from awards.csv

Nothing here computes a new result; every number comes from the database or data/processed. No file
carries a vendor name: the public dashboard shows a vendor code instead.
"""
from __future__ import annotations

import json

import pandas as pd

import config
from bunching import trend
from db import connect, query

OUT = config.ROOT / "data" / "tableau"


def check_public(df: pd.DataFrame) -> None:
    """Refuse a table that would publish vendor names. A vendor_code column is allowed."""
    named = [c for c in df.columns if "vendor" in c.lower() and c != "vendor_code"]
    if named:
        raise ValueError(f"vendor names must not reach the public files: {named}")


def bins_with_trend(bins: pd.DataFrame) -> pd.DataFrame:
    """One row per commodity and $1,000 bin, the groups side by side, plus the trend the bunching
    estimate fitted. The trend has a value only in the fit span and window below each limit."""
    wide = (bins.pivot_table(index=["commodity_type", "bin_start"], columns="group", values="n_awards",
                             aggfunc="sum", fill_value=0)
                .reindex(columns=["non_competitive", "competitive", "unknown"], fill_value=0)
                .rename(columns={"non_competitive": "sole_sourced", "competitive": "competed"})
                .reset_index())
    wide.columns.name = None
    wide["total"] = wide[["sole_sourced", "competed", "unknown"]].sum(axis=1)
    wide["bin_label"] = [f"${b // 1000}K to ${b // 1000 + 1}K" for b in wide["bin_start"]]
    wide["trend"] = float("nan")
    wide["in_window"] = False
    for commodity, limit in config.S6B_LIMIT.items():
        lo = limit - config.BUNCH_WINDOW - config.BUNCH_FIT_SPAN
        rows = wide.index[(wide["commodity_type"] == commodity) & wide["bin_start"].between(lo, limit - 1)]
        if len(rows):
            ordered = wide.loc[rows].sort_values("bin_start").index
            wide.loc[ordered, "trend"] = trend(wide.loc[ordered, "total"].to_numpy()).round(1)
            wide.loc[ordered, "in_window"] = wide.loc[ordered, "bin_start"] >= limit - config.BUNCH_WINDOW
    return wide


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    P = config.PROCESSED_DIR
    R = json.loads((P / "results.json").read_text())
    with connect() as con:
        awards = query(con, "SELECT * FROM vw_tableau_awards ORDER BY risk_rank")
    placebo = pd.read_csv(P / "bunching_summary.csv").query("limit_kind == 'placebo' and group == 'all'")
    tables = {
        "awards": awards,
        "value_bins": bins_with_trend(pd.read_csv(P / "value_bins.csv")),
        "bunching_summary": pd.read_csv(P / "bunching_summary.csv").round(3),
        "bunching_by_department": pd.read_csv(P / "bunching_by_department.csv").drop(columns="owner_org").round(3),
        "headline": pd.DataFrame([{
            "data_as_of": R["source"]["portal_last_modified"][:10],
            "analysis_start": config.ANALYSIS_START,
            "checks_matching": R["reconciliation"]["n_matching"],
            "checks_total": R["reconciliation"]["n_checks"],
            "hard_checks_passed": R["sql_checks"]["n_hard_passed"],
            "hard_checks_total": R["sql_checks"]["n_hard"],
            "placebo_low_services": placebo.query("commodity_type == 'S'")["ratio"].min().round(2),
            "placebo_high_services": placebo.query("commodity_type == 'S'")["ratio"].max().round(2),
            "amended_past_limit": R["amended_past_limit"]["n_awards"],
            "amended_past_limit_value_at_award": round(R["amended_past_limit"]["awarded_value"], 2),
            "amended_past_limit_value_now": round(R["amended_past_limit"]["current_value"], 2),
            "departments_clear_of_own_placebo": R["departments_services"]["n_interval_above_own_placebo"],
            "departments_estimated": R["departments_services"]["n_estimated"],
        }]),
    }
    for name, table in tables.items():
        check_public(table)
        table.to_csv(OUT / f"{name}.csv", index=False)
        print(f"  {name}.csv: {len(table):,} rows, {len(table.columns)} columns")


if __name__ == "__main__":
    main()
