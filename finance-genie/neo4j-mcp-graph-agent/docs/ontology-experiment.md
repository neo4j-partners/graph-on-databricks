# Run the ontology example

NAMS reads each stored conversation and extracts entities from the text. An ontology tells the extractor what to look for. This page loads the ontology that ships in this repo and then measures what it changes with a before and after run.

You need these before you start:

- **A deployed app:** The app must be deployed with the NAMS key attached, and `DATABRICKS_CONFIG_PROFILE` and `APP_URL` must be set in your shell.
- **NAMS workspaces:** The `MEMORY_API_KEY` selects the NAMS workspace. The before and after run needs empty workspaces, as the steps below explain.
- **Working directory:** Run every command from `neo4j-mcp-graph-agent/`. All three scripts take `MEMORY_API_KEY` from your shell or from `.env`.

## What the ontology is

The ontology has 11 entity types and 15 relationships. The types are Analyst, Team, InvestigationFocus, Account, Customer, Merchant, Community, IdentityCluster, PhoneNumber, Address, and Case.

The ontology is not the fraud graph schema. NAMS extracts entities from the conversation text, so the ontology describes what analysts talk about. Analyst covers managers too, because analysts name the person they report to.

The ontology runs in permissive validation. It guides extraction and does not reject anything.

## The files

- `ontology/finance_genie.ontology.yaml` is the ontology itself.
- `ontology/apply_ontology.py` validates the ontology and loads it into NAMS.
- `ontology/measure_ingestion.py` reads a NAMS workspace and computes quality metrics. It only reads.
- `ontology/replay_transcripts.py` exports the stored conversations from one workspace and writes them unchanged into another.

## Load the ontology

```bash
uv run ontology/apply_ontology.py                      # dry run, no network, validates locally
uv run ontology/apply_ontology.py --create             # load it in permissive mode
uv run ontology/apply_ontology.py --create --activate  # load it and make it the active ontology
uv run ontology/apply_ontology.py --update <ontology id>   # load the YAML as a new revision
uv run ontology/apply_ontology.py --rollback <version id>
```

Or run `make apply-ontology` for the `--create --activate` line.

- **Dry run:** The default run makes no network calls. It prints the types and relationships and checks them locally.
- **`--create`:** This flag loads the ontology with validation mode `permissive`. Afterward the script reads the version back and prints what the service dropped.
- **`--update`:** This flag loads the YAML as a new revision. It never edits an existing version.
- **`--activate`:** This flag makes the version active. Before it activates, the script prints the currently active version id and saves that id to `ontology/previous_active_<UTC timestamp>.json`. If no ontology is active, it records `none`.
- **`--rollback <version id>`:** This flag reactivates an earlier version. Use an id from a `previous_active_*.json` file. There is no way to unbind an ontology, so a rollback to `none` fails.

The hosted API spec does not model `aliases` on entity types, so the service may silently ignore the four Team aliases. The dry run prints a warning, and the read-back after `--create` shows what survived. The Team description also lists the aliases as a fallback. The `description` fields are accepted.

## Run the before and after comparison

Entities in NAMS are not scoped by run, so each snapshot needs its own empty NAMS workspace. A live agent also gives a different answer each time, and extraction is LLM based. If you ran live traffic on both sides, you could not tell the effect of the ontology from the agent's own variation.

So this comparison runs the agent once and replays the stored conversations into each workspace. Then the ontology and the extraction are the only things that change.

1. **Smoke test:** Ask the deployed app one question, "Which community is Account 15940 in?". The answer should name Community 19766. In NAMS, check for one conversation with two messages and one trace, and check that extraction has finished. Or run `make smoke QUESTION="Which community is Account 15940 in?"`.
2. **Run live once:** Point `MEMORY_API_KEY` at an empty workspace A with the default ontology active. Run the traffic from `traffic/`. The run sends 24 turns. It needs 6 users, because users 1 and 6 investigate the same community, Community 3040, from different teams. That shows one entity shared across analysts. Your user must be trusted before the deploy, as step 7 of [Quick start with make](../README.md#quick-start-with-make) explains. Otherwise all 24 turns land under your own user.

   ```bash
   cd traffic
   uv sync
   uv run agent-traffic --profile "$DATABRICKS_CONFIG_PROFILE" --app-url "$APP_URL" \
     --users 6 --sessions-per-user 2 --turns-per-session 2
   cd ..
   ```

   Or run `make traffic` from `neo4j-mcp-graph-agent/`. Its default size is this same 6, 2, and 2 run.

3. **Save the transcripts:** This reads the 24 conversations and fails if the count is wrong.

   ```bash
   uv run ontology/replay_transcripts.py export --out transcripts.json --expect-turns 24
   ```

   Or run `make export`.

4. **Replay into the default side:** Point `MEMORY_API_KEY` at an empty workspace with the default ontology active. Replay the transcripts, then snapshot. Do this in two separate empty workspaces, so you get `before-1.json` and `before-2.json`.

   ```bash
   uv run ontology/replay_transcripts.py replay transcripts.json --execute --wait
   uv run ontology/measure_ingestion.py snapshot --label before-1 --out before-1.json \
     --ontology-yaml ontology/finance_genie.ontology.yaml --expect-turns 24
   ```

   Or run `make replay`, then `make snapshot LABEL=before-1`. Use `LABEL=before-2` in the second workspace.

5. **Replay into the ontology side:** Point `MEMORY_API_KEY` at another empty workspace. Load the ontology, then replay and snapshot as in step 4. Do this in two workspaces, so you get `after-1.json` and `after-2.json`.

   ```bash
   uv run ontology/apply_ontology.py --create --activate
   uv run ontology/replay_transcripts.py replay transcripts.json --execute --wait
   uv run ontology/measure_ingestion.py snapshot --label after-1 --out after-1.json \
     --ontology-yaml ontology/finance_genie.ontology.yaml --expect-turns 24
   ```

   Or run `make apply-ontology`, `make replay`, and then `make snapshot LABEL=after-1`. Use `LABEL=after-2` in the second workspace.

6. **Compare:** The `--users`, `--sessions`, and `--turns` flags give the run size and add the ground-truth rows.

   ```bash
   uv run ontology/measure_ingestion.py compare before-1.json after-1.json \
     --users 6 --sessions 2 --turns 2
   ```

   Or run `make compare`. Set `BEFORE=` and `AFTER=` to compare other snapshot files.

The difference between `before-1` and `before-2`, and between `after-1` and `after-2`, is the noise floor. Treat a change smaller than that as noise.

If you can only use one workspace, reset it between snapshots. The reset path is not confirmed. Check the `ontology_version_id` that each snapshot records, because a reset might keep the active ontology. The second "before" would then use the custom one.

## Other commands

- **`gold`:** `uv run ontology/measure_ingestion.py gold --snapshot after-1.json --users 6 --sessions 2 --turns 2` scores one snapshot on its own.
- **`recompute`:** `uv run ontology/measure_ingestion.py recompute before-1.json --out before-1.new.json` redoes the metrics from the saved entities and relationships, with no network.
- **`--expect-turns`:** This check fails with exit code 3 if a conversation, message, or trace is missing. The app does not fail a turn when a NAMS write fails, so a run can store fewer turns than it sent. A turn where the agent made no tool call has no trace steps, so it also trips the trace check. Use `--allow-incomplete` to override the check.

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

- **Results vary:** Extraction is LLM based, so two replays of the same side differ. The second workspace on each side shows the spread.
- **No proof of cause:** The comparison shows what changed. It does not prove the ontology caused the change.
- **Replay limits:** A replay writes the same message text and trace steps, but with new timestamps. NAMS does not store the trace task or outcome, so they are not replayed.
- **Snapshot contents:** The snapshot and transcript files hold entity names and conversation text from synthetic analysts.
