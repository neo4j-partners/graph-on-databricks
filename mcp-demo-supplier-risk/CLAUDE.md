# mcp-demo-supplier-risk — CLAUDE.md

## The point of the demo

The point is to demonstrate that a frontier LLM, given just the two MCP servers and minimal
prompting, can introspect both schemas itself and discover that the graph's ontology layer is what
turns a plausible-sounding answer into a grounded one.

## What this directory is for

This directory exists to demo the two MCP servers defined in `.mcp.json`: `genie-supplier-risk`
(a Genie space over the Unity Catalog `supplier_risk` schema) and `neo4j-agentcore` (a Neo4j graph
reachable through an AgentCore gateway). The demo's point is showing what Genie plus a lakehouse
can do, and what an MCP server plus a graph can do, where the graph supplies the ontology the
lakehouse alone doesn't carry. Work here stays scoped to this directory and these two servers —
don't pull in sibling projects under `graph-on-databricks/` or their docs/conventions.

## Let each server do its own job

`genie-supplier-risk` is a Genie space: it takes a natural-language question and writes its own
SQL against the lakehouse. Ask it the actual question in plain language and let it translate and
run the query itself — don't pre-write the SQL logic, don't hand it column-by-column instructions,
don't spoon-feed it the answer shape. That translation step is the thing being demoed.

`neo4j-agentcore` exposes a schema-inspection tool. Use that to discover node labels, properties,
and relationships live rather than relying on a schema written down here, since the graph can
change and the tool is always current.

## Crossing between the two

The lakehouse and the graph share data by construction: a row's `id` in the lakehouse and its
node's `id` in the graph are the same string. When a question needs both — structure from the
graph, figures from the lakehouse, or vice versa — get the `id` set from one server and look the
rest up in the other on that key.

## Act like an analyst, not a report generator

Treat the first coherent answer as a draft, not a conclusion. Before reporting a number or a
judgment word like "diversified," "critical," or "high-risk," check whether the graph already has
an authored answer to that judgment sitting in its own data — a term, rule, or threshold — rather
than eyeballing a raw property and asserting the label. This graph encodes those calls as data the
same way it encodes what counts as "delinquent."

Likewise, don't treat a relationship as fully explored just because the first hop resolved into
something interesting. If there's reason to think the same relationship keeps going, one more
question — does this go deeper, and does the answer change if it does — is often where the real
finding is.

This is deliberately not a checklist of what to look up or in what order. The point of the demo is
that a frontier LLM finds this on its own with minimal prompting; a recipe here would defeat that.
