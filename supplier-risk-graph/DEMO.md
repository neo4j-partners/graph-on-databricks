# Demo walkthrough

This walkthrough assumes the one-time setup in the [`README.md`](README.md) is done: the data is generated, Neo4j is loaded, the GDS analytics have run, the Unity Catalog tables are uploaded, and the Genie space is created with the two gold tables and `compliance_findings` kept out of it.

> **Data freshness.** The dataset is a forward-looking snapshot taken from the date it was generated. `generate_data.py` defaults `--as-of` to today, and Story 2 depends on Jade's invoices still reading as open and on time. Regenerate the data and rerun the pipeline shortly before any demo.
>
> **This script quotes no figures.** Every number comes back from Genie live and the presenter reads it off the screen. Amounts, scores, and cutoffs all move when the data is regenerated, so a number typed into a slide is a number that will eventually be wrong in front of an audience. What this script does state are the structural claims: who ranks first, how far apart things sit, and which shortcut misses. The generator asserts all of them on every run, so if one breaks you find out before you walk in.

## Graph terms used in this walkthrough

| Term | Meaning |
|---|---|
| Betweenness | A score for how often a node sits on the paths between other nodes; a high score marks a bottleneck or bridge |
| PageRank (personalized) | A score for how much influence flows to a node from a chosen set of starting nodes, spreading along relationships |
| Contagion | Risk spreading across relationships, so a clean node inherits risk from the nodes it is connected to |

## What the demo proves

Two engines answer the same question over the same data:

- **Genie Agent (lakehouse-only):** a Databricks Genie space scoped to the `supplier_risk` schema. It reads the raw instance tables and the `customer_risk_exposure` metric view over them, and nothing else. The metric view holds no conclusions, only aggregates of columns already in those tables.
- **Genie One (Genie plus the graph):** the same Genie Agent under a supervisor that can also call a read-only Neo4j MCP server over the knowledge graph.

The demo runs two stories:

- **The setup:** each story puts one natural question to both engines.
- **The miss:** the lakehouse-only engine reads every column correctly and still gets the answer wrong, because the risk is a shape in the connections, not a value in a column.
- **The catch:** Genie One resolves the governed definition from the graph, walks the connections, and flags what the columns cannot show.

### The honesty framing

Never claim SQL cannot express these traversals. A Databricks audience knows recursive CTEs exist. The defensible claims are narrower and true:

*Betweenness is a graph score for how often a node sits on the paths between other nodes; a high score marks a bottleneck. PageRank is a graph score for how much influence flows to a node from a chosen set of starting nodes.*

- No lakehouse column governs what "single point of failure" or "same ownership group" means. The definition lives in the graph.
- The two graph-native signals, supplier betweenness and weighted ownership PageRank, are graph computations no column carries and no aggregate reproduces. Both are expressible in SQL and neither is anything a BI tool writes unprompted. Their governing cutoffs are governed values in the graph, never a column a BI tool could sort on.
- Asked a plain question, Genie Agent groups by the obvious column and answers from it. It does not spontaneously write the multi-tier convergence query or the transitive ownership walk that surfaces the real risk.

### The five-beat arc

Both stories run the same five beats, so the audience learns the rhythm on story 1 and feels it confirm on story 2:

1. **The ask:** one natural question, put to both engines.
2. **The miss:** the lakehouse-only engine answers from the columns, correctly, and gets it wrong.
3. **The flag:** Genie One shows the structure, one picture the tables cannot draw.
4. **The exposure:** the flag gets a euro figure, computed from the same lakehouse data.
5. **The decision:** the recommended action, handed to the room as a live choice.

- **Nothing here is pasted.** Both engines write their own queries. The presenter types a question and Genie or Genie One generates the SQL or Cypher, so this script gives questions and talking points, not queries.
- **The names line up on both sides.** Graph properties and the instance tables both use camelCase. See [`DATA_ARCHITECTURE.md`](DATA_ARCHITECTURE.md) for the full label, relationship, and property model.

## Story 1: the hidden glassworks

Supplier concentration risk hiding in the sub-tier. Five bottle suppliers are separately qualified and separately contracted, so the supply base looks diversified. All five buy their glass from the same hidden glassworks, so if that one furnace fails the enterprise cannot bottle its product. Procurement knows its tier-1 suppliers. It does not know who they buy from.

```text
              tier 1 glass bottle suppliers (all clean scores)
              +--> Harbor Bottling Supply --+
              +--> Summit Glass Packaging --+
 Americas ----+--> Ironbridge Containers ---+--> Cascade Glassworks
              +--> Clearwater Bottles ------+    (hidden tier 2, raw glass)
              +--> Aurora Packaging Co -----+

 arrows read "buys from"; the SUPPLIES edges point the opposite way

 BI sees:    five independent bottle suppliers, diversified
 Graph sees: every bottle traces back to one hidden furnace
```

### Beat 1, the ask

Put to both engines:

> "How diversified is our glass bottle supply for the Americas, and what is our single biggest point of failure?"

### Beat 2, the miss

- **What it does:** groups suppliers by the `subcategory` column and reports five glass-bottle suppliers feeding the Americas, all with clean risk scores. A correct read of every column, and the wrong answer.
- **What comes back:** five rows on screen. Five names, five clean scores, every one of them well under the governed high-risk cutoff. Read them out. The read is "well diversified."
- **Why it is wrong:** the `supply_relationships` table is in the space, so the raw links are visible, but nothing labels Cascade as critical, and the engine does not invent the multi-tier convergence join that would find it.

### Beat 3, the flag

- **The governed definition:** Genie One first resolves what a Critical Supplier means from the graph: a supplier that a disproportionate share of the multi-tier supply paths carrying a commodity into a business unit run through, leaving few alternatives around it, and one that need not sell to that business unit directly. The Supply Concentration Threshold, a betweenness cutoff, parameterizes it.
- **The walk:** it then walks the multi-tier chain into the Americas and collapses the five bottle suppliers onto their shared source.
- **The result:** one row comes back, Cascade Glassworks, the hidden raw-glass supplier reaching all five bottle suppliers into the Americas. Its precomputed betweenness is the strict maximum in the supplier network, and applying the governed cutoff confirms it is the only Critical Supplier.
- **Why no score sort finds it:** Cascade's own risk score sits below the High-Risk threshold, and plenty of suppliers score higher, so no score filter flags it as the one that matters.

### Beat 4, the exposure

- **What beat 3 handed over:** an entity, Cascade Glassworks, not a number. The graph has no euros in it.
- **How Genie One gets to a number:** it follows `MEASURED_BY` from the Critical Supplier term to the Supply Exposure measure, reads the Supply Exposure Rule, and lands on the `RevenueEntry` and `BusinessUnit` entities and the tables they map to. That is what tells it which question to ask next, and about which business unit.
- **The follow-on question, put to Genie:**

> "What was the Americas business unit's recognized revenue for the most recent full quarter?"

- **The figure:** a single quarterly revenue number in EUR, returned by plain Genie over the instance tables. Read it off the screen and use that. No graph query produces it.
- **What the figure is:** the Americas business unit's recognized revenue for the quarter, the revenue at risk behind the bridge. It is not euros attributable to Cascade. The dataset carries no supplier spend column, so no engine can attribute revenue to a supplier.
- **Why this is the honesty beat:** the lakehouse had the money the whole time and could always add it up. What it lacked was a reason to ask about the Americas rather than about anything else, because no column names Cascade as the bridge. The graph supplies the entity and the governed measure; Genie supplies the arithmetic.

### Beat 5, the decision

Qualify a second glass source to protect the Americas quarterly revenue flow, quoting the figure beat 4 just returned. The rough cost of a second source is presenter framing on a slide, not a data answer. Genie One's data answer ends at the flag and the exposure.

### Graph mechanics

*A traversal walks the graph relationship by relationship; a variable-length traversal keeps walking through any number of hops. GDS is Neo4j Graph Data Science, the library that computes graph algorithms such as betweenness.*

- **The traversal:** a variable-length traversal walks the multi-tier chain. `SUPPLIES` points from a supplier toward what it feeds, so the path is `(Cascade)-[:SUPPLIES]->(bottle supplier)-[:SUPPLIES]->(Americas)`.
- **The GDS piece:** `gds.betweenness`, precomputed by `gds.py` as a `betweenness` property on every Supplier node, confirming the share of commodity-carrying supply paths into a business unit that run through Cascade.
- **The cutoff:** the Supply Concentration Threshold is set from the score distribution so only Cascade clears it.

## Story 2: the clean payer in a bad group

Group credit exposure hiding in the ownership structure. A customer pays every bill on time and is assessed standalone, the way credit control assesses every account. Nothing near it looks alarming either. But the group that controls it also controls four companies that went bankrupt, two levels further down, and it holds all of them outright. A lender would call these a group of connected clients and aggregate the exposure. The account-level rating cannot.

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

Nothing is one hop away, which is the point. Customers across the book defaulted, and plenty of clean accounts sit directly next to one. Those accounts hold only a few percent of the company that failed. Jade holds nothing directly and is owned 85% by a group that owns its failures outright, so far more damage reaches Jade than reaches anyone standing closer.

### Say this in the room: it is pipes, not distance

If you explain one thing in Story 2, explain this. It is the whole reason the graph is required.

The instinct everyone has is that risk is about **distance**: who is standing closest to the fire. That instinct is what SQL is good at, and it is wrong here.

Ownership is not a distance, it is a **pipe**. Owning 90% of a company is a wide pipe, and almost everything that happens to it flows through to you. Owning 3% is a straw. So the right question is not "how close are you to a failure" but "how many pipes lead from failures to you, and how wide is each one."

- The accounts standing right next to a bankruptcy hold only a few percent of it. Straws. Almost nothing arrives.
- Jade is three levels away from four bankruptcies, but every pipe on the path is 65% to 90% wide. Four failures arrive largely intact.

Distance says Jade is fine. Pipes say Jade is the most exposed trading account on the book. Adding up flow through a web of pipes, where damage arrives by several routes at once, is exactly what the graph algorithm does in one line and what a join cannot express.

### Beat 1, the ask

Put to both engines:

> "Which customers should credit review look at next?"

### Beat 2, the miss

- **What it does:** goes to the `customer_risk_exposure` metric view and ranks customers by `credit_utilization` and `overdue_amount`, taking the top ten. A clean, sensible query: it picks the two columns that most directly express credit strain and orders by them.
- **What it does not do:** `avgDaysLate` and `churnRisk` never enter the query at all. The engine reads the exposure measures correctly and never has a reason to reach past them.
- **Who is missing:** Jade Beverage Distribution is nowhere in the ten.
- **Why:** every column it reads is clean. Jade carries no overdue balance at all, so `overdue_amount` is zero, and it draws a modest share of a large committed facility, so `credit_utilization` sits nowhere near the top of the book. Widen the ranking to lateness or churn and Jade is still clean: 0.0 average days late, 0.0 overdue share, low churn risk. A correct read of every column, and it misses the account credit review should worry about most.
- **If the room asks about the ownership table:** it is in the Genie space, stakes and all, so push the question. Ask which customers are near a default, and the lakehouse answers correctly and still misses Jade, because the accounts nearest a default are the ones holding a few percent of it. Ask which ownership group holds the most defaults and it returns a different group, not Kestrel's. Both are right, both are the wrong account.

### Beat 3, the flag

*Contagion is risk spreading across relationships, so a clean node inherits risk from the nodes it is connected to.*

- **The governed definition:** Genie One resolves what Ownership Risk means from the graph: "an active customer with a clean record of its own, no default and never delinquent, that absorbs more failure through its ownership stakes than any other trading customer," parameterized by the Ownership Contagion Threshold, a weighted PageRank cutoff.
- **How it filters:** it excludes the defaulted customers and the invoice-less holding companies, then returns the clean operating customers whose stake-weighted propagated risk clears the cutoff, with the ownership chain as the stated reason.
- **The result:** Jade Beverage Distribution comes back, a platinum account owned 85% by Kestrel Holdings, which owns Harbour Group and Tern Capital outright, and those two own the four companies that defaulted in the most recent quarter. Jade scores clearly ahead of the next trading customer, a gap wide enough that the cutoff sits between them with room to spare, even though Jade itself never missed a payment and nothing within two hops of it has failed.
- **Why nobody else clears it:** the accounts sitting directly beside a default hold only a few percent of it, so almost nothing propagates to them. Kestrel's stakes are 65% to 90% at every level, so four failures arrive at Jade largely intact. The cutoff sits between Jade and the field.
- **If someone asks why Kestrel or Harbour is not the answer:** they score higher, and they are correctly excluded. Kestrel, Harbour Group, and Tern Capital are holding companies. They stand between Jade and the failures, so more risk lands on them, but they buy nothing and carry no invoices, so there is no receivable to act on and no facility to cut. The governed definition of Ownership Risk says "an active customer" for exactly this reason, and having invoices is how the graph decides that. The question the demo answers is which **trading** account is most exposed, and that is Jade.

### Beat 4, the exposure

- **What beat 3 handed over:** an entity, Jade Beverage Distribution, not a number.
- **How Genie One gets to a number:** it follows `MEASURED_BY` from the Ownership Risk term to the Credit Exposure measure, reads the Credit Exposure Rule, and lands on the `Invoice` and `Customer` entities and the tables they map to. That is what tells it which question to ask next, and about which customer.
- **The follow-on question, put to Genie:**

> "What is Jade Beverage Distribution's committed credit facility, and how much of it is drawn as open invoice balance?"

- **The figure:** a committed facility, of which a smaller amount is drawn across the open invoices. Both numbers come back from plain Genie over the instance tables. Read them off the screen. The exposure is the whole facility, not the drawn portion, because all of it is committed and can be drawn.
- **Why this is the honesty beat:** the credit line and the open invoices were sitting in the lakehouse the whole time. Nothing in those columns says Jade is the account to ask about, because Jade's own record is spotless.
- **Why it lands:** Jade is also a Strategic Account, so the line lands hard: the biggest clean customer on the book is the one absorbing the most failure in it, and nothing in its own record or its immediate neighbourhood says so.

### Beat 5, the decision

Cut Jade's committed facility down toward the balance already drawn, using the two figures beat 4 just returned, and require prepayment on new orders, so the enterprise stops carrying the full committed exposure on the account absorbing more of the book's failure than any other.

### Graph mechanics

*Personalized PageRank scores how much influence flows to each node from a chosen set of starting nodes, spreading along relationships. Weighting it means influence splits by the size of each stake rather than evenly.*

- **The algorithm:** weighted personalized `gds.pageRank`, seeded on every defaulted customer in the book and propagated over the `OWNED_BY` edges with `ownershipPct` as the relationship weight, precomputed by `gds.py` as a `pagerank` property on every Customer node.
- **The flow:** failure flows out of every default in proportion to who holds it. Through Kestrel's 65% to 90% stakes it arrives at Jade nearly intact, three levels up and back down. Through a filler's few-percent stake it effectively stops.
- **Why the weight is the whole story:** unweighted, this collapses back into a hop count and the nearest account wins, which is a query anyone can write. Weighted, the answer depends on the product of stakes along every route and the sum over all routes, which is what the iteration computes and what no join reproduces.
- **The cutoff:** the Ownership Contagion Threshold is set from the score distribution so Jade clears it and no other trading customer does.

## Why the arc works

- **The miss is the proof.** No prediction, no proof by clock. The lakehouse-only engine reading every column correctly and still missing the risk is the whole argument, demonstrated live, twice.
- **Beat 5 stays open on purpose.** Handing the room a live decision with a euro figure attached converts the contrast into urgency, and it costs nothing to build.
- **Genie One's answers read like actions.** It composes its reason from the path itself and closes with the recommended action, something a risk officer acts on rather than provenance trivia.

## The fairness rebuttal: show the GDS run once

- **The question the room asks:** whether plain Genie was denied the scores.
- **The show:** run `gds.py` once on stage, about 30 seconds.
- **The rebuttal:** both engines get every table, including the raw supply links and the ownership stakes. What plain Genie will not do is invent an all-pairs shortest-path computation or an iterative weighted propagation, unprompted, from a business question. Both are expressible in SQL; neither is something a BI tool reaches for, and both are one line of GDS.
- **Do not say BI cannot compute these at all.** It is not true, a Databricks audience knows it is not true, and the demo does not need it. The claim that holds is the one above.
- **If challenged, invite the shortcut.** Offer the room the obvious aggregates live and let Genie run them. Count supplier connections and a different supplier comes back, not Cascade. Rank customers by distance to a default, or by defaults per ownership group, and neither returns Jade. The shortcuts are available, they run, and they produce the wrong answer on screen.

Three facts behind the rebuttal:

- **The scores are precomputed.** `Supplier.betweenness` and `Customer.pagerank` are written as Neo4j node properties at setup and never recomputed during the walkthrough. The `gds.py` run above is a rebuttal aside, not part of either story.
- **Neither property is ever synced to Delta.** Writing them into a gold table would recreate the write-back leakage this demo removes, and the lakehouse-only engine would tie again.
- **The two cutoffs come from the score distributions,** set after the algorithms run, so Cascade clears the concentration cutoff and Jade clears the contagion cutoff while no other supplier or trading customer does.

## The background contrast: governed definitions the columns can carry

The two stories are the payoff. The four column-findable terms make the contrast honest by showing what the lakehouse-only engine can govern, so the gap is clearly the two it cannot. Use one as a warm-up if the room needs it.

- **The warm-up question:** ask both engines "Which suppliers are high-risk?"
- **The lakehouse answer:** it has the `riskScore` column but no governed threshold, so it guesses a cutoff, often a top-N or a round number, and can miscount.
- **The Genie One answer:** it reads the governed threshold off the rule and returns every supplier at or above 70, the governed cutoff, consistent no matter who asks.
- **Why it matters:** this is the honest baseline. With a column and a governed number, BI can close most of the gap; the two stories are exactly the cases where there is no such column.

## What else Genie One can answer

The knowledge layer answers questions that span definitions, which the fact side finds awkward or cannot express.

- **Impact analysis.** "If we lower the Late Payment Threshold to 45 days, which terms, rules, and tables change?" A traversal from `Threshold` through `APPLIES_TO`, `DEFINED_BY`, and `EVALUATES` to the affected entities and their Unity Catalog tables.
- **Policy scope.** "Which policies govern customer data?" Follow `CONSTRAINS` from each `Policy` to its `Entity`. The Credit Risk Policy and the Compliance (KYC) Policy both constrain the Customer entity.
- **Provenance.** "Show the full lineage behind Jade's Strategic Account label." Genie One walks instance to term to rule to entity to the physical tables, returning the Strategic Account term, the reason recorded on the edge, the Strategic Account Rule, the Customer entity, and the tables it maps to. Customer carries two sources, `supplier_risk.customers` and `supplier_risk.owned_by`, so the walk returns both. That is the honest answer: the ownership stakes are part of what the Customer entity is made of.
- **Queryable glossary.** The knowledge layer is the catalog. List every governed term and its definition, which threshold parameterizes which term, or which policy owns which rule.

The two graph-native terms, Critical Supplier and Ownership Risk, are never pre-planted as `CLASSIFIED_AS` edges. Genie One resolves each from its definition and applies it live using the precomputed betweenness and PageRank properties, so those labels never exist as a materializable row and can never leak into a gold table.

## Pre-flight check

You do not need to verify figures. Every number comes back from Genie live, and whatever it returns is right for that build. What you need is confidence that the two stories still have their shape, because if one breaks the demo silently stops making its point.

- **`make demo`** rebuilds everything. The generator asserts both story shapes on every run, so a clean run with no `AssertionError` is the check.
- **`make expected`** prints the figures this build actually produced, generated from `data/ground_truth.json` on the spot. Read it once before you go on and treat it as the answer key, not anything typed into this file.
- **`make check`** validates the CSVs offline and touches neither Neo4j nor Unity Catalog.

The two shapes the generator asserts:

- **Story 1.** Cascade ranks first on betweenness in the supplier network, well clear of the runner-up, and is the only supplier over the concentration cutoff. It is not the most-connected supplier, it does not top a descendant count, and it has no rows in `supplier_business_units`, so no region-scoped supplier query can return it.
- **Story 2.** Jade ranks first among trading customers on stake-weighted PageRank, far enough ahead that the cutoff sits between it and the field. Jade sits three hops from the nearest default while other clean accounts sit one hop away, and another ownership group holds more defaults than Kestrel's.

Both of those are the demo. Everything else on screen is arithmetic Genie does live.

### Three things that will quietly break this demo

All three look like harmless cleanups. All three destroy the answer rather than degrade it, so none of them announces itself on stage.

- **Do not drop the trading-customer filter.** `gds.py` ranks only customers that carry invoices and are neither defaulted nor delinquent. The three holding companies score higher than Jade because they sit between it and the failures, so removing the filter makes the demo's answer a paperwork company with no receivable, no facility, and no decision to hand the room. The filter is the governed definition ("an active customer"), not a convenience.
- **Do not lower the PageRank iteration limit.** The ownership structure is deep and the stakes are lopsided, so the scores take many times the GDS default of 20 iterations to settle. Cut the limit and the contagion cutoff gets read off numbers that are still moving. The convergence check in `gds.py` fails the build loudly if this happens; leave it in place.
- **Do not "fix" the UNDIRECTED graph projections.** Both projections in `gds.py` erase edge direction, and both stories depend on it. Jade is reached only by travelling up to the shared parent and back down, so under a directed projection Jade scores zero and Story 2 disappears entirely. Cascade's bridge role likewise depends on direction being ignored. Making the projection match the edge semantics looks like a correctness fix and is a story-ending change.

A fourth, subtler one, if the generator is ever retuned: **the gap between Kestrel's controlling stakes and the filler minority stakes is what makes accumulation beat proximity.** Flatten those two ranges towards each other and the account nearest a default wins again, which is a query anyone can write in SQL, and the demo loses its point. `FILLER_STAKE_RANGE` in `generate_data.py` carries the same warning.

### The fanout check

This one is about the lakehouse engine rather than the data, so it is not a figure you can read off a file.

- **The failure it guards against:** Genie once answered a combined exposure-and-findings question by joining the two one-to-many branches off `customers` in a single pass, so each branch multiplied the other and both numbers came back inflated by the other's row count.
- **Guard one:** `compliance_findings` is out of the Genie space entirely, so a two-branch fanout is structurally impossible. The raw findings table is not there to join against.
- **Guard two:** the `customer_risk_exposure` metric view declares each join `one_to_many`, so every measure aggregates at its own grain. It is the only place in the space where a finding count is available at all.
- **How to run the check:** pick a customer with both open invoices and open findings, confirm the true figures against `data/invoices.csv` and `data/compliance_findings.csv`, then ask the space for that customer's open exposure and open findings together. Pick from the current data rather than reusing a name from a previous run, because which customers carry open findings is date-derived.
- **How to read the result:** correct figures confirm both guards. Figures that are exact multiples of the true ones mean `compliance_findings` found its way back into the space, and the Story 2 miss will read as a broken BI tool rather than a blind one.

## Genie space and MCP setup

For the one-time setup that creates the Genie space and confirms which tables are kept out of it, see [`README.md`](README.md). The two blocks below are the descriptions the supervisor reads to route between the two engines.

### What to put in the MCP server description

Paste the block below into the server or tool `description` field and adjust names to match your deployment.

- **Why it is written this way:** the supervisor decides when to call the graph from this description alone, so it spells out the graph's job and the behavior expected of it.
- **Why the schema is absent:** the server has schema discovery, and resolving definitions live from the graph is the point of the demo.

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

### What to put in the Genie space description and instructions

The space has two separate authored fields and they take different text. **Description** is the short blurb under the space title, on the About tab. **Instructions** is its own tab and holds the block below. Setting one and not the other is the failure mode: Genie ships an auto-generated description the moment a space is created, and that generated text stays until it is overwritten by hand.

**Replace the generated description.** A newly created space describes itself with capability marketing, along the lines of "enables assessment of supplier risk and financial health" followed by Capabilities and Limitations lists. That text is not neutral, it was not authored against the vocabulary rules, and it drifts back if the space is recreated. Overwrite it with:

```text
Answers questions over the supplier and customer data in Unity Catalog schema
supplier_risk, for a global beverage producer. It reports rows, counts, totals,
and rankings from the instance tables and the customer_risk_exposure metric view.
```

Nothing more. No capability list, no limitations list, no statement of what the space is good at. A capabilities list is a hint sheet: it tells the model which questions it is expected to be able to answer, and the demo turns on the model reaching its own conclusions about what it can see.

- **Keep the space neutral.** It carries facts about the data, not routing rules. The same block serves beats 1 and 2 standalone and under Genie One, so it must never tell the space which questions to refuse. Routing lives in the supervisor's Genie-tool description, given right after the block.
- **The table set it assumes:** the instance tables plus the `customer_risk_exposure` metric view. Kept out are the two gold tables, `classifications` and `business_unit_exposure`, and the raw `compliance_findings` table. Findings reach the space only as the metric view's `open_finding_count` measure, which makes a two-branch fanout impossible rather than merely discouraged.
- **Schema facts only:** grain, units, join paths, and what a coded value means. No analytical conclusions. The demo turns on Genie reading every column correctly and still missing what only the graph can see, so an instruction that hints at a multi-tier traversal or pre-judges what a metric implies would hand over the answer. `upload.py` applies the same rule to the comments it writes into Unity Catalog.

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

**Do not name the question's own vocabulary in the instructions.** The scoping bullet above says rank, count, or aggregate rather than naming the thing Beat 1 asks about. Repeating a beat's question word inside the instructions primes the axis Genie picks, and `CONTRACT.md` section 4 makes Beat 1's ambiguity the demonstration rather than a bug to fix. The instructions may say how to scope, how to join, and what a column means. They may not say what to conclude, and a question word carried across from a beat is halfway to a conclusion.

**Check the deployed text against this block, not against a worklog.** The instructions field drifts: a deployed space has been found carrying an older, shorter variant missing the currency rendering rule, the `supplier_business_units` bridge rule, the `revenue_entries.period` rule, and the status value lists. Read the field back from the live space and compare it line by line.

**Supervisor routing (Genie One only).** When Genie runs under the Genie One supervisor, the routing lives in the supervisor's description of the Genie tool, not in the neutral space above. Set that tool description to: Genie owns facts, counts, totals, and rankings over the instance tables; route anything that needs a business-term definition, a relationship judgment, or classification provenance to the graph tool instead.

> **Guardrail.** The two gold tables, `classifications` and `business_unit_exposure`, are produced by the pipeline but must never be added to the Genie space. They materialize the graph's answers into Delta, and adding them re-introduces write-back leakage: the lakehouse-only engine would read the graph's conclusions straight from a column and tie, which is the exact failure this demo is built to expose.

## Generating a dashboard with Neo4j AI

Neo4j's "Create with AI" dashboard generator builds a dashboard from a prompt and the database schema. Naming the exact labels, relationships, and camelCase property names gets far closer than a generic "show me risk" prompt.

### Dashboard description

Paste this into the **Dashboard description** box:

```text
Build a supplier and customer risk dashboard for a global beverage producer that
sells to Customers, buys from Suppliers, and rolls both up into internal
BusinessUnits. Suppliers feed each other and the business units via SUPPLIES;
customers own each other via OWNED_BY.

Include:
- A KPI row: total customers, total suppliers, count of High-Risk suppliers
  (Supplier.riskScore >= 70), count of Delinquent customers, and count of open
  ComplianceFindings.
- High-risk suppliers ranked by riskScore, with their category and subcategory.
- Critical Supplier view: suppliers ranked by Supplier.betweenness, highlighting
  any above the Supply Concentration Threshold, with the business units their
  multi-tier supply paths reach.
- Ownership Risk view: customers ranked by Customer.pagerank, highlighting the
  clean trading customers above the Ownership Contagion Threshold. A customer
  qualifies only if it carries its own invoices and is neither defaulted nor
  Delinquent, so invoice-less holding companies are excluded even though they
  score highly. Show creditLimit as the committed credit facility and the open
  invoice balance as the drawn portion of it. Rank by absorbed risk, not by
  whether a defaulted company happens to share an owner.
- Strategic accounts (Customers CLASSIFIED_AS 'Strategic Account') with segment
  and any ownership link.
- A lineage view: for a selected classified Customer or Supplier, walk
  CLASSIFIED_AS -> BusinessTerm -DEFINED_BY-> BusinessRule -EVALUATES-> Entity
  -MAPS_TO-> DataSource, showing the term, the reason, the rule, and the
  physical DataSource.table.

Prefer the governed CLASSIFIED_AS labels and BusinessRule thresholds over
recomputing definitions from raw properties. All properties are camelCase.
Supplier.betweenness and Customer.pagerank are precomputed graph properties.
```

### Optional focus

```text
Supplier and customer risk exposure, with governed classifications, the two
graph-native risks, and provenance
```

- **Assumes:** the graph as loaded by `load.py` plus `gds.py`, so `Supplier.betweenness` and `Customer.pagerank` exist.
- **If you skipped `gds.py`:** drop the Critical Supplier and Ownership Risk views, since those properties will not be present.

## Why the demo is built this way

The dataset looks more complicated than the story needs. Two cross-linked supplier clusters, a decoy hub, weighted multi-parent ownership, defaults planted in pairs, a trading-customer filter, thresholds computed after the fact. None of it is there for realism or for show.

**Every piece of that complexity is a scar.** We built the simple version four times. Each time, someone answered the graph's question with one line of SQL, and the demo died on the spot. The complexity is what is left after closing each of those shortcuts.

### The four times the lakehouse tied

- **Leak 1, the answers were in a Delta column.** The pipeline materializes the graph's classifications into the `classifications` and `business_unit_exposure` gold tables, and those tables were in the Genie space. The lakehouse-only engine read the graph's conclusions, labels and reasons included, without ever touching the graph. Both engines returned the same nine customers with the same rule split and the same threshold. **Fix:** the gold tables stay out of the space.
- **Leak 2, the scores would have been in a Delta column.** Syncing `betweenness` and `pagerank` into a gold table recreates leak 1 one layer up. **Fix:** the GDS scores are never synced to Delta and live only in the graph.
- **Leak 3, the supplier network was a star forest.** This was the one that nearly ended the project. Every supplier fed a few plants and nothing fed it back, so the graph was 46 disjoint one-hop stars. On a star, betweenness is exactly `k(k-1)/2` where `k` is the number of children, which means **betweenness rank and connection-count rank are the same ranking**. Cascade scored 10 because it had 5 children. The best filler scored 3 because it had 3. The cutoff sat at the midpoint. On that shape every centrality measure collapses to degree, so `COUNT(*) GROUP BY supplier` returned the graph's answer instantly. The worklog's verdict: *"The demo built a $1,000 tool to answer a $1 question."* **Fix:** rebuild the topology, described below.
- **Leak 4, the ownership was one level deep.** Thirteen flat parent-and-children families, and both defaults sat in Kestrel's. Personalized PageRank could only answer *reachable or not*, never *how much*, and reachability is a join. Adding depth alone did not fix it either: counting defaults three levels out is three joins, annoying but not different in kind. **Fix:** put the ownership percentage on the edge, described below.

### What each piece of complexity buys

**Story 1, the supplier network:**

- **Two cross-linked clusters, not stars.** Each cluster is a spanning tree plus extra chords, so several routes run between any two suppliers and no node inside a cluster is a bottleneck. Betweenness only means something when there are multiple routes to choose between.
- **Cascade as the only edge between the clusters.** Remove it and the network falls in two. That is what makes it the bridge rather than the hub.
- **A decoy hub in cluster A.** SUP-109 is pushed to the highest connection count in the network, so the obvious aggregate returns SUP-109 and not Cascade. Cascade sits third on that ranking.
- **Cascade buys from the B side as well as selling to the A side.** Raw material flows in, glass flows out. This is what kills the descendant-count shortcut: Cascade is not the source of the whole network, so it ranks 42nd by transitive descendants.

**Story 2, the ownership network:**

- **Ownership percentages on the edge.** The single most important change in the demo. Influence splits by the size of each stake instead of by hop count, so the question stops being *how close are you to the fire* and becomes *how many pipes lead to you and how wide is each one*. Without weights this collapses back into hop counting and the nearest account wins, which anyone can write in SQL.
- **Multi-parent ownership.** `owned_by.csv` with an `ownershipPct` column replaced the single `parentCustomerId` field, because a subsidiary can now be held by several owners at different stakes.
- **Filler defaults planted in pairs holding each other at 80% to 95%.** A default with a single neighbour dumps all of its mass onto that neighbour no matter what the weight says, so lone defaults kept handing the top score to whoever happened to sit beside them. Paired defaults absorb each other and only a token stake leaks outward.
- **Filler stakes spread wide, not uniformly thin.** Weighted PageRank normalizes per node, so making every filler stake small had literally zero effect on the ranking. Only the relative stake around a given node matters. The gap between Kestrel's controlling stakes and the filler minority stakes is what makes accumulation beat proximity.
- **Two intermediate holding companies between Kestrel and the four defaults,** at 65% to 90% throughout. This puts Jade three hops from every failure while ordinary clean accounts sit one hop from one, so distance ranks Jade as safe and pipe-width ranks it first.
- **The trading-customer filter.** The three holding companies stand between Jade and the damage, so they always score higher. They are excluded for carrying no invoices, which the governed term already required by saying "an active customer." This is a real filter, not a fudge, and it is load-bearing.

**Both stories:**

- **Thresholds computed from the score distribution after the algorithms run.** If a cutoff were a constant in a column, the lakehouse could sort on it. Being derived from the distribution is what keeps it graph-native.
- **A few hundred filler entities with ordinary edge shapes.** Row count alone hides a plant in a table scan but does nothing against a graph algorithm. If Cascade were the only supplier-of-suppliers, or Kestrel the only owned group, each would be the only structure of its kind and trivially findable.

### The one test that keeps it honest

Everything above is enforced by a single rule, asserted in `generate_data.py` on every build:

> **Rank by the GDS metric must disagree with rank by every simple SQL aggregate.**

| Story | Graph ranking | Naive rankings that must miss |
|---|---|---|
| 1 | Cascade first on betweenness | out-degree, transitive descendant count, reachable business units |
| 2 | Jade first on weighted PageRank | hop distance to nearest default, defaults per ownership group |

When the demo was broken, all five naive rankings picked the protagonist. Now none of them does, and the build fails loudly if that ever stops being true. This is why the offer in the fairness rebuttal is safe: you can invite the room to run the shortcuts live, because they run and they return the wrong name.

### What we deliberately did not do

- **We did not hide data from the lakehouse.** Pulling `supply_relationships` or `owned_by` out of the Genie space would have made the shortcut invisible rather than absent. That rigs the demo instead of repairing it. Both engines get every table.
- **We did not claim SQL cannot do this.** Both algorithms are expressible in SQL and a Databricks audience knows it. The claim that survives is narrower and true: no BI tool writes them unprompted from a business question, and no column governs the cutoff.
- **We did not pre-plant the two graph-native labels.** They are resolved live and never exist as a `CLASSIFIED_AS` edge, so they can never be materialized into a gold table and leak back.

### Why it is simpler than it looks

The audience never sees any of this. On stage the two stories are still *five bottle suppliers, one hidden furnace* and *one spotless account inside a family of failures*. The webbing, the decoys, the paired defaults, and the filler stakes are all background that goes unmentioned, in exactly the way the couple of hundred filler suppliers go unmentioned today.

**Depth in the data does not require depth in the story.** The complexity buys one thing: when someone in the room reaches for the obvious query, it runs and it returns the wrong answer. That moment is the demo.
