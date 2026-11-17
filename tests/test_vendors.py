"""Tests for the vendor name clean-up. Author: Neo Nguyen"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from vendors import (build_vendor_table, fuzzy_pairs, normalize_name, review_precision,  # noqa: E402
                     review_sample)


# ---- rules -----------------------------------------------------------------------------------

def test_case_punctuation_and_legal_suffix_are_ignored():
    assert normalize_name("GC Strategies Inc.") == "GC STRATEGIES"
    assert normalize_name("GC STRATEGIES INC") == "GC STRATEGIES"
    assert normalize_name("GC STRATEGIES INCORPORATED") == "GC STRATEGIES"


def test_supplier_number_prefix_is_dropped():
    assert normalize_name("198085 : GCStrategies Inc.") == "GCSTRATEGIES"


def test_quebec_numbered_company_keeps_its_whole_number():
    # "9107-0003 Québec inc." is a company number, not a supplier code in front of a name
    assert normalize_name("9107-0003 Québec inc.") == "9107 0003 QUEBEC"
    assert normalize_name("9081-0060 QUEBEC INC") != normalize_name("9180-0060 QUÉBEC INC")


def test_accents_ampersand_and_the():
    assert normalize_name("Société Générale") == "SOCIETE GENERALE"
    assert normalize_name("Smith & Wesson Ltd") == "SMITH AND WESSON"
    assert normalize_name("The Right Door Consulting & Solutions Inc.") == "RIGHT DOOR CONSULTING AND SOLUTIONS"


def test_several_suffixes_in_a_row_but_never_an_empty_name():
    assert normalize_name("Acme Co. Ltd.") == "ACME"
    assert normalize_name("Inc.") == "INC"
    assert normalize_name("  ") == ""


def test_rule_pass_alone_keeps_spellings_that_differ_in_letters_apart():
    assert normalize_name("GCStrategies Inc.") != normalize_name("GC Strategies Inc.")


# ---- fuzzy -----------------------------------------------------------------------------------

def test_fuzzy_merges_a_missing_space_and_a_typo_but_not_a_different_number():
    keys = ["GC STRATEGIES", "GCSTRATEGIES", "GC STRATEGIS", "9876543 CANADA", "9876544 CANADA",
            "ACME", "ACMF", "BLUE SKY CONSULTING", "BLUE SKY CONSULTANTS"]
    pairs = {(keys[i], keys[j]): how for i, j, _, how in fuzzy_pairs(keys)}
    assert pairs[("GC STRATEGIES", "GCSTRATEGIES")] == "squeezed"
    assert pairs[("GC STRATEGIES", "GC STRATEGIS")] == "fuzzy"
    assert ("9876543 CANADA", "9876544 CANADA") not in pairs       # digits differ
    assert ("ACME", "ACMF") not in pairs                            # too short to trust
    assert ("BLUE SKY CONSULTING", "BLUE SKY CONSULTANTS") not in pairs   # below the threshold


def test_vendor_table_groups_aliases_and_picks_the_common_spelling():
    names = pd.Series(["GC Strategies Inc.", "GC STRATEGIES INC", "GCStrategies Inc.", "GCStrategies Inc.",
                       "GCStrategies Inc.", "Beta Ltd", ""])
    vendors, aliases, ids = build_vendor_table(names)
    gc = vendors[vendors.display_name == "GCStrategies Inc."].iloc[0]
    assert gc.vendor_name_normalized == "GCSTRATEGIES"             # the alias with most rows is canonical
    assert gc.raw_name_count == 3 and gc.alias_count == 2 and gc.row_count == 5
    assert ids.tolist()[:5] == [gc.vendor_id] * 5 and pd.isna(ids.iloc[6])
    moved = aliases[aliases.alias_key == "GC STRATEGIES"].iloc[0]
    assert moved.vendor_id == gc.vendor_id and moved.match_method == "squeezed"
    assert set(aliases.match_method) == {"rule", "squeezed"}


def test_chained_merge_leaves_exactly_one_rule_alias_per_vendor():
    # A ~ B by a missing space, B ~ C by a typo; C has the most rows, so C is canonical
    names = pd.Series(["GC Strategies", "GCStrategies", "GCStrategis", "GCStrategis", "GCStrategis"])
    vendors, aliases, _ = build_vendor_table(names)
    assert len(vendors) == 1 and vendors.vendor_name_normalized.iloc[0] == "GCSTRATEGIS"
    assert aliases.match_method.tolist().count("rule") == 1
    assert set(aliases.match_method) == {"rule", "squeezed", "fuzzy"}


def test_rule_only_mode_keeps_them_apart():
    vendors, aliases, _ = build_vendor_table(pd.Series(["GC Strategies Inc.", "GCStrategies Inc."]), fuzzy=False)
    assert len(vendors) == 2 and set(aliases.match_method) == {"rule"}


def test_review_sample_lists_only_merged_names_with_a_blank_verdict():
    names = pd.Series(["GC Strategies Inc.", "GCStrategies Inc.", "Beta Ltd"])
    vendors, aliases, _ = build_vendor_table(names)
    sample = review_sample(vendors, aliases)
    assert len(sample) == 1 and sample.same_vendor.tolist() == [""]


def test_review_precision_counts_only_rows_with_a_verdict(tmp_path):
    path = tmp_path / "review.csv"
    pd.DataFrame({"alias_key": ["A", "B", "C"], "same_vendor": ["yes", "no", ""]}).to_csv(path, index=False)
    assert review_precision(path) == (2, 1)
    assert review_precision(tmp_path / "missing.csv") == (0, 0)
