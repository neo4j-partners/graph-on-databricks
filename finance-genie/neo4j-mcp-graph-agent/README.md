# neo4j-mcp-graph-agent

This is a Databricks App agent. It answers questions about the finance-genie fraud graph. It also remembers each analyst's earlier questions in NAMS.

- **Graph access:** The agent calls the Unity Catalog MCP service `graph-on-databricks.finance_genie.finance_genie_mcp`. The service fronts Neo4j. The app calls it with its own service principal.
- **Runtime:** The app runs on Agent Bricks. It uses the OpenAI Agents SDK for the agent loop. It uses `DurableAgentServer` for sync, streaming, and background calls with crash recovery.
- **Memory:** The app saves each turn to NAMS and reads recent turns back before it answers. See [How the sample uses NAMS](#how-the-sample-uses-nams).

## How it works

- **`agent.toml`:** Declares the MCP service as an app-identity tool, a session store for multi-turn history, and the MLflow tracing experiment.
- **`agent/agent.py`:** Builds the agent, loads the MCP server from `agent.toml`, and applies the guardrails.
- **`agent/guardrails.py`:** Defines the guardrails. They expose only `get_neo4j_schema` and `read_neo4j_cypher`. They reject write Cypher, cut results at 8000 characters, and stop a run after 20 steps.
- **`agent/nams.py`:** Reads and writes NAMS.
- **`runtime/`:** Serves the agent at `/api/invocations`.
- **`agentbricks deploy`:** Creates the app and the declared stores. It grants the app service principal `EXECUTE` on the MCP service, plus `USE_SCHEMA` and `USE_CATALOG` on its parents. Deploy does all the grants for the MCP service.

## Prerequisites

- **Tools:** Python 3.11 or newer, [uv](https://docs.astral.sh/uv/), and the [Databricks CLI](https://docs.databricks.com/aws/en/dev-tools/cli/install).
- **Agent Bricks CLI:** The CLI is in Beta. Install it with `uv tool install databricks-agentbricks`, or run it with `uvx --from databricks-agentbricks agentbricks ...`.
- **Workspace:** The workspace needs Databricks Apps and Unity Catalog AI Gateway.
- **MCP service:** The service `graph-on-databricks.finance_genie.finance_genie_mcp` must exist. It must expose the tools `get_neo4j_schema` and `read_neo4j_cypher`. TODO: link the MCP service creation doc.
- **Grant right:** You must own the MCP service or have `MANAGE` on it. Deploy grants `EXECUTE` on it for the app.
- **NAMS key:** Create a key at https://memory.neo4jlabs.com/. [Set up the key](#set-up-the-key) shows where it goes.

## Quick start

1. **Install the CLI.**

   ```bash
   uv tool install databricks-agentbricks
   agentbricks --help
   ```

2. **Sign in.** Set the profile variable first. Every command below that takes a profile uses it.

   ```bash
   databricks auth profiles                      # list your profiles
   export DATABRICKS_CONFIG_PROFILE=<your-profile>
   agentbricks login --profile "$DATABRICKS_CONFIG_PROFILE"
   ```

3. **Run the checks.**

   ```bash
   uv sync
   MLFLOW_DISABLE_AGENT_HINT=1 uv run pytest
   agentbricks doctor .
   ```

4. **Run it locally.** Use two terminal windows, because the server keeps running.

   In window 1, create `.env` and start the server. Set `DATABRICKS_CONFIG_PROFILE` and `MEMORY_API_KEY` in `.env`. Also export `MEMORY_API_KEY` in this shell. `agentbricks dev` stops with an error if the shell does not have it.

   ```bash
   cp .env.example .env
   export MEMORY_API_KEY=<your-key>
   agentbricks dev             # serves http://localhost:8000
   ```

   In window 2, ask a question. Export `DATABRICKS_CONFIG_PROFILE` in this shell too.

   ```bash
   agentbricks endpoint invoke --url http://localhost:8000 --path /api/invocations \
     --json '{"id":"'$(uuidgen)'","session_id":"demo-1","input":[{"role":"user","content":"Which communities look like fraud ring candidates?"}]}'
   ```

5. **Deploy.** App names can have at most 30 characters, and the `agent-bricks-` prefix uses 13. So the deploy name can have at most 17.

   ```bash
   agentbricks deploy neo4j-graph-agent
   agentbricks deployments get agent-bricks-neo4j-graph-agent   # URL and status
   ```

   On the first deploy, attach the NAMS key to the new app as shown in [Set up the key](#set-up-the-key). Then deploy again.

6. **Test the deployed app.**

   ```bash
   SESSION_ID=$(uuidgen)
   agentbricks --profile "$DATABRICKS_CONFIG_PROFILE" endpoint invoke agent-bricks-neo4j-graph-agent \
     --path /api/invocations --routing-key "$SESSION_ID" \
     --json '{"id":"'$(uuidgen)'","session_id":"'$SESSION_ID'","input":[{"role":"user","content":"What does the SIMILAR_TO relationship mean?"}]}'
   agentbricks deployments logs agent-bricks-neo4j-graph-agent
   ```

   Use a new `id` for every request. Reuse `session_id` to continue a conversation.

## Architecture

The app answers questions about the fraud graph. It also remembers what each analyst asked before.

![Architecture of the agent, the MCP service, and NAMS](docs/architecture.svg)

How one turn flows:

1. **Request:** A caller sends a question with a `user_id`.
2. **Recall:** The app reads that user's recent conversations from NAMS.
3. **Answer:** The agent asks the model and reads the graph through the MCP service.
4. **Reply:** The app sends the answer back to the caller.
5. **Write:** The app saves the turn to NAMS.
6. **History:** Agent Bricks keeps the session history and the MLflow traces.

The parts:

- **Caller:** The client that sends questions. It is the traffic CLI, the Databricks Job, or any other client.
- **Databricks App:** The deployed agent. It runs the Agent Bricks `DurableAgentServer`.
- **Agent:** The OpenAI Agents SDK loop. Guardrails allow only two read-only graph tools.
- **TurnMemory:** The class in `agent/nams.py` that handles one turn. A turn is one question and its answer. The class reads memory before the turn and writes the turn to NAMS after it.
- **AI Gateway model:** The model that writes the answer. `app.yaml` pins `claude-sonnet-4-5`.
- **MCP service:** The Unity Catalog service `finance_genie_mcp`. It runs read-only Cypher on Neo4j.
- **NAMS:** The hosted [Neo4j Agent Memory Service](https://memory.neo4jlabs.com/). It stores conversations, messages, traces, and entities.
- **Secret scope `nams`:** The place that holds the NAMS key. The app resource `nams-api-key` hands it to the app as `MEMORY_API_KEY`.

## How the sample uses NAMS

The app uses NAMS as long term memory. It saves every turn and reads recent turns back before it answers. The AWS `fraud-memory-agent` demo only saves. This sample also recalls.

![Sequence of one turn: recall from NAMS, answer, then write to NAMS](docs/nams-flow.svg)

How one turn uses NAMS:

1. **Request:** The caller sends a question and a `user_id`.
2. **Recall:** The app opens a `TurnMemory` for the turn. It lists the user's conversations in NAMS and reads the latest two.
3. **Run:** The app runs the agent with the recalled text in its instructions.
4. **Buffer:** The app hands each tool call and the final answer to `TurnMemory`. It holds them in memory.
5. **Reply:** The app sends the answer to the caller.
6. **Write:** `TurnMemory` saves the turn to NAMS as one conversation with two messages and a reasoning trace.

**Turn:** One question and its answer. `TurnMemory` handles one turn. NAMS stores each turn as its own conversation, and the `user_id` links a user's turns together.

- **Write:** After each turn, the app saves the user message and the answer as a conversation.
- **Trace:** When the agent uses tools, the app saves one reasoning trace. The trace has one step and one tool call for each MCP call.
- **Entities:** NAMS finds entities in the messages on its own servers. The app does nothing for this.
- **Recall:** Before the agent runs, the app lists the user's latest conversations and reads the last two.
- **Where recall goes:** The recalled text goes into the agent instructions as background. It stays out of the message input, because Agent Bricks saves input to the session store.
- **User:** Send `user_id` next to `messages`. Without it, the app uses `session_id` as the user, and recall finds only turns from that session.
- **One conversation per turn:** Each turn is its own conversation in NAMS. Each one carries the `user_id` in its metadata, and recall filters on it.
- **Limits:** Recall waits at most 10 seconds and adds at most 2000 characters.
- **Best effort:** If the key is missing, or NAMS is slow or down, the agent answers without memory. NAMS never breaks an answer.
- **Retries:** A recovery run reads memory but does not write. A replayed turn is not saved twice.
- **Evaluation:** `agent-evaluate` calls the agent directly. It never writes to NAMS.

Try it against a local server:

```bash
agentbricks endpoint invoke --url http://localhost:8000 --path /api/invocations \
  --json '{"id":"'$(uuidgen)'","session_id":"demo-1","input":{"user_id":"analyst-7","messages":[{"role":"user","content":"I focus on hub accounts. Which accounts act as hubs?"}]}}'
```

Then send a second question with a new `session_id` and the same `user_id`. The answer uses the hub focus from the first question.

For local runs, `agentbricks dev` reads `MEMORY_API_KEY` from your shell, not from `.env`. Export it first.

### Set up the key

1. **Create the key:** Make a key at https://memory.neo4jlabs.com/.
2. **Save it locally:** Put it in `.env` as `MEMORY_API_KEY`.
3. **Save it in Databricks:** Run `./setup_secrets.sh`. The script reads `MEMORY_API_KEY` and `DATABRICKS_CONFIG_PROFILE` from `.env`. It creates the scope `nams` if needed and writes the key as `memory-api-key`. Pass `--profile <name>` to use another profile.
4. **Attach it to the app:** After the first `agentbricks deploy`, add an app resource named `nams-api-key`. Use type secret, scope `nams`, key `memory-api-key`, and `CAN_READ`. Add it in the app's Resources settings, or with `databricks apps update`.
5. **Deploy again:** Run `agentbricks deploy` so the app picks up the key.

The resource stayed attached across later deploys in testing. Check it after each deploy anyway.

## Run the jobs

The traffic project fills NAMS with conversations. Fake analysts call the deployed app, and the app writes to NAMS. You can run it from your laptop or as a Databricks Job.

- **Analysts:** Each analyst states a team and a focus in the first session. Later sessions do not repeat it, so an answer that uses the focus shows recall working.
- **Through the app:** Traffic goes through the app, so only the app holds the NAMS key.
- **Safe retries:** Each turn has a fixed invocation id. A retry cannot save a turn twice.
- **Replay:** Running the same `--run-id` again replays the stored invocations. It writes no new conversations.

Before you start, deploy the app and set up the key as described above.

### Run it from your laptop

```bash
cd traffic
uv sync
uv run agent-traffic --dry-run --users 2 --sessions-per-user 2
uv run agent-traffic --profile "$DATABRICKS_CONFIG_PROFILE" --app-url https://<app-url> \
  --users 2 --sessions-per-user 2 --turns-per-session 2
```

The dry run prints the plan and calls nothing. The second command signs in with your profile.

The options:

- **`--users`:** The number of analysts. The default is 20.
- **`--sessions-per-user`:** The sessions each analyst starts. The default is 3.
- **`--turns-per-session`:** The questions in each session. The default is 4.
- **`--concurrency`:** The sessions that run at once. The default is 4.
- **`--timeout`:** The seconds allowed for one turn. The default is 300.
- **`--retry-attempts`:** The tries for each turn. The default is 1.
- **`--continue-after-error`:** Keeps going after a failed turn. By default the run stops.
- **`--run-id`:** Names the users and sessions. A random id is the default.

The default run is 240 turns. Each turn takes 20 to 60 seconds, so the full run takes close to an hour.

### Run it as a Databricks Job

The Databricks Apps proxy returns a 401 for the token that a job gets from its own runtime. So the job signs in as a service principal. This setup happens once.

1. **Create the principal and its secret:**

   ```bash
   databricks service-principals create --display-name nams-traffic-runner -p <profile>
   databricks service-principal-secrets-proxy create <service-principal-id> -p <profile>
   ```

   The second command prints the OAuth secret once. Copy it now.

2. **Store the credentials:** The `put-secret` commands ask for each value. Use the principal's application id and the OAuth secret.

   ```bash
   databricks secrets create-scope nams-traffic -p <profile>
   databricks secrets put-secret nams-traffic client-id -p <profile>
   databricks secrets put-secret nams-traffic client-secret -p <profile>
   ```

3. **Let the principal call the app:**

   ```bash
   databricks apps update-permissions agent-bricks-neo4j-graph-agent -p <profile> \
     --json '{"access_control_list":[{"service_principal_name":"<client-id>","permission_level":"CAN_USE"}]}'
   ```

Then deploy the bundle and run the job. The job runs as you, so you need `READ` on the scope `nams-traffic`.

```bash
cd traffic
databricks bundle deploy -p <profile> --var app_url=https://<app-url>
databricks bundle run nams_traffic -p <profile> --var app_url=https://<app-url> \
  --params users=2,sessions_per_user=1,turns_per_session=2
```

The job parameters:

- **`app_url`:** The URL of the deployed app. You must pass it with `--var`.
- **`credentials_scope`:** The scope that holds the principal's credentials. The default is `nams-traffic`.
- **`users`, `sessions_per_user`, `turns_per_session`, `concurrency`, `timeout`:** The same settings as the CLI options. Change them with `--params`.

To run the job every hour, set `pause_status: UNPAUSED` in `traffic/databricks.yml` and deploy the bundle again. The schedule is paused by default.

To check a run:

- **Job output:** Open the run URL that `bundle run` prints. The log ends with `done ok=N failed=0`.
- **NAMS:** Open your NAMS workspace and look for users named `nams-load-<run-id>-user-NNNN`. The run id is in the first log line.

If something fails:

- **401 from the app:** The principal lacks `CAN_USE` on the app, or the credentials in the scope are wrong.
- **`no value assigned to required variable app_url`:** Add `--var app_url=...` to the command.
- **No data in NAMS:** Check that the `nams-api-key` resource is still attached to the app.

The app is not part of this bundle. `agentbricks deploy` provisions its runtime store, session store, and MCP grants, and a bundle app resource would conflict with that.

## Configuration

| Setting | Where to change it | Default |
| --- | --- | --- |
| NAMS key | `MEMORY_API_KEY` env var, or the `nams-api-key` app resource when deployed | Unset, so memory is off |
| NAMS endpoint and workspace | Optional `MEMORY_ENDPOINT` and `MEMORY_WORKSPACE_ID` env vars | The NAMS defaults |
| MCP service | `agent.toml` `[[tools]]` | `graph-on-databricks.finance_genie.finance_genie_mcp` |
| Model | `LLM_MODEL` env var | Code default `system.ai.claude-sonnet-5-5`. `app.yaml` pins `system.ai.claude-sonnet-4-5`. |
| Judge model | `JUDGE_MODEL` env var | `databricks:/databricks-claude-sonnet-5-5` |
| Session store | `agent.toml` `[session_store]` | `neo4j-mcp-graph-agent-sessions` |
| Tracing experiment | `agent.toml` `[tracing]` | `/Shared/agentbricks_traces/neo4j-mcp-graph-agent` |
| Traffic credentials scope | `credentials_scope` job parameter | `nams-traffic` |

- **Other MCP service:** Edit the `service` value in `agent.toml`, or run `agentbricks tools add mcp <service> --auth app`. Then deploy again.
- **Model:** Read [Known issue](#known-issue-claude-5-models-fail-to-stream) before you change the model.

## Evaluate

```bash
LLM_MODEL=system.ai.claude-sonnet-4-5 uv run agent-evaluate
```

- **What it runs:** The agent answers the questions in `agent/evaluate.py`. MLflow scorers grade the answers.
- **Judges:** The judges use a Databricks-hosted model, set by `JUDGE_MODEL`. The judges use no external API key.
- **Pass rule:** The run fails unless every case passes the safety and no-write checks.
- **Model:** Set `LLM_MODEL` as shown, because the code default fails. See the known issue below.
- **NAMS:** The run never writes to NAMS.

## Delete the agent

```bash
agentbricks --profile "$DATABRICKS_CONFIG_PROFILE" deployments delete agent-bricks-neo4j-graph-agent
```

- **What it deletes:** The app and, when managed provisioning is on, its runtime store.
- **What it keeps:** The grants on the MCP service and the MLflow tracing experiment stay in place.
- **Stop only:** Run `agentbricks deployments stop agent-bricks-neo4j-graph-agent` to stop the app without deleting it.

## Layout

```
agent.toml          MCP binding, session store, tracing
app.yaml            App start command
setup_secrets.sh    Writes the .env secrets to a Databricks secret scope
docs/               Architecture diagram
agent/              agent, system prompt, guardrails, NAMS memory, evaluation
runtime/            DurableAgentServer entrypoint and adapter
tests/              guardrail, adapter, and memory tests
traffic/            synthetic analyst traffic CLI and its Databricks Job bundle
```

## Notes

- **Beta CLI:** The Agent Bricks CLI is in Beta. Its README documents the grant behavior.
- **Grant fails:** If deploy cannot grant on the MCP service, grant by hand in Catalog Explorer. Open Permissions on the MCP service. Give the app's service principal `EXECUTE`, plus `USE_CATALOG` and `USE_SCHEMA` on its parents.
- **Backing resources:** The MCP service must be allowed to reach whatever backs it. Agent Bricks does not grant access to those resources.

## Known issue: Claude 5 models fail to stream

The default in `agent/agent.py` is `system.ai.claude-sonnet-5-5`, and `app.yaml` overrides it with
`LLM_MODEL=system.ai.claude-sonnet-4-5`. Every run on the default fails with the error below.
`claude-sonnet-5` and `claude-opus-5-5` fail the same way, while `claude-sonnet-4-5` completes.

```
pydantic_core._pydantic_core.ValidationError: 1 validation error for ResponseTextDeltaEvent
delta
  Input should be a valid string [type=string_type, input_value=[{'type': 'reasoning', ...}]]
```

The OpenAI Agents SDK chat completions stream handler (`chatcmpl_stream_handler.py`, openai-agents
0.23.1) builds `ResponseTextDeltaEvent` from the chunk delta. The Claude 5 models return a list of
reasoning blocks in that field, and the event requires a string. The failure does not depend on NAMS,
MCP, or the Agent Bricks runtime. Calling `run_question` from `agent/evaluate.py` with no
`MEMORY_API_KEY` reproduces it.

To investigate, check whether a newer `openai-agents` release handles reasoning deltas, whether
the AI Gateway can return the reasoning in a separate field, or whether the Responses API works
for these models. Run `agent-evaluate` with `LLM_MODEL` set to the Claude 5 model to retest, then
remove the pin in `app.yaml`.
