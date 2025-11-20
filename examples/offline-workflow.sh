#!/bin/sh
# Run from the repository root after `python -m pip install -e ".[dev]"`.
set -eu
mfgbench tasks list
mfgbench tasks validate
mfgbench run supplier-reconciliation --agent oracle
mfgbench run supplier-reconciliation --agent nop
mfgbench run supplier-reconciliation --agent mutation
mfgbench report --format html --output reports/example-offline.html
