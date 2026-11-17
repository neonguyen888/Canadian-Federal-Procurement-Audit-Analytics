"""Turn the raw portal CSV into the tables PostgreSQL loads, and count what was changed or dropped.

Author: Neo Nguyen

Source: https://open.canada.ca/data/en/dataset/d8f85d91-7dec-4fd1-8055-483b77225d8b

The portal file is typed by 99 organisations and it shows: dollar values with and without cents,
blank codes, dates in 1900, reference numbers written with a non-breaking hyphen that looks right on
screen and fails every join. This script parses the columns the analysis needs, keeps rows from
LOAD_START on, gives each row a vendor key, and writes these CSVs for sql/01_tables.sql:

  contract_reports.csv   one row per reported transaction (contract, amendment or standing offer)
  vendors.csv            one row per vendor after the rule and fuzzy passes
  vendor_aliases.csv     every cleaned spelling and which vendor it was merged into
  departments.csv        one row per reporting organisation

It also writes vendor_review_sample.csv: 100 merged names, from the space and the fuzzy step, to check by
hand (see reports/report.md).

Every row that is changed or dropped is counted in dq_python.csv, which the report shows next to
the SQL checks. A row is dropped when it falls outside the load window, has a date in the future,
has no date or value, or repeats a key. Anything else odd is kept, and sql/04_checks.sql counts it.
"""
from __future__ import annotations

import pandas as pd

from config import LOAD_START, PROCESSED_DIR, RAW_CSV
from vendors import build_vendor_table, review_precision, review_sample

KEEP = [
    "reference_number", "procurement_id", "vendor_name", "vendor_postal_code", "buyer_name",
    "contract_date", "contract_period_start", "delivery_date",
    "contract_value", "original_value", "amendment_value",
    "economic_object_code", "description_en", "commodity_type", "commodity_code", "country_of_vendor",
    "solicitation_procedure", "limited_tendering_reason", "number_of_bids", "article_6_exceptions",
    "award_criteria", "agreement_type_code", "instrument_type", "contracting_entity", "standing_offer_number",
    "ministers_office", "former_public_servant", "reporting_period", "owner_org", "owner_org_title",
]
MONEY = ["contract_value", "original_value", "amendment_value"]
DATES = ["contract_date", "contract_period_start", "delivery_date"]
CODES = ["commodity_type", "solicitation_procedure", "article_6_exceptions", "instrument_type",
         "contracting_entity", "award_criteria", "agreement_type_code", "country_of_vendor"]
YES_NO = ["ministers_office", "former_public_servant"]
# Characters that look like a hyphen but are not one. Each is replaced with the plain hyphen.
HYPHENS = {"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"}


def fiscal_year(dates: pd.Series) -> pd.Series:
    """Federal fiscal year label, April to March: 2022-05-16 -> "2022-2023", 2023-02-01 -> "2022-2023"."""
    start = dates.dt.year.where(dates.dt.month >= 4, dates.dt.year - 1)
    return start.astype("Int64").astype(str) + "-" + (start + 1).astype("Int64").astype(str)


def fiscal_quarter(dates: pd.Series) -> pd.Series:
    return "Q" + (((dates.dt.month - 4) % 12) // 3 + 1).astype("Int64").astype(str)


def parse_money(s: pd.Series) -> pd.Series:
    return pd.to_numeric(s.str.replace(r"[$,\s]", "", regex=True), errors="coerce").round(2)


def clean(raw: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """Cleans the raw portal frame (all strings). Returns the output tables by name:
    contract_reports, vendors, vendor_aliases, departments, dq."""
    dq: list[tuple[str, int]] = [("rows in portal file", len(raw))]
    df = raw[KEEP].copy()
    for c in df.columns:
        df[c] = df[c].str.strip()

    # ---- Reference numbers: the key for everything downstream ------------------------------
    fixed = df["reference_number"].str.contains("|".join(HYPHENS), regex=True)
    df["reference_number"] = df["reference_number"].replace(HYPHENS, regex=True)
    dq.append(("reference numbers with a non-ASCII hyphen, replaced", int(fixed.sum())))

    # ---- Types ---------------------------------------------------------------------------
    for c in MONEY:
        blank = df[c].eq("")
        df[c] = parse_money(df[c])
        dq.append((f"{c}: blank in file", int(blank.sum())))
        dq.append((f"{c}: present but not a number, set to null", int((df[c].isna() & ~blank).sum())))
    for c in DATES:
        parsed = pd.to_datetime(df[c], errors="coerce", format="%Y-%m-%d")
        dq.append((f"{c}: not a valid date, set to null", int((parsed.isna() & df[c].ne("")).sum())))
        df[c] = parsed
    df["number_of_bids"] = pd.to_numeric(df["number_of_bids"], errors="coerce").astype("Int64")
    for c in CODES:
        df[c] = df[c].str.upper().replace("", pd.NA)
    for c in YES_NO:
        df[c] = df[c].str.upper().map({"Y": True, "N": False})
    df["vendor_postal_fsa"] = df.pop("vendor_postal_code").str.upper().str[:3].replace({"": pd.NA, "NA": pd.NA})
    df["procurement_id"] = df["procurement_id"].replace("", pd.NA)
    df["standing_offer_number"] = df["standing_offer_number"].replace("", pd.NA)
    df["description_en"] = df["description_en"].str[:500]

    # ---- Rows that cannot be used at all -------------------------------------------------
    no_date = df["contract_date"].isna()
    dq.append(("dropped: no contract date", int(no_date.sum())))
    df = df[~no_date]
    before = df["contract_date"] < pd.Timestamp(LOAD_START)
    dq.append((f"dropped: contract date before {LOAD_START} (outside load window)", int(before.sum())))
    df = df[~before]
    future = df["contract_date"] > pd.Timestamp.today().normalize()   # probably a typo in the year
    dq.append(("dropped: contract date after today", int(future.sum())))
    df = df[~future]
    no_value = df["contract_value"].isna()
    dq.append(("dropped: no total contract value", int(no_value.sum())))
    df = df[~no_value]
    dup = df.duplicated(["owner_org", "reference_number"], keep="first")
    dq.append(("dropped: duplicate (owner_org, reference_number), later copy", int(dup.sum())))
    df = df[~dup].copy()

    # ---- Derived columns ------------------------------------------------------------------
    df["fiscal_year"] = fiscal_year(df["contract_date"])
    df["fiscal_quarter"] = fiscal_quarter(df["contract_date"])
    bad_period = ~df["reporting_period"].str.match(r"^\d{4}-\d{4}-Q[1-4]$")
    dq.append(("reporting_period not in YYYY-YYYY-Qn form, set to null", int(bad_period.sum())))
    df.loc[bad_period, "reporting_period"] = pd.NA

    # ---- Vendors and departments ---------------------------------------------------------
    vendors, aliases, df["vendor_id"] = build_vendor_table(df["vendor_name"])
    dq.append(("rows whose vendor name cleaned to nothing (no vendor_id)", int(df["vendor_id"].isna().sum())))
    dq.append(("distinct raw vendor spellings", int(df["vendor_name"].nunique())))
    dq.append(("distinct names after the rule-based pass", len(aliases)))
    dq.append(("names merged by removing spaces", int((aliases.match_method == "squeezed").sum())))
    dq.append(("names merged by fuzzy matching", int((aliases.match_method == "fuzzy").sum())))
    dq.append(("distinct vendors after both passes", len(vendors)))
    titles = df[["owner_org", "owner_org_title"]].drop_duplicates("owner_org").set_index("owner_org")["owner_org_title"]
    departments = pd.DataFrame({
        "owner_org": titles.index,
        "name_en": titles.str.split(" | ", regex=False).str[0].str.strip().values,
        "name_fr": titles.str.split(" | ", regex=False).str[-1].str.strip().values,
    }).sort_values("owner_org")
    dq.append(("rows written to contract_reports.csv", len(df)))

    df = df.rename(columns={"vendor_name": "vendor_name_raw"}).drop(columns=["owner_org_title"])
    return {"contract_reports": df, "vendors": vendors, "vendor_aliases": aliases, "departments": departments,
            "dq": pd.DataFrame(dq, columns=["check_name", "value"])}


def main():
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(RAW_CSV, dtype=str, keep_default_na=False, encoding="utf-8-sig", low_memory=False)
    out = clean(raw)
    for c in DATES:
        out["contract_reports"][c] = out["contract_reports"][c].dt.strftime("%Y-%m-%d")

    # The review file is only written when it does not exist, so verdicts typed into it survive a
    # rerun. Once it has verdicts, they go into the data-quality counts as the merge precision.
    review = PROCESSED_DIR / "vendor_review_sample.csv"
    if not review.exists():
        review_sample(out["vendors"], out["vendor_aliases"]).to_csv(review, index=False)
    reviewed, correct = review_precision(review)
    out["dq"] = pd.concat([out["dq"], pd.DataFrame(
        [("merged names checked by hand", reviewed), ("merged names judged the same vendor", correct)],
        columns=["check_name", "value"])], ignore_index=True)

    for name, table in out.items():
        table.to_csv(PROCESSED_DIR / f"{'dq_python' if name == 'dq' else name}.csv", index=False)
    print(out["dq"].to_string(index=False))


if __name__ == "__main__":
    main()
