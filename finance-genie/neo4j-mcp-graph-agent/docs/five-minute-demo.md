# Five-minute demo

This page is a short demo against the deployed app. It shows short-term memory, then long-term memory, and it shows each one in the NAMS Query Console by conversation id.

- **Short-term memory:** One analyst's own earlier questions. A new session recalls what the analyst looked at last time.
- **Long-term memory:** The entity graph that NAMS builds from every analyst's conversations. A new analyst gets findings that other analysts made.

## Before you present

Do these steps before the talk. They are not part of the five minutes.

1. **Finish the cloud quick start:** Do steps 1 to 7 of [Quick start cloud with make](../README.md#quick-start-cloud-with-make). Your user must be in `MEMORY_TRUSTED_CALLERS` in `app.yaml`.

2. **Load your variables:** Run every command from `neo4j-mcp-graph-agent/`. Run this again in every new terminal.

   ```bash
   set -a; source .env; set +a
   ```

3. **Apply the ontology and run the traffic:** Skip this step if NAMS already holds traffic from an earlier run with the finance ontology. The traffic sends 24 turns from six made-up analysts. Three of them investigate Community 3040.

   ```bash
   make apply-ontology
   make traffic
   ```

4. **Wait for extraction:** Open the Query Console in your NAMS workspace at https://memory.neo4jlabs.com/. Run this query until the only status is `done`. Extraction of the traffic takes about 10 minutes.

   ```cypher
   MATCH (m:Message) RETURN m.extractionStatus AS status, count(*) AS n
   ```

5. **Get the app URL:** This saves the deployed app's URL in `APP_URL`.

   ```bash
   export APP_URL=$(databricks apps get agent-bricks-neo4j-graph-agent -p "$DATABRICKS_CONFIG_PROFILE" -o json | jq -r .url)
   ```

6. **Run turn 1 as analyst A:** This asks "I am investigating Community 3040..." as analyst A. Then it waits until NAMS has extracted the entities from this turn, which takes about a minute.

   ```bash
   uv run scripts/demo_longterm.py --turn 1 --app-url "$APP_URL" --profile "$DATABRICKS_CONFIG_PROFILE"
   ```

7. **Copy analyst A's conversation id:** Run this in the Query Console. Copy the `c.id` value from the top row, which is the newest turn.

   ```cypher
   MATCH (c:Conversation)-[:HAS_MESSAGE]->(m:Message {role: 'user'})
   WHERE c.userId = 'demo-analyst-a'
   RETURN c.id, m.content, c.createdAt
   ORDER BY c.createdAt DESC LIMIT 20
   ```

8. **Set up your screen:** Keep a terminal open in `neo4j-mcp-graph-agent/` and the NAMS Query Console open in a browser tab.

## The demo

### 1. Short-term memory (about 2 minutes)

1. **Run three questions:** This asks three questions in about 90 seconds.

   ```bash
   uv run scripts/demo.py --cloud --step 2 3 5
   ```

2. **Point out each step while it runs:**
   - **Step 2, Hub:** The agent asks the graph whether Account 15940 is a hub. The answer names Community 19766.
   - **Step 3, Recall:** A new session asks "What was I looking at last time?" The answer names Account 15940, although this session never did. The app read it from your earlier conversation in NAMS.
   - **Step 5, Graph, then lakehouse:** The agent asks the graph which phones are shared. Then it asks Genie for the balances of those accounts.

### 2. Short-term memory in NAMS (about 30 seconds)

1. **Copy the conversation id from step 2:** Under the step 2 answer, the script prints a line like `In NAMS: user <your email>, conversation <id>`. Copy that id.

2. **Show the conversation:** Paste this in the Query Console, and replace `<conversation id>` with the id. The graph shows the question, the answer, the agent's reasoning steps, and its tool calls. Step 3 recalled this conversation.

   ```cypher
   MATCH (c:Conversation {id: '<conversation id>'})
   OPTIONAL MATCH (c)-[:HAS_MESSAGE]->(m:Message)
   OPTIONAL MATCH (c)-[:HAS_STEP]->(s:AgentStep)-[:USED_TOOL]->(t:ToolCall)
   RETURN c, m, s, t
   ```

### 3. Long-term memory (about 1 minute)

1. **Run turn 2 as analyst B:** This asks "What is already known about Community 3040?" as analyst B in a new session.

   ```bash
   uv run scripts/demo_longterm.py --turn 2 --analyst-b demo-analyst-b-1 --app-url "$APP_URL" --profile "$DATABRICKS_CONFIG_PROFILE"
   ```

2. **Point out the findings:** The answer opens with notes from earlier investigations. These include the case that investigated Community 3040, its rank among ring candidates, and Account 7890. Analyst B shares no session and no conversation history with any other analyst. Those notes came from the entity graph.

### 4. Long-term memory in NAMS (about 1 minute)

1. **Show who else talked about it:** Paste this in the Query Console, and replace `<conversation id>` with analyst A's id from step 7 of [Before you present](#before-you-present). The query starts at analyst A's conversation and finds its Community 3040 entity. Then it lists every conversation that mentioned an entity of that name.

   ```cypher
   MATCH (c:Conversation {id: '<conversation id>'})-[:HAS_MESSAGE]->(:Message)<-[:EXTRACTED_FROM]-(e:Entity {name: 'Community 3040'})
   MATCH (:Entity {name: e.name})-[:EXTRACTED_FROM]->(:Message)<-[:HAS_MESSAGE]-(other:Conversation)-[:HAS_MESSAGE]->(q:Message {role: 'user'})
   RETURN DISTINCT other.userId AS analyst, q.content AS question, other.createdAt AS asked
   ORDER BY asked
   ```

   The table lists analysts from different teams, such as the owners of CASE-4001 and CASE-4006. Analyst A is in it too. Analyst B appears after NAMS extracts the turn 2 conversation.

2. **Say this:** "The conversation history belongs to one analyst. This entity graph belongs to the team. Nobody queried for it. It fell out of storing conversations."

## Run it again

- **Analyst B:** Change the `--analyst-b` value on each run, for example to `demo-analyst-b-2`. Analyst B then has no earlier demo turns of their own to recall.
- **Analyst A:** Each turn 1 run stores a new conversation. Run step 7 of [Before you present](#before-you-present) again and copy the newest id.
- **Full walkthrough:** [Long-term memory](longterm.md) has the longer version of the long-term memory demo. The [demo section of the README](../README.md#demo-graph-genie-and-short-term-memory) covers all five routing steps.
