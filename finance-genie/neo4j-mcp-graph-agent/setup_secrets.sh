#!/usr/bin/env bash
# Stores AgentCore OAuth credentials for the Neo4j MCP graph agent in Databricks
# secrets. This is the Neo4j MCP equivalent of ../enrichment-pipeline/setup_secrets.sh,
# but delegates validation and SDK calls to setup/store_secrets.py.
#
# Secrets written:
#   gateway_host    - scheme and host from .mcp-credentials.json gateway_url
#   client_id       - AgentCore OAuth client id
#   client_secret   - AgentCore OAuth client secret
#   token_endpoint  - AgentCore OAuth token URL
#   oauth_scope     - AgentCore OAuth scope
#
# Usage:
#   ./setup_secrets.sh [--profile NAME]
#
# Prerequisites:
#   1. Copy .env.sample to .env and fill in Databricks settings.
#   2. Copy the AgentCore-generated .mcp-credentials.json into this directory.
#   3. Authenticate the Databricks CLI/SDK, or pass --profile NAME.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
ROOT_ENV_FILE="${SCRIPT_DIR}/../.env"
CREDENTIALS_FILE="${SCRIPT_DIR}/.mcp-credentials.json"
PROFILE=""

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

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--profile)
      if [[ $# -lt 2 ]]; then
        echo "Error: --profile requires a value." >&2
        exit 1
      fi
      PROFILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Error: unknown argument: $1" >&2
      echo "Run ./setup_secrets.sh --help for usage." >&2
      exit 1
      ;;
  esac
done

if [[ -f "$ROOT_ENV_FILE" ]]; then
  ENV_FILE="$ROOT_ENV_FILE"
elif [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: ${ROOT_ENV_FILE} not found." >&2
  echo "Copy ../.env.sample to ../.env and fill in the Databricks settings." >&2
  exit 1
fi

if [[ ! -f "$CREDENTIALS_FILE" ]]; then
  echo "Error: ${CREDENTIALS_FILE} not found." >&2
  echo "Copy the AgentCore-generated .mcp-credentials.json into this directory." >&2
  exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
  echo "Error: uv not found. Install uv before running setup." >&2
  exit 1
fi

cd "$SCRIPT_DIR"

echo "Validating AgentCore credential file..."
uv run validation/validate_credentials.py

echo
echo "Writing AgentCore OAuth credentials to Databricks secrets..."
if [[ -n "$PROFILE" ]]; then
  uv run setup/store_secrets.py --profile "$PROFILE"
else
  uv run setup/store_secrets.py
fi

echo
echo "Done. Continue with:"
echo "  uv run setup/provision_connection.py${PROFILE:+ --profile $PROFILE}"
