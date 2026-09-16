# Production Scoping Guide

Finance Genie is a deterministic teaching dataset and integration reference. Its
default thresholds demonstrate the difference between row-level analysis and
graph-derived structural features. They are not production fraud thresholds.

## What must be recalibrated

Production adoption requires calibration against the target institution's data:

- **Population and edge volume:** account counts, transfer counts, merchant
  counts, retention windows, and graph density determine projection size and
  runtime.
- **Signal prevalence:** expected fraud prevalence and the available labeled
  cases determine useful precision, recall, and alert-volume targets.
- **Algorithm parameters:** PageRank, Louvain, and Node Similarity parameters
  must be evaluated on representative graph snapshots rather than copied from
  the synthetic dataset.
- **Decision thresholds:** community-size, risk-score, and similarity cutoffs
  should be selected from validation curves and an explicit review-capacity
  budget.
- **Operational constraints:** Aura capacity, Databricks compute, SQL warehouse
  concurrency, refresh cadence, and acceptable end-to-end latency must be sized
  together.

## Evaluation sequence

1. Build a time-bounded, representative graph snapshot and a labeled evaluation
   set with known positive and negative cases.
2. Run the GDS algorithms without changing downstream decision thresholds.
3. Measure ranking quality, community coverage and purity, pairwise similarity
   quality, and alert volume.
4. Select thresholds against the required precision, recall, investigation
   capacity, and cost envelope.
5. Validate on a later holdout period to detect leakage and temporal drift.
6. Establish monitoring for feature distributions, graph size, runtime, and
   analyst outcomes before automating decisions.

The repository's deterministic checks illustrate this pattern:

- `enrichment-pipeline/validation/verify_gds.py` validates structural separation.
- `enrichment-pipeline/jobs/04_validate_gold_tables.py` validates the materialized
  Gold-table contract.
- `enrichment-pipeline/jobs/01_genie_run_before.py` records the limitations of
  flat-table proxies for structural questions.

## Result-count expectations

Genie can generate different valid SQL shapes for the same natural-language
question. A strict superlative may return only tied top rows, while an explicit
top-N request returns a broader sample. Production acceptance tests should
therefore evaluate the returned evidence and generated SQL shape, not require an
identical row count for every paraphrase.

For operational demonstrations, phrase questions with an explicit limit when
sample breadth matters, such as “show the 100 account pairs with the highest
similarity score.” Keep the underlying GDS features deterministic so query-shape
variation does not become signal variation.

## Production boundary

The graph features in this repository are investigation signals, not fraud
verdicts. A production system should preserve human review or a separately
validated decision model, record feature and threshold provenance, and retain
the evidence used for every alert.
