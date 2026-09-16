#!/usr/bin/env bash
#
# deploy.sh: deploy the graph-fraud-analyst bundle to Databricks.
#
# Reads the shared finance-genie/.env (one directory up) for:
#   DATABRICKS_PROFILE             ~/.databrickscfg profile name
#   GRAPH_FRAUD_ANALYST_WAREHOUSE_ID     SQL warehouse the app queries
#   GRAPH_FRAUD_ANALYST_GENIE_SPACE_ID   Genie Space the app calls
#
# Usage:
#   scripts/deploy.sh           deploy and exit
#   scripts/deploy.sh --log     deploy, then tail app logs until you ctrl-c
#   scripts/deploy.sh -h        show this help

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
ROOT_DIR="$(cd "${APP_DIR}/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"

show_help() {
  awk '/^[^#]/{exit} NR>2{sub(/^# ?/,""); print}' "${BASH_SOURCE[0]}"
  exit 0
}

case "${1:-}" in
  -h|--help) show_help ;;
esac

LOG_AFTER_DEPLOY=false
if [[ "${1:-}" == "--log" ]]; then
  LOG_AFTER_DEPLOY=true
fi

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "❌ Missing ${ENV_FILE}"
  echo "   cp ${ROOT_DIR}/.env.sample ${ENV_FILE} and fill in values."
  echo "   The finance-genie repo uses one shared .env at the repo root."
  exit 1
fi

# shellcheck disable=SC1090
set -a; source "${ENV_FILE}"; set +a

: "${DATABRICKS_PROFILE:?DATABRICKS_PROFILE must be set in .env}"
: "${GRAPH_FRAUD_ANALYST_WAREHOUSE_ID:?GRAPH_FRAUD_ANALYST_WAREHOUSE_ID must be set in .env}"
: "${GRAPH_FRAUD_ANALYST_GENIE_SPACE_ID:?GRAPH_FRAUD_ANALYST_GENIE_SPACE_ID must be set in .env}"

APP_NAME="graph-fraud-analyst"
BUNDLE_APP_KEY="graph-fraud-analyst-app"

echo "── graph-fraud-analyst deploy ─────────────────────────────────────────"
echo "  profile        : ${DATABRICKS_PROFILE}"
echo "  warehouse_id   : ${GRAPH_FRAUD_ANALYST_WAREHOUSE_ID}"
echo "  genie_space_id : ${GRAPH_FRAUD_ANALYST_GENIE_SPACE_ID}"
echo "  catalog        : ${GRAPH_FRAUD_ANALYST_CATALOG:-graph-on-databricks}"
echo "  schema         : ${GRAPH_FRAUD_ANALYST_SCHEMA:-graph-enriched-schema}"
echo "──────────────────────────────────────────────────────────────────"

cd "${APP_DIR}"

# Step 1: upload bundle + create/update the app resource.
databricks bundle deploy \
  --profile "${DATABRICKS_PROFILE}" \
  --var "warehouse_id=${GRAPH_FRAUD_ANALYST_WAREHOUSE_ID}" \
  --var "genie_space_id=${GRAPH_FRAUD_ANALYST_GENIE_SPACE_ID}"

echo ""
echo "✅ Bundle deployed."

# Step 2: push the uploaded source to the app's compute and start uvicorn.
# bundle deploy alone leaves the app UNAVAILABLE with zero deployments.
echo ""
echo "🚀 Starting app on compute…"
databricks bundle run "${BUNDLE_APP_KEY}" \
  --profile "${DATABRICKS_PROFILE}" \
  --var "warehouse_id=${GRAPH_FRAUD_ANALYST_WAREHOUSE_ID}" \
  --var "genie_space_id=${GRAPH_FRAUD_ANALYST_GENIE_SPACE_ID}"

echo ""
echo "✅ App is live."

if [[ "${LOG_AFTER_DEPLOY}" == "true" ]]; then
  echo ""
  echo "📜 Tailing logs for app '${APP_NAME}' (ctrl-c to stop)…"
  echo ""
  databricks apps logs "${APP_NAME}" --profile "${DATABRICKS_PROFILE}" --follow
fi
