# Demo walkthrough

This walkthrough assumes the one-time setup in the [`README.md`](README.md) is done: the data is generated, Neo4j is loaded, the GDS analytics have run, the Unity Catalog tables are uploaded, and the Genie space is created with the two gold tables kept out of it.

## What the demo proves

Two engines answer the same question over the same data:

- **Genie Agent (lakehouse-only):** a Databricks Genie space scoped to the `supplier_risk` schema. It reads the raw instance tables and nothing else.
- **Genie One (Genie plus the graph):** the same Genie Agent under a supervisor that can also call a read-only Neo4j MCP server over the knowledge graph.

The demo runs two stories. In each, the lakehouse-only engine reads every column correctly and still gets the answer wrong, because the risk is a shape in the connections, not a value in a column. Genie One resolves the governed definition from the graph, walks the connections, and flags what the columns cannot show.

### The honesty framing

Never claim SQL cannot express these traversals. A Databricks audience knows recursive CTEs exist. The defensible claims are narrower and true:

- No lakehouse column governs what "single point of failure" or "same ownership group" means. The definition lives in the graph.
- The two graph-native signals, supplier betweenness and ownership PageRank, are graph metrics BI cannot compute from the raw tables at all. Their governing cutoffs are governed values in the graph, never a column a BI tool could sort on.
- Asked a plain question, Genie Agent groups by the obvious column and answers from it. It does not spontaneously write the multi-tier convergence query or the transitive ownership walk that surfaces the real risk.

### The five-beat arc

Both stories run the same five beats, so the audience learns the rhythm on story 1 and feels it confirm on story 2:

1. **The ask:** one natural question, put to both engines.
2. **The miss:** the lakehouse-only engine answers from the columns, correctly, and gets it wrong.
3. **The flag:** Genie One shows the structure, one picture the tables cannot draw.
4. **The exposure:** the flag gets a euro figure, computed from the same lakehouse data.
5. **The decision:** the recommended action, handed to the room as a live choice.

Both engines write their own queries; the presenter types a question, and Genie or Genie One generates the SQL or Cypher. This script gives the questions and the talking points, not queries to paste. Graph properties and the instance tables use camelCase, so the same names line up on both sides. See [`DATA_ARCHITECTURE.md`](DATA_ARCHITECTURE.md) for the full label, relationship, and property model.

## Story 1: the hidden glassworks

Five bottle suppliers look independent and safe. All five secretly buy their glass from the same hidden glassworks, so if that one furnace fails the enterprise cannot bottle its product.

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

The lakehouse-only engine groups suppliers by the `subcategory` column and reports five glass-bottle suppliers feeding the Americas, all with clean risk scores. A correct read of every column, and the wrong answer. The five rows that come back:

| supplierId | name | riskScore |
|---|---|---|
| SUP-903 | Summit Glass Packaging | 18 |
| SUP-904 | Ironbridge Containers | 18 |
| SUP-905 | Clearwater Bottles | 30 |
| SUP-906 | Aurora Packaging Co | 32 |
| SUP-902 | Harbor Bottling Supply | 37 |

Five names, five clean scores, so the read is "well diversified." The `supply_relationships` table is in the space, so the raw links are visible, but nothing labels Cascade as critical and the engine does not invent the multi-tier convergence join that would find it.

### Beat 3, the flag

Genie One first resolves the governed definition of a Critical Supplier from the graph. The definition is "the narrowest bridge on a business unit's multi-tier supply paths," parameterized by the Supply Concentration Threshold (THR-03), a betweenness cutoff of 6.5. It then walks the multi-tier chain into the Americas and collapses the five bottle suppliers onto their shared source.

One row comes back: Cascade Glassworks (SUP-901), raw glass, riskScore 65, reaching all five bottle suppliers into the Americas. Its precomputed betweenness is the strict maximum in the supplier network, so it is the one node every Americas bottle path runs through. Applying the governed cutoff confirms it is the only Critical Supplier: Cascade clears it, and no other supplier does. Its own risk score of 65 sits below the 70 High-Risk threshold, so no score sort would ever surface it.

### Beat 4, the exposure

The flag gets a euro figure: the Americas' recognized revenue for the most recent quarter, read from the same lakehouse data through the graph. About 4.2M EUR (4,222,032.81) of Americas revenue for 2026-Q2 sits behind this one hidden glassworks. Plain BI can read the same revenue, but it cannot tie a single euro to a supplier it cannot see.

### Beat 5, the decision

Qualify a second glass source to protect a 4.2M-EUR-per-quarter flow. The rough cost of a second source is presenter framing on a slide, not a data answer. Genie One's data answer ends at the flag and the exposure.

### Graph mechanics

A variable-length traversal walks the multi-tier chain. `SUPPLIES` points from a supplier toward what it feeds, so the path is `(Cascade)-[:SUPPLIES]->(bottle supplier)-[:SUPPLIES]->(Americas)`. The one GDS piece is `gds.betweenness`, precomputed by `gds.py` as a `betweenness` property on every Supplier node, confirming Cascade as the narrowest bridge. The cutoff THR-03 is set from the score distribution so only Cascade clears it.

## Story 2: the clean payer in a bad family

A customer pays every bill on time, yet the family that owns it also owns two companies that already went bankrupt, so it is far riskier than its own record shows.

```text
                      Kestrel Holdings
                     /       |        \
                OWNED_BY  OWNED_BY  OWNED_BY
                   /         |         \
    Marlin Wholesale  Pelican Beverage  Jade Beverage
        Drinks            Retail        Distribution
      DEFAULTED         DEFAULTED     (spotless record)

 BI sees:    an on-time payer, nothing to flag
 Graph sees: two defaults one hop away, flag it
```

### Beat 1, the ask

Put to both engines:

> "Which customers should credit review look at next?"

### Beat 2, the miss

The lakehouse-only engine returns the late payers, the customers more than 60 days late on each of their last three invoices. It comes back with 15 delinquent customers. Jade Beverage Distribution (CUST-904) is nowhere on the list, because it is never late; its own payment record is spotless. A correct read of every invoice, and it misses the account credit review should worry about most.

### Beat 3, the flag

Genie One resolves the governed definition of Ownership Risk from the graph. The definition is "a customer inside an ownership group that contains a defaulted member, so its risk exceeds its own record," parameterized by the Ownership Contagion Threshold (THR-04), a PageRank cutoff of 0.123197. It then returns the clean customers whose propagated risk clears the cutoff, with the ownership chain as the stated reason.

Jade Beverage Distribution (CUST-904) comes back: a platinum account, owned by Kestrel Holdings, whose siblings Marlin Wholesale Drinks and Pelican Beverage Retail both defaulted in 2026-Q2. The propagated risk lit Jade up over the `OWNED_BY` edges even though Jade itself never missed a payment. No filler customer clears the cutoff, because no filler family contains a defaulted member.

### Beat 4, the exposure

The flag gets a euro figure: Jade's open invoice balance plus its credit line, read from the lakehouse. About 800K EUR (800,448.11) of live exposure, an open balance of 252,448.11 across four open invoices plus a 548,000 credit line. Jade is also a Strategic Account, so the line lands hard: the biggest clean customer is one step away from two companies that just went under.

### Beat 5, the decision

Cut Jade's credit line and require prepayment now, capping the exposure at about 800K EUR.

### Graph mechanics

Personalized `gds.pageRank`, seeded on the two defaulted siblings and propagated over the `OWNED_BY` edges, precomputed by `gds.py` as a `pagerank` property on every Customer node. Risk flows from the siblings up to the shared parent and back down onto Jade. The cutoff THR-04 is set from the score distribution so Jade clears it and no filler family does.

## Why the arc works

- **The miss is the proof.** No prediction, no proof by clock. The lakehouse-only engine reading every column correctly and still missing the risk is the whole argument, demonstrated live, twice.
- **Beat 5 stays open on purpose.** Handing the room a live decision with a euro figure attached converts the contrast into urgency, and it costs nothing to build.
- **Genie One's answers read like actions.** It composes its reason from the path itself and closes with the recommended action, something a risk officer acts on rather than provenance trivia.

## The fairness rebuttal: show the GDS run once

A savvy room will ask whether plain Genie was denied the scores. Show the `gds.py` run once, about 30 seconds, then make the rebuttal: BI cannot compute betweenness or personalized PageRank from the raw tables at all. They are graph metrics, not columns.

- Betweenness and PageRank are precomputed as Neo4j node properties (`Supplier.betweenness`, `Customer.pagerank`) and never run live on stage.
- Neither property is ever synced to Delta. Writing them into a gold table would recreate the exact write-back leakage the sharpened demo removes, and the lakehouse-only engine would tie again.
- The two graph-native thresholds are set from the score distributions after the algorithms run, so Cascade clears the concentration cutoff and Jade clears the contagion cutoff while filler entities do not.

## The background contrast: governed definitions the columns can carry

The two stories are the payoff. The four column-findable terms make the contrast honest by showing what the lakehouse-only engine can govern, so the gap is clearly the two it cannot. Use one as a warm-up if the room needs it.

Ask both engines: "Which suppliers are high-risk?" The lakehouse-only engine has the `riskScore` column but no governed threshold, so it guesses a cutoff, often a top-N or a round number, and can miscount. Genie One reads the governed threshold off the rule and returns every supplier at or above 70, the governed cutoff, consistent no matter who asks. This is the honest baseline: with a column and a governed number, BI can close most of the gap. The two stories are exactly the cases where there is no such column.

## What else Genie One can answer

The knowledge layer answers questions that span definitions, which the fact side finds awkward or cannot express.

- **Impact analysis.** "If we lower the Late Payment Threshold to 45 days, which terms, rules, and tables change?" A traversal from `Threshold` through `APPLIES_TO`, `DEFINED_BY`, and `EVALUATES` to the affected entities and their Unity Catalog tables.
- **Policy scope.** "Which policies govern customer data?" Follow `CONSTRAINS` from each `Policy` to its `Entity`. The Credit Risk Policy and the Compliance (KYC) Policy both constrain the Customer entity.
- **Provenance.** "Show the full lineage behind Jade's Strategic Account label." Genie One walks instance to term to rule to entity to the physical table, returning the Strategic Account term, the reason recorded on the edge, the Strategic Account Rule, the Customer entity, and the `supplier_risk.customers` table.

- **Queryable glossary.** The knowledge layer is the catalog. List every governed term and its definition, which threshold parameterizes which term, or which policy owns which rule.

The two graph-native terms, Critical Supplier and Ownership Risk, are never pre-planted as `CLASSIFIED_AS` edges. Genie One resolves each from its definition and applies it live using the precomputed betweenness and PageRank properties, so those labels never exist as a materializable row and can never leak into a gold table.

## Expected results

Validated against the generated data, so you can confirm a load and compute worked.

| Check | Result |
|---|---|
| Story 1, glass-bottle suppliers into the Americas | 5: SUP-902, SUP-903, SUP-904, SUP-905, SUP-906, all riskScore below 40 |
| Story 1, Critical Supplier | SUP-901 Cascade Glassworks, riskScore 65, strict betweenness maximum, only supplier over THR-03 (6.5) |
| Story 1, Americas 2026-Q2 revenue | 4,222,032.81 EUR (about 4.2M) |
| Story 2, delinquent customers | 15, Jade (CUST-904) not among them |
| Story 2, Ownership Risk flag | CUST-904 Jade, platinum, owned by CUST-901 Kestrel, siblings CUST-902 and CUST-903 defaulted 2026-Q2, clears THR-04 (0.123197) |
| Story 2, Jade exposure | 800,448.11 EUR (about 800K): 252,448.11 open plus 548,000 credit |

The exact betweenness and PageRank scores print from the `gds.py` run at setup. The two euro figures come straight from the generated data, not a slide.

## Genie space and MCP setup

For the one-time setup that creates the Genie space and confirms the two gold tables are kept out of it, see [`README.md`](README.md). The two blocks below are the descriptions the supervisor reads to route between the two engines.

### What to put in the MCP server description

The supervisor decides when to call the graph from the server description alone, so make it spell out the graph's job, its shape, and the provenance pattern. Paste the block below into the server or tool `description` field and adjust names to match your deployment.

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
- Apply the two graph-native terms that no column can express. Critical Supplier
  is the narrowest bridge on a business unit's multi-tier supply paths, read from
  the precomputed Supplier.betweenness property. Ownership Risk is a clean
  customer inside an ownership group that contains a defaulted member, read from
  the precomputed Customer.pagerank property.
- Read a governed threshold value instead of assuming one. Thresholds: Supplier
  Risk Threshold, Late Payment Threshold, Supply Concentration Threshold,
  Ownership Contagion Threshold.
- Explain why a record was classified, tracing it to the rule, entity, and
  source table behind it.
- Answer policy, governance, and impact questions that span definitions.

Do NOT use this server for large scans, counts, sums, or joins over the fact
tables. Send those to Genie.

Graph shape. Knowledge layer: Entity, BusinessTerm, BusinessRule, Policy,
Threshold, DataSource. Instance layer, a mirror of the lakehouse tables:
Customer, Supplier, BusinessUnit, Invoice, RevenueEntry, ComplianceFinding.

Key relationships:
- (:BusinessTerm)-[:DEFINED_BY]->(:BusinessRule): the rule behind a term.
- (:BusinessRule)-[:EVALUATES]->(:Entity): what the rule operates on.
- (:Threshold)-[:APPLIES_TO]->(:BusinessTerm): the number parameterizing a term.
- (:Policy)-[:CONSTRAINS]->(:Entity): policy scope, the entity a policy governs.
- (:Policy)-[:GOVERNS]->(:BusinessRule): the rules a policy operationalizes. Read
  this to find a policy's rules; do NOT infer them from a shared Entity. The
  Compliance (KYC) Policy constrains the Customer entity but governs no rule (it
  is operationalized through ComplianceFinding records).
- (:Entity)-[:MAPS_TO]->(:DataSource): semantic mapping (lineage); DataSource.table
  is the real Unity Catalog table.
- (:Supplier)-[:SUPPLIES]->(:Supplier): supplier-to-supplier supply, the
  multi-tier chain. (:Supplier)-[:SUPPLIES]->(:BusinessUnit): a vendor feeds a unit.
- (:Customer)-[:OWNED_BY]->(:Customer): ownership, child points at parent.
- (:Customer|:Supplier)-[:CLASSIFIED_AS]->(:BusinessTerm): a classification. The
  edge carries reason, evaluatedAt, and ruleVersion. Only the four column-findable
  terms carry these edges; Critical Supplier and Ownership Risk are resolved live.

To explain any classification, walk:
  instance -[:CLASSIFIED_AS]-> term -[:DEFINED_BY]-> rule
           -[:EVALUATES]-> entity -[:MAPS_TO]-> dataSource
Return the term, the reason on the edge, the rule expression, and
DataSource.table.

Conventions:
- All properties are camelCase.
- Node ids are stable prefixes: ENT-0x, TERM-0x, RULE-0x, POL-0x, THR-0x, DS-0x,
  CUST-0xx, SUP-0xx, BU-0x.
- gds.py writes Supplier.betweenness and Customer.pagerank as node properties.
  These live only in the graph and are never in Unity Catalog.
- The graph is read-only. Emit read Cypher only, and prefer parameters over
  string interpolation.
```

### What to put in the Genie space description

The supervisor routes fact and count questions to Genie, so its description has to say what Genie owns and what it does not. Paste the block below into the Genie space instructions or the tool `description` the supervisor sees.

```text
This Genie space answers questions over the supplier and customer risk data in
Unity Catalog schema supplier_risk, for a global beverage producer. Use it for
facts. The Neo4j graph owns definitions, relationships, and provenance; this
space owns the numbers.

Use this space to:
- Return rows, counts, totals, and rankings from a single table or a join or
  two: customers by segment, suppliers by risk, invoices by status, revenue by
  business unit and period.
- Apply a threshold the graph already resolved. Pass the concrete value in the
  question.

Do NOT use this space to:
- Invent what a business term means. If a question depends on high-risk,
  delinquent, strategic, critical, or ownership risk, resolve it in the graph
  first.
- Judge diversification or single points of failure from the supply links, or
  ownership risk from parentCustomerId. Those are graph traversals; send them to
  the graph.

Tables and joins:
- Instance tables, primary key id, camelCase columns: customers, suppliers,
  business_units, invoices, revenue_entries, compliance_findings.
- supply_relationships (fromSupplierId, toSupplierId): raw supplier-to-supplier
  links. Visible, but a single point of failure across tiers is a graph question.
- supplier_business_units (supplierId, businessUnitId): the many-to-many
  supplier-to-unit bridge.
- Foreign keys: invoices.customerId and compliance_findings.customerId join to
  customers.id; customers.businessUnitId and revenue_entries.businessUnitId join
  to business_units.id; customers.parentCustomerId self-references customers.id.

Conventions:
- All instance-table columns are camelCase: riskScore, subcategory, daysLate,
  creditLimit, parentCustomerId, defaultedPeriod.
- The primary key on every instance table is id.
```

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
- Ownership Risk view: customers ranked by Customer.pagerank, highlighting clean
  customers (no defaultedPeriod) inside an ownership group that contains a
  defaulted member, with their creditLimit and open invoice balance as exposure.
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

The prompt assumes the graph as loaded by `load.py` plus `gds.py`, so it expects `Supplier.betweenness` and `Customer.pagerank` to exist. If you only ran `load.py` and skipped `gds.py`, drop the Critical Supplier and Ownership Risk views, since those properties will not be present.
