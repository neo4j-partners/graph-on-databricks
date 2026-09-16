# Finance Genie Presenter Guide

Use this guide to prepare and deliver the Finance Genie demo. The demo is a
synthetic teaching example. Production evaluation requires representative data.

## Overview

- **Audience:** Fraud, data, analytics, and platform teams.
- **Duration:** 15 minutes plus questions.
- **Purpose:** Show how graph features add relationship-based questions to Databricks Genie.
- **Core message:** Neo4j computes graph features, Databricks stores them in Gold, and Genie queries them as ordinary columns.
- **Decision boundary:** GDS identifies investigation candidates. Analysts or validated models make fraud decisions.

## Demo Story

Lead with one question and two answers. Show the Silver answer first and the
Gold answer second. Explain the architecture after the audience sees the gap.

1. **Set the problem:** Coordinated fraud appears across connected accounts. A single transaction can look ordinary.
2. **Show the Silver answer:** Genie uses available volume and frequency columns to return a broad merchant list.
3. **Show the Gold answer:** Genie uses graph-derived community columns to return a focused merchant list.
4. **Explain the cause:** Neo4j GDS created structural features before Genie ran the Gold query.
5. **Show the pipeline:** Silver data loads into Neo4j, GDS computes features, and Databricks writes them to Gold.
6. **Close with the boundary:** The result is an investigation queue. Analysts make fraud decisions.

Use the [current 15-minute slides](slides/slides-15min.md) for this sequence.
Use the [full deck](slides/slides.md) when the session allows more detail.

## What Each Platform Does

- **Databricks Genie:** Translates business questions into SQL over governed Delta tables.
- **Neo4j GDS:** Computes centrality, community, and similarity from network structure.
- **Enrichment pipeline:** Moves GDS results back into Databricks Gold tables.
- **Analyst:** Reviews the candidates and supporting evidence.

Genie's behavior stays the same after enrichment. The Gold schema gives Genie
new columns that represent network structure.

## Graph Features

- **`risk_score`:** PageRank centrality over the account transfer graph.
- **`community_id`:** Louvain community membership based on transfer density.
- **`similarity_score`:** Jaccard overlap between account merchant neighborhoods.
- **`fraud_risk_tier`:** A demo label derived from ring-candidate community membership.
- **`gold_fraud_ring_communities`:** A community-level table for summary questions.

These features are reproducible for a fixed graph projection. Genie may produce
different valid SQL for the same question, but the stored graph features remain
stable.

## Primary Demo Questions

### Before Graph Enrichment

> Which merchants are most commonly transacted with by the top 10% of accounts
> by total dollar amount spent across merchants?

The result is a broad popularity list with equal investigation priority across
many merchants.

### After Graph Enrichment

> Which merchants show the highest concentration of ring-candidate transactions
> relative to the overall book?

The result shows merchants where ring-candidate activity is much higher than the
book baseline. The analyst receives a focused review target.

Use [genie-questions.md](genie-questions.md) for copy-ready prompts and expected
results.

## Pipeline Explanation

- **Load:** Read Silver tables from Unity Catalog and load accounts, merchants, and relationships into Neo4j.
- **Compute:** Run PageRank, Louvain, and Node Similarity over the graph.
- **Write:** Pull the graph results into Databricks and materialize Gold tables.
- **Query:** Ask Genie to group, filter, and rank the graph-derived columns.
- **Audit:** Keep the source data, graph configuration, Gold values, and generated SQL available for review.

The graph performs structural discovery. Genie performs business analysis over
the resulting segments and scores.

## Delivery Rules

- **Start with value:** Show the before and after answers before the architecture.
- **Use plain terms:** Say central account, connected group, and shared behavior before naming each algorithm.
- **Keep the claim narrow:** Say the graph surfaces candidates for analyst review.
- **Name the synthetic design:** State that the dataset is tuned for a short, repeatable demo.
- **Show evidence:** Use the generated tables, graph paths, and validation results.
- **Control result breadth:** Ask for an explicit top count when a wider sample matters.

## Common Questions

### Why use a 4% fraud rate?

The dataset compresses the signal into 25,000 accounts so the demo runs quickly.
Production teams must recalibrate prevalence, thresholds, and capacity with
representative data.

### Was the dataset designed for GDS?

Yes. The synthetic data creates visible centrality, community, and similarity
patterns. The demo proves the integration pattern and explains the features.
The production scoping guide defines the precision evaluation process.

### Does GDS find fraud?

GDS computes mathematical features. PageRank measures centrality. Louvain finds
communities. Node Similarity measures shared neighborhoods. Analysts and
validated decision systems interpret those features.

### What causes false positives?

Louvain can include nearby background accounts in a dense community. The demo
reports about 70% community purity. Production teams must evaluate this tradeoff
against review capacity and labeled outcomes.

### Why can Genie return a different row count?

Genie can generate different valid SQL shapes. A strict rank can return only
tied top rows. An explicit `LIMIT 100` can return a broader sample. The stored
GDS features remain the same.

## Production Boundary

Review the [production scoping guide](../SCOPING_GUIDE.md) before using this
pattern with customer data. Production work requires representative snapshots,
labeled evaluation cases, threshold calibration, capacity planning, monitoring,
and human review.

## Related Material

- **Short summary:** [Presentation brief](presentation-brief.md).
- **Question script:** [Genie questions](genie-questions.md).
- **Technical detail:** [Pipeline architecture](../architecture.md).
- **KYC extension:** [Shared-identity guide](../kyc-guide.md).
- **Archived planning:** [Earlier demo flow notes](archive/demo-flow-notes.md).
