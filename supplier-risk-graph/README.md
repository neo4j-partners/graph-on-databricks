# supplier-risk-graph

**Governed, explainable supply-and-credit risk across a Neo4j knowledge graph and a Databricks lakehouse.**

A runnable demo built on a beverage producer's supply-and-credit risk scenario. The Databricks lakehouse holds the facts as Unity Catalog Delta tables: customers, suppliers, invoices, revenue, compliance findings, and the supplier-to-supplier links. The Neo4j knowledge graph mirrors those facts and adds the governed meaning: the business definitions, thresholds, rules, and the multi-hop lineage that ties every risk classification back to the physical table behind it.

The demo contrasts two engines over the same data. A Databricks Genie Agent over the Unity Catalog tables is the lakehouse-only engine. Genie paired with a read-only Neo4j knowledge graph is the second engine. Both answer the everyday risk questions. The payoff is two graph-native questions the lakehouse-only engine cannot answer, because their definitions live only in the graph. One set of CSVs feeds both sides, so it runs offline.

## Overview

In a lakehouse the facts are clean, but the *meaning* is scattered. What counts as a "high-risk" supplier, a "strategic" account, or a "delinquent" customer tends to live in ad hoc SQL, notebooks, and tribal knowledge. Worse, some risk is not a column at all: it is a shape in the connections between suppliers or between customers. No column governs it, and a lakehouse-only engine will not spontaneously write the recursive query that would trace it.

This demo fixes that with a division of labor:

- **Databricks owns the facts.** The lakehouse is the source of truth, holding the raw data as Unity Catalog Delta tables.
- **Neo4j owns the meaning.** The knowledge layer holds the governed definitions, thresholds, policies, and the multi-hop lineage that ties every business term back to the physical table. Neo4j also mirrors the instance data, plus two new edge types no lakehouse column captures, so one query can walk facts and meaning together.

Because both sides load from the same CSVs in `data/`, the two layers always agree.

What the demo shows, through two stories:

- **The hidden glassworks (Story 1).** Cascade Glassworks is a mid-tier supplier whose own risk score never trips a sort, yet the Americas business unit depends on it disproportionately: five clean tier-1 bottle suppliers all trace back to it for raw glass. The graph surfaces it with betweenness centrality over the multi-tier supply chain, the **Critical Supplier** term. Roughly 4.2M EUR per quarter of Americas revenue sits behind it. The lakehouse-only engine cannot find it: there is no "critical" column.
- **The clean payer in a bad family (Story 2).** Jade Beverage Distribution is a spotless platinum customer inside the Kestrel Holdings ownership group, whose sibling companies have defaulted. Asked for late payers, the lakehouse-only engine returns the delinquent accounts and Jade is nowhere on the list. The graph flags Jade with personalized PageRank seeded on the defaulted siblings over the ownership edges, the **Ownership Risk** term. Roughly 800K EUR of live exposure sits behind it.
- **The two graph-native terms have no lakehouse column and no BI-sortable threshold.** That is exactly why the lakehouse-only engine cannot resolve them, and it is the whole payoff. The graph resolves each from its governed definition, then walks the connections live.

For the full walkthrough and the two-engine comparison, see [`DEMO.md`](DEMO.md). For the complete data model, see [`DATA_ARCHITECTURE.md`](DATA_ARCHITECTURE.md).

## The two-layer model

Two layers, tied together by two cross-layer edges:

- **Instance layer:** a mirror of the lakehouse tables, plus two edge types no lakehouse column captures: supplier-to-supplier `SUPPLIES` (the multi-tier supply chain) and customer-to-customer `OWNED_BY` (ownership groups).
- **Knowledge layer:** entities, business terms, business rules, policies, thresholds, and the semantic mapping (lineage) to the real Unity Catalog tables.
- **`REALIZED_AS`:** links a logical entity to its physical instances.
- **`CLASSIFIED_AS`:** records a column-findable classification with provenance. The two graph-native terms are never planted as edges; they are resolved live.

See [`DATA_ARCHITECTURE.md`](DATA_ARCHITECTURE.md) for the data diagrams and the full label, relationship, and property model. Graph properties and the instance tables use camelCase, so the Cypher in the walkthrough runs unchanged against either side. The two graph-derived gold tables, `classifications` and `business_unit_exposure`, are snake_case.

## The dataset

The data is generated from scratch, deterministically, with a fixed seed and a frozen as-of date of 2026-07-01:

- **About 500 customers and 150 suppliers**, with a believable spread of late payers, overdue balances, supplier risk scores, and compliance findings so the two contrasts land against ordinary background risk.
- **Two filler edge layers hide the plants.** A few dozen filler supplier-to-supplier links and a few dozen filler ownership families make the two planted subgraphs look ordinary to the graph algorithms. Size alone is not enough: the filler edge layers are what make Cascade one of many suppliers-of-suppliers and Kestrel one of many owned groups, so only the real metric singles each out.

## How to run

Run these in order from this folder. Steps 1 and 2 need no live service; steps 3 to 5 need `.env` filled in.

1. Generate the data. This writes the 12 node CSVs, the relationship CSVs, the `supply_relationships` link CSV, the `supplier_business_units` lakehouse bridge CSV, and `ground_truth.json` to `data/`. It is deterministic, with a fixed seed and a frozen as-of date of 2026-07-01.

   ```bash
   uv run generate_data.py
   ```

2. Copy the environment sample and fill it in. The Neo4j section drives `load.py` and `gds.py`; the Databricks section drives `upload.py`.

   ```bash
   cp .env.sample .env
   # edit .env: NEO4J_URI, NEO4J_PASSWORD, and the Databricks / Unity Catalog values
   ```

3. Load Neo4j. The loader wipes the target database, creates id uniqueness constraints, then loads nodes and relationships in `UNWIND` batches, including the two new same-graph edges (supplier-to-supplier `SUPPLIES` and customer-to-customer `OWNED_BY`). Point it at a database dedicated to this demo. Use `--check` to validate the CSVs offline without connecting.

   ```bash
   uv run load.py            # wipe and load
   uv run load.py --check    # validate CSVs only, no database
   ```

4. Run the GDS analytics. This runs the two algorithms and writes their results back into Neo4j as node properties only: betweenness centrality over the supplier network (behind Critical Supplier) and personalized PageRank over the ownership network (behind Ownership Risk). Neither score is ever synced to Delta. Run it after the loader.

   ```bash
   uv run gds.py
   ```

5. Upload to Unity Catalog. This uploads the instance CSVs as Delta tables, including the new `supply_relationships` table, and materializes the two graph-derived gold tables, `business_unit_exposure` and `classifications`.

   ```bash
   uv run upload.py
   ```

Quick check that the load worked, before you walk through anything live:

- **Referential integrity:** `uv run load.py --check` reports the node and relationship totals and confirms every relationship endpoint resolves.
- **Story 1:** after `gds.py`, Cascade Glassworks (SUP-901) carries the highest betweenness in the supplier network, and the five tier-1 bottle suppliers score clean.
- **Story 2:** after `gds.py`, Jade Beverage Distribution (CUST-904) is the customer lit up by personalized PageRank, while its own record stays clean.

## Set up the Genie Agent (one-time)

Do this once before the call so the lakehouse-only engine answers over the instance tables and nothing else. The point of the demo is that this engine cannot resolve the two graph-native questions, so the space must not be given the graph's answers.

1. Confirm `upload.py` has published these tables into `graph-on-databricks.supplier_risk`:
   - Core instance tables: `customers`, `suppliers`, `business_units`, `invoices`, `revenue_entries`, `compliance_findings`. Columns are camelCase and share keys where they join: `invoices.customerId` and `compliance_findings.customerId` to `customers.id`, `revenue_entries.businessUnitId` and `customers.businessUnitId` to `business_units.id`.
   - Supplier-to-supplier links: `supply_relationships` (`fromSupplierId`, `toSupplierId`), so the lakehouse-only engine can see the raw links even though no column captures the multi-tier structure they form.
   - Bridge table: `supplier_business_units` (`supplierId`, `businessUnitId`) for the many-to-many supplier-to-unit link.
   - Gold tables: `classifications` and `business_unit_exposure`. These are produced by the pipeline but stay out of the Genie space (see below).
2. Create a Genie space scoped to the `supplier_risk` schema. Add the instance tables the questions read: `customers`, `suppliers`, `business_units`, `invoices`, `compliance_findings`, `revenue_entries`, `supply_relationships`, and the `supplier_business_units` bridge.
3. **Do not add the two gold tables, `classifications` and `business_unit_exposure`, to the space.** They materialize the graph's answers into Delta. Adding them re-introduces write-back leakage: the lakehouse-only engine could read the graph's conclusions straight from a column and tie, which is the exact failure this demo is built to expose. For the same reason, the GDS scores (betweenness, personalized PageRank) are never synced to Delta and live only in the graph.
4. Add sample-question SQL for a couple of the column-findable questions so Genie has curated examples to learn from. The [`DEMO.md`](DEMO.md) walkthrough lists the sample questions and their expected answers, including the two graph-native questions the lakehouse-only engine cannot answer.
5. Publish and smoke-test the space before the call.

For the questions to ask, how the graph engine consumes the governed semantics, and the deeper multi-agent supervisor story, see [`DEMO.md`](DEMO.md).
