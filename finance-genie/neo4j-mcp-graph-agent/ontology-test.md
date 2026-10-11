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
- [x] Claude: `make reset-ontology` and `make baseline BASELINE=default` leave the default active.

Ontology example, trial 1 (default baseline)
- [x] Claude: Run traffic against the local server. The fourth attempt stored 24 of 24 conversations with no connect failures. Attempts 1 to 3 lost turns, see the audit log.
- [x] Claude: `make export` saves 24 turns.
- [x] Claude: `make snapshot LABEL=before-1` records the NAMS Default version. Saved `ontology/out/before-1.json`, conformance 0.0% (0/355).

Ontology example, trial 2 (finance ontology)
- [x] You: Reset the NAMS database between the trials.
- [x] Claude: `make apply-ontology` creates and activates the finance ontology. The first try failed with 409 because the NAMS reset keeps ontologies. `apply_ontology.py --create` now falls back to adding a revision. Live run added revision 4 (`ov_602c9c3f3425`) and activated it.
- [x] Claude: `make replay` writes the 24 turns back. Wrote 24 conversations, 48 messages, 28 steps, 28 tool calls.
- [x] Claude: `make snapshot LABEL=after-1` records the finance version (revision 2, `ov_db0ef7bb9529`).
- [x] Claude: `make compare` shows two different ontology versions and the expected direction of change. Conformance 0 to 100%, Object/Concept 183 to 0.

Hybrid baseline
- [x] Dropped. It failed live with 403 (system ontologies are immutable), so you chose to remove it. `set_baseline.py` now takes `default` or `none`.

Long-term memory demo
- [x] Claude: `make apply-ontology` (Tier 1 step 1), then local traffic. The finance ontology was already active from trial 2. Run `lt2` stored 24 of 24.
- [ ] You: Find Community 3040 in the NAMS console and check that its provenance lists two analysts.
- [x] Claude: `uv run scripts/demo_longterm.py --analyst-b demo-analyst-b-t1` prints analyst B's answer with analyst A's findings. Exit 0.

Clean up
- [x] Claude: README Clean up step 4 (`--reset`) returns the default. Activated `ov_345ad0e8d72a`.
- [ ] Claude: README Clean up step 5 clears `ontology/out/*.json`. Held back so the cloud trial can be compared with the local snapshots.
- [x] Claude: Stop the local server.

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
- **2026-10-11, trial 1 traffic, second attempt (`--concurrency 3`):** Lower concurrency did not avoid the NAMS error. The run finished ok=22 failed=1 skipped=1 in 387s, 11 turns ran without memory (424 `external_database_error` on the connect probe), and NAMS held 20 conversations. The 424s are scattered through the run, not one burst. A direct burst of 36 parallel `GET /v1/conversations` calls all returned 200, so the error is intermittent and could not be reproduced outside the agent. The one failed turn was `ModelBehaviorError: Model did not produce a final response!`, an LLM failure unrelated to NAMS.
- **2026-10-11, silent-loss fix:** The SDK retries only 429 and 5xx, so a 424 on the connect probe made the agent skip memory for that turn and never store it. `agent/nams.py` `TurnMemory.__aenter__` now tries the connect up to 3 times with a 1s then 2s backoff, using a fresh client each time. If all three fail it still continues without memory, as before. Two tests were added to `tests/test_nams.py`. 42 tests pass. The dev server was restarted to load the change. The fix is not yet proven live. The third traffic attempt will show whether the 424s still cost turns.
- **2026-10-11, trial 1 traffic, third attempt (3-attempt retry, default concurrency):** ok=24 failed=0 in 183s, but NAMS held 20 conversations and `make export` refused. The log shows 14 connect failures and 4 turns that gave up after all three attempts. The retry recovered only 2 turns. Failures cluster in the first wave of concurrent turns: the same four turns failed attempt 1, 2 and 3, while two later turns failed once and recovered. The 3 second backoff window is too short for the first wave.
- **2026-10-11, retry tuning:** `CONNECT_ATTEMPTS` raised from 3 to 5, so the backoff is 1, 2, 4 and 8 seconds, about 15 seconds in total. The give-up test now uses `nams.CONNECT_ATTEMPTS`. 42 tests pass. The dev server was restarted. NAMS holds 20 stale conversations, so it needs a reset before the next traffic run.
- **2026-10-11, retry values changed again:** hthz read the project-nams source (`nams-424.md`). A 424 means a database-side failure on an external workspace, with no retry in the NAMS request path and no fix on any branch. hthz recommended 3 attempts with waits of about 0.5 and 1 seconds plus jitter, and a readiness check after a reset. `CONNECT_ATTEMPTS` is now 3 and `CONNECT_RETRY_SECONDS` is 0.5, with jitter. Reason: a real outage should cost about 2 seconds, not about 60.
- **2026-10-11, traffic client fix:** `agent-traffic` now reports and fails on lost data. It waits until NAMS answers 200 twice before sending turns. After the run it counts the stored conversations per run session and compares them with the completed turns. It prints every failed turn and every turn NAMS did not store. Exit code 1 means a turn failed or was skipped. Exit code 2 means NAMS stored fewer turns than completed, or was not ready. The check needs `MEMORY_API_KEY` in the environment or `.env`, and `--no-verify-nams` turns it off for jobs with no key. 35 traffic tests pass. This also catches a write failure after a successful connect, which the connect retry does not cover.
- **2026-10-11, trial 1 traffic, fourth attempt:** NAMS reset, then `agent-traffic` (old client, new 5-attempt retry) finished ok=24 failed=0 in 154s. NAMS held 24 conversations, 2 per session across 12 sessions, with no connect failures. `make export` saved 24 conversations, 48 messages, 28 steps, 28 tool calls. Open items from hthz: the connect failure counts in the earlier attempts do not reconcile with the stored counts (run 2 logged 11 connect failures but 4 turns went missing), and snapshots do not record the git commit, so the code under test changed during trial 1.
- **2026-10-11, trial 1 complete:** `make snapshot LABEL=before-1` saved `ontology/out/before-1.json` after extraction finished: 355 entities, 0 of 355 conform to the finance types (NAMS Default types Object, Person, Organization, Concept, Event dominate). The stored-count check paged correctly against the live API with a page size of 5 (24 conversations, 12 sessions). Caveat from hthz: none of this code is committed, and the retry changed during trial 1, so commit before trial 2 so both trials run on the same code.
- **2026-10-11, trial 2 start (code committed as `0254207`):** `make apply-ontology` exited 3 with `409 ontology with this name already exists in workspace`, because the console reset clears conversations and entities but keeps ontologies, so `finance-genie-fraud-memory` (`ont_c383f6622e01`) still existed. The make target printed the validation text and the rollback line and nothing about the 409, because the filtered make output hid the error line. I did not check the active ontology before starting the replay, so `make replay` wrote 11 conversations while the NAMS Default was still active, and I stopped it. I then ran `--update ont_c383f6622e01 --activate`, which created revision 2 (`ov_db0ef7bb9529`) and activated it. A second `make replay` refused: 11 replayed session ids already exist with the `-r1` suffix. NAMS needs another reset before trial 2 can run. Lesson: confirm `GET /v1/ontologies/active` names the finance ontology before the replay.
- **2026-10-11, trial 2 replay and compare:** After another NAMS reset, `make apply-ontology` hit the 409 again. `apply_ontology.py --create` now looks up the existing ontology by `domain.id` and adds a revision, with three new tests (58 pass with the baseline tests). The live run added revision 4 (`ov_602c9c3f3425`) and activated it. I confirmed the active ontology before `make replay`, which wrote 24 conversations, 48 messages, 28 steps and 28 tool calls. `make compare` of `before-1` (NAMS Default `ov_345ad0e8d72a`) with `after-1` (Finance Genie Fraud Memory revision 2, `ov_db0ef7bb9529`): total entities 355 to 288, generic Object/Concept 183 to 0 (share 0.515 to 0), duplicate groups 77 to 72, duplicate excess 169 to 138, type conflicts 6 to 2, conformance 0 to 100% (288 of 288). Instance counts (account 64, community 12, identity_cluster 1, phone 2, case 6) and gold recall are unchanged. Typed relationships MEMBER_OF, REPORTS_TO, OWNS and INVESTIGATES increased.
- **2026-10-11, new traffic client, live:** Run `lt1` failed 4 turns with "agent invocation failed". The server log showed `No MCP server connected: TimeoutError()` on a stale server. The client reported each failed turn and exited 1. After a clean `make dev`, run `lt2` finished ok=24 failed=0 in 147s and printed "NAMS stored 24 of 24 completed turn(s)". Minor oddity: a turn interrupted with "stopped" is counted as failed.
- **2026-10-11, hybrid baseline:** `make baseline BASELINE=hybrid` fails live with 403 "system ontologies are immutable; clone to edit", because it PUTs a revision to the system `nams-default`. The unit tests do not catch it because the fake client allows the PUT. Open: decide between cloning the ontology (if the API supports it), dropping the hybrid baseline, or changing the docs. No fix made.
- **2026-10-11, long-term demo (local):** `uv run scripts/demo_longterm.py --analyst-b demo-analyst-b-t1` exited 0. Analyst B's answer recalled analyst A's work on Community 3040, including the comparison with Community 24683 and the stats (126 members, average risk 2.72, highest risk 3.80 for Account 7890).
- **2026-10-11, local clean up:** `apply_ontology.py --reset` activated plain NAMS Default revision 3. The local server on :8000 is stopped. `ontology/out/*.json` is kept for now. NAMS holds the `lt2` traffic, the trial 2 replay and the demo conversations, so it needs a reset before Phase 2.
- **2026-10-11, hybrid baseline dropped:** Removed `--baseline hybrid`, `merge_finance_into_default`, `set_hybrid`, the two hybrid tests and the doc references (`docs/ontology-experiment.md`, `docs/reference.md`, `README.md`, Makefile comment, `apply_ontology.py` docstrings). The `--reset` logic that picks the newest revision with no finance types is unchanged. 313 tests pass.
