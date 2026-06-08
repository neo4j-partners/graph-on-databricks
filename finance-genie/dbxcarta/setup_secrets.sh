#!/usr/bin/env bash
# Provisions the Neo4j secret scope for the finance-genie dbxcarta consumer.
#
# The scope name is read from the committed, secret-free dbxcarta-overlay.env
# (DATABRICKS_SECRET_SCOPE, the single source of truth). The NEO4J_URI /
# NEO4J_USERNAME / NEO4J_PASSWORD values are read from the gitignored standalone
# .env. The cluster ingest and client jobs read these back with
# dbutils.secrets.get(scope, key).
#
# Usage:
#   ./setup_secrets.sh [--profile NAME]
#
#   --profile NAME   Databricks profile to create the scope with, overriding the
#                    DATABRICKS_PROFILE in .env.
#
# The script reads:
#   dbxcarta-overlay.env  DATABRICKS_SECRET_SCOPE  required
#   .env  DATABRICKS_PROFILE  optional, used when --profile is not provided
#   .env  NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD  required
#
# Secret key names are uppercase by design. They match the keys read by the
# Databricks jobs.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OVERLAY_FILE="${ROOT_DIR}/dbxcarta-overlay.env"
ENV_FILE=""
PROFILE_OVERRIDE=""

usage() {
  sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'
}

trim() {
  local value="$1"
  value="${value#"${value%%[![:space:]]*}"}"
  value="${value%"${value##*[![:space:]]}"}"
  printf '%s' "$value"
}

env_value() {
  local key="$1"
  local line raw_key raw_value value

  while IFS= read -r line || [[ -n "$line" ]]; do
    line="$(trim "$line")"
    [[ -z "$line" || "$line" == \#* ]] && continue
    [[ "$line" == export\ * ]] && line="$(trim "${line#export }")"
    [[ "$line" != *=* ]] && continue

    raw_key="$(trim "${line%%=*}")"
    [[ "$raw_key" != "$key" ]] && continue

    raw_value="$(trim "${line#*=}")"
    if [[ "$raw_value" == \"*\" && "$raw_value" == *\" ]]; then
      value="${raw_value:1:${#raw_value}-2}"
    elif [[ "$raw_value" == \'*\' && "$raw_value" == *\' ]]; then
      value="${raw_value:1:${#raw_value}-2}"
    else
      value="$raw_value"
    fi
    printf '%s' "$value"
    return 0
  done < "$ENV_FILE"

  return 1
}

is_placeholder() {
  local value="$1"
  [[ -z "$value" || "$value" == *\<* || "$value" == *\>* ]]
}

required_env() {
  local key="$1"
  local value
  value="$(env_value "$key" || true)"
  if is_placeholder "$value"; then
    echo "Error: $key is not set in $ENV_FILE." >&2
    exit 1
  fi
  printf '%s' "$value"
}

ensure_scope() {
  local scope="$1"
  local output rc

  set +e
  output="$(databricks secrets create-scope "$scope" 2>&1)"
  rc=$?
  set -e

  if [[ "$rc" -eq 0 ]]; then
    echo "  created scope: $scope"
  elif [[ "$output" == *"already exists"* || "$output" == *"RESOURCE_ALREADY_EXISTS"* ]]; then
    echo "  scope exists:  $scope"
  else
    echo "Error creating scope $scope: $output" >&2
    exit 1
  fi
}

put_secret() {
  local scope="$1"
  local key="$2"
  local value="$3"
  printf '    - %s/%s\n' "$scope" "$key"
  databricks secrets put-secret "$scope" "$key" --string-value "$value"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -p|--profile)
      [[ $# -lt 2 ]] && { echo "Error: --profile requires a value." >&2; exit 1; }
      PROFILE_OVERRIDE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v databricks >/dev/null 2>&1; then
  echo "Error: databricks CLI not found." >&2
  exit 1
fi

# The committed overlay is the single source of the scope name.
if [[ ! -f "$OVERLAY_FILE" ]]; then
  echo "Error: $OVERLAY_FILE not found." >&2
  exit 1
fi
ENV_FILE="$OVERLAY_FILE"
scope="$(env_value DATABRICKS_SECRET_SCOPE || true)"
if is_placeholder "$scope"; then
  echo "Error: DATABRICKS_SECRET_SCOPE not set in $OVERLAY_FILE." >&2
  exit 1
fi

# Secrets live only in the gitignored standalone .env.
ENV_FILE="${ROOT_DIR}/.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "Error: ${ENV_FILE} not found (copy .env.sample to .env and fill in NEO4J_* values)." >&2
  exit 1
fi

uri="$(required_env NEO4J_URI)"
username="$(required_env NEO4J_USERNAME)"
password="$(required_env NEO4J_PASSWORD)"

profile="${PROFILE_OVERRIDE:-$(env_value DATABRICKS_PROFILE || true)}"
if is_placeholder "$profile"; then
  echo "Error: no DATABRICKS_PROFILE in $ENV_FILE and no --profile given." >&2
  exit 1
fi
export DATABRICKS_CONFIG_PROFILE="$profile"

echo "profile:       $profile"
echo "scope:         $scope (from overlay)"
ensure_scope "$scope"
put_secret "$scope" "NEO4J_URI" "$uri"
put_secret "$scope" "NEO4J_USERNAME" "$username"
put_secret "$scope" "NEO4J_PASSWORD" "$password"

echo
echo "Done. Jobs read these with dbutils.secrets.get(\"$scope\", key)."
