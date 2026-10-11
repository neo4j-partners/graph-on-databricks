# Ontology and demo end-to-end test plan

This plan tests the new `apply_ontology.py --reset`, `ontology/set_baseline.py`, `scripts/demo.py`, the new Makefile targets, and the restructured README. It runs local first, then cloud. Run every command from `neo4j-mcp-graph-agent/`.

Started: 2026-10-11. Update the checkboxes and the audit log as each step finishes.

## How to read this file

- **Status list:** Each step has a checkbox. `[x]` means done and passed. `[ ]` means not done. `[!]` means it ran and failed, with a note.
- **Who:** `Claude` runs the step. `You` is a step only you can do, such as resetting the NAMS database in the console.
- **Audit log:** The last section holds one summary line per major step, newest at the bottom.

## Status

### Phase 0: preflight

- [x] Claude: Confirm `.env` has `DATABRICKS_CONFIG_PROFILE` and `MEMORY_API_KEY`, the CLIs exist, and port 8000 is free.
- [x] Claude: Move the old run files from `ontology/out/` into `ontology/out/old-run/`.
- [x] Claude: Run the unit tests (`test_ontology_apply.py`, `test_set_baseline.py`, `test_demo_script.py`). 64 passed.

### Phase 1: local

Setup and the quick start
- [x] You: Reset the NAMS database in the console (done before this run).
- [x] Claude: `make reset-ontology` activates the plain NAMS Default.
- [x] Claude: `make baseline BASELINE=default` reports "already active" and changes nothing.
- [x] Claude: `make baseline BASELINE=none` fails with exit 3 while an ontology is active.
- [x] Claude: `make dev` starts the server on :8000.
- [x] Claude: `make smoke-local` returns an answer.

Demo script
- [x] Claude: `uv run scripts/demo.py` runs steps 1 to 5 locally.
- [x] Claude: `uv run scripts/demo.py --step ring` runs the ring question.
- [ ] You: Check the MLflow spans by hand (`read_neo4j_cypher`, `genie_ask`, `genie_query_result`).
- [ ] You: Open https://memory.neo4jlabs.com/ and confirm each demo question appears as a conversation.

Reset before the ontology example
- [x] You: Reset the NAMS database again. `demo.py` wrote conversations into it, and the ontology example counts every stored conversation.
- [ ] Claude: `make reset-ontology` and `make baseline BASELINE=default` leave the default active.

Ontology example, trial 1 (default baseline)
- [!] Claude: Run traffic against the local server. The client ran fine locally with no profile (24 ok, 0 failed), but NAMS stored only 16 of 24 conversations. See the audit log. Rerun needed.
- [ ] Claude: `make export` saves 24 turns.
- [ ] Claude: `make snapshot LABEL=before-1` records the NAMS Default version.

Ontology example, trial 2 (finance ontology)
- [ ] You: Reset the NAMS database between the trials.
- [ ] Claude: `make apply-ontology` creates and activates the finance ontology.
- [ ] Claude: `make replay` writes the 24 turns back.
- [ ] Claude: `make snapshot LABEL=after-1` records the finance version.
- [ ] Claude: `make compare` shows two different ontology versions and the expected direction of change.

Hybrid baseline
- [ ] Claude: `make baseline BASELINE=hybrid` creates a new revision of the system `nams-default` and activates it. This adds a revision to a system ontology, so run it once.
- [ ] Claude: `make baseline BASELINE=hybrid` a second time reuses that revision and creates nothing.
- [ ] Claude: `make reset-ontology` skips the hybrid revision and activates plain revision 3.

Long-term memory demo
- [ ] Claude: `make apply-ontology` (Tier 1 step 1), then local traffic.
- [ ] You: Find Community 3040 in the NAMS console and check that its provenance lists two analysts.
- [ ] Claude: `uv run scripts/demo_longterm.py` prints analyst B's answer with analyst A's findings.

Clean up
- [ ] Claude: README Clean up step 4 (`--reset`) returns the default.
- [ ] Claude: README Clean up step 5 clears `ontology/out/*.json`.
- [ ] Claude: Stop the local server.

### Phase 2: cloud

Starts only after you reset the NAMS database again.

- [ ] You: Reset the NAMS database.
- [ ] Claude: `make reset-ontology`, then confirm the default is active.
- [ ] Claude: `make secrets`.
- [ ] Claude: `make deploy` prints `APP_URL`.
- [ ] Claude: `make grant-genie`.
- [ ] Claude: `make smoke` returns an answer.
- [ ] Claude: `uv run scripts/demo.py --cloud` runs steps 1 to 5.
- [ ] Claude: `uv run scripts/demo.py --cloud --step ring`.
- [ ] You: Reset the NAMS database before the ontology example.
- [ ] Claude: Trial 1 with `make traffic`, `make export`, `make snapshot LABEL=before-1`.
- [ ] You: Reset the NAMS database between the trials.
- [ ] Claude: Trial 2 with `make apply-ontology`, `make replay`, `make snapshot LABEL=after-1`, `make compare`.
- [ ] Claude: `uv run scripts/demo_longterm.py --app-url "$APP_URL" --profile "$DATABRICKS_CONFIG_PROFILE"`.
- [ ] Claude: README Clean up steps 4 and 5. Do not run step 1 (delete the app) unless you say so.

## What else needs testing

- **Local traffic:** Whether `agent-traffic` works against `http://localhost:8000`. If it does not, the docs must say the ontology example needs the cloud app.
- **Hybrid on a system ontology:** The hybrid adds a revision to the system `nams-default`. Check that the revision does not break other users of the workspace and that `--reset` still finds the plain revision.
- **`--baseline none`:** Only the failure path is tested. The success path needs a workspace that never activated an ontology, which this workspace is not.
- **Copy-paste of the doc commands:** Run each raw command in `docs/ontology-experiment.md` as written, not only the `make` wrapper, because the two can drift.
- **README links:** Check every in-page anchor after the section move, and the anchors that other docs use (`#quick-start-cloud-with-make`, `#quick-start-with-make`).
- **Error paths:** `make dev` with no `.env`, `demo.py` with the server down, `demo.py --cloud` without a profile, and `set_baseline.py` without `MEMORY_API_KEY`.
- **`--reset` output:** It prints the whole finance ontology summary before it acts. Decide whether to quiet it.
- **Trusted callers:** Whether `MEMORY_TRUSTED_CALLERS` makes the traffic land under six analyst ids in the cloud, and one user when it is not set.
- **Deploy from a clean app:** The first-deploy path that attaches `nams-api-key` and deploys twice.
- **Run-to-run noise:** Extraction is LLM based. If a result looks wrong, repeat one side (`before-2`) before blaming the code.

## Audit log

- **2026-10-11, preflight:** `.env` has both variables, all CLIs present, port 8000 free. Old run files moved to `ontology/out/old-run/`. 64 unit tests pass.
- **2026-10-11, local reset:** `make reset-ontology` replaced the finance ontology (`ov_a2184a75281d`) with NAMS Default revision 3 (`ov_345ad0e8d72a`). It saved the rollback file. NAMS entity search returned nothing, so the database was empty. Finding: the command prints the whole finance ontology summary first.
- **2026-10-11, baseline targets:** `BASELINE=default` was a no-op because the default was already active. `BASELINE=none` failed with exit 3 and the "cannot unbind" message, as designed.
- **2026-10-11, local server:** `make dev` started on :8000. `make smoke-local` returned a graph-backed answer about `SIMILAR_TO`.
- **2026-10-11, demo script:** `uv run scripts/demo.py` ran steps 1 to 5 locally. Step 1 named Accounts 368, 927, 1033, 1696 and Community 8174. Step 2 named Community 19766. Step 3 recalled Account 15940 in a new session. Step 4 returned the Genie balance table. Step 5 combined graph and Genie. The ring question and the MLflow span checks are not done. These runs wrote conversations into NAMS, so the NAMS database needs a reset before the ontology example.
- **2026-10-11, ring question:** `demo.py --step ring` named Community 3040 with size 126, average risk 2.72, and about 90% internal transfers. The local server stays up for the next phase.
- **2026-10-11, trial 1 traffic, first attempt:** The NAMS reset was done and the default ontology was active. `agent-traffic --app-url http://localhost:8000` ran 24 turns, ok=24 failed=0 in 151s. This answers the open question: the traffic client works against a local server without a Databricks profile. `make export` and `make snapshot LABEL=before-1` then refused to write, because NAMS held 16 conversations, not 24. The server log shows 8 turns hit `NAMS GET /v1/conversations 424 external_database_error` during the connect probe, so the agent continued without memory and did not store them. The traffic client reports those turns as ok, so only the export and snapshot count checks caught the loss. The cause is on the hosted NAMS side and not in the changed files. Nothing was written to `ontology/out/`. Next: reset NAMS and rerun the traffic at lower concurrency.
