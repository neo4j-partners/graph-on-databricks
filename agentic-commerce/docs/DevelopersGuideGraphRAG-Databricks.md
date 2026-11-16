# The Developer's Guide to GraphRAG on Databricks

---

## How Databricks and Neo4j Integrate

Databricks and Neo4j solve different problems well. Databricks handles large-scale structured data, including aggregations, time-series analysis, and machine learning over tables. Neo4j handles how things connect, following chains of relationships, finding patterns, and answering questions about structure. Most real-world problems need both, and the two platforms integrate at multiple levels.

Here are the most common high-level patterns:

- **Spark Connector for data movement.** The Neo4j Spark Connector is a two-way bridge between the platforms. Databricks notebooks and workflows can write Lakehouse rows into Neo4j as nodes and relationships, and pull graph data back into DataFrames for analytics or ML. What was implicit in table joins becomes explicit and traversable in the graph.

- **GraphRAG for smarter retrieval.** Documents get chunked and embedded using Databricks Foundation Models, stored as nodes in Neo4j linked to a knowledge graph, and retrieved using vector search combined with graph traversal. The result is AI responses grounded in connected context rather than isolated text fragments. This is the focus of this guide.

- **Unity Catalog JDBC for federated queries.** Neo4j can be registered as a JDBC connection in Unity Catalog. The Neo4j JDBC driver translates SQL into Cypher automatically, so graph data is queryable alongside Lakehouse tables in standard SQL. Graph data can also be materialized as Delta tables for dashboards and Genie spaces, all under unified governance.

- **Neo4j as an MCP server.** Model Context Protocol lets AI agents discover the graph schema and run Cypher queries on their own. An agent on Databricks can explore and query Neo4j without pre-built integrations. It learns the shape of the data, then writes and executes queries to answer user questions.

- **Multi-agent architectures.** Specialized agents for each platform (a Genie Space agent for Lakehouse analytics, a Neo4j agent for graph traversal) combine under a supervisor that routes questions to the right place. The Neo4j agent can be deployed as a Databricks Model Serving endpoint with its own conversation memory, or connected via MCP at the supervisor level.

---

## Table of Contents

- [Part I: The Problem With Current RAG](#part-i-the-problem-with-current-rag)
- [Part II: What Makes It GraphRAG](#part-ii-what-makes-it-graphrag)
  - [What Is RAG?](#what-is-rag)
  - [What Is GraphRAG?](#what-is-graphrag)
    - [1. Context-Aware Responses](#1-context-aware-responses)
    - [2. Traceability and Explainability](#2-traceability-and-explainability)
    - [3. Access to Structured and Unstructured Data](#3-access-to-structured-and-unstructured-data)
  - [How GraphRAG Works](#how-graphrag-works)
  - [Prepare a Knowledge Graph for GraphRAG](#prepare-a-knowledge-graph-for-graphrag)
  - [The Retail Graph Schema](#the-retail-graph-schema)
- [Part III: Constructing the Graph on Databricks](#part-iii-constructing-the-graph-on-databricks)
  - [Loading the Product Knowledge Graph](#loading-the-product-knowledge-graph)
  - [Building the GraphRAG Layer](#building-the-graphrag-layer)
  - [Loading Structured Data Into the Lakehouse](#loading-structured-data-into-the-lakehouse)
- [Part IV: Retrieval Patterns](#part-iv-retrieval-patterns)
  - [Databricks Model Adapters](#databricks-model-adapters)
  - [VectorRetriever (Baseline)](#vectorretriever-baseline)
  - [VectorCypherRetriever (Vector + Entity Traversal)](#vectorcypherretriever-vector--entity-traversal)
  - [HybridCypherRetriever (Hybrid Search + Entity Traversal)](#hybridcypherretriever-hybrid-search--entity-traversal)
  - [Text2CypherRetriever (LLM-Generated Cypher)](#text2cypherretriever-llm-generated-cypher)
- [Part V: From Retriever to Deployed Agent](#part-v-from-retriever-to-deployed-agent)
  - [The LangGraph ReAct Agent](#the-langgraph-react-agent)
  - [Deployment Pipeline](#deployment-pipeline)
  - [Serving Internals](#serving-internals)
- [Appendix: Configuration Reference](#appendix-configuration-reference)

---

## Part I: The Problem With Current RAG

**Why chunk-based RAG hits a ceiling, and why retrieval needs structure**

RAG systems start strong. Embed the product catalog, wire up a vector store, wrap a prompt around the results, and deploy. The first demo looks great. The model pulls from real data, answers sound grounded, and stakeholders nod approvingly.

Then a customer asks: "My running shoes feel flat and unresponsive after 300 miles. What should I do?"

The RAG system returns the product description for a running shoe. Technically relevant. Semantically similar. Completely unhelpful. It missed the knowledge article explaining that foam degradation is normal after 300 miles. It missed the support ticket where another customer reported the same symptom and got a resolution. It missed the recommendation to rotate between two pairs to extend cushion life. All of that context exists in the data. The retriever just can't see it.

> RAG retrieves semantically similar text, but it doesn't know how the pieces fit together.

The system has no concept of a "product" as a thing with features, known issues, and documented fixes. It doesn't know that a support ticket about outsole separation relates to the same shoe that has a knowledge article about care instructions. It treats every chunk as an island.

This is the ceiling. RAG retrieves based on similarity, not understanding. It fetches the closest-matching chunks and hopes the answer is in there. When the answer requires connecting information across a knowledge article, a support ticket, and a review, chunk-based retrieval falls short.

The fix is structure. Give the retriever a map of the domain, with products, categories, symptoms, features, and solutions connected by explicit relationships, and it can traverse that map to gather the right context. That's GraphRAG.

This guide walks through building it on Databricks, from loading products into a Neo4j knowledge graph, to extracting entities with Databricks-hosted LLMs, to deploying a retrieval agent on Model Serving. All code, no fluff.

---

## Part II: What Makes It GraphRAG

### What Is RAG?

LLMs generate responses from their training data. When a prompt goes straight to the model, responses lack business-specific knowledge. The model doesn't know your product catalog, your return policies, or the support ticket that was filed yesterday.

RAG addresses this by intercepting the prompt, querying an external knowledge base, and passing the retrieved context to the LLM along with the original question. Three components make this work:

- An **LLM** that generates the response
- A **knowledge base** that stores the information to retrieve from
- A **retrieval mechanism** that finds relevant information based on the input query

The quality of the response depends on what the retriever can find. In a traditional vector-based RAG system, the query gets converted into a numeric representation that captures its meaning, and the retriever finds chunks with the most similar representations. This works when the answer lives inside a single chunk. It breaks down when the answer requires context that spans multiple documents or data types.

### What Is GraphRAG?

In GraphRAG, the knowledge base is a knowledge graph. Instead of flat chunks in a vector store, information is organized as connected entities and relationships. Products connect to categories. Support tickets connect to products. Features, symptoms, and solutions extracted from documentation connect to the chunks they came from and to the products they describe.

The knowledge graph becomes a map of the domain. The retriever doesn't just find similar text; it follows relationships to gather context that no amount of vector similarity would surface on its own.

Consider an Agentic Commerce assistant chatbot. A customer asks about a shoe they bought, and a traditional RAG system would retrieve the closest-matching product description:

| Chunk Source | Text | Embedding |
|---|---|---|
| Product description | Nike Pegasus 40. Versatile everyday running shoe with responsive React foam... | [.234, .789, .123...] |

That's all it surfaces.

A GraphRAG system retrieves that product description, then traverses the graph to find the knowledge article about foam degradation after 300 miles, the support ticket where another customer reported the same symptom, and the solution recommending rotation between pairs. The graph connects what the vector store treats as unrelated.

#### 1. Context-Aware Responses

Traditional RAG retrieves isolated chunks based on similarity. GraphRAG retrieves facts in context. Because the knowledge graph encodes relationships explicitly, the retriever returns not just the matching chunk but also related products, known symptoms, documented solutions, and customer reviews. This structured retrieval reduces hallucinations and produces responses grounded in connected facts rather than isolated text fragments.

#### 2. Traceability and Explainability

Standard RAG operates as a black box. GraphRAG structures retrieval paths through the knowledge graph, making it possible to see which sources and relationships contributed to a response. When the agent recommends rotating running shoes, the graph shows that recommendation came from a specific knowledge article, linked to a specific product, connected to a specific symptom. Every hop in the traversal is auditable.

#### 3. Access to Structured and Unstructured Data

Vector-only RAG handles text. GraphRAG integrates structured data (product catalogs, transaction history, inventory levels) alongside unstructured content (knowledge articles, support tickets, reviews) in a single graph. A product node holds structured properties like price and category while connecting to unstructured chunks containing detailed troubleshooting guides. Richer data, richer answers.

### How GraphRAG Works

GraphRAG starts with a search to find entry points in the graph, then follows relationships to gather more context. The search can be vector-based, full-text, or both. From the initial results, the retriever traverses connected nodes and relationships, filters and ranks the results, and passes them to the LLM for response generation.

Building a GraphRAG application requires two steps:

1. **Preparing a knowledge graph** by ingesting documents, extracting entities, and importing structured data
2. **Implementing retrieval patterns** that combine search with graph traversal

The rest of this guide walks through both steps on Databricks.

### Prepare a Knowledge Graph for GraphRAG

A knowledge graph for GraphRAG needs two layers:

**The document layer** models how content is organized:
- How chunks connect to their source documents (knowledge articles, support tickets, reviews)
- How chunks connect to each other (a support ticket's issue description links to its resolution via `NEXT_CHUNK`)
- How documents connect to the products they cover

**The business entity layer** models the domain:
- Products, categories, brands, and attributes
- How products relate to each other (same category, same brand, bought together, similar)
- Features, symptoms, and solutions extracted from the document layer and linked back to products

These two layers work together. A chunk from a knowledge article connects to the product it covers. An entity extracted from that chunk (say, "outsole separation" as a Symptom) connects back to the product through a graph traversal. When a customer reports a similar symptom, the retriever can follow the graph from the symptom node to every product that shares it, every solution that addresses it, and every chunk that mentions it.

### The Retail Graph Schema

The Agentic Commerce assistant's knowledge graph has three tiers of nodes and relationships:

```
BUSINESS ENTITIES
─────────────────
(Product)─[:IN_CATEGORY]─>(Category)
(Product)─[:MADE_BY]─────>(Brand)
(Product)─[:HAS_ATTRIBUTE]─>(Attribute)
(Product)─[:SIMILAR_TO]──>(Product)
(Product)─[:BOUGHT_TOGETHER]─>(Product)

DOCUMENT LAYER
──────────────
(KnowledgeArticle)─[:COVERS]──>(Product)
(SupportTicket)────[:ABOUT]───>(Product)
(Review)───────────[:REVIEWS]─>(Product)

(KnowledgeArticle)─[:HAS_CHUNK]─>(Chunk)
(SupportTicket)────[:HAS_CHUNK]─>(Chunk)
(Review)───────────[:HAS_CHUNK]─>(Chunk)
(Chunk)────────────[:NEXT_CHUNK]─>(Chunk)

GRAPHRAG ENTITY LAYER (extracted by LLM)
────────────────────────────────────────
(Chunk)─[:MENTIONS_FEATURE]──>(Feature)
(Chunk)─[:REPORTS_SYMPTOM]───>(Symptom)
(Chunk)─[:PROVIDES_SOLUTION]─>(Solution)

(Product)─[:HAS_FEATURE]──>(Feature)
(Product)─[:HAS_SYMPTOM]──>(Symptom)
(Product)─[:HAS_SOLUTION]─>(Solution)
```

The business entity layer comes from the product catalog, loaded by [`retail_agent/deployment/load_products.py`](../retail_agent/deployment/load_products.py). The document layer comes from the same module, which creates KnowledgeArticle, SupportTicket, and Review nodes and links them to products.

The GraphRAG entity layer is where the graph gets its reasoning power. [`retail_agent/deployment/load_graphrag.py`](../retail_agent/deployment/load_graphrag.py) reads the document nodes, sends them through `neo4j-graphrag` `SimpleKGPipeline`, embeds chunks with `databricks-bge-large-en`, and uses the configured Databricks LLM endpoint to extract Feature, Symptom, and Solution entities. A final graph traversal links those entities back to the products they describe, creating the `HAS_FEATURE`, `HAS_SYMPTOM`, and `HAS_SOLUTION` relationships that make cross-product retrieval possible.

The connection between layers is what makes it work. A query about "flat, unresponsive cushioning" hits the chunk vector index, finds a matching chunk, traverses to the Symptom node "cushion responsiveness loss," then follows that symptom to every other chunk that reports it and every product that has it. The retriever gathers context that spans products, documents, and extracted entities in a single traversal.

---

## Part III: Constructing the Graph on Databricks

Building the knowledge graph happens in two Python wheel entry points designed to run on a Databricks cluster. [`retail_agent/deployment/load_products.py`](../retail_agent/deployment/load_products.py) creates the product catalog and document nodes. [`retail_agent/deployment/load_graphrag.py`](../retail_agent/deployment/load_graphrag.py) adds the GraphRAG layer on top: chunks, embeddings, and LLM-extracted entities.

### Loading the Product Knowledge Graph

The [Neo4j Spark Connector](https://neo4j.com/docs/spark/current/) is the bridge between Databricks and Neo4j. It implements Spark's DataSource V2 API, so any DataFrame can be written to Neo4j as nodes or relationships using standard Spark write operations. The connector takes care of converting DataFrame rows into graph operations, batching them for performance, and retrying automatically if something fails mid-write. Reading works in the other direction: the connector queries Neo4j by label, relationship type, or arbitrary Cypher and returns the results as DataFrames for analytics or ML pipelines.

For building a knowledge graph, the write path matters most. Data from Delta tables, CSVs, or in-memory collections becomes a DataFrame, and the connector maps columns to node properties or relationship attributes. Node writes use a key column to match existing records, so re-running the load updates what's there rather than creating duplicates. Relationship writes match the source and target nodes by their identifying properties (like product ID or category name), then create the connection between them.

The Agentic Commerce assistant's loader module ([`retail_agent/deployment/load_products.py`](../retail_agent/deployment/load_products.py)) centralizes graph writes in two helpers:

```python
def write_nodes(df, label, id_column):
    (df.write
     .format("org.neo4j.spark.DataSource")
     .mode("Overwrite")
     .option("labels", f":{label}")
     .option("node.keys", id_column)
     .save())

def write_relationships(df, rel_type, source_label, source_key,
                        target_label, target_key):
    (df.write
     .format("org.neo4j.spark.DataSource")
     .mode("Overwrite")
     .option("relationship", rel_type)
     .option("relationship.save.strategy", "keys")
     .option("relationship.source.labels", f":{source_label}")
     .option("relationship.source.save.mode", "Match")
     .option("relationship.source.node.keys", source_key)
     .option("relationship.target.labels", f":{target_label}")
     .option("relationship.target.save.mode", "Match")
     .option("relationship.target.node.keys", target_key)
     .save())
```

Every node type (Product, Category, Brand, Attribute, KnowledgeArticle, SupportTicket, Review) and every relationship type (`IN_CATEGORY`, `MADE_BY`, `HAS_ATTRIBUTE`, `COVERS`, `ABOUT`, `REVIEWS`, `BOUGHT_TOGETHER`) flows through these two functions. The connector batches the writes and handles retries on transient failures. Operations like index creation and embedding storage still use the Neo4j Python driver directly, since those are single-statement operations that don't benefit from Spark distribution.

From there, the script builds out the business entity layer. Category and Brand nodes are derived from the product data and linked with `IN_CATEGORY` and `MADE_BY` relationships. Attribute nodes (Cushion Level, Surface, Occasion, Fit, Material) get `HAS_ATTRIBUTE` relationships. Products in the same category get `SIMILAR_TO` edges. Frequently co-purchased items get `BOUGHT_TOGETHER` relationships with frequency and confidence properties.

The script also creates the document nodes: KnowledgeArticle, SupportTicket, and Review. Each connects to its product through `COVERS`, `ABOUT`, or `REVIEWS` relationships. These document nodes become the raw material for the GraphRAG pipeline in the next step.

The final step generates product embeddings using the Databricks Foundation Model API. The `databricks-bge-large-en` model produces 1024-dimensional vectors, which are stored directly on Product nodes and indexed with a cosine similarity vector index called `product_embedding`.

```python
client = mlflow.deployments.get_deploy_client("databricks")
response = client.predict(
    endpoint="databricks-bge-large-en",
    inputs={"input": ["Nike Pegasus 40: Versatile everyday running shoe..."]},
)
embedding = response["data"][0]["embedding"]  # 1024-dim vector
```

> **Tip:** The embedding dimension must match everywhere: product embeddings, chunk embeddings, and the agent's runtime embedder. A mismatch causes silent failures where vector queries return zero results.

### Building the GraphRAG Layer

This is where the graph gets its reasoning power. [`retail_agent/deployment/load_graphrag.py`](../retail_agent/deployment/load_graphrag.py) runs after the product load and uses `neo4j-graphrag` `SimpleKGPipeline` to add the retrieval graph on top of the existing product and document graph. Each stage builds on the previous one.

**Stage 1: Chunk.** The script fetches KnowledgeArticle, SupportTicket, and Review text from Neo4j and passes each document to `SimpleKGPipeline`. The pipeline creates Document and Chunk nodes, stores document metadata, and links chunks to generated Document nodes. A post-processing step connects those chunks back to the existing KnowledgeArticle, SupportTicket, and Review nodes with `HAS_CHUNK`.

**Stage 2: Embed.** Chunk text is embedded through a `neo4j-graphrag` embedder adapter backed by the Databricks Foundation Model API. Two indexes get created on the Chunk nodes: a vector index (`chunk_embedding`, 1024 dimensions, cosine similarity) for semantic search, and a fulltext index (`chunkText`) configured for English-language text for keyword matching. The fulltext index matters for queries containing specific brand or product terms that need exact matching alongside semantic similarity.

**Stage 3: Extract Entities.** `SimpleKGPipeline` sends each chunk to the configured Databricks LLM adapter with a schema that allows Feature, Symptom, and Solution nodes and their relationships:

```json
{
  "node_types": ["Feature", "Symptom", "Solution"],
  "relationship_types": ["HAS_FEATURE", "HAS_SYMPTOM", "HAS_SOLUTION", "RELATED_TO"]
}
```

The schema constrains extraction to the retail support concepts the agent needs. Each entity becomes a Feature, Symptom, or Solution node. The library links entities to chunks with `FROM_CHUNK`, and the loader adds retrieval relationships (`MENTIONS_FEATURE`, `REPORTS_SYMPTOM`, `PROVIDES_SOLUTION`) so the deployed tools and demo retrievers can query the graph directly.

This is the defining step of GraphRAG. An LLM reads unstructured text and produces structured entities that become graph nodes. The same approach can be applied to any domain by changing the extraction prompt and entity types.

**Stage 4: Link Entities to Products.** The final stage creates aggregated relationships between products and their entities through graph traversal. The path follows existing edges: from Product through the document that covers it, through the chunk extracted from that document, to the entity extracted from that chunk:

```
Product <-[:COVERS|ABOUT|REVIEWS]- doc -[:HAS_CHUNK]-> chunk <-[:FROM_CHUNK]- entity
```

This traversal produces `Product -[:HAS_FEATURE]-> Feature`, `Product -[:HAS_SYMPTOM]-> Symptom`, and `Product -[:HAS_SOLUTION]-> Solution` relationships. These aggregated edges are what make cross-product retrieval possible. When a customer reports "cushion responsiveness loss," the retriever can go from that Symptom node to every product that has it and every solution that addresses it, without re-traversing the chunk layer each time.

### Loading Structured Data Into the Lakehouse

The knowledge graph handles product information, documentation, and entity relationships. Transaction-level analytics live in the Databricks Lakehouse as Delta tables. The [`generate_transactions.py`](../retail_agent/scripts/generate_transactions.py) script creates realistic retail data: 1.15 million transaction line items, 5,000 customers, 115,000 reviews, 417,000 daily inventory snapshots across 20 stores. The [`lakehouse_tables.py`](../retail_agent/scripts/lakehouse_tables.py) script uploads the generated CSVs to a Unity Catalog volume and creates Delta tables.

These tables complement the knowledge graph. A multi-agent architecture can route analytical queries ("What are our top-selling running shoes this quarter?") to Databricks SQL or Genie, while product knowledge queries ("Why do my shoes feel flat?") go to the Neo4j-backed GraphRAG retriever.

---

## Part IV: Retrieval Patterns

GraphRAG retrieval patterns define how the LLM accesses the context and connections in the knowledge graph. This section demonstrates four patterns from the `neo4j-graphrag` Python package, each using Databricks-hosted models. The patterns progress from simple vector search to graph-enhanced retrieval to LLM-generated Cypher.

### Databricks Model Adapters

The `neo4j-graphrag` retrievers expect an `Embedder` and `LLMInterface`. Two thin adapter classes bridge the gap to the Databricks Foundation Model API via `mlflow.deployments`. The embedder wraps `databricks-bge-large-en` and implements `embed_query()`. The LLM adapter wraps the configured Databricks LLM endpoint and implements `invoke()`, handling both string and message-list inputs since different retrievers use different calling conventions.

Both adapters use `mlflow.deployments.get_deploy_client("databricks")`, which handles authentication automatically on Databricks clusters. No API keys to manage.

### VectorRetriever (Baseline)

The basic retriever uses vector embeddings to find Chunk nodes that are semantically similar to the query. It embeds the query, searches the `chunk_embedding` vector index, and returns the closest matches. This retriever handles specific information requests where the answer lives within a single chunk.

```python
vector_retriever = VectorRetriever(
    driver=driver,
    index_name="chunk_embedding",
    embedder=embedder,
    return_properties=["text", "chunk_id", "source_type"],
)
```

For the query "My running shoes feel flat and unresponsive. What should I do?", the retriever finds chunks that mention cushioning problems. It returns semantically similar text, and that text might contain useful advice.

But it has no awareness of the entity graph. It doesn't know which other products share the same symptom, which solutions other customers found helpful, or which features relate to the problem. Each result is an isolated chunk. The retriever works, but it leaves context on the table.

This is the baseline. Everything that follows builds on it.

### VectorCypherRetriever (Vector + Entity Traversal)

The `VectorCypherRetriever` overcomes the baseline's limitation by combining vector similarity search with graph traversal. It starts with the same semantic search to find the top-k chunks, then executes a Cypher query to traverse from those chunks through the entity graph. The retriever completes two actions: first a similarity search against the vector index, then a graph traversal based on the matched nodes.

The retrieval query walks from each matched chunk through its extracted entities and then to related chunks and products:

```cypher
RETURN node.text AS text, score,
  collect {
    MATCH (node)-[:MENTIONS_FEATURE]->(f:Feature) RETURN f.name
  } AS features,
  collect {
    MATCH (node)-[:REPORTS_SYMPTOM]->(s:Symptom) RETURN s.name
  } AS symptoms,
  collect {
    MATCH (node)-[:PROVIDES_SOLUTION]->(sol:Solution) RETURN sol.name
  } AS solutions,
  collect {
    MATCH (node)-[:REPORTS_SYMPTOM]->(s:Symptom)
          <-[:REPORTS_SYMPTOM]-(other:Chunk)
    WHERE other <> node
    MATCH (other)<-[:HAS_CHUNK]-(doc)
          -[:COVERS|ABOUT|REVIEWS]->(p:Product)
    RETURN DISTINCT p.name
  } AS related_products
```

The last `collect` clause is where graph traversal shines. It follows the symptom reported in the matched chunk to every other chunk that reports the same symptom, then resolves which products those chunks belong to. For the "flat and unresponsive" query, the retriever now surfaces not just the matching chunk but also related products that share the "cushion responsiveness loss" symptom and the solutions documented for them.

Run both retrievers on the same query, side by side, and the difference is concrete. VectorRetriever returns five chunks. VectorCypherRetriever returns five chunks plus their extracted features, symptoms, solutions, and a list of related products that share those symptoms. The LLM gets richer context, which means a more complete answer.

The power of this pattern lies in its flexibility. While this example focuses on retail product symptoms, the approach applies to any domain by customizing the graph schema and Cypher traversal queries. Healthcare teams could traverse from clinical notes through diagnoses to treatment plans. Cybersecurity teams could follow threat intelligence from vulnerabilities to affected assets to mitigation strategies.

### HybridCypherRetriever (Hybrid Search + Entity Traversal)

Some queries contain specific terms where exact keyword matching matters. "Continental outsole peeling after 3 months" includes "Continental," a brand name that vector similarity alone might not weight correctly. The `HybridCypherRetriever` combines fulltext search (which catches exact keyword hits) with vector search (which catches semantic similarity), then runs the same entity traversal.

This retriever uses both the `chunk_embedding` vector index and the `chunkText` fulltext index. The retrieval query follows solutions instead of symptoms, finding other products that share the same fix. When to use hybrid over pure vector: any time the query contains brand names, product model numbers, or specific technical terms.

### Text2CypherRetriever (LLM-Generated Cypher)

This pattern skips embeddings entirely. The LLM translates natural language into a Cypher query that runs directly against the entity graph. The `examples` parameter provides few-shot guidance, mapping natural language questions to the Cypher queries that answer them.

For "What are the most common problems with running shoes?", the LLM generates a Cypher query that aggregates symptom counts across products in the Running Shoes category. No vector index needed. The query goes straight to the structured entity graph.

The tradeoff is determinism. The LLM generates a different query each time, and those queries may not be optimized or even correct. For exploratory questions and prototyping, Text2Cypher is fast and flexible. For production systems where the same question must return consistent results, VectorCypherRetriever or HybridCypherRetriever are safer choices.

All four retrievers can be wrapped with `GraphRAG` for end-to-end question answering:

```python
rag = GraphRAG(llm=llm, retriever=retriever)
response = rag.search(query, return_context=True)
```

---

## Part V: From Retriever to Deployed Agent

The retriever patterns from Part IV work in notebooks and scripts. Putting them behind a production endpoint requires an agent framework, a model serving adapter, and a deployment pipeline. The Agentic Commerce assistant uses LangGraph for the agent, MLflow ChatAgent for the serving contract, and `agents.deploy()` for the infrastructure.

### The LangGraph ReAct Agent

The agent is a LangGraph `create_react_agent` backed by `databricks-claude-sonnet-4-6`. It has tools for product search, product details, and related products. It also has tools for GraphRAG knowledge search and issue diagnosis, session memory, long-term preferences, personalized recommendations, and reasoning traces. The `context_schema=RetailContext` parameter passes shared resources (like the Neo4j client and session ID) to every tool automatically, without routing them through the LLM.

The agent decides which tool to call based on the user's question. "Search for running shoes under $200" triggers `search_products`, which embeds the query with `databricks-bge-large-en` and runs a vector search against the product graph. "What products are related to the Nike Pegasus 40?" triggers `get_related_products`, which uses graph traversal across category, brand, and attribute relationships to score and rank related items. The LLM handles orchestration; the tools handle data access.

### Deployment Pipeline

Deployment follows a four-step pipeline in [`retail_agent/deployment/deploy_agent.py`](../retail_agent/deployment/deploy_agent.py):

1. **Log model to MLflow.** The [`serving.py`](../retail_agent/agent/serving.py) file is the entry point. MLflow's Models from Code approach packages it along with all imported modules (agent, tools, embedder, config) as code artifacts. The `neo4j-agent-memory` library is installed as a pinned pip requirement.

2. **Register to Unity Catalog.** The logged model gets registered as a versioned model at `retail_assistant.retail.retail_agent_v3`.

3. **Deploy with `agents.deploy()`.** Neo4j credentials are injected as secret-backed environment variables. The deployment configuration requests scale-to-zero by default. The served endpoint versions validated for this project reported `scale_to_zero_enabled: false`.

4. **Wait for ready.** The script polls the endpoint state until it reports `READY` or the timeout expires.

The [serving adapter](../retail_agent/agent/serving.py) handles the transition from Model Serving's synchronous `predict()` contract to the agent's async internals. A background thread manages the async Neo4j connection and keeps it alive across requests. The adapter delays connecting to Neo4j until the first real request arrives, since credentials aren't available during initial validation. Once connected, it reuses the same client for all subsequent calls.

### Serving Internals

The serving adapter integrates the `neo4j-agent-memory` library into Model Serving in three steps:

- **Lazy initialization:** The adapter creates the `MemoryClient` on the first real request. It reads the Neo4j credentials from Databricks secrets and passes a custom `DatabricksEmbedder`, which wraps the Foundation Model API to satisfy the library's `Embedder` interface.
- **Per-request context:** Each request builds a `RetailContext` that holds the shared `MemoryClient`, the caller's session ID, and the caller's user ID. LangGraph injects that context into every tool through `ToolRuntime`.
- **Direct memory calls:** Tools call the `MemoryClient` directly. Short-term calls store and recall messages. Long-term calls track and retrieve preferences with user ID metadata. Reasoning calls record and search multi-step traces.

The serving configuration disables conversation entity extraction in `neo4j-agent-memory`. The endpoint therefore needs no additional extraction model at runtime.

The Neo4j async driver must stay bound to one event loop, so the adapter keeps a persistent loop:

- A daemon thread runs a single asyncio loop for the lifetime of the serving process.
- The `MemoryClient` connects on that loop during lazy initialization, which binds the Neo4j driver to the persistent loop from the start.
- Every request dispatches its async work to the same loop with `run_coroutine_threadsafe`.

---

## Appendix: Configuration Reference

All configuration lives in [`agent/config.py`](../retail_agent/agent/config.py) as a dataclass with sensible defaults:

| Setting | Default | Description |
|---|---|---|
| `catalog` | `retail_assistant` | Unity Catalog catalog name |
| `schema` | `retail` | Unity Catalog schema name |
| `model_name` | `retail_agent_v3` | Model name in Unity Catalog |
| `llm_endpoint` | `databricks-claude-sonnet-4-6` | Databricks-hosted LLM for the agent |
| `embedding_model` | `databricks-bge-large-en` | Foundation Model API embedding endpoint |
| `embedding_dimensions` | `1024` | Must match vector index dimensions |
| `scale_to_zero` | `true` | Enable scale-to-zero on serving endpoint |
| `max_wait_seconds` | `1200` | Timeout for endpoint readiness check |

The full Unity Catalog model name resolves to `retail_assistant.retail.retail_agent_v3` by default. The active validated serving endpoint is `agents_retail_assistant-retail-retail_agent_v3`.
