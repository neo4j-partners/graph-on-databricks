# Run the ontology example

NAMS reads each stored conversation and extracts entities from the text. An ontology tells the extractor what to look for. This page runs the same conversations through NAMS twice, first without the ontology and then with the one that ships in this repo. Then it compares what NAMS stored.

You need these before you start:

- **A deployed app:** The app must be deployed with the NAMS key attached, and `DATABRICKS_CONFIG_PROFILE` and `APP_URL` must be set in your shell.
- **A NAMS database you can reset:** The experiment resets the database once between the two trials. Use a database that holds nothing you want to keep.
- **Working directory:** Run every command from `neo4j-mcp-graph-agent/`. All three scripts take `MEMORY_API_KEY` from your shell or from `.env`.

## What the ontology is

The ontology has 11 entity types and 15 relationships. The types are Analyst, Team, InvestigationFocus, Account, Customer, Merchant, Community, IdentityCluster, PhoneNumber, Address, and Case.

The ontology is not the fraud graph schema. NAMS extracts entities from the conversation text, so the ontology describes what analysts talk about. Analyst covers managers too, because analysts name the person they report to.

The ontology runs in permissive validation. It guides extraction and does not reject anything.

## The files

- `ontology/finance_genie.ontology.yaml` is the ontology itself.
- `ontology/apply_ontology.py` validates the ontology and loads it into NAMS.
- `ontology/measure_ingestion.py` reads a NAMS database and computes quality metrics. It only reads.
- `ontology/replay_transcripts.py` exports the stored conversations and writes them unchanged back into NAMS.

## Understand how the ontology drives the schema

Without an ontology, NAMS picks entity types on its own. With one, NAMS types entities from the list you gave it. The experiment shows that difference on identical conversations.

An agent gives a different answer each time and extraction is LLM based. So the experiment runs the agent live once, in trial 1. Trial 2 replays the stored conversations from trial 1. Then the ontology and the extraction are the only things that change between the trials.

### Set up

1. **Check the app:** Ask the deployed app one question, "Which community is Account 15940 in?". The answer should name Community 19766. Or run `make smoke QUESTION="Which community is Account 15940 in?"`.
2. **Start empty:** Reset the NAMS database so it holds no conversations and no active ontology. The smoke test stored a conversation, and the export below counts every stored conversation, so the count check would fail without the reset.

### Trial 1: without the ontology

No ontology is active, so NAMS chooses the entity types.

1. **Run the traffic:** The run sends 24 turns. It needs 6 users, because users 1 and 6 investigate the same community, Community 3040, from different teams. That shows one entity shared across analysts. Your user must be trusted before the deploy, as step 7 of [Quick start with make](../README.md#quick-start-with-make) explains. Otherwise all 24 turns land under your own user.

   ```bash
   cd traffic
   uv sync
   uv run agent-traffic --profile "$DATABRICKS_CONFIG_PROFILE" --app-url "$APP_URL" \
     --users 6 --sessions-per-user 2 --turns-per-session 2
   cd ..
   ```

   Or run `make traffic` from `neo4j-mcp-graph-agent/`. Its default size is this same 6, 2, and 2 run.

2. **Save the transcripts:** This reads the 24 conversations and fails if the count is wrong. Trial 2 replays this file.

   ```bash
   uv run ontology/replay_transcripts.py export --out transcripts.json --expect-turns 24
   ```

   Or run `make export`.

3. **Snapshot:** Wait for extraction to finish, then save the metrics as `before-1.json`.

   ```bash
   uv run ontology/measure_ingestion.py snapshot --label before-1 --out before-1.json \
     --ontology-yaml ontology/finance_genie.ontology.yaml --expect-turns 24
   ```

   Or run `make snapshot LABEL=before-1`. The snapshot should record no active ontology version.

### Trial 2: with the ontology

1. **Reset the database:** Reset the NAMS database again so the entities from trial 1 are gone. Entities are not scoped by run, so without the reset the second snapshot would count both trials.
2. **Load the ontology:** This loads it in permissive mode and makes it the active ontology.

   ```bash
   uv run ontology/apply_ontology.py --create --activate
   ```

   Or run `make apply-ontology`. The next section lists the other flags.

3. **Replay the conversations:** This writes the trial 1 conversations into NAMS unchanged, so the extractor now runs with the ontology.

   ```bash
   uv run ontology/replay_transcripts.py replay transcripts.json --execute --wait
   ```

   Or run `make replay`.

4. **Snapshot:** Save the metrics as `after-1.json`.

   ```bash
   uv run ontology/measure_ingestion.py snapshot --label after-1 --out after-1.json \
     --ontology-yaml ontology/finance_genie.ontology.yaml --expect-turns 24
   ```

   Or run `make snapshot LABEL=after-1`. The snapshot should record the version id that step 2 activated.

### Compare the results

Run `compare` on the two snapshot files. The `--users`, `--sessions`, and `--turns` flags give the run size and add the ground-truth rows.

```bash
uv run ontology/measure_ingestion.py compare before-1.json after-1.json \
  --users 6 --sessions 2 --turns 2
```

Or run `make compare`. Set `BEFORE=` and `AFTER=` to compare other snapshot files.

The output starts with the ontology line for each snapshot. Check that `before` says "no active ontology version" and `after` names the ontology and its version. If both snapshots show the same version, the reset did not clear the ontology and the comparison is invalid.

Then read the table. Each row shows the before value, the after value, the delta, and the direction of the change. These rows are where an effect of the ontology shows:

- **Generic-bucket share:** The share of entities typed `Object` or `Concept` should fall. The extractor now has better types to use.
- **Type conflicts and duplicates:** Both should fall. The ontology gives one type per kind of thing and names the team aliases.
- **Noise:** The count of tool and schema plumbing entities should fall.
- **Instance coverage:** The count of entities such as "Community 3040" and "CASE-4001" should rise.
- **Ontology conformance:** The share of entities with a declared type should rise.
- **Ground truth:** Recall, type accuracy, alias resolution, and the stored relationships should improve. The next section explains each row.

To see the entities themselves, run `uv run ontology/measure_ingestion.py gold --snapshot before-1.json --users 6 --sessions 2 --turns 2` and the same for `after-1.json`. Or open the two snapshot files and compare the `by type` lists.

To measure the noise floor, repeat one side. Reset the database, set the state for that side, replay, and snapshot as `before-2` or `after-2`. The difference between `before-1` and `before-2` is how much the same input varies. Treat a change between the sides that is smaller than that as noise.

## Other commands

- **`gold`:** `uv run ontology/measure_ingestion.py gold --snapshot after-1.json --users 6 --sessions 2 --turns 2` scores one snapshot on its own.
- **`recompute`:** `uv run ontology/measure_ingestion.py recompute before-1.json --out before-1.new.json` redoes the metrics from the saved entities and relationships, with no network.
- **`--expect-turns`:** This check fails with exit code 3 if a conversation, message, or trace is missing. The app does not fail a turn when a NAMS write fails, so a run can store fewer turns than it sent. A turn where the agent made no tool call has no trace steps, so it also trips the trace check. Use `--allow-incomplete` to override the check.

`apply_ontology.py` takes these flags:

```bash
uv run ontology/apply_ontology.py                      # dry run, no network, validates locally
uv run ontology/apply_ontology.py --create             # load it in permissive mode
uv run ontology/apply_ontology.py --create --activate  # load it and make it the active ontology
uv run ontology/apply_ontology.py --update <ontology id>   # load the YAML as a new revision
uv run ontology/apply_ontology.py --rollback <version id>
```

- **Dry run:** The default run makes no network calls. It prints the types and relationships and checks them locally.
- **`--create`:** This flag loads the ontology with validation mode `permissive`. Afterward the script reads the version back and prints what the service dropped.
- **`--update`:** This flag loads the YAML as a new revision. It never edits an existing version.
- **`--activate`:** This flag makes the version active. Before it activates, the script prints the currently active version id and saves that id to `ontology/previous_active_<UTC timestamp>.json`. If no ontology is active, it records `none`.
- **`--rollback <version id>`:** This flag reactivates an earlier version. Use an id from a `previous_active_*.json` file. There is no way to unbind an ontology, so a rollback to `none` fails.

The hosted API spec does not model `aliases` on entity types, so the service may silently ignore the four Team aliases. The dry run prints a warning, and the read-back after `--create` shows what survived. The Team description also lists the aliases as a fallback. The `description` fields are accepted.

## What the metrics mean

- **Generic-bucket share:** This is the share of entities typed `Object` or `Concept`. A high share means the extractor had no better type to use.
- **Duplicate surface forms:** These are the same entity written several ways. They are counted by exact type and by pole type, such as person or organization. The custom types Analyst and Customer both count as person.
- **Type conflicts:** These are the same name stored under several types.
- **Noise:** This counts entities that are tool or schema plumbing, such as MCP tool names and words like "schema" or "table".
- **Instance coverage:** This counts the entities for specific instances that reached memory, such as "Community 3040" or "CASE-4001". It covers Account, Community, identity cluster, phone, and case instances.
- **Ontology conformance:** This is the share of entities whose type the ontology declares.
- **Ground truth:** The traffic knows every analyst, manager, team, case, community, account, phone, and merchant it mentions. The `gold` rows show recall and type accuracy. They also show whether the analyst's first name, "D. Reyes" style name, and team abbreviation resolve to one entity. They show whether the relationships MEMBER_OF, REPORTS_TO, OWNS, and INVESTIGATES were stored. Relationships come from `GET /v1/entities/graph`, which is capped at 1000 nodes.
- **Ontology version:** Each snapshot records the active ontology version id. `compare` warns if both snapshots used the same version.

## An earlier baseline for context

An earlier run had no ontology, used older traffic, and ran against an agent with an empty graph. It produced 388 entities, 67.3% generic, 25 type conflicts, 40.2% noise, and 0 instances. This is context and not a comparison, because the traffic and the agent have changed since.

## Caveats

- **Reset is not confirmed here:** This page does not say how to reset a NAMS database. Check the `ontology_version_id` that each snapshot records. A reset might keep the active ontology, in which case trial 1 would run with it. A reset might also clear the ontology, in which case step 2 of trial 2 is what turns it on.
- **Results vary:** Extraction is LLM based, so two replays of the same side differ. A repeat of one side shows the spread.
- **Live versus replay:** Trial 1 stores the live run and trial 2 stores a replay of it. A replay writes the same message text and trace steps, but with new timestamps. NAMS does not store the trace task or outcome, so they are not replayed.
- **No proof of cause:** The comparison shows what changed. It does not prove the ontology caused the change.
- **Snapshot contents:** The snapshot and transcript files hold entity names and conversation text from synthetic analysts.
