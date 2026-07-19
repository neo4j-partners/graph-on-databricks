# Demo walkthrough

The speaker's script for the two-story demo. One-time setup (data generation, Neo4j load, GDS,
Unity Catalog upload, and the Genie space) is covered in the setup section at the end.

**Before every demo:** regenerate the data and rerun the pipeline. The dataset is a forward-looking
snapshot from its generation date, and Story 2 depends on the invoices reading as open and on time.
Regenerating keeps `SEED = 42` and refreshes only the as-of date, so names, ids, topology, and every
rank stay identical. Never edit `SEED`: that is a reseed, not a refresh, and it moves the ranks the
demo rests on.

## What the demo proves

Two engines answer the same question over the same data.

- **Genie alone:** a Databricks Genie space scoped to the `supplier_risk` schema. It reads the raw
  instance tables and the `customer_risk_exposure` metric view, nothing else.
- **Genie + Graph:** that same space under a supervisor that can also call a read-only Neo4j
  knowledge graph.

Say those two names on stage. The contrast is in the name itself, so the room follows it without
being told.

Each story puts one natural question to both engines:

- **Ungrounded:** Genie alone reads every column correctly and returns a plausible, defensible answer
  anchored to nothing, because no lakehouse artifact defines the question's terms.
- **Grounded:** Genie + Graph resolves the governed definition from the graph, walks the connections,
  and returns an answer a risk committee can act on because it cites an authored definition.

Beats are numbered one to five and are the only numbered sequence. Everything else is named: the two
engines above, and the three steps of Beat 3, which are Definition, Discovery, and Explanation.

## The honesty framing

**The demo is ungrounded versus grounded. It is not wrong versus right.** Genie alone is a frontier
LLM over tables; the axis it picks is generative, not reproducible. Genie + Graph's answer is
grounded in an authored definition, so it is the same answer every time.

Genie alone **can** return an answer that is false at full depth, and that is a legitimate finding.
Narrate the mechanism, never the verdict: Genie looks one level deep by default. It could likely be
prompted deeper, and saying so costs nothing, because default behavior is what an analyst gets. Never
frame a beat as Genie being wrong, bad, or beaten. The room should leave thinking about depth of
question, not about which vendor lost.

Two claims, different strength, kept separate on stage:

- **Load-bearing, cannot fail:** no answer from Genie alone cites a governed business definition,
  because none exists in the lakehouse. True on every run.
- **Vivid, not guaranteed:** Genie alone's answers vary across runs. Show it live, never depend on it.

**Do not predict what Genie will answer, in this file or on stage.** No beat carries a scripted answer
for Genie alone.

Never claim SQL cannot express these traversals; a Databricks audience knows recursive CTEs exist.
The defensible claims are narrower and true:

- No lakehouse column defines what "single point of failure" or "same ownership group" means. The
  definition lives in the graph.
- Supplier betweenness and weighted ownership PageRank are graph computations no column carries. Both
  are expressible in SQL, but no BI tool writes them unprompted, and their cutoffs are governed values
  in the graph.

## The five-beat arc

Both stories run the same five beats, so the room learns the rhythm on Story 1 and feels it confirm
on Story 2:

1. **The ask:** one natural question, put to both engines.
2. **Ungrounded:** Genie alone answers from the columns, correctly, with nothing governing what the
   answer means.
3. **Grounded:** Genie + Graph resolves the definition, applies it, and explains the structure behind
   the result.
4. **The exposure:** the grounded finding gets a euro figure, computed from the same lakehouse data.
5. **The fix:** the action the finding points to, shown on screen rather than handed to the room as a
   choice.

Nothing is pasted. Both engines write their own queries; the presenter types a question. Graph
properties and instance tables both use camelCase.

## Story 1: the hidden glassworks

Supplier concentration risk hiding in the sub-tier. One business unit's tier-1 bottle suppliers are
separately qualified and separately contracted, so its supply base looks diversified. All of them buy
their glass, through a sub-tier of glass processors, from the same furnace. If that furnace stops,
that unit cannot bottle its product. The other units draw their glass from independent furnaces and
keep shipping. Procurement knows its tier-1 suppliers. It does not know who they buy from.

```text
 tier              the Americas chain                 the other units' chains

 feedstock         vendors across several regions     their own vendors
                   (cullet, sand, soda ash)
                            |                                  |
 raw glass         Cascade Glassworks                   independent furnaces
                            |                                  |
 processing        glass processors                     glass processors
                   (container glass)
                            |                                  |
 tier 1            bottle makers, separately            bottle makers
                   qualified, all clean scores                 |
                            |                                  |
 business unit     Americas                             the other business units

 each column reads downward as "supplies". Cascade sells to no business unit
 directly, and sits one tier back from the bottle makers rather than beside them.

 BI sees:    separately contracted bottle suppliers, a supply base that looks diversified
 Graph sees: every commodity-carrying glass path into the Americas crosses one furnace,
             while the other units' glass arrives through furnaces that do not
```

Cascade is not a cut vertex: the background network has inter-cluster bridges carrying freight,
equipment, and ingredients but never glass, so removing Cascade leaves the network in one component.
Cascade earns its position by spanning the feedstock and processor tiers, not by being the only way
across the graph.

### Beat 1, the ask

Asked verbatim, of both engines:

> "How diversified is our glass bottle supply for the Americas?"

- **The ambiguity is the demonstration, not a bug to fix.** "Diversified" can mean units per supplier
  or sources per unit. Nothing in the lakehouse says which axis is correct. Do not reword the question
  to force the intended axis.
- **Avoid "depend on" and "common upstream" here.** They hand Genie alone the convergence query
  directly. "Point of failure" is safe.

### Beat 2, ungrounded

Genie alone, no script.

- **Ask it three times, live, in fresh conversations.** Two asks can land on the same axis and show no
  spread.
- **Read out what comes back and note that nothing references a governed definition.** That is the
  load-bearing observation and it holds on every run.
- **If the three answers differ, narrate the spread. If they agree, narrate the ungroundedness.** Both
  land. Do not ask a fourth to manufacture a disagreement.
- **Every table is in the space,** including `supply_relationships` and `supplier_business_units`. The
  gap is grounding, not access.

### Beat 3, grounded

Genie + Graph, three steps in order, each with its own visible output.

- **Definition.** It resolves what a Critical Supplier means from the graph: a supplier that a
  disproportionate share of the multi-tier supply paths carrying a commodity into a business unit run
  through, leaving few alternatives around it, and one that need not sell to that unit directly. The
  Supply Concentration Threshold parameterizes it. The lakehouse has no answer to that question at all.
- **Discovery.** It reads the precomputed supply betweenness and applies the governed threshold, which
  returns a cohort of suppliers rather than a single name.
- **Explanation.** It walks the commodity-carrying glass chain and shows that the Americas
  container-glass processors all draw their raw glass from one upstream furnace, Cascade Glassworks.

The result: Cascade clears the Supply Concentration Threshold, and so do other suppliers, because the
threshold catches a cohort. What singles Cascade out is the definition and the commodity scoping
applied together. **The finding does not come from topping a ranking, so do not describe it as one.**
Cascade's own risk score sits below the High-Risk threshold, so no risk-score filter surfaces it.

- **Ask for the governed term by name.** Say "Critical Supplier" rather than describing the idea in
  loose business language. It is a term in the ontology with an authored definition, a rule, and a
  threshold. Genie alone cannot answer at all, because no column of that name exists on its side.
  Describing the term instead routes the request to whichever governed term sounds closest, usually
  High-Risk Supplier, which answers a different question.
- **Carry the criticality side by side.** Also ask both engines: "What is our single biggest point of
  failure in our supply base?" Safe to ask, because no beat depends on Genie alone answering any
  particular way. Ask it live and script neither side.

### The convergence caveat

Convergence is cheap in SQL once you know where to start. "Which supplier feeds all of these" is a
short query against the tier-1 bottle makers, well within Genie alone. The graph-native step is the
one before it: knowing which suppliers to ask about at all.

Invite that question rather than hoping nobody asks it. The frozen phrasing is "do all our Americas
glass bottle suppliers share a common upstream supplier?" With a processor tier between Cascade and
the bottle makers, one hop up lands on the processors, not the furnace, so the convergence query Genie
alone writes answers about the tier it can see. The graph, walking the commodity-carrying chain to
full depth, answers about the tier below. Narrate the mechanism: Genie looks one level deep by default
and could likely be prompted deeper.

The beat works whichever way Genie alone answers. If it converges on the furnace on the day, nothing
breaks: the graph still resolved the definition, the commodity scoping, and the tier that made the
finding actionable.

### Beat 4, the exposure

Asked of Genie + Graph:

> "What is our business exposure to Cascade Glassworks?"

Genie alone cannot answer it, because no lakehouse column connects Cascade to a business unit's
revenue.

- **What Beat 3 handed over:** an entity, Cascade Glassworks, not a number. The graph holds no euros.
- **How Genie + Graph gets to a number:** it follows `MEASURED_BY` from the Critical Supplier term to
  the Supply Exposure measure, reads the Supply Exposure Rule, and lands on the `RevenueEntry` and
  `BusinessUnit` tables. That turns "exposure to Cascade" into a revenue question about one unit.
- **What the measure says:** the recognized revenue that stops when a Critical Supplier stops, for the
  most recent full quarter, for every business unit whose supply of the commodity at risk runs wholly
  through that supplier. A path that does not carry the commodity is excluded. The measure returns one
  unit and no other.
- **The arithmetic, sent to Genie:** recognized revenue per business unit for the most recent full
  quarter, so the exposed unit's figure sits next to the units that keep shipping. Read it off the
  screen.
- **Why the revenue stops, not just dips:** you cannot ship a bottled product without bottles. If the
  furnace stops, that unit's revenue stops rather than degrades, while the other units keep shipping.
  The comparison across units is the argument; a single number is not.
- **The kicker, presenter framing:** what you pay Cascade is a rounding error. The exposure is the
  revenue that stops when they do. The dataset carries no supplier-spend column, so this line is said,
  not queried.
- **Why this is the honesty beat:** the lakehouse had the money the whole time. What it lacked was a
  reason to ask about this unit, because no column says whose glass supply runs wholly through one
  furnace. The graph supplies the entity and the governed measure; Genie supplies the arithmetic.

### Beat 5, the fix

The fix is a second glass source for the exposed unit, and Genie + Graph can show whether a given
candidate actually is one. Ask it to walk the candidate's chain: a supplier drawing raw glass from an
independent furnace breaks the dependency, and one that routes back to Cascade does not.

**A second supplier whose own glass also traces back to Cascade changes nothing,** because the
commodity-carrying paths still converge on the same furnace. Sourcing decisions made on the tier-1
view cannot tell the two cases apart; the governed definition can. The cost of a second source is
presenter framing, not a data answer.

### Graph mechanics

- **The traversal:** a variable-length traversal walks the multi-tier chain. `SUPPLIES` points from a
  supplier toward what it feeds:
  `(Cascade)-[:SUPPLIES]->(processor)-[:SUPPLIES]->(bottle maker)-[:SUPPLIES]->(Americas)`. Cascade
  never appears one hop from a business unit.
- **The commodity test:** a path counts only when every supplier on it trades in a glass subcategory.
  Without it, the non-glass bridges would leak the exposure measure into units that are not exposed.
- **The GDS piece:** supplier betweenness, a graph score for how often a node sits on the paths between
  others, precomputed as a node property over an undirected projection of the supplier network.
- **The cutoff:** the Supply Concentration Threshold is a hand-set percentile of supply betweenness,
  fixed before the run. Cascade clears it and the clearing cohort has more than one member. That is
  cohort membership, not rank.

## Story 2: the clean payer in a bad group

Group credit exposure hiding in the ownership structure. A customer pays every bill on time and is
assessed standalone, the way credit control assesses every account. Nothing near it looks alarming.
But the group that controls it also controls four companies that went bankrupt, two levels further
down, and it holds all of them outright. A lender would call these a group of connected clients and
aggregate the exposure. The account-level rating cannot.

```text
                     Kestrel Holdings
              85%          70%         65%
               /            |            \
    Jade Beverage    Harbour Group    Tern Capital
     Distribution       Holdings         Partners
  (spotless record)    90%    80%     85%     75%
                        /      \       /       \
                   Marlin    Osprey Pelican   Heron
                  DEFAULTED       DEFAULTED
                              (all four)

 BI sees:    an on-time payer, nothing within two hops to flag
 Graph sees: four failures arriving through controlling stakes
```

Nothing is one hop away, which is the point. Clean accounts sit directly next to defaults across the
book, but they hold only a few percent of the company that failed. Jade holds nothing directly and is
owned 85% by a group that owns its failures outright, so far more damage reaches Jade than reaches
anyone standing closer.

### Pipes, not distance

If you explain one thing in Story 2, explain this. It is the whole reason the graph is required.

The instinct everyone has is that risk is about **distance**: who is standing closest to the fire.
That instinct is what SQL is good at, and it is wrong here.

Ownership is not a distance, it is a **pipe**. Owning 90% of a company is a wide pipe, and almost
everything that happens to it flows through to you. Owning 3% is a straw. So the question is not "how
close are you to a failure" but "how many pipes lead from failures to you, and how wide is each one."

- Accounts standing right next to a bankruptcy hold only a few percent of it. Straws. Almost nothing
  arrives.
- Jade is three levels from four bankruptcies, but every pipe on the path is 65% to 90% wide. Four
  failures arrive largely intact.

Distance says Jade is fine. Pipes say Jade is the most exposed trading account on the book. Adding up
flow through a web of pipes, where damage arrives by several routes at once, is what the graph
algorithm does in one line and what a join cannot express.

### Beat 1, the ask

Put to both engines:

> "Which customers should credit review look at next?"

### Beat 2, the miss

- **What it does:** goes to the `customer_risk_exposure` metric view, ranks customers by
  `credit_utilization` and `overdue_amount`, and takes the top ten. A clean, sensible query.
- **What it does not do:** `avgDaysLate` and `churnRisk` never enter the query. It reads the exposure
  measures correctly and has no reason to reach past them.
- **Who is missing:** Jade Beverage Distribution.
- **Why:** every column it reads is clean. Jade carries no overdue balance, so `overdue_amount` is
  zero, and it draws a modest share of a large committed facility, so `credit_utilization` sits nowhere
  near the top. Widen the ranking to lateness or churn and Jade is still clean. A correct read of every
  column that misses the account credit review should worry about most.
- **If the room asks about the ownership table:** it is in the space, stakes and all. Ask which
  customers are near a default and the lakehouse still misses Jade, because the nearest accounts hold a
  few percent of it. Ask which ownership group holds the most defaults and it returns a different
  group, not Kestrel's. Both right, both the wrong account.

### Beat 3, the flag

- **The governed definition:** Genie + Graph resolves what Ownership Risk means from the graph: "an
  active customer with a clean record of its own, no default and never delinquent, that absorbs more
  failure through its ownership stakes than any other trading customer," parameterized by the Ownership
  Contagion Threshold, a weighted PageRank cutoff.
- **How it filters:** it excludes the defaulted customers and the invoice-less holding companies, then
  returns the clean operating customers whose stake-weighted propagated risk clears the cutoff, with
  the ownership chain as the stated reason.
- **The result:** Jade Beverage Distribution, a platinum account owned 85% by Kestrel Holdings, which
  owns Harbour Group and Tern Capital outright, and those two own the four companies that defaulted in
  the most recent quarter. Jade scores clearly ahead of the next trading customer, a gap wide enough
  that the cutoff sits between them with room to spare, even though Jade never missed a payment and
  nothing within two hops of it has failed.
- **Why nobody else clears it:** accounts sitting directly beside a default hold only a few percent of
  it. Kestrel's stakes are 65% to 90% at every level, so four failures arrive at Jade largely intact.
- **If someone asks why not Kestrel or Harbour:** they score higher and are correctly excluded. They
  are holding companies: they buy nothing and carry no invoices, so there is no receivable to act on
  and no facility to cut. The definition says "an active customer" for exactly this reason. The demo
  answers which trading account is most exposed, and that is Jade.

### Beat 4, the exposure

- **What Beat 3 handed over:** an entity, Jade Beverage Distribution, not a number.
- **How Genie + Graph gets to a number:** it follows `MEASURED_BY` from the Ownership Risk term to the
  Credit Exposure measure, reads the Credit Exposure Rule, and lands on the `Invoice` and `Customer`
  tables.
- **The follow-on question, put to Genie:**

> "What is Jade Beverage Distribution's committed credit facility, and how much of it is drawn as open
> invoice balance?"

- **The figure:** a committed facility, of which a smaller amount is drawn across the open invoices.
  Both come back from plain Genie over the instance tables. Read them off the screen. The exposure is
  the whole facility, not the drawn portion, because all of it is committed and can be drawn.
- **Why this is the honesty beat:** the credit line and the open invoices were in the lakehouse the
  whole time. Nothing in those columns flags Jade, because Jade's own record is spotless.
- **Why it lands:** Jade is also a Strategic Account, so the biggest clean customer on the book is the
  one absorbing the most failure in it.

### Beat 5, the fix

The fix is to cut Jade's committed facility down toward the balance already drawn, using the two
figures Beat 4 returned, and to require prepayment on new orders, so the enterprise stops carrying the
full committed exposure on the account absorbing more of the book's failure than any other.

### Graph mechanics

- **The algorithm:** weighted personalized PageRank, seeded on every defaulted customer and propagated
  over the `OWNED_BY` edges with `ownershipPct` as the relationship weight, precomputed as a node
  property on every Customer.
- **The flow:** failure flows out of every default in proportion to who holds it. Through Kestrel's 65%
  to 90% stakes it arrives at Jade nearly intact, three levels up and back down. Through a filler's
  few-percent stake it effectively stops.
- **Why the weight is the whole story:** unweighted, this collapses into a hop count and the nearest
  account wins, a query anyone can write. Weighted, the answer depends on the product of stakes along
  every route and the sum over all routes, which no join reproduces.
- **The cutoff:** the Ownership Contagion Threshold is set from the score distribution so Jade clears
  it and no other trading customer does.

## Why the arc works

- **The grounding gap is the proof.** The lakehouse-only engine reading every column correctly and
  still having nothing to anchor the answer to is the whole argument, demonstrated live, twice.
- **Beat 5 shows the fix.** Attaching a concrete action to the euro figure converts the contrast into
  something a risk officer acts on rather than an abstract point.
- **Genie + Graph's answers read like actions.** It composes its reason from the path itself and closes
  with the recommended action, something a risk officer acts on.

## The fairness rebuttal: both engines get every table

The room will ask whether plain Genie was denied the scores. The rebuttal is an answer, not a
demonstration.

- **Both engines get every table,** including the raw supply links and the ownership stakes. What plain
  Genie will not do is invent an all-pairs shortest-path computation or an iterative weighted
  propagation, unprompted, from a business question. Both are expressible in SQL; neither is what a BI
  tool reaches for; both are one line of GDS.
- **Do not say BI cannot compute these at all.** It can, and a Databricks audience knows it. The claim
  that holds is the one above.
- **If challenged, invite the shortcut.** Counting connections over `supply_relationships` does not
  name Cascade. Ranking customers by distance to a default, or by defaults per ownership group, does
  not return Jade. The shortcuts run, and they return a different name.
- **The scores are precomputed graph properties and never synced to Delta.** Writing them into a gold
  table would recreate the write-back leakage this demo removes. Do not run GDS on stage.

## Warm-up and other questions

- **Warm-up, if the room needs it:** ask both engines "Which suppliers are high-risk?" Genie alone has
  the `riskScore` column but no governed threshold, so it guesses a cutoff and can miscount. Genie +
  Graph reads the governed threshold off the rule and returns every supplier at or above it, consistent
  no matter who asks. This is the honest baseline: with a column and a governed number, BI can close
  most of the gap, and the two stories are exactly the cases where there is no such column.
- **Genie + Graph also answers questions that span definitions:** impact analysis ("if we lower the
  Late Payment Threshold to 45 days, which terms, rules, and tables change?"), policy scope ("which
  policies govern customer data?"), provenance ("show the full lineage behind Jade's Strategic Account
  label"), and a queryable glossary of every governed term, threshold, and rule.

## Pre-flight check

You do not need to verify figures. Every number comes back from Genie live. What you need is
confidence that the two stories still have their shape, because if one breaks the demo silently stops
making its point.

- **`make demo`** rebuilds everything. The generator asserts both story shapes, so a clean run with no
  `AssertionError` is the check.
- **`make expected`** prints the figures this build produced. Read it once as the answer key.
- **`make check`** validates the CSVs offline.

Three checks that run on every demo day, after everything else has passed:

- **`make guard`** runs the vocabulary guard against the live Genie space, which is hand-synced and can
  drift after a build. It protects the load-bearing claim, so it runs last.
- **Confirm today's quarter still matches the quarter the build was shaped around.** Read the "Last
  full quarter" row from `make expected`. A calendar quarter rolling between build and demo silently
  changes what "the most recent full quarter" means in Beat 4. The fix is a regenerate.
- **Re-probe the live questions after any model update or regenerate.** Genie's default reflex drifts
  with model updates even though the data does not move.

The two shapes the generator asserts:

- **Story 1.** One unit's glass suppliers all trace to Cascade through commodity-carrying paths and
  every other unit has at least one that does not; the commodity-scoped exposure measure returns that
  one unit; Cascade clears the Supply Concentration Threshold with a cohort of more than one member;
  Cascade is not the top-degree supplier; the network is one connected component. Cascade's betweenness
  rank is read from the output, never asserted.
- **Story 2.** Jade tops weighted PageRank among trading customers, far enough ahead that the cutoff
  sits between it and the field; Jade sits three hops from the nearest default while other clean
  accounts sit one hop away; another ownership group holds more defaults than Kestrel's.

### Four changes that quietly break the demo

All four look like harmless cleanups and all four destroy the answer rather than degrade it.

- **Do not drop the trading-customer filter.** GDS ranks only customers that carry invoices and are
  neither defaulted nor delinquent. The holding companies score higher than Jade, so removing the
  filter makes the answer a paperwork company with no receivable and no decision. The filter is the
  governed definition ("an active customer"), not a convenience.
- **Do not lower the PageRank iteration limit.** The ownership structure is deep and the stakes are
  lopsided, so the scores take many times the GDS default to settle. The convergence check fails the
  build loudly if this happens; leave it in place.
- **Do not "fix" the UNDIRECTED graph projections.** Both stories depend on erased edge direction. Jade
  is reached only by travelling up to the shared parent and back down, so a directed projection scores
  it zero and Story 2 disappears.
- **Do not flatten the gap between Kestrel's controlling stakes and the filler minority stakes.** The
  gap is what makes accumulation beat proximity. Flatten it and the nearest account wins again, which
  anyone can write in SQL.

### The fanout check

Genie once answered a combined exposure-and-findings question by joining the two one-to-many branches
off `customers` in a single pass, so each branch multiplied the other and both numbers came back
inflated.

- **How to run it:** pick a customer with both open invoices and open findings, confirm the true
  figures, then ask the space for that customer's open exposure and open findings together. Pick from
  the current data, since which customers carry open findings is date-derived.
- **How to read it:** correct figures confirm the guards. Figures that are exact multiples of the true
  ones mean Genie joined the two branches without aggregating each to grain first, and the Story 2 miss
  will read as a broken BI tool rather than a blind one.

## Setup: Genie space and MCP server

The one-time setup that creates the Genie space and loads the graph is covered in the project README.
The blocks below are the authored text that setup depends on.

**Guardrail: the two gold tables never enter the Genie space.** `classifications` and
`business_unit_exposure` materialize the graph's conclusions into Delta. Adding them re-introduces
write-back leakage, where the lakehouse-only engine reads the graph's answer straight from a column and
ties. Kept in the space are every instance table (`compliance_findings` and `owned_by` included) plus
the `customer_risk_exposure` metric view.

### MCP server description

Paste into the server or tool `description` field and adjust names to match your deployment. The
supervisor decides when to call the graph from this description alone.

```text
This server exposes a Neo4j knowledge graph for the supplier and customer risk
domain of a global beverage producer. Use it to resolve governed business
definitions, to apply the two graph-native definitions that have no lakehouse
column, and to explain the provenance behind an answer. Databricks Genie owns
the raw facts and aggregations; this graph owns their meaning and lineage.

Use this server to:
- Resolve what a business term means before querying facts. Terms: Strategic
  Account, Defaulted Customer, Delinquent Customer, High-Risk Supplier,
  Critical Supplier, Ownership Risk.
- Apply the two graph-native terms that no column can express, Critical Supplier
  and Ownership Risk. Resolve each definition and its governing threshold from
  the graph; never assume either.
- Resolve what a governed term is worth, not only what it means. A term may
  carry a measure describing the exposure behind it; read the measure and the
  rule it is defined by, then send the arithmetic to Genie.
- Read a governed threshold value instead of assuming one. Thresholds: Supplier
  Risk Threshold, Late Payment Threshold, Supply Concentration Threshold,
  Ownership Contagion Threshold.
- Explain why a record was classified, tracing it to the rule, entity, and
  source table behind it.
- Answer policy, governance, and impact questions that span definitions.

Do NOT use this server for large scans, counts, sums, or joins over the fact
tables. Send those to Genie.

Graph shape. A knowledge layer of business terms, rules, policies, thresholds,
and lineage, plus an instance layer that mirrors the lakehouse tables. Discover
the exact labels, relationships, and properties through the schema tools.

Conventions:
- Supplier betweenness and customer PageRank are precomputed graph metrics
  stored as node properties.
- The graph is read-only. Emit read Cypher only, and prefer parameters over
  string interpolation.
```

### Genie space description and instructions

Two separate authored fields. **Description** is the short blurb on the About tab. **Instructions** is
its own tab. Genie ships auto-generated text for both the moment a space is created, so both must be
overwritten by hand and checked against these blocks after any build.

**Description.** Replace the generated capability marketing with:

```text
Answers questions over the supplier and customer data in Unity Catalog schema
supplier_risk, for a global beverage producer. It reports rows, counts, totals,
and rankings from the instance tables and the customer_risk_exposure metric view.
```

Nothing more. A capabilities list tells the model which questions it is expected to answer, and the
demo turns on the model reaching its own conclusions about what it can see.

**Instructions.** Schema facts only: grain, units, join paths, and what a coded value means. No
analytical conclusions, and never a beat's own question word, which would prime the axis Genie picks.

```text
This Genie space answers questions over the supplier and customer risk data in
Unity Catalog schema supplier_risk, for a global beverage producer. It answers
from the raw facts: rows, counts, totals, and rankings over the instance tables.

Use this space to:
- Return rows, counts, totals, and rankings from a single table or a join or
  two: customers by segment, suppliers by risk, invoices by status, revenue by
  business unit and period.
- Answer customer-level aggregates from the customer_risk_exposure metric view.
  It carries open exposure, overdue amount, invoice and compliance finding
  counts, credit limit, and credit utilization, each aggregated at its own grain,
  and it is the only place compliance finding counts are available.
- Apply a threshold the graph already resolved. Pass the concrete value in the
  question.
- Scope every answer to the region or business unit named in the question. When a
  question names a region or business unit, for example the Americas, filter to
  that unit before you rank, count, or aggregate, and never widen a scoped
  question to the global population.

Conventions:
- Lateness is precomputed in the daysLate and status columns; never compute
  lateness from current_date.
- Every amount in this dataset is EUR. Render amounts with the euro symbol and
  never with a dollar sign.
- invoices is a one-to-many branch off customers. Aggregate it to customer grain
  in its own subquery before joining to another customer-grain table, or read the
  metric view, which already does this.
- suppliers has no business unit column. Route through the
  supplier_business_units bridge to scope any supplier question to a region or
  business unit.
- revenue_entries.period is a monthly DATE on the first of the month, not a
  quarter label. Derive quarters with YEAR and QUARTER.
- Invoice status values are paid, open, and overdue; only open and overdue are
  live exposure. Compliance finding status values are open and closed.
```

The instructions field drifts, so read it back from the live space and compare it line by line against
this block after every build.

**Supervisor routing (Genie + Graph only).** Routing lives in the supervisor's description of the
Genie tool, never in the neutral space above. Set that tool description to: Genie owns facts, counts,
totals, and rankings over the instance tables; route anything that needs a business-term definition, a
relationship judgment, or classification provenance to the graph tool instead.
