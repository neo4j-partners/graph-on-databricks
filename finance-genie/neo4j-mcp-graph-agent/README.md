# Neo4j MCP Graph Agent

An end-to-end Databricks integration that provisions access to an externally hosted
Neo4j MCP server and deploys a graph-only Model Serving agent that uses it.

This directory is the single owner of both responsibilities. Connection
provisioning and agent deployment live together so their credentials, resource
names, validation, and smoke tests cannot drift across separate projects.

## What this builds

- A Databricks secret scope containing AgentCore OAuth machine-to-machine credentials.
- A Unity Catalog HTTP connection with MCP enabled.
- A Unity Catalog catalog and schema for the registered agent model.
- A LangGraph `ResponsesAgent` that discovers Neo4j MCP tools through the Databricks MCP proxy.
- A Model Serving endpoint deployed with `databricks.agents.deploy`.

The endpoint is intentionally graph-only: it uses the MCP tools for read-only
Neo4j Cypher and has no Genie, Delta, or web-UI responsibilities. Add it to a
Databricks Supervisor Agent when graph evidence should be combined with a
separately configured Genie Space.

## Prerequisites

- `uv` installed locally.
- Databricks CLI or SDK authentication configured through a profile, `DATABRICKS_HOST` plus `DATABRICKS_TOKEN`, or standard Databricks SDK auth.
- Unity Catalog enabled in the target workspace.
- External MCP server support enabled in the target workspace.
- `CREATE CONNECTION` privilege on the Unity Catalog metastore.
- Permission to create or use the configured secret scope, catalog, schema, model, and serving endpoint.
- A Pro or Serverless SQL warehouse, or a DBR 15.4 LTS or later cluster using Standard or Dedicated access mode.
- A Neo4j MCP server that supports Streamable HTTP transport.
- `.mcp-credentials.json` copied into this directory by the operator.

## Quick start

This is an optional product. Run the Finance Genie root `make demo` first when
you want it to use the canonical graph-enrichment environment. That command
does not create the MCP connection or deploy this endpoint.

From the `finance-genie` repository root:

```bash
cp .env.sample .env
# Fill in the shared Databricks, Neo4j, and MCP values.
cd neo4j-mcp-graph-agent
```

Copy the AgentCore-generated credentials file into this directory:

```bash
cp /path/to/.mcp-credentials.json .mcp-credentials.json
```

Edit `.env` and set at least:

- `DATABRICKS_PROFILE` or standard Databricks SDK auth environment variables
- `DATABRICKS_WAREHOUSE_ID` or `DATABRICKS_CLUSTER_ID`
- `NEO4J_MCP_AGENT_DATABRICKS_WORKSPACE_DIR`, or the shared
  `DATABRICKS_WORKSPACE_DIR` fallback
- `MCP_SECRET_SCOPE`
- `UC_CONNECTION_NAME`
- `CATALOG`
- `SCHEMA`
- `LLM_ENDPOINT_NAME`, for example `databricks-claude-sonnet-4-6` if available in your region
- `MODEL_SERVING_ENDPOINT_NAME`

Validate the local credential file:

```bash
uv run validation/validate_credentials.py
```

Deploy everything and run the endpoint smoke test:

```bash
./deploy.sh
```

The deploy script runs the setup, Databricks-side validation jobs, agent
deployment, endpoint readiness polling, and smoke test in order. It stops at
the first failed step.

If an existing connection has different settings, recreate it explicitly:

```bash
./deploy.sh --replace-connection
```

To choose Databricks job compute for the submitted validation and deploy jobs:

```bash
./deploy.sh --compute serverless
```

The equivalent step-by-step sequence is:

```bash
./setup_secrets.sh
uv run setup/provision_connection.py
uv run validation/validate_connection.py
uv run setup/provision_uc_resources.py
```

If an existing connection has different settings during the manual flow,
recreate it explicitly:

```bash
uv run setup/provision_connection.py --replace
```

Upload job code and run the Databricks-side sequence:

```bash
uv run python -m cli upload --all
uv run python -m cli submit 00_validate_mcp_gateway.py
uv run python -m cli submit 01_deploy_agent.py
uv run validation/validate_endpoint.py
uv run python -m cli submit 02_validate_endpoint.py
```

## Connect it to a Supervisor Agent

The deployed endpoint is one specialist, not a complete multi-agent system.
Configure the Supervisor Agent in Databricks:

1. Add this Model Serving endpoint as the graph-evidence specialist.
2. Add the canonical BEFORE Genie Space as the structured-data specialist.
3. Route graph schema, relationship, neighborhood, community, and read-only
   Cypher questions to this endpoint.
4. Route account, merchant, transaction, balance, and other Silver-table
   business questions to Genie.
5. Instruct the Supervisor to combine graph rationale with the business context
   returned by Genie.

Supervisor and Genie configuration remain outside this project so the endpoint
can also be used independently.

## Stop the serving endpoint

Delete the Model Serving endpoint when it is no longer needed to stop its remote
serving cost. With the default endpoint name:

```bash
databricks serving-endpoints delete neo4j-mcp-agent \
  --profile <your-databricks-profile>
```

This removes only the serving endpoint. It does not delete the registered Unity
Catalog model, MCP connection, secret scope, or external AgentCore gateway.

## Validation and troubleshooting

Use these checks when you want to isolate where MCP connectivity is failing.
Run commands from `finance-genie/neo4j-mcp-graph-agent`. The validation clients load
Databricks auth and object names from `.env`, including `DATABRICKS_PROFILE`
when you use profile-based auth.

Validate the local AgentCore credential file without calling Databricks or the
MCP gateway:

```bash
uv run validation/validate_credentials.py
```

Test the AgentCore MCP gateway directly from your laptop. This performs the
OAuth client credentials flow, sends a JSON-RPC `tools/list` request to the
gateway, and prints the discovered tool names without printing secret values:

```bash
uv run validation/validate_mcp_gateway_local.py
```

Expected direct gateway tools include:

- `neo4j-mcp-server-target___get-schema`
- `neo4j-mcp-server-target___read-cypher`
- `neo4j-mcp-server-target___list-gds-procedures`

Validate the Databricks Unity Catalog HTTP connection and MCP flag from your
local machine:

```bash
uv run validation/validate_connection.py
```

Run the Databricks-side MCP validation job. This verifies that Databricks can
read the stored OAuth secrets, reach the AgentCore gateway, list direct gateway
tools, and list tools through the UC MCP proxy:

```bash
uv run python -m cli submit --compute serverless 00_validate_mcp_gateway.py
```

After the agent is deployed, validate serving endpoint readiness and then run a
tool-backed smoke test:

```bash
uv run validation/validate_endpoint.py
uv run python -m cli submit --compute serverless 02_validate_endpoint.py
```

### Operational notes

- `.mcp-credentials.json` and `.env` are local operator inputs and must not be committed.
- The MCP flag is set with the preview HTTP connection option `is_mcp_connection 'true'`. The setup validates the resulting metadata and the Databricks MCP proxy instead of relying only on SQL success.
- Re-test connection provisioning when upgrading Databricks SDK packages or moving to a new workspace because external MCP availability can vary by workspace and region.
- The deploy job logs MCP resource dependencies with `DatabricksMCPClient.get_databricks_resources()` so Model Serving can authenticate to the Unity Catalog connection.
- Confirm the configured `LLM_ENDPOINT_NAME` is available in the target region before deployment.
- This project uses Model Serving because its deployable artifact is a reusable agent endpoint rather than an interactive web application.

### Failure guide

- `validate_credentials.py` fails: confirm the local `.mcp-credentials.json` contains `gateway_url`, `client_id`, `client_secret`, `token_url`, and `scope`.
- `provision_connection.py` fails with drift: rerun with `--replace` after confirming the existing connection can be recreated.
- `00_validate_mcp_gateway.py` fails: check AgentCore gateway reachability, OAuth credentials, and whether the Databricks workspace can reach the gateway host.
- `validate_endpoint.py` fails: wait for the serving endpoint deployment to finish, then rerun validation.

## Databricks references

- [External MCP servers](https://docs.databricks.com/aws/en/generative-ai/mcp/external-mcp)
- [HTTP connections](https://docs.databricks.com/aws/en/query-federation/http)
- [Connect agents to external services](https://docs.databricks.com/aws/en/generative-ai/agent-framework/external-connection-tools)
- [Deploy agents on Model Serving](https://docs.databricks.com/gcp/en/generative-ai/agent-framework/deploy-agent)
- [Model Context Protocol overview](https://docs.databricks.com/aws/en/generative-ai/mcp)
- [Databricks-hosted foundation models](https://docs.databricks.com/aws/en/machine-learning/foundation-model-apis/supported-models)
