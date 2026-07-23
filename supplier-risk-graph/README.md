# Finding the Risk Your Columns Cannot See

**Governed, explainable supply-and-credit risk across a Neo4j knowledge graph and a Databricks lakehouse.**

## The business story

A global beverage producer runs two mature risk programs. Procurement scores and qualifies every supplier. Credit control rates every customer and sets facility limits. Both are healthy, and both grade entities one at a time. The exposures and early warnings that matter are structural, and neither program can see them.

- **Supplier concentration risk, hidden in the sub-tier.** Procurement has five qualified, separately-contracted tier-1 bottle suppliers in the Americas. All five buy their container glass from a tier of processors, and every one of those processors melts its glass at Cascade Glassworks, which scores mid-tier and never trips a report. It is a single point of failure behind a supply base that looks diversified, and the exposure is the Americas' recognized revenue for the most recent full quarter. The producer knows its tier-1 suppliers. It does not know who *they* buy from.
- **Group credit exposure, hidden in the ownership structure.** Jade Beverage Distribution is a spotless platinum account with an 800,000 EUR facility, assessed standalone and rated accordingly. It is owned 85% by a holding group whose other arms own the four companies that already defaulted. Every late-payer report puts Jade in the clear, right up until the parent pulls it down with the rest.
- **Customer deterioration, visible before the rule trips.** The Delinquent Customer rule identifies accounts whose last three invoices are each more than 60 days late. Risky Customer restores the missing early-warning definition: an active, not-yet-delinquent customer is risky when at least half of its ten nearest payment-behavior neighbours are already Delinquent. kNN finds the cohort from standardized average lateness and overdue share, then the graph keeps the specific delinquent neighbours as evidence.

All three risks are already in the data. None is visible from a single column: the first two live in *connections* such as who supplies whom and who owns whom, while the early warning emerges from the payment-behavior neighbourhood around each customer.

## The value

- **Quantify revenue at risk, not just supplier scores.** Sub-tier visibility turns a diversified-looking supply base into a named single point of failure with a revenue figure attached, before the plant stops.
- **Assess credit by group, not by account.** Exposure aggregates across entities under common ownership, the way a lender assesses a group of connected clients, so a clean account inside a failing group stops reading as clean.
- **Answer in governed business language.** "Critical Supplier," "Ownership Risk," and "Risky Customer" resolve from definitions, rules, and thresholds the business owns, so two people asking the same question get the same answer.
- **Show the work.** Every materialized classification traces back through the rule that produced it to the physical Unity Catalog table behind it. Ownership Risk retains the ownership path behind its live decision, and Risky Customer retains the named delinquent neighbours behind its early-warning score.
- **Keep the lakehouse as the system of record.** The graph adds meaning on top of Databricks rather than replacing it. No second source of truth.

## What this repo is

A runnable demo of that scenario. Suppliers specialize by subcategory: glass bottles, malt, hops, cans, labels, and the tiers behind the bottles, which run from feedstock through the furnaces to the processors. The subcategories that make up one commodity are the `COMMODITY_SUBCATEGORIES` dict in the generator, and a supply path counts as carrying that commodity only when every supplier on it trades in one of them. Customers are the drinks trade: distributors, wholesalers, supermarket groups, and bar and hotel chains.

- **Databricks owns the facts.** Unity Catalog Delta tables hold customers, suppliers, invoices, revenue, compliance findings, and the supplier-to-supplier links.
- **Neo4j owns the meaning.** The knowledge graph mirrors those facts and adds the governed definitions, thresholds, rules, and the multi-hop lineage tying every risk classification back to its physical table.

One set of CSVs in `data/` feeds both sides, so the two layers always agree and the demo runs offline.

## The two engines

- **Genie Agent:** the lakehouse-only engine. A Databricks Genie space scoped to the Unity Catalog instance tables and nothing else.
- **Genie One:** the same Genie Agent under a supervisor that can also call a read-only Neo4j MCP server over the knowledge graph.

Both answer the everyday risk questions. The payoff is three graph-native questions the lakehouse-only engine cannot answer reproducibly, because their definitions live only in the graph.

## How the graph finds them

In a lakehouse the facts are clean, but the *meaning* is scattered. What counts as a "high-risk" supplier, a "strategic" account, or a "delinquent" customer lives in ad hoc SQL, notebooks, and tribal knowledge. None of the three governed conclusions is a lakehouse column: each depends on a graph computation plus a governed cutoff that the lakehouse-only engine cannot discover from the instance tables.

### Story 1: the hidden glassworks

- **Who:** Cascade Glassworks, SUP-901.
- **Business term:** Critical Supplier.
- **Algorithm:** betweenness centrality over the multi-tier supply chain.
- **What it finds:** the sub-tier supplier that every commodity-carrying glass path into the Americas runs through, sitting a tier back from anything that unit buys from directly.
- **The decoy:** counting connections does not find it. The most connected supplier in the network is somebody else, which the build asserts, and Cascade sells to no business unit at all, so the supplier-to-unit bridge table never names it.

### Story 2: the clean payer in a bad group

- **Who:** Jade Beverage Distribution, CUST-904.
- **Business term:** Ownership Risk.
- **Algorithm:** stake-weighted personalized PageRank over the ownership edges.
- **What it finds:** group credit exposure inherited through the parent, not through Jade's own record.
- **The decoy:** ranking by distance to the nearest default returns someone else. Nothing within two hops of Jade has failed, and the accounts sitting next to a default hold only a few percent of it.

### Story 3: the customer heading toward delinquency

- **Who:** a derived cohort, not a hand-picked protagonist. The current build includes planted near-miss accounts and at least one emergent customer found by the metric.
- **Business term:** Risky Customer.
- **Algorithm:** deterministic GDS kNN over a standardized two-feature payment-behavior vector.
- **What it finds:** active customers that have not tripped the Delinquent Customer rule, but whose ten nearest behavioural neighbours are already majority delinquent.
- **Why it is explainable:** every classification retains the delinquent neighbours that contributed to the score, their rank, and their similarity.

### Why none is findable in the lakehouse

- **The math is not the barrier.** All three algorithms are expressible outside the graph.
- **No BI tool reaches for them unprompted.** An all-pairs shortest-path computation, iterative weighted propagation, or governed nearest-neighbour screen is not what a natural-language question turns into.
- **The cutoff lives in the graph.** What decides each answer is a governed threshold, not a column to sort on.

Live figures for the two structural stories, including `story1_hidden_glassworks.bu03_last_quarter_revenue` and `story2_clean_payer.jade_open_invoice_balance`, are in [`data/ground_truth.json`](data/ground_truth.json). The Risky Customer cohort is derived rather than planted, so `gds.py` prints its current members, scores, and planted-versus-emergent status on every run.

See [`DEMO.md`](DEMO.md) for the walkthrough and the two-engine comparison, and [`DATA_ARCHITECTURE.md`](DATA_ARCHITECTURE.md) for the complete data model.

## The two-layer model

- **Instance layer:** a mirror of the lakehouse tables, including the two structural edge types: supplier-to-supplier `SUPPLIES` for the multi-tier supply chain, and customer-to-customer `OWNED_BY` for ownership stakes. Both are uploaded to Unity Catalog too, so the lakehouse-only engine has the raw networks in full. What it lacks is the computation over them.
- **Knowledge layer:** entities, business terms, business rules, policies, thresholds, and the semantic mapping to the real Unity Catalog tables.
- **`REALIZED_AS`:** links a logical entity to its physical instances.
- **`CLASSIFIED_AS`:** records a classification with provenance. The four column-findable terms carry these edges. `gds.py` also writes the derived Critical Supplier and Risky Customer cohorts from their governed thresholds. Ownership Risk alone carries none and is resolved live.

Graph properties and the instance tables use camelCase, so the Cypher in the walkthrough runs unchanged against either side. The two graph-derived gold tables, `classifications` and `business_unit_exposure`, are snake_case.

## The dataset

Generated from scratch with a fixed seed of 42 and an as-of date that defaults to today, so the demo shows forward-looking risk rather than a stale snapshot. Pass `--as-of YYYY-MM-DD` to `generate_data.py` for a reproducible build. Names, ids, and the hand-set business thresholds come from the seed and never move. Every date, euro amount, row count, and resolved graph-native cutoff is re-derived on each run.

**The seed is load-bearing and must not be changed.** `make demo` regenerates with seed 42 every time and only the as-of date moves, so the supply topology, the betweenness ranks, and the Critical Supplier cohort are identical on every build. Story 1 rests on that specific arrangement: the container-glass processor the Americas bottle makers share, and the single furnace behind it that no bottle maker can see directly. Editing `SEED` in `generate_data.py` is a reseed, not a refresh, and it can move who sits where, so treat it as a change to the story that has to be re-probed rather than a setting to tune. Regenerating is safe; reseeding is not.

**Do not read live figures out of this file.** `generate_data.py` rewrites [`data/ground_truth.json`](data/ground_truth.json) on every run, stamped with the `as_of_date` it used, and that file is the reference for counts, quarterly revenue, and exposure amounts. The docs quote only the values that cannot drift.

- **Scale:** a few hundred customers and a couple of hundred suppliers, sized from the generator's background population constants with the story protagonists added on top. Late payers, overdue balances, supplier risk scores, and compliance findings carry a believable spread so all three contrasts land against ordinary background risk.
- **Two webbed edge layers hide the plants.** Supplier-to-supplier links form several regional clusters, each grown by preferential attachment and then given chords beyond the spanning tree that connects it, so a cluster's interior traffic always has more than one route. Several cross-cluster bridges join the clusters to each other, every bridge a different supplier and none of them trading glass, so no single supplier separates the network and the commodity-scoped exposure measure has nowhere to leak. The constants are `SUP_CLUSTERS`, `SUP_WEB_CHORD_RATIO`, and `SUP_INTER_CLUSTER_BRIDGES` in the generator. Ownership links form weighted multi-parent groups: a customer can be held by several owners at different stakes, so Kestrel is one of many owned groups rather than the only one. The webbing is what makes the two planted subgraphs look ordinary to the graph algorithms, so only the real metric singles each out.

Per-table and per-edge counts for the current dataset are in the `summary` block of `data/ground_truth.json`.

## How to run

Copy the environment sample and fill it in. The Neo4j section drives `load.py` and `gds.py`. The Databricks section drives `upload.py`. Only `generate_data.py` runs without it.

```bash
cp .env.sample .env
# edit .env: NEO4J_URI, NEO4J_PASSWORD, and the Databricks / Unity Catalog values
```

**The four pipeline steps are one unit, and they run strictly in order.** The supported path is a single target:

```bash
make demo
```

The raw commands are the same four steps, and running them by hand is fine as long as the order holds:

```bash
uv run generate_data.py   # writes data/ CSVs + ground_truth.json
uv run load.py            # WIPES Neo4j (DETACH DELETE all) and reloads
uv run gds.py             # computes betweenness + PageRank + customer kNN
uv run upload.py          # rebuilds Unity Catalog tables + metric view
```

Each step depends on the state the previous one leaves behind, and two of the graph's governing thresholds do not exist until step 3 computes them. **Partial runs are the failure mode to avoid.** The generator re-derives every date from today, so re-running it alone leaves Neo4j and Unity Catalog holding the previous run's data while `ground_truth.json` claims today's.

1. **Generate the data.** Writes the 14 node CSVs, the relationship CSVs, the `supply_relationships` link CSV, the `supplier_business_units` lakehouse bridge CSV, and `ground_truth.json` to `data/`.

   ```bash
   uv run generate_data.py
   ```

2. **Load Neo4j.** **Destructive to the graph:** the loader `DETACH DELETE`s every node in the target database before writing. It then creates id uniqueness constraints and loads nodes and relationships in `UNWIND` batches, including the `SUPPLIES` and `OWNED_BY` same-graph edges. Point it at a database dedicated to this demo, never a shared one.

   ```bash
   uv run load.py            # wipe and load
   uv run load.py --check    # validate CSVs only, no database
   ```

3. **Run the GDS analytics.** Runs betweenness centrality over the supplier network, personalized PageRank over the ownership network, and payment-behavior kNN for the Risky Customer early warning. Results are written back as Neo4j node properties only and never synced to Delta. The kNN pass also writes explainable `SIMILAR_PAYMENT_BEHAVIOR` edges to the delinquent neighbours behind each classified customer. This step resolves THR-03 and THR-04, the two graph-native thresholds the generator leaves blank, and verifies the pre-authored THR-05 value used by kNN. **Until this step runs, the three graph-native demo beats are incomplete.**

   ```bash
   uv run gds.py
   ```

4. **Upload to Unity Catalog.** Uploads the instance CSVs as Delta tables, including `supply_relationships` and `owned_by`, applies the semantic metadata Genie reads, builds the `customer_risk_exposure` metric view, and materializes the two graph-derived gold tables. The comments and the metric view are rebuilt on every run, because `CREATE OR REPLACE TABLE` drops them, which is also what makes the script idempotent with no bookkeeping.

   ```bash
   uv run upload.py
   ```

Quick check that the load worked, before you walk through anything live:

- **Referential integrity:** `uv run load.py --check` reports node and relationship totals and confirms every relationship endpoint resolves.
- **Story 1:** after `gds.py`, Cascade Glassworks (SUP-901) clears the Supply Concentration Threshold, in a cohort with more than one member, and the five tier-1 bottle suppliers score clean. Where Cascade ranks on betweenness is printed to the build log and never asserted: `assert_betweenness` in `gds.py` reports the ranking rather than requiring a winner.
- **Story 2:** after `gds.py`, Jade Beverage Distribution (CUST-904) is the top *trading* customer by stake-weighted PageRank while its own record stays clean. The trading qualifier is load-bearing: Kestrel, Harbour, and Tern score higher and are correctly excluded, because they carry no invoices, so there is no receivable to act on and no facility to cut.
- **Story 3:** after `gds.py`, Risky Customer is a multi-customer early-warning cohort containing at least one planted near-miss account and no already-delinquent, defaulted, or invoice-less customer. The build log prints the complete cohort and marks each member as planted or emergent.

## The threshold lifecycle

`data/thresholds.csv` holds five governing cutoffs, filled at two different times, so run order matters:

- **THR-01 Supplier Risk Threshold (70)** and **THR-02 Late Payment Threshold (60)** are hand-set business constants. The generator writes them with values and `load.py` loads them as-is. Edit these in the generator to change what "high-risk supplier" or "delinquent customer" means.
- **THR-03 Supply Concentration Threshold** and **THR-04 Ownership Contagion Threshold** are graph-native. The generator writes their `value` blank and `load.py` creates the nodes with a null value, because a cutoff cannot be placed until the GDS scores exist. Do not hand-edit these two. `gds.py` overwrites them on every run.

  The two are set by different routes, and the distinction is the point of THR-03's `basis` column. THR-03's governed parameter is a percentile of supply betweenness, hand-set in the generator before any score is computed and before the topology it applies to exists, which is why it lands in git ahead of the data rather than alongside it. The run resolves that percentile against its own distribution, so the resolved cutoff is an output of the build and not a target it was aimed at. It catches whoever is in the tail, which is a cohort rather than a name, and the build fails if that cohort has fewer than two members. If the protagonist fails to clear the percentile, the topology is what gets fixed and the percentile does not move. THR-04 is placed from the computed PageRank distribution instead, and Story 2 is out of scope for change.

- **THR-05 Customer Similarity Threshold (0.5)** is authored before kNN runs. It means that at least half of an eligible customer's ten nearest payment-behavior neighbours are already Delinquent. Because both the threshold and the metric are shares on the same scale, no fitted cutoff is needed. `gds.py` verifies that the live threshold and rule carry the value it screened against.

The demo Cypher reads each cutoff from the live `Threshold` node, so the values only need to be correct in the graph, which they are once `gds.py` has run.

`thresholds.csv` is graph-only and is **never uploaded to Unity Catalog.** This is deliberate: if the graph-native cutoffs became Delta columns, the lakehouse-only engine could read them and the demo would tie.

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
   - **Gold tables:** `classifications` and `business_unit_exposure`, produced by the pipeline but kept out of the Genie space.

   `upload.py` writes table and column comments but declares no primary or foreign keys. Databricks' Genie guidance ranks descriptions, metric views, and example SQL as the levers that matter and does not mention constraints. The fanout constraints were meant to prevent is prevented structurally by the metric view instead.

2. **Create a Genie space** scoped to the `supplier_risk` schema, with every instance table: `customers`, `suppliers`, `business_units`, `invoices`, `revenue_entries`, `compliance_findings`, `supply_relationships`, `owned_by`, the `supplier_business_units` bridge, and the `customer_risk_exposure` metric view. The fairness rule is non-negotiable: both engines get every table, so nothing is withheld from the space and the gap is grounding, not access.

   **`compliance_findings` and `owned_by` are both in the space**, given to the lakehouse-only engine like every other instance table. Neither carries a graph-derived conclusion: `owned_by` is the raw ownership stakes, and `compliance_findings` is raw instance data that already feeds the `customer_risk_exposure` metric view, which is itself in the space. When a question needs aggregated finding counts, prefer the metric view's `open_finding_count`, which aggregates each measure at its own source grain and so cannot fan a customer's finding count out by its invoice count the way a raw two-branch join off `customers` can. The raw table is present for any question that reads it directly. The `ComplianceFinding` nodes stay in the graph for the same reason the table stays in Unity Catalog: removing them would leave ENT-06 mapping to nothing and POL-03 Compliance (KYC) governing no data. `constrains.csv` points POL-03 at ENT-01 Customer, not ENT-06, so DEMO.md's policy-scope example does not depend on the finding nodes.

3. **Do not add `classifications` or `business_unit_exposure` to the space.** They materialize the graph's answers into Delta, so adding them re-introduces write-back leakage and the lakehouse-only engine could read the graph's conclusions straight from a column. For the same reason, the GDS scores are never synced to Delta and live only in the graph.

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
