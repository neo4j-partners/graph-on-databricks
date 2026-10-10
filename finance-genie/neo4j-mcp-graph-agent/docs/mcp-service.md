# Create the finance-genie MCP service

The agent reads the fraud graph through the Unity Catalog MCP service `graph-on-databricks.finance_genie.finance_genie_mcp`. This guide creates that service. It assumes the finance-genie fraud graph is already loaded in Neo4j Aura.

The setup has three parts:

1. Deploy the Neo4j MCP server on AWS.
2. Create a Unity Catalog connection to the server.
3. Register the MCP service on that connection.

## What you build

- **MCP server:** The [Neo4j Cypher MCP server](https://github.com/neo4j-partners/mcp-neo4j/tree/main/servers/mcp-neo4j-cypher), `mcp-neo4j-cypher`, runs on Amazon Bedrock AgentCore Runtime.
- **Gateway:** An AgentCore Gateway is the only way in. It accepts a request only with a valid token from a Cognito machine client.
- **Connection:** The Unity Catalog HTTP connection `finance_genie_mcp_connection` holds the Gateway URL and the Cognito client. It uses OAuth machine-to-machine, so Databricks fetches and refreshes the tokens itself.
- **Service:** The MCP service `finance_genie_mcp` points at the connection. It exposes the tools `get_neo4j_schema` and `read_neo4j_cypher`.

## Before you begin

- **AWS:** You need an AWS account with working CLI credentials, Docker with buildx support, the AWS CDK CLI, Python 3.10 or newer, and [uv](https://docs.astral.sh/uv/).
- **Neo4j:** The Aura instance that holds the graph must be running. The MCP server checks the database at startup and exits if it cannot connect, so resume a paused instance first.
- **Databricks:** You need the Databricks CLI and [jq](https://jqlang.org/). Export `DATABRICKS_CONFIG_PROFILE`, because the commands below read the profile from it.
- **Unity Catalog rights:** You need `USE CATALOG` on `graph-on-databricks`, plus `USE SCHEMA`, `CREATE CONNECTION`, and `CREATE SERVICE` on `graph-on-databricks.finance_genie`.

## Step 1: Deploy the Neo4j MCP server

The `neo4j-mcp-server` project in [aws-starter](https://github.com/neo4j-partners/aws-starter/tree/main/neo4j-mcp-server) deploys the server. Its README is the full guide. This step covers the finance deployment. Run the commands from the project's `neo4j-mcp-server/` folder.

1. **Clone the sources:** Clone `aws-starter` and [mcp-neo4j](https://github.com/neo4j-partners/mcp-neo4j). The deploy builds the server image from the `servers/mcp-neo4j-cypher` folder of `mcp-neo4j`.
2. **Configure the finance deployment:** Copy `.env.sample` to `.env.finance` and fill in these keys.

   ```bash
   NEO4J_URI=neo4j+s://<instance-id>.databases.neo4j.io
   NEO4J_DATABASE=neo4j
   NEO4J_USERNAME=<read-only-user>
   NEO4J_PASSWORD=<password>
   NEO4J_MCP_REPO=/path/to/mcp-neo4j/servers/mcp-neo4j-cypher
   AWS_REGION=us-east-1
   ```

   The `--env finance` flag selects this file. It also names the stack `neo4j-mcp-server-finance`.
3. **Deploy:** The deploy builds the ARM64 image, pushes it to ECR, and deploys the CDK stack. It takes 5 to 10 minutes.

   ```bash
   export AWS_PROFILE=<your-aws-profile>   # only for a non-default profile
   ./deploy.py --env finance
   ```

4. **Write the credentials file:** This command writes `.mcp-credentials.finance.json`. The file holds the Gateway URL, the Cognito token URL and scope, and the client ID and secret. It also holds a test token that lasts about an hour. The connection in step 2 needs only the client fields, so the token expiry does not matter there. The repo's `.gitignore` already excludes the file. Keep it out of any other repo too.

   ```bash
   ./deploy.py --env finance credentials
   ```

5. **Test through the Gateway:** This script opens an MCP session, lists the tools, and runs a test query.

   ```bash
   ./cloud.sh --env finance
   ```

### Use a read-only database user

The server runs every query as `NEO4J_USERNAME`. The deploy turns off the server's write tool, and the server refuses queries that Neo4j reports as writes. The database user is still the only hard limit, so do not use the admin `neo4j` user. Use a user that can only read.

On Aura Professional, the built-in `reader` role can read data but cannot call procedures. The schema tool calls `apoc.meta.schema`, so `reader` alone breaks `get_neo4j_schema`. Aura also creates a managed role named `graphql_app_read_only_<instance-id>` on each instance. It allows those procedures and denies writes. The name pattern is what this repo found on its instances, not a documented rule, so check it on yours.

1. **Find the role:** Sign in as the admin user and run this on the `system` database.

   ```cypher
   SHOW ROLES YIELD role WHERE role STARTS WITH 'graphql_app_read_only_' RETURN role;
   ```

2. **Create the user and grant both roles:** Replace `<instance-id>` with the suffix from step 1. Use a password of letters and digits that starts with a letter. The deploy passes the password to `cypher-shell -p`, and a leading `-` is read as a flag.

   ```cypher
   CREATE USER mcp_reader SET PASSWORD '<password>' CHANGE NOT REQUIRED;
   GRANT ROLE reader TO mcp_reader;
   GRANT ROLE graphql_app_read_only_<instance-id> TO mcp_reader;
   ```

3. **Point the deploy at it:** Set `NEO4J_USERNAME=mcp_reader` and its password in `.env.finance`, then run the deploy command from step 3 above.
4. **Probe the user:** Sign in as `mcp_reader`. `CALL apoc.meta.schema()` should succeed. `CREATE (:Probe)` should fail with `Neo.ClientError.Security.Forbidden`. Run the probe again after any change to the Aura instance, because Aura manages the second role and may change it.

To undo it, run `REVOKE ROLE graphql_app_read_only_<instance-id> FROM mcp_reader;`, which breaks `get_neo4j_schema`, or `DROP USER mcp_reader;`. If you drop the user, point `NEO4J_USERNAME` at another user and deploy again.

## Step 2: Create the Unity Catalog connection

The connection stores the Gateway URL and the Cognito client. The `parent` field makes it a schema-level connection, so its full name is `graph-on-databricks.finance_genie.finance_genie_mcp_connection`.

`jq` builds the request body from the credentials file and pipes it to the CLI. This keeps the client secret out of your shell history and out of any new file. Set `CREDS` to the file from step 1.

```bash
CREDS=/path/to/aws-starter/neo4j-mcp-server/.mcp-credentials.finance.json
jq -c '{
    name: "finance_genie_mcp_connection",
    parent: "schemas/graph-on-databricks.finance_genie",
    connection_type: "HTTP",
    options: {
      host: (.gateway_url | sub("/mcp$"; "")),
      base_path: "/mcp",
      client_id: .client_id,
      client_secret: .client_secret,
      token_endpoint: .token_url,
      oauth_scope: .scope,
      oauth_credential_exchange_method: "header_and_body"
    }
  }' "$CREDS" \
  | databricks connections create --json @/dev/stdin
```

- **Host and base path:** The Gateway URL ends in `/mcp`. The host is the URL without that suffix, and `base_path` adds it back.
- **OAuth fields:** The client ID, client secret, token endpoint, and scope make this an OAuth machine-to-machine connection. Databricks trades the client for a token at the Cognito token endpoint.

Check the connection. The `credential_type` should be `OAUTH_M2M`, and `host` should match the Gateway URL.

```bash
databricks connections get graph-on-databricks.finance_genie.finance_genie_mcp_connection -o json \
  | jq '{full_name, connection_type, credential_type, host: .options.host}'
```

## Step 3: Register the MCP service

The service holds no URL or credentials. It points at the connection from step 2. Register it in the UI or with the CLI.

### In the UI

1. **Open the MCPs page:** In your workspace, open **Unity Gateway**, select **MCPs**, and click **+ MCP**.
2. **Choose the server type:** Choose **Connect an existing MCP server**.
3. **Name it:** Choose the catalog `graph-on-databricks` and the schema `finance_genie`. Enter the name `finance_genie_mcp`. The name cannot change after creation.
4. **Pick the connection:** Select the existing connection `finance_genie_mcp_connection`. Click **Create & load tools**.
5. **Keep both tools:** The tool list shows the schema tool and the Cypher tool. Keep both.
6. **Create it:** Click **Create MCP Service**.

### With the CLI

```bash
databricks ai-gateway create-mcp-service schemas/graph-on-databricks.finance_genie finance_genie_mcp --json '{
  "config": {
    "source_connection": {
      "name": "connections/graph-on-databricks.finance_genie.finance_genie_mcp_connection"
    }
  }
}'
```

The body sets no `include_tool_selectors`, so the service exposes every tool the server lists. The server lists only the two read tools, because the deploy turns off its write tool.

Check that the service points at the connection:

```bash
databricks ai-gateway get-mcp-service mcp-services/graph-on-databricks.finance_genie.finance_genie_mcp -o json \
  | jq '.config.source_connection.name'
```

## Step 4: Test the service

Call the service as yourself. The first request is an MCP `initialize`. A healthy service returns HTTP 200 with a `serverInfo` result.

```bash
HOST=$(databricks auth describe -o json | jq -r '.details.host // .details.configuration.host.value')
TOKEN=$(databricks auth token -o json | jq -r .access_token)
MCP_URL="$HOST/ai-gateway/mcp-services/graph-on-databricks.finance_genie.finance_genie_mcp"
curl -s -X POST "$MCP_URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}'
```

The second request lists the tools.

```bash
curl -s -X POST "$MCP_URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | jq -r '.result.tools[].name'
```

The output should be these two names:

```
neo4j-mcp-server-target___get_neo4j_schema
neo4j-mcp-server-target___read_neo4j_cypher
```

The Gateway adds its target name, `neo4j-mcp-server-target`, to each tool name. The agent's tool allowlist matches the name after the prefix, so the prefix needs no change in this repo.

## Step 5: Use the service from the agent

The agent already names this service in `agent.toml`. When you run `agentbricks deploy`, it grants the app's service principal `EXECUTE` on the service. To do that, you must own the service or have `MANAGE` on it. The [README](../README.md#prerequisites) lists the rest of the prerequisites.

## After a redeploy

Running `./deploy.py --env finance` again on the existing stack updates the server in place. The Gateway and the Cognito client stay the same, so the connection needs no change.

A teardown followed by a fresh deploy is different. It creates a new Gateway ID and a new Cognito client, and the connection keeps the old values until you update it. After a fresh stack, follow [Troubleshooting: Update the MCP connection](../README.md#troubleshooting-update-the-mcp-connection).
