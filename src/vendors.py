"""Turn the vendor names departments typed into one key per supplier.

Author: Neo Nguyen

Each department types supplier names its own way. The portal has GC Strategies
as "GC STRATEGIES INC", "GCStrategies Inc.", "GCSTRATEGIES INCORPORATED" and a few more, and one
department prefixes names with its own supplier number ("198085 : GCStrategies Inc."). Every test
that groups by vendor would split such a supplier into several, so the names are cleaned first.

Two passes:
  1. rules: case, accents, punctuation, supplier-number prefixes and legal suffixes. Two names only
     merge when they are the same string after those rules.
  2. fuzzy: names that still differ by a space ("GC STRATEGIES" / "GCSTRATEGIES") or a letter or two
     are merged when their letters match at least FUZZY_THRESHOLD out of 100. Numbered companies
     are never merged across different digits, and short names are left alone. A random sample of
     the fuzzy merges is written out for a manual check; the precision from that check is reported.

The output keeps every alias, so any merge can be traced back and undone.
"""
from __future__ import annotations

import re
import unicodedata

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

from config import FUZZY_MIN_LEN, FUZZY_THRESHOLD, REVIEW_SAMPLE_SIZE, REVIEW_SEED, VENDOR_SUFFIXES

# "198085 : GCStrategies Inc." or "V000123 - Acme": a supplier code glued to the front of the name.
# The lookahead stops it eating a Quebec company number: "9107-0003 Quebec" is a name, not a code.
_CODE_PREFIX = re.compile(r"^\s*[A-Z]?\d{3,}\s*[:\-]\s*(?=\D)")
_NOT_ALNUM = re.compile(r"[^A-Z0-9 ]+")
_SPACES = re.compile(r"\s+")
_DIGITS = re.compile(r"\d+")


# ---- Pass 1: rules ---------------------------------------------------------------------------

def normalize_name(raw: str) -> str:
    """One cleaned key for a raw vendor name. Returns "" when nothing usable is left."""
    s = unicodedata.normalize("NFKD", str(raw)).encode("ascii", "ignore").decode()   # é -> e
    s = _CODE_PREFIX.sub("", s.upper())
    s = s.replace("&", " AND ")
    s = _NOT_ALNUM.sub(" ", s)                 # punctuation becomes a space, so "GC-Strategies" splits
    words = _SPACES.sub(" ", s).strip().split(" ")
    if words and words[0] == "THE":
        words = words[1:]
    # strip legal suffixes from the end until none is left, but never empty the name
    while len(words) > 1 and words[-1] in VENDOR_SUFFIXES:
        words.pop()
    return " ".join(words)


# ---- Pass 2: fuzzy ---------------------------------------------------------------------------

class _Groups:
    """Union-find over key indexes, so merges chain: if A~B and B~C then A, B, C are one vendor."""

    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, i: int, j: int) -> None:
        self.parent[self.find(i)] = self.find(j)


def fuzzy_pairs(keys: list[str]) -> list[tuple[int, int, float, str]]:
    """Index pairs (i, j, score, method) of keys judged to be the same vendor."""
    squeezed = [k.replace(" ", "") for k in keys]
    pairs: list[tuple[int, int, float, str]] = []

    # a) identical once spaces are removed
    first_seen: dict[str, int] = {}
    for i, s in enumerate(squeezed):
        if s in first_seen:
            pairs.append((first_seen[s], i, 100.0, "squeezed"))
        else:
            first_seen[s] = i

    # b) near-identical letters, compared only inside blocks that share the first four letters,
    #    so 95,000 names do not need 95,000 x 95,000 comparisons
    blocks: dict[str, list[int]] = {}
    for s, i in first_seen.items():
        if len(s) >= FUZZY_MIN_LEN:
            blocks.setdefault(s[:4], []).append(i)
    for members in blocks.values():
        if len(members) < 2:
            continue
        names = [squeezed[i] for i in members]
        scores = process.cdist(names, names, scorer=fuzz.ratio, score_cutoff=FUZZY_THRESHOLD, workers=-1)
        for a, b in zip(*np.nonzero(np.triu(scores, k=1))):
            i, j = members[a], members[b]
            if _DIGITS.findall(squeezed[i]) != _DIGITS.findall(squeezed[j]):   # different numbered companies
                continue
            pairs.append((i, j, float(scores[a, b]), "fuzzy"))
    return pairs


# ---- Putting it together ---------------------------------------------------------------------

def build_vendor_table(raw_names: pd.Series, fuzzy: bool = True):
    """Vendor lookup, alias table and the vendor_id for every row.

    Returns (vendors, aliases, ids).
      vendors   one row per vendor: the canonical key (the alias with most rows), the most common raw
                spelling for display, and how many spellings and aliases fed into it
      aliases   one row per rule-cleaned key: which vendor it belongs to and how it got there
      ids       lines up with raw_names; NA where the name cleaned to nothing
    """
    keys = raw_names.map(normalize_name)
    raw = pd.DataFrame({"key": keys, "raw": raw_names.str.strip()}).query("key != ''")
    per_key = raw.groupby("key").size().rename("row_count")
    key_list = per_key.index.tolist()
    index_of = {k: i for i, k in enumerate(key_list)}

    # Each key remembers the weakest match that pulled it into a group, so the alias table shows
    # the least certain step behind every merge. The canonical key of a group is reset to "rule".
    groups = _Groups(len(key_list))
    method = {k: ("rule", 100.0) for k in key_list}
    if fuzzy:
        for i, j, score, how in fuzzy_pairs(key_list):
            groups.union(i, j)
            for k in (key_list[i], key_list[j]):
                if method[k][0] == "rule" or score < method[k][1]:
                    method[k] = (how, score)

    # canonical key per group = the member with the most rows
    members = pd.DataFrame({"key": key_list, "row_count": per_key.values,
                            "root": [groups.find(index_of[k]) for k in key_list]})
    canon = (members.sort_values(["root", "row_count", "key"], ascending=[True, False, True])
             .drop_duplicates("root").set_index("root")["key"])
    alias_to_canon = pd.Series(members["root"].map(canon).values, index=key_list)
    for k in canon.values:
        method[k] = ("rule", 100.0)

    # display name: the most common raw spelling across the whole group
    raw["canon"] = raw["key"].map(alias_to_canon)
    spellings = raw.groupby(["canon", "raw"]).size().rename("n").reset_index()
    display = (spellings.sort_values(["canon", "n", "raw"], ascending=[True, False, True])
               .drop_duplicates("canon").set_index("canon")["raw"])
    vendors = (spellings.groupby("canon").agg(raw_name_count=("raw", "size"), row_count=("n", "sum"))
               .join(display.rename("display_name"))
               .join(alias_to_canon.groupby(alias_to_canon).size().rename("alias_count"))
               .reset_index().rename(columns={"canon": "vendor_name_normalized"})
               .sort_values(["row_count", "vendor_name_normalized"], ascending=[False, True])
               .reset_index(drop=True))
    vendors.insert(0, "vendor_id", range(1, len(vendors) + 1))
    vendors = vendors[["vendor_id", "vendor_name_normalized", "display_name", "raw_name_count", "alias_count", "row_count"]]

    canon_id = vendors.set_index("vendor_name_normalized")["vendor_id"]
    aliases = pd.DataFrame({
        "alias_key": key_list,
        "vendor_id": alias_to_canon.map(canon_id).values,
        "match_method": [method[k][0] for k in key_list],
        "match_score": [method[k][1] for k in key_list],
        "row_count": per_key.values,
    }).sort_values(["vendor_id", "row_count"], ascending=[True, False]).reset_index(drop=True)
    ids = keys.map(alias_to_canon).map(canon_id).astype("Int64")
    return vendors, aliases, ids


def review_sample(vendors: pd.DataFrame, aliases: pd.DataFrame) -> pd.DataFrame:
    """A fixed random sample of merged names (space or fuzzy step) for a manual check, with a blank verdict."""
    merged = aliases[aliases.match_method != "rule"].merge(
        vendors[["vendor_id", "vendor_name_normalized", "display_name"]], on="vendor_id")
    n = min(REVIEW_SAMPLE_SIZE, len(merged))
    sample = merged.sample(n=n, random_state=REVIEW_SEED).sort_values("match_score")
    return sample[["alias_key", "vendor_name_normalized", "display_name", "match_method", "match_score"]] \
        .assign(same_vendor="").reset_index(drop=True)


def review_precision(path) -> tuple[int, int]:
    """(pairs with a verdict, pairs judged the same vendor) from the filled-in review file."""
    try:
        verdict = pd.read_csv(path, dtype=str, keep_default_na=False)["same_vendor"].str.strip().str.lower()
    except FileNotFoundError:
        return 0, 0
    return int(verdict.isin(["yes", "no"]).sum()), int(verdict.eq("yes").sum())
