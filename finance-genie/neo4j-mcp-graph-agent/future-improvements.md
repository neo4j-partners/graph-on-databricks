# Future improvements

This file lists improvements that are agreed in principle but not scheduled. Each entry says why it matters and what to check first.

## Connect the Neo4j MCP server with a read-only Aura user

The Neo4j MCP server signs in as the Aura `neo4j` admin user. That instance is the same one the finance-genie pipeline writes to. Two checks stop writes today. The agent guardrail in `agent/guardrails.py` rejects write Cypher, and the server rejects queries that EXPLAIN reports as writes. Both checks parse the query. A database user with the built-in `reader` role would make the database itself refuse writes, whatever the query says.

Steps:

1. Confirm that the Aura tier supports creating database users and assigning the `reader` role.
2. Create the user, for example `mcp_reader`, and grant it `reader`. Store its password where the server's existing Neo4j credentials live.
3. Point the MCP server's `finance` environment at the new user and redeploy it from the aws-starter `neo4j-mcp-server` project.
4. Check whether the redeploy kept the AgentCore gateway id. If the id changed, update the Unity Catalog connection with the steps in the README troubleshooting section.
5. Run the smoke question again. Then confirm that a write such as `CREATE (:Probe)`, sent straight to the server, fails with a permission error.

Keep the agent guardrail after this change. It gives the agent a fast, clear error before any query reaches the server.
