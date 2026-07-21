# supplier-risk-graph — CLAUDE.md

## The two MCP servers are one domain, joined on id

This demo is served by two MCP servers over the same supplier and customer data. Treat them as two
views of one dataset, not two datasets.

- **`genie-supplier-risk`** is the lakehouse view. It answers over the Unity Catalog `supplier_risk`
  schema in natural language and returns rows, counts, totals, and rankings. Authoritative for
  amounts, dates, aggregates, and the `customer_risk_exposure` metric view. Tables: `customers`,
  `suppliers`, `invoices`, `business_units`, `revenue_entries`, `compliance_findings`, the bridge
  tables `supplier_business_units`, `supply_relationships`, `owned_by`, and the
  `customer_risk_exposure` metric view.
- **`neo4j-agentcore`** is the graph view. It answers structural questions in Cypher: paths,
  ownership chains, supply chains, betweenness, PageRank, and the governed knowledge layer.
  Authoritative for relationships and for any authored business definition.

**The join key is the `id` string, shared by construction.** A lakehouse row and its graph node
carry the same `id`, so a value that names one names the other:

| Lakehouse (Genie)                         | Graph (Neo4j)                          | Join |
|-------------------------------------------|----------------------------------------|------|
| `customers.id`                            | `Customer.id`                          | equal string |
| `suppliers.id`                            | `Supplier.id`                          | equal string |
| `invoices.id` (`.customerId` → customer)  | `Invoice.id` (`(:Customer)-[:HAS_INVOICE]->`) | equal string |
| `business_units.id`                       | `BusinessUnit.id`                      | equal string |
| `revenue_entries.id`                      | `RevenueEntry.id`                      | equal string |
| `compliance_findings.id`                  | `ComplianceFinding.id`                 | equal string |
| `supplier_business_units` bridge          | `(:Supplier)-[:SUPPLIES]->(:BusinessUnit)` | endpoint ids |
| `supply_relationships` (`from`/`to`)      | `(:Supplier)-[:SUPPLIES]->(:Supplier)` | endpoint ids |
| `owned_by` (`customer_id`/`parent_customer_id`, `ownershipPct`) | `(:Customer)-[:OWNED_BY]->(:Customer)` `{ownershipPct}` | endpoint ids |

**Only the graph carries the knowledge layer.** The `Policy`, `Entity`, `BusinessRule`,
`BusinessTerm`, `Measure`, `Threshold`, `DataSource`, and `GraphMetric` nodes, wired by
`REALIZED_AS`, `DEFINED_BY`, `CLASSIFIED_AS`, and `MAPS_TO`, have no lakehouse equivalent. This is
the grounding the tables alone do not hold. A `DataSource` node even records the `system` and
`table` that each `Entity` maps back to, so the graph is where an authored definition points at the
lakehouse column that realizes it. This layer is the whole reason a graph is in the demo. See the
core-point section below.

**Routing rule.** Relationship, path, chain, centrality, or "who connects to whom" and any
definition-backed classification go to `neo4j-agentcore`. Totals, counts, rankings, amounts, and
metric-view measures go to `genie-supplier-risk`. For a cross-source answer, get the `id` set from
one server and look the rest up in the other on that key: graph for the structure, Genie for the
figures, stitched on `id`.

## Read this before proposing anything about the demo

Two files, and they are the whole reading list.

`proposals/CONTRACT.md` is the authority for Story 1. Read it before suggesting a change to the
demo's narrative, questions, beats, data topology, or knowledge layer.

`proposals/REBUILD.md` is the current work list: what is left to do, in the order it has to happen.
Read it before starting work. It gets deleted when the rebuild is done.

Where they disagree, the contract wins.

**`proposals/simplified-plan.md` and `worklog/` are reference, not required reading.** They hold the
history of how the demo reached its current shape, including the reasoning behind decisions that are
now settled. Go there when you need to know why something was decided, not to find out what to do.
Do not treat them as instructions and do not keep them in sync with the two files above: they are a
record of the past, so they are allowed to be stale.

## The core point, which is misread constantly

The demo is **ungrounded versus grounded**. It is NOT wrong versus right.

**The two engines are called Genie alone and Genie + Graph.** Those names replace Run A and Run B
everywhere in `DEMO.md` and `proposals/CONTRACT.md` as of 2026-07-19. `worklog/` and `REBUILD.md`
still use the old names and are not being rewritten. Contract section 3 holds the mapping.

Genie alone is a frontier LLM over tables. Ask it a business question and it returns a plausible
answer grounded in nothing but column names. The axis it picks is generative and not reproducible.
Genie + Graph returns an answer grounded in an authored definition, so it is the
same answer every time and a risk committee can act on it.

Genie alone's answers are plausible, defensible, and anchored to nothing. It **can** return an answer
that is false at full depth, and reporting that honestly is allowed: contract section 1 supersedes
the earlier absolute that it is never wrong. The line that survives is that an emerged wrong answer
is a finding and an engineered one is a plant. Never frame a beat as Genie being wrong, bad, or
beaten. Narrate the mechanism, that Genie looks one level deep by default and could likely be
prompted deeper, and never the verdict.

## The rule that this project keeps violating

**Do not predict what Genie will answer, and do not engineer data so a predicted answer is wrong.**

Genie alone is stochastic. Every previous version of this demo tried to pin down its answer and
build the story on top of that prediction. Each one got relitigated when the prediction turned out
to be untested or wrong. That is the single largest source of wasted work in this project's history.

Two claims, different strength, and they must stay separate:

- **Load-bearing, cannot fail:** no answer from Genie alone cites a governed business definition, because none
  exists in the lakehouse. True by construction, every run.
- **Vivid, not guaranteed:** the answers Genie alone gives vary across runs. Show it, never depend on it.

Never build a beat on the second alone.

## Consequences for anything you propose

- No beat contains a scripted answer for Genie alone. If you find yourself writing "Genie will say X," stop.
- Ambiguity in a demo question is usually the demonstration, not a bug. Do not "fix" a question to
  force the intended axis without checking the contract first.
- If a beat only works because of a data plant, change the beat. See the banned list in the
  contract, section 8. Every item on it was a real failure, not a hypothetical.
- Investigation comes before code. Probe first, write the script from transcripts, never from
  expectations. See `worklog/probe-run-a.md` for the format.
- Story 2 is out of scope for the current work. Do not touch it.

## Writing style for all docs in this project

No em-dashes. Use commas, colons, or restructure. Plain declarative prose, no emoji. Do not quote
counts, scores, or totals in prose: the numbers belong on screen at demo time, calculated live.

**Never cite line numbers.** Reference functions, named blocks, and dict keys instead:
`make_supply_relationships` in the generator, the `supply_relationships` entry in `upload.py`'s
SEMANTICS dict, `assert_betweenness` in `gds.py`. Line numbers in the worklog went stale within a
day and sent a reader to the wrong place.

**No demo artifact contains a value that a reseed would change.** The generator is RNG-driven and
Genie alone is stochastic. See the reseed-invariance section in `proposals/CONTRACT.md`. Enforcement
is editorial: re-read what you changed before committing.
