# Semantic Investigation Copilot UI

A five-page Streamlit app that follows one thread end to end: the financial
data as it actually sits in two systems, the semantic map NeoCarta builds over
each of them, and a question answered by retrieving that map and running the
query it grounds.

Each of the first four pages holds one subject and one visual. The data and the
map are shown separately per system so neither screen is crowded, and the two
systems come back together on the last page, where a single question retrieves
both halves of the map and queries both sources.

The app reads three sources, all read-only:

| Source | What the app reads | Used on |
|---|---|---|
| Databricks SQL warehouse | Table and column metadata, sample rows, generated query results | Lakehouse data, Ask |
| Operational Neo4j (Finance Genie) | A bounded subgraph, and the generated Cypher result | Operational graph, Ask |
| NeoCarta semantic store | The metadata graph and the MCP retrieval tools | Catalog map, Graph map, Ask |

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

## 95-second demo script

```text
 0:00  Open the app. It lands on Lakehouse data.
       Say: here are the accounts, as tables.
       Point at: the six declared foreign keys, then the sample rows of
       gold_accounts with real balances and risk scores.

 0:15  Click Operational graph.
       Say: here are the same accounts, as a graph. Neither system knows
       about the other.
       Point at: the transfer subgraph around one account.

 0:35  Click Catalog map.
       Say: NeoCarta read the lakehouse and wrote this. Every table and
       column is now a node.
       Point at: gold_accounts and its columns.

 0:50  Click Graph map.
       Say: it read the graph and wrote this the same way. Same store, same
       vocabulary, both systems.
       Point at: :Account, its properties, and TRANSFERRED_TO.

 1:05  Click Ask. Pick "Which fraud rings share an identity cluster?"
       Say: one question, and it retrieves from both halves before it writes
       anything.
       Point at: the MCP tools firing, then the generated SQL and Cypher
       built from exactly those retrieved names.

 1:25  The results land.
       Say: every table, column, label, and relationship in those two queries
       came out of the map. Nothing was guessed.

 1:35  Stop.
```

Anything not on this path is optional. Cut it before adding to it.

## App shell

```text
+--------------------------------------------------------------------------------+
|  Finance Genie · Semantic Investigation Copilot                                |
+--------------------------+-----------------------------------------------------+
| SIDEBAR                  | PAGE                                                |
|                          |                                                     |
| [✓] Lakehouse            |  Page-specific content                              |
| [✓] Operational graph    |                                                     |
| [✓] Semantic map         |                                                     |
|                          |                                                     |
| THE DATA                 |                                                     |
|   Lakehouse data         |                                                     |
|   Operational graph      |                                                     |
|                          |                                                     |
| THE SEMANTIC MAP         |                                                     |
|   Catalog map            |                                                     |
|   Graph map              |                                                     |
|                          |                                                     |
|   Ask                    |                                                     |
|                          |                                                     |
| [Connections v]          |                                                     |
| [Store not built? v]     |                                                     |
+--------------------------+-----------------------------------------------------+
```

Three connection badges, one per source. A page that needs a source it cannot
reach says so in place and leaves the other pages usable. The `Connections`
expander holds hosts, catalog, schema, and database names. The
`Store not built?` expander shows the Makefile sequence as copyable text and
runs nothing.

The two group headings carry the argument before anyone clicks anything. Two
systems under `THE DATA`, the same two under `THE SEMANTIC MAP`, and one `Ask`
that needs both.

The store-contract comparison from the earlier draft moves out of the UI.
`make validate` already reports expected against found, and a passing test
suite is not a demo screen.

## 1. Lakehouse data

The accounts as tables. Full width, one subject.

```text
Lakehouse data              graph-on-databricks.graph-enriched-schema · warehouse

SILVER
 +----------------+  +----------------+  +----------------+  +----------------+
 |    accounts    |  |   customers    |  |   merchants    |  | account_labels |
 |  account_id PK |  |  account_id FK |  | merchant_id PK |  |  account_id FK |
 |  account_type  |  |  customer_name |  |  category      |  |  is_fraud      |
 |  balance       |  +----------------+  +----------------+  +----------------+
 |  region        |
 +----------------+  +----------------+  +----------------+
                     |  transactions  |  | account_links  |
                     |  account_id FK |  | src_account_id |
                     |  merchant_id FK|  | dst_account_id |
                     |  amount        |  |  amount        |
                     |  txn_timestamp |  | transfer_ts    |
                     +----------------+  +----------------+

 Declared foreign keys, six RELY constraints
   customers.account_id          -> accounts.account_id
   transactions.account_id       -> accounts.account_id
   transactions.merchant_id      -> merchants.merchant_id
   account_links.src_account_id  -> accounts.account_id
   account_links.dst_account_id  -> accounts.account_id
   account_labels.account_id     -> accounts.account_id

GOLD, written back from the graph
 +-----------------------------+ +---------------------------+ +----------------+
 | gold_accounts               | | gold_fraud_ring_          | | gold_account_  |
 |  risk_score                 | | communities               | | similarity_    |
 |  community_id               | |  community_id             | | pairs          |
 |  identity_cluster_id        | |  member_count             | |  similarity_   |
 |  fraud_risk_tier            | |  is_ring_candidate        | |   score        |
 +-----------------------------+ +---------------------------+ +----------------+

[Table: gold_accounts v]                                      [Sample 10 rows]

+------------+----------+------------+--------------+------------------+
| account_id | balance  | risk_score | community_id | fraud_risk_tier  |
+------------+----------+------------+--------------+------------------+
| 8842       | 41208.55 | 3.42       | 17           | high             |
| 8843       |  2190.10 | 0.11       | 17           | low              |
| ...        |          |            |              |                  |
+------------+----------+------------+--------------+------------------+

17 tables in scope. Column comments shown on hover.
```

Tables are boxes and the six declared `RELY` foreign keys are edges. Those six
constraints are the same six `REFERENCES` edges NeoCarta retains, so the
Catalog map page can show the identical structure.

The Gold tables sit apart because they are graph output that came back into the
lakehouse. That is the only reason the two systems have anything to say to each
other, and it is worth one sentence out loud.

Sample rows come from `SELECT ... LIMIT 10` against the chosen table. Ten rows
of real balances and risk scores do more work than any count.

## 2. Operational graph

The same accounts as a graph. Full width, one canvas, rendered live.

```text
Operational graph                                       neo4j @ <source-host>

[Account: 8842 v]  [Depth: 2 v]  [Types: TRANSFERRED_TO, OWNS, HAS_PHONE v]

                      (Phone: ***4417)      (Address: ***Elm St)
                             ^                       ^
                             | HAS_PHONE             | HAS_ADDRESS
                             |                       |
                        (Customer: C-2291)      (Customer: C-3380)
                             |                       |
                             | OWNS                  | OWNS
                             v                       v
     (Account 8842) --TRANSFERRED_TO--> (Account 8843) --TRANSFERRED_TO--> ...
           |                                   ^
           +-----------SIMILAR_TO--------------+

Legend  (Account) risk_score high / low    (Customer)   (Phone)   (Address)

Selected: Account 8842 · risk_score 3.42 · community_id 17
Showing 34 of 128 nodes within depth 2. Capped at 150 nodes.
```

One selected account, expanded to a capped depth. State the cap in the caption
every time. A demo that tries to draw the whole transfer network draws a
hairball.

Nodes are coloured by `risk_score`, which puts the graph-derived signal on
screen before anyone has explained what PageRank is. Selecting a node shows its
properties beside the canvas.

The relationship-type filter matters here. Turning `HAS_PHONE` and
`HAS_ADDRESS` on and off separates the transfer network from the identity
network, and those are two different fraud stories in the same graph.

## 3. Catalog map

What NeoCarta wrote after reading the lakehouse. Same subject as page 1, now as
metadata nodes.

```text
Catalog map                       NeoCarta store · neo4j @ 127.0.0.1
                                  Describes: the Lakehouse data page

[Trace a table: gold_accounts v]   [Show columns ✓]   [Show REFERENCES ✓]

  (Database: graph-on-databricks)
        | HAS_SCHEMA
        v
  (Schema: graph-enriched-schema)
        | HAS_TABLE
        +--> (Table: accounts)
        |        | HAS_COLUMN
        |        +--> (Column: account_id)
        |        +--> (Column: balance)
        |        +--> (Column: region)
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

`Trace a table` is the control that earns the page. Pick a table and the map
dims to that `Table`, its `Column` nodes, and its `REFERENCES` edges. Tracing
`gold_accounts` right after looking at its sample rows on page 1 is the whole
capture argument in two clicks.

`Describes:` in the header is the link back to page 1. Every map page carries
one, because a metadata graph with no stated subject is just an abstract
diagram.

Counts belong in the caption under the trace, not in metric tiles.

## 4. Graph map

What NeoCarta wrote after reading the operational graph. Drawn with the same
idiom as page 3, deliberately.

```text
Graph map                         NeoCarta store · neo4j @ 127.0.0.1
                                  Describes: the Operational graph page

[Trace a label: Account v]   [Show properties ✓]   [Show endpoints ✓]

  (Database: finance-genie)
        | HAS_SCHEMA
        v
  (Schema: <source-scope>)
        | HAS_NODE
        +--> (Node: Account)                 <-- traced
        |        | HAS_PROPERTY
        |        +--> (Property: account_id :: String)
        |        +--> (Property: risk_score :: Float)
        |        +--> (Property: community_id :: Integer)
        |
        +--> (Node: Customer)
        +--> (Node: Phone)
        +--> (Node: Address)
        |
        | HAS_RELATIONSHIP
        +--> (Relationship: TRANSFERRED_TO)
        |        | HAS_SOURCE_NODE -> Account
        |        | HAS_TARGET_NODE -> Account
        +--> (Relationship: OWNS)
        |        | HAS_SOURCE_NODE -> Customer
        |        | HAS_TARGET_NODE -> Account
        +--> (Relationship: HAS_PHONE)
        +--> (Relationship: HAS_ADDRESS)
        +--> (Relationship: SIMILAR_TO)

Traced: Account · 3 reported properties · source of 2 relationship types
Endpoint pairs are statistics-based. No property values retained.
```

The page is the mirror of page 3 on purpose. An audience that just traced a
table and watched its columns light up traces a label here and watches its
properties do the same thing. The two systems are in one store at the same
fidelity, and the identical layout is what proves it without anyone asserting
it.

Endpoint pairs come from `db.schema.visualization` and are statistics-based.
Neo4j reports possible label combinations rather than observed paths, and the
page says so once. When visualization was unavailable at ingest, the persisted
map records that. Drop the endpoint edges, keep the node and relationship
inventory, and state that source permissions did not allow endpoint metadata.
Do not infer endpoints from names.

Splitting the map across two pages costs the single-canvas moment the earlier
draft had. The next page pays it back. Ask retrieves from both halves in one
question, so the two systems reunite where it matters, over a result rather
than over a diagram.

## 5. Ask

A question goes in. Both halves of the map are retrieved, the queries are built
from what came back, they run against the two systems from pages 1 and 2, and
the answers land.

```text
Ask

[ Which fraud rings share an identity cluster?            v ]  [Ask]
  or type your own: [                                       ]

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
   | FROM gold_fraud_ring_communities r|   | RETURN a, b LIMIT 200         |
   | JOIN gold_accounts a              |   +-------------------------------+
   |   ON a.community_id =             |
   |      r.community_id               |   [Run]  read-only transaction
   | WHERE r.is_ring_candidate         |
   | GROUP BY 1, 2                     |
   +-----------------------------------+
   [Run]  read-only warehouse

4  ANSWER

   +--------------+--------------+-------------------+    rendered subgraph for
   | community_id | member_count | identity_clusters |    the selected ring
   +--------------+--------------+-------------------+
   | 17           | 112          | 4                 |
   | 33           |  87          | 1                 |
   +--------------+--------------+-------------------+

   The map supplied the names. It does not assert that
   gold_accounts.community_id and :Account.community_id are the same
   population. A reviewer confirms that join.
```

Step 2 is the load-bearing panel. It is the bridge from retrieval to execution,
and it is what makes the demo different from watching any agent write SQL. Each
identifier in the generated queries links back to the tool call that produced
it. A name that appears in a query without a source in step 1 is a bug and the
panel should mark it.

The question input is a dropdown of three curated questions plus a free text
box. Full-text search misses on unlucky phrasing, so the preset carries the
demo and the box carries the follow-up. This resolves the earlier draft's open
question 2.

Query generation calls a Databricks serving endpoint with the retrieved context
and the two schemas as the only source of names. Keep the prompt in one module
and keep it short. Show the generated query before running it, always.

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
operational graph from being mistaken for the metadata store. They are unchanged.

Rejecting write clauses by string matching does not work. Do not try.

## Implementation boundary

```text
Page                 Widgets                        Backing call
------------------   ----------------------------   ---------------------------
Sidebar              3 status badges, 2 expanders   one probe per source
Lakehouse data       1 ER diagram, 1 selectbox,     information_schema for the
                     1 dataframe                    ER shape and the six RELY
                                                    constraints, SELECT ... LIMIT
                                                    10 for rows
Operational graph    1 graph component,             bounded MATCH from the
                     2 selectbox, 1 multiselect,    selected account, capped by
                     1 property panel               depth and node budget
Catalog map          1 graph component, 1 select,   read-only Cypher over the
                     2 toggle, 1 caption            NeoCarta Database / Schema /
                                                    Table / Column nodes
Graph map            1 graph component, 1 select,   read-only Cypher over the
                     2 toggle, 1 caption            NeoCarta Node / Relationship
                                                    / Property nodes, filtered by
                                                    source_scope
Ask                  1 selectbox, 1 text_input,     MCP stdio session, then a
                     st.status per tool call,       serving endpoint, then the
                     2 code blocks, 2 buttons,      warehouse and the graph
                     1 dataframe, 1 graph component
```

Call the MCP server exactly the way `validate_mcp.py` does, over stdio with
`StdioServerParameters(command=sys.executable, args=["-m", "mcp_server"],
cwd=DEMO_DIR)`. Cache one client session per Streamlit session and reuse it.
Both full-text tools return records carrying `database_name` and `schema_name`.
Filter them to the configured catalog and schema the way
`validate_mcp.records_for_source` does.

Use `neo4j-viz` for all four graph surfaces. The sibling `ot-cyber-cfihos20`
app already renders Neo4j results this way with `from_neo4j` into
`components.html`, so this needs no spike. That resolves the earlier draft's
open question 3.

Pages 3 and 4 share one rendering function and one trace control, parameterised
by which node labels they pull. They are the same screen over a different slice
of the same store, and writing them twice is how they drift apart.

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

## Open question

**App name.** The README calls this the Finance Genie Lakehouse Metadata Demo,
which no longer describes what the app does. The Ask page now retrieves,
generates, and executes, so "Copilot" is earned. Confirm which name ships.

## Deferred

```text
Deferred item                  Why it waits
---------------------------    -----------------------------------------------
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
