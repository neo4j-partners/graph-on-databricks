# Databricks notebook source

# COMMAND ----------
# MAGIC %md
# MAGIC # Supply Chain Agent — MLflow Registration
# MAGIC
# MAGIC Wraps the Graph and GDS agents as MLflow PyFunc models, registers them in Unity Catalog,
# MAGIC and deploys them as Model Serving endpoints for use with the AgentBricks Supervisor.
# MAGIC
# MAGIC **Run order:**
# MAGIC 1. Run all cells to register both models
# MAGIC 2. Deploy endpoints from the Serving UI or via the last cell
# MAGIC 3. Add endpoints to the Supply Chain Supervisor in AgentBricks

# COMMAND ----------
# MAGIC %pip install anthropic>=0.49.0 neo4j>=5.18.0 mlflow>=2.13.0 databricks-sdk --quiet

# COMMAND ----------
import os, json, mlflow
from mlflow.models import infer_signature
import pandas as pd

# Disable system metrics logging — blocked in serverless by Py4J security
mlflow.disable_system_metrics_logging()
os.environ["MLFLOW_ENABLE_SYSTEM_METRICS_LOGGING"] = "false"

CATALOG  = "supplychain_optimizer"
SCHEMA   = "supply_chain_medallion"

mlflow.set_registry_uri("databricks-uc")

# Paths to code-based model files (must be uploaded alongside this notebook)
GRAPH_MODEL_PATH = "/Workspace/Users/pramod.borkar@neo4j.com/supply-chain-optimizer/agents/graph_agent_model.py"
GDS_MODEL_PATH   = "/Workspace/Users/pramod.borkar@neo4j.com/supply-chain-optimizer/agents/gds_agent_model.py"

print("Config ready.")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Graph Agent — MLflow Model (code-based logging)
# MAGIC
# MAGIC Model class is defined in `graph_agent_model.py` (uploaded alongside this notebook).

# COMMAND ----------
# Verify model files are accessible
import os
for path in [GRAPH_MODEL_PATH, GDS_MODEL_PATH]:
    print(f"{'OK' if os.path.exists(path) else 'MISSING'}: {path}")

print("Model files checked.")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Log & Register — Graph Agent

# COMMAND ----------
MODEL_CONFIG = {
    "catalog":        "supplychain_optimizer",
    "schema":         "supply_chain_medallion",
    "model":          "claude-sonnet-4-6",
    "max_rows":       200,
    "neo4j_uri":      "neo4j+s://26bf512b.databases.neo4j.io",
    "neo4j_username": "neo4j",
    "neo4j_database": "neo4j",
}

SAMPLE_INPUT = pd.DataFrame([{
    "messages": [{"role": "user", "content": "What parts are at risk if our highest-risk supplier fails?"}],
    "subgraph_type": "supplier_risk",
}])

SAMPLE_OUTPUT = pd.DataFrame([{
    "predictions": ["Based on the graph analysis..."]
}])

with mlflow.start_run(run_name="graph_agent_registration"):
    signature = infer_signature(SAMPLE_INPUT, SAMPLE_OUTPUT)
    model_info = mlflow.pyfunc.log_model(
        artifact_path="graph_agent",
        python_model=GRAPH_MODEL_PATH,
        model_config=MODEL_CONFIG,
        signature=signature,
        pip_requirements=["anthropic>=0.49.0", "neo4j>=5.18.0", "databricks-sdk"],
        registered_model_name=f"{CATALOG}.{SCHEMA}.supply_chain_graph_agent",
    )
    print(f"Graph agent logged: {model_info.model_uri}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Log & Register — GDS Agent

# COMMAND ----------
SAMPLE_GDS_INPUT = pd.DataFrame([{
    "messages": [{"role": "user", "content": "Which parts are the biggest structural bottlenecks in the BOM?"}],
    "projection": "bom_network",
}])

with mlflow.start_run(run_name="gds_agent_registration"):
    signature = infer_signature(SAMPLE_GDS_INPUT, SAMPLE_OUTPUT)
    model_info = mlflow.pyfunc.log_model(
        artifact_path="gds_agent",
        python_model=GDS_MODEL_PATH,
        model_config=MODEL_CONFIG,
        signature=signature,
        pip_requirements=["anthropic>=0.49.0", "neo4j>=5.18.0", "databricks-sdk"],
        registered_model_name=f"{CATALOG}.{SCHEMA}.supply_chain_gds_agent",
    )
    print(f"GDS agent logged: {model_info.model_uri}")

# COMMAND ----------
# MAGIC %md
# MAGIC ## Deploy as Model Serving Endpoints
# MAGIC
# MAGIC Run this cell after both models are registered.
# MAGIC You can also deploy from the Serving UI: **Serving → Create Endpoint → select registered model**

# COMMAND ----------
from databricks.sdk import WorkspaceClient
from databricks.sdk.service.serving import EndpointCoreConfigInput, ServedEntityInput

w = WorkspaceClient()

def deploy_agent_endpoint(endpoint_name: str, model_name: str, model_version: str = "1"):
    try:
        w.serving_endpoints.create(
            name=endpoint_name,
            config=EndpointCoreConfigInput(
                served_entities=[
                    ServedEntityInput(
                        entity_name=model_name,
                        entity_version=model_version,
                        workload_size="Small",
                        scale_to_zero_enabled=True,
                    )
                ]
            ),
        )
        print(f"Endpoint '{endpoint_name}' deployment started.")
    except Exception as e:
        print(f"Endpoint '{endpoint_name}' error: {e}")

deploy_agent_endpoint(
    "supply-chain-graph-agent",
    f"{CATALOG}.{SCHEMA}.supply_chain_graph_agent",
    "1",
)
deploy_agent_endpoint(
    "supply-chain-gds-agent",
    f"{CATALOG}.{SCHEMA}.supply_chain_gds_agent",
    "1",
)

# COMMAND ----------
# MAGIC %md
# MAGIC ## Add Endpoints to the Supply Chain Supervisor
# MAGIC
# MAGIC Once both endpoints are **Ready**, add them to the existing Supervisor in AgentBricks UI:
# MAGIC - **supply-chain-graph-agent** → handles: supplier failure impact, BOM dependencies, cascading disruptions
# MAGIC - **supply-chain-gds-agent**   → handles: bottleneck analysis, PageRank, community detection, shortest path
# MAGIC
# MAGIC Or update the supervisor programmatically — tile_id: `af2a86be-f0f0-4d1d-9b59-0bc6659c74ed`
