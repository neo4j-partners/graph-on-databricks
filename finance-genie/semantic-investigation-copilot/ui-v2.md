# Semantic Investigation Copilot UI, v2

A three-page Streamlit app that follows one thread end to end: the financial
data as it sits in two systems, the semantic map NeoCarta builds over each of
them, and a question answered by retrieving that map and running the queries
it grounds.

This revision folds the five pages of `ui.md` into three. Each data page now
shows the real data and the map that describes it on one screen, driven by one
selector. The two systems come back together on the last page, where a single
question retrieves both halves of the map and queries both sources.

The app reads three sources, all read-only:

| Source | What the app reads | Used on |
|---|---|---|
| Databricks SQL warehouse | Table and column metadata, sample rows, generated query results | Lakehouse, Ask |
| Operational Neo4j (Finance Genie) | A bounded subgraph, and the generated Cypher result | Operational graph, Ask |
| NeoCarta semantic store | The metadata graph and the MCP retrieval tools | Lakehouse, Operational graph, Ask |

The NeoCarta store holds metadata only. That is a property of the store and of
the ingest, not a restriction on the app. Ingest runs with
`value_sample_limit=0` and the schema-map extractor calls only `db.labels`,
`db.relationshipTypes`, `db.schema.nodeTypeProperties`,
`db.schema.relTypeProperties`, and `db.schema.visualization`. No row or
property value is ever written into the store. The app displays rows. The store
never retains them.

## The claim

One sentence, and every screen should support it:

> Two systems hold the same accounts in different shapes. NeoCarta captures
> both shapes as one governed map, and a question answered through that map is
> grounded in retrieved structure instead of in a guess.

## What changed from v1

```text
v1                                      v2                                   Why
-------------------------------------   ----------------------------------   ------------------------------------------
5 pages                                 3 pages                              Data and its map share a screen and a selector.
ER diagram on Lakehouse data            Removed                              The six RELY foreign keys are the six REFERENCES
                                                                             edges NeoCarta retains. Draw them once, as the map.
Trace control on a separate map page    Same selector drives rows and map    The capture argument goes from two clicks to zero.
Provenance panel parses SQL and Cypher  Model declares identifiers used,     Parsing generated queries is the most fragile item
                                        app checks set membership            in the spec. A set difference has no edge cases.
MCP stdio session cached per Streamlit  One stdio session per Ask click      Streamlit reruns the script on every widget change.
session                                                                      A cached async session across reruns is a bug farm.
Subgraph canvas on Ask                  Dataframe for the Cypher result      One fewer canvas, no post-result selection state.
Dropdown plus free-text box             Three pills that fill one text box   Same function, one widget fewer.
Connection probes on every rerun        Probes cached as resources           Three live probes per rerun make the sidebar drag.
App name open                           Semantic Investigation Copilot       The directory already carries the name.
```

Everything not listed here is unchanged from `ui.md`: neo4j-viz for graph
surfaces, caps stated in captions, read-only enforced at the connection, and
the deferred list.

## 80-second demo script

```text
 0:00  Open the app. It lands on Lakehouse.
       Say: here are the accounts, as tables. Below them, what NeoCarta
       wrote after reading the lakehouse.
       Point at: ten rows of gold_accounts with real balances and risk
       scores, then the same table lit up in the map with its columns.

 0:20  Click Operational graph.
       Say: here are the same accounts, as a graph. Below it, what NeoCarta
       wrote after reading the graph. Same store, same vocabulary.
       Point at: the transfer subgraph around one account, then :Account
       lit up in the map with its properties and TRANSFERRED_TO.

 0:40  Click Ask. Pick "Which fraud rings share an identity cluster?"
       Say: one question, and it retrieves from both halves before it
       writes anything.
       Point at: the MCP tools firing, then the generated SQL and Cypher
       built from exactly those retrieved names.

 1:05  The results land.
       Say: every table, column, label, and relationship in those two
       queries came out of the map. Nothing was guessed.

 1:20  Stop.
```

Anything not on this path is optional. Cut it before adding to it.

## App shell

```text
+--------------------------------------------------------------------------------+
|  Semantic Investigation Copilot                                                |
+--------------------------+-----------------------------------------------------+
| SIDEBAR                  | PAGE                                                |
|                          |                                                     |
| [✓] Lakehouse            |  Page-specific content                              |
| [✓] Operational graph    |                                                     |
| [✓] Semantic map         |                                                     |
|                          |                                                     |
| DATA AND ITS MAP         |                                                     |
|   Lakehouse              |                                                     |
|   Operational graph      |                                                     |
|                          |                                                     |
| ASK                      |                                                     |
|   Ask                    |                                                     |
|                          |                                                     |
| [Connections v]          |                                                     |
| [Store not built? v]     |                                                     |
+--------------------------+-----------------------------------------------------+
```

Use `st.navigation` with two sections. It gives the group headings for free
and needs no custom sidebar code.

Three connection badges, one per source. Each badge comes from a probe wrapped
in `st.cache_resource`, so the probes run once per process and not once per
rerun. A page that needs a source it cannot reach says so in place and leaves
the other pages usable. The `Connections` expander holds hosts, catalog,
schema, and database names. The `Store not built?` expander shows the Makefile
sequence as copyable text and runs nothing.

## 1. Lakehouse

The accounts as tables, and the map NeoCarta wrote over them. One selector
drives both halves.

```text
Lakehouse                   graph-on-databricks.graph-enriched-schema · warehouse

[Table: gold_accounts v]

THE DATA                                                       10 sample rows
+------------+----------+------------+--------------+------------------+
| account_id | balance  | risk_score | community_id | fraud_risk_tier  |
+------------+----------+------------+--------------+------------------+
| 8842       | 41208.55 | 3.42       | 17           | high             |
| 8843       |  2190.10 | 0.11       | 17           | low              |
| ...        |          |            |              |                  |
+------------+----------+------------+--------------+------------------+
Column comments shown on hover. 17 tables in scope.

THE MAP                            NeoCarta store · neo4j @ 127.0.0.1
[Show columns ✓]   [Show REFERENCES ✓]

  (Database: graph-on-databricks)
        | HAS_SCHEMA
        v
  (Schema: graph-enriched-schema)
        | HAS_TABLE
        +--> (Table: accounts)
        |        +--> (Column: account_id)
        |        +--> (Column: balance)
        |
        +--> (Table: gold_accounts)          <-- traced
        |        +--> (Column: risk_score)
        |        +--> (Column: community_id)
        |        +--> (Column: identity_cluster_id)
        |        +--> (Column: fraud_risk_tier)
        |
        +--> (Table: transactions)
        |        | REFERENCES -> accounts
        |        | REFERENCES -> merchants
        |
        +--> (Table: account_links)
                 | REFERENCES -> accounts   (src)
                 | REFERENCES -> accounts   (dst)

Traced: gold_accounts · 28 columns · 0 REFERENCES out · 0 REFERENCES in
Captured from Unity Catalog information_schema. No row values retained.
```

The selector at the top is the whole page. Pick a table and the rows change
and the map dims to that `Table`, its `Column` nodes, and its `REFERENCES`
edges at the same moment. Nobody has to click across to a second page to see
that the store captured what the warehouse holds.

The ER diagram from v1 is gone. Its six foreign-key edges are the six
`REFERENCES` edges in the map, so the map already shows the shape of the
schema. With `Show columns` off, the map is the ER diagram.

Sample rows come from `SELECT ... LIMIT 10` against the chosen table. Ten rows
of real balances and risk scores do more work than any count.

The Gold tables are graph output that came back into the lakehouse. That is
the only reason the two systems have anything to say to each other, and it is
worth one sentence out loud when `gold_accounts` is selected. Say it; do not
build a widget for it.

Counts belong in the caption under the trace, not in metric tiles.

## 2. Operational graph

The same accounts as a graph, and the map NeoCarta wrote over it. Same page
shape as Lakehouse, deliberately.

```text
Operational graph                                       neo4j @ <source-host>

[Label: Account v]   [Account: 8842 v]   [Depth: 2 v]   [Types: TRANSFERRED_TO, OWNS, HAS_PHONE v]

THE DATA
                      (Phone: ***4417)      (Address: ***Elm St)
                             ^                       ^
                             | HAS_PHONE             | HAS_ADDRESS
                        (Customer: C-2291)      (Customer: C-3380)
                             | OWNS                  | OWNS
                             v                       v
     (Account 8842) --TRANSFERRED_TO--> (Account 8843) --TRANSFERRED_TO--> ...
           |                                   ^
           +-----------SIMILAR_TO--------------+

Legend  (Account) risk_score high / low    (Customer)   (Phone)   (Address)
Selected: Account 8842 · risk_score 3.42 · community_id 17
Showing 34 of 128 nodes within depth 2. Capped at 150 nodes.

THE MAP                            NeoCarta store · neo4j @ 127.0.0.1
[Show properties ✓]   [Show endpoints ✓]

  (Database: finance-genie)
        | HAS_SCHEMA
        v
  (Schema: <source-scope>)
        | HAS_NODE
        +--> (Node: Account)                 <-- traced
        |        +--> (Property: account_id :: String)
        |        +--> (Property: risk_score :: Float)
        |        +--> (Property: community_id :: Integer)
        +--> (Node: Customer)
        +--> (Node: Phone)
        +--> (Node: Address)
        |
        | HAS_RELATIONSHIP
        +--> (Relationship: TRANSFERRED_TO)
        |        | HAS_SOURCE_NODE -> Account
        |        | HAS_TARGET_NODE -> Account
        +--> (Relationship: OWNS)
        +--> (Relationship: HAS_PHONE)
        +--> (Relationship: HAS_ADDRESS)
        +--> (Relationship: SIMILAR_TO)

Traced: Account · 3 reported properties · source of 2 relationship types
Endpoint pairs are statistics-based. No property values retained.
```

This page carries two selectors where Lakehouse carries one. The data half is
keyed by an account and the map half is keyed by a label, and those are
different things. Do not try to derive one from the other. `Label` traces the
map. `Account`, `Depth`, and `Types` bound the subgraph.

One selected account, expanded to a capped depth. State the cap in the caption
every time. A demo that tries to draw the whole transfer network draws a
hairball.

Nodes are coloured by `risk_score`, which puts the graph-derived signal on
screen before anyone has explained what PageRank is. Selecting a node shows its
properties beside the canvas.

The relationship-type filter matters here. Turning `HAS_PHONE` and
`HAS_ADDRESS` on and off separates the transfer network from the identity
network, and those are two different fraud stories in the same graph.

The map half is the mirror of the Lakehouse map half on purpose. An audience
that just watched a table light up with its columns watches a label light up
with its properties. The two systems are in one store at the same fidelity,
and the identical layout is what proves it without anyone asserting it.

Endpoint pairs come from `db.schema.visualization` and are statistics-based.
Neo4j reports possible label combinations rather than observed paths, and the
page says so once. When visualization was unavailable at ingest, the persisted
map records that. Drop the endpoint edges, keep the node and relationship
inventory, and state that source permissions did not allow endpoint metadata.
Do not infer endpoints from names.

## 3. Ask

A question goes in. Both halves of the map are retrieved, the queries are built
from what came back, they run against the two systems from pages 1 and 2, and
the answers land.

```text
Ask

( Which fraud rings share an identity cluster? ) ( Which accounts moved money to a high-risk account? ) ( Where do identity clusters cross regions? )

[ Which fraud rings share an identity cluster?                              ]  [Ask]

1  RETRIEVED FROM THE MAP
   [✓] get_context_by_table_full_text_search   {"text_content": "fraud ring
       identity cluster", "max_tables": 5}
         -> gold_fraud_ring_communities, gold_accounts          [JSON v]
   [✓] get_context_by_column_full_text_search  {...}
         -> community_id, identity_cluster_id,
            identity_cluster_size, is_ring_community            [JSON v]
   [✓] get_neo4j_schema_context                {}
         -> Account, Customer, TRANSFERRED_TO, OWNS             [JSON v]

2  GROUNDED IN                                 every name below traces to step 1

   gold_fraud_ring_communities.community_id      [from table search]
   gold_accounts.identity_cluster_id             [from column search]
   gold_accounts.community_id                    [from column search]
   (:Account)-[:TRANSFERRED_TO]->(:Account)      [from schema context]

3  QUERIES BUILT FROM THAT CONTEXT

   SQL over the lakehouse                  Cypher over the operational graph
   +-----------------------------------+   +-------------------------------+
   | SELECT r.community_id,            |   | MATCH (a:Account)             |
   |        r.member_count,            |   |   -[:TRANSFERRED_TO]->(b)     |
   |        count(DISTINCT             |   | WHERE a.community_id = $cid   |
   |          a.identity_cluster_id)   |   |   AND b.community_id = $cid   |
   | FROM gold_fraud_ring_communities r|   | RETURN a.account_id,          |
   | JOIN gold_accounts a              |   |        b.account_id,          |
   |   ON a.community_id =             |   |        a.risk_score           |
   |      r.community_id               |   | LIMIT 200                     |
   | WHERE r.is_ring_candidate         |   +-------------------------------+
   | GROUP BY 1, 2                     |   [Run]  read-only transaction
   +-----------------------------------+
   [Run]  read-only warehouse

4  ANSWER

   +--------------+--------------+-------------------+   +------------+------------+------------+
   | community_id | member_count | identity_clusters |   | a.account_id | b.account_id | a.risk_score |
   +--------------+--------------+-------------------+   +------------+------------+------------+
   | 17           | 112          | 4                 |   | 8842       | 8843       | 3.42       |
   | 33           |  87          | 1                 |   | ...        |            |            |
   +--------------+--------------+-------------------+   +------------+------------+------------+

   The map supplied the names. It does not assert that
   gold_accounts.community_id and :Account.community_id are the same
   population. A reviewer confirms that join.
```

### Input

Three curated questions as `st.pills`. Clicking a pill fills the one text box.
The box is editable, so the preset carries the demo and the same box carries
the follow-up. There is no second input.

### Retrieval

Each Ask click opens one MCP stdio session, runs the three tool calls, and
closes the session. Call the server exactly the way `validate_mcp.py` does,
with `StdioServerParameters(command=sys.executable, args=["-m", "mcp_server"],
cwd=DEMO_DIR)`, inside one `asyncio.run`. Do not cache the session across
Streamlit reruns. The session costs a second or two per question and removes
every event-loop and subprocess-lifecycle failure a cached session would
introduce.

Both full-text tools return records carrying `database_name` and
`schema_name`. Filter them to the configured catalog and schema the way
`validate_mcp.records_for_source` does.

Each tool call renders as one `st.status` block with the call arguments, the
names it returned, and the raw JSON behind an expander.

### Grounding

Step 2 is the load-bearing panel. It is the bridge from retrieval to
execution, and it is what makes the demo different from watching any agent
write SQL.

Build it without parsing the generated queries. The serving endpoint returns
structured output with three fields: the SQL, the Cypher, and a list of the
identifiers it used, each tagged with the tool call it came from. The app
takes the set of names step 1 returned and the set the model declared, and the
difference is the panel:

```text
declared ⊆ retrieved      every row shows its source tool
declared − retrieved ≠ ∅  each extra name is shown in red with "not retrieved"
```

A name in red is a real finding, not a bug in the app. It means the model
reached for something the map did not give it. Show it and let the audience
see it. Do not attempt to catch a name the model used but failed to declare.
That would need a parser, and a parser is what this design removes.

### Generation

Query generation calls a Databricks serving endpoint with the retrieved
context and the two schemas as the only source of names. Keep the prompt in
one module and keep it short. Ask for the structured output above and nothing
else. Show the generated queries before running them, always.

### Execution

Two `Run` buttons, one per query. Each runs the query shown above it and
nothing else. The SQL result and the Cypher result both land as dataframes. A
failed run shows the server's error in place of the table. An empty table
with no explanation is the one outcome the page must never produce.

The Cypher should return scalar columns rather than nodes so the dataframe
reads cleanly. The prompt asks for that. A rendered subgraph of the result is
deferred, below.

## Safety

Executing a generated query is the one new risk this design takes. Enforce
read-only at the connection, never by inspecting the generated string.

```text
Surface                    Enforcement
------------------------   ----------------------------------------------
Lakehouse queries          A warehouse reached by a principal with SELECT
                           grants only on the one configured schema.
Operational graph queries  A read-only Neo4j user, and every call issued
                           through a read transaction so write clauses
                           fail at the server.
Semantic store             Read-only session. The app runs no make target
                           and opens no write session.
Row display                LIMIT on every sample query, node budget and
                           depth cap on every rendered subgraph.
```

The store target is still guarded before any connection by
`config.assert_semantic_store_target` for loopback or an explicitly approved
remote store, and by `config.assert_no_operational_graph_nodes` for the
`Account`, `Customer`, `Phone`, and `Address` labels. Those guards keep the
operational graph from being mistaken for the metadata store. They are
unchanged.

Rejecting write clauses by string matching does not work. Do not try.

## Implementation boundary

```text
Page                 Widgets                        Backing call
------------------   ----------------------------   ---------------------------
Sidebar              3 status badges, 2 expanders   one cached probe per source
Lakehouse            1 selectbox, 1 dataframe,      SELECT ... LIMIT 10 for rows;
                     1 graph component, 2 toggle,   read-only Cypher over the
                     1 caption                      NeoCarta Database / Schema /
                                                    Table / Column nodes
Operational graph    2 selectbox, 1 multiselect,    bounded MATCH from the
                     1 graph component,             selected account, capped by
                     1 property panel,              depth and node budget;
                     1 graph component, 2 toggle,   read-only Cypher over the
                     1 caption                      NeoCarta Node / Relationship
                                                    / Property nodes, filtered
                                                    by source_scope
Ask                  1 pills, 1 text_input,         one MCP stdio session per
                     1 button, st.status per tool   click, then a serving
                     call, 1 grounding table,       endpoint, then the warehouse
                     2 code blocks, 2 buttons,      and the graph
                     2 dataframes
```

Use `neo4j-viz` for all three graph surfaces. The sibling `ot-cyber-cfihos20`
app already renders Neo4j results this way with `from_neo4j` into
`components.html`, so this needs no spike.

The two map halves share one rendering function and one trace control,
parameterised by which node labels they pull. They are the same canvas over a
different slice of the same store, and writing them twice is how they drift
apart.

## Build state

The NeoCarta store is built from the documented Makefile sequence before the
app runs:

```bash
make neo4j-up
make ingest
make neo4j-schema-ingest
make validate
make validate-neo4j-schema
make validate-mcp
```

NeoCarta's catalog loader is additive, so a refresh needs
`docker compose --env-file .env down --volumes` followed by a rebuild. Show
that command for a loopback store only. The UI must never offer a destructive
action against a remote store.

## Deferred

```text
Deferred item                  Why it waits
---------------------------    -----------------------------------------------
Subgraph canvas on Ask         The dataframe answers the question. A rendered
                               ring is a fourth canvas plus selection state
                               after the result, and it can be added once the
                               dataframe version has been shown to feel flat.
Guided build walkthrough       Subprocess orchestration, streamed log parsing,
                               and partial-failure states are the most fragile
                               code in the app. The Makefile already works.
Free-form Cypher editor        The Ask page already runs generated Cypher under
                               a read-only user. A hand-editable box adds
                               surface area and no narrative.
Cross-source join assertion    The map does not claim that
                               gold_accounts.community_id and
                               :Account.community_id are one population. Making
                               it claim that is a modelling project.
Run history                    Nothing in the demo needs evidence to persist
                               across a browser session.
```
