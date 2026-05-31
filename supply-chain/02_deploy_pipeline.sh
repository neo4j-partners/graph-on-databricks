#!/bin/bash
# Step 2 — Deploy and Run the Medallion Pipeline
# ================================================
# Deploys the Lakeflow Spark Declarative Pipeline via Databricks Asset Bundles
# and runs it to populate Bronze → Silver → Gold tables in Unity Catalog.
#
# Prerequisites:
#   - Databricks CLI configured (databricks auth login)
#   - Step 1 complete (data in /Volumes/supplychain/supply_chain_raw/landing/)
#   - Unity Catalog: supplychain.supply_chain_medallion schema must exist
#
# Usage:
#   chmod +x 02_deploy_pipeline.sh
#   ./02_deploy_pipeline.sh

set -e

echo "Deploying pipeline bundle..."
databricks bundle deploy

echo "Running supply chain pipeline..."
databricks bundle run supply_chain_pipeline

echo "Pipeline complete. Gold tables available in supplychain.supply_chain_medallion"
