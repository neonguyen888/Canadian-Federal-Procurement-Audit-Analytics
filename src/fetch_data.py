"""Download the contracts file and its data dictionary from open.canada.ca, and record what was fetched.

Author: Neo Nguyen

The CSV is about 650 MB and changes as departments file each quarter, so a run keeps a metadata
file with the portal's last-modified stamp, the size, the download time and the row count. The
file is only downloaded again when the portal's stamp has moved. The data dictionary is checked
against the CSV header before anything else runs: a renamed or added column would otherwise show
up much later as a confusing load error.
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timezone

import requests

from config import CKAN_API, DATASET_URL, PROCESSED_DIR, RAW_CSV, RAW_DIR, RAW_SCHEMA, RESOURCE_ID, SCHEMA_URL

META_PATH = PROCESSED_DIR / "source_metadata.json"
# The portal adds the reporting organisation to every row; the dictionary describes the file departments upload.
PORTAL_COLUMNS = ["owner_org", "owner_org_title"]


def resource_info() -> dict:
    r = requests.get(f"{CKAN_API}/resource_show", params={"id": RESOURCE_ID}, timeout=30)
    r.raise_for_status()
    return r.json()["result"]


def download(url: str, dest) -> None:
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)


def csv_header_and_rows(path) -> tuple[list[str], int]:
    # utf-8-sig drops the byte-order mark the portal puts in front of the first column name
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        header = next(reader)
        n = sum(1 for _ in reader)
    return header, n


def fetch(force: bool = False) -> dict:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    info = resource_info()
    previous = json.loads(META_PATH.read_text()) if META_PATH.exists() else {}

    # Skip the big download when the portal still serves the vintage we already have
    unchanged = (RAW_CSV.exists() and not force
                 and previous.get("portal_last_modified") == info["last_modified"]
                 and RAW_CSV.stat().st_size == info["size"])
    if unchanged:
        print(f"  contracts.csv unchanged on the portal (last modified {info['last_modified']}), keeping local copy")
    else:
        print(f"  downloading contracts.csv ({info['size'] / 1e6:,.0f} MB) ...")
        download(info["url"], RAW_CSV)
    download(SCHEMA_URL, RAW_SCHEMA)

    # ---- Header check against the dictionary ----------------------------------------------
    schema = json.loads(RAW_SCHEMA.read_text())
    expected = [f["id"] for f in schema["resources"][0]["fields"]] + PORTAL_COLUMNS
    header, n_rows = csv_header_and_rows(RAW_CSV)
    if header != expected:
        raise SystemExit(f"CSV header differs from the data dictionary.\n  only in CSV: {set(header) - set(expected)}"
                         f"\n  only in dictionary: {set(expected) - set(header)}")

    meta = {
        "source": "Open Government Portal, Proactive Publication - Contracts over $10,000",
        "dataset_url": DATASET_URL,
        "resource_url": info["url"],
        "schema_url": SCHEMA_URL,
        "portal_last_modified": info["last_modified"],
        "size_bytes": info["size"],
        "downloaded_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds") if not unchanged
                             else previous.get("downloaded_at_utc"),
        "n_rows": n_rows,
        "n_columns": len(header),
        "licence": "Open Government Licence - Canada, https://open.canada.ca/en/open-government-licence-canada",
    }
    META_PATH.write_text(json.dumps(meta, indent=2))
    print(f"  {n_rows:,} rows, {len(header)} columns, portal vintage {info['last_modified'][:10]}")
    return meta


if __name__ == "__main__":
    fetch(force="--force" in sys.argv)
