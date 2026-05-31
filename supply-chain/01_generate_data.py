"""
Step 1 — Generate Synthetic Supply Chain Data
==============================================
Uploads synthetic data to the Databricks volume used by the medallion pipeline.

Two options:
  A) Run as a Databricks notebook (recommended):
       Open data_gen/generate_supply_chain_data_notebook.py in your Databricks workspace
       and click Run All.

  B) Run locally with a Spark session:
       python 01_generate_data.py

Data lands at:
  /Volumes/supplychain/supply_chain_raw/landing/
"""
import subprocess, sys

if __name__ == "__main__":
    subprocess.run([sys.executable, "data_gen/generate_supply_chain_data.py"], check=True)
