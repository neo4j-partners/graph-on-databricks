# Re: GDS projections and non-numeric properties

Good news: what you ran into is expected GDS behavior, and there is a clean pattern that works well for exactly the subset-and-analyze workflow you want.

You are correct on both points. Native in-memory GDS projections only carry numeric property values, and `gds.graph.export` only writes what is in the projection, so an export of a property-free or numeric-only projection comes out bare. Both are by design rather than a defect, which means the fix is to change the workflow rather than fight the constraint.

Because your source graph is large enough that a separate working graph makes sense, here is the pattern we recommend:

1. Do the subsetting at the Cypher or database layer, not through a GDS projection. Options include `apoc.export.cypher`, `apoc.graph.fromCypher`, or `neo4j-admin database copy` with a filter. This carries every property, numeric and string, into the new graph at full fidelity, which is exactly what a GDS projection cannot do.
2. In the new subset graph, project a lightweight topology-only subgraph in memory. The structural algorithms (PageRank, Louvain, Betweenness, Node Similarity) need only the relationship structure, so no node properties go into the projection at all.
3. Run the algorithms with `.write()`. Results land back on the original nodes in the subset graph as numeric properties. The projection keeps an internal mapping to the source nodes, so the writes land correctly without any non-numeric data ever passing through the projection.
4. Drop the projection and read the enriched nodes from the subset graph, where every property, including the string ones, is still present.

The key shift is that the subsetting and the algorithm work happen at different layers. The database or Cypher layer moves the full subset with all properties intact, and the GDS projection is used only as numeric compute scratch space for the algorithms. Treating a projection as a graph-extraction tool is what leads to the bare-export surprise, so the two jobs stay separate.

## How Finance Genie lands this in Gold tables

1. A Databricks job reads the Silver Delta tables and writes them into Neo4j through the Spark Connector as a property graph: `:Account` and `:Merchant` nodes, with `TRANSACTED_WITH` and `TRANSFERRED_TO` relationships.
2. GDS runs against that graph and writes the structural scores back onto the nodes as numeric properties.
3. A Databricks job reads the enriched node properties from Neo4j through the Spark Connector.
4. It writes them into Gold Delta tables as plain numeric columns: `risk_score`, `community_id`, and `similarity_score`, plus a few derived rollups like community size and risk tier.
5. Genie, SQL warehouses, and dashboards read those columns directly, with no graph knowledge needed downstream.
6. The graph stays the system of record for structure.

The Finance Genie demo walks through this end to end, including the projection setup, the write-back, and pulling the enriched results out into downstream tables. Happy to walk you through it live or share the workshop notebook so you can see the full sequence.
