# Deployment Runbook

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
| Verify endpoint | Checks endpoint readiness, diagnostics, product tools, short-term memory, and long-term preferences | `uv run python -m cli submit retail-agent-demo` |
| Verify retrievers | Demonstrates vector, vector-plus-Cypher, hybrid, and Text2Cypher GraphRAG retrievers | `uv run python -m cli submit retail-agent-demo-retrievers` |
| Verify knowledge | Sends live troubleshooting, hybrid search, issue diagnosis, and comparison queries through the endpoint | `uv run python -m cli submit retail-agent-check-knowledge` |

Useful options:

```bash
uv run python -m cli pipeline --all --dry-run
uv run python -m cli pipeline --data --skip-upload
uv run python -m cli pipeline --verify --compute serverless
```

Use `uv run python -m cli logs <run-id>` after a submitted step to inspect Databricks task output.

## Step-by-step Runbook

Use this path when validating a deployment, debugging a failure, or keeping a clear record of each Databricks run ID. It is the same sequence as `pipeline --all`, but each step can be checked before continuing.

Run local checks first:

```bash
uv run python -m pytest tests
uv run python -m compileall -q retail_agent demo-client/src
uv run python -m cli validate
```

Build and upload the wheel:

```bash
uv run python -m cli upload --wheel
```

Submit each Databricks job in order:

```bash
uv run python -m cli submit retail-agent-load-products
uv run python -m cli submit retail-agent-load-graphrag
uv run python -m cli submit retail-agent-deploy
uv run python -m cli submit retail-agent-demo
uv run python -m cli submit retail-agent-demo-retrievers
uv run python -m cli submit retail-agent-check-knowledge
```

After each submitted job, inspect the logs before moving to the next step:

```bash
uv run python -m cli logs <run-id>
```

Expected success signals:

| Step | Success signal |
|------|----------------|
| Load products | `Sample data loaded successfully`, 21 products, 84 knowledge articles, 84 support tickets, 84 reviews, and 21 product embeddings |
| Build GraphRAG | `Pipeline complete. 252 processed, 0 failed` |
| Deploy agent | A new Unity Catalog model version is created and the endpoint reports target version traffic |
| Verify endpoint | `Overall: 9 passed, 0 failed` |
| Verify retrievers | `Demo complete` with vector, vector-plus-Cypher, hybrid, and Text2Cypher sections |
| Verify knowledge | `Knowledge exercise: 4 passed, 0 failed` |

## Long-running Jobs

Databricks jobs can outlive the local SDK waiter. A local `TimeoutError` means the CLI stopped waiting; it does not prove that the Databricks run failed. Check the run state and logs with:

```bash
databricks jobs get-run <run-id> --profile <profile>
uv run python -m cli logs <run-id>
```

For this project, `retail-agent-load-graphrag` can run long enough to hit the local waiter timeout while still finishing successfully in Databricks. Treat the Databricks run state and final log counts as the source of truth.

Some GraphRAG logs can include nonfatal warnings from Neo4j APOC relationship merges or from a malformed LLM extraction response. Inspect the final result state and summary counts before treating these warnings as failures.

## Focused Testing

Test only the deployed agent endpoint on Databricks:

```bash
uv run python -m cli submit retail-agent-demo
uv run python -m cli submit retail-agent-check-knowledge
uv run python -m cli logs <run-id>
```

`retail-agent-demo` verifies endpoint readiness, diagnostics, product search, product lookup, graph traversal, short-term memory, long-term preferences, profile retrieval, and preference-based recommendations.

`retail-agent-check-knowledge` verifies the GraphRAG path with knowledge search, hybrid search, product diagnosis, and cross-product knowledge comparison.

Test only the local `retail_agent` package before submitting Databricks jobs:

```bash
uv run python -m pytest tests
uv run python -m compileall retail_agent
uv run python -m cli validate retail-agent-demo
```

## Individual Commands

Use these commands for debugging, rerunning one step, or checking a submitted run.

```bash
# Show project CLI help
uv run python -m cli --help

# Validate cluster access and available wheel entry points
uv run python -m cli validate

# Build and upload the package wheel
uv run python -m cli upload --wheel

# Run one wheel entry point
uv run python -m cli submit retail-agent-demo

# View Databricks job logs
uv run python -m cli logs <run-id>
```

Available wheel entry points:

| Entry point | Purpose |
|-------------|---------|
| `retail-agent-load-products` | Load product catalog, source knowledge, relationships, product embeddings, and memory indexes |
| `retail-agent-load-graphrag` | Build the GraphRAG chunk/entity layer and retrieval indexes |
| `retail-agent-deploy` | Log, register, deploy, and wait for the serving endpoint |
| `retail-agent-demo` | Verify endpoint, product tools, and memory |
| `retail-agent-demo-retrievers` | Demonstrate GraphRAG retriever patterns |
| `retail-agent-check-knowledge` | Verify knowledge tools through the live endpoint |
| `retail-agent-deploy-supervisor` | Stub supervisor deployment entry point |

## Local Validation

Run local checks before submitting Databricks jobs:

```bash
uv run python -m pytest
uv run python -m compileall -q retail_agent demo-client/src
uv run python -m cli validate
```

The latest verified Databricks pipeline completed product loading, GraphRAG loading, endpoint deployment, endpoint and memory checks, retriever demos, and knowledge checks successfully. The verified endpoint was `agents_retail_assistant-retail-retail_agent_v3`.
