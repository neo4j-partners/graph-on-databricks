# GENIE.md: proposed customer questions, grounded in the ontology

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
What is customer CUST-904's credit exposure, and how is that number defined here?
```

### 3. Ownership Risk: naive ranking versus governed screen

```
If I rank customers by PageRank, who looks highest-risk? Does that match the governed Ownership Risk
screen, and if not, why not?
```

### 4. Compound: delinquency plus exposure on the same set

```
Which customers are delinquent according to the governed rule, and what is each one's credit limit
and total open invoice amount?
```

### 5. Overlapping classifications: defaulted and delinquent at once

```
Which customers carry more than one governed classification at the same time, and what is each one's
credit limit and current open invoice exposure?
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

### 8. Strategic Account: segment versus the strategic flag

```
Which customers are Strategic Accounts, and is that something only the graph knows, or could Genie
have answered it alone from the lakehouse tables?
```

### 9. Risky Customer: the early warning a lateness ranking does not reproduce

```
Which customers are Risky Customers, how is that defined here, and how does that set compare to
simply ranking customers by their average days late?
```

---

Candidate replacements for "who are the top high-risk customers," which fails immediately because
no `High-Risk Customer` term exists in the graph. Only suppliers have a governed high-risk term.
Every option below is built from a real `BusinessTerm`, `BusinessRule`, or `Measure` node and
requires both MCP servers to answer in full: Neo4j for the definition and the entity set, Genie for
the figures, stitched on `id` per the routing rule in `CLAUDE.md`.

Examples are pulled live from the current snapshot on 2026-07-21. The generator is RNG-driven, so a
reseed changes every id and number quoted here. Re-pull the examples after any reseed instead of
reusing these.

## Recommended: Delinquent Customer, average versus recency

`TERM-03` defines a Delinquent Customer as more than 60 days late on each of its last three
invoices. `RULE-03`'s expression is `all(last 3 invoices WHERE invoice.daysLate > 60)`, evaluated
against the most recent three invoices only. The `avgDaysLate` column on `Customer` is a lifetime
average across all invoices, so a customer with a long clean history and a recent collapse can carry
a low average while failing the governed rule outright.

That divergence exists today for seven customers: CUST-062 Poplar Trading, CUST-111 Iris Group,
CUST-155 Larch Beverages, CUST-211 Wren Drinks Co, CUST-256 Thistle Retail, CUST-312 Onyx Foods,
and CUST-313 Kelvin Group. All seven are governed Delinquent Customers, yet each carries an
`avgDaysLate` under 49, well short of 60.

Onyx Foods is the clearest walkthrough. It has eight invoices. The first five were paid 10, 13, 4, 4,
and 3 days late. The last three are still unpaid and sit 111, 93, and 65 days late. The lifetime
average is 37.9 days: five small numbers pulling down three large ones.
The last-three rule reads only the recent pattern and correctly flags the account.

**The question:** "Which customers are delinquent, and what does that mean?"

- Neo4j answers what the term means (`TERM-03`, `RULE-03`) and which customers satisfy it, with the
  `reason` and `evaluatedAt` on each `CLASSIFIED_AS` edge.
- Genie answers what a column-level read of `avgDaysLate` alone would suggest for the same
  customer ids, which is the naive comparison to hold up against the governed set.
- This is not a claim about what either engine will say in the room. It is a claim about the data:
  an average-based read and the governed recency rule disagree for specific, named accounts in this
  snapshot, and the disagreement is explainable invoice by invoice.

## Option 2: Credit Exposure, facility versus drawn

`MEAS-02` defines Credit Exposure as the total committed credit facility on a customer, which is
`customers.creditLimit`. The open invoice balance is the drawn portion of that facility, reported
alongside it, not added to it. "Exposure" reads naturally as "what is currently owed," so a
column-level answer is likely to substitute the open invoice total for exposure, or sum the two.
Neither move matches the authored definition, because that distinction exists only in the graph.

CUST-904 Jade Beverage Distribution is a concrete instance: an €800,000 facility with €222,153.66
currently drawn, about 27.8 percent utilized. The facility figure and the drawn figure are both real
and both useful. They answer different questions, and the Measure node is the only place that says so.

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

The exclusion is not academic in this snapshot. The raw `pagerank` ranking is dominated by customers
that have already defaulted, while invoice-less holding companies also score highly. Both groups are
excluded by the clean, trading-customer definition. Once the rule is applied, CUST-904 Jade Beverage
Distribution ranks first among eligible customers at 0.185723 and is the only one above the live
Ownership Contagion Threshold of 0.17168.

Ownership Risk deliberately has no `CLASSIFIED_AS` edge. It is the live-decision pattern in this
demo: resolve the eligible population from `RULE-06`, compare each stored `pagerank` score with
`THR-04`, and retain the ownership path as evidence. Critical Supplier and Risky Customer demonstrate
the complementary materialized pattern. Do not query a classification edge that this term is not
designed to carry.

**The question:** "If you just sort customers by PageRank, who looks highest-risk, and why does the
governed definition throw most of them out?"

- Neo4j answers both halves: the raw ranked list, and the same list after the clean-record and
  invoice-less exclusions in `RULE-06` and the live threshold in `THR-04` are applied.
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

- Neo4j: the 15 delinquent ids and the reason each was classified.
- Genie: `creditLimit` and open invoice sum for those same 15 ids.
- Nothing here is scripted. The delinquent set is fixed by the rule; the exposure figures are
  whatever the lakehouse returns for those ids on the day of the demo.

## Option 5: overlapping classifications, defaulted and delinquent at once

`CLASSIFIED_AS` edges are not exclusive, so one customer can hold several governed terms at the same
time, and the combination is where the interesting cases sit. Each edge also carries `reason`,
`ruleVersion`, and `evaluatedAt`, so the graph states not only that a customer was classified but on
what basis and against which version of the rule.

One customer currently holds two terms at once: CUST-118 Linden Hospitality is both a Defaulted
Customer and a Delinquent Customer. Its row records `defaultedPeriod` 2026-Q2, while the live exposure
is €31,167.94 against a €64,000 facility, or about 48.7 percent utilized. Its lifetime
`avgDaysLate` is only 56.1, below the 60-day threshold, which makes the overlap especially useful:
the recent-invoice rule finds the delinquency that the average obscures, and the independent default
classification confirms that the deterioration has already become material.

**The question:** "Which customers carry more than one governed classification, and what is each
one's credit limit and current open invoice exposure?"

- Neo4j answers which terms co-occur on the same customer, and the `reason` on each edge says why.
- Genie answers what the exposure measures say about those same ids: `creditLimit` and the open
  invoice total, which is the contrast, since nothing in the metric view distinguishes this account
  from a healthy one.
- The demo point is the co-occurrence, not the specific pair. Terms are authored independently and
  nothing reconciles them, so the graph is the only place the collision is visible.

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
grows from 15 to 21. The six additions are CUST-048, CUST-171, CUST-232, CUST-251, CUST-350, and
CUST-480.

**The question:** "If we moved the Late Payment Threshold to 45, what changes?"

- Neo4j answers the governance half: the current value, the rule and term that depend on it, the
  entities they evaluate, and the tables behind those entities.
- Genie answers the population half by recomputing membership at the proposed value.
- Compare the returned set with the governed 60-day set rather than presenting the 21 customers as
  though policy had already changed.

## Option 7: policy coverage, which customer rules have an owner

Every `BusinessRule` is reachable from a `Policy` by `GOVERNS`, except that the coverage is not
complete, and the gaps are visible only in the graph. `POL-01` Credit Risk Policy governs the
Defaulted Customer, Delinquent Customer, Ownership Risk, Credit Exposure, and Risky Customer rules.
`RULE-01` Strategic Account Rule has no governing policy at all. In the other direction, `POL-03` Compliance
(KYC) Policy constrains the `Customer` entity but governs no rule, so a policy exists with no
operative definition behind it while `supplier_risk.compliance_findings` carries findings data in
the lakehouse.

**The question:** "Which policies govern our customer rules, and is anything ungoverned?"

- Neo4j answers by traversing `GOVERNS` and `CONSTRAINS` and reporting what is missing from each.
- Genie confirms the data exists on the ungoverned side, for example the volume of compliance
  findings sitting behind a policy with no rule.
- This is an ontology-health question rather than a customer question, so it works better as a
  closing beat for a governance audience than as an opener.

## Option 8: Strategic Account, segment versus the strategic flag

`TERM-01` defines a Strategic Account as a platinum-segment customer flagged strategic by account
management. Only the segment half of that lives on `supplier_risk.customers`: the `segment` column
carries platinum for 61 customers. No column anywhere in the lakehouse records the strategic flag
itself. It exists only as the `CLASSIFIED_AS` edge to `TERM-01` in the graph, currently held by 7 of
those 61 platinum customers.

That makes this a partial-grounding case, not a control. Genie alone can narrow a Strategic Account
question to the 61-customer platinum superset and no further. It has no field to read the other half
of the definition from, and asked directly, it confirms no such column exists. Reaching the actual 7
requires the graph.

**The question:** "Which customers are Strategic Accounts, and could Genie have answered that alone
from the lakehouse tables?"

- Neo4j answers in full: `TERM-01`'s definition and the 7 customers holding the `CLASSIFIED_AS` edge.
- Genie answers the first half only: the 61-customer platinum superset from `segment`, and, asked
  directly, that it has no strategic-flag column to narrow further.
- The demo point is the gap between the superset and the governed set, not a specific name in either.

## Option 9: Risky Customer, the early warning a lateness ranking does not reproduce

Pulled live on 2026-07-21. Re-pull the figures after any regenerate or reseed.

`TERM-07` defines a Risky Customer as an active customer, neither defaulted nor already Delinquent,
where at least half of the ten customers it most resembles on payment behavior are themselves
classified Delinquent. `RULE-09` reads `THR-05` the Customer Similarity Threshold, currently 0.5,
whose `basis` reads "Review any active customer where at least half of its 10 nearest neighbours by
payment behavior are already Delinquent Customers." `GM-03` Delinquency Similarity names the score,
`Customer.delinquencySimilarity`, produced by `gds.knn` over standardized `avgDaysLate` and
`overdueShare`. The Credit Risk Policy governs the rule and the existing Credit Exposure measure
prices it.

This is the only governed term in the ontology built on resemblance rather than on a property of the
customer itself. Every other term asks what an account did. This one asks who it looks like.

**Why the naive comparison is a lateness ranking, and why it is a fair one.** `avgDaysLate` and
`overdueShare` are excluded from `supplier_risk.customers`, but `supplier_risk.invoices` carries
`daysLate` and `status`, so ranking customers by average lateness is fully available from the
lakehouse alone. It is the sensible thing to reach for and it should not be presented as impossible.
What it has no way to supply is the cutoff and the reference cohort.

Seven customers currently hold the classification, out of 474 that the rule considers eligible. Ranked
against those 474 by average days late, six of the seven land in the top eight, so the ranking and the
governed set agree about most of the book. The two places they diverge are the interesting ones:

- **The ranking flags accounts the rule does not.** CUST-251 Ember Group and CUST-048 Willow Foods
  sit third and sixth on lateness, above classified accounts in both cases. Neither clears the
  governed share, because the customers they most resemble are not delinquent. Both are planted
  near-miss accounts that the screen declined, which is the clearest evidence available that the
  cohort is an output of the scoring rather than a list.
- **The rule reaches an account the ranking does not.** CUST-356 Cinder Retail sits 29th of 474 on
  lateness with an average of 31.2 days, well inside the ordinary population, and six of its ten
  nearest neighbours are already Delinquent. Nothing about its own record stands out. Its
  neighbourhood does. It is also planted by nobody: it is not in the near-miss set the generator
  seeded, so it emerged from the scoring.

CUST-285 Ember Drinks Co is the clearest walkthrough at the top of the set. It pays 51.0 days late on
average, which several governed Delinquent Customers beat outright, and its `overdueShare` of 0.33 is
the lowest of the seven classified accounts. It scores 0.8, meaning eight of its ten nearest neighbours are
governed Delinquent Customers, among them Poplar Trading, Raven Retail, and Iris Group. The graph
holds all eight as `SIMILAR_PAYMENT_BEHAVIOR` edges carrying similarity and neighbour rank, so the
classification explains itself by naming accounts rather than by quoting a decimal.

**The question:** "Which customers are Risky Customers, and how does that compare to ranking by
average days late?"

- Neo4j answers the definition (`TERM-07`, `RULE-09`, `THR-05`, `GM-03`, the governing policy), the
  classified set with the `reason` on each `CLASSIFIED_AS` edge, and the named delinquent neighbours
  behind each one.
- Genie answers the naive ranking from `invoices`, and then the exposure on whichever ids the graph
  named: `creditLimit` against the open invoice balance, the same facility-versus-drawn split as
  Option 2.
- This is not a claim about what either engine will say in the room. It is a claim about the data:
  the two lists overlap heavily and disagree at both ends, and every disagreement is explainable
  neighbour by neighbour.
- The set moves with the data. It is derived from the scoring on every build, so re-pull it rather
  than reusing the names above, and never quote a cohort size on stage.
