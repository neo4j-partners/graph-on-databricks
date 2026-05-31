"""
Step 3 — Run the Supply Chain Agent (Local CLI or Databricks Notebook)
=======================================================================
Two options:

  A) Local CLI (requires .env with credentials):
       python 03_run_agents.py
       python 03_run_agents.py --question "Which suppliers have Critical risk?"

  B) Databricks notebook:
       Open agents/supply_chain_agent_notebook.py in your Databricks workspace,
       run all cells, then update the Question widget and re-run the last cell.

The agent routes each question to:
  - SQL Agent    → Delta Lake gold tables
  - Graph Agent  → Neo4j AuraDB (Cypher traversal)
  - GDS Agent    → Neo4j AuraDB (graph algorithms)
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from main import main

if __name__ == "__main__":
    main()
