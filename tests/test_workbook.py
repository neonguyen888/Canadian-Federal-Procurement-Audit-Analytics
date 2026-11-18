"""Checks on the Tableau workbook tableau/build_workbook.py writes.

Author: Neo Nguyen
"""
import importlib.util
import json
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(not (ROOT / "data" / "tableau" / "awards.csv").exists(),
                                reason="the workbook is built from data/tableau, which a run of the pipeline writes")


@pytest.fixture(scope="module")
def workbook(tmp_path_factory):
    spec = importlib.util.spec_from_file_location("build_workbook", ROOT / "tableau" / "build_workbook.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = module.workbook()
    out = tmp_path_factory.mktemp("twb") / "test.twb"
    ET.ElementTree(root).write(out, encoding="utf-8")
    return ET.parse(out).getroot(), out.read_text()


def test_the_three_pages_are_there(workbook):
    root, _ = workbook
    assert [d.get("name") for d in root.iter("dashboard")] == ["Overview", "Limits", "Queue"]


def test_the_data_path_is_relative_so_the_file_opens_anywhere(workbook):
    root, _ = workbook
    dirs = {c.get("directory") for c in root.iter("connection") if c.get("class") == "textscan"}
    assert dirs == {"../data/tableau"}


def test_no_vendor_name_reaches_the_dashboard(workbook):
    _, text = workbook
    assert "vendor_name" not in text and "display_name" not in text


def test_the_text_on_the_dashboard_comes_from_the_run(workbook):
    _, text = workbook
    results = json.loads((ROOT / "data" / "processed" / "results.json").read_text())
    stamp = datetime.fromisoformat(results["source"]["portal_last_modified"]).strftime("%-d %B %Y")
    assert f"as of {stamp}" in text
    assert f"{results['flagged']['pct_flagged']:.1f}% average" in text
    assert f"{results['services_near_limit']['n_last_1000']:,} awards" in text
