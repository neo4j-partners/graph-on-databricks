# Add NAMS as a Databricks MCP service

This step is optional. The app in this repo calls NAMS directly through `agent/nams.py`. An MCP service exposes the same NAMS memory tools to other Databricks agents, such as the Playground, as a Unity Catalog object.

You need a NAMS key from https://memory.neo4jlabs.com/ and permission to create services in the target schema.

1. **Open the schema:** In Catalog Explorer, open the catalog and schema that will own the service. This sample uses `graph-on-databricks` and `finance_genie`.
2. **Create a service:** Click **Create**, then **Service**. Choose the MCP option to open the Create MCP Service dialog.
3. **Name it:** Enter a name such as `finance_agent_memory`. The name cannot change after creation.
4. **Create the connection:** Keep **Create new connection** selected and fill in these fields.
   - **Server URL:** Enter `https://memory.neo4jlabs.com/mcp`. NAMS uses Streamable HTTP.
   - **Authentication:** Choose **Bearer token**.
   - **Bearer token:** Paste the NAMS key. Paste the key only, without a `Bearer ` prefix.
5. **Load the tools:** Click **Create & load tools**. Databricks lists the 40 NAMS tools. A 401 error means the NAMS key is wrong.
6. **Trim the tools:** Click **Edit tools** on the service page and choose **Select manually**. Deselect every `memory_ontology_*` tool and `memory_create_relation`, which leaves 32 of 40 selected. The tool filter matches the exact start of a name, so type `memory_ontology` and then `memory_create_relation`.
7. **Grant access:** Give each user or service principal that will call the service `USE CONNECTION` on the connection.
8. **Try it:** Click **Try in Playground**, then ask the model to remember a fact and recall it in a new chat.

**Why trim the tools:** The Playground parses every tool schema and fails the whole listing when one schema is a bare `true`. Some NAMS ontology tools and `memory_create_relation` publish such schemas. The error reads `Failed to list tools from UC MCP service` and mentions `InputSchema from Boolean value (true)`. The sample does not use the ontology tools or `memory_create_relation`, so removing them loses nothing.

## Sample questions

Use these in the Playground to check that the NAMS tools work. Run the recall questions in a new chat, because remembering across chats is the point of memory.

**Save a fact**

- "Remember that I'm investigating Community 19766 as a fraud ring candidate and that the hub account is Account 15940."
- "I prefer results as a table, top 10 only, with risk_score included. Remember that."

**Recall in a new chat**

- "What was I investigating last time?" The answer should name Community 19766 and Account 15940 without being told again.
- "What account did I say was the hub?" The answer should be the specific account, not a summary.
- "Show me the top ring candidate communities." The answer should follow the saved table preference.

**Entities**

- "List the accounts and communities I've mentioned so far." NAMS extracts entities from messages on its own servers, so these should come back as entities.

**Corrections**

- "Actually, I'm investigating Community 22341 now, and its hub account is Account 7321." Then ask "What's the hub account?" The answer should be the new value, or the agent should point out the conflict.

**Cases that should fail safely**

- "What did I tell you about merchant Contoso?" when you never did. The agent should say it has no memory of that and should not invent one.
- "What did another analyst ask you yesterday?" The agent should refuse or return nothing, because memory belongs to one user.

The Playground has no graph tools, so it cannot answer questions about the fraud graph itself. Ask those of the deployed app.
