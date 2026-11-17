"""Checks on the written documents: links resolve and the wording stays careful. Author: Neo Nguyen"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = [ROOT / "README.md", ROOT / "reports" / "report.md"]


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_local_link_and_image_points_at_a_file(doc):
    targets = re.findall(r"\]\(([^)#]+)(?:#[^)]*)?\)", doc.read_text())
    local = [t for t in targets if not t.startswith(("http://", "https://", "mailto:"))]
    missing = [t for t in local if not (doc.parent / t).exists()]
    assert local and not missing, f"broken links in {doc.name}: {missing}"


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_a_flag_is_never_called_fraud(doc):
    # a flag is a reason to review a contract; the documents must not call it anything stronger
    assert not re.search(r"fraud", doc.read_text(), flags=re.IGNORECASE)


def test_every_figure_drawn_is_used_in_the_report():
    drawn = {p.name for p in (ROOT / "reports" / "figures").glob("*.png")}
    used = set(re.findall(r"figures/([\w.]+\.png)", DOCS[1].read_text()))
    assert drawn and drawn - used == set(), f"figures not in the report: {sorted(drawn - used)}"


# ---- Every number in the documents comes from a run ---------------------------------------------
# A number in README.md or report.md must appear in data/processed/results.json (in any of the ways
# the text rounds it) or be a setting in src/config.py. The few that are neither are listed below.

ELSEWHERE = {
    "19.1", "59.5", "7.9", "2.35", "1.1", "1.38",   # Auditor General's report: dollar figures, Exhibit 1.1, paragraph 1.38
    "100,000",                                       # the regulation's higher limit for some services
    "18,000", "36,000",                              # worked examples: three $18,000 awards; the top 10% band for services
    "277", "12,315",                                 # section 9: figures before the fixes it describes
}


def known_numbers() -> set[str]:
    import json
    import sys
    sys.path.insert(0, str(ROOT / "src"))
    import config

    values = []
    def walk(o):
        if isinstance(o, dict):
            values.append(len(o)); [walk(v) for v in o.values()]
        elif isinstance(o, (list, tuple)):
            values.append(len(o)); [walk(v) for v in o]
        elif isinstance(o, (int, float)) and not isinstance(o, bool):
            values.append(o)
        elif isinstance(o, str):
            values.extend(float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*\.?\d*", o) if n[-1] != ",")
    walk(json.loads((ROOT / "data" / "processed" / "results.json").read_text()))
    walk({k: v for k, v in vars(config).items() if k.isupper()})
    values += [v * 100 for v in values if isinstance(v, float) and v < 1]      # 0.5 -> 50%
    values += list(range(10_000, 100_001, 1_000)) + list(range(13))           # $1,000 bins; small counts
    known = set(ELSEWHERE)
    for v in values:
        for scale in (1, 1e3, 1e6, 1e9):
            for d in (0, 1, 2):
                known.update({f"{v / scale:,.{d}f}", f"{v / scale:.{d}f}"})
    return known


def untraceable(text: str, known: set[str]) -> set[str]:
    """Numbers in `text` that are not in `known`, after removing links, code, dates and identifiers."""
    months = "January|February|March|April|May|June|July|August|September|October|November|December|Jan|Jun|Apr|Mar"
    for pattern in (r"\]\([^)]*\)", r"`[^`]*`", r"https?://\S+", r"SOR/\S+",
                    rf"\b\d{{1,2}} (?:{months})\b", rf"\b(?:{months}) \d{{4}}\b",
                    r"\b(?:19|20)\d\d(?:-\d\d(?:\d\d)?|s)?\b", r"\b\d{4}-\d{4}\b", r"\b[TQ]\d\b", r"s\.6"):
        text = re.sub(pattern, " ", text)
    found = {n.rstrip(".,") for n in re.findall(r"(?<![\w.])\d[\d,]*(?:\.\d+)?", text)}
    return {n for n in found if n not in known and n.replace(",", "") not in known}


def test_an_untraceable_number_is_reported():
    assert untraceable("We found 12,345,678 awards in 2024-25, see SOR/87-402 and 17 November 2026.", {"9"}) == {"12,345,678"}


@pytest.mark.parametrize("doc", DOCS, ids=lambda p: p.name)
def test_every_number_in_the_documents_comes_from_a_run(doc):
    assert untraceable(doc.read_text(), known_numbers()) == set()
