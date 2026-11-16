# Deployment Runbook

This runbook covers the prerequisites, the one-time setup, and the deployment pipeline for the Agentic Commerce agent. It also covers step-by-step deployment, focused testing, individual commands, and local validation.

## Prerequisites

1. Python 3.12 or newer.
2. `uv` installed locally.
3. Databricks CLI configured with a profile that can access the target workspace.
4. A running Databricks cluster for job steps. Jobs can also run on serverless compute with `--compute serverless`. The product loader needs the Neo4j Spark Connector, so run it on the cluster described below.
5. Unity Catalog catalog, schema, and volume:
   - `retail_assistant`
   - `retail`
   - `retail_volume`
6. A Neo4j database reachable from Databricks.
7. Databricks model serving access to:
   - `databricks-claude-sonnet-4-6`
   - `databricks-bge-large-en`

The product loader uses Spark and the Neo4j Spark Connector. Use a dedicated-access cluster and install:

```text
org.neo4j:neo4j-connector-apache-spark_2.12:5.3.1_for_spark_3
```

## Setup

Install local dependencies:

```bash
uv sync
```

Create `.env` from `.env.sample` and fill in the Databricks and Neo4j values:

```bash
cp .env.sample .env
```

Upload Neo4j credentials into the Databricks secret scope used by serving:

```bash
./retail_agent/scripts/setup_databricks_secrets.sh --profile <profile>
```

The script reads `NEO4J_URI` and `NEO4J_PASSWORD` from `.env` and writes them to the `retail-agent-secrets` scope. The runner treats these Neo4j values as local setup inputs and does not forward the password as a job parameter.

Validate the Databricks configuration. The command checks cluster access and lists the available wheel entry points.

```bash
uv run python -m cli validate
```

Run the full pipeline:

```bash
uv run python -m cli pipeline --all
```

[Pipeline](#pipeline) describes the other pipeline modes and each step. The sections after it cover step-by-step deployment, focused testing, and individual commands.

Run the demo client locally after the serving endpoint is deployed:

```bash
cd demo-client
cp .env.sample .env
apx dev start
```

Open `http://localhost:9000`. Use `apx dev status`, `apx dev logs`, and `apx dev stop` to manage the local app. See [demo-client/README.md](../demo-client/README.md) for full local checks, runtime settings, backend smoke tests, and deployment commands.

## Pipeline

`pipeline` is a local orchestrator over the existing Databricks wheel jobs. It builds and uploads the current wheel, submits each Databricks job in order, waits for each job to finish, and stops on the first failure.

Pipeline modes:

Run the full end-to-end path: upload the wheel, load Neo4j data, build GraphRAG, deploy the endpoint, and run all verification jobs.

```bash
uv run python -m cli pipeline --all
```

Run only the data path: upload the wheel, load products/source knowledge into Neo4j, and build the GraphRAG layer.

```bash
uv run python -m cli pipeline --data
```

Run only deployment: upload the wheel and deploy the agent endpoint. Use this after code changes that do not require reloading Neo4j data.

```bash
uv run python -m cli pipeline --deploy
```

Run only verification against an existing deployed endpoint.

```bash
uv run python -m cli pipeline --verify
```

Pipeline steps:

| Step | What it does | Individual command |
|------|--------------|--------------------|
| Upload wheel | Builds `retail_agent` and uploads it to `DATABRICKS_VOLUME_PATH/wheels` | `uv run python -m cli upload --wheel` |
| Load products | Creates the retail product graph, source knowledge nodes, product embeddings, and memory indexes in Neo4j | `uv run python -m cli submit retail-agent-load-products` |
| Build GraphRAG | Reads source knowledge from Neo4j, runs `SimpleKGPipeline`, creates chunks/entities, links them to products, and creates retrieval indexes | `uv run python -m cli submit retail-agent-load-graphrag` |
| Deploy agent | Logs the agent to MLflow, registers `retail_assistant.retail.retail_agent_v3`, deploys with `databricks-agents`, and waits for active traffic | `uv run python -m cli submit retail-agent-deploy` |
| Verify endpoint | Checks endpoint readiness, diagnostics, product search, product lookup, graph traversal, short-term memory, long-term preferences, profile retrieval, and preference-based recommendations | `uv run python -m cli submit retail-agent-demo` |
| Verify retrievers | Demonstrates vector, vector-plus-Cypher, hybrid, and Text2Cypher GraphRAG retrievers | `uv run python -m cli submit retail-agent-demo-retrievers` |
| Verify knowledge | Verifies the GraphRAG path by sending live troubleshooting knowledge search, hybrid search, product issue diagnosis, and cross-product knowledge comparison queries through the endpoint | `uv run python -m cli submit retail-agent-check-knowledge` |

Useful options:

```bash
uv run python -m cli pipeline --all --dry-run
uv run python -m cli pipeline --data --skip-upload
uv run python -m cli pipeline --verify --compute serverless
```

After a submitted step, inspect the Databricks task output with the logs command in [Individual Commands](#individual-commands).

## Step-by-step Runbook

Use this path when validating a deployment, debugging a failure, or keeping a clear record of each Databricks run ID. It is the same sequence as `pipeline --all`, but each step can be checked before continuing.

1. Run the local checks in [Local Validation](#local-validation).
2. Run the individual command for each row of the pipeline steps table in [Pipeline](#pipeline), from top to bottom. The first command builds and uploads the wheel. Each later command submits one Databricks job.
3. After each submitted job, inspect the logs before moving to the next step.

Expected success signals:

| Step | Success signal |
|------|----------------|
| Load products | `Sample data loaded successfully`, 21 products, 84 knowledge articles, 84 support tickets, 84 reviews, and 21 product embeddings |
| Build GraphRAG | `Pipeline complete. 252 processed, 0 failed` |
| Deploy agent | A new Unity Catalog model version is created and the endpoint reports target version traffic |
| Verify endpoint | `Overall: 9 passed, 0 failed` |
| Verify retrievers | `Demo complete` with vector, vector-plus-Cypher, hybrid, and Text2Cypher sections |
| Verify knowledge | `Knowledge exercise: 4 passed, 0 failed` |

The latest verified Databricks pipeline completed product loading, GraphRAG loading, endpoint deployment, endpoint and memory checks, retriever demos, and knowledge checks successfully. The verified endpoint was `agents_retail_assistant-retail-retail_agent_v3`.

## Long-running Jobs

Databricks jobs can outlive the local SDK waiter. A local `TimeoutError` means the CLI stopped waiting; it does not prove that the Databricks run failed. Check the run state with the command below, then read the run logs with the logs command in [Individual Commands](#individual-commands).

```bash
databricks jobs get-run <run-id> --profile <profile>
```

For this project, `retail-agent-load-graphrag` can run long enough to hit the local waiter timeout while still finishing successfully in Databricks. Treat the Databricks run state and final log counts as the source of truth.

Some GraphRAG logs can include nonfatal warnings from Neo4j APOC relationship merges or from a malformed LLM extraction response. Inspect the final result state and summary counts before treating these warnings as failures.

## Focused Testing

To test only the deployed agent endpoint on Databricks, run the Verify endpoint and Verify knowledge commands from the pipeline steps table in [Pipeline](#pipeline). Inspect the logs of each run afterward.

To test only the local `retail_agent` package before submitting Databricks jobs, run the checks in [Local Validation](#local-validation).

## Individual Commands

Use these commands for debugging, rerunning one step, or checking a submitted run. The pipeline steps table in [Pipeline](#pipeline) lists the upload command and the submit command for each step. [Local Validation](#local-validation) lists the validation commands.

```bash
# Show project CLI help
uv run python -m cli --help

# Run one wheel entry point
uv run python -m cli submit <entry-point>

# View Databricks job logs
uv run python -m cli logs <run-id>
```

Available wheel entry points:

| Entry point | Pipeline step |
|-------------|---------------|
| `retail-agent-load-products` | Load products |
| `retail-agent-load-graphrag` | Build GraphRAG |
| `retail-agent-deploy` | Deploy agent |
| `retail-agent-demo` | Verify endpoint |
| `retail-agent-demo-retrievers` | Verify retrievers |
| `retail-agent-check-knowledge` | Verify knowledge |
| `retail-agent-deploy-supervisor` | None. This entry point is the stub supervisor deployment, and the pipeline does not run it. |

## Local Validation

Run local checks before submitting Databricks jobs:

```bash
uv run python -m pytest
uv run python -m compileall -q retail_agent demo-client/src
uv run python -m cli validate
```

Pass an entry point name to `validate` to also confirm that the name is a known wheel entry point:

```bash
uv run python -m cli validate retail-agent-demo
```
