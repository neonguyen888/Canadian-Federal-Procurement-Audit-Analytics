"""Tests for the bunching estimate. Author: Neo Nguyen"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bunching import bin_counts, bootstrap_ci, excess_mass, placebo_range  # noqa: E402

LIMIT = 40_000


def smooth_values(n=60_000, seed=1):
    """Contract values with no bunching: a smooth, falling distribution that starts at $10,000."""
    return pd.Series(10_000 + np.random.default_rng(seed).exponential(30_000, n))


def test_bins_are_zero_filled_and_include_their_upper_edge():
    # (10,000 to 11,000] and so on: an award of exactly $11,000 belongs with the ones just under it
    counts = bin_counts(pd.Series([10_000, 10_000.01, 11_000, 11_000.01, 13_500]), 10_000, 14_000, 1_000)
    assert counts.index.tolist() == [10_000, 11_000, 12_000, 13_000]
    assert counts.tolist() == [2, 1, 0, 1]


def test_an_award_exactly_at_the_limit_counts_as_under_it():
    at_limit = pd.concat([smooth_values(), pd.Series([float(LIMIT)] * 5_000)])
    assert excess_mass(at_limit, LIMIT)["observed"] == excess_mass(smooth_values(), LIMIT)["observed"] + 5_000


def test_an_award_one_cent_over_the_limit_is_left_out():
    over = pd.concat([smooth_values(), pd.Series([LIMIT + 0.01] * 5_000)])
    assert excess_mass(over, LIMIT)["observed"] == excess_mass(smooth_values(), LIMIT)["observed"]


def test_no_bunching_gives_a_ratio_near_one():
    assert 0.9 < excess_mass(smooth_values(), LIMIT)["ratio"] < 1.1


def test_added_mass_under_the_limit_is_recovered():
    extra = pd.Series(np.random.default_rng(2).uniform(36_000, 40_000, 600))
    result = excess_mass(pd.concat([smooth_values(), extra]), LIMIT)
    assert 500 < result["excess"] < 700
    assert result["excess"] == result["observed"] - result["expected"]


def test_too_little_data_returns_nan_instead_of_failing():
    result = excess_mass(pd.Series([26_000.0, 27_000.0, 36_000.0, 37_000.0, 38_000.0]), LIMIT)
    assert np.isnan(result["ratio"]) and np.isnan(result["expected"])
    assert all(np.isnan(v) for v in bootstrap_ci(pd.Series([36_000.0]), LIMIT))
    assert all(np.isnan(v) for v in bootstrap_ci(pd.Series([], dtype=float), LIMIT))


def test_bootstrap_interval_contains_one_when_nothing_piles_up():
    lo, hi = bootstrap_ci(smooth_values(), LIMIT)
    assert lo < 1 < hi and hi - lo < 0.5


def test_bootstrap_interval_excludes_one_when_awards_pile_up():
    extra = pd.Series(np.random.default_rng(2).uniform(36_000, 40_000, 600))
    lo, _ = bootstrap_ci(pd.concat([smooth_values(), extra]), LIMIT)
    assert lo > 1


def test_bootstrap_interval_narrows_with_more_awards():
    width = lambda n: (lambda lo, hi: hi - lo)(*bootstrap_ci(smooth_values(n=n, seed=3), LIMIT))
    assert width(60_000) < width(6_000)


def test_placebo_range_is_the_spread_of_the_ratios_at_values_with_no_rule():
    lo, hi = placebo_range(smooth_values())
    assert 0.8 < lo <= hi < 1.25               # smooth data: every placebo lands near 1


def test_placebo_range_is_nan_when_any_placebo_cannot_be_fitted():
    lo, hi = placebo_range(pd.Series([12_000.0, 36_000.0, 38_000.0]))
    assert np.isnan(lo) and np.isnan(hi)
