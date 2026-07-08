# TLDR: Adding Basic KYC to Finance Genie

## Status: code complete, verified locally (2026-07-07)

| Increment | Status | Notes |
|-----------|--------|-------|
| 1. Identity attributes in background data | Done | `customers.csv` (25,000 rows) generated; all five pre-existing CSVs verified byte-identical, so the current pipeline and Genie space are untouched |
| 2. One named KYC story ring | Done | 8 accounts inside fraud ring 0 share phones 312-555-0142 / 312-555-0143 (4 each) and one address spanning both phone groups; recorded under `kyc_story_ring` in `ground_truth.json` |
| 3. Gold columns + verification | Code done, deploy pending | `verify_fraud_patterns.py` passes all 6 checks including the two new KYC checks; Gold changes need a pipeline run on Databricks |

What was changed:

- `enrichment-pipeline/setup/generate_data.py`: `generate_customers()` runs last so it cannot shift the seeded RNG stream; background phones never use the story-reserved 555 exchange, and emails and addresses are unique per customer.
- `enrichment-pipeline/setup/checks_structural.py`: new `check_kyc_story_ring` (ring returns exactly its 8 members) and `check_kyc_background_uniqueness` (zero duplicate background identifiers, zero 555 phones). Both wired into `diagnostics/verify_fraud_patterns.py` and passing.
- `enrichment-pipeline/sql/schema.sql`: new silver `customers` table with a foreign key to `accounts`.
- `enrichment-pipeline/upload_and_create_tables.sh`: loads `customers.csv` into the new table.
- `enrichment-pipeline/sql/gold_schema.sql` and `jobs/03_pull_gold_tables.py`: `gold_accounts` gains `shared_phone_count` and `shared_address_count` (22 columns now). A pandas simulation of the Spark logic flags exactly the 8 story accounts, everyone else 0.
- `enrichment-pipeline/run_existing_data_pipeline.py`: requires `customers.csv`.

Remaining to land it on Databricks (not run, to avoid overwriting the live demo tables from a stale Neo4j state):

1. `./upload_and_create_tables.sh` to create and load the silver `customers` table and re-load the other tables.
2. Re-run the gold pull (`python -m cli submit 03_pull_gold_tables.py`, or the full `run_existing_data_pipeline.py`) so `gold_accounts` picks up the two new columns. This reads GDS features from Neo4j, so Neo4j must hold current GDS output first.

## What KYC would add to the demo

- Today the demo only sees money movement: accounts, merchants, transfers, and GDS scores. It has no identity data at all.
- Add a minimal KYC identity layer: Customer nodes with phone, email, and address, linked to the existing Account nodes.
- Shared-identity edges expose synthetic-identity rings, for example accounts that share a phone number or address, which transfer patterns alone cannot catch.
- New story beat: the fraud ring GDS finds today gets explained by KYC. "These 8 accounts share 2 phone numbers and one address."
- Watchlist screening and beneficial ownership are deferred. Add them later only if the basic identity layer lands well.

## What we take from the demostack

Only one idea, from the `demo-data` skill: the two-layer data model.

- **Layer 1, story data:** a small number of hand-designed, named records. Every account, phone, and address in the KYC ring is written explicitly in code, so scripted queries return exact, known results.
- **Layer 2, background data:** generated volume that makes the story credible, with exclusion rules so it can never contaminate story query results. For example, story data owns the 555- phone prefix and background data never uses it.
- **Verification:** after generation, run checks that the story ring is intact and that zero background records collide with it.

The generator already does the background layer well: seeded RNG, log-normal amounts, weak tabular signals, and `ground_truth.json`. What it lacks is identity data and named story records. No DISCOVERY.md, blueprint, QA gates, rehearsal, or autopilot.

## Minimal increments

### Increment 1: identity attributes in background data

Extend `generate_data.py` to emit a `customers.csv` with one customer per account: Faker-generated name, phone, email, and address, all unique per customer. This is pure background data. Nothing shares anything yet, so no existing query changes behavior.

### Increment 2: one named KYC story ring

Hand-design a single ring of about 8 accounts inside one existing fraud ring: 2 shared phone numbers and 1 shared address, written as explicit records in the generator, not sampled. Reserve identifiable values for the story layer, such as the 555- phone prefix, and add an exclusion rule so background customers can never draw them. Record the ring membership and shared identifiers in `ground_truth.json`.

### Increment 3: land it in Gold and verify

- Add shared-attribute counts to the Gold layer, for example `shared_phone_count` and `shared_address_count` per account, so Genie can answer "which accounts share a phone number" the same way it answers fraud questions today.
- Extend `verify_fraud_patterns.py` with two checks: the story ring returns exactly its 8 members, and zero background customers share any identifier.

## Suggested first step

Increment 1 only: add `customers.csv` to the generator and confirm the existing pipeline and Genie space still work unchanged.

Update: all three increments are implemented and verified locally; see the Status section at the top for what remains on the Databricks side.
