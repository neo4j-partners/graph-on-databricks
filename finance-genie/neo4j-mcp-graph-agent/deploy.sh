#!/usr/bin/env bash
# Run the Neo4j MCP graph-agent deployment end to end.
#
# Usage:
#   ./deploy.sh [--profile NAME] [--replace-connection] [--compute cluster|serverless]
#               [--endpoint-timeout-min MINUTES] [--skip-smoke-test]
#
# Prerequisites:
#   1. Copy ../.env.sample to ../.env and fill in Databricks settings.
#   2. Copy the AgentCore-generated .mcp-credentials.json into this directory.
#   3. Authenticate the Databricks CLI/SDK, or pass --profile NAME.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
ROOT_ENV_FILE="${SCRIPT_DIR}/../.env"
CREDENTIALS_FILE="${SCRIPT_DIR}/.mcp-credentials.json"

PROFILE=""
REPLACE_CONNECTION=0
COMPUTE=""
ENDPOINT_TIMEOUT_MIN=30
SKIP_SMOKE_TEST=0
CURRENT_STEP=""

usage() {
  awk '
    NR == 1 { next }
    /^#($| )/ {
      sub(/^# ?/, "")
      print
      next
    }
    { exit }
  ' "$0"
}

fail() {
  echo "Error: $*" >&2
  exit 1
}

on_error() {
  local status=$?
  echo >&2
  echo "FAILED: ${CURRENT_STEP:-deploy} (exit ${status})" >&2
  exit "$status"
}
trap on_error ERR

run_step() {
  CURRENT_STEP="$1"
  shift
  echo
  echo "==> ${CURRENT_STEP}"
  "$@"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--profile)
      [[ $# -ge 2 ]] || fail "--profile requires a value"
      PROFILE="$2"
      shift 2
      ;;
    --replace-connection)
      REPLACE_CONNECTION=1
      shift
      ;;
    --compute)
      [[ $# -ge 2 ]] || fail "--compute requires cluster or serverless"
      case "$2" in
        cluster|serverless) COMPUTE="$2" ;;
        *) fail "--compute must be cluster or serverless" ;;
      esac
      shift 2
      ;;
    --endpoint-timeout-min)
      [[ $# -ge 2 ]] || fail "--endpoint-timeout-min requires a value"
      [[ "$2" =~ ^[0-9]+$ ]] || fail "--endpoint-timeout-min must be an integer"
      ENDPOINT_TIMEOUT_MIN="$2"
      shift 2
      ;;
    --skip-smoke-test)
      SKIP_SMOKE_TEST=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

if [[ -f "$ROOT_ENV_FILE" ]]; then
  ENV_FILE="$ROOT_ENV_FILE"
fi
[[ -f "$ENV_FILE" ]] || fail "${ROOT_ENV_FILE} not found. Copy ../.env.sample to ../.env first."
[[ -f "$CREDENTIALS_FILE" ]] || fail "${CREDENTIALS_FILE} not found. Copy .mcp-credentials.json into this directory first."
command -v uv >/dev/null 2>&1 || fail "uv not found. Install uv before running deploy."

cd "$SCRIPT_DIR"

PROFILE_ARGS=()
if [[ -n "$PROFILE" ]]; then
  PROFILE_ARGS=(--profile "$PROFILE")
  export DATABRICKS_PROFILE="$PROFILE"
fi

CONNECTION_ARGS=("${PROFILE_ARGS[@]}")
if [[ "$REPLACE_CONNECTION" -eq 1 ]]; then
  CONNECTION_ARGS+=(--replace)
fi

COMPUTE_ARGS=()
if [[ -n "$COMPUTE" ]]; then
  export DATABRICKS_COMPUTE_MODE="$COMPUTE"
  COMPUTE_ARGS=(--compute "$COMPUTE")
fi

run_step "Validate local AgentCore credentials" \
  uv run validation/validate_credentials.py

run_step "Store AgentCore OAuth credentials in Databricks secrets" \
  uv run setup/store_secrets.py "${PROFILE_ARGS[@]}"

run_step "Provision UC HTTP connection with MCP enabled" \
  uv run setup/provision_connection.py "${CONNECTION_ARGS[@]}"

run_step "Validate UC HTTP MCP connection" \
  uv run validation/validate_connection.py

run_step "Provision Unity Catalog catalog and schema" \
  uv run setup/provision_uc_resources.py "${PROFILE_ARGS[@]}"

run_step "Upload Databricks job scripts and agent code" \
  uv run python -m cli upload --all

run_step "Run Databricks-side MCP gateway validation" \
  uv run python -m cli submit "${COMPUTE_ARGS[@]}" 00_validate_mcp_gateway.py

run_step "Deploy Neo4j MCP agent endpoint" \
  uv run python -m cli submit "${COMPUTE_ARGS[@]}" 01_deploy_agent.py

CURRENT_STEP="Wait for serving endpoint readiness"
echo
echo "==> ${CURRENT_STEP}"
deadline=$((SECONDS + ENDPOINT_TIMEOUT_MIN * 60))
while true; do
  if uv run validation/validate_endpoint.py; then
    break
  fi
  if (( SECONDS >= deadline )); then
    fail "endpoint did not become READY within ${ENDPOINT_TIMEOUT_MIN} minutes"
  fi
  echo "Endpoint is not READY yet; retrying in 60 seconds..."
  sleep 60
done

if [[ "$SKIP_SMOKE_TEST" -eq 0 ]]; then
  run_step "Run endpoint smoke test" \
    uv run python -m cli submit "${COMPUTE_ARGS[@]}" 02_validate_endpoint.py
else
  echo
  echo "==> Skipping endpoint smoke test"
fi

echo
echo "Deployment complete."
