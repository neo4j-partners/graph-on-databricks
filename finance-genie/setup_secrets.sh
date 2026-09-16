#!/usr/bin/env bash
# Provisions the canonical Finance Genie Databricks secret scope from the root
# .env file. Optional products provision their own credentials separately.
#
# Usage:
#   ./setup_secrets.sh [--profile NAME] [ENV_FILE]
#
# ENV_FILE defaults to finance-genie/.env.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
PROFILE="${DATABRICKS_CONFIG_PROFILE:-${DATABRICKS_PROFILE:-}}"

usage() {
  sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--profile)
      PROFILE="$2"
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
  echo "Copy .env.sample to .env at the finance-genie root and fill in values." >&2
  exit 1
fi

if ! command -v databricks >/dev/null 2>&1; then
  echo "Error: databricks CLI not found." >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$ENV_FILE"

PROFILE="${PROFILE:-${DATABRICKS_CONFIG_PROFILE:-${DATABRICKS_PROFILE:-}}}"
if [[ -z "$PROFILE" ]]; then
  echo "Available Databricks profiles:"
  databricks auth profiles 2>/dev/null || echo "  (could not list profiles; check ~/.databrickscfg)"
  echo
  read -r -p "Profile name [DEFAULT]: " PROFILE
  PROFILE="${PROFILE:-DEFAULT}"
fi

export DATABRICKS_CONFIG_PROFILE="$PROFILE"
echo "Using Databricks profile: $DATABRICKS_CONFIG_PROFILE"

: "${NEO4J_URI:?NEO4J_URI is not set in $ENV_FILE}"
: "${NEO4J_USERNAME:?NEO4J_USERNAME is not set in $ENV_FILE}"
: "${NEO4J_PASSWORD:?NEO4J_PASSWORD is not set in $ENV_FILE}"
: "${GENIE_SPACE_ID_BEFORE:?GENIE_SPACE_ID_BEFORE is not set in $ENV_FILE}"
: "${GENIE_SPACE_ID_AFTER:?GENIE_SPACE_ID_AFTER is not set in $ENV_FILE}"

NEO4J_SECRET_SCOPE="${NEO4J_SECRET_SCOPE:-neo4j-graph-engineering}"

ensure_scope() {
  local scope="$1"
  set +e
  local output
  output="$(databricks secrets create-scope "$scope" 2>&1)"
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
  printf '%s' "$value" | databricks secrets put-secret "$scope" "$key"
}

echo
echo "Writing enrichment-pipeline/workshop Neo4j and Genie secrets"
ensure_scope "$NEO4J_SECRET_SCOPE"
put_secret "$NEO4J_SECRET_SCOPE" "uri" "$NEO4J_URI"
put_secret "$NEO4J_SECRET_SCOPE" "username" "$NEO4J_USERNAME"
put_secret "$NEO4J_SECRET_SCOPE" "password" "$NEO4J_PASSWORD"
put_secret "$NEO4J_SECRET_SCOPE" "genie_space_id_before" "$GENIE_SPACE_ID_BEFORE"
put_secret "$NEO4J_SECRET_SCOPE" "genie_space_id_after" "$GENIE_SPACE_ID_AFTER"
put_secret "$NEO4J_SECRET_SCOPE" "genie_space_id" "$GENIE_SPACE_ID_BEFORE"

echo
echo "Done."
