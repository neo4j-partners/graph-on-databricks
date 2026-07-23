# GENIE.md — proposed customer questions, grounded in the ontology

## What this demonstrates

Connect `genie-supplier-risk` and `neo4j-agentcore` and nothing else. No system prompt explains
either schema, and no question below names a node label, relationship type, or table. A frontier
LLM given just the two servers and minimal prompting has to introspect both schemas itself: which
server holds which fact, how an entity in one maps to the other, and where the authored meaning of
a word like "delinquent" or "risk" actually lives. It finds all of that on its own, by asking each
server what it has.

That discovery is the whole demo. Asked what "delinquent" means from lakehouse tables alone, an LLM
infers an answer from column names, a different guess every run. Asked the same question with the
graph connected, its own introspection surfaces an authored business term, rule, and classification
already sitting in the data. The gap between a plausible answer and a grounded one comes entirely
from whether the model found that ontology layer, not from anything this file tells it to say.

## Quick reference: copy-paste for the live demo

Ask these to the LLM directly, with both MCP servers connected and nothing else in the system
prompt. Do not mention node labels, relationship types, table names, or which server answers what.
The model has to find the schema, the join key, and the routing itself by calling
`get_neo4j_schema` and querying Genie directly, the same way it would find anything else it was not
told. Rationale and full walkthroughs, written for the person running the demo rather than the
model answering it, are below.

### 1. Delinquent Customer: average versus recency

```
Which customers are delinquent according to our governed definition, and how does that compare to
just sorting customers by their average days late on invoices?
```

### 2. Credit Exposure: facility versus drawn

```
What is customer CUST-449's credit exposure, and how is that number defined here?
```

### 3. Ownership Risk: naive ranking versus governed classification

```
If I rank customers by PageRank, who looks highest-risk? Does that match who is actually classified
as Ownership Risk, and if not, why not?
```

### 4. Compound: delinquency plus exposure on the same set

```
Which customers are delinquent according to the governed rule, and what is each one's credit limit
and total open invoice amount?
```

### 5. Overlapping classifications: strategic and defaulted at once

```
Which customers carry more than one governed classification at the same time, and for any that are
both a Strategic Account and a Defaulted Customer, what facility is still committed to them?
```

### 6. Threshold impact: what moves if the cutoff moves

```
The Late Payment Threshold is 60 days. If credit policy moved it to 45, what would that change, and
which customers would become delinquent that are not delinquent today?
```

### 7. Policy coverage: which customer rules have an owner

```
Which policies govern our customer business rules, and is there any customer term or policy with no
rule behind it?
```

### 8. Control, not recommended: Strategic Account

```
Which customers are Strategic Accounts, and is that something only the graph knows, or could Genie
have answered it alone from the lakehouse tables?
```

### 9. Supplier Concentration: headcount versus governed criticality

```
How diversified is our glass bottle supply for the Americas, and does the number of direct
suppliers tell the whole story?
```

---

Candidate replacements for "who are the top high-risk customers," which fails immediately because
no `High-Risk Customer` term exists in the graph. Only suppliers have a governed high-risk term.
Every option below is built from a real `BusinessTerm`, `BusinessRule`, or `Measure` node and
requires both MCP servers to answer in full: Neo4j for the definition and the entity set, Genie for
the figures, stitched on `id` per the routing rule in `CLAUDE.md`.

Examples are pulled live from the current snapshot on 2026-07-20. The generator is RNG-driven, so a
reseed changes every id and number quoted here. Re-pull the examples after any reseed instead of
reusing these.

## Recommended: Delinquent Customer, average versus recency

`TERM-03` defines a Delinquent Customer as more than 60 days late on each of its last three
invoices. `RULE-03`'s expression is `all(last 3 invoices WHERE invoice.daysLate > 60)`, evaluated
against the most recent three invoices only. The `avgDaysLate` column on `Customer` is a lifetime
average across all invoices, so a customer with a long clean history and a recent collapse can carry
a low average while failing the governed rule outright.

That divergence exists today for five customers: CUST-312 Onyx Foods, CUST-367 Vector Beverages,
CUST-155 Larch Beverages, CUST-211 Wren Drinks Co, and CUST-067 Cinder Foods. All five are governed
Delinquent Customers. All five carry an `avgDaysLate` under 49, well short of 60.

Onyx Foods is the clearest walkthrough. It has eight invoices. The first five were paid 14, 4, 2, 6,
and 9 days late. The last three were issued in 2026-Q1 and Q2, are still unpaid, and sit 98, 97, and
75 days late. The lifetime average is 38.1 days: five small numbers pulling down three large ones.
The last-three rule reads only the recent pattern and correctly flags the account.

**The question:** "Which customers are delinquent, and what does that mean?"

- Neo4j answers what the term means (`TERM-03`, `RULE-03`) and which customers satisfy it, with the
  `reason` and `evaluatedAt` on each `CLASSIFIED_AS` edge.
- Genie answers what a column-level read of `avgDaysLate` alone would suggest for the same
  customer ids, which is the naive comparison to hold up against the governed set.
- This is not a claim about what either engine will say in the room. It is a claim about the data:
  an average-based read and the governed recency rule disagree for specific, named accounts in this
  snapshot, and the disagreement is explainable invoice by invoice.
- Do not expect the model to reproduce this exact framing. The underlying set is fixed, but a live
  run may demonstrate the divergence a different way, for example by ranking both the governed set
  and a plain average-based top-N of the same size and pointing out which name swaps in or out,
  rather than by listing which governed members carry an average under 49. Either framing proves the
  same point; only the specific walkthrough above is scripted, not the model's path to it.

## Option 2: Credit Exposure, facility versus drawn

`MEAS-02` defines Credit Exposure as the total committed credit facility on a customer, which is
`customers.creditLimit`. The open invoice balance is the drawn portion of that facility, reported
alongside it, not added to it. "Exposure" reads naturally as "what is currently owed," so a
column-level answer is likely to substitute the open invoice total for exposure, or sum the two.
Neither move matches the authored definition, because that distinction exists only in the graph.

CUST-449 Willow Trading is a concrete instance: a $80,000 facility with $67,504.82 currently drawn,
84 percent utilized. The facility figure and the drawn figure are both real and both useful. They
answer different questions, and the Measure node is the only place that says so.

**The question:** "What's our credit exposure to [customer], and how is that number built?"

- Neo4j answers the definition: `MEAS-02`, its `DataSource` mapping back to
  `supplier_risk.customers` and `supplier_risk.invoices`, and the facility-versus-drawn split.
- Genie answers the figures: `creditLimit` and `sum(invoices.amount WHERE status = 'open')` for the
  customer id the graph names.

## Option 3: Ownership Risk, propagation and exclusion

`TERM-06` defines Ownership Risk as a clean-record customer, meaning not defaulted and not
delinquent, that carries its own invoices and absorbs more propagated failure through its ownership
stakes than any other trading customer. Risk propagates from every defaulted customer along
`OWNED_BY` edges, weighted by stake size. Defaulted members and invoice-less holding companies are
excluded by name in the rule text, so the clean operating account is the one the rule is built to
surface.

The exclusion is not academic in this snapshot. The three highest raw `pagerank` values among
customers belong to CUST-905 Harbour Group Holdings, CUST-907 Tern Capital Partners, and CUST-901
Kestrel Holdings, all of which carry zero invoices and are excluded as holding companies. The next
tier of raw pagerank belongs to customers who are themselves defaulted, also excluded. Separately,
and just as usefully: zero customers currently hold a `CLASSIFIED_AS` edge to Ownership Risk at all.
Do not reconstruct that outcome from the raw `pagerank` property in front of a room. `pagerank` is a
general centrality score stored on the node, not necessarily the same stake-weighted propagation
value `RULE-06` evaluates, and the two disagree for at least one customer past the top of the list.
Query the `CLASSIFIED_AS` edge directly for the governed answer; use raw `pagerank` only for the
naive comparison.

CUST-451 Tidal Hospitality is not defaulted itself and anchors a nine-member ownership chain,
including Hollow Beverages, Quartz Hospitality, Ridgeline Foods, Glacier Markets, and Moss Wholesale
among its descendants. It is a useful structural example even though it does not clear the
Ownership Risk threshold today.

Presenter note: zero customers currently hold a `CLASSIFIED_AS` edge to Ownership Risk, so there is
no stored answer to retrieve for "who qualifies" — the model has to apply `RULE-06`'s filter and
threshold live against the raw `pagerank` property. Watch for it asserting that the raw `pagerank`
property already *is* the stake-weighted propagation value the rule describes, rather than verifying
that live. The two are not guaranteed to be the same number, per the warning above, and a model that
skips the check will still sound confident. If it happens in the room, that is itself a demonstration
of the ungrounded-answer failure mode, not a broken demo — but be ready to press on it rather than
letting the assertion pass.

**The question:** "If you just sort customers by PageRank, who looks highest-risk, and why does the
governed definition throw most of them out?"

- Neo4j answers both halves: the raw ranked list, and the same list after the clean-record and
  invoice-less exclusions in `RULE-06` are applied.
- Genie confirms the excluded accounts' status from the lakehouse columns directly:
  `defaultedPeriod` for the defaulted members, invoice count for the holding companies.
- Framing note: lead with the naive ranking, then apply the rule live. The gap between the two lists
  is the demo, not a specific name landing on either side.

## Option 4, compound: delinquency plus exposure on the same set

Chain Option 1 and Option 2 into a single beat: name the governed Delinquent Customers from `TERM-03`
in Neo4j, then pull each one's Credit Exposure split from Genie. This is the version that most
plainly needs both servers to complete a single answer, since neither server alone can name the
delinquent set and price it.

**The question:** "Which customers are delinquent by the governed rule, and what's our credit
exposure to each one, facility versus drawn?"

- Neo4j: the five delinquent ids and the reason each was classified.
- Genie: `creditLimit` and open invoice sum for those same five ids.
- Nothing here is scripted. The delinquent set is fixed by the rule; the exposure figures are
  whatever the lakehouse returns for those ids on the day of the demo.

## Option 5: overlapping classifications, strategic and defaulted at once

`CLASSIFIED_AS` edges are not exclusive, so one customer can hold several governed terms at the same
time, and the combination is where the interesting cases sit. Each edge also carries `reason`,
`ruleVersion`, and `evaluatedAt`, so the graph states not only that a customer was classified but on
what basis and against which version of the rule.

One customer currently holds two terms at once: CUST-240 Ochre Markets is both a Strategic Account
and a Defaulted Customer, with `defaultedPeriod` 2026-Q2 on the row. The lakehouse view of the same
account is unremarkable. The `customer_risk_exposure` metric view returns overdue 0, open compliance
findings 0, credit utilization 5.3 percent against a 729,000 facility, and the `Customer` node
carries `avgDaysLate` 14.2 with an improving profitability trend. Every exposure measure reads
healthy on an account that defaulted last quarter and still holds strategic status.

**The question:** "Which customers carry more than one governed classification, and what is still
committed to them?"

- Neo4j answers which terms co-occur on the same customer, and the `reason` on each edge says why.
- Genie answers what the exposure measures say about those same ids, which is the contrast: nothing
  in the metric view distinguishes this account from a healthy one.
- The demo point is the co-occurrence, not the specific pair. Terms are authored independently and
  nothing reconciles them, so the graph is the only place the collision is visible.
- "Facility" in the question above is not an authored term anywhere in the graph. It maps to
  `customers.creditLimit` via `MEAS-02`/`RULE-08` (see Option 2), but nothing forces Genie to make
  that connection when asked cold — it has to infer the mapping itself. It has inferred correctly
  when checked, but be ready to steer if a live run substitutes a different column instead.

## Option 6: threshold impact, what moves if the cutoff moves

`THR-02` Late Payment Threshold holds the value 60 and is reached from `RULE-03` by `USES_THRESHOLD`
and from `TERM-03` by `APPLIES_TO`. Because the cutoff is a node rather than a literal in a query,
the blast radius of changing it is a traversal: which rules read it, which terms those rules define,
which entities those rules evaluate, and which lakehouse tables those entities map to. No lakehouse
artifact can answer the impact question at all, because the 60 exists there only inside whatever SQL
someone wrote that day.

The recomputation is the other half and it belongs to Genie. Handed the rule text and a candidate
value, Genie writes the window function over the three most recent invoices per customer and returns
the population at the new cutoff. Tested live at 45 days on the current snapshot, the qualifying set
came back identical to the governed set at 60, so the honest answer today is that the threshold has
slack in this range rather than that a wave of new accounts appears.

**The question:** "If we moved the Late Payment Threshold to 45, what changes?"

- Neo4j answers the governance half: the current value, the rule and term that depend on it, the
  entities they evaluate, and the tables behind those entities.
- Genie answers the population half by recomputing membership at the proposed value.
- A null result is a result. Do not re-ask with a lower number until the population moves, because
  that is engineering the answer rather than reporting it.

## Option 7: policy coverage, which customer rules have an owner

Every `BusinessRule` is reachable from a `Policy` by `GOVERNS`, except that the coverage is not
complete, and the gaps are visible only in the graph. `POL-01` Credit Risk Policy governs the
Defaulted Customer, Delinquent Customer, Ownership Risk, and Credit Exposure rules. `RULE-01`
Strategic Account Rule has no governing policy at all. In the other direction, `POL-03` Compliance
(KYC) Policy constrains the `Customer` entity but governs no rule, so a policy exists with no
operative definition behind it while `supplier_risk.compliance_findings` carries findings data in
the lakehouse.

**The question:** "Which policies govern our customer rules, and is anything ungoverned?"

- Neo4j answers by traversing `GOVERNS` and `CONSTRAINS` and reporting what is missing from each.
- Genie confirms the data exists on the ungoverned side, for example the volume of compliance
  findings sitting behind a policy with no rule.
- This is an ontology-health question rather than a customer question, so it works better as a
  closing beat for a governance audience than as an opener.

## Correction, no longer a control question: Strategic Account

This section previously claimed `TERM-01`'s two conditions, `segment` and a strategic flag, both
live as plain columns on `supplier_risk.customers`, so Genie could answer it correctly alone and it
was listed as a control question rather than a headline beat. That claim does not hold against the
live schema: `supplier_risk.customers` has exactly six columns (`id`, `businessUnitId`, `name`,
`segment`, `creditLimit`, `defaultedPeriod`) and no strategic-flag column exists anywhere in the
schema. Genie confirmed this directly when asked.

Asked "Which customers are Strategic Accounts?" with no graph involved, Genie can only filter on
`segment = 'platinum'` and returns every platinum customer, 61 in the snapshot checked. The graph's
`CLASSIFIED_AS` edges to `TERM-01`, which encode the account-management flag that has no lakehouse
column at all, name 7. Genie's answer is an 8.7x over-count driven by a condition it has no way to
see.

So this question behaves like the other headline beats, not like a control question: Genie produces
a plausible, wrong answer, and the graph is the only place the second condition exists. Whether this
reflects a column that existed when this file was first written and was later dropped, or the
original claim was simply wrong, is unconfirmed — verify the current `supplier_risk.customers`
schema before relying on this section's characterization again. Use it as a headline beat, not a
control question, until that's resolved.

## Option 8: Supplier Concentration, headcount versus governed criticality

`TERM-05` defines a Critical Supplier as one whose supply betweenness — `gds.betweenness` computed
over the full multi-tier `SUPPLIES` network, suppliers supplying suppliers, walked transitively —
sits at or above `THR-03`, the Supply Concentration Threshold of 846.35. The definition says
explicitly that a Critical Supplier "need not sell to a business unit directly, and often does not."
`TERM-04` is a separate axis entirely: High-Risk Supplier is a plain `riskScore >= 70` (`THR-01`),
unrelated to network position.

The Americas' glass bottle category looks well diversified at the direct-supplier level: 5 suppliers
(Aurora Packaging Co, Clearwater Bottles, Harbor Bottling Supply, Ironbridge Containers, Summit Glass
Packaging), risk scores 19-36, none high-risk. None of the five are Critical Suppliers either — their
own betweenness tops out at 659.7, well under the 846.35 cutoff.

The governed Critical Suppliers sit upstream of that list, not on it. Two suppliers currently hold a
`CLASSIFIED_AS` edge to Critical Supplier: Fairview Container Works (betweenness 1242.2, risk score
37) and Cascade Glassworks (betweenness 879.2, risk score 60). Fairview supplies 4 of the 5 direct
glass bottle suppliers; Cascade Glassworks is reachable upstream of all 5 through multiple paths.
Neither is High-Risk by the separate risk-score term — both sit well under the 70 cutoff. A supplier
can be a structural chokepoint and read clean on every other measure at once; the two governed terms
are authored independently and nothing reconciles them.

**The question:** "How diversified is our glass bottle supply for the Americas, and does the number
of direct suppliers tell the whole story?"

- Genie answers the direct count and risk profile: 5 suppliers serving the Americas glass bottle
  category, pulled straight from the supplier-to-business-unit table.
- Neo4j answers what "diversified" leaves out: the same suppliers' upstream dependencies, and
  whether anything in that upstream structure clears the governed Critical Supplier threshold — a
  classification the lakehouse has no way to compute, since it requires walking a multi-tier chain
  the tables don't carry.
- Presenter note: a live run may stop at the direct-supplier count and treat 5 as diversified without
  checking further, or it may walk upstream but eyeball the betweenness numbers as "high" instead of
  checking them against `THR-03`. Both are the ungrounded-answer failure mode this option exists to
  surface, not a broken demo — watch for whether the model checks the governed threshold itself
  rather than asserting a judgment call.
- Examples verified live against the running graph on 2026-07-21. Like the rest of this file, the
  generator is RNG-driven — re-verify the classified set after any reseed.

## Visualizing Option 8 in Aura Explore

The supply chain behind Option 8 is graphable directly: `BusinessUnit` ← glass-bottle suppliers ←
container-glass suppliers ← raw-glass suppliers, with the `TERM-05` classification lineage attached.
Paste into Explore's Cypher tab:

```cypher
MATCH (bu:BusinessUnit {id:'BU-03'})<-[s1:SUPPLIES]-(bottle:Supplier {subcategory:'glass bottles'})
OPTIONAL MATCH (bottle)<-[s2:SUPPLIES]-(container:Supplier {subcategory:'container glass'})
OPTIONAL MATCH (container)<-[s3:SUPPLIES]-(raw:Supplier {subcategory:'raw glass'})
OPTIONAL MATCH (raw)-[cls1:CLASSIFIED_AS]->(term:BusinessTerm {id:'TERM-05'})
OPTIONAL MATCH (container)-[cls2:CLASSIFIED_AS]->(term)
OPTIONAL MATCH (bottle)-[cls3:CLASSIFIED_AS]->(term)
OPTIONAL MATCH (term)-[def:DEFINED_BY]->(rule:BusinessRule)-[ut:USES_THRESHOLD]->(th:Threshold)
RETURN *
```

Every hop is a named variable (`s1`, `s2`, `s3`), not an anonymous variable-length `SUPPLIES*1..2`
path — Explore only draws nodes bound to a variable in the return, so an unnamed intermediate hop
would silently drop out of the graph view. No `LIMIT` is needed; the query is naturally bounded to
roughly fifteen nodes.

For an always-on highlight independent of `CLASSIFIED_AS` state, add a rule-based Perspective style
on `Supplier`: color/size by `betweenness >= 846.35` (`THR-03`, the live Supply Concentration
Threshold value). This lights up the structural chokepoints even when the classification edges
below are stale.

Presenter note, confirmed live on 2026-07-21: `CLASSIFIED_AS` edges into `TERM-05` were observed
flipping between 8 rows, 0 rows, and 9 rows across identical repeated queries in the same session,
with no query change in between — most likely tied to the sibling `supplier-risk-graph` project's
data-generation files being mid-edit at the time (`classified_as.csv`, `business_rules.csv`,
`generate_data.py` all showed uncommitted changes). Separately, a live re-check that same day found
Fairview Container Works supplying **all 5** direct glass bottle suppliers, not 4 as stated in
Option 8 above, and all three container-glass suppliers (Fairview Container Works, Oakline Container
Works, Brackwater Container Works) converging on the **same single raw-glass supplier**, Cascade
Glassworks — a tighter chokepoint than Option 8 currently describes. Re-verify both the
classification edges and the exact supplier counts before presenting; treat Option 8's specific
counts as unconfirmed against the current snapshot until then.

## Operational notes for whoever runs this live

- Genie's first `poll_response` call often returns `ASKING_AI` rather than a final answer. Budget at
  least one extra poll before treating a Genie response as final; don't read the first poll as a
  timeout or an error.
- Write Cypher aggregate-first when a question could touch most of the customer or invoice
  population. Returning row-level detail (for example, every customer's last three invoices as an
  array) can exceed the tool's output size limit; aggregating in the query avoids it.
