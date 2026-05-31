"""
Central configuration — reads all credentials and settings from environment variables.
Load .env before importing this module:
    from dotenv import load_dotenv; load_dotenv()
"""
import os


def _require(key: str) -> str:
    val = os.getenv(key)
    if not val:
        raise EnvironmentError(f"Required environment variable '{key}' is not set.")
    return val


# ── Anthropic ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY: str = _require("ANTHROPIC_API_KEY")
CLAUDE_MODEL: str = "claude-opus-4-6"

# ── Neo4j AuraDB ─────────────────────────────────────────────────────────────
NEO4J_URI: str = _require("NEO4J_URI")
NEO4J_USERNAME: str = _require("NEO4J_USERNAME")
NEO4J_PASSWORD: str = _require("NEO4J_PASSWORD")
NEO4J_DATABASE: str = os.getenv("NEO4J_DATABASE", "neo4j")

# ── Databricks ───────────────────────────────────────────────────────────────
# The Databricks SDK picks up DATABRICKS_HOST + DATABRICKS_TOKEN automatically,
# or falls back to ~/.databrickscfg. We only read them here for the warehouse lookup.
DATABRICKS_HOST: str = os.getenv(
    "DATABRICKS_HOST", "https://dbc-768fa6aa-1875.cloud.databricks.com"
)

# ── Unity Catalog ─────────────────────────────────────────────────────────────
CATALOG: str = os.getenv("SUPPLYCHAIN_CATALOG", "supplychain")
SCHEMA: str = os.getenv("SUPPLYCHAIN_SCHEMA", "supply_chain_medallion")

# Fully-qualified gold table names
GOLD_SUPPLIER_RISK = f"{CATALOG}.{SCHEMA}.gold_supplier_risk"
GOLD_PART_AVAILABILITY = f"{CATALOG}.{SCHEMA}.gold_part_availability"
GOLD_ACTIVE_POS = f"{CATALOG}.{SCHEMA}.gold_active_purchase_orders"
GOLD_SHIPMENT_PIPELINE = f"{CATALOG}.{SCHEMA}.gold_shipment_pipeline"
GOLD_BOM_EXPLOSION = f"{CATALOG}.{SCHEMA}.gold_bom_explosion"

ANSWER_CACHE_TABLE = f"{CATALOG}.{SCHEMA}.answer_cache"

# ── Agent tuning ──────────────────────────────────────────────────────────────
CACHE_TTL_HOURS: int = int(os.getenv("CACHE_TTL_HOURS", "24"))
MAX_SQL_ROWS: int = int(os.getenv("MAX_SQL_ROWS", "500"))
