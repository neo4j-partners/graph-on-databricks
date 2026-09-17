# Canonical Finance Genie environment.
#
# `make demo` intentionally prepares only the shared data platform: Silver
# tables, the Aura graph and its GDS properties, Gold tables, and the two Genie
# spaces. It does not deploy the optional Fraud Signal Workbench, MCP graph
# agent, or Virtual Graph demo.

UV ?= uv
PIPELINE_DIR := enrichment-pipeline

.DEFAULT_GOAL := help
.PHONY: help demo graph check data

help:
	@echo "Finance Genie canonical environment"
	@echo ""
	@echo "  make demo   Build the shared Silver -> Neo4j/GDS -> Gold -> Genie demo."
	@echo "              Creates or reconciles the canonical BEFORE and AFTER Genie"
	@echo "              spaces, then stores their IDs in the local .env file."
	@echo "              Does not deploy optional apps, agents, or a Virtual Graph."
	@echo "  make graph  Rebuild Neo4j and its GDS properties from existing Silver tables."
	@echo "  make check  Validate Databricks, Neo4j, and the committed fraud dataset."
	@echo "  make data   Regenerate the local synthetic dataset only."
	@echo "  make help   Show this message."
	@echo ""
	@echo "First run: cp .env.sample .env, fill in workspace/Neo4j values, then make demo."
	@echo "make demo updates shared tables and clears/reloads the configured Neo4j graph."

demo:
	@echo "==> Building the canonical Finance Genie environment"
	cd $(PIPELINE_DIR) && $(UV) run python run_existing_data_pipeline.py

graph:
	@echo "==> Building the Finance Genie graph from existing Silver tables"
	cd $(PIPELINE_DIR) && PIPELINE_START_STEP=7 PIPELINE_STOP_STEP=8 $(UV) run python run_existing_data_pipeline.py
	cd $(PIPELINE_DIR) && PIPELINE_START_STEP=10 PIPELINE_STOP_STEP=12 $(UV) run python run_existing_data_pipeline.py

check:
	@echo "==> Validating the canonical Finance Genie environment"
	cd $(PIPELINE_DIR) && $(UV) run python validation/validate_cluster.py
	cd $(PIPELINE_DIR) && $(UV) run python validation/validate_neo4j.py
	cd $(PIPELINE_DIR) && $(UV) run python diagnostics/verify_fraud_patterns.py --input ../data

data:
	@echo "==> Regenerating Finance Genie synthetic data"
	cd $(PIPELINE_DIR) && $(UV) run python setup/generate_data.py
