"""Bring the numbers in README.md and reports/report.md up to date after a run on a newer file.

Author: Neo Nguyen

The portal replaces the contracts file most days. results.py keeps the previous run's results as
results_previous.json; this script finds every number that changed, replaces it in the documents in
the way the text already writes it (427,302 / $156.1B / 36.6% / 656 MB), moves the data date on, and
then deletes the previous results. A short number that could also stand for something that did not
change (an "17" that is two different counts, say) is not touched: the script names it, and
tests/test_docs.py fails until a person fixes it, so the documents never quote a stale figure.
"""
from __future__ import annotations

import json
import re
from datetime import datetime

import config

DOCS = [config.ROOT / "README.md", config.ROOT / "reports" / "report.md"]
PREVIOUS = config.PROCESSED_DIR / "results_previous.json"


def flatten(o, path="") -> dict:
    if isinstance(o, dict):
        return {k: v for key, val in o.items() for k, v in flatten(val, f"{path}.{key}").items()}
    if isinstance(o, list):
        return {k: v for i, val in enumerate(o) for k, v in flatten(val, f"{path}[{i}]").items()}
    return {path: o}


def written_forms(value) -> list[tuple[str, str]]:
    """The ways the documents write a number, each with the text that must follow it ("" for any)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return []
    forms = []
    if float(value).is_integer() and abs(value) < 1e8:
        forms.append((f"{value:,.0f}", ""))                                   # counts: 427,302
    if abs(value) >= 1e8:
        forms += [(f"{value / 1e9:,.1f}", "B"), (f"{value / 1e9:,.1f}", " billion"),
                  (f"{value / 1e6:,.1f}", "M"), (f"{value / 1e6:,.1f}", " million"),
                  (f"{value / 1e6:,.0f}", " MB")]                             # money and file size
    elif abs(value) >= 1e6:
        forms += [(f"{value / 1e6:,.1f}", "M"), (f"{value / 1e6:,.1f}", " million")]
    elif not float(value).is_integer():
        forms += [(f"{value:,.{d}f}", "") for d in (1, 2)]                   # shares and ratios
    return forms


def update_text(text: str, old: dict, new: dict) -> tuple[str, set[str]]:
    """Replace changed numbers in `text`. Returns the new text and the numbers left for a person."""
    old_flat, new_flat = flatten(old), flatten(new)
    unchanged = {form for path, v in old_flat.items() if new_flat.get(path) == v for form, _ in written_forms(v)}
    unsure = set()
    for path, before in old_flat.items():
        after = new_flat.get(path)
        if after == before or after is None:
            continue
        for (was, follow), (now, _) in zip(written_forms(before), written_forms(after)):
            if was == now:
                continue
            pattern = rf"(?<![\w.,]){re.escape(was)}(?=(?:{re.escape(follow)})(?![\d]|[.,]\d))"
            if not re.search(pattern, text):
                continue
            if was in unchanged and not follow:      # the same figure also stands for a value that held
                unsure.add(was)
                continue
            text = re.sub(pattern, now, text)
    date = lambda r: datetime.fromisoformat(r["source"]["portal_last_modified"]).strftime("%-d %B %Y")  # noqa: E731
    return text.replace(date(old), date(new)), unsure


def main():
    if not PREVIOUS.exists():
        print("  no previous results: the documents were written from this run")
        return
    old = json.loads(PREVIOUS.read_text())
    new = json.loads((config.PROCESSED_DIR / "results.json").read_text())
    unsure = set()
    for doc in DOCS:
        text, left = update_text(doc.read_text(), old, new)
        unsure |= left
        if text != doc.read_text():
            doc.write_text(text)
            print(f"  updated {doc.relative_to(config.ROOT)}")
    PREVIOUS.unlink()
    if unsure:
        print(f"  check by hand, these could mean more than one figure: {sorted(unsure)}")


if __name__ == "__main__":
    main()
