# Long-term memory

This page walks through the long-term memory demo against the deployed app. Part 1 shows the long-term memory itself. Part 2 shows the agent using it.

## Overview

The app writes every turn to NAMS. NAMS reads each stored conversation and extracts entities from it. Those entities form a graph that spans sessions and analysts. That graph is the long-term memory. The agent recalls it before it answers.

## Key terms

- **Short-term memory**: one analyst's stored conversations. The app reads the analyst's two latest conversations before each turn.
- **Long-term memory**: the entity graph in NAMS. It holds the entities that all analysts' conversations mentioned.
- **Entity**: one thing analysts talked about, such as Community 3040 or Account 7890. An entity has a name, a type, and a description.
- **Extraction**: the NAMS background process that reads a stored conversation and creates entities. It finishes seconds to minutes after a turn.
- **Ontology**: the type list in `ontology/finance_genie.ontology.yaml`. It makes extraction produce types such as Account, Community, and Case.
- **NAMS graph database**: the Neo4j database behind NAMS. It holds conversations, messages, and entities, and each entity links to the messages it came from.

## Before you start

Do steps 1 to 7 of [Quick start cloud with make](../README.md#quick-start-cloud-with-make) first. The app must be deployed, and your user must be in `MEMORY_TRUSTED_CALLERS` in `app.yaml`. If you already ran step 8, `make traffic`, that is fine. Step 4 below runs it again with the finance ontology active.

Install `neo4j-cli`. Parts 1 and 2 read the NAMS graph database with it.

Run every command from `neo4j-mcp-graph-agent/`.

## Set up

1. **Add the NAMS graph database to `.env`:** Open `.env` and fill in the four `NEO4J_*` lines with the connection details of the NAMS graph database. Remove the `#` at the start of each line.

   ```bash
   NEO4J_URI=
   NEO4J_USERNAME=
   NEO4J_PASSWORD=
   NEO4J_DATABASE=
   ```

2. **Load your variables:** This loads `.env` into your shell. Run it again in every new terminal.

   ```bash
   set -a; source .env; set +a
   ```

3. **Apply the ontology:** Extraction now types entities as Account, Community, Case, and Analyst.

   ```bash
   make apply-ontology
   ```

4. **Run the traffic:** This sends 24 turns from six analysts through the deployed app. Analysts 1 and 6 investigate the same Community 3040 from different teams.

   ```bash
   make traffic
   ```

   If the run exits with code 2 and prints `NOT STORED` lines, NAMS dropped some turns. Reset NAMS and run the traffic again.

5. **Wait for extraction:** `make traffic` returns before NAMS finishes extracting, which takes a few minutes. Run this query until the only status is `done`.

   ```bash
   neo4j-cli query "MATCH (m:Message) RETURN m.extractionStatus AS status, count(*) AS n"
   ```

## Part 1: show the entity graph

This part proves the long-term memory exists.

1. **Find the shared entity:** This lists the entities that more than one analyst's conversations fed, most analysts first. Copy the id from the top row. After `make traffic`, the top row has been Community 3040. Extraction merges some mentions and leaves others as duplicates, so the top row can change between runs.

   ```bash
   make who-shares
   ```

2. **Show the entity:** Open the Aura Query tab for the NAMS graph database. Paste this query, and replace `<id>` with the id from the last step.

   ```cypher
   MATCH p=(e:Entity {id:'<id>'})-[:EXTRACTED_FROM]->(:Message)<-[:HAS_MESSAGE]-(:Conversation)
   RETURN p
   ```

   The Graph view shows one entity in the center, with a message on each `EXTRACTED_FROM` arrow and a conversation behind each message.

3. **Show the analysts:** In the results overview, click the Conversation chip and set its caption to `userId`. Each conversation node now shows its analyst id. One entity spans many people.

4. **Say this:** "The conversation history belongs to one analyst. This entity graph belongs to the team. Nobody queried for it. It fell out of storing conversations."

5. **Use a backup if the Graph view fails:** This waits for extraction and writes every entity and relationship to `snapshot.json`.

   ```bash
   uv run ontology/measure_ingestion.py snapshot --label demo --out snapshot.json
   ```

## Part 2: show the agent using the graph

This part shows the agent answering a new analyst with another analyst's findings.

1. **Get the app URL:** This saves the deployed app's URL in `APP_URL`.

   ```bash
   export APP_URL=$(databricks apps get agent-bricks-neo4j-graph-agent -p "$DATABRICKS_CONFIG_PROFILE" -o json | jq -r .url)
   ```

2. **Run turn 1 as analyst A:** This asks "I am investigating Community 3040..." as analyst A. Then it waits until NAMS has extracted the entities from this turn. Extraction takes seconds to minutes, so for a talk, run this step before you go on stage.

   ```bash
   uv run scripts/demo_longterm.py --turn 1 --app-url "$APP_URL" --profile "$DATABRICKS_CONFIG_PROFILE"
   ```

3. **Run turn 2 as analyst B:** This asks "What is already known about Community 3040?" as analyst B in a new session. Run this step live.

   ```bash
   uv run scripts/demo_longterm.py --turn 2 --analyst-b demo-analyst-b-1 --app-url "$APP_URL" --profile "$DATABRICKS_CONFIG_PROFILE"
   ```

4. **Point out the findings:** The second answer opens with findings from earlier investigations. These include the case that investigated Community 3040, its rank among ring candidates, its member count, and its average risk score. Analyst B shares no session and no conversation history with analyst A. Those facts came from the entity graph.

5. **Keep re-runs clean:** Each run gets new session ids. On the next run, change the `--analyst-b` value, for example to `demo-analyst-b-2`. Analyst B then has no earlier demo turns of their own to recall.

## How recall works

The recall code is in `agent/nams.py`.

- **Finds terms:** `extract_entity_terms` pulls terms such as "Community 3040" out of the prompt. NAMS entity search matches keywords, so a full sentence returns nothing. Short terms keep the search precise.
- **Searches the graph:** `_recall_entities` searches each term and keeps up to five entities. One name can match many entities, and each one holds a different finding in its description. So it dedupes by description, and it skips entities without one. It puts first the descriptions that name a value beyond the entity's own id, such as "126 members" or "CASE-4001". Descriptions that only restate the entity come last.
- **Tells the agent:** The entities join the agent's instructions under the header "Entities known from earlier investigations by any analyst". The instructions tell the agent to treat memory as data and to verify facts against the graph.
- **Degrades safely:** A failed entity search returns the conversation recall alone. A failed NAMS returns no memory, and the agent still answers.

## Limits

- **Keyword search:** Entity recall needs an entity name in the prompt, such as "Community 3040". A prompt without a name gets conversation recall only.
- **Duplicate entities:** Extraction merges some mentions of an entity and leaves others as separate nodes. After `make traffic`, 9 to 12 nodes are named Community 3040, and the count changes between runs. Usually one of them holds about six messages from three or four analysts, and each of the others holds one message. A run with only two turns, such as `demo_longterm.py` on an empty NAMS, produced no merged entity at all. Use `make who-shares` to find the merged entity instead of searching by name.
- **Async extraction:** A turn's entities appear after extraction finishes. The demo script waits for this.
- **NAMS scope:** On NAMS, long-term memory is the entity graph. Preferences and facts need the self-hosted Neo4j backend.
