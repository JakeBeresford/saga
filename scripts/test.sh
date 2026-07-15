#!/usr/bin/env bash
#
# Run the test suite. Run by scripts/check.sh and by the CI `test` job (once
# per Python version in the matrix), so local and CI tests are the same.

set -euo pipefail

cd "$(dirname "$0")/.."

printf '\033[1;34m==>\033[0m %s\n' "Running tests"
uv run pytest
