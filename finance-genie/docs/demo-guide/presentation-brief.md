# Presentation Brief

## Overview

- **Title:** Financial Crime Hides Between the Rows.
- **Audience:** Data, fraud, and investigation teams using Databricks.
- **Purpose:** Show how graph features add relationship-based questions to Genie.
- **Core message:** Neo4j computes graph features, Databricks stores them as Gold columns, and Genie queries them with ordinary SQL.

## Abstract

Fraud rings hide across connected transactions. Each transaction can look
ordinary while the full network shows coordinated behavior. Finance Genie loads
Lakehouse data into Neo4j, calculates centrality, community, and similarity
features, and writes the results back to Delta tables.

The analyst keeps the same Genie workflow. The available questions improve
because Gold now includes graph-derived columns. The live demo compares a broad
merchant popularity result with a focused list of merchants used by accounts in
ring-candidate communities.

## Short Talk Track

- **Business shape:** Accounts connect through transfers, merchants, phones, and addresses.
- **Graph value:** Centrality finds important accounts, community detection finds groups, and similarity finds shared behavior.
- **Lakehouse value:** Unity Catalog governs the inputs and Gold outputs.
- **Analyst value:** Genie groups, filters, and ranks graph features like any other dimension.
- **Decision boundary:** Graph features identify investigation candidates. Analysts decide which cases need review.

Use the [presenter preparation guide](prep-guide.md) for the full narrative and
the [slides](slides/slides.md) for the current speaker notes.
