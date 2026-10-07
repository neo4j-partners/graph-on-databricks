#!/usr/bin/env bash
# Provisions the Databricks secret scope for the neo4j-mcp-graph-agent from its .env file.
# The deployed app reads the NAMS key through the `nams-api-key` app resource, which points at
# the scope and key written here.
#
# Usage:
#   ./setup_secrets.sh [--profile NAME] [ENV_FILE]
#
# The profile is DATABRICKS_CONFIG_PROFILE from ENV_FILE. --profile overrides it.
# ENV_FILE defaults to .env in this directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${SCRIPT_DIR}/.env"
PROFILE=""

usage() {
  sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--profile)
      PROFILE="${2:?--profile needs a value}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      ENV_FILE="$(cd "$(dirname "$1")" && pwd)/$(basename "$1")"
      shift
      ;;
  esac
done

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: $ENV_FILE not found." >&2
  echo "Copy .env.example to .env and fill in values." >&2
  exit 1
fi

if ! command -v databricks >/dev/null 2>&1; then
  echo "Error: databricks CLI not found." >&2
  exit 1
fi

# Reads one KEY=value line from ENV_FILE without executing the file. Strips matching quotes.
env_value() {
  local line
  line="$(grep -E "^[[:space:]]*$1=" "$ENV_FILE" | tail -n 1 || true)"
  line="${line#*=}"
  line="${line%%[[:space:]]#*}"
  line="${line#"${line%%[![:space:]]*}"}"
  line="${line%"${line##*[![:space:]]}"}"
  if [[ "$line" =~ ^\"(.*)\"$ || "$line" =~ ^\'(.*)\'$ ]]; then
    line="${BASH_REMATCH[1]}"
  fi
  printf '%s' "$line"
}

PROFILE="${PROFILE:-$(env_value DATABRICKS_CONFIG_PROFILE)}"
if [[ -z "$PROFILE" ]]; then
  echo "Error: DATABRICKS_CONFIG_PROFILE is not set in $ENV_FILE and --profile was not given." >&2
  exit 1
fi
echo "Using Databricks profile: $PROFILE"

MEMORY_API_KEY="$(env_value MEMORY_API_KEY)"
if [[ -z "$MEMORY_API_KEY" ]]; then
  echo "Error: MEMORY_API_KEY is not set in $ENV_FILE." >&2
  exit 1
fi

NAMS_SECRET_SCOPE="$(env_value NAMS_SECRET_SCOPE)"
NAMS_SECRET_SCOPE="${NAMS_SECRET_SCOPE:-nams}"

ensure_scope() {
  local scope="$1"
  set +e
  local output
  output="$(databricks secrets create-scope "$scope" --profile "$PROFILE" 2>&1)"
  local rc=$?
  set -e

  if [[ "$rc" -eq 0 ]]; then
    echo "Created secret scope: $scope"
  elif [[ "$output" == *"already exists"* ]]; then
    echo "Secret scope already exists: $scope"
  else
    echo "Error creating scope $scope: $output" >&2
    exit 1
  fi
}

put_secret() {
  local scope="$1"
  local key="$2"
  local value="$3"
  printf '  - %s/%s\n' "$scope" "$key"
  # Feed values through stdin so they are not exposed in the local process list.
  printf '%s' "$value" | databricks secrets put-secret "$scope" "$key" --profile "$PROFILE"
}

echo
echo "Writing NAMS secret"
ensure_scope "$NAMS_SECRET_SCOPE"
put_secret "$NAMS_SECRET_SCOPE" "memory-api-key" "$MEMORY_API_KEY"

echo
echo "Done."
echo "App resource: nams-api-key -> scope $NAMS_SECRET_SCOPE, key memory-api-key, CAN_READ"
