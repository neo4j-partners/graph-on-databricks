# Is this an ontology, and is this a true knowledge graph?

This note answers three questions about the domain definitions in this project: whether they form a
domain dictionary, whether that dictionary is a formal ontology, and whether the result is a true
knowledge graph with a defined schema. It answers the question twice: once for the case where the
definitions live in `supplier-risk-ontology.ttl`, `supplier-risk-r2rml.ttl`, and
`supplier-risk-shapes.ttl`, and once for the case where the same definitions live directly in the
graph as `BusinessTerm`, `BusinessRule`, `Policy`, `Measure`, `Threshold`, and `DataSource` nodes, the
pattern this project's own `CLAUDE.md` describes for the knowledge layer.

Reference material: `/Users/ryanknight/projects/cloud-integration/knowledge-layer/reference/dictionary.md`,
`modeling-ontology-schema-faqs.md`, and `knowledge-layer-official.md` in the same directory, plus
Jesus Barrasa's public post, ["The knowledge layer for enterprise AI"](https://neo4j.com/blog/agentic-ai/enterprise-knowledge-layer),
which the internal reference material is built on and which governs wherever the two could be read as
disagreeing.

## 1. Is there a domain dictionary here?

Yes. `dictionary.md` defines the domain (business) ontology as the Conceptual Map: what kinds of
things exist in a domain, what each term means, and how concepts relate. `supplier-risk-ontology.ttl`
does exactly this. It defines Customer, Supplier, and BusinessUnit as base entities, then layers
classified business terms on top: `HighRiskSupplier`, `DefaultedCustomer`, `DelinquentCustomer`,
`CriticalSupplier`, `OwnershipRisk`, and `RiskyCustomer`. Each carries a comment stating the rule and
threshold that govern it. That is the Conceptual Map, stated formally.

This holds regardless of which storage form is used. A `BusinessTerm` node connected by `DEFINED_BY`
to the rule that governs it carries the same content: a business dictionary and a relationship map.
Storage format does not decide whether a domain dictionary exists.

## 2. Is it a formal ontology?

### With the ttl files

Yes, in the literal sense, not the loose sense. The file is serialized as OWL 2 and uses real
description-logic constructs, not just labels: cardinality restrictions through `owl:Restriction`,
disjointness axioms such as `OwnershipRisk owl:disjointWith DefaultedCustomer`, transitive properties
and property chains for `supplies` and `ownedBy`, and two SWRL rules a reasoner can execute directly,
`RuleHighRiskSupplier` and `RuleDefaultedCustomer`. This satisfies the engineering definition in
`modeling-ontology-schema-faqs.md`: a formal description of concepts and their semantics in a domain,
independent of how data is stored or implemented.

Two qualifications follow directly from the file's own content.

The file is not a pure Conceptual Map. Every class carries an `ontobricks:dataset` annotation binding
it to a specific Unity Catalog table, for example `main.supplier_risk.customers`. That is system-aware
information, which is Semantic Map content, not pure meaning. `dictionary.md`'s section on where the
ontology boundary falls addresses this directly: Neo4j's published position places these mappings
inside the broader five-part Knowledge Layer ontology. The file is doing double duty as Conceptual
Map and technical sub-ontology. It is not staying at the pure meaning layer alone.

Three of the seven classified terms have no computable definition. `CriticalSupplier`, `OwnershipRisk`,
and `RiskyCustomer` are declared as classes with their governing rule written in a comment, but the
file states plainly that betweenness, weighted PageRank, and kNN are not expressible in SWRL. Those
three terms are asserted by an external reasoning or graph data science step, not derived by a
reasoner from the ontology's own axioms. The ontology declares these terms in full. It computes only
two of the seven.

### Without the ttl files

Still yes, but only on the condition that the definitions stay explicit and governed. It is not yes
because Neo4j's schema optionality lets meaning emerge informally from labels. That distinction needs
its own check against Barrasa's public post, because the internal FAQ and the post pull in different
directions here.

`modeling-ontology-schema-faqs.md` states that Neo4j does not force a full separation of meaning,
structure, and implementation the way relational systems do, and that in practice, ontology, logical
model, and schema collapse toward each other in Neo4j. Barrasa's post backs the integration half of
that claim. It describes the Knowledge Layer ontology as one connected structure holding meaning,
constraints, and system mappings together, not three separate documents, and it justifies using a
graph at all on exactly this basis: what it encodes is naturally connected, concepts related to
concepts, mapped to systems, wrapped in policy. On that point, a graph-native `BusinessTerm` node
sitting next to the `DataSource` node it maps to is the pattern the post describes.

The same FAQ also says ontologies are entirely optional in Neo4j, and that schemas have always been
optional, so the model and its semantics emerge from the data. Barrasa's post does not say this, and
argues close to the opposite. Its whole case rests on the failure mode of an AI system reasoning over
raw tables or a raw graph with no explicit, governed definition behind it: answers that are plausible
but cannot be checked. That is this project's own load-bearing point, stated in
`supplier-risk-graph/CLAUDE.md`: Genie alone is ungrounded because no formal business definition exists
behind it in the lakehouse. Reading "collapse toward each other" as license to skip formal definition,
so a `BusinessTerm` node's meaning is just whatever a label name implies, runs against that argument.
Reading it as license to keep the formal definition and its data in one graph instead of three
separate files does not.

So a `BusinessTerm` node is a legitimate ontology entry by the business definition in `dictionary.md`,
a company's master dictionary and relationship map, on the condition that the node is an explicit,
named, governed construct connected by `DEFINED_BY` to the rule it encodes. That condition is doing
the real work. The storage location is not what makes it formal or not.

What still changes, even when the definition is explicit, is the formal engineering claim about
independence from storage. A ttl file sitting outside the graph satisfies that by construction, since
it is a portable artifact usable by any RDF tool. A `BusinessRule` node living in the same database as
the data it governs cannot make that claim. Its meaning and its storage are the same layer. That is
the exact distinction `modeling-ontology-schema-faqs.md` draws between Ontology and Logical Data
Model, and Neo4j's own answer is that these two rungs collapse into one inside a property graph,
provided what lands in that one layer is still explicit and governed rather than emergent.

Two concrete capabilities are lost regardless, not just a label.

Automatic reasoning is lost. The OWL file's disjointness axioms and SWRL rules are checkable by a
generic reasoner without writing new code: hand it the ontology and the instance data, and it reports
whether `OwnershipRisk` and `DefaultedCustomer` ever overlap. A `BusinessRule` node's constraint holds
only if someone writes and runs a Cypher query that checks it. Nothing stops a graph-native
`BusinessRule` node from drifting out of sync with the data it claims to govern.

Standard, tool-independent serialization is lost. An OWL file is portable to any RDF tool, a
reasoner, a SHACL validator, or another team's triplestore. A `BusinessTerm` node's meaning exists
only insofar as this graph's own Cypher queries interpret it correctly.

## 3. Is this a true knowledge graph with a defined schema?

`dictionary.md` gives a specific formula: a Knowledge Graph is a Graph plus an Ontology plus a
Semantic Mapping.

### With the ttl files

All three parts exist as separate, real artifacts. The ontology is `supplier-risk-ontology.ttl`. The
Semantic Mapping is `supplier-risk-r2rml.ttl`, a W3C R2RML mapping from nine Unity Catalog tables to
the ontology's classes and properties, written with explicit column lists rather than `SELECT *` so
every mapped column is traceable. The graph is the instance data materialized through that mapping. A
fourth file, `supplier-risk-shapes.ttl`, adds SHACL shapes: cardinality, pattern, and range constraints
checked against the materialized triples. That is closer to the FAQ's Schema or Graph Type rung,
physical and enforceable, than to the Ontology rung, which is about meaning.

One caveat on the schema question specifically. `modeling-ontology-schema-faqs.md` notes that Neo4j
schemas are optional and emergent by design: the model and its semantics emerge from the data rather
than the reverse. These four files target the classic RDF and OWL stack, which does separate meaning,
mapping, and validation the way this question asks about. Whether the same rigor exists as a native
Neo4j constraint schema in the graph engine this project actually queries is a separate question these
files do not answer on their own.

### Without the ttl files

The formula still holds structurally. The graph is the Neo4j graph itself. The ontology is the
`BusinessTerm`, `BusinessRule`, `Policy`, `Measure`, and `Threshold` subgraph. The Semantic Mapping is
the `DataSource` nodes connected by `MAPS_TO`, recording the system and table each entity maps back
to, the same role R2RML plays, expressed as graph data instead of RDF triples. By the dictionary's own
formula, this still qualifies as a knowledge graph.

The schema answer weakens here, and this is where dropping the ttl files matters most. Without SHACL
shapes or OWL restrictions, whatever cardinality or type constraints exist are either genuine Neo4j
constraints, if explicitly declared, or prose on a `BusinessRule` node. `modeling-ontology-schema-faqs.md`
states this limitation about Neo4j models directly: models are informative rather than normative, and
Neo4j's schemaless design permits graph elements that are undefined in the model. The schema exists as
an assertion inside the graph. Nothing enforces it the way an OWL restriction or a SHACL shape does.
The honest answer moves from "yes, formally, with axioms a reasoner can check" to "yes, it is declared
and queryable, but it is a convention the graph is trusted to follow, not a constraint the database
enforces."

## Summary

| Question | With the ttl files | Without them, graph-native only |
|---|---|---|
| Is there a domain dictionary? | Yes | Yes |
| Is it a formal ontology? | Yes, with real OWL axioms. Three of seven classified terms are declared but not reasoner-computable. | Yes, only if the definitions stay explicit and governed, not because Neo4j lets meaning emerge informally. Still loses automatic reasoning and standard serialization, and collapses ontology into the same storage layer as the data. |
| Is it a true knowledge graph with a defined schema? | Yes. Graph, Ontology, and Semantic Mapping each exist as separate artifacts, plus SHACL for enforceable validation. | Structurally yes, the same three parts exist as graph data. The schema is declared and queryable but not engine-enforced. |
