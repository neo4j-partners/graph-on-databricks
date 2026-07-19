# Data Architecture

The demo uses a dual data architecture. The Databricks lakehouse owns the instance layer as Unity Catalog Delta tables. Neo4j owns the knowledge layer and holds a mirror of the instance data so multi-hop and provenance queries run in one graph. One set of CSVs in `data/` is the single source for both sides.

The point of the demo is a contrast between two engines. A Databricks Genie Agent over the Unity Catalog Delta tables is the lakehouse-only engine: it sees the facts and nothing else. Genie paired with the read-only Neo4j knowledge graph is the second engine: it sees the same facts plus the governed meaning. Both engines answer the everyday risk questions. The payoff is the two graph-native questions the lakehouse-only engine cannot answer, because their definitions live only in the graph.

> **A note on "knowledge layer".** This demo uses the term narrowly, for the governed-meaning half of the graph: entities, business terms, business rules, policies, thresholds, and the semantic mapping (`MAPS_TO`), held distinct from the instance layer. The two are kept as sibling layers because the split maps directly onto the demo's division of labor: the lakehouse owns the facts, Neo4j owns the meaning.

## The two stories

The dataset serves two contrasts. Each is a question the lakehouse-only engine gets wrong or misses, and the graph engine answers by resolving a governed definition that has no lakehouse column.

### Story 1: the hidden glassworks

Cascade Glassworks is a mid-tier raw-glass supplier. Its own risk score sits in the middling band, below the risk threshold, so no risk-score sort ever surfaces it. Yet the Americas business unit depends on it disproportionately, because five clean tier-1 bottle suppliers all trace back to Cascade for their raw glass. If Cascade fails, all five paths into the Americas fail with it.

The graph engine surfaces Cascade with betweenness centrality over the multi-tier supply graph, the metric behind the **Critical Supplier** term. Cascade is the narrowest bridge on the Americas' supply paths. Roughly 4.2M EUR per quarter of Americas revenue sits behind it. The lakehouse-only engine cannot find Cascade: there is no column that says "critical", and no threshold a BI tool could sort by.

### Story 2: the clean payer in a bad family

Jade Beverage Distribution is a spotless platinum customer with a clean payment record and a Strategic Account flag. It sits inside the Kestrel Holdings ownership group, whose sibling companies (Marlin and Pelican) have defaulted. Asked for late payers, the lakehouse-only engine returns the delinquent accounts, and Jade is nowhere on the list: its own record is clean.

The graph engine flags Jade with personalized PageRank seeded on the defaulted siblings and propagated over the `OWNED_BY` edges, the metric behind the **Ownership Risk** term. Roughly 800K EUR of live exposure sits behind Jade. The lakehouse-only engine cannot find it: ownership contagion is a traversal, not a column.

## Dual data architecture

![Dual data architecture](dual-data-architecture.png)

## A note on BusinessUnit

`BusinessUnit` is an internal division of the enterprise this demo models, not a unit of a supplier or a customer. It is the shared pivot of the instance layer: customers roll up into it (`BELONGS_TO`), suppliers feed it (`SUPPLIES`), and revenue is booked against it (`RECOGNIZES`). A customer is therefore a customer of the enterprise; `BELONGS_TO` only records which internal division carries that account for revenue roll-up, and `SUPPLIES` points a vendor into the division it serves. The Americas division (`BU-03`) is the pivot for Story 1: the five tier-1 bottle suppliers all supply it, so the multi-tier path `Supplier-SUPPLIES->Supplier-SUPPLIES->BusinessUnit` converges on Cascade behind it.

## Lakehouse Tables (Unity Catalog Delta)

The lakehouse holds three kinds of table: the **core instance tables** that carry the facts, the two **gold write-back tables** the pipeline produces, and one **bridge table**. Instance-table columns are camelCase, since the CSV headers load verbatim into both Neo4j and UC. The two gold tables are snake_case, built from Cypher `RETURN` aliases.

### Core instance tables

| Table | Business description | Columns (key) | Notes |
|---|---|---|---|
| `customers` | The accounts the enterprise sells to, with commercial segment, credit line, and ownership | `id, businessUnitId, name, segment, creditLimit, parentCustomerId, defaultedPeriod, churnRisk, upsellScore, profitabilityTrend, avgDaysLate, overdueShare` | `parentCustomerId` self-references `customers.id` and sources the `OWNED_BY` edge. `creditLimit` (EUR) is set for every customer and feeds the Story 2 exposure figure. `defaultedPeriod` (format `YYYY-Qn`) is set only on defaulted customers, null otherwise |
| `suppliers` | The vendors the enterprise buys from, each carrying a procurement risk score and a specialty | `id, name, category, subcategory, riskScore` | `subcategory` is the supplier's specialty within its category (for example `glass bottles` or `raw glass` under `packaging`), never null. It is the column the lakehouse-only engine groups by in Story 1 (the "five glass-bottle suppliers, diversified" read); `riskScore` is what drives the High-Risk Supplier term |
| `business_units` | The enterprise's own internal divisions; the pivot customers roll up into, suppliers feed, and revenue is booked to | `id, name, region` | Rolls up customers, suppliers, and revenue |
| `invoices` | Bills the enterprise issued to its customers, each recording what was owed, when it was due, and how late it was paid | `id, customerId, amount, currency, issueDate, dueDate, paidDate, daysLate, status` | `customerId` joins to `customers.id`. Backs the Delinquent Customer term and Jade's open-balance exposure |
| `revenue_entries` | Revenue booked to an internal division for a period | `id, businessUnitId, period, amount, currency, reconciled` | `businessUnitId` joins to `business_units.id`. The Americas rows for the recent quarters back the Story 1 exposure figure |
| `compliance_findings` | Compliance issues (KYC, AML, sanctions) raised against a customer, open or closed | `id, customerId, type, status, openedDate` | `customerId` joins to `customers.id`. Feeds the Compliance (KYC) Policy |
| `supply_relationships` | The supplier-to-supplier links: which supplier supplies which other supplier | `fromSupplierId, toSupplierId` | New table. A row `fromSupplierId = SUP-901, toSupplierId = SUP-902` means SUP-901 supplies SUP-902. This is the one CSV that loads into both sides: UC gets the table so the lakehouse-only engine can see the raw links, and Neo4j gets the supplier-to-supplier `SUPPLIES` edges |

The commercial and payment-behavior attributes on `customers` (`churnRisk`, `upsellScore`, `profitabilityTrend`, `avgDaysLate`, `overdueShare`) provide background realism so the population looks ordinary; no story depends on them.

One bridge table, `supplier_business_units` (`supplierId, businessUnitId`), carries the many-to-many supplier-to-unit link so the lakehouse can join suppliers to the units they supply. It mirrors the supplier-to-unit `SUPPLIES` edge and is uploaded to UC but not loaded into Neo4j.

### Gold write-back tables

| Table | Business description | Columns (key) | Notes |
|---|---|---|---|
| `classifications` | Business-term labels assigned to customers and suppliers, with the reason that produced them | `entity_id, entity_type, term, reason, evaluated_at, rule_version` | Materializes the `CLASSIFIED_AS` edges written back from Neo4j, each carrying rule provenance. Because the two graph-native terms are never planted as edges, this table holds only the column-findable classifications, never Critical Supplier or Ownership Risk |
| `business_unit_exposure` | Each internal division's aggregate supplier-risk exposure | `business_unit_id, name, supplier_exposure_score, supplier_count, avg_supplier_risk, max_supplier_risk` | One row per business unit |

**The two gold tables must never be added to the Genie space.** They materialize the graph's answers into Delta. Re-adding them re-introduces write-back leakage, so the lakehouse-only engine could read the graph's conclusions straight from a column and tie. That leakage is the exact failure the demo is built to avoid, so the gold tables stay out of the space. See "GDS properties" below for the same rule applied to the graph algorithm scores.

The six core instance tables are mirrored into Neo4j as nodes; `supply_relationships` is not a node type, it sources the supplier-to-supplier `SUPPLIES` edges. Sample a few of each mirrored instance label:

```cypher
UNWIND ['Customer', 'Supplier', 'BusinessUnit', 'Invoice', 'RevenueEntry', 'ComplianceFinding'] AS label
CALL {
  WITH label
  MATCH (n) WHERE label IN labels(n)
  RETURN n LIMIT 3
}
RETURN label, n;
```

## Neo4j Nodes

### Instance layer (mirror of the lakehouse)

Because the instance CSVs are the single source for both sides, the mirror nodes also carry the foreign-key columns as properties (`Invoice.customerId`, `RevenueEntry.businessUnitId`, `ComplianceFinding.customerId`, `Customer.businessUnitId`, `Customer.parentCustomerId`). They are redundant with the instance-layer relationships below, which is what the demo's Cypher traverses.

| Label | Key properties | Business description | Notes |
|---|---|---|---|
| `Customer` | `id, name, segment, creditLimit, parentCustomerId, defaultedPeriod` | An account the enterprise sells to | `parentCustomerId` sources `OWNED_BY`; `defaultedPeriod` is set only on defaulted customers |
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
| `Entity` | `name, description` | A logical business entity in the knowledge layer | Seven entities, each mapping to one UC table |
| `BusinessTerm` | `name, definition` | A named business definition the organization agrees on | For example "Critical Supplier" or "Ownership Risk" |
| `BusinessRule` | `name, expression, description` | The machine-evaluable logic that backs a term | Machine-evaluable logic behind a term |
| `Policy` | `name, type` | A governance policy that scopes entities and rules | For example Credit Risk Policy, Supply Chain Resilience Policy |
| `Threshold` | `name, value, currency` | A parameter value a business term depends on | For example the Supplier Risk Threshold |
| `DataSource` | `name, system, table` | The physical table a logical entity is stored in | Lineage target; `table` holds the real Unity Catalog table name |

Sample a few of each knowledge-layer label:

```cypher
UNWIND ['Entity', 'BusinessTerm', 'BusinessRule', 'Policy', 'Threshold', 'DataSource'] AS label
CALL {
  WITH label
  MATCH (n) WHERE label IN labels(n)
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

`SupplyRelationship` is a new entity, mapping the new supplier-to-supplier table, so the Critical Supplier definition traces to a real table. Ownership needs no new entity: it is the `parentCustomerId` column on Customer, so it traces through the existing Customer mapping.

### Business terms

| Term | Plain meaning | Nature |
|---|---|---|
| Strategic Account | A platinum customer flagged strategic by account management | Rule, column-findable |
| Defaulted Customer | A customer with a recorded default in the snapshot | Fact, column-findable |
| Delinquent Customer | A customer more than 60 days late on each of its last three invoices | Rule, column-findable |
| High-Risk Supplier | A supplier whose procurement risk score meets or exceeds the threshold | Rule, column-findable |
| Critical Supplier | A supplier the network disproportionately depends on: the narrowest bridge on a business unit's multi-tier supply paths | Graph-native, no column |
| Ownership Risk | A customer inside an ownership group that contains a defaulted member, so its risk exceeds its own record | Graph-native, no column |

The two graph-native terms are the whole point. **Critical Supplier and Ownership Risk have no lakehouse column, no threshold a BI tool could sort by, and no clean SQL the lakehouse-only engine would spontaneously write.** Their definitions live in the graph. The four column-findable terms exist to make the contrast honest: they show what the lakehouse-only engine can govern, so the gap is clearly the two it cannot.

### Business rules

One rule defines each term, by a `DEFINED_BY` edge, and reads one or more entities, by `EVALUATES` edges.

| Rule | Defines | Plain expression | Reads (EVALUATES) |
|---|---|---|---|
| Strategic Account Rule | Strategic Account | segment is platinum and flagged strategic | Customer |
| Defaulted Customer Rule | Defaulted Customer | a default period is recorded | Customer |
| Delinquent Customer Rule | Delinquent Customer | each of the last three invoices is more than 60 days late | Customer, Invoice |
| High-Risk Supplier Rule | High-Risk Supplier | risk score is at least 70 | Supplier |
| Critical Supplier Rule | Critical Supplier | highest-betweenness bridge on a business unit's multi-tier supply paths, at or above the supply concentration threshold | Supplier, SupplyRelationship, BusinessUnit |
| Ownership Risk Rule | Ownership Risk | member of an ownership group (`OWNED_BY`, walked transitively) that contains a Defaulted Customer, with propagated risk at or above the ownership contagion threshold | Customer |

The two graph-native rules are expressed as traversals and graph metrics, never as a column predicate. Critical Supplier references betweenness over the supply network; Ownership Risk references transitive ownership plus a propagated risk score. Both read the precomputed Neo4j node properties, not a Delta column.

### Policies

| Policy | Governs (rules) | Constrains (entities) |
|---|---|---|
| Credit Risk Policy | Delinquent Customer Rule, Defaulted Customer Rule, Ownership Risk Rule | Customer |
| Supply Chain Resilience Policy | High-Risk Supplier Rule, Critical Supplier Rule | Supplier |
| Compliance (KYC) Policy | (none) | Customer (via ComplianceFinding) |

The Compliance (KYC) Policy carries no rule. It is operationalized through compliance findings, not a business rule. It stays for governance breadth and to answer "which policies govern customer data."

### Thresholds

| Threshold | Value | Applies to term |
|---|---|---|
| Supplier Risk Threshold | 70 | High-Risk Supplier |
| Late Payment Threshold | 60 days | Delinquent Customer |
| Supply Concentration Threshold | a betweenness cutoff, set from the computed distribution | Critical Supplier |
| Ownership Contagion Threshold | a propagated-risk (personalized PageRank) cutoff, set from the computed distribution | Ownership Risk |

The two graph-native thresholds are set after the algorithms run, from the score distribution, so Cascade clears the concentration cutoff and Jade clears the contagion cutoff while filler entities do not. They are governed values in the graph, never columns.

### Classifications

Column-findable classifications are pre-planted as `CLASSIFIED_AS` edges carrying provenance (source, reason, evaluated-at, rule version): Jade to Strategic Account; Marlin and Pelican to Defaulted Customer; the background high-risk suppliers to High-Risk Supplier; the background late payers to Delinquent Customer. These are deterministic facts.

**The two graph-native terms are resolved live, never pre-planted.** No `CLASSIFIED_AS` edge is created for Critical Supplier or Ownership Risk. The graph engine resolves the governed definition from the ontology, then walks the graph live using the precomputed betweenness and PageRank node properties to apply it. This keeps the flag a genuine live traversal and guarantees the two graph-native labels never exist as a materializable row anywhere, so they can never leak into a gold table.

## Relationships

### Instance layer

| Relationship | Pattern | Business description | Notes |
|---|---|---|---|
| `HAS_INVOICE` | `(:Customer)-[:HAS_INVOICE]->(:Invoice)` | A customer was billed on this invoice | Payment behavior per customer |
| `BELONGS_TO` | `(:Customer)-[:BELONGS_TO]->(:BusinessUnit)` | A customer account rolls up into this internal division | Customer roll-up |
| `RECOGNIZES` | `(:BusinessUnit)-[:RECOGNIZES]->(:RevenueEntry)` | A division books this revenue entry | Revenue recognition per unit |
| `SUPPLIES` | `(:Supplier)-[:SUPPLIES]->(:BusinessUnit)` and `(:Supplier)-[:SUPPLIES]->(:Supplier)` | A supplier feeds this internal division, or a supplier feeds another supplier | Now runs at two levels: supplier-to-unit (from `supplies.csv`) and supplier-to-supplier (from `supply_relationships.csv`), giving the multi-tier supply chain Story 1 needs |
| `OWNED_BY` | `(:Customer)-[:OWNED_BY]->(:Customer)` | A customer is owned by a parent customer | New edge, sourced from `parentCustomerId`. Builds the ownership groups Story 2 needs |
| `HAS_FINDING` | `(:Customer)-[:HAS_FINDING]->(:ComplianceFinding)` | A customer has this compliance issue | Compliance exposure |

Sample a few of each instance-layer relationship:

```cypher
UNWIND ['HAS_INVOICE', 'BELONGS_TO', 'RECOGNIZES', 'SUPPLIES', 'OWNED_BY', 'HAS_FINDING'] AS relType
CALL {
  WITH relType
  MATCH (a)-[r]->(b) WHERE type(r) = relType
  RETURN a, r, b LIMIT 3
}
RETURN a, r, b;
```

### Knowledge layer

| Relationship | Pattern | Business description | Notes |
|---|---|---|---|
| `DEFINED_BY` | `(:BusinessTerm)-[:DEFINED_BY]->(:BusinessRule)` | A business term is backed by this rule | One rule per term |
| `EVALUATES` | `(:BusinessRule)-[:EVALUATES]->(:Entity)` | A rule operates over this logical entity | The rule reads one or more entities |
| `GOVERNS` | `(:Policy)-[:GOVERNS]->(:BusinessRule)` | A policy operationalizes this rule | Credit Risk governs the Delinquent, Defaulted, and Ownership Risk rules; Supply Chain Resilience governs the High-Risk Supplier and Critical Supplier rules; the Compliance (KYC) Policy governs no rule, since it is operationalized through `ComplianceFinding` records |
| `CONSTRAINS` | `(:Policy)-[:CONSTRAINS]->(:Entity)` | A policy governs this logical entity | Policy scope, the entity a policy governs |
| `APPLIES_TO` | `(:Threshold)-[:APPLIES_TO]->(:BusinessTerm)` | A threshold parameterizes this term | Threshold that parameterizes a term |
| `MAPS_TO` | `(:Entity)-[:MAPS_TO]->(:DataSource)` | The semantic mapping: a logical entity is stored in this physical source | Lineage from logical entity to physical source; `DataSource.table` points at the real UC table |

Sample a few of each knowledge-layer relationship:

```cypher
UNWIND ['DEFINED_BY', 'EVALUATES', 'CONSTRAINS', 'GOVERNS', 'APPLIES_TO', 'MAPS_TO'] AS relType
CALL {
  WITH relType
  MATCH (a)-[r]->(b) WHERE type(r) = relType
  RETURN a, r, b LIMIT 3
}
RETURN a, r, b;
```

### Cross-layer

| Relationship | Pattern | Business description | Notes |
|---|---|---|---|
| `REALIZED_AS` | `(:Entity)-[:REALIZED_AS]->(:Customer\|:Supplier\|:BusinessUnit\|:Invoice\|:RevenueEntry\|:ComplianceFinding)` | A logical entity is realized by these physical instances | Logical entity to its physical instances. The six instance entities (Customer, Supplier, BusinessUnit, Invoice, RevenueEntry, ComplianceFinding) are realized; SupplyRelationship has a table mapping but no realized instance nodes |
| `CLASSIFIED_AS` | `(:Customer\|:Supplier)-[:CLASSIFIED_AS {source, reason, evaluatedAt, ruleVersion}]->(:BusinessTerm)` | An instance is labeled with a column-findable business term | Materialized classification with provenance; written back to the `classifications` Delta table. Only the four column-findable terms carry these edges. The two graph-native terms are never planted here |

Sample the cross-layer edges that tie the knowledge layer to instances:

```cypher
UNWIND ['REALIZED_AS', 'CLASSIFIED_AS'] AS relType
CALL {
  WITH relType
  MATCH (a)-[r]->(b) WHERE type(r) = relType
  RETURN a, r, b LIMIT 5
}
RETURN a, r, b;
```

The `CLASSIFIED_AS` edge is the explainability payoff for the column-findable terms: every one traces instance to business term to rule to entity to data source. The two graph-native flags are explainable too, but through a live traversal over the precomputed graph metrics rather than a stored edge.

## CSV Mapping

Each node label and each relationship type loads from one CSV in `data/`. The six core instance node CSVs and `supply_relationships.csv`, plus the `supplier_business_units.csv` bridge, are uploaded to Unity Catalog as the tables above; the knowledge-layer CSVs stay graph-only.

- Node CSVs: `customers.csv`, `suppliers.csv`, `business_units.csv`, `invoices.csv`, `revenue_entries.csv`, `compliance_findings.csv`, `entities.csv`, `business_terms.csv`, `business_rules.csv`, `policies.csv`, `thresholds.csv`, `data_sources.csv`
- Relationship CSVs: `has_invoice.csv`, `belongs_to.csv`, `recognizes.csv`, `supplies.csv`, `supply_relationships.csv`, `owned_by.csv`, `has_finding.csv`, `defined_by.csv`, `evaluates.csv`, `constrains.csv`, `governs.csv`, `applies_to.csv`, `maps_to.csv`, `realized_as.csv`, `classified_as.csv`
- Loads on both sides: `supply_relationships.csv`. UC gets it as the `supply_relationships` table so the lakehouse-only engine can see the raw supplier-to-supplier links; Neo4j sources the supplier-to-supplier `SUPPLIES` edge from the same file.
- Lakehouse-only CSV: `supplier_business_units.csv`, the camelCase bridge uploaded to UC but not loaded into Neo4j, where the supplier-to-unit `SUPPLIES` edge already carries the link.

`classified_as.csv` carries the provenance columns `reason`, `evaluatedAt`, and `ruleVersion`, and targets both Customer and Supplier instances.

## GDS properties (precomputed, never synced to Delta)

The two graph-native terms are resolved with two Graph Data Science passes, precomputed once and stored as Neo4j node properties.

### Betweenness centrality (Critical Supplier)

- **What it does:** computes betweenness over the multi-tier supplier network (`Supplier-SUPPLIES->Supplier` and `Supplier-SUPPLIES->BusinessUnit`), stored as a node property on suppliers.
- **Why it matters:** a plain risk-score filter only finds individually risky suppliers. Betweenness finds the narrowest bridge: Cascade sits where five clean same-subcategory tier-1 suppliers feeding the Americas converge, so it carries the most supply flow while its own score stays middling.
- **Story line:** the score filter finds risky suppliers; the graph finds the supplier the network cannot lose.

### Personalized PageRank (Ownership Risk)

- **What it does:** computes personalized PageRank seeded on the defaulted siblings and propagated over the `OWNED_BY` edges, stored as a node property on customers.
- **Why it matters:** the late-payment rule only catches customers who already trip it. PageRank propagates default risk through ownership, so Jade lights up because its siblings defaulted, even though its own record is spotless.
- **Story line:** the payment rule finds the late payers; the graph finds the clean payer in a bad family.

### Why they never sync to Delta

**Both scores stay as Neo4j node properties only. Neither is ever written into a Delta table.** Syncing them would re-materialize the graph's answers into a column the lakehouse-only engine could sort by, and the contrast the demo is built on would collapse: the lakehouse-only engine would tie. This is the same guardrail as the two gold tables staying out of the Genie space. The graph-native terms have no lakehouse column by design, and the GDS scores must stay in the graph to keep it that way.

## Lineage

The `MAPS_TO` edge is the semantic mapping: the data lineage that connects a logical business entity in the knowledge layer to the physical table where that data actually lives. In this demo every entity points at a real Databricks Unity Catalog table:

```
(:Entity {name:'Customer'})-[:MAPS_TO]->(:DataSource {table:'supplier_risk.customers'})
```

So "Customer" as a logical entity in the knowledge layer is realized in `supplier_risk.customers` on the lakehouse. The `DataSource.table` values are the actual UC table names (`supplier_risk.customers`, `.suppliers`, `.supply_relationships`, and so on), which is why lineage points at real Databricks assets rather than placeholders. All seven entities have a 1:1 mapping.

Lineage is one link in a longer chain that answers "where did this answer come from". A business term traces down through its rule, to the logical entity, and finally to the exact UC table backing it:

```
BusinessTerm -DEFINED_BY-> BusinessRule -EVALUATES-> Entity -MAPS_TO-> DataSource (physical table)
                                                      Entity -REALIZED_AS-> Customer/Invoice (instances)
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
