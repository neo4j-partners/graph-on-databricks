# Data Architecture

The demo models a global beverage producer. Its suppliers specialize by subcategory (glass bottles, malt, hops, cans, labels, and the raw glass behind the bottles), and its customers are the drinks trade: distributors, wholesalers, supermarket groups, and bar and hotel chains.

The demo uses a dual data architecture. The Databricks lakehouse owns the instance layer as Unity Catalog Delta tables. Neo4j owns the knowledge layer and holds a mirror of the instance data so multi-hop and provenance queries run in one graph. One set of CSVs in `data/` is the single source for both sides.

The point of the demo is a contrast between two engines. A Databricks Genie Agent over the Unity Catalog Delta tables is the lakehouse-only engine: it sees the facts and nothing else. Genie paired with the read-only Neo4j knowledge graph is the second engine: it sees the same facts plus the governed meaning. Both engines answer the everyday risk questions. The payoff is the two graph-native questions the lakehouse-only engine cannot answer, because their definitions live only in the graph.

> **Where the numbers live.** The dataset regenerates from today's date on purpose, so the demo shows forward-looking risk rather than a historical snapshot. Names, ids, risk scores, cohorts, and the governed thresholds come from the fixed seed and never move. Every date, every euro amount, and every row count is re-derived on each run and recorded in `data/ground_truth.json`, which carries the `as_of_date` it was written with. This page quotes the stable values and points at `ground_truth.json` for the rest.
>
> **The four pipeline steps run as a unit,** in order: `generate_data.py`, then `load.py`, then `gds.py`, then `upload.py`, or `make demo` for all four. `load.py` is destructive to the graph, wiping the target Neo4j database before it loads. Running the generator alone leaves Neo4j and Unity Catalog holding the previous run's data while `ground_truth.json` claims today's. See [`README.md`](README.md) for the full run instructions.

> **A note on "knowledge layer".** This demo uses the term narrowly, for the governed-meaning half of the graph: entities, business terms, business rules, policies, thresholds, and the semantic mapping (`MAPS_TO`), held distinct from the instance layer. The two are kept as sibling layers because the split maps directly onto the demo's division of labor: the lakehouse owns the facts, Neo4j owns the meaning.

## The two stories

The dataset serves two contrasts. Each is a question the lakehouse-only engine gets wrong or misses, and the graph engine answers by resolving a governed definition that has no lakehouse column.

### Story 1: the hidden glassworks

Cascade Glassworks is a mid-tier raw-glass supplier. Its own risk score sits in the middling band, below the risk threshold, so no risk-score sort ever surfaces it. Yet the Americas business unit depends on it disproportionately, because five clean tier-1 bottle suppliers all trace back to Cascade for their raw glass. If Cascade fails, all five paths into the Americas fail with it.

The graph engine surfaces Cascade with betweenness centrality over the multi-tier supply graph, the metric behind the **Critical Supplier** term. The supplier network is two cross-linked clusters joined at exactly one point, Cascade, so removing it splits the network in two and every path between the halves runs through it. One quarter of Americas recognized revenue sits behind it, which is revenue at risk behind the bridge rather than spend attributable to Cascade. The current figure is `story1_hidden_glassworks.bu03_last_quarter_revenue` in `data/ground_truth.json`, for the quarter named in `last_quarter`; it moves with every regeneration, so read it there rather than from this page.

Counting connections does not find Cascade: SUP-109 leads the network on raw link count and Cascade does not come out on top, and neither descendant count nor reachable-business-unit count picks it either. The bridge is not the busy node, which is the entire reason the metric has to be a shortest-path computation.

### Story 2: the clean payer in a bad group

Jade Beverage Distribution is a spotless platinum customer with a clean payment record and a Strategic Account flag. Kestrel Holdings owns 85% of it, and Kestrel's two intermediate holding companies, Harbour Group and Tern Capital, own the four companies that defaulted. Nothing within two hops of Jade has failed. Asked for late payers, the lakehouse-only engine returns the delinquent accounts, and Jade is nowhere on the list: its own record is clean.

The graph engine flags Jade with stake-weighted personalized PageRank, seeded on every defaulted customer in the book and propagated over the `OWNED_BY` edges with `ownershipPct` as the weight, the metric behind the **Ownership Risk** term. Jade carries an 800,000.00 EUR committed credit facility, which the generator pins as a constant, and the portion drawn against it as open invoice balance is `story2_clean_payer.jade_open_invoice_balance` in `data/ground_truth.json`. The facility is fixed; the drawn balance is recomputed from the invoices on every run.

The weighting is what makes this a graph question rather than a join. Defaults are scattered across the book, and many clean accounts sit one hop from one of them, but those accounts hold two to five percent of the company that failed, so almost nothing propagates to them. Kestrel's stakes run 65% to 90% at every level, so four failures reach Jade three hops away largely intact. Ranking by distance to the nearest default does not return Jade, and neither does counting defaults per ownership group, where another group holds more defaults than Kestrel's. Both shortcuts run fine against the lakehouse tables and both return the wrong account.

## Dual data architecture

![Dual data architecture](dual-data-architecture.png)

## A note on BusinessUnit

`BusinessUnit` is an internal division of the enterprise this demo models, not a unit of a supplier or a customer. It is the shared pivot of the instance layer: customers roll up into it (`BELONGS_TO`), suppliers feed it (`SUPPLIES`), and revenue is booked against it (`RECOGNIZES`). A customer is therefore a customer of the enterprise; `BELONGS_TO` only records which internal division carries that account for revenue roll-up, and `SUPPLIES` points a vendor into the division it serves. The Americas division (`BU-03`) is the pivot for Story 1: the five tier-1 bottle suppliers all supply it, so the multi-tier path `Supplier-SUPPLIES->Supplier-SUPPLIES->BusinessUnit` converges on Cascade behind it.

## Lakehouse Tables (Unity Catalog Delta)

The lakehouse holds three kinds of table: the **core instance tables** that carry the facts, the two **gold write-back tables** the pipeline produces, and one **bridge table**, plus one **metric view** over the customer tables. Instance-table columns are camelCase, since the CSV headers load verbatim into both Neo4j and UC. The two gold tables are snake_case, built from Cypher `RETURN` aliases.

Every table also carries a comment, and the columns whose meaning cannot be read off the name carry one too. `upload.py` applies these on every run, since `CREATE OR REPLACE TABLE` drops them. There are deliberately no primary or foreign key constraints: Databricks' Genie guidance ranks descriptions, metric views, and example SQL as the levers that matter and does not mention constraints, and the aggregate fanout they were meant to prevent is prevented structurally by the metric view below.

### Core instance tables

| Table | Business description | Columns (key) | Notes |
|---|---|---|---|
| `customers` | The accounts the enterprise sells to, with commercial segment and credit line | `id, businessUnitId, name, segment, creditLimit, defaultedPeriod, churnRisk, upsellScore, profitabilityTrend, avgDaysLate, overdueShare` | Ownership lives in its own `owned_by` table, not a parent column here, because a customer can have more than one owner. `creditLimit` (EUR) is the total committed credit facility on the account, set for every customer with one consistent meaning. The customer's open invoice balance is the drawn portion of that facility, never an addition to it, so the two are never summed. It feeds the Story 2 exposure figure. `defaultedPeriod` (format `YYYY-Qn`) is set only on defaulted customers, null otherwise |
| `suppliers` | The vendors the enterprise buys from, each carrying a procurement risk score and a specialty | `id, name, category, subcategory, riskScore` | `subcategory` is the supplier's specialty within its category (for example `glass bottles` or `raw glass` under `packaging`), never null. It is the column the lakehouse-only engine groups by in Story 1 (the "five glass-bottle suppliers, diversified" read); `riskScore` is what drives the High-Risk Supplier term |
| `business_units` | The enterprise's own internal divisions; the pivot customers roll up into, suppliers feed, and revenue is booked to | `id, name, region` | Rolls up customers, suppliers, and revenue |
| `invoices` | Bills the enterprise issued to its customers, each recording what was owed, when it was due, and how late it was paid | `id, customerId, amount, currency, issueDate, dueDate, paidDate, daysLate, status` | `customerId` joins to `customers.id`. Backs the Delinquent Customer term and Jade's open-balance exposure |
| `revenue_entries` | Revenue booked to an internal division for a period | `id, businessUnitId, period, amount, currency, reconciled` | `businessUnitId` joins to `business_units.id`. The Americas rows for the recent quarters back the Story 1 exposure figure |
| `compliance_findings` | Compliance issues (KYC, AML, sanctions) raised against a customer, open or closed | `id, customerId, type, status, openedDate` | `customerId` joins to `customers.id`. Feeds the Compliance (KYC) Policy |
| `supply_relationships` | The supplier-to-supplier links: which supplier supplies which other supplier | `fromSupplierId, toSupplierId` | New table. A row `fromSupplierId = SUP-901, toSupplierId = SUP-902` means SUP-901 supplies SUP-902. One of two CSVs that load into both sides: UC gets the table so the lakehouse-only engine can see the raw links, and Neo4j gets the supplier-to-supplier `SUPPLIES` edges |
| `owned_by` | The ownership stakes between customers: who owns whom, and how much of them | `customer_id, parent_customer_id, ownershipPct` | New table. A row `customer_id = CUST-904, parent_customer_id = CUST-901, ownershipPct = 0.85` means Kestrel owns 85% of Jade. A customer can appear as `customer_id` on several rows, so ownership is a multi-parent DAG, not a tree. Loads into both sides: UC gets the table so the lakehouse-only engine has the full structure and the stakes, and Neo4j gets the `OWNED_BY` edges with `ownershipPct` as a relationship property |

The commercial and payment-behavior attributes on `customers` (`churnRisk`, `upsellScore`, `profitabilityTrend`, `avgDaysLate`, `overdueShare`) provide background realism so the population looks ordinary; no story depends on them.

One bridge table, `supplier_business_units` (`supplierId, businessUnitId`), carries the many-to-many supplier-to-unit link so the lakehouse can join suppliers to the units they supply. It mirrors the supplier-to-unit `SUPPLIES` edge and is uploaded to UC but not loaded into Neo4j.

### Metric view

One metric view, `customer_risk_exposure`, sits over `customers` joined to `invoices` and `compliance_findings`, with `cardinality: one_to_many` declared on each, and to `business_units` with `rely: at_most_one_match` so business unit and region come through as dimensions. It carries open exposure, overdue amount, total invoiced amount, invoice and finding counts, credit limit, and credit utilization. `upload.py` defines it and rebuilds it on every run, alongside the table and column comments, because `CREATE OR REPLACE TABLE` on the base tables drops everything defined over them.

It exists for correctness, not for meaning. `customers` has two independent one-to-many branches hanging off it, and a query joining both in one pass multiplies each by the other's row count: one customer's open exposure came back multiplied by its finding count, and its open findings came back multiplied by its invoice count. Declaring the cardinality makes each measure aggregate at its own source grain, so the fanout stops being something a query can express. Every measure in it is an aggregate over columns the lakehouse-only engine could already read, so it adds no knowledge the graph owns.

`compliance_findings` is not added to the Genie space, which is a separate exclusion from the gold-table guardrail below and a weaker one: no story reads that table, a fanout needs both branches to occur at all, and the metric view still carries `open_finding_count` and `finding_count` for any question that genuinely needs them. The table stays in Unity Catalog because `ComplianceFinding` maps to it in the lineage layer.

### Gold write-back tables

| Table | Business description | Columns (key) | Notes |
|---|---|---|---|
| `classifications` | Business-term labels assigned to customers and suppliers, with the reason that produced them | `entity_id, entity_type, term, reason, evaluated_at, rule_version` | Materializes the `CLASSIFIED_AS` edges written back from Neo4j, each carrying rule provenance. Because the two graph-native terms are never planted as edges, this table holds only the column-findable classifications, never Critical Supplier or Ownership Risk |
| `business_unit_exposure` | Each internal division's aggregate supplier-risk exposure | `business_unit_id, name, supplier_count, avg_supplier_risk, max_supplier_risk` | One row per business unit, reporting supplier count, average, and max feeding-supplier risk, ordered by supplier count |

**The two gold tables must never be added to the Genie space.** They materialize the graph's answers into Delta. Re-adding them re-introduces write-back leakage, so the lakehouse-only engine could read the graph's conclusions straight from a column and tie. That leakage is the exact failure the demo is built to avoid, so the gold tables stay out of the space. See "GDS properties" below for the same rule applied to the graph algorithm scores.

The six core instance tables are mirrored into Neo4j as nodes; `supply_relationships` is not a node type, it sources the supplier-to-supplier `SUPPLIES` edges. Sample a few of each mirrored instance label:

```cypher
UNWIND ['Customer', 'Supplier', 'BusinessUnit', 'Invoice', 'RevenueEntry', 'ComplianceFinding'] AS label
CALL (label) {
  MATCH (n:$(label))
  RETURN n LIMIT 3
}
RETURN label, n;
```

## Neo4j Nodes

### Instance layer (mirror of the lakehouse)

Because the instance CSVs are the single source for both sides, the mirror nodes also carry the foreign-key columns as properties (`Invoice.customerId`, `RevenueEntry.businessUnitId`, `ComplianceFinding.customerId`, `Customer.businessUnitId`). They are redundant with the instance-layer relationships below, which is what the demo's Cypher traverses.

| Label | Key properties | Business description | Notes |
|---|---|---|---|
| `Customer` | `id, name, segment, creditLimit, defaultedPeriod` | An account the enterprise sells to | `OWNED_BY` comes from `owned_by.csv`, not a property here; `defaultedPeriod` is set only on defaulted customers; `creditLimit` is the total committed credit facility, and the customer's open invoice balance is the drawn portion inside it, so the Story 2 exposure is the facility itself and the two figures are never added together |
| `Supplier` | `id, name, category, subcategory, riskScore` | A vendor the enterprise buys from | `subcategory` is the specialty within the category |
| `BusinessUnit` | `id, name, region` | An internal division of the enterprise; the pivot customers, suppliers, and revenue attach to | Rolls up customers, suppliers, revenue |
| `Invoice` | `id, amount, currency, issueDate, dueDate, paidDate, daysLate, status` | A bill issued to a customer | Basis for payment-behavior rules |
| `RevenueEntry` | `period, amount, currency, reconciled` | Revenue booked to a division for a period | Backs the Story 1 exposure figure for the Americas |
| `ComplianceFinding` | `id, type, status, openedDate` | A compliance issue raised against a customer | Feeds the Compliance (KYC) Policy |

Sample one customer's instance subgraph, its unit, invoices, and findings:

```cypher
MATCH (c:Customer)-[:BELONGS_TO]->(bu:BusinessUnit)
OPTIONAL MATCH (c)-[:HAS_INVOICE]->(i:Invoice)
OPTIONAL MATCH (c)-[:HAS_FINDING]->(f:ComplianceFinding)
RETURN c, bu, i, f LIMIT 25;
```

### Knowledge layer (graph only)

| Label | Key properties | Business description | Notes |
|---|---|---|---|
| `Entity` | `name, description` | A logical business entity in the knowledge layer | Seven entities and eight mappings, Customer carrying two sources |
| `BusinessTerm` | `name, definition` | A named business definition the organization agrees on | For example "Critical Supplier" or "Ownership Risk" |
| `BusinessRule` | `name, expression, description` | The machine-evaluable logic that backs a term | Machine-evaluable logic behind a term |
| `Measure` | `name, definition, grain, aggregation` | What a business term is worth, expressed as a governed euro quantity | Supply Exposure and Credit Exposure. A term says what something is; a measure says what it costs. `grain` names the level the figure is reported at; `aggregation` carries the arithmetic the lakehouse is asked for |
| `GraphMetric` | `name, nodeLabel, property, algorithm, description` | The precomputed graph score a graph-native term is detected by | Supply Betweenness (`Supplier.betweenness`) and Ownership Contagion (`Customer.pagerank`). `nodeLabel` and `property` locate the score; `algorithm` names the GDS procedure that produced it. Detection, not valuation |
| `Policy` | `name, type` | A governance policy that scopes entities and rules | For example Credit Risk Policy, Supply Chain Resilience Policy |
| `Threshold` | `name, value, currency` | A parameter value a business term depends on | For example the Supplier Risk Threshold |
| `DataSource` | `name, system, table` | The physical table a logical entity is stored in | Lineage target; `table` holds the real Unity Catalog table name |

Sample a few of each knowledge-layer label:

```cypher
UNWIND ['Entity', 'BusinessTerm', 'BusinessRule', 'Measure', 'GraphMetric', 'Policy', 'Threshold', 'DataSource'] AS label
CALL (label) {
  MATCH (n:$(label))
  RETURN n LIMIT 3
}
RETURN label, n;
```

## The knowledge layer (governed ontology)

The knowledge layer is rebuilt from scratch so every governed concept earns its place in one of the two stories or the background contrast. Entities map to tables, terms are defined by rules, rules read entities, policies govern rules and constrain entities, thresholds apply to terms. The payoff is the two graph-native terms: their definitions and thresholds live only in the graph, and no lakehouse column carries them, which is exactly why the lakehouse-only engine cannot resolve them.

### Entities and their table mappings

Each entity is a logical business object mapped to one Unity Catalog table by a `MAPS_TO` edge, so any definition traces down to the physical table.

| Entity | Maps to table |
|---|---|
| Customer | `supplier_risk.customers` |
| Supplier | `supplier_risk.suppliers` |
| BusinessUnit | `supplier_risk.business_units` |
| Invoice | `supplier_risk.invoices` |
| RevenueEntry | `supplier_risk.revenue_entries` |
| ComplianceFinding | `supplier_risk.compliance_findings` |
| SupplyRelationship | `supplier_risk.supply_relationships` |
| Customer (second source) | `supplier_risk.owned_by` |

`SupplyRelationship` is a new entity, mapping the new supplier-to-supplier table, so the Critical Supplier definition traces to a real table. Ownership needs no new entity: the `owned_by` table is customer data, so the Customer entity maps to it as a second data source alongside `customers`.

### Business terms

| Term | Plain meaning | Nature |
|---|---|---|
| Strategic Account | A platinum customer flagged strategic by account management | Rule, column-findable |
| Defaulted Customer | A customer with a recorded default in the snapshot | Fact, column-findable |
| Delinquent Customer | A customer more than 60 days late on each of its last three invoices | Rule, column-findable |
| High-Risk Supplier | A supplier whose procurement risk score meets or exceeds the threshold | Rule, column-findable |
| Critical Supplier | A supplier the network disproportionately depends on: the narrowest bridge on a business unit's multi-tier supply paths | Graph-native, no column |
| Ownership Risk | An active, clean-record customer (its own invoices, no default, not delinquent) that absorbs more failure through its ownership stakes than any other trading customer, where risk propagates from every default in proportion to the size of each stake; defaulted members and invoice-less holding companies are excluded | Graph-native, no column |

The two graph-native terms are the whole point. **Critical Supplier and Ownership Risk have no lakehouse column, and a governing cutoff that lives only in the graph.** Both algorithms are expressible in SQL. What no BI tool does is reach for an all-pairs shortest-path computation or an iterative weighted propagation, unprompted, from a business question, and the cutoff that decides each answer is a governed value in the graph rather than a column to sort on. Their definitions live in the graph. The four column-findable terms exist to make the contrast honest: they show what the lakehouse-only engine can govern, so the gap is clearly the two it cannot.

### Business rules

One rule defines each term, by a `DEFINED_BY` edge, and reads one or more entities, by `EVALUATES` edges.

| Rule | Defines | Plain expression | Reads (EVALUATES) |
|---|---|---|---|
| Strategic Account Rule | Strategic Account | segment is platinum and flagged strategic | Customer |
| Defaulted Customer Rule | Defaulted Customer | a default period is recorded | Customer |
| Delinquent Customer Rule | Delinquent Customer | each of the last three invoices is more than 60 days late | Customer, Invoice |
| High-Risk Supplier Rule | High-Risk Supplier | risk score is at least 70 | Supplier |
| Critical Supplier Rule | Critical Supplier | highest-betweenness bridge on a business unit's multi-tier supply paths, at or above the supply concentration threshold | Supplier, SupplyRelationship, BusinessUnit |
| Ownership Risk Rule | Ownership Risk | stake-weighted propagated risk over `OWNED_BY` (walked transitively, weighted by `ownershipPct`, propagated from every Defaulted Customer) at or above the ownership contagion threshold | Customer |
| Supply Exposure Rule | Supply Exposure measure | sum of recognized revenue for the most recent full quarter, over every business unit the supplier's multi-tier `SUPPLIES` paths reach | RevenueEntry, BusinessUnit |
| Credit Exposure Rule | Credit Exposure measure | the customer's total committed credit facility, reported alongside the open invoice balance drawn against it | Invoice, Customer |

The two graph-native rules are expressed as traversals and graph metrics, never as a column predicate. Critical Supplier references betweenness over the supply network; Ownership Risk references stake-weighted propagation over transitive ownership. Both read the precomputed Neo4j node properties, not a Delta column. Neither reduces to an aggregate over the underlying tables: the most connected supplier is not Cascade, and the account nearest a default is not Jade.

Two further rules define the measures rather than the terms. The Supply Exposure Rule reads `RevenueEntry` and `BusinessUnit`; the Credit Exposure Rule reads `Invoice` and `Customer`. Each rule carries its aggregation in its expression, the same way the High-Risk Supplier Rule carries `riskScore >= 70`.

### Measures

A business term says what something is. A measure says what it is worth. Each measure hangs off its term by a `MEASURED_BY` edge and is backed by its own rule through `DEFINED_BY`, so the whole path down to the physical tables reuses vocabulary the model already knows:

```
BusinessTerm -MEASURED_BY-> Measure -DEFINED_BY-> BusinessRule -EVALUATES-> Entity -MAPS_TO-> DataSource
```

| Measure | Measures term | Plain meaning | Defined by | Reads (EVALUATES) |
|---|---|---|---|---|
| Supply Exposure | Critical Supplier | The recognized revenue at risk behind a critical supplier: the most recent full quarter of recognized revenue for every business unit the supplier's multi-tier `SUPPLIES` paths reach | Supply Exposure Rule | RevenueEntry, BusinessUnit |
| Credit Exposure | Ownership Risk | The total committed credit facility on a customer, with the open invoice balance being the drawn portion of that facility rather than an addition to it | Credit Exposure Rule | Invoice, Customer |

Supply Exposure is revenue at risk behind a bridge, not revenue attributable to the supplier. The dataset carries no supplier spend column, so no attribution is possible on either engine, and the measure does not claim one.

The graph holds no euros. A measure tells the graph engine which entity, which tables, and which aggregation the question needs, and the arithmetic is then handed to the lakehouse. This is why the exposure figure is a live answer rather than a stored one.

### Graph metrics

Where a measure says what a term is worth, a `GraphMetric` says how the term is detected. The two graph-native terms each name their precomputed score formally through a `SCORED_BY` edge, so the governed vocabulary is reachable from the term rather than carried only in prose.

| Graph metric | Scores term | Node property |
|---|---|---|
| Supply Betweenness | Critical Supplier | `Supplier.betweenness` |
| Ownership Contagion | Ownership Risk | `Customer.pagerank` |

The scores themselves stay Neo4j node properties and are never synced to Delta. See "GDS properties" below.

### Policies

| Policy | Governs (rules) | Constrains (entities) |
|---|---|---|
| Credit Risk Policy | Delinquent Customer Rule, Defaulted Customer Rule, Ownership Risk Rule, Credit Exposure Rule | Customer |
| Supply Chain Resilience Policy | High-Risk Supplier Rule, Critical Supplier Rule, Supply Exposure Rule | Supplier |
| Compliance (KYC) Policy | (none) | Customer (via ComplianceFinding) |

The Compliance (KYC) Policy carries no rule. It is operationalized through compliance findings, not a business rule. It stays for governance breadth and to answer "which policies govern customer data."

### Thresholds

| Threshold | Value | Applies to term |
|---|---|---|
| Supplier Risk Threshold | 70 | High-Risk Supplier |
| Late Payment Threshold | 60 days | Delinquent Customer |
| Supply Concentration Threshold | a betweenness cutoff, set from the computed distribution | Critical Supplier |
| Ownership Contagion Threshold | a stake-weighted propagated-risk (weighted personalized PageRank) cutoff, set from the computed distribution | Ownership Risk |

The two graph-native thresholds are set after the algorithms run, from the score distribution, so Cascade clears the concentration cutoff and Jade clears the contagion cutoff while no other supplier or trading customer does. They are governed values in the graph, never columns.

`APPLIES_TO` runs from the threshold to the term, so a traversal that starts at a term and follows outbound edges reaches the rule and the tables but never the number. The `USES_THRESHOLD` edge from rule to threshold closes that gap, and the graph-native rules also carry the value inline on a `threshold` property the way the column-findable rules already do. The redundancy is deliberate.

### Classifications

Column-findable classifications are pre-planted as `CLASSIFIED_AS` edges carrying provenance (reason, evaluated-at, rule version): Jade to Strategic Account; every customer carrying a recorded default, the four Kestrel members among them, to Defaulted Customer; the background high-risk suppliers to High-Risk Supplier; the background late payers to Delinquent Customer. These are deterministic facts, and the membership of each cohort is listed under `classification_cohorts` in `data/ground_truth.json`.

**The two graph-native terms are resolved live, never pre-planted.** No `CLASSIFIED_AS` edge is created for Critical Supplier or Ownership Risk. The graph engine resolves the governed definition from the ontology, then walks the graph live using the precomputed betweenness and PageRank node properties to apply it. This keeps the flag a genuine live traversal and guarantees the two graph-native labels never exist as a materializable row anywhere, so they can never leak into a gold table.

## Relationships

### Instance layer

| Relationship | Pattern | Business description | Notes |
|---|---|---|---|
| `HAS_INVOICE` | `(:Customer)-[:HAS_INVOICE]->(:Invoice)` | A customer was billed on this invoice | Payment behavior per customer |
| `BELONGS_TO` | `(:Customer)-[:BELONGS_TO]->(:BusinessUnit)` | A customer account rolls up into this internal division | Customer roll-up |
| `RECOGNIZES` | `(:BusinessUnit)-[:RECOGNIZES]->(:RevenueEntry)` | A division books this revenue entry | Revenue recognition per unit |
| `SUPPLIES` | `(:Supplier)-[:SUPPLIES]->(:BusinessUnit)` and `(:Supplier)-[:SUPPLIES]->(:Supplier)` | A supplier feeds this internal division, or a supplier feeds another supplier | Now runs at two levels: supplier-to-unit (from `supplies.csv`) and supplier-to-supplier (from `supply_relationships.csv`), giving the multi-tier supply chain Story 1 needs |
| `OWNED_BY` | `(:Customer)-[:OWNED_BY]->(:Customer)` | A customer is owned by a parent customer, holding `ownershipPct` of it | New edge, sourced from `owned_by.csv`. A customer can have several owners, so the ownership graph is a weighted multi-parent DAG rather than a tree. `ownershipPct` is the relationship weight the Story 2 propagation runs on |
| `HAS_FINDING` | `(:Customer)-[:HAS_FINDING]->(:ComplianceFinding)` | A customer has this compliance issue | Compliance exposure |

Sample a few of each instance-layer relationship:

```cypher
UNWIND ['HAS_INVOICE', 'BELONGS_TO', 'RECOGNIZES', 'SUPPLIES', 'OWNED_BY', 'HAS_FINDING'] AS relType
CALL (relType) {
  MATCH (a)-[r:$(relType)]->(b)
  RETURN a, r, b LIMIT 3
}
RETURN a, r, b;
```

### Knowledge layer

| Relationship | Pattern | Business description | Notes |
|---|---|---|---|
| `DEFINED_BY` | `(:BusinessTerm)-[:DEFINED_BY]->(:BusinessRule)` and `(:Measure)-[:DEFINED_BY]->(:BusinessRule)` | A business term or a measure is backed by this rule | One rule per term, and one rule per measure. The same edge type serves both, so nothing new has to be discovered to walk from a measure down to its tables |
| `MEASURED_BY` | `(:BusinessTerm)-[:MEASURED_BY]->(:Measure)` | A business term carries this governed euro measure | What the term is worth. Critical Supplier reaches Supply Exposure; Ownership Risk reaches Credit Exposure |
| `SCORED_BY` | `(:BusinessTerm)-[:SCORED_BY]->(:GraphMetric)` | A graph-native term is detected by this precomputed graph score | How the term is detected. Critical Supplier reaches Supply Betweenness; Ownership Risk reaches Ownership Contagion. Distinct from `MEASURED_BY`, which is valuation rather than detection |
| `USES_THRESHOLD` | `(:BusinessRule)-[:USES_THRESHOLD]->(:Threshold)` | A rule applies this governed cutoff | Gives the cutoff a forward path from the rule, since `APPLIES_TO` runs the other way and a term-outbound traversal never reaches the number |
| `EVALUATES` | `(:BusinessRule)-[:EVALUATES]->(:Entity)` | A rule operates over this logical entity | The rule reads one or more entities |
| `GOVERNS` | `(:Policy)-[:GOVERNS]->(:BusinessRule)` | A policy operationalizes this rule | Credit Risk governs the Delinquent, Defaulted, Ownership Risk, and Credit Exposure rules; Supply Chain Resilience governs the High-Risk Supplier, Critical Supplier, and Supply Exposure rules; the Compliance (KYC) Policy governs no rule, since it is operationalized through `ComplianceFinding` records |
| `CONSTRAINS` | `(:Policy)-[:CONSTRAINS]->(:Entity)` | A policy governs this logical entity | Policy scope, the entity a policy governs |
| `APPLIES_TO` | `(:Threshold)-[:APPLIES_TO]->(:BusinessTerm)` | A threshold parameterizes this term | Threshold that parameterizes a term |
| `MAPS_TO` | `(:Entity)-[:MAPS_TO]->(:DataSource)` | The semantic mapping: a logical entity is stored in this physical source | Lineage from logical entity to physical source; `DataSource.table` points at the real UC table |

Sample a few of each knowledge-layer relationship:

```cypher
UNWIND ['DEFINED_BY', 'MEASURED_BY', 'SCORED_BY', 'USES_THRESHOLD', 'EVALUATES', 'CONSTRAINS', 'GOVERNS', 'APPLIES_TO', 'MAPS_TO'] AS relType
CALL (relType) {
  MATCH (a)-[r:$(relType)]->(b)
  RETURN a, r, b LIMIT 3
}
RETURN a, r, b;
```

### Cross-layer

| Relationship | Pattern | Business description | Notes |
|---|---|---|---|
| `REALIZED_AS` | `(:Entity)-[:REALIZED_AS]->(:Customer\|:Supplier\|:BusinessUnit\|:Invoice\|:RevenueEntry\|:ComplianceFinding)` | A logical entity is realized by these physical instances | Logical entity to its physical instances. The six instance entities (Customer, Supplier, BusinessUnit, Invoice, RevenueEntry, ComplianceFinding) are realized; SupplyRelationship has a table mapping but no realized instance nodes |
| `CLASSIFIED_AS` | `(:Customer\|:Supplier)-[:CLASSIFIED_AS {reason, evaluatedAt, ruleVersion}]->(:BusinessTerm)` | An instance is labeled with a column-findable business term | Materialized classification with provenance; written back to the `classifications` Delta table. Only the four column-findable terms carry these edges. The two graph-native terms are never planted here |

Sample the cross-layer edges that tie the knowledge layer to instances:

```cypher
UNWIND ['REALIZED_AS', 'CLASSIFIED_AS'] AS relType
CALL (relType) {
  MATCH (a)-[r:$(relType)]->(b)
  RETURN a, r, b LIMIT 5
}
RETURN a, r, b;
```

The `CLASSIFIED_AS` edge is the explainability payoff for the column-findable terms: every one traces instance to business term to rule to entity to data source. The two graph-native flags are explainable too, but through a live traversal over the precomputed graph metrics rather than a stored edge.

## CSV Mapping

Each node label and each relationship type loads from one CSV in `data/`. The six core instance node CSVs and `supply_relationships.csv`, plus the `supplier_business_units.csv` bridge, are uploaded to Unity Catalog as the tables above; the knowledge-layer CSVs stay graph-only.

- Node CSVs: `customers.csv`, `suppliers.csv`, `business_units.csv`, `invoices.csv`, `revenue_entries.csv`, `compliance_findings.csv`, `entities.csv`, `business_terms.csv`, `business_rules.csv`, `measures.csv`, `graph_metrics.csv`, `policies.csv`, `thresholds.csv`, `data_sources.csv`
- Relationship CSVs: `has_invoice.csv`, `belongs_to.csv`, `recognizes.csv`, `supplies.csv`, `supply_relationships.csv`, `owned_by.csv`, `has_finding.csv`, `defined_by.csv`, `measure_defined_by.csv`, `measured_by.csv`, `scored_by.csv`, `rule_thresholds.csv`, `evaluates.csv`, `constrains.csv`, `governs.csv`, `applies_to.csv`, `maps_to.csv`, `realized_as.csv`, `classified_as.csv`
- `defined_by.csv` and `measure_defined_by.csv` both load `DEFINED_BY`, one from `BusinessTerm` and one from `Measure`; `rule_thresholds.csv` loads the `USES_THRESHOLD` edge from rule to threshold.
- Loads on both sides: `supply_relationships.csv` and `owned_by.csv`. UC gets both as tables so the lakehouse-only engine can see the raw supplier-to-supplier links and the full ownership structure with its stakes; Neo4j sources the supplier-to-supplier `SUPPLIES` edge and the `OWNED_BY` edge from the same files. Neither network is withheld from the lakehouse side.
- Lakehouse-only CSV: `supplier_business_units.csv`, the camelCase bridge uploaded to UC but not loaded into Neo4j, where the supplier-to-unit `SUPPLIES` edge already carries the link.
The `Measure` and `GraphMetric` nodes and their `MEASURED_BY`, `SCORED_BY`, and `USES_THRESHOLD` edges are knowledge-layer content and load from their own graph-only CSVs alongside the rest of the ontology. None of them is uploaded to Unity Catalog.

`classified_as.csv` carries the provenance columns `reason`, `evaluatedAt`, and `ruleVersion`, and targets both Customer and Supplier instances.

## GDS properties (precomputed, never synced to Delta)

The two graph-native terms are resolved with two Graph Data Science passes, precomputed once and stored as Neo4j node properties.

### Betweenness centrality (Critical Supplier)

- **What it does:** computes betweenness over the multi-tier supplier network (`Supplier-SUPPLIES->Supplier` edges only; the `Supplier-SUPPLIES->BusinessUnit` edges fall out of the projection because their endpoint is not a Supplier), stored as a node property on suppliers.
- **Why it matters:** a plain risk-score filter only finds individually risky suppliers. Betweenness finds the narrowest bridge: Cascade sits where five clean same-subcategory tier-1 suppliers feeding the Americas converge, so it carries the most supply flow while its own score stays middling.
- **Story line:** the score filter finds risky suppliers; the graph finds the supplier the network cannot lose.

### Personalized PageRank (Ownership Risk)

- **What it does:** computes personalized PageRank seeded on every defaulted customer in the book and propagated over the `OWNED_BY` edges with `ownershipPct` as the relationship weight, stored as a node property on customers.
- **Why it matters:** the late-payment rule only catches customers who already trip it. Weighted PageRank propagates default risk along the ownership stakes, so Jade lights up even though nothing within two hops of it has failed: the four defaults are three levels away, reached through Harbour and Tern, and the stakes along that path run 65% to 90%, so the failures arrive largely intact. Jade's own record is spotless throughout.
- **Story line:** the payment rule finds the late payers; the graph finds the clean payer holding the far end of a chain of wide stakes.

### Why they never sync to Delta

**Both scores stay as Neo4j node properties only. Neither is ever written into a Delta table.** Syncing them would re-materialize the graph's answers into a column the lakehouse-only engine could sort by, and the contrast the demo is built on would collapse: the lakehouse-only engine would tie. This is the same guardrail as the two gold tables staying out of the Genie space. The graph-native terms have no lakehouse column by design, and the GDS scores must stay in the graph to keep it that way.

## Lineage

The `MAPS_TO` edge is the semantic mapping: the data lineage that connects a logical business entity in the knowledge layer to the physical table where that data actually lives. In this demo every entity points at a real Databricks Unity Catalog table:

```
(:Entity {name:'Customer'})-[:MAPS_TO]->(:DataSource {table:'supplier_risk.customers'})
```

So "Customer" as a logical entity in the knowledge layer is realized in `supplier_risk.customers` on the lakehouse. The `DataSource.table` values are the actual UC table names (`supplier_risk.customers`, `.suppliers`, `.supply_relationships`, and so on), which is why lineage points at real Databricks assets rather than placeholders. All seven entities are mapped, and Customer is the one entity with two sources, `customers` and `owned_by`.

Lineage is one link in a longer chain that answers "where did this answer come from". A business term traces down through its rule, to the logical entity, and finally to the exact UC table backing it:

```
BusinessTerm -DEFINED_BY-> BusinessRule -EVALUATES-> Entity -MAPS_TO-> DataSource (physical table)
                                                      Entity -REALIZED_AS-> Customer/Invoice (instances)
```

The measure path is the same chain with one extra hop at the front, which is how a governed euro figure traces to the tables it must be computed over:

```
BusinessTerm -MEASURED_BY-> Measure -DEFINED_BY-> BusinessRule -EVALUATES-> Entity -MAPS_TO-> DataSource
```

### Seeing lineage in Neo4j

The lineage edges as a table, each logical entity and its physical source:

```cypher
MATCH (e:Entity)-[:MAPS_TO]->(ds:DataSource)
RETURN e.name AS entity, ds.system AS system, ds.table AS unityCatalogTable
ORDER BY entity;
```

The lineage layer as a graph, for the Browser visual:

```cypher
MATCH p = (:Entity)-[:MAPS_TO]->(:DataSource)
RETURN p;
```

Full end-to-end lineage, a business term down to its physical table:

```cypher
MATCH (t:BusinessTerm)-[:DEFINED_BY]->(r:BusinessRule)-[:EVALUATES]->(e:Entity)-[:MAPS_TO]->(ds:DataSource)
RETURN t.name AS term, r.name AS rule, e.name AS entity, ds.table AS sourceTable;
```

One entity's complete picture, its physical source and its realized instances together:

```cypher
MATCH (e:Entity {name: 'Customer'})
OPTIONAL MATCH (e)-[:MAPS_TO]->(ds:DataSource)
OPTIONAL MATCH (e)-[:REALIZED_AS]->(inst)
RETURN e, ds, inst LIMIT 25;
```

The six instance entities (`Customer`, `Supplier`, `BusinessUnit`, `Invoice`, `RevenueEntry`, `ComplianceFinding`) have `REALIZED_AS` edges to their instances; `SupplyRelationship` has lineage (`MAPS_TO`) to its table but no realized instance nodes.
