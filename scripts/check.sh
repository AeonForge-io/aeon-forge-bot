#!/bin/sh
# Run one project check: scripts/check.sh <format|lint|test>
# uv syncs the environment from uv.lock (so a fresh worktree needs no .venv) and downloads Python 3.11
# (python-build-standalone from GitHub) into ~/.cache, to match production. Running it rebuilds this .venv on 3.11.
set -eu

export UV_PYTHON_INSTALL_DIR="$HOME/.cache/uv-python"
export UV_CACHE_DIR="$HOME/.cache/uv"
export UV_LINK_MODE=copy
export MYPY_CACHE_DIR="$HOME/.cache/aeon-forge-bot/mypy"
export RUFF_CACHE_DIR="$HOME/.cache/aeon-forge-bot/ruff"
export PYTEST_ADDOPTS="-p no:cacheprovider ${PYTEST_ADDOPTS:-}"

cd "$(dirname "$0")/.."
uv_run="uv run --locked --extra dev --python 3.11"

case "${1:-}" in
format) exec $uv_run python scripts/check_format.py ;;
lint) shift; exec $uv_run python scripts/check_lint.py "$@" ;;
test) exec $uv_run pytest ;;
*) echo "usage: scripts/check.sh <format|lint|test>" >&2; exit 2 ;;
esac
