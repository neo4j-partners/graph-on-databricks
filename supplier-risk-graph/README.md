# Finding the Risk Your Columns Cannot See

**Governed, explainable supply-and-credit risk across a Neo4j knowledge graph and a Databricks lakehouse.**

## The business story

A global beverage producer runs two mature risk programs, procurement scoring for suppliers and credit control for customers. Both are healthy. Both grade entities one at a time, and the exposures that matter are structural.

- **Supplier concentration risk, hidden in the sub-tier:** five qualified, separately-contracted tier-1 bottle suppliers in the Americas all buy container glass from processors that melt at one furnace, Cascade Glassworks, which scores mid-tier and never trips a report. The producer knows its tier-1 suppliers. It does not know who *they* buy from.
- **Group credit exposure, hidden in the ownership structure:** Jade Beverage Distribution is a spotless platinum account, assessed standalone, owned 85% by a holding group whose other arms own the four companies that already defaulted. Every late-payer report puts Jade in the clear, right up until the parent pulls it down.
- **Customer deterioration, visible before the rule trips:** the Delinquent Customer rule fires only once the last three invoices each run more than 60 days late. Risky Customer restores the missing early warning: an active, not-yet-delinquent account is risky when at least half of its ten nearest payment-behavior neighbours are already Delinquent.

All three risks are already in the data, and none is visible from a single column. The first two live in connections, who supplies whom and who owns whom. The third emerges from the payment-behavior neighbourhood around each customer.

## The value

- **Quantify revenue at risk, not just supplier scores:** sub-tier visibility turns a diversified-looking supply base into a named single point of failure with a revenue figure attached, before the plant stops.
- **Assess credit by group, not by account:** exposure aggregates across entities under common ownership, the way a lender assesses connected clients, so a clean account inside a failing group stops reading as clean.
- **Answer in governed business language:** Critical Supplier, Ownership Risk, and Risky Customer resolve from definitions, rules, and thresholds the business owns, so two people asking the same question get the same answer.
- **Show the work:** every materialized classification traces back through its rule to the physical Unity Catalog table behind it. Ownership Risk retains the ownership path behind its live decision, and Risky Customer retains the named delinquent neighbours behind its score.
- **Keep the lakehouse as the system of record:** the graph adds meaning on top of Databricks rather than replacing it. No second source of truth.

## What this repo is

A runnable demo of that scenario. One set of CSVs in `data/` feeds both sides, so the two layers always agree and the demo runs offline.

- **Databricks owns the facts:** Unity Catalog Delta tables hold customers, suppliers, invoices, revenue, compliance findings, and the supplier-to-supplier links.
- **Neo4j owns the meaning:** the knowledge graph mirrors those facts and adds the governed definitions, thresholds, rules, and the multi-hop lineage tying every classification back to its physical table.
- **Suppliers specialize by subcategory:** glass bottles, malt, hops, cans, labels, and the tiers behind the bottles, running from feedstock through the furnaces to the processors. `COMMODITY_SUBCATEGORIES` in the generator sets which subcategories make up a commodity, and a supply path carries that commodity only when every supplier on it trades in one of them.
- **Customers are the drinks trade:** distributors, wholesalers, supermarket groups, and bar and hotel chains.

## The two engines

- **Genie Agent:** the lakehouse-only engine. A Databricks Genie space scoped to the Unity Catalog instance tables and nothing else.
- **Genie One:** the same Genie Agent under a supervisor that can also call a read-only Neo4j MCP server over the knowledge graph.

Both answer the everyday risk questions. The payoff is three graph-native questions the lakehouse-only engine cannot answer reproducibly, because their definitions live only in the graph.

## How the graph finds them

In a lakehouse the facts are clean but the meaning is scattered across ad hoc SQL, notebooks, and tribal knowledge. None of the three conclusions below is a column: each needs a graph computation plus a governed cutoff the lakehouse-only engine cannot discover from the instance tables.

### Story 1: the hidden glassworks

- **Who:** Cascade Glassworks, SUP-901.
- **Business term:** Critical Supplier.
- **Algorithm:** betweenness centrality over the multi-tier supply chain.
- **What it finds:** the sub-tier supplier every commodity-carrying glass path into the Americas runs through, sitting a tier back from anything that unit buys from directly.
- **The decoy:** counting connections does not find it. The most connected supplier is somebody else, which the build asserts, and Cascade sells to no business unit, so the supplier-to-unit bridge table never names it.

### Story 2: the clean payer in a bad group

- **Who:** Jade Beverage Distribution, CUST-904.
- **Business term:** Ownership Risk.
- **Algorithm:** stake-weighted personalized PageRank over the ownership edges.
- **What it finds:** group credit exposure inherited through the parent, not through Jade's own record.
- **The decoy:** ranking by distance to the nearest default returns someone else. Nothing within two hops of Jade has failed, and the accounts sitting next to a default hold only a few percent of it.

### Story 3: the warning before delinquency

- **Who:** a derived cohort, not a hand-picked protagonist. The current build includes planted near-miss accounts and at least one emergent customer found by the metric.
- **Business term:** Risky Customer.
- **Algorithm:** deterministic GDS kNN over a standardized two-feature payment-behavior vector.
- **What it finds:** active customers that have not tripped the Delinquent Customer rule, but whose ten nearest behavioural neighbours are already majority delinquent.
- **Why it is explainable:** every classification retains the delinquent neighbours that contributed to the score, their rank, and their similarity.

### Why none is findable in the lakehouse

- **The math is not the barrier:** all three algorithms are expressible outside the graph.
- **No BI tool reaches for them unprompted:** an all-pairs shortest-path computation, iterative weighted propagation, or governed nearest-neighbour screen is not what a natural-language question turns into.
- **The cutoff lives in the graph:** what decides each answer is a governed threshold, not a column to sort on.
- **Where the live figures are:** [`data/ground_truth.json`](data/ground_truth.json) carries the two structural stories, including `story1_hidden_glassworks.bu03_last_quarter_revenue` and `story2_clean_payer.jade_open_invoice_balance`. The Risky Customer cohort is derived rather than planted, so `gds.py` prints its current members, scores, and planted-versus-emergent status on every run.

See [`DEMO.md`](DEMO.md) for the walkthrough and the two-engine comparison, and [`DATA_ARCHITECTURE.md`](DATA_ARCHITECTURE.md) for the complete data model.

## The two-layer model

- **Instance layer:** a mirror of the lakehouse tables, including the two structural edge types, supplier-to-supplier `SUPPLIES` for the multi-tier chain and customer-to-customer `OWNED_BY` for ownership stakes. Both are uploaded to Unity Catalog too, so the lakehouse-only engine has the raw networks in full. What it lacks is the computation over them.
- **Knowledge layer:** entities, business terms, business rules, policies, thresholds, and the semantic mapping to the real Unity Catalog tables.
- **`REALIZED_AS`:** links a logical entity to its physical instances.
- **`CLASSIFIED_AS`:** records a classification with provenance. The four column-findable terms carry these edges, and `gds.py` adds the derived Critical Supplier and Risky Customer cohorts from their governed thresholds. Ownership Risk alone carries none and is resolved live.
- **Naming:** graph properties and instance tables both use camelCase, so the Cypher in the walkthrough runs unchanged against either side.

## The dataset

Generated from scratch with a fixed seed of 42 and an as-of date defaulting to today, so the demo shows forward-looking risk rather than a stale snapshot. Pass `--as-of YYYY-MM-DD` to `generate_data.py` for a reproducible build.

- **What is stable:** names, ids, and the hand-set business thresholds come from the seed and never move.
- **What is re-derived every run:** every date, euro amount, row count, and resolved graph-native cutoff.
- **The seed is load-bearing and must not be changed.** `make demo` regenerates with seed 42 every time and only the as-of date moves, so the supply topology, the betweenness ranks, and the Critical Supplier cohort are identical on every build. Story 1 rests on that specific arrangement. Editing `SEED` in `generate_data.py` is a reseed, not a refresh, and it can move who sits where, so treat it as a change to the story that has to be re-probed. Regenerating is safe; reseeding is not.
- **Do not read live figures out of this file.** `generate_data.py` rewrites [`data/ground_truth.json`](data/ground_truth.json) on every run, stamped with the `as_of_date` it used, and that file is the reference for counts, quarterly revenue, and exposure amounts. Its `summary` block holds the per-table and per-edge counts. The docs quote only values that cannot drift.
- **Scale:** a few hundred customers and a couple of hundred suppliers, sized from the generator's background population constants with the protagonists added on top. Late payers, overdue balances, supplier risk scores, and compliance findings carry a believable spread, so all three contrasts land against ordinary background risk.
- **Two webbed edge layers hide the plants:** supplier links form regional clusters, each grown by preferential attachment and then given chords beyond its spanning tree so interior traffic always has more than one route. Cross-cluster bridges join the clusters, every bridge a different supplier and none of them trading glass, so no single supplier separates the network and the commodity-scoped exposure measure has nowhere to leak. The constants are `SUP_CLUSTERS`, `SUP_WEB_CHORD_RATIO`, and `SUP_INTER_CLUSTER_BRIDGES` in the generator. Ownership links form weighted multi-parent groups, so Kestrel is one of many owned groups rather than the only one. The webbing is what makes the planted subgraphs look ordinary to the algorithms, so only the real metric singles each out.

## How to run

Copy the environment sample and fill it in. The Neo4j section drives `load.py` and `gds.py`, the Databricks section drives `upload.py`, and only `generate_data.py` runs without either.

```bash
cp .env.sample .env
# edit .env: NEO4J_URI, NEO4J_PASSWORD, and the Databricks / Unity Catalog values
```

**The four pipeline steps are one unit and run strictly in order.** The supported path is a single target:

```bash
make demo
```

Each step depends on the state the previous one leaves behind, and two governing thresholds do not exist until step 3 computes them. **Partial runs are the failure mode to avoid:** the generator re-derives every date from today, so re-running it alone leaves Neo4j and Unity Catalog holding the previous run's data while `ground_truth.json` claims today's.

Running the steps by hand is fine as long as the order holds:

```bash
uv run generate_data.py   # writes data/ CSVs + ground_truth.json
uv run load.py            # WIPES Neo4j (DETACH DELETE all) and reloads
uv run gds.py             # computes betweenness + PageRank + customer kNN
uv run upload.py          # rebuilds Unity Catalog tables + metric view
```

1. **Generate the data:** writes the 14 node CSVs, the relationship CSVs, the `supply_relationships` link CSV, the `supplier_business_units` lakehouse bridge CSV, and `ground_truth.json` to `data/`.

2. **Load Neo4j:** creates id uniqueness constraints and loads nodes and relationships in `UNWIND` batches, including the `SUPPLIES` and `OWNED_BY` same-graph edges. **Destructive to the graph:** the loader `DETACH DELETE`s every node in the target database first, so point it at a database dedicated to this demo, never a shared one. `uv run load.py --check` validates the CSVs without touching the database.

3. **Run the GDS analytics:** betweenness centrality over the supplier network, personalized PageRank over the ownership network, and payment-behavior kNN for the Risky Customer early warning. Results are written back as Neo4j node properties only and never synced to Delta. The kNN pass also writes explainable `SIMILAR_PAYMENT_BEHAVIOR` edges to the delinquent neighbours behind each classified customer. This step resolves THR-03 and THR-04 and verifies the pre-authored THR-05 value. **Until it runs, the three graph-native demo beats are incomplete.**

4. **Upload to Unity Catalog:** uploads the instance CSVs as Delta tables, including `supply_relationships` and `owned_by`, applies the semantic metadata Genie reads, and builds the `customer_risk_exposure` metric view. It also drops any stale graph-derived gold table a prior build left behind, so the graph's conclusions never sit in a column. Comments and the metric view are rebuilt on every run because `CREATE OR REPLACE TABLE` drops them, which is also what makes the script idempotent with no bookkeeping.

Quick checks before you walk through anything live:

- **Referential integrity:** `uv run load.py --check` reports node and relationship totals and confirms every relationship endpoint resolves.
- **Story 1:** Cascade Glassworks (SUP-901) clears the Supply Concentration Threshold in a cohort with more than one member, and the five tier-1 bottle suppliers score clean. Where Cascade ranks on betweenness is printed to the build log and never asserted: `assert_betweenness` reports the ranking rather than requiring a winner.
- **Story 2:** Jade Beverage Distribution (CUST-904) is the top *trading* customer by stake-weighted PageRank while its own record stays clean. The trading qualifier is load-bearing: Kestrel, Harbour, and Tern score higher and are correctly excluded, because they carry no invoices, so there is no receivable to act on and no facility to cut.
- **Story 3:** Risky Customer is a multi-customer early-warning cohort containing at least one planted near-miss account and no already-delinquent, defaulted, or invoice-less customer. The build log prints the complete cohort and marks each member as planted or emergent.

## The threshold lifecycle

`data/thresholds.csv` holds five governing cutoffs filled at two different times, which is why run order matters. The demo Cypher reads each cutoff from the live `Threshold` node, so the values only need to be correct in the graph, which they are once `gds.py` has run.

- **THR-01 Supplier Risk Threshold (70)** and **THR-02 Late Payment Threshold (60)**: hand-set business constants. The generator writes them with values and `load.py` loads them as-is. Edit these in the generator to change what "high-risk supplier" or "delinquent customer" means.
- **THR-03 Supply Concentration Threshold** and **THR-04 Ownership Contagion Threshold**: graph-native. The generator writes their `value` blank and `load.py` creates the nodes with a null value, because a cutoff cannot be placed until the GDS scores exist. Do not hand-edit these two. `gds.py` overwrites them on every run.
- **How THR-03 and THR-04 differ**, which is the point of THR-03's `basis` column: THR-03's governed parameter is a percentile of supply betweenness, hand-set in the generator before any score is computed and before the topology it applies to exists, so it lands in git ahead of the data. The run resolves that percentile against its own distribution, making the resolved cutoff an output of the build rather than a target it was aimed at. It catches whoever is in the tail, a cohort rather than a name, and the build fails if that cohort has fewer than two members. If the protagonist fails to clear the percentile, the topology gets fixed and the percentile does not move. THR-04 is placed from the computed PageRank distribution instead, and Story 2 is out of scope for change.
- **THR-05 Customer Similarity Threshold (0.5)**: authored before kNN runs. It means at least half of an eligible customer's ten nearest payment-behavior neighbours are already Delinquent. Because both the threshold and the metric are shares on the same scale, no fitted cutoff is needed. `gds.py` verifies that the live threshold and rule carry the value it screened against.
- **`thresholds.csv` is graph-only and never uploaded to Unity Catalog.** This is deliberate: if the graph-native cutoffs became Delta columns, the lakehouse-only engine could read them and the demo would tie.

## Set up the two engines (one-time)

Do this once before the call. The point of the demo is that Genie Agent cannot resolve the three graph-native questions reproducibly, so its space must not be given the graph's answers.

### Genie Agent (the lakehouse-only engine)

Scope this space to the instance tables and nothing else.

1. **Confirm `upload.py` published these into `graph-on-databricks.supplier_risk`:**
   - **Core instance tables:** `customers`, `suppliers`, `business_units`, `invoices`, `revenue_entries`, `compliance_findings`. Columns are camelCase and share keys where they join: `invoices.customerId` and `compliance_findings.customerId` to `customers.id`; `revenue_entries.businessUnitId` and `customers.businessUnitId` to `business_units.id`.
   - **`supply_relationships`** (`fromSupplierId`, `toSupplierId`): the raw supplier-to-supplier links, even though no column captures the multi-tier structure they form.
   - **`owned_by`** (`customer_id`, `parent_customer_id`, `ownershipPct`): the full ownership structure and every stake. Included for the same reason: the demo is won on a computation the lakehouse will not perform, not by withholding a table.
   - **`supplier_business_units`** (`supplierId`, `businessUnitId`): the many-to-many supplier-to-unit bridge.
   - **`customer_risk_exposure`:** a metric view over `customers`, joined to `invoices` and `compliance_findings` with `cardinality: one_to_many` on each. Two independent one-to-many branches hang off `customers`, and joining both in one pass multiplies each by the other's row count. The metric view aggregates each measure at its own source grain, so the fanout stops being something a query can express. This is a SQL-correctness fix, not an answer: every measure in it is an aggregate over columns Genie could already read.
   - **No gold tables.** Earlier builds published `classifications` and `business_unit_exposure` and kept them out of the space by hand. `upload.py` no longer produces either and drops any stale copy on upload, so the graph's conclusions never reach a column.
   - **No constraints.** `upload.py` writes table and column comments but declares no primary or foreign keys. Databricks' Genie guidance ranks descriptions, metric views, and example SQL as the levers that matter. The fanout constraints were meant to prevent is prevented structurally by the metric view instead.

2. **Create a Genie space** scoped to the `supplier_risk` schema with every instance table: `customers`, `suppliers`, `business_units`, `invoices`, `revenue_entries`, `compliance_findings`, `supply_relationships`, `owned_by`, the `supplier_business_units` bridge, and the `customer_risk_exposure` metric view. The fairness rule is non-negotiable: both engines get every table, so the gap is grounding, not access.

   **`compliance_findings` and `owned_by` are both in the space**, given to the lakehouse-only engine like every other instance table. Neither carries a graph-derived conclusion: `owned_by` is the raw ownership stakes, and `compliance_findings` is raw instance data that already feeds the `customer_risk_exposure` metric view, which is itself in the space. When a question needs aggregated finding counts, prefer the metric view's `open_finding_count`, which aggregates each measure at its own source grain and so cannot fan a customer's finding count out by its invoice count the way a raw two-branch join off `customers` can. The `ComplianceFinding` nodes stay in the graph for the same reason the table stays in Unity Catalog: removing them would leave ENT-06 mapping to nothing and POL-03 Compliance (KYC) governing no data. `constrains.csv` points POL-03 at ENT-01 Customer, not ENT-06, so DEMO.md's policy-scope example does not depend on the finding nodes.

3. **The pipeline materializes no gold tables.** Earlier builds wrote `classifications` and `business_unit_exposure` back into Delta and fenced them out of the space by hand. Materializing the graph's answers into a column is write-back leakage, so those answers now live only in the graph: `upload.py` no longer builds either table and drops any stale copy on upload. `guard.py` keeps both names in its banned list as a defensive backstop, and for the same reason the GDS scores are never synced to Delta.

4. **Add sample-question SQL** for a handful of the column-findable questions. Databricks ranks these trusted assets above text instructions, so they are the strongest lever in the space. Cover the mechanics the stories need: a region-scoped supplier query through the `supplier_business_units` bridge, customer exposure and compliance findings via the metric view, overdue balances by customer, revenue by business unit and quarter deriving the quarter from the monthly `period` date, and suppliers above a governed threshold passed as a concrete value.

   **What the examples must not teach.** No example may join a supplier to a supplier, walk `supply_relationships`, join or aggregate `owned_by`, or read `defaultedPeriod`. Nothing may group customers into ownership groups or rank them by proximity to a default. Any of these hands the lakehouse-only engine the shape behind Story 1 or Story 2. For the same reason, rank an open-balance example by *overdue* balance rather than total open balance: ranking by open balance puts Jade on top as a standing trusted asset, which primes Genie to volunteer that account for the open-ended credit-review question that is precisely Story 2's miss. Genie can still compute Jade's drawn balance when a question names Jade, which is what beat 4 needs.

5. **Set the space instructions** from the neutral Genie space description block in [`DEMO.md`](DEMO.md) under **What to put in the Genie space description**. It carries only facts about the data and does not tell the space which questions to refuse, so the same space serves both the standalone runs and Genie One. The routing lives in the supervisor's tool descriptions.

6. **Publish and smoke-test the space** before the call.

### Genie One (Genie Agent plus the graph)

1. **Stand up a read-only Neo4j MCP server** against the loaded graph, the same database `load.py` and `gds.py` wrote. It must emit read Cypher only.
2. **Register both tools with the supervisor:** the Genie Agent space above and the Neo4j MCP server.
3. **Set the descriptions the supervisor routes on,** both in [`DEMO.md`](DEMO.md). Paste the block under **What to put in the MCP server description** onto the Neo4j MCP server or tool. Set the Genie tool's description from the **Supervisor routing (Genie One only)** note: facts, counts, and rankings go to Genie; definitions, relationships, and provenance go to the graph. The Genie space instructions themselves stay neutral.
4. **Smoke-test both routes:** a plain fact question should land on Genie, and a Critical Supplier, Ownership Risk, or Risky Customer question should route to the graph.

For the questions to ask, how Genie One consumes the governed semantics, and the deeper multi-agent supervisor story, see [`DEMO.md`](DEMO.md).

## Adding customer risk to the BU-03 supply chain query

The Story 1 browser query walks the glass chain into BU-03 and hangs the Critical Supplier definition off it:

```cypher
MATCH (bu:BusinessUnit {id:'BU-03'})<-[s1:SUPPLIES]-(bottle:Supplier {subcategory:'glass bottles'})
OPTIONAL MATCH (bottle)<-[s2:SUPPLIES]-(container:Supplier {subcategory:'container glass'})
OPTIONAL MATCH (container)<-[s3:SUPPLIES]-(raw:Supplier {subcategory:'raw glass'})
OPTIONAL MATCH (raw)-[cls1:CLASSIFIED_AS]->(term:BusinessTerm {id:'TERM-05'})
OPTIONAL MATCH (container)-[cls2:CLASSIFIED_AS]->(term)
OPTIONAL MATCH (bottle)-[cls3:CLASSIFIED_AS]->(term)
OPTIONAL MATCH (term)-[def:DEFINED_BY]->(rule:BusinessRule)-[ut:USES_THRESHOLD]->(th:Threshold)
RETURN * LIMIT 50
```

That is the supply side only. Customer risk hangs off the same `BusinessUnit` anchor from the other direction: suppliers reach a unit through `SUPPLIES`, customers through `BELONGS_TO`. Both legs terminate in the same knowledge layer, so customer terms resolve their rule and cutoff through the identical `DEFINED_BY` and `USES_THRESHOLD` hops.

### Which customer terms are edges and which are traversals

Four business terms carry customer risk, and they are not reachable the same way.

- **TERM-02 Defaulted Customer, TERM-03 Delinquent Customer, TERM-07 Risky Customer:** carry `CLASSIFIED_AS` edges on the loaded graph, so a plain pattern matches them. `load.py` writes the first two from `classified_as.csv`; `gds.py` materializes TERM-07 after the kNN pass.
- **TERM-06 Ownership Risk:** carries no `CLASSIFIED_AS` edge at all. It stays a live traversal against the PageRank property and THR-04, so it needs its own query shape.
- **TERM-01 Strategic Account:** also sits on customers, but it is a commercial tag rather than a risk classification. Leave it out unless you want it on screen.

### The customer leg

Wrap each leg in its own scoped subquery. Appending the customer `OPTIONAL MATCH` clauses directly onto the supply chain pattern multiplies supplier rows by customer rows, and the `LIMIT 50` then truncates before the deep chain is drawn.

```cypher
MATCH (bu:BusinessUnit {id:'BU-03'})

CALL (bu) {
  MATCH (bu)<-[s1:SUPPLIES]-(bottle:Supplier {subcategory:'glass bottles'})
  OPTIONAL MATCH (bottle)<-[s2:SUPPLIES]-(container:Supplier {subcategory:'container glass'})
  OPTIONAL MATCH (container)<-[s3:SUPPLIES]-(raw:Supplier {subcategory:'raw glass'})
  OPTIONAL MATCH (raw)-[cls1:CLASSIFIED_AS]->(term:BusinessTerm {id:'TERM-05'})
  OPTIONAL MATCH (container)-[cls2:CLASSIFIED_AS]->(term)
  OPTIONAL MATCH (bottle)-[cls3:CLASSIFIED_AS]->(term)
  OPTIONAL MATCH (term)-[def:DEFINED_BY]->(rule:BusinessRule)-[ut:USES_THRESHOLD]->(th:Threshold)
  RETURN s1, bottle, s2, container, s3, raw, cls1, cls2, cls3, term, def, rule, ut, th
  LIMIT 50
}

CALL (bu) {
  MATCH (bu)<-[bel:BELONGS_TO]-(cust:Customer)-[ccls:CLASSIFIED_AS]->(cterm:BusinessTerm)
  WHERE cterm.id IN ['TERM-02', 'TERM-03', 'TERM-07']
  OPTIONAL MATCH (cterm)-[cdef:DEFINED_BY]->(crule:BusinessRule)-[cut:USES_THRESHOLD]->(cth:Threshold)
  RETURN bel, cust, ccls, cterm, cdef, crule, cut, cth
  LIMIT 50
}

RETURN *
```

- **What lands on screen:** the browser draws the union of both subqueries, so the unit sits in the middle with the multi-tier glass chain on one side and the classified customers on the other, each cohort wired to the definition that put it there.
- **The asymmetry worth pausing on:** TERM-02's rule reads a recorded default rather than a cutoff, so its `USES_THRESHOLD` leg comes back empty while TERM-03 resolves the Late Payment Threshold and TERM-07 the Customer Similarity Threshold. The graph says which definitions are threshold-governed and which are not, without anyone explaining it.
- **To widen past classification into exposure:** add the lines below inside the customer subquery, before its `RETURN`, then add the new variables to that `RETURN` and raise its `LIMIT`, since a customer's invoices fan out fast.

```cypher
  OPTIONAL MATCH (cust)-[hi:HAS_INVOICE]->(inv:Invoice)
  OPTIONAL MATCH (cust)-[hf:HAS_FINDING]->(find:ComplianceFinding)
```

### The Ownership Risk leg

TERM-06 has to be evaluated rather than matched, because no edge records it. The rule reads the stake-weighted PageRank written by `gds.py` against the Ownership Contagion Threshold, and the eligibility clauses in the definition become the traversal's `WHERE`: an active customer, carrying its own invoices, neither defaulted nor already Delinquent.

```cypher
MATCH (bu:BusinessUnit {id:'BU-03'})<-[bel:BELONGS_TO]-(cust:Customer)
MATCH (cterm:BusinessTerm {id:'TERM-06'})-[cdef:DEFINED_BY]->(crule:BusinessRule)-[cut:USES_THRESHOLD]->(cth:Threshold)
WHERE cust.defaultedPeriod IS NULL
  AND EXISTS { (cust)-[:HAS_INVOICE]->(:Invoice) }
  AND NOT EXISTS { (cust)-[:CLASSIFIED_AS]->(:BusinessTerm {id:'TERM-03'}) }
  AND cust.pagerank >= cth.value
OPTIONAL MATCH stake = (cust)-[:OWNED_BY*1..4]->(parent:Customer)
RETURN * LIMIT 50
```

- **The cutoff is read, not typed:** it comes from the live `Threshold` node, so the query stays correct across rebuilds even though `gds.py` fits THR-04 from each run's own PageRank distribution.
- **The `OWNED_BY` path is the explanation:** it draws the ownership chain the failure propagates along, which is the thing no column holds.
- **Order matters:** run this only after `gds.py` completes, since the `pagerank` property does not exist before then.
- **Composing the legs:** both customer legs drop into the combined query above as further `CALL (bu) { ... }` blocks. Keep each one's `RETURN` explicit and its `LIMIT` local, so no leg starves another of rows.
