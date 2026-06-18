# Talk Track: Graphs Power Enterprise Transformation

*Slide: graph_use_cases.png*

Neo4j is a graph database that models a business the way it actually works using nodes and relationships. It allows you to model cities and the roadways that connect them, suppliers to parts, employees to skills, accounts to the
money that flows between them. That gives you a rich, interconnected data model, and
graph data science turns that model into deeper insight. In this talk we'll show an example
of how that's used to find financial fraud.

Take financial crime. Model each account as a node, every transaction as a
relationship, and the merchants and counterparties they route money through as the
entities that tie them together. A fraud ring is not one bad transaction. It is a
shape: a tight cluster of accounts moving money densely among themselves. Each
transaction looks ordinary; the pattern across accounts does not. That structure
yields deeper insight and more effective detection than tabular analysis alone.

This is where Graph Data Science earns its place. GDS lets us model, query, and
analyze that structure in ways flat tables cannot. Centrality finds the accounts at
the heart of the money flow, community detection finds the clusters, and similarity
finds the accounts routing through the same counterparties, sharpening our ability
to identify malicious activity. In this demo we show exactly that: when we add
graph-derived features to the lakehouse, every metric improves.
