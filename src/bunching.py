"""Do awards pile up just under the dollar limit that requires bids?

Author: Neo Nguyen

Up to the s.6(b) limit a department may award a contract without soliciting bids
(https://laws-lois.justice.gc.ca/eng/regulations/SOR-87-402/section-6.html). If contracts are
sized or priced to stay under it, the count of awards just below the limit will be higher than the
trend of the bins further down predicts.

Method: count awards in $1,000 bins, fit a straight line to log(count) over the ten bins from
limit-$15,000 to limit-$5,000, extend it across the five bins up to the limit, and compare
with what is there. Only bins up to the limit are used. Above it bids are required, so the count
drops there for legal reasons and says nothing about bunching.

Three comparisons put the estimate in context: non-competitive against competitive awards (only the
first have a reason to stay under the limit), four round dollar values where no rule changes, and
each department on its own with a bootstrap interval.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from config import (BUNCH_BIN_WIDTH, BUNCH_BOOTSTRAP, BUNCH_FIT_SPAN, BUNCH_MIN_AWARDS, BUNCH_SEED,
                    BUNCH_WINDOW, PLACEBO_LIMITS, PROCESSED_DIR, S6B_LIMIT)
from db import connect, read_awards

N_FIT = BUNCH_FIT_SPAN // BUNCH_BIN_WIDTH        # bins the trend is fitted on; the rest are the window
BINS_LO, BINS_HI = 10_000, 100_000               # range of the histogram exported for the charts


def bin_counts(values, lo: float, hi: float, width: float) -> pd.Series:
    """Awards per bin (start, start + width] from lo up to hi, indexed by bin start, zeros kept.

    Bins include their upper edge because the regulation does: a contract that "does not exceed"
    $40,000 needs no bids, so an award of exactly $40,000 belongs with the ones just under it.
    """
    v = np.asarray(values, dtype=float)
    v = v[(v > lo) & (v <= hi)]
    n_bins = int(round((hi - lo) / width))
    counts = np.bincount((np.ceil((v - lo) / width) - 1).astype(int), minlength=n_bins)[:n_bins]
    return pd.Series(counts, index=np.arange(lo, hi, width, dtype=int))


def _range_counts(values, limit: float) -> np.ndarray:
    """Counts for the bins the estimate uses: the fit span, then the window, ending at the limit."""
    return bin_counts(values, limit - BUNCH_WINDOW - BUNCH_FIT_SPAN, limit, BUNCH_BIN_WIDTH).to_numpy()


def trend(counts: np.ndarray) -> np.ndarray:
    """The fitted log-linear trend at every bin (fit span and window). NaN when it cannot be fitted."""
    x, y = np.arange(len(counts)), counts[:N_FIT]
    usable = y > 0
    if usable.sum() < 3:                         # too few bins with any award to draw a line through
        return np.full(len(counts), np.nan)
    slope, intercept = np.polyfit(x[:N_FIT][usable], np.log(y[usable]), 1)
    return np.exp(intercept + slope * x)


def _expected(counts: np.ndarray) -> float:
    """Awards the trend predicts for the window."""
    return float(trend(counts)[N_FIT:].sum())


def excess_mass(values, limit: float) -> dict:
    """Observed and expected awards in the window under `limit`, their difference and their ratio."""
    counts = _range_counts(values, limit)
    observed, expected = int(counts[N_FIT:].sum()), _expected(counts)
    return {"observed": observed, "expected": expected, "excess": observed - expected,
            "ratio": observed / expected if expected > 0 else np.nan}


def bootstrap_ci(values, limit: float) -> tuple[float, float]:
    """95% interval for the ratio. Redrawing the bin counts is the same as resampling the awards."""
    counts = _range_counts(values, limit)
    if counts.sum() == 0 or np.isnan(_expected(counts)):
        return np.nan, np.nan
    draws = np.random.default_rng(BUNCH_SEED).multinomial(counts.sum(), counts / counts.sum(), size=BUNCH_BOOTSTRAP)
    ratios = [d[N_FIT:].sum() / _expected(d) for d in draws]
    lo, hi = np.nanpercentile(ratios, [2.5, 97.5])
    return float(lo), float(hi)


def placebo_range(values) -> tuple[float, float]:
    """Lowest and highest ratio at the round values where no rule changes (PLACEBO_LIMITS).

    This is how far the method strays from 1 on this set of awards when there is nothing to find.
    NaN when any of the placebos cannot be fitted.
    """
    ratios = [excess_mass(values, at)["ratio"] for at in PLACEBO_LIMITS]
    if any(np.isnan(r) for r in ratios):
        return np.nan, np.nan
    return float(min(ratios)), float(max(ratios))


def _estimate(values, limit: float) -> dict:
    lo, hi = bootstrap_ci(values, limit)
    return {**excess_mass(values, limit), "ci_lo": lo, "ci_hi": hi}


def main():
    with connect() as con:
        a = read_awards(con)
    a = a[a["commodity_type"].notna() & (a["original_value"] > 0)]
    groups = {"all": slice(None), "non_competitive": a["is_competitive"].eq(False),
              "competitive": a["is_competitive"].eq(True)}

    # ---- Government-wide: real limit and placebo, by group ---------------------------------
    rows = []
    for commodity, limit in S6B_LIMIT.items():
        for kind, at in [("real", limit)] + [("placebo", p) for p in PLACEBO_LIMITS]:
            for group, mask in groups.items():
                values = a.loc[mask].loc[lambda d: d["commodity_type"] == commodity, "original_value"]
                rows.append({"commodity_type": commodity, "limit_kind": kind, "limit": at, "group": group,
                             **_estimate(values, at)})
    summary = pd.DataFrame(rows)
    summary.to_csv(PROCESSED_DIR / "bunching_summary.csv", index=False)

    # ---- Department by department, at the real limit ---------------------------------------
    # Each department is measured against its own placebo range: a small department's ratios wander
    # much further from 1 than the government-wide ones, so the government-wide range would flatter it.
    rows = []
    for (org, department, commodity), d in a.groupby(["owner_org", "department", "commodity_type"]):
        limit = S6B_LIMIT[commodity]
        n_in_range = int(_range_counts(d["original_value"], limit).sum())
        if n_in_range >= BUNCH_MIN_AWARDS:
            placebo_lo, placebo_hi = placebo_range(d["original_value"])
            rows.append({"owner_org": org, "department": department, "commodity_type": commodity,
                         "n_in_range": n_in_range, **_estimate(d["original_value"], limit),
                         "placebo_lo": placebo_lo, "placebo_hi": placebo_hi})
    by_department = pd.DataFrame(rows).drop(columns="excess").sort_values(["commodity_type", "ratio"], ascending=[True, False])
    by_department.to_csv(PROCESSED_DIR / "bunching_by_department.csv", index=False)

    # ---- $1,000 histogram for the charts -------------------------------------------
    procedure = a["is_competitive"].map({True: "competitive", False: "non_competitive"}).fillna("unknown")
    bins = (a.groupby(["commodity_type", procedure.rename("group")])["original_value"]
             .apply(lambda v: bin_counts(v, BINS_LO, BINS_HI, BUNCH_BIN_WIDTH))
             .rename("n_awards").rename_axis(["commodity_type", "group", "bin_start"]).reset_index())
    bins.to_csv(PROCESSED_DIR / "value_bins.csv", index=False)

    print(summary.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
    print(f"\n{len(by_department)} department estimates, top five by ratio:")
    print(by_department.head(5).to_string(index=False, float_format=lambda v: f"{v:,.2f}"))


if __name__ == "__main__":
    main()
