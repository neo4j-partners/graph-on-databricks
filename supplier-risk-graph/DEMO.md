# Demo walkthrough

This walkthrough assumes the one-time setup in the [`README.md`](README.md) is done: the data is generated, Neo4j is loaded, the GDS analytics have run, the Unity Catalog tables are uploaded, and the Genie space is created. It walks the six validation questions and then the Genie flow that consumes the graph's semantics.

The questions build in graph value:

- **Q1 to Q3:** definition lookups. The threshold and the definition come from the knowledge layer.
- **Q4 to Q6:** add multi-hop provenance across both layers, returning the reasoning alongside the result.
- **Two analytics passes:** find what the flat rules cannot. One is a supplier-risk exposure aggregation for Q4; the other is a Graph Data Science algorithm, kNN customer similarity, for Q5 and Q6.

Each query resolves its definition in the knowledge layer and pulls its facts from the mirrored instance data. Thresholds are read from the graph, never hardcoded. Graph properties and the instance tables use camelCase, so the Cypher below runs unchanged against either side. See [`DATA_ARCHITECTURE.md`](DATA_ARCHITECTURE.md) for the full label, relationship, and property model.

## Note on Cypher Functions: a quick primer

A few functions appear repeatedly:

- `sum(...)`, `round(...)`, `size(...)` do what their names suggest.
- `collect(...)` gathers many rows into a single list, the graph way of grouping child rows under a parent.
- `[0..3]` slices the first three elements off a list.
- `all(x IN list WHERE ...)` is true only when every element passes the test.
- `EXISTS { (pattern) }` is true when that sub-pattern exists at all, a cheap "is there at least one" check without pulling the rows back.

## The six questions

Each query resolves its definition in the knowledge layer and pulls its facts from the mirrored instance data. Thresholds are read from the graph, never hardcoded. The queries are grouped by how much graph they use:

- **First three:** look up a governed definition.
- **Next three:** traverse across both layers for provenance.
- **Extensions at the end:** find what the rules alone miss.

### Definitions live in the graph (Q1 to Q3)

The first three questions are definition lookups. The threshold and the definition come from the knowledge layer, so the answer stays consistent no matter who asks it, instead of being baked into hardcoded SQL.

#### Q1 — Unreconciled revenue above the materiality threshold, per business unit

**Plain English:** "Which business units have enough unmatched revenue above the materiality threshold that we'd better take a look at? And what is the materiality threshold currently set as?"

Sums unreconciled revenue per business unit and keeps only the units whose total exceeds the Materiality Threshold read from the Threshold node. Backed by rule RULE-05, term "Unreconciled Revenue" (TERM-05), and Threshold "Materiality Threshold" (THR-01, 100000 EUR). Facts come from the `revenue_entries` table via `RevenueEntry`.

```cypher
MATCH (thr:Threshold {name: 'Materiality Threshold'})
MATCH (bu:BusinessUnit)-[:RECOGNIZES]->(re:RevenueEntry {reconciled: false})
WITH bu, thr.value AS threshold, sum(re.amount) AS unreconciledTotal
WHERE unreconciledTotal > threshold
RETURN bu.id AS businessUnitId, bu.name AS name,
       round(unreconciledTotal, 2) AS unreconciledTotal, threshold
ORDER BY unreconciledTotal DESC
```

Essentially it grabs the materiality threshold node so we have the number to compare against. Then follow every business unit out to the revenue entries it recognizes, keeping only the unreconciled ones, and add up their amounts per business unit. Keep the business units whose unreconciled total is over the threshold, and sort the biggest first.

Why the graph: materiality is a governed threshold node rather than a number buried in a query, so finance owns it and every answer stays consistent.

Expected: 2 units, BU-04 Asia Pacific (189924.86) and BU-02 Southern Europe (175803.01).

#### Q2 — Customers with open KYC compliance findings

**Plain English:** "Which customers have open KYC compliance findings that we still need to clear? And which policy defines what KYC covers?"

- **What it does:** starts at the KYC Policy, walks to the Customer entity it constrains, follows that entity to the mirrored `Customer` instances, and keeps the ones with an open KYC finding.
- **Backed by:** policy "KYC Policy" (POL-01), which CONSTRAINS the Customer entity (ENT-01).
- **Scope note:** KYC constrains the Customer *entity* and is operationalized through `ComplianceFinding` records, not a business rule, so it `GOVERNS` no rule. The Platinum, Strategic Account, and Risky Customer rules also evaluate the Customer entity, but they are commercial and credit definitions, not part of the KYC policy. Read `(:Policy)-[:GOVERNS]->(:BusinessRule)` to see what a policy operationalizes rather than inferring it from the shared entity.
- **Facts from:** `customers` and `compliance_findings`.
- **Where the findings come from:** the compliance findings are synthetic demo data, not real regulatory filings. `generate_data.py` deterministically selects a 6-customer KYC cohort from a fixed seed, which includes the first at-risk strategic account, and gives each customer one or two findings of `type: KYC, status: open`. Those rows land in the `compliance_findings` table (DS-07), and the loader mirrors them into Neo4j as `ComplianceFinding` nodes linked to each customer by `HAS_FINDING`. The cohort is sized so Q2 returns exactly 6 customers.

```cypher
MATCH (pol:Policy {name: 'KYC Policy'})-[:CONSTRAINS]->(entity:Entity)-[:REALIZED_AS]->(c:Customer)
MATCH (c)-[:HAS_FINDING]->(f:ComplianceFinding {type: 'KYC', status: 'open'})
RETURN c.id AS customerId, c.name AS name, collect(f.id) AS openKycFindings
ORDER BY c.id
```

Start at the KYC Policy, walk to the entity it constrains, then out to the real customers that entity stands for. From each of those customers, follow the findings and keep only the open KYC ones. Return each customer once, with the list of their open findings gathered together.

Why the graph: the policy is connected to the data it governs, so the query starts from the policy itself rather than from a table name.

Expected: 6 customers, CUST-016, CUST-017, CUST-024, CUST-040, CUST-067, CUST-080.

#### Q3 — Platinum customers ranked by upsell score

**Plain English:** "Which of our platinum customers are the best bets to sell more to, ranked by upsell score? And how is a platinum customer defined?"

Returns platinum-segment customers ordered by upsell score. Backed by term "Platinum Customer" (TERM-01) and rule RULE-01 (`customer.segment = 'platinum'`). Facts come from `customers`, including the derived `upsellScore` ML feature.

```cypher
MATCH (c:Customer {segment: 'platinum'})
RETURN c.id AS customerId, c.name AS name, c.upsellScore AS upsellScore
ORDER BY c.upsellScore DESC
```

Find the customers whose segment is platinum, and list them highest upsell score first.

Why the graph: `upsellScore` is an ML feature engineered in Databricks. The graph consumes it and joins it to the governed definition of a platinum customer, so feature engineering stays in the lakehouse while the definition stays governed.

Expected: 15 customers, led by CUST-065 Orchid Retail (100), CUST-019 Alder Drinks Co (99), CUST-011 Ridgeline Trading (98).

### Multi-hop provenance and explainability (Q4 to Q6)

These three questions answer the deeper ask: not just "return the rows" but "explain which definitions and data sources were used". Each traversal reaches across the two layers and returns the reasoning alongside the result.

#### Q4 — High-risk suppliers

**Plain English:** "Which suppliers are risky enough that we should worry about relying on them? And what is the supplier risk threshold currently set as?"

Reads the supplier risk threshold from the rule behind the High-Risk Supplier term, then returns suppliers at or above it. Backed by rule RULE-03 and term "High-Risk Supplier" (TERM-03); the threshold of 70 is stored on the rule and also as Threshold "Supplier Risk Threshold" (THR-02). Facts come from `suppliers`.

```cypher
MATCH (term:BusinessTerm {name: 'High-Risk Supplier'})-[:DEFINED_BY]->(rule:BusinessRule)
MATCH (s:Supplier)
WHERE s.riskScore >= rule.threshold
RETURN s.id AS supplierId, s.name AS name, s.riskScore AS riskScore,
       rule.threshold AS threshold
ORDER BY s.riskScore DESC
```

In plain English: walk from the High-Risk Supplier term to the rule that defines it, and read the threshold number off that rule. Then keep every supplier whose risk score is at least that number, riskiest first.

Why the graph: the rule and its threshold are data, so procurement can change the policy without anyone rewriting a query.

Expected: 5 suppliers, SUP-024 (94), SUP-010 (90), SUP-003 (86), SUP-007 (85), SUP-001 (77).

#### Q5 — Risky customers: more than 60 days late on each of their last 3 invoices

**Plain English:** "Which customers have been more than the late-payment threshold days late on each of their last three invoices? And what is the late payment threshold currently set as?"

For each customer, takes the three most recent invoices by issue date and keeps only customers whose all three are more than the Late Payment Threshold days late. Backed by rule RULE-04, term "Risky Customer" (TERM-04), and Threshold "Late Payment Threshold" (THR-03, 60). Facts come from `invoices`.

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

Read the late-payment threshold, then for each customer pull all their invoices sorted newest first, and take just the top three into a list. Drop any customer without a full three, then keep only the customers where all three of those recent invoices were more than the threshold days late. Return each surviving customer with those three invoices and how late each was.

Why the graph: this is a per-customer, ordered, last-three-of-N pattern. It reads cleanly in one traversal and returns the supporting invoices, not just the verdict.

Expected: 5 customers, CUST-015, CUST-020, CUST-036, CUST-067, CUST-091.

#### Q6 — Strategic accounts at risk

**Plain English:** "Which strategic accounts are at risk on every dimension — declining profitability, high churn risk, at least one overdue invoice, and at least one open compliance finding? And how is a strategic account defined?"

A strategic account that is also trending down on every risk dimension: profitability declining, churn risk high, at least one overdue invoice, and at least one open compliance finding. Backed by term "Strategic Account" (TERM-02), whose `CLASSIFIED_AS` edges are pre-planted. Facts come from `customers`, `invoices`, and `compliance_findings`.

```cypher
MATCH (c:Customer)-[:CLASSIFIED_AS]->(:BusinessTerm {name: 'Strategic Account'})
WHERE c.profitabilityTrend = 'declining' AND c.churnRisk = 'high'
  AND EXISTS { (c)-[:HAS_INVOICE]->(:Invoice {status: 'overdue'}) }
  AND EXISTS { (c)-[:HAS_FINDING]->(:ComplianceFinding {status: 'open'}) }
RETURN c.id AS customerId, c.name AS name,
       c.profitabilityTrend AS profitabilityTrend, c.churnRisk AS churnRisk
ORDER BY c.id
```

Start with the customers already classified as Strategic Accounts. Keep the ones whose profitability is declining and whose churn risk is high, and that also have at least one overdue invoice and at least one open compliance finding. All four conditions, expressed as one pattern.

Why the graph: strategic, declining, high churn, overdue, and an open finding, all checked in a single readable pattern.

Expected: 3 customers, CUST-019, CUST-065, CUST-067. CUST-067 also appears in Q2 and Q5; the cohorts overlap by design.

#### Q6 explanation query — the explainability payoff

For any strategic-at-risk customer, this returns the business terms it is classified as, plus the full lineage from term to backing rule to entity to the real Unity Catalog table. Every answer can be traced from instance to definition to data source.

```cypher
MATCH (c:Customer {id: 'CUST-019'})-[cls:CLASSIFIED_AS]->(term:BusinessTerm)
MATCH (term)-[:DEFINED_BY]->(rule:BusinessRule)-[:EVALUATES]->(entity:Entity)-[:MAPS_TO]->(ds:DataSource)
RETURN term.name AS term, cls.reason AS reason,
       rule.name AS rule, entity.name AS entity, ds.table AS dataSource
ORDER BY term, entity
```

Pick one customer, follow every "classified as" edge to the business terms it carries, and read the reason recorded on each edge. From each term, keep walking the same chain every time: term to the rule that defines it, rule to the entity it evaluates, entity to the physical table it maps to. The result is one row per classification showing what it is, why it applies, and where the data lives.

For CUST-019 this returns the Platinum Customer and Strategic Account terms, their rules RULE-01 and RULE-02, the Customer entity, and the `supplier_risk.customers` table. This traceability is the core of what the demo proves, and it is what a text or RDF glossary cannot query.

## The two graph analytics extensions

Q4 is a plain Cypher exposure aggregation; Q5/Q6 is the one genuine GDS algorithm, kNN. Both ran during setup and wrote their results back into the graph, so they join the same provenance story and flow into Unity Catalog. They are deterministic given the fixed-seed data.

### Q4 exposure — supplier risk to business unit exposure

The flat rule finds individually risky suppliers but says nothing about aggregate exposure. `gds.py` aggregates supplier risk over the `Supplier-SUPPLIES->BusinessUnit` edges and writes the mean supplying-supplier risk onto each `BusinessUnit` as `supplierExposureScore`. This result is materialized to the `business_unit_exposure` gold table by `upload.py`.

The flat rule finds the 5 obvious suppliers and misses BU-03:

```cypher
MATCH (s:Supplier)
WHERE s.riskScore >= 70
RETURN s.id AS supplierId, s.name AS name, s.riskScore AS riskScore
ORDER BY s.riskScore DESC
```

The mean-exposure aggregation surfaces BU-03 Americas at the top, even though none of its suppliers cross 70:

```cypher
MATCH (bu:BusinessUnit)
RETURN bu.id AS businessUnitId, bu.name AS name,
       bu.supplierExposureScore AS supplierExposureScore
ORDER BY bu.supplierExposureScore DESC
```

The first query is the flat rule again, listing suppliers over 70. The second reads the exposure score the analytics pass already wrote onto each business unit and sorts the most exposed first. That score is the average risk of the suppliers feeding a unit, so a unit can rank high even when no single supplier trips the rule.

Expected top result: BU-03 Americas. It is served by 4 mid-risk suppliers with an average risk of 64.2 and no single score over 67, so the flat filter never sees it. Demo line: the rule finds risky suppliers; the graph finds risky exposure.

### Q5 / Q6 similarity — the next risky customers

`gds.py` runs GDS kNN over the payment-behavior features `avgDaysLate`, `overdueShare`, `churnRisk`, and `profitabilityTrend` to build the similarity graph, then classifies the non-flagged customers most similar to the known risky cohort. It writes `CLASSIFIED_AS {source: 'gds', algorithm: 'knn', score, evaluatedAt, reason}` edges from those candidates to the "Risky Customer" term, where `score` is the kNN similarity to the nearest risky member. These flow into the `classifications` gold table via `upload.py`.

```cypher
MATCH (c:Customer)-[cls:CLASSIFIED_AS {source: 'gds'}]->(:BusinessTerm {name: 'Risky Customer'})
RETURN c.id AS customerId, c.name AS name,
       cls.algorithm AS algorithm, cls.score AS score, cls.reason AS reason
ORDER BY cls.score DESC
```

This reads back what the algorithm already decided. It finds every "classified as" edge that the GDS pass wrote to the Risky Customer term, and returns those customers with the algorithm name, similarity score, and reason, closest to the risky cohort first.

Expected: 4 candidates, the non-flagged customers the kNN run ranks most similar to the risky cohort. None trips the last-3-invoices rule, but each sits close to the known risky cohort. The specific four emerge from the run rather than a planted list; check the `gds.py` output for the current set. Demo line: rule-based classification finds the ones already defined; GDS finds the next ones.

## Expected results

From `ground_truth.json`, so you can verify a load worked.

| Question | Result | Count |
|---|---|---|
| Q1 unreconciled business units | BU-04, BU-02 | 2 |
| Q2 open KYC violators | CUST-016, CUST-017, CUST-024, CUST-040, CUST-067, CUST-080 | 6 |
| Q3 platinum by upsell | led by CUST-065, CUST-019, CUST-011 | 15 |
| Q4 high-risk suppliers | SUP-024, SUP-010, SUP-003, SUP-007, SUP-001 | 5 |
| Q5 risky customers | CUST-015, CUST-020, CUST-036, CUST-067, CUST-091 | 5 |
| Q6 strategic at risk | CUST-019, CUST-065, CUST-067 | 3 |
| GDS Q4 exposed business unit | BU-03 Americas (top by exposure) | 1 |

The GDS Q5/Q6 similarity candidates are not listed here: they emerge from the kNN run rather than a frozen key, so `gds.py` checks only their shape (four non-flagged customers, each near the risky cohort) and prints the current set.

## How Genie consumes the graph semantics

Genie is the consumer of what the graph produces, not a competing answer path.

- **Governed definitions:** the graph supplies the definitions that make Genie answers accurate, cheaper, and explainable.
- **Write-back:** classifications land in Delta, so Genie answers over gold tables that already carry the graph's meaning.
- **Meaning, not guesswork:** when a user asks "which business units have material unreconciled revenue" or "who are our high-risk suppliers", the meaning of "material" and "high-risk" lives in the knowledge layer as thresholds and rules, not an ad hoc SQL guess.
- **Resolved once:** the graph resolves the definition once, points at the real Unity Catalog tables through `MAPS_TO` lineage, and both rule-based and GDS-scored classifications flow back into Delta so Databricks users see the graph value in their own tables.

For the one-time setup that creates and configures the Genie space, see [`README.md`](README.md).

### Sample Genie questions

Asked in the Genie space, these return answers that line up with the Cypher results, because both read from the same governed definitions.

- "Which customers are classified as risky, and what rule or model classified them and why?" Genie reads `classifications` and returns the `source` and `reason`, including the GDS-sourced candidates.
- "Which business units carry the highest supplier risk exposure, and what business rule categorizes them and why?" Genie reads `business_unit_exposure` and returns BU-03 at the top, matching the GDS result, with the exposure score as the reason.
- "List our platinum customers ranked by upsell score, and what rule defines a platinum customer?" Matches Q3; Genie returns the ranking and the governed Platinum Customer label from `classifications`.
- "Which suppliers are high risk, and what rule categorizes them as high-risk and why?" Genie reads the governed `classifications` labels and their `reason` rather than guessing a threshold.
- "How many strategic accounts have an open compliance finding, and what rule classifies them as strategic accounts?" Genie joins `classifications` (term = Strategic Account) to `customers` on `entity_id = id`, then to `compliance_findings` on `customerId`, and returns the classification `reason`.

### Why the graph makes Genie better

Without the graph, Genie has to infer what "risky" or "material" or "high-risk" means from column names. With the graph, those definitions are governed once, written back into Delta, and Genie answers over them. It is the same Genie, now accurate, consistent, and explainable, and cheaper because the meaning is resolved once in the graph instead of re-derived on every prompt.

The difference is visible in a side-by-side comparison. A "risky customers" question asked against the raw instance tables alone forces Genie to guess a definition. The same question asked against a space that includes `classifications` returns the governed reason and matches the Cypher exactly.

## A multi-agent supervisor over Genie and the graph

Expose the Neo4j instance as an MCP server and a supervisor agent can pair it with the Genie space to answer questions and explain their provenance from the knowledge layer. The two agents have complementary jobs, and the split matches the two layers this demo already builds.

- **Genie agent (facts):** scans, aggregations, and joins over the gold tables. It answers how much, how many, and which rows over `customers`, `invoices`, `business_unit_exposure`, and `classifications`.
- **Neo4j MCP agent (meaning):** holds what Genie cannot infer from column names. Business term definitions, rule expressions, threshold values, policy scope, and the `MAPS_TO`, `REALIZED_AS`, and `CLASSIFIED_AS` lineage.
- **Supervisor:** routes and stitches. It resolves the definition in the graph first, hands Genie a precise parameterized query, then asks the graph for the provenance chain behind the answer Genie produced.

An off-the-shelf Neo4j Cypher MCP server exposes read-only, parameterized Cypher as tools, so the MCP layer does not have to be built from scratch. Keep it read-only so the agent cannot mutate the graph.

### What to put in the MCP server description

The supervisor decides when to call the graph from the server description alone, so make it spell out the graph's job, its shape, and the provenance pattern. Paste the block below into the server or tool `description` field and adjust names to match your deployment.

```text
This server exposes a Neo4j knowledge graph for the supplier and customer risk
domain. Use it to resolve governed business definitions and to explain the
provenance behind an answer. Databricks Genie owns the raw facts and
aggregations; this graph owns their meaning and lineage.

Use this server to:
- Resolve what a business term means before querying facts. Terms: Platinum
  Customer, Strategic Account, High-Risk Supplier, Risky Customer, Unreconciled
  Revenue.
- Read a governed threshold value instead of assuming one. Thresholds:
  Materiality Threshold, Supplier Risk Threshold, Late Payment Threshold.
- Explain why a record was classified, tracing it to the rule, entity, and
  source table behind it.
- Answer policy, governance, and impact questions that span definitions.

Do NOT use this server for large scans, counts, sums, or joins over the fact
tables. Send those to Genie.

Graph shape. Knowledge layer: Entity, BusinessTerm, BusinessRule, Policy,
Threshold, DataSource. Instance layer, a mirror of the lakehouse tables:
Customer, Supplier, BusinessUnit, Invoice, Payment, RevenueEntry,
ComplianceFinding.

Key relationships:
- (:BusinessTerm)-[:DEFINED_BY]->(:BusinessRule): the rule behind a term.
- (:BusinessRule)-[:EVALUATES]->(:Entity): what the rule operates on.
- (:Threshold)-[:APPLIES_TO]->(:BusinessTerm): the number parameterizing a term.
- (:Policy)-[:CONSTRAINS]->(:Entity): policy scope, the entity a policy governs.
- (:Policy)-[:GOVERNS]->(:BusinessRule): the rules a policy operationalizes. Read
  this to find a policy's rules; do NOT infer them from a shared Entity. The
  KYC Policy constrains the Customer entity but governs no rule (it is
  operationalized through ComplianceFinding records), even though the Platinum,
  Strategic, and Risky Customer rules also evaluate the Customer entity.
- (:Entity)-[:MAPS_TO]->(:DataSource): semantic mapping (lineage); DataSource.table
  is the real Unity Catalog table.
- (:Customer|:Supplier)-[:CLASSIFIED_AS]->(:BusinessTerm): a classification. The
  edge carries reason, source of 'rule' or 'gds', algorithm, and score.

To explain any classification, walk:
  instance -[:CLASSIFIED_AS]-> term -[:DEFINED_BY]-> rule
           -[:EVALUATES]-> entity -[:MAPS_TO]-> dataSource
Return the term, the reason on the edge, the rule expression, and
DataSource.table.

Conventions:
- All properties are camelCase.
- Node ids are stable prefixes: ENT-0x, TERM-0x, RULE-0x, POL-0x, THR-0x, DS-0x,
  CUST-0xx, SUP-0xx, BU-0x.
- The graph is read-only. Emit read Cypher only, and prefer parameters over
  string interpolation.
```

### What to put in the Genie space description

The supervisor routes fact and count questions to Genie, so its description has to say what Genie owns and, just as important, what it does not. Paste the block below into the Genie space instructions or the tool `description` the supervisor sees.

```text
This Genie space answers questions over the supplier and customer risk data in
Unity Catalog schema supplier_risk. Use it for facts and for the governed labels
the graph wrote back. The Neo4j graph owns definitions, relationships, and
provenance; this space owns the numbers.

Use this space to:
- Return rows, counts, totals, and rankings from a single table: customers by
  segment, suppliers by risk, invoices by status.
- Read graph-derived labels from classifications and exposure scores from
  business_unit_exposure. Prefer these governed tables over recomputing a
  definition from raw columns.
- Apply a threshold the graph already resolved. Pass the concrete value in the
  question.

Do NOT use this space to:
- Invent what a business term means. If a question depends on material,
  high-risk, risky, strategic, or platinum, resolve it in the graph first.
- Trace long provenance chains. A join or two is fine here; anything deeper, or
  any why-was-this-classified question, belongs to the graph.

Tables and joins:
- Instance tables, primary key id, camelCase columns: customers, suppliers,
  business_units, invoices, payments, revenue_entries, compliance_findings.
- Foreign keys on the instance tables: invoices.customerId and
  compliance_findings.customerId join to customers.id; payments.invoiceId joins
  to invoices.id; revenue_entries.businessUnitId and customers.businessUnitId
  join to business_units.id.
- supplier_business_units (bridge): supplierId, businessUnitId. Join suppliers to
  the units they supply; the supplier-to-unit link is many-to-many.
- classifications (gold, snake_case): entity_id, entity_type, term, source,
  algorithm, score, reason, evaluated_at, rule_version. source is 'rule' or
  'gds'; reason explains each label. Join entity_id back to a customer or
  supplier id. Use this, not ad hoc heuristics, to decide who is a Risky
  Customer, High-Risk Supplier, Strategic Account, or Platinum Customer.
- business_unit_exposure (gold, snake_case): business_unit_id, name,
  supplier_exposure_score, supplier_count, avg_supplier_risk, max_supplier_risk.
  Use supplier_exposure_score for aggregate exposure, not raw supplier scores.

Conventions:
- Instance-table columns, including the foreign keys, are camelCase: riskScore,
  upsellScore, daysLate, issueDate, customerId. The two gold tables are
  snake_case.
- The primary key on every instance table is id.
```

### Provenance the supervisor can explain

For any answer it can walk the same chain the Q6 explanation query uses and cite each hop:

- **Instance to term:** a `Customer` or `Supplier` is `CLASSIFIED_AS` a `BusinessTerm`, with the `reason` recorded on the edge.
- **Term to rule:** `BusinessTerm` `DEFINED_BY` `BusinessRule`, the actual expression.
- **Rule to entity:** `BusinessRule` `EVALUATES` `Entity`.
- **Entity to source:** `Entity` `MAPS_TO` `DataSource.table`, the real Unity Catalog table the number came from.

So the answer to Q2 is not just "6 customers". It is 6 customers because the KYC Policy POL-01 constrains the Customer entity ENT-01, which maps to `supplier_risk.compliance_findings`, filtered to `type = KYC` and `status = open`.

### What else it can combine from the knowledge layer

- **Definition resolution before querying:** the supervisor asks the graph what "material", "high-risk", or "risky" means, reads the `Threshold` off the rule, and only then queries Genie. Meaning is resolved once, not re-guessed per prompt.
- **Impact analysis:** because `Threshold` `APPLIES_TO` `BusinessTerm` `DEFINED_BY` `BusinessRule` `EVALUATES` `Entity` `MAPS_TO` `DataSource`, the agent can answer "if I raise the Late Payment Threshold THR-03, which terms, rules, tables, and prior answers change". That traversal has no clean SQL equivalent.
- **Policy and governance reasoning:** `CONSTRAINS` ties each `Policy` to an `Entity`, so the agent can answer which policies govern customer data or which answers touch a compliance-constrained entity.
- **Queryable glossary:** the knowledge layer is the catalog. List every governed term and its definition, which thresholds parameterize which terms, or who owns a given number.
- **Rule versus model provenance:** `CLASSIFIED_AS` carries `source`, `algorithm`, `score`, and `reason`, so the agent can separate policy-flagged accounts from kNN-similar ones and explain each, including the GDS candidates no rule caught.
- **Multi-hop the fact side finds awkward:** supplier to business unit to customer exposure paths and similarity neighborhoods, the Q4 exposure and Q5/Q6 kNN stories.
- **Consistency check:** both layers derive from one source, so the supervisor can cross-check Genie's Delta counts against the graph's classification counts and flag drift as a self-verification step.

### Sample supervisor questions

Each of these needs both agents. The graph supplies the definition or the provenance; Genie supplies the facts. All counts were verified against the loaded Aura instance.

- **"Which customers have open KYC findings, and why are they flagged?"** The graph resolves the KYC Policy scope and the provenance chain; Genie returns the finding rows. The answer names policy POL-01, the Customer entity ENT-01, and the `compliance_findings` table. Returns the 6 Q2 customers.
- **"What does high-risk supplier mean, and who qualifies?"** The graph reads the definition and the Supplier Risk Threshold off RULE-03; Genie scans `suppliers` against that threshold. Meaning is resolved once, not guessed.
- **"If we lower the Late Payment Threshold to 45 days, which terms, rules, and answers change?"** A pure graph traversal from THR-03 through `APPLIES_TO`, `DEFINED_BY`, and `EVALUATES` to the affected entities and tables. Impact analysis with no clean SQL equivalent.
- **"Which policies govern customer data?"** The graph follows `CONSTRAINS` from each `Policy` to its `Entity`, returning the KYC Policy over the Customer entity.
- **"Who is classified as a Risky Customer, and was it a rule or the model?"** The graph reads `CLASSIFIED_AS` with its `source`, `algorithm`, `score`, and `reason`, separating the rule-flagged accounts from the 4 kNN-similar ones.
- **"Show the full lineage behind CUST-019's Strategic Account label."** The graph walks instance to term to rule to entity to the `supplier_risk.customers` table, the Q6 explanation payoff.
- **"Which business units carry the highest supplier-risk exposure?"** Genie reads `business_unit_exposure`; the graph explains that the score is the mean supplier risk over `SUPPLIES` edges, surfacing BU-03 that the flat rule misses.

### The dependency that keeps it honest

The provenance is only as trustworthy as the maintained edges.

- **Keep write-back running:** the `classifications` and `business_unit_exposure` tables are what stop Genie and the graph from becoming two sources of truth.
- **Change rules in both places:** if a rule changes in code, the `BusinessRule.expression` and `Threshold.value` in the graph must change with it, or the explanation will confidently cite the wrong definition.

## Appendix: mapping to the Databricks integration modes

The demo runs one mode, Multi-Hop Native with write-back, because it is offline and self-contained. In production each question would use whichever mode fits its data gravity and hop count. The table below maps each question to the mode it would use.

| Mode | What it means | Where the data sits | Best-fit questions |
|---|---|---|---|
| **Virtual** | Neo4j queries Databricks directly, leaving the data in place. | Facts stay in Unity Catalog; the knowledge layer lives in Neo4j. | Q1 to Q3. Definition lookups over large, aggregation-friendly fact tables where the graph adds the governed threshold or term but the heavy scan stays in the lakehouse. |
| **Federated** | The knowledge layer is native in Neo4j; instance facts are read from Databricks as needed. | Metadata native in Neo4j; facts federated from Unity Catalog. | Q4 and Q5. Rule-plus-threshold questions that traverse a few hops over the knowledge layer while still resolving facts against the warehouse. |
| **Multi-Hop Native** | Instance data is mirrored into Neo4j; multi-hop and algorithm results are written back to Databricks. | Both layers native in Neo4j; results written back to Delta. | Q6 and the two graph analytics extensions. Deep provenance traversals and graph analytics that are expensive or awkward in SQL, with the classifications written back as gold tables for Genie and BI. |

Per-question summary for the slide:

- Q1, Q2, Q3: **Virtual**. The graph governs the definition; the lakehouse keeps the scan.
- Q4, Q5: **Federated**. Multi-hop over the knowledge layer, facts from the warehouse.
- Q6, GDS exposure, GDS similarity: **Multi-Hop Native**. Deep traversal and algorithms in Neo4j, results written back to Delta.

The demo's write-back tables, `classifications` and `business_unit_exposure`, are the Multi-Hop Native story made concrete: graph-derived value landing back in Unity Catalog where Databricks users and Genie already work.
