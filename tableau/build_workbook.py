"""Write the Tableau workbook tableau/procurement_review.twb from the files in data/tableau.

Author: Neo Nguyen

A .twb file is XML. Writing it from code means every run of the pipeline rebuilds the dashboard on the
latest data, and the text on it (key findings, chart titles, the data date) is filled from
data/processed/results.json instead of being typed in by hand. Open the file in Tableau Desktop or
Tableau Public; the three pages are Overview, Limits and Queue.

    .venv/bin/python tableau/build_workbook.py
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tableau" / "procurement_review.twb"
DATA_DIR = "../data/tableau"     # relative to the workbook, so the file opens on any machine
PAGES = ["Overview", "Limits", "Queue"]

USER = "http://www.tableausoftware.com/xml/user"
ET.register_namespace("user", USER)

BG, PANEL, RAIL = "#1f1f27", "#2a2a33", "#16161c"
TEXT, MARK, TEXT2 = "#f2f2f5", "#c9c9d2", "#a3a3b0"
GREY, GRID, YELLOW, KEYFILL = "#5e5e6c", "#3a3a46", "#ffe600", "#32321f"
FONT, FONT_B = "Tableau Book", "Tableau Semibold"
W, H = 1600, 900            # layout is drawn on a 1600 x 900 grid ...
SIZE_W, SIZE_H = 1440, 810  # ... and shown at 1440 x 810, so it fits a laptop screen in presentation mode
FS = SIZE_W / W             # font sizes scale with it


def facts():
    """Every number and claim the dashboard text uses, read from the run, so the text follows the data."""
    import json
    from datetime import datetime
    import pandas as pd
    R = json.loads((ROOT / "data" / "processed" / "results.json").read_text())
    a = pd.read_csv(ROOT / "data" / "tableau" / "awards.csv", low_memory=False,
                    usecols=["fiscal_year", "fiscal_quarter", "value_at_award", "is_flagged", "risk_score",
                             "risk_rank", "t1_splitting", "t2_near_limit", "t3_amendment_growth"])
    open_year, first_year = a.fiscal_year.max(), a.fiscal_year.min()      # the year still open, the part year
    full = a[~a.fiscal_year.isin([open_year, first_year])]
    q_avg = full.groupby(["fiscal_year", "fiscal_quarter"]).value_at_award.sum().groupby("fiscal_quarter").mean()
    real = {x["group"]: x for x in R["bunching"] if x["commodity_type"] == "S" and x["limit_kind"] == "real"}
    placebo = [x["ratio"] for x in R["bunching"]
               if x["commodity_type"] == "S" and x["limit_kind"] == "placebo" and x["group"] == "all"]
    closed = [y for y in R["by_fiscal_year"] if y["fiscal_year"] != open_year]
    peak = max(closed, key=lambda y: y["pct_non_competitive"])
    tests = {t["test_id"]: t for t in R["tests"]}
    flagged = a[a.is_flagged == 1]
    top = flagged.nsmallest(13, "risk_rank")
    return {
        "date": datetime.fromisoformat(R["source"]["portal_last_modified"]).strftime("%-d %B %Y"),
        "pct": R["flagged"]["pct_flagged"],
        "one_in": round(100 / R["flagged"]["pct_flagged"]),
        "t3_value_share": tests["T3"]["awarded_value_flagged"] / R["flagged"]["awarded_value_flagged"],
        "most_flags": max(tests.values(), key=lambda t: t["n_flagged"])["test_name"],
        "n_last_1000": R["services_near_limit"]["n_last_1000"],
        "obs": real["all"]["observed"], "exp": real["all"]["expected"],
        "nc": real["non_competitive"]["ratio"], "comp": real["competitive"]["ratio"],
        "pl_lo": min(placebo), "pl_hi": max(placebo),
        "apl": R["amended_past_limit"]["n_awards"], "apl_double": R["amended_past_limit"]["n_over_double_the_limit"],
        "under_30": (flagged.risk_score < 30).mean(),
        "q4_biggest": q_avg.idxmax() == "Q4",
        "peak_year": peak["fiscal_year"][:5] + peak["fiscal_year"][-2:],
        "top_pattern": bool((top.t1_splitting & top.t2_near_limit & top.t3_amendment_growth).all()),
    }


F = facts()


def el(tag, attrib=None, *children, text=None):
    e = ET.Element(tag, {k: str(v) for k, v in (attrib or {}).items() if v is not None})
    for c in children:
        if c is not None:
            e.append(c)
    if text is not None:
        e.text = text
    return e


def u(attr):
    return f"{{{USER}}}{attr}"


def fs(size):
    return str(max(7, round(size * FS)))


# ---------------------------------------------------------------------------------------------
# Data sources
# ---------------------------------------------------------------------------------------------
class DS:
    def __init__(self, name, caption, filename, cols, calcs=()):
        self.name, self.caption, self.filename = name, caption, filename
        self.raw, self.cols, self.palettes = cols, {}, []
        for col, dtype, *rest in cols:
            caption_, role, typ, fmt = (list(rest) + [None] * 4)[:4]
            role = role or ("measure" if dtype in ("real", "integer") else "dimension")
            typ = typ or ("quantitative" if role == "measure" else ("ordinal" if dtype == "date" else "nominal"))
            self.cols[col] = dict(datatype=dtype, role=role, type=typ, caption=caption_, fmt=fmt)
        for col, dtype, role, typ, caption_, formula, fmt in calcs:
            self.cols[col] = dict(datatype=dtype, role=role, type=typ, caption=caption_, formula=formula, fmt=fmt)

    def column_el(self, col):
        c = self.cols[col]
        e = el("column", {"caption": c.get("caption"), "datatype": c["datatype"], "default-format": c.get("fmt"),
                          "name": f"[{col}]", "role": c["role"], "type": c["type"]})
        if c.get("formula"):
            e.append(el("calculation", {"class": "tableau", "formula": c["formula"]}))
        return e

    def palette(self, field, mapping):
        self.palettes.append((field, mapping))
        bare = field.split(":")[1] if field.count(":") == 2 else None
        if bare and bare in self.cols and self.cols[bare].get("formula"):
            self.palettes.append((f"[{bare}]", mapping))

    def xml(self):
        conn = el("connection", {"class": "federated"},
                  el("named-connections", {},
                     el("named-connection", {"caption": self.caption, "name": f"textscan.{self.name}"},
                        el("connection", {"class": "textscan", "directory": DATA_DIR, "filename": self.filename,
                                          "password": "", "server": "", "character-set": "UTF-8", "header": "yes",
                                          "separator": ",", "text-qualifier": '"'}))),
                  el("relation", {"connection": f"textscan.{self.name}", "name": self.filename,
                                  "table": f"[{self.filename.replace('.', '#')}]", "type": "table"},
                     el("columns", {"character-set": "UTF-8", "header": "yes", "locale": "en_US", "separator": ",",
                                    "text-qualifier": '"'},
                        *[el("column", {"datatype": d, "name": n, "ordinal": i})
                          for i, (n, d, *_) in enumerate(self.raw)])))
        ds = el("datasource", {"caption": self.caption, "inline": "true", "name": self.name, "version": "18.1"}, conn)
        for col in self.cols:
            ds.append(self.column_el(col))
        if self.palettes:
            rule = el("style-rule", {"element": "mark"})
            for field, mapping in self.palettes:
                enc = el("encoding", {"attr": "color", "field": field, "type": "palette"})
                for value, color in mapping.items():
                    enc.append(el("map", {"to": color}, el("bucket", text=value)))
                rule.append(enc)
            ds.append(el("style", {}, rule))
        return ds


def calc(col, caption, formula, dtype="real", role="measure", typ="quantitative", fmt=None):
    return (col, dtype, role, typ, caption, formula, fmt)


def dim_calc(col, caption, formula, dtype="boolean"):
    return calc(col, caption, formula, dtype=dtype, role="dimension", typ="nominal")


RATIO = '*0.00"x"'
BILLIONS, MILLIONS = '*$#,##0.0"B"', '*$#,##0.0"M"'
TESTS = [("t1_splitting", "T1"), ("t2_near_limit", "T2"), ("t3_amendment_growth", "T3"),
         ("t4_duplicate", "T4"), ("t5_concentration", "T5")]

AWARDS = DS("awards", "Awards", "awards.csv", [
    ("owner_org", "string", "Department code"), ("department", "string", "Department"),
    ("award_reference", "string", "Award reference"), ("vendor_code", "string", "Vendor"),
    ("award_date", "date", "Award date"), ("fiscal_year", "string", "Fiscal year"),
    ("fiscal_quarter", "string", "Fiscal quarter"), ("commodity", "string", "Commodity"),
    ("competition", "string", "Competition"),
    ("value_at_award", "real", "At award", None, None, '*$#,##0'),
    ("value_now", "real", "Now", None, None, '*$#,##0'),
    ("n_amendments", "integer", "Amendments"), ("s6b_limit", "real", "Limit", None, None, '*$#,##0'),
    ("is_within_limit", "boolean", "Within limit"),
    ("t1_splitting", "integer", "Contract splitting", None, None, 'n#,##0'),
    ("t2_near_limit", "integer", "Sole-source near limit", None, None, 'n#,##0'),
    ("t3_amendment_growth", "integer", "Amendment growth", None, None, 'n#,##0'),
    ("t4_duplicate", "integer", "Possible duplicate", None, None, 'n#,##0'),
    ("t5_concentration", "integer", "Vendor concentration", None, None, 'n#,##0'),
    ("n_flags", "integer", "Flags"), ("is_flagged", "integer", "Flagged", None, None, 'n#,##0'),
    ("risk_score", "real", "Score", None, None, '*0.0'),
    ("risk_rank", "integer", "#", "dimension", "ordinal"),
    ("flag_details", "string", "Why it is flagged"),
], [
    calc("c_awards", "Awards", "COUNT([award_reference])", fmt='n#,##0'),
    calc("c_dept_label", "Departments",
         'IIF(COUNTD([department]) = 1, "1 department", STR(COUNTD([department])) + " departments")',
         dtype="string", typ="nominal"),
    calc("c_flag_rate", "Flag rate", "SUM([is_flagged]) / COUNT([award_reference])", fmt='p0.0%'),
    calc("c_sole_n", "Sole-sourced awards", 'SUM(IIF([competition] = "Sole-sourced", 1, 0))', fmt='n#,##0'),
    calc("c_sole_share", "Sole-sourced share",
         'SUM(IIF([competition] = "Sole-sourced", 1, 0)) / COUNT([award_reference])', fmt='p0.0%'),
    calc("c_value_b", "Value at award ($B)", "SUM([value_at_award]) / 1000000000", fmt=BILLIONS),
    calc("c_value_now_b", "Value now ($B)", "SUM([value_now]) / 1000000000", fmt=BILLIONS),
    calc("c_flagged_value_b", "Value flagged ($B)",
         "SUM(IIF([is_flagged] = 1, [value_at_award], 0)) / 1000000000", fmt=BILLIONS),
    calc("c_two_plus", "Two or more flags", "SUM(IIF([n_flags] >= 2, 1, 0))", fmt='n#,##0'),
    dim_calc("c_is_q4", "Quarter group", 'IIF([fiscal_quarter] = "Q4", "Q4", "Other quarters")', "string"),
    dim_calc("c_first", "First row", "FIRST() = 0"),
    dim_calc("c_closed_year", "Year is closed", '[fiscal_year] <> "2026-2027"'),
    calc("c_overall_rate", "Overall flag rate",
         "{FIXED : SUM([is_flagged])} / {FIXED : COUNT([award_reference])}", fmt='p0.0%'),
    dim_calc("c_above_avg", "Against the average",
             'IIF([c_flag_rate] > AVG([c_overall_rate]), "Above average", "At or below average")', "string"),
    dim_calc("c_year_short", "Year", 'MID([fiscal_year], 3, 2) + "-" + MID([fiscal_year], 8, 2)', "string"),
    calc("c_change", "Change", "SUM([value_now]) / SUM([value_at_award]) - 1", fmt='*+0%;-0%'),
    calc("c_val_q4", "Q4 (January to March)",
         'SUM(IIF([fiscal_quarter] = "Q4", [value_at_award], NULL)) / 1000000000', fmt=BILLIONS),
    calc("c_val_other", "Other quarters",
         'SUM(IIF([fiscal_quarter] <> "Q4", [value_at_award], NULL)) / 1000000000', fmt=BILLIONS),
    calc("c_rate_above", "Above the average",
         "IIF([c_flag_rate] > AVG([c_overall_rate]), [c_flag_rate], NULL)", fmt='p0.0%'),
    calc("c_rate_below", "At or below the average",
         "IIF([c_flag_rate] <= AVG([c_overall_rate]), [c_flag_rate], NULL)", fmt='p0.0%'),
    calc("c_at_k", "At award", "SUM([value_at_award]) / 1000", fmt='*$#,##0.0"K"'),
    calc("c_now_k", "Now", "SUM([value_now]) / 1000", fmt='*$#,##0.0"K"'),
    dim_calc("c_tests", "Tests", " + ".join(f'IIF([{c}] = 1, "{t}   ", "")' for c, t in TESTS), "string"),
    dim_calc("c_is_flagged", "Is flagged", "[is_flagged] = 1"),
    dim_calc("c_details", "Why it is flagged", 'REPLACE([flag_details], " | ", CHAR(10) + CHAR(10))', "string"),
])
AWARDS.palette("[none:c_is_q4:nk]", {'"Q4"': YELLOW, '"Other quarters"': MARK})
AWARDS.palette("[usr:c_above_avg:nk]", {'"Above average"': YELLOW, '"At or below average"': MARK})
AWARDS.palette("[:Measure Names]", {
    **{f'"[awards].[sum:{c}:qk]"': (YELLOW if c == "t3_amendment_growth" else MARK) for c, _ in TESTS},
    '"[awards].[usr:c_at_k:qk]"': TEXT, '"[awards].[usr:c_now_k:qk]"': TEXT,
    '"[awards].[usr:c_change:qk]"': YELLOW, '"[awards].[sum:risk_score:qk]"': TEXT,
    '"[awards].[usr:c_val_q4:qk]"': YELLOW, '"[awards].[usr:c_val_other:qk]"': MARK,
    '"[awards].[usr:c_rate_above:qk]"': YELLOW, '"[awards].[usr:c_rate_below:qk]"': MARK})

PARAM_MATCH = "[commodity_type] = [Parameters].[p_commodity]"
BINS = DS("bins", "Value bins", "value_bins.csv", [
    ("commodity_type", "string", "Commodity type"), ("bin_start", "integer", "Value", "dimension", "quantitative",
                                                     '*$#,##0'),
    ("sole_sourced", "integer", "Sole-sourced"), ("competed", "integer", "Competed"),
    ("unknown", "integer", "Unknown"), ("total", "integer", "Awards", None, None, 'n#,##0'),
    ("bin_label", "string", "Range"), ("trend", "real", "Trend", None, None, 'n#,##0'),
    ("in_window", "boolean", "Last $5,000"),
], [
    dim_calc("c_param", "Chosen commodity", PARAM_MATCH),
    calc("c_limit", "Limit", 'IIF([Parameters].[p_commodity] = "G", 25000, 40000)', fmt='*$#,##0'),
    dim_calc("c_in_range", "Near the limit",
             '[bin_start] >= IIF([Parameters].[p_commodity] = "G", 5000, 20000) AND '
             '[bin_start] < IIF([Parameters].[p_commodity] = "G", 45000, 60000)'),
    dim_calc("c_bar", "Bar", 'IIF([in_window], "Last $5,000 up to the limit", "Other values")', "string"),
    calc("c_share", "Sole-sourced share", "SUM([sole_sourced]) / SUM([total])", fmt='p0%'),
    dim_calc("c_commodity_name", "Commodity",
             'CASE [commodity_type] WHEN "S" THEN "Services ($40K)" WHEN "G" THEN "Goods ($25K)" '
             'ELSE "Construction" END', "string"),
    dim_calc("c_share_range", "In range", '[bin_start] <= 80000'),
    calc("c_win", "Last $5,000 up to the limit", "SUM(IIF([in_window], [total], NULL))", fmt='n#,##0'),
    calc("c_out", "Other values", "SUM(IIF([in_window], NULL, [total]))", fmt='n#,##0'),
    calc("c_share_s", "Services ($40K limit)",
         'SUM(IIF([commodity_type] = "S", [sole_sourced], NULL)) / SUM(IIF([commodity_type] = "S", [total], NULL))',
         fmt='p0%'),
    calc("c_share_g", "Goods ($25K limit)",
         'SUM(IIF([commodity_type] = "G", [sole_sourced], NULL)) / SUM(IIF([commodity_type] = "G", [total], NULL))',
         fmt='p0%'),
])
BINS.palette("[:Measure Names]", {'"[bins].[usr:c_win:qk]"': YELLOW, '"[bins].[usr:c_out:qk]"': GREY,
                                  '"[bins].[usr:c_share_s:qk]"': YELLOW, '"[bins].[usr:c_share_g:qk]"': MARK})
BINS.palette("[none:c_bar:nk]", {'"Last $5,000 up to the limit"': YELLOW, '"Other values"': GREY})
BINS.palette("[none:c_commodity_name:nk]", {'"Services ($40K)"': MARK, '"Goods ($25K)"': GREY})

BUNCH = DS("bunch", "Bunching summary", "bunching_summary.csv", [
    ("commodity_type", "string", "Commodity type"), ("limit_kind", "string", "Kind"),
    ("limit", "integer", "Limit", "dimension", "ordinal"), ("group", "string", "Group"),
    ("observed", "integer", "Observed"), ("expected", "real", "Expected"), ("excess", "real", "Excess"),
    ("ratio", "real", "Ratio", None, None, RATIO), ("ci_lo", "real", "Interval low", None, None, RATIO),
    ("ci_hi", "real", "Interval high", None, None, RATIO),
], [
    dim_calc("c_param", "Chosen commodity", PARAM_MATCH),
    calc("c_obs", "Observed", 'MAX(IIF([group] = "all", [observed], NULL))', fmt='n#,##0'),
    calc("c_exp", "Expected", 'MAX(IIF([group] = "all", [expected], NULL))', fmt='n#,##0'),
    calc("c_ratio", "All awards", 'MAX(IIF([group] = "all", [ratio], NULL))', fmt=RATIO),
    calc("c_lo", "Interval low", 'MAX(IIF([group] = "all", [ci_lo], NULL))', fmt=RATIO),
    calc("c_hi", "Interval high", 'MAX(IIF([group] = "all", [ci_hi], NULL))', fmt=RATIO),
    calc("c_ratio_nc", "Sole-sourced", 'MAX(IIF([group] = "non_competitive", [ratio], NULL))', fmt=RATIO),
    calc("c_ratio_c", "Competed", 'MAX(IIF([group] = "competitive", [ratio], NULL))', fmt=RATIO),
    calc("c_pl_min", "Placebo low", 'MIN(IIF([group] = "all", [ratio], NULL))', fmt=RATIO),
    calc("c_pl_max", "Placebo high", 'MAX(IIF([group] = "all", [ratio], NULL))', fmt=RATIO),
])

DEPT = DS("dept", "Departments", "bunching_by_department.csv", [
    ("department", "string", "Department"), ("commodity_type", "string", "Commodity type"),
    ("n_in_range", "integer", "Awards in range"), ("observed", "integer", "Observed"),
    ("expected", "real", "Expected"), ("ratio", "real", "Excess", None, None, RATIO),
    ("ci_lo", "real", "Interval low", None, None, RATIO), ("ci_hi", "real", "Interval high", None, None, RATIO),
    ("placebo_lo", "real", "Own range", None, None, RATIO), ("placebo_hi", "real", "Own range high", None, None,
                                                               RATIO),
], [
    dim_calc("c_param", "Chosen commodity", PARAM_MATCH),
    calc("c_width", "Range width", "SUM([placebo_hi]) - SUM([placebo_lo])", fmt=RATIO),
    calc("c_r_clear", "Clear of its own range", "SUM(IIF([ci_lo] > [placebo_hi], [ratio], NULL))", fmt=RATIO),
    calc("c_r_not", "Inside or near it", "SUM(IIF([ci_lo] > [placebo_hi], NULL, [ratio]))", fmt=RATIO),
    dim_calc("c_clear", "Against its own range",
             'IIF([ci_lo] > [placebo_hi], "Clear of its own range", "Inside or near it")', "string"),
])
DEPT.palette("[:Measure Names]", {'"[dept].[usr:c_r_clear:qk]"': YELLOW, '"[dept].[usr:c_r_not:qk]"': MARK})

HEAD = DS("headline", "Headline", "headline.csv", [
    ("data_as_of", "string", "Data as of"), ("analysis_start", "string", "Analysis start"),
    ("checks_matching", "integer", "Checks matching"), ("checks_total", "integer", "Checks"),
    ("hard_checks_passed", "integer", "Hard checks passed"), ("hard_checks_total", "integer", "Hard checks"),
    ("placebo_low_services", "real", "Placebo low"), ("placebo_high_services", "real", "Placebo high"),
    ("amended_past_limit", "integer", "Amended past the limit", None, None, 'n#,##0'),
    ("amended_past_limit_value_at_award", "real", "At award"), ("amended_past_limit_value_now", "real", "Now"),
    ("departments_clear_of_own_placebo", "integer", "Departments clear"),
    ("departments_estimated", "integer", "Departments estimated"),
], [
    calc("c_apl_at", "At award ($M)", "SUM([amended_past_limit_value_at_award]) / 1000000", fmt=MILLIONS),
    calc("c_apl_now", "Now ($M)", "SUM([amended_past_limit_value_now]) / 1000000", fmt=MILLIONS),
])

DATASOURCES = [AWARDS, BINS, BUNCH, DEPT, HEAD]


def parameters_ds():
    commodity = el("column", {"caption": "Commodity", "datatype": "string", "name": "[p_commodity]",
                              "param-domain-type": "list", "role": "measure", "type": "nominal", "value": '"S"',
                              "alias": "Services"},
                   el("calculation", {"class": "tableau", "formula": '"S"'}),
                   el("aliases", {}, *[el("alias", {"key": f'"{k}"', "value": v})
                                       for k, v in [("C", "Construction"), ("G", "Goods"), ("S", "Services")]]),
                   el("members", {}, *[el("member", {"alias": v, "value": f'"{k}"'})
                                       for k, v in [("S", "Services"), ("G", "Goods"), ("C", "Construction")]]))
    return el("datasource", {"hasconnection": "false", "inline": "true", "name": "Parameters", "version": "18.1"},
              el("aliases", {"enabled": "yes"}), commodity)


# ---------------------------------------------------------------------------------------------
# Worksheets
# ---------------------------------------------------------------------------------------------
DERIV = {"none": "None", "sum": "Sum", "cnt": "Count", "ctd": "CountD", "usr": "User", "avg": "Avg",
         "attr": "Attribute", "min": "Min", "max": "Max"}
KIND = {"nk": "nominal", "ok": "ordinal", "qk": "quantitative"}
SHEETS = []


class Sheet:
    def __init__(self, name, ds, uses_param=False):
        self.name, self.ds, self.uses_param = name, ds, uses_param
        self.base, self.inst = [], {}
        self.filters, self.sorts, self.styles, self.panes = [], [], [], []
        self.rows = self.cols = ""
        self.title = None
        SHEETS.append(self)

    def f(self, col, deriv="none", kind=None):
        if col in (":Measure Names", "Multiple Values"):
            return f"[{self.ds.name}].[{col}]"
        c = self.ds.cols[col]
        if kind is None:
            if deriv == "usr" and c["role"] == "dimension":
                kind = "nk"
            elif deriv not in ("none", "attr") or c["type"] == "quantitative":
                kind = "qk"
            else:
                kind = "ok" if c["type"] == "ordinal" else "nk"
        name = f"{deriv}:{col}:{kind}"
        if col not in self.base:
            self.base.append(col)
        self.inst[name] = el("column-instance", {"column": f"[{col}]", "derivation": DERIV[deriv],
                                                 "name": f"[{name}]", "pivot": "key", "type": KIND[kind]})
        return f"[{self.ds.name}].[{name}]"

    def style(self, element, *formats, encodings=()):
        rule = el("style-rule", {"element": element})
        for enc in encodings:
            rule.append(enc)
        for fmt in formats:
            rule.append(el("format", fmt))
        self.styles.append(rule)

    def keep_true(self, col, context=False):
        ref = self.f(col)
        self.filters.append(el("filter", {"class": "categorical", "column": ref,
                                          "context": "true" if context else None},
                               el("groupfilter", {"function": "member", "level": f"[none:{col}:nk]",
                                                  "member": "true", u("ui-domain"): "database",
                                                  u("ui-enumeration"): "inclusive", u("ui-marker"): "enumerate"})))

    def keep(self, col, values):
        ref = self.f(col)
        members = [el("groupfilter", {"function": "member", "level": f"[none:{col}:nk]", "member": f'"{v}"'})
                   for v in values]
        inner = members[0] if len(members) == 1 else el("groupfilter", {"function": "union"}, *members)
        inner.set(u("ui-domain"), "database")
        inner.set(u("ui-enumeration"), "inclusive")
        inner.set(u("ui-marker"), "enumerate")
        self.filters.append(el("filter", {"class": "categorical", "column": ref}, inner))

    def top(self, col, n, expression, end="top"):
        ref = self.f(col)
        level = ref.split("].", 1)[1]
        self.filters.append(el("filter", {"class": "categorical", "column": ref},
                               el("groupfilter", {"count": n, "end": end, "function": "end", "units": "records",
                                                  u("ui-marker"): "end", u("ui-top-by-field"): "true"},
                                  el("groupfilter", {"direction": "DESC", "expression": expression,
                                                     "function": "order", u("ui-marker"): "order"},
                                     el("groupfilter", {"function": "level-members", "level": level,
                                                        u("ui-enumeration"): "all", u("ui-marker"): "enumerate"})))))

    def table_calc_true(self, col, along):
        ref = self.f(col, "usr")
        name = ref.split("].", 1)[1][1:-1]
        self.inst[name].append(el("table-calc", {"ordering-field": along, "ordering-type": "Field"}))
        self.filters.append(el("filter", {"class": "categorical", "column": ref},
                               el("groupfilter", {"function": "member", "level": f"[{name}]", "member": "true",
                                                  u("ui-enumeration"): "inclusive", u("ui-marker"): "enumerate"})))

    def xml(self):
        view = el("view", {}, el("datasources", {}, el("datasource", {"caption": self.ds.caption,
                                                                      "name": self.ds.name})))
        if self.uses_param:
            view[0].append(el("datasource", {"name": "Parameters"}))
        deps = el("datasource-dependencies", {"datasource": self.ds.name})
        for col in self.base:
            deps.append(self.ds.column_el(col))
        for inst in self.inst.values():
            deps.append(inst)
        view.append(deps)
        if self.uses_param:
            view.append(el("datasource-dependencies", {"datasource": "Parameters"},
                           parameters_ds().find("column")))
        for x in self.filters + self.sorts:
            view.append(x)
        view.append(el("aggregation", {"value": "true"}))
        table = el("table", {}, view)
        style = el("style", {})
        for r in dark_rules() + self.styles:
            style.append(r)
        table.append(style)
        panes = el("panes", {})
        for p in self.panes:
            panes.append(p)
        table.append(panes)
        table.append(el("rows", text=self.rows or None))
        table.append(el("cols", text=self.cols or None))
        ws = el("worksheet", {"name": self.name})
        if self.title:
            ws.append(el("layout-options", {}, el("title", {}, formatted(self.title))))
        ws.append(table)
        return ws


def rule(element, *formats):
    r = el("style-rule", {"element": element})
    for fmt in formats:
        r.append(el("format", fmt))
    return r


def lines_off(element):
    return rule(element, *[{"attr": a, "scope": s, "value": v} for s in ("rows", "cols")
                           for a, v in (("line-visibility", "off"), ("stroke-size", "0"), ("div-level", "0"))])


def dark_rules():
    """Dark theme for every sheet: panel background, light text, no borders, faint horizontal grid."""
    return [
        rule("table", {"attr": "background-color", "value": PANEL}, {"attr": "omit-on-special", "value": "true"},
             {"attr": "break-on-special", "value": "true"}, {"attr": "show-null-value-warning", "value": "false"}),
        rule("title", {"attr": "background-color", "value": PANEL}),
        rule("pane", {"attr": "background-color", "value": PANEL},
             {"attr": "border-style", "scope": "rows", "value": "none"},
             {"attr": "border-style", "scope": "cols", "value": "none"},
             {"attr": "band-color", "scope": "rows", "value": PANEL},
             {"attr": "band-color", "scope": "cols", "value": PANEL}),
        rule("worksheet", {"attr": "font-family", "value": FONT}, {"attr": "color", "value": TEXT2},
             {"attr": "display-field-labels", "scope": "rows", "value": "false"},
             {"attr": "display-field-labels", "scope": "cols", "value": "false"}),
        rule("header", {"attr": "background-color", "value": PANEL},
             {"attr": "border-style", "scope": "rows", "value": "none"},
             {"attr": "border-style", "scope": "cols", "value": "none"},
             {"attr": "band-color", "scope": "rows", "value": PANEL},
             {"attr": "band-color", "scope": "cols", "value": PANEL}),
        rule("axis", {"attr": "color", "value": TEXT2}, {"attr": "font-size", "value": fs(10)},
             {"attr": "tick-color", "value": PANEL}),
        rule("label", {"attr": "color", "value": TEXT2}, {"attr": "font-size", "value": fs(10)}),
        lines_off("table-div"),
        lines_off("header-div"),
        rule("gridline", {"attr": "line-visibility", "scope": "cols", "value": "off"},
             {"attr": "stroke-color", "scope": "rows", "value": GRID}),
        rule("zeroline", {"attr": "line-visibility", "scope": "rows", "value": "off"},
             {"attr": "line-visibility", "scope": "cols", "value": "off"}),
        rule("dropline", {"attr": "line-visibility", "value": "off"}),
        rule("tooltip", {"attr": "font-family", "value": FONT}),
        *filter_rules(),
    ]


def formatted(runs):
    ft = el("formatted-text", {})
    for r in runs:
        text, attrs = (r, {}) if isinstance(r, str) else r
        ft.append(el("run", attrs, text=text))
    return ft


def run(text, size=None, color=None, bold=False, font=None, align=None):
    return (text, {"bold": "true" if bold else None, "fontcolor": color, "fontsize": fs(size) if size else None,
                   "fontname": font, "fontalignment": align})


def pane(mark, encodings=(), label=None, tooltip=None, mark_formats=(), pane_id=None, axis=None):
    attrs = {"id": pane_id, "selection-relaxation-option": "selection-relaxation-allow"}
    if axis:
        attrs[axis[0]] = axis[1]
    p = el("pane", attrs, el("view", {}, el("breakdown", {"value": "auto"})), el("mark", {"class": mark}))
    if encodings:
        enc = el("encodings", {})
        for kind, ref in encodings:
            enc.append(el(kind, {"column": ref}))
        p.append(enc)
    if tooltip:
        p.append(el("customized-tooltip", {"show-buttons": "false"}, formatted(tooltip)))
    if label:
        p.append(el("customized-label", {}, formatted(label)))
    r = el("style-rule", {"element": "mark"})
    for fmt in mark_formats:
        r.append(el("format", fmt))
    p.append(el("style", {}, r))
    return p


def labels_on(*extra):
    return [{"attr": "mark-labels-show", "value": "true"}, *extra]


def measures(sheet, refs):
    """Show these measures, in this order, on Measure Values; colour comes from the Measure Names palette."""
    names, values = sheet.f(":Measure Names"), sheet.f("Multiple Values")
    sheet.filters.append(el("filter", {"class": "categorical", "column": names},
                            el("groupfilter", {"function": "union", u("op"): "manual"},
                               *[el("groupfilter", {"function": "member", "level": "[:Measure Names]",
                                                    "member": f'"{r}"'}) for r in refs])))
    sheet.sorts.append(el("sort", {"class": "manual", "column": names, "direction": "ASC"},
                          el("dictionary", {}, *[el("bucket", text=f'"{r}"') for r in refs])))
    return names, values


def all_filter(sheet, col, group, context=False):
    ref = sheet.f(col)
    sheet.filters.append(el("filter", {"class": "categorical", "column": ref,
                                       "context": "true" if context else None, "filter-group": group},
                            el("groupfilter", {"function": "level-members", "level": f"[none:{col}:nk]",
                                               u("ui-enumeration"): "all", u("ui-marker"): "enumerate"})))


SHARED = {"year": ("fiscal_year", 2), "dept": ("department", 3), "commodity": ("commodity", 4),
          "q_dept": ("department", 5), "q_commodity": ("commodity", 6)}


def shared(sheet, keys, context=False):
    for k in keys:
        all_filter(sheet, *SHARED[k], context=context)


def title_runs(title, subtitle):
    return [run(title + "\n", 14, TEXT, bold=True, font=FONT_B), run(subtitle, 10.5, TEXT2)]


def big(color=TEXT):
    return dict(size=27, color=color, bold=True, font=FONT_B)


def card(name, ds, label, encodings, keys=(), uses_param=False, tooltip=None, setup=None):
    s = Sheet(name, ds, uses_param)
    shared(s, keys)
    refs = label(s)
    if setup:
        setup(s)
    s.panes.append(pane("Text", [("text", r) for r in refs[1]], label=refs[0],
                        tooltip=tooltip or [run(name.replace("Card: ", "").capitalize(), 10)],
                        mark_formats=labels_on()))
    s.style("cell", {"attr": "text-align", "value": "left"})
    return s


# ---------------------------------------------------------------------------------------------
# Page 1: Overview
# ---------------------------------------------------------------------------------------------
OV = ["year", "dept", "commodity"]


def overview_sheets():
    def awards(s):
        n, d = s.f("c_awards", "usr"), s.f("c_dept_label", "usr", "nk")
        return [run("Awards analysed\n", 11, TEXT2), run(f"<{n}>\n", **big()),
                run(f"<{d}>", 9.5, TEXT2)], [n, d]

    def value(s):
        v, now = s.f("c_value_b", "usr"), s.f("c_value_now_b", "usr")
        return [run("Value at award\n", 11, TEXT2), run(f"<{v}>\n", **big()),
                run(f"<{now}> after amendments", 9.5, TEXT2)], [v, now]

    def sole(s):
        share, n = s.f("c_sole_share", "usr"), s.f("c_sole_n", "usr")
        return [run("Awarded without competition\n", 11, TEXT2), run(f"<{share}>\n", **big()),
                run(f"<{n}> sole-sourced awards", 9.5, TEXT2)], [share, n]

    def flagged(s):
        n, rate = s.f("is_flagged", "sum"), s.f("c_flag_rate", "usr")
        return [run("Flagged for review\n", 11, TEXT2), run(f"<{n}>\n", **big(YELLOW)),
                run(f"<{rate}> of awards", 9.5, TEXT2)], [n, rate]

    def flagged_value(s):
        v, two = s.f("c_flagged_value_b", "usr"), s.f("c_two_plus", "usr")
        return [run("Value flagged\n", 11, TEXT2), run(f"<{v}>\n", **big()),
                run(f"<{two}> flagged by two or more tests", 9.5, TEXT2)], [v, two]

    cards = [card(n, AWARDS, fn, None, OV) for n, fn in [
        ("Card: awards", awards), ("Card: value", value), ("Card: sole-sourced", sole),
        ("Card: flagged", flagged), ("Card: value flagged", flagged_value)]]

    q = Sheet("Value by quarter", AWARDS)
    shared(q, OV)
    q.keep_true("c_closed_year")
    year, quarter = q.f("fiscal_year"), q.f("fiscal_quarter")
    names, v = measures(q, [q.f("c_val_q4", "usr"), q.f("c_val_other", "usr")])
    q.cols, q.rows = f"({year} / {quarter})", v
    q.panes.append(pane("Bar", [("color", names)],
                        tooltip=[run(f"<{year}>, <{quarter}>\n", 10, bold=True),
                                 run(f"Value at award: <{v}>", 10)],
                        mark_formats=[{"attr": "size", "value": "0.62"}]))
    q.style("label", {"attr": "display", "field": quarter, "value": "false"},
            {"attr": "color", "field": year, "value": TEXT2})
    q.style("axis", {"attr": "title", "class": "0", "field": v, "scope": "rows", "value": "$ billions"},
            {"attr": "text-format", "class": "0", "field": v, "scope": "rows", "value": '*$#,##0"B"'})
    q.title = title_runs("January to March is the biggest quarter on average" if F["q4_biggest"] else
                         "Value at award by quarter",
                         "Value at award by fiscal quarter. Yellow: Q4 (January to March), the last quarter of the "
                         "fiscal year.")

    t = Sheet("Flags by test", AWARDS)
    shared(t, OV)
    names, values = t.f(":Measure Names"), t.f("Multiple Values")
    refs = [t.f(c, "sum") for c, _ in TESTS]
    t.filters.append(el("filter", {"class": "categorical", "column": names},
                        el("groupfilter", {"function": "union", u("op"): "manual"},
                           *[el("groupfilter", {"function": "member", "level": "[:Measure Names]",
                                                "member": f'"{r}"'}) for r in refs])))
    t.sorts.append(el("sort", {"class": "manual", "column": names, "direction": "ASC"},
                      el("dictionary", {}, *[el("bucket", text=f'"{r}"') for r in refs])))
    t.rows, t.cols = names, values
    t.panes.append(pane("Bar", [("color", names), ("text", values)], label=[run(f"<{values}>", 10, TEXT2)],
                        mark_formats=labels_on({"attr": "size", "value": "0.55"})))
    t.style("axis", {"attr": "display", "class": "0", "field": values, "scope": "cols", "value": "false"})
    t.style("label", {"attr": "color", "field": names, "value": TEXT2})
    t.style("gridline", {"attr": "line-visibility", "scope": "rows", "value": "off"})
    t.title = title_runs(f"{F['most_flags'].capitalize()} flags the most awards", "Awards flagged by each test.")

    d = Sheet("Flag rate by department", AWARDS)
    shared(d, ["year", "commodity"], context=True)
    dept, rate, n = d.f("department"), d.f("c_flag_rate", "usr"), d.f("is_flagged", "sum")
    overall = d.f("c_overall_rate", "avg")
    d.top("department", 8, "SUM([is_flagged])")
    d.sorts.append(el("sort", {"class": "computed", "column": dept, "direction": "DESC", "using": n}))
    names, vals = measures(d, [d.f("c_rate_above", "usr"), d.f("c_rate_below", "usr")])
    d.rows, d.cols = dept, f"({rate} + {vals})"
    d.panes.append(pane("Automatic"))
    d.panes.append(pane("Bar", [("text", rate), ("text", n), ("lod", overall)], pane_id="1",
                        axis=("x-axis-name", rate), label=[run(f"<{rate}>  (<{n}>)", 10, TEXT2)],
                        tooltip=[run(f"<{dept}>\n", 10, bold=True), run(f"Flag rate: <{rate}>\n", 10),
                                 run(f"Awards flagged: <{n}>\n", 10), run(f"All departments: <{overall}>", 10)],
                        mark_formats=labels_on({"attr": "size", "value": "0.5"},
                                               {"attr": "mark-color", "value": PANEL})))
    d.panes.append(pane("Bar", [("color", names), ("lod", n), ("lod", overall), ("lod", rate)], pane_id="2",
                        axis=("x-axis-name", vals),
                        tooltip=[run(f"<{dept}>\n", 10, bold=True), run(f"Flag rate: <{rate}>\n", 10),
                                 run(f"Awards flagged: <{n}>\n", 10), run(f"All departments: <{overall}>", 10)],
                        mark_formats=[{"attr": "size", "value": "0.5"}]))
    d.style("axis", {"attr": "display", "class": "0", "field": vals, "scope": "cols", "value": "false"},
            {"attr": "display", "class": "0", "field": rate, "scope": "cols", "value": "false"},
            encodings=[el("encoding", {"attr": "space", "class": "0", "field": vals, "field-type": "quantitative",
                                       "fold": "true", "scope": "cols", "synchronized": "true",
                                       "type": "space"})])
    d.style("label", {"attr": "color", "field": dept, "value": TEXT})
    d.style("header", {"attr": "width", "field": dept, "value": "260"})
    d.style("gridline", {"attr": "line-visibility", "scope": "rows", "value": "off"})
    d.title = title_runs(f"Flag rate by department, against the {F['pct']:.1f}% average",
                         "The eight departments with the most flagged awards. Yellow: above the average.")

    y = Sheet("Sole-sourced share by year", AWARDS)
    shared(y, OV)
    y.keep_true("c_closed_year")
    short, share = y.f("c_year_short"), y.f("c_sole_share", "usr")
    y.cols, y.rows = short, share
    y.panes.append(pane("Bar", [("text", share)], label=[run(f"<{share}>", 10, TEXT)],
                        tooltip=[run(f"<{short}>\n", 10, bold=True), run(f"Sole-sourced: <{share}>", 10)],
                        mark_formats=labels_on({"attr": "mark-color", "value": MARK},
                                               {"attr": "size", "value": "0.6"})))
    y.style("axis", {"attr": "title", "class": "0", "field": share, "scope": "rows", "value": ""})
    y.style("label", {"attr": "color", "field": short, "value": TEXT2})
    y.title = title_runs(f"Sole-sourcing peaked in {F['peak_year']}", "Share of awards made without competition.")
    return cards, q, t, d, y


# ---------------------------------------------------------------------------------------------
# Page 2: Limits
# ---------------------------------------------------------------------------------------------
def limits_sheets():
    def real(s):
        s.keep_true("c_param")
        s.keep("limit_kind", ["real"])

    def placebo(s):
        s.keep_true("c_param")
        s.keep("limit_kind", ["placebo"])

    def observed(s):
        o, e = s.f("c_obs", "usr"), s.f("c_exp", "usr")
        return [run("Last $5,000 up to the limit\n", 11, TEXT2), run(f"<{o}>\n", **big()),
                run(f"awards; the trend predicts <{e}>", 9.5, TEXT2)], [o, e]

    def ratio(s):
        r, lo, hi = s.f("c_ratio", "usr"), s.f("c_lo", "usr"), s.f("c_hi", "usr")
        return [run("All awards, against the trend\n", 11, TEXT2), run(f"<{r}>\n", **big()),
                run(f"95% interval <{lo}> to <{hi}>", 9.5, TEXT2)], [r, lo, hi]

    def ratio_nc(s):
        nc, c = s.f("c_ratio_nc", "usr"), s.f("c_ratio_c", "usr")
        return [run("Sole-sourced, against the trend\n", 11, TEXT2), run(f"<{nc}>\n", **big(YELLOW)),
                run(f"competed awards: <{c}>", 9.5, TEXT2)], [nc, c]

    def placebo_range(s):
        lo, hi = s.f("c_pl_min", "usr"), s.f("c_pl_max", "usr")
        return [run("Where no rule changes\n", 11, TEXT2), run(f"<{lo}> to <{hi}>\n", **big()),
                run("same test at $60K to $90K", 9.5, TEXT2)], [lo, hi]

    def amended(s):
        n, at, now = s.f("amended_past_limit", "sum"), s.f("c_apl_at", "usr"), s.f("c_apl_now", "usr")
        return [run("Amended past the limit\n", 11, TEXT2), run(f"<{n}>\n", **big()),
                run(f"<{at}> at award, <{now}> now", 9.5, TEXT2)], [n, at, now]

    cards = [card("Card: observed", BUNCH, observed, None, uses_param=True, setup=real),
             card("Card: ratio", BUNCH, ratio, None, uses_param=True, setup=real),
             card("Card: sole-sourced ratio", BUNCH, ratio_nc, None, uses_param=True, setup=real),
             card("Card: placebo", BUNCH, placebo_range, None, uses_param=True, setup=placebo),
             card("Card: amended past limit", HEAD, amended, None)]

    h = Sheet("Awards per $1,000", BINS, uses_param=True)
    h.keep_true("c_param")
    h.keep_true("c_in_range")
    x, total, trend = h.f("bin_start", kind="qk"), h.f("total", "sum"), h.f("trend", "sum")
    label = h.f("bin_label", "attr")
    names, total_v = measures(h, [h.f("c_win", "usr"), h.f("c_out", "usr")])
    h.cols, h.rows = x, f"({total_v} + {trend})"
    tip = [run(f"<{label}>\n", 10, bold=True), run(f"Awards: <{total}>\n", 10), run(f"Trend: <{trend}>", 10)]
    h.panes.append(pane("Automatic"))
    h.panes.append(pane("Bar", [("color", names), ("tooltip", label), ("tooltip", total)], tooltip=tip,
                        pane_id="1", axis=("y-axis-name", total_v), mark_formats=[{"attr": "size", "value": "0.8"}]))
    h.panes.append(pane("Line", [("tooltip", label), ("tooltip", total)], tooltip=tip, pane_id="2",
                        axis=("y-axis-name", trend),
                        mark_formats=[{"attr": "mark-color", "value": TEXT}, {"attr": "size", "value": "1.2"}]))
    h.style("axis", {"attr": "display", "class": "0", "field": trend, "scope": "rows", "value": "false"},
            {"attr": "title", "class": "0", "field": total_v, "scope": "rows", "value": ""},
            {"attr": "title", "class": "0", "field": x, "scope": "cols", "value": ""},
            encodings=[el("encoding", {"attr": "space", "class": "0", "field": trend,
                                       "field-type": "quantitative", "fold": "true", "scope": "rows",
                                       "synchronized": "true", "type": "space"})])
    h.title = title_runs("Awards jump in the last $1,000 before the limit",
                         "Awards per $1,000 of value. Yellow: the last $5,000 up to the limit. "
                         "White line: the trend from the values below.")

    sh = Sheet("Sole-sourced share by value", BINS)
    sh.keep_true("c_share_range")
    x2 = sh.f("bin_start", kind="qk")
    name, share = measures(sh, [sh.f("c_share_s", "usr"), sh.f("c_share_g", "usr")])
    sh.cols, sh.rows = x2, share
    sh.panes.append(pane("Line", [("color", name)],
                         tooltip=[run(f"<{name}>, from <{x2}>\n", 10, bold=True),
                                  run(f"Sole-sourced: <{share}>", 10)],
                         mark_formats=[{"attr": "size", "value": "0.9"}]))
    sh.style("axis", {"attr": "title", "class": "0", "field": share, "scope": "rows", "value": "Share sole-sourced"},
             {"attr": "text-format", "class": "0", "field": share, "scope": "rows", "value": "p0%"},
             {"attr": "title", "class": "0", "field": x2, "scope": "cols", "value": ""})
    sh.title = title_runs("Sole-sourcing peaks just under each limit",
                          "Sole-sourced share per $1,000 of value. Yellow: services ($40K). Grey: goods ($25K).")

    dp = Sheet("Departments against their own range", DEPT, uses_param=True)
    dp.keep_true("c_param", context=True)
    dpt, lo, width, r = dp.f("department"), dp.f("placebo_lo", "sum"), dp.f("c_width", "usr"), dp.f("ratio", "sum")
    ci_lo, ci_hi = dp.f("ci_lo", "sum"), dp.f("ci_hi", "sum")
    hi = dp.f("placebo_hi", "sum")
    dp.top("department", 10, "SUM([ratio])")
    dp.sorts.append(el("sort", {"class": "computed", "column": dpt, "direction": "DESC", "using": r}))
    cnames, cvals = measures(dp, [dp.f("c_r_clear", "usr"), dp.f("c_r_not", "usr")])
    dp.rows, dp.cols = dpt, f"({lo} + {cvals})"
    tip = [run(f"<{dpt}>\n", 10, bold=True), run(f"Excess: <{r}> the trend (95% interval <{ci_lo}> to <{ci_hi}>)\n",
                                                  10),
           run(f"Its own range at $60K to $90K: <{lo}> to <{hi}>", 10)]
    dp.panes.append(pane("Automatic"))
    dp.panes.append(pane("GanttBar", [("size", width), ("lod", ci_lo), ("lod", ci_hi), ("lod", hi)], tooltip=tip,
                         pane_id="1", axis=("x-axis-name", lo),
                         mark_formats=[{"attr": "mark-color", "value": GRID}, {"attr": "size", "value": "0.6"}]))
    dp.panes.append(pane("Circle", [("color", cnames), ("lod", ci_lo), ("lod", ci_hi), ("lod", hi), ("lod", lo),
                                    ("lod", r)],
                         tooltip=tip, pane_id="2", axis=("x-axis-name", cvals),
                         mark_formats=[{"attr": "size", "value": "0.9"}]))
    dp.style("axis", {"attr": "display", "class": "0", "field": cvals, "scope": "cols", "value": "false"},
             {"attr": "title", "class": "0", "field": lo, "scope": "cols",
              "value": "Awards just under the limit, as a multiple of the trend"},
             encodings=[el("encoding", {"attr": "space", "class": "0", "field": cvals, "field-type": "quantitative",
                                        "fold": "true", "scope": "cols", "synchronized": "true",
                                        "type": "space"})])
    dp.style("label", {"attr": "color", "field": dpt, "value": TEXT})
    dp.style("header", {"attr": "width", "field": dpt, "value": "250"})
    dp.title = title_runs("The ten largest excesses, against each department's own range",
                          "Dot: excess against the trend. Grey bar: same test at $60K to $90K. "
                          "Yellow: 95% interval clears it.")
    return cards, h, sh, dp


# ---------------------------------------------------------------------------------------------
# Page 3: Queue
# ---------------------------------------------------------------------------------------------
QK = ["q_dept", "q_commodity"]


def queue_sheets():
    def flagged(s):
        n, rate = s.f("is_flagged", "sum"), s.f("c_flag_rate", "usr")
        return [run("Flagged awards in the queue\n", 11, TEXT2), run(f"<{n}>\n", **big()),
                run(f"<{rate}> of all awards", 9.5, TEXT2)], [n, rate]

    def two(s):
        n = s.f("c_two_plus", "usr")
        return [run("Flagged by two or more tests\n", 11, TEXT2), run(f"<{n}>\n", **big(YELLOW)),
                run("the strongest candidates", 9.5, TEXT2)], [n]

    def value(s):
        v = s.f("c_flagged_value_b", "usr")
        return [run("Value at award in the queue\n", 11, TEXT2), run(f"<{v}>\n", **big()),
                run("before amendments", 9.5, TEXT2)], [v]

    def top_score(s):
        m = s.f("risk_score", "max")
        return [run("Highest risk score\n", 11, TEXT2), run(f"<{m}>\n", **big()),
                run("out of 100", 9.5, TEXT2)], [m]

    def checks(s):
        a, b = s.f("checks_matching", "sum"), s.f("checks_total", "sum")
        return [run("Checked two ways\n", 11, TEXT2), run(f"<{a}> of <{b}>\n", **big()),
                run("checks where SQL and pandas agree", 9.5, TEXT2)], [a, b]

    cards = [card("Card: queue size", AWARDS, flagged, None, QK), card("Card: two or more", AWARDS, two, None, QK),
             card("Card: queue value", AWARDS, value, None, QK), card("Card: top score", AWARDS, top_score, None, QK),
             card("Card: checks", HEAD, checks, None)]

    qt = Sheet("Review queue", AWARDS)
    shared(qt, QK, context=True)
    qt.keep_true("c_is_flagged", context=True)
    rank, dept, vendor, com, tests = (qt.f("risk_rank"), qt.f("department"), qt.f("vendor_code"),
                                      qt.f("commodity"), qt.f("c_tests"))
    ref = qt.f("award_reference")
    names, values = qt.f(":Measure Names"), qt.f("Multiple Values")
    ms = [qt.f("c_at_k", "usr"), qt.f("c_now_k", "usr"), qt.f("c_change", "usr"),
          qt.f("risk_score", "sum")]
    qt.top("risk_rank", 13, "SUM([risk_score])")
    qt.filters.append(el("filter", {"class": "categorical", "column": names},
                         el("groupfilter", {"function": "union", u("op"): "manual"},
                            *[el("groupfilter", {"function": "member", "level": "[:Measure Names]",
                                                 "member": f'"{m}"'}) for m in ms])))
    qt.sorts.append(el("sort", {"class": "manual", "column": names, "direction": "ASC"},
                       el("dictionary", {}, *[el("bucket", text=f'"{m}"') for m in ms])))
    qt.rows = f"{rank} / {dept} / {vendor} / {com} / {tests}"
    qt.cols = names
    qt.panes.append(pane("Text", [("text", values), ("color", names), ("lod", ref)],
                         tooltip=[run(f"#<{rank}> <{dept}>\n", 10, bold=True), run("Click to see why it is flagged",
                                                                                10)],
                         mark_formats=labels_on()))
    qt.style("worksheet", {"attr": "display-field-labels", "scope": "rows", "value": "true"})
    qt.style("label", {"attr": "color", "field": dept, "value": TEXT}, {"attr": "color", "field": tests,
                                                                        "value": YELLOW})
    qt.style("header", {"attr": "width", "field": dept, "value": "290"},
             {"attr": "width", "field": rank, "value": "34"}, {"attr": "width", "field": vendor, "value": "62"},
             {"attr": "width", "field": com, "value": "92"}, {"attr": "width", "field": tests, "value": "130"})
    qt.style("cell", {"attr": "text-align", "value": "right"}, {"attr": "height", "value": "26"})
    qt.title = title_runs("Highest scores first",
                          "Vendor names are hidden in this public version. Click a row to see why it is flagged.")

    why = Sheet("Why it is flagged", AWARDS)
    shared(why, QK, context=True)
    why.keep_true("c_is_flagged", context=True)
    why.top("risk_rank", 13, "SUM([risk_score])")
    det, dept2, com2 = why.f("c_details", "attr"), why.f("department", "attr"), why.f("commodity", "attr")
    rank2 = why.f("risk_rank")
    why.table_calc_true("c_first", rank2)
    why.rows = rank2
    why.style("label", {"attr": "display", "field": rank2, "value": "false"})
    rank_label = why.f("risk_rank", "attr")
    why.panes.append(pane("Text", [("text", det), ("text", dept2), ("text", com2), ("text", rank_label)],
                          label=[run(f"Award #<{rank_label}>: <{dept2}>, <{com2}>\n\n", 11, TEXT, bold=True),
                                 run(f"<{det}>", 10, TEXT)], mark_formats=labels_on()))
    why.style("cell", {"attr": "text-align", "value": "left"}, {"attr": "vertical-align", "value": "top"})
    why.title = title_runs("Why it is flagged", "One line per test. Click a row in the queue to change the award.")
    return cards, qt, why


# ---------------------------------------------------------------------------------------------
# Dashboards
# ---------------------------------------------------------------------------------------------
class Dash:
    def __init__(self, name):
        self.name, self.zones, self.next_id, self.sheets = name, [], 2, []

    def _id(self):
        self.next_id += 1
        return self.next_id

    @staticmethod
    def _pos(x, y, w, h):
        return {"x": round(x / W * 100000), "y": round(y / H * 100000),
                "w": round(w / W * 100000), "h": round(h / H * 100000)}

    def box(self, x, y, w, h, color):
        self.zones.append(el("zone", {"id": self._id(), "type-v2": "empty", **self._pos(x, y, w, h)},
                             zone_style(color)))

    def text(self, x, y, w, h, runs, color=None):
        self.zones.append(el("zone", {"id": self._id(), "type-v2": "text", **self._pos(x, y, w, h)},
                             formatted(runs), zone_style(color)))

    def sheet(self, x, y, w, h, sheet, title=False, color=PANEL):
        self.sheets.append(sheet)
        self.zones.append(el("zone", {"id": self._id(), "name": sheet.name,
                                      "show-title": "true" if title else "false", **self._pos(x, y, w, h)},
                             zone_style(color)))

    def filter(self, x, y, w, h, sheet, param, mode="dropdown"):
        self.zones.append(el("zone", {"id": self._id(), "mode": mode, "name": sheet.name, "param": param,
                                      "type-v2": "filter", "values": "relevant", **self._pos(x, y, w, h)},
                             zone_style(BG)))

    def param(self, x, y, w, h, param):
        self.zones.append(el("zone", {"id": self._id(), "mode": "compact", "param": param, "type-v2": "paramctrl",
                                      **self._pos(x, y, w, h)}, zone_style(None)))

    def xml(self):
        d = el("dashboard", {"name": self.name},
               el("style", {}, el("style-rule", {"element": "table"},
                                  el("format", {"attr": "background-color", "value": BG})),
                  *filter_rules()),
               el("size", {"maxheight": SIZE_H, "maxwidth": SIZE_W, "minheight": SIZE_H, "minwidth": SIZE_W,
                           "sizing-mode": "fixed"}))
        zones = el("zones", {}, el("zone", {"h": 100000, "id": 1, "type-v2": "layout-basic", "w": 100000,
                                            "x": 0, "y": 0}, zone_style(BG)))
        for z in self.zones:
            zones.append(z)
        d.append(zones)
        return d


def filter_rules():
    return [rule("quick-filter", {"attr": "color", "value": TEXT}, {"attr": "background-color", "value": PANEL}),
            rule("quick-filter-title", {"attr": "color", "value": TEXT2}),
            rule("parameter-ctrl", {"attr": "color", "value": TEXT}, {"attr": "background-color", "value": PANEL}),
            rule("parameter-ctrl-title", {"attr": "color", "value": TEXT2})]


def zone_style(color):
    zs = el("zone-style", {},
            el("format", {"attr": "border-color", "value": "#000000"}),
            el("format", {"attr": "border-style", "value": "none"}),
            el("format", {"attr": "border-width", "value": "0"}),
            el("format", {"attr": "margin", "value": "0"}))
    if color:
        zs.append(el("format", {"attr": "background-color", "value": color}))
    return zs


def chrome(d, page, subtitle):
    d.box(0, 0, 84, 900, RAIL)
    d.box(28, 30, 28, 28, YELLOW)
    for i, item in enumerate(["Overview", "Limits", "Queue"]):
        y = 118 + i * 94
        current = item == page
        if current:
            d.box(0, y, 4, 72, YELLOW)
        d.text(4, y + 22, 80, 30, [run(item, 10, TEXT if current else TEXT2, bold=current, align="1")])
    d.text(104, 22, 700, 46, [run("Federal procurement review", 24, TEXT, bold=True, font=FONT_B)])
    d.text(104, 72, 980, 28, [run(subtitle, 12, TEXT2)])
    d.text(1180, 72, 400, 28, [run(f"Data from open.canada.ca, as of {F['date']}", 10.5, TEXT2, align="2")])
    d.text(104, 872, 1400, 24, [run("Source: Government of Canada, Proactive Publication of Contracts over $10,000 "
                                    "(open.canada.ca). A flag marks an award for review. It is not a finding of "
                                    "wrongdoing. Chart titles describe all departments and years.", 9.5, TEXT2)])


def cards_row(d, cards, yellow_index):
    for i, c in enumerate(cards):
        x = 112 + i * 296
        d.box(x, 121, 280, 117, PANEL)
        if i == yellow_index:
            d.box(x, 121, 4, 117, YELLOW)
        d.sheet(x + 16, 129, 258, 103, c)


def panel(d, x, y, w, h, sheet, fill=PANEL):
    d.box(x, y, w, h, fill)
    d.sheet(x + 16, y + 12, w - 32, h - 24, sheet, title=True, color=fill)


def key_panel(d, x, y, w, h, title, paragraphs, label, closing):
    d.box(x, y, w, h, KEYFILL)
    d.box(x, y, 4, h, YELLOW)
    runs = [run(title + "\n\n", 14, YELLOW, bold=True, font=FONT_B)]
    runs += [run(p + "\n\n", 10.5, TEXT) for p in paragraphs]
    runs += [run(label + "\n", 10.5, TEXT, bold=True), run(closing, 10.5, TEXT)]
    d.text(x + 24, y + 16, w - 44, h - 28, runs, color=KEYFILL)


def overview():
    d = Dash("Overview")
    cards, q, t, dept, y = overview_sheets()
    chrome(d, "Overview", "Where the money went and what the tests flagged. Awards over $10,000 from 10 June 2019.")
    cards_row(d, cards, 3)
    key_panel(d, 112, 257, 496, 288, "Key finding", [
        f"About 1 in {F['one_in']} federal awards ({F['pct']:.1f}%) matches a pattern worth a reviewer's time. "
        + ("Most of the value flagged comes from contracts that grew through amendments."
           if F["t3_value_share"] > 0.5 else ""),
        f"Service contracts pile up just under the $40,000 limit for sole-sourcing: {F['n_last_1000']:,} awards in "
        "the last $1,000 before it."], "Where to start",
        "The highest-scoring awards were each sole-sourced within the limit, sit in a run of awards to the same "
        "vendor, and were amended past the limit.")
    panel(d, 624, 257, 952, 288, q)
    panel(d, 112, 563, 432, 300, t)
    panel(d, 560, 563, 616, 300, dept)
    panel(d, 1192, 563, 384, 300, y)
    for i, key in enumerate(OV):
        d.filter(1002 + i * 195, 18, 184, 46, cards[0], f"[awards].[none:{SHARED[key][0]}:nk]")
    return d


def limits():
    d = Dash("Limits")
    cards, h, sh, dp = limits_sheets()
    chrome(d, "Limits", "Do awards pile up under the limit that requires bids? Government Contracts "
                        "Regulations s.6(b).")
    cards_row(d, cards, 2)
    key_panel(d, 112, 257, 496, 288, "Key finding", [
        f"Service awards pile up just under the $40,000 limit: {F['obs']:,} in the last $5,000, where the trend "
        f"from the values below predicts {F['exp']:,.0f}.",
        f"The excess comes from sole-sourced awards ({F['nc']:.2f}x the trend). Competed awards ({F['comp']:.2f}x) "
        f"sit close to the {F['pl_lo']:.2f}x to {F['pl_hi']:.2f}x that round numbers produce where no rule "
        "changes."], "What to review",
        f"{F['apl']:,} awards sole-sourced within the limit and later amended past it, {F['apl_double']:,} of them "
        "to more than double the limit.")
    panel(d, 624, 257, 952, 288, h)
    panel(d, 112, 563, 608, 300, sh)
    panel(d, 736, 563, 840, 300, dp)
    d.param(1392, 18, 184, 46, "[Parameters].[p_commodity]")
    return d


def queue():
    d = Dash("Queue")
    cards, qt, why = queue_sheets()
    chrome(d, "Queue", "Which awards to look at first. Flagged awards ranked by risk score: flag weights, scaled "
                       "up for larger awards.")
    cards_row(d, cards, 1)
    panel(d, 112, 257, 960, 606, qt)
    key_panel(d, 1088, 257, 488, 222, "Start here", [
        f"{F['under_30']:.0%} of the queue scores under 30. "
        + ("The awards at the top each were sole-sourced within the limit, sit in a run of awards to the same "
           "vendor, and were amended past the limit." if F["top_pattern"] else
           "The awards at the top combine several flags on larger contracts.")], "Next step",
        "Open the contract file and check the reason given for each amendment.")
    panel(d, 1088, 495, 488, 368, why)
    for i, key in enumerate(QK):
        d.filter(1197 + i * 195, 18, 184, 46, cards[0], f"[awards].[none:{SHARED[key][0]}:nk]")
    return d


def actions(dashes):
    names = {d.name: d for d in dashes}
    acts = []
    if "Queue" in names:
        others = ",".join(s.name for s in names["Queue"].sheets if s.name != "Why it is flagged")
        acts.append(el("action", {"caption": "Show why the selected award is flagged", "name": "[Action_why]"},
                       el("activation", {"auto-clear": "true", "type": "on-select"}),
                       el("source", {"dashboard": "Queue", "type": "sheet", "worksheet": "Review queue"}),
                       el("link", {"caption": "Why it is flagged", "delimiter": ",", "escape": "\\",
                                   "expression": "tsl:Queue?%5Bawards%5D.%5Brisk_rank%5D~s0="
                                                 "<[risk_rank]~na>",
                                   "include-null": "true", "multi-select": "true", "url-escape": "true"}),
                       el("command", {"command": "tsc:tsl-filter"},
                          el("param", {"name": "exclude", "value": others}),
                          el("param", {"name": "target", "value": "Queue"}))))
    if not acts:
        return None
    a = el("actions", {}, *acts)
    a.append(el("datasources", {}, el("datasource", {"caption": "Awards", "name": "awards"})))
    a.append(el("datasource-dependencies", {"datasource": "awards"}, AWARDS.column_el("risk_rank")))
    return a


def workbook():
    builders = {"Overview": overview, "Limits": limits, "Queue": queue}
    dashes = [builders[p]() for p in PAGES]
    wb = el("workbook", {"source-build": "2026.3.0", "source-platform": "mac", "version": "18.1",
                         "locale": "en_US"})
    wb.append(el("preferences", {}))
    wb.append(el("style", {},
                 rule("quick-filter", {"attr": "color", "value": TEXT}, {"attr": "background-color", "value": PANEL},
                      {"attr": "font-family", "value": FONT}),
                 rule("quick-filter-title", {"attr": "color", "value": TEXT2}, {"attr": "font-family", "value": FONT}),
                 rule("parameter-ctrl", {"attr": "color", "value": TEXT}, {"attr": "background-color", "value": PANEL},
                      {"attr": "font-family", "value": FONT}),
                 rule("parameter-ctrl-title", {"attr": "color", "value": TEXT2},
                      {"attr": "font-family", "value": FONT})))
    used = {s.ds.name for s in SHEETS}
    wb.append(el("datasources", {}, parameters_ds(), *[ds.xml() for ds in DATASOURCES if ds.name in used]))
    acts = actions(dashes)
    if acts is not None:
        wb.append(acts)
    wb.append(el("worksheets", {}, *[s.xml() for s in SHEETS]))
    wb.append(el("dashboards", {}, *[d.xml() for d in dashes]))
    windows = el("windows", {"source-height": "30"})
    for d in dashes:
        seen = list(dict.fromkeys(s.name for s in d.sheets))
        windows.append(el("window", {"class": "dashboard", "maximized": "true", "name": d.name},
                          el("viewpoints", {}, *[el("viewpoint", {"name": n}, el("zoom", {"type": "entire-view"}))
                                                 for n in seen]),
                          el("active", {"id": "-1"})))
    for s in SHEETS:
        windows.append(el("window", {"class": "worksheet", "hidden": "true", "maximized": "true", "name": s.name},
                          el("cards", {},
                             el("edge", {"name": "left"},
                                el("strip", {"size": "160"}, el("card", {"type": "pages"}),
                                   el("card", {"type": "filters"}), el("card", {"type": "marks"}))),
                             el("edge", {"name": "top"},
                                el("strip", {"size": "2147483647"}, el("card", {"type": "columns"})),
                                el("strip", {"size": "2147483647"}, el("card", {"type": "rows"})),
                                el("strip", {"size": "31"}, el("card", {"type": "title"}))))))
    wb.append(windows)
    return wb


if __name__ == "__main__":
    tree = ET.ElementTree(workbook())
    ET.indent(tree, space="  ")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "wb") as fh:
        fh.write(b"<?xml version='1.0' encoding='utf-8' ?>\n\n")
        tree.write(fh, encoding="utf-8", xml_declaration=False)
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes), {len(SHEETS)} sheets")
