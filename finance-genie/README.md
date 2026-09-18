# Graph-Enriched Lakehouse: Finance Genie

[Project website and slides](https://neo4j-partners.github.io/graph-on-databricks/)

Finance Genie is a set of Databricks and Neo4j demos for fraud analysis.

- **Silver tables:** Base account, merchant, transaction, and relationship data in Databricks.
- **Neo4j Graph Data Science:** Graph algorithms that find connected accounts, important accounts, and similar accounts.
- **Gold tables:** Databricks tables that store graph results for SQL, Genie, dashboards, and models.
- **Genie:** A Databricks assistant that answers questions about your data.

The main demo loads Silver data into Neo4j, runs graph algorithms, and writes the results to Gold tables. Databricks tools can then use graph results as normal table columns.

## Canonical Setup

Run this setup first. It creates the shared Finance Genie data, graph, Gold tables, and Genie Spaces. The optional demos use this environment.

### Create `.env`

Copy the sample file. Then add your Databricks, compute, warehouse, and Neo4j Aura values.

```bash
cd finance-genie
cp .env.sample .env
# Add your Databricks and Neo4j Aura values to .env.
```

### Run the full setup

**`make demo` is the main setup command.** It loads the sample data, builds the Neo4j graph, runs Graph Data Science, creates Gold tables, and creates or updates the BEFORE and AFTER Genie Spaces.

```bash
make demo
```

- **First run:** `make demo` saves the Genie Space IDs in your local `.env` file.
- **Later runs:** `make demo` updates the same Genie Spaces and reloads the configured Neo4j graph.
- **Sample data:** The committed synthetic data is the default. Run `make data` only when you need a new dataset.

### Check the setup

Run this command to check Databricks access, Neo4j access, and source data. It does not change them.

```bash
make check
```

### Build only the Neo4j graph

Use this command when the Finance Genie Silver tables already exist. It builds the Neo4j graph and graph results. It does not create Lakehouse tables, Gold tables, or Genie results. Databricks job compute is still required because the ingest job reads Silver tables.

```bash
make graph
```

- **Optional demos:** `make demo` does not deploy the MCP agent, Fraud Signal Workbench, Semantic Investigation Copilot, or Virtual Graph Demo. Use the links below to run them.

## Demo Applications

Choose the demo that matches your goal.

| Demo | Purpose | Start here |
|---|---|---|
| **Graph-Enriched Lakehouse** | Shows how graph results become reusable Gold table columns for Genie, SQL, dashboards, and models. | [Enrichment Pipeline](./enrichment-pipeline/README.md) or [Workshop](./workshop/README.md) |
| **Neo4j MCP Graph Agent** | Deploys a graph-only agent that retrieves live Neo4j evidence through MCP. Pair it with a Databricks Supervisor Agent and Genie when needed. | [Neo4j MCP Graph Agent](./neo4j-mcp-graph-agent/README.md) |
| **Fraud Signal Workbench** | Provides a guided web application for fraud investigators. Users search, load selected graph evidence into Delta tables, and analyze it with Genie. | [Fraud Signal Workbench](./fraud-signal-workbench/README.md) |
| **Semantic Investigation Copilot** | Builds a local metadata graph for one Databricks schema and the Finance Genie graph. The Streamlit app uses that map to create grounded SQL and graph queries. | [Semantic Investigation Copilot](./semantic-investigation-copilot/README.md) |
| **Virtual Graph Demo** | Queries Finance Genie Silver tables from Neo4j without copying them. It shows Cypher and Graph Data Science behavior over a Databricks Virtual Graph. | [Virtual Graph Demo](./virtual-graph-demo/README.md) |

## Project Map

- **Enrichment Pipeline:** Admin and CI commands for the shared setup. It loads data, creates tables and secrets, runs graph enrichment, creates Genie Spaces, and validates results. See [enrichment-pipeline/](./enrichment-pipeline/README.md).
- **Workshop:** Databricks notebooks for running the graph-enrichment demo step by step. See [workshop/](./workshop/README.md).
- **Demo guide:** Presenter story, questions, speaker notes, and slides. See [docs/demo-guide/](./docs/demo-guide/).
- **Neo4j MCP Graph Agent:** MCP connection setup and graph-agent deployment. See [neo4j-mcp-graph-agent/](./neo4j-mcp-graph-agent/README.md).
- **Fraud Signal Workbench:** React and FastAPI investigation application. See [fraud-signal-workbench/](./fraud-signal-workbench/README.md).
- **Semantic Investigation Copilot:** Metadata graph, MCP server, command-line query tool, and Streamlit app. See [semantic-investigation-copilot/](./semantic-investigation-copilot/README.md).
- **Virtual Graph Demo:** Cypher and Graph Data Science examples over a Databricks Virtual Graph. See [virtual-graph-demo/](./virtual-graph-demo/README.md).

## Further Reading

- **Architecture:** [Pipeline design and data flow](./docs/architecture.md).
- **KYC:** [Shared-identity detection and demo walkthrough](./docs/kyc-guide.md).
- **Production scoping:** [Evaluation and operating guidance](./docs/SCOPING_GUIDE.md).
- **Presenter guide:** [Story, questions, and slides](./docs/demo-guide/prep-guide.md).
- **Full deck:** [Finance Genie presentation](https://neo4j-partners.github.io/graph-on-databricks/slides.html).
- **15-minute deck:** [Short Finance Genie presentation](https://neo4j-partners.github.io/graph-on-databricks/slides-15min.html).
