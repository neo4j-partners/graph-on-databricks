# neo4j-mcp-graph-agent

This is a fraud analyst agent built on Agent Bricks. It reads the finance-genie fraud graph in Neo4j through a Unity Catalog MCP service. It asks a Genie space for values over the gold Delta tables. The agent sends structure questions to the graph and value questions to Genie, and that routing is what makes the two better together. It remembers each analyst's earlier questions in NAMS, the hosted [Neo4j Agent Memory Service](https://memory.neo4jlabs.com/). MLflow tracing records every model call and tool call, so you can see how each answer was found.

What you'll see:

- **Graph and Genie answers:** The agent answers structure questions with read-only Cypher and value questions with Genie. Each MLflow trace shows which source it called and what it asked.
- **Memory across sessions:** A new session picks up what the same analyst asked before.
- **Memory you can inspect:** NAMS shows each analyst's conversations, reasoning traces, and the entities it found.

## Table of contents

- [Prerequisites](#prerequisites)
- [Quick start with make](#quick-start-with-make)
  - [Quick start local with make](#quick-start-local-with-make)
  - [Quick start cloud with make](#quick-start-cloud-with-make)
- [Architecture](#architecture)
- [Demo: short-term memory](#demo-short-term-memory)
- [Long-term memory and the ontology](#long-term-memory-and-the-ontology)
- [Clean up](#clean-up)
- [Documentation](#documentation)

## Prerequisites

- **Tools:** You need Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), [jq](https://jqlang.org/), and the [Databricks CLI](https://docs.databricks.com/aws/en/dev-tools/cli/install).
- **Agent Bricks CLI:** The CLI is in Beta. Install it with `uv tool install databricks-agentbricks`, or run it with `uvx --from databricks-agentbricks agentbricks ...`.
- **Workspace:** The workspace needs Databricks Apps and Unity Catalog AI Gateway.
- **MCP service:** The service `graph-on-databricks.finance_genie.finance_genie_mcp` must exist. It must expose the tools `get_neo4j_schema` and `read_neo4j_cypher`. [Create the finance-genie MCP service](docs/mcp-service.md) covers the setup.
- **Grant right:** You must own the MCP service or have `MANAGE` on it. Deploy grants `EXECUTE` on it for the app.
- **Genie space:** The agent asks the AFTER Genie space from finance-genie, which covers the gold tables. Set your own space id in the `genie` tool block of `agent.toml`. Deploy grants the app `CAN_RUN` on the space. Then `make grant-genie` grants the warehouse and table access that Genie needs.
- **NAMS key:** You need a NAMS key from https://memory.neo4jlabs.com/. [Quick start with make](#quick-start-with-make) step 1 covers it.

## Quick start with make

Run these steps from `neo4j-mcp-graph-agent/`. Install the tools in [Prerequisites](#prerequisites) first. [What the make targets run](docs/reference.md#what-the-make-targets-run) shows the raw commands behind each target. Steps 1 and 2 are shared. Then pick a path: [Quick start local with make](#quick-start-local-with-make) runs the agent on your laptop, and [Quick start cloud with make](#quick-start-cloud-with-make) deploys it as a Databricks app. Steps marked optional can be skipped.

1. **Set your variables and the NAMS key:** Two variables drive everything below. `DATABRICKS_CONFIG_PROFILE` is your Databricks profile, and `databricks auth profiles` lists them. `MEMORY_API_KEY` is your NAMS key. Create the key at https://memory.neo4jlabs.com/. Copy the example file, fill in both values, then load them into your shell. Run the last line again in every new terminal.

   ```bash
   cp .env.example .env
   # edit .env: set DATABRICKS_CONFIG_PROFILE and MEMORY_API_KEY
   set -a; source .env; set +a
   ```

   Each command reads the key from a different place:

   - **From `.env`:** `make`, `setup_secrets.sh`, `agent-evaluate`, and the ontology scripts read `.env` themselves. A value exported in your shell wins over `.env`.
   - **From your shell:** `agentbricks dev` reads the key only from your shell. The `source .env` line above covers it. The commands in this README that you type by hand use `$DATABRICKS_CONFIG_PROFILE` from your shell.
   - **From the app resource:** The deployed app reads the key from its `nams-api-key` resource. The cloud steps below set that up.

2. **Install the Agent Bricks CLI and sign in:** This installs the CLI, then signs in with your profile.

   ```bash
   uv tool install databricks-agentbricks
   agentbricks login --profile "$DATABRICKS_CONFIG_PROFILE"
   ```

### Quick start local with make

The local server runs the same code as the deployed app. It needs no secret scope and no deploy. Use two terminals, because the server keeps running.

3. **Start the server (terminal 1):** `make dev` loads `.env` and starts the agent on http://localhost:8000. It stops with an error if `.env` or `MEMORY_API_KEY` is missing.

   ```bash
   make dev
   ```

4. **Ask a question (terminal 2, optional):** This asks the local server one question in a new session. Set another question with `make smoke-local QUESTION="..."`.

   ```bash
   make smoke-local
   ```

5. **See memory across sessions (terminal 2, optional):** The agent remembers each user's earlier questions, even in a new session. Locally, you choose the user by sending a `user_id` next to `messages`. This first question tells the agent what `analyst-7` focuses on:

   ```bash
   agentbricks endpoint invoke --url http://localhost:8000 --path /api/invocations \
     --json '{"id":"'$(uuidgen)'","session_id":"demo-1","input":{"user_id":"analyst-7","messages":[{"role":"user","content":"I focus on hub accounts. Which accounts act as hubs?"}]}}'
   ```

   Now ask as the same user in a new session. The answer uses the hub focus from the first question, although this session never saw it.

   ```bash
   agentbricks endpoint invoke --url http://localhost:8000 --path /api/invocations \
     --json '{"id":"'$(uuidgen)'","session_id":"demo-2","input":{"user_id":"analyst-7","messages":[{"role":"user","content":"What was I looking at last time?"}]}}'
   ```

   A body `user_id` works locally. A deployed app takes the user from the caller's identity, as [What gets recalled](docs/how-memory-works.md#what-gets-recalled) explains.

If you start the server by hand instead of through make, export `MEMORY_API_KEY` first. `agentbricks dev` reads the NAMS key only from the shell, and it stops with an error if the key is missing.

To run the tests and the CLI check, see [Develop and test](docs/reference.md#develop-and-test).

### Quick start cloud with make

3. **Save the NAMS key in Databricks:** This saves `MEMORY_API_KEY` from `.env` as the Databricks secret `nams/memory-api-key`. It creates the secret scope `nams` if needed.

   ```bash
   make secrets
   ```

4. **Trust your user:** Some tools act as several made-up analysts, so NAMS gets memory from more than one person. `make traffic` and the long-term memory demo work this way. Each request names its analyst in a `user_id` field. The app accepts that field only from callers listed in `MEMORY_TRUSTED_CALLERS` in `app.yaml`. This rule stops one user from reading another user's memory. Add yourself to the list now, before the first deploy. The app reads `app.yaml` only when it deploys, so a later change needs another deploy.

   This command prints your Databricks user name, which is usually your email:

   ```bash
   databricks current-user me -p "$DATABRICKS_CONFIG_PROFILE" -o json | jq -r .userName
   ```

   Put that value in `app.yaml`. Replace the values that are there now, because they belong to this repo's workspace. The match is exact, so copy the value as printed.

   ```yaml
   - name: MEMORY_TRUSTED_CALLERS
     value: <your-email>
   ```

   The list can hold more than one value, separated by commas. You need a second value only if you run traffic as a Databricks Job. [Run it as a Databricks Job](docs/traffic.md#run-it-as-a-databricks-job) covers that.

   If you skip this step, the other steps still work. Only the tools that send a `user_id` fail. Their first request gets a 403 error, and the error names the exact value to add. Add it, run `make deploy`, then run the tool again.

5. **Deploy:** This deploys the app `agent-bricks-neo4j-graph-agent` and prints its URL. On the first deploy, it adds the app resource `nams-api-key`, which points at the secret `nams/memory-api-key` with `READ` permission, and deploys again. To check it, open the app's Resources tab.

   ```bash
   make deploy
   ```

6. **Grant Genie access:** This grants the app what Genie needs to run its SQL. Run it once after the first deploy. It is safe to run again, and `make grant-genie DRY_RUN=1` only prints the grants.

   ```bash
   make grant-genie
   ```

7. **Test (optional):** `make smoke` asks the app one question in a new session. `make logs` streams the app logs until you press Ctrl-C. Set another question with `make smoke QUESTION="..."`.

   ```bash
   make smoke
   make logs
   ```

8. **Fill NAMS with traffic (optional):** This sends 24 questions from 6 made-up analysts through the app, so NAMS has memory to show. It needs your user in `MEMORY_TRUSTED_CALLERS` from step 4. When the run ends, it checks that NAMS stored every turn. That check needs `MEMORY_API_KEY` in your shell or in `.env`. [Generate traffic](docs/traffic.md) covers larger runs and running it as a Databricks Job.

   ```bash
   make traffic
   ```

   If the first turn fails with a 403, your user is missing from the list. The error names the value to add. Add it to `MEMORY_TRUSTED_CALLERS` in `app.yaml`, run `make deploy`, then run `make traffic` again.

## Architecture

![Architecture of the agent, the MCP service, the Genie space, and NAMS](docs/architecture.svg)

The parts:

- **Caller:** The caller is any client that sends questions, such as the CLI, the traffic generator, or a Databricks Job.
- **Databricks App:** The app is the deployed agent, served by the Agent Bricks `DurableAgentServer`.
- **Agent:** The agent is an OpenAI Agents SDK loop with two read-only graph tools and the Genie tools.
- **TurnMemory:** This class in `agent/nams.py` recalls memory before a turn and writes the turn to NAMS after it.
- **AI Gateway model:** This model writes the answer. The default is `claude-sonnet-5-5`.
- **MCP service:** The Unity Catalog service `finance_genie_mcp` runs read-only Cypher on Neo4j.
- **Genie space:** The Genie space answers value questions over the gold Delta tables.
- **NAMS:** NAMS stores conversations, messages, reasoning traces, and entities.
- **Secret scope `nams`:** This scope holds the NAMS key, which the app reads as `MEMORY_API_KEY`.

[How memory works](docs/how-memory-works.md) walks through one turn step by step.

## Demo: short-term memory

This demo shows short-term memory: one analyst's own earlier questions. In step 3, a new session asks "What was I looking at last time?", and the agent answers from that analyst's past conversations. The next section, [Long-term memory and the ontology](#long-term-memory-and-the-ontology), shows memory that is shared across all analysts. Run this demo first, because it needs only the quick start.

The demo script asks six questions in five steps and prints each answer. The steps show the graph, Genie, and memory working together. The evidence is the ids in each answer and the spans in the MLflow trace. The exact answer text changes from run to run.

### The steps

Each step lists the question the script asks, the ids the answer should name, and the spans the MLflow trace should show.

- **1. Shared phone:** This step asks two questions. It asks which customers share phone 312-555-0142 and which accounts they own, then which community those accounts are in.
  - **Answer:** The first answer names Accounts 368, 927, 1033, and 1696. The second answer names Community 8174.
  - **Trace:** The trace has a span ending in `read_neo4j_cypher`. The Gateway adds a prefix, so the full name is `neo4j-mcp-server-target___read_neo4j_cypher`.
- **2. Hub:** This step asks whether Account 15940 is a hub and which community it is in.
  - **Answer:** The answer names Community 19766.
  - **Trace:** The trace has a span ending in `read_neo4j_cypher`.
- **3. Recall:** This step starts a new session and asks "What was I looking at last time?"
  - **Answer:** The answer names Account 15940, although this session never did. The agent found it in NAMS.
  - **Note:** Recall reads only your two latest conversations, so run step 2 right before this step.
- **4. Genie value question:** This step asks for the average account balance by region and account type.
  - **Trace:** The trace has a `genie_ask` span, then a `genie_query_result` span.
- **5. Graph and Genie:** This step asks which phone numbers are shared by more than one customer, and what the balances and 30-day transaction counts of those accounts are.
  - **Trace:** The trace has a span ending in `read_neo4j_cypher`, then a `genie_ask` span. The Genie question names the account ids that the graph found.
- **ring (optional):** This step asks whether Community 3040 is a fraud ring candidate. The default run skips it. Run it with `--step ring` after step 3.
  - **Answer:** The answer names Community 3040.
  - **Trace:** The trace has a span ending in `read_neo4j_cypher`.

Steps 1 and 2 share one session. Step 3 starts a new session, and steps 4 and 5 stay in it.

### Run the script

Run from `neo4j-mcp-graph-agent/`. The script prints each question, the answer, and a **You should see** list for the step. It cannot read MLflow, so open the latest traces and check the spans yourself.

- **Local:** Start `make dev` in another terminal, as in the [local quick start](#quick-start-local-with-make). Then run the script.

  ```bash
  uv run scripts/demo.py
  ```

- **Cloud:** Do the [cloud quick start](#quick-start-cloud-with-make) first. The script reads `DATABRICKS_CONFIG_PROFILE` from `.env`, finds the app URL, and signs in for you.

  ```bash
  uv run scripts/demo.py --cloud
  ```

### Run one step or your own question

- **`--step`:** This flag runs only the steps you name. Steps 2 and 3 are the memory demo. Run them back to back, because recall reads only your two latest conversations.

  ```bash
  uv run scripts/demo.py --step 2 3
  ```

- **`--ask`:** This flag asks one question of your own instead of the steps.

  ```bash
  uv run scripts/demo.py --ask "Which community is Account 15940 in?"
  ```

### See the memory in NAMS

Open your NAMS workspace at https://memory.neo4jlabs.com/ and find your user.

- **User:** The deployed app uses your Databricks email. The local server uses `demo-analyst`.
- **Conversations:** Each question is its own conversation, with its messages and a reasoning trace.
- **Entities:** Entities such as Account 15940 and Community 19766 appear after NAMS extracts them. They lag the write by seconds to minutes.

## Long-term memory and the ontology

This section shows long-term memory: memory that all analysts share. The demo above shows one analyst's own history. Here, NAMS reads every stored conversation and pulls out entities, such as Community 3040. Those entities form one graph for the whole team. So a new analyst can get findings that another analyst made. The ontology is the list of entity types that tells NAMS what to pull out.

Do these two pages in this order:

1. [Show long-term memory](docs/longterm.md): Do this first, because it is the main point. The page turns on the finance ontology, then runs traffic from six made-up analysts so NAMS has conversations to read. Then it shows two things:
   - **Demo 1:** The NAMS console shows one entity that several analysts talked about.
   - **Demo 2:** The agent answers a new analyst with another analyst's findings.
2. [Run the ontology example](docs/ontology-experiment.md): This page is optional. Do it second, because it goes deeper and it erases your NAMS data. It runs the same 24 conversations through NAMS twice and compares what NAMS pulled out.
   - **Trial 1:** This trial uses the generic NAMS Default ontology.
   - **Trial 2:** This trial uses the finance ontology.
   - **Warning:** The run resets your NAMS database. Use a database that holds nothing you want to keep.

## Clean up

Run these from `neo4j-mcp-graph-agent/` with the variables from [Quick start with make](#quick-start-with-make) loaded.

### Delete the app and its data

The first command also starts you over if a deploy fails and you want a fresh app.

1. **Delete the app:** This deletes the app `agent-bricks-neo4j-graph-agent` and its Agent Bricks Runtime Store. The command asks you to confirm. Add `--yes` to skip the prompt.

   ```bash
   agentbricks --profile "$DATABRICKS_CONFIG_PROFILE" deployments delete agent-bricks-neo4j-graph-agent
   ```

2. **Delete the NAMS secret:** This deletes the secret scope `nams`, which holds the NAMS key. Skip it if you plan to deploy again.

   ```bash
   databricks secrets delete-scope nams -p "$DATABRICKS_CONFIG_PROFILE"
   ```

3. **Delete the NAMS data:** The conversations from your runs stay in NAMS. Remove them in your NAMS workspace at https://memory.neo4jlabs.com/, or revoke the key there.

To deploy again after a cleanup, start at step 3 of [Quick start cloud with make](#quick-start-cloud-with-make). A new app has a new service principal, so run `make grant-genie` again after the deploy.

### Start the ontology example over

Do these after you delete the NAMS data in step 3 above.

1. **Reset the ontology to the default:** NAMS cannot remove an active ontology. You switch back to the NAMS Default ontology instead. Do this before you repeat the [ontology example](docs/ontology-experiment.md) or the [long-term memory demo](docs/longterm.md) from a clean start.

   ```bash
   uv run ontology/apply_ontology.py --reset
   ```

   Or run `make reset-ontology`. The command finds the NAMS Default ontology by name and activates its newest revision that has none of the finance types. It prints the activated version. It needs no saved file.

2. **Clear the saved run files (optional):** The ontology scripts save transcripts and snapshots in `ontology/out/`. This deletes them so the next run starts empty. Git ignores this folder, so the files cannot be restored.

   ```bash
   rm -f ontology/out/*.json
   ```

Then go to [Run the ontology example](docs/ontology-experiment.md).

### Fix a Runtime Store that blocks deploy or delete

If `deploy` or `delete` fails with "Runtime Store ... does not belong to this app identity", this is the fix. A Runtime Store with the same name was left behind by an earlier app that was deleted outside `agentbricks`. The store belongs to a service principal that no longer exists, so the CLI refuses to reuse or delete it. To confirm, read the store. Its `owner.app.service_principal_id` differs from your app's `service_principal_client_id`.

```bash
databricks api get /api/2.0/agents/runtime-stores/agent-bricks-neo4j-graph-agent -p "$DATABRICKS_CONFIG_PROFILE"
databricks apps get agent-bricks-neo4j-graph-agent -p "$DATABRICKS_CONFIG_PROFILE" -o json | jq -r .service_principal_client_id
```

If the two ids differ and the old owner is gone, delete the orphaned store directly. This also deletes the store's database, and it skips the CLI's ownership check, so confirm the ids first. Then run `make deploy` again.

```bash
databricks api delete /api/2.0/agents/runtime-stores/agent-bricks-neo4j-graph-agent -p "$DATABRICKS_CONFIG_PROFILE"
```

## Documentation

- [How memory works](docs/how-memory-works.md): This page walks through one turn and shows what NAMS saves and recalls.
- [Long-term memory](docs/longterm.md): Two demos show the NAMS entity graph and the agent recalling it across analysts.
- [Generate traffic](docs/traffic.md): The traffic generator runs from your laptop or as a Databricks Job.
- [Run the ontology example](docs/ontology-experiment.md): Two trials, with the generic default and with the finance ontology, show how the ontology drives the schema.
- [Add NAMS as a Databricks MCP service](docs/nams-mcp-service.md): Other agents, such as the Playground, can use the NAMS tools.
- [Create the finance-genie MCP service](docs/mcp-service.md): The agent reads the graph through this Neo4j MCP service.
- [Reference](docs/reference.md): This page covers configuration, guardrails, evaluation, tests, delete, layout, and notes.
- [Troubleshooting](docs/troubleshooting.md): This page shows how to update the MCP connection and check the deployed MCP server image.
