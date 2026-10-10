# fz plan: neo4j-mcp-graph-agent

This file holds the high-level goal, the plan, the current status, and an audit log for the work coordinated by fz, the principal engineer session. Ryan owns the decisions. dbz and zzz implement.

## Goal

Show the community that Databricks agents, Genie, Neo4j, and Neo4j Agent Memory are better together.

- **Databricks Agent Bricks:** Agent Bricks hosts the agent. It provides durable serving, session history, MLflow tracing, and Unity Catalog governance for every tool.
- **Neo4j through a Unity Catalog MCP service:** The graph answers relationship questions, such as rings, hubs, shared phones, and lookalike accounts.
- **Genie:** Genie answers table questions over the lakehouse Gold tables, such as totals by customer, region, or period. The graph answers how things connect, and Genie answers how much and how many across the business. This piece is proposed and not built yet.
- **Neo4j Agent Memory (NAMS):** NAMS remembers each analyst across sessions and extracts the entities they talk about into a graph.

## Design principles

The demo is for the community, so simplicity wins over completeness.

1. A reader should understand the agent by reading `agent/` and `runtime/` in one sitting.
2. A reader should go from clone to a working deployed agent with a short list of commands.
3. Experiments, such as the ontology before-and-after run, live beside the core agent and never complicate it.
4. Security fixes stay in, because people copy demos into production. Each one must be small, in one place, and clearly commented.
5. Docs lead with the story and the quick start. Deep detail moves to `docs/`.
6. Nobody predicts what an LLM will answer. Demo checks look for grounded evidence, such as named ids that exist in the graph, not for exact answer text.

## Workstreams

| Id | Item | Owner | Status |
| --- | --- | --- | --- |
| A | Bind the memory user to the signed-in caller, so a request cannot read another analyst's memory | dbz | Done and reviewed |
| B | Tighten the read-only Cypher check and report what the MCP server enforces | dbz | Done and reviewed |
| C | Make recall reliably return the newest turns, and read them in parallel | zzz | Done and reviewed |
| D | Make Claude 5 models stream, then remove the Claude 4.5 pin | zzz | Done and reviewed |
| E | Add an opt-in check for drift between the prompt and scenarios and the live graph | zzz | Done and reviewed |
| E2 | Fix the prompt schema: the live relationships hold amounts and timestamps, but the prompt says they do not | zzz | Done and reviewed |
| F | Strip Cypher from the tool-call arguments stored in NAMS traces | zzz | Done and reviewed |
| I | In the MCP server fork, pass `routing_` and reject schema writes. Code and tests only, no rebuild | dbz | Done and reviewed, uncommitted in the fork |
| J | Rebuild the MCP server once: read-only Aura user, the fork fix, and a record of the deployed image | azz | Planning, needs fz approval before any change |
| K | Fix the README inconsistencies in place, such as the three different names for the NAMS key steps | zzz | Done and reviewed |
| L | Trust Ryan's Databricks user in MEMORY_TRUSTED_CALLERS, and fix the README laptop-traffic steps | dbz | Assigned |
| M | Split the README into a short front door, a demo script, and docs/ | zzz | Outline first |
| N | Write docs/mcp-service.md on how to create the UC MCP service | dbz | Assigned after L |
| G | Review all diffs, run the tests, and commit | fz | Done |
| H | Deploy, smoke test, and run the ontology before-and-after experiment | fz | Waiting on J and on Ryan's traffic identity ruling |

## Proposed additions, waiting on Ryan

1. **Add Genie as a tool:** Bind the existing AFTER Genie space with `agentbricks tools add genie-agent <space_id>`. This is one line in `agent.toml`, and it completes the story. The agent sends structure questions to the graph and value questions to Genie. The prompt needs a short routing rule, and the evaluation needs one question that uses both.
2. **Shorten the front door:** The README is about 650 lines. Cut it to the story, the architecture picture, a short quick start, and a demo script. Move memory internals, the ontology experiment, the traffic job, and troubleshooting into `docs/`.
3. **One-command targets:** Add `make deploy`, `make smoke`, `make traffic`, and `make experiment`. Also find out whether the NAMS key resource can be declared in config, which would remove the manual attach step after the first deploy.
4. **A demo script:** Write four or five questions. Each one shows one piece: graph, Genie, memory recall in a new session, and the ontology effect. For each question, say what evidence to look for.

## MCP server read-only findings, waiting on Ryan

The Neo4j MCP server is built from the mcp-neo4j fork and deployed from the aws-starter repo. Both live outside this project, so nothing here changes them.

- **Wrong transaction mode:** The server passes `routing_control=RoutingControl.READ`, but the driver keyword is `routing_`. The value becomes a query parameter, and every read runs as a WRITE transaction. fz confirmed this in the fork's source.
- **Gap in the server's write check:** The server rejects a query only when its EXPLAIN query type contains "w". Schema writes report "s", so `CREATE INDEX` and `CREATE CONSTRAINT` pass the server. The agent guardrail blocks them.
- **Admin user:** The server signs in as the Aura `neo4j` admin user. That instance is the same one the finance-genie pipeline writes to.
- **Unknown image version:** No record shows which fork commit is deployed.

Recommended, in order. Ryan approved 2 and 3 on 2026-10-10. Item 1 moved to `future-improvements.md`.

1. Create a read-only Aura user with the built-in reader role, and point the MCP server at it. First confirm that the Aura tier supports database users. Also confirm whether a runtime env change keeps the gateway id. A new gateway id means running the connection update in the README troubleshooting section.
2. In the fork, pass `routing_=RoutingControl.READ` and block query type "s". Ship this with the next planned server rebuild.
3. Record the deployed image SHA in the README troubleshooting section.

## Live run plan (item H)

Ryan approved this on 2026-10-10.

1. Check with read-only calls which NAMS workspace each key points at, which ontology is active, and whether the workspace is empty.
2. Deploy, then confirm that the `nams-api-key` resource is attached.
3. Smoke test. Ask "Which community is Account 15940 in?" The answer should name Community 19766. NAMS should show one conversation with two messages and one trace. The app logs should show the bound principal.
4. Run one live traffic run with 6 users, 2 sessions each, and 2 turns per session. Then export the 24 turns.
5. Replay the turns twice into empty workspaces on the default ontology, and snapshot each.
6. Activate the ontology in two empty workspaces, replay twice, and snapshot each.
7. Compare the results. Report the spread within each side as the noise floor.
8. Answer the open questions below along the way.

## Open questions to settle during the live run

- Does a NAMS reset also clear the ontology binding?
- Does `GET /v1/ontologies/active` return a version object on a fresh workspace?
- Does NAMS accept one relationship type between several pairs of entity types?
- Do the Team aliases survive the upload?
- Does `get_context` return extracted entities?
- Does NAMS extract entities from reasoning traces?
- What does the Apps proxy put in the `X-Forwarded-*` headers for a service principal?

## Decisions

| Date | Decision | By |
| --- | --- | --- |
| 2026-10-10 | Approve the deploy and the ontology before-and-after run | Ryan |
| 2026-10-10 | Strip Cypher from trace tool-call arguments stored in NAMS | Ryan |
| 2026-10-10 | Commit the work with no co-author line | Ryan |
| 2026-10-10 | Simplicity is the key constraint, because this is a community demo | Ryan |
| 2026-10-10 | Fix the fork's `routing_` keyword and schema-write check, and record the deployed image digest. The read-only Aura user goes to `future-improvements.md` | Ryan |
| 2026-10-10 | A request with no input binds the caller's own identity, because the route defaults input to [] and the session id is client-chosen | fz |
| 2026-10-10 | Implement the read-only Aura user now, with azz, the AWS specialist | Ryan |
| 2026-10-10 | All requests go through fz, and fz coordinates all work | Ryan |
| 2026-10-10 | Read-only role: try an Aura-managed role (A), and keep the admin user (D) if that fails | Ryan |
| 2026-10-10 | Fix laptop traffic by trusting Ryan's Databricks user email in MEMORY_TRUSTED_CALLERS | Ryan |
| 2026-10-10 | Split the README into a short front door plus docs/, and write an MCP service setup doc | Ryan |
| 2026-10-10 | Bind the memory user with middleware that writes it into the persisted invocation input | fz |
| 2026-10-10 | Reject a deployed request that has no forwarded identity with a 401 | fz |
| 2026-10-10 | Document, but do not fix, unnamespaced invocation reads in Agent Bricks | fz |
| 2026-10-10 | Use the Responses API instead of chat completions, which works on Claude 4.5 and 5 with no model-specific settings | fz |
| 2026-10-10 | Keep the drift check as one opt-in script in `scripts/`, with offline unit tests | fz |

## Audit log

- **2026-10-10, fz:** fz read the README, the config, and the agent, guardrail, memory, prompt, and runtime code. fz listed five review findings.
- **2026-10-10, fz:** fz split the work. dbz took A and B. zzz took C, D, and E. Neither may commit, deploy, rebuild the MCP server, write to NAMS, or change grants without going through fz.
- **2026-10-10, fz:** fz checked zam's review against HEAD. Items 1 to 12 were already fixed. Nothing was left to implement. zam stood down.
- **2026-10-10, fz:** fz approved dbz's identity design with four rulings and added logging and test requirements.
- **2026-10-10, fz:** zam handed off before shutdown. zam made no edits and ran nothing live. The open questions moved into this plan.
- **2026-10-10, fz:** Ryan approved the deploy, the experiment, Cypher stripping, and the commit. fz wrote this plan and assigned F to zzz.
- **2026-10-10, fz:** zzz reported findings. NAMS lists conversations newest first. Claude 5 fails only on the model call after a tool result, because AI Gateway streams reasoning as a list. The Responses API fixes it on both model families. The live graph has amount and timestamp properties on TRANSFERRED_TO and TRANSACTED_WITH, which the prompt says do not exist. fz approved C, D, and E, and assigned the prompt fix E2 and the Cypher strip F to zzz.
- **2026-10-10, fz:** Observation for later: the live graph also holds Policy and BusinessTerm labels from another demo. The agent sees them in the schema. Decide whether this demo should use its own database.
- **2026-10-10, fz:** dbz finished A and B. The suite had 266 passing and 1 failing test. The failure is an old test in zzz's file that the identity change replaced by design. fz reviewed the identity middleware and asked for one fix: do not create an input when the request has none. fz asked dbz to drop the redundant APOC pattern and block RENAME. fz routed the old test to zzz for deletion.
- **2026-10-10, fz:** fz confirmed dbz's MCP server findings in the fork's source and found the schema-write gap. All server fixes are outside this project and go to Ryan.
- **2026-10-10, fz:** Housekeeping: `mlflow.db` is tracked in git although `.gitignore` lists it. Local runs modify it. It will not be committed. Untracking it needs Ryan's OK.
- **2026-10-10, fz:** dbz pushed back on the identity fix, and dbz was right. The route defaults a missing input to [], so skipping the bind would let a client-chosen session id pick the memory user. fz kept the current behavior. dbz added a comment and a test, removed the redundant APOC and CALL subquery patterns, and blocked RENAME. The suite had 269 passing and 1 failing test. The failure is the old test zzz is deleting.
- **2026-10-10, fz:** Ryan approved the fork fix and the image digest record. fz assigned both to dbz as I and J. The fork change is code and tests only, with no commit, rebuild, or deploy. fz wrote `future-improvements.md` with the read-only Aura user plan.
- **2026-10-10, fz:** Ryan approved untracking `mlflow.db`. fz ran `git rm --cached`, and the file stays on disk. Correction: the earlier entry said `.gitignore` lists the file, but no ignore rule covers it, so it now shows as untracked. `.agentbricks/mlflow.db` and `.agentbricks/mlflow-server.log` are also tracked. Adding ignore rules waits on Ryan.
- **2026-10-10, fz:** dbz finished I in the fork. The read and schema tools now pass `routing_`, and the write check rejects query types containing "w" or "s". A new unit test covers the query types, and the fork's 58 unit tests pass. fz reviewed the diff. Nothing in the fork is committed, built, or deployed. J is blocked: the AWS SSO token has expired, and only Ryan can log in again.
- **2026-10-10, fz:** zzz finished C, D, E, E2, and F. Recall reads conversations in parallel and documents the newest-first order. The agent uses the Responses API, and the Claude 4.5 pin is gone. `scripts/check_drift.py` passed all 11 checks live. The prompt schema lists the relationship amounts and timestamps. Cypher tool calls go to NAMS without the query. `agent-evaluate` passed on claude-sonnet-5-5. fz reviewed every diff. The agent suite has 273 passing tests, and the traffic suite has 21. fz committed the work with no co-author line.
- **2026-10-10, fz:** Ryan asked for a more readable README and for its inconsistencies fixed. fz gave zzz the in-place fixes as K. A restructure into a short README plus `docs/` waits on Ryan.
- **2026-10-10, fz:** Ryan approved the read-only Aura user now. fz briefed azz to plan one rebuild with the reader user, dbz's fork fix, and the image record. azz must send the plan before changing anything. J moved from dbz to azz.
- **2026-10-10, fz:** fz found a regression from A. A laptop traffic run calls the app with the runner's own token, and that runner is not a trusted caller. So every synthetic analyst's turn is saved under the runner's email. The quick start and the ontology live run both use the laptop path. The fix is a design choice, so it went to Ryan.
- **2026-10-10, fz:** Ryan ruled that all requests go through fz. fz told dbz, zzz, and azz.
- **2026-10-10, fz:** azz reported. On Ryan's direct instruction, azz created the Aura user `mcp_reader` with the built-in `reader` role. Its password is in a gitignored file. Reads work and writes are forbidden. But Aura Professional also forbids `apoc.meta.schema` and `db.schema.*` for `reader`, so `get_neo4j_schema` would break. Custom roles need Business Critical. azz's options: A, an Aura-internal role; B, a schema fallback in the fork that uses plain Cypher; C, upgrade the tier; D, stay on the admin user. fz recommends B and took the choice to Ryan. The rebuild changes only the Runtime, so the gateway and the UC connection should survive. azz will confirm with `cdk diff` first.
- **2026-10-10, fz:** zzz finished K. The README now has one set of NAMS key steps, one install step, one heading style, identity-aware flows, real sample ids, and a full table of contents. The prerequisite TODO for the MCP service creation doc stays, because no such doc exists in the repo. fz reviewed and committed it. The traffic lines that A broke stay unchanged until Ryan rules.
- **2026-10-10, fz:** Ryan ruled: role option A, then D; laptop traffic trusts his Databricks user; split the README; write the MCP service doc. Ryan logged in to AWS. fz assigned L and N to dbz, and the M outline to zzz. The auto mode classifier blocked fz's go message to azz for the Aura and AWS changes, so Ryan's direct instruction to azz stands.
- **2026-10-10, fz:** dbz finished the README part of L: a new deploy step 3 that trusts your user, the log check in step 8, and pointers from the ontology run, the laptop run, and the Job steps. fz reviewed it, and pytest gives 273 passed. The permission classifier blocked dbz's one-line `app.yaml` edit, so it went to Ryan. L is not committed yet.
- **2026-10-10, fz:** azz ran test A, and it passed. `mcp_reader` has `reader` plus the Aura-managed role `graphql_app_read_only_decff32a`. Reads and the schema procedures work. Every write probe is forbidden, including APOC creates, and nothing persisted. Caveat: the managed role is instance-specific and Aura may change it, so verification stays in the runbook. fz told azz to commit the fork fix and to run up to the `cdk diff` gate. The deploy go waits on Ryan.
- **2026-10-10, fz:** zzz pulled the Q1 ids live with a read-only query. Phone 312-555-0142 is shared by customers 368, 927, 1033, and 1696, and their accounts are all in Community 8174. Whether to add these ids to the drift check is new scope, so it went to Ryan.
- **2026-10-10, fz:** dbz finished N: `docs/mcp-service.md` covers the server deploy, the UC connection built with jq, the MCP service in the UI and the CLI, curl tests, and the rebuild pointer. The README TODO now links to it. fz reviewed it. Open items for fz: fill in the read-only TODO after azz deploys, and check the claim that every rebuild changes the Gateway and Cognito against azz's `cdk diff`. azz committed the fork fix as `f1b33d3`. It is not pushed, so a reader who clones the fork does not get it yet. Pushing needs Ryan.
- **2026-10-10, fz:** azz stopped at the gate. `cdk diff` shows no template change. Only two parameters change, the image (`:latest` to `:f1b33d3`) and the username (`neo4j` to `mcp_reader`), and both feed only the Runtime. The Runtime updates in place, and the Gateway, Cognito, and UC connection stay untouched. So the claim that every rebuild changes the Gateway is wrong for an update deploy. The permission classifier blocked the creds swap, which needs Ryan's OK in azz's session. ECR holds only one untagged-by-SHA image (`:latest`, pushed 2026-10-09). azz proposes tagging it `rollback-20261009` before the deploy. Hazard: `deploy.py` writes the new password before `cdk deploy`, so a CFN auto-rollback would break auth until the admin `.env` is restored and redeployed.
- **2026-10-10, fz:** azz deployed with Ryan's approval in its session. The image is `neo4j-mcp-server:f1b33d3` (digest `sha256:8e5b52d1…c6d1`), and the Runtime now pins that tag instead of `:latest`. The Runtime moved to version 2 with `NEO4J_USERNAME=mcp_reader`. The Gateway, Cognito, and UC connection are unchanged. The previous image is tagged `rollback-20261009`. azz verified through the Gateway: two tools, the schema works, 15940 returns 19766, the app rejects CREATE, and the database forbids it as `mcp_reader`. fz smoke-tested the UC MCP service with the same result. azz found a `deploy.py` bug: it tags the image `latest` when `NEO4J_MCP_REPO` is a subfolder, so the old live image had no SHA. The fix waits on Ryan. fz corrected the "every rebuild changes the Gateway" claim in the README and `docs/mcp-service.md`: only a fresh stack does. The read-only TODO waits on azz's exact commands.
- **2026-10-10, fz:** fz filled in the read-only section of `docs/mcp-service.md`. It explains why `reader` alone breaks the schema tool, then covers finding the managed role, creating the user, the password rule, the probe, and how to undo it. azz ran the setup with `neo4j-cli`. The doc shows the equivalent Cypher, which nobody ran directly, so a reader is the first to run it as written. The role name pattern was seen on two Professional instances and is not documented, so the doc says to check it. `future-improvements.md` still lists the read-only user as future work. Removing that entry waits on Ryan.
- **2026-10-10, fz:** Ryan ruled. Trust his user in `app.yaml`: done. Fix `deploy.py`: azz did it. Remove `future-improvements.md`: done. No drift check for the Q1 ids. Ryan will commit and push the aws-starter fix and push the fork commit himself. He then approved the four "Proposed additions". fz committed L, N, and the doc fixes as `7b959e8`, with no co-author line. fz gave zzz the go for M, which already covers the short front door and the demo script, now with a Genie beat. fz assigned dbz O (the Genie tool) and P (Make targets and the NAMS key in config).
- **2026-10-10, fz:** fz tested the MCP change.
  - The UC connection host and client match the redeployed Gateway, so no connection update is needed.
  - pytest: 273 passed.
  - `check_drift.py` live: The first run crashed on a non-JSON tool result, probably a cold start after the Runtime update. Two reruns found no drift. The script still crashes with no message when a tool returns text that is not JSON.
  - `agent-evaluate`: The safety and no-write gates passed. MLflow warned that it failed to log traces locally.
  - Local `agentbricks dev`: 15940 returns Community 19766 through `read_neo4j_cypher`, and recall in a new session for the same user works.
  - `agentbricks deploy`: The permission classifier blocked it as a production deploy, so the deployed-app smoke test and the laptop traffic identity check wait on Ryan.
- **2026-10-10, fz:** azz finished the `deploy.py` fix. A new `resolve_image_tag` uses `git rev-parse --show-toplevel` and keeps the IMAGE_TAG override and the `latest` fallback. Five direct tests pass. Nothing is committed. aws-starter has other modified and untracked files that existed before this session, so Ryan should stage only `neo4j-mcp-server/deploy.py`.
- **2026-10-10, fz:** zzz finished M. The README is a 162-line front door: story, architecture, prerequisites, NAMS key, deploy and try, a demo script, and run locally. Six pages moved to `docs/`, and every link resolves. The two Genie demo beats are marked placeholders. fz reviewed it and asked for two fixes: the optional ring question conflicts with the recall step, and troubleshooting needs the deployed-image record from J. fz confirmed the live Runtime runs `neo4j-mcp-server:f1b33d3`. `.agentbricks/mlflow.db` and its log changed from fz's local dev run, and they stay uncommitted.
- **2026-10-10, fz:** zzz fixed both M items. The ring question is now an add-on after step 3, and troubleshooting records the deployed image `f1b33d3` and how to check it. fz committed M as `9482f9e`, with docs and README only. dbz's Genie work stays uncommitted.
- **2026-10-10, fz:** dbz finished O.
  - The AFTER space `01f15efe10cf196a8d310614b9acf78e` is bound as the `genie` tool with `auth = "app"`, and the agent passes `genie_tools()`.
  - The prompt has a ROUTING section.
  - A new eval question needs both sources. Its scorer `graph_and_genie_called` never reads Genie's answer.
  - fz reviewed it. pytest: 273 passed. agent-evaluate: every metric is 1.0, including the new scorer.
  - fz committed it as `a8d8cc8`. `app.agentbricksdev.yaml` changed only from the local dev run and stays uncommitted.
  - Found: the app `agent-bricks-neo4j-graph-agent` does not exist in the workspace, so the next deploy is a first deploy and needs the NAMS key attach.
  - Deploy grants only CAN_RUN on the space. The app principal probably also needs CAN_USE on warehouse `b0fffb8e3255bf85`. Both go to Ryan.
  - zzz is filling in the Genie demo beats and README lines. dbz moved to P.
- **2026-10-10, fz:** dbz reported P. The Makefile has deploy, smoke, and traffic targets, which wrap the documented commands and require `DATABRICKS_CONFIG_PROFILE`. P2 found that neither `agent.toml` nor `app.yaml` can declare the NAMS secret resource. agentbricks keeps resources it did not create across deploys, so the attach is a one-time step. fz picked a separate `logs` target, so smoke exits on its own, and one experiment target per documented step, with the NAMS key switch kept manual.
- **2026-10-10, dbz:** `make deploy` runs only `agentbricks deploy`, `deployments get`, and a read-only `apps get`. The Makefile itself attaches no resources and changes no grants. On a first deploy, `agentbricks deploy` grants what agent.toml declares: EXECUTE on finance_genie_mcp, USE_SCHEMA and USE_CATALOG on its parents, and CAN_RUN on the Genie space as an app resource. fz will include this in the deploy ask to Ryan.
- **2026-10-10, zzz:** zzz finished the Genie README updates: the story, "what you'll see", "the parts", a prerequisites bullet, demo steps 4 and 5, and the reference.md Genie tools and evaluate lines. fz accepted zzz's edit to the Agent line and added the Genie space to the reference.md `agent.toml` sentence. fz checked that `gold_accounts` has region, account_type, balance, and txn_count_30d, so the space can answer both demo questions. fz does not predict Genie's answers.
- **2026-10-10, dbz:** P is done. The Makefile has nine targets: deploy, smoke, logs, traffic, export, replay, snapshot, apply-ontology, and compare. `make -n` matches each documented command, and pytest gives 273 passed. Next, zzz swaps make lines into the docs.
- **2026-10-10, zzz:** Q is done. Make lines now sit next to the unchanged raw commands in the README, traffic.md, and ontology-experiment.md, and the README has a Shortcuts table. fz committed the Makefile together with the docs. Accepted as is: the ontology targets do not check the profile, because they read NAMS through .env. Known limit: a QUESTION with an apostrophe breaks `make smoke`, and no documented question has one. troubleshooting.md keeps its raw commands.
