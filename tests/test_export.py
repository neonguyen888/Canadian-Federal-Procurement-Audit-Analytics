"""Tests for the files the Tableau dashboard reads. Author: Neo Nguyen"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import config  # noqa: E402
from export_tableau import bins_with_trend, check_public  # noqa: E402


# ---- No vendor names in the public files ---------------------------------------------------

def test_a_table_with_a_vendor_name_column_is_refused():
    with pytest.raises(ValueError, match="vendor"):
        check_public(pd.DataFrame({"department": ["d"], "vendor": ["Acme Inc."]}))
    with pytest.raises(ValueError, match="vendor"):
        check_public(pd.DataFrame({"vendor_name_raw": ["Acme Inc."]}))


def test_a_pseudonymous_vendor_code_is_allowed():
    check_public(pd.DataFrame({"department": ["d"], "vendor_code": ["V00042"]}))


# ---- Histogram bins with the fitted trend --------------------------------------------------

def bins_for(commodity, counts_by_bin):
    """value_bins.csv rows: every award sole-sourced, so the totals equal the counts given."""
    return pd.DataFrame([{"commodity_type": commodity, "group": "non_competitive", "bin_start": b, "n_awards": n}
                         for b, n in counts_by_bin.items()])


def test_bins_are_one_row_per_commodity_and_bin_with_the_groups_side_by_side():
    raw = pd.concat([bins_for("S", {39_000: 10}),
                     pd.DataFrame([{"commodity_type": "S", "group": "competitive", "bin_start": 39_000, "n_awards": 4}])])
    out = bins_with_trend(raw)
    row = out.iloc[0]
    assert (row["sole_sourced"], row["competed"], row["unknown"], row["total"]) == (10, 4, 0, 14)
    assert row["bin_label"] == "$39K to $40K"


def test_the_trend_covers_the_fit_span_and_window_below_each_limit_only():
    limit = config.S6B_LIMIT["S"]
    lo = limit - config.BUNCH_WINDOW - config.BUNCH_FIT_SPAN
    counts = {b: int(4_000 * np.exp(-(b - 10_000) / 20_000)) for b in range(10_000, 60_000, 1_000)}
    out = bins_with_trend(bins_for("S", counts)).set_index("bin_start")
    inside = out.loc[lo:limit - 1, "trend"]
    outside = out.drop(index=range(lo, limit, 1_000))["trend"]
    assert inside.notna().all() and outside.isna().all()
    # a smooth exponential fall is fitted almost exactly
    assert np.allclose(inside, out.loc[lo:limit - 1, "total"], rtol=0.02)
    assert out.loc[lo:limit - 1, "in_window"].tolist() == [False] * 10 + [True] * 5
