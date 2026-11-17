#!/usr/bin/env bash
# Author: Neo Nguyen
# Rebuild everything from scratch, in order:
#   download + header check -> clean + vendor keys -> PostgreSQL tables, tests, scores and checks
#   -> SQL vs pandas reconciliation -> bunching -> sensitivity -> case study -> results file -> charts
#   -> files for the Tableau dashboard -> tests
# PostgreSQL itself must already be running (Postgres.app on a Mac); src/run_sql.py creates the database.
set -euo pipefail
cd "$(dirname "$0")"

# Libraries the project needs. On the first run they go into a private .venv folder, so nothing
# touches the system Python. pyarrow lets pandas hold the 1.3 million text values in less memory;
# rapidfuzz does the fuzzy matching of vendor names.
PACKAGES=("pandas>=2.2" "pyarrow>=15.0" "psycopg[binary]>=3.2" "requests>=2.31" "rapidfuzz>=3.6" "matplotlib>=3.8" "pytest>=8.0")
[ -d .venv ] || { python3 -m venv .venv && .venv/bin/python -m pip install -q "${PACKAGES[@]}"; }

PY="$(pwd)/.venv/bin/python"
(cd src && "$PY" fetch_data.py && "$PY" clean.py && "$PY" run_sql.py && "$PY" reconcile.py \
        && "$PY" bunching.py && "$PY" sensitivity.py && "$PY" case_study.py && "$PY" results.py && "$PY" charts.py \
        && "$PY" export_tableau.py)
"$PY" -m pytest -q tests
rm -rf src/__pycache__ tests/__pycache__ .pytest_cache
