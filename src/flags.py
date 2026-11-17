"""The five audit tests a second time, in pandas.

Author: Neo Nguyen

sql/03_audit_tests.sql is the version of record. This module repeats each test from the same written
definition, and reconcile.py compares the two award by award, so a mistake in either one shows up as
a mismatch. Each function takes its cut-off as an argument, which is what sensitivity.py varies.

Every function takes the awards frame from db.read_awards and returns a boolean Series on its index.
"""
from __future__ import annotations

import pandas as pd

import config

STANDING_OFFER_ENTITIES = {"DSOSA", "PWSOSA", "SSCSOSA"}


def _non_competitive(a: pd.DataFrame) -> pd.Series:
    """True only where the award is known to be non-competitive (an unknown procedure is not)."""
    return a["is_competitive"].eq(False)


def flag_splitting(a: pd.DataFrame, window_days: int) -> pd.Series:
    """T1: non-competitive awards to one vendor, each within the limit, that together pass it."""
    keys = ["owner_org", "vendor_id", "commodity_type"]
    out = pd.Series(False, index=a.index)
    # Call-ups against a standing offer are left out: the competition was held when the offer was set up
    eligible = (_non_competitive(a) & a["vendor_id"].notna() & a["commodity_type"].notna()
                & ~a["contracting_entity"].isin(STANDING_OFFER_ENTITIES) & a["standing_offer_number"].isna())
    e = a.loc[eligible, keys + ["award_date", "original_value", "s6b_limit"]].copy()
    if e.empty:
        return out
    e["vendor_id"] = e["vendor_id"].astype("int64")
    e["over"] = ~a.loc[eligible, "is_within_limit"].astype(bool)

    # One row per vendor and day first, so awards dated the same day are always counted together
    daily = (e.groupby(keys + ["award_date"])
              .agg(n=("original_value", "size"), value=("original_value", "sum"),
                   over=("over", "sum"), limit=("s6b_limit", "first"))
              .reset_index())
    look_back = (daily.set_index("award_date").groupby(keys)[["n", "value", "over"]]
                      .rolling(f"{window_days}D", closed="both").sum().reset_index())
    trigger = ((look_back["n"] >= 2) & (look_back["over"] == 0)
               & (look_back["value"].round(2) > daily["limit"]))

    # An award is part of the cluster when a trigger falls on its day or within the window after it
    next_trigger = daily["award_date"].where(trigger).groupby([daily[k] for k in keys]).bfill()
    daily["in_cluster"] = (next_trigger - daily["award_date"]).dt.days <= window_days

    hit = e[keys + ["award_date"]].merge(daily[keys + ["award_date", "in_cluster"]], on=keys + ["award_date"], how="left")
    out.loc[e.index] = hit["in_cluster"].to_numpy()
    return out


def flag_near_limit(a: pd.DataFrame, band: float) -> pd.Series:
    """T2: a non-competitive award priced inside the top `band` of the range that needs no bids."""
    floor = (a["s6b_limit"] * (1 - band)).round(2)
    return _non_competitive(a) & (a["original_value"] >= floor) & (a["original_value"] <= a["s6b_limit"])


def flag_amendment_growth(a: pd.DataFrame, growth: float, count: int, min_original: float) -> pd.Series:
    """T3: final value more than `growth` above the award, or at least `count` amendments."""
    grew = a["final_value"] - a["original_value"] * (1 + growth) > 1e-6
    return (a["original_value"] >= min_original) & (grew | (a["n_amendments"] >= count))


def flag_duplicate(a: pd.DataFrame, window_days: int) -> pd.Series:
    """T4: same department, vendor and award value as an earlier contract within `window_days`."""
    out = pd.Series(False, index=a.index)
    group = ["owner_org", "vendor_id", "original_value"]
    e = (a[a["vendor_id"].notna() & (a["original_value"] > 0)]
         .sort_values(group + ["award_date", "contract_key"]))
    gap = e.groupby(group)["award_date"].diff().dt.days
    out.loc[e.index] = (gap <= window_days).to_numpy()
    return out


def flag_concentration(a: pd.DataFrame, share: float, min_spend: float) -> pd.Series:
    """T5: the vendor holds over `share` of the department's non-competitive spend."""
    nc = a[_non_competitive(a) & (a["original_value"] > 0)]
    by_dept = nc.groupby("owner_org")["original_value"].sum()
    by_vendor = nc[nc["vendor_id"].notna()].groupby(["owner_org", "vendor_id"])["original_value"].sum()
    dept_total = by_dept.reindex(by_vendor.index.get_level_values("owner_org")).to_numpy()
    dominant = by_vendor[(by_vendor.to_numpy() / dept_total > share) & (dept_total >= min_spend)].index
    pairs = pd.MultiIndex.from_frame(a[["owner_org", "vendor_id"]])
    return pd.Series(_non_competitive(a).to_numpy() & pairs.isin(dominant), index=a.index)


def all_flags(a: pd.DataFrame) -> pd.DataFrame:
    """All five tests at the cut-offs in config.py, plus how many flagged each award."""
    f = pd.DataFrame({
        "t1": flag_splitting(a, config.SPLIT_WINDOW_DAYS),
        "t2": flag_near_limit(a, config.NEAR_LIMIT_BAND),
        "t3": flag_amendment_growth(a, config.AMENDMENT_GROWTH_FLAG, config.AMENDMENT_COUNT_FLAG,
                                    config.MIN_ORIGINAL_FOR_GROWTH),
        "t4": flag_duplicate(a, config.DUPLICATE_WINDOW_DAYS),
        "t5": flag_concentration(a, config.CONCENTRATION_SHARE, config.CONCENTRATION_MIN_SPEND),
    }, index=a.index)
    f["n_flags"] = f.sum(axis=1)
    return f


def risk_score(f: pd.DataFrame, original_value: pd.Series) -> pd.DataFrame:
    """Review priority per award: the weights of its flags, scaled up for larger awards.

    points      sum of config.RISK_WEIGHTS over the tests that flagged the award (0 to 100)
    percentile  the award's percent rank by original value among all awards (0 to 1)
    score       points x (0.5 + 0.5 x percentile), so the same flags count double on the largest
                award compared with the smallest. Unflagged awards score 0.
    """
    points = sum(f[test.lower()].astype(int) * weight for test, weight in config.RISK_WEIGHTS.items())
    percentile = (original_value.rank(method="min") - 1) / max(len(original_value) - 1, 1)
    return pd.DataFrame({"flag_points": points, "value_percentile": percentile,
                         "risk_score": points * (0.5 + 0.5 * percentile)})
