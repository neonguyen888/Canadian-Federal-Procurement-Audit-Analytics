"""Tests for the raw-file clean-up. Author: Neo Nguyen"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from clean import KEEP, clean, fiscal_quarter, fiscal_year, parse_money  # noqa: E402


def test_fiscal_year_runs_april_to_march():
    d = pd.to_datetime(pd.Series(["2022-04-01", "2023-03-31", "2023-04-01", "2022-05-16"]))
    assert fiscal_year(d).tolist() == ["2022-2023", "2022-2023", "2023-2024", "2022-2023"]
    assert fiscal_quarter(d).tolist() == ["Q1", "Q4", "Q1", "Q1"]


def test_money_accepts_dollar_signs_commas_and_blanks():
    s = parse_money(pd.Series(["38900.25", "$1,234", " 15 ", "", "abc"]))
    assert s.tolist()[:3] == [38900.25, 1234.0, 15.0]
    assert s.isna().tolist()[3:] == [True, True]


def raw_frame(rows):
    df = pd.DataFrame(rows)
    for c in KEEP:
        df[c] = df.get(c, "")
    return df.astype(str)


def test_clean_fixes_hyphens_drops_unusable_rows_and_counts_everything():
    base = dict(owner_org="dnd-mdn", owner_org_title="National Defence | Défense nationale",
                vendor_name="Acme Inc.", contract_date="2022-05-16", contract_value="50000",
                instrument_type="C", reporting_period="2022-2023-Q1", commodity_type="s",
                ministers_office="N", vendor_postal_code="K1A", number_of_bids="3")
    raw = raw_frame([
        {**base, "reference_number": "C-2022‑2023-Q1-1"},                       # non-ASCII hyphen
        {**base, "reference_number": "C-2022-2023-Q1-2", "contract_date": ""},        # no date -> dropped
        {**base, "reference_number": "C-2022-2023-Q1-3", "contract_date": "2015-01-01"},  # before window
        {**base, "reference_number": "C-2022-2023-Q1-4", "contract_value": ""},       # no value -> dropped
        {**base, "reference_number": "C-2022-2023-Q1-9", "contract_date": "2099-01-01"},  # future -> dropped
        {**base, "reference_number": "C-2022-2023-Q1-5", "reporting_period": "Q1"},   # malformed period
        {**base, "reference_number": "C-2022-2023-Q1-5"},                             # duplicate key
    ])
    out = clean(raw)
    reports, vendors, departments = out["contract_reports"], out["vendors"], out["departments"]
    counts = out["dq"].set_index("check_name")["value"]

    assert reports.reference_number.tolist() == ["C-2022-2023-Q1-1", "C-2022-2023-Q1-5"]
    assert counts["reference numbers with a non-ASCII hyphen, replaced"] == 1
    assert counts["dropped: no contract date"] == 1
    assert counts["dropped: contract date before 2017-04-01 (outside load window)"] == 1
    assert counts["dropped: no total contract value"] == 1
    assert counts["dropped: contract date after today"] == 1
    assert counts["dropped: duplicate (owner_org, reference_number), later copy"] == 1
    assert counts["reporting_period not in YYYY-YYYY-Qn form, set to null"] == 1
    assert reports.reporting_period.isna().tolist() == [False, True]

    assert reports.fiscal_year.tolist() == ["2022-2023"] * 2
    assert reports.commodity_type.tolist() == ["S", "S"]
    assert reports.ministers_office.tolist() == [False, False]
    assert reports.number_of_bids.tolist() == [3, 3]
    assert vendors.vendor_name_normalized.tolist() == ["ACME"]
    assert departments.name_en.tolist() == ["National Defence"]
    assert departments.name_fr.tolist() == ["Défense nationale"]
