"""Draw the report figures.

Author: Neo Nguyen

One function per figure, all in the same style (colours below). Each title states what the chart
shows, with the numbers filled in from the data at run time, and every figure carries the same source
line. The figures read data/processed and the database; they compute nothing the report quotes.
"""
from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter

import config
from bunching import N_FIT, trend
from db import connect, query

# Charcoal for the main series, amber for whatever is flagged or sits at the limit, silver for
# context. The bright yellow is only used as a background tint: on white it is too pale for lines or text.
CHARCOAL, SILVER, AMBER, YELLOW = "#2E2E38", "#A9A9B5", "#D97706", "#FFE600"
GREY, INK, MUTED = "#DEDEE5", "#2E2E38", "#6B6B78"
LABEL = {"S": "Services", "G": "Goods", "C": "Construction"}
START = pd.Timestamp(config.ANALYSIS_START)
START_LABEL = f"{START.day} {START:%B %Y}"                       # "10 June 2019"
SOURCE = ("Source: Government of Canada, Proactive Publication of Contracts over $10,000 (open.canada.ca). "
          f"Awards from {START_LABEL}.\nA flag marks an award for review. It is not a finding of wrongdoing.")

plt.rcParams.update({
    "font.family": "sans-serif", "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
    "font.size": 9.5, "text.color": INK, "axes.labelcolor": MUTED, "axes.edgecolor": "#A9A9B5",
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": "#ECECF0", "grid.linewidth": 0.8, "axes.axisbelow": True,
    "legend.frameon": False, "savefig.dpi": 200, "text.parse_math": False,
})


# ---- Shared pieces ---------------------------------------------------------------------------

def money(v, _=None) -> str:
    """$39,900 -> $40K, $294,223,922 -> $294M, $25.7B. Used for axis ticks and labels."""
    for unit, size in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(v) >= size:
            scaled = v / size
            if unit == "K" or abs(scaled) >= 100:
                return f"${scaled:,.0f}{unit}"
            return f"${scaled:,.1f}".rstrip("0").rstrip(".") + unit
    return f"${v:,.0f}"


def figure(title: str, subtitle: str, size=(9, 5), left=0.09, **kw):
    """A figure with the title block at the top left and the source line at the bottom."""
    fig, ax = plt.subplots(figsize=size, **kw)
    top = 1 - 0.8 / size[1]
    fig.subplots_adjust(top=top, bottom=0.95 / size[1], left=left, right=0.97)
    fig.text(0.012, top + 0.47 / size[1], title, fontsize=12.5, fontweight="bold", va="bottom")
    fig.text(0.012, top + 0.17 / size[1], subtitle, fontsize=9.5, color=MUTED, va="bottom")
    fig.text(0.012, 0.1 / size[1], SOURCE, fontsize=7, color="#8A8A96", va="bottom", linespacing=1.4)
    return fig, ax


def save(fig, name: str) -> None:
    fig.savefig(config.FIGURES_DIR / name)
    plt.close(fig)


# ---- 01 What went in and what came out -------------------------------------------------------

def data_funnel(R):
    steps = [("Rows in the portal file", R["cleaning"]["rows in portal file"]),
             ("Rows loaded, fiscal 2017-18 on", R["database"]["n_report_rows"]),
             ("Contracts (an award and its amendments)", R["database"]["n_contracts"]),
             (f"Awards analysed, from {START_LABEL}", R["window"]["n_awards"]),
             ("Flagged by at least one test", R["flagged"]["n_flagged"])]
    fig, ax = figure(f"{R['window']['n_awards']:,} awards analysed, {R['flagged']['n_flagged']:,} flagged for review",
                     "From the published file to the review queue", size=(9, 4.2), left=0.36)
    names, values = zip(*steps[::-1])
    bars = ax.barh(names, values, color=[AMBER] + [CHARCOAL] * 4, height=0.62)
    ax.bar_label(bars, labels=[f"{v:,}" for v in values], padding=5, fontsize=9.5)
    ax.set_xlim(0, max(values) * 1.14)
    ax.xaxis.set_visible(False)
    ax.grid(False)
    ax.spines["bottom"].set_visible(False)
    save(fig, "01_data_funnel.png")


# ---- 02, 03 Awards just under the limit ------------------------------------------------------

def under_the_limit(bins, summary, commodity: str, lo: int, hi: int, name: str):
    limit = config.S6B_LIMIT[commodity]
    b = (bins[bins["commodity_type"] == commodity]
         .pivot(index="bin_start", columns="group", values="n_awards").fillna(0).loc[lo:hi - 1])
    total, mid = b.sum(axis=1), b.index + config.BUNCH_BIN_WIDTH / 2
    est = summary[(summary["commodity_type"] == commodity) & (summary["limit_kind"] == "real")].set_index("group")

    fig, ax = figure(
        f"{LABEL[commodity]}: {est.loc['all', 'ratio']:.2f} times the trend in the last $5,000 up to the ${limit:,} limit",
        f"Awards per $1,000 of contract value. {est.loc['all', 'observed']:,.0f} awards where the trend predicts "
        f"{est.loc['all', 'expected']:,.0f}; non-competitive awards alone run at {est.loc['non_competitive', 'ratio']:.2f} times.")
    other = total - b["non_competitive"]
    ax.bar(mid, other, width=820, color=SILVER, label="Competitive")
    ax.bar(mid, b["non_competitive"], bottom=other, width=820, color=CHARCOAL, label="Non-competitive")
    ax.axvspan(limit - config.BUNCH_WINDOW, limit, color=YELLOW, alpha=0.3, lw=0, zorder=0)

    # The trend: fitted on the ten bins below the shaded window, extended across it
    span = total.loc[limit - config.BUNCH_WINDOW - config.BUNCH_FIT_SPAN:limit - 1]
    fitted = trend(span.to_numpy())
    ax.plot(span.index[:N_FIT] + 500, fitted[:N_FIT], color=AMBER, lw=2, label="Trend, fitted")
    ax.plot(span.index[N_FIT - 1:] + 500, fitted[N_FIT - 1:], color=AMBER, lw=2, ls="--", label="Trend, extended")
    ax.axvline(limit, color=INK, lw=1)
    ax.annotate(f"${limit:,} limit:\nno bids needed\nup to here", (limit, ax.get_ylim()[1] * 0.97), xytext=(8, 0),
                textcoords="offset points", va="top", fontsize=8.5, color=INK)
    ax.set_xlim(lo, hi)
    ax.xaxis.set_major_formatter(FuncFormatter(money))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:,.0f}"))
    ax.set_xlabel("Value at award")
    ax.set_ylabel("Awards")
    ax.legend(loc="upper right", ncols=2, fontsize=8.5)
    save(fig, name)


# ---- 04 Non-competitive share by value -------------------------------------------------------

def non_competitive_share(bins):
    wide = bins.pivot_table(index=["commodity_type", "bin_start"], columns="group", values="n_awards", fill_value=0)
    share = (wide["non_competitive"] / wide.sum(axis=1)).unstack(0).loc[10_000:79_999]
    s_counts = wide.loc["S"]
    below = s_counts.loc[35_000:39_999]
    above = s_counts.loc[40_000:44_999]
    pct = lambda d: 100 * d["non_competitive"].sum() / d.to_numpy().sum()

    fig, ax = figure(
        f"{pct(below):.0f}% of service awards in the last $5,000 under the limit are non-competitive, "
        f"{pct(above):.0f}% just above it",
        "Share of awards made without competition, by $1,000 of contract value")
    mid = share.index + 500
    ax.plot(mid, 100 * share["S"], color=CHARCOAL, lw=2, label="Services ($40,000 limit)")
    ax.plot(mid, 100 * share["G"], color=SILVER, lw=2, label="Goods ($25,000 limit)")
    for limit in (25_000, 40_000):
        ax.axvline(limit, color=AMBER, lw=1.2, ls="--")
    ax.set_ylim(0, 80)
    ax.set_xlim(10_000, 80_000)
    ax.xaxis.set_major_formatter(FuncFormatter(money))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.set_xlabel("Value at award")
    ax.set_ylabel("Non-competitive share")
    ax.legend(loc="upper right", fontsize=8.5)
    save(fig, "04_non_competitive_share_by_value.png")


# ---- 05 Real limits against round numbers with no rule ---------------------------------------

def real_against_placebo(summary):
    fig, ax = figure("The excess at the real limits is outside what round numbers produce on their own",
                     "Awards observed in the last $5,000 up to each value, as a multiple of the trend below it",
                     size=(9, 4.6), left=0.27)
    rows = [(c, g) for c in ("S", "C", "G") for g in ("non_competitive", "competitive")][::-1]
    for y, (commodity, group) in enumerate(rows):
        d = summary[(summary["commodity_type"] == commodity) & (summary["group"] == group)]
        placebo, real = d[d["limit_kind"] == "placebo"], d[d["limit_kind"] == "real"].iloc[0]
        ax.scatter(placebo["ratio"], [y] * len(placebo), color=SILVER, s=38, zorder=2,
                   label="$60K, $70K, $80K, $90K: no rule changes" if y == 0 else None)
        ax.errorbar(real["ratio"], y, xerr=[[real["ratio"] - real["ci_lo"]], [real["ci_hi"] - real["ratio"]]],
                    fmt="o", color=AMBER, ms=8, capsize=3, zorder=3, label="The real limit, with 95% interval" if y == 0 else None)
        ax.annotate(f"{real['ratio']:.2f}", (real["ci_hi"], y), xytext=(6, 0), textcoords="offset points",
                    va="center", fontsize=9, color=INK)
    ax.axvline(1, color=INK, lw=1)
    ax.set_yticks(range(len(rows)), [f"{LABEL[c]}, {g.replace('_', '-')}" for c, g in rows])
    ax.set_xlabel("Observed awards as a multiple of the trend (1.0 = no excess)")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right", fontsize=8.5)
    save(fig, "05_real_limits_vs_placebo.png")


# ---- 06 Department by department -------------------------------------------------------------

def departments(by_department):
    d = by_department[by_department["commodity_type"] == "S"].sort_values("ratio").reset_index(drop=True)
    above = d["ci_lo"] > d["placebo_hi"]            # whole interval above the department's own placebo range
    fig, ax = figure(
        "Service awards in the last $5,000 up to $40,000, department by department",
        f"Multiple of each department's own trend (95% interval). Grey: its own range at $60K to $90K. "
        f"Amber: {int(above.sum())} of {int(d['placebo_hi'].notna().sum())} clear of it.",
        size=(9, 0.27 * len(d) + 1.9), left=0.42)
    for y, r in d.iterrows():
        if pd.notna(r["placebo_hi"]):
            ax.plot([r["placebo_lo"], r["placebo_hi"]], [y, y], color=GREY, lw=7, solid_capstyle="butt", zorder=1)
    ax.errorbar(d["ratio"], d.index, xerr=[d["ratio"] - d["ci_lo"], d["ci_hi"] - d["ratio"]], fmt="none",
                ecolor=SILVER, capsize=2, lw=1.2, zorder=2)
    ax.scatter(d["ratio"], d.index, color=np.where(above, AMBER, CHARCOAL), s=26, zorder=3)
    ax.axvline(1, color=INK, lw=1)
    ax.set_yticks(d.index, d["department"], fontsize=8)
    ax.set_ylim(-0.7, len(d) - 0.3)
    ax.set_xlim(0, min(d["ci_hi"].max() * 1.05, 8))
    ax.set_xlabel("Observed awards as a multiple of the trend (1.0 = no excess)")
    ax.grid(axis="y", visible=False)
    save(fig, "06_departments_services.png")


# ---- 07 Amendment growth ---------------------------------------------------------------------

def amendment_growth(awards, R):
    a = awards[(awards["n_amendments"] > 0) & (awards["original_value"] >= 1_000) & (awards["final_value"] >= 1_000)]
    a = a.sample(min(len(a), 25_000), random_state=config.BUNCH_SEED)       # enough dots to show the shape
    t3 = next(t for t in R["tests"] if t["test_id"] == "T3")
    past = R["amended_past_limit"]
    fig, ax = figure(
        f"{t3['n_flagged']:,} awards grew by more than half or were amended three times or more",
        f"Each dot is an amended contract. {past['n_awards']:,} sole-source awards began within the limit and were "
        f"amended past it ({money(past['awarded_value'])} at award, {money(past['current_value'])} now).",
        size=(9, 5.6))
    for flagged, colour, label in ((False, SILVER, "Amended, not flagged"), (True, AMBER, "Flagged for amendment growth")):
        d = a[a["t3_amendment_growth"] == flagged]
        ax.scatter(d["original_value"], d["final_value"], s=5, color=colour, alpha=0.35, lw=0, label=label)
    line = np.array([1e3, 1e10])
    ax.plot(line, line, color=INK, lw=1, label="No change")
    ax.plot(line, line * (1 + config.AMENDMENT_GROWTH_FLAG), color=INK, lw=1, ls="--", label="50% above the award")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlim(8e3, 2e9)
    ax.set_ylim(1e3, 5e9)
    ax.xaxis.set_major_formatter(FuncFormatter(money))
    ax.yaxis.set_major_formatter(FuncFormatter(money))
    ax.set_xlabel("Value at award")
    ax.set_ylabel("Value now")
    legend = ax.legend(loc="lower right", fontsize=8.5, markerscale=3)
    for handle in legend.legend_handles:
        handle.set_alpha(1)
    save(fig, "07_amendment_growth.png")


# ---- 08 What a splitting flag looks like -----------------------------------------------------

def splitting_example(awards):
    # A run small enough to read: one department, one vendor, one fiscal year of service awards, six
    # non-competitive awards and all six flagged. Of those, the one worth the most in total.
    keys = ["owner_org", "vendor_id", "commodity_type", "fiscal_year"]
    nc = awards[awards["is_competitive"].eq(False) & (awards["commodity_type"] == "S")]
    runs = nc.groupby(keys).agg(n=("t1_splitting", "size"), flagged=("t1_splitting", "sum"), value=("original_value", "sum"))
    pick = runs[(runs["n"] == 6) & (runs["flagged"] == 6)].sort_values("value", ascending=False, kind="stable").index[0]
    d = nc.set_index(keys).loc[[pick]].sort_values("award_date")
    limit = config.S6B_LIMIT["S"]
    # running total over the 30 days up to each award: the quantity the test compares with the limit
    daily = d.groupby("award_date")["original_value"].sum()
    running = daily.rolling(f"{config.SPLIT_WINDOW_DAYS}D", closed="both").sum()

    fig, ax = figure(
        f"One vendor, one department, one year: {len(d)} sole-source awards within the limit, "
        f"{money(d['original_value'].sum())} in total",
        f"How the splitting test reads it. Bars are single awards; the line is the running {config.SPLIT_WINDOW_DAYS}-day total. "
        "Names are left out on purpose.")
    ax.bar(d["award_date"], d["original_value"], width=3, color=AMBER)
    ax.plot(running.index, running.values, color=CHARCOAL, lw=1.8, marker="o", ms=4)
    ax.axhline(limit, color=INK, lw=1, ls="--")
    ax.annotate(f"${limit:,} limit for one contract", (d["award_date"].min(), limit), xytext=(0, 4),
                textcoords="offset points", fontsize=8.5)
    ax.yaxis.set_major_formatter(FuncFormatter(money))
    ax.set_ylabel("Value at award")
    ax.set_ylim(0, running.max() * 1.15)
    ax.legend(handles=[Patch(color=AMBER, label="Award flagged as part of a run"),
                       plt.Line2D([], [], color=CHARCOAL, marker="o", ms=4, label=f"Running {config.SPLIT_WINDOW_DAYS}-day total")],
              loc="upper left", fontsize=8.5)
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.grid(axis="x", visible=False)
    save(fig, "08_splitting_example.png")


# ---- 09 Flags by test ------------------------------------------------------------------------

def flags_by_test(R):
    t = pd.DataFrame(R["tests"]).iloc[::-1]
    f = R["flagged"]
    fig, ax = figure(
        f"{f['n_flagged']:,} awards ({f['pct_flagged']:.1f}%) are flagged by at least one of five tests",
        f"{f['n_with_two_or_more']:,} are flagged by two or more. Awards flagged per test, with their value at award.",
        size=(9, 4.2), left=0.25)
    bars = ax.barh(t["test_id"] + "  " + t["test_name"].str.capitalize(), t["n_flagged"], color=CHARCOAL, height=0.6)
    ax.bar_label(bars, labels=[f"{n:,} awards · {money(v)}" for n, v in zip(t["n_flagged"], t["awarded_value_flagged"])],
                 padding=5, fontsize=9)
    ax.set_xlim(0, t["n_flagged"].max() * 1.32)
    ax.xaxis.set_visible(False)
    ax.grid(False)
    ax.spines["bottom"].set_visible(False)
    save(fig, "09_flags_by_test.png")


# ---- 10 Non-competitive share over time ------------------------------------------------------

def non_competitive_by_year(R):
    y = pd.DataFrame(R["by_fiscal_year"])
    # the first fiscal year starts when the limits came in, and the last one is still open
    y.loc[0, "fiscal_year"] += f"\n(from {START:%-d %b})"
    full, part = y.iloc[:-1], y.iloc[-2:]
    peak = full.loc[full["pct_non_competitive"].idxmax()]
    fig, ax = figure(
        f"The non-competitive share of awards rose from {full['pct_non_competitive'].iloc[0]:.1f}% in "
        f"{full['fiscal_year'].iloc[0].splitlines()[0]} to {peak['pct_non_competitive']:.1f}% in {peak['fiscal_year']}",
        "Share of awards made without competition, by fiscal year of award (April to March)", size=(9, 4.4))
    ax.plot(full["fiscal_year"], full["pct_non_competitive"], color=CHARCOAL, lw=2, marker="o")
    ax.plot(part["fiscal_year"], part["pct_non_competitive"], color=CHARCOAL, lw=1.5, ls=":")
    last = y.iloc[-1]
    ax.plot(last["fiscal_year"], last["pct_non_competitive"], marker="o", color=CHARCOAL, mfc="white")
    for _, r in full.iterrows():
        ax.annotate(f"{r['pct_non_competitive']:.1f}%", (r["fiscal_year"], r["pct_non_competitive"]), xytext=(0, 8),
                    textcoords="offset points", ha="center", fontsize=8.5)
    ax.annotate(f"{last['pct_non_competitive']:.1f}%\nyear to date", (last["fiscal_year"], last["pct_non_competitive"]),
                xytext=(0, -24), textcoords="offset points", ha="center", fontsize=8.5, color=MUTED)
    ax.set_ylim(28, 43)
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
    ax.grid(axis="x", visible=False)
    save(fig, "10_non_competitive_by_year.png")


# ---- 11 Sensitivity --------------------------------------------------------------------------

def sensitivity(sens):
    names = {"T1": "T1 splitting\nwindow (days)", "T2": "T2 near limit\nband below the limit",
             "T3": "T3 amendment growth\ngrowth over the award", "T4": "T4 duplicate\nwindow (days)"}
    fig, axes = figure("How many awards each test flags as its cut-off moves",
                       "One cut-off changes at a time. Amber is the setting used in the analysis.",
                       size=(9, 4.4), ncols=4, sharey=False)
    fig.subplots_adjust(wspace=0.42, left=0.07, bottom=0.3)
    for ax, (test, d) in zip(axes, sens.groupby("test_id")):
        labels = [f"{v:.0%}" if v < 1.5 and test in ("T2", "T3") else f"{v:.0f}" for v in d["value"]]
        bars = ax.bar(labels, d["n_flagged"], color=np.where(d["is_base"], AMBER, SILVER), width=0.65)
        ax.bar_label(bars, labels=[f"{n / 1000:.1f}K" for n in d["n_flagged"]], padding=2, fontsize=8)
        ax.set_ylim(0, d["n_flagged"].max() * 1.15)
        ax.set_xlabel(names[test], fontsize=8.5)
        ax.yaxis.set_visible(False)
        ax.grid(False)
        ax.spines["left"].set_visible(False)
    save(fig, "11_sensitivity.png")


# ---- 12 Case study ---------------------------------------------------------------------------

def case_study(summary):
    s = summary.set_index("group")
    panels = [("All awards", "case awards", "CBSA, other awards"),
              (f"Like for like: services of {money(config.CASE_COMPARABLE_MIN)}+, same period",
               "case awards, large services", "CBSA, other large services, same period")]
    measures = [("Flagged by\nany test", "pct_flagged"), ("Amendment\ngrowth (T3)", "pct_T3"),
                ("Possible\nduplicate (T4)", "pct_T4")]
    like, other = s.loc["case awards, large services"], s.loc["CBSA, other large services, same period"]
    fig, axes = figure(
        "Like for like, these awards are flagged about as often as CBSA's other large contracts",
        f"CBSA awards to GC Strategies, Dalian and Coradix, Apr 2020 to Mar 2023. Possible duplicates still stand out: "
        f"{like['pct_T4']:.0f}% against {other['pct_T4']:.0f}%.", size=(9, 4.8), ncols=2, sharey=True)
    fig.subplots_adjust(wspace=0.08)
    x = np.arange(len(measures))
    for ax, (title, case, base) in zip(axes, panels):
        for i, (group, colour, label) in enumerate(((case, AMBER, "ArriveCAN contractors"), (base, CHARCOAL, "Other CBSA awards"))):
            values = [s.loc[group, col] for _, col in measures]
            bars = ax.bar(x + (i - 0.5) * 0.36, values, width=0.34, color=colour,
                          label=f"{label} ({s.loc[group, 'n_awards']:,.0f})")
            ax.bar_label(bars, labels=[f"{v:.0f}%" for v in values], padding=2, fontsize=8.5)
        ax.text(0.02, 0.98, title, transform=ax.transAxes, fontsize=9, color=MUTED, va="top", wrap=True)
        ax.set_xticks(x, [m for m, _ in measures])
        ax.set_ylim(0, 50)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:.0f}%"))
        ax.grid(axis="x", visible=False)
        ax.legend(loc="upper right", fontsize=8, bbox_to_anchor=(1, 0.9))
    save(fig, "12_case_study.png")


# ---- Run them all ----------------------------------------------------------------------------

def main():
    config.FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    P = config.PROCESSED_DIR
    R = json.loads((P / "results.json").read_text())
    bins, summary = pd.read_csv(P / "value_bins.csv"), pd.read_csv(P / "bunching_summary.csv")
    with connect() as con:
        awards = query(con, """
            SELECT owner_org, vendor_id, commodity_type, fiscal_year, award_date, original_value, final_value,
                   n_amendments, is_competitive, t1_splitting, t3_amendment_growth
            FROM vw_award_flags""")

    data_funnel(R)
    under_the_limit(bins, summary, "S", 20_000, 60_000, "02_services_under_limit.png")
    under_the_limit(bins, summary, "G", 10_000, 45_000, "03_goods_under_limit.png")
    non_competitive_share(bins)
    real_against_placebo(summary)
    departments(pd.read_csv(P / "bunching_by_department.csv"))
    amendment_growth(awards, R)
    splitting_example(awards)
    flags_by_test(R)
    non_competitive_by_year(R)
    sensitivity(pd.read_csv(P / "sensitivity.csv"))
    case_study(pd.read_csv(P / "case_study_summary.csv"))
    print(f"wrote {len(list(config.FIGURES_DIR.glob('*.png')))} figures to {config.FIGURES_DIR.relative_to(config.ROOT)}/")


if __name__ == "__main__":
    main()
