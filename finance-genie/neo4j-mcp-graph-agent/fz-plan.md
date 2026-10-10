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
