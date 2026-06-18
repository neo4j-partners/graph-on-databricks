#!/usr/bin/env bash
# upload_and_create_tables.sh
#
# 1. Applies schema.sql — creates all five base tables with column-level
#    Unity Catalog comments (DDL only, no data).
# 2. Uploads CSVs from finance-genie/data/ to the Unity Catalog Volume.
# 3. Inserts data into each table from the uploaded CSVs.
#
# Schema and data are intentionally separate:
#   - schema.sql defines column types and descriptions (the contract)
#   - INSERT OVERWRITE loads data without touching the schema
#   - Column comments survive every re-run because they live in the schema DDL
#
# Usage:
#   export DATABRICKS_WAREHOUSE_ID=<sql-warehouse-id>
#   ./upload_and_create_tables.sh
#
# Optional overrides:
#   DATABRICKS_PROFILE   (required — set in .env)
#   DATABRICKS_CATALOG   (default: graph-on-databricks)
#   DATABRICKS_SCHEMA    (default: graph-enriched-schema)
#   DATABRICKS_VOLUME    (default: graph-enriched-volume)

set -euo pipefail

# ── Load shared finance-genie/.env ────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
if [[ ! -f "${ROOT_DIR}/.env" ]]; then
  echo "Error: ${ROOT_DIR}/.env not found. Copy .env.sample to .env at the finance-genie root." >&2
  exit 1
fi
set -o allexport
# shellcheck source=/dev/null
source "${ROOT_DIR}/.env"
set +o allexport

# ── Configuration ─────────────────────────────────────────────────────────────
if [[ -z "${DATABRICKS_PROFILE:-}" ]]; then
  echo "Error: DATABRICKS_PROFILE is not set. Add it to finance-genie/.env." >&2
  exit 1
fi
PROFILE="${DATABRICKS_PROFILE}"
# Silver catalog precedence: SILVER_CATALOG → CATALOG → DATABRICKS_CATALOG →
# literal fallback. With all three unset this is byte-for-byte the legacy
# single-CATALOG behavior. This script only creates the five raw (silver)
# business tables, so the resolved value is the silver catalog.
CATALOG="${SILVER_CATALOG:-${CATALOG:-${DATABRICKS_CATALOG:-graph-on-databricks}}}"
SCHEMA="${DATABRICKS_SCHEMA:-graph-enriched-schema}"
VOLUME="${DATABRICKS_VOLUME:-graph-enriched-volume}"
VOLUME_PATH="/Volumes/${CATALOG}/${SCHEMA}/${VOLUME}"

if [[ -z "${DATABRICKS_WAREHOUSE_ID:-}" ]]; then
  echo "Error: DATABRICKS_WAREHOUSE_ID is not set." >&2
  echo "Find your warehouse ID in Databricks under SQL Warehouses → <warehouse> → Connection Details." >&2
  exit 1
fi

DATA_DIR="${ROOT_DIR}/data"
SCHEMA_FILE="${SCRIPT_DIR}/sql/schema.sql"
CLI="databricks --profile ${PROFILE}"

# ── Helpers ───────────────────────────────────────────────────────────────────
log()  { echo "[$(date '+%H:%M:%S')] $*"; }
ok()   { echo "[$(date '+%H:%M:%S')]   ✓ $*"; }
err()  { echo "[$(date '+%H:%M:%S')]   ✗ $*" >&2; }

# Execute a single SQL statement via the Databricks SQL Statements REST API.
run_sql() {
  local label="$1"
  local sql="$2"
  log "SQL: ${label}"

  local tmpfile
  tmpfile=$(mktemp /tmp/dbr_sql_XXXXX)
  trap 'rm -f "$tmpfile"' RETURN

  python3 - "$DATABRICKS_WAREHOUSE_ID" "$sql" <<'PYEOF' > "$tmpfile"
import json, sys
print(json.dumps({
    "warehouse_id":    sys.argv[1],
    "statement":       sys.argv[2],
    "wait_timeout":    "50s",
    "on_wait_timeout": "CANCEL"
}))
PYEOF

  local result state
  result=$($CLI api post /api/2.0/sql/statements --json @"$tmpfile")
  state=$(echo "$result" | python3 -c \
    'import json,sys; print(json.load(sys.stdin).get("status",{}).get("state","UNKNOWN"))')

  if [[ "$state" != "SUCCEEDED" ]]; then
    local detail
    detail=$(echo "$result" | python3 -c \
      'import json,sys; d=json.load(sys.stdin); e=d.get("status",{}).get("error",{}); print(e)' 2>/dev/null || true)
    err "${label} failed (state=${state}): ${detail}"
    exit 1
  fi
  ok "${label}"
}

# Read schema.sql, substitute ${catalog} and ${schema}, split on semicolons,
# and execute each statement. Column comments in CREATE TABLE DDL survive every
# re-run because they are part of the schema definition, not post-hoc ALTERs.
apply_schema_file() {
  local sql_file="$1"
  log "Applying schema: $(basename "${sql_file}")"

  python3 - "$DATABRICKS_WAREHOUSE_ID" "$sql_file" "$CATALOG" "$SCHEMA" "$PROFILE" <<'PYEOF'
import json, os, subprocess, sys, tempfile

warehouse_id, sql_file, catalog, schema_name, profile = sys.argv[1:]

with open(sql_file) as f:
    text = f.read()
text = text.replace("${catalog}", catalog).replace("${schema}", schema_name)

# Strip comment lines before splitting so semicolons inside comments don't
# become statement boundaries.
text = "\n".join(l for l in text.split("\n") if not l.strip().startswith("--"))
statements = []
for raw in text.split(";"):
    stmt = raw.strip()
    if stmt:
        statements.append(stmt)

cli = ["databricks", "--profile", profile, "api", "post", "/api/2.0/sql/statements"]

for stmt in statements:
    label = next((l.strip() for l in stmt.split("\n") if l.strip()), stmt[:60])
    payload = {
        "warehouse_id":    warehouse_id,
        "statement":       stmt,
        "wait_timeout":    "50s",
        "on_wait_timeout": "CANCEL",
    }
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        tmpname = f.name
    try:
        result = subprocess.run(
            cli + ["--json", f"@{tmpname}"],
            capture_output=True, text=True, check=False,
        )
    finally:
        os.unlink(tmpname)

    if result.returncode != 0:
        print(f"  ✗ CLI error: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    resp = json.loads(result.stdout)
    state = resp.get("status", {}).get("state", "UNKNOWN")
    if state != "SUCCEEDED":
        error = resp.get("status", {}).get("error", {})
        print(f"  ✗ {label}: {error}", file=sys.stderr)
        sys.exit(1)

    print(f"  ✓ {label}")
PYEOF
  ok "Schema applied"
}

# ── Step 1: Bootstrap schema / volume ────────────────────────────────────────
log "=== Step 1: Bootstrapping schema / volume ==="

run_sql "CREATE SCHEMA IF NOT EXISTS" \
  "CREATE SCHEMA IF NOT EXISTS \`${CATALOG}\`.\`${SCHEMA}\`"

run_sql "CREATE VOLUME IF NOT EXISTS" \
  "CREATE VOLUME IF NOT EXISTS \`${CATALOG}\`.\`${SCHEMA}\`.\`${VOLUME}\`"

# ── Step 2: Apply base table schema (DDL with column comments) ────────────────
#
# CREATE OR REPLACE TABLE defines column types and descriptions in Unity Catalog.
# Column comments are part of the schema DDL — they survive every re-run without
# needing post-hoc ALTER statements.
log ""
log "=== Step 2: Applying base table schema (schema.sql) ==="

if [[ ! -f "$SCHEMA_FILE" ]]; then
  err "schema.sql not found at: ${SCHEMA_FILE}"
  exit 1
fi

apply_schema_file "$SCHEMA_FILE"

# ── Step 3: Upload CSVs and ground_truth.json to Volume ──────────────────────
log ""
log "=== Step 3: Uploading data files → ${VOLUME_PATH} ==="

if [[ ! -d "$DATA_DIR" ]]; then
  err "Data directory not found: ${DATA_DIR}"
  exit 1
fi

for csv_file in "${DATA_DIR}"/*.csv; do
  [[ -f "$csv_file" ]] || { err "No CSV files found in ${DATA_DIR}"; exit 1; }
  filename=$(basename "$csv_file")
  log "  Uploading ${filename}…"
  $CLI fs cp "$csv_file" "dbfs:${VOLUME_PATH}/${filename}" --overwrite
  ok "${filename} → ${VOLUME_PATH}/${filename}"
done

GT_FILE="${DATA_DIR}/ground_truth.json"
if [[ ! -f "$GT_FILE" ]]; then
  err "ground_truth.json not found: ${GT_FILE}"
  err "Run 'uv run setup/generate_data.py' to generate it first."
  exit 1
fi
$CLI fs cp "$GT_FILE" "dbfs:${VOLUME_PATH}/ground_truth.json" --overwrite
ok "ground_truth.json → ${VOLUME_PATH}/ground_truth.json"

# ── Step 4: Load data into tables ─────────────────────────────────────────────
#
# INSERT OVERWRITE replaces all rows without touching the schema or column comments.
log ""
log "=== Step 4: Loading data into tables ==="

run_sql "INSERT INTO accounts" \
  "INSERT OVERWRITE \`${CATALOG}\`.\`${SCHEMA}\`.accounts
   SELECT
     CAST(account_id   AS BIGINT)  AS account_id,
     account_hash,
     account_name,
     account_type,
     region,
     CAST(balance      AS DOUBLE)  AS balance,
     CAST(opened_date  AS DATE)    AS opened_date,
     CAST(holder_age   AS INT)     AS holder_age
   FROM read_files(
     '${VOLUME_PATH}/accounts.csv',
     format      => 'csv',
     header      => 'true',
     inferSchema => 'false',
     schema      => 'account_id STRING, account_hash STRING, account_name STRING, account_type STRING, region STRING, balance STRING, opened_date STRING, holder_age STRING'
   )"

run_sql "INSERT INTO merchants" \
  "INSERT OVERWRITE \`${CATALOG}\`.\`${SCHEMA}\`.merchants
   SELECT
     CAST(merchant_id AS BIGINT) AS merchant_id,
     merchant_name,
     category,
     region
   FROM read_files(
     '${VOLUME_PATH}/merchants.csv',
     format      => 'csv',
     header      => 'true',
     inferSchema => 'false',
     schema      => 'merchant_id STRING, merchant_name STRING, category STRING, region STRING'
   )"

run_sql "INSERT INTO transactions" \
  "INSERT OVERWRITE \`${CATALOG}\`.\`${SCHEMA}\`.transactions
   SELECT
     CAST(txn_id        AS BIGINT)    AS txn_id,
     CAST(account_id    AS BIGINT)    AS account_id,
     CAST(merchant_id   AS BIGINT)    AS merchant_id,
     CAST(amount        AS DOUBLE)    AS amount,
     CAST(txn_timestamp AS TIMESTAMP) AS txn_timestamp,
     CAST(txn_hour      AS INT)       AS txn_hour
   FROM read_files(
     '${VOLUME_PATH}/transactions.csv',
     format      => 'csv',
     header      => 'true',
     inferSchema => 'false',
     schema      => 'txn_id STRING, account_id STRING, merchant_id STRING, amount STRING, txn_timestamp STRING, txn_hour STRING'
   )"

run_sql "INSERT INTO account_links" \
  "INSERT OVERWRITE \`${CATALOG}\`.\`${SCHEMA}\`.account_links
   SELECT
     CAST(link_id            AS BIGINT)    AS link_id,
     CAST(src_account_id     AS BIGINT)    AS src_account_id,
     CAST(dst_account_id     AS BIGINT)    AS dst_account_id,
     CAST(amount             AS DOUBLE)    AS amount,
     CAST(transfer_timestamp AS TIMESTAMP) AS transfer_timestamp
   FROM read_files(
     '${VOLUME_PATH}/account_links.csv',
     format      => 'csv',
     header      => 'true',
     inferSchema => 'false',
     schema      => 'link_id STRING, src_account_id STRING, dst_account_id STRING, amount STRING, transfer_timestamp STRING'
   )"

run_sql "INSERT INTO account_labels" \
  "INSERT OVERWRITE \`${CATALOG}\`.\`${SCHEMA}\`.account_labels
   SELECT
     CAST(account_id AS BIGINT)  AS account_id,
     CAST(
       CASE WHEN lower(is_fraud) = 'true' THEN 'true' ELSE 'false' END
       AS BOOLEAN
     ) AS is_fraud
   FROM read_files(
     '${VOLUME_PATH}/account_labels.csv',
     format      => 'csv',
     header      => 'true',
     inferSchema => 'false',
     schema      => 'account_id STRING, is_fraud STRING'
   )"

# ── Done ──────────────────────────────────────────────────────────────────────
log ""
log "=== All done! ==="
log "Volume:  ${VOLUME_PATH}"
log "Tables (schema defined in schema.sql, column comments visible in Catalog Explorer):"
log "  \`${CATALOG}\`.\`${SCHEMA}\`.accounts"
log "  \`${CATALOG}\`.\`${SCHEMA}\`.merchants"
log "  \`${CATALOG}\`.\`${SCHEMA}\`.transactions"
log "  \`${CATALOG}\`.\`${SCHEMA}\`.account_links"
log "  \`${CATALOG}\`.\`${SCHEMA}\`.account_labels"
log "Files:"
log "  ${VOLUME_PATH}/ground_truth.json"
