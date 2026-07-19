# Makefile for the supplier-risk-graph demo pipeline.
#
# The five steps are one unit, not five independent chores. generate_data.py
# stamps data/ with a fresh as-of date, and load.py, gds.py and upload.py each
# carry that same snapshot onward. Run one without the others and Neo4j or
# Unity Catalog holds a stale snapshot while data/ground_truth.json claims
# today, which surfaces on stage as a figure that does not match the graph.
# `make demo` is the supported way to rebuild.
#
# The as-of date is deliberately not pinned. generate_data.py defaults --as-of
# to date.today() because the demo shows forward-looking risk, so every euro
# amount, invoice and finding count, quarter label and exposure number moves
# with the build. `make expected` prints what this build actually produced.
#
# DESTRUCTIVE. `make demo` wipes live state before it writes:
#   - load.py runs DETACH DELETE over every node in the target Neo4j database
#     before loading, so that database must be dedicated to this demo.
#   - upload.py rebuilds its Unity Catalog tables and metric view with
#     CREATE OR REPLACE.
# There is no confirmation prompt on purpose: this has to run non-interactively.
# `make check` validates the CSVs offline and touches neither system.
#
# Credentials for load.py, gds.py and upload.py come from .env (see .env.sample).

UV ?= uv

.DEFAULT_GOAL := help
.PHONY: help demo data check expected guard

help:
	@echo "supplier-risk-graph demo pipeline"
	@echo ""
	@echo "  make demo      Rebuild the whole demo: regenerate data/, reload"
	@echo "                 Neo4j, recompute graph metrics, rebuild Unity Catalog."
	@echo "                 DESTRUCTIVE: wipes the target Neo4j database"
	@echo "                 (DETACH DELETE on every node) and replaces the UC"
	@echo "                 tables. No confirmation prompt. Stops on first failure."
	@echo "  make data      Regenerate data/ CSVs and ground_truth.json only."
	@echo "                 Fresh as-of date, so every date-derived figure moves."
	@echo "  make check     Offline validation only. Parses the CSVs, checks"
	@echo "                 referential integrity and the UC column contracts."
	@echo "                 Connects to nothing and changes nothing."
	@echo "  make guard     Vocabulary guard against the LIVE workspace: Unity"
	@echo "                 Catalog names and comments, and the Genie space."
	@echo "                 Read-only. Run in pre-flight on the day, because the"
	@echo "                 space is hand-synced and can drift after a build."
	@echo "  make expected  Print the presenter's expected-results table for the"
	@echo "                 current data/ground_truth.json."
	@echo "  make help      This message."
	@echo ""
	@echo "The as-of date is never pinned: the demo shows forward-looking risk."
	@echo "After 'make demo', run 'make expected' for the figures to confirm."

# The steps live in one recipe rather than as prerequisites so their order is
# guaranteed even under make -j. Each line is its own shell and make stops on
# the first non-zero exit, so a failed step never lets a later one publish a
# half-built snapshot.
demo:
	@echo "==> [1/5] generate_data.py: writing data/ CSVs and ground_truth.json"
	$(UV) run generate_data.py
	@echo "==> [2/5] load.py: WIPING Neo4j and reloading from data/"
	$(UV) run load.py
	@echo "==> [3/5] gds.py: computing betweenness and pageRank into Neo4j"
	$(UV) run gds.py
	@echo "==> [4/5] upload.py: rebuilding Unity Catalog tables and metric view"
	$(UV) run upload.py
	@echo "==> [5/5] guard.py: no governed vocabulary visible to Run A"
	$(UV) run guard.py
	@echo "==> Pipeline complete. Expected results for this build:"
	$(UV) run expected_results.py

data:
	$(UV) run generate_data.py

# Offline validation. load.py --check parses every node and relationship CSV
# and resolves every relationship endpoint; upload.py --check confirms the base
# CSVs carry the load-bearing columns their table specs and comments name.
# gds.py has no --check mode: it has nothing to validate without a loaded graph,
# since every assertion it makes is about scores it computes in Neo4j.
check:
	$(UV) run load.py --check
	$(UV) run upload.py --check
	$(UV) run guard.py --offline

# The live half of the guard, split out so it can run on its own on the day.
# `make demo` runs it as step 5; this target is the pre-flight re-run, and it
# exists because the Genie space is hand-synced through the manage_genie MCP
# tool, so a build-time pass says nothing about the space at demo time.
guard:
	$(UV) run guard.py

expected:
	$(UV) run expected_results.py
