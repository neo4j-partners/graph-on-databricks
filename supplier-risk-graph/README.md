# supplier-risk-graph

A runnable demo of Neo4j and Databricks working together on supplier and customer risk. It is built for two people: the sales engineer who has to stand it up and present it, and the customer evaluating whether a knowledge graph earns its place next to the lakehouse.

## Why this demo exists

In a lakehouse the facts are clean, but the *meaning* is scattered. What counts as "material" unreconciled revenue, a "high-risk" supplier, a "risky" customer, or a "strategic" account tends to live in ad hoc SQL, notebooks, and tribal knowledge. Different queries encode slightly different definitions, thresholds drift, and when someone asks "why was this flagged?" there is no clean answer to give.

This demo fixes that with a division of labor:

- **Databricks owns the facts.** The lakehouse holds the data as Unity Catalog Delta tables: customers, suppliers, invoices, revenue, compliance findings.
- **Neo4j owns the meaning.** The knowledge layer holds the governed definitions, thresholds, policies, and the multi-hop lineage that ties every business term back to the physical table behind it.

One set of CSVs in `data/` feeds both sides, so the demo runs offline and the two layers always agree.

What a sales engineer can say out loud while running it:

- **Definitions are governed once.** A threshold like the materiality cutoff is a node in the graph that finance owns, not a number buried in a query, so every answer stays consistent no matter who asks.
- **Every answer is explainable.** A classification traces from the instance record to the business term to the rule to the entity to the real Unity Catalog table. That provenance chain is what a text or RDF glossary cannot query.
- **The graph finds what flat rules miss.** Two analytics passes surface risk the rules never see: a supplier-risk *exposure* aggregation that flags a business unit no single supplier trips, and a kNN customer *similarity* pass that finds the next risky accounts before they break a rule.
- **The value lands back in Delta.** Both rule-based and algorithm-derived classifications are written back to Unity Catalog as gold tables, so Databricks and Genie users get the graph's meaning in their own tables. It is the same Genie, now accurate, consistent, explainable, and cheaper, because the meaning is resolved once in the graph instead of re-guessed on every prompt.

For the full walkthrough, the six validation questions and the Genie flow, see [`DEMO.md`](DEMO.md). For the complete data model, see [`DATA_ARCHITECTURE.md`](DATA_ARCHITECTURE.md).

## The two-layer model

Two layers, tied together by two cross-layer edges:

- **Instance layer:** a mirror of the lakehouse tables.
- **Knowledge layer:** entities, business terms, business rules, policies, thresholds, and the semantic mapping (lineage) to the real Unity Catalog tables.
- **`REALIZED_AS`:** links a logical entity to its physical instances.
- **`CLASSIFIED_AS`:** records a classification with provenance.

See [`DATA_ARCHITECTURE.md`](DATA_ARCHITECTURE.md) for the data diagram and the full label, relationship, and property model. Graph properties and the instance tables use camelCase, so the Cypher in the walkthrough runs unchanged against either side. The two graph-derived gold tables, `classifications` and `business_unit_exposure`, are snake_case.

## How to run

Run these in order from this folder. Steps 1 and 2 need no live service; steps 3 to 5 need `.env` filled in.

1. Generate the data. This writes the 13 node CSVs, 13 relationship CSVs, the `supplier_business_units` lakehouse bridge CSV, and `ground_truth.json` to `data/`. It is deterministic, with a fixed seed and a frozen as-of date of 2026-07-01.

   ```bash
   uv run generate_data.py
   ```

2. Copy the environment sample and fill it in. The Neo4j section drives `load.py` and `gds.py`; the Databricks section drives `upload.py`.

   ```bash
   cp .env.sample .env
   # edit .env: NEO4J_URI, NEO4J_PASSWORD, and the Databricks / Unity Catalog values
   ```

3. Load Neo4j. The loader wipes the target database, creates id uniqueness constraints, then loads nodes and relationships in `UNWIND` batches. Point it at a database dedicated to this demo. Use `--check` to validate the CSVs offline without connecting.

   ```bash
   uv run load.py            # wipe and load
   uv run load.py --check    # validate CSVs only, no database
   ```

4. Run the GDS analytics. This runs the two algorithms and writes their results back into Neo4j: a `supplierExposureScore` on each `BusinessUnit` and `CLASSIFIED_AS {source: 'gds'}` edges to the Risky Customer term. Run it after the loader.

   ```bash
   uv run gds.py
   ```

5. Upload to Unity Catalog. This uploads the instance CSVs as Delta tables and materializes the two graph-derived gold tables, `business_unit_exposure` and `classifications`.

   ```bash
   uv run upload.py
   ```

Quick check that the load worked, before you walk through anything live. Open Neo4j Browser on the demo database with the results pane set to Table view, then confirm:

- **Counts:** `uv run load.py --check` reports 1433 nodes and 2221 relationships.
- **Q1:** 2 business units.
- **Q2:** 6 customers.
- **Q6:** 3 customers.

If those three match, everything upstream loaded correctly.

## Set up the Genie space (one-time)

Do this once before the call so Genie answers over the governed tables the graph wrote back.

1. Confirm `upload.py` has published these tables into `graph-on-databricks.supplier_risk`:
   - Instance tables: `customers`, `suppliers`, `business_units`, `invoices`, `payments`, `revenue_entries`, `compliance_findings`. These carry camelCase foreign keys, so the lakehouse side joins like a star schema: `invoices.customerId` and `compliance_findings.customerId` to `customers.id`, `payments.invoiceId` to `invoices.id`, and `revenue_entries.businessUnitId` and `customers.businessUnitId` to `business_units.id`.
   - Bridge table: `supplier_business_units` (`supplierId`, `businessUnitId`) for the many-to-many supplier-to-unit link.
   - Graph-derived gold tables: `classifications` (every `CLASSIFIED_AS` edge, rule- and GDS-sourced) and `business_unit_exposure` (the Q4 propagation result).
2. Create a Genie space scoped to the `supplier_risk` schema. Add all ten tables above.
3. Add general instructions to the space so Genie prefers the governed tables:
   - "`classifications` holds governed labels written back from the knowledge graph. Use it, not ad hoc heuristics, to decide who is a Risky Customer, High-Risk Supplier, Strategic Account, or Platinum Customer. Join `classifications.entity_id` to `customers.id` or `suppliers.id`."
   - "The `source` column in `classifications` is `rule` for policy-based labels and `gds` for algorithm-derived ones. `reason` explains each label."
   - "`business_unit_exposure` holds supplier-risk exposure per business unit. Use `supplier_exposure_score` for aggregate exposure, not just individual `suppliers.riskScore`."
4. Add sample-question SQL for a couple of the questions so Genie has curated examples to learn from. The [`DEMO.md`](DEMO.md) walkthrough lists the sample Genie questions and their expected answers.
5. Publish and smoke-test the space with the first question before the call.

For the questions to ask, how Genie consumes the graph semantics, and the deeper multi-agent supervisor story, see [`DEMO.md`](DEMO.md).
