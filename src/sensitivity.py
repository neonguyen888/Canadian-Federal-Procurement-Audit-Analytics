"""How much do the flag counts depend on the cut-offs?

Author: Neo Nguyen

Each test has one cut-off that is a judgement call: how many days count as "close together", how
far above the award counts as "a lot". This script moves one cut-off at a time and counts the awards
flagged at each setting, using the pandas tests in flags.py. A test whose count barely moves does
not depend much on the choice. One that doubles needs its cut-off defended in the report.
"""
from __future__ import annotations

import pandas as pd

import config
from db import connect, query, read_awards
from flags import flag_amendment_growth, flag_duplicate, flag_near_limit, flag_splitting

# test -> (parameter name, values to try, value used in the analysis, function of (awards, value))
GRID = {
    "T1": ("split_window_days", (15, 30, 60, 90), config.SPLIT_WINDOW_DAYS, flag_splitting),
    "T2": ("near_limit_band", (0.05, 0.10, 0.20), config.NEAR_LIMIT_BAND, flag_near_limit),
    "T3": ("amendment_growth_flag", (0.25, 0.50, 1.00), config.AMENDMENT_GROWTH_FLAG,
           lambda a, v: flag_amendment_growth(a, v, config.AMENDMENT_COUNT_FLAG, config.MIN_ORIGINAL_FOR_GROWTH)),
    "T4": ("duplicate_window_days", (3, 7, 14), config.DUPLICATE_WINDOW_DAYS, flag_duplicate),
}


def main():
    with connect() as con:
        a = read_awards(con)
        sql_counts = query(con, "SELECT test_id, n_flagged FROM vw_test_summary").set_index("test_id")["n_flagged"]

    rows = []
    for test, (parameter, values, base, flag) in GRID.items():
        for value in values:
            flagged = flag(a, value)
            rows.append({"test_id": test, "parameter": parameter, "value": value,
                         "n_flagged": int(flagged.sum()),
                         "awarded_value_flagged": round(float(a.loc[flagged, "original_value"].sum()), 2),
                         "is_base": value == base})
    out = pd.DataFrame(rows)

    # The base setting must reproduce the SQL count, or the comparison is against the wrong thing
    base_rows = out[out["is_base"]].set_index("test_id")["n_flagged"]
    if not (base_rows == sql_counts.reindex(base_rows.index)).all():
        raise SystemExit(f"Base settings do not match SQL:\n{base_rows}\n{sql_counts}")

    out.to_csv(config.PROCESSED_DIR / "sensitivity.csv", index=False)
    print(out.to_string(index=False, float_format=lambda v: f"{v:,.2f}"))


if __name__ == "__main__":
    main()
