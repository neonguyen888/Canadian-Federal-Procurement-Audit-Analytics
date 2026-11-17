"""Project-wide settings.

Author: Neo Nguyen

Every number that shapes the analysis lives here: where the data comes from, which dates are loaded
and analysed, the dollar limits from the Government Contracts Regulations, and the cut-offs each
audit test uses. The cut-offs are round, conventional values (30 days, 50%, one week). They were not
tuned to the results; src/sensitivity.py shows how the flag counts move when they change.
"""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
PROCESSED_DIR = ROOT / "data" / "processed"
FIGURES_DIR = ROOT / "reports" / "figures"

# PostgreSQL. Postgres.app on a Mac accepts the logged-in user with no password.
# Override with e.g. PROCUREMENT_PG_DSN="host=localhost dbname=procurement_audit user=me password=..."
PG_DSN = os.environ.get("PROCUREMENT_PG_DSN", "host=localhost port=5432 dbname=procurement_audit")
PG_SCHEMA = "procurement"

# ---- Source data --------------------------------------------------------------------------------
# Proactive Publication: Contracts over $10,000, Government of Canada, Open Government Licence.
# One CSV for every federal organisation, refreshed as departments report each quarter.
#   dataset page     https://open.canada.ca/data/en/dataset/d8f85d91-7dec-4fd1-8055-483b77225d8b
#   the CSV          https://open.canada.ca/data/en/dataset/d8f85d91-7dec-4fd1-8055-483b77225d8b/resource/fac950c0-00d5-4ec1-a4d3-9cbebf98a305
#   data dictionary  https://open.canada.ca/data/recombinant-published-schema/contracts.json
#   search one row   https://search.open.canada.ca/contracts/
#   licence          https://open.canada.ca/en/open-government-licence-canada
# fetch_data.py asks the portal's API (CKAN) where the CSV is and when it last changed.
CKAN_API = "https://open.canada.ca/data/api/action"
DATASET_ID = "d8f85d91-7dec-4fd1-8055-483b77225d8b"
RESOURCE_ID = "fac950c0-00d5-4ec1-a4d3-9cbebf98a305"
DATASET_URL = f"https://open.canada.ca/data/en/dataset/{DATASET_ID}"
SCHEMA_URL = "https://open.canada.ca/data/recombinant-published-schema/contracts.json"
RAW_CSV = RAW_DIR / "contracts.csv"
RAW_SCHEMA = RAW_DIR / "contracts_schema.json"

# ---- Government Contracts Regulations, section 6(b) ---------------------------------------------
# A department may award a contract without soliciting bids when the estimated expenditure "does not
# exceed" $25,000 for goods or $40,000 for any other contract, so $40,000 exactly is still within it.
#   section 6, in force   https://laws-lois.justice.gc.ca/eng/regulations/SOR-87-402/section-6.html
# These limits came in on 10 June 2019 (SOR/2019-199) and section 6 has not been amended since.
# Before that date the limit was $25,000 for goods and services alike, a wording last amended in 1996:
#   earlier wording       https://laws-lois.justice.gc.ca/eng/regulations/SOR-87-402/section-6-20060322.html
# The regulation also allows $100,000 for architectural and engineering services tied to construction
# and for international development work. The data cannot pick those contracts out, so they are tested
# against $40,000, which is stricter than the rule for that group.
S6B_LIMIT = {"G": 25_000, "S": 40_000, "C": 40_000}      # by commodity_type: Good, Service, Construction
NEAR_LIMIT_BAND = 0.10          # "near the limit" = the top 10% of the range (e.g. $36,000 to $40,000)

# ---- Dates --------------------------------------------------------------------------------------
# The portal holds rows back to the 1990s, but whether a row is an award or an amendment is only
# recorded reliably from fiscal 2017-18 (27% of 2016-17 rows leave it blank). Rows are loaded from
# then so that an amendment can find its award. The tests start on the day the limits above came in.
LOAD_START = "2017-04-01"
ANALYSIS_START = "2019-06-10"

# ---- Audit test cut-offs ------------------------------------------------------------------------
SPLIT_WINDOW_DAYS = 30          # T1: awards to one vendor from one department inside this many days
AMENDMENT_GROWTH_FLAG = 0.50    # T3: value now more than 50% above the award ...
AMENDMENT_COUNT_FLAG = 3        #     ... or at least this many amendments
MIN_ORIGINAL_FOR_GROWTH = 10_000  #   awards smaller than this are skipped (a $1 award can grow 100,000%)
DUPLICATE_WINDOW_DAYS = 7       # T4: same department, vendor and value within a week
CONCENTRATION_SHARE = 0.50      # T5: one vendor with over half a department's non-competitive spend ...
CONCENTRATION_MIN_SPEND = 1_000_000  # ... in departments with at least this much non-competitive spend

# ---- Risk score ---------------------------------------------------------------------------------
# Points per test, adding up to 100. Splitting and amendment growth weigh most: each describes a
# contract that ended up past a control. A duplicate is often a batch of task authorisations, and
# concentration says more about the vendor than about any one award.
RISK_WEIGHTS = {"T1": 30, "T2": 20, "T3": 25, "T4": 15, "T5": 10}

# ---- Bunching under the limit (src/bunching.py) -------------------------------------------------
# Awards are counted in $1,000 bins. A log-linear trend is fitted to the BUNCH_FIT_SPAN below the
# window and extended across the BUNCH_WINDOW up to the limit.
BUNCH_BIN_WIDTH = 1_000
BUNCH_WINDOW = 5_000              # the last $5,000 up to and including the limit
BUNCH_FIT_SPAN = 10_000           # the trend comes from the $10,000 below that window
BUNCH_BOOTSTRAP = 500             # resamples behind each 95% interval
BUNCH_SEED = 20261116
BUNCH_MIN_AWARDS = 300            # a department needs this many awards in range for its own estimate
# Round values where no procurement rule changes, used as a yardstick for how much excess
# round-number pricing produces by itself. Their fit ranges stay clear of both real limits.
PLACEBO_LIMITS = (60_000, 70_000, 80_000, 90_000)

# ---- ArriveCAN case study (src/case_study.py) ---------------------------------------------------
# Auditor General of Canada, 2024 Report 1: ArriveCAN (tabled 12 February 2024).
#   report   https://www.oag-bvg.gc.ca/internet/English/att__e_44429.html
#   PDF      https://open.canada.ca/data/en/info/2a492f50-15c0-4ced-91b9-3260e85e1f7a
# Exhibit 1.1 puts GC Strategies ($19.1M) and Dalian Enterprises ($7.9M) first among contractors, and
# paragraph 1.38 says the first contract went to GC Strategies through a non-competitive process in
# April 2020. Coradix is Dalian's joint-venture partner; CBSA's briefing to the Public Accounts
# committee lists GC Strategies, Coradix and the Dalian/Coradix joint venture together:
#   https://www.cbsa-asfc.gc.ca/transparency-transparence/pd-dp/bbp-rpp/pacp/2024-05-14/overview-apercu-eng.html
# The case group is every CBSA award to those firms from April 2020 to March 2023 (Exhibit 1.1 runs to
# 31 March 2023). The data does not say which contracts were for ArriveCAN, so the group is wider.
CASE_OWNER_ORG = "cbsa-asfc"
CASE_VENDOR_PATTERN = r"GC ?STRATEGIES|DALIAN|CORADIX"      # matched against every cleaned vendor spelling
CASE_START, CASE_END = "2020-04-01", "2023-03-31"
# The first ArriveCAN contract as paragraph 1.38 describes it, matched to its award row in the data
AUDIT_FIRST_CONTRACT = {"owner_org": "cbsa-asfc", "award_date": "2020-04-08", "original_value": 2_350_000}
# The case awards are all services and mostly large; amendments and duplicates are both more common
# on large contracts. The like-for-like comparison uses service awards of at least this much.
CASE_COMPARABLE_MIN = 100_000

# ---- Vendor names (src/vendors.py) --------------------------------------------------------------
# After the rule-based clean-up, names still spelt slightly differently are merged when their letters
# (spaces removed) match at FUZZY_THRESHOLD out of 100 or better and both have at least FUZZY_MIN_LEN
# letters. Names whose digits differ never merge: "9876543 CANADA" and "9876544 CANADA" are two
# numbered companies. A random sample of merges is written out to be checked by hand.
FUZZY_THRESHOLD = 94
FUZZY_MIN_LEN = 6
REVIEW_SAMPLE_SIZE = 100
REVIEW_SEED = 20261116

# Legal-form words that departments write inconsistently ("Inc", "Inc.", "Incorporated"). They are
# dropped from the end of a name until none is left: "ABC Consulting Ltd. Inc" becomes "ABC CONSULTING".
VENDOR_SUFFIXES = {
    "INC", "INCORPORATED", "INCORPORATION", "LTD", "LIMITED", "LTEE", "LIMITEE", "LLC", "LLP", "LP",
    "CORP", "CORPORATION", "CO", "COMPANY", "ULC", "PLC", "GMBH", "SA", "SRL", "SARL", "SENC", "ENR",
    "SEC", "PTY", "AG", "BV", "NV", "AB", "OY", "AS", "SAS", "SPA", "KK", "LLLP",
}
