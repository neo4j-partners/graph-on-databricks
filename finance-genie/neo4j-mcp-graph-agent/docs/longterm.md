# Long-term memory

This page shows how to demonstrate long-term memory in this app. It covers two demos. Tier 1 shows the long-term memory itself. Tier 2 shows the agent using it.

## Overview

The app writes every turn to NAMS. NAMS reads each stored conversation and extracts entities from it. Those entities form a graph that spans sessions and analysts. That graph is the long-term memory. The agent recalls it before it answers.

## Key terms

- **Short-term memory**: one analyst's stored conversations. The app reads the analyst's two latest conversations before each turn.
- **Long-term memory**: the entity graph in NAMS. It holds what all analysts' conversations mentioned, merged by entity.
- **Entity**: one thing analysts talked about, such as Community 3040 or Account 7890. An entity has a name, a type, and a description.
- **Extraction**: the NAMS background process that reads a stored conversation and creates entities. It finishes seconds to minutes after a turn.
- **Ontology**: the type list in `ontology/finance_genie.ontology.yaml`. It makes extraction produce types such as Account, Community, and Case.
- **Recall**: what the app reads from NAMS before it answers.
- **NAMS console**: the web UI at https://memory.neo4jlabs.com/. It shows conversations, reasoning traces, and entities.
- **Snapshot**: a JSON dump of the entity graph from `ontology/measure_ingestion.py`.

## Tier 1: show the entity graph

This demo proves the long-term memory exists. Run these steps in order.

1. **Apply the ontology:** Run `uv run ontology/apply_ontology.py --create --activate`, or `make apply-ontology`. Extraction now types entities as Account, Community, Case, and Analyst.
2. **Run the traffic:** Run `make traffic`. This sends 24 turns from six analysts. Analysts 1 and 6 investigate the same Community 3040 from different teams. If the run exits with code 2 and prints `NOT STORED` lines, NAMS dropped some turns. Reset NAMS and run the traffic again.
3. **Open the NAMS console:** Go to https://memory.neo4jlabs.com/ and search for 3040. The search returns about ten nodes named Community 3040, because extraction merges some mentions and leaves others as duplicates. Open the Community node with the most source messages. Show its type, its description, and its relationships. Open its provenance. The provenance lists source messages from several analysts. One entity now spans many people.
4. **Say this:** "The conversation history belongs to one analyst. This entity graph belongs to the team. Nobody queried for it. It fell out of storing conversations."
5. **Use a backup if the console fails:** Run `uv run ontology/measure_ingestion.py snapshot --label demo --out snapshot.json`. It waits for extraction and writes every entity and relationship to `snapshot.json`.

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
- **Async extraction:** A turn's entities appear after extraction finishes. The demo script waits for this.
- **NAMS scope:** On NAMS, long-term memory is the entity graph. Preferences and facts need the self-hosted Neo4j backend.
