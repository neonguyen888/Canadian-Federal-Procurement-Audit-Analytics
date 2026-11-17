"""Draw the dashboard design before building it in Tableau.

Author: Neo Nguyen

Three pages, each drawn from the real data at the size Tableau Public shows them (1600 x 900), in the
dark theme chosen for the dashboard. The images in tableau/design/ are the layout to build from: what
goes on each page, where, and in which colour. Nothing here feeds the analysis.

The layout: a narrow rail on the left for the pages, the method note and the PNG/PDF downloads; a row
of headline cards, each with its trend by fiscal year; a key-finding panel that states the result in
words, the way an audit report opens; then the charts. Every chart title states what the chart shows.

    python tableau/mockup.py
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import to_rgb
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, FancyBboxPatch, Rectangle

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import config  # noqa: E402
from bunching import trend  # noqa: E402
from db import connect, query  # noqa: E402

OUT = config.ROOT / "tableau" / "design"
THEMES = {
    "dark": dict(page="#1F1F27", panel="#2A2A33", rail="#16161C", on_rail="#FFFFFF", ink="#F2F2F5", muted="#A3A3B0",
                 grid="#3A3A46", main="#C9C9D2", second="#5E5E6C", accent="#FFE600", spark="#FFE600", edge="#3A3A46",
                 tint="#32321F"),
}
T: dict = {}                                     # the theme being drawn
PAGES = ("Overview", "Limits", "Queue")
TYPE_NAME = {"S": "Service", "G": "Good", "C": "Construction"}
X0, X1 = 0.07, 0.985                             # left and right edge of the content, right of the rail
KPI_Y, KPI_H = 0.735, 0.13
ROW2, ROW3 = (0.395, 0.32), (0.035, 0.34)        # (y, height) of the two rows of panels
px, py = 1 / 1600, 1 / 900                       # one pixel, as a fraction of the page


def money(v: float) -> str:
    for unit, size in (("B", 1e9), ("M", 1e6), ("K", 1e3)):
        if abs(v) >= size:
            return f"${v / size:,.1f}".rstrip("0").rstrip(".") + unit
    return f"${v:,.0f}"


def clip(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1].rstrip(" ,") + "…"


def short_year(fy: str) -> str:
    return fy[:4] + "-" + fy[7:]


def faded(colour: str, alpha: float):
    return (*to_rgb(colour), alpha)


# ---- The rail: pages, method note, downloads ------------------------------------------------

def icon(fig, kind: str, cx: float, cy: float, colour):
    """A 20-pixel line icon centred on (cx, cy), drawn from simple shapes."""
    def line(xs, ys, lw=1.6):
        fig.add_artist(Line2D([cx + x * px for x in xs], [cy + y * py for y in ys], color=colour, lw=lw,
                              solid_capstyle="round", transform=fig.transFigure))
    if kind == "Overview":                       # four tiles
        for dx in (-5, 5):
            for dy in (-5, 5):
                fig.add_artist(Rectangle((cx + (dx - 4) * px, cy + (dy - 4) * py), 8 * px, 8 * py, fill=False,
                                         ec=colour, lw=1.4, transform=fig.transFigure))
    elif kind == "Limits":                       # bars rising to a limit line
        for dx, h in ((-7, 6), (-2, 9), (3, 16)):
            fig.add_artist(Rectangle((cx + (dx - 2) * px, cy - 8 * py), 4 * px, h * py, color=colour,
                                     transform=fig.transFigure))
        line([7, 7], [-9, 9])
    elif kind == "Queue":                        # a ranked list
        for dy in (6, 0, -6):
            line([-9, -6], [dy, dy], lw=2)
            line([-3, 9], [dy, dy])
    elif kind == "Method":                       # an "i" in a circle
        fig.add_artist(Circle((cx, cy), 9 * px, fill=False, ec=colour, lw=1.4, transform=fig.transFigure))
        line([0, 0], [-4, 2])
        line([0, 0], [5, 5.5], lw=2.2)
    else:                                        # download: an arrow into a tray
        line([0, 0], [8, -3])
        line([-4, 0, 4], [1, -3, 1])
        line([-8, -8, 8, 8], [-4, -8, -8, -4])


def rail(fig, active: int):
    fig.add_artist(Rectangle((0, 0), 0.052, 1, color=T["rail"], transform=fig.transFigure, zorder=-2))
    fig.add_artist(Rectangle((0.0175, 0.935), 28 * px, 28 * py, color=T["spark"], transform=fig.transFigure))
    for i, name in enumerate(PAGES):
        y = 0.83 - i * 0.105
        on = i == active
        if on:
            fig.add_artist(Rectangle((0, y - 0.04), 4 * px, 0.08, color=T["spark"], transform=fig.transFigure))
        icon(fig, name, 0.026, y + 0.012, T["spark"] if on else faded(T["on_rail"], 0.55))
        fig.text(0.026, y - 0.025, name, color=T["on_rail"], alpha=1 if on else 0.55, fontsize=8, ha="center",
                 fontweight="bold" if on else "normal")
    fig.add_artist(Line2D([0.012, 0.04], [0.47, 0.47], color=T["on_rail"], alpha=0.2, lw=1, transform=fig.transFigure))
    for i, name in enumerate(("Method", "PNG", "PDF")):
        y = 0.25 - i * 0.09
        icon(fig, name, 0.026, y + 0.012, faded(T["on_rail"], 0.7))
        fig.text(0.026, y - 0.025, name, color=T["on_rail"], alpha=0.7, fontsize=8, ha="center")


# ---- Page furniture ------------------------------------------------------------------------

def page(question: str, filters: list[str], active: int, note: str):
    fig = plt.figure(figsize=(16, 9), facecolor=T["page"])
    rail(fig, active)
    fig.text(X0, 0.948, "Federal procurement review", color=T["ink"], fontsize=20, fontweight="bold", va="center")
    fig.text(X0, 0.902, question, color=T["muted"], fontsize=10.5, va="center")
    for i, label in enumerate(filters[::-1]):
        x = X1 - (i + 1) * 0.122 + 0.008
        fig.add_artist(FancyBboxPatch((x, 0.933), 0.114, 0.03, boxstyle="round,pad=0,rounding_size=0.004",
                                      fc=T["panel"], ec=T["edge"], lw=1, transform=fig.transFigure))
        fig.text(x + 0.007, 0.948, label, color=T["ink"], fontsize=9, va="center")
        cx = x + 0.103                           # a small chevron, drawn rather than typed
        fig.add_artist(Line2D([cx - 0.004, cx, cx + 0.004], [0.951, 0.945, 0.951], color=T["muted"], lw=1.1,
                              transform=fig.transFigure))
    fig.text(X1, 0.902, note, color=T["muted"], fontsize=9, ha="right", va="center")
    fig.text(X0, 0.012, "Source: Government of Canada, Proactive Publication of Contracts over $10,000 (open.canada.ca). "
             "A flag marks an award for review. It is not a finding of wrongdoing.", color=T["muted"], fontsize=8)
    return fig


def box(fig, rect, accent_bar: bool = False, fill: str | None = None):
    x, y, w, h = rect
    fig.add_artist(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.004", fc=fill or T["panel"],
                                  ec=T["edge"], lw=0.8, transform=fig.transFigure, zorder=-1))
    if accent_bar:
        fig.add_artist(Rectangle((x, y), 4 * px, h, color=T["accent"], transform=fig.transFigure, zorder=-0.5))


def panel(fig, rect, title: str, subtitle: str = "", pad=(0.04, 0.045, 0.015, 0.09)):
    """A panel whose title states the finding; returns the axes inside it. rect = (x, y, w, h)."""
    x, y, w, h = rect
    box(fig, rect)
    fig.text(x + 0.012, y + h - 0.03, title, color=T["ink"], fontsize=11, fontweight="bold", va="center")
    fig.text(x + 0.012, y + h - 0.057, subtitle, color=T["muted"], fontsize=8.6, va="center")
    left, bottom, right, top = pad
    ax = fig.add_axes((x + left, y + bottom, w - left - right, h - bottom - top), facecolor="none")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(T["edge"])
    ax.tick_params(colors=T["muted"], labelsize=8.3, length=0)
    ax.grid(color=T["grid"], lw=0.8)
    ax.set_axisbelow(True)
    return ax


def kpi_cards(fig, cards: list[dict]):
    """Headline cards. Each is a dict with label, value, note, and optionally highlight (bool) and
    mini (a function that draws a small trend or comparison into the card)."""
    gap = 0.01
    w = (X1 - X0 - gap * (len(cards) - 1)) / len(cards)
    for i, c in enumerate(cards):
        x = X0 + i * (w + gap)
        box(fig, (x, KPI_Y, w, KPI_H), accent_bar=c.get("highlight", False))
        fig.text(x + 0.012, KPI_Y + KPI_H - 0.024, c["label"], color=T["muted"], fontsize=9, va="center")
        fig.text(x + 0.012, KPI_Y + 0.066, c["value"], color=T["accent"] if c.get("highlight") else T["ink"],
                 fontsize=21, fontweight="bold", va="center")
        fig.text(x + 0.012, KPI_Y + 0.02, c["note"], color=T["muted"], fontsize=8.2, va="center")
        if c.get("mini"):
            ax = fig.add_axes((x + w * 0.58, KPI_Y + 0.042, w * 0.38, 0.05), facecolor="none")
            ax.axis("off")
            c["mini"](ax)


def spark(values):
    """A sparkline over complete fiscal years, the latest year marked."""
    def draw(ax):
        v = list(values)
        ax.plot(range(len(v)), v, color=T["main"], lw=1.6)
        ax.plot(len(v) - 1, v[-1], "o", ms=4.5, color=T["accent"])
        ax.margins(x=0.06, y=0.2)
    return draw


def mini_bars(values, colours):
    def draw(ax):
        ax.bar(range(len(values)), values, color=colours, width=0.75)
        ax.margins(x=0.04)
    return draw


def mini_compare(values, labels, colours):
    """Two or three thin horizontal bars with short labels: a comparison that fits inside a card."""
    def draw(ax):
        y = np.arange(len(values))[::-1]
        ax.barh(y, values, color=colours, height=0.42)
        for yi, v, label in zip(y, values, labels):
            ax.text(max(values) * 1.04, yi, label, fontsize=7.4, color=T["muted"], va="center")
        ax.set_xlim(0, max(values) * 2.6)
        ax.set_ylim(-0.6, len(values) - 0.4)
    return draw


def finding(fig, rect, heading: str, paragraphs: list[str], next_step: tuple[str, str]):
    """The key-finding panel: what the data shows, in sentences, and where a reviewer should start."""
    x, y, w, h = rect
    box(fig, rect, accent_bar=True, fill=T["tint"])
    fig.text(x + 0.016, y + h - 0.03, heading, color=T["accent"], fontsize=10.5, fontweight="bold", va="center")
    width = int(w * 1600 / 6.8)                  # about how many characters fit on a line at 9.3 pt
    top = y + h - 0.058
    for text in paragraphs:
        wrapped = textwrap.fill(text, width)
        fig.text(x + 0.016, top, wrapped, color=T["ink"], fontsize=9.3, va="top", linespacing=1.38)
        top -= (wrapped.count("\n") + 1) * 0.0225 + 0.014
    label, text = next_step
    fig.add_artist(Line2D([x + 0.016, x + w - 0.016], [top + 0.006] * 2, color=T["edge"], lw=1, transform=fig.transFigure))
    fig.text(x + 0.016, top - 0.012, label, color=T["ink"], fontsize=9.3, fontweight="bold", va="top")
    fig.text(x + 0.016, top - 0.037, textwrap.fill(text, width), color=T["ink"], fontsize=9.3, va="top", linespacing=1.4)


def save(fig, name: str, theme: str):
    fig.savefig(OUT / f"{name}_{theme}.png", dpi=100, facecolor=T["page"])
    plt.close(fig)


# ---- Page 1: overview ------------------------------------------------------------------------

def overview(R, D, theme, note):
    w, f = R["window"], R["flagged"]
    yrs = D["years"]
    full = yrs[(yrs["fiscal_year"] > yrs["fiscal_year"].min()) & (yrs["fiscal_year"] < yrs["fiscal_year"].max())]
    last, prev = full.iloc[-1], full.iloc[-2]
    start = pd.Timestamp(config.ANALYSIS_START)
    fig = page(f"Where the money went and what the tests flagged. Awards over $10,000 from {start.day} {start:%B %Y}.",
               ["Fiscal year: All", "Department: All", "Commodity: All"], 0, note)
    kpi_cards(fig, [
        dict(label="Awards analysed", value=f"{w['n_awards']:,}",
             note=f"{short_year(last['fiscal_year'])}: {last['n']:,}, {last['n'] / prev['n'] - 1:+.1%} on prior year",
             mini=spark(full["n"])),
        dict(label="Value at award", value=money(w["awarded_value"]),
             note=f"{money(w['current_value'])} after amendments", mini=spark(full["value"])),
        dict(label="Awarded without competition", value=f"{w['pct_non_competitive']:.1f}%",
             note=f"{short_year(last['fiscal_year'])}: {last['pct_nc']:.1f}%, {last['pct_nc'] - prev['pct_nc']:+.1f} pts on prior year",
             mini=spark(full["pct_nc"])),
        dict(label="Flagged for review", value=f"{f['n_flagged']:,}", highlight=True,
             note=f"{f['pct_flagged']:.1f}%; recent awards have had less time to grow",
             mini=spark(full["pct_flagged"])),
        dict(label="Value flagged", value=money(f["awarded_value_flagged"]),
             note=f"{f['n_with_two_or_more']:,} awards flagged by two or more tests", mini=spark(full["flagged_value"])),
    ])

    tests = pd.DataFrame(R["tests"]).set_index("test_id")
    t3_share = tests.loc["T3", "awarded_value_flagged"] / f["awarded_value_flagged"]
    finding(fig, (X0, *ROW2[:1], 0.31, ROW2[1]), "Key finding", [
        f"About 1 in {round(100 / f['pct_flagged'])} federal awards ({f['pct_flagged']:.1f}%) matches a pattern worth a "
        f"reviewer's time. {t3_share:.0%} of the value flagged comes from contracts that grew through amendments.",
        f"Service contracts pile up just under the $40,000 limit for sole-sourcing: "
        f"{R['services_near_limit']['n_last_1000']:,} awards in the last $1,000 before it.",
    ], ("Where to start", f"The {len(D['queue'])} highest-scoring awards were each sole-sourced within the limit, sit in "
                          f"a run of awards to the same vendor, and were amended past the limit."))

    # value by fiscal quarter, January to March highlighted
    q = D["quarters"]
    avg = q[q["fiscal_year"] > q["fiscal_year"].min()].groupby("fiscal_quarter")["awarded_value"].mean()
    ax = panel(fig, (X0 + 0.32, *ROW2[:1], X1 - X0 - 0.32, ROW2[1]),
               f"January to March is the biggest quarter: {money(avg['Q4'])} on average, against {money(avg['Q2'])} in July to September",
               "Value at award by fiscal quarter. Highlighted: Q4, the last quarter of the fiscal year.")
    ax.bar(range(len(q)), q["awarded_value"] / 1e9, color=np.where(q["fiscal_quarter"] == "Q4", T["accent"], T["main"]), width=0.72)
    ticks = [i for i, fq in enumerate(q["fiscal_quarter"]) if fq == "Q1"]
    ax.set_xticks(ticks, q["fiscal_year"].iloc[ticks].map(short_year))
    ax.yaxis.set_major_formatter(lambda v, _: f"${v:.0f}B")
    ax.grid(axis="x", visible=False)

    # flags by test
    t = tests.iloc[::-1]
    ax = panel(fig, (X0, *ROW3[:1], 0.27, ROW3[1]), f"Amendment growth covers {t3_share:.0%} of the value flagged",
               "Awards flagged by each test, and their value at award.", pad=(0.105, 0.03, 0.015, 0.09))
    bars = ax.barh(t["test_name"].str.capitalize(), t["n_flagged"],
                   color=[T["accent"] if i == "T3" else T["main"] for i in t.index], height=0.56)
    ax.bar_label(bars, labels=[f"{n:,}  {money(v)}" for n, v in zip(t["n_flagged"], t["awarded_value_flagged"])],
                 padding=4, fontsize=8.2, color=T["ink"])
    ax.set_xlim(0, t["n_flagged"].max() * 1.75)
    ax.xaxis.set_visible(False)
    ax.grid(False)
    ax.spines["bottom"].set_visible(False)

    # departments: flag rate against the average, ranked by flagged awards
    d = D["departments"].nlargest(8, "n_flagged").reset_index(drop=True)
    x = X0 + 0.28
    ax = panel(fig, (x, *ROW3[:1], 0.385, ROW3[1]),
               f"Flag rate by department, against the {f['pct_flagged']:.1f}% average",
               "The eight departments with the most flagged awards, most first. Amber: above average.",
               pad=(0.175, 0.03, 0.02, 0.09))
    y = np.arange(len(d))[::-1]
    ax.barh(y, d["pct_flagged"], color=np.where(d["pct_flagged"] > f["pct_flagged"], T["accent"], T["main"]), height=0.5)
    ax.axvline(f["pct_flagged"], color=T["ink"], lw=1.2, ls=(0, (2, 2)), zorder=2)
    ax.text(f["pct_flagged"], len(d) - 0.45, f" average {f['pct_flagged']:.1f}%", color=T["muted"], fontsize=8, va="bottom")
    for yi, (_, r) in zip(y, d.iterrows()):
        ax.text(r["pct_flagged"] + 0.4, yi, f"{r['pct_flagged']:.0f}%  ({r['n_flagged']:,})", fontsize=8.2,
                color=T["ink"], va="center", zorder=3, bbox=dict(boxstyle="square,pad=0.15", fc=T["panel"], ec="none"))
        ax.text(-0.86, yi, str(len(d) - yi), transform=ax.get_yaxis_transform(), fontsize=7.5, color=T["panel"],
                ha="center", va="center", fontweight="bold", bbox=dict(boxstyle="circle,pad=0.3", fc=T["main"], ec="none"))
        ax.text(-0.8, yi, clip(r["department"], 34), transform=ax.get_yaxis_transform(), fontsize=8.2,
                color=T["ink"], ha="left", va="center")
    ax.set_xlim(0, d["pct_flagged"].max() * 1.35)
    ax.set_ylim(-0.6, len(d) - 0.1)
    ax.set_yticks([])
    ax.xaxis.set_visible(False)
    ax.grid(False)
    ax.spines["bottom"].set_visible(False)

    # non-competitive share by fiscal year
    yy = pd.DataFrame(R["by_fiscal_year"]).iloc[:-1]
    peak = yy["pct_non_competitive"].idxmax()
    x = X0 + 0.675
    ax = panel(fig, (x, *ROW3[:1], X1 - x, ROW3[1]),
               f"Sole-sourcing peaked at {yy.loc[peak, 'pct_non_competitive']:.1f}%",
               "Share of awards made without competition.", pad=(0.035, 0.045, 0.012, 0.09))
    ax.plot(range(len(yy)), yy["pct_non_competitive"], color=T["main"], lw=2.2, marker="o", ms=4)
    ax.plot(peak, yy.loc[peak, "pct_non_competitive"], "o", ms=7, color=T["accent"])
    for i, v in enumerate(yy["pct_non_competitive"]):
        ax.annotate(f"{v:.1f}", (i, v), xytext=(0, 7), textcoords="offset points", ha="center", fontsize=7.8,
                    color=T["accent"] if i == peak else T["ink"], fontweight="bold" if i == peak else "normal")
    ax.set_xticks(range(len(yy)), [fy[2:4] + "-" + fy[7:] for fy in yy["fiscal_year"]], fontsize=7.8)
    ax.set_ylim(31, 42)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")
    ax.grid(axis="x", visible=False)
    save(fig, "1_overview", theme)


# ---- Page 2: limits and departments ----------------------------------------------------------

def limits(R, D, theme, note):
    est = D["summary"][(D["summary"]["commodity_type"] == "S") & (D["summary"]["limit_kind"] == "real")].set_index("group")
    placebo = D["summary"].query("commodity_type == 'S' and limit_kind == 'placebo' and group == 'all'")["ratio"]
    near, past = R["services_near_limit"], R["amended_past_limit"]
    b = (D["bins"][D["bins"]["commodity_type"] == "S"].pivot(index="bin_start", columns="group", values="n_awards")
         .fillna(0))
    total = b.sum(axis=1)
    around = total.loc[30_000:44_999]
    fig = page("Do service awards pile up under the $40,000 limit that requires bids? Government Contracts Regulations s.6(b).",
               ["Commodity: Services"], 1, note)
    kpi_cards(fig, [
        dict(label="Awards in the last $5,000 up to $40,000", value=f"{est.loc['all', 'observed']:,.0f}",
             note=f"the trend from the values below predicts {est.loc['all', 'expected']:,.0f}",
             mini=mini_bars(around.values, [T["accent"] if v == 39_000 else T["second"] for v in around.index])),
        dict(label="All service awards, against the trend", value=f"{est.loc['all', 'ratio']:.2f}x",
             note=f"95% interval {est.loc['all', 'ci_lo']:.2f}x to {est.loc['all', 'ci_hi']:.2f}x"),
        dict(label="Sole-sourced awards, against the trend", value=f"{est.loc['non_competitive', 'ratio']:.2f}x", highlight=True,
             note=f"competed awards: {est.loc['competitive', 'ratio']:.2f}x",
             mini=mini_compare([est.loc["non_competitive", "ratio"], est.loc["competitive", "ratio"]],
                               ["sole-sourced", "competed"], [T["accent"], T["second"]])),
        dict(label="Where no rule changes ($60K to $90K)", value=f"{placebo.min():.2f}x to {placebo.max():.2f}x",
             note="what round numbers produce on their own"),
        dict(label="Sole-sourced, then amended past the limit", value=f"{past['n_awards']:,}",
             note=f"{money(past['awarded_value'])} at award, {money(past['current_value'])} now",
             mini=mini_compare([past["awarded_value"], past["current_value"]], ["at award", "now"],
                               [T["second"], T["accent"]])),
    ])

    finding(fig, (X0, *ROW2[:1], 0.31, ROW2[1]), "Key finding", [
        f"Service awards pile up just under the $40,000 limit: {est.loc['all', 'observed']:,.0f} in the last $5,000, "
        f"where the trend from the values below predicts {est.loc['all', 'expected']:,.0f}.",
        f"The excess comes from sole-sourced awards ({est.loc['non_competitive', 'ratio']:.2f}x the trend). Competed awards "
        f"({est.loc['competitive', 'ratio']:.2f}x) sit close to the {placebo.min():.2f}x to {placebo.max():.2f}x that round "
        f"numbers produce where no rule changes.",
    ], ("What to review", f"{past['n_awards']:,} awards sole-sourced within the limit and later amended past it, "
                          f"{past['n_over_double_the_limit']:,} of them to more than double the limit."))

    # awards per $1,000 around the limit, with the trend and the spike labelled
    b = b.loc[20_000:59_999]
    other = b.sum(axis=1) - b["non_competitive"]
    tot = b.sum(axis=1)
    ax = panel(fig, (X0 + 0.32, *ROW2[:1], X1 - X0 - 0.32, ROW2[1]),
               "Service awards jump in the last $1,000 before the $40,000 limit",
               "Awards per $1,000 of value, sole-sourced stacked on competed. Dashed: the trend from the values below.")
    ax.axvspan(35_000, 40_000, color=T["spark"], alpha=0.08, lw=0, zorder=0)
    ax.bar(b.index + 500, other, width=840, color=T["second"])
    ax.bar(b.index + 500, b["non_competitive"], bottom=other, width=840, color=T["main"])
    span = tot.loc[40_000 - config.BUNCH_WINDOW - config.BUNCH_FIT_SPAN:39_999]
    ax.plot(span.index + 500, trend(span.to_numpy()), color=T["accent"], lw=2, ls="--")
    ax.axvline(40_000, color=T["accent"], lw=1.6)
    peak = tot.loc[39_000]
    ax.annotate(f"{near['n_last_1000']:,} awards between\n$39,000 and $40,000", (39_500, peak), xytext=(46_000, peak * 0.86),
                fontsize=9, color=T["ink"], fontweight="bold", va="center", arrowprops=dict(arrowstyle="-", color=T["muted"], lw=0.8))
    ax.annotate(f"about {near['n_per_1000_before_that']:,.0f} in each\n$1,000 before that", (37_000, tot.loc[37_000]),
                xytext=(46_000, peak * 0.52), fontsize=9, color=T["muted"], va="center",
                arrowprops=dict(arrowstyle="-", color=T["muted"], lw=0.8))
    ax.set_xlim(20_000, 60_000)
    ax.xaxis.set_major_formatter(lambda v, _: f"${v / 1000:.0f}K")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:,.0f}")
    ax.grid(axis="x", visible=False)

    # sole-source share by value
    wide = D["bins"].pivot_table(index=["commodity_type", "bin_start"], columns="group", values="n_awards", fill_value=0)
    share = (wide["non_competitive"] / wide.sum(axis=1)).unstack(0).loc[10_000:79_999]
    ax = panel(fig, (X0, *ROW3[:1], 0.38, ROW3[1]),
               f"{near['pct_non_competitive_last_5000']:.0f}% are sole-sourced just under the limit, "
               f"{near['pct_non_competitive_next_5000']:.0f}% just above",
               "Sole-sourced share by $1,000 of value. Solid: services ($40K). Dashed: goods ($25K).")
    ax.plot(share.index + 500, 100 * share["S"], color=T["main"], lw=2.2)
    ax.plot(share.index + 500, 100 * share["G"], color=T["main"], lw=1.5, ls="--", alpha=0.7)
    for limit in (25_000, 40_000):
        ax.axvline(limit, color=T["accent"], lw=1.4)
    ax.set_xlim(10_000, 80_000)
    ax.set_ylim(0, 85)
    ax.xaxis.set_major_formatter(lambda v, _: f"${v / 1000:.0f}K")
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0f}%")

    # department excess against each department's own placebo range
    s = R["departments_services"]
    e = D["by_department"][D["by_department"]["commodity_type"] == "S"].nlargest(10, "ratio").iloc[::-1].reset_index(drop=True)
    clear = e["ci_lo"] > e["placebo_hi"]
    x = X0 + 0.39
    ax = panel(fig, (x, *ROW3[:1], X1 - x, ROW3[1]),
               f"{s['n_interval_above_own_placebo']} of {s['n_estimated']} departments sit clear of their own round-number range",
               "Ten largest excesses: multiple of the department's own trend, 95% interval. Grey: its range at $60K to $90K.",
               pad=(0.2, 0.06, 0.02, 0.09))
    for i, r in e.iterrows():
        ax.plot([r["placebo_lo"], r["placebo_hi"]], [i, i], color=T["grid"], lw=7, solid_capstyle="butt", zorder=1)
    ax.errorbar(e["ratio"], e.index, xerr=[e["ratio"] - e["ci_lo"], e["ci_hi"] - e["ratio"]], fmt="none",
                ecolor=T["second"], capsize=2, lw=1.1, zorder=2)
    ax.scatter(e["ratio"], e.index, color=np.where(clear, T["accent"], T["main"]), s=34, zorder=3)
    ax.axvline(1, color=T["muted"], lw=0.8)
    ax.set_yticks(e.index, e["department"].map(lambda v: clip(v, 40)), fontsize=8)
    ax.set_xlim(0, 9)
    ax.set_xlabel("Observed awards as a multiple of the trend (1 = no excess)", color=T["muted"], fontsize=8.3)
    ax.grid(axis="y", visible=False)
    save(fig, "2_limits", theme)


# ---- Page 3: review queue --------------------------------------------------------------------

def review_queue(R, D, theme, note):
    f, q = R["flagged"], D["queue"]
    s = D["scores"]
    under = s[s.index < 30].sum() / s.sum()
    fig = page("Which awards to look at first. Flagged awards ranked by risk score: flag weights, scaled up for larger awards.",
               ["Department: All", "Test: All", "Minimum score: 0"], 2, note)
    buckets = list(range(0, 80, 5))
    kpi_cards(fig, [
        dict(label="Flagged awards in the queue", value=f"{f['n_flagged']:,}", note=f"{f['pct_flagged']:.1f}% of all awards"),
        dict(label="Flagged by two or more tests", value=f"{f['n_with_two_or_more']:,}", highlight=True,
             note="the strongest candidates"),
        dict(label="Value at award in the queue", value=money(f["awarded_value_flagged"]), note="before amendments"),
        dict(label="Highest risk score", value=f"{q['risk_score'].iloc[0]:.1f}", note=f"out of 100; {under:.0%} score under 30",
             mini=mini_bars(s.reindex(buckets, fill_value=0).values ** 0.35,
                            [T["accent"] if v >= 60 else T["second"] for v in buckets])),
        dict(label="Checked two ways", value=f"{R['reconciliation']['n_matching']} of {R['reconciliation']['n_checks']}",
             note="checks where SQL and pandas agree"),
    ])

    ax = panel(fig, (X0, 0.035, 0.6, 0.68), "Highest scores first",
               "Vendor names are hidden in this public version. Click a row to see why it is flagged.",
               pad=(0.01, 0.012, 0.01, 0.075))
    ax.axis("off")
    cols = [("#", 0.0, "left"), ("Department", 0.035, "left"), ("Vendor", 0.38, "left"), ("Type", 0.47, "left"),
            ("At award", 0.63, "right"), ("Now", 0.71, "right"), ("Change", 0.79, "right"), ("Tests", 0.815, "left"),
            ("Score", 1.0, "right")]
    for name, x, ha in cols:
        ax.text(x, 0.975, name, color=T["muted"], fontsize=8.8, ha=ha, va="center", fontweight="bold")
    ax.plot([0, 1], [0.952, 0.952], color=T["edge"], lw=1)
    row_h = 0.92 / len(q)
    for i, r in q.iterrows():
        y = 0.92 - i * row_h
        if i == 0:
            ax.add_patch(Rectangle((-0.006, y - row_h / 2), 1.012, row_h, color=T["accent"], alpha=0.12, lw=0))
        change = r["final_value"] / r["original_value"] - 1
        cells = [str(r["risk_rank"]), clip(r["department"], 44), f"Vendor {chr(65 + i)}", TYPE_NAME[r["commodity_type"]],
                 money(r["original_value"]), money(r["final_value"]), f"+{change:.0%}"]
        for (name, x, ha), text in zip(cols[:7], cells):
            ax.text(x, y, text, color=T["accent"] if name == "Change" else T["ink"], fontsize=9, ha=ha, va="center")
        for j, test in enumerate(("t1", "t2", "t3", "t4", "t5")):
            on = bool(r[test])
            ax.text(0.828 + j * 0.03, y, f"T{j + 1}", fontsize=7.6, ha="center", va="center",
                    color=T["panel"] if on else T["muted"], fontweight="bold" if on else "normal",
                    bbox=dict(boxstyle="round,pad=0.28", fc=T["accent"] if on else "none",
                              ec=T["accent"] if on else T["edge"], lw=0.8))
        ax.text(1.0, y, f"{r['risk_score']:.1f}", color=T["ink"], fontsize=9.8, ha="right", va="center", fontweight="bold")
        ax.plot([0, 1], [y - row_h / 2, y - row_h / 2], color=T["grid"], lw=0.7)
    ax.set_xlim(-0.006, 1.006)
    ax.set_ylim(0, 1)

    x = X0 + 0.61
    finding(fig, (x, 0.47, X1 - x, 0.245), "Start here", [
        f"{under:.0%} of the queue scores under 30. The {len(q)} awards shown score above {q['risk_score'].min():.0f}: "
        f"each was sole-sourced within the limit, sits in a run of awards to the same vendor, and was amended past the limit.",
    ], ("Next step", "Open the contract file and check the reason given for each amendment."))

    top = q.iloc[0]
    ax = panel(fig, (x, 0.035, X1 - x, 0.415), "Why award #1 is flagged",
               f"{clip(top['department'], 44)}, {TYPE_NAME[top['commodity_type']].lower()}",
               pad=(0.013, 0.015, 0.013, 0.08))
    ax.axis("off")
    for i, line in enumerate(top["flag_details"].split(" | ")[:4]):
        test, text = line.split(": ", 1)
        ax.text(0, 0.86 - i * 0.24, test, fontsize=8.5, color=T["panel"], va="center", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.3", fc=T["accent"], ec="none"))
        ax.text(0.1, 0.86 - i * 0.24, textwrap.fill(text, 52), fontsize=8.6, color=T["ink"], va="center", linespacing=1.35)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    save(fig, "3_queue", theme)


# ---- Run -------------------------------------------------------------------------------------

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob("*.png"):                # drafts are redrawn from scratch each time
        old.unlink()
    P = config.PROCESSED_DIR
    R = json.loads((P / "results.json").read_text())
    with connect() as con:
        D = {
            "years": query(con, """
                SELECT fiscal_year, count(*) AS n, sum(original_value) AS value,
                       100.0 * count(*) FILTER (WHERE NOT is_competitive) / count(*) AS pct_nc,
                       100.0 * count(*) FILTER (WHERE n_flags > 0) / count(*) AS pct_flagged,
                       sum(original_value) FILTER (WHERE n_flags > 0) AS flagged_value
                FROM vw_award_flags GROUP BY 1 ORDER BY 1"""),
            "quarters": query(con, """SELECT fiscal_year, fiscal_quarter, sum(original_value) AS awarded_value FROM awards
                                      WHERE fiscal_year < '2026-2027' GROUP BY 1, 2 ORDER BY 1, 2"""),
            "departments": query(con, """
                SELECT department, count(*) AS n_awards, count(*) FILTER (WHERE n_flags > 0) AS n_flagged,
                       100.0 * count(*) FILTER (WHERE n_flags > 0) / count(*) AS pct_flagged
                FROM vw_award_flags GROUP BY 1"""),
            "queue": query(con, """
                SELECT r.risk_rank, f.department, f.commodity_type, f.original_value, f.final_value, f.flag_details,
                       f.t1_splitting AS t1, f.t2_near_limit AS t2, f.t3_amendment_growth AS t3, f.t4_duplicate AS t4,
                       f.t5_concentration AS t5, r.risk_score
                FROM risk_scores r JOIN vw_award_flags f USING (owner_org, contract_key)
                WHERE r.risk_rank <= 13 ORDER BY r.risk_rank"""),
            "scores": query(con, """SELECT floor(risk_score / 5) * 5 AS bucket, count(*) AS n FROM risk_scores
                                    WHERE risk_score > 0 GROUP BY 1 ORDER BY 1""").set_index("bucket")["n"],
        }
    D["summary"], D["bins"] = pd.read_csv(P / "bunching_summary.csv"), pd.read_csv(P / "value_bins.csv")
    D["by_department"] = pd.read_csv(P / "bunching_by_department.csv")
    as_of = pd.Timestamp(R["source"]["portal_last_modified"])
    note = f"Data from open.canada.ca, as of {as_of.day} {as_of:%B %Y}"

    plt.rcParams.update({"font.family": "sans-serif", "font.sans-serif": ["Helvetica Neue", "Helvetica", "Arial", "DejaVu Sans"],
                         "text.parse_math": False})
    for theme, colours in THEMES.items():
        T.clear()
        T.update(colours)
        overview(R, D, theme, note)
        limits(R, D, theme, note)
        review_queue(R, D, theme, note)
    print(f"wrote {len(list(OUT.glob('*.png')))} design drafts to {OUT.relative_to(config.ROOT)}/")


if __name__ == "__main__":
    main()
