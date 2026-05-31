#!/bin/bash
# Step 4 — Deploy the Gradio App to Databricks Apps
# ===================================================
# Uploads the app/ directory to your Databricks workspace and deploys it
# as a serverless Databricks App (no external hosting required).
#
# Prerequisites:
#   - Steps 1-3 complete
#   - Secrets configured: databricks secrets create-scope supply_chain
#   - App service principal granted access (see README Step 5b)
#
# Usage:
#   chmod +x 04_deploy_app.sh
#   ./04_deploy_app.sh

set -e

EMAIL=$(databricks current-user me | python3 -c "import sys,json; print(json.load(sys.stdin)['userName'])")
WORKSPACE_PATH="/Workspace/Users/$EMAIL/supply-chain-optimizer"

echo "Uploading app to $WORKSPACE_PATH ..."
databricks workspace import-dir app "$WORKSPACE_PATH" --overwrite

echo "Deploying Databricks App..."
databricks apps deploy supply-chain-optimizer --source-code-path "$WORKSPACE_PATH"

echo "App deployed. Check status with: databricks apps get supply-chain-optimizer"
