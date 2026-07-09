# Supplier Risk Demo: Talk Track for the Team

## Message to the team

I updated the slides and built a demo showing how the knowledge layer is actually applied: the graph classifies a customer as risky, then stores the classification and its reasoning in the knowledge layer so anyone can trace the "why."

Here is how I see it mapping to what the customer asked for:

- **IP ownership:** The risk rules and business terms live in the graph they own, pointing at Databricks tables instead of copying the data.
- **Agentic BI accuracy:** Their BI errors trace back to an inaccurate semantic layer. That is the strongest argument for a curated graph knowledge layer, so the demo makes that layer visible.
- **Complement vs. overlap:** Show where Neo4j overlaps Genie Ontology. The dual architecture draws the line: lakehouse owns the instance data, graph owns the knowledge layer.
- **Explainable answers:** They need verified paths for business-critical metrics. The provenance view is exactly that: every classification carries its rule, inputs, and reason.

## Proposed talk track (full version)

1. **Neo4j + Databricks integration, dual data architecture** (new slide 7): Lakehouse owns the instance tables, graph owns the knowledge layer plus the instance graph. Call out MAPS_TO lineage to Unity Catalog and the gold write-back.
2. **How a customer is classified** (new slide 8): Walk one customer from record to CLASSIFIED_AS, to the business term, to the rule, to the data sources, to the gold write-back. This is the traceable "why."
3. **Live demo:** Genie answering across both sources: which customers are risky (lakehouse) and why (knowledge layer). One question, both sources, reasoning attached.
4. **Compare to Databricks ontology:** Where Genie Ontology fits, where the owned graph layer fits, why they complement.

## Alternative if this is too in-depth for the audience

- **High-level architecture:** Lakehouse owns the data, graph owns the knowledge layer.
- **Live demo:** Genie pulling from both sources.
- **Cut:** the detailed classification and provenance walkthrough.
