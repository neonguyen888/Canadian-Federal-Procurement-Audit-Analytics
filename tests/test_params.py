"""Every setting the SQL reads must be written from config.py. Author: Neo Nguyen"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from run_sql import PARAMS, missing_params  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


def test_a_setting_the_sql_reads_but_nobody_writes_is_reported():
    assert missing_params("SELECT param('a'), param( 'b' ) FROM t", {"a": 1}) == {"b"}


def test_every_setting_the_sql_files_read_is_written():
    sql = "\n".join(p.read_text() for p in sorted((ROOT / "sql").glob("*.sql")))
    assert missing_params(sql, PARAMS) == set()
