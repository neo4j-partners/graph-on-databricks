---
marp: true
theme: default
paginate: true
---

<style>
section {
  --marp-auto-scaling-code: false;
}

li {
  opacity: 1 !important;
  animation: none !important;
  visibility: visible !important;
}

.marp-fragment {
  opacity: 1 !important;
  visibility: visible !important;
}

ul > li,
ol > li {
  opacity: 1 !important;
}

.columns {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 32px;
  align-items: start;
}

.columns ul {
  margin-top: 0;
}

.placeholder {
  border: 3px dashed #9aa5b5;
  border-radius: 10px;
  color: #536174;
  font-size: 20px;
  line-height: 1.4;
  padding: 24px;
  text-align: center;
  min-height: 300px;
  display: flex;
  flex-direction: column;
  justify-content: center;
}

.placeholder strong {
  display: block;
  font-size: 22px;
  margin-bottom: 10px;
}

.small li,
.small p {
  font-size: 21px;
}

table {
  font-size: 20px;
}
</style>

# Agents That Remember What the Team Learned

**Databricks:** Agent Bricks, Genie, Databricks Apps, and MLflow Tracing

**Neo4j:** AuraDB, the Neo4j MCP server, and the Neo4j Agent Memory Service

<!--
The talk builds and deploys an Agent Bricks agent that reads the
fraud graph through the Neo4j MCP service and remembers through the
Neo4j Agent Memory Service, NAMS for short. That gives two graphs: a
domain graph and a memory graph. Once both exist, Genie One can use
the same two MCP servers to answer natural language questions. The
ontology section at the end shows what typing the memory graph
changes.

Product names were checked in October 2026. Genie Agents were called
Genie Spaces until July 2026, so say "Genie Agent" on stage even
though the repo and the API still say "space".
-->

---

## Every Session Starts Cold

- An analyst finds a suspicious community on Monday.
- A second analyst on another team opens the same community on Wednesday.
- Without memory, the agent re-runs the work.
- The second analyst never sees the first finding.
- **Chat history belongs to one session.** Investigations belong to the team.

<!--
Set up the problem in human terms before any architecture. The
Monday and Wednesday analysts come back on the slide "Demo: One
Analyst's Finding Reaches Another", where the
second analyst gets the first analyst's finding without re-running
it. Hold the last line: session history and team knowledge are
different things, and this deck is about the second one.
-->

---

## Demo Use Case: A Fraud Graph

- **A synthetic banking network.** Accounts, customers, merchants, phones, and addresses.
- **Money moves between accounts.** `TRANSFERRED_TO` carries the amount.
- **Customers link to phones and addresses.** A shared one ties identities together.
- **A fraud ring is a dense community of accounts.** Graph analysis scores each account with `community_id` and `risk_score`.

```
(Customer)-[:OWNS]->(Account)-[:TRANSFERRED_TO]->(Account)
(Customer)-[:HAS_PHONE]->(Phone)   (Account)-[:TRANSACTED_WITH]->(Merchant)
```

<!--
The audience has not seen the other finance-genie decks, so this
is the only introduction to the data. Stay on the graph model: five
node labels and the relationships that connect them. There is no
fraud label. A ring candidate is a community of 50 to 200 accounts
with a high average risk score, and the agent treats that as a
signal, not a verdict. The pipeline that builds the graph and
writes the scores is in slides.md, and it is not needed here.
-->

---

## Architecture

- **A Databricks App runs the agent on Agent Bricks.** The Agent Bricks CLI deploys it.
- **The agent reads the fraud graph through a Unity Catalog MCP service.** The service wraps the Neo4j MCP server and allows read-only Cypher.
- **The agent asks a Genie Agent for values over the Gold Delta tables.**
- **An AI Gateway model writes the answer.** Any chat model can be set.
- **The Neo4j Agent Memory Service stores each turn.** It keeps conversations, reasoning traces, and entities.
- **Agent Bricks keeps the session history and the MLflow traces.** Every model call and tool call is recorded.

<!--
The agent itself is an OpenAI Agents SDK loop with two read-only
graph tools, get_neo4j_schema and read_neo4j_cypher, and the Genie
tools. The Genie tools are OpenAI Agents SDK function tools built
by genie_tools() in agent/agent.py, not MCP tools, so the Cypher
guardrails and the MCP allowlist do not apply to them. They run
with auth = "app", so Genie executes its SQL as the app's service
principal, not as the analyst. The caller sends messages, and in the deployed app the
identity comes from the Databricks Apps proxy. The NAMS key lives
in the secret scope nams, and the app reads it as MEMORY_API_KEY.
The next slide is the diagram of the same parts.
-->

---

![bg contain](./architecture.svg)

<!--
Walk it left to right. The caller sends a question to the app. The
app recalls memory from NAMS, runs the agent, and the agent reads
the graph through the MCP service and the Gold tables through the
Genie Agent. The answer goes back to the caller, and then the app
writes the turn to NAMS. Agent Bricks keeps the session store and
the MLflow traces on its own.
-->

---

## What the Agent Shows

- **Build an agent on Agent Bricks and deploy it as a Databricks App.**
- **Give it the fraud graph through the Neo4j MCP service.** Unity Catalog governs the read-only Cypher.
- **Give it memory through the Neo4j Agent Memory Service.** Every turn is saved and recalled.
- **Route structure to the graph and values to Genie.** The system prompt sends totals and averages to the Genie Agent.
- **The result is two graphs.** One holds the domain, and one holds the memory.

<!--
This is the point of the module, and it is the point to land
before any demo. The agent is the vehicle for showing how an Agent
Bricks agent gets a graph through an MCP service and gets memory
through NAMS. Genie answers the value questions. The system prompt
in agent/prompt.py sends communities, paths, hubs, and shared
phones to the graph tools, and totals, averages, counts, and
breakdowns to Genie. A mixed question finds the ids in the graph
first, then asks Genie about those ids. The story is that the
agent ends up with two graphs, and the next slide puts them side
by side.
-->

---

## Two Graphs: Domain and Memory

| | Domain graph | Memory graph |
|---|---|---|
| **Holds** | Accounts, customers, merchants, phones, addresses | Conversations, reasoning traces, entities |
| **Built by** | The enrichment pipeline and Neo4j GDS | NAMS, from what the agent saves |
| **Reached through** | The Neo4j MCP service | The NAMS API, or NAMS as an MCP service |
| **Answers** | Who connects to whom | What the team already found |

<!--
The domain graph was modeled and loaded on purpose. The memory
graph was not modeled at all. It fell out of storing conversations,
and NAMS extracted the entities on its own servers. Both are Neo4j
graphs, and both are reachable through MCP. Backup slide B5 shows
NAMS registered as a Unity Catalog MCP service, which is what lets
Genie One reach the memory graph later in the deck. The ontology
section at the end is about typing the memory graph.
-->

---

![bg contain](./neo4j-agent-memory-diagram.svg)

<!--
The diagram labels its own three parts, so this slide has no title.
Say them: short-term memory is each conversation as a chain of
messages, long-term memory is the entities extracted from those
messages with links back to them, and reasoning memory is a trace
of the agent's steps and tool calls. All three live in one graph,
so a message links to the entities it mentions and to the reasoning
it triggered. The next slide is what this app does with each part.

Source: https://github.com/neo4j-labs/agent-memory
-->

---

## How the Agent Uses Each Part

- **Short-term memory belongs to one analyst.** Before each turn, the app reads that analyst's two latest conversations.
- **Long-term memory belongs to the team.** Every analyst's conversations feed the entity graph, and the app searches it for the entities a prompt names.
- **Reasoning memory is written, not read.** A turn with tool calls saves one trace with a step per tool call.
- **Agent Bricks keeps one session's history.** NAMS holds what outlives the session.

<!--
The diagram before this showed what NAMS stores. This slide is what
the app does with each part, and the new point is scope. Short-term
recall is filtered to one analyst. Long-term recall reads a graph
that every analyst's conversations built. Reasoning traces are
saved for the NAMS console and are not recalled by the agent. The
session store and the MLflow traces stay with Agent Bricks, so NAMS
only holds what has to outlive the session.
-->

---

## Memory Flow in One Turn

1. **Recall:** The app reads the analyst's recent conversations and the matching entities from NAMS.
2. **Run:** The agent runs with the recalled text in its instructions, not in its input.
3. **Reply:** The caller gets the answer before any memory write.
4. **Write:** The app saves the turn as one conversation with two messages and a reasoning trace.

- **A slow or missing NAMS never blocks the answer.**

<!--
Recall goes into the instructions because Agent Bricks saves the
message input to its session store, and the recalled text should
not be saved twice. The write happens after the reply, so the
caller never waits on NAMS. Recall waits at most 10 seconds and
adds at most 2000 characters. A recovery run reads memory but does
not write, so a replayed turn is not saved twice. The next slide
is the sequence diagram of the same four steps.
-->

---

![bg contain](./nams-flow.svg)

<!--
Walk the diagram top to bottom. The caller sends the question and
the user id. The TurnMemory lists the analyst's conversations in
NAMS and reads the latest two. The agent runs with that text. The
app returns the answer, then flushes the buffered tool calls and
answer to NAMS as a conversation, two messages, and a trace.
-->

---

## What Gets Saved, and What Does Not

<div class="columns small">
<div>

- **The stored answer drops Cypher code fences and MCP tool names.** Without that cleanup, NAMS would extract them as entities.
- **The reasoning trace keeps one plain-sentence step per tool call.** The query text stays out.
- **The MLflow trace keeps the full Cypher.** That is where debugging happens.
- **The system prompt fixes the id format.** Extracted names stay consistent.

</div>
<div class="placeholder">
<strong>PLACEHOLDER: NAMS console screenshot</strong>
One analyst's conversations, one reasoning trace, and the entities NAMS found. Replace with <code>./nams-console.png</code>.
</div>
</div>

<!--
NAMS extracts entities from whatever it stores, so what the app
writes decides what the memory graph contains. A trace step reads
like "The agent queried the graph database." Ids, scores, and
counts stay in the answer text, and the prompt writes them as
"Account <id>" and "Community <id>" every time. The NAMS console on the right is
what an analyst sees: each question as its own conversation, with
its messages, its trace, and the entities extracted from it.
-->

---

## Memory Follows the Caller's Identity

- **In the deployed app, the server picks whose memory a turn uses.** It reads the forwarded Databricks identity.
- **A caller cannot read another analyst's memory by sending a different `user_id`.** The deployed app ignores it.
- **Recall treats memory as data.** The agent verifies facts against the graph.
- **If NAMS is slow or down, the agent answers without memory.** NAMS never breaks an answer.

<!--
The local server honors a body user_id, and so does the deployed
app for callers listed in MEMORY_TRUSTED_CALLERS. That is how the
traffic generator runs several synthetic analysts. Backup slide B4
covers both, with the header names and the recall limits.
-->

---

## Demo: Recall Across Sessions

- **Step 2 asks whether Account 15940 is a hub.** The answer names Community 19766.
- **Step 3 starts a new session and asks "What was I looking at last time?"**
- **The answer names Account 15940.** This session never did.

<!--
Run: uv run scripts/demo.py --step 2 3

The step 2 question starts with "I focus on hub accounts", and
that phrase is what makes the step 3 recall visible. Point to the
ids, not the wording. The answer text changes from run to run.
Open the step 2 MLflow trace to show the span ending in
read_neo4j_cypher. Steps 2 and 3 use conversation recall, which
reads the stored conversation right away, so this demo does not
wait for extraction. Run the two steps back to back, because
recall reads only the two latest conversations.
-->

---

## The Entity Graph Belongs to the Team

<div class="columns">
<div class="placeholder">
<strong>PLACEHOLDER: Aura graph view</strong>
One entity in the center, a message on each <code>EXTRACTED_FROM</code> arrow, and a conversation behind each message, captioned with its analyst id. Replace with <code>./aura-entity-graph.png</code>.
</div>
<div>

- **One entity sits in the center.** A message hangs on each `EXTRACTED_FROM` arrow.
- **Each message leads back to a conversation.** The caption is its analyst id.
- **Nobody queried for this graph.** It came from storing conversations.

</div>
</div>

<!--
Say this: "The conversation history belongs to one analyst. This
entity graph belongs to the team. Nobody queried for it. It fell
out of storing conversations." The screenshot comes from the Aura
Query tab on the NAMS database, with the Conversation caption set
to userId. make who-shares lists the entities that more than one
analyst's conversations fed, and the top row is the one to show.
-->

---

## Demo: One Analyst's Finding Reaches Another

- **Analyst A asked about Community 3040 and its accounts before the talk.** NAMS has already extracted Community 3040 from that turn.
- **Analyst B now asks "What is already known about Community 3040?"** This is a new session and a different user.
- **The answer lists earlier findings it did not re-run.** Analyst B shares no history with analyst A.

<!--
Before the talk: uv run scripts/demo_longterm.py --turn 1
That call asks as analyst A and waits until NAMS has extracted
the entity.

Live: uv run scripts/demo_longterm.py --turn 2 --analyst-b <fresh id>

Say on stage that turn 1 ran earlier. Hiding it would look like a
trick. The facts in the answer came from the entity graph. The
demo depends on the make traffic run having filled the graph
first. A two-turn run on an empty NAMS produced no merged entity
at all. Pass a fresh --analyst-b every time, so analyst B has no
earlier demo turns of their own to recall.

PLACEHOLDER: paste the recorded turn 2 output here as the fallback
if the live call fails or times out.
-->

---

## What an Ontology Is

- **An ontology is a list of entity types and relationships.** It tells NAMS what to look for.
- **The finance ontology has types such as Analyst, Team, Account, Community, Case, and PhoneNumber.**
- **It has relationships such as `MEMBER_OF`, `OWNS`, `INVESTIGATES`, and `PART_OF`.**
- **It describes what analysts talk about.** It is not the fraud graph schema.

<!--
NAMS extracts entities from conversation text, not from the
graph. So the ontology lists the things analysts say: who they
are, which team they are on, what they investigate, and the
accounts, communities, phones, and cases they name. Analyst
covers managers too, because analysts name the person they report
to. Backup slide B3 shows the full list.
-->

---

## Each Type Says What It Is and What It Is Not

**The Community type:**

> A Louvain community of accounts found by graph analysis, identified by a numeric id such as 'Community 24683'. Not an organization, a team, or an identity cluster.

- **A Customer is an account holder.** It is not an analyst and not the bank's own staff.
- **These descriptions go straight to the extractor.**
- **The ontology runs in permissive mode.** It guides extraction and rejects nothing.

<!--
The quotation is the Community type's description, word for word
from ontology/finance_genie.ontology.yaml. Every type has one. The
"not" half matters as much as the first half. Permissive mode
means an entity outside the list is still stored. The ontology
shapes extraction. It is not a schema check.
-->

---

## The Experiment: Same Conversations, Two Ontologies

- **The input is a set of synthetic analyst conversations.** Analysts on different teams investigate the same community.
- **Trial 1 runs the conversations live with the generic NAMS Default ontology.**
- **Trial 2 replays the same stored conversations with the finance ontology.**
- **Only the ontology and the extraction change between the trials.**

<!--
An agent gives a different answer each time and extraction is LLM
based. So the agent runs live once, in trial 1, and trial 2
replays the stored transcripts unchanged. The database is reset
between the trials, but a reset keeps the active ontology, so
trial 1 is the generic default and not "no ontology". Backup
slide B6 has the caveats. The traffic is synthetic. Do not quote
sizes.
-->

---

## Results: Generic Buckets Become Finance Types

<div class="columns">
<div>
<img src="./ontology-before-after.png" alt="Entity counts by type for trial 1 and trial 2" style="width: 100%;">
</div>
<div>

- **Generic entities fell from 173 to 0.**
- **Type conflicts fell from 20 to 1.**
- **Type accuracy rose from 0.714 to 1.**
- **Duplicate groups did not improve.** They went from 64 to 71.
- **These numbers come from one run.**

</div>
</div>

<!--
These numbers come from one reference run. Extraction is LLM
based, so a rerun gives different numbers. The direction is what
holds. Recall stayed at 1 on both sides, and instance coverage did
not change. The ontology changed how entities were typed, not
whether they were found. Say the duplicates line out loud. The
slide is stronger with the limit on it than without. Backup slide
B2 has the rest of the rows.
-->

---

## What the Ontology Changes in Long-Term Memory

- **Recall finds an entity by name either way. The ontology changes what comes back with it.** It returns the type, and the description the extractor wrote under that type's guidance.
- **Fewer type conflicts mean fewer cases where one name is split across types.** That split is what makes a keyword search return the wrong node.
- **Typed relationships make the memory graph queryable by people.** A person can ask who investigates a community, or which team an analyst is on.
- **The agent's recall sees names, types, and descriptions.** It does not see relationships.

<!--
This is the honest version of "why the ontology matters". It does
not make recall find more. It changes what a found entity says
about itself, and it makes the graph legible to a human running a
query. The example to say aloud: "Community 3040 (Community)" with
a description of the investigation tells the model more than
"Community 3040 (Object)". The typed relationships are read through GET
/v1/entities/graph, which ontology/measure_ingestion.py uses for
the gold rel typed rows. The who-shares query does not need them.
Duplicates got worse in the reference run. The comparison shows
change, not cause.
-->

---

## Limits to Know

- **Entity recall needs an entity name in the prompt.** A prompt without one gets conversation recall only.
- **Extraction merges some mentions and leaves others as duplicates.** Several nodes can share the same name.
- **Extraction is asynchronous.** New entities appear seconds to minutes after a turn.
- **On hosted NAMS, long-term memory is the entity graph.** Preferences and facts need the self-hosted backend.

<!--
NAMS entity search matches keywords, so the app pulls short terms
such as "Community 3040" out of the prompt instead of searching
the full sentence. The duplicates are why "The Entity Graph
Belongs to the Team" uses make who-shares to find the merged
entity instead of searching by name. The async lag is why turn 1
of that demo runs before the talk.
-->

---

## Genie One Asks the Same Two Graphs

- **Both graphs are Unity Catalog MCP services.** The Neo4j MCP service exists, and backup slide B5 adds NAMS as one.
- **Genie One calls MCP services as tools.** A business user asks in plain English with no agent code.
- **The domain graph answers structure.** Which customers share a phone, and which community is an account in?
- **The memory graph answers history.** What was I investigating last time?
- **Unity Gateway governs both.** Each MCP call is logged like any other tool.

<!--
This is the payoff of building two graphs. The agent was the first
consumer. Once both graphs sit behind Unity Catalog MCP services,
Genie One can reach them without the agent. The Neo4j MCP server
has been added to Genie One before. NAMS with Genie One was marked
untested in the Databricks overview deck, so test it before the
talk, or show the NAMS tools through the Playground as backup
slide B5 describes.
-->

---

## Key Takeaways and Try It

<div class="columns">
<div>

- **One agent on Agent Bricks reads two graphs.** The domain graph comes through the Neo4j MCP service, and the memory graph through NAMS.
- **Short-term memory carries one analyst across sessions.**
- **Long-term memory is a graph.** It carries findings across analysts.
- **An ontology types that graph.** It adds finance types and relationships.

</div>
<div>

- **Project:** [neo4j-mcp-graph-agent on GitHub](https://github.com/neo4j-partners/graph-on-databricks/tree/main/finance-genie/neo4j-mcp-graph-agent)
- **Quick start:** The README runs the agent locally with `make dev` or deploys it with `make deploy`.
- **Memory console:** [memory.neo4jlabs.com](https://memory.neo4jlabs.com/)

</div>
</div>

<!--
The README quick start comes first. The ontology example and the
long-term memory demo follow, in that order, from the README's
"Ontology and long-term memory" section.
-->

---

# Backup

The following slides cover the demo steps, the metric definitions, the full ontology, the recall limits, and the experiment caveats.

---

## B1. The Five Demo Steps

| Step | Question | Evidence |
|---|---|---|
| 1. Shared phone | Which customers share phone 312-555-0142, and which community are their accounts in? | Accounts 368, 927, 1033, and 1696, then Community 8174. A span ending in `read_neo4j_cypher`. |
| 2. Hub | Is Account 15940 a hub, and which community is it in? | Community 19766. A span ending in `read_neo4j_cypher`. |
| 3. Recall | What was I looking at last time? | Account 15940, in a new session. |
| 4. Genie value | What is the average balance by region and account type? | A `genie_ask` span, then a `genie_query_result` span. |
| 5. Graph and Genie | Which phones are shared, and what are those accounts' balances and 30-day counts? | A `read_neo4j_cypher` span, then a `genie_ask` span that names the account ids. |

<!--
Run all five with uv run scripts/demo.py, or pick steps with
--step. Steps 1 and 2 share one session. Step 3 starts a new
session, and steps 4 and 5 stay in it. The script prints a "You
should see" list for each step. It cannot read MLflow, so open the
latest traces and check the spans yourself.
-->

---

## B2. What the Metrics Mean

<div class="columns small">
<div>

- **Generic-bucket share:** This is the share of entities typed `Object` or `Concept`.
- **Type conflicts:** These are the same name stored under several types.
- **Noise:** This counts entities that are tool or schema plumbing.
- **Instance coverage:** This counts entities for specific instances, such as "Community 3040" or "CASE-4001".
- **Conformance:** This is the share of entities whose type the ontology declares.
- **Ground truth:** The traffic knows every entity it mentions, so recall and type accuracy can be scored.

</div>
<div>

- **Conformance:** It rose from 0 to about 0.997.
- **Typed relationships:** `MEMBER_OF`, `REPORTS_TO`, `OWNS`, and `INVESTIGATES` each reached 1. They started at 0 or 0.333.
- **Recall:** It stayed at 1 on both sides.
- **Instance coverage:** It did not change.
- **Noise:** It was 0 on both sides.
- **Total entities:** They went from 324 to 309. Do not read much into a change of this size.

</div>
</div>

<!--
Left column: the definitions from "What the metrics mean" in
ontology-experiment.md. Right column: the rows that the results
slide leaves out. All numbers are from the one reference run.
-->

---

## B3. The Full Ontology

<div class="columns small">
<div>

**Types:** Analyst, Team, InvestigationFocus, Account, Customer, Merchant, Community, IdentityCluster, PhoneNumber, Address, and Case.

Each type carries a pole type for NAMS, such as person, organization, object, or location, and a description that says what it is and what it is not.

</div>
<div>

- `Analyst -[MEMBER_OF]-> Team`
- `Analyst -[REPORTS_TO]-> Analyst`
- `Analyst -[FOCUSES_ON]-> InvestigationFocus`
- `Analyst -[OWNS]-> Case`
- `Customer -[OWNS]-> Account`
- `Analyst -[INVESTIGATES]-> Community | Account`
- `Case -[INVESTIGATES]-> Community`
- `Account -[PART_OF]-> Community | IdentityCluster`
- `Customer -[HAS_PHONE]-> PhoneNumber`
- `Customer -[HAS_ADDRESS]-> Address`
- `Account -[TRANSACTED_WITH]-> Merchant`
- `Account -[TRANSFERRED_TO | SIMILAR_TO]-> Account`

</div>
</div>

<!--
The source is ontology/finance_genie.ontology.yaml. Team also
carries aliases for the short team names, but the hosted API spec
does not model aliases, so the service may ignore them. The Team
description lists the aliases as a fallback.
-->

---

## B4. Recall Limits and Identity

- **Recall waits at most 10 seconds.** It adds at most 2000 characters to the instructions.
- **The deployed app takes the user from `X-Forwarded-Email`.** It falls back to `X-Forwarded-User` when the email is missing.
- **A request without a forwarded identity gets a 401.**
- **The local server honors a body `user_id`.** Without one, it uses the session id as the user.
- **Callers listed in `MEMORY_TRUSTED_CALLERS` may set `user_id` on the deployed app.** That is how the traffic generator runs several synthetic analysts.

<!--
The match on MEMORY_TRUSTED_CALLERS is exact. The checked-in
values belong to this repo's workspace, so anyone running traffic
replaces them with their own service principal id and email. A
recovery run reads memory but does not write, so a replayed turn
is not saved twice. Evaluation calls the agent directly and never
writes to NAMS.
-->

---

## B5. Add NAMS as a Databricks MCP Service

- **An MCP service exposes the NAMS tools to other Databricks agents.** The Playground can use them as a Unity Catalog object.
- **The service points at `https://memory.neo4jlabs.com/mcp` with a bearer token.** The token is the NAMS key.
- **Trim the tool list after loading.** Deselect the `memory_ontology_*` tools and `memory_create_relation`, because their schemas break the Playground listing.
- **Grant `USE CONNECTION` to each caller.**
- **Try it in the Playground.** Ask the model to remember a fact, then recall it in a new chat.

<!--
This step is optional. The app in this repo calls NAMS directly
through agent/nams.py. The doc is docs/nams-mcp-service.md in the
module. It has sample questions for the Playground, such as
remembering that Community 19766 is under investigation and
recalling it in a new chat.
-->

---

## B6. Experiment Caveats

- **A reset keeps the active ontology.** Trial 1 ran with the generic NAMS Default ontology, not with no ontology.
- **There is no API to unbind an ontology.** A no-ontology baseline only works on a workspace that never activated one.
- **Results vary between runs.** Extraction is LLM based, so two replays of the same side differ.
- **The reference after snapshot held extra smoke-test conversations.** They can only add to the count rows.
- **The comparison shows change, not cause.**

<!--
Each snapshot records the active ontology version id, so the two
versions can be checked. If they match, trial 2 did not activate
the finance ontology and the comparison is invalid. To measure the
noise floor, repeat one side and compare it with itself. A change
between the sides that is smaller than that spread is noise.
-->
