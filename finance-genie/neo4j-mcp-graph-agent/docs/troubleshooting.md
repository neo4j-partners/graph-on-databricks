# Troubleshooting

## Update the MCP connection

**Symptom:** `agentbricks endpoint invoke` returns `HTTP 500` with `{"detail": "agent invocation failed"}`. The app logs (`agentbricks deployments logs agent-bricks-neo4j-graph-agent`) show `No MCP server connected` and `Resource not found - Requested gateway does not exist`.

**Cause:** The Neo4j MCP server stack was torn down and deployed again. A fresh stack creates a new AgentCore gateway ID and a new Cognito OAuth client. A redeploy onto the existing stack keeps both, so it does not cause this error. The Unity Catalog connection behind `finance_genie_mcp` still holds the old host and client, so the gateway returns 404. Your direct gateway test can pass while the service fails, because the test uses the new URL from `.mcp-credentials.finance.json` and the service does not.

**Where the URL lives:** The service holds no URL or credentials. It points at the connection `graph-on-databricks.finance_genie.finance_genie_mcp_connection`. `databricks ai-gateway update-mcp-service` only changes the comment and owner, so it cannot fix this. Update the connection instead.

1. **Confirm the mismatch:** Compare the connection host with the `gateway_url` in `.mcp-credentials.finance.json`. The hosts differ after a fresh stack.

   ```bash
   databricks connections get graph-on-databricks.finance_genie.finance_genie_mcp_connection -o json | jq '.options | {host, client_id}'
   jq '{gateway_url, client_id}' .mcp-credentials.finance.json
   ```

2. **Update the connection:** Build the request body with `jq` and pipe it to the CLI. This keeps the client secret out of your shell history and out of any file.

   ```bash
   jq -c '{options: {
       host: (.gateway_url | sub("/mcp$"; "")),
       base_path: "/mcp",
       client_id: .client_id,
       client_secret: .client_secret,
       token_endpoint: .token_url,
       oauth_scope: .scope,
       oauth_credential_exchange_method: "header_and_body"
     }}' .mcp-credentials.finance.json \
     | databricks connections update \
         graph-on-databricks.finance_genie.finance_genie_mcp_connection \
         --json @/dev/stdin
   ```

   The response shows the new `host` and a fresh `access_token_expiration`, which means Databricks fetched a token with the new client.

3. **Test the service:** Call the service as yourself. A healthy service returns HTTP 200 with a `serverInfo` result.

   ```bash
   HOST=$(databricks auth describe -o json | jq -r '.details.host // .details.configuration.host.value')
   TOKEN=$(databricks auth token -o json | jq -r .access_token)
   curl -s -X POST "$HOST/ai-gateway/mcp-services/graph-on-databricks.finance_genie.finance_genie_mcp" \
     -H "Authorization: Bearer $TOKEN" \
     -H 'Content-Type: application/json' \
     -H 'Accept: application/json, text/event-stream' \
     -d '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}'
   ```

4. **Invoke the agent:** Run `make smoke` from step 7 of [Quick start with make](../README.md#quick-start-with-make) again. The app reads the service on every request, so it needs no redeploy.

**Notes:**
- **Repeat after each fresh stack:** Every fresh MCP server stack has a new gateway ID and OAuth client, so repeat these steps each time. A redeploy onto the existing stack needs none of them.
- **Profile:** Pass `--profile` or set `DATABRICKS_CONFIG_PROFILE` for every command.
- **Permissions:** You must own the connection or have `MANAGE` on it.

## Check which MCP server image is deployed

The finance MCP server runs the image `neo4j-mcp-server:f1b33d3`.

- **Tag:** The tag is the short commit SHA of the mcp-neo4j fork that the image was built from. That commit fixes read routing and rejects schema writes.
- **Check the live image:** Run the command below. The runtime id is in the CDK stack outputs.

  ```bash
  aws bedrock-agentcore-control get-agent-runtime --agent-runtime-id <runtime-id> \
    --query 'agentRuntimeArtifact.containerConfiguration.containerUri' --output text
  ```

- **Tag `latest`:** If the tag is `latest`, the image predates the `deploy.py` fix, and its source commit is unknown. Redeploy to get a SHA tag.
