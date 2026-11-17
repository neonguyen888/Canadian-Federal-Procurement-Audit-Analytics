"""Tests for the pandas versions of the five audit tests and the risk score. Author: Neo Nguyen"""
import sys
from pathlib import Path

import numpy as np
import pytest
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from config import S6B_LIMIT  # noqa: E402
from flags import (all_flags, flag_amendment_growth, flag_concentration, flag_duplicate,  # noqa: E402
                   flag_near_limit, flag_splitting, risk_score)


def awards(rows):
    """Each row overrides the default: an $18,000 non-competitive service award, one department, one vendor."""
    base = dict(owner_org="d1", vendor_id=1, commodity_type="S", day=0, original_value=18_000.0, final_value=None,
                n_amendments=0, is_competitive=False, contracting_entity=None, standing_offer_number=None)
    df = pd.DataFrame([{**base, **r} for r in rows])
    df["contract_key"] = [f"k{i}" for i in range(len(df))]
    df["award_date"] = pd.Timestamp("2024-01-01") + pd.to_timedelta(df.pop("day"), unit="D")
    df["final_value"] = df["final_value"].fillna(df["original_value"]).astype(float)
    df["s6b_limit"] = df["commodity_type"].map(S6B_LIMIT)
    df["is_within_limit"] = df["original_value"] <= df["s6b_limit"]
    df["growth_ratio"] = np.where(df["original_value"] > 0, df["final_value"] / df["original_value"] - 1, np.nan)
    df["vendor_id"] = df["vendor_id"].astype("Int64")
    return df


# ---- T1 contract splitting -------------------------------------------------------------------

def test_splitting_flags_the_whole_cluster():
    a = awards([{"day": 0}, {"day": 10}, {"day": 20}, {"day": 70}])
    assert flag_splitting(a, 30).tolist() == [True, True, True, False]


def test_splitting_ignores_competitive_awards():
    a = awards([{"day": 0, "is_competitive": True}, {"day": 10, "is_competitive": True},
                {"day": 20, "is_competitive": True}])
    assert not flag_splitting(a, 30).any()


def test_splitting_ignores_standing_offer_call_ups():
    a = awards([{"day": d, "contracting_entity": "PWSOSA"} for d in (0, 10, 20)])
    b = awards([{"day": d, "standing_offer_number": "E60ZT-1"} for d in (0, 10, 20)])
    assert not flag_splitting(a, 30).any() and not flag_splitting(b, 30).any()


def test_splitting_needs_every_award_in_the_window_under_the_limit():
    a = awards([{"day": 0}, {"day": 5, "original_value": 45_000.0}])
    assert not flag_splitting(a, 30).any()


def test_awards_exactly_at_the_limit_can_form_a_split():
    a = awards([{"day": 0, "original_value": 40_000.0}, {"day": 5, "original_value": 40_000.0}])
    assert flag_splitting(a, 30).tolist() == [True, True]


def test_splitting_needs_the_total_to_pass_the_limit():
    a = awards([{"day": 0}, {"day": 5}])                # $36,000 together, under $40,000
    assert not flag_splitting(a, 30).any()


def test_same_day_awards_count_together():
    a = awards([{"original_value": 21_000.0}, {"original_value": 21_000.0}])
    assert flag_splitting(a, 30).tolist() == [True, True]


def test_splitting_window_is_inclusive_at_30_days_and_closed_at_31():
    inside = awards([{"day": 0, "original_value": 21_000.0}, {"day": 30, "original_value": 21_000.0}])
    outside = awards([{"day": 0, "original_value": 21_000.0}, {"day": 31, "original_value": 21_000.0}])
    assert flag_splitting(inside, 30).all() and not flag_splitting(outside, 30).any()


def test_splitting_keeps_vendors_departments_and_commodities_apart():
    a = awards([{"original_value": 21_000.0}, {"original_value": 21_000.0, "vendor_id": 2},
                {"original_value": 21_000.0, "owner_org": "d2"}, {"original_value": 21_000.0, "commodity_type": "C"}])
    assert not flag_splitting(a, 30).any()


# ---- Review focus: rows with missing keys ----------------------------------------------------

def test_awards_with_no_vendor_are_never_grouped():
    a = awards([{"original_value": 600_000.0, "vendor_id": None}, {"original_value": 600_000.0, "vendor_id": None}])
    small = awards([{"original_value": 21_000.0, "vendor_id": None}, {"original_value": 21_000.0, "vendor_id": None}])
    assert not flag_splitting(small, 30).any()
    assert not flag_duplicate(a, 7).any()
    assert not flag_concentration(a, 0.5, 1_000_000).any()


def test_awards_with_no_commodity_type_have_no_limit_to_test():
    a = awards([{"original_value": 21_000.0, "commodity_type": None}, {"original_value": 21_000.0, "commodity_type": None}])
    assert not flag_splitting(a, 30).any() and not flag_near_limit(a, 0.10).any()


# ---- T2 sole-source near the limit -----------------------------------------------------------

def test_near_limit_band_runs_up_to_and_including_the_limit():
    # the regulation says "does not exceed", so an award of exactly $40,000 still needs no bids
    a = awards([{"original_value": v} for v in (35_999.99, 36_000.0, 40_000.0, 40_000.01)])
    assert flag_near_limit(a, 0.10).tolist() == [False, True, True, False]


def test_near_limit_uses_the_goods_limit_for_goods_and_skips_competitive():
    a = awards([{"original_value": 24_000.0, "commodity_type": "G"},
                {"original_value": 38_000.0, "commodity_type": "G"},
                {"original_value": 38_000.0, "is_competitive": True}])
    assert flag_near_limit(a, 0.10).tolist() == [True, False, False]


# ---- T3 amendment growth ---------------------------------------------------------------------

def test_amendment_growth_or_count():
    a = awards([{"original_value": 100_000.0, "final_value": 151_000.0},
                {"original_value": 100_000.0, "final_value": 150_000.0},
                {"original_value": 100_000.0, "n_amendments": 3},
                {"original_value": 5_000.0, "final_value": 50_000.0},
                {"original_value": 0.0, "final_value": 50_000.0, "n_amendments": 5}])
    assert flag_amendment_growth(a, 0.50, 3, 10_000).tolist() == [True, False, True, False, False]


# ---- T4 possible duplicate -------------------------------------------------------------------

def test_duplicate_within_a_week_flags_the_later_award():
    a = awards([{"day": 0}, {"day": 7}, {"day": 15}])
    assert flag_duplicate(a, 7).tolist() == [False, True, False]


def test_duplicate_needs_same_vendor_department_and_value():
    a = awards([{"day": 0}, {"day": 1, "vendor_id": 2}, {"day": 1, "owner_org": "d2"},
                {"day": 1, "original_value": 18_000.01}, {"day": 0, "original_value": 0.0},
                {"day": 1, "original_value": 0.0}])
    assert not flag_duplicate(a, 7).any()


# ---- T5 vendor concentration -----------------------------------------------------------------

def test_concentration_flags_the_dominant_vendor_only():
    a = awards([{"original_value": 300_000.0}, {"original_value": 300_000.0},
                {"original_value": 400_000.0, "vendor_id": 2},
                {"original_value": 900_000.0, "is_competitive": True}])
    assert flag_concentration(a, 0.5, 1_000_000).tolist() == [True, True, False, False]


def test_concentration_skips_departments_under_the_spend_floor():
    a = awards([{"original_value": 300_000.0}, {"original_value": 300_000.0},
                {"original_value": 300_000.0, "vendor_id": 2}])
    assert not flag_concentration(a, 0.5, 1_000_000).any()


# ---- all five together -----------------------------------------------------------------------

def test_all_flags_has_one_column_per_test_and_a_count():
    a = awards([{"day": 0, "original_value": 38_000.0}, {"day": 3, "original_value": 38_000.0}, {"day": 200}])
    f = all_flags(a)
    assert list(f.columns) == ["t1", "t2", "t3", "t4", "t5", "n_flags"]
    assert f.index.equals(a.index)
    assert f.loc[1, ["t1", "t2", "t4"]].all() and f.n_flags.tolist() == [2, 3, 0]


# ---- risk score ------------------------------------------------------------------------------

def no_flags(a):
    return pd.DataFrame(False, index=a.index, columns=["t1", "t2", "t3", "t4", "t5"])


def test_score_is_flag_points_scaled_by_the_size_of_the_award():
    a = awards([{"original_value": v} for v in (10_000.0, 20_000.0, 30_000.0, 40_000.0)])
    f = no_flags(a)
    f.loc[0, "t2"] = True                       # smallest award, one 20-point flag
    f.loc[3, ["t1", "t3"]] = True               # largest award, 30 + 25 points
    s = risk_score(f, a["original_value"])
    assert s["flag_points"].tolist() == [20, 0, 0, 55]
    assert s["value_percentile"].tolist() == pytest.approx([0, 1 / 3, 2 / 3, 1])
    assert s["risk_score"].tolist() == pytest.approx([10.0, 0.0, 0.0, 55.0])


def test_score_is_defined_for_zero_and_tied_values():
    a = awards([{"original_value": 0.0}, {"original_value": 0.0}, {"original_value": 50_000.0, "commodity_type": None}])
    f = no_flags(a)
    f["t3"] = True
    s = risk_score(f, a["original_value"])
    assert s["value_percentile"].tolist() == [0.0, 0.0, 1.0]
    assert s["risk_score"].tolist() == pytest.approx([12.5, 12.5, 25.0])


def test_all_five_flags_on_the_largest_award_score_100():
    a = awards([{"original_value": 1.0}, {"original_value": 2.0}])
    f = no_flags(a)
    f.loc[1] = True
    assert risk_score(f, a["original_value"])["risk_score"].tolist() == pytest.approx([0.0, 100.0])
