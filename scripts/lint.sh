#!/usr/bin/env bash
#
# Lint and type-check the codebase. Run by scripts/check.sh and by the CI
# `lint` job, so local and CI linting are always the same checks.

set -euo pipefail

cd "$(dirname "$0")/.."

info() { printf '\033[1;34m==>\033[0m %s\n' "$1"; }

info "Ruff lint"
uv run ruff check .

info "Ruff format"
uv run ruff format --check .

info "Type check"
uv run ty check
