# Neo4j Graph Algorithms — Use Case Notes


- Scale: 30.7M nodes and 56.5M relationships over a 14-day rolling window of completed claim packets. Because every claim is recorded as a time-ordered path through the graph, we can see exactly where packets slow down or pile up. Tracing these paths surfaces the real bottlenecks — and, just as importantly, what feeds into them and what they hold up downstream. That lets us reason about flow across the whole process instead of chasing one constraint at a time, since unblocking one bottleneck usually reveals the next.

Vector search finds products that look similar but can't traverse relationships, so it can't answer the questions that drive sales and resolve support issues. This demo treats product data as a graph: Neo4j handles multi-hop discovery, GraphRAG-grounded support answers, and cross-session customer memory, while Databricks handles inference and deployment. The takeaway: graph plus LLM beats vector-only RAG because the agent reasons over relationships and remembers the customer.

Policy Synchronization: Instead of just syncing raw data, you synchronize security metadata and policies. This ensures that the access controls applied in Databricks (or your source system) are translated into equivalent constraints or views within the graph.
Ontology-Driven Access Control: You can explain that the ontology provides a flexible framework for Attribute-Based Access Control (ABAC). Within the graph, access rights can be modeled as relationships between "User," "Role," and "Data Entity" nodes. This allows for fine-grained security where the graph engine can dynamically filter traversals based on a user's permissions in real-time.

## Use Case → Algorithm Mapping

### Boeing Aircraft Digital Twin (tail → faults, parts, forecast, one hop)
- **Not a GDS algorithm — it's a Cypher traversal/pattern match.** Variable-length expand (BFS) from the tail-number node across `HAS_FAULT`, `REQUIRES_PART`, `HAS_FORECAST` relationships.
- Optional: **Weighted shortest path (Dijkstra)** if you rank remediation options by cost/time for the go/no-go call.

### Boeing Design Requirement → Parts → In-Service Performance
- **Traversal/lineage** first: multi-hop pattern match `Requirement→Part→PerformanceRecord`.
- **Node Similarity / KNN** to match requirements to candidate parts that satisfy them.
- **PageRank (or Betweenness)** to surface the most critical / most-reused parts across the design.
- Optional: **Node2Vec / graph embeddings** to correlate part attributes with delivered performance.

### Veterans Affairs Disability Claim Process Graph (time-ordered paths)
- **Shortest / longest path on a DAG** — measure turnaround time along the event chain.
- **Betweenness Centrality** — the core bottleneck detector (which states/steps most claims must pass through).
- **Degree Centrality** — spot high-traffic hand-off nodes / queues.
- This is classic **process mining** over temporal paths (weight relationships by dwell time).

### Staples Agentic Commerce (GraphRAG retail assistant + Agent Memory)
- **Vector Search / KNN** — semantic retrieval for the GraphRAG layer.
- **Node Similarity + Personalized PageRank** — "customers/products like this" recommendations.
- **Collaborative filtering via graph traversal** — relationship-aware product answers.
- **Louvain / Leiden (community detection)** — customer/product segmentation.
- **Node2Vec embeddings** — power similarity + recommendations from graph structure.

---

## ELI5: Centrality Measures

### Degree Centrality — "How many friends do you have?"
- Just **count the connections** each node has.
- A person with 100 friends has high degree; a person with 2 friends has low degree.
- Answers: **"Who is the busiest / most connected?"**
- VA claim example: a claim step that 10,000 claims all pass into = high degree = a crowded desk.

### Betweenness Centrality — "Who is the bridge everyone has to cross?"
- Imagine everyone walking the **shortest route** to reach everyone else. Count how often each person gets **stepped on / passed through** along the way.
- A node scores high if it sits **on the path between other nodes** — like the only bridge between two islands.
- Answers: **"Who is the bottleneck / chokepoint?"**
- VA claim example: a single review step that almost every claim *must* funnel through to get to the end = high betweenness = the traffic jam.

### The Key Difference
- **Degree** = how many roads connect to *your* house.
- **Betweenness** = how many people drive *through your street* to get somewhere else.

> A node can have **low degree but high betweenness** — a small bridge with only 2 connections, but everyone must cross it. That's exactly the bottleneck you want to find in a process graph.
