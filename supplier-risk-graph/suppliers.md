# supplier-risk-graph: Demo Proposal

## TLDR

- Build a small demo that implements the customer use-case data model from the customer requirements doc.
- Dual data architecture: the lakehouse holds the instance data, Neo4j holds the knowledge layer plus a mirror of the instance nodes.
  - Data layer: Customer, Supplier, BusinessUnit, Invoice, Payment, RevenueEntry, ComplianceFinding.
  - Knowledge layer: EDMEntity, BusinessTerm, BusinessRule, Policy, Threshold, DataSource.
- Goal: answer all 6 of the customer's validation questions through the graph and explain which definitions and data sources were used. Genie stays prominent as the consumer of graph semantics, not as a standalone answer path.
- GDS on top of the rules: supplier risk propagation extends Q4, customer similarity extends Q5/Q6, and both write results back as classifications.
- Style: same simple setup as `finance-genie`. CSV files, uv, `.env`, plain Python.

## Status

- [x] Phase 1: CSV data generator — done 2026-07-07. `generate_data.py` (stdlib only, `uv run generate_data.py`) writes 13 node CSVs, 13 relationship CSVs, and `ground_truth.json` to `data/`. Ground truth is recomputed from the generated rows, not copied from the plant lists, and built-in assertions fail the run if the two drift. Regeneration is byte-identical (fixed seed, as-of date 2026-07-01). Planted answer counts: Q1 = 2 business units, Q2 = 6 KYC violators, Q3 = 15 platinum customers, Q4 = 5 high-risk suppliers, Q5 = 5 risky customers, Q6 = 3 strategic accounts at risk (one deliberately overlapping Q5 and Q2).
- [x] Phase 1 rev: generator additions for GDS — done 2026-07-07. Suppliers now carry three exclusive risk bands (high 70+, mid 60-69, low 5-54); the 4 mid-band suppliers are the only ones supplying BU-03, giving it the top average supplier risk (64.2 vs 42.0 runner-up) with no single score over the threshold. Customers gain `avgDaysLate` and `overdueShare` columns derived from their invoices. Four similar-cohort customers are planted with high churn, declining profitability, and last-three lateness of 40 to 59 days, so they sit near the risky cohort in feature space without tripping the rule, a believable near-risky population for the kNN pass to find. `ground_truth.json` gains `gds_q4_*` entries; the Q5/Q6 candidates emerge from the kNN run, so they are not recorded there. New assertions fail the run if the Q4 plant drifts. Regeneration remains byte-identical.
- [x] Phase 2: Neo4j loader — done 2026-07-07. `load.py` (`uv run load.py`, neo4j driver + python-dotenv, `.env` per `.env.sample`) wipes the target database in batched transactions, creates 13 id uniqueness constraints, then loads nodes and relationships with `UNWIND` batches. Dates/datetimes/numbers/booleans are typed, empty CSV fields become absent properties, and `realized_as.csv` splits per `instance_label` (Customer, Invoice). Referential integrity is checked before touching the database and created counts are verified against CSV row counts. `uv run load.py --check` validates the CSVs offline: 1433 nodes, 2219 relationships, all endpoints resolve.
- [x] Phase 3: README with sample queries — done 2026-07-07. `README.md` covers the two-layer model (Mermaid diagram plus the existing `dual-data-architecture.svg`), the run order (generate, load, gds, upload), all six Cypher queries ready to paste (Q2's `REALIZED_AS` flipped to the entity-to-instance direction the model uses, with a note; Q1/Q4/Q5 read their thresholds from the graph), the Q6 term-to-rule-to-EDM-to-DataSource explanation query, the Genie-as-consumer framing, both GDS extension queries (BU exposure property, `source:'gds'` similarity edges), and an expected-results table mirroring `ground_truth.json`.
- [x] Phase 4: Lakehouse tables — done 2026-07-07. `upload.py` (`uv run upload.py`, databricks-sdk + neo4j driver, `.env` per `.env.sample`) uploads the 7 instance node CSVs into a UC volume and builds one Delta table each with `read_files` (headers verbatim/camelCase, `schemaHints` from load.py's type maps), then reads the two graph-derived tables back out of Neo4j: `classifications` (every `CLASSIFIED_AS` edge, rule- and GDS-sourced, 9 cols) and `business_unit_exposure` (the Q4 propagation result, matching `gds_q4_supplier_exposure_by_business_unit`). Idempotent: `CREATE SCHEMA/VOLUME IF NOT EXISTS`, `CREATE OR REPLACE TABLE`. `uv run upload.py --check` validates the base CSVs offline (1403 rows). Target is `graph-on-databricks.supplier_risk`, matching `data_sources.csv`. Offline-validated; not yet run against a live workspace.
- [x] Phase 5: GDS analytics — done 2026-07-07. `gds.py` (`uv run gds.py`, graphdatascience client, `.env`) runs both analytics passes and writes results back to Neo4j. Q4 supplier-risk exposure aggregates the `SUPPLIES` network with a single Cypher `avg()` and computes each BusinessUnit's exposure as the mean supplying-supplier `riskScore`, writing `supplierExposureScore` on every BusinessUnit; BU-03 tops at 64.2 from four mid-band suppliers the flat 70 filter misses. Q5/Q6 similarity runs GDS kNN over the encoded payment-behavior features (`avgDaysLate`, `overdueShare`, `churnRisk`, `profitabilityTrend`; `upsellScore` excluded) to build the similarity graph, then classifies the four non-flagged customers most similar to the known risky cohort as Risky Customer (TERM-04) via `CLASSIFIED_AS {source:'gds', algorithm:'knn', score, evaluatedAt, reason}` edges (idempotent MERGE, prior gds edges cleared); the candidates emerge from the run, not a planted set. Q4 exposure is asserted against `ground_truth.json` at runtime; Q5/Q6 is checked only for shape (four non-flagged candidates, each near the risky cohort). Q4 offline reproduction against the CSVs matched exactly (BU-03 64.2); the kNN pass has not yet been run against a live Aura + GDS instance.

## Dual Data Architecture

- Lakehouse side, Unity Catalog Delta tables. This is the data/instance layer, the part the customer said resides in a cloud warehouse:
  - Fact tables: `invoices`, `payments`, `revenue_entries`. High volume, append-only, aggregation-friendly, the SQL and Genie sweet spot.
  - Dimension tables: `customers`, `suppliers`, `business_units`.
  - `compliance_findings` as an operational log.
  - Derived ML features on customers: `churn_risk`, `upsell_score`, `profitability_trend`. Shows Databricks doing feature engineering with the graph consuming the output.
- Graph side, Neo4j. This is the knowledge/semantic layer plus the relationship-heavy connections:
  - `EDMEntity`, `BusinessTerm`, `BusinessRule`, `Policy`, `Threshold`, `DataSource` nodes.
  - `MAPS_TO` lineage edges point at the real UC table names, so lineage references real Databricks assets.
  - `CLASSIFIED_AS` provenance edges, the explainability payoff, written back to a Delta table to complete the Multi-Hop Native story.
- Instance nodes are mirrored into Neo4j:
  - The same CSVs load into both UC and Neo4j, so the demo runs offline and both sides always match.
  - Virtual access from Neo4j to Databricks is presented as an architecture option on the slide, not built in this demo.
- Demo narrative:
  - All six questions run through the graph. Every question resolves its definition in the knowledge layer (Q1 the Materiality Threshold node, Q2 the KYC Policy constraint, Q3 the Platinum Customer term, Q4 to Q6 the rule and provenance traversals) and pulls its facts from the instance data.
  - Genie stays prominent as the consumer of graph semantics: the graph supplies the definitions that make Genie answers accurate, cheaper, and explainable. Genie is never positioned as a standalone answer path, which would concede the questions to the lakehouse alone.
  - The questions escalate in graph value: Q1 to Q3 are definition lookups grounded in the knowledge layer, Q4 to Q6 add multi-hop provenance, and the GDS extensions (Phase 5) add risk propagation and similarity, finding what rule filters cannot.
  - Classification results, rule-based and GDS-scored, flow back into Delta so Databricks users see graph value in their own tables.

## Phase 1: CSV Data Generator

- One small Python script that writes CSV files to a `data/` folder.
- Same pattern as `finance-genie/data`: one CSV per node type, one CSV per relationship type.
- The same CSVs are the single source for both sides: uploaded to UC in Phase 4 and loaded into Neo4j in Phase 2.
- Node CSVs:
  - `customers.csv`, `suppliers.csv`, `business_units.csv`, `invoices.csv`, `payments.csv`, `revenue_entries.csv`, `compliance_findings.csv`
  - `edm_entities.csv`, `business_terms.csv`, `business_rules.csv`, `policies.csv`, `thresholds.csv`, `data_sources.csv`
  - `business_rules.csv` carries a numeric `threshold` column so Q4's `WHERE s.riskScore >= rule.threshold` runs verbatim. `thresholds.csv` still holds the Materiality Threshold node that Q1 reads.
- Relationship CSVs:
  - `has_invoice.csv`, `settled_by.csv`, `belongs_to.csv`, `recognizes.csv`, `supplies.csv`, `has_finding.csv`
  - `classified_as.csv` with `reason`, `evaluatedAt`, `ruleVersion` columns for provenance. Pre-plant only `Platinum Customer` and `Strategic Account` edges (Q3 and Q6 need them to exist up front). `High-Risk Supplier` and `Risky Customer` are deliberately absent: they get computed live during the demo and written back, which is the Multi-Hop Native moment.
  - `defined_by.csv`, `evaluates.csv`, `constrains.csv`, `applies_to.csv`, `maps_to.csv`, `realized_as.csv`
  - `realized_as.csv` uses the entity-to-instance direction, `(:EDMEntity)-[:REALIZED_AS]->(instance)`, with one row per Customer and per Invoice only (payments and revenue entries are skipped to keep the graph readable). The Q2 query in the requirements doc traverses the opposite direction and gets corrected in the README.
- Plant known answers so every one of the 6 questions returns results:
  - A few business units with unreconciled revenue above the threshold.
  - A few customers with open KYC findings.
  - Platinum customers with high upsell scores.
  - Suppliers with risk scores above the procurement rule threshold.
  - Customers more than 60 days late on their last 3 invoices.
  - At least 2 strategic accounts that hit all four risk conditions.
- Write the planted answers to `ground_truth.json`, same as finance-genie.
  - Planted cohorts may overlap (the Q6 strategic accounts will also show up in Q5 and Q2 results); `ground_truth.json` records each question's answer set independently.
- Keep it small: about 100 customers, 30 suppliers, 5 business units, a few hundred invoices.

### Generator defaults

Simplifying choices baked into the generator so the data stays deterministic and the requirements-doc Cypher runs as written:

- Frozen as-of date (`2026-07-01`). All dates are generated relative to it and `daysLate` is computed once at generation time and stored on the invoice, so `ground_truth.json` never goes stale.
- Fixed random seed, so regenerating produces identical CSVs and ground truth.
- Single currency: EUR everywhere. No FX logic in any threshold comparison.
- Payments settle invoices 1:1. No partial payments, no credit notes.
- Invoice `status` vocabulary: `paid | open | overdue`. Q6 matches `status:'overdue'` literally.
- Small fixed enums: `segment` platinum/gold/silver, `churnRisk` low/medium/high, `profitabilityTrend` improving/stable/declining, finding `type` KYC/AML/sanctions, finding `status` open/closed.
- `riskScore` on a 0 to 100 integer scale; the procurement rule threshold is 70.
- Human-readable ids (`CUST-001`, `SUP-001`, `INV-0001`) so results read well on screen during the demo.
- CSV headers use the camelCase property names from the requirements Cypher (`upsellScore`, `daysLate`, `profitabilityTrend`) and are used unchanged in both Neo4j and UC, so the doc's queries match without renaming.
- About 12 months of invoice history with 4 to 8 invoices per customer, so the last-3-invoices window in Q5 always exists.
- Fixed `evaluatedAt` timestamp and `ruleVersion` (`v1.0`) on all pre-planted `CLASSIFIED_AS` edges.

### Phase 1 rev: generator additions for GDS

Phase 1 shipped star-shaped data (each supplier supplies 1 to 3 business units, customers hang off invoices), which is fine for traversals but too thin for algorithms. A generator rev adds the connective tissue and planted cohorts the Phase 5 GDS angles need:

- Denser `SUPPLIES` edges: each supplier supplies 2 to 4 business units instead of one, so risk propagation has real paths to flow through. The propagation path `Supplier-SUPPLIES->BusinessUnit<-BELONGS_TO-Customer` already exists in the model; density is what makes it interesting.
- A planted exposure cohort for Q4 propagation: one business unit served by several mid-risk suppliers (scores in the 60 to 69 range), so its aggregate exposure is high even though no single supplier crosses the rule threshold of 70. This is the "propagation finds what the flat filter misses" moment.
- Feature variance for similarity: per-customer payment-behavior features (average `daysLate`, share of overdue invoices) generated with enough spread that kNN separates cohorts instead of collapsing them.
- A planted similarity cohort for Q5/Q6: a few customers who do not trip the last-3-invoices rule but whose feature vectors sit close to the known risky cohort. These are the "next ones" GDS finds before the rule does.
- `ground_truth.json` gains entries for both GDS cohorts (expected exposed business unit, expected similarity candidates) so the validation script can check the algorithm outputs too. Fixed seed keeps them reproducible.

## Phase 2: Neo4j Loader

- Small uv project with `pyproject.toml`, `.env`, and `.env.sample`.
- `.env` holds `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE`.
- One `load.py` script using the neo4j Python driver:
  - Create uniqueness constraints on all node ids first.
  - Load node CSVs, then relationship CSVs.
  - Mirrors the instance nodes into Neo4j alongside the knowledge layer, same CSVs as the lakehouse.
  - Batch with `UNWIND`, nothing fancy.
- Run with `uv run load.py`. Re-runnable: wipe and reload, or use `MERGE`.

## Phase 3: README with Sample Queries

- Short README covering:
  - What the demo is and the two-layer model, with the mermaid diagram from the requirements doc.
  - How to run: generate CSVs, set `.env`, load, query.
  - The 6 Cypher queries from the requirements doc, ready to paste. Corrected where the doc is internally inconsistent: Q2's `REALIZED_AS` pattern is flipped to the entity-to-instance direction the model actually uses.
  - For each query, one line on what it shows and which definitions and sources back the answer.
  - How each question resolves its definition from the knowledge layer, and how Genie consumes the graph semantics rather than answering on the lakehouse alone.
  - The two graph analytics extensions from Phase 5, with the queries that read their write-back classifications.
  - Expected results from `ground_truth.json` so anyone can verify the load worked.

## Phase 4: Lakehouse Tables

- Upload the same CSVs to Unity Catalog as Delta tables, reusing the `finance-genie` upload pattern.
- Set each `DataSource` node's `table` property to the real UC table name so lineage in the graph points at real assets.
- Write the `CLASSIFIED_AS` results back to a `classifications` Delta table for the Multi-Hop Native write-back story.

## Phase 5: GDS Analytics

Two algorithm angles that extend the rule-based answers. Both write results back as `CLASSIFIED_AS` edges so they join the same provenance story and flow into the `classifications` Delta table with the rest.

- Q4 extension, supplier risk exposure:
  - Aggregate supplier `riskScore` over the `Supplier-SUPPLIES->BusinessUnit` edges as a mean. A one-hop aggregation, so a single Cypher `avg()` computes it exactly, no GDS algorithm required.
  - Surfaces the planted exposure cohort: a business unit and its customers exposed through several mid-risk suppliers that the flat `riskScore >= 70` filter misses.
  - Demo line: the rule finds risky suppliers; the graph finds risky exposure.
- Q5/Q6 extension, customer similarity:
  - GDS kNN over payment-behavior features (`avgDaysLate`, `overdueShare`, `churnRisk`, `profitabilityTrend`, with the categorical fields encoded numerically). `upsellScore` is deliberately excluded: it is random relative to risk, and the noise would make the results nondeterministic.
  - Surfaces the non-flagged customers most similar to the known risky cohort in the kNN graph, before they trip the rule; the candidates emerge from the run, not a planted set.
  - Demo line: rule-based classification finds the ones already defined; GDS finds the next ones.
- Write-back with provenance: new `CLASSIFIED_AS` edges carry `source: 'gds'`, the algorithm name, the score, and `evaluatedAt`, the same shape as the rule-planted edges, so the Q6 explanation query returns them without modification.
- Implementation: one `gds.py` script in the same uv project using the GDS Python client, run with `uv run gds.py` after the loader. Deterministic given the fixed-seed data. Q4 results match `ground_truth.json`; the Q5/Q6 kNN candidates emerge from the run and are checked for shape.

## What Else Is Needed (open questions)

- A validation script that runs the 6 queries plus the two graph analytics extensions and checks results against `ground_truth.json`.
- Genie integration: a Genie space over the UC tables, since the customer wants Genie everywhere. Could be Phase 6.
- A few text documents such as policy PDFs to show the unstructured plus structured story. Optional.
- The demo lives in the top-level `supplier-risk-graph/` folder in this repo.
- Reconcile property names and thresholds against the customer's actual EDM before showing externally, as flagged in the requirements doc.
