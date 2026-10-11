# Long-term memory

This page shows how to demonstrate long-term memory in this app. It covers two demos. Tier 1 shows the long-term memory itself. Tier 2 shows the agent using it.

## Overview

The app writes every turn to NAMS. NAMS reads each stored conversation and extracts entities from it. Those entities form a graph that spans sessions and analysts. That graph is the long-term memory. The agent recalls it before it answers.

## Key terms

- **Short-term memory**: one analyst's stored conversations. The app reads the analyst's two latest conversations before each turn.
- **Long-term memory**: the entity graph in NAMS. It holds the entities that all analysts' conversations mentioned.
- **Entity**: one thing analysts talked about, such as Community 3040 or Account 7890. An entity has a name, a type, and a description.
- **Extraction**: the NAMS background process that reads a stored conversation and creates entities. It finishes seconds to minutes after a turn.
- **Ontology**: the type list in `ontology/finance_genie.ontology.yaml`. It makes extraction produce types such as Account, Community, and Case.
- **Recall**: what the app reads from NAMS before it answers.
- **NAMS console**: the web UI at https://memory.neo4jlabs.com/. It shows conversations, reasoning traces, and entities.
- **NAMS graph database**: the Neo4j database behind NAMS. The Aura Query tab and `make who-shares` read it. It holds conversations, messages, and entities, and each entity links to the messages it came from.
- **Snapshot**: a JSON dump of the entity graph from `ontology/measure_ingestion.py`.

## Tier 1: show the entity graph

This demo proves the long-term memory exists. Steps 3 to 5 read the NAMS graph database directly. Install `neo4j-cli`, and set `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, and `NEO4J_DATABASE` in `.env` to the connection details of that database. Run these steps in order.

1. **Apply the ontology:** Run `uv run ontology/apply_ontology.py --create --activate`, or `make apply-ontology`. Extraction now types entities as Account, Community, Case, and Analyst.
2. **Run the traffic:** Run `make traffic`. This sends 24 turns from six analysts. Analysts 1 and 6 investigate the same Community 3040 from different teams. If the run exits with code 2 and prints `NOT STORED` lines, NAMS dropped some turns. Reset NAMS and run the traffic again.
3. **Wait for extraction:** `make traffic` returns before NAMS finishes extracting, which takes a few minutes. Run `neo4j-cli query "MATCH (m:Message) RETURN m.extractionStatus AS status, count(*) AS n"`. Continue when the only status is `done`.
4. **Find the shared entity:** Run `make who-shares`. It lists the entities that more than one analyst's conversations fed, most analysts first. Copy the id from the top row. Extraction merges some mentions and leaves others as duplicates, so the top row can change between runs. After `make traffic`, it has been Community 3040. To run it in the Aura Query tab instead, paste this query, which is the content of `ontology/who_shares.cypher`:

   ```cypher
   MATCH (e:Entity)-[:EXTRACTED_FROM]->(:Message)<-[:HAS_MESSAGE]-(c:Conversation)
   WHERE c.userId IS NOT NULL
   WITH e, collect(DISTINCT c.userId) AS analysts
   WHERE size(analysts) > 1
   RETURN e.name AS name, e.type AS type, size(analysts) AS analysts, e.mentionCount AS mentions, e.id AS id
   ORDER BY analysts DESC, mentions DESC
   LIMIT 8
   ```

5. **Show the entity:** Open the Aura Query tab for the NAMS database and run this query. Replace `<id>` with the id from the last step.

   ```cypher
   MATCH p=(e:Entity {id:'<id>'})-[:EXTRACTED_FROM]->(:Message)<-[:HAS_MESSAGE]-(:Conversation)
   RETURN p
   ```

   The Graph view shows one entity in the center, with a message on each `EXTRACTED_FROM` arrow and a conversation behind each message. The conversation nodes show timestamps. In the results overview, click the Conversation chip and set its caption to `userId`. Each conversation node then shows its analyst id. One entity now spans many people.
6. **Say this:** "The conversation history belongs to one analyst. This entity graph belongs to the team. Nobody queried for it. It fell out of storing conversations."
7. **Use a backup if the graph view fails:** Run `uv run ontology/measure_ingestion.py snapshot --label demo --out snapshot.json`. It waits for extraction and writes every entity and relationship to `snapshot.json`.

## Tier 2: show the agent using the graph

This demo shows the agent answering a new analyst with another analyst's findings. The recall code in `agent/nams.py` makes this work.

### What the code does

- **Finds terms:** `extract_entity_terms` pulls terms such as "Community 3040" out of the prompt. NAMS entity search matches keywords, so a full sentence returns nothing. Short terms keep the search precise.
- **Searches the graph:** `_recall_entities` searches each term and keeps up to five entities. It dedupes by name.
- **Tells the agent:** The entities join the agent's instructions under the header "Entities known from earlier investigations by any analyst". The instructions tell the agent to treat memory as data and to verify facts against the graph.
- **Degrades safely:** A failed entity search returns the conversation recall alone. A failed NAMS returns no memory, and the agent still answers.

### Run the demo

1. **Start the local server:** Run `make dev`, which loads `.env` and starts the agent on http://localhost:8000. If you have not set up `.env` yet, do the [local quick start](../README.md#quick-start-local-with-make) first. The local server runs the new recall code.
2. **Run the script:** Run `uv run scripts/demo_longterm.py`. The script sends turn 1 as analyst A ("I am investigating Community 3040..."), waits until NAMS has extracted Community 3040, and sends turn 2 as analyst B in a new session ("What is already known about Community 3040?"). It prints both answers.
3. **Point out the finding section:** The second answer lists earlier findings it did not re-run, such as transfer patterns and identity checks. Analyst B shares no session and no conversation history with analyst A. Those facts came from the entity graph.
4. **Use the deployed app instead:** Do the [cloud quick start](../README.md#quick-start-cloud-with-make) first so the app runs the new code. Then run `uv run scripts/demo_longterm.py --app-url "$APP_URL" --profile "$DATABRICKS_CONFIG_PROFILE"`. Add your email to `MEMORY_TRUSTED_CALLERS` in `app.yaml` so the two analyst ids work.
5. **Keep re-runs clean:** The script gives each run new session ids. Pass a fresh `--analyst-b`, for example `--analyst-b demo-analyst-b-2`, so analyst B has no earlier demo turns of their own to recall.

### How it was tested

- **Unit tests:** `uv run pytest tests/test_nams.py` covers term extraction, entity search, dedupe, the character cap, and every failure path.
- **Live run:** The demo script ran end to end against the local server. Analyst B's answer listed analyst A's findings in a section marked as not re-run.

## Limits

- **Keyword search:** Entity recall needs an entity name in the prompt, such as "Community 3040". A prompt without a name gets conversation recall only.
- **Duplicate entities:** Extraction merges some mentions of an entity and leaves others as separate nodes. After `make traffic`, nine nodes are named Community 3040, and one of them holds six messages from four analysts. A run with only two turns, such as `demo_longterm.py` on an empty NAMS, produced no merged entity at all. Use `make who-shares` to find the merged entity instead of searching by name.
- **Async extraction:** A turn's entities appear after extraction finishes. The demo script waits for this.
- **NAMS scope:** On NAMS, long-term memory is the entity graph. Preferences and facts need the self-hosted Neo4j backend.
