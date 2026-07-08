# Data Architecture

The demo uses a dual data architecture. The Databricks lakehouse owns the data / instance layer as Unity Catalog Delta tables. Neo4j owns the knowledge / semantic layer and holds a mirror of the instance data so multi-hop and provenance queries run in one graph. One set of CSVs in `data/` is the single source for both sides.

![Dual data architecture](dual-data-architecture.svg)

## Lakehouse Tables (Unity Catalog Delta)

| Table | Kind | Columns (key) | Notes |
|---|---|---|---|
| `invoices` | Fact | `id, customer_id, amount, currency, issue_date, due_date, paid_date, days_late, status` | Basis for payment-behavior rules; drives Q5 and the Q6 payment condition |
| `payments` | Fact | `id, invoice_id, amount, date` | Settles one or more invoices |
| `revenue_entries` | Fact | `id, business_unit_id, period, amount, currency, reconciled` | `reconciled = false` drives Q1 |
| `customers` | Dimension | `id, name, segment, business_unit_id, churn_risk, upsell_score, profitability_trend` | The last three columns are derived ML features consumed by the graph |
| `suppliers` | Dimension | `id, name, category, risk_score` | Procurement counterpart; drives Q4 |
| `business_units` | Dimension | `id, name, region` | Rolls up customers, suppliers, and revenue |
| `compliance_findings` | Operational log | `id, customer_id, type, status, opened_date` | `type = 'KYC'` and `status = 'open'` drive Q2; open findings feed Q6 |
| `classifications` | Write-back | `entity_id, entity_type, term, source, algorithm, score, reason, evaluated_at, rule_version` | `CLASSIFIED_AS` results written back from Neo4j, the Multi-Hop Native story. `source` is `rule` for the pre-planted edges or `gds` for the algorithm-derived ones; `algorithm`, `score` are populated only for `gds` rows and `rule_version` only for `rule` rows |

## Neo4j Nodes

### Data / instance layer (mirror of the lakehouse)

| Label | Key properties | Notes |
|---|---|---|
| `Customer` | `id, name, segment, profitabilityTrend, churnRisk, upsellScore` | Trend and score fields come from the warehouse ML features |
| `Supplier` | `id, name, category, riskScore` | Procurement counterpart |
| `BusinessUnit` | `id, name, region` | Rolls up customers, suppliers, revenue |
| `Invoice` | `id, amount, currency, issueDate, dueDate, paidDate, daysLate, status` | Basis for payment-behavior rules |
| `Payment` | `id, amount, date` | Settles one or more invoices |
| `RevenueEntry` | `period, amount, currency, reconciled` | `reconciled = false` drives Q1 |
| `ComplianceFinding` | `id, type, status, openedDate` | `status = 'open'` drives Q2 and Q6 |

### Knowledge / semantic layer (graph only)

| Label | Key properties | Notes |
|---|---|---|
| `EDMEntity` | `name, description` | Logical entities from the Enterprise Data Model |
| `BusinessTerm` | `name, definition` | Human-readable definition, for example "Platinum Customer" |
| `BusinessRule` | `name, expression, description` | Machine-evaluable logic behind a term |
| `Policy` | `name, type` | For example KYC Policy, Procurement Policy |
| `Threshold` | `name, value, currency` | For example Materiality Threshold |
| `DataSource` | `name, system, table` | Lineage target; `table` holds the real Unity Catalog table name |

## Relationships

### Instance layer

| Relationship | Pattern | Notes |
|---|---|---|
| `HAS_INVOICE` | `(:Customer)-[:HAS_INVOICE]->(:Invoice)` | Payment behavior per customer |
| `SETTLED_BY` | `(:Invoice)-[:SETTLED_BY]->(:Payment)` | Invoice settlement |
| `BELONGS_TO` | `(:Customer)-[:BELONGS_TO]->(:BusinessUnit)` | Customer roll-up |
| `RECOGNIZES` | `(:BusinessUnit)-[:RECOGNIZES]->(:RevenueEntry)` | Revenue recognition per unit |
| `SUPPLIES` | `(:Supplier)-[:SUPPLIES]->(:BusinessUnit)` | Supply relationships |
| `HAS_FINDING` | `(:Customer)-[:HAS_FINDING]->(:ComplianceFinding)` | Compliance exposure |

### Knowledge layer

| Relationship | Pattern | Notes |
|---|---|---|
| `DEFINED_BY` | `(:BusinessTerm)-[:DEFINED_BY]->(:BusinessRule)` | A term is backed by an explicit rule |
| `EVALUATES` | `(:BusinessRule)-[:EVALUATES]->(:EDMEntity)` | The rule operates over EDM entities |
| `CONSTRAINS` | `(:Policy)-[:CONSTRAINS]->(:EDMEntity)` | Policy scope |
| `APPLIES_TO` | `(:Threshold)-[:APPLIES_TO]->(:BusinessTerm)` | Threshold that parameterizes a term |
| `MAPS_TO` | `(:EDMEntity)-[:MAPS_TO]->(:DataSource)` | Lineage from logical entity to physical source; `DataSource.table` points at the real UC table |

### Cross-layer

| Relationship | Pattern | Notes |
|---|---|---|
| `REALIZED_AS` | `(:EDMEntity)-[:REALIZED_AS]->(:Customer\|:Invoice)` | Logical entity to its physical instances. The demo realizes only the Customer and Invoice entities, the ones the six questions traverse: 100 Customer edges and 612 Invoice edges. |
| `CLASSIFIED_AS` | `(:Customer\|:Supplier)-[:CLASSIFIED_AS {reason, evaluatedAt, ruleVersion}]->(:BusinessTerm)` | Materialized classification with provenance; written back to the `classifications` Delta table |

The `CLASSIFIED_AS` edge is the explainability payoff: every answer can be traced instance to business term to rule to EDM entity to data source, so Q6 can report which business definitions and data sources were used.

## CSV Mapping

Each node label and each relationship type loads from one CSV in `data/`. The same node CSVs are uploaded to Unity Catalog as the tables above.

- Node CSVs: `customers.csv`, `suppliers.csv`, `business_units.csv`, `invoices.csv`, `payments.csv`, `revenue_entries.csv`, `compliance_findings.csv`, `edm_entities.csv`, `business_terms.csv`, `business_rules.csv`, `policies.csv`, `thresholds.csv`, `data_sources.csv`
- Relationship CSVs: `has_invoice.csv`, `settled_by.csv`, `belongs_to.csv`, `recognizes.csv`, `supplies.csv`, `has_finding.csv`, `defined_by.csv`, `evaluates.csv`, `constrains.csv`, `applies_to.csv`, `maps_to.csv`, `realized_as.csv`, `classified_as.csv`

`classified_as.csv` carries the provenance columns `reason`, `evaluatedAt`, and `ruleVersion`.

## Graph Analytics Extensions

The demo uses two graph analytics passes to extend the rule-based answers: a plain Cypher exposure aggregation for Q4 and one Graph Data Science algorithm, kNN, for Q5/Q6. Both write their results back as `CLASSIFIED_AS` edges, so they join the same provenance story and flow into the `classifications` Delta table.

### Supplier risk exposure (extends Q4)

- **ELI5:** think of each supplier as carrying a risk score. A business unit's exposure is the average risk of all the suppliers feeding it. A unit served by several middling-risk suppliers can carry high average exposure even when no single supplier looks alarming on its own.
- **Method:** the mean supplier `riskScore` per business unit. This is a one-hop aggregation, computed with a single Cypher `avg()` over the supply edges.
- **Edges aggregated:** `Supplier-SUPPLIES->BusinessUnit`.
- **What it does:** averages supplier risk per business unit to score its exposure.
- **Why it matters:** the rule filter `riskScore >= 70` only finds individually risky suppliers. The aggregation finds a business unit whose average exposure is high because several mid-risk suppliers serve it, even though no single supplier crosses the threshold.
- **Demo line:** the rule finds risky suppliers; the graph finds risky exposure.

### Customer similarity (extends Q5 and Q6)

- **ELI5:** describe every customer as a point on a map, where the coordinates are how late they pay, how much of their book is overdue, and how their profitability is trending. Customers who behave alike land close together. If a customer's point sits in the same neighborhood as the known troublemakers, they probably belong to that crowd, even if they have not broken a rule yet.
- **Algorithm:** GDS k-Nearest Neighbors over payment-behavior features. It builds a similarity graph, linking each customer to its most similar peers by feature distance, then ranks the non-flagged customers by their highest similarity to any member of the known risky cohort. The four nearest are the candidates; they emerge from the run, not a planted set.
- **Features:** `avgDaysLate`, `overdueShare`, `churnRisk`, and `profitabilityTrend`, with the categorical fields encoded numerically. `upsellScore` is deliberately excluded because it is random relative to risk and would make results nondeterministic.
- **What it does:** surfaces the non-flagged customers whose feature vectors sit closest to the known risky accounts in the kNN similarity graph.
- **Why it matters:** the last-3-invoices rule only catches customers who already trip it. Similarity surfaces the ones trending toward the risky cohort before the rule fires.
- **Demo line:** rule-based classification finds the ones already defined; GDS finds the next ones.

### Write-back with provenance

- Both passes write new `CLASSIFIED_AS` edges carrying `source: 'gds'`, the algorithm name, the score, and `evaluatedAt`.
- The edges have the same shape as the rule-planted ones, so the Q6 explanation query returns them without modification.
- Results are deterministic given the fixed-seed data. Q4 exposure matches the `gds_q4_*` entries in `ground_truth.json`; the Q5/Q6 kNN candidates emerge from the run and are checked only for shape (four non-flagged customers, each near the risky cohort).
