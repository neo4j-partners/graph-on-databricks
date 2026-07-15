# Dual Data Architecture: Classifications & Realizations

## CLASSIFIED_AS (knowledge applied to instances)
- Instance node (Customer / Supplier) is **classified as** a governed `BusinessTerm`
- Edge carries `{reason, evaluatedAt, ruleVersion}`
- Result written back to Databricks Gold table `classifications` (one row = one entity tagged with a term + why)

### Business terms assigned
- **Platinum Customer** — top commercial tier (pre-planted)
- **Strategic Account** — platinum customer flagged strategic (pre-planted)
- **High-Risk Supplier** — supplier riskScore >= threshold (computed live)
- **Risky Customer** — >60 days late on each of last 3 invoices (computed live)
- **Unreconciled Revenue** — recognized revenue over materiality threshold per business unit

## REALIZED_AS (knowledge type made concrete)
- Knowledge-layer `Entity` is **realized as** the concrete instance-graph nodes:
  - Customer
  - Supplier
  - BusinessUnit
  - Invoice
  - RevenueEntry
  - ComplianceFinding

## How this demo maps to the customer requirements
- **Own IP** — the knowledge layer (`BusinessTerm`, `BusinessRule`, `Threshold`, `Policy`) lives in Neo4j, owned by the customer, never embedded in the vendor platform
- **No duplication with Databricks** — lakehouse owns instance data, graph owns the knowledge layer; results written back to Delta rather than re-storing raw data
- **Zero-copy / virtual graph** — `DataSource.MAPS_TO` points at real Unity Catalog tables; optional virtual access from Neo4j (no data movement)
- **Agentic AI misalignment (verified, not hallucinated)** — classifications come from explicit rules, so every `CLASSIFIED_AS` carries `{reason, ruleVersion, evaluatedAt}`: a verified, explainable path, not an LLM guess
- **Curated semantic layer** — governed terms + rules give one consistent definition of each metric, fixing the conflicting-versions problem behind bad agentic BI
- **Keep it flat / debuggable** — one knowledge layer over the instance graph; provenance on every edge, no stacked harnesses
- **Multi-hop over connected data** — instance graph (`SUPPLIES`, `HAS_INVOICE`, `BELONGS_TO`, `RECOGNIZES`) plus GDS exposure scoring, the traversal Databricks' columnar store is weak at
