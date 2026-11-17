"""Tests for the case-study comparison. Author: Neo Nguyen"""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from case_study import summarize  # noqa: E402


def scored():
    """Ten awards: three case awards in department x, two other awards in x, five in department y."""
    df = pd.DataFrame({
        "owner_org":  ["x", "x", "x", "x", "x", "y", "y", "y", "y", "y"],
        "n_flags":    [2, 1, 0, 1, 0, 0, 0, 0, 0, 1],
        "risk_score": [50.0, 30.0, 0.0, 10.0, 0.0, 0.0, 0.0, 0.0, 0.0, 5.0],
    })
    for test in ("t1_splitting", "t2_near_limit", "t3_amendment_growth", "t4_duplicate", "t5_concentration"):
        df[test] = False
    df.loc[[0, 1], "t3_amendment_growth"] = True
    df.loc[[0, 3, 9], "t4_duplicate"] = True
    return df


def test_summary_gives_each_group_its_rates_in_the_order_given():
    df = scored()
    case = pd.Series([True, True, True] + [False] * 7)
    s = summarize(df, {"case": case, "same department": (df.owner_org == "x") & ~case, "everyone else": ~case})

    assert s.index.tolist() == ["case", "same department", "everyone else"]
    assert s["n_awards"].tolist() == [3, 2, 7]
    assert s["pct_flagged"].tolist() == pytest.approx([66.67, 50.0, 28.57], abs=0.01)
    # top decile of all ten awards by score is the single award scoring 50
    assert s["pct_top_decile"].tolist() == pytest.approx([33.33, 0.0, 0.0], abs=0.01)
    assert s["pct_T3"].tolist() == pytest.approx([66.67, 0.0, 0.0], abs=0.01)
    assert s["pct_T4"].tolist() == pytest.approx([33.33, 50.0, 28.57], abs=0.01)


def test_an_empty_group_has_zero_awards_and_no_rates():
    s = summarize(scored(), {"nobody": pd.Series([False] * 10)})
    assert s.loc["nobody", "n_awards"] == 0
    assert pd.isna(s.loc["nobody", "pct_flagged"]) and pd.isna(s.loc["nobody", "pct_T3"])
