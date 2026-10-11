# Run the ontology example

NAMS reads each stored conversation and extracts entities from the text. An ontology tells the extractor what to look for. This page runs the same conversations through NAMS twice, each time with a different ontology active, and then compares what NAMS stored. As run for the snapshots discussed here, trial 1 had the generic NAMS Default ontology active and trial 2 had only the finance ontology. The comparison is generic default versus finance-only, not no ontology versus ontology, because resetting the database does not unbind the active ontology. [Choose the trial 1 baseline](#choose-the-trial-1-baseline) shows how to run the other baselines, including a hybrid of the default plus the finance types.

You need these before you start:

- **The quick start:** Run [Quick start with make](../README.md#quick-start-with-make) first. Its first step creates `.env`, sets `DATABRICKS_CONFIG_PROFILE` and `MEMORY_API_KEY`, and loads both into your shell. Its deploy step deploys the app with the NAMS key attached.
- **The app URL:** The raw traffic command below also needs `APP_URL` in your shell. `make deploy` prints it but does not export it, so set it after the deploy. Or skip this and run `make traffic`, which looks up `APP_URL` on its own.

  ```bash
  export APP_URL=$(databricks apps get agent-bricks-neo4j-graph-agent \
    -p "$DATABRICKS_CONFIG_PROFILE" -o json | jq -r .url)
  ```

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
- `ontology/out/` holds the generated transcripts, snapshots, and rollback files. It is git ignored, and the scripts create it when needed.

## Understand how the ontology drives the schema

Without an ontology, NAMS picks entity types on its own. With one, NAMS types entities from the list you gave it. The experiment shows that difference on identical conversations. The NAMS Default ontology sits between those two extremes: its types are generic (Person, Organization, Location, Event, Object, and a few software types), so it guides extraction toward generic buckets instead of domain types.

An agent gives a different answer each time and extraction is LLM based. So the experiment runs the agent live once, in trial 1. Trial 2 replays the stored conversations from trial 1. Then the ontology and the extraction are the only things that change between the trials.

### Choose the trial 1 baseline

Trial 1 can run against three baselines. Pick one before you start, and confirm which one ran from the `ontology_version_id` and `ontology_name` in the trial 1 snapshot.

- **The generic default (as run):** Reset the database and leave it alone. The reset clears entities but does not unbind the active ontology, so the NAMS Default ontology stays active and its generic types guide extraction. The saved `before-1.json` records the NAMS Default version, which is how we know this is the baseline that ran.
- **No ontology:** Only possible on a workspace where no version has ever been activated. The API has no way to unbind the active ontology, so once any version is active you cannot get back to this baseline. The snapshot records `ontology_version_id: none`.
- **Hybrid:** The finance types merged into the NAMS Default ontology, loaded as a new revision of the default. This mirrors how a team adopts an ontology without giving up the generic types, and it measures what the generic buckets cost when domain types are also available.

To build the hybrid baseline, run these commands while the NAMS Default ontology is the active one. If the finance ontology is currently active, first restore the default with `uv run ontology/apply_ontology.py --rollback <version id>`, using the id saved in the newest `ontology/out/previous_active_*.json` file.

```bash
source .env
ENDPOINT=${MEMORY_ENDPOINT:-https://memory.neo4jlabs.com}

# Find the active default ontology and download its document.
curl -sS -H "Authorization: Bearer $MEMORY_API_KEY" \
  "$ENDPOINT/v1/ontologies/active" -o ontology/out/active.json
ONT_ID=$(python3 -c "import json; print(json.load(open('ontology/out/active.json'))['version']['ontology_id'])")
REV=$(python3 -c "import json; print(json.load(open('ontology/out/active.json'))['version']['revision'])")
curl -sS -H "Authorization: Bearer $MEMORY_API_KEY" \
  "$ENDPOINT/v1/ontologies/$ONT_ID/versions/$REV" -o ontology/out/default_version.json

# Append the finance types and relationships to the default document.
uv run --with pyyaml python - <<'EOF'
import json

import yaml

record = json.load(open("ontology/out/default_version.json"))
merged = json.loads(record["version"]["schema_json"])
finance = yaml.safe_load(open("ontology/finance_genie.ontology.yaml"))

labels = {e["label"] for e in merged["entity_types"]}
merged["entity_types"] += [
    e for e in finance["entity_types"] if e["label"] not in labels
]
triples = {
    (r["type"], r["source"], r["target"]) for r in merged.get("relationships", [])
}
merged.setdefault("relationships", [])
merged["relationships"] += [
    r
    for r in finance.get("relationships", [])
    if (r["type"], r["source"], r["target"]) not in triples
]
with open("ontology/out/hybrid.ontology.yaml", "w") as fh:
    yaml.safe_dump(merged, fh, sort_keys=False)
EOF

# Load the merged document as a new revision of the default and activate it.
uv run ontology/apply_ontology.py --update "$ONT_ID" \
  --yaml ontology/out/hybrid.ontology.yaml --activate
```

The merged document keeps the default's domain and generic types and adds the 11 finance types and 15 relationships, and it passes the script's local validation. To return to the plain default afterwards, roll back to the version id in the `previous_active_*.json` file that the activation saved.

### Set up

1. **Check the app:** Ask the deployed app one question, "Which community is Account 15940 in?". The answer should name Community 19766. Or run `make smoke QUESTION="Which community is Account 15940 in?"`.
2. **Start empty:** Reset the NAMS database so it holds no conversations. The reset does not unbind the active ontology; that is what makes the baseline the generic default. The smoke test stored a conversation, and the export below counts every stored conversation, so the count check would fail without the reset.

### Trial 1: the baseline

Run trial 1 with the baseline you chose above. As run, this was the generic default: the reset cleared the entities but left the NAMS Default ontology active, so NAMS typed entities with the generic types. Step 3 records which version actually ran.

1. **Run the traffic:** The run sends 24 turns. It needs 6 users, because users 1 and 6 investigate the same community, Community 3040, from different teams. That shows one entity shared across analysts. Your user must be trusted before the deploy, as step 7 of [Quick start cloud with make](../README.md#quick-start-cloud-with-make) explains. Otherwise all 24 turns land under your own user.

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
   uv run ontology/replay_transcripts.py export --out ontology/out/transcripts.json \
     --expect-turns 24
   ```

   Or run `make export`.

3. **Snapshot:** Run the snapshot. It waits for extraction by default, polling NAMS every 10 seconds and printing `extraction: N message(s) open`. When it reaches 0 open messages, it writes `ontology/out/before-1.json`. If it times out after 900 seconds, rerun it with a larger `--wait-timeout`.

   ```bash
   uv run ontology/measure_ingestion.py snapshot --label before-1 \
     --out ontology/out/before-1.json \
     --ontology-yaml ontology/finance_genie.ontology.yaml --expect-turns 24
   ```

   Or run `make snapshot LABEL=before-1`. The snapshot records the active baseline ontology version: the NAMS Default version as run, the hybrid revision, or `none` for the no-ontology baseline. The `ontology_name` field says which it was.

### Trial 2: with the finance-only ontology

1. **Reset the database:** Reset the NAMS database again so the entities from trial 1 are gone. Entities are not scoped by run, so without the reset the second snapshot would count both trials.
2. **Load the ontology:** This creates a new standalone ontology with only the 11 finance types and activates it, replacing the baseline. It loads in permissive mode.

   ```bash
   uv run ontology/apply_ontology.py --create --activate
   ```

   Or run `make apply-ontology`. The next section lists the other flags.

3. **Replay the conversations:** This writes the trial 1 conversations into NAMS unchanged, so the extractor now runs with the ontology.

   ```bash
   uv run ontology/replay_transcripts.py replay ontology/out/transcripts.json \
     --execute --wait
   ```

   Or run `make replay`.

4. **Snapshot:** Save the metrics as `ontology/out/after-1.json`.

   ```bash
   uv run ontology/measure_ingestion.py snapshot --label after-1 \
     --out ontology/out/after-1.json \
     --ontology-yaml ontology/finance_genie.ontology.yaml --expect-turns 24
   ```

   Or run `make snapshot LABEL=after-1`. The snapshot should record the version id that step 2 activated.

### Compare the results

Run `compare` on the two snapshot files. The `--users`, `--sessions`, and `--turns` flags give the run size and add the ground-truth rows.

```bash
uv run ontology/measure_ingestion.py compare \
  ontology/out/before-1.json ontology/out/after-1.json \
  --users 6 --sessions 2 --turns 2
```

Or run `make compare`. Set `BEFORE=` and `AFTER=` to compare other snapshot files.

The output starts with the ontology line for each snapshot. Check that `before` records the baseline you chose (the NAMS Default version as run, the hybrid revision, or none) and `after` names the finance ontology and its version. The two versions must differ. If they are the same, trial 2 did not activate the finance ontology and the comparison is invalid.

Then read the table. Each row shows the before value, the after value, the delta, and the direction of the change. These rows are where an effect of the ontology shows:

- **Generic-bucket share:** The share of entities typed `Object` or `Concept` should fall. The extractor now has better types to use.
- **Type conflicts and duplicates:** Both should fall. The ontology gives one type per kind of thing and names the team aliases.
- **Noise:** The count of tool and schema plumbing entities should fall.
- **Instance coverage:** The count of entities such as "Community 3040" and "CASE-4001" should rise.
- **Ontology conformance:** The share of entities with a declared type should rise.
- **Ground truth:** Recall, type accuracy, alias resolution, and the stored relationships should improve. The next section explains each row.

To see the entities themselves, run `uv run ontology/measure_ingestion.py gold --snapshot ontology/out/before-1.json --users 6 --sessions 2 --turns 2` and the same for `ontology/out/after-1.json`. Or open the two snapshot files and compare the `by type` lists.

To measure the noise floor, repeat one side. Reset the database, set the state for that side, replay, and snapshot as `before-2` or `after-2`. The difference between `before-1` and `before-2` is how much the same input varies. Treat a change between the sides that is smaller than that as noise.

### Expected results

These expectations come from one run of the generic default against the finance-only ontology. Extraction is LLM based, so your numbers will differ. The direction of the main rows should hold.

- **Generic types disappear:** The generic count falls to 0. In the reference run it went from 173 to 0, and the share from 0.534 to 0. Conformance rises from 0 to about 0.997.
- **Type conflicts fall:** The reference run went from 20 to 1.
- **Typed relationships improve:** The four relationship rows `MEMBER_OF`, `REPORTS_TO`, `OWNS`, and `INVESTIGATES` reach 1 under `gold rel typed`. In the reference run they started at 0 or 0.333.
- **Type accuracy rises:** The reference run went from 0.714 to 1.
- **Recall stays at 1:** Both sides find every analyst, manager, team, case, community, account, and phone the traffic mentions. The ontology changes how entities are typed, not whether they are found.
- **Instance coverage is unchanged:** Both sides store the same accounts, communities, identity clusters, phones, and cases. The reference run had 68, 12, 1, 2, and 6.
- **Noise is 0 on both sides:** The reference run shows no tool or schema plumbing entities in either snapshot.
- **Total entities may move either way:** The reference run went from 324 to 309. Do not read much into a change of this size.
- **Duplicates may not improve:** The reference run went from 64 to 71 duplicate groups, and from 132 to 162 excess entities. A repeat of one side shows whether that change is noise.
- **Alias resolution may stay at 0:** The service may ignore the Team aliases, as the note under [Other commands](#other-commands) explains. The reference run scored 0 on both sides.

The ontology line at the top of the `compare` output must show two different version ids. If it does not, trial 2 did not activate the finance ontology.

The reference `after-1` snapshot holds 26 conversations instead of 24, because two smoke-test questions were asked after the reset and before the replay. It was taken with `--allow-incomplete`. Those turns can only add to the count rows. Your own run should pass the `--expect-turns 24` check.

## Other commands

- **`gold`:** `uv run ontology/measure_ingestion.py gold --snapshot ontology/out/after-1.json --users 6 --sessions 2 --turns 2` scores one snapshot on its own.
- **`recompute`:** `uv run ontology/measure_ingestion.py recompute ontology/out/before-1.json --out ontology/out/before-1.new.json` redoes the metrics from the saved entities and relationships, with no network.
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
- **`--activate`:** This flag makes the version active. Before it activates, the script prints the currently active version id and saves that id to `ontology/out/previous_active_<UTC timestamp>.json`. If no ontology is active, it records `none`.
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

- **Reset keeps the ontology:** This page does not say how to reset a NAMS database, but the reset used here cleared entities without unbinding the active ontology: trial 1 ran with the NAMS Default still active, and the before-1 snapshot records its version. There is no API to unbind, so the no-ontology baseline is only possible on a workspace where no version was ever activated. Check the `ontology_version_id` that each snapshot records.
- **Snapshot type map:** A snapshot's `ontology_type_poles` merges the active ontology's types with the types from the `--ontology-yaml` file, so `before-1.json` lists the finance types even though the active ontology did not declare them. `ontology_name` and `ontology_domain_id` show what was actually active.
- **Results vary:** Extraction is LLM based, so two replays of the same side differ. A repeat of one side shows the spread.
- **Live versus replay:** Trial 1 stores the live run and trial 2 stores a replay of it. A replay writes the same message text and trace steps, but with new timestamps. NAMS does not store the trace task or outcome, so they are not replayed.
- **No proof of cause:** The comparison shows what changed. It does not prove the ontology caused the change.
- **Snapshot contents:** The snapshot and transcript files hold entity names and conversation text from synthetic analysts.
