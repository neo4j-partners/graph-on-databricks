# Proposal: Agent Memory Slides

This is a proposal for a new slide deck about the agent memory module in `finance-genie/neo4j-mcp-graph-agent/`. The outline at the end lists each proposed slide with its bullets. No Marp deck exists yet.

## Summary

The existing decks, `slides.md` and `slides-15min.md`, cover the enrichment pipeline. Neo4j GDS writes graph features into Gold tables, and Genie queries them. The new module goes one step further. A fraud analyst agent on Agent Bricks reads the graph through a Unity Catalog MCP service, asks Genie for values, and remembers every turn in NAMS, the hosted Neo4j Agent Memory Service.

The deck tells one story in four steps:

1. **The agent:** The agent sends structure questions to the graph and value questions to Genie.
2. **The memory:** NAMS stores each turn and reads the analyst's latest conversations back before the next one.
3. **The long-term memory:** NAMS extracts entities from every stored turn. The entities form a graph that carries one analyst's findings to another.
4. **The ontology:** An ontology tells NAMS what to look for. It explains why the entity graph the audience just saw is typed and connected the way it is.

## Audience and length

- **Audience:** The audience is data, fraud, and AI platform teams on Databricks. They have seen Genie and want to know what an agent with memory adds.
- **Length:** The main deck has 18 slides and runs about 25 minutes, including two demos. A backup section holds the metric details and the setup steps.
- **Prerequisite:** The audience does not need the enrichment deck first. One slide recaps the fraud graph and the Gold columns.

## Core message

Memory stored as a graph becomes shared knowledge. An ontology shapes how that knowledge is typed and connected.

## Where it fits

- **Source file:** The deck lives at `finance-genie/docs/demo-guide/slides/slides-agent-memory.md`, next to the other Marp decks. This proposal stays in `docs/demo-guide/proposals/`.
- **Slide build:** The deck uses the `finance` theme, so it joins the `decks` object in `scripts/build-theme-gallery.mjs`, next to `slides.md` and `slides-15min.md`. That object builds every theme variant. The `standaloneDecks` array is the wrong place, because it builds each deck once with the theme from its own front matter.
- **Build script details:** The general case in `outputFile` already names the variant files. The `requested === "all"` block needs one more `copyFileSync` line, so the build emits `slides-agent-memory.html` as the recommended finance build.
- **Gallery page:** `renderIndex` in the same script has hardcoded buttons for the two existing decks. A third button for the new deck goes there.
- **Microsite:** The deck gets its own card in the `decks` array of `docs/site/build-site.mjs`, with its own description line. `databricks-overview` is already a finance-genie deck in that array. The publish workflow already rebuilds on changes under the slides folder.
- **15-minute deck:** `slides-15min.md` gets at most one closing slide. It says that an agent with memory sits on top of the enrichment pipeline, and it links to the new deck.

## Evidence the deck can use

The deck stays inside what the module docs already show. The numbers come from the reference run in `ontology-experiment.md`. Extraction is LLM based, so the slides label them as one run, not as a benchmark. A fresh run will not reproduce these exact numbers, and the deck must match the published docs.

- **Demo ids:** The demo script names Accounts 368, 927, 1033, and 1696, Community 8174, Account 15940, and Community 19766. The evidence is the ids in the answer and the spans in the MLflow trace, not the answer text.
- **Generic types:** The generic entity count fell from 173 to 0. Its share fell from 0.534 to 0.
- **Conformance:** The share of entities with a declared type rose from 0 to about 0.997.
- **Type conflicts:** Type conflicts fell from 20 to 1.
- **Type accuracy:** Type accuracy rose from 0.714 to 1.
- **Typed relationships:** `MEMBER_OF`, `REPORTS_TO`, `OWNS`, and `INVESTIGATES` each reached 1. They started at 0 or 0.333.
- **What did not change:** Recall stayed at 1, and instance coverage stayed the same. The ontology changed how entities were typed, not whether they were found.
- **What did not improve:** Duplicate groups went from 64 to 71. The deck says so plainly.
- **Optional repeat:** If there is time, a `before-2` repeat shows the run-to-run spread. The deck shows that spread on the duplicates row only, because that is the one row where noise versus effect matters to the story.

## Visual assets

- **Reuse:** `neo4j-mcp-graph-agent/docs/architecture.svg` and `neo4j-mcp-graph-agent/docs/nams-flow.svg` can be copied into the slides folder.
- **New screenshot:** The MLflow trace from demo step 5 shows a `read_neo4j_cypher` span and a `genie_ask` span in one trace.
- **New screenshot:** The Aura graph view shows one entity linked to messages and conversations from several analysts.
- **New screenshot:** The NAMS console shows one analyst's conversations, reasoning trace, and entities.
- **New chart:** A before and after bar chart shows entity types for the two ontology trials.

## Demo plan

- **Recall across sessions, live:** Slide 9 runs live. Steps 2 and 3 use conversation recall, which reads the stored conversation right away and does not wait for extraction.
- **Finding across analysts, half live:** Slide 11 runs turn 1 as analyst A before the talk with `uv run scripts/demo_longterm.py --turn 1`. That call waits until NAMS has extracted the entity. Turn 2 runs live as analyst B with `uv run scripts/demo_longterm.py --turn 2 --analyst-b <fresh id>`. The slide says that turn 1 ran earlier, because hiding it would look like a trick. The recorded output stays in the speaker notes as a fallback.

## Proposed outline

### Section 1: Opening

1. **Title: Agents That Remember What the Team Learned**
   - The subtitle is "Agent Bricks, Neo4j, Genie, and Neo4j Agent Memory."
   - Speaker note: The fraud graph answers structure. Genie answers values. Memory carries findings from one analyst to the next.

2. **The Problem: Every Session Starts Cold**
   - An analyst finds a suspicious community on Monday.
   - A second analyst on another team opens the same community on Wednesday.
   - Without memory, the agent re-runs the work.
   - The second analyst never sees the first finding.
   - Chat history belongs to one session. Investigations belong to the team.

3. **Recap: The Fraud Graph and the Gold Columns**
   - Accounts connect through transfers, merchants, phones, and addresses.
   - GDS writes `risk_score`, `community_id`, and `similarity_score` into Gold tables.
   - The new module adds an agent on top of both.
   - Speaker note: Link to the enrichment deck for the full pipeline.

### Section 2: The Agent

4. **Architecture**
   - The image is `architecture.svg`. The diagram carries NAMS and MLflow.
   - A Databricks App runs the agent on Agent Bricks.
   - The agent reads Neo4j through a Unity Catalog MCP service.
   - The agent asks a Genie space for values over the Gold Delta tables.

5. **Structure to the Graph, Values to Genie**
   - The image is the MLflow trace screenshot from demo step 5.
   - Structure questions go to read-only Cypher. An example is "Which customers share this phone number?"
   - Value questions go to Genie. An example is "What is the average balance by region?"
   - Mixed questions use both in order. The graph finds the account ids, and Genie gets those ids in its question.
   - The MLflow trace shows each call: a `read_neo4j_cypher` span for the graph, then a `genie_ask` span for Genie.

### Section 3: Memory

6. **Two Kinds of Memory, One Turn**
   - The image is `nams-flow.svg` on the left. The two kinds of memory sit in two text columns on the right.
   - Short-term memory is one analyst's stored conversations. The app reads the two latest before each turn.
   - Long-term memory is the entity graph in NAMS. Every analyst's conversations feed it.
   - Agent Bricks keeps one session's history in its session store. NAMS holds what outlives the session.
   - Recall goes into the agent's instructions, not its input, so the session store does not save it again.
   - After the reply, the app writes the turn to NAMS as one conversation with two messages. When tools ran, it also writes a reasoning trace.

7. **What Gets Saved, and What Does Not**
   - The stored answer drops Cypher code fences and MCP tool names.
   - Without that cleanup, NAMS would extract them as entities.
   - The reasoning trace keeps one plain-sentence step per tool call, without the query text.
   - The MLflow trace keeps the full Cypher for debugging.
   - The system prompt asks the agent to write ids as "Account <id>" and "Community <id>", so extracted names stay consistent.

8. **Memory Follows the Caller's Identity**
   - In the deployed app, the server picks whose memory a turn uses, from the forwarded Databricks identity.
   - In the deployed app, a caller cannot read another analyst's memory by sending a different `user_id`.
   - Recall treats memory as data. The agent verifies facts against the graph.
   - If NAMS is slow or down, the agent answers without memory.
   - Speaker note: The local server honors a body `user_id`, and so does the app for callers in `MEMORY_TRUSTED_CALLERS`. B4 covers both.

9. **Demo: Recall Across Sessions**
   - Step 2 asks whether Account 15940 is a hub. The answer names Community 19766.
   - Step 3 starts a new session and asks "What was I looking at last time?"
   - The answer names Account 15940, although this session never did.
   - Speaker note: Run `uv run scripts/demo.py --step 2 3`. The step 2 question starts with "I focus on hub accounts", and that phrase is what makes the step 3 recall visible. Point to the ids, not the wording. Open the step 2 MLflow trace to show the `read_neo4j_cypher` span.

### Section 4: Long-Term Memory

10. **The Entity Graph Belongs to the Team**
    - The image is the Aura graph view of one entity.
    - One entity sits in the center, with a message on each `EXTRACTED_FROM` arrow.
    - Each message leads back to a conversation, captioned with its analyst id.
    - Nobody queried for this graph. It came from storing conversations.

11. **Demo: One Analyst's Finding Reaches Another**
    - Analyst A asked about Community 3040 and its accounts before the talk.
    - NAMS has already extracted Community 3040 from that turn.
    - Analyst B now asks "What is already known about Community 3040?" in a new session.
    - The answer lists earlier findings it did not re-run. Analyst B shares no history with analyst A.
    - Speaker note: Run `uv run scripts/demo_longterm.py --turn 2 --analyst-b <fresh id>` live. The facts came from the entity graph. The demo depends on the `make traffic` run having filled the graph first. A two-turn run on an empty NAMS produced no merged entity at all. Keep the recorded output as a fallback.

### Section 5: The Ontology

12. **What an Ontology Is**
    - An ontology is a list of entity types and relationships.
    - It tells NAMS what to look for.
    - The finance ontology has types such as Analyst, Team, Account, Community, Case, and PhoneNumber.
    - It has relationships such as `MEMBER_OF`, `OWNS`, `INVESTIGATES`, and `PART_OF`.
    - It describes what analysts talk about. It is not the fraud graph schema.

13. **Each Type Says What It Is and What It Is Not**
    - The Community description reads, set as a quotation: "A Louvain community of accounts... Not an organization, a team, or an identity cluster."
    - A Customer is an account holder. It is not an analyst.
    - These descriptions go straight to the extractor.
    - The ontology runs in permissive mode. It guides extraction and rejects nothing.

14. **The Experiment: Same Conversations, Two Ontologies**
    - The input is a set of synthetic analyst conversations. Analysts on different teams investigate the same community.
    - Trial 1 runs the conversations live with the generic NAMS Default ontology.
    - Trial 2 replays the same stored conversations with the finance ontology.
    - Only the ontology and the extraction change between the trials.

15. **Results: Generic Buckets Become Finance Types**
    - The image is the before and after chart of entity types, on one side of the slide.
    - Generic entities fell from 173 to 0.
    - Type conflicts fell from 20 to 1.
    - Type accuracy rose from 0.714 to 1.
    - Duplicate groups did not improve. They went from 64 to 71.
    - Speaker note: These numbers come from one run. Recall stayed at 1 on both sides, and instance coverage did not change. The ontology changed how entities were typed, not whether they were found. B2 has the rest of the rows.

16. **What the Ontology Changes in Long-Term Memory**
    - Recall finds an entity by name with or without the ontology.
    - What changes is what comes back with it: the type, and the description the extractor wrote under that type's guidance.
    - "Community 3040 (Community)" with a description of the investigation tells the model more than "Community 3040 (Object)".
    - Fewer type conflicts mean fewer cases where one name is split across types. That split is what makes a keyword search return the wrong node.
    - Typed relationships let a person ask the memory graph who investigates a community, or which team an analyst is on.
    - The agent's recall sees names, types, and descriptions, not relationships.
    - Speaker note: Duplicates got worse in the reference run. The comparison shows change, not cause.

### Section 6: Close

17. **Limits to Know**
    - Entity recall needs an entity name in the prompt. A prompt without one gets conversation recall only.
    - Extraction merges some mentions and leaves others as duplicate nodes with the same name.
    - Extraction is asynchronous. New entities appear seconds to minutes after a turn.
    - On hosted NAMS, long-term memory is the entity graph. Preferences and facts need the self-hosted backend.

18. **Key Takeaways and Try It**
    - The left column holds the takeaways. The right column holds the links.
    - The agent sends structure to the graph and values to Genie, and every call shows in MLflow.
    - Short-term memory carries one analyst across sessions.
    - Long-term memory is a graph, so it carries findings across analysts.
    - An ontology types that graph with finance types and relationships.
    - The links are the GitHub project, the README quick start, and the NAMS console.

### Backup slides

- **B1. The Five Demo Steps:** This slide lists shared phone, hub, recall, Genie value question, and graph plus Genie, with the span each one should show.
- **B2. What the Metrics Mean:** This slide defines generic-bucket share, type conflicts, noise, instance coverage, conformance, and ground truth. It holds the result rows that slide 15 leaves out.
- **B3. The Full Ontology:** This slide shows every type and relationship as a diagram.
- **B4. Recall Limits and Identity:** This slide covers the 10 second wait, the 2000 character cap, `X-Forwarded-Email`, the local body `user_id`, and `MEMORY_TRUSTED_CALLERS`.
- **B5. Add NAMS as a Databricks MCP Service:** This slide shows how other agents, such as the Playground, can use the NAMS tools.
- **B6. Experiment Caveats:** This slide says that a reset keeps the active ontology, so trial 1 is the generic default and not "no ontology." The comparison shows change, not cause.

## Decisions

1. **Deck name:** The deck is `slides-agent-memory.md`. This proposal lives in `docs/demo-guide/proposals/`.
2. **Standalone deck:** The deck stands alone. `slides-15min.md` gets at most one closing slide that links to it.
3. **Microsite placement:** The deck gets its own card in the `decks` array of `build-site.mjs`.
4. **Demos:** Slide 9 runs live. Slide 11 runs half live, as the demo plan describes.
5. **Chart source:** Slide 15 uses the reference run numbers from `ontology-experiment.md`, labeled as one run. B6 carries the caveats.
