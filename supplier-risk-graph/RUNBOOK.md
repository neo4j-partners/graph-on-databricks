# supplier-risk-graph: Call Runbook

A walkthrough of the graph demo that reads on its own. It separates one-time setup
from the queries run during the session, lists the queries in order with an
explanation of what each one does and why the graph approach matters, adds a Genie
section, and closes with an appendix mapping each question to the Databricks
integration modes.

The demo answers the six validation questions and, for each one, shows which
business definition, threshold, policy, and data source backed the answer. The
questions build in graph value: Q1 to Q3 are definition lookups, Q4 to Q6 add
multi-hop provenance, and the two graph analytics extensions find what the rules cannot.

---

## Before the call (one-time setup)

Run these once, ahead of the session. None of them happen live.

1. `uv run generate_data.py` writes the CSVs and `ground_truth.json`. Deterministic, frozen as-of date 2026-07-01.
2. Fill in `.env` from `.env.sample` (Neo4j and Databricks sections).
3. `uv run load.py` wipes and loads Neo4j. Confirm with `uv run load.py --check` first: 1433 nodes, 2219 relationships.
4. `uv run gds.py` runs the two algorithms and writes results back into the graph.
5. `uv run upload.py` builds the Delta tables and the two graph-derived gold tables in `graph-on-databricks.supplier_risk`.

Setup verification checklist, so you know the graph is demo-ready:

- Neo4j Browser open on the demo database, results pane set to Table view.
- Q1 returns 2 business units, Q2 returns 6 customers, Q6 returns 3 customers. If those match, everything upstream loaded.
- Genie space published over the `supplier_risk` schema (see the Genie section).

Keep two windows visible during the call: Neo4j Browser for the Cypher, and the Genie space for the consumption story.

---

## The demo flow

The demo starts from the model, not a query. The lakehouse owns the facts, Neo4j
owns the definitions plus a mirror of the facts, so every answer can be traced
from an instance back to the business term, rule, EDM entity, and the Unity
Catalog table it came from. The diagram `dual-data-architecture.svg` shows both
layers and the two cross-layer edges that connect them.

### Definitions live in the graph (Q1 to Q3)

The first three questions are definition lookups. The threshold and the definition
come from the knowledge layer, so the answer stays consistent no matter who asks
it, instead of being baked into hardcoded SQL.

**Q1. Unreconciled revenue above the materiality threshold.** The threshold is a node, read at query time.

```cypher
MATCH (thr:Threshold {name: 'Materiality Threshold'})
MATCH (bu:BusinessUnit)-[:RECOGNIZES]->(re:RevenueEntry {reconciled: false})
WITH bu, thr.value AS threshold, sum(re.amount) AS unreconciledTotal
WHERE unreconciledTotal > threshold
RETURN bu.id AS businessUnitId, bu.name AS name,
       round(unreconciledTotal, 2) AS unreconciledTotal, threshold
ORDER BY unreconciledTotal DESC
```

Materiality is a governed threshold node rather than a number buried in a query, so finance owns it and every answer stays consistent. Result: BU-04 and BU-02.

**Q2. Customers with open KYC findings.** The KYC policy constrains the Customer entity; the entity realizes as the mirrored customers.

```cypher
MATCH (pol:Policy {name: 'KYC Policy'})-[:CONSTRAINS]->(edm:EDMEntity)-[:REALIZED_AS]->(c:Customer)
MATCH (c)-[:HAS_FINDING]->(f:ComplianceFinding {type: 'KYC', status: 'open'})
RETURN c.id AS customerId, c.name AS name, collect(f.id) AS openKycFindings
ORDER BY c.id
```

The policy is connected to the data it governs, so the query starts from the policy itself rather than from a table name. Result: 6 customers.

**Q3. Platinum customers by upsell potential.** The definition of "platinum" is a business term backed by a rule.

```cypher
MATCH (c:Customer {segment: 'platinum'})
RETURN c.id AS customerId, c.name AS name, c.upsellScore AS upsellScore
ORDER BY c.upsellScore DESC
```

`upsellScore` is an ML feature engineered in Databricks. The graph consumes it and joins it to the governed definition of a platinum customer, so feature engineering stays in the lakehouse while the definition stays governed. Result: 15 customers, led by CUST-065.

### Multi-hop provenance and explainability (Q4 to Q6)

These three questions answer the deeper ask: not just "return the rows" but
"explain which definitions and data sources were used." Each traversal reaches
across the two layers and returns the reasoning alongside the result.

**Q4. High-risk suppliers.** The threshold lives on the rule, read at query time.

```cypher
MATCH (term:BusinessTerm {name: 'High-Risk Supplier'})-[:DEFINED_BY]->(rule:BusinessRule)
MATCH (s:Supplier)
WHERE s.riskScore >= rule.threshold
RETURN s.id AS supplierId, s.name AS name, s.riskScore AS riskScore,
       rule.threshold AS threshold
ORDER BY s.riskScore DESC
```

The rule and its threshold are data, so procurement can change the policy without anyone rewriting a query. Result: 5 suppliers.

**Q5. Risky customers: more than 60 days late on each of their last three invoices.**

```cypher
MATCH (thr:Threshold {name: 'Late Payment Threshold'})
MATCH (c:Customer)-[:HAS_INVOICE]->(inv:Invoice)
WITH c, thr.value AS lateThreshold, inv
ORDER BY inv.issueDate DESC
WITH c, lateThreshold, collect(inv)[0..3] AS lastThree
WHERE size(lastThree) = 3
  AND all(i IN lastThree WHERE i.daysLate > lateThreshold)
RETURN c.id AS customerId, c.name AS name,
       [i IN lastThree | {invoiceId: i.id, daysLate: i.daysLate}] AS lastThree
ORDER BY c.id
```

This is a per-customer, ordered, last-three-of-N pattern. It reads cleanly in one graph traversal and returns the supporting invoices, not just the verdict. Result: 5 customers.

**Q6. Strategic accounts at risk.** All four risk conditions on one governed term.

```cypher
MATCH (c:Customer)-[:CLASSIFIED_AS]->(:BusinessTerm {name: 'Strategic Account'})
WHERE c.profitabilityTrend = 'declining' AND c.churnRisk = 'high'
  AND EXISTS { (c)-[:HAS_INVOICE]->(:Invoice {status: 'overdue'}) }
  AND EXISTS { (c)-[:HAS_FINDING]->(:ComplianceFinding {status: 'open'}) }
RETURN c.id AS customerId, c.name AS name,
       c.profitabilityTrend AS profitabilityTrend, c.churnRisk AS churnRisk
ORDER BY c.id
```

Strategic, declining, high churn, overdue, and an open finding, all expressed in one pattern. Result: CUST-019, CUST-065, CUST-067.

**Q6 explanation. The payoff.** For any account above, trace the full lineage.

```cypher
MATCH (c:Customer {id: 'CUST-019'})-[cls:CLASSIFIED_AS]->(term:BusinessTerm)
MATCH (term)-[:DEFINED_BY]->(rule:BusinessRule)-[:EVALUATES]->(edm:EDMEntity)-[:MAPS_TO]->(ds:DataSource)
RETURN term.name AS term, cls.reason AS reason,
       rule.name AS rule, edm.name AS edmEntity, ds.table AS dataSource
ORDER BY term.name, edm.name
```

Every classification returns why it applies through the rule, by what definition through the term, and from where through the Unity Catalog table. This traceability is the core of what the demo proves, and it is what a text or RDF glossary cannot query.

### The extensions: finding what the rules miss

Both algorithms already ran in setup and wrote their results back as
`CLASSIFIED_AS` edges, so they share the same provenance story.

**GDS Q4 exposure.** The flat rule finds five risky suppliers and misses the exposed business unit.

```cypher
MATCH (bu:BusinessUnit)
RETURN bu.id AS businessUnitId, bu.name AS name,
       bu.supplierExposureScore AS supplierExposureScore
ORDER BY bu.supplierExposureScore DESC
```

BU-03 tops the exposure list because four mid-risk suppliers feed it, none of them over the threshold. The rule finds risky suppliers; the graph finds risky exposure. Result: BU-03 first.

**GDS Q5 similarity.** kNN finds the customers trending toward the risky cohort before they trip the rule.

```cypher
MATCH (c:Customer)-[cls:CLASSIFIED_AS {source: 'gds'}]->(:BusinessTerm {name: 'Risky Customer'})
RETURN c.id AS customerId, c.name AS name,
       cls.algorithm AS algorithm, cls.score AS score, cls.reason AS reason
ORDER BY cls.score DESC
```

Rule-based classification finds the ones already defined; GDS finds the next ones, and writes them back with the same provenance shape. Result: 4 candidates.

---

## Genie: consuming the graph semantics

Genie is the consumer of what the graph produces, not a competing answer path.
The graph supplies the governed definitions and writes its classifications back
into Delta, so Genie answers over gold tables that already carry the graph's
meaning.

### Setup (one-time, before the call)

1. Confirm `upload.py` has published these tables into `graph-on-databricks.supplier_risk`:
   - Instance tables: `customers`, `suppliers`, `business_units`, `invoices`, `payments`, `revenue_entries`, `compliance_findings`.
   - Graph-derived gold tables: `classifications` (every `CLASSIFIED_AS` edge, rule- and GDS-sourced) and `business_unit_exposure` (the Q4 propagation result).
2. Create a Genie space scoped to the `supplier_risk` schema. Add all nine tables above.
3. Add general instructions to the space so Genie prefers the governed tables:
   - "`classifications` holds governed labels written back from the knowledge graph. Use it, not ad hoc heuristics, to decide who is a Risky Customer, High-Risk Supplier, Strategic Account, or Platinum Customer."
   - "The `source` column in `classifications` is `rule` for policy-based labels and `gds` for algorithm-derived ones. `reason` explains each label."
   - "`business_unit_exposure` holds supplier-risk exposure per business unit. Use `supplier_exposure_score` for aggregate exposure, not just individual `suppliers.risk_score`."
4. Add sample-question SQL for a couple of the questions below so Genie has curated examples to learn from.
5. Publish and smoke-test the space with the first question before the call.

### Sample Genie questions

Asked in the Genie space, these return answers that line up with the Cypher
results, because both read from the same governed definitions.

- "Which customers are classified as risky, and why?" Genie reads `classifications` and returns the `reason`, including the GDS-sourced candidates.
- "Which business units have the highest supplier risk exposure?" Genie reads `business_unit_exposure` and returns BU-03 at the top, matching the GDS result.
- "List our platinum customers ranked by upsell score." Matches Q3.
- "Which suppliers are high risk?" Genie reads the governed `classifications` labels rather than guessing a threshold.
- "How many strategic accounts have an open compliance finding?" Genie joins `classifications` to `compliance_findings`.

### Why the graph makes Genie better

Without the graph, Genie has to infer what "risky" or "material" or "high-risk"
means from column names. With the graph, those definitions are governed once,
written back into Delta, and Genie answers over them. It is the same Genie, now
accurate, consistent, and explainable, and cheaper because the meaning is resolved
once in the graph instead of re-derived on every prompt.

The difference is visible in a side-by-side comparison. A "risky customers"
question asked against the raw instance tables alone forces Genie to guess a
definition. The same question asked against a space that includes
`classifications` returns the governed reason and matches the Cypher exactly.

---

## Appendix: mapping to the Databricks integration modes

The demo runs one mode, Multi-Hop Native with write-back, because it is offline
and self-contained. In production each question would use whichever mode fits its
data gravity and hop count. The table below maps each question to the mode it
would use.

| Mode | What it means | Where the data sits | Best-fit questions |
|---|---|---|---|
| **Virtual** | Neo4j queries Databricks directly, leaving the data in place. | Facts stay in Unity Catalog; the knowledge layer lives in Neo4j. | Q1 to Q3. Definition lookups over large, aggregation-friendly fact tables where the graph adds the governed threshold or term but the heavy scan stays in the lakehouse. |
| **Federated** | The knowledge layer is native in Neo4j; instance facts are read from Databricks as needed. | Metadata native in Neo4j; facts federated from Unity Catalog. | Q4 and Q5. Rule-plus-threshold questions that traverse a few hops over the semantic layer while still resolving facts against the warehouse. |
| **Multi-Hop Native** | Instance data is mirrored into Neo4j; multi-hop and algorithm results are written back to Databricks. | Both layers native in Neo4j; results written back to Delta. | Q6 and the two GDS extensions. Deep provenance traversals and graph algorithms that are expensive or awkward in SQL, with the classifications written back as gold tables for Genie and BI. |

Per-question summary for the slide:

- Q1, Q2, Q3: **Virtual**. The graph governs the definition; the lakehouse keeps the scan.
- Q4, Q5: **Federated**. Multi-hop over the semantic layer, facts from the warehouse.
- Q6, GDS exposure, GDS similarity: **Multi-Hop Native**. Deep traversal and algorithms in Neo4j, results written back to Delta.

The demo's write-back tables, `classifications` and `business_unit_exposure`, are
the Multi-Hop Native story made concrete: graph-derived value landing back in
Unity Catalog where Databricks users and Genie already work.
