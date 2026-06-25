# Lakehouse Data

The main agent runtime uses Neo4j. The repo also contains scripts for generating synthetic retail lakehouse data for Databricks SQL and Genie-style analytics demos.

This step is optional for the current Agentic Commerce pipeline. If you do not generate or upload the lakehouse data, the Neo4j-backed product search, GraphRAG tools, memory, recommendations, model deployment, and endpoint checks still work. What you do not get is the separate Delta table dataset used for SQL analytics or future Genie/supervisor demos.

Generate expanded catalog data:

```bash
uv run python -m retail_agent.scripts.generate_transactions --expanded --verify
```

This writes CSVs to `data/lakehouse/`:

| File | Rows | Description |
|------|------|-------------|
| `transactions.csv` | ~1.15M | Line items across 500K orders |
| `customers.csv` | 5,000 | Customer dimension with segments |
| `reviews.csv` | ~115K | Product reviews linked to transactions |
| `inventory_snapshots.csv` | ~417K | Daily stock levels per product |
| `stores.csv` | 20 | Physical store locations |
| `knowledge_articles.csv` | Product knowledge articles | Product manuals, FAQs, and troubleshooting content |

Upload CSVs and create Delta tables:

```bash
uv run python -m retail_agent.scripts.lakehouse_tables
```

Options:

```bash
uv run python -m retail_agent.scripts.lakehouse_tables --skip-upload
uv run python -m retail_agent.scripts.lakehouse_tables --skip-tables
```
