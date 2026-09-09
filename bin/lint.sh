#!/usr/bin/env bash
# Lint via the project's pre-commit hooks — the single source of truth for
# formatters and linters (ruff, yamllint, ...). pre-commit's per-hook file-type
# matching handles routing (a .py runs ruff, a .yml runs yamllint), so there's
# no per-extension logic to maintain here.
#
# Usage:
#   bin/lint.sh            # lint all files
#   bin/lint.sh FILE...    # lint just these files
set -euo pipefail

if [ "$#" -eq 0 ]; then
    uv run pre-commit run --all-files
else
    uv run pre-commit run --files "$@"
fi
