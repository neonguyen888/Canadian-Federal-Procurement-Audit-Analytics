"""Tests for src/update_docs.py: bringing the numbers in the documents up to date after a new run.

Author: Neo Nguyen
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from update_docs import update_text  # noqa: E402

OLD = {"source": {"portal_last_modified": "2026-11-17T06:54:42", "size_bytes": 655_508_816},
       "window": {"n_awards": 427_302, "awarded_value": 156_109_748_906.0, "pct_non_competitive": 36.5587},
       "small": {"checks": 17, "other": 17}}


def run(text, **changes):
    new = {k: dict(v) for k, v in OLD.items()}
    for path, value in changes.items():
        group, key = path.split("__")
        new[group][key] = value
    return update_text(text, OLD, new)


def test_a_changed_count_is_replaced_in_every_place_it_appears():
    text, unsure = run("We analysed 427,302 awards. Of the 427,302 awards...", window__n_awards=427_310)
    assert text == "We analysed 427,310 awards. Of the 427,310 awards..." and not unsure


def test_money_and_shares_keep_the_way_the_text_rounds_them():
    text, _ = run("$156.1B at award; 36.6% non-competitive",
                  window__awarded_value=157_240_000_000.0, window__pct_non_competitive=36.71)
    assert text == "$157.2B at award; 36.7% non-competitive"


def test_the_data_date_and_file_size_follow_the_new_file():
    text, _ = run("Data as of: 17 November 2026. The 656 MB file.",
                  source__portal_last_modified="2026-11-18T06:55:09", source__size_bytes=655_472_409)
    assert text == "Data as of: 18 November 2026. The 655 MB file."


def test_a_short_number_that_could_mean_something_else_is_left_for_a_person():
    # "17" is both a count that changed and a count that did not, so the script cannot tell them apart
    text, unsure = run("All 17 checks match.", small__checks=18)
    assert text == "All 17 checks match." and unsure == {"17"}


def test_nothing_changes_when_the_numbers_are_the_same():
    text, unsure = run("We analysed 427,302 awards.")
    assert text == "We analysed 427,302 awards." and not unsure
