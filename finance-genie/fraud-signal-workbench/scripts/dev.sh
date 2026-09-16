#!/usr/bin/env bash
#
# dev.sh: run apx dev commands against this project's venv.
#
# Wraps `apx dev <subcommand>` with two project-local fixes so nothing on the
# host machine needs configuring:
#
#   1. PATH is set to include this project's .venv/bin so apx finds the
#      project's uvicorn (and any other entry-point scripts) before any global
#      shadow.
#   2. If the .venv is missing or has a stale shebang (e.g. created before this
#      directory was renamed), it is rebuilt with `uv sync` automatically.
#
# Usage:
#   scripts/dev.sh start         start backend + frontend + OpenAPI watcher
#   scripts/dev.sh stop          stop everything
#   scripts/dev.sh status        what's running and on which ports
#   scripts/dev.sh logs          recent logs
#   scripts/dev.sh logs -f       follow logs
#   scripts/dev.sh check         tsc + ty type checks
#   scripts/dev.sh restart       restart backend (preserves port)
#   scripts/dev.sh -h            show this help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${APP_DIR}/.venv"
VENV_PY="${VENV_DIR}/bin/python"

show_help() {
  awk '/^[^#]/{exit} NR>2{sub(/^# ?/,""); print}' "${BASH_SOURCE[0]}"
  exit 0
}

case "${1:-}" in
  -h|--help) show_help ;;
esac

if ! command -v apx >/dev/null 2>&1; then
  echo "apx CLI not found on PATH." >&2
  echo "Install: curl -fsSL https://databricks-solutions.github.io/apx/install.sh | sh" >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "uv not found on PATH (needed to manage this project's venv)." >&2
  echo "Install: brew install uv  (or see https://docs.astral.sh/uv/)" >&2
  exit 1
fi

venv_stale() {
  [[ ! -x "${VENV_PY}" ]] && return 0
  # The first line of the venv python is its shebang interpreter path.
  # If the interpreter does not exist (e.g. the directory was renamed after
  # the venv was created), the venv is unusable.
  local interp
  interp="$(head -n 1 "${VENV_DIR}/bin/uvicorn" 2>/dev/null | sed 's/^#! *//' || true)"
  [[ -n "${interp}" && ! -x "${interp}" ]] && return 0
  return 1
}

if venv_stale; then
  echo "Recreating ${VENV_DIR} (missing or stale shebang)..."
  rm -rf "${VENV_DIR}"
  (cd "${APP_DIR}" && uv sync)
fi

export PATH="${VENV_DIR}/bin:${PATH}"

cd "${APP_DIR}"
exec apx dev "$@"
