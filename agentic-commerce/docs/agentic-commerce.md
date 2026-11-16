# Agentic Commerce: GraphRAG Meets Agent Memory on Neo4j

Autonomous commerce requires agents that do more than generate text. An agent negotiating a bulk purchase needs to traverse supplier relationships, recall a buyer's past preferences, and remember which negotiation strategy worked three months ago. Those are three distinct capabilities, and they map to three distinct technologies: knowledge graphs for relational structure, GraphRAG for grounded retrieval, and persistent agent memory for learning from experience. The vision for agentic commerce is the convergence of all three, running against a single Neo4j database where the connections between them are native graph relationships rather than foreign keys across separate systems.

Knowledge graphs store the commercial ontology, the products, suppliers, pricing tiers, and compatibility rules all connected through explicit relationships that an agent can traverse with mathematical precision. GraphRAG retrieves from that graph to ground LLM responses in relational fact rather than probabilistic similarity, turning multi-hop questions like "which compatible accessories are in stock near this customer" into concrete graph traversals instead of embedding lookups. Agent memory records every conversation, extracted entity, and reasoning trace, so the agent accumulates operational intelligence over time without requiring model retraining.

## Anatomy of an Agentic Transaction

When a user initiates a commercial request, the agent logs the interaction into short-term memory and parses the natural language to extract entities and constraints. The POLE+O data model (Person, Object, Location, Event, Organization) classifies those entities by type, updating the agent's long-term memory graph with new user preferences that persist across sessions.

With the request understood, the agent triggers a GraphRAG retrieval against the Neo4j knowledge graph, traversing semantic relationships that connect the user's preferences to product catalogs, pricing tiers, and fulfillment logistics. Because the data is structured relationally, the agent can execute multi-hop reasoning in a single pass: verifying that a specific device is compatible with the user's existing hardware, checking stock at a nearby warehouse via geospatial indexing, and confirming it qualifies for an active promotional discount.

Every step in this process, each API call, logical deduction, and intermediate result, gets recorded as a reasoning trace. When the agent successfully negotiates a price or identifies a novel product pairing, that success is codified in the graph. Future transactions benefit directly, since the agent can query its own reasoning memory to recall structural precedents and apply proven strategies to comparable tasks. Graph retrieval grounds each decision in fact, memory updates capture what the agent learned, and reasoning traces preserve how it got there.

Neo4j is what makes this convergence practical. Knowledge graph traversals, vector-similarity retrieval, and memory writes all execute against a single database, connected through native graph relationships rather than API calls between separate systems. A Cypher query can follow a path from a user's conversation history through the entities mentioned in that conversation to the product nodes, pricing tiers, and fulfillment data those entities reference. That path crosses all three capabilities in one traversal because the data lives in one graph. Two open-source libraries divide the work. neo4j-graphrag-python handles knowledge graph construction and retrieval, turning unstructured documents into queryable graph structures and getting the right context to the LLM. Agent-Memory handles the other side, giving the agent persistent short-term, long-term, and reasoning memory that accumulates across sessions. The sections that follow cover each library in detail.

---

## [neo4j-graphrag-python](https://github.com/neo4j/neo4j-graphrag-python): Full-Pipeline GraphRAG in a Single Library

**Built on Neo4j | Open Source**

### Standard RAG Loses Relationships. GraphRAG Keeps Them.

Ask a vector-only RAG system "how are Company A and Company B connected?" and it retrieves chunks that mention each company independently. The relationship between them, a shared board member, a joint venture filed in an SEC document three pages away from either mention, never surfaces. Flat embeddings capture what words mean. They don't capture how entities relate to each other across a corpus.

The neo4j-graphrag-python library addresses this gap directly. It builds knowledge graphs from unstructured text and retrieves information from those graphs to feed into LLM-powered answer generation. Raw text goes in, a queryable knowledge graph comes out, and the same library handles retrieval and response generation on the other side. Construction and retrieval share the same abstractions, the same Neo4j connection, and the same schema definitions.

### Two Paths to Knowledge Graph Construction

Two construction approaches target fundamentally different use cases. One optimizes for speed. The other trades convenience for full control over every component in the pipeline.

#### SimpleKGPipeline Gets a Graph Running in Minutes

SimpleKGPipeline wraps the entire construction process into a single class. Hand it an LLM, a Neo4j driver, and an embedder, point it at a PDF or a block of text, and it handles document loading, chunking, embedding, entity extraction, schema validation, graph writing, and entity resolution automatically, seven components wired together in one constructor call.

Schema configuration determines how much structure the LLM applies during extraction. Three modes cover the spectrum. "EXTRACTED" lets the LLM discover the schema from the data, which works well for exploratory analysis where the developer doesn't know what's in the documents yet. "FREE" removes constraints entirely. Explicit schema definition locks things down with typed node properties (strings, integers, dates, floats, booleans), relationship types, and patterns specifying which relationships can connect which nodes.

The pipeline also builds a lexical graph alongside the knowledge graph. This tracks which document produced which chunks, links sequential chunks to each other, and ties extracted entities back to the specific chunks they came from. That lineage matters when debugging extraction quality or when retrieval needs surrounding context.

Entity resolution runs by default after extraction. The built-in resolver handles exact name matches across chunks. For abbreviations, misspellings, or alternate names, optional resolvers using spaCy for semantic similarity or RapidFuzz for fuzzy string matching step in, though they require additional dependencies.

#### The Pipeline Class Gives Full DAG Control

The Pipeline class provides a blank directed acyclic graph. The developer adds components individually and wires them together explicitly, controlling ordering, data flow, and which components to include.

The tradeoff is more upfront configuration for real flexibility. Swap in a LangChain text splitter. Skip entity resolution entirely. Add a custom validation step between extraction and writing. Route different document types through different processing paths. Each component gets instantiated individually, assigned a name, and connected to other components through an explicit mapping that defines how outputs flow into inputs. That explicit wiring is what makes custom workflows possible, since the developer decides exactly which components participate, in what order, and how data moves between them.

### Six Retrieval Strategies, Each With Different Strengths

Six retrieval strategies get information out of Neo4j and into an LLM's context window. Each makes a different tradeoff between precision, recall, and the types of questions it handles well, and the right choice depends on whether the question is conceptual, factual, or structural.

**VectorRetriever** runs similarity search against a Neo4j vector index. Standard "find chunks similar to my question" pattern. Works for conceptual questions where semantic proximity matters.

**VectorCypherRetriever** adds a graph traversal step after the vector match. Find the closest nodes, then run a custom Cypher query to pull in connected information. Vector search finds a chunk mentioning a specific person; the Cypher traversal grabs that person's relationships, affiliations, and associated events. A flat vector store returns the chunk. VectorCypherRetriever returns the chunk plus everything connected to it in the graph.

**HybridRetriever** combines vector similarity with fulltext keyword search, blended through a configurable alpha weight. Alpha closer to 1.0 favors vector results; closer to 0.0 favors keyword matches. Catches cases where pure semantic search misses exact terminology and pure keyword search misses conceptual similarity.

**HybridCypherRetriever** layers graph traversal on top of hybrid search, combining all three approaches in a single retrieval pass.

**Text2CypherRetriever** takes a different approach entirely. It uses an LLM to translate a natural language question into a Cypher query, runs that query against Neo4j, and returns the results. This handles precise, structured questions that vector search struggles with, things like "which companies did Alice work for between 2015 and 2020" where the answer requires filtering on specific properties and traversing specific relationship types. The retriever feeds the database schema to the LLM so the generated Cypher targets actual node labels and relationship types rather than hallucinated ones.

**ToolsRetriever** is a meta-retriever. It wraps other retrievers as tools with names and descriptions, then uses an LLM to decide which retriever to invoke for a given question. A factual question routes to Text2Cypher. A conceptual question routes to vector search. Any retriever can be converted into a tool with a single method call, which means ToolsRetriever can orchestrate complex retrieval strategies without custom routing logic.

For teams already running Pinecone, Weaviate, or Qdrant, dedicated external retrievers keep vectors in those stores while pulling entity metadata and graph context from Neo4j. Each system handles what it's best at, and data stays in one place.

### LLM and Embedder Support

Multiple LLM providers and embedders work out of the box, including OpenAI, Anthropic, Google Vertex AI, Cohere, Mistral AI, Ollama, and Azure OpenAI. Every provider includes built-in rate limit handling with configurable retry behavior and exponential backoff.

### Orchestration, Prompts, and Index Management

The GraphRAG class ties retrieval and generation together, running the full retrieve-augment-generate loop with any retriever, any LLM, and a customizable prompt template. It supports multi-turn conversation through message history, stored in memory or persisted to Neo4j for applications that need conversation continuity across sessions.

Helper functions handle Neo4j vector and fulltext index creation and management. Every LLM interaction in the library, from entity extraction to Cypher generation to final answer synthesis, uses a prompt template that can be replaced for domain-specific tuning. Modular installation via optional dependency groups keeps the base install light and avoids version conflicts across AI library dependencies.

The library is open source and under active development. For teams already running Neo4j, it turns a knowledge graph from a retrieval experiment into a production pipeline without stitching together five different libraries to get there.

---

## [Agent-Memory](https://github.com/neo4j-labs/agent-memory/): A Three-Layer Memory Architecture for AI Agents

**Built on Neo4j | Neo4j Labs Project**

### The Problem With Treating All Memory as One Thing

Most agent memory systems store everything in a single knowledge graph of entities and facts. That works for basic recall. But agents operate across multiple types of memory simultaneously, and those types have different retrieval characteristics. An agent tracking a conversation needs different recall than an agent looking up a known entity, and both differ from an agent trying to remember how it solved a similar problem last week. Flattening three fundamentally different types of recall into one structure forces tradeoffs that show up as missing capabilities downstream.

### Three Connected Memory Layers in One Graph

Agent-Memory organizes agent memory into three distinct layers, all stored in a single Neo4j graph and connected through native graph relationships.

**Short-term memory** captures conversation history. Every message goes in as a node, linked into a session chain with an embedding attached for semantic search. When an agent needs to recall what was discussed three messages ago, it traverses the chain directly rather than searching through episode records. The conversation stays intact as a sequence, not scattered across disconnected nodes.

**Long-term memory** captures distilled knowledge. When a message like "I met Alice at Google in Berlin" enters short-term memory, the extraction pipeline classifies Alice as a Person, Google as an Organization, and Berlin as a Location. Each entity gets resolution against known duplicates, type-appropriate enrichment, and EXTRACTED_FROM relationships back to the original message for provenance. The raw conversation feeds the structured graph automatically.

**Reasoning memory** captures decision-making. Every time an agent works on a task, a ReasoningTrace opens, recording each step, tool call, and result with duration and success/failure status. The trace links back to the message that triggered it, connecting behavior to the conversation that prompted it. Agents accumulate operational history, not just factual knowledge.

Because all three layers share the same graph, the connections between them are real graph relationships rather than foreign keys across separate databases. A single Cypher query can traverse from a reasoning trace to the message that triggered it, to the entities mentioned in that conversation, to other messages referencing those same entities. That kind of traversal is what a native graph architecture makes possible without stitching together results from multiple stores.

### POLE+O Gives Every Entity a Type the Whole System Honors

Agent-Memory classifies every entity using the POLE+O data model: Person, Object, Location, Event, and Organization. This taxonomy originated in law enforcement and intelligence analysis, where organizing real-world information by entity type proved more reliable than ad-hoc categorization. Each category carries subtypes. A Person can be an Individual, Alias, or Persona. An Object can be a Vehicle, Phone, Email, or Document. A Location can be a City, Country, Address, or Landmark.

POLE+O goes beyond typical entity labeling to establish a contract that every component in the system honors. The extraction pipeline applies domain schemas built around these categories. The resolution engine uses different matching strategies by type, including name-based fuzzy matching for Persons, address matching for Locations, and identifier matching for Objects. The enrichment service geocodes Location entities with real-world coordinates while looking up Person and Organization entities in Wikipedia and Diffbot. The search layer filters Location entities geospatially while applying semantic or metadata filters to other types. Even the graph schema participates, using POLE+O types as additional Neo4j node labels so Cypher queries can target specific entity categories efficiently.

### Cost-Efficient Extraction Without Constant LLM Calls

Agent-Memory's extraction pipeline starts with spaCy, which runs locally for free and handles common entity types. GLiNER runs next, also locally, applying zero-shot extraction against eight pre-built domain schemas organized around POLE+O categories, covering podcast, news, scientific, business, medical, and legal domains. The LLM only fires as a fallback when the first two stages can't handle the input.

Each stage produces confidence scores, so downstream components know how reliable each extraction is. The majority of entity extraction happens without any LLM cost at all, which changes the economics of running memory extraction at production volumes.

### Entity Resolution That Preserves History

Extracting entities is half the problem. The other half is figuring out that "Alice Smith," "A. Smith," and "Alice" all refer to the same person. Agent-Memory runs four resolution strategies in sequence: exact matching, fuzzy matching with RapidFuzz, semantic matching using embeddings already computed for search (making deduplication essentially free), and a composite approach combining all three. Configurable thresholds auto-merge at 95% confidence and flag for human review at 85%. Merges create explicit SAME_AS relationships, preserving the full record of what was combined and why rather than overwriting one entity with another.

Enrichment builds on the POLE+O classification. Person and Organization entities get looked up in Wikipedia and Diffbot, adding descriptions, images, and structured data. Location entities get geocoded through Nominatim or Google Maps, enabling geospatial queries like "find all entities within 50 kilometers of this point." The knowledge graph grows richer over time in ways appropriate to each entity's nature, even without new conversations.

### Reasoning Traces Create a Learning Feedback Loop

Agent-Memory tracks both what an agent knows and how it reasons. Every time an agent works on a task, a ReasoningTrace opens. Each step the agent takes, whether thinking through a problem, calling a tool, or processing a result, gets recorded as a ReasoningStep within that trace. Tool calls are logged with their inputs, outputs, duration, and success or failure status.

The value surfaces when the agent encounters a similar problem later. Task descriptions get embedded, so semantic similarity search can retrieve past reasoning traces that worked for comparable tasks, even if the wording differs completely. An agent that previously figured out how to query a complex API can surface that successful trace when facing a similar integration challenge months later. The agent improves at tasks it has done before because its memory of successful approaches feeds directly into prompt context, independent of any model retraining.

### Native Neo4j Integration

Agent-Memory commits fully to Neo4j's feature set rather than targeting a lowest-common-denominator abstraction across multiple databases. Vector indexes handle semantic search across messages, entities, preferences, and reasoning tasks using Neo4j's built-in vector capabilities. Point indexes on Location entities support geospatial queries, like finding all entities within a specified radius of a coordinate.

The optional Graph Data Science library exposes algorithms like shortest path, node similarity, and community detection as agent tools through the Microsoft Agent Framework integration. These computations run as optimized graph algorithms rather than LLM inference, which matters when the analysis involves traversing thousands of nodes.

### Composable With Neo4j GraphRAG

Neo4j GraphRAG builds knowledge bases from documents: PDFs, technical documentation, structured data. Agent-Memory builds personal memory from interactions: conversations, entity extraction, preferences, reasoning traces. Both write to the same Neo4j database, and Agent-Memory's POLE+O model gives the combined graph a consistent entity classification spanning both sources.

A Person entity extracted from a PDF by Neo4j GraphRAG and a Person entity extracted from a conversation by Agent-Memory share the same type system, making it natural to link, resolve, and query across both. Over time, the agent's personal memory grows on top of the document-derived knowledge base. A single Cypher query can traverse from a document chunk to an extracted entity to a conversation where that entity was discussed to the reasoning trace of how the agent used that information.

### Built-In Observability and Framework Support

Agent-Memory includes OpenTelemetry tracing for extraction pipelines and Opik integration for monitoring LLM calls. Developers can trace how long each extraction stage takes, which extractor produced which entities, and where bottlenecks form as the system scales. When GLiNER starts taking longer than expected on certain document types, or when LLM fallback rates climb, the telemetry surfaces it.

Native integrations ship for six agent frameworks: LangChain, Pydantic AI, CrewAI, LlamaIndex, OpenAI Agents, and the Microsoft Agent Framework. These integrations automate the full memory lifecycle. All three layers get queried before execution, combined context gets injected into system instructions, and responses save to short-term memory afterward while optionally triggering entity extraction and reasoning trace recording in the background.

### Architectural Tradeoffs With Graphiti

Graphiti's bi-temporal design tracks both when a fact became true in the real world and when the graph recorded it. For applications where temporal reasoning is the primary concern, like tracking how a customer's preferences changed over six months or auditing when specific facts entered the system, that design carries real value. The approach is backed by peer-reviewed research (arXiv: 2501.13956) and handles point-in-time queries and automatic contradiction detection well.

That temporal depth comes with architectural tradeoffs. Graphiti operates as a single memory layer where all memory lives in one knowledge graph of entities and facts, without separation between conversation history, structured knowledge, and reasoning traces. Reconstructing prior conversations means searching through episode records rather than traversing a dedicated session chain.

Extraction cost scales linearly with usage since every episode requires LLM calls for both entity and relationship extraction, with no local extraction stage. Entities are loosely typed through ad-hoc Pydantic models rather than a shared taxonomy, which limits the system's ability to apply type-specific strategies across extraction, resolution, enrichment, and search.

Entities contain only what the LLM extracted, without geocoding, external knowledge base lookups, or mechanisms to grow records beyond their original extraction. Entity merges overwrite rather than preserving the history of what was combined. And reasoning traces, tool calls, and their outcomes go unrecorded, so agents can't retrieve past decision-making patterns.

Supporting four graph backends (Neo4j, FalkorDB, Kuzu, Neptune) gives Graphiti broader database compatibility, but limits it to features common across all four. That rules out vector indexes, geospatial queries via point indexes, and graph algorithms from the Neo4j Graph Data Science library.

### Side-by-Side Comparison

| Capability | Agent-Memory | Graphiti |
|---|---|---|
| Memory layers | 3 (short-term, long-term, reasoning) | 1 (knowledge graph) |
| Entity classification | POLE+O taxonomy with type-specific handling | Ad-hoc per deployment |
| Extraction cost | Mostly local (spaCy + GLiNER); LLM as fallback | LLM required for every extraction |
| Entity resolution | 4 strategies; non-destructive with SAME_AS | 3 strategies; destructive merge |
| Automatic enrichment | Type-specific (geocoding, Wikipedia, Diffbot) | None |
| Reasoning/tool tracking | Full traces with semantic search | Not supported |
| Geospatial queries | Native via Neo4j point indexes | Not supported |
| Graph algorithms | Via Graph Data Science library | Not available |
| Temporal tracking | Optional fields | Bi-temporal (stronger) |
| Database backends | Neo4j (deep integration) | Neo4j, FalkorDB, Kuzu, Neptune |
| Framework integrations | 6 (LangChain, Pydantic AI, CrewAI, LlamaIndex, OpenAI Agents, Microsoft Agent Framework) | LangChain, OpenAI Agents |

*Agent-Memory is a Neo4j Labs project under active development.*

---

For a hands-on guide to building GraphRAG on Databricks using these libraries, see [The Developer's Guide to GraphRAG on Databricks](DevelopersGuideGraphRAG-Databricks.md).
