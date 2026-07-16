#!/usr/bin/env bash
#
# Validate the codebase: lint, type-check, and test. Run this before pushing
# or releasing. Composes scripts/lint.sh and scripts/test.sh — the same pieces
# CI runs — so the release gate, the local gate, and CI never drift apart.

set -euo pipefail

cd "$(dirname "$0")/.."

scripts/lint.sh
scripts/test.sh

printf '\033[1;34m==>\033[0m %s\n' "All checks passed."
